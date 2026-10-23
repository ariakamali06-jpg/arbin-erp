"""
Standard Chart of Accounts for Iranian Commercial & Service Enterprises
(کدینگ استاندارد حسابداری ایران برای شرکت‌های بازرگانی و خدماتی در آربین)

# Fixed hierarchy (Iranian standard accounting compatible):
- Account Group  (گروه  - 1 digit): 1 دارایی جاری، 2 دارایی غیرجاری، 4 بدهی،
                                     5 حقوق صاحبان سهام، 6 درآمدها، 7 بهای تمام شده و هزینه‌ها
- General Ledger (کل    - 2 digits): 10 موجودی نقد و بانک، 12 حساب‌های دریافتنی تجاری، ...
- Subsidiary     (معین  - 4 digits): 1010 حساب‌های بانکی، 1020 صندوق،
                                     1210 حساب‌های دریافتنی تجاری، ...
"""

import uuid

STANDARD_IRAN_CHART_OF_ACCOUNTS = [
    # ------------------ گروه ۱: دارایی‌های جاری ------------------
    {"code": "1", "title": "دارایی‌های جاری", "level": "group", "nature": "debit", "parent_code": None},

    # کل ۱۰: موجودی نقد و بانک (Cash & Banks)
    {"code": "10", "title": "موجودی نقد و بانک", "level": "general", "nature": "debit", "parent_code": "1"},
    {"code": "1010", "title": "حساب‌های بانکی و صندوق (Cash & Bank Accounts)", "level": "subsidiary", "nature": "debit", "parent_code": "10"},
    {"code": "1020", "title": "صندوق و تنخواه‌گردان (Petty Cash)", "level": "subsidiary", "nature": "debit", "parent_code": "10"},
    {"code": "1030", "title": "اسناد دریافتنی نزد صندوق (چک‌های اشخاص)", "level": "subsidiary", "nature": "debit", "parent_code": "10"},
    {"code": "1040", "title": "اسناد دریافتنی در جریان وصول (نزد بانک)", "level": "subsidiary", "nature": "debit", "parent_code": "10"},

    # کل ۱۱: موجودی کالا و مواد (Inventory)
    {"code": "11", "title": "موجودی کالا و مواد", "level": "general", "nature": "debit", "parent_code": "1"},
    {"code": "1110", "title": "موجودی کالای تجاری در انبار", "level": "subsidiary", "nature": "debit", "parent_code": "11"},
    {"code": "1120", "title": "موجودی مواد اولیه و قطعات", "level": "subsidiary", "nature": "debit", "parent_code": "11"},
    {"code": "1130", "title": "کالای در جریان ساخت (Work In Progress)", "level": "subsidiary", "nature": "debit", "parent_code": "11"},

    # کل ۱۲: حساب‌ها و اسناد دریافتنی تجاری (Trade Receivables)
    {"code": "12", "title": "حساب‌ها و اسناد دریافتنی تجاری", "level": "general", "nature": "debit", "parent_code": "1"},
    {"code": "1210", "title": "حساب‌های دریافتنی تجاری (بدهکاران تجاری)", "level": "subsidiary", "nature": "debit", "parent_code": "12"},

    # کل ۱۳: سایر حساب‌ها و سپرده‌های دریافتنی (Contracting Deposits)
    {"code": "13", "title": "سایر حساب‌ها و سپرده‌های دریافتنی", "level": "general", "nature": "debit", "parent_code": "1"},
    {"code": "1320", "title": "سپرده حسن انجام کار نزد کارفرما (۱۰٪)", "level": "subsidiary", "nature": "debit", "parent_code": "13"},
    {"code": "1330", "title": "ودیعه بیمه ماده ۳۸ تأمین اجتماعی نزد کارفرما", "level": "subsidiary", "nature": "debit", "parent_code": "13"},

    # کل ۱۵: پیش‌پرداخت‌ها
    {"code": "15", "title": "پیش‌پرداخت‌ها و علی‌الحساب‌ها", "level": "general", "nature": "debit", "parent_code": "1"},
    {"code": "1510", "title": "پیش‌پرداخت خرید کالا و خدمات", "level": "subsidiary", "nature": "debit", "parent_code": "15"},
    {"code": "1520", "title": "پیش‌پرداخت مالیات و بیمه", "level": "subsidiary", "nature": "debit", "parent_code": "15"},

    # ------------------ گروه ۲: دارایی‌های غیرجاری ------------------
    {"code": "2", "title": "دارایی‌های غیرجاری", "level": "group", "nature": "debit", "parent_code": None},
    {"code": "20", "title": "دارایی‌های ثابت مشهود", "level": "general", "nature": "debit", "parent_code": "2"},
    {"code": "2010", "title": "اثاثه و منصوبات اداری", "level": "subsidiary", "nature": "debit", "parent_code": "20"},
    {"code": "2020", "title": "وسایل نقلیه", "level": "subsidiary", "nature": "debit", "parent_code": "20"},
    {"code": "2030", "title": "تجهیزات کامپیوتری و نرم‌افزار", "level": "subsidiary", "nature": "debit", "parent_code": "20"},
    {"code": "21", "title": "استهلاک انباشته دارایی‌های ثابت", "level": "general", "nature": "credit", "parent_code": "2"},
    {"code": "2110", "title": "استهلاک انباشته اثاثه و تجهیزات", "level": "subsidiary", "nature": "credit", "parent_code": "21"},

    # ------------------ گروه ۴: بدهی‌ها (Liabilities) ------------------
    {"code": "4", "title": "بدهی‌ها", "level": "group", "nature": "credit", "parent_code": None},
    {"code": "40", "title": "بدهی‌های جاری", "level": "general", "nature": "credit", "parent_code": "4"},
    {"code": "4010", "title": "حساب‌های پرداختنی تجاری (بستانکاران / تأمین‌کنندگان)", "level": "subsidiary", "nature": "credit", "parent_code": "40"},
    {"code": "4020", "title": "اسناد پرداختنی تجاری (چک‌های صادره شرکت)", "level": "subsidiary", "nature": "credit", "parent_code": "40"},
    {"code": "4030", "title": "مالیات بر ارزش افزوده پرداختنی", "level": "subsidiary", "nature": "credit", "parent_code": "40"},
    {"code": "4040", "title": "حقوق و دستمزد پرداختنی به پرسنل", "level": "subsidiary", "nature": "credit", "parent_code": "40"},
    {"code": "4050", "title": "بیمه پرداختنی (تأمین اجتماعی ۳۰٪)", "level": "subsidiary", "nature": "credit", "parent_code": "40"},
    {"code": "4060", "title": "مالیات حقوق و تکلیفی پرداختنی", "level": "subsidiary", "nature": "credit", "parent_code": "40"},
    {"code": "4070", "title": "حساب جاری شرکا و سهامداران", "level": "subsidiary", "nature": "credit", "parent_code": "40"},
    {"code": "4080", "title": "پیش‌دریافت‌های پیمانکاری و قراردادها", "level": "subsidiary", "nature": "credit", "parent_code": "40"},
    {"code": "41", "title": "بدهی‌های غیرجاری", "level": "general", "nature": "credit", "parent_code": "4"},
    {"code": "4110", "title": "وام‌ها و تسهیلات بلندمدت بانکی", "level": "subsidiary", "nature": "credit", "parent_code": "41"},

    # ------------------ گروه ۵: حقوق صاحبان سهام (Equity) ------------------
    {"code": "5", "title": "حقوق مالکانه و سرمایه", "level": "group", "nature": "credit", "parent_code": None},
    {"code": "50", "title": "سرمایه ثبت شده", "level": "general", "nature": "credit", "parent_code": "5"},
    {"code": "5010", "title": "سرمایه اولیه نقدی شرکا", "level": "subsidiary", "nature": "credit", "parent_code": "50"},
    {"code": "51", "title": "سود و زیان انباشته", "level": "general", "nature": "credit", "parent_code": "5"},
    {"code": "5110", "title": "سود (زیان) انباشته سنواتی - سود انباشته", "level": "subsidiary", "nature": "credit", "parent_code": "51"},
    {"code": "5120", "title": "سود (زیان) جاری سال", "level": "subsidiary", "nature": "credit", "parent_code": "51"},
    {"code": "52", "title": "خلاصه سود و زیان", "level": "general", "nature": "credit", "parent_code": "5"},
    {"code": "5210", "title": "حساب خلاصه سود و زیان (Income Summary)", "level": "subsidiary", "nature": "credit", "parent_code": "52"},

    # ------------------ گروه ۶: درآمدها و فروش (Revenues) ------------------
    {"code": "6", "title": "درآمدها و فروش", "level": "group", "nature": "credit", "parent_code": None},
    {"code": "60", "title": "فروش و درآمدهای عملیاتی", "level": "general", "nature": "credit", "parent_code": "6"},
    {"code": "6010", "title": "فروش کالا و خدمات", "level": "subsidiary", "nature": "credit", "parent_code": "60"},
    {"code": "6020", "title": "درآمد ارائه خدمات و پشتیبانی نرم‌افزار", "level": "subsidiary", "nature": "credit", "parent_code": "60"},
    {"code": "6030", "title": "درآمد کارکرد پیمانکاری و پروژه‌ها", "level": "subsidiary", "nature": "credit", "parent_code": "60"},
    {"code": "6040", "title": "سود ناشی از واگذاری دارایی‌های ثابت", "level": "subsidiary", "nature": "credit", "parent_code": "60"},
    {"code": "61", "title": "تخفیفات و برگشت از فروش", "level": "general", "nature": "debit", "parent_code": "6"},
    {"code": "6110", "title": "برگشت از فروش و تخفیفات اعطایی", "level": "subsidiary", "nature": "debit", "parent_code": "61"},

    # ------------------ گروه ۷: بهای تمام شده و هزینه‌ها (Costs & Expenses) ------------------
    {"code": "7", "title": "بهای تمام شده و هزینه‌ها", "level": "group", "nature": "debit", "parent_code": None},
    {"code": "70", "title": "بهای تمام شده کالای فروش رفته", "level": "general", "nature": "debit", "parent_code": "7"},
    {"code": "7010", "title": "بهای تمام شده کالای فروش رفته (COGS)", "level": "subsidiary", "nature": "debit", "parent_code": "70"},
    {"code": "7020", "title": "دستمزد مستقیم جذب‌شده تولید", "level": "subsidiary", "nature": "credit", "parent_code": "70"},
    {"code": "7030", "title": "سربار جذب‌شده ساخت و تولید", "level": "subsidiary", "nature": "credit", "parent_code": "70"},
    {"code": "71", "title": "هزینه‌های حقوق و دستمزد پرسنل", "level": "general", "nature": "debit", "parent_code": "7"},
    {"code": "7110", "title": "حقوق پایه و دستمزد ماهیانه", "level": "subsidiary", "nature": "debit", "parent_code": "71"},
    {"code": "7120", "title": "حق بیمه تأمین اجتماعی سهم کارفرما (۲۳٪)", "level": "subsidiary", "nature": "debit", "parent_code": "71"},
    {"code": "7130", "title": "پاداش، مزایا، حق مسکن و بن کارگری", "level": "subsidiary", "nature": "debit", "parent_code": "71"},
    {"code": "72", "title": "هزینه‌های عمومی و اداری", "level": "general", "nature": "debit", "parent_code": "7"},
    {"code": "7210", "title": "هزینه اجاره دفتر مرکزی", "level": "subsidiary", "nature": "debit", "parent_code": "72"},
    {"code": "7220", "title": "هزینه سرورها، هاستینگ و اینترنت", "level": "subsidiary", "nature": "debit", "parent_code": "72"},
    {"code": "7230", "title": "هزینه ملزومات اداری و مصرفی", "level": "subsidiary", "nature": "debit", "parent_code": "72"},
    {"code": "7240", "title": "هزینه تبلیغات و بازاریابی", "level": "subsidiary", "nature": "debit", "parent_code": "72"},
    {"code": "7250", "title": "هزینه استهلاک دارایی‌های ثابت", "level": "subsidiary", "nature": "debit", "parent_code": "72"},
    {"code": "7260", "title": "زیان ناشی از واگذاری دارایی‌های ثابت", "level": "subsidiary", "nature": "debit", "parent_code": "72"},
]

