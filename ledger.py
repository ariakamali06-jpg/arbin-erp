"""
Arbin Double-Entry Accounting Engine (هسته حسابداری دوبل آربین)
Guarantees:
- Strict Mathematical Balance: SUM(debit) == SUM(credit)
- Multi-tenant data segregation
- Immutable audit logging
- Entry status lifecycle:
    draft -> approved -> permanent   (سند پیش‌نویس، تایید شده، دائم/قطعی)
    plus opening_entry / closing_entry (سند افتتاحیه / اختتامیه)
- Year-end closing (سند اختتامیه) and next-year opening (سند افتتاحیه) automation
"""

import json
import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from database import gregorian_to_jalali, get_database

POSTED_STATUSES = ("approved", "permanent", "opening_entry", "closing_entry", "confirmed")
IMMUTABLE_STATUSES = ("permanent", "opening_entry", "closing_entry")


class AccountingError(Exception):
    """Base exception for Arbin Accounting Engine"""


class UnbalancedJournalEntryError(AccountingError):
    def __init__(self, debit_sum: Decimal, credit_sum: Decimal, diff: Decimal):
        self.debit_sum = debit_sum
        self.credit_sum = credit_sum
        self.diff = diff
        super().__init__(
            f"سند حسابداری تراز نیست! جمع بدهکار: {debit_sum:,.2f}، جمع بستانکار: {credit_sum:,.2f}، اختلاف: {diff:,.2f}"
        )


class ImmutableEntryError(AccountingError):
    pass


class AccountNotFoundError(AccountingError):
    pass


class FiscalYearClosedError(AccountingError):
    pass


