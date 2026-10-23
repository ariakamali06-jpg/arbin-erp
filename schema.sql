-- ==============================================================================
-- ARBIN ACCOUNTING ENGINE (آربین)
-- Core Double-Entry Ledger Schema (SQLite / PostgreSQL compatible)
-- Hierarchy: گروه (1 digit) -> کل (2 digits) -> معین (4 digits)
-- Floating sub-ledgers: تفصیلی شناور (مشتریان، تامین‌کنندگان، بانک‌ها، پرسنل، مراکز هزینه)
-- ==============================================================================

-- 1. Multi-Tenant Organization Isolation
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    national_id TEXT,
    economic_code TEXT,
    currency TEXT NOT NULL DEFAULT 'IRR', -- IRR, IRT (Toman), USD, EUR
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER NOT NULL DEFAULT 1
);

-- 2. Fiscal Years (سال‌های مالی)
CREATE TABLE IF NOT EXISTS fiscal_years (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    title TEXT NOT NULL,                -- e.g. "سال مالی ۱۴۰۵"
    start_date TEXT NOT NULL,           -- ISO YYYY-MM-DD
    end_date TEXT NOT NULL,
    is_closed INTEGER NOT NULL DEFAULT 0,
    closed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

-- 3. Standard Chart of Accounts (کدینگ حساب‌ها: گروه، کل، معین)
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,                 -- '1' (گروه), '10' (کل), '1010' (معین)
    title TEXT NOT NULL,
    level TEXT NOT NULL,                -- 'group' (گروه), 'general' (کل), 'subsidiary' (معین)
    nature TEXT NOT NULL,               -- 'debit', 'credit', 'both'
    parent_id TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES accounts(id),
    UNIQUE (tenant_id, code)
);

-- 4. Floating Sub-Ledgers / تفصیلی‌های شناور (SubLedger)
--    Multi-dimensional sub-accounts attached to journal lines:
--    مشتریان، تامین‌کنندگان (وندورها)، بانک‌ها، پرسنل، مراکز هزینه
CREATE TABLE IF NOT EXISTS sub_ledgers (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,                 -- e.g. '4001', '100201'
    title TEXT NOT NULL,
    sub_ledger_type TEXT NOT NULL,      -- 'customer','supplier','bank','personnel','cost_center','product','warehouse'
    dimension TEXT,                     -- بعد تفصیلی اضافه (مرکز هزینه/پروژه/شعبه)
    phone TEXT,
    national_id TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    UNIQUE (tenant_id, code)
);

-- Backward compatible alias (legacy name of the floating sub-ledger table)
CREATE VIEW IF NOT EXISTS detail_accounts AS
    SELECT id, tenant_id, code, title, sub_ledger_type AS detail_type, dimension,
           phone, national_id, is_active, created_at
    FROM sub_ledgers;

-- 5. Journal Entries Header (سربرگ اسناد حسابداری)
CREATE TABLE IF NOT EXISTS journal_entries (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    fiscal_year_id TEXT NOT NULL,
    entry_number INTEGER NOT NULL,      -- شماره سند متوالی سیستمی
    manual_number TEXT,                 -- شماره عطف / دستی (Reference Number)
    entry_date TEXT NOT NULL,           -- تاریخ سند میلادی (YYYY-MM-DD)
    entry_date_jalali TEXT,             -- تاریخ سند شمسی (YYYY/MM/DD)
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'approved',
        -- 'draft' (پیش‌نویس), 'approved' (تایید شده), 'permanent' (دائم/قطعی),
        -- 'opening_entry' (سند افتتاحیه), 'closing_entry' (سند اختتامیه)
    source_module TEXT DEFAULT 'manual', -- 'manual','sales','treasury','inventory','payroll','closing'
    source_id TEXT,                     -- آیدی فاکتور یا چک مرجع
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (fiscal_year_id) REFERENCES fiscal_years(id),
    UNIQUE (tenant_id, fiscal_year_id, entry_number)
);