# Canonical account codes used by the automatic journal-entry engine (سندزن خودکار)
ACCOUNT_CODES = {
    "bank": "1010",                   # Cash & Bank Accounts
    "petty_cash": "1020",             # Petty Cash / صندوق
    "notes_in_safe": "1030",          # Notes Receivable - In Safe
    "cheques_in_collection": "1040",  # Cheques in Collection
    "inventory": "1110",              # Inventory
    "raw_materials": "1120",          # Raw Materials Inventory
    "wip": "1130",                    # Work In Progress
    "receivables": "1210",            # Trade Receivables
    "retention_deposit": "1320",      # 10% Retention Deposit
    "sso_deposit": "1330",            # 5% Article 38 SSO Deposit
    "payables": "4010",               # Trade Payables
    "notes_payable": "4020",          # Notes Payable (issued cheques)
    "vat_payable": "4030",            # Value Added Tax Payable
    "salaries_payable": "4040",       # Salaries Payable
    "insurance_payable": "4050",      # Social Security Payable (30%)
    "tax_payable": "4060",            # Withholding Income Tax Payable
    "advance_contracting": "4080",    # Contracting Advance Payments
    "capital": "5010",                # Registered Capital
    "retained_earnings": "5110",      # Retained Earnings
    "current_year_profit": "5120",    # Current Year Profit / Loss
    "income_summary": "5210",         # Income Summary (خلاصه سود و زیان)
    "sales_revenue": "6010",          # Sales Revenue
    "service_revenue": "6020",        # Service Revenue
    "contract_revenue": "6030",       # Contracting Revenue
    "asset_sale_gain": "6040",        # Gain on Disposal of Assets
    "sales_return": "6110",           # Sales Returns & Discounts
    "cogs": "7010",                   # Cost of Goods Sold
    "direct_labor_absorbed": "7020",  # Direct Labor Absorbed
    "overhead_absorbed": "7030",      # Overhead Absorbed
    "salaries_expense": "7110",       # Salaries & Wages Expense
    "employer_insurance": "7120",     # Employer Social Security (23%)
    "benefits_expense": "7130",       # Allowances & Benefits
    "rent_expense": "7210",           # Office Rent
    "depreciation_expense": "7250",   # Depreciation Expense
    "asset_sale_loss": "7260",        # Loss on Disposal of Assets
}


