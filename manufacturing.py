"""
Arbin Manufacturing & BOM Engine (سیستم تولید و بهای تمام‌شده صنعتی آربین)
=============================================================================
Follows Iranian industrial standard double-entry accounting:
1. Bill of Materials (فرمول ساخت - BOM):
   - Product recipe with raw material quantities and standard waste %
   - Standard direct labor allocation rate
   - Standard factory overhead absorption rate
2. Production Orders (سفارش تولید / برگه کار):
   - Planned vs actual output quantities
   - Start and scheduled completion dates
3. Material Issuance to WIP (حواله مصرف مواد اولیه به خط تولید):
   - Perpetual inventory deduction with weighted-average valuation
   - Automatic voucher:
     Debit 1130 (کالای در جریان ساخت - WIP)
     Credit 1120 (موجودی مواد اولیه و قطعات)
4. Completion & Cost Finalization (رسید محصول و محاسبه بهای تمام‌شده قطعی):
   - Absorbed labor and factory overhead allocation
   - Finished goods warehouse receipt at exact unit manufacturing cost
   - Balanced double-entry voucher:
     Debit 1110 (موجودی کالای ساخته‌شده در انبار) [Total Cost]
     Credit 1130 (کالای در جریان ساخت) [Material Cost]
     Credit 7020 (دستمزد مستقیم جذب‌شده) [Labor Cost]
     Credit 7030 (سربار جذب‌شده تولید) [Overhead Cost]
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
import uuid


class ManufacturingError(Exception):
    """Domain exception for manufacturing operations."""
    pass


class ArbinManufacturing:
    """Manages Bill of Materials (BOM), production orders, and industrial costing vouchers."""

    def __init__(self, ledger, inventory=None):
        self.ledger = ledger
        self.inventory = inventory
        self.init_db()

    def init_db(self):
        """Create manufacturing tables if not present."""
        with self.ledger.get_connection() as conn:
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
                    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                    FOREIGN KEY (target_product_id) REFERENCES products(id) ON DELETE CASCADE
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bom_items (
                    id TEXT PRIMARY KEY,
                    bom_id TEXT NOT NULL,
                    raw_material_id TEXT NOT NULL,
                    qty_required REAL NOT NULL,
                    waste_percentage REAL NOT NULL DEFAULT 0.0,
                    FOREIGN KEY (bom_id) REFERENCES boms(id) ON DELETE CASCADE,
                    FOREIGN KEY (raw_material_id) REFERENCES products(id) ON DELETE CASCADE
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
                    status TEXT NOT NULL DEFAULT 'planned', -- planned, in_progress, completed, cancelled
                    material_cost REAL NOT NULL DEFAULT 0.0,
                    labor_cost REAL NOT NULL DEFAULT 0.0,
                    overhead_cost REAL NOT NULL DEFAULT 0.0,
                    total_cost REAL NOT NULL DEFAULT 0.0,
                    unit_cost REAL NOT NULL DEFAULT 0.0,
                    issue_voucher_id TEXT,
                    completion_voucher_id TEXT,
                    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                    UNIQUE(tenant_id, order_no),
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                    FOREIGN KEY (bom_id) REFERENCES boms(id) ON DELETE CASCADE,
                    FOREIGN KEY (target_product_id) REFERENCES products(id) ON DELETE CASCADE
                );
            """)

    def create_bom(
        self,
        tenant_id: str,
        target_product_id: str,
        title: str,
        items: List[Dict[str, Any]],
        standard_qty: float = 1.0,
        direct_labor_rate: float = 0.0,
        overhead_rate: float = 0.0
    ) -> Dict[str, Any]:
        """Create a new Bill of Materials recipe."""
        if not items:
            raise ManufacturingError("فرمول ساخت باید حداقل دارای یک قلم مواد اولیه باشد.")
        if standard_qty <= 0:
            raise ManufacturingError("تعداد مبنای فرمول ساخت باید بزرگتر از صفر باشد.")

        bom_id = str(uuid.uuid4())
        with self.ledger.get_connection() as conn:
            conn.execute("""
                INSERT INTO boms (
                    id, tenant_id, target_product_id, title, standard_qty,
                    direct_labor_rate, overhead_rate, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                bom_id, tenant_id, target_product_id, title,
                standard_qty, direct_labor_rate, overhead_rate
            ))

            for item in items:
                item_id = str(uuid.uuid4())
                qty = float(item["qty_required"])
                waste = float(item.get("waste_percentage", 0.0))
                conn.execute("""
                    INSERT INTO bom_items (
                        id, bom_id, raw_material_id, qty_required, waste_percentage
                    ) VALUES (?, ?, ?, ?, ?)
                """, (item_id, bom_id, item["raw_material_id"], qty, waste))

        return {
            "id": bom_id,
            "title": title,
            "target_product_id": target_product_id,
            "items_count": len(items),
            "message": f"فرمول ساخت «{title}» با {len(items)} قلم مواد اولیه با موفقیت ثبت شد."
        }

    def create_production_order(
        self,
        tenant_id: str,
        order_no: str,
        bom_id: str,
        planned_qty: float,
        start_date: str,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new planned production order."""
        if planned_qty <= 0:
            raise ManufacturingError("تعداد برنامه تولید باید بزرگتر از صفر باشد.")

        with self.ledger.get_connection() as conn:
            bom_row = conn.execute(
                "SELECT * FROM boms WHERE tenant_id = ? AND id = ?",
                (tenant_id, bom_id)
            ).fetchone()
            if not bom_row:
                raise ManufacturingError("فرمول ساخت مورد نظر یافت نشد.")

            bom = dict(bom_row)
            order_id = str(uuid.uuid4())

            conn.execute("""
                INSERT INTO production_orders (
                    id, tenant_id, order_no, bom_id, target_product_id,
                    planned_qty, actual_qty, start_date, end_date, status
                ) VALUES (?, ?, ?, ?, ?, ?, 0.0, ?, ?, 'planned')
            """, (
                order_id, tenant_id, order_no, bom_id, bom["target_product_id"],
                planned_qty, start_date, end_date
            ))

        return {
            "id": order_id,
            "order_no": order_no,
            "target_product_id": bom["target_product_id"],
            "planned_qty": planned_qty,
            "status": "planned",
            "message": f"سفارش تولید شماره «{order_no}» با تیراژ {planned_qty} با موفقیت صادر گردید."
        }

    def start_production(
        self,
        tenant_id: str,
        fiscal_year_id: str,
        order_id: str,
        warehouse_id: str,
        issue_date: str
    ) -> Dict[str, Any]:
        """
        Start production order:
        - Issues raw materials from specified warehouse
        - Computes material cost using perpetual inventory weighted-average
        - Books double-entry voucher: Debit 1130 (WIP) / Credit 1120 (Raw Materials)
        """
        with self.ledger.get_connection() as conn:
            ord_row = conn.execute(
                "SELECT * FROM production_orders WHERE tenant_id = ? AND id = ?",
                (tenant_id, order_id)
            ).fetchone()
            if not ord_row:
                raise ManufacturingError("سفارش تولید یافت نشد.")
            order = dict(ord_row)

            if order["status"] != "planned":
                raise ManufacturingError(f"سفارش تولید در وضعیت '{order['status']}' است و امکان شروع مجدد ندارد.")

            bom_row = conn.execute("SELECT * FROM boms WHERE id = ?", (order["bom_id"],)).fetchone()
            bom = dict(bom_row)

            item_rows = conn.execute(
                "SELECT * FROM bom_items WHERE bom_id = ?",
                (bom["id"],)
            ).fetchall()

        if not item_rows:
            raise ManufacturingError("فرمول ساخت فاقد اقلام مواد اولیه است.")

        scale = Decimal(str(order["planned_qty"])) / Decimal(str(bom["standard_qty"]))
        total_material_cost = Decimal("0.00")
        issued_items_detail = []

        with self.ledger.get_connection() as conn:
            for row in item_rows:
                item = dict(row)
                base_qty = Decimal(str(item["qty_required"])) * scale
                waste_ratio = Decimal("1.00") + (Decimal(str(item["waste_percentage"])) / Decimal("100"))
                needed_qty = (base_qty * waste_ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

                # Check stock in products table
                prod_row = conn.execute("SELECT * FROM products WHERE id = ?", (item["raw_material_id"],)).fetchone()
                if not prod_row:
                    raise ManufacturingError(f"ماده اولیه با شناسه {item['raw_material_id']} یافت نشد.")

                prod = dict(prod_row)
                curr_stock = Decimal(str(prod["current_stock"]))
                avg_cost = Decimal(str(prod["weighted_avg_cost"]))

                if curr_stock < needed_qty:
                    raise ManufacturingError(
                        f"کسری موجودی مواد اولیه! کالای «{prod['title']}» نیاز به {needed_qty} دارد، اما موجودی انبار {curr_stock} است."
                    )

                line_cost = (needed_qty * avg_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                total_material_cost += line_cost
                new_stock = curr_stock - needed_qty

                # Deduct stock in products
                conn.execute(
                    "UPDATE products SET current_stock = ? WHERE id = ?",
                    (float(new_stock), item["raw_material_id"])
                )

                # Log Kardex transaction
                tx_id = str(uuid.uuid4())
                cur = conn.execute(
                    "SELECT COALESCE(MAX(tx_number), 0) + 1 FROM inventory_transactions WHERE tenant_id = ?",
                    (tenant_id,)
                )
                tx_num = cur.fetchone()[0]
                conn.execute("""
                    INSERT INTO inventory_transactions (
                        id, tenant_id, fiscal_year_id, warehouse_id, product_id, tx_type, tx_number,
                        tx_date, quantity, unit_cost, total_cost, running_qty, running_avg_cost, description
                    ) VALUES (?, ?, ?, ?, ?, 'production_issue', ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    tx_id, tenant_id, fiscal_year_id, warehouse_id, item["raw_material_id"],
                    tx_num, issue_date, float(needed_qty), float(avg_cost), float(line_cost),
                    float(new_stock), float(avg_cost), f"حواله مصرف مواد اولیه سفارش تولید {order['order_no']}"
                ))

                issued_items_detail.append({
                    "raw_material_id": item["raw_material_id"],
                    "qty": float(needed_qty),
                    "cost": float(line_cost)
                })

        # Post balanced double-entry voucher:
        # Debit: 1130 (کالای در جریان ساخت - WIP)
        # Credit: 1120 (موجودی مواد اولیه و قطعات)
        mat_float = float(total_material_cost)
        voucher_id = self.ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fiscal_year_id,
            entry_date=issue_date,
            description=f"حواله مصرف مواد اولیه به خط تولید (سفارش تولید {order['order_no']})",
            items=[
                {
                    "account_code": "1130",  # کالای در جریان ساخت
                    "debit": mat_float,
                    "credit": 0.0,
                    "description": f"ورود مواد اولیه به خط تولید - سفارش {order['order_no']}"
                },
                {
                    "account_code": "1120",  # موجودی مواد اولیه و قطعات
                    "debit": 0.0,
                    "credit": mat_float,
                    "description": f"حواله انبار مواد اولیه مصرفی - سفارش {order['order_no']}"
                }
            ]
        )

        with self.ledger.get_connection() as conn:
            conn.execute("""
                UPDATE production_orders
                SET status = 'in_progress', material_cost = ?, issue_voucher_id = ?
                WHERE id = ?
            """, (mat_float, voucher_id, order_id))

        return {
            "order_id": order_id,
            "status": "in_progress",
            "material_cost": mat_float,
            "voucher_id": voucher_id,
            "issued_items": issued_items_detail,
            "message": f"مواد اولیه با بهای {mat_float:,.0f} تومان به خط تولید منتقل شد و وضعیت سفارش به 'در حال تولید' تغییر یافت."
        }

    def complete_production(
        self,
        tenant_id: str,
        fiscal_year_id: str,
        order_id: str,
        warehouse_id: str,
        completion_date: str,
        actual_qty: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Complete production order:
        - Calculates total production cost: Material + Absorbed Labor + Factory Overhead
        - Calculates exact unit manufacturing cost
        - Receipts finished goods into destination warehouse
        - Balances WIP:
          Debit 1110 (Finished Goods) [Total Cost]
          Credit 1130 (WIP) [Material Cost]
          Credit 7020 (Labor Absorbed) [Labor Cost]
          Credit 7030 (Overhead Absorbed) [Overhead Cost]
        """
        with self.ledger.get_connection() as conn:
            ord_row = conn.execute(
                "SELECT * FROM production_orders WHERE tenant_id = ? AND id = ?",
                (tenant_id, order_id)
            ).fetchone()
            if not ord_row:
                raise ManufacturingError("سفارش تولید یافت نشد.")
            order = dict(ord_row)

            if order["status"] != "in_progress":
                raise ManufacturingError("تنها سفارش‌های 'در حال تولید' قابلیت تکمیل نهایی دارند.")

            bom_row = conn.execute("SELECT * FROM boms WHERE id = ?", (order["bom_id"],)).fetchone()
            bom = dict(bom_row)

        finished_qty = actual_qty if actual_qty is not None else order["planned_qty"]
        if finished_qty <= 0:
            raise ManufacturingError("تعداد واقعی محصول ساخته‌شده باید بزرگتر از صفر باشد.")

        fin_dec = Decimal(str(finished_qty))
        mat_dec = Decimal(str(order["material_cost"]))
        labor_dec = (fin_dec * Decimal(str(bom["direct_labor_rate"]))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        ovh_dec = (fin_dec * Decimal(str(bom["overhead_rate"]))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_cost_dec = mat_dec + labor_dec + ovh_dec
        unit_cost_dec = (total_cost_dec / fin_dec).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Update destination product in inventory and log Kardex
        with self.ledger.get_connection() as conn:
            target_prod_row = conn.execute(
                "SELECT * FROM products WHERE id = ?",
                (order["target_product_id"],)
            ).fetchone()
            if not target_prod_row:
                raise ManufacturingError("محصول هدف یافت نشد.")

            target_prod = dict(target_prod_row)
            old_qty = Decimal(str(target_prod["current_stock"]))
            old_avg = Decimal(str(target_prod["weighted_avg_cost"]))

            new_qty = old_qty + fin_dec
            new_total_val = (old_qty * old_avg) + total_cost_dec
            new_avg = (new_total_val / new_qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if new_qty > 0 else Decimal("0.0")

            conn.execute(
                "UPDATE products SET current_stock = ?, weighted_avg_cost = ? WHERE id = ?",
                (float(new_qty), float(new_avg), order["target_product_id"])
            )

            tx_id = str(uuid.uuid4())
            cur = conn.execute(
                "SELECT COALESCE(MAX(tx_number), 0) + 1 FROM inventory_transactions WHERE tenant_id = ?",
                (tenant_id,)
            )
            tx_num = cur.fetchone()[0]
            conn.execute("""
                INSERT INTO inventory_transactions (
                    id, tenant_id, fiscal_year_id, warehouse_id, product_id, tx_type, tx_number,
                    tx_date, quantity, unit_cost, total_cost, running_qty, running_avg_cost, description
                ) VALUES (?, ?, ?, ?, ?, 'production_receipt', ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tx_id, tenant_id, fiscal_year_id, warehouse_id, order["target_product_id"],
                tx_num, completion_date, float(fin_dec), float(unit_cost_dec), float(total_cost_dec),
                float(new_qty), float(new_avg), f"رسید محصول نهایی سفارش تولید {order['order_no']}"
            ))

        # Build balanced double-entry voucher
        voucher_items = [
            {
                "account_code": "1110",  # موجودی کالای تجاری/محصول ساخته شده در انبار
                "debit": float(total_cost_dec),
                "credit": 0.0,
                "description": f"رسید محصول نهایی سفارش تولید {order['order_no']} (تعداد {finished_qty})"
            },
            {
                "account_code": "1130",  # تسویه کالای در جریان ساخت
                "debit": 0.0,
                "credit": float(mat_dec),
                "description": f"تخصیص هزینه مواد مصرفی سفارش تولید {order['order_no']}"
            }
        ]

        if labor_dec > Decimal("0.00"):
            voucher_items.append({
                "account_code": "7020",  # دستمزد مستقیم جذب‌شده تولید
                "debit": 0.0,
                "credit": float(labor_dec),
                "description": f"دستمزد مستقیم جذب‌شده ساخت سفارش {order['order_no']}"
            })

        if ovh_dec > Decimal("0.00"):
            voucher_items.append({
                "account_code": "7030",  # سربار جذب‌شده ساخت و تولید
                "debit": 0.0,
                "credit": float(ovh_dec),
                "description": f"سربار ساخت و تولید جذب‌شده سفارش {order['order_no']}"
            })

        voucher_id = self.ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fiscal_year_id,
            entry_date=completion_date,
            description=f"سند بهای تمام‌شده و رسید محصول تولیدی (سفارش {order['order_no']})",
            items=voucher_items
        )

        with self.ledger.get_connection() as conn:
            conn.execute("""
                UPDATE production_orders
                SET status = 'completed', actual_qty = ?, labor_cost = ?,
                    overhead_cost = ?, total_cost = ?, unit_cost = ?,
                    completion_voucher_id = ?, end_date = ?
                WHERE id = ?
            """, (
                float(fin_dec), float(labor_dec), float(ovh_dec),
                float(total_cost_dec), float(unit_cost_dec),
                voucher_id, completion_date, order_id
            ))

        return {
            "order_id": order_id,
            "order_no": order["order_no"],
            "status": "completed",
            "actual_qty": float(fin_dec),
            "material_cost": float(mat_dec),
            "labor_cost": float(labor_dec),
            "overhead_cost": float(ovh_dec),
            "total_production_cost": float(total_cost_dec),
            "unit_cost": float(unit_cost_dec),
            "voucher_id": voucher_id,
            "message": f"سفارش تولید «{order['order_no']}» تکمیل شد. {finished_qty} واحد با بهای واحد {float(unit_cost_dec):,.0f} تومان وارد انبار شد."
        }

    def list_orders(self, tenant_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List production orders with current status and costs."""
        query = "SELECT * FROM production_orders WHERE tenant_id = ?"
        params = [tenant_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC"

        with self.ledger.get_connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        return [dict(r) for r in rows]

    def list_boms(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List active BOM formulas."""
        with self.ledger.get_connection() as conn:
            rows = conn.execute("""
                SELECT b.*, p.title as target_product_title
                FROM boms b
                JOIN products p ON b.target_product_id = p.id
                WHERE b.tenant_id = ? AND b.is_active = 1
                ORDER BY b.created_at DESC
            """, (tenant_id,)).fetchall()

        return [dict(r) for r in rows]
