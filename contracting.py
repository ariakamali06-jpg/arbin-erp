"""
Arbin Contracting & Projects Engine (سیستم پیمانکاری و قراردادهای آربین)
=============================================================================
Follows Iranian contracting laws and enterprise ERP standard workflows:
1. Contracts Master (پیمان‌ها و قراردادها):
   - Contract number, title, employer detail account (کارفرما), contract value
   - Statutory 10% Good-Performance Retention rate (سپرده حسن انجام کار)
   - Article 38 Social Security withholding rate (ودیعه بیمه ماده ۳۸ - پیش‌فرض ۵٪)
   - Advance payments (پیش‌دریافت‌ها)
2. Progress Billings (صورت‌وضعیت‌های کارکرد):
   - Gross billing amount (کارکرد ناخالص دوره)
   - Automatic deduction of 10% retention deposit
   - Automatic deduction of 5% Article 38 social security withholding
   - Advance payment amortization (استهلاک پیش‌دریافت)
   - 10% VAT calculation on taxable work
   - Net receivable calculation
3. Statutory Balanced Double-Entry Voucher:
   - Debit 1210 (حساب‌های دریافتنی تجاری / کارفرما) [خالص مطالبات]
   - Debit 1320 (سپرده حسن انجام کار نزد کارفرما - ۱۰٪)
   - Debit 1330 (ودیعه بیمه ماده ۳۸ نزد کارفرما - ۵٪)
   - Debit 4080 (پیش‌دریافت‌های پیمانکاری - در صورت استهلاک)
   - Credit 6030 (درآمد کارکرد پیمانکاری و پروژه‌ها) [ناخالص]
   - Credit 4030 (مالیات بر ارزش افزوده پرداختنی - ۱۰٪)
   - Guaranteed 100% mathematical balance: SUM(Debit) == SUM(Credit).
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
import uuid


class ContractingError(Exception):
    """Domain exception for contracting operations."""
    pass


class ArbinContracting:
    """Manages Iranian contracting projects, progress billings, statutory deductions, and vouchers."""

    def __init__(self, ledger):
        self.ledger = ledger
        self.init_db()

    def init_db(self):
        """Create contracting tables if not present."""
        with self.ledger.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS contracts (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    contract_no TEXT NOT NULL,
                    title TEXT NOT NULL,
                    employer_sub_ledger_id TEXT, -- Customer / Employer Detail
                    total_amount REAL NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT,
                    retention_rate REAL NOT NULL DEFAULT 0.10, -- 10% حسن انجام کار
                    sso_rate REAL NOT NULL DEFAULT 0.05,       -- 5% بیمه ماده ۳۸
                    advance_received REAL NOT NULL DEFAULT 0.0,
                    status TEXT NOT NULL DEFAULT 'active',     -- active, completed, suspended
                    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                    UNIQUE(tenant_id, contract_no),
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS progress_billings (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    contract_id TEXT NOT NULL,
                    billing_no TEXT NOT NULL,
                    billing_date TEXT NOT NULL,
                    gross_amount REAL NOT NULL,
                    retention_amount REAL NOT NULL,
                    sso_amount REAL NOT NULL,
                    advance_amortization REAL NOT NULL DEFAULT 0.0,
                    taxable_amount REAL NOT NULL,
                    vat_amount REAL NOT NULL,
                    net_receivable REAL NOT NULL,
                    voucher_id TEXT,
                    status TEXT NOT NULL DEFAULT 'draft', -- draft, confirmed
                    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                    UNIQUE(contract_id, billing_no),
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                    FOREIGN KEY (contract_id) REFERENCES contracts(id) ON DELETE CASCADE
                );
            """)

    def create_contract(
        self,
        tenant_id: str,
        contract_no: str,
        title: str,
        total_amount: float,
        start_date: str,
        employer_sub_ledger_id: Optional[str] = None,
        end_date: Optional[str] = None,
        retention_rate: float = 0.10,
        sso_rate: float = 0.05,
        advance_received: float = 0.0
    ) -> Dict[str, Any]:
        """Register a new construction or service contract."""
        if total_amount <= 0:
            raise ContractingError("مبلغ کل قرارداد باید بزرگتر از صفر باشد.")

        contract_id = str(uuid.uuid4())
        with self.ledger.get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM contracts WHERE tenant_id = ? AND contract_no = ?",
                (tenant_id, contract_no)
            ).fetchone()
            if row:
                raise ContractingError(f"قرارداد شماره «{contract_no}» قبلاً ثبت شده است.")

            conn.execute("""
                INSERT INTO contracts (
                    id, tenant_id, contract_no, title, employer_sub_ledger_id,
                    total_amount, start_date, end_date, retention_rate, sso_rate,
                    advance_received, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """, (
                contract_id, tenant_id, contract_no, title, employer_sub_ledger_id,
                total_amount, start_date, end_date, retention_rate, sso_rate,
                advance_received
            ))

        return {
            "id": contract_id,
            "contract_no": contract_no,
            "title": title,
            "total_amount": total_amount,
            "message": f"قرارداد پیمانکاری «{title}» با شماره «{contract_no}» با موفقیت ثبت شد."
        }

    def submit_progress_billing(
        self,
        tenant_id: str,
        contract_id: str,
        billing_no: str,
        billing_date: str,
        gross_amount: float,
        advance_amortization: float = 0.0
    ) -> Dict[str, Any]:
        """
        Draft a progress billing statement with statutory deductions:
        - 10% Good performance retention
        - 5% Article 38 SSO withholding
        - Advance payment amortization
        - 10% VAT
        """
        if gross_amount <= 0:
            raise ContractingError("مبلغ ناخالص صورت‌وضعیت باید بزرگتر از صفر باشد.")

        with self.ledger.get_connection() as conn:
            contract_row = conn.execute(
                "SELECT * FROM contracts WHERE tenant_id = ? AND id = ?",
                (tenant_id, contract_id)
            ).fetchone()
            if not contract_row:
                raise ContractingError("قرارداد مورد نظر یافت نشد.")

            contract = dict(contract_row)

            # Check duplicate billing_no
            dup = conn.execute(
                "SELECT id FROM progress_billings WHERE contract_id = ? AND billing_no = ?",
                (contract_id, billing_no)
            ).fetchone()
            if dup:
                raise ContractingError(f"صورت‌وضعیت شماره «{billing_no}» برای این قرارداد قبلاً ثبت شده است.")

        gross_dec = Decimal(str(gross_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        ret_rate = Decimal(str(contract["retention_rate"]))
        sso_rate = Decimal(str(contract["sso_rate"]))
        adv_dec = Decimal(str(advance_amortization)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        ret_dec = (gross_dec * ret_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        sso_dec = (gross_dec * sso_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        taxable_dec = gross_dec - adv_dec
        if taxable_dec < Decimal("0.00"):
            taxable_dec = Decimal("0.00")
        vat_dec = (taxable_dec * Decimal("0.10")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Net receivable from employer
        net_dec = gross_dec - ret_dec - sso_dec - adv_dec + vat_dec

        billing_id = str(uuid.uuid4())
        with self.ledger.get_connection() as conn:
            conn.execute("""
                INSERT INTO progress_billings (
                    id, tenant_id, contract_id, billing_no, billing_date,
                    gross_amount, retention_amount, sso_amount, advance_amortization,
                    taxable_amount, vat_amount, net_receivable, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft')
            """, (
                billing_id, tenant_id, contract_id, billing_no, billing_date,
                float(gross_dec), float(ret_dec), float(sso_dec), float(adv_dec),
                float(taxable_dec), float(vat_dec), float(net_dec)
            ))

        return {
            "id": billing_id,
            "contract_no": contract["contract_no"],
            "billing_no": billing_no,
            "gross_amount": float(gross_dec),
            "retention_amount": float(ret_dec),
            "sso_amount": float(sso_dec),
            "advance_amortization": float(adv_dec),
            "vat_amount": float(vat_dec),
            "net_receivable": float(net_dec),
            "status": "draft",
            "message": f"پیش‌نویس صورت‌وضعیت شماره «{billing_no}» به خالص مبلغ {float(net_dec):,.0f} تومان محاسبه و ذخیره گردید."
        }

    def confirm_progress_billing(
        self,
        tenant_id: str,
        fiscal_year_id: str,
        billing_id: str
    ) -> Dict[str, Any]:
        """
        Confirm progress billing and post balanced Iranian statutory double-entry voucher:
        Debit:
          1210 (Receivable from Employer) [net_receivable]
          1320 (Retention Deposit 10%) [retention_amount]
          1330 (Article 38 SSO Deposit 5%) [sso_amount]
          4080 (Advance Payments Amortization) [advance_amortization]
        Credit:
          6030 (Contracting Revenue) [gross_amount]
          4030 (Output VAT 10%) [vat_amount]
        """
        with self.ledger.get_connection() as conn:
            bill_row = conn.execute(
                "SELECT * FROM progress_billings WHERE tenant_id = ? AND id = ?",
                (tenant_id, billing_id)
            ).fetchone()
            if not bill_row:
                raise ContractingError("صورت‌وضعیت یافت نشد.")

            bill = dict(bill_row)
            if bill["status"] == "confirmed":
                raise ContractingError("این صورت‌وضعیت قبلاً تایید و سند آن صادر گردیده است.")

            contract_row = conn.execute(
                "SELECT * FROM contracts WHERE id = ?",
                (bill["contract_id"],)
            ).fetchone()
            contract = dict(contract_row)

        items = [
            # Debit: Net receivable from employer
            {
                "account_code": "1210",
                "sub_ledger_id": contract.get("employer_sub_ledger_id"),
                "debit": float(bill["net_receivable"]),
                "credit": 0.0,
                "description": f"خالص مطالبات صورت‌وضعیت {bill['billing_no']} قرارداد {contract['contract_no']}"
            },
            # Debit: 10% Good performance retention deposit
            {
                "account_code": "1320",
                "sub_ledger_id": contract.get("employer_sub_ledger_id"),
                "debit": float(bill["retention_amount"]),
                "credit": 0.0,
                "description": f"سپرده حسن انجام کار (۱۰٪) صورت‌وضعیت {bill['billing_no']}"
            },
            # Debit: 5% Article 38 SSO deposit
            {
                "account_code": "1330",
                "sub_ledger_id": contract.get("employer_sub_ledger_id"),
                "debit": float(bill["sso_amount"]),
                "credit": 0.0,
                "description": f"ودیعه بیمه ماده ۳۸ تأمین اجتماعی صورت‌وضعیت {bill['billing_no']}"
            }
        ]

        # Debit: Advance payment amortization if any
        if bill["advance_amortization"] > 0:
            items.append({
                "account_code": "4080",
                "sub_ledger_id": contract.get("employer_sub_ledger_id"),
                "debit": float(bill["advance_amortization"]),
                "credit": 0.0,
                "description": f"استهلاک پیش‌دریافت صورت‌وضعیت {bill['billing_no']}"
            })

        # Credit: Contracting revenue (gross amount)
        items.append({
            "account_code": "6030",
            "debit": 0.0,
            "credit": float(bill["gross_amount"]),
            "description": f"درآمد کارکرد پیمانکاری صورت‌وضعیت {bill['billing_no']} قرارداد {contract['contract_no']}"
        })

        # Credit: VAT 10%
        if bill["vat_amount"] > 0:
            items.append({
                "account_code": "4030",
                "debit": 0.0,
                "credit": float(bill["vat_amount"]),
                "description": f"مالیات بر ارزش افزوده فروش صورت‌وضعیت {bill['billing_no']}"
            })

        voucher_id = self.ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fiscal_year_id,
            entry_date=bill["billing_date"],
            description=f"سند حسابداری صورت‌وضعیت کارکرد شماره {bill['billing_no']} (قرارداد {contract['contract_no']})",
            items=items
        )

        with self.ledger.get_connection() as conn:
            conn.execute("""
                UPDATE progress_billings
                SET status = 'confirmed', voucher_id = ?
                WHERE id = ?
            """, (voucher_id, billing_id))

        return {
            "billing_id": billing_id,
            "status": "confirmed",
            "voucher_id": voucher_id,
            "net_receivable": float(bill["net_receivable"]),
            "message": f"صورت‌وضعیت شماره «{bill['billing_no']}» قطعی شد و سند حسابداری پیمانکاری با موفقیت صادر گردید."
        }

    def list_contracts(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List active and completed contracts."""
        with self.ledger.get_connection() as conn:
            rows = conn.execute("""
                SELECT c.*, s.title as employer_name
                FROM contracts c
                LEFT JOIN sub_ledgers s ON c.employer_sub_ledger_id = s.id
                WHERE c.tenant_id = ?
                ORDER BY c.created_at DESC
            """, (tenant_id,)).fetchall()

        return [dict(r) for r in rows]

    def list_billings(self, tenant_id: str, contract_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List progress billings."""
        query = """
            SELECT b.*, c.contract_no, c.title as contract_title
            FROM progress_billings b
            JOIN contracts c ON b.contract_id = c.id
            WHERE b.tenant_id = ?
        """
        params = [tenant_id]
        if contract_id:
            query += " AND b.contract_id = ?"
            params.append(contract_id)
        query += " ORDER BY b.billing_date DESC, b.created_at DESC"

        with self.ledger.get_connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        return [dict(r) for r in rows]
