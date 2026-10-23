"""
Arbin Modular Architecture & Licensing Engine (مدیریت ماژول‌ها و لایسنس آربین)
=============================================================================
Enables feature-flagged modular licensing per tenant.
Allows businesses (e.g. supermarkets, service companies, general trading)
to only activate and pay for the specific modules they need.

Modules:
- ledger: Core double-entry accounting (Always enabled, cannot be disabled)
- treasury: Cash, bank accounts, POS, and 4-step Sayadi cheque lifecycle
- invoicing: Official sales invoices, 10% VAT, and Taxpayer System (سامانه مؤدیان)
- inventory: Warehouses, receipts, deliveries, weighted average cost, and Kardex
- payroll: Social security 30%, progressive labor income tax, and Paya payment
- fixed_assets: (Planned) Fixed assets, tagging, and depreciation
- manufacturing: (Planned) Bill of Materials (BOM), raw materials, and production cost
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Set


class ModuleManagementError(Exception):
    """Raised when module operations violate business or licensing rules."""
    pass


MODULE_CATALOG: Dict[str, Dict[str, Any]] = {
    "ledger": {
        "key": "ledger",
        "title": "حسابداری مالی و اسناد",
        "subtitle": "هسته اصلی سیستم (General Ledger)",
        "description": "دفتر کل، روزنامه، کدینگ استاندارد ۴ سطحی ایران، اسناد دوبل حسابداری و تراز آزمایشی.",
        "icon": "book",
        "is_core": True,
        "is_ready": True,
        "category": "core",
        "badge": "هسته پایه"
    },
    "treasury": {
        "key": "treasury",
        "title": "خزانه‌داری و چک صیادی",
        "subtitle": "مدیریت وجوه نقد، بانک و چک",
        "description": "صندوق، حساب‌های بانکی، ثبت و گردش ۴ مرحله‌ای چک صیادی (وصول/برگشت) و رأس‌گیری دقیق چک‌ها.",
        "icon": "wallet",
        "is_core": False,
        "is_ready": True,
        "category": "financial",
        "badge": "تجاری"
    },
    "invoicing": {
        "key": "invoicing",
        "title": "مشتریان و فروش",
        "subtitle": "صدور فاکتور و سامانه مؤدیان",
        "description": "فاکتور رسمی، ارزش افزوده ۱۰٪، الگوریتم شناسه یکتای مالیاتی Verhoeff و خروجی کارپوشه مؤدیان.",
        "icon": "receipt",
        "is_core": False,
        "is_ready": True,
        "category": "commercial",
        "badge": "تجاری"
    },
    "inventory": {
        "key": "inventory",
        "title": "تأمین‌کنندگان و انبار",
        "subtitle": "انبارداری و بهای تمام‌شده کالا",
        "description": "رسید و حواله انبار، کنترل موجودی، کاردکس کالا، قیمت‌گذاری میانگین موزون و هشدارهای کسری کالا.",
        "icon": "box",
        "is_core": False,
        "is_ready": True,
        "category": "logistics",
        "badge": "بازرگانی"
    },
    "payroll": {
        "key": "payroll",
        "title": "حقوق و دستمزد و پرسنلی",
        "subtitle": "محاسبات قانون کار و بیمه تامین اجتماعی",
        "description": "بیمه ۳۰٪، مالیات پله‌ای ماده ۸۴، اضافه‌کاری، فیش حقوقی، دیسکت واریز گروهی پایا و صدور خودکار سند.",
        "icon": "users",
        "is_core": False,
        "is_ready": True,
        "category": "hr",
        "badge": "سازمانی"
    },
    "fixed_assets": {
        "key": "fixed_assets",
        "title": "اموال و دارایی ثابت",
        "subtitle": "پلاک‌گذاری و استهلاک دارایی‌ها",
        "description": "پلاک‌گذاری اموال، جدول ماده ۱۴۹ قانون مالیات‌ها، استهلاک مستقیم و نزولی و اسقاط دارایی.",
        "icon": "truck",
        "is_core": False,
        "is_ready": True,
        "category": "specialized",
        "badge": "تخصصی"
    },
    "manufacturing": {
        "key": "manufacturing",
        "title": "تولید و بهای تمام‌شده (BOM)",
        "subtitle": "فرمول ساخت و خط تولید کارخانه‌ای",
        "description": "فرمول ساخت محصولات (BOM)، حواله مصرف مواد اولیه، تخصیص دستمزد مستقیم و سربار و بهای تمام‌شده.",
        "icon": "cogs",
        "is_core": False,
        "is_ready": True,
        "category": "specialized",
        "badge": "تخصصی"
    },
    "contracting": {
        "key": "contracting",
        "title": "پیمانکاری و صورت‌وضعیت",
        "subtitle": "مدیریت قراردادها و پروژه‌ها",
        "description": "مدیریت پیمان‌ها، صورت‌وضعیت کارکرد، کسر ۱۰٪ حسن انجام کار، ۵٪ بیمه ماده ۳۸ و پیش‌دریافت‌ها.",
        "icon": "hard-hat",
        "is_core": False,
        "is_ready": True,
        "category": "specialized",
        "badge": "پروژه‌ای"
    }
}

PRESET_BUNDLES: Dict[str, Dict[str, Any]] = {
    "supermarket": {
        "key": "supermarket",
        "title": "پکیج سوپرمارکت و خرده‌فروشی",
        "description": "بهینه‌شده برای فروشگاه‌های زنجیره‌ای و سوپرمارکت‌ها؛ بدون شلوغی بخش حقوق یا چک‌های پیچیده.",
        "icon": "shopping-cart",
        "modules": ["ledger", "invoicing", "inventory"]
    },
    "services": {
        "key": "services",
        "title": "پکیج خدماتی، مطب و دفاتر",
        "description": "مخصوص کلینیک‌ها، شرکت‌های مشاوره‌ای و خدماتی که انبار فیزیکی کالا ندارند.",
        "icon": "briefcase",
        "modules": ["ledger", "treasury", "invoicing"]
    },
    "trading": {
        "key": "trading",
        "title": "پکیج بازرگانی و فروش عمده",
        "description": "گردش کامل چک، خرید و فروش کالا و انبارداری بدون محاسبات حقوق پرسنل.",
        "icon": "store",
        "modules": ["ledger", "treasury", "invoicing", "inventory"]
    },
    "enterprise": {
        "key": "enterprise",
        "title": "پکیج جامع شرکتی و بازرگانی",
        "description": "تمام ۵ ماژول تجاری شامل اسناد، خزانه، فروش، انبار و حقوق و دستمزد کامل.",
        "icon": "shield-check",
        "modules": ["ledger", "treasury", "invoicing", "inventory", "payroll"]
    },
    "industrial": {
        "key": "industrial",
        "title": "پکیج صنعتی و تولیدی (کارخانه‌ها)",
        "description": "فرمول ساخت BOM، کنترل انبار مواد و محصول، بهای تمام‌شده، دارایی ثابت و استهلاک ماشین‌آلات.",
        "icon": "cogs",
        "modules": ["ledger", "invoicing", "inventory", "manufacturing", "fixed_assets", "payroll"]
    },
    "contractor": {
        "key": "contractor",
        "title": "پکیج پیمانکاری و عمرانی",
        "description": "قراردادها، صورت‌وضعیت‌ها، سپرده حسن انجام کار، بیمه ماده ۳۸، خزانه، دارایی ثابت و حقوق پرسنل کارگاه.",
        "icon": "hard-hat",
        "modules": ["ledger", "treasury", "invoicing", "contracting", "fixed_assets", "payroll"]
    }
}


class ArbinModuleManager:
    """Manages tenant module activation, feature-flags, and bundle presets."""

    def __init__(self, ledger_or_db: Any):
        self.ledger = ledger_or_db
        self.init_table()

    def get_connection(self) -> sqlite3.Connection:
        if hasattr(self.ledger, "get_connection"):
            return self.ledger.get_connection()
        if hasattr(self.ledger, "session"):
            return self.ledger.session()
        raise AttributeError("Invalid ledger or database instance passed to ArbinModuleManager")

    def init_table(self) -> None:
        """Create tenant_modules table if not existing."""
        with self.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tenant_modules (
                    tenant_id TEXT NOT NULL,
                    module_key TEXT NOT NULL,
                    is_enabled INTEGER NOT NULL DEFAULT 1,
                    activated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                    PRIMARY KEY (tenant_id, module_key)
                );
            """)

    def bootstrap_default_modules(self, tenant_id: str, preset: str = "enterprise") -> None:
        """Ensure all modules are registered for a tenant. Default is enterprise bundle."""
        bundle = PRESET_BUNDLES.get(preset, PRESET_BUNDLES["enterprise"])
        active_set = set(bundle["modules"])

        with self.get_connection() as conn:
            for mod_key, meta in MODULE_CATALOG.items():
                if not meta["is_ready"]:
                    continue
                is_on = 1 if (mod_key in active_set or meta["is_core"]) else 0
                conn.execute("""
                    INSERT OR IGNORE INTO tenant_modules (tenant_id, module_key, is_enabled)
                    VALUES (?, ?, ?)
                """, (tenant_id, mod_key, is_on))

    def get_tenant_modules(self, tenant_id: str) -> List[Dict[str, Any]]:
        """Return catalog of all modules merged with current tenant activation status."""
        self.bootstrap_default_modules(tenant_id)

        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT module_key, is_enabled, activated_at
                FROM tenant_modules
                WHERE tenant_id = ?
            """, (tenant_id,)).fetchall()

        status_map: Dict[str, Dict[str, Any]] = {
            r["module_key"] if isinstance(r, sqlite3.Row) else r[0]: {
                "is_enabled": bool(r["is_enabled"] if isinstance(r, sqlite3.Row) else r[1]),
                "activated_at": r["activated_at"] if isinstance(r, sqlite3.Row) else r[2]
            }
            for r in rows
        }

        result = []
        for mod_key, meta in MODULE_CATALOG.items():
            mod_data = dict(meta)
            st = status_map.get(mod_key, {"is_enabled": meta["is_core"], "activated_at": None})
            mod_data["is_enabled"] = True if meta["is_core"] else st["is_enabled"]
            mod_data["activated_at"] = st.get("activated_at")
            result.append(mod_data)

        return result

    def is_module_enabled(self, tenant_id: str, module_key: str) -> bool:
        """Fast check whether a module is active for a given tenant."""
        meta = MODULE_CATALOG.get(module_key)
        if not meta or not meta["is_ready"]:
            return False
        if meta["is_core"]:
            return True

        with self.get_connection() as conn:
            row = conn.execute("""
                SELECT is_enabled FROM tenant_modules
                WHERE tenant_id = ? AND module_key = ?
            """, (tenant_id, module_key)).fetchone()

        if row is None:
            # Bootstrap if not present, then re-check
            self.bootstrap_default_modules(tenant_id)
            return module_key in PRESET_BUNDLES["enterprise"]["modules"]

        val = row["is_enabled"] if isinstance(row, sqlite3.Row) else row[0]
        return bool(val)

    def set_module_enabled(self, tenant_id: str, module_key: str, enabled: bool) -> Dict[str, Any]:
        """Activate or deactivate a module for a tenant."""
        meta = MODULE_CATALOG.get(module_key)
        if not meta:
            raise ModuleManagementError(f"ماژول نامعتبر است: {module_key}")
        if meta["is_core"] and not enabled:
            raise ModuleManagementError(
                f"ماژول «{meta['title']}» هسته حیاتی سیستم حسابداری است و امکان غیرفعال‌سازی آن وجود ندارد."
            )
        if not meta["is_ready"] and enabled:
            raise ModuleManagementError(
                f"ماژول «{meta['title']}» هنوز در فاز توسعه قرار دارد و آماده بهره‌برداری نیست."
            )

        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO tenant_modules (tenant_id, module_key, is_enabled, activated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(tenant_id, module_key) DO UPDATE SET
                    is_enabled = excluded.is_enabled,
                    activated_at = CURRENT_TIMESTAMP
            """, (tenant_id, module_key, 1 if enabled else 0))

        return {
            "tenant_id": tenant_id,
            "module_key": module_key,
            "module_title": meta["title"],
            "is_enabled": enabled,
            "message": f"ماژول «{meta['title']}» با موفقیت {'فعال' if enabled else 'غیرفعال'} شد."
        }

    def apply_preset(self, tenant_id: str, preset_name: str) -> Dict[str, Any]:
        """Apply a predefined bundle to a tenant."""
        preset = PRESET_BUNDLES.get(preset_name)
        if not preset:
            valid = list(PRESET_BUNDLES.keys())
            raise ModuleManagementError(f"پکیج ناشناخته: {preset_name}. پکیج‌های مجاز: {valid}")

        active_keys = set(preset["modules"])
        with self.get_connection() as conn:
            for mod_key, meta in MODULE_CATALOG.items():
                if not meta["is_ready"]:
                    continue
                is_on = 1 if (mod_key in active_keys or meta["is_core"]) else 0
                conn.execute("""
                    INSERT INTO tenant_modules (tenant_id, module_key, is_enabled, activated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(tenant_id, module_key) DO UPDATE SET
                        is_enabled = excluded.is_enabled,
                        activated_at = CURRENT_TIMESTAMP
                """, (tenant_id, mod_key, is_on))

        return {
            "tenant_id": tenant_id,
            "preset_key": preset_name,
            "preset_title": preset["title"],
            "active_modules": list(active_keys),
            "message": f"پکیج «{preset['title']}» با موفقیت اعمال گردید."
        }
