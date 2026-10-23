"""
Arbin Invoicing & Taxpayer System Engine (سیستم صدور فاکتور فروش و سامانه مؤدیان)
- Automated VAT Calculation (مالیات بر ارزش افزوده ۱۰٪)
- 22-Character Compliant Fiscal Tax ID Generator (شناسه یکتای مالیاتی)
- Automated Double-Entry Journal Voucher Posting (ثبت خودکار سند حسابداری فروش)
- Compliant JSON Export for Tax Authority Dispatch (کارپوشه مالیاتی)
"""

import uuid
from typing import List, Dict, Any
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from database import to_jalali

# ---------------------------------------------------------------------------
# Verhoeff checksum (کنترل‌رقم استاندارد وِرهوف)
# ---------------------------------------------------------------------------
_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_BASE36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def verhoeff_checksum_digit(number: str) -> int:
    """Verhoeff control digit for a numeric string."""
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c


def verhoeff_validate(number: str) -> bool:
    """True when the numeric string carries a valid Verhoeff check digit."""
    return verhoeff_checksum_digit(number) == 0


def _to_base36(value: int, width: int) -> str:
    if value < 0:
        raise ValueError("مقدار منفی در مبدل پایه ۳۶ مجاز نیست.")
    out = ""
    while value:
        value, rem = divmod(value, 36)
        out = _BASE36[rem] + out
    return (out or "0").rjust(width, "0")[-width:]


class InvoicingError(Exception):
    pass

