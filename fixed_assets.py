"""
Arbin Fixed Assets & Depreciation Engine (سیستم دارایی ثابت و استهلاک آربین)
=============================================================================
Complies with Article 149 of the Iranian Direct Taxes Act (جدول استهلاک ماده ۱۴۹)
and standard Iranian enterprise ERP specifications.

Capabilities:
1. Asset Registration & Tagging (پلاک‌گذاری اموال، کارت مشخصات دارایی و محل استقرار)
2. Straight-line Depreciation (استهلاک به روش خط مستقیم بر اساس عمر مفید سالانه/ماهانه)
3. Declining Balance Depreciation (استهلاک به روش مانده نزولی بر اساس نرخ مصوب مالیاتی)
4. Automated Double-Entry Depreciation Vouchers:
   - Debit 7250 (هزینه استهلاک دارایی‌های ثابت)
   - Credit 2110 (استهلاک انباشته دارایی مربوطه)
5. Asset Disposal & Sale (فروش، اسقاط یا خروج دارایی):
   - Closing historical cost & accumulated depreciation
   - Recognition of Gain (Credit 6040) or Loss (Debit 7260) on disposal
   - Strict mathematical balance guaranteed on all vouchers.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
import uuid


class FixedAssetError(Exception):
    """Domain exception for fixed asset operations."""
    pass


class ArbinFixedAssets:
    """Manages Iranian statutory fixed assets, depreciation schedules, and disposals."""

    def __init__(self, ledger):
        self.ledger = ledger
        self.init_db()

    def init_db(self):
        """Create fixed assets tables if not present."""
        with self.ledger.get_connection() as conn:
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
                    depreciation_method TEXT NOT NULL, -- straight_line, declining_balance
                    useful_life_years INTEGER NOT NULL DEFAULT 5,
                    depreciation_rate REAL NOT NULL DEFAULT 0.20,
                    accumulated_depreciation REAL NOT NULL DEFAULT 0.0,
                    book_value REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active', -- active, disposed, scrapped
                    location TEXT,
                    custodian_name TEXT,
                    asset_account_code TEXT NOT NULL DEFAULT '2010',
                    depr_account_code TEXT NOT NULL DEFAULT '2110',
                    expense_account_code TEXT NOT NULL DEFAULT '7250',
                    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                    UNIQUE(tenant_id, asset_code),
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
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
                    calculated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                    FOREIGN KEY (asset_id) REFERENCES fixed_assets(id) ON DELETE CASCADE
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS asset_disposals (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    disposal_date TEXT NOT NULL,
                    disposal_type TEXT NOT NULL, -- sale, scrap
                    sale_price REAL NOT NULL DEFAULT 0.0,
                    historical_cost REAL NOT NULL,
                    accumulated_depr REAL NOT NULL,
                    book_value REAL NOT NULL,
                    gain_loss REAL NOT NULL,
                    voucher_id TEXT,
                    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                    FOREIGN KEY (asset_id) REFERENCES fixed_assets(id) ON DELETE CASCADE
                );
            """)

    def register_asset(
        self,
        tenant_id: str,
        asset_code: str,
        title: str,
        category: str,
        purchase_date: str,
        purchase_cost: float,
        salvage_value: float = 0.0,
        depreciation_method: str = "straight_line",
        useful_life_years: int = 5,
        depreciation_rate: float = 0.20,
        location: str = "دفتر مرکزی",
        custodian_name: Optional[str] = None,
        asset_account_code: str = "2010",
        depr_account_code: str = "2110",
        expense_account_code: str = "7250",
        post_purchase_voucher: bool = False,
        fiscal_year_id: Optional[str] = None,
        settlement_account_code: str = "1010"
    ) -> Dict[str, Any]:
        """Register a new physical fixed asset and optionally record purchase voucher."""
        if purchase_cost <= 0:
            raise FixedAssetError("بهای تمام‌شده دارایی باید بزرگتر از صفر باشد.")
        if salvage_value < 0 or salvage_value >= purchase_cost:
            raise FixedAssetError("ارزش اسقاط نمی‌تواند منفی یا بزرگتر/مساوی بهای تمام‌شده باشد.")
        if depreciation_method not in ("straight_line", "declining_balance"):
            raise FixedAssetError("روش استهلاک باید «straight_line» (مستقیم) یا «declining_balance» (نزولی) باشد.")

        asset_id = str(uuid.uuid4())
        initial_book_value = float(Decimal(str(purchase_cost)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

        with self.ledger.get_connection() as conn:
            # Check unique asset_code
            row = conn.execute(
                "SELECT id FROM fixed_assets WHERE tenant_id = ? AND asset_code = ?",
                (tenant_id, asset_code)
            ).fetchone()
            if row:
                raise FixedAssetError(f"پلاک یا کد دارایی «{asset_code}» قبلاً ثبت شده است.")

            conn.execute("""
                INSERT INTO fixed_assets (
                    id, tenant_id, asset_code, title, category, purchase_date,
                    purchase_cost, salvage_value, depreciation_method, useful_life_years,
                    depreciation_rate, accumulated_depreciation, book_value, status,
                    location, custodian_name, asset_account_code, depr_account_code,
                    expense_account_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?, 'active', ?, ?, ?, ?, ?)
            """, (
                asset_id, tenant_id, asset_code, title, category, purchase_date,
                purchase_cost, salvage_value, depreciation_method, useful_life_years,
                depreciation_rate, initial_book_value, location, custodian_name,
                asset_account_code, depr_account_code, expense_account_code
            ))

        voucher_id = None
        if post_purchase_voucher:
            if not fiscal_year_id:
                raise FixedAssetError("جهت صدور سند خرید دارایی، شناسه سال مالی الزامی است.")
            voucher_id = self.ledger.record_journal_entry(
                tenant_id=tenant_id,
                fiscal_year_id=fiscal_year_id,
                entry_date=purchase_date,
                description=f"خرید و تحصیل دارایی ثابت پلاک {asset_code} ({title})",
                items=[
                    {
                        "account_code": asset_account_code,
                        "debit": purchase_cost,
                        "credit": 0.0,
                        "description": f"تحصیل دارایی {title} - پلاک {asset_code}"
                    },
                    {
                        "account_code": settlement_account_code,
                        "debit": 0.0,
                        "credit": purchase_cost,
                        "description": f"تسویه بهای دارایی ثابت پلاک {asset_code}"
                    }
                ]
            )

        return {
            "id": asset_id,
            "asset_code": asset_code,
            "title": title,
            "purchase_cost": purchase_cost,
            "book_value": initial_book_value,
            "purchase_voucher_id": voucher_id,
            "message": f"دارایی ثابت «{title}» با پلاک «{asset_code}» با موفقیت ثبت شد."
        }

    def calculate_asset_depreciation(
        self,
        asset: Dict[str, Any],
        months: int = 12
    ) -> float:
        """
        Calculate depreciation amount for a given number of months under Iranian Tax Law.
        - Straight-line: ((Cost - Salvage) / Useful_Life) * (months / 12)
        - Declining balance: Current_Book_Value * Rate * (months / 12)
        """
        cost = Decimal(str(asset["purchase_cost"]))
        salvage = Decimal(str(asset["salvage_value"]))
        accum = Decimal(str(asset["accumulated_depreciation"]))
        book_value = Decimal(str(asset["book_value"]))
        months_ratio = Decimal(str(months)) / Decimal("12")

        if book_value <= salvage:
            return 0.0

        if asset["depreciation_method"] == "straight_line":
            depreciable_base = cost - salvage
            if depreciable_base <= 0:
                return 0.0
            years = Decimal(str(asset["useful_life_years"]))
            annual = depreciable_base / years
            amount = annual * months_ratio
        else:
            # Declining balance
            rate = Decimal(str(asset["depreciation_rate"]))
            amount = book_value * rate * months_ratio

        # Cannot depreciate below salvage value
        max_possible = book_value - salvage
        if amount > max_possible:
            amount = max_possible

        return float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def run_depreciation_cycle(
        self,
        tenant_id: str,
        fiscal_year_id: str,
        period_date: str,
        period_name: str = "استهلاک پایان سال مالی",
        months: int = 12
    ) -> Dict[str, Any]:
        """
        Run batch statutory depreciation for all active assets of a tenant
        and generate an automatic consolidated balanced journal entry.
        """
        with self.ledger.get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM fixed_assets
                WHERE tenant_id = ? AND status = 'active'
            """, (tenant_id,)).fetchall()

        if not rows:
            return {
                "total_depreciation": 0.0,
                "asset_count": 0,
                "voucher_id": None,
                "message": "هیچ دارایی فعالی برای استهلاک‌گیری یافت نشد."
            }

        total_depr = Decimal("0.00")
        processed_logs = []

        for row in rows:
            asset = dict(row)
            depr_amt = self.calculate_asset_depreciation(asset, months=months)
            if depr_amt <= 0:
                continue

            amt_dec = Decimal(str(depr_amt))
            total_depr += amt_dec
            before_accum = Decimal(str(asset["accumulated_depreciation"]))
            after_accum = before_accum + amt_dec
            after_book = Decimal(str(asset["purchase_cost"])) - after_accum

            processed_logs.append({
                "asset_id": asset["id"],
                "asset_code": asset["asset_code"],
                "title": asset["title"],
                "depr_amount": float(amt_dec),
                "accum_before": float(before_accum),
                "accum_after": float(after_accum),
                "book_value_after": float(after_book),
                "depr_account_code": asset["depr_account_code"],
                "expense_account_code": asset["expense_account_code"]
            })

        if total_depr <= Decimal("0.00"):
            return {
                "total_depreciation": 0.0,
                "asset_count": len(rows),
                "voucher_id": None,
                "message": "تمامی دارایی‌ها به سقف استهلاک (ارزش اسقاط) رسیده‌اند و استهلاکی شناسایی نشد."
            }

        # Build balanced voucher:
        # Debit: Expense (7250) for total
        # Credit: Each accumulated depr account (2110)
        # Group credits by account code
        credits_by_account: Dict[str, Decimal] = {}
        for item in processed_logs:
            acc = item["depr_account_code"]
            credits_by_account[acc] = credits_by_account.get(acc, Decimal("0.00")) + Decimal(str(item["depr_amount"]))

        voucher_items = [
            {
                "account_code": "7250",
                "debit": float(total_depr),
                "credit": 0.0,
                "description": f"هزینه استهلاک دارایی‌های ثابت ({period_name} - {len(processed_logs)} قلم)"
            }
        ]

        for acc, amt in credits_by_account.items():
            voucher_items.append({
                "account_code": acc,
                "debit": 0.0,
                "credit": float(amt),
                "description": f"استهلاک انباشته دارایی‌های ثابت دوره {period_name}"
            })

        voucher_id = self.ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fiscal_year_id,
            entry_date=period_date,
            description=f"سند خودکار محاسبات استهلاک دارایی‌های ثابت ({period_name})",
            items=voucher_items
        )

        # Update database logs and asset records
        with self.ledger.get_connection() as conn:
            for item in processed_logs:
                conn.execute("""
                    UPDATE fixed_assets
                    SET accumulated_depreciation = ?, book_value = ?
                    WHERE id = ?
                """, (item["accum_after"], item["book_value_after"], item["asset_id"]))

                log_id = str(uuid.uuid4())
                conn.execute("""
                    INSERT INTO asset_depreciation_logs (
                        id, tenant_id, asset_id, fiscal_year_id, period_name,
                        depreciation_amount, accumulated_before, accumulated_after,
                        book_value_after, voucher_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    log_id, tenant_id, item["asset_id"], fiscal_year_id, period_name,
                    item["depr_amount"], item["accum_before"], item["accum_after"],
                    item["book_value_after"], voucher_id
                ))

        return {
            "total_depreciation": float(total_depr),
            "asset_count": len(processed_logs),
            "voucher_id": voucher_id,
            "period_name": period_name,
            "items": processed_logs,
            "message": f"محاسبه استهلاک {len(processed_logs)} دارایی با مبلغ {float(total_depr):,.0f} تومان و صدور سند دوبل با موفقیت انجام شد."
        }

    def dispose_asset(
        self,
        tenant_id: str,
        fiscal_year_id: str,
        asset_code: str,
        disposal_date: str,
        disposal_type: str = "sale",  # sale, scrap
        sale_price: float = 0.0,
        settlement_account_code: str = "1010"
    ) -> Dict[str, Any]:
        """
        Record asset disposal or scrap under Iranian Accounting Standards.
        - Closes original cost (Credit 20xx)
        - Closes accumulated depreciation (Debit 21xx)
        - Debits Cash/Bank for sale_price
        - Balances gain to Credit 6040 or loss to Debit 7260.
        """
        with self.ledger.get_connection() as conn:
            row = conn.execute("""
                SELECT * FROM fixed_assets
                WHERE tenant_id = ? AND asset_code = ?
            """, (tenant_id, asset_code)).fetchone()

        if not row:
            raise FixedAssetError(f"دارایی با پلاک «{asset_code}» یافت نشد.")

        asset = dict(row)
        if asset["status"] != "active":
            raise FixedAssetError(f"دارایی با پلاک «{asset_code}» قبلاً از سرفصل خارج یا اسقاط شده است.")

        cost = Decimal(str(asset["purchase_cost"]))
        accum = Decimal(str(asset["accumulated_depreciation"]))
        book_val = cost - accum
        price = Decimal(str(sale_price))
        gain_loss = price - book_val  # positive: gain, negative: loss

        items = []

        # 1. Cash/Bank from sale if price > 0
        if price > Decimal("0.00"):
            items.append({
                "account_code": settlement_account_code,
                "debit": float(price),
                "credit": 0.0,
                "description": f"وجه حاصل از واگذاری دارایی پلاک {asset_code}"
            })

        # 2. Close accumulated depreciation
        if accum > Decimal("0.00"):
            items.append({
                "account_code": asset["depr_account_code"],
                "debit": float(accum),
                "credit": 0.0,
                "description": f"بستن استهلاک انباشته دارایی واگذار شده پلاک {asset_code}"
            })

        # 3. Handle Loss (Debit 7260) or Gain (Credit 6040)
        if gain_loss < Decimal("0.00"):
            loss_amt = abs(gain_loss)
            items.append({
                "account_code": "7260",  # زیان ناشی از واگذاری دارایی
                "debit": float(loss_amt),
                "credit": 0.0,
                "description": f"زیان حاصل از واگذاری/اسقاط دارایی ثابت پلاک {asset_code}"
            })
        elif gain_loss > Decimal("0.00"):
            gain_amt = gain_loss
            items.append({
                "account_code": "6040",  # سود ناشی از واگذاری دارایی
                "debit": 0.0,
                "credit": float(gain_amt),
                "description": f"سود حاصل از واگذاری دارایی ثابت پلاک {asset_code}"
            })

        # 4. Close historical asset cost
        items.append({
            "account_code": asset["asset_account_code"],
            "debit": 0.0,
            "credit": float(cost),
            "description": f"خروج بهای تمام‌شده تاریخی دارایی پلاک {asset_code}"
        })

        voucher_id = self.ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fiscal_year_id,
            entry_date=disposal_date,
            description=f"سند خروج و واگذاری دارایی ثابت {asset['title']} (پلاک {asset_code})",
            items=items
        )

        with self.ledger.get_connection() as conn:
            conn.execute("""
                UPDATE fixed_assets
                SET status = ?, book_value = 0.0
                WHERE id = ?
            """, (disposal_type, asset["id"]))

            disp_id = str(uuid.uuid4())
            conn.execute("""
                INSERT INTO asset_disposals (
                    id, tenant_id, asset_id, disposal_date, disposal_type,
                    sale_price, historical_cost, accumulated_depr, book_value,
                    gain_loss, voucher_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                disp_id, tenant_id, asset["id"], disposal_date, disposal_type,
                float(price), float(cost), float(accum), float(book_val),
                float(gain_loss), voucher_id
            ))

        return {
            "asset_code": asset_code,
            "title": asset["title"],
            "historical_cost": float(cost),
            "accumulated_depreciation": float(accum),
            "book_value": float(book_val),
            "sale_price": float(price),
            "gain_loss": float(gain_loss),
            "voucher_id": voucher_id,
            "message": f"عملیات {disposal_type} برای دارایی «{asset['title']}» ثبت شد و سند دوبل صادر گردید."
        }

    def list_assets(self, tenant_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List fixed assets for tenant with current status and book values."""
        query = "SELECT * FROM fixed_assets WHERE tenant_id = ?"
        params = [tenant_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY asset_code ASC"

        with self.ledger.get_connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        return [dict(r) for r in rows]
