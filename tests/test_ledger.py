import sys
import os
import tempfile
from pathlib import Path

# Add core to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ledger import (
    AccountingError,
    ArbinLedger,
    FiscalYearClosedError,
    ImmutableEntryError,
    UnbalancedJournalEntryError,
)
from reports import ArbinReports


def _temp_db(name: str) -> str:
    return os.path.join(tempfile.gettempdir(), name)


def test_full_accounting_cycle():
    print("==================================================")
    print(" ARBIN ACCOUNTING ENGINE (آربین) - VERIFICATION TEST")
    print("==================================================")

    db_test_path = _temp_db("arbin_test.db")
    if os.path.exists(db_test_path):
        os.remove(db_test_path)

    ledger = ArbinLedger(db_path=db_test_path)
    reports = ArbinReports(ledger)

    # 1. Create Tenant (شرکت فناوران آربین)
    tenant_id = ledger.create_tenant(
        name="شرکت فناوری مالی آربین پارس",
        national_id="14009988776",
        currency="IRT"  # تومان
    )
    print(f"OK شرکت با موفقیت ساخته شد. Tenant ID: {tenant_id}")

    # 2. Create Fiscal Year (سال مالی ۱۴۰۵)
    fy_id = ledger.create_fiscal_year(
        tenant_id=tenant_id,
        title="سال مالی ۱۴۰۵",
        start_date="2026-03-21",
        end_date="2027-03-20"
    )
    print(f"OK سال مالی فعال شد. FY ID: {fy_id}")

    # 3. Seed Iranian Standard Chart of Accounts (کدینگ معیار ۴ رقمی)
    ledger.seed_standard_accounts(tenant_id)
    print("OK کدینگ استاندارد حسابداری ایران (گروه، کل، معین) با موفقیت تزریق شد.")

    # 4. Create Floating Sub-Ledgers (تفصیلی شناور)
    cust_id = ledger.create_detail_account(tenant_id, "4001", "فروشگاه آنلاین زنجیره‌ای", "customer", phone="09121112233")
    emp_id = ledger.create_detail_account(tenant_id, "9001", "آریا کمالی (مدیر فنی)", "personnel")
    bank_id = ledger.create_detail_account(tenant_id, "100201", "بانک ملت - حساب تجاری اصلی", "bank")
    assert cust_id and emp_id and bank_id
    print("OK حساب‌های تفصیلی اشخاص و بانک‌ها ثبت شدند.")

    # -------------------------------------------------------------
    # Test Transaction 1: سرمایه‌گذاری اولیه (۵۰۰ میلیون تومان)
    # بانک (بدهکار) / سرمایه اولیه شرکا (بستانکار)
    # -------------------------------------------------------------
    tx1_id = ledger.record_journal_entry(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        entry_date="2026-04-01",
        description="سرمایه‌گذاری نقدی اولیه سهامداران در شرکت",
        items=[
            {"account_code": "1010", "detail_code": "100201", "description": "واریز به حساب بانک ملت", "debit": 500_000_000, "credit": 0},
            {"account_code": "5010", "detail_code": None, "description": "سرمایه ثبت شده نقدی شرکا", "debit": 0, "credit": 500_000_000}
        ]
    )
    print("OK سند ۱ (سرمایه اولیه): ثبت موفق (مبلغ: ۵۰۰,۰۰۰,۰۰۰ تومان)")

    # -------------------------------------------------------------
    # Test Transaction 2: پرداخت اجاره دفتر (۲۰ میلیون تومان)
    # -------------------------------------------------------------
    ledger.record_journal_entry(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        entry_date="2026-04-05",
        description="پرداخت اجاره ماهانه دفتر کار مرکزی",
        items=[
            {"account_code": "7210", "detail_code": None, "description": "هزینه اجاره فروردین ماه", "debit": 20_000_000, "credit": 0},
            {"account_code": "1010", "detail_code": "100201", "description": "پرداخت از حساب بانک ملت", "debit": 0, "credit": 20_000_000}
        ]
    )
    print("OK سند ۲ (هزینه اجاره): ثبت موفق (مبلغ: ۲۰,۰۰۰,۰۰۰ تومان)")

    # -------------------------------------------------------------
    # Test Transaction 3: فروش لایسنس نرم‌افزار به صورت نسیه (۱۵۰ میلیون تومان)
    # حساب‌های دریافتنی تجاری / مشتری (بدهکار) / درآمد خدمات نرم‌افزار (بستانکار)
    # -------------------------------------------------------------
    ledger.record_journal_entry(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        entry_date="2026-04-10",
        description="فروش لایسنس سازمانی نرم‌افزار آربین به مشتری",
        items=[
            {"account_code": "1210", "detail_code": "4001", "description": "فروش نسیه طبق فاکتور شماره ۱۰۰۱", "debit": 150_000_000, "credit": 0},
            {"account_code": "6020", "detail_code": None, "description": "درآمد ارائه خدمات نرم‌افزاری", "debit": 0, "credit": 150_000_000}
        ]
    )
    print("OK سند ۳ (فروش لایسنس): ثبت موفق (مبلغ: ۱۵۰,۰۰۰,۰۰۰ تومان)")

    # -------------------------------------------------------------
    # Test Transaction 4: وصول مطالبات از مشتری (۱۰۰ میلیون تومان)
    # -------------------------------------------------------------
    ledger.record_journal_entry(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        entry_date="2026-04-15",
        description="وصول چک/واریز نقد مشتری به حساب بانک",
        items=[
            {"account_code": "1010", "detail_code": "100201", "description": "وصول واریزی مشتری", "debit": 100_000_000, "credit": 0},
            {"account_code": "1210", "detail_code": "4001", "description": "تسویه بخشی از فاکتور ۱۰۰۱", "debit": 0, "credit": 100_000_000}
        ]
    )
    print("OK سند ۴ (وصول وجه): ثبت موفق (مبلغ: ۱۰۰,۰۰۰,۰۰۰ تومان)")

    # -------------------------------------------------------------
    # Test Transaction 5: حقوق و دستمزد پرسنل (۳۰ میلیون تومان)
    # -------------------------------------------------------------
    ledger.record_journal_entry(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        entry_date="2026-04-20",
        description="پرداخت حقوق فروردین ماه پرسنل",
        items=[
            {"account_code": "7110", "detail_code": "9001", "description": "حقوق پایه آریا کمالی", "debit": 30_000_000, "credit": 0},
            {"account_code": "1010", "detail_code": "100201", "description": "واریز پایا از بانک ملت", "debit": 0, "credit": 30_000_000}
        ]
    )
    print("OK سند ۵ (حقوق پرسنل): ثبت موفق (مبلغ: ۳۰,۰۰۰,۰۰۰ تومان)")

    # -------------------------------------------------------------
    # Test Transaction 6: آزمون جلوگیری از سند ناهمتراز (Negative Test)
    # -------------------------------------------------------------
    imbalance_passed = False
    try:
        ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fy_id,
            entry_date="2026-04-22",
            description="سند خراب و نامتوازن تستی",
            items=[
                {"account_code": "1010", "detail_code": None, "description": "بدهکار", "debit": 10_000_000, "credit": 0},
                {"account_code": "6010", "detail_code": None, "description": "بستانکار کمتر", "debit": 0, "credit": 9_000_000}
            ]
        )
    except UnbalancedJournalEntryError as e:
        imbalance_passed = True
        print(f"OK سیستم امنیتی سند ناهمتراز کار کرد: {e}")

    assert imbalance_passed, "خطا! سیستم سند ناهمتراز را رد نکرد!"

    # -------------------------------------------------------------
    # 7. وضعیت پیش‌نویس: سند draft در گزارش‌ها نمی‌آید و قابل حذف است
    # -------------------------------------------------------------
    draft_id = ledger.record_journal_entry(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        entry_date="2026-04-25",
        description="سند آزمونی پیش‌نویس",
        items=[
            {"account_code": "1010", "detail_code": None, "description": "بدهکار", "debit": 1_000_000, "credit": 0},
            {"account_code": "6010", "detail_code": None, "description": "بستانکار", "debit": 0, "credit": 1_000_000}
        ],
        status="draft",
    )
    entries_visible = ledger.list_journal_entries(tenant_id, fiscal_year_id=fy_id)
    assert all(e["id"] != draft_id for e in entries_visible), "سند پیش‌نویس نباید در فهرست عادی بیاید."
    entries_with_drafts = ledger.list_journal_entries(
        tenant_id, fiscal_year_id=fy_id, include_drafts=True
    )
    assert any(e["id"] == draft_id for e in entries_with_drafts)
    assert ledger.delete_journal_entry(tenant_id, draft_id) is True

    # -------------------------------------------------------------
    # 8. چرخه وضعیت سند: approved -> permanent و جلوگیری از بازگشت
    # -------------------------------------------------------------
    updated = ledger.update_entry_status(tenant_id, tx1_id, "permanent")
    assert updated["status"] == "permanent"
    try:
        ledger.update_entry_status(tenant_id, tx1_id, "approved")
        raise AssertionError("بازگشت وضعیت از permanent به approved باید رد شود.")
    except (ImmutableEntryError, AccountingError):
        pass
    try:
        ledger.delete_journal_entry(tenant_id, tx1_id)
        raise AssertionError("حذف سند قطعی باید رد شود.")
    except ImmutableEntryError:
        pass

    # -------------------------------------------------------------
    # Financial Reports Verification
    # -------------------------------------------------------------
    print("\n--------------------------------------------------")
    print("1. تراز آزمایشی ۴ ستونی (Trial Balance):")
    print("--------------------------------------------------")
    tb = reports.get_trial_balance(tenant_id, level="subsidiary", fiscal_year_id=fy_id)
    total_tb_debit = sum(row["total_debit"] for row in tb)
    total_tb_credit = sum(row["total_credit"] for row in tb)
    total_bal_debit = sum(row["balance_debit"] for row in tb)
    total_bal_credit = sum(row["balance_credit"] for row in tb)

    for row in tb:
        if row["total_debit"] > 0 or row["total_credit"] > 0:
            print(f"[{row['code']:<6}] {row['title']:<30} | گردش بد: {row['total_debit']:>12,.0f} | گردش بس: {row['total_credit']:>12,.0f} | مانده: {row['balance_debit'] or row['balance_credit']:>12,.0f}")

    print("--------------------------------------------------")
    print(f"جمع تراز گردش: بدهکار={total_tb_debit:,.0f} | بستانکار={total_tb_credit:,.0f}")
    print(f"جمع تراز مانده: بدهکار={total_bal_debit:,.0f} | بستانکار={total_bal_credit:,.0f}")
    assert total_tb_debit == total_tb_credit, "خطای عدم توازن در تراز آزمایشی گردش!"
    assert total_bal_debit == total_bal_credit, "خطای عدم توازن در تراز آزمایشی مانده!"
    print("OK تراز آزمایشی کاملاً متوازن و دقیق است!")

    # -------------------------------------------------------------
    # Income Statement: Revenue 150M - Rent 20M - Salaries 30M = 100M
    # -------------------------------------------------------------
    print("\n--------------------------------------------------")
    print("2. صورت سود و زیان (Income Statement):")
    print("--------------------------------------------------")
    inc = reports.get_income_statement(tenant_id, fy_id)
    print(f"کل درآمدهای عملیاتی: {inc['total_revenue']:>15,.0f} تومان")
    print(f"بهای تمام شده:       {inc['total_cogs']:>15,.0f} تومان")
    print(f"سود ناخالص:          {inc['gross_profit']:>15,.0f} تومان")
    for exp in inc["operating_expenses"]:
        print(f"  - {exp['title']:<25}: {exp['amount']:>12,.0f} تومان")
    print(f"مجموع هزینه‌ها:      {inc['total_expenses']:>15,.0f} تومان")
    print(f"💰 سود خالص دوره:     {inc['net_profit']:>15,.0f} تومان")
    assert inc["total_revenue"] == 150_000_000
    assert inc["total_expenses"] == 50_000_000
    assert inc["net_profit"] == 100_000_000
    print("OK محاسبات سود و زیان کاملاً دقیق است!")

    # -------------------------------------------------------------
    # Balance Sheet: Assets 600M = Liabilities 0 + Equity 600M
    # -------------------------------------------------------------
    print("\n--------------------------------------------------")
    print("3. ترازنامه مالی (Balance Sheet):")
    print("--------------------------------------------------")
    bs = reports.get_balance_sheet(tenant_id, fy_id)
    print(f"جمع کل دارایی‌ها: {bs['total_assets']:>15,.0f} تومان")
    print(f"جمع حقوق سهامداران و بدهی‌ها: {bs['total_equity_and_liabilities']:>15,.0f} تومان")
    print(f"وضعیت تعادل ترازنامه: {'متوازن (BALANCED)' if bs['is_balanced'] else 'ناهمتراز (ERROR)'}")
    assert bs["is_balanced"], "خطای عدم تعادل ترازنامه!"
    assert bs["total_assets"] == 600_000_000
    assert bs["total_equity_and_liabilities"] == 600_000_000
    assert bs["current_year_profit"] == 100_000_000

    print("\n==================================================")
    print("ALL TESTS PASSED! ARBIN LEDGER IS ROCK-SOLID!")
    print("==================================================")


