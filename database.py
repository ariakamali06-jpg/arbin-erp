"""
Arbin Database Layer (لایه پایگاه داده آربین)
==============================================
Central SQLite connection & session management shared by every Arbin module
(general ledger, treasury, inventory, invoicing, payroll and reports).

Responsibilities:
- Connection factory: Row factory, Foreign Keys, WAL, busy-timeout
- Managed sessions: `with db.session() as conn:` -> COMMIT / ROLLBACK / CLOSE
- Schema bootstrap (`schema.sql`) + forward migrations (safe column/table upgrades)
- Jalali (Shamsi) <-> Gregorian conversion helpers for document dates
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_FILENAME = "arbin.db"
SCHEMA_FILE = BASE_DIR / "schema.sql"

# ---------------------------------------------------------------------------
# Jalali (Persian / Shamsi) calendar helpers
# ---------------------------------------------------------------------------
# Anchor: 1 Farvardin 1405 == 2026-03-21 (Iranian solar New Year 1405).
_JALALI_ANCHOR_YEAR = 1405
_JALALI_ANCHOR_GREGORIAN = (2026, 3, 21)
# Arithmetic 33-year cycle leap years (matches the official Iranian calendar
# for the current era: 1399, 1403, 1408, 1412, ...)
_JALALI_LEAP_CYCLE = {1, 5, 9, 13, 17, 22, 26, 30}
# Far..Shahrivar = 31, Mehr..Bahman = 30, Esfand = 29 (30 in leap years)
_JALALI_MONTH_DAYS = (31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29)


def gregorian_to_jdn(year: int, month: int, day: int) -> int:
    """Gregorian calendar date -> Julian Day Number (Fliegel-Van Flandern)."""
    a = (14 - month) // 12
    y = year + 4800 - a
    m = month + 12 * a - 3
    return day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045


def jdn_to_gregorian(jdn: int) -> Tuple[int, int, int]:
    """Julian Day Number -> Gregorian (year, month, day)."""
    a = jdn + 32044
    b = (4 * a + 3) // 146097
    c = a - (146097 * b) // 4
    d = (4 * c + 3) // 1461
    e = c - (1461 * d) // 4
    m = (5 * e + 2) // 153
    day = e - (153 * m + 2) // 5 + 1
    month = m + 3 - 12 * (m // 10)
    year = 100 * b + d - 4800 + m // 10
    return year, month, day


def is_jalali_leap_year(jy: int) -> bool:
    return (jy % 33) in _JALALI_LEAP_CYCLE


def jalali_month_days(jy: int, jm: int) -> int:
    if jm == 12:
        return 30 if is_jalali_leap_year(jy) else 29
    return _JALALI_MONTH_DAYS[jm - 1]


def _anchor_jdn() -> int:
    gy, gm, gd = _JALALI_ANCHOR_GREGORIAN
    return gregorian_to_jdn(gy, gm, gd)


def jalali_to_jdn(jy: int, jm: int, jd: int) -> int:
    """Jalali date -> Julian Day Number."""
    if not (1 <= jm <= 12):
        raise ValueError("ماه شمسی باید بین ۱ تا ۱۲ باشد.")
    days = 0
    if jy >= _JALALI_ANCHOR_YEAR:
        for year in range(_JALALI_ANCHOR_YEAR, jy):
            days += 366 if is_jalali_leap_year(year) else 365
    else:
        for year in range(jy, _JALALI_ANCHOR_YEAR):
            days -= 366 if is_jalali_leap_year(year) else 365
    days += sum(_JALALI_MONTH_DAYS[: jm - 1]) + (jd - 1)
    return _anchor_jdn() + days


def jdn_to_jalali(jdn: int) -> Tuple[int, int, int]:
    """Julian Day Number -> Jalali (year, month, day)."""
    delta = jdn - _anchor_jdn()
    jy = _JALALI_ANCHOR_YEAR
    if delta >= 0:
        while True:
            year_len = 366 if is_jalali_leap_year(jy) else 365
            if delta < year_len:
                break
            delta -= year_len
            jy += 1
    else:
        while delta < 0:
            jy -= 1
            delta += 366 if is_jalali_leap_year(jy) else 365

    jm = 1
    while jm <= 12:
        month_len = jalali_month_days(jy, jm)
        if delta < month_len:
            break
        delta -= month_len
        jm += 1
    return jy, jm, delta + 1


def gregorian_to_jalali(date_str: str) -> str:
    """
    'YYYY-MM-DD' (Gregorian) -> 'YYYY/MM/DD' (Jalali / شمسی).
    Raises ValueError on malformed input.
    """
    dt = _parse_date(date_str)
    jy, jm, jd = jdn_to_jalali(gregorian_to_jdn(dt.year, dt.month, dt.day))
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


def jalali_to_gregorian(date_str: str) -> str:
    """'YYYY/MM/DD' (Jalali) -> 'YYYY-MM-DD' (Gregorian)."""
    parts = date_str.replace("-", "/").split("/")
    if len(parts) != 3:
        raise ValueError("تاریخ شمسی باید با قالب YYYY/MM/DD وارد شود.")
    jy, jm, jd = (int(p) for p in parts)
    gy, gm, gd = jdn_to_gregorian(jalali_to_jdn(jy, jm, jd))
    return f"{gy:04d}-{gm:02d}-{gd:02d}"


def to_jalali(date_value) -> Optional[str]:
    """Best-effort conversion of an ISO date string / date / datetime to Jalali."""
    if date_value is None or date_value == "":
        return None
    try:
        if isinstance(date_value, datetime):
            dt = date_value.date()
        elif isinstance(date_value, date):
            dt = date_value
        else:
            dt = _parse_date(str(date_value))
        jy, jm, jd = jdn_to_jalali(gregorian_to_jdn(dt.year, dt.month, dt.day))
        return f"{jy:04d}/{jm:02d}/{jd:02d}"
    except (ValueError, TypeError):
        return None


def _parse_date(value: str) -> date:
    value = value.strip().replace("/", "-")
    # Accept both 'YYYY-MM-DD' and 'YYYY-M-D'
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"تاریخ نامعتبر است: {value!r} (انتظار YYYY-MM-DD)")


def today_jalali() -> str:
    return to_jalali(date.today())


def jalali_today_offset(days: int) -> str:
    return to_jalali(date.today() + timedelta(days=days))


# ---------------------------------------------------------------------------
# Connection & session management
# ---------------------------------------------------------------------------
class DatabaseError(Exception):
    """Raised when the database layer cannot complete an operation."""


class ManagedConnection(sqlite3.Connection):
    """
    sqlite3 connection whose `with` block is a managed transaction:
    - success  -> COMMIT
    - failure  -> ROLLBACK (exception re-raised)
    - always   -> CLOSE (no connection leaks)
    """

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()
        return False


class Database:
    """SQLite connection factory + schema/session manager."""

    def __init__(self, db_path: Optional[str] = None):
        self.base_dir = BASE_DIR
        resolved = (
            db_path
            or os.environ.get("ARBIN_DB_PATH")
            or os.environ.get("ARBIN_DATABASE_URL")
            or str(BASE_DIR / DEFAULT_DB_FILENAME)
        )
        if resolved.startswith("sqlite:///"):
            resolved = resolved[len("sqlite:///"):]
        self.db_path = str(resolved)

    # -- connections -------------------------------------------------------
    def connect(self) -> ManagedConnection:
        parent = Path(self.db_path).expanduser().parent
        if str(parent) and parent.is_absolute() and not parent.exists():
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:  # pragma: no cover - exotic filesystems
                raise DatabaseError(f"ایجاد مسیر پایگاه داده ممکن نشد: {parent}") from exc

        conn = sqlite3.connect(self.db_path, factory=ManagedConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 8000;")
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
        except sqlite3.DatabaseError:
            pass  # in-memory or read-only databases
        return conn

    # Backwards compatible alias used by every Arbin module.
    get_connection = connect

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        """Managed transaction: commit on success, rollback on error, always close."""
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- schema ------------------------------------------------------------
    def init_schema(self, schema_path: Optional[str] = None) -> None:
        """Run forward migrations, then apply `schema.sql` (idempotent)."""
        path = Path(schema_path) if schema_path else SCHEMA_FILE
        if not path.exists():
            raise DatabaseError(f"فایل ساختار دیتابیس یافت نشد: {path}")
        sql = path.read_text(encoding="utf-8")
        with self.session() as conn:
            self.migrate(conn)
            conn.executescript(sql)

    def migrate(self, conn: sqlite3.Connection) -> None:
        """Upgrade legacy databases in place (safe / idempotent)."""
        # REFERENCES clauses of sibling tables are re-written by SQLite on rename,
        # which requires foreign key enforcement to be enabled.
        conn.execute("PRAGMA foreign_keys = ON;")

        # 1) detail_accounts -> sub_ledgers (Floating sub-ledgers / تفصیلی شناور)
        if self.table_exists(conn, "detail_accounts") and not self.table_exists(conn, "sub_ledgers"):
            conn.execute("ALTER TABLE detail_accounts RENAME TO sub_ledgers")

        # 2) journal_items.detail_id -> journal_items.sub_ledger_id
        self._rename_column(conn, "journal_items", "detail_id", "sub_ledger_id")
        # 3) employees.detail_id -> employees.sub_ledger_id
        self._rename_column(conn, "employees", "detail_id", "sub_ledger_id")

        # 4) Jalali document date on journal entries
        self.add_column_if_missing(conn, "journal_entries", "entry_date_jalali", "TEXT")

        # 5) Invoice type (proforma/official_sale/sales_return) + payment status
        self.add_column_if_missing(
            conn, "invoices", "invoice_type", "TEXT NOT NULL DEFAULT 'official_sale'"
        )
        self.add_column_if_missing(
            conn, "invoices", "payment_status", "TEXT NOT NULL DEFAULT 'unpaid'"
        )

        # 6) Extra columns introduced by the Enterprise ERP parity release
        self.add_column_if_missing(conn, "fiscal_years", "closed_at", "TIMESTAMP")
        self.add_column_if_missing(conn, "cheques", "payee_detail_id", "TEXT")
        self.add_column_if_missing(conn, "cheques", "bank_account_detail_id", "TEXT")
        self.add_column_if_missing(conn, "warehouses", "custodian", "TEXT")
        self.add_column_if_missing(conn, "products", "category", "TEXT")
        # legacy detail_accounts table -> sub_ledgers column set
        self._rename_column(conn, "sub_ledgers", "detail_type", "sub_ledger_type")
        self.add_column_if_missing(conn, "sub_ledgers", "dimension", "TEXT")
        self.add_column_if_missing(conn, "sub_ledgers", "national_id", "TEXT")
        self.add_column_if_missing(
            conn, "sub_ledgers", "is_active", "INTEGER NOT NULL DEFAULT 1"
        )
        self.add_column_if_missing(
            conn, "sub_ledgers", "created_at", "TIMESTAMP"
        )
        self.add_column_if_missing(conn, "employees", "family_allowance", "REAL DEFAULT 0.0")
        self.add_column_if_missing(conn, "employees", "working_days", "INTEGER DEFAULT 30")
        self.add_column_if_missing(conn, "employees", "overtime_hours", "REAL DEFAULT 0.0")
        self.add_column_if_missing(conn, "payroll_slips", "breakdown", "TEXT")
        self.add_column_if_missing(conn, "journal_entries", "source_id", "TEXT")
        self.add_column_if_missing(
            conn, "journal_entries", "updated_at", "TIMESTAMP"
        )
        for column, decl in (
            ("pattern_code", "TEXT NOT NULL DEFAULT 'pattern1'"),
            ("tax_unique_id", "TEXT"),
            ("tax_fiscal_id", "TEXT"),
            ("journal_entry_id", "TEXT"),
            ("total_discount", "REAL NOT NULL DEFAULT 0.0"),
            ("total_vat", "REAL NOT NULL DEFAULT 0.0"),
            ("final_payable", "REAL NOT NULL DEFAULT 0.0"),
        ):
            self.add_column_if_missing(conn, "invoices", column, decl)

        # 7) tenant_modules table (Modular licensing)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tenant_modules (
                tenant_id TEXT NOT NULL,
                module_key TEXT NOT NULL,
                is_enabled INTEGER NOT NULL DEFAULT 1,
                activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, module_key)
            );
        """)

        # 8) Fixed Assets (سیستم دارایی ثابت و استهلاک)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fixed_assets (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                asset_code TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                purchase_date TEXT NOT NULL,
                purchase_cost REAL NOT NULL,
                salvage_value REAL NOT NULL DEFAULT 0.0,
                depreciation_method TEXT NOT NULL,
                useful_life_years INTEGER NOT NULL DEFAULT 5,
                depreciation_rate REAL NOT NULL DEFAULT 0.20,
                accumulated_depreciation REAL NOT NULL DEFAULT 0.0,
                book_value REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                location TEXT,
                custodian_name TEXT,
                asset_account_code TEXT NOT NULL DEFAULT '2010',
                depr_account_code TEXT NOT NULL DEFAULT '2110',
                expense_account_code TEXT NOT NULL DEFAULT '7250',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id, asset_code)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS asset_depreciation_logs (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                fiscal_year_id TEXT NOT NULL,
                period_name TEXT NOT NULL,
                depreciation_amount REAL NOT NULL,
                accumulated_before REAL NOT NULL,
                accumulated_after REAL NOT NULL,
                book_value_after REAL NOT NULL,
                voucher_id TEXT,
                calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS asset_disposals (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                disposal_date TEXT NOT NULL,
                disposal_type TEXT NOT NULL,
                sale_price REAL NOT NULL DEFAULT 0.0,
                historical_cost REAL NOT NULL,
                accumulated_depr REAL NOT NULL,
                book_value REAL NOT NULL,
                gain_loss REAL NOT NULL,
                voucher_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 9) Manufacturing & BOM (سیستم تولید و فرمول ساخت)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS boms (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                target_product_id TEXT NOT NULL,
                title TEXT NOT NULL,
                standard_qty REAL NOT NULL DEFAULT 1.0,
                direct_labor_rate REAL NOT NULL DEFAULT 0.0,
                overhead_rate REAL NOT NULL DEFAULT 0.0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bom_items (
                id TEXT PRIMARY KEY,
                bom_id TEXT NOT NULL,
                raw_material_id TEXT NOT NULL,
                qty_required REAL NOT NULL,
                waste_percentage REAL NOT NULL DEFAULT 0.0
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS production_orders (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                order_no TEXT NOT NULL,
                bom_id TEXT NOT NULL,
                target_product_id TEXT NOT NULL,
                planned_qty REAL NOT NULL,
                actual_qty REAL NOT NULL DEFAULT 0.0,
                start_date TEXT NOT NULL,
                end_date TEXT,
                status TEXT NOT NULL DEFAULT 'planned',
                material_cost REAL NOT NULL DEFAULT 0.0,
                labor_cost REAL NOT NULL DEFAULT 0.0,
                overhead_cost REAL NOT NULL DEFAULT 0.0,
                total_cost REAL NOT NULL DEFAULT 0.0,
                unit_cost REAL NOT NULL DEFAULT 0.0,
                issue_voucher_id TEXT,
                completion_voucher_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id, order_no)
            );
        """)

        # 10) Contracting & Progress Billings (سیستم پیمانکاری)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contracts (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                contract_no TEXT NOT NULL,
                title TEXT NOT NULL,
                employer_sub_ledger_id TEXT,
                total_amount REAL NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT,
                retention_rate REAL NOT NULL DEFAULT 0.10,
                sso_rate REAL NOT NULL DEFAULT 0.05,
                advance_received REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id, contract_no)
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
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(contract_id, billing_no)
            );
        """)

    def _rename_column(self, conn: sqlite3.Connection, table: str, old: str, new: str) -> None:
        if not self.table_exists(conn, table):
            return
        cols = self.columns(conn, table)
        if old in cols and new not in cols:
            conn.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
            # drop legacy indexes that referenced the old column name
            for row in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL",
                (table,),
            ).fetchall():
                if f"({old}" in (row[1] or ""):
                    conn.execute(f"DROP INDEX IF EXISTS {row[0]}")

    # -- introspection helpers --------------------------------------------
    @staticmethod
    def table_exists(conn: sqlite3.Connection, name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None

    @staticmethod
    def columns(conn: sqlite3.Connection, table: str) -> List[str]:
        if not Database.table_exists(conn, table):
            return []
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]

    @staticmethod
    def add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
        if not Database.table_exists(conn, table):
            return
        if column not in Database.columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    @staticmethod
    def table_names(conn: sqlite3.Connection) -> Sequence[str]:
        return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]


_database_cache: dict = {}


def get_database(db_path: Optional[str] = None) -> Database:
    """Return a cached Database instance (one connection factory per file)."""
    key = str(Path(db_path).resolve()) if db_path else "default"
    if key not in _database_cache:
        _database_cache[key] = Database(db_path)
    return _database_cache[key]
