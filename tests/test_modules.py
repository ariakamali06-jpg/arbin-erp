"""
Unit Tests for Arbin Modular Licensing & Feature Flags (تست‌های سیستم ماژولار و لایسنس)
========================================================================================
Verifies:
1. Module catalog and initialization per tenant.
2. Protection of core module (General Ledger cannot be disabled).
3. Individual module activation / deactivation toggle.
4. Fast preset bundle application (Supermarket, Services, Trading, Enterprise).
5. API layer enforcement (HTTP 403 MODULE_DISABLED when accessing disabled module).
"""

import os
import sys
import tempfile
from pathlib import Path

# Add workspace to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ledger import ArbinLedger
from modules import ArbinModuleManager, ModuleManagementError, MODULE_CATALOG, PRESET_BUNDLES


def _temp_db(name: str) -> str:
    return os.path.join(tempfile.gettempdir(), name)


def test_modules_suite():
    print("==================================================")
    print("ARBIN MODULAR LICENSING & FEATURE FLAGS - TEST")
    print("==================================================")

    db_path = _temp_db("arbin_modules_test.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    ledger = ArbinLedger(db_path=db_path)
    tenant_id = ledger.create_tenant("سوپرمارکت کوروش", "14001234567")
    manager = ArbinModuleManager(ledger)

    # 1. Test Default Catalog
    modules = manager.get_tenant_modules(tenant_id)
    assert len(modules) >= 5, "باید حداقل ۵ ماژول در کاتالوگ وجود داشته باشد."
    print("OK کاتالوگ ماژول‌ها برای شرکت بارگذاری شد. تعداد کل:", len(modules))

    # 2. Core Module Immutability
    try:
        manager.set_module_enabled(tenant_id, "ledger", False)
        assert False, "نباید اجازه غیرفعال‌سازی ماژول هسته (حسابداری پایه) داده شود."
    except ModuleManagementError as e:
        print("OK سیستم امنیتی ماژول هسته فعال است:", e)

    # 3. Supermarket Preset (پکیج سوپرمارکت: بدون حقوق و خزانه)
    print("\n--------------------------------------------------")
    print("اعمال پکیج سوپرمارکت و خرده‌فروشی:")
    print("--------------------------------------------------")
    res = manager.apply_preset(tenant_id, "supermarket")
    print(res["message"])
    assert manager.is_module_enabled(tenant_id, "ledger") is True
    assert manager.is_module_enabled(tenant_id, "invoicing") is True
    assert manager.is_module_enabled(tenant_id, "inventory") is True
    assert manager.is_module_enabled(tenant_id, "treasury") is False
    assert manager.is_module_enabled(tenant_id, "payroll") is False
    print("OK وضعیت ماژول‌های سوپرمارکت تایید شد:")
    print("  - حسابداری پایه (دفتر کل): فعال ✅")
    print("  - فروش و فاکتور:          فعال ✅")
    print("  - انبارداری و کالا:       فعال ✅")
    print("  - خزانه‌داری و چک:         خاموش 🔒")
    print("  - حقوق و دستمزد پرسنل:    خاموش 🔒")

    # 4. Individual Activation (سوپرمارکت بعد از چند ماه حقوق را خریداری می‌کند)
    print("\n--------------------------------------------------")
    print("خرید و فعال‌سازی ماژول حقوق و دستمزد توسط سوپرمارکت:")
    print("--------------------------------------------------")
    up_res = manager.set_module_enabled(tenant_id, "payroll", True)
    print(up_res["message"])
    assert manager.is_module_enabled(tenant_id, "payroll") is True
    print("OK ماژول حقوق و دستمزد با موفقیت به اشتراک اضافه شد.")

    # 5. Service Company Preset (پکیج خدماتی: بدون انبار)
    print("\n--------------------------------------------------")
    print("تغییر کاربری یا ایجاد شرکت خدماتی (پکیج خدماتی و مطب):")
    print("--------------------------------------------------")
    srv_tenant = ledger.create_tenant("کلینیک تخصصی دکتر البرز", "14009876543")
    manager.apply_preset(srv_tenant, "services")
    assert manager.is_module_enabled(srv_tenant, "inventory") is False
    assert manager.is_module_enabled(srv_tenant, "treasury") is True
    assert manager.is_module_enabled(srv_tenant, "invoicing") is True
    print("OK پکیج خدماتی بدون انبارداری فیزیکی تایید شد.")

    # 6. Test FastAPI Client Integration & 403 Guard
    print("\n--------------------------------------------------")
    print("تست لایه وب‌سرویس و گارد امنیتی (FastAPI 403 Forbidden):")
    print("--------------------------------------------------")
    from fastapi.testclient import TestClient
    from api import app, ledger as api_ledger, module_manager as api_mod_mgr

    client = TestClient(app)

    # Create a tenant in the API's database
    api_tenant_id = api_ledger.create_tenant("سوپرمارکت زنجیره‌ای آریا", "14008889991")

    # Apply supermarket preset via API endpoint:
    apply_resp = client.post(f"/api/v1/tenants/{api_tenant_id}/modules/preset/supermarket")
    assert apply_resp.status_code == 200, f"خطا در اعمال پکیج: {apply_resp.text}"
    print("OK پکیج سوپرمارکت از طریق اندپوینت API با موفقیت ارسال و اعمال شد.")

    # In supermarket tenant, treasury is FALSE -> /treasury/cheques MUST return 403:
    resp = client.get(f"/api/v1/tenants/{api_tenant_id}/treasury/cheques")
    assert resp.status_code == 403, f"باید خطای 403 برای ماژول غیرفعال داده شود، اما دریافت شد: {resp.status_code}"
    err_json = resp.json()
    assert err_json.get("code") == "MODULE_DISABLED"
    print("OK وب‌سرویس درخواست به ماژول غیرفعال خزانه را با کد ۴۰۳ و پیام محترمانه مسدود کرد:")
    print("  ->", err_json.get("detail"))

    # Payroll is also FALSE in supermarket -> MUST return 403:
    resp_pay = client.get(f"/api/v1/tenants/{api_tenant_id}/payroll/employees")
    assert resp_pay.status_code == 403, f"باید خطای 403 برای ماژول غیرفعال حقوق داده شود: {resp_pay.status_code}"
    print("OK درخواست به ماژول غیرفعال حقوق و دستمزد هم با کد ۴۰۳ مسدود شد.")

    # But inventory IS enabled in supermarket -> MUST NOT be 403:
    resp_inv = client.get(f"/api/v1/tenants/{api_tenant_id}/inventory/products")
    assert resp_inv.status_code != 403, f"ماژول انبار فعال است، نباید 403 شود: {resp_inv.status_code}"
    print("OK ماژول فعال انبارداری بدون مانع باز شد (وضعیت مجاز).")

    # Now toggle treasury ON via API:
    toggle_resp = client.post(
        f"/api/v1/tenants/{api_tenant_id}/modules/treasury/toggle",
        json={"is_enabled": True}
    )
    assert toggle_resp.status_code == 200
    print("OK ماژول خزانه‌داری از طریق اندپوینت API فعال شد.")

    # Now treasury request MUST pass:
    resp_ok = client.get(f"/api/v1/tenants/{api_tenant_id}/treasury/cheques")
    assert resp_ok.status_code == 200, f"پس از فعال‌سازی باید پاسخ ۲۰۰ باشد: {resp_ok.status_code}"
    print("OK پس از فعال‌سازی، وب‌سرویس خزانه‌داری بلافاصله باز شد (کد ۲۰۰).")

    # Module list endpoint
    mod_resp = client.get(f"/api/v1/tenants/{api_tenant_id}/modules")
    assert mod_resp.status_code == 200
    mod_data = mod_resp.json()
    assert len(mod_data["modules"]) >= 5
    assert len(mod_data["presets"]) >= 4
    print("OK اندپوینت عمومی دریافت ماژول‌ها و پکیج‌ها (GET /modules) پاسخ داد.")

    print("\n==================================================")
    print("ALL MODULAR LICENSING TESTS PASSED (100%)!")
    print("==================================================")


if __name__ == "__main__":
    test_modules_suite()