class ArbinLedger:
    def __init__(self, db_path: Optional[str] = None):
        from pathlib import Path

        self.base_dir = Path(__file__).parent
        self.database = get_database(db_path)
        self.db_path = self.database.db_path
        self.database.init_schema()

    # ---------------------------------------------------------
    # Connections
    # ---------------------------------------------------------
    def get_connection(self):
        """Managed connection: `with ledger.get_connection() as conn` commits & closes."""
        return self.database.connect()

    # ---------------------------------------------------------
    # Tenant & Fiscal Year Management
    # ---------------------------------------------------------
    def create_tenant(
        self, name: str, national_id: Optional[str] = None, currency: str = "IRT"
    ) -> str:
        tenant_id = str(uuid.uuid4())
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO tenants (id, name, national_id, currency) VALUES (?, ?, ?, ?)",
                (tenant_id, name, national_id, currency),
            )
        return tenant_id

    def create_fiscal_year(
        self, tenant_id: str, title: str, start_date: str, end_date: str
    ) -> str:
        fy_id = str(uuid.uuid4())
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO fiscal_years (id, tenant_id, title, start_date, end_date) VALUES (?, ?, ?, ?, ?)",
                (fy_id, tenant_id, title, start_date, end_date),
            )
        return fy_id

    def get_fiscal_year(self, tenant_id: str, fiscal_year_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM fiscal_years WHERE tenant_id = ? AND id = ?",
                (tenant_id, fiscal_year_id),
            ).fetchone()
        return dict(row) if row else None

    # ---------------------------------------------------------
    # Chart of Accounts Seeding (کدینگ استاندارد حسابها)
    # ---------------------------------------------------------
    def seed_standard_accounts(self, tenant_id: str) -> None:
        from seed_data import STANDARD_IRAN_CHART_OF_ACCOUNTS

        with self.get_connection() as conn:
            code_to_id: Dict[str, str] = {}
            for acc in STANDARD_IRAN_CHART_OF_ACCOUNTS:
                existing = conn.execute(
                    "SELECT id FROM accounts WHERE tenant_id = ? AND code = ?",
                    (tenant_id, acc["code"]),
                ).fetchone()
                if existing:
                    code_to_id[acc["code"]] = existing[0]
                    continue
                acc_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO accounts (id, tenant_id, code, title, level, nature, parent_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        acc_id,
                        tenant_id,
                        acc["code"],
                        acc["title"],
                        acc["level"],
                        acc["nature"],
                        code_to_id.get(acc["parent_code"]),
                    ),
                )
                code_to_id[acc["code"]] = acc_id

    # ---------------------------------------------------------
    # Floating sub-ledgers (تفصیلی‌های شناور)
    # ---------------------------------------------------------
    def create_sub_ledger(
        self,
        tenant_id: str,
        code: str,
        title: str,
        sub_ledger_type: str,
        phone: Optional[str] = None,
        national_id: Optional[str] = None,
        dimension: Optional[str] = None,
    ) -> str:
        with self.get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM sub_ledgers WHERE tenant_id = ? AND code = ?",
                (tenant_id, code),
            ).fetchone()
            if existing:
                return existing[0]
            sub_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO sub_ledgers (id, tenant_id, code, title, sub_ledger_type, dimension, phone, national_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sub_id,
                    tenant_id,
                    code,
                    title,
                    sub_ledger_type,
                    dimension,
                    phone,
                    national_id,
                ),
            )
        return sub_id

    def create_detail_account(
        self,
        tenant_id: str,
        code: str,
        title: str,
        detail_type: str,
        phone: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Backward-compatible alias of `create_sub_ledger` (تفصیلی سنتی)."""
        return self.create_sub_ledger(
            tenant_id, code, title, detail_type, phone=phone, **kwargs
        )

    def get_sub_ledger(self, tenant_id: str, code: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM sub_ledgers WHERE tenant_id = ? AND code = ?",
                (tenant_id, code),
            ).fetchone()
        return dict(row) if row else None

    # ---------------------------------------------------------
    # Journal Entries (ثبت اسناد دوبل با تضمین موازنه)
    # ---------------------------------------------------------
    def _next_entry_number(self, conn, tenant_id: str, fiscal_year_id: str) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(entry_number), 0) + 1 FROM journal_entries WHERE tenant_id = ? AND fiscal_year_id = ?",
            (tenant_id, fiscal_year_id),
        ).fetchone()
        return int(row[0])

    def _assert_fiscal_year_open(self, conn, tenant_id: str, fiscal_year_id: str) -> None:
        row = conn.execute(
            "SELECT is_closed FROM fiscal_years WHERE tenant_id = ? AND id = ?",
            (tenant_id, fiscal_year_id),
        ).fetchone()
        if row is None:
            raise AccountNotFoundError(
                f"سال مالی '{fiscal_year_id}' برای این شرکت تعریف نشده است."
            )
        if int(row[0] or 0) == 1:
            raise FiscalYearClosedError(
                "سال مالی بسته شده است؛ ثبت سند جدید در آن مجاز نیست (از سند افتتاحیه سال جدید استفاده کنید)."
            )

    @staticmethod
    def _parse_items(items: List[Dict[str, Any]]):
        if len(items) < 2:
            raise AccountingError(
                "سند حسابداری باید حداقل دارای ۲ ردیف (بدهکار و بستانکار) باشد."
            )
        total_debit = Decimal("0.0")
        total_credit = Decimal("0.0")
        parsed = []
        for idx, item in enumerate(items, start=1):
            debit = Decimal(str(item.get("debit", 0))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            credit = Decimal(str(item.get("credit", 0))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if debit < 0 or credit < 0:
                raise AccountingError(f"مبلغ ردیف {idx} نمی‌تواند منفی باشد.")
            if debit > 0 and credit > 0:
                raise AccountingError(
                    f"ردیف {idx} نمی‌تواند همزمان دارای بدهکار و بستانکار باشد."
                )
            if debit == 0 and credit == 0:
                raise AccountingError(f"ردیف {idx} دارای مبلغ صفر است.")
            total_debit += debit
            total_credit += credit
            parsed.append(
                {
                    "row_number": idx,
                    "account_code": item["account_code"],
                    "sub_ledger_code": item.get("sub_ledger_code") or item.get("detail_code"),
                    "description": item.get("description", ""),
                    "debit": float(debit),
                    "credit": float(credit),
                }
            )
        diff = abs(total_debit - total_credit)
        if diff > Decimal("0.001"):
            raise UnbalancedJournalEntryError(total_debit, total_credit, diff)
        return parsed, total_debit

    def record_journal_entry(
        self,
        tenant_id: str,
        fiscal_year_id: str,
        entry_date: str,
        description: str,
        items: List[Dict[str, Any]],
        manual_number: Optional[str] = None,
        source_module: str = "manual",
        user_id: str = "system",
        status: str = "approved",
        source_id: Optional[str] = None,
        entry_date_jalali: Optional[str] = None,
    ) -> str:
        """
        Record a double-entry transaction.

        items example:
        [
            {"account_code": "1010", "sub_ledger_code": "100201",
             "description": "واریز مشتری", "debit": 10000000, "credit": 0},
            {"account_code": "1210", "sub_ledger_code": "4001",
             "description": "تسویه بدهی مشتری", "debit": 0, "credit": 10000000}
        ]
        """
        parsed, total_debit = self._parse_items(items)
        jalali_date = entry_date_jalali or gregorian_to_jalali(entry_date)

        with self.get_connection() as conn:
            self._assert_fiscal_year_open(conn, tenant_id, fiscal_year_id)

            next_num = self._next_entry_number(conn, tenant_id, fiscal_year_id)
            entry_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO journal_entries (
                    id, tenant_id, fiscal_year_id, entry_number, manual_number,
                    entry_date, entry_date_jalali, description, status,
                    source_module, source_id, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    tenant_id,
                    fiscal_year_id,
                    next_num,
                    manual_number,
                    entry_date,
                    jalali_date,
                    description,
                    status,
                    source_module,
                    source_id,
                    user_id,
                ),
            )

            for row in parsed:
                acc_row = conn.execute(
                    "SELECT id FROM accounts WHERE tenant_id = ? AND code = ?",
                    (tenant_id, row["account_code"]),
                ).fetchone()
                if not acc_row:
                    raise AccountNotFoundError(
                        f"کد حساب '{row['account_code']}' در سیستم تعریف نشده است."
                    )
                sub_id = None
                if row["sub_ledger_code"]:
                    sub_row = conn.execute(
                        "SELECT id FROM sub_ledgers WHERE tenant_id = ? AND code = ?",
                        (tenant_id, row["sub_ledger_code"]),
                    ).fetchone()
                    if not sub_row:
                        raise AccountNotFoundError(
                            f"کد تفصیلی '{row['sub_ledger_code']}' تعریف نشده است."
                        )
                    sub_id = sub_row[0]
                conn.execute(
                    """
                    INSERT INTO journal_items (
                        id, entry_id, tenant_id, row_number, account_id,
                        sub_ledger_id, description, debit, credit
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        entry_id,
                        tenant_id,
                        row["row_number"],
                        acc_row[0],
                        sub_id,
                        row["description"],
                        row["debit"],
                        row["credit"],
                    ),
                )

            self._audit(
                conn,
                tenant_id,
                "journal_entry",
                entry_id,
                "CREATE",
                user_id,
                {
                    "entry_number": next_num,
                    "date": entry_date,
                    "date_jalali": jalali_date,
                    "status": status,
                    "total_amount": float(total_debit),
                    "items_count": len(parsed),
                },
            )

        return entry_id

    # ---------------------------------------------------------
    # Status lifecycle (چرخه وضعیت اسناد)
    # ---------------------------------------------------------
    def _audit(
        self,
        conn,
        tenant_id: str,
        entity_name: str,
        entity_id: str,
        action: str,
        user_id: str,
        payload: Dict[str, Any],
        payload_before: Optional[Dict[str, Any]] = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO audit_logs (id, tenant_id, entity_name, entity_id, action, user_id, payload_before, payload_after)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                tenant_id,
                entity_name,
                entity_id,
                action,
                user_id,
                json.dumps(payload_before, ensure_ascii=False) if payload_before else None,
                json.dumps(payload, ensure_ascii=False) if payload else None,
            ),
        )

    def get_journal_entry(self, tenant_id: str, entry_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM journal_entries WHERE tenant_id = ? AND id = ?",
                (tenant_id, entry_id),
            ).fetchone()
            if not row:
                return None
            entry = dict(row)
            entry["items"] = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT ji.id, ji.row_number, a.code AS account_code, a.title AS account_title,
                           s.code AS sub_ledger_code, s.title AS sub_ledger_title,
                           ji.description, ji.debit, ji.credit
                    FROM journal_items ji
                    JOIN accounts a ON ji.account_id = a.id
                    LEFT JOIN sub_ledgers s ON ji.sub_ledger_id = s.id
                    WHERE ji.entry_id = ?
                    ORDER BY ji.row_number
                    """,
                    (entry_id,),
                ).fetchall()
            ]
        return entry

    def update_entry_status(
        self, tenant_id: str, entry_id: str, status: str, user_id: str = "system"
    ) -> Dict[str, Any]:
        """
        Move a voucher along its lifecycle:
        draft -> approved (تایید) -> permanent (قید/تصویب نهایی)
        """
        allowed = ("draft", "approved", "permanent")
        if status not in allowed:
            raise AccountingError(f"وضعیت نامعتبر است: {status}")

        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT status, fiscal_year_id FROM journal_entries WHERE tenant_id = ? AND id = ?",
                (tenant_id, entry_id),
            ).fetchone()
            if not row:
                raise AccountNotFoundError("سند مورد نظر یافت نشد.")
            current = row["status"]
            if current in IMMUTABLE_STATUSES or current == "permanent":
                raise ImmutableEntryError(
                    "سند قطعی/افتتاحیه/اختتامیه است و قابل تغییر وضعیت نیست."
                )
            order = {"draft": 0, "approved": 1, "permanent": 2}
            if order.get(status, -1) <= order.get(current, -1):
                raise AccountingError(
                    f"وضعیت سند '{current}' است؛ تغییر به '{status}' مجاز نیست."
                )
            if status == "permanent":
                self._assert_no_drafts_around(conn, tenant_id, row["fiscal_year_id"])
            conn.execute(
                "UPDATE journal_entries SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, entry_id),
            )
            action = {"approved": "APPROVE", "permanent": "POST"}.get(status, "UPDATE")
            self._audit(
                conn,
                tenant_id,
                "journal_entry",
                entry_id,
                action,
                user_id,
                {"status": status},
                {"status": current},
            )
            updated = conn.execute(
                "SELECT * FROM journal_entries WHERE id = ?", (entry_id,)
            ).fetchone()
        return dict(updated)

    def _assert_no_drafts_around(self, conn, tenant_id: str, fiscal_year_id: str) -> None:
        """A fiscal year can only be closed when no draft voucher remains."""
        row = conn.execute(
            "SELECT COUNT(*) FROM journal_entries WHERE tenant_id = ? AND fiscal_year_id = ? AND status = 'draft'",
            (tenant_id, fiscal_year_id),
        ).fetchone()
        if int(row[0] or 0):
            raise AccountingError(
                "سند پیش‌نویس (draft) در این سال مالی وجود دارد؛ ابتدا آن را تایید یا حذف کنید."
            )

    def delete_journal_entry(self, tenant_id: str, entry_id: str, user_id: str = "system") -> bool:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT status FROM journal_entries WHERE tenant_id = ? AND id = ?",
                (tenant_id, entry_id),
            ).fetchone()
            if not row:
                return False
            if row["status"] != "draft":
                raise ImmutableEntryError("فقط سند پیش‌نویس (draft) قابل حذف است.")
            conn.execute("DELETE FROM journal_items WHERE entry_id = ?", (entry_id,))
            conn.execute("DELETE FROM journal_entries WHERE id = ?", (entry_id,))
            self._audit(conn, tenant_id, "journal_entry", entry_id, "DELETE", user_id, {})
        return True

    def list_journal_entries(
        self,
        tenant_id: str,
        fiscal_year_id: Optional[str] = None,
        include_drafts: bool = False,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        sql = [
            """
            SELECT je.*,
                   COALESCE((SELECT SUM(ji.debit) FROM journal_items ji WHERE ji.entry_id = je.id), 0.0)
                       AS total_amount
            FROM journal_entries je WHERE je.tenant_id = ?
            """,
        ]
        params: List[Any] = [tenant_id]
        if fiscal_year_id:
            sql.append("AND je.fiscal_year_id = ?")
            params.append(fiscal_year_id)
        if not include_drafts:
            sql.append("AND je.status != 'draft'")
        sql.append("ORDER BY je.entry_date, je.entry_number LIMIT ?")
        params.append(limit)
        with self.get_connection() as conn:
            rows = conn.execute(" ".join(sql), params).fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------
    # Account balances & tree (موجودی حساب‌ها و ساختار درختی)
    # ---------------------------------------------------------
    def account_balances(
        self,
        tenant_id: str,
        fiscal_year_id: Optional[str] = None,
        code_prefix: Optional[str] = None,
        include_drafts: bool = False,
    ) -> Dict[str, Dict[str, float]]:
        """Return {account_code: {debit, credit, balance_debit, balance_credit}}."""
        sql = [
            """
            SELECT a.code, a.title, a.level,
                   SUM(CASE WHEN ji.debit > 0 THEN ji.debit ELSE 0 END) AS total_debit,
                   SUM(CASE WHEN ji.credit > 0 THEN ji.credit ELSE 0 END) AS total_credit
            FROM accounts a
            JOIN journal_items ji ON ji.account_id = a.id
            JOIN journal_entries je ON je.id = ji.entry_id
            WHERE a.tenant_id = ? AND je.tenant_id = ?
            """
        ]
        params: List[Any] = [tenant_id, tenant_id]
        if fiscal_year_id:
            sql.append("AND je.fiscal_year_id = ?")
            params.append(fiscal_year_id)
        if not include_drafts:
            sql.append("AND je.status != 'draft'")
        if code_prefix:
            sql.append("AND a.code LIKE ?")
            params.append(f"{code_prefix}%")
        sql.append("GROUP BY a.code, a.title, a.level")

        balances: Dict[str, Dict[str, float]] = {}
        with self.get_connection() as conn:
            for row in conn.execute(" ".join(sql), params).fetchall():
                debit = float(row["total_debit"] or 0)
                credit = float(row["total_credit"] or 0)
                balances[row["code"]] = {
                    "title": row["title"],
                    "level": row["level"],
                    "total_debit": debit,
                    "total_credit": credit,
                    "balance_debit": debit if debit >= credit else 0.0,
                    "balance_credit": credit if credit > debit else 0.0,
                    "net": debit - credit,
                }
        return balances

    def get_account_tree(self, tenant_id: str) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, code, title, level, nature, parent_id, is_active
                FROM accounts WHERE tenant_id = ? ORDER BY code
                """,
                (tenant_id,),
            ).fetchall()
        nodes = {
            r["code"]: {
                "id": r["id"],
                "code": r["code"],
                "title": r["title"],
                "level": r["level"],
                "nature": r["nature"],
                "is_active": bool(r["is_active"]),
                "children": [],
            }
            for r in rows
        }
        roots: List[Dict[str, Any]] = []
        by_id = {v["id"]: v for v in nodes.values()}
        for r in rows:
            node = nodes[r["code"]]
            parent = by_id.get(r["parent_id"]) if r["parent_id"] else None
            if parent:
                parent["children"].append(node)
            else:
                roots.append(node)
        return roots

    # ---------------------------------------------------------
    # Year-end closing & opening entries (سند اختتامیه و افتتاحیه)
    # ---------------------------------------------------------
    def _closing_balances(
        self, conn, tenant_id: str, fiscal_year_id: str, prefixes: tuple
    ) -> List[Dict[str, Any]]:
        """Balances of leaf (معین / 4-digit) accounts matching the group prefixes."""
        rows = conn.execute(
            """
            SELECT a.code, a.title,
                   SUM(CASE WHEN ji.debit > 0 THEN ji.debit ELSE 0 END) AS total_debit,
                   SUM(CASE WHEN ji.credit > 0 THEN ji.credit ELSE 0 END) AS total_credit
            FROM accounts a
            JOIN journal_items ji ON ji.account_id = a.id
            JOIN journal_entries je ON je.id = ji.entry_id
            WHERE a.tenant_id = ? AND je.tenant_id = ? AND je.fiscal_year_id = ?
              AND je.status != 'draft'
            GROUP BY a.code, a.title
            """,
            (tenant_id, tenant_id, fiscal_year_id),
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            code = r["code"]
            if len(code) < 4 or not code.startswith(tuple(prefixes)):
                continue
            net = float(r["total_debit"] or 0) - float(r["total_credit"] or 0)
            if abs(net) < 0.005:
                continue
            out.append({"code": code, "title": r["title"], "net": net})
        return out

    def close_fiscal_year(
        self,
        tenant_id: str,
        fiscal_year_id: str,
        closing_date: Optional[str] = None,
        user_id: str = "system",
    ) -> Dict[str, Any]:
        """
        بستن سال مالی (سند اختتامیه):
        1) صفر کردن درآمدها (گروه ۶) و هزینه‌ها/بهای تمام شده (گروه ۷) در «خلاصه سود و زیان»
        2) انتقال سود/زیان خالص از خلاصه سود و زیان به «سود انباشته سنواتی»
        3) مهر بستن سال مالی (is_closed = 1)
        """
        fy = self.get_fiscal_year(tenant_id, fiscal_year_id)
        if not fy:
            raise AccountNotFoundError("سال مالی یافت نشد.")
        if int(fy["is_closed"] or 0) == 1:
            raise FiscalYearClosedError("این سال مالی قبلاً بسته شده است.")

        date = closing_date or fy["end_date"]
        jalali = gregorian_to_jalali(date)

        # ---- phase 1: read balances & validate -----------------------------
        with self.get_connection() as conn:
            self._assert_no_drafts_around(conn, tenant_id, fiscal_year_id)
            balances = self._closing_balances(conn, tenant_id, fiscal_year_id, ("6", "7"))

        result: Dict[str, Any] = {
            "fiscal_year_id": fiscal_year_id,
            "closing_date": date,
            "entry_ids": [],
            "net_income": 0.0,
        }

        # ---- phase 2: closing entry for revenues & expenses ----------------
        if balances:
            lines: List[Dict[str, Any]] = []
            income_total = 0.0
            for b in balances:
                desc = f"بستن حساب {b['code']} {b['title']}"
                if b["code"].startswith("6"):
                    if b["net"] < 0:  # normal credit balance (revenue)
                        lines.append({"account_code": b["code"], "description": desc,
                                      "debit": -b["net"], "credit": 0})
                        income_total += -b["net"]
                    else:  # abnormal debit balance (e.g. sales return)
                        lines.append({"account_code": b["code"], "description": desc,
                                      "debit": 0, "credit": b["net"]})
                        income_total -= b["net"]
                else:
                    if b["net"] > 0:  # normal debit balance (cost/expense)
                        lines.append({"account_code": b["code"], "description": desc,
                                      "debit": 0, "credit": b["net"]})
                        income_total -= b["net"]
                    else:  # abnormal credit balance
                        lines.append({"account_code": b["code"], "description": desc,
                                      "debit": -b["net"], "credit": 0})
                        income_total += -b["net"]

            if abs(income_total) >= 0.005:
                lines.append(
                    {
                        "account_code": "5210",
                        "description": "انتقال درآمدها و هزینه‌ها به حساب خلاصه سود و زیان",
                        "debit": round(-income_total, 2) if income_total < 0 else 0,
                        "credit": round(income_total, 2) if income_total > 0 else 0,
                    }
                )
            entry_id = self.record_journal_entry(
                tenant_id=tenant_id,
                fiscal_year_id=fiscal_year_id,
                entry_date=date,
                description="سند اختتامیه: بستن حساب‌های درآمد و هزینه",
                items=lines,
                source_module="closing",
                user_id=user_id,
                status="closing_entry",
                entry_date_jalali=jalali,
            )
            result["entry_ids"].append(entry_id)
            result["net_income"] = round(income_total, 2)

        # ---- phase 3: income summary -> retained earnings ------------------
        with self.get_connection() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN ji.debit > 0 THEN ji.debit ELSE 0 END), 0) -
                       COALESCE(SUM(CASE WHEN ji.credit > 0 THEN ji.credit ELSE 0 END), 0) AS net
                FROM journal_items ji
                JOIN accounts a ON a.id = ji.account_id
                JOIN journal_entries je ON je.id = ji.entry_id
                WHERE a.tenant_id = ? AND a.code = '5210'
                  AND je.fiscal_year_id = ? AND je.status != 'draft'
                """,
                (tenant_id, fiscal_year_id),
            ).fetchone()
            summary_net = float(row["net"] or 0)  # debit - credit
            profit = -summary_net  # credit - debit (سود خالص)

        if abs(profit) >= 0.005:
            if profit > 0:  # credit balance -> profit
                transfer = [
                    {"account_code": "5210",
                     "description": "بستن حساب خلاصه سود و زیان (اتصال به سود انباشته)",
                     "debit": round(profit, 2), "credit": 0},
                    {"account_code": "5110",
                     "description": "سود (زیان) انباشته سنواتی",
                     "debit": 0, "credit": round(profit, 2)},
                ]
            else:  # loss
                transfer = [
                    {"account_code": "5110",
                     "description": "انتقال زیان خالص سال مالی به سود انباشته",
                     "debit": round(-profit, 2), "credit": 0},
                    {"account_code": "5210",
                     "description": "بستن حساب خلاصه سود و زیان (زیان)",
                     "debit": 0, "credit": round(-profit, 2)},
                ]
            entry_id = self.record_journal_entry(
                tenant_id=tenant_id,
                fiscal_year_id=fiscal_year_id,
                entry_date=date,
                description="سند اختتامیه: بستن حساب خلاصه سود و زیان",
                items=transfer,
                source_module="closing",
                user_id=user_id,
                status="closing_entry",
                entry_date_jalali=jalali,
            )
            result["entry_ids"].append(entry_id)
            result["net_income"] = round(profit, 2)

        # ---- phase 4: seal the fiscal year ---------------------------------
        with self.get_connection() as conn:
            current = conn.execute(
                "SELECT is_closed FROM fiscal_years WHERE id = ?", (fiscal_year_id,)
            ).fetchone()
            if current is None:
                raise AccountNotFoundError("سال مالی یافت نشد.")
            if int(current[0] or 0) == 1:
                raise FiscalYearClosedError("این سال مالی قبلاً بسته شده است.")
            conn.execute(
                "UPDATE fiscal_years SET is_closed = 1, closed_at = CURRENT_TIMESTAMP WHERE id = ?",
                (fiscal_year_id,),
            )
            self._audit(
                conn,
                tenant_id,
                "fiscal_year",
                fiscal_year_id,
                "CLOSE",
                user_id,
                {"closed_at": date, "entry_ids": result["entry_ids"]},
            )
        return result

    def create_opening_entry(
        self,
        tenant_id: str,
        fiscal_year_id: str,
        opening_date: Optional[str] = None,
        source_fiscal_year_id: Optional[str] = None,
        user_id: str = "system",
    ) -> Dict[str, Any]:
        """
        سند افتتاحیه سال جدید: انتقال مانده حساب‌های دائمی
        (گروه ۱ دارایی‌های جاری، ۲ دارایی غیرجاری، ۴ بدهی، ۵ حقوق صاحبان سهام)
        به سال مالی جدید.
        """
        with self.get_connection() as conn:
            if not source_fiscal_year_id:
                row = conn.execute(
                    """
                    SELECT id FROM fiscal_years
                    WHERE tenant_id = ? AND end_date < (
                        SELECT end_date FROM fiscal_years WHERE tenant_id = ? AND id = ?
                    )
                    ORDER BY end_date DESC LIMIT 1
                    """,
                    (tenant_id, tenant_id, fiscal_year_id),
                ).fetchone()
                if not row:
                    raise AccountNotFoundError("سال مالی مبدأ برای سند افتتاحیه یافت نشد.")
                source_fiscal_year_id = row[0]
            source_closed = conn.execute(
                "SELECT is_closed FROM fiscal_years WHERE id = ?", (source_fiscal_year_id,)
            ).fetchone()
            if int(source_closed[0] or 0) != 1:
                raise AccountingError(
                    "پیش از ثبت سند افتتاحیه، سال مالی قبلی باید بسته شود."
                )

            balances = self._closing_balances(
                conn, tenant_id, source_fiscal_year_id, ("1", "2", "4", "5")
            )

        fy = self.get_fiscal_year(tenant_id, fiscal_year_id)
        date = opening_date or (fy["start_date"] if fy else None)
        if not date:
            raise AccountNotFoundError("سال مالی مقصد یافت نشد.")

        items = []
        for b in balances:
            if b["net"] > 0:
                items.append(
                    {
                        "account_code": b["code"],
                        "description": f"انتقال مانده {b['code']} {b['title']} (سند افتتاحیه)",
                        "debit": b["net"],
                        "credit": 0,
                    }
                )
            else:
                items.append(
                    {
                        "account_code": b["code"],
                        "description": f"انتقال مانده {b['code']} {b['title']} (سند افتتاحیه)",
                        "debit": 0,
                        "credit": -b["net"],
                    }
                )

        if len(items) < 2:
            return {"entry_id": None, "items": 0, "skipped": True}

        entry_id = self.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fiscal_year_id,
            entry_date=date,
            description="سند افتتاحیه سال مالی جدید",
            items=items,
            source_module="opening",
            user_id=user_id,
            status="opening_entry",
        )
        return {"entry_id": entry_id, "items": len(items), "skipped": False}