def test_year_end_closing_and_opening():
    """بستن سال مالی (اختتامیه) و انتقال مانده به سال جدید (افتتاحیه)."""
    db_test_path = _temp_db("arbin_test_close.db")
    if os.path.exists(db_test_path):
        os.remove(db_test_path)

    ledger = ArbinLedger(db_path=db_test_path)
    tenant_id = ledger.create_tenant("شرکت تست بستن سال", "14001112223", "IRT")
    fy1 = ledger.create_fiscal_year(tenant_id, "سال مالی ۱۴۰۵", "2026-03-21", "2027-03-20")
    fy2 = ledger.create_fiscal_year(tenant_id, "سال مالی ۱۴۰۶", "2027-03-21", "2028-03-20")
    ledger.seed_standard_accounts(tenant_id)

    ledger.record_journal_entry(
        tenant_id=tenant_id,
        fiscal_year_id=fy1,
        entry_date="2026-04-01",
        description="سرمایه اولیه",
        items=[
            {"account_code": "1010", "description": "بانک", "debit": 40_000_000, "credit": 0},
            {"account_code": "5010", "description": "سرمایه", "debit": 0, "credit": 40_000_000},
        ],
    )
    ledger.record_journal_entry(
        tenant_id=tenant_id,
        fiscal_year_id=fy1,
        entry_date="2026-04-02",
        description="فروش نقدی",
        items=[
            {"account_code": "1010", "description": "بانک", "debit": 60_000_000, "credit": 0},
            {"account_code": "6010", "description": "درآمد فروش", "debit": 0, "credit": 60_000_000},
        ],
    )
    ledger.record_journal_entry(
        tenant_id=tenant_id,
        fiscal_year_id=fy1,
        entry_date="2026-04-03",
        description="پرداخت اجاره",
        items=[
            {"account_code": "7210", "description": "اجاره", "debit": 25_000_000, "credit": 0},
            {"account_code": "1010", "description": "بانک", "debit": 0, "credit": 25_000_000},
        ],
    )

    # سال باز است و سند قابل ثبت
    with ledger.get_connection() as conn:
        closed = conn.execute(
            "SELECT is_closed FROM fiscal_years WHERE id = ?", (fy1,)
        ).fetchone()
    assert int(closed["is_closed"] or 0) == 0

    closing = ledger.close_fiscal_year(tenant_id, fy1)
    assert closing["net_income"] == 35_000_000
    assert len(closing["entry_ids"]) >= 1

    # سال بسته شد و دیگر نمی‌توان سند ثبت کرد
    with ledger.get_connection() as conn:
        closed = conn.execute(
            "SELECT is_closed FROM fiscal_years WHERE id = ?", (fy1,)
        ).fetchone()
    assert int(closed["is_closed"]) == 1
    try:
        ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fy1,
            entry_date="2026-04-04",
            description="سند پس از بستن سال",
            items=[
                {"account_code": "1010", "description": "بانک", "debit": 1_000_000, "credit": 0},
                {"account_code": "6010", "description": "درآمد", "debit": 0, "credit": 1_000_000},
            ],
        )
        raise AssertionError("ثبت سند در سال مالی بسته باید رد شود.")
    except FiscalYearClosedError:
        pass

    # بستن مجدد باید رد شود
    try:
        ledger.close_fiscal_year(tenant_id, fy1)
        raise AssertionError("بستن مجدد سال مالی باید رد شود.")
    except FiscalYearClosedError:
        pass

    # مانده حساب‌های دائمی صفر شده و سود به سود انباشته رفته است
    with ledger.get_connection() as conn:
        rev = conn.execute(
            """
            SELECT COALESCE(SUM(ji.debit - ji.credit), 0) FROM journal_items ji
            JOIN accounts a ON a.id = ji.account_id
            JOIN journal_entries je ON je.id = ji.entry_id
            WHERE a.tenant_id = ? AND a.code = '6010' AND je.fiscal_year_id = ?
              AND je.status != 'draft'
            """,
            (tenant_id, fy1),
        ).fetchone()
        exp = conn.execute(
            """
            SELECT COALESCE(SUM(ji.debit - ji.credit), 0) FROM journal_items ji
            JOIN accounts a ON a.id = ji.account_id
            JOIN journal_entries je ON je.id = ji.entry_id
            WHERE a.tenant_id = ? AND a.code = '7210' AND je.fiscal_year_id = ?
              AND je.status != 'draft'
            """,
            (tenant_id, fy1),
        ).fetchone()
        ret = conn.execute(
            """
            SELECT COALESCE(SUM(ji.credit - ji.debit), 0) FROM journal_items ji
            JOIN accounts a ON a.id = ji.account_id
            JOIN journal_entries je ON je.id = ji.entry_id
            WHERE a.tenant_id = ? AND a.code = '5110' AND je.fiscal_year_id = ?
              AND je.status != 'draft'
            """,
            (tenant_id, fy1),
        ).fetchone()
    assert abs(float(rev[0])) < 0.01, "درآمد باید پس از اختتامیه صفر شود."
    assert abs(float(exp[0])) < 0.01, "هزینه باید پس از اختتامیه صفر شود."
    assert abs(float(ret[0]) - 35_000_000) < 0.01, "سود باید به سود انباشته منتقل شود."

    # سند افتتاحیه سال جدید
    opening = ledger.create_opening_entry(tenant_id, fy2)
    assert opening.get("entry_id"), "سند افتتاحیه سال جدید ثبت نشد."
    with ledger.get_connection() as conn:
        total_debit = conn.execute(
            """
            SELECT COALESCE(SUM(ji.debit), 0) FROM journal_items ji
            JOIN journal_entries je ON je.id = ji.entry_id
            WHERE je.id = ? AND je.status = 'opening_entry'
            """,
            (opening["entry_id"],),
        ).fetchone()
        bank_open = conn.execute(
            """
            SELECT COALESCE(SUM(ji.debit - ji.credit), 0) FROM journal_items ji
            JOIN accounts a ON a.id = ji.account_id
            JOIN journal_entries je ON je.id = ji.entry_id
            WHERE a.tenant_id = ? AND a.code = '1010' AND je.fiscal_year_id = ?
              AND je.status = 'opening_entry'
            """,
            (tenant_id, fy2),
        ).fetchone()
    assert float(total_debit[0]) > 0
    assert abs(float(bank_open[0]) - 75_000_000) < 0.01

    # ترازنامه سال جدید متوازن است
    reports = ArbinReports(ledger)
    bs = reports.get_balance_sheet(tenant_id, fy2)
    assert bs["is_balanced"], "ترازنامه سال جدید پس از افتتاحیه نامتوازن است!"
    assert bs["total_assets"] == 75_000_000


if __name__ == "__main__":
    test_full_accounting_cycle()
    test_year_end_closing_and_opening()