-- 6. Journal Items / Rows (سطرهای سند حسابداری دوبل)
CREATE TABLE IF NOT EXISTS journal_items (
    id TEXT PRIMARY KEY,
    entry_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    row_number INTEGER NOT NULL,        -- ردیف سند
    account_id TEXT NOT NULL,           -- حساب معین (moein_code)
    sub_ledger_id TEXT,                 -- تفصیلی شناور (sub_ledger_id)
    description TEXT NOT NULL,          -- شرح ردیف
    debit REAL NOT NULL DEFAULT 0.0,    -- بدهکار
    credit REAL NOT NULL DEFAULT 0.0,   -- بستانکار
    FOREIGN KEY (entry_id) REFERENCES journal_entries(id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(id),
    FOREIGN KEY (sub_ledger_id) REFERENCES sub_ledgers(id),
    CHECK (debit >= 0 AND credit >= 0),
    CHECK (debit > 0 OR credit > 0),
    CHECK (NOT (debit > 0 AND credit > 0)) -- یک سطر نمی‌تواند همزمان بدهکار و بستانکار باشد
);

-- 7. Immutable Audit Trail (ردپای حسابرسی تغییرات اسناد مالی - غیرقابل جعل)
CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    entity_name TEXT NOT NULL,          -- 'journal_entry', 'account', ...
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,               -- 'CREATE','UPDATE','DELETE','CONFIRM','APPROVE','POST','LOCK'
    user_id TEXT NOT NULL,
    payload_before TEXT,
    payload_after TEXT,
    client_ip TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

-- 8. Invoices Header (فاکتورهای فروش رسمی و غیررسمی)
CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    fiscal_year_id TEXT NOT NULL,
    invoice_number INTEGER NOT NULL,    -- شماره متوالی فاکتور فروش
    invoice_date TEXT NOT NULL,         -- تاریخ صدور (YYYY-MM-DD)
    customer_detail_id TEXT NOT NULL,   -- تفصیلی شناور مشتری
    invoice_type TEXT NOT NULL DEFAULT 'official_sale',
        -- 'proforma' (پیش‌فاکتور), 'official_sale' (فاکتور رسمی فروش), 'sales_return' (برگشت از فروش)
    payment_status TEXT NOT NULL DEFAULT 'unpaid',
        -- 'unpaid' (نسیه), 'cash' (نقدی), 'cheque' (چکی), 'split' (ترکیبی)
    pattern_code TEXT NOT NULL DEFAULT 'pattern1', -- الگوی سامانه مؤدیان
    status TEXT NOT NULL DEFAULT 'draft', -- 'draft','confirmed','sent_to_tax','cancelled'
    total_amount REAL NOT NULL DEFAULT 0.0,
    total_discount REAL NOT NULL DEFAULT 0.0,
    total_vat REAL NOT NULL DEFAULT 0.0,
    final_payable REAL NOT NULL DEFAULT 0.0,
    tax_unique_id TEXT,                 -- شناسه منحصر به فرد مالیاتی ۲۲ کاراکتری
    tax_fiscal_id TEXT,                 -- شناسه حافظه مالیاتی (۶ کاراکتر)
    journal_entry_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (fiscal_year_id) REFERENCES fiscal_years(id),
    FOREIGN KEY (customer_detail_id) REFERENCES sub_ledgers(id),
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id),
    UNIQUE (tenant_id, fiscal_year_id, invoice_number)
);

-- 9. Invoice Items / Rows (اقلام فاکتور فروش)
CREATE TABLE IF NOT EXISTS invoice_items (
    id TEXT PRIMARY KEY,
    invoice_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    row_number INTEGER NOT NULL,
    item_code TEXT NOT NULL,            -- شناسه کالا/خدمت (شناسه ۱۳ یا ۱۶ رقمی مودیان)
    item_title TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'تعداد',
    quantity REAL NOT NULL,
    unit_price REAL NOT NULL,
    discount REAL NOT NULL DEFAULT 0.0,
    vat_rate REAL NOT NULL DEFAULT 0.10, -- نرخ مالیات بر ارزش افزوده (۱۰٪)
    vat_amount REAL NOT NULL DEFAULT 0.0,
    total_price REAL NOT NULL,          -- (quantity * unit_price) - discount + vat_amount
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    CHECK (quantity > 0 AND unit_price >= 0)
);

