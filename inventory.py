"""
Arbin Inventory & Warehouse Management Engine (سیستم انبارداری و بهای تمام‌شده آربین)
- Multi-Warehouse Support (پشتیبانی از چندین انبار مجزا)
- Perpetual Inventory System & Weighted Average Costing (سیستم ثبت دائم و میانگین موزون)
- Automatic Double-Entry Voucher Generation for Receipts & Deliveries (COGS)
- Real-Time Product Kardex (کاردکس تعدادی و ریالی)
- Low-Stock Automated Alerts (سیستم هشدار هوشمند نقطه سفارش کالا)
"""

import uuid
from typing import List, Dict, Any, Optional
from decimal import Decimal, ROUND_HALF_UP

class InventoryError(Exception):
    pass

class InsufficientStockError(InventoryError):
    pass


class ArbinInventory:
    def __init__(self, ledger):
        self.ledger = ledger

    def create_warehouse(self, tenant_id: str, code: str, title: str, location: Optional[str] = None) -> str:
        wh_id = str(uuid.uuid4())
        with self.ledger.get_connection() as conn:
            conn.execute(
                "INSERT INTO warehouses (id, tenant_id, code, title, location) VALUES (?, ?, ?, ?, ?)",
                (wh_id, tenant_id, code, title, location)
            )
        return wh_id

    def create_product(
        self,
        tenant_id: str,
        sku: str,
        title: str,
        unit: str = "عدد",
        min_stock_alert: float = 5.0,
        sale_price: float = 0.0,
        barcode: Optional[str] = None
    ) -> str:
        prod_id = str(uuid.uuid4())
        with self.ledger.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO products (id, tenant_id, sku, barcode, title, unit, min_stock_alert, sale_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (prod_id, tenant_id, sku, barcode, title, unit, min_stock_alert, sale_price)
            )
        return prod_id

    def record_receipt(
        self,
        tenant_id: str,
        fiscal_year_id: str,
        warehouse_id: str,
        product_id: str,
        supplier_detail_id: str,
        quantity: float,
        unit_cost: float,
        tx_date: str,
        description: Optional[str] = None,
        user_id: str = "system"
    ) -> Dict[str, Any]:
        """
        Record Goods Receipt / Purchase (رسید انبار / خرید کالا):
        1. Updates Product current_stock and recalculates weighted average cost.
        2. Logs to inventory_transactions (Kardex).
        3. Automatic Double-Entry Voucher:
           - Debit: 1110 (موجودی کالای تجاری در انبار)
           - Credit: 4010 (حساب‌های پرداختنی تجاری / تامین‌کننده)
        """
        if quantity <= 0 or unit_cost < 0:
            raise InventoryError("تعداد و قیمت خرید کالا باید مقادیر معتبر باشند.")

        with self.ledger.get_connection() as conn:
            prod = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            if not prod:
                raise InventoryError("کالای مورد نظر یافت نشد.")

            supp = conn.execute("SELECT code, title FROM sub_ledgers WHERE id = ?", (supplier_detail_id,)).fetchone()
            if not supp:
                raise InventoryError("حساب تفصیلی تامین‌کننده یافت نشد.")

            old_qty = Decimal(str(prod["current_stock"]))
            old_avg = Decimal(str(prod["weighted_avg_cost"]))
            in_qty = Decimal(str(quantity))
            in_cost = Decimal(str(unit_cost))

            # Weighted Average Cost Formula:
            # new_avg = ((old_qty * old_avg) + (in_qty * in_cost)) / (old_qty + in_qty)
            new_qty = old_qty + in_qty
            new_total_val = (old_qty * old_avg) + (in_qty * in_cost)
            new_avg = (new_total_val / new_qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if new_qty > 0 else Decimal("0.0")

            total_receipt_cost = (in_qty * in_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # Update product stock and avg cost
            conn.execute(
                "UPDATE products SET current_stock = ?, weighted_avg_cost = ? WHERE id = ?",
                (float(new_qty), float(new_avg), product_id)
            )

            # Atomic transaction number
            cur = conn.execute(
                "SELECT COALESCE(MAX(tx_number), 0) + 1 FROM inventory_transactions WHERE tenant_id = ? AND tx_type = 'purchase_receipt'",
                (tenant_id,)
            )
            tx_num = cur.fetchone()[0]

            tx_id = str(uuid.uuid4())
            desc = description or f"رسید انبار شماره {tx_num} - خرید کالا از {supp['title']}"

            # Insert Kardex record
            conn.execute(
                """
                INSERT INTO inventory_transactions (
                    id, tenant_id, fiscal_year_id, warehouse_id, product_id, tx_type, tx_number,
                    tx_date, quantity, unit_cost, total_cost, running_qty, running_avg_cost, description
                ) VALUES (?, ?, ?, ?, ?, 'purchase_receipt', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tx_id, tenant_id, fiscal_year_id, warehouse_id, product_id, tx_num,
                    tx_date, float(in_qty), float(in_cost), float(total_receipt_cost),
                    float(new_qty), float(new_avg), desc
                )
            )

        # Automatic Accounting Voucher
        voucher_items = [
            {
                "account_code": "1110",
                "detail_code": None,
                "description": f"ورود کالا به انبار طبق رسید شماره {tx_num} ({prod['title']})",
                "debit": float(total_receipt_cost),
                "credit": 0
            },
            {
                "account_code": "4010",
                "detail_code": supp["code"],
                "description": f"بستانکاری تامین‌کننده طبق رسید انبار شماره {tx_num}",
                "debit": 0,
                "credit": float(total_receipt_cost)
            }
        ]

        entry_id = self.ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fiscal_year_id,
            entry_date=tx_date,
            description=desc,
            items=voucher_items,
            manual_number=str(tx_num),
            source_module="inventory",
            user_id=user_id
        )

        with self.ledger.get_connection() as conn:
            conn.execute("UPDATE inventory_transactions SET journal_entry_id = ? WHERE id = ?", (entry_id, tx_id))

        return {
            "transaction_id": tx_id,
            "receipt_number": tx_num,
            "quantity": float(in_qty),
            "unit_cost": float(in_cost),
            "total_cost": float(total_receipt_cost),
            "new_stock": float(new_qty),
            "new_avg_cost": float(new_avg),
            "journal_entry_id": entry_id
        }

    def record_delivery(
        self,
        tenant_id: str,
        fiscal_year_id: str,
        warehouse_id: str,
        product_id: str,
        quantity: float,
        tx_date: str,
        reference_id: Optional[str] = None,
        description: Optional[str] = None,
        user_id: str = "system"
    ) -> Dict[str, Any]:
        """
        Record Goods Delivery / Sales Outflow (حواله خروج انبار بابت فروش کالا):
        1. Checks available stock.
        2. Values outgoing goods at current weighted average cost (COGS).
        3. Updates running stock.
        4. Automatic Double-Entry Voucher for Cost of Goods Sold:
           - Debit: 7010 (بهای تمام‌شده کالای فروش رفته)
           - Credit: 1110 (موجودی کالای تجاری در انبار)
        """
        if quantity <= 0:
            raise InventoryError("تعداد خروج کالا باید مثبت باشد.")

        with self.ledger.get_connection() as conn:
            prod = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            if not prod:
                raise InventoryError("کالای مورد نظر یافت نشد.")

            current_stock = Decimal(str(prod["current_stock"]))
            out_qty = Decimal(str(quantity))

            if out_qty > current_stock:
                raise InsufficientStockError(
                    f"کسری موجودی انبار! موجودی فعلی: {current_stock}، تعداد درخواستی برای خروج: {out_qty}"
                )

            avg_cost = Decimal(str(prod["weighted_avg_cost"]))
            new_qty = current_stock - out_qty
            total_delivery_cost = (out_qty * avg_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # Update product stock
            conn.execute("UPDATE products SET current_stock = ? WHERE id = ?", (float(new_qty), product_id))

            # Atomic transaction number
            cur = conn.execute(
                "SELECT COALESCE(MAX(tx_number), 0) + 1 FROM inventory_transactions WHERE tenant_id = ? AND tx_type = 'sales_delivery'",
                (tenant_id,)
            )
            tx_num = cur.fetchone()[0]

            tx_id = str(uuid.uuid4())
            desc = description or f"حواله خروج انبار شماره {tx_num} بابت فروش کالا ({prod['title']})"

            conn.execute(
                """
                INSERT INTO inventory_transactions (
                    id, tenant_id, fiscal_year_id, warehouse_id, product_id, tx_type, tx_number,
                    reference_id, tx_date, quantity, unit_cost, total_cost, running_qty,
                    running_avg_cost, description
                ) VALUES (?, ?, ?, ?, ?, 'sales_delivery', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tx_id, tenant_id, fiscal_year_id, warehouse_id, product_id, tx_num,
                    reference_id, tx_date, float(out_qty), float(avg_cost), float(total_delivery_cost),
                    float(new_qty), float(avg_cost), desc
                )
            )

        # Automatic COGS Accounting Voucher: Debit 7010 / Credit 1110
        voucher_items = [
            {
                "account_code": "7010",
                "detail_code": None,
                "description": f"بهای تمام‌شده کالا طبق حواله خروج انبار شماره {tx_num}",
                "debit": float(total_delivery_cost),
                "credit": 0
            },
            {
                "account_code": "1110",
                "detail_code": None,
                "description": f"خروج کالای تجاری از انبار طبق حواله شماره {tx_num}",
                "debit": 0,
                "credit": float(total_delivery_cost)
            }
        ]

        entry_id = self.ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fiscal_year_id,
            entry_date=tx_date,
            description=desc,
            items=voucher_items,
            manual_number=str(tx_num),
            source_module="inventory",
            user_id=user_id
        )

        with self.ledger.get_connection() as conn:
            conn.execute("UPDATE inventory_transactions SET journal_entry_id = ? WHERE id = ?", (entry_id, tx_id))

        return {
            "transaction_id": tx_id,
            "delivery_number": tx_num,
            "quantity": float(out_qty),
            "unit_cogs": float(avg_cost),
            "total_cogs": float(total_delivery_cost),
            "remaining_stock": float(new_qty),
            "journal_entry_id": entry_id
        }

    def get_stock_kardex(self, product_id: str) -> List[Dict[str, Any]]:
        """
        Get Chronological Stock Kardex (کاردکس تعدادی و ریالی کالا)
        """
        with self.ledger.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT it.*, w.title as warehouse_title
                FROM inventory_transactions it
                JOIN warehouses w ON it.warehouse_id = w.id
                WHERE it.product_id = ?
                ORDER BY it.tx_date ASC, it.created_at ASC
                """,
                (product_id,)
            ).fetchall()

            return [
                {
                    "tx_number": r["tx_number"],
                    "tx_type": self.TX_LABELS.get(r["tx_type"], r["tx_type"]),
                    "tx_code": r["tx_type"],
                    "date": r["tx_date"],
                    "warehouse": r["warehouse_title"],
                    "quantity": r["quantity"],
                    "unit_cost": r["unit_cost"],
                    "total_cost": r["total_cost"],
                    "running_qty": r["running_qty"],
                    "running_avg_cost": r["running_avg_cost"],
                    "description": r["description"]
                }
                for r in rows
            ]

    def get_low_stock_alerts(self, tenant_id: str) -> List[Dict[str, Any]]:
        """
        Automated Low-Stock Warning (هشدار کسر موجودی زیر نقطه سفارش)
        """
        with self.ledger.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT sku, title, unit, current_stock, min_stock_alert, weighted_avg_cost
                FROM products
                WHERE tenant_id = ? AND current_stock <= min_stock_alert AND is_active = 1
                ORDER BY current_stock ASC
                """,
                (tenant_id,)
            ).fetchall()

            return [
                {
                    "sku": r["sku"],
                    "title": r["title"],
                    "unit": r["unit"],
                    "current_stock": r["current_stock"],
                    "min_stock_alert": r["min_stock_alert"],
                    "avg_cost": r["weighted_avg_cost"],
                    "status": "CRITICAL" if r["current_stock"] == 0 else "WARNING"
                }
                for r in rows
            ]

    # ------------------------------------------------------------------
    # Catalogue helpers (کاتالوگ کالاها و انبارها)
    # ------------------------------------------------------------------
    TX_LABELS = {
        "purchase_receipt": "رسید خرید",
        "sales_delivery": "حواله فروش",
        "purchase_return": "برگشت خرید",
        "sales_return": "برگشت فروش",
        "stock_reconciliation": "مغایرت انبار",
    }

    def list_products(self, tenant_id: str, include_inactive: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM products WHERE tenant_id = ?"
        if not include_inactive:
            sql += " AND is_active = 1"
        sql += " ORDER BY title"
        with self.ledger.get_connection() as conn:
            rows = conn.execute(sql, (tenant_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_product(self, product_id: str) -> Dict[str, Any]:
        with self.ledger.get_connection() as conn:
            row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if not row:
            raise InventoryError("کالای مورد نظر یافت نشد.")
        return dict(row)

    def list_warehouses(self, tenant_id: str) -> List[Dict[str, Any]]:
        with self.ledger.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM warehouses WHERE tenant_id = ? AND is_active = 1 ORDER BY code",
                (tenant_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_stock_summary(self, tenant_id: str) -> Dict[str, Any]:
        with self.ledger.get_connection() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(current_stock * weighted_avg_cost), 0) AS value,
                       COUNT(*) AS sku_count,
                       SUM(CASE WHEN current_stock <= min_stock_alert THEN 1 ELSE 0 END) AS low_count
                FROM products WHERE tenant_id = ? AND is_active = 1
                """,
                (tenant_id,),
            ).fetchone()
        return {
            "inventory_value": float(row["value"] or 0),
            "sku_count": int(row["sku_count"] or 0),
            "low_stock_count": int(row["low_count"] or 0),
        }

    # ------------------------------------------------------------------
    # Returns & reconciliation (برگشت و مغایرت انبار)
    # ------------------------------------------------------------------
    def _next_tx_number(self, conn, tenant_id: str, tx_type: str) -> int:
        cur = conn.execute(
            "SELECT COALESCE(MAX(tx_number), 0) + 1 FROM inventory_transactions "
            "WHERE tenant_id = ? AND tx_type = ?",
            (tenant_id, tx_type),
        )
        return int(cur.fetchone()[0])

    def _apply_stock_change(
        self,
        tenant_id: str,
        fiscal_year_id: str,
        warehouse_id: str,
        product_id: str,
        tx_type: str,
        quantity: float,
        tx_date: str,
        direction: int,          # +1 in, -1 out
        unit_cost: Optional[float] = None,
        reference_id: Optional[str] = None,
        description: Optional[str] = None,
        user_id: str = "system",
        voucher_items: Optional[List[Dict[str, Any]]] = None,
        entry_description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Shared Kardex writer + optional automatic voucher."""
        with self.ledger.get_connection() as conn:
            prod = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            if not prod:
                raise InventoryError("کالای مورد نظر یافت نشد.")
            old_qty = Decimal(str(prod["current_stock"]))
            old_avg = Decimal(str(prod["weighted_avg_cost"]))
            qty = Decimal(str(quantity))

            if direction < 0 and qty > old_qty:
                raise InsufficientStockError(
                    f"کسری موجودی انبار! موجودی فعلی: {old_qty}، تعداد درخواستی برای خروج: {qty}"
                )

            if direction > 0 and unit_cost is not None:
                cost = Decimal(str(unit_cost))
                new_qty = old_qty + qty
                new_avg = (
                    ((old_qty * old_avg) + (qty * cost)) / new_qty
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if new_qty > 0 else Decimal("0")
            else:
                new_qty = old_qty + (qty if direction > 0 else -qty)
                new_avg = old_avg if new_qty > 0 else Decimal("0")

            effective_cost = Decimal(str(unit_cost)) if unit_cost is not None else old_avg
            total_cost = (qty * effective_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            conn.execute(
                "UPDATE products SET current_stock = ?, weighted_avg_cost = ? WHERE id = ?",
                (float(new_qty), float(new_avg), product_id),
            )

            tx_num = self._next_tx_number(conn, tenant_id, tx_type)
            tx_id = str(uuid.uuid4())
            desc = description or f"{self.TX_LABELS.get(tx_type, tx_type)} شماره {tx_num}"
            conn.execute(
                """
                INSERT INTO inventory_transactions (
                    id, tenant_id, fiscal_year_id, warehouse_id, product_id, tx_type, tx_number,
                    reference_id, tx_date, quantity, unit_cost, total_cost, running_qty,
                    running_avg_cost, description
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tx_id, tenant_id, fiscal_year_id, warehouse_id, product_id, tx_type, tx_num,
                    reference_id, tx_date, abs(float(qty)), float(effective_cost),
                    float(total_cost), float(new_qty), float(new_avg), desc,
                ),
            )

        entry_id = None
        if voucher_items:
            entry_id = self.ledger.record_journal_entry(
                tenant_id=tenant_id,
                fiscal_year_id=fiscal_year_id,
                entry_date=tx_date,
                description=entry_description or desc,
                items=voucher_items,
                manual_number=str(tx_num),
                source_module="inventory",
                source_id=tx_id,
                user_id=user_id,
            )
            with self.ledger.get_connection() as conn:
                conn.execute(
                    "UPDATE inventory_transactions SET journal_entry_id = ? WHERE id = ?",
                    (entry_id, tx_id),
                )

        return {
            "transaction_id": tx_id,
            "tx_number": tx_num,
            "tx_type": tx_type,
            "quantity": float(qty),
            "direction": direction,
            "total_cost": float(total_cost),
            "new_stock": float(new_qty),
            "new_avg_cost": float(new_avg),
            "journal_entry_id": entry_id,
        }

    def record_sales_return(
        self,
        tenant_id: str,
        fiscal_year_id: str,
        warehouse_id: str,
        product_id: str,
        quantity: float,
        tx_date: str,
        description: Optional[str] = None,
        user_id: str = "system",
    ) -> Dict[str, Any]:
        """برگشت فروش: افزایش موجودی - Debit 1110 / Credit 7010 (کاهش بهای تمام شده)"""
        if quantity <= 0:
            raise InventoryError("تعداد برگشت باید مثبت باشد.")
        prod = self.get_product(product_id)
        unit_cost = float(prod["weighted_avg_cost"])
        total = round(quantity * unit_cost, 2)
        return self._apply_stock_change(
            tenant_id, fiscal_year_id, warehouse_id, product_id,
            tx_type="sales_return", quantity=quantity, tx_date=tx_date, direction=1,
            description=description, user_id=user_id,
            voucher_items=[
                {"account_code": "1110", "description": "برگشت کالا به انبار بابت فروش",
                 "debit": total, "credit": 0},
                {"account_code": "7010", "description": "کاهش بهای تمام شده بابت برگشت فروش",
                 "debit": 0, "credit": total},
            ],
            entry_description=f"سند برگشت فروش {prod['title']}",
        )

    def record_purchase_return(
        self,
        tenant_id: str,
        fiscal_year_id: str,
        warehouse_id: str,
        product_id: str,
        supplier_detail_id: str,
        quantity: float,
        tx_date: str,
        description: Optional[str] = None,
        user_id: str = "system",
    ) -> Dict[str, Any]:
        """برگشت خرید: کاهش موجودی - Debit 4010 / Credit 1110"""
        if quantity <= 0:
            raise InventoryError("تعداد برگشت باید مثبت باشد.")
        prod = self.get_product(product_id)
        with self.ledger.get_connection() as conn:
            supp = conn.execute(
                "SELECT code, title FROM sub_ledgers WHERE id = ?", (supplier_detail_id,)
            ).fetchone()
            if not supp:
                raise InventoryError("حساب تفصیلی تامین‌کننده یافت نشد.")
        unit_cost = float(prod["weighted_avg_cost"])
        total = round(quantity * unit_cost, 2)
        return self._apply_stock_change(
            tenant_id, fiscal_year_id, warehouse_id, product_id,
            tx_type="purchase_return", quantity=quantity, tx_date=tx_date, direction=-1,
            description=description, user_id=user_id,
            voucher_items=[
                {"account_code": "4010", "sub_ledger_code": supp["code"],
                 "description": f"کاهش بدهی به {supp['title']} بابت برگشت کالا",
                 "debit": total, "credit": 0},
                {"account_code": "1110", "description": "خروج کالای برگشتی از انبار",
                 "debit": 0, "credit": total},
            ],
            entry_description=f"سند برگشت خرید {prod['title']}",
        )

    def record_stock_reconciliation(
        self,
        tenant_id: str,
        fiscal_year_id: str,
        warehouse_id: str,
        product_id: str,
        counted_quantity: float,
        tx_date: str,
        description: Optional[str] = None,
        user_id: str = "system",
    ) -> Dict[str, Any]:
        """
        مغایرت شمارش انبار (stock_reconciliation)
        کسری:  Debit 7010 / Credit 1110     |     اضافی: Debit 1110 / Credit 7010
        """
        prod = self.get_product(product_id)
        current = float(prod["current_stock"])
        diff = round(float(counted_quantity) - current, 6)
        if abs(diff) < 1e-9:
            raise InventoryError("مقدار شمارش‌شده با موجودی فعلی یکسان است.")
        unit_cost = float(prod["weighted_avg_cost"])
        total = round(abs(diff) * unit_cost, 2)
        if diff > 0:  # overage
            items = [
                {"account_code": "1110", "description": "افزایش موجودی بر اساس شمارش انبار",
                 "debit": total, "credit": 0},
                {"account_code": "7010", "description": "کاهش بهای تمام شده بابت اضافی انبار",
                 "debit": 0, "credit": total},
            ]
        else:  # shortage
            items = [
                {"account_code": "7010", "description": "افزایش بهای تمام شده بابت کسری انبار",
                 "debit": total, "credit": 0},
                {"account_code": "1110", "description": "کاهش موجودی بر اساس شمارش انبار",
                 "debit": 0, "credit": total},
            ]
        return self._apply_stock_change(
            tenant_id, fiscal_year_id, warehouse_id, product_id,
            tx_type="stock_reconciliation", quantity=abs(diff), tx_date=tx_date,
            direction=1 if diff > 0 else -1, description=description, user_id=user_id,
            voucher_items=items,
            entry_description=f"سند مغایرت انبار {prod['title']}",
        )
