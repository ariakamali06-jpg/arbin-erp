import sys
import os
import tempfile
from decimal import Decimal
from pathlib import Path

# Add workspace to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ledger import ArbinLedger
from reports import ArbinReports
from payroll import ArbinPayroll, PayrollError


def _temp_db(name: str) -> str:
    return os.path.join(tempfile.gettempdir(), name)


def test_full_payroll_cycle():
    print("==================================================")
    print("ARBIN PAYROLL & STATUTORY LABOR ENGINE - TEST")
    print("==================================================")

    db_test_path = _temp_db("arbin_payroll_test.db")
    if os.path.exists(db_test_path):
        os.remove(db_test_path)

    ledger = ArbinLedger(db_path=db_test_path)
    reports = ArbinReports(ledger)
    payroll = ArbinPayroll(ledger)

    # 1. Setup Tenant & Accounts
    tenant_id = ledger.create_tenant(name="شرکت فناوری مالی آربین پارس", currency="IRT")
    fy_id = ledger.create_fiscal_year(tenant_id, "سال مالی ۱۴۰۵", "2026-03-21", "2027-03-20")
    ledger.seed_standard_accounts(tenant_id)

    # -------------------------------------------------------------
    # 0. ماده ۸۴ قانون مالیات‌های مستقیم (پلکانی ماهانه)
    # -------------------------------------------------------------
    assert payroll.calculate_progressive_tax(Decimal("0")) == Decimal("0")
    assert payroll.calculate_progressive_tax(Decimal("10000000")) == Decimal("1000000.00")
    assert payroll.calculate_progressive_tax(Decimal("15000000")) == Decimal("1750000.00")
    assert payroll.calculate_progressive_tax(Decimal("30000000")) == Decimal("5000000.00")
    brackets = payroll.tax_brackets()
    assert len(brackets) == 7
    print("OK نردبان مالیات ماده ۸۴ (۱۰٪ تا ۴۰٪) تایید شد.")

    # سقف معافیت ماهانه
    slip = ArbinPayroll.calculate_employee_slip(
        Decimal("100000000"), Decimal("9000000"), Decimal("14000000"),
        Decimal("0"), 30, 0.0,
    )
    assert slip["tax_exemption_ceiling"] == 105_000_000
    # بیمه ۷٪ فقط روی پایه + بن (۱۱۴ میلیون) اعمال می‌شود
    assert slip["employee_insurance_7pct"] == 7_980_000
    # درآمد مشمول مالیات = ۱۲۳M - ۷.۹۸M - ۱۰۵M معافیت = ۱۰,۰۲۰,۰۰۰
    assert slip["taxable_income"] == 10_020_000
    # مالیات پلکانی: ۱۰M × ۱۰٪ + ۲۰,۰۰۰ × ۱۵٪ = ۱,۰۰۳,۰۰۰
    assert slip["income_tax"] == 1_003_000
    assert slip["net_payable"] == 114_017_000

    # 2. Register Employees
    emp1 = payroll.register_employee(
        tenant_id=tenant_id,
        national_id="0011223344",
        full_name="آریا کمالی",
        job_title="مدیر ارشد مهندسی نرم‌افزار",
        base_monthly_salary=100_000_000,
        housing_allowance=9_000_000,
        grocery_allowance=14_000_000,
        child_count=0,
        bank_shaba="IR120120000000001234567890"
    )
    print(f"OK کارمند ۱ ثبت شد: {emp1['full_name']} (تفصیلی: {emp1['sub_ledger_code']})")

    emp2 = payroll.register_employee(
        tenant_id=tenant_id,
        national_id="0022334455",
        full_name="بنیامین رضایی",
        job_title="مدیر محصول",
        base_monthly_salary=80_000_000,
        housing_allowance=9_000_000,
        grocery_allowance=14_000_000,
        child_count=1,
        bank_shaba="IR980180000000009876543210"
    )
    assert emp2["sub_ledger_id"] == emp2["detail_id"]
    employees = payroll.list_employees(tenant_id)
    assert len(employees) == 2

    # ثبت مجدد با کد ملی تکراری باید خطا بدهد
    try:
        payroll.register_employee(
            tenant_id=tenant_id,
            national_id="0011223344",
            full_name="آریا کمالی تکراری",
            job_title="کارشناس",
            base_monthly_salary=50_000_000,
        )
        raise AssertionError("ثبت مجدد کد ملی تکراری باید رد شود.")
    except PayrollError:
        pass

    # 3. Process Monthly Payroll for Farvardin 1405
    run_res = payroll.process_monthly_payroll(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        month_label="فروردین ۱۴۰۵",
        run_date="2026-04-25",
        records=[
            {"employee_id": emp1["employee_id"], "worked_days": 30, "overtime_hours": 10},
            {"employee_id": emp2["employee_id"], "worked_days": 30, "overtime_hours": 0}
        ]
    )

    print("\nOK لیست حقوق و دستمزد فروردین با موفقیت محاسبه شد:")
    print(f"  - مجموع حقوق ناخالص پرسنل: {run_res['total_gross']:,.0f} تومان")
    print(f"  - کل بیمه ۳۰٪ (۷٪ کارمند + ۲۳٪ کارفرما): {run_res['total_insurance_30pct']:,.0f} تومان")
    print(f"  - کل مالیات تکلیفی حقوق: {run_res['total_tax']:,.0f} تومان")
    print(f"  - خالص کل پرداختی به پرسنل: {run_res['total_net_payable']:,.0f} تومان")
    print(f"  - شناسه سند دوبل صادر شده: {run_res['journal_entry_id']}")

    assert run_res["employees_count"] == 2
    assert run_res["total_tax"] > 0, "مالیات تکلیفی باید برای پرسنل بالای سقف معافیت محاسبه شود."

    # 4. Verify Double-Entry Accounting Balances in General Ledger
    tb = {row["code"]: row for row in reports.get_trial_balance(tenant_id, fiscal_year_id=fy_id)}

    # هزینه‌ها: 7110 حقوق، 7120 بیمه کارفرما، 7130 مزایا
    assert tb["7110"]["balance_debit"] > 0, "هزینه حقوق پایه باید بدهکار باشد"
    assert tb["7120"]["balance_debit"] > 0, "هزینه بیمه کارفرما باید بدهکار باشد"
    assert tb["7130"]["balance_debit"] > 0, "هزینه مزایا باید بدهکار باشد"
    # بدهی‌ها: 4040 خالص حقوق، 4050 بیمه ۳۰٪، 4060 مالیات تکلیفی
    assert tb["4040"]["balance_credit"] == run_res["total_net_payable"], "خالص حقوق پرداختنی مغایرت دارد"
    assert tb["4050"]["balance_credit"] == run_res["total_insurance_30pct"], "بیمه پرداختنی ۳۰٪ مغایرت دارد"
    assert tb["4060"]["balance_credit"] == run_res["total_tax"], "مالیات تکلیفی مغایرت دارد"

    total_debit = sum(r["total_debit"] for r in tb.values())
    total_credit = sum(r["total_credit"] for r in tb.values())
    assert abs(total_debit - total_credit) < 0.01, "سند حقوق باید متوازن باشد."

    print("\n--------------------------------------------------")
    print("مانده‌های تراز آزمایشی حقوق و دستمزد تایید شدند:")
    print(f"  - حساب ۷۱۱۰ (هزینه حقوق پایه): {tb['7110']['balance_debit']:,.0f} تومان")
    print(f"  - حساب ۷۱۲۰ (بیمه سهم کارفرما): {tb['7120']['balance_debit']:,.0f} تومان")
    print(f"  - حساب ۷۱۳۰ (هزینه مزایا و رفاهی): {tb['7130']['balance_debit']:,.0f} تومان")
    print(f"  - حساب ۴۰۴۰ (حقوق خالص پرداختنی): {tb['4040']['balance_credit']:,.0f} تومان")
    print(f"  - حساب ۴۰۵۰ (بدهی به تأمین اجتماعی ۳۰٪): {tb['4050']['balance_credit']:,.0f} تومان")
    print(f"  - حساب ۴۰۶۰ (بدهی مالیات به دارایی): {tb['4060']['balance_credit']:,.0f} تومان")

    # 5. Verify individual payslips + breakdown
    slips = payroll.get_payslips(run_res["payroll_run_id"])
    assert len(slips) == 2
    for s in slips:
        assert "breakdown" in s
        assert s["breakdown"]["tax_exemption_ceiling"] == 105_000_000
        assert s["net_payable"] == s["breakdown"]["net_payable"]

    # 6. Export Bank Paya Diskette
    paya = payroll.export_bank_payment_paya(run_res["payroll_run_id"])
    print("\n--------------------------------------------------")
    print(f"دیسکت پرداخت گروهی بانک پایا (تعداد واریز: {len(paya)} نفر):")
    print("--------------------------------------------------")
    for p in paya:
        print(f"  - نام: {p['name']:<18} | شبا: {p['shaba']} | مبلغ: {p['amount']:>12,.0f} تومان")
    assert len(paya) == 2
    assert abs(sum(p["amount"] for p in paya) - run_res["total_net_payable"]) < 0.01

    runs = payroll.list_payroll_runs(tenant_id)
    assert len(runs) == 1
    assert runs[0]["id"] == run_res["payroll_run_id"]

    print("\n==================================================")
    print("ALL PAYROLL & LABOR LAW TESTS PASSED!")
    print("==================================================")


if __name__ == "__main__":
    test_full_payroll_cycle()