-- 10. Treasury & Sayyad Cheques (سیستم خزانه‌داری و مدیریت چک‌های صیادی)
CREATE TABLE IF NOT EXISTS cheques (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    fiscal_year_id TEXT NOT NULL,
    cheque_type TEXT NOT NULL,          -- 'received' (دریافتی), 'issued' (صادره)
    sayyad_id TEXT,                     -- شناسه ۱۶ رقمی چک صیادی
    cheque_number TEXT NOT NULL,        -- شماره سریال چک
    bank_name TEXT NOT NULL,
    branch_name TEXT,
    due_date TEXT NOT NULL,             -- تاریخ سررسید (YYYY-MM-DD)
    amount REAL NOT NULL,
    party_detail_id TEXT NOT NULL,      -- تفصیلی طرف حساب (مشتری یا تامین‌کننده)
    bank_account_detail_id TEXT,        -- تفصیلی حساب بانکی مقصد
    payee_detail_id TEXT,               -- تفصیلی گیرنده در صورت انتقال/خرج
    status TEXT NOT NULL,
        -- دریافتی: 'in_safe' (نزد صندوق) -> 'deposited_to_bank' (در جریان وصول)
        --          -> 'cleared' (وصول شده) | 'bounced' (واخواست) | 'transferred' (خرج شده) | 'returned' (مسترد شده)
        -- صادره:   'issued' (صادره) -> 'cleared' (پاس شده) | 'cancelled' (ابطال شده)
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (fiscal_year_id) REFERENCES fiscal_years(id),
    FOREIGN KEY (party_detail_id) REFERENCES sub_ledgers(id),
    FOREIGN KEY (bank_account_detail_id) REFERENCES sub_ledgers(id),
    FOREIGN KEY (payee_detail_id) REFERENCES sub_ledgers(id),
    CHECK (amount > 0)
);

-- 10-bis. Treasury Transactions (رسید و پرداخت خزانه: نقدی، کارت به کارت، کارتخوان، چک صیادی)
CREATE TABLE IF NOT EXISTS treasury_transactions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    fiscal_year_id TEXT NOT NULL,
    tx_type TEXT NOT NULL,              -- 'receipt' (دریافت), 'payment' (پرداخت)
    method TEXT NOT NULL,               -- 'cash','bank_transfer','pos','sayyad_cheque'
    amount REAL NOT NULL,
    tx_date TEXT NOT NULL,
    party_detail_id TEXT,               -- تفصیلی مشتری / تامین‌کننده
    bank_account_detail_id TEXT,        -- تفصیلی حساب بانکی
    pos_terminal_id TEXT,               -- ترمینال کارتخوان (در صورت استفاده از POS)
    cheque_id TEXT,                     -- مرجع چک صیادی
    description TEXT,
    journal_entry_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (fiscal_year_id) REFERENCES fiscal_years(id),
    FOREIGN KEY (party_detail_id) REFERENCES sub_ledgers(id),
    FOREIGN KEY (bank_account_detail_id) REFERENCES sub_ledgers(id),
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id),
    CHECK (amount > 0)
);

-- 10-ter. POS Terminals (کارتخوان‌های فروشگاهی)
CREATE TABLE IF NOT EXISTS pos_terminals (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    terminal_no TEXT NOT NULL,          -- شماره ترمینال
    merchant_id TEXT,                   -- شماره پذیرنده
    bank_name TEXT,
    bank_account_detail_id TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (bank_account_detail_id) REFERENCES sub_ledgers(id),
    UNIQUE (tenant_id, terminal_no)
);

-- 11. Warehouses (انبارها)
CREATE TABLE IF NOT EXISTS warehouses (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    custodian TEXT,                     -- مسئول/انباردار
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    UNIQUE (tenant_id, code)
);

-- 12. Products & Inventory Items (کالاها و خدمات)
CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    barcode TEXT,
    title TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'عدد',   -- واحد سنجش اولیه
    category TEXT,                      -- دسته/گروه کالا
    min_stock_alert REAL DEFAULT 5.0,   -- نقطه سفارش (ایمنی موجودی)
    sale_price REAL NOT NULL DEFAULT 0.0,
    current_stock REAL NOT NULL DEFAULT 0.0,
    weighted_avg_cost REAL NOT NULL DEFAULT 0.0,
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    UNIQUE (tenant_id, sku)
);

-- 13. Inventory Ledger / Kardex (کاردکس تعدادی و ریالی کالا)
CREATE TABLE IF NOT EXISTS inventory_transactions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    fiscal_year_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    tx_type TEXT NOT NULL,
        -- 'purchase_receipt','sales_delivery','purchase_return','sales_return','stock_reconciliation'
    tx_number INTEGER NOT NULL,
    reference_id TEXT,
    tx_date TEXT NOT NULL,
    quantity REAL NOT NULL,
    unit_cost REAL NOT NULL DEFAULT 0.0,
    total_cost REAL NOT NULL DEFAULT 0.0,
    running_qty REAL NOT NULL,
    running_avg_cost REAL NOT NULL,
    description TEXT,
    journal_entry_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (warehouse_id) REFERENCES warehouses(id),
    FOREIGN KEY (product_id) REFERENCES products(id),
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id)
);

