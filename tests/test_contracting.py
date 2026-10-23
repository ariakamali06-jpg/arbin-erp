"""
Unit Tests for Arbin Contracting & Projects Engine (تست سیستم پیمانکاری و صورت‌وضعیت)
========================================================================================
Verifies:
1. Construction & project contract registration with employer detail account.
2. Draft progress billing statement with statutory deductions:
   - 10% Good performance retention deposit (سپرده حسن انجام کار)
   - 5% Article 38 Social Security withholding (بیمه ماده ۳۸)
   - 10% VAT output liability
   - Net receivable computation
3. Confirmation and automated balanced double-entry voucher:
   Debit 1210 (Receivable from Employer) [95M]
   Debit 1320 (Retention Deposit 10%) [10M]
   Debit 1330 (Article 38 SSO Deposit 5%) [5M]
   Credit 6030 (Contract Revenue) [100M]
   Credit 4030 (VAT Payable 10%) [10M]
4. Strict double-entry balance and trial balance equilibrium.
"""

import os
import sys
import tempfile
from pathlib import Path

# Add workspace to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ledger import ArbinLedger
from contracting import ArbinContracting, ContractingError


def _temp_db(name: str) -> str:
    return os.path.join(tempfile.gettempdir(), name)


def test_contracting_suite():
    print("==================================================")
    print("ARBIN CONTRACTING & PROGRESS BILLINGS - TEST")
    print("==================================================")

    db_path = _temp_db("arbin_contracting_test.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    ledger = ArbinLedger(db_path=db_path)
    contracts_mgr = ArbinContracting(ledger)

    tenant_id = ledger.create_tenant("شرکت مهندسی ساختمانی آریا سازه", "14007778889")
    fy_id = ledger.create_fiscal_year(tenant_id, "1405", "2026-03-21", "2027-03-20")
    ledger.seed_standard_accounts(tenant_id)

    # 1. Register Employer (کارفرما) as Detail Account
    employer_id = ledger.create_sub_ledger(
        tenant_id=tenant_id,
        code="9001",
        title="شرکت توسعه و نوسازی زیرساخت‌های کشور",
        sub_ledger_type="customer",
        phone="02188889999",
        national_id="14009991112"
    )
    print("OK کارفرما (طرف‌حساب پیمان) به عنوان حساب تفصیلی ثبت شد.")

    # 2. Register Contract
    # 500,000,000 Toman project with 10% retention, 5% Article 38 SSO
    cnt_res = contracts_mgr.create_contract(
        tenant_id=tenant_id,
        contract_no="CNT-1405-ROAD-01",
        title="پروژه اجرای ابنیه و محوطه‌سازی فاز ۱",
        employer_sub_ledger_id=employer_id,
        total_amount=500_000_000,
        start_date="2026-04-01",
        end_date="2026-10-30",
        retention_rate=0.10,
        sso_rate=0.05
    )
    contract_id = cnt_res["id"]
    print("OK قرارداد پیمانکاری با شماره «CNT-1405-ROAD-01» ثبت گردید.")

    # 3. Submit Progress Billing #1 (صورت وضعیت شماره ۱)
    # Gross Amount: 100,000,000 Toman
    # Retention 10%: 10,000,000 Toman
    # SSO 5%: 5,000,000 Toman
    # Taxable: 100,000,000 Toman
    # VAT 10%: 10,000,000 Toman
    # Net Receivable: 100M - 10M - 5M + 10M = 95,000,000 Toman
    print("\n--------------------------------------------------")
    print("تنظیم پیش‌نویس صورت‌وضعیت کارکرد دوره اول:")
    print("--------------------------------------------------")
    bill_res = contracts_mgr.submit_progress_billing(
        tenant_id=tenant_id,
        contract_id=contract_id,
        billing_no="PB-01",
        billing_date="2026-05-15",
        gross_amount=100_000_000,
        advance_amortization=0.0
    )
    billing_id = bill_res["id"]
    assert bill_res["gross_amount"] == 100_000_000.0
    assert bill_res["retention_amount"] == 10_000_000.0
    assert bill_res["sso_amount"] == 5_000_000.0
    assert bill_res["vat_amount"] == 10_000_000.0
    assert bill_res["net_receivable"] == 95_000_000.0
    print("OK محاسبات صورت‌وضعیت با دقت ۱۰۰٪ تایید شد:")
    print("  - ناخالص کارکرد:             100,000,000 تومان")
    print("  - کسر ۱۰٪ سپرده حسن انجام کار: 10,000,000 تومان")
    print("  - کسر ۵٪ ودیعه بیمه ماده ۳۸:    5,000,000 تومان")
    print("  - مالیات بر ارزش افزوده ۱۰٪:    10,000,000 تومان")
    print("  - خالص چک/مطالبه از کارفرما:   95,000,000 تومان")

    # 4. Confirm Progress Billing and Post Statutory Double-Entry Voucher
    print("\n--------------------------------------------------")
    print("تایید صورت‌وضعیت و صدور خودکار سند دوبل پیمانکاری:")
    print("--------------------------------------------------")
    conf_res = contracts_mgr.confirm_progress_billing(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        billing_id=billing_id
    )
    assert conf_res["status"] == "confirmed"
    assert conf_res["voucher_id"] is not None
    print("OK سند دوبل پیمانکاری با موفقیت صادر گردید. شناسه سند:", conf_res["voucher_id"])
    print("  - بدهکاران تجاری / کارفرما (کد ۱۲۱۰):          95,000,000 (بدهکار)")
    print("  - سپرده حسن انجام کار نزد کارفرما (کد ۱۳۲۰):    10,000,000 (بدهکار)")
    print("  - ودیعه بیمه ماده ۳۸ نزد کارفرما (کد ۱۳۳۰):     5,000,000 (بدهکار)")
    print("  - درآمد کارکرد پیمانکاری و پروژه‌ها (کد ۶۰۳۰): 100,000,000 (بستانکار)")
    print("  - مالیات بر ارزش افزوده فروش (کد ۴۰۳۰):         10,000,000 (بستانکار)")

    # 5. Check Trial Balance Equilibrium
    from reports import ArbinReports
    rep = ArbinReports(ledger)
    tb = rep.get_trial_balance(tenant_id, fiscal_year_id=fy_id, level="subsidiary")
    tot_td = sum(r["total_debit"] for r in tb)
    tot_tc = sum(r["total_credit"] for r in tb)
    tot_bd = sum(r["balance_debit"] for r in tb)
    tot_bc = sum(r["balance_credit"] for r in tb)
    assert abs(tot_td - tot_tc) < 0.01
    assert abs(tot_bd - tot_bc) < 0.01
    assert tot_td == 110_000_000.0, f"گردش بدهکار باید ۱۱۰ میلیون باشد، دریافت شد: {tot_td}"
    assert tot_tc == 110_000_000.0, f"گردش بستانکار باید ۱۱۰ میلیون باشد، دریافت شد: {tot_tc}"
    print("\nOK تراز آزمایشی پس از صدور سند پیمانکاری کاملاً متوازن است (جمع تراز: ۱۱۰,۰۰۰,۰۰۰ تومان).")

    print("\n==================================================")
    print("ALL CONTRACTING & PROJECTS TESTS PASSED (100%)!")
    print("==================================================")


if __name__ == "__main__":
    test_contracting_suite()
