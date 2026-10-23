import sys
import os
import tempfile
from pathlib import Path

# Add core to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ledger import ArbinLedger
from reports import ArbinReports
from inventory import ArbinInventory, InsufficientStockError, InventoryError


def _temp_db(name: str) -> str:
    return os.path.join(tempfile.gettempdir(), name)


def test_inventory_and_cogs():
    print("==================================================")
    print("ARBIN INVENTORY & COGS ENGINE (انبارداری و بهای تمام‌شده) - TEST")
    print("==================================================")

    db_test_path = _temp_db("arbin_inv_test.db")
    if os.path.exists(db_test_path):
        os.remove(db_test_path)

    ledger = ArbinLedger(db_path=db_test_path)
    reports = ArbinReports(ledger)
    inventory = ArbinInventory(ledger)

    # 1. Setup Tenant & Accounts
    tenant_id = ledger.create_tenant(name="شرکت بازرگانی قطعات سخت‌افزار آربین", currency="IRT")
    fy_id = ledger.create_fiscal_year(tenant_id, "سال مالی ۱۴۰۵", "2026-03-21", "2027-03-20")
    ledger.seed_standard_accounts(tenant_id)

    # Add Warehouse & Supplier
    wh_id = inventory.create_warehouse(tenant_id, "01", "انبار مرکزی تهران")
    supp_id = ledger.create_detail_account(tenant_id, "300201", "شرکت واردات رایانه پارس", "supplier")

    # Add Product: لپ‌تاپ ایسوس با نقطه سفارش ۵ عدد
    prod_id = inventory.create_product(
        tenant_id=tenant_id,
        sku="ASUS-ROG-16",
        title="لپ‌تاپ گیمینگ ایسوس ROG Zephyrus",
        unit="دستگاه",
        min_stock_alert=5.0,
        sale_price=80_000_000
    )
    print("OK انبار مرکزی و کالای تستی با موفقیت تعریف شدند.")

    # -------------------------------------------------------------
    # Batch 1: خرید و رسید پارت اول (۱۰ دستگاه با قیمت ۵۰ میلیون)
    # -------------------------------------------------------------
    r1 = inventory.record_receipt(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        warehouse_id=wh_id,
        product_id=prod_id,
        supplier_detail_id=supp_id,
        quantity=10,
        unit_cost=50_000_000,
        tx_date="2026-04-05"
    )
    print(f"OK رسید انبار شماره ۱: ورود ۱۰ دستگاه با نرخ ۵۰M (موجودی: {r1['new_stock']} | میانگین: {r1['new_avg_cost']:,.0f})")
    assert r1["new_stock"] == 10
    assert r1["new_avg_cost"] == 50_000_000

    # -------------------------------------------------------------
    # Batch 2: خرید و رسید پارت دوم (۱۰ دستگاه با قیمت ۶۰ میلیون)
    # میانگین موزون جدید: (10*50 + 10*60)/20 = 55 میلیون تومان
    # -------------------------------------------------------------
    r2 = inventory.record_receipt(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        warehouse_id=wh_id,
        product_id=prod_id,
        supplier_detail_id=supp_id,
        quantity=10,
        unit_cost=60_000_000,
        tx_date="2026-04-12"
    )
    print(f"OK رسید انبار شماره ۲: ورود ۱۰ دستگاه با نرخ ۶۰M (موجودی: {r2['new_stock']} | میانگین موزون: {r2['new_avg_cost']:,.0f})")
    assert r2["new_stock"] == 20
    assert r2["new_avg_cost"] == 55_000_000, f"خطای میانگین موزون: {r2['new_avg_cost']}"

    # -------------------------------------------------------------
    # Batch 3: حواله خروج انبار بابت فروش ۱۵ دستگاه
    # COGS = 15 * 55,000,000 = 825,000,000 تومان / باقی‌مانده: ۵
    # -------------------------------------------------------------
    d1 = inventory.record_delivery(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        warehouse_id=wh_id,
        product_id=prod_id,
        quantity=15,
        tx_date="2026-04-18"
    )
    print("OK حواله خروج انبار شماره ۱: خروج ۱۵ دستگاه بابت فروش:")
    print(f"  - نرخ بهای تمام‌شده واحد (COGS): {d1['unit_cogs']:,.0f} تومان")
    print(f"  - کل بهای تمام‌شده کالای فروش رفته: {d1['total_cogs']:,.0f} تومان")
    print(f"  - موجودی باقی‌مانده در انبار:      {d1['remaining_stock']} دستگاه")
    assert d1["total_cogs"] == 825_000_000
    assert d1["remaining_stock"] == 5

    # -------------------------------------------------------------
    # Step 4: بررسی تراز حساب‌های انبار و بهای تمام‌شده در دفتر کل
    # 1110 (موجودی کالا): 5 * 55M = 275,000,000
    # 7010 (بهای تمام شده): 825,000,000
    # 4010 (بستانکاران تجاری): 500M + 600M = 1,100,000,000
    # -------------------------------------------------------------
    tb = {row["code"]: row for row in reports.get_trial_balance(tenant_id)}
    assert tb["1110"]["balance_debit"] == 275_000_000, f"ارزش موجودی کالا اشتباه است: {tb['1110']['balance_debit']}"
    assert tb["7010"]["balance_debit"] == 825_000_000, f"بهای تمام‌شده اشتباه است: {tb['7010']['balance_debit']}"
    assert tb["4010"]["balance_credit"] == 1_100_000_000, f"بستانکاران اشتباه است: {tb['4010']['balance_credit']}"
    print("\n--------------------------------------------------")
    print("مانده‌های حسابداری خودکار تایید شدند:")
    print(f"  - حساب ۱۱۱۰ (موجودی ریالی انبار): {tb['1110']['balance_debit']:,.0f} تومان")
    print(f"  - حساب ۷۰۱۰ (بهای تمام‌شده فروش رفته): {tb['7010']['balance_debit']:,.0f} تومان")
    print(f"  - حساب ۴۰۱۰ (بستانکاری تامین‌کننده): {tb['4010']['balance_credit']:,.0f} تومان")

    # -------------------------------------------------------------
    # Step 5: آزمون جلوگیری از کسری انبار (Negative Test)
    # -------------------------------------------------------------
    insufficient_raised = False
    try:
        inventory.record_delivery(
            tenant_id=tenant_id,
            fiscal_year_id=fy_id,
            warehouse_id=wh_id,
            product_id=prod_id,
            quantity=10,
            tx_date="2026-04-20"
        )
    except InsufficientStockError as e:
        insufficient_raised = True
        print(f"OK سیستم امنیتی جلوگیری از منفی شدن انبار کار کرد: {e}")

    assert insufficient_raised, "خطا! سیستم اجازه داد انبار منفی شود!"

    # -------------------------------------------------------------
    # Step 6: هشدار هوشمند نقطه سفارش (Low Stock Alert)
    # -------------------------------------------------------------
    alerts = inventory.get_low_stock_alerts(tenant_id)
    print(f"\nهشدارهای هوشمند کسری کالا: {len(alerts)} کالا در مرز ناموجودی")
    for a in alerts:
        print(f"  - کالا: {a['title']} | موجودی: {a['current_stock']} (حداقل مجاز: {a['min_stock_alert']})")
    assert len(alerts) == 1
    assert alerts[0]["current_stock"] == 5

    # -------------------------------------------------------------
    # Step 7: گزارش کاردکس کالا (Stock Kardex)
    # -------------------------------------------------------------
    kardex = inventory.get_stock_kardex(prod_id)
    print("\n--------------------------------------------------")
    print("کاردکس تعدادی و ریالی کالا:")
    print("--------------------------------------------------")
    for k in kardex:
        print(f"[{k['date']}] {k['tx_type']} | تعداد: {k['quantity']} | نرخ: {k['unit_cost']:,.0f} | مانده: {k['running_qty']}")
    assert len(kardex) == 3

    # -------------------------------------------------------------
    # Step 8: برگشت فروش (۲ دستگاه) -> موجودی ۷، کاهش COGS
    # -------------------------------------------------------------
    sr = inventory.record_sales_return(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        warehouse_id=wh_id,
        product_id=prod_id,
        quantity=2,
        tx_date="2026-04-25"
    )
    assert sr["new_stock"] == 7
    tb = {row["code"]: row for row in reports.get_trial_balance(tenant_id)}
    assert tb["1110"]["balance_debit"] == 385_000_000  # 7 * 55M
    assert tb["7010"]["balance_debit"] == 715_000_000  # 825M - 110M
    print("OK برگشت فروش ۲ دستگاه: موجودی ۷ عدد / COGS کاهش یافت.")

    # -------------------------------------------------------------
    # Step 9: مغایرت شمارش انبار (کسری ۱ عدد)
    # -------------------------------------------------------------
    rc = inventory.record_stock_reconciliation(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        warehouse_id=wh_id,
        product_id=prod_id,
        counted_quantity=6,
        tx_date="2026-04-28"
    )
    assert rc["new_stock"] == 6
    tb = {row["code"]: row for row in reports.get_trial_balance(tenant_id)}
    assert tb["1110"]["balance_debit"] == 330_000_000  # 6 * 55M
    assert tb["7010"]["balance_debit"] == 770_000_000  # 715M + 55M

    # شمارش با موجودی فعلی یکسان باید خطا بدهد
    try:
        inventory.record_stock_reconciliation(
            tenant_id=tenant_id,
            fiscal_year_id=fy_id,
            warehouse_id=wh_id,
            product_id=prod_id,
            counted_quantity=6,
            tx_date="2026-04-29"
        )
        raise AssertionError("مغایرت بدون تفاوت باید رد شود.")
    except InventoryError:
        pass
    print("OK مغایرت شمارش انبار (کسری + اعتبارسنجی) تایید شد.")

    # -------------------------------------------------------------
    # Step 10: ترازنامه در پایان عملیات انبار متوازن است
    # -------------------------------------------------------------
    bs = reports.get_balance_sheet(tenant_id, fy_id)
    assert bs["is_balanced"], "ترازنامه پس از عملیات انبار نامتوازن است!"

    products = inventory.list_products(tenant_id)
    assert len(products) == 1
    summary = inventory.get_stock_summary(tenant_id)
    assert summary["sku_count"] == 1
    assert summary["inventory_value"] == 330_000_000

    print("\n==================================================")
    print("ALL INVENTORY & COGS TESTS PASSED!")
    print("==================================================")


if __name__ == "__main__":
    test_inventory_and_cogs()