-- 14. Employees (اطلاعات پرسنل و احکام استخدامی)
CREATE TABLE IF NOT EXISTS employees (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    sub_ledger_id TEXT NOT NULL,        -- تفصیلی شناور شخص (کد ۹xxx)
    national_id TEXT NOT NULL,
    insurance_number TEXT,              -- شماره بیمه تأمین اجتماعی
    full_name TEXT NOT NULL,
    job_title TEXT NOT NULL DEFAULT 'کارشناس',
    base_monthly_salary REAL NOT NULL,
    housing_allowance REAL NOT NULL DEFAULT 9000000.0,  -- حق مسکن
    grocery_allowance REAL NOT NULL DEFAULT 14000000.0,  -- بن کارگری
    family_allowance REAL NOT NULL DEFAULT 0.0,          -- حق اولاد (مبلغ هر فرزند)
    child_count INTEGER NOT NULL DEFAULT 0,
    working_days INTEGER NOT NULL DEFAULT 30,
    overtime_hours REAL NOT NULL DEFAULT 0.0,
    bank_shaba TEXT,
    phone TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (sub_ledger_id) REFERENCES sub_ledgers(id),
    UNIQUE (tenant_id, national_id)
);

-- 15. Payroll Runs (سربرگ محاسبات حقوق و دستمزد ماهانه)
CREATE TABLE IF NOT EXISTS payroll_runs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    fiscal_year_id TEXT NOT NULL,
    month_label TEXT NOT NULL,
    run_date TEXT NOT NULL,
    total_gross REAL NOT NULL DEFAULT 0.0,
    total_employee_insurance REAL NOT NULL DEFAULT 0.0, -- بیمه سهم کارمند (۷٪)
    total_employer_insurance REAL NOT NULL DEFAULT 0.0, -- بیمه سهم کارفرما (۲۳٪)
    total_tax REAL NOT NULL DEFAULT 0.0,
    total_net_payable REAL NOT NULL DEFAULT 0.0,
    journal_entry_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (fiscal_year_id) REFERENCES fiscal_years(id),
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id)
);

-- 16. Payroll Slips (فیش حقوقی انفرادی هر پرسنل)
CREATE TABLE IF NOT EXISTS payroll_slips (
    id TEXT PRIMARY KEY,
    payroll_run_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    gross_salary REAL NOT NULL,
    employee_insurance REAL NOT NULL,
    employer_insurance REAL NOT NULL,
    income_tax REAL NOT NULL,
    net_payable REAL NOT NULL,
    breakdown TEXT,                     -- JSON محاسبات تفصیلی فیش
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (payroll_run_id) REFERENCES payroll_runs(id) ON DELETE CASCADE,
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);

-- 15. Modular Licensing & Feature Flags (مدیریت ماژول‌ها و اشتراک)
CREATE TABLE IF NOT EXISTS tenant_modules (
    tenant_id TEXT NOT NULL,
    module_key TEXT NOT NULL,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, module_key),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

-- Indexes for ultra-fast reporting and real-time dashboard queries
CREATE INDEX IF NOT EXISTS idx_accounts_tenant_code ON accounts(tenant_id, code);
CREATE INDEX IF NOT EXISTS idx_sub_ledgers_tenant_code ON sub_ledgers(tenant_id, code);
CREATE INDEX IF NOT EXISTS idx_entries_tenant_date ON journal_entries(tenant_id, entry_date);
CREATE INDEX IF NOT EXISTS idx_entries_fy_status ON journal_entries(fiscal_year_id, status);
CREATE INDEX IF NOT EXISTS idx_items_entry ON journal_items(entry_id);
CREATE INDEX IF NOT EXISTS idx_items_account ON journal_items(account_id);
CREATE INDEX IF NOT EXISTS idx_items_sub_ledger ON journal_items(sub_ledger_id);
CREATE INDEX IF NOT EXISTS idx_invoices_tenant_num ON invoices(tenant_id, invoice_number);
CREATE INDEX IF NOT EXISTS idx_invoices_tax_id ON invoices(tax_unique_id);
CREATE INDEX IF NOT EXISTS idx_cheques_tenant_due ON cheques(tenant_id, due_date);
CREATE INDEX IF NOT EXISTS idx_cheques_sayyad ON cheques(sayyad_id);
CREATE INDEX IF NOT EXISTS idx_treasury_tx_tenant ON treasury_transactions(tenant_id, tx_date);
CREATE INDEX IF NOT EXISTS idx_inv_tx_product ON inventory_transactions(product_id);
CREATE INDEX IF NOT EXISTS idx_products_tenant_sku ON products(tenant_id, sku);
CREATE INDEX IF NOT EXISTS idx_employees_tenant ON employees(tenant_id);
CREATE INDEX IF NOT EXISTS idx_payroll_runs_tenant ON payroll_runs(tenant_id);