class ArbinInvoicing:
    def __init__(self, ledger):
        self.ledger = ledger

    def _generate_tax_unique_id(
        self, fiscal_memory_id: str, invoice_number: int, invoice_date_str: str
    ) -> str:
        """
        Generate 22-character unique fiscal ID (شناسه یکتای مالیاتی ۲۲ رقمی)
        Structure:
        - 6 chars : Memory Fiscal ID (شناسه حافظه مالیاتی تخصیص‌یافته توسط سازمان)
        - 5 chars : Days elapsed since 2020-01-01 (base36, Julian-style serial day)
        - 10 chars: Serial number (base36, zero-padded)
        - 1 char  : Verhoeff control digit (کنترل‌رقم وِرهوف)
        """
        fiscal_id = (fiscal_memory_id or "ARB001").upper()
        fiscal_id = "".join(ch for ch in fiscal_id if ch in _BASE36)[:6].ljust(6, "0")

        try:
            inv_dt = datetime.strptime(invoice_date_str, "%Y-%m-%d")
        except ValueError:
            inv_dt = datetime.now()
        days = max(0, (inv_dt - datetime(2020, 1, 1)).days)
        days_str = _to_base36(days, 5)
        serial_str = _to_base36(int(invoice_number), 10)

        body = f"{fiscal_id}{days_str}{serial_str}"
        checksum = verhoeff_checksum_digit(str(int(body, 36)))
        return f"{body}{checksum}"[:22]

    @staticmethod
    def validate_tax_id(tax_id: str) -> bool:
        """
        اعتبارسنجی شناسه یکتای مالیاتی ۲۲ کاراکتری (ساختار + کنترل‌رقم وِرهوف)
        """
        if not tax_id or len(tax_id) != 22:
            return False
        body, check = tax_id[:21], tax_id[21:]
        if any(ch not in _BASE36 for ch in body) or check not in _BASE36:
            return False
        try:
            expected = verhoeff_checksum_digit(str(int(body, 36)))
        except ValueError:
            return False
        return int(check) == expected

    def create_invoice(
        self,
        tenant_id: str,
        fiscal_year_id: str,
        customer_detail_id: str,
        invoice_date: str,
        items: List[Dict[str, Any]],
        tax_fiscal_id: str = "ARB001",
        pattern_code: str = "pattern1",
        invoice_type: str = "official_sale",
        payment_status: str = "unpaid",
    ) -> Dict[str, Any]:
        """
        Create a new sales invoice with automatic VAT calculation.
        invoice_type: 'proforma' (پیش‌فاکتور) | 'official_sale' (فاکتور رسمی) | 'sales_return' (برگشت از فروش)
        payment_status: 'unpaid' (نسیه) | 'cash' (نقدی) | 'cheque' (چکی) | 'split' (ترکیبی)
        Items:
        [
            {"item_code": "2720000123456", "item_title": "لایسنس نرم‌افزار آربین",
             "quantity": 2, "unit_price": 50000000, "discount": 5000000, "vat_rate": 0.10}
        ]
        """
        if not items:
            raise InvoicingError("فاکتور فروش باید حداقل دارای یک ردیف کالا یا خدمت باشد.")
        if invoice_type not in ("proforma", "official_sale", "sales_return"):
            raise InvoicingError(f"نوع فاکتور نامعتبر است: {invoice_type}")
        if payment_status not in ("unpaid", "cash", "cheque", "split"):
            raise InvoicingError(f"وضعیت پرداخت فاکتور نامعتبر است: {payment_status}")

        total_amount = Decimal("0.0")
        total_discount = Decimal("0.0")
        total_vat = Decimal("0.0")
        final_payable = Decimal("0.0")

        parsed_items = []
        for idx, item in enumerate(items, start=1):
            qty = Decimal(str(item["quantity"]))
            u_price = Decimal(str(item["unit_price"]))
            disc = Decimal(str(item.get("discount", 0)))
            vat_rate = Decimal(str(item.get("vat_rate", 0.10)))

            subtotal = (qty * u_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            taxable = (subtotal - disc).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            vat_amt = (taxable * vat_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            line_total = taxable + vat_amt

            total_amount += subtotal
            total_discount += disc
            total_vat += vat_amt
            final_payable += line_total

            parsed_items.append({
                "row_number": idx,
                "item_code": item.get("item_code", "2720000000000"),
                "item_title": item["item_title"],
                "unit": item.get("unit", "تعداد"),
                "quantity": float(qty),
                "unit_price": float(u_price),
                "discount": float(disc),
                "vat_rate": float(vat_rate),
                "vat_amount": float(vat_amt),
                "total_price": float(line_total)
            })

        with self.ledger.get_connection() as conn:
            # Atomic invoice number increment
            cur = conn.execute(
                "SELECT COALESCE(MAX(invoice_number), 0) + 1 FROM invoices WHERE tenant_id = ? AND fiscal_year_id = ?",
                (tenant_id, fiscal_year_id)
            )
            inv_number = cur.fetchone()[0]

            tax_unique_id = self._generate_tax_unique_id(tax_fiscal_id, inv_number, invoice_date)
            invoice_id = str(uuid.uuid4())

            conn.execute(
                """
                INSERT INTO invoices (
                    id, tenant_id, fiscal_year_id, invoice_number, invoice_date, customer_detail_id,
                    invoice_type, payment_status, pattern_code, status, total_amount, total_discount,
                    total_vat, final_payable, tax_unique_id, tax_fiscal_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?)
                """,
                (
                    invoice_id, tenant_id, fiscal_year_id, inv_number, invoice_date, customer_detail_id,
                    invoice_type, payment_status, pattern_code,
                    float(total_amount), float(total_discount), float(total_vat), float(final_payable),
                    tax_unique_id, tax_fiscal_id
                )
            )

            # Insert invoice rows
            for p_item in parsed_items:
                row_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO invoice_items (
                        id, invoice_id, tenant_id, row_number, item_code, item_title, unit,
                        quantity, unit_price, discount, vat_rate, vat_amount, total_price
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row_id, invoice_id, tenant_id, p_item["row_number"], p_item["item_code"], p_item["item_title"],
                        p_item["unit"], p_item["quantity"], p_item["unit_price"], p_item["discount"],
                        p_item["vat_rate"], p_item["vat_amount"], p_item["total_price"]
                    )
                )

        return {
            "invoice_id": invoice_id,
            "invoice_number": inv_number,
            "tax_unique_id": tax_unique_id,
            "total_amount": float(total_amount),
            "total_discount": float(total_discount),
            "total_vat": float(total_vat),
            "final_payable": float(final_payable),
            "invoice_type": invoice_type,
            "payment_status": payment_status,
            "status": "draft",
        }

    def confirm_and_post_invoice(
        self,
        invoice_id: str,
        revenue_account_code: str = "6010",
        receivables_account_code: str = "1210",
        vat_account_code: str = "4030",
        user_id: str = "system"
    ) -> str:
        """
        Confirm sales invoice and automatically post double-entry journal voucher to the ledger:
        Debit: Accounts Receivable (1210) with Customer Sub-Ledger -> Final Payable
        Credit: Sales Revenue (6010) -> Total Amount - Total Discount
        Credit: VAT Payable (4030) -> Total VAT
        """
        with self.ledger.get_connection() as conn:
            inv_row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
            if not inv_row:
                raise InvoicingError("فاکتور مورد نظر یافت نشد.")
            if inv_row["status"] == "confirmed":
                raise InvoicingError("این فاکتور قبلاً تایید و سند حسابداری آن صادر شده است.")

            tenant_id = inv_row["tenant_id"]
            fy_id = inv_row["fiscal_year_id"]
            inv_num = inv_row["invoice_number"]
            inv_date = inv_row["invoice_date"]
            cust_det_id = inv_row["customer_detail_id"]
            final_payable = inv_row["final_payable"]
            net_sales = inv_row["total_amount"] - inv_row["total_discount"]
            vat_amount = inv_row["total_vat"]

            # Lookup customer sub-ledger code
            det_row = conn.execute(
                "SELECT code, title FROM sub_ledgers WHERE id = ?", (cust_det_id,)
            ).fetchone()
            cust_code = det_row["code"] if det_row else None
            cust_name = det_row["title"] if det_row else "مشتری"

        # Build journal voucher rows
        voucher_items = [
            {
                "account_code": receivables_account_code,
                "detail_code": cust_code,
                "description": f"فروش کالا/خدمات طبق فاکتور شماره {inv_num} به {cust_name}",
                "debit": final_payable,
                "credit": 0
            },
            {
                "account_code": revenue_account_code,
                "detail_code": None,
                "description": f"درآمد فروش طبق فاکتور شماره {inv_num}",
                "debit": 0,
                "credit": net_sales
            }
        ]

        if vat_amount > 0:
            voucher_items.append({
                "account_code": vat_account_code,
                "detail_code": None,
                "description": f"مالیات بر ارزش افزوده (۱۰٪) فاکتور شماره {inv_num}",
                "debit": 0,
                "credit": vat_amount
            })

        # Post to ledger via double-entry engine
        entry_id = self.ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fy_id,
            entry_date=inv_date,
            description=f"ثبت خودکار فاکتور فروش شماره {inv_num} - {cust_name}",
            items=voucher_items,
            manual_number=str(inv_num),
            source_module="sales",
            user_id=user_id
        )

        # Update invoice status
        with self.ledger.get_connection() as conn:
            conn.execute(
                "UPDATE invoices SET status = 'confirmed', journal_entry_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (entry_id, invoice_id)
            )

        return entry_id

    def export_taxpayer_system_json(self, invoice_id: str) -> Dict[str, Any]:
        """
        Export invoice in the exact JSON payload format mandated by the Iranian National Tax Administration
        (قالب استاندارد صورتحساب الکترونیکی سامانه مؤدیان)
        """
        with self.ledger.get_connection() as conn:
            inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
            if not inv:
                raise InvoicingError("فاکتور یافت نشد.")

            tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (inv["tenant_id"],)).fetchone()
            cust = conn.execute("SELECT * FROM sub_ledgers WHERE id = ?", (inv["customer_detail_id"],)).fetchone()
            items = conn.execute("SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY row_number", (invoice_id,)).fetchall()

            # Millisecond timestamp for indatim (Issue Date and Time)
            dt_obj = datetime.strptime(inv["invoice_date"], "%Y-%m-%d")
            indatim = int(dt_obj.replace(tzinfo=timezone.utc).timestamp() * 1000)

            header = {
                "taxid": inv["tax_unique_id"],
                "indatim": indatim,
                "Indati2m": indatim,
                "inty": 1,                      # نوع صورتحساب (۱: صورتحساب الکترونیکی نوع اول)
                "inno": f"{inv['invoice_number']:010d}",
                "irtaxid": None,
                "inp": 1,                       # الگوی فروش (۱: فروش کالا و خدمات)
                "ins": 1,                       # موضوع صورتحساب (۱: اصلی)
                "tins": tenant["national_id"] or "14000000000", # شناسه ملی فروشنده
                "tob": 2 if cust and cust["sub_ledger_type"] == "customer" else 1, # نوع خریدار (۱: حقیقی، ۲: حقوقی)
                "bid": cust["national_id"] if cust else None,
                "tinb": cust["national_id"] if cust else None,
                "tprdis": inv["total_amount"],
                "tdis": inv["total_discount"],
                "tadis": inv["total_amount"] - inv["total_discount"],
                "tvam": inv["total_vat"],
                "todam": 0.0,
                "tbill": inv["final_payable"],
                "setm": 1 if inv["payment_status"] == "cash" else 2  # روش تسویه (۱: نقدی، ۲: نسیه)
            }

            body = []
            for it in items:
                body.append({
                    "sstid": it["item_code"],   # شناسه کالا/خدمت سازمان امور مالیاتی
                    "sstt": it["item_title"],
                    "mu": it["unit"],
                    "am": it["quantity"],
                    "fee": it["unit_price"],
                    "prdis": it["quantity"] * it["unit_price"],
                    "dis": it["discount"],
                    "adis": (it["quantity"] * it["unit_price"]) - it["discount"],
                    "vra": int(it["vat_rate"] * 100), # نرخ مالیات (۱۰)
                    "vam": it["vat_amount"],
                    "tsstam": it["total_price"]
                })

            return {
                "header": header,
                "body": body,
                "payments": [
                    {
                        "iinn": "1010",
                        "acn": "MAIN_IRAN_ACCOUNT",
                        "trmn": "POS_001",
                        "pdt": indatim,
                        "pv": inv["final_payable"]
                    }
                ]
            }

    INVOICE_TYPE_LABELS = {
        "proforma": "پیش‌فاکتور",
        "official_sale": "فاکتور فروش",
        "sales_return": "برگشت از فروش",
    }
    PAYMENT_STATUS_LABELS = {
        "unpaid": "نسیه",
        "cash": "نقدی",
        "cheque": "چکی",
        "split": "ترکیبی",
    }

    def list_invoices(self, tenant_id: str) -> List[Dict[str, Any]]:
        with self.ledger.get_connection() as conn:
            rows = conn.execute("""
                SELECT i.*, d.title as customer_name, d.code as customer_code
                FROM invoices i
                JOIN sub_ledgers d ON i.customer_detail_id = d.id
                WHERE i.tenant_id = ?
                ORDER BY i.invoice_number DESC
            """, (tenant_id,)).fetchall()
            return [
                {
                    "id": r["id"],
                    "number": r["invoice_number"],
                    "date": r["invoice_date"],
                    "date_jalali": to_jalali(r["invoice_date"]),
                    "customer": r["customer_name"],
                    "customer_code": r["customer_code"],
                    "total_amount": float(r["total_amount"]),
                    "discount": float(r["total_discount"]),
                    "vat": float(r["total_vat"]),
                    "final_payable": float(r["final_payable"]),
                    "tax_id": r["tax_unique_id"],
                    "invoice_type": r["invoice_type"],
                    "invoice_type_label": self.INVOICE_TYPE_LABELS.get(
                        r["invoice_type"], r["invoice_type"]
                    ),
                    "payment_status": r["payment_status"],
                    "payment_status_label": self.PAYMENT_STATUS_LABELS.get(
                        r["payment_status"], r["payment_status"]
                    ),
                    "status": "تایید شده" if r["status"] == "confirmed" else ("ابطال شده" if r["status"] == "cancelled" else "پیش‌نویس"),
                    "raw_status": r["status"]
                }
                for r in rows
            ]

    def get_invoice(self, invoice_id: str) -> Dict[str, Any]:
        """Full invoice (header + rows) for print preview and API consumers."""
        with self.ledger.get_connection() as conn:
            inv = conn.execute(
                """
                SELECT i.*, d.title AS customer_name, d.code AS customer_code,
                       d.phone AS customer_phone, d.national_id AS customer_national_id
                FROM invoices i
                LEFT JOIN sub_ledgers d ON i.customer_detail_id = d.id
                WHERE i.id = ?
                """,
                (invoice_id,),
            ).fetchone()
            if not inv:
                raise InvoicingError("فاکتور مورد نظر یافت نشد.")
            items = conn.execute(
                "SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY row_number",
                (invoice_id,),
            ).fetchall()
        data = dict(inv)
        data["items"] = [dict(i) for i in items]
        data["tax_id_valid"] = self.validate_tax_id(data.get("tax_unique_id") or "")
        data["invoice_type_label"] = self.INVOICE_TYPE_LABELS.get(
            data.get("invoice_type"), data.get("invoice_type")
        )
        data["payment_status_label"] = self.PAYMENT_STATUS_LABELS.get(
            data.get("payment_status"), data.get("payment_status")
        )
        return data

    def cancel_invoice(self, invoice_id: str, reason: str = "ابطال توسط کاربر", user_id: str = "system") -> Dict[str, Any]:
        """
        Cancels a confirmed invoice or deletes a draft invoice.
        If confirmed: Generates reverse double-entry voucher (Storno) to cancel receivables and revenues cleanly.
        """
        with self.ledger.get_connection() as conn:
            inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
            if not inv:
                raise InvoicingError("فاکتور مورد نظر یافت نشد.")

            if inv["status"] == "cancelled":
                raise InvoicingError("این فاکتور قبلاً ابطال شده است.")

            tenant_id = inv["tenant_id"]
            fy_id = inv["fiscal_year_id"]
            inv_num = inv["invoice_number"]
            cust_det_id = inv["customer_detail_id"]
            final_payable = inv["final_payable"]
            net_sales = inv["total_amount"] - inv["total_discount"]
            vat_amount = inv["total_vat"]

            det_row = conn.execute("SELECT code, title FROM sub_ledgers WHERE id = ?", (cust_det_id,)).fetchone()
            cust_code = det_row["code"] if det_row else None
            cust_name = det_row["title"] if det_row else "مشتری"

            if inv["status"] == "draft":
                conn.execute("DELETE FROM invoice_items WHERE invoice_id = ?", (invoice_id,))
                conn.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
                return {"status": "deleted", "message": "فاکتور پیش‌نویس حذف شد."}

        # If confirmed: post reversing accounting entry (سند اصلاحی/برگشت از فروش)
        reverse_voucher_items = [
            {
                "account_code": "6110", # برگشت از فروش و تخفیفات اعطایی (6110)
                "detail_code": None,
                "description": f"ابطال و برگشت فاکتور شماره {inv_num} ({cust_name}) - علت: {reason}",
                "debit": net_sales,
                "credit": 0
            },
            {
                "account_code": "1210", # کاهش بدهکاری مشتری
                "detail_code": cust_code,
                "description": f"کاهش بدهی بابت ابطال فاکتور شماره {inv_num}",
                "debit": 0,
                "credit": final_payable
            }
        ]
        if vat_amount > 0:
            reverse_voucher_items.insert(1, {
                "account_code": "4030", # کاهش بدهی مالیات ارزش افزوده
                "detail_code": None,
                "description": f"ابطال مالیات ارزش افزوده فاکتور شماره {inv_num}",
                "debit": vat_amount,
                "credit": 0
            })

        rev_entry_id = self.ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fy_id,
            entry_date=datetime.now().strftime("%Y-%m-%d"),
            description=f"سند اصلاحی/ابطال خودکار فاکتور فروش شماره {inv_num}",
            items=reverse_voucher_items,
            source_module="sales_cancel",
            user_id=user_id
        )

        with self.ledger.get_connection() as conn:
            conn.execute(
                "UPDATE invoices SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (invoice_id,)
            )

        return {
            "status": "cancelled",
            "reversal_journal_entry_id": rev_entry_id,
            "message": f"فاکتور شماره {inv_num} با موفقیت ابطال و سند معکوس مالی آن صادر گردید."
        }

