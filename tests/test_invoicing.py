import sys
import os
import json
import tempfile
from pathlib import Path

# Add core to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ledger import ArbinLedger
from reports import ArbinReports
from invoicing import ArbinInvoicing


def _temp_db(name: str) -> str:
    return os.path.join(tempfile.gettempdir(), name)


def test_invoicing_and_taxpayer_system():
    print("==================================================")
    print("ARBIN INVOICING & TAXPAYER SYSTEM (سامانه مؤدیان) - TEST")
    print("==================================================")

    db_test_path = _temp_db("arbin_invoice_test.db")
    if os.path.exists(db_test_path):
        os.remove(db_test_path)

    ledger = ArbinLedger(db_path=db_test_path)
    reports = ArbinReports(ledger)
    invoicing = ArbinInvoicing(ledger)

    # 1. Setup Tenant & Fiscal Year
    tenant_id = ledger.create_tenant(
        name="شرکت توسعه فناوری مالی آربین",
        national_id="14009876543",
        currency="IRT"
    )
    fy_id = ledger.create_fiscal_year(
        tenant_id=tenant_id,
        title="سال مالی ۱۴۰۵",
        start_date="2026-03-21",
        end_date="2027-03-20"
    )
    ledger.seed_standard_accounts(tenant_id)

    # 2. Add customer
    cust_id = ledger.create_detail_account(
        tenant_id=tenant_id,
        code="4002",
        title="شرکت راهکار نوین پرداز (مشتری حقوقی)",
        detail_type="customer",
        phone="02188889999"
    )
    print("OK مشتری و تنظیمات اولیه مالیاتی با موفقیت ثبت شد.")

    # 3. Create Sales Invoice with 2 items and 10% VAT
    # Item 1: 5 x 20,000,000 = 100,000,000 (Discount 10,000,000 -> 90,000,000, VAT 9,000,000)
    # Item 2: 1 x 30,000,000 = 30,000,000 (VAT 3,000,000)
    # Taxable = 120,000,000 | VAT = 12,000,000 | Payable = 132,000,000
    inv_data = invoicing.create_invoice(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        customer_detail_id=cust_id,
        invoice_date="2026-04-12",
        items=[
            {
                "item_code": "2720000112233",
                "item_title": "اشتراک سالانه نرم‌افزار ابری آربین",
                "quantity": 5,
                "unit_price": 20_000_000,
                "discount": 10_000_000,
                "vat_rate": 0.10
            },
            {
                "item_code": "2720000445566",
                "item_title": "خدمات استقرار و کانفیگ اختصاصی سرور",
                "quantity": 1,
                "unit_price": 30_000_000,
                "discount": 0,
                "vat_rate": 0.10
            }
        ],
        tax_fiscal_id="ARB999"
    )

    print(f"OK فاکتور فروش پیش‌نویس شماره {inv_data['invoice_number']} صادر شد:")
    print(f"  - جمع ناخالص: {inv_data['total_amount']:,.0f} تومان")
    print(f"  - تخفیف:      {inv_data['total_discount']:,.0f} تومان")
    print(f"  - مالیات بر ارزش افزوده (۱۰٪): {inv_data['total_vat']:,.0f} تومان")
    print(f"  - مبلغ نهایی قابل پرداخت:     {inv_data['final_payable']:,.0f} تومان")
    print(f"  - شناسه یکتای مالیاتی (Tax ID): {inv_data['tax_unique_id']}")

    assert inv_data["total_amount"] == 130_000_000
    assert inv_data["total_discount"] == 10_000_000
    assert inv_data["total_vat"] == 12_000_000
    assert inv_data["final_payable"] == 132_000_000
    assert len(inv_data["tax_unique_id"]) == 22, "شناسه مالیاتی باید دقیقاً ۲۲ کاراکتر باشد!"
    assert inv_data["invoice_type"] == "official_sale"
    assert inv_data["payment_status"] == "unpaid"
    assert inv_data["status"] == "draft"

    # -------------------------------------------------------------
    # اعتبارسنجی شناسه مالیاتی با الگوریتم Verhoeff
    # -------------------------------------------------------------
    tax_id = inv_data["tax_unique_id"]
    assert ArbinInvoicing.validate_tax_id(tax_id) is True
    # تغییر یک رقم بدون اصلاح رقم کنترلی باید رد شود
    tampered = tax_id[:-1] + ("0" if tax_id[-1] != "0" else "1")
    assert ArbinInvoicing.validate_tax_id(tampered) is False
    assert ArbinInvoicing.validate_tax_id("123") is False
    print("OK الگوریتم Verhoeff شناسه مالیاتی تایید شد (کد صحیح پذیرفته، کد خطا رد شد).")

    # 4. Confirm and Automatically Post to Accounting Ledger
    entry_id = invoicing.confirm_and_post_invoice(inv_data["invoice_id"])
    print(f"OK فاکتور تایید شد و سند حسابداری دوبل با شناسه {entry_id} خودکار صادر گردید.")

    # 5. Verify Ledger Balances immediately reflect the sale and VAT liability
    tb = reports.get_trial_balance(tenant_id, level="subsidiary", fiscal_year_id=fy_id)
    account_map = {row["code"]: row for row in tb}

    # Receivable (1210) should have Debit balance of 132M
    rec_acc = account_map.get("1210")
    assert rec_acc is not None
    assert rec_acc["balance_debit"] == 132_000_000, f"خطا در مانده بدهکاران: {rec_acc['balance_debit']}"
    print(f"OK مانده بدهکاران تجاری (حساب ۱۲۱۰): {rec_acc['balance_debit']:,.0f} تومان")

    # Sales Revenue (6010) should have Credit balance of 120M
    rev_acc = account_map.get("6010")
    assert rev_acc is not None
    assert rev_acc["balance_credit"] == 120_000_000, f"خطا در درآمد فروش: {rev_acc['balance_credit']}"
    print(f"OK درآمد ناخالص فروش (حساب ۶۰۱۰): {rev_acc['balance_credit']:,.0f} تومان")

    # VAT Payable (4030) should have Credit balance of 12M
    vat_acc = account_map.get("4030")
    assert vat_acc is not None
    assert vat_acc["balance_credit"] == 12_000_000, f"خطا در ارزش افزوده: {vat_acc['balance_credit']}"
    print(f"OK ارزش افزوده پرداختنی (حساب ۴۰۳۰): {vat_acc['balance_credit']:,.0f} تومان")

    # 6. Verify Taxpayer System JSON Export
    tax_payload = invoicing.export_taxpayer_system_json(inv_data["invoice_id"])
    print("\n--------------------------------------------------")
    print("خروجی استاندارد کارپوشه سامانه مؤدیان (Taxpayer Payload):")
    print("--------------------------------------------------")
    print(json.dumps(tax_payload["header"], indent=2, ensure_ascii=False))
    print(f"تعداد اقلام صورتحساب ارسالی: {len(tax_payload['body'])}")
    assert tax_payload["header"]["taxid"] == inv_data["tax_unique_id"]
    assert tax_payload["header"]["tbill"] == 132_000_000
    assert tax_payload["header"]["setm"] == 2  # نسیه
    assert len(tax_payload["body"]) == 2
    assert len(tax_payload["payments"]) == 1

    # 7. جزئیات فاکتور و فهرست فاکتورها
    detail = invoicing.get_invoice(inv_data["invoice_id"])
    assert len(detail["items"]) == 2
    assert detail["tax_id_valid"] is True
    assert detail["invoice_type"] == "official_sale"
    assert detail["payment_status"] == "unpaid"

    listed = invoicing.list_invoices(tenant_id)
    assert len(listed) == 1
    assert listed[0]["invoice_type"] == "official_sale"
    assert listed[0]["date_jalali"] == "1405/01/23"

    # 8. فاکتور نقدی + تایید + ابطال (سند معکوس/استورنو)
    cash_inv = invoicing.create_invoice(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        customer_detail_id=cust_id,
        invoice_date="2026-04-14",
        items=[{"item_code": "2720000778899", "item_title": "پشتیبانی فنی",
                "quantity": 1, "unit_price": 10_000_000, "vat_rate": 0.10}],
        invoice_type="proforma",
        payment_status="cash",
    )
    assert cash_inv["invoice_type"] == "proforma"
    assert cash_inv["payment_status"] == "cash"
    assert cash_inv["final_payable"] == 11_000_000

    invoicing.confirm_and_post_invoice(cash_inv["invoice_id"])
    tb = {row["code"]: row for row in reports.get_trial_balance(tenant_id, fiscal_year_id=fy_id)}
    assert tb["1210"]["balance_debit"] == 143_000_000
    assert tb["6010"]["balance_credit"] == 130_000_000
    assert tb["4030"]["balance_credit"] == 13_000_000

    cancelled = invoicing.cancel_invoice(cash_inv["invoice_id"], reason="ابطال پیش‌فاکتور آزمایشی")
    assert cancelled["status"] == "cancelled"
    assert cancelled["reversal_journal_entry_id"]
    tb = {row["code"]: row for row in reports.get_trial_balance(tenant_id, fiscal_year_id=fy_id)}
    assert tb["6110"]["balance_debit"] == 10_000_000, "سند معکوس باید بدهکار برگشت از فروش شود."
    assert tb["1210"]["balance_debit"] == 132_000_000, "ابطال باید مطالبات را به قبل برگرداند."
    assert tb["6010"]["balance_credit"] == 130_000_000, "درآمد فروش دست‌نخورده می‌ماند (ابطال در ۶۱۱۰ ثبت می‌شود)."
    assert tb["4030"]["balance_credit"] == 12_000_000
    inc = reports.get_income_statement(tenant_id, fy_id)
    assert inc["total_revenue"] == 120_000_000, "درآمد خالص (فروش منهای برگشت) باید ۱۲۰M باشد."
    print("OK ابطال فاکتور تاییدشده با سند معکوس (استورنو) و تراز مجدد دفتر کل تایید شد.")

    print("\n==================================================")
    print("ALL INVOICING & TAXPAYER TESTS PASSED!")
    print("==================================================")


if __name__ == "__main__":
    test_invoicing_and_taxpayer_system()