def get_account_code(key: str) -> str:
    """Return the canonical 4-digit account code for a logical account key."""
    try:
        return ACCOUNT_CODES[key]
    except KeyError as exc:  # pragma: no cover - defensive
        raise KeyError(f"کد حساب نامشخص: {key}") from exc


# ---------------------------------------------------------------------------
# Demo / seed data (داده اولیه نمایشی)
# ---------------------------------------------------------------------------
DEFAULT_TENANT_ID = "default_company"
DEFAULT_FISCAL_YEAR_ID = "fy_1405"


def seed_demo_company(ledger) -> dict:
    """
    Idempotently create the demo company used by the web dashboard:
    - Tenant + Fiscal Year 1405 + standard chart of accounts
    - Floating sub-ledgers (customers, vendor, banks, cost center)
    - Warehouse + product catalogue (for the invoice builder)
    - Opening capital journal entry so KPI cards show live numbers
    """
    with ledger.get_connection() as conn:
        row = conn.execute("SELECT id FROM tenants WHERE id = ?", (DEFAULT_TENANT_ID,)).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO tenants (id, name, national_id, currency) VALUES (?, ?, ?, ?)",
                (
                    DEFAULT_TENANT_ID,
                    "شرکت فناوری مالی آربین پارس",
                    "14009988776",
                    "IRT",
                ),
            )
        fy_row = conn.execute(
            "SELECT id FROM fiscal_years WHERE id = ?", (DEFAULT_FISCAL_YEAR_ID,)
        ).fetchone()
        if not fy_row:
            conn.execute(
                "INSERT INTO fiscal_years (id, tenant_id, title, start_date, end_date) VALUES (?, ?, ?, ?, ?)",
                (
                    DEFAULT_FISCAL_YEAR_ID,
                    DEFAULT_TENANT_ID,
                    "سال مالی ۱۴۰۵",
                    "2026-03-21",
                    "2027-03-20",
                ),
            )

    ledger.seed_standard_accounts(DEFAULT_TENANT_ID)

    def _ensure_sub(code, title, kind, phone=None, dimension=None):
        with ledger.get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM sub_ledgers WHERE tenant_id = ? AND code = ?",
                (DEFAULT_TENANT_ID, code),
            ).fetchone()
            if existing:
                return existing[0]
        return ledger.create_sub_ledger(
            DEFAULT_TENANT_ID, code, title, kind, phone=phone, dimension=dimension
        )

    _ensure_sub("4001", "فروشگاه آنلاین زنجیره‌ای", "customer", phone="09121112233")
    _ensure_sub("4002", "شرکت راهکار نوین پرداز", "customer", phone="02188889999")
    _ensure_sub("3001", "شرکت واردات رایانه پارس", "supplier")
    _ensure_sub("100201", "بانک ملت - حساب تجاری اصلی", "bank", dimension="01")
    _ensure_sub("100202", "بانک صادرات - حساب جاری ۲۲۲", "bank", dimension="02")
    _ensure_sub("100", "مرکز هزینه دفتر مرکزی", "cost_center", dimension="HQ")

    with ledger.get_connection() as conn:
        wh = conn.execute(
            "SELECT id FROM warehouses WHERE tenant_id = ? AND code = '01'", (DEFAULT_TENANT_ID,)
        ).fetchone()
        if wh:
            warehouse_id = wh[0]
        else:
            warehouse_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO warehouses (id, tenant_id, code, title, location) VALUES (?, ?, ?, ?, ?)",
                (warehouse_id, DEFAULT_TENANT_ID, "01", "انبار مرکزی تهران", "تهران - خیابان ولیعصر"),
            )

        def _ensure_product(sku, title, unit, price, category):
            row = conn.execute(
                "SELECT id FROM products WHERE tenant_id = ? AND sku = ?",
                (DEFAULT_TENANT_ID, sku),
            ).fetchone()
            if row:
                return row[0]
            product_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO products (id, tenant_id, sku, title, unit, category, sale_price, min_stock_alert)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (product_id, DEFAULT_TENANT_ID, sku, title, unit, category, price, 5.0),
            )
            return product_id

        _ensure_product("ARB-SUB-12", "اشتراک سازمانی نرم‌افزار آربین (سالانه)", "سال", 50_000_000, "نرم‌افزار")
        _ensure_product("ASUS-ROG-16", "لپ‌تاپ گیمینگ ایسوس ROG Zephyrus", "دستگاه", 80_000_000, "سخت‌افزار")
        _ensure_product("DELL-27-MON", "مانیتور دل ۲۷ اینچ", "عدد", 18_000_000, "سخت‌افزار")

    # Opening capital so the dashboard shows real live balances
    with ledger.get_connection() as conn:
        already = conn.execute(
            "SELECT id FROM journal_entries WHERE tenant_id = ? AND source_id = 'demo_opening_capital'",
            (DEFAULT_TENANT_ID,),
        ).fetchone()
    if not already:
        ledger.record_journal_entry(
            tenant_id=DEFAULT_TENANT_ID,
            fiscal_year_id=DEFAULT_FISCAL_YEAR_ID,
            entry_date="2026-04-01",
            description="سرمایه‌گذاری نقدی اولیه سهامداران در شرکت",
            items=[
                {
                    "account_code": ACCOUNT_CODES["bank"],
                    "sub_ledger_code": "100201",
                    "description": "واریز به حساب بانک ملت",
                    "debit": 500_000_000,
                    "credit": 0,
                },
                {
                    "account_code": ACCOUNT_CODES["capital"],
                    "description": "سرمایه ثبت شده نقدی شرکا",
                    "debit": 0,
                    "credit": 500_000_000,
                },
            ],
            source_module="opening",
            source_id="demo_opening_capital",
        )

    return {
        "tenant_id": DEFAULT_TENANT_ID,
        "fiscal_year_id": DEFAULT_FISCAL_YEAR_ID,
        "warehouse_id": warehouse_id,
    }
