"""
Arbin Treasury & Cheque Engine (سیستم خزانه‌داری و مدیریت چک‌های صیادی آربین)
- Sayyadi Cheque Management (ثبت چک صیادی ۱۶ رقمی)
- Full Cheque Lifecycle:
    received:   in_safe (نزد صندوق) -> deposited_to_bank (در جریان وصول)
                -> cleared (وصول شده) | bounced (واخواست) |
                   transferred (خرج/واگذاری شده) | returned (مسترد شده)
    issued:     issued (صادره) -> cleared (پاس شده) | cancelled (ابطال شده)
- Receipt / Payment vouchers (رسید و پرداخت): cash, bank_transfer, POS, Sayyad cheque
- Automated Double-Entry Voucher Generation at each step
- Bazaar Cheque Ras Calculator (راس‌گیری هوشمند میانگین وزنی سررسید چک‌ها)

Canonical accounts used by this module:
    1010 حساب‌های بانکی و صندوق   1020 صندوق و تنخواه‌گردان
    1030 اسناد دریافتنی نزد صندوق 1040 اسناد دریافتنی در جریان وصول
    1210 حساب‌های دریافتنی تجاری  4010 حساب‌های پرداختنی تجاری
    4020 اسناد پرداختنی تجاری (چک‌های صادره)
"""

import sqlite3
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from seed_data import ACCOUNT_CODES


class TreasuryError(Exception):
    pass


RECEIVED_TRANSITIONS = {
    "in_safe": ("deposited_to_bank", "returned", "transferred"),
    "deposited_to_bank": ("cleared", "bounced", "transferred", "returned"),
}
ISSUED_TRANSITIONS = {
    "issued": ("cleared", "cancelled"),
}


