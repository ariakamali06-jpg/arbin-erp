"""
Unit Tests for Arbin Manufacturing & BOM Engine (تست سیستم تولید و بهای تمام‌شده صنعتی)
========================================================================================
Verifies:
1. Product and Raw Material definitions in perpetual warehouse.
2. Bill of Materials (BOM / فرمول ساخت) creation with waste percentage.
3. Issuing raw materials to line: Debit 1130 (WIP) / Credit 1120 (Raw Materials).
4. Direct labor and factory overhead allocation.
5. Receipt of finished products into warehouse at exact unit manufacturing cost.
6. Consolidated balanced voucher:
   Debit 1110 (Finished Goods) / Credit 1130 (WIP), Credit 7020 (Labor), Credit 7030 (Overhead).
7. Strict trial balance mathematical equilibrium.
"""

import os
import sys
import tempfile
from pathlib import Path

# Add workspace to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ledger import ArbinLedger
from inventory import ArbinInventory
from manufacturing import ArbinManufacturing, ManufacturingError


def _temp_db(name: str) -> str:
    return os.path.join(tempfile.gettempdir(), name)


def test_manufacturing_suite():
    print("==================================================")
    print("ARBIN MANUFACTURING & BOM INDUSTRIAL ENGINE - TEST")
    print("==================================================")

    db_path = _temp_db("arbin_mfg_test.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    ledger = ArbinLedger(db_path=db_path)
    inv = ArbinInventory(ledger)
    mfg = ArbinManufacturing(ledger, inventory=inv)

    tenant_id = ledger.create_tenant("کارخانه تولیدی صنعتی آریا پنجره", "14001122334")
    fy_id = ledger.create_fiscal_year(tenant_id, "1405", "2026-03-21", "2027-03-20")
    ledger.seed_standard_accounts(tenant_id)

    # 1. Setup Warehouse, Supplier Detail & Products
    wh_id = inv.create_warehouse(tenant_id, "انبار مرکزی مواد و قطعات", "تهران، شهرک صنعتی شمس‌آباد")
    supp_id = ledger.create_sub_ledger(tenant_id, "supplier", "4010", "شرکت تامین فلزات البرز", "14009988771")
    raw1_id = inv.create_product(tenant_id, "RM-ALU-01", "پروفیل آلومینیوم ترمال‌بریک", "شاخه", min_stock_alert=5.0, sale_price=600_000)
    raw2_id = inv.create_product(tenant_id, "RM-PNT-01", "رنگ الکترواستاتیک ضدخش", "کیلوگرم", min_stock_alert=2.0, sale_price=250_000)
    fin_id = inv.create_product(tenant_id, "FG-WIN-01", "پنجره دوجداره آلومینیومی سایز ۱۲۰x۱۵۰", "عدد", min_stock_alert=1.0, sale_price=2_500_000)

    print("OK انبار مرکزی، مواد اولیه و محصول نهایی تعریف شدند.")

    # 2. Receive Initial Raw Materials into Warehouse
    # 50 branches of aluminum @ 500,000 = 25,000,000
    # 20 kg of paint @ 200,000 = 4,000,000
    inv.record_receipt(tenant_id, fy_id, wh_id, raw1_id, supplier_detail_id=supp_id, quantity=50, unit_cost=500_000, tx_date="2026-04-01")
    inv.record_receipt(tenant_id, fy_id, wh_id, raw2_id, supplier_detail_id=supp_id, quantity=20, unit_cost=200_000, tx_date="2026-04-01")
    print("OK مواد اولیه با موفقیت وارد انبار شدند.")

    # 3. Create Bill of Materials (BOM)
    # Per window:
    # - 2 branches of aluminum (0% waste) -> 2 * 500,000 = 1,000,000
    # - 1 kg of paint (5% waste -> 1.05 kg) -> 1.05 * 200,000 = 210,000
    # - Direct labor: 150,000
    # - Factory overhead: 80,000
    # Estimated standard unit cost = 1,000,000 + 210,000 + 150,000 + 80,000 = 1,440,000
    bom_res = mfg.create_bom(
        tenant_id=tenant_id,
        target_product_id=fin_id,
        title="فرمول استاندارد پنجره ترمال‌بریک ۱۲۰x۱۵۰",
        standard_qty=1.0,
        direct_labor_rate=150_000,
        overhead_rate=80_000,
        items=[
            {"raw_material_id": raw1_id, "qty_required": 2.0, "waste_percentage": 0.0},
            {"raw_material_id": raw2_id, "qty_required": 1.0, "waste_percentage": 5.0}
        ]
    )
    bom_id = bom_res["id"]
    print("OK فرمول ساخت (BOM) با موفقیت ثبت شد:", bom_res["title"])

    # 4. Create Production Work Order for 10 windows
    order_res = mfg.create_production_order(
        tenant_id=tenant_id,
        order_no="WO-1405-001",
        bom_id=bom_id,
        planned_qty=10.0,
        start_date="2026-04-05",
        end_date="2026-04-10"
    )
    order_id = order_res["id"]
    print("OK سفارش تولید ۱۰ دستگاه پنجره صادر شد:", order_res["order_no"])

    # 5. Start Production & Issue Materials to Line (WIP)
    # Needs:
    # - Aluminum: 10 * 2 = 20 branches @ 500,000 = 10,000,000
    # - Paint: 10 * 1.05 = 10.5 kg @ 200,000 = 2,100,000
    # Total Material Cost = 12,100,000
    print("\n--------------------------------------------------")
    print("آغاز تولید و حواله مصرف مواد اولیه به خط تولید (WIP):")
    print("--------------------------------------------------")
    start_res = mfg.start_production(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        order_id=order_id,
        warehouse_id=wh_id,
        issue_date="2026-04-05"
    )
    assert start_res["status"] == "in_progress"
    assert start_res["material_cost"] == 12_100_000.0
    print("OK سند مصرف مواد اولیه صادر شد:")
    print("  - کالای در جریان ساخت بدهکار (کد ۱۱۳۰): 12,100,000 تومان")
    print("  - موجودی مواد اولیه بستانکار (کد ۱۱۲۰):  12,100,000 تومان")

    # Verify inventory was perpetually deducted:
    # Aluminum was 50, now 30
    # Paint was 20, now 9.5
    alu_stock = inv.get_product(raw1_id)["current_stock"]
    pnt_stock = inv.get_product(raw2_id)["current_stock"]
    assert alu_stock == 30.0, f"موجودی آلومینیوم باید ۳۰ باشد، دریافت شد: {alu_stock}"
    assert pnt_stock == 9.5, f"موجودی رنگ باید ۹.۵ باشد، دریافت شد: {pnt_stock}"
    print("OK موجودی انبار به صورت دائمی کاهش یافت (آلومینیوم: ۳۰ شاخه / رنگ: ۹.۵ کیلو).")

    # 6. Complete Production
    # Total Labor for 10 units = 10 * 150,000 = 1,500,000
    # Total Overhead for 10 units = 10 * 80,000 = 800,000
    # Total Cost = 12,100,000 (Mat) + 1,500,000 (Labor) + 800,000 (Ovh) = 14,400,000
    # Unit Cost = 14,400,000 / 10 = 1,440,000
    print("\n--------------------------------------------------")
    print("تکمیل سفارش تولید و محاسبه بهای تمام‌شده قطعی محصول:")
    print("--------------------------------------------------")
    comp_res = mfg.complete_production(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        order_id=order_id,
        warehouse_id=wh_id,
        completion_date="2026-04-10",
        actual_qty=10.0
    )
    assert comp_res["status"] == "completed"
    assert comp_res["total_production_cost"] == 14_400_000.0
    assert comp_res["unit_cost"] == 1_440_000.0
    print("OK بهای تمام‌شده قطعی محاسبه و سند دوبل صنعتی صادر شد:")
    print(f"  - کل بهای تمام‌شده: {comp_res['total_production_cost']:,.0f} تومان")
    print(f"  - بهای تمام‌شده هر واحد: {comp_res['unit_cost']:,.0f} تومان")
    print("  - آرتیکل‌های سند دوبل:")
    print("    * موجودی کالای ساخته‌شده در انبار (کد ۱۱۱۰): 14,400,000 (بدهکار)")
    print("    * تسویه کالای در جریان ساخت (کد ۱۱۳۰):       12,100,000 (بستانکار)")
    print("    * دستمزد مستقیم جذب‌شده ساخت (کد ۷۰۲۰):      1,500,000 (بستانکار)")
    print("    * سربار جذب‌شده ساخت و تولید (کد ۷۰۳۰):         800,000 (بستانکار)")

    # 7. Verify Finished Product In Warehouse
    fin_stock = inv.get_product(fin_id)
    assert fin_stock["current_stock"] == 10.0
    assert fin_stock["weighted_avg_cost"] == 1_440_000.0
    print("\nOK ۱۰ دستگاه پنجره دوجداره با نرخ میانگین موزون ۱,۴۴۰,۰۰۰ تومان در انبار محصول قرار گرفت.")

    # 8. Check Trial Balance Equilibrium
    from reports import ArbinReports
    rep = ArbinReports(ledger)
    tb = rep.get_trial_balance(tenant_id, fiscal_year_id=fy_id, level="subsidiary")
    tot_td = sum(r["total_debit"] for r in tb)
    tot_tc = sum(r["total_credit"] for r in tb)
    tot_bd = sum(r["balance_debit"] for r in tb)
    tot_bc = sum(r["balance_credit"] for r in tb)
    assert abs(tot_td - tot_tc) < 0.01
    assert abs(tot_bd - tot_bc) < 0.01
    print("OK تراز آزمایشی پس از کلیه فرایندهای تولید و بهای تمام‌شده صنعتی ۱۰۰٪ متوازن است.")

    print("\n==================================================")
    print("ALL MANUFACTURING & BOM TESTS PASSED (100%)!")
    print("==================================================")


if __name__ == "__main__":
    test_manufacturing_suite()
