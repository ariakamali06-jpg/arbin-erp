import sys
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

# Add workspace to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ledger import ArbinLedger
from treasury import ArbinTreasury
from ai_copilot import ArbinAICopilot


def _temp_db(name: str) -> str:
    return os.path.join(tempfile.gettempdir(), name)


def test_ai_copilot_suite():
    print("==================================================")
    print("ARBIN AI FINANCIAL COPILOT - TEST SUITE")
    print("==================================================")

    db_test_path = _temp_db("arbin_copilot_test.db")
    if os.path.exists(db_test_path):
        os.remove(db_test_path)

    ledger = ArbinLedger(db_path=db_test_path)
    treasury = ArbinTreasury(ledger)
    copilot = ArbinAICopilot(ledger)

    # 1. Setup Tenant & Initial Capital (Bank = 40,000,000 Toman)
    tenant_id = ledger.create_tenant(name="شرکت هوش مالی آربین", currency="IRT")
    fy_id = ledger.create_fiscal_year(tenant_id, "سال ۱۴۰۵", "2026-03-21", "2027-03-20")
    ledger.seed_standard_accounts(tenant_id)

    ledger.record_journal_entry(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        entry_date="2026-04-01",
        description="سرمایه اولیه موجود در بانک",
        items=[
            {"account_code": "1010", "description": "موجودی اولیه بانک", "debit": 40_000_000, "credit": 0},
            {"account_code": "5010", "description": "سرمایه شرکا", "debit": 0, "credit": 40_000_000}
        ]
    )
    print("OK موجودی اولیه بانک ملت: ۴۰,۰۰۰,۰۰۰ تومان")

    # -------------------------------------------------------------
    # Test 1: OCR & Unstructured Invoice Parsing
    # -------------------------------------------------------------
    sample_ocr_receipt = """
    صورتحساب فروش کالا و خدمات فروشگاه آریا
    تاریخ: 2026/04/18
    اقلام فاکتور:
    مانیتور دل ۲۷ اینچ 2 عدد نرخ 15,000,000 تومان
    کیبورد مکانیکی 3 عدد قیمت 2,000,000 تومان
    کابل اچ‌دی‌ام‌آی 5 عدد فی 400,000 تومان
    مجموع کل: 38,000,000 تومان
    """
    parsed = copilot.parse_unstructured_invoice(sample_ocr_receipt)
    print("\n--------------------------------------------------")
    print("1. نتیجه استخراج هوشمند از متن فاکتور/رسید:")
    print("--------------------------------------------------")
    print(f"تاریخ استخراج شده: {parsed['parsed_date']}")
    print(f"تعداد اقلام شناسایی شده: {parsed['detected_items_count']}")
    for item in parsed["items"]:
        print(f"  - کالا: {item['item_title']:<25} | تعداد: {item['quantity']} | قیمت واحد: {item['unit_price']:>12,.0f}")
    assert parsed["detected_items_count"] == 3
    assert parsed["items"][0]["quantity"] == 2
    assert parsed["items"][0]["unit_price"] == 15_000_000
    assert parsed["parsed_date"] == "2026-04-18"
    print("OK فاکتورخوان هوش مصنوعی با دقت ۱۰۰٪ راستی‌آزمایی شد!")

    # -------------------------------------------------------------
    # Test 2: AI Predictive Cash-Flow Risk Assessment
    # Bank has 40M. Incoming cheque 30M + Outgoing cheque 100M
    # Expected net liquidity = 40M + 30M - 100M = -30M (CRITICAL DEFICIT!)
    # سررسیدها نسبت به امروز محاسبه می‌شوند تا آزمون زمان‌وابسته نباشد.
    # -------------------------------------------------------------
    cust_id = ledger.create_detail_account(tenant_id, "4009", "مشتری وفادار", "customer")
    supp_id = ledger.create_detail_account(tenant_id, "3009", "تامین‌کننده اصلی", "supplier")

    today = date.today()
    incoming_due = (today + timedelta(days=10)).isoformat()
    outgoing_due = (today + timedelta(days=20)).isoformat()

    # Incoming cheque
    treasury.receive_cheque(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        customer_detail_id=cust_id,
        sayyad_id="1111222233334444",
        cheque_number="IN-101",
        bank_name="ملت",
        due_date=incoming_due,
        amount=30_000_000,
        receive_date="2026-04-01"
    )

    # Outgoing cheque (simulate paid cheque in database)
    with ledger.get_connection() as conn:
        conn.execute("""
            INSERT INTO cheques (
                id, tenant_id, fiscal_year_id, cheque_type, sayyad_id, cheque_number,
                bank_name, due_date, amount, party_detail_id, status, description
            ) VALUES ('chk-out-1', ?, ?, 'paid', '9999888877776666', 'OUT-501', 'ملی', ?, 100000000, ?, 'in_safe', 'چک صادره به تامین‌کننده')
        """, (tenant_id, fy_id, outgoing_due, supp_id))

    print("\n--------------------------------------------------")
    print("2. پیش‌بینی هوشمند نقدینگی و ریسک چک‌ها:")
    print("--------------------------------------------------")
    forecast = copilot.predict_cashflow_risks(tenant_id, days_ahead=40)
    print(f"موجودی نقد فعلی بانک:       {forecast['current_liquid_cash']:>15,.0f} تومان")
    print(f"چک‌های دریافتی در موعد:     {forecast['total_incoming_cheques']:>15,.0f} تومان")
    print(f"چک‌های صادره نیازمند پاس:   {forecast['total_outgoing_cheques']:>15,.0f} تومان")
    print(f"خالص پیش‌بینی نقدینگی:       {forecast['net_projected_liquidity']:>15,.0f} تومان")
    print(f"سطح ریسک هوش مصنوعی:        {forecast['risk_level']}")
    for adv in forecast["ai_financial_advice"]:
        print(f"  -> {adv}")

    assert forecast["current_liquid_cash"] == 40_000_000
    assert forecast["risk_level"] == "CRITICAL_DEFICIT"
    assert forecast["net_projected_liquidity"] == -30_000_000
    assert forecast["cheques_in_window_count"] == 2
    print("OK سامانه پیش‌بینی کسری نقدینگی با موفقیت خطر را کشف کرد!")

    # -------------------------------------------------------------
    # Test 3: Natural Language Accounting Instruction
    # -------------------------------------------------------------
    print("\n--------------------------------------------------")
    print("3. تبدیل دستور محاوره‌ای به سند دوبل حسابداری:")
    print("--------------------------------------------------")
    nl_cmd = "ثبت کن ۲۰ میلیون تومان بابت هزینه اجاره دفتر مرکزی"
    voucher_draft = copilot.natural_language_to_voucher(nl_cmd)
    print(f"فرمان صوتی/متنی: \"{nl_cmd}\"")
    print(f"مبلغ شناسایی‌شده: {voucher_draft['amount']:,.0f} تومان")
    for row in voucher_draft["suggested_items"]:
        print(f"  - کد حساب: {row['account_code']} | بدهکار: {row['debit']:>12,.0f} | بستانکار: {row['credit']:>12,.0f}")
    assert voucher_draft["amount"] == 20_000_000
    assert voucher_draft["suggested_items"][0]["account_code"] == "7210"  # هزینه اجاره
    assert voucher_draft["suggested_items"][1]["account_code"] == "1010"  # بانک

    # قصد «وصول مطالبات»: بانک بدهکار / بدهکان تجاری بستانکار
    collect = copilot.natural_language_to_voucher("وصول ۵ میلیون تومان از مشتری")
    assert collect["suggested_items"][0]["account_code"] == "1010"
    assert collect["suggested_items"][1]["account_code"] == "1210"
    print("OK تبدیل گفتار محاوره‌ای به سند دوبل تایید شد!")

    print("\n==================================================")
    print("ALL AI FINANCIAL COPILOT TESTS PASSED!")
    print("==================================================")


if __name__ == "__main__":
    test_ai_copilot_suite()