class ArbinTreasury:
    def __init__(self, ledger):
        self.ledger = ledger

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _code(key: str) -> str:
        return ACCOUNT_CODES[key]

    @staticmethod
    def _party(conn, party_id: Optional[str]) -> tuple:
        if not party_id:
            return None, None
        row = conn.execute(
            "SELECT code, title FROM sub_ledgers WHERE id = ?", (party_id,)
        ).fetchone()
        if not row:
            raise TreasuryError("تفصیلی طرف حساب یافت نشد.")
        return row["code"], row["title"]

    @staticmethod
    def _get_cheque(conn, cheque_id: str) -> sqlite3.Row:  # type: ignore[name-defined]
        chk = conn.execute("SELECT * FROM cheques WHERE id = ?", (cheque_id,)).fetchone()
        if not chk:
            raise TreasuryError("چک مورد نظر یافت نشد.")
        return chk

    @staticmethod
    def _assert_transition(current: str, new: str, cheque_type: str) -> None:
        table = RECEIVED_TRANSITIONS if cheque_type == "received" else ISSUED_TRANSITIONS
        allowed = table.get(current, ())
        if new not in allowed:
            raise TreasuryError(
                f"تغییر وضعیت چک از '{current}' به '{new}' مجاز نیست "
                f"(وضعیت‌های مجاز: {', '.join(allowed) or '—'})."
            )

    def list_cheques(
        self,
        tenant_id: str,
        cheque_type: Optional[str] = None,
        status: Optional[str] = None,
        fiscal_year_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        sql = [
            """
            SELECT c.*, p.code AS party_code, p.title AS party_title,
                   b.title AS bank_account_title
            FROM cheques c
            LEFT JOIN sub_ledgers p ON c.party_detail_id = p.id
            LEFT JOIN sub_ledgers b ON c.bank_account_detail_id = b.id
            WHERE c.tenant_id = ?
            """
        ]
        params: List[Any] = [tenant_id]
        if cheque_type:
            sql.append("AND c.cheque_type = ?")
            params.append(cheque_type)
        if status:
            sql.append("AND c.status = ?")
            params.append(status)
        if fiscal_year_id:
            sql.append("AND c.fiscal_year_id = ?")
            params.append(fiscal_year_id)
        sql.append("ORDER BY c.due_date")
        with self.ledger.get_connection() as conn:
            rows = conn.execute(" ".join(sql), params).fetchall()
        return [dict(r) for r in rows]

    def get_cheque(self, cheque_id: str) -> Dict[str, Any]:
        with self.ledger.get_connection() as conn:
            chk = self._get_cheque(conn, cheque_id)
            data = dict(chk)
        return data

    # ------------------------------------------------------------------
    # 1. Receive a Sayyad cheque from a customer
    # ------------------------------------------------------------------
    def receive_cheque(
        self,
        tenant_id: str,
        fiscal_year_id: str,
        customer_detail_id: str,
        sayyad_id: str,
        cheque_number: str,
        bank_name: str,
        due_date: str,
        amount: float,
        receive_date: str,
        branch_name: Optional[str] = None,
        description: Optional[str] = None,
        user_id: str = "system",
    ) -> Dict[str, Any]:
        """
        1. Register Received Cheque from Customer (ثبت چک دریافتی از مشتری)
        Status: 'in_safe' (نزد صندوق)
        Automatic Voucher:
        - Debit:  1030 (اسناد دریافتنی نزد صندوق)
        - Credit: 1210 (حساب‌های دریافتنی تجاری / مشتری)
        """
        if amount <= 0:
            raise TreasuryError("مبلغ چک باید مثبت باشد.")

        cheque_id = str(uuid.uuid4())
        desc = description or (
            f"دریافت چک صیادی شماره {cheque_number} ({bank_name}) سررسید {due_date}"
        )

        with self.ledger.get_connection() as conn:
            cust_code, cust_title = self._party(conn, customer_detail_id)
            if not cust_code:
                raise TreasuryError("تفصیلی مشتری الزامی است.")
            conn.execute(
                """
                INSERT INTO cheques (
                    id, tenant_id, fiscal_year_id, cheque_type, sayyad_id, cheque_number,
                    bank_name, branch_name, due_date, amount, party_detail_id, status, description
                ) VALUES (?, ?, ?, 'received', ?, ?, ?, ?, ?, ?, ?, 'in_safe', ?)
                """,
                (
                    cheque_id, tenant_id, fiscal_year_id, sayyad_id, cheque_number,
                    bank_name, branch_name, due_date, amount, customer_detail_id, desc,
                ),
            )

        entry_id = self.ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fiscal_year_id,
            entry_date=receive_date,
            description=desc,
            items=[
                {
                    "account_code": self._code("notes_in_safe"),
                    "description": f"دریافت چک شماره {cheque_number} از {cust_title}",
                    "debit": amount,
                    "credit": 0,
                },
                {
                    "account_code": self._code("receivables"),
                    "sub_ledger_code": cust_code,
                    "description": f"تسویه با چک شماره {cheque_number} سررسید {due_date}",
                    "debit": 0,
                    "credit": amount,
                },
            ],
            manual_number=cheque_number,
            source_module="treasury",
            source_id=cheque_id,
            user_id=user_id,
        )

        return {
            "cheque_id": cheque_id,
            "status": "in_safe",
            "journal_entry_id": entry_id,
            "message": "چک با موفقیت در گاوصندوق ثبت و سند حسابداری صادر شد.",
        }

    # ------------------------------------------------------------------
    # 2. Deposit cheque to bank (در جریان وصول)
    # ------------------------------------------------------------------
    def deposit_cheque_to_bank(
        self,
        cheque_id: str,
        bank_account_detail_id: str,
        deposit_date: str,
        user_id: str = "system",
    ) -> Dict[str, Any]:
        """
        2. Deposit Cheque to Bank (خواباندن چک به حساب / در جریان وصول)
        Status: 'deposited_to_bank'
        Automatic Voucher:
        - Debit:  1040 (اسناد دریافتنی در جریان وصول - نزد بانک)
        - Credit: 1030 (اسناد دریافتنی نزد صندوق)
        """
        with self.ledger.get_connection() as conn:
            chk = self._get_cheque(conn, cheque_id)
            if chk["cheque_type"] != "received":
                raise TreasuryError("عملیات وصول فقط برای چک‌های دریافتی مجاز است.")
            self._assert_transition(chk["status"], "deposited_to_bank", chk["cheque_type"])
            bank_code, bank_title = self._party(conn, bank_account_detail_id)
            if not bank_code:
                raise TreasuryError("حساب بانکی مقصد یافت نشد.")
            tenant_id, fy_id = chk["tenant_id"], chk["fiscal_year_id"]
            amount, chk_num = chk["amount"], chk["cheque_number"]

        desc = f"خواباندن چک شماره {chk_num} به حساب {bank_title} جهت وصول"
        entry_id = self.ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fy_id,
            entry_date=deposit_date,
            description=desc,
            items=[
                {
                    "account_code": self._code("cheques_in_collection"),
                    "sub_ledger_code": bank_code,
                    "description": desc,
                    "debit": amount,
                    "credit": 0,
                },
                {
                    "account_code": self._code("notes_in_safe"),
                    "description": f"خروج چک شماره {chk_num} از صندوق و واگذاری به بانک",
                    "debit": 0,
                    "credit": amount,
                },
            ],
            manual_number=chk_num,
            source_module="treasury",
            source_id=cheque_id,
            user_id=user_id,
        )

        with self.ledger.get_connection() as conn:
            conn.execute(
                "UPDATE cheques SET status = 'deposited_to_bank', bank_account_detail_id = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (bank_account_detail_id, cheque_id),
            )

        return {
            "cheque_id": cheque_id,
            "status": "deposited_to_bank",
            "journal_entry_id": entry_id,
            "message": "چک به بانک واگذار شد و سند انتقال به جریان وصول ثبت گردید.",
        }

    # ------------------------------------------------------------------
    # 3. Clear (وصول قطعی)
    # ------------------------------------------------------------------
    def clear_cheque(
        self, cheque_id: str, clear_date: str, user_id: str = "system"
    ) -> Dict[str, Any]:
        """
        3. Clear Cheque into Bank Balance (وصول نهایی چک و افزایش موجودی بانک)
        received: Debit 1010 (بانک) / Credit 1040 (در جریان وصول)
        issued:   Debit 4020 (اسناد پرداختنی) / Credit 1010 (بانک صاحب چک)
        """
        with self.ledger.get_connection() as conn:
            chk = self._get_cheque(conn, cheque_id)
            self._assert_transition(chk["status"], "cleared", chk["cheque_type"])
            tenant_id, fy_id = chk["tenant_id"], chk["fiscal_year_id"]
            amount, chk_num = chk["amount"], chk["cheque_number"]
            bank_code, bank_title = self._party(conn, chk["bank_account_detail_id"])
            party_code, party_title = self._party(conn, chk["party_detail_id"])
            cheque_type = chk["cheque_type"]

        if cheque_type == "received":
            desc = f"وصول قطعی چک شماره {chk_num} و افزایش موجودی حساب {bank_title or 'بانک'}"
            items = [
                {
                    "account_code": self._code("bank"),
                    "sub_ledger_code": bank_code,
                    "description": desc,
                    "debit": amount,
                    "credit": 0,
                },
                {
                    "account_code": self._code("cheques_in_collection"),
                    "sub_ledger_code": bank_code,
                    "description": f"تسویه اسناد در جریان وصول بابت چک شماره {chk_num}",
                    "debit": 0,
                    "credit": amount,
                },
            ]
        else:
            desc = f"پاس شدن چک صادره شماره {chk_num} به {party_title or 'ذینفع'}"
            items = [
                {
                    "account_code": self._code("notes_payable"),
                    "sub_ledger_code": bank_code,
                    "description": f"بستن اسناد پرداختنی بابت چک شماره {chk_num}",
                    "debit": amount,
                    "credit": 0,
                },
                {
                    "account_code": self._code("bank"),
                    "sub_ledger_code": bank_code,
                    "description": desc,
                    "debit": 0,
                    "credit": amount,
                },
            ]

        entry_id = self.ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fy_id,
            entry_date=clear_date,
            description=desc,
            items=items,
            manual_number=chk_num,
            source_module="treasury",
            source_id=cheque_id,
            user_id=user_id,
        )

        with self.ledger.get_connection() as conn:
            conn.execute(
                "UPDATE cheques SET status = 'cleared', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (cheque_id,),
            )

        return {
            "cheque_id": cheque_id,
            "status": "cleared",
            "journal_entry_id": entry_id,
            "message": "چک با موفقیت وصول/پاس شد.",
        }

    # ------------------------------------------------------------------
    # 4. Bounce (واخواست)
    # ------------------------------------------------------------------
    def bounce_cheque(
        self, cheque_id: str, bounce_date: str, reason: Optional[str] = None,
        user_id: str = "system",
    ) -> Dict[str, Any]:
        """
        4. Bounce a deposited cheque (واخواست چک)
        Automatic Voucher: Debit 1210 (بدهکار مشتری) / Credit 1040 (خروج از در جریان وصول)
        """
        with self.ledger.get_connection() as conn:
            chk = self._get_cheque(conn, cheque_id)
            if chk["cheque_type"] != "received":
                raise TreasuryError("واخواست فقط برای چک‌های دریافتی مجاز است.")
            self._assert_transition(chk["status"], "bounced", "received")
            tenant_id, fy_id = chk["tenant_id"], chk["fiscal_year_id"]
            amount, chk_num = chk["amount"], chk["cheque_number"]
            party_code, party_title = self._party(conn, chk["party_detail_id"])
            bank_code, _ = self._party(conn, chk["bank_account_detail_id"])
            in_bank = chk["status"] == "deposited_to_bank"

        desc = f"واخواست چک شماره {chk_num} بابت {party_title or 'بدهکار'}"
        if reason:
            desc = f"{desc} - علت: {reason}"
        items = [
            {
                "account_code": self._code("receivables"),
                "sub_ledger_code": party_code,
                "description": desc,
                "debit": amount,
                "credit": 0,
            },
            {
                "account_code": self._code(
                    "cheques_in_collection" if in_bank else "notes_in_safe"
                ),
                "sub_ledger_code": bank_code,
                "description": f"برگشت چک شماره {chk_num}",
                "debit": 0,
                "credit": amount,
            },
        ]

        entry_id = self.ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fy_id,
            entry_date=bounce_date,
            description=desc,
            items=items,
            manual_number=chk_num,
            source_module="treasury",
            source_id=cheque_id,
            user_id=user_id,
        )

        with self.ledger.get_connection() as conn:
            conn.execute(
                "UPDATE cheques SET status = 'bounced', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (cheque_id,),
            )

        return {
            "cheque_id": cheque_id,
            "status": "bounced",
            "journal_entry_id": entry_id,
            "message": "چک واخواست شد؛ مبلغ به بدهکار مشتری بازگشت.",
        }

    # ------------------------------------------------------------------
    # 5. Transfer / endorse (خرج یا واگذاری چک به ثالث)
    # ------------------------------------------------------------------
    def transfer_cheque(
        self,
        cheque_id: str,
        payee_detail_id: str,
        transfer_date: str,
        user_id: str = "system",
    ) -> Dict[str, Any]:
        """
        5. Endorse a received cheque to a third party (خرج/واگذاری چک)
        - Debit:  4010 (کسر از بدهی به تأمین‌کننده / ذینفع)
        - Credit: 1030 or 1040 (خروج چک از مجموعه اسناد دریافتنی)
        """
        with self.ledger.get_connection() as conn:
            chk = self._get_cheque(conn, cheque_id)
            if chk["cheque_type"] != "received":
                raise TreasuryError("واگذاری فقط برای چک‌های دریافتی مجاز است.")
            self._assert_transition(chk["status"], "transferred", "received")
            tenant_id, fy_id = chk["tenant_id"], chk["fiscal_year_id"]
            amount, chk_num = chk["amount"], chk["cheque_number"]
            payee_code, payee_title = self._party(conn, payee_detail_id)
            bank_code, _ = self._party(conn, chk["bank_account_detail_id"])
            in_bank = chk["status"] == "deposited_to_bank"

        desc = f"واگذاری (خرج) چک شماره {chk_num} به {payee_title}"
        items = [
            {
                "account_code": self._code("payables"),
                "sub_ledger_code": payee_code,
                "description": desc,
                "debit": amount,
                "credit": 0,
            },
            {
                "account_code": self._code("cheques_in_collection" if in_bank else "notes_in_safe"),
                "sub_ledger_code": bank_code,
                "description": f"خروج چک شماره {chk_num} از اسناد دریافتنی",
                "debit": 0,
                "credit": amount,
            },
        ]

        entry_id = self.ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fy_id,
            entry_date=transfer_date,
            description=desc,
            items=items,
            manual_number=chk_num,
            source_module="treasury",
            source_id=cheque_id,
            user_id=user_id,
        )

        with self.ledger.get_connection() as conn:
            conn.execute(
                "UPDATE cheques SET status = 'transferred', payee_detail_id = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (payee_detail_id, cheque_id),
            )

        return {
            "cheque_id": cheque_id,
            "status": "transferred",
            "journal_entry_id": entry_id,
            "message": f"چک به {payee_title} واگذار شد.",
        }

    # ------------------------------------------------------------------
    # 6. Return cheque (استرداد)
    # ------------------------------------------------------------------
    def return_cheque(
        self, cheque_id: str, return_date: str, user_id: str = "system"
    ) -> Dict[str, Any]:
        """
        6. Return a cheque to the original drawer (استرداد چک)
        Reverses the original receipt voucher:
        - Debit:  1210 (مشتری)
        - Credit: 1030 or 1040
        """
        with self.ledger.get_connection() as conn:
            chk = self._get_cheque(conn, cheque_id)
            if chk["cheque_type"] != "received":
                raise TreasuryError("استرداد فقط برای چک‌های دریافتی مجاز است.")
            self._assert_transition(chk["status"], "returned", "received")
            tenant_id, fy_id = chk["tenant_id"], chk["fiscal_year_id"]
            amount, chk_num = chk["amount"], chk["cheque_number"]
            party_code, party_title = self._party(conn, chk["party_detail_id"])
            bank_code, _ = self._party(conn, chk["bank_account_detail_id"])
            in_bank = chk["status"] == "deposited_to_bank"

        desc = f"استرداد چک شماره {chk_num} از {party_title}"
        items = [
            {
                "account_code": self._code("receivables"),
                "sub_ledger_code": party_code,
                "description": desc,
                "debit": amount,
                "credit": 0,
            },
            {
                "account_code": self._code("cheques_in_collection" if in_bank else "notes_in_safe"),
                "sub_ledger_code": bank_code,
                "description": f"خروج چک شماره {chk_num} پس از استرداد",
                "debit": 0,
                "credit": amount,
            },
        ]

        entry_id = self.ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fy_id,
            entry_date=return_date,
            description=desc,
            items=items,
            manual_number=chk_num,
            source_module="treasury",
            source_id=cheque_id,
            user_id=user_id,
        )

        with self.ledger.get_connection() as conn:
            conn.execute(
                "UPDATE cheques SET status = 'returned', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (cheque_id,),
            )

        return {
            "cheque_id": cheque_id,
            "status": "returned",
            "journal_entry_id": entry_id,
            "message": "چک مسترد شد.",
        }

    # ------------------------------------------------------------------
    # 7. Issue a cheque (چک صادره)
    # ------------------------------------------------------------------
    def issue_cheque(
        self,
        tenant_id: str,
        fiscal_year_id: str,
        payee_detail_id: str,
        sayyad_id: str,
        cheque_number: str,
        bank_name: str,
        bank_account_detail_id: str,
        due_date: str,
        amount: float,
        issue_date: str,
        branch_name: Optional[str] = None,
        description: Optional[str] = None,
        user_id: str = "system",
    ) -> Dict[str, Any]:
        """
        7. Issue a company cheque (ثبت چک صادره)
        - Debit:  4010 (کاهش بدهی به ذینفع)
        - Credit: 4020 (اسناد پرداختنی تجاری / چک‌های صادره)
        Status: 'issued'
        """
        if amount <= 0:
            raise TreasuryError("مبلغ چک باید مثبت باشد.")
        cheque_id = str(uuid.uuid4())
        desc = description or f"صدور چک شماره {cheque_number} به {bank_name} سررسید {due_date}"

        with self.ledger.get_connection() as conn:
            payee_code, payee_title = self._party(conn, payee_detail_id)
            if not payee_code:
                raise TreasuryError("تفصیلی ذینفع الزامی است.")
            bank_code, bank_title = self._party(conn, bank_account_detail_id)
            if not bank_code:
                raise TreasuryError("حساب بانکی صاحب چک یافت نشد.")
            conn.execute(
                """
                INSERT INTO cheques (
                    id, tenant_id, fiscal_year_id, cheque_type, sayyad_id, cheque_number,
                    bank_name, branch_name, due_date, amount, party_detail_id,
                    bank_account_detail_id, status, description
                ) VALUES (?, ?, ?, 'issued', ?, ?, ?, ?, ?, ?, ?, ?, 'issued', ?)
                """,
                (
                    cheque_id, tenant_id, fiscal_year_id, sayyad_id, cheque_number,
                    bank_name, branch_name, due_date, amount, payee_detail_id,
                    bank_account_detail_id, desc,
                ),
            )

        entry_id = self.ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fiscal_year_id,
            entry_date=issue_date,
            description=desc,
            items=[
                {
                    "account_code": self._code("payables"),
                    "sub_ledger_code": payee_code,
                    "description": f"کاهش بدهی به {payee_title} با چک شماره {cheque_number}",
                    "debit": amount,
                    "credit": 0,
                },
                {
                    "account_code": self._code("notes_payable"),
                    "sub_ledger_code": bank_code,
                    "description": f"ثبت سند پرداختنی چک صادره {cheque_number} ({bank_title})",
                    "debit": 0,
                    "credit": amount,
                },
            ],
            manual_number=cheque_number,
            source_module="treasury",
            source_id=cheque_id,
            user_id=user_id,
        )

        return {
            "cheque_id": cheque_id,
            "status": "issued",
            "journal_entry_id": entry_id,
            "message": "چک صادره ثبت شد.",
        }

    def cancel_cheque(
        self, cheque_id: str, cancel_date: str, user_id: str = "system"
    ) -> Dict[str, Any]:
        """8. Cancel an issued cheque (ابطال چک صادره) - reverses the issue voucher."""
        with self.ledger.get_connection() as conn:
            chk = self._get_cheque(conn, cheque_id)
            if chk["cheque_type"] != "issued":
                raise TreasuryError("ابطال فقط برای چک‌های صادره مجاز است.")
            self._assert_transition(chk["status"], "cancelled", "issued")
            tenant_id, fy_id = chk["tenant_id"], chk["fiscal_year_id"]
            amount, chk_num = chk["amount"], chk["cheque_number"]
            payee_code, payee_title = self._party(conn, chk["party_detail_id"])
            bank_code, _ = self._party(conn, chk["bank_account_detail_id"])

        desc = f"ابطال چک صادره شماره {chk_num} در حق {payee_title}"
        entry_id = self.ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fy_id,
            entry_date=cancel_date,
            description=desc,
            items=[
                {
                    "account_code": self._code("notes_payable"),
                    "sub_ledger_code": bank_code,
                    "description": f"ابطال سند پرداختنی چک شماره {chk_num}",
                    "debit": amount,
                    "credit": 0,
                },
                {
                    "account_code": self._code("payables"),
                    "sub_ledger_code": payee_code,
                    "description": desc,
                    "debit": 0,
                    "credit": amount,
                },
            ],
            manual_number=chk_num,
            source_module="treasury",
            source_id=cheque_id,
            user_id=user_id,
        )

        with self.ledger.get_connection() as conn:
            conn.execute(
                "UPDATE cheques SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (cheque_id,),
            )

        return {
            "cheque_id": cheque_id,
            "status": "cancelled",
            "journal_entry_id": entry_id,
            "message": "چک صادره ابطال شد.",
        }

    # ------------------------------------------------------------------
    # 9. Receipts & payments (رسید و پرداخت)
    # ------------------------------------------------------------------
    def record_transaction(
        self,
        tenant_id: str,
        fiscal_year_id: str,
        tx_type: str,               # 'receipt' | 'payment'
        method: str,                # 'cash' | 'bank_transfer' | 'pos' | 'sayyad_cheque'
        amount: float,
        tx_date: str,
        party_detail_id: Optional[str] = None,
        bank_account_detail_id: Optional[str] = None,
        pos_terminal_id: Optional[str] = None,
        cheque_id: Optional[str] = None,
        account_code: Optional[str] = None,
        description: Optional[str] = None,
        user_id: str = "system",
    ) -> Dict[str, Any]:
        """
        Treasury receipt / payment voucher (رسید و پرداخت خزانه)
        method:
          cash         -> 1020 صندوق (یا 1010 چنانچه حساب بانکی انتخاب شود)
          bank_transfer-> 1010 حساب‌های بانکی (با تفصیلی بانک)
          pos          -> 1010 حساب بانکی متصل به ترمینال کارتخوان
          sayyad_cheque-> 1030 اسناد دریافتنی نزد صندوق
        """
        if amount <= 0:
            raise TreasuryError("مبلغ تراکنش باید مثبت باشد.")
        if tx_type not in ("receipt", "payment"):
            raise TreasuryError("نوع تراکنش باید receipt یا payment باشد.")
        if method not in ("cash", "bank_transfer", "pos", "sayyad_cheque"):
            raise TreasuryError("روش پرداخت نامعتبر است.")

        with self.ledger.get_connection() as conn:
            party_code, party_title = self._party(conn, party_detail_id)
            bank_code, bank_title = self._party(conn, bank_account_detail_id)
            pos_account_code = bank_code
            if method == "pos" and pos_terminal_id:
                term = conn.execute(
                    "SELECT bank_account_detail_id FROM pos_terminals WHERE id = ? AND tenant_id = ?",
                    (pos_terminal_id, tenant_id),
                ).fetchone()
                if term and term[0]:
                    pos_account_code, bank_title = self._party(conn, term[0])

        if method == "cash":
            asset_code = bank_code or self._code("petty_cash")
        elif method in ("bank_transfer", "pos"):
            asset_code = pos_account_code or bank_code or self._code("bank")
        else:
            asset_code = self._code("notes_in_safe")

        default_counter = (
            self._code("receivables") if tx_type == "receipt" else self._code("payables")
        )
        counter_code = account_code or (default_counter if party_code else (
            self._code("sales_revenue") if tx_type == "receipt" else "7230"
        ))

        desc = description or (
            f"{'رسید' if tx_type == 'receipt' else 'پرداخت'} {method} "
            f"{party_title or ''} به مبلغ {amount:,.0f}".strip()
        )

        if tx_type == "receipt":
            items = [
                {"account_code": asset_code, "sub_ledger_code": bank_code,
                 "description": desc, "debit": amount, "credit": 0},
                {"account_code": counter_code, "sub_ledger_code": party_code,
                 "description": desc, "debit": 0, "credit": amount},
            ]
        else:
            items = [
                {"account_code": counter_code, "sub_ledger_code": party_code,
                 "description": desc, "debit": amount, "credit": 0},
                {"account_code": asset_code, "sub_ledger_code": bank_code,
                 "description": desc, "debit": 0, "credit": amount},
            ]

        entry_id = self.ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fiscal_year_id,
            entry_date=tx_date,
            description=desc,
            items=items,
            source_module="treasury",
            user_id=user_id,
        )

        tx_id = str(uuid.uuid4())
        with self.ledger.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO treasury_transactions (
                    id, tenant_id, fiscal_year_id, tx_type, method, amount, tx_date,
                    party_detail_id, bank_account_detail_id, pos_terminal_id, cheque_id,
                    description, journal_entry_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tx_id, tenant_id, fiscal_year_id, tx_type, method, amount, tx_date,
                    party_detail_id, bank_account_detail_id, pos_terminal_id, cheque_id,
                    desc, entry_id,
                ),
            )

        return {
            "transaction_id": tx_id,
            "journal_entry_id": entry_id,
            "tx_type": tx_type,
            "method": method,
            "amount": amount,
            "message": "سند رسید/پرداخت خزانه ثبت شد.",
        }

    def list_transactions(
        self, tenant_id: str, tx_type: Optional[str] = None,
        fiscal_year_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        sql = ["SELECT * FROM treasury_transactions WHERE tenant_id = ?"]
        params: List[Any] = [tenant_id]
        if tx_type:
            sql.append("AND tx_type = ?")
            params.append(tx_type)
        if fiscal_year_id:
            sql.append("AND fiscal_year_id = ?")
            params.append(fiscal_year_id)
        sql.append("ORDER BY tx_date DESC")
        with self.ledger.get_connection() as conn:
            rows = conn.execute(" ".join(sql), params).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 10. POS terminals
    # ------------------------------------------------------------------
    def create_pos_terminal(
        self,
        tenant_id: str,
        terminal_no: str,
        merchant_id: Optional[str] = None,
        bank_name: Optional[str] = None,
        bank_account_detail_id: Optional[str] = None,
    ) -> str:
        with self.ledger.get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM pos_terminals WHERE tenant_id = ? AND terminal_no = ?",
                (tenant_id, terminal_no),
            ).fetchone()
            if existing:
                return existing[0]
            term_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO pos_terminals (id, tenant_id, terminal_no, merchant_id, bank_name, bank_account_detail_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (term_id, tenant_id, terminal_no, merchant_id, bank_name, bank_account_detail_id),
            )
        return term_id

    def list_pos_terminals(self, tenant_id: str) -> List[Dict[str, Any]]:
        with self.ledger.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM pos_terminals WHERE tenant_id = ? ORDER BY terminal_no",
                (tenant_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 11. Ras calculator (راس‌گیری)
    # ------------------------------------------------------------------
    @staticmethod
    def calculate_ras(cheques: List[Dict[str, Any]], base_date_str: str) -> Dict[str, Any]:
        """
        Calculate Bazaar Weighted Average Due Date (محاسبه راس‌گیری میانگین وزنی چک‌ها)
        Formula:
        days_i = (due_date_i - base_date).days
        ras_days = SUM(amount_i * days_i) / SUM(amount_i)
        """
        if not cheques:
            raise TreasuryError("لیست چک‌ها برای راس‌گیری خالی است.")

        base_date = datetime.strptime(base_date_str, "%Y-%m-%d").date()
        total_amount = Decimal("0.0")
        weighted_product = Decimal("0.0")

        for c in cheques:
            amt = Decimal(str(c["amount"]))
            due = datetime.strptime(c["due_date"], "%Y-%m-%d").date()
            diff_days = (due - base_date).days

            total_amount += amt
            weighted_product += amt * Decimal(str(diff_days))

        if total_amount == 0:
            raise TreasuryError("مجموع مبالغ چک‌ها نمی‌تواند صفر باشد.")

        avg_days = float(weighted_product / total_amount)
        ras_date = base_date + date.resolution * int(round(avg_days))

        return {
            "base_date": base_date_str,
            "total_amount": float(total_amount),
            "cheques_count": len(cheques),
            "weighted_average_days": round(avg_days, 1),
            "ras_due_date": ras_date.strftime("%Y-%m-%d"),
        }
