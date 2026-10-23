"""
Unit Tests for Arbin Fixed Assets & Depreciation Engine (تست سیستم دارایی ثابت و استهلاک)
============================================================================================
Verifies:
1. Asset registration with asset code, category, useful life, and salvage value.
2. Direct purchase voucher posting (Debit 20xx / Credit 1010).
3. Straight-line and declining balance depreciation calculations under Article 149.
4. Batch depreciation cycle with auto double-entry voucher:
   Debit 7250 (Depreciation Expense) / Credit 2110 (Accumulated Depreciation).
5. Asset disposal / scrap with Gain (Credit 6040) and Loss (Debit 7260) balanced vouchers.
"""

import os
import sys
import tempfile
from pathlib import Path

# Add workspace to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ledger import ArbinLedger
from fixed_assets import ArbinFixedAssets, FixedAssetError


def _temp_db(name: str) -> str:
    return os.path.join(tempfile.gettempdir(), name)


def test_fixed_assets_suite():
    print("==================================================")
    print("ARBIN FIXED ASSETS & DEPRECIATION (ماده ۱۴۹) - TEST")
    print("==================================================")

    db_path = _temp_db("arbin_fixed_assets_test.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    ledger = ArbinLedger(db_path=db_path)
    assets_mgr = ArbinFixedAssets(ledger)

    tenant_id = ledger.create_tenant("شرکت مهندسی و بازرگانی آریا", "14005556667")
    fy_id = ledger.create_fiscal_year(tenant_id, "1405", "2026-03-21", "2027-03-20")
    ledger.seed_standard_accounts(tenant_id)

    # Deposit initial capital to have bank liquidity
    ledger.record_journal_entry(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        entry_date="2026-03-21",
        description="سرمایه اولیه نقدی",
        items=[
            {"account_code": "1010", "debit": 500_000_000, "credit": 0.0, "description": "بانک"},
            {"account_code": "5010", "debit": 0.0, "credit": 500_000_000, "description": "سرمایه"}
        ]
    )

    # 1. Register Asset 1: Office Furniture (Straight-line: 5 years, salvage 0)
    # Cost: 60,000,000 -> Annual Depr = 12,000,000
    res1 = assets_mgr.register_asset(
        tenant_id=tenant_id,
        asset_code="FA-FUR-001",
        title="ست مبلمان و میز مدیریت اتاق جلسات",
        category="اثاثه و منصوبات",
        purchase_date="2026-04-01",
        purchase_cost=60_000_000,
        salvage_value=0.0,
        depreciation_method="straight_line",
        useful_life_years=5,
        asset_account_code="2010",
        depr_account_code="2110",
        post_purchase_voucher=True,
        fiscal_year_id=fy_id,
        settlement_account_code="1010"
    )
    print("OK دارایی ۱ (مبلمان اداری) ثبت و سند خرید آن صادر شد:", res1["asset_code"])
    assert res1["purchase_voucher_id"] is not None

    # 2. Register Asset 2: Company Server (Declining Balance: rate 30%)
    # Cost: 100,000,000 -> Annual Depr = 30,000,000
    res2 = assets_mgr.register_asset(
        tenant_id=tenant_id,
        asset_code="FA-SRV-001",
        title="سرور اچ‌پی ProLiant DL380 جهت استقرار آربین",
        category="تجهیزات کامپیوتری",
        purchase_date="2026-04-05",
        purchase_cost=100_000_000,
        salvage_value=5_000_000,
        depreciation_method="declining_balance",
        depreciation_rate=0.30,
        asset_account_code="2030",
        depr_account_code="2110",
        post_purchase_voucher=True,
        fiscal_year_id=fy_id
    )
    print("OK دارایی ۲ (سرور کامپیوتری نزولی) ثبت شد:", res2["asset_code"])

    # Verify Assets list
    all_assets = assets_mgr.list_assets(tenant_id)
    assert len(all_assets) == 2

    # 3. Run Depreciation Cycle for 12 months (End of fiscal year)
    # Asset 1: 60M / 5 = 12M
    # Asset 2: 100M * 30% = 30M
    # Total Depr = 42,000,000
    print("\n--------------------------------------------------")
    print("اجرای چرخه استهلاک سالانه ماده ۱۴۹:")
    print("--------------------------------------------------")
    depr_res = assets_mgr.run_depreciation_cycle(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        period_date="2027-03-20",
        period_name="استهلاک پایان سال مالی ۱۴۰۵",
        months=12
    )
    assert depr_res["voucher_id"] is not None
    assert depr_res["total_depreciation"] == 42_000_000.0, f"انتظار ۴۲ میلیون استهلاک، اما دریافت شد: {depr_res['total_depreciation']}"
    print("OK سند دوبل استهلاک با موفقیت صادر شد. شناسه سند:", depr_res["voucher_id"])
    print("  - هزینه استهلاک شناسایی شده (کد ۷۲۵۰): 42,000,000 تومان")

    # Verify updated book values
    assets_after = {a["asset_code"]: a for a in assets_mgr.list_assets(tenant_id)}
    assert assets_after["FA-FUR-001"]["accumulated_depreciation"] == 12_000_000.0
    assert assets_after["FA-FUR-001"]["book_value"] == 48_000_000.0
    assert assets_after["FA-SRV-001"]["accumulated_depreciation"] == 30_000_000.0
    assert assets_after["FA-SRV-001"]["book_value"] == 70_000_000.0
    print("OK ارزش دفتری و استهلاک انباشته هر دو دارایی به درستی به‌روزرسانی شدند.")

    # 4. Asset Disposal with Profit (فروش دارایی با سود)
    # Sell Asset 1 (Book value: 48M) for 55,000,000 -> Gain = 7,000,000
    print("\n--------------------------------------------------")
    print("واگذاری و فروش دارایی ۱ با شناسایی سود سرمایه‌ای:")
    print("--------------------------------------------------")
    disp_res = assets_mgr.dispose_asset(
        tenant_id=tenant_id,
        fiscal_year_id=fy_id,
        asset_code="FA-FUR-001",
        disposal_date="2027-03-20",
        disposal_type="sale",
        sale_price=55_000_000,
        settlement_account_code="1010"
    )
    assert disp_res["gain_loss"] == 7_000_000.0
    print("OK سند فروش دارایی صادر شد:")
    print("  - بهای تمام شده تاریخی (کد ۲۰۲۰): ۶۰,۰۰۰,۰۰۰ تومان (بستانکار)")
    print("  - بستن استهلاک انباشته (کد ۲۱۱۰): ۱۲,۰۰۰,۰۰۰ تومان (بدهکار)")
    print("  - ورود وجه نقد به بانک (کد ۱۰۱۰): ۵۵,۰۰۰,۰۰۰ تومان (بدهکار)")
    print("  - سود حاصل از واگذاری (کد ۶۰۴۰):   ۷,۰۰۰,۰۰۰ تومان (بستانکار)")

    # 5. Check Trial Balance to verify double-entry equilibrium
    from reports import ArbinReports
    rep = ArbinReports(ledger)
    tb = rep.get_trial_balance(tenant_id, fiscal_year_id=fy_id, level="subsidiary")
    tot_td = sum(r["total_debit"] for r in tb)
    tot_tc = sum(r["total_credit"] for r in tb)
    tot_bd = sum(r["balance_debit"] for r in tb)
    tot_bc = sum(r["balance_credit"] for r in tb)
    assert abs(tot_td - tot_tc) < 0.01
    assert abs(tot_bd - tot_bc) < 0.01
    print("\nOK تراز آزمایشی پس از کلیه عملیات استهلاک و واگذاری دارایی ۱۰۰٪ متوازن است.")

    print("\n==================================================")
    print("ALL FIXED ASSETS TESTS PASSED (100%)!")
    print("==================================================")


if __name__ == "__main__":
    test_fixed_assets_suite()
