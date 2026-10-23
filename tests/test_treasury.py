import sys
import os
import tempfile
from pathlib import Path

# Add core to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ledger import ArbinLedger
from reports import ArbinReports
from treasury import ArbinTreasury, TreasuryError


def _temp_db(name: str) -> str:
    return os.path.join(tempfile.gettempdir(), name)


def test_treasury_lifecycle_and_ras():
    print("==================================================")
    print("ARBIN TREASURY & CHEQUE ENGINE (خزانه‌داری آربین) - TEST")
    print("==================================================")

    db_test_path = _temp_db("arbin_treasury_test.db")
    if os.path.exists(db_test_path):
        os.remove(db_test_path)

    ledger = ArbinLedger(db_path=db_test_path)
    reports = ArbinReports(ledger)
    treasury = ArbinTreasury(ledger)

    # 1. Setup Tenant & Accounts
    tenant_id = ledger.create_tenant(
        name="شرکت تجارت الکترونیک آربین",
        currency="IRT"
    )
    fy_id = ledger.create_fiscal_year(
        tenant_id=tenant_id,
        title="سال مالی ۱۴۰۵",
        start_date="2026-03-21",
        end_date="2027-03-20"
    )
    ledger.seed_standard_accounts(tenant_id)

    # Add Customer, Vendor and Bank Account sub-ledgers
    cust_id = ledger.create_detail_account(tenant_id, "4005", "فروشگاه بزرگ آریا", "customer")
    supp_id = ledger.create_detail_account(tenant_id, "300201", "شرکت واردات رایانه پارس", "supplier")
    bank_id = ledger.create_detail_account(tenant_id, "100202", "بانک صادرات - حساب جاری ۲۲۲", "bank")

    # -------------------------------------------------------------
    # Step 1: دریافت چک صیادی از مشتری (۵۰ میلیون تومان)
    # -------------------------------------------------------------
    recv_res = treasury.receive_cheque(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        customer_detail_id=cust_id,
        sayyad_id="7123456789012345",
        cheque_number="CHK-8801",
        bank_name="بانک ملت",
        due_date="2026-06-20",
        amount=50_000_000,
        receive_date="2026-04-10"
    )
    cheque_id = recv_res["cheque_id"]
    assert recv_res["status"] == "in_safe"
    print("OK مرحله ۱: چک صیادی دریافتی در گاوصندوق ثبت شد (مبلغ: ۵۰,۰۰۰,۰۰۰ تومان)")

    # 1030 (اسناد در صندوق) بدهکار ۵۰M / 1210 (بدهکاران) بستانکار ۵۰M
    tb1 = {r["code"]: r for r in reports.get_trial_balance(tenant_id)}
    assert tb1["1030"]["balance_debit"] == 50_000_000
    assert tb1["1210"]["balance_credit"] == 50_000_000
    print("  -> سند دوبل مرحله ۱: اسناد در صندوق (بدهکار ۵۰M) / مشتری (بستانکار ۵۰M) OK")

    # -------------------------------------------------------------
    # Step 2: خواباندن چک به حساب بانک صادرات جهت وصول
    # -------------------------------------------------------------
    dep_res = treasury.deposit_cheque_to_bank(
        cheque_id=cheque_id,
        bank_account_detail_id=bank_id,
        deposit_date="2026-06-18"
    )
    assert dep_res["status"] == "deposited_to_bank"
    print("OK مرحله ۲: چک به بانک صادرات واگذار شد (در جریان وصول)")

    tb2 = {r["code"]: r for r in reports.get_trial_balance(tenant_id)}
    assert tb2["1030"]["balance_debit"] == 0
    assert tb2["1040"]["balance_debit"] == 50_000_000
    print("  -> سند دوبل مرحله ۲: در جریان وصول (بدهکار ۵۰M) / اسناد در صندوق (بستانکار ۵۰M) OK")

    # -------------------------------------------------------------
    # Step 3: وصول قطعی چک در روز سررسید
    # -------------------------------------------------------------
    clr_res = treasury.clear_cheque(
        cheque_id=cheque_id,
        clear_date="2026-06-20"
    )
    assert clr_res["status"] == "cleared"
    print("OK مرحله ۳: چک سررسید و پاس شد (افزایش موجودی حساب بانک)")

    tb3 = {r["code"]: r for r in reports.get_trial_balance(tenant_id)}
    assert tb3["1040"]["balance_debit"] == 0
    assert tb3["1010"]["balance_debit"] == 50_000_000
    assert tb3["1210"]["balance_credit"] == 50_000_000
    print("  -> سند دوبل مرحله ۳: موجودی بانک (بدهکار ۵۰M) / در جریان وصول (بستانکار ۵۰M) OK")

    # -------------------------------------------------------------
    # Step 4: چک برگشتی (bounce) - چرخه چهار مرحله‌ای
    # -------------------------------------------------------------
    recv2 = treasury.receive_cheque(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        customer_detail_id=cust_id,
        sayyad_id="7123456789012399",
        cheque_number="CHK-8802",
        bank_name="بانک ملت",
        due_date="2026-07-15",
        amount=30_000_000,
        receive_date="2026-05-01"
    )
    cheque2 = recv2["cheque_id"]
    # انتقال مستقیم از «نزد صندوق» به «برگشتی» مجاز نیست
    try:
        treasury.bounce_cheque(cheque2, bounce_date="2026-07-15", reason="موجودی ناکافی")
        raise AssertionError("برگشت چک پیش از واگذاری به بانک باید رد شود.")
    except TreasuryError as e:
        print(f"  -> قاعده گذار وضعیت چک فعال است: {e}")

    treasury.deposit_cheque_to_bank(
        cheque_id=cheque2,
        bank_account_detail_id=bank_id,
        deposit_date="2026-07-13"
    )
    tb_before_bounce = {r["code"]: r for r in reports.get_trial_balance(tenant_id)}
    assert tb_before_bounce["1040"]["balance_debit"] == 30_000_000
    assert tb_before_bounce["1210"]["balance_credit"] == 80_000_000

    bounce_res = treasury.bounce_cheque(cheque2, bounce_date="2026-07-15", reason="موجودی ناکافی")
    assert bounce_res["status"] == "bounced"
    tb4 = {r["code"]: r for r in reports.get_trial_balance(tenant_id)}
    # مطالبه بابت چک برگشتی دوباره بدهکار می‌شود (۸۰-۳۰ = ۵۰ میلیون بستانکار)
    assert tb4["1210"]["balance_credit"] == 50_000_000, "پس از برگشت، مطالبه باید دوباره ثبت شود."
    assert tb4["1040"]["balance_debit"] == 0, "پس از برگشت، اسناد در جریان وصول باید صفر شود."
    # چک برگشتی دیگر قابل پاس شدن نیست
    try:
        treasury.clear_cheque(cheque_id=cheque2, clear_date="2026-07-20")
        raise AssertionError("پاس چک برگشتی باید رد شود.")
    except TreasuryError:
        pass
    print("OK مرحله ۴: چرخه برگشت چک (واگذاری -> برگشت -> اعاده مطالبات) تایید شد.")

    # -------------------------------------------------------------
    # Step 5: چک صادره و ابطال آن
    # -------------------------------------------------------------
    issue_res = treasury.issue_cheque(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        payee_detail_id=supp_id,
        sayyad_id="7123456789012400",
        cheque_number="CHK-9001",
        bank_name="بانک ملت",
        bank_account_detail_id=bank_id,
        due_date="2026-08-20",
        amount=20_000_000,
        issue_date="2026-05-10"
    )
    assert issue_res["status"] == "issued"
    tb5 = {r["code"]: r for r in reports.get_trial_balance(tenant_id)}
    assert tb5["4010"]["balance_debit"] == 20_000_000
    assert tb5["4020"]["balance_credit"] == 20_000_000

    cancel_res = treasury.cancel_cheque(issue_res["cheque_id"], cancel_date="2026-05-11")
    assert cancel_res["status"] == "cancelled"
    tb6 = {r["code"]: r for r in reports.get_trial_balance(tenant_id)}
    assert tb6["4010"]["balance_debit"] == 0, "ابطال چک باید سند صدور را وارونه کند."
    assert tb6["4020"]["balance_credit"] == 0
    print("OK مرحله ۵: صدور و ابطال چک صادره با وارونه‌سازی خودکار سند تایید شد.")

    # -------------------------------------------------------------
    # Step 6: آزمون راس‌گیری چک‌های بازار (Bazaar Ras Calculation)
    # چک ۱: ۱۰ میلیون (۳۰ روزه) / چک ۲: ۳۰ میلیون (۹۰ روزه)
    # میانگین وزنی روزها: (10*30 + 30*90) / 40 = 75 روز
    # -------------------------------------------------------------
    print("\n--------------------------------------------------")
    print("آزمون الگوریتم راس‌گیری هوشمند چک‌ها (Ras Calculation):")
    print("--------------------------------------------------")
    test_cheques = [
        {"amount": 10_000_000, "due_date": "2026-05-01"},
        {"amount": 30_000_000, "due_date": "2026-06-30"}
    ]
    ras_info = treasury.calculate_ras(test_cheques, base_date_str="2026-04-01")
    print(f"مبنای تاریخ فاکتور: {ras_info['base_date']}")
    print(f"مجموع مبلغ چک‌ها:  {ras_info['total_amount']:,.0f} تومان")
    print(f"میانگین وزنی سررسید: {ras_info['weighted_average_days']} روز")
    print(f"تاریخ دقیق راس چک‌ها: {ras_info['ras_due_date']}")

    assert abs(ras_info["weighted_average_days"] - 75.0) < 0.5, f"خطای راس‌گیری: {ras_info['weighted_average_days']}"
    print("OK فرمول راس‌گیری بازار با دقت ۱۰۰٪ راستی‌آزمایی شد!")

    # -------------------------------------------------------------
    # Step 7: فهرست چک‌ها و ترازنامه نهایی
    # -------------------------------------------------------------
    cheques = treasury.list_cheques(tenant_id)
    statuses = {c["cheque_number"]: c["status"] for c in cheques}
    assert statuses["CHK-8801"] == "cleared"
    assert statuses["CHK-8802"] == "bounced"
    assert statuses["CHK-9001"] == "cancelled"

    bs = reports.get_balance_sheet(tenant_id, fy_id)
    assert bs["is_balanced"], "ترازنامه پس از چرخه چک‌ها نامتوازن است!"

    print("\n==================================================")
    print("ALL TREASURY & CHEQUE TESTS PASSED!")
    print("==================================================")


if __name__ == "__main__":
    test_treasury_lifecycle_and_ras()
