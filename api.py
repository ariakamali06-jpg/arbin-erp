"""
Arbin Financial REST API (رابط نرم‌افزاری هسته حسابداری آربین)
Ready for frontend integration (Next.js / Flutter) and third-party webhooks.
Includes Double-Entry Ledger, Treasury, Inventory, Invoicing, Payroll,
financial reports and the Taxpayer System (سامانه مؤدیان).
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ai_copilot import ArbinAICopilot
from inventory import ArbinInventory, InsufficientStockError, InventoryError
from invoicing import ArbinInvoicing, InvoicingError
from ledger import (
    AccountingError,
    ArbinLedger,
    FiscalYearClosedError,
    ImmutableEntryError,
    UnbalancedJournalEntryError,
)
from modules import (
    ArbinModuleManager,
    ModuleManagementError,
    MODULE_CATALOG,
    PRESET_BUNDLES,
)
from payroll import ArbinPayroll, PayrollError
from reports import ArbinReports
from treasury import ArbinTreasury, TreasuryError
from fixed_assets import ArbinFixedAssets, FixedAssetError
from manufacturing import ArbinManufacturing, ManufacturingError
from contracting import ArbinContracting, ContractingError
from document_flow import ArbinDocumentFlow

app = FastAPI(
    title="Arbin Accounting Engine API (آربین)",
    version="2.0.0",
    description="Next-Generation Cloud-Native Double-Entry Financial Ledger for Iranian Businesses",
)

ledger = ArbinLedger()
module_manager = ArbinModuleManager(ledger)
reports = ArbinReports(ledger)
document_flow = ArbinDocumentFlow(ledger)
invoicing = ArbinInvoicing(ledger)
treasury = ArbinTreasury(ledger)
inventory = ArbinInventory(ledger)
payroll = ArbinPayroll(ledger)
fixed_assets = ArbinFixedAssets(ledger)
manufacturing = ArbinManufacturing(ledger, inventory=inventory)
contracting = ArbinContracting(ledger)
copilot = ArbinAICopilot(ledger)

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
STATIC_INDEX = STATIC_DIR / "index.html"


# ---------------------------------------------------------------------------
# Module Licensing Guard Middleware (کنترل دسترسی ماژول‌ها)
# ---------------------------------------------------------------------------
@app.middleware("http")
async def module_guard_middleware(request: Request, call_next):
    path = request.url.path
    # Intercept /api/v1/tenants/{tenant_id}/{module_name}/...
    m = re.match(
        r"^/api/v1/tenants/([^/]+)/(treasury|inventory|invoices|payroll|fixed-assets|manufacturing|contracting)(?:/|$)",
        path,
    )
    if m:
        tenant_id = m.group(1)
        segment = m.group(2)
        segment_to_key = {
            "invoices": "invoicing",
            "fixed-assets": "fixed_assets",
            "treasury": "treasury",
            "inventory": "inventory",
            "payroll": "payroll",
            "manufacturing": "manufacturing",
            "contracting": "contracting",
        }
        mod_key = segment_to_key.get(segment, segment)
        if not module_manager.is_module_enabled(tenant_id, mod_key):
            meta = MODULE_CATALOG.get(mod_key, {})
            title = meta.get("title", mod_key)
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "detail": f"ماژول «{title}» برای این شرکت فعال نیست. جهت دسترسی، آن را در بخش مدیریت ماژول‌ها فعال کنید.",
                    "code": "MODULE_DISABLED",
                    "module": mod_key,
                },
            )
    return await call_next(request)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------
class CreateTenantRequest(BaseModel):
    name: str = Field(..., example="شرکت بازرگانی آریا")
    national_id: Optional[str] = Field(None, example="14001234567")
    currency: str = Field("IRT", example="IRT")


class CreateFiscalYearRequest(BaseModel):
    title: str = Field(..., example="سال مالی ۱۴۰۵")
    start_date: str = Field(..., example="2026-03-21")
    end_date: str = Field(..., example="2027-03-20")


class JournalItemRequest(BaseModel):
    account_code: str = Field(..., example="1010")
    detail_code: Optional[str] = Field(None, example="4001")
    sub_ledger_code: Optional[str] = Field(None, example="4001")
    description: str = Field(..., example="واریز وجه به بانک")
    debit: float = Field(0.0, ge=0)
    credit: float = Field(0.0, ge=0)


class RecordEntryRequest(BaseModel):
    fiscal_year_id: str
    entry_date: str = Field(..., example="2026-04-10")
    description: str = Field(..., example="فروش کالا طبق فاکتور ۱۰۱")
    items: List[JournalItemRequest]
    manual_number: Optional[str] = None
    source_module: str = "manual"
    status: str = Field("approved", example="approved")


class EntryStatusRequest(BaseModel):
    status: str = Field(..., example="permanent")


class InvoiceItemRequest(BaseModel):
    item_code: str = Field(..., example="2720000112233")
    item_title: str = Field(..., example="لایسنس نرم‌افزار آربین")
    unit: str = Field("تعداد", example="تعداد")
    quantity: float = Field(..., gt=0, example=2)
    unit_price: float = Field(..., ge=0, example=50000000)
    discount: float = Field(0.0, ge=0, example=5000000)
    vat_rate: float = Field(0.10, ge=0, example=0.10)


class CreateInvoiceRequest(BaseModel):
    fiscal_year_id: str
    customer_detail_id: str
    invoice_date: str = Field(..., example="2026-04-12")
    items: List[InvoiceItemRequest]
    tax_fiscal_id: str = Field("ARB001", example="ARB001")
    pattern_code: str = Field("pattern1", example="pattern1")
    invoice_type: str = Field("official_sale", example="official_sale")
    payment_status: str = Field("unpaid", example="unpaid")


# ---------------------------------------------------------------------------
# Static SPA
# ---------------------------------------------------------------------------
@app.api_route("/", methods=["GET", "HEAD"])
def serve_dashboard():
    if STATIC_INDEX.exists():
        return FileResponse(str(STATIC_INDEX))
    return {"message": "Arbin API is running", "docs": "/docs"}


if STATIC_DIR.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Bootstrap (راه‌اندازی داده نمایشی)
# ---------------------------------------------------------------------------
@app.post("/api/v1/bootstrap")
def bootstrap_endpoint():
    """
    Idempotent demo bootstrap: tenant 'default_company', fiscal year 'fy_1405',
    standard chart of accounts, sub-ledgers, warehouse, products and opening capital.
    """
    from seed_data import seed_demo_company

    try:
        info = seed_demo_company(ledger)
    except AccountingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "آربین با موفقیت راه‌اندازی شد.", **info}


@app.get("/api/v1/health")
def health_check():
    return {
        "status": "online",
        "system": "Arbin Financial Engine (آربین)",
        "version": "2.0.0",
        "compliance": "Iranian Accounting Standards & Tax Regulations (سامانه مؤدیان)",
    }


# ---------------------------------------------------------------------------
# Module Licensing & Feature Flags (مدیریت ماژول‌ها و لایسنس)
# ---------------------------------------------------------------------------
class SetModuleStatusRequest(BaseModel):
    is_enabled: bool = Field(...)


@app.get("/api/v1/tenants/{tenant_id}/modules")
def list_tenant_modules_endpoint(tenant_id: str):
    """List all available modules with activation status for this tenant."""
    return {
        "tenant_id": tenant_id,
        "modules": module_manager.get_tenant_modules(tenant_id),
        "presets": list(PRESET_BUNDLES.values())
    }


@app.post("/api/v1/tenants/{tenant_id}/modules/{module_key}/toggle")
def toggle_module_endpoint(tenant_id: str, module_key: str, req: Optional[SetModuleStatusRequest] = None):
    """Toggle or explicitly set module active status."""
    try:
        current = module_manager.is_module_enabled(tenant_id, module_key)
        target = req.is_enabled if req is not None else not current
        return module_manager.set_module_enabled(tenant_id, module_key, target)
    except ModuleManagementError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/modules/preset/{preset_name}")
def apply_preset_endpoint(tenant_id: str, preset_name: str):
    """Apply a business bundle preset (supermarket, services, trading, enterprise)."""
    try:
        return module_manager.apply_preset(tenant_id, preset_name)
    except ModuleManagementError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.get("/api/v1/tenants/{tenant_id}/dashboard-summary")
def get_dashboard_summary_endpoint(tenant_id: str, fiscal_year_id: Optional[str] = None):
    with ledger.get_connection() as conn:
        if not fiscal_year_id:
            row = conn.execute(
                "SELECT id FROM fiscal_years WHERE tenant_id = ? ORDER BY end_date DESC LIMIT 1",
                (tenant_id,),
            ).fetchone()
            fiscal_year_id = row[0] if row else None

        bank_row = conn.execute(
            """
            SELECT COALESCE(SUM(ji.debit - ji.credit), 0.0)
            FROM journal_items ji
            JOIN accounts a ON ji.account_id = a.id
            JOIN journal_entries je ON ji.entry_id = je.id
            WHERE a.tenant_id = ? AND a.code IN ('1010', '1020') AND je.status != 'draft'
            """,
            (tenant_id,),
        ).fetchone()
        bank_balance = float(bank_row[0]) if bank_row else 0.0

        rec_row = conn.execute(
            """
            SELECT COALESCE(SUM(ji.debit - ji.credit), 0.0)
            FROM journal_items ji
            JOIN accounts a ON ji.account_id = a.id
            JOIN journal_entries je ON ji.entry_id = je.id
            WHERE a.tenant_id = ? AND a.code = '1210' AND je.status != 'draft'
            """,
            (tenant_id,),
        ).fetchone()
        receivables = float(rec_row[0]) if rec_row else 0.0

        inv_row = conn.execute(
            "SELECT COALESCE(SUM(final_payable), 0.0) FROM invoices WHERE tenant_id = ? AND status != 'cancelled'",
            (tenant_id,),
        ).fetchone()

        entries = conn.execute(
            """
            SELECT je.entry_number, je.entry_date, je.entry_date_jalali, je.description,
                   je.status, je.source_module,
                   COALESCE(SUM(ji.debit), 0.0) AS total_amount
            FROM journal_entries je
            LEFT JOIN journal_items ji ON je.id = ji.entry_id
            WHERE je.tenant_id = ? AND (? IS NULL OR je.fiscal_year_id = ?)
            GROUP BY je.id
            ORDER BY je.entry_date DESC, je.entry_number DESC
            LIMIT 10
            """,
            (tenant_id, fiscal_year_id, fiscal_year_id),
        ).fetchall()

        customers = conn.execute(
            """
            SELECT id, code, title, phone FROM sub_ledgers
            WHERE tenant_id = ? AND sub_ledger_type = 'customer'
            ORDER BY code ASC
            """,
            (tenant_id,),
        ).fetchall()

    inc = reports.get_income_statement(tenant_id, fiscal_year_id)
    dash = reports.get_dashboard(tenant_id, fiscal_year_id)

    status_labels = {
        "draft": "پیش‌نویس",
        "approved": "تایید شده",
        "permanent": "قید شده",
        "confirmed": "تایید شده",
        "opening_entry": "سند افتتاحیه",
        "closing_entry": "سند اختتامیه",
    }

    return {
        "fiscal_year_id": fiscal_year_id,
        "bank_balance": bank_balance,
        "cash_and_bank": dash["cash_and_bank"],
        "total_sales": inc["total_revenue"],
        "total_receivables": receivables,
        "total_invoiced": float(inv_row[0] if inv_row else 0),
        "net_profit": inc["net_profit"],
        "total_assets": dash["total_assets"],
        "total_liabilities": dash["total_liabilities"],
        "recent_entries": [
            {
                "number": e["entry_number"],
                "date": e["entry_date"],
                "date_jalali": e["entry_date_jalali"],
                "description": e["description"],
                "status": status_labels.get(e["status"], e["status"]),
                "raw_status": e["status"],
                "source_module": e["source_module"],
                "amount": float(e["total_amount"]),
            }
            for e in entries
        ],
        "customers": [
            {"id": c["id"], "code": c["code"], "title": c["title"], "phone": c["phone"]}
            for c in customers
        ],
        "active_modules": [
            m["key"] for m in module_manager.get_tenant_modules(tenant_id) if m.get("is_enabled")
        ],
    }


# ---------------------------------------------------------------------------
# Tenants & Fiscal Years
# ---------------------------------------------------------------------------
@app.post("/api/v1/tenants", status_code=status.HTTP_201_CREATED)
def create_tenant_endpoint(req: CreateTenantRequest):
    tenant_id = ledger.create_tenant(req.name, req.national_id, req.currency)
    ledger.seed_standard_accounts(tenant_id)
    return {"tenant_id": tenant_id, "message": "شرکت و کدینگ استاندارد حسابداری با موفقیت ایجاد شد."}


@app.post("/api/v1/tenants/{tenant_id}/fiscal-years", status_code=status.HTTP_201_CREATED)
def create_fiscal_year_endpoint(tenant_id: str, req: CreateFiscalYearRequest):
    fy_id = ledger.create_fiscal_year(tenant_id, req.title, req.start_date, req.end_date)
    return {"fiscal_year_id": fy_id, "message": "سال مالی ایجاد شد."}


@app.get("/api/v1/tenants/{tenant_id}/fiscal-years")
def list_fiscal_years_endpoint(tenant_id: str):
    with ledger.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM fiscal_years WHERE tenant_id = ? ORDER BY start_date DESC",
            (tenant_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/v1/tenants/{tenant_id}/fiscal-years/{fiscal_year_id}/close")
def close_fiscal_year_endpoint(tenant_id: str, fiscal_year_id: str):
    """سند اختتامیه: بستن حساب‌های درآمد/هزینه و مهر بستن سال مالی"""
    try:
        return ledger.close_fiscal_year(tenant_id, fiscal_year_id)
    except (FiscalYearClosedError, AccountingError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/fiscal-years/{fiscal_year_id}/opening")
def opening_entry_endpoint(tenant_id: str, fiscal_year_id: str, opening_date: Optional[str] = None):
    """سند افتتاحیه سال مالی جدید"""
    try:
        return ledger.create_opening_entry(tenant_id, fiscal_year_id, opening_date=opening_date)
    except AccountingError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Journal Entries
# ---------------------------------------------------------------------------
@app.post("/api/v1/tenants/{tenant_id}/entries", status_code=status.HTTP_201_CREATED)
def record_entry_endpoint(tenant_id: str, req: RecordEntryRequest):
    try:
        items_dict = [item.model_dump() for item in req.items]
        entry_id = ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=req.fiscal_year_id,
            entry_date=req.entry_date,
            description=req.description,
            items=items_dict,
            manual_number=req.manual_number,
            source_module=req.source_module,
            status=req.status,
        )
        return {"entry_id": entry_id, "message": "سند حسابداری با تراز دوبل با موفقیت ثبت شد."}
    except UnbalancedJournalEntryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AccountingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/tenants/{tenant_id}/entries")
def list_entries_endpoint(
    tenant_id: str,
    fiscal_year_id: Optional[str] = None,
    include_drafts: bool = False,
    limit: int = 200,
):
    return ledger.list_journal_entries(
        tenant_id, fiscal_year_id=fiscal_year_id, include_drafts=include_drafts, limit=limit
    )


@app.get("/api/v1/tenants/{tenant_id}/entries/{entry_id}")
def get_entry_endpoint(tenant_id: str, entry_id: str):
    entry = ledger.get_journal_entry(tenant_id, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="سند یافت نشد.")
    return entry


@app.post("/api/v1/tenants/{tenant_id}/entries/{entry_id}/status")
def entry_status_endpoint(tenant_id: str, entry_id: str, req: EntryStatusRequest):
    try:
        return ledger.update_entry_status(tenant_id, entry_id, req.status)
    except (ImmutableEntryError, AccountingError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/v1/tenants/{tenant_id}/entries/{entry_id}")
def delete_entry_endpoint(tenant_id: str, entry_id: str):
    try:
        removed = ledger.delete_journal_entry(tenant_id, entry_id)
    except ImmutableEntryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not removed:
        raise HTTPException(status_code=404, detail="سند یافت نشد.")
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Chart of accounts & sub-ledgers
# ---------------------------------------------------------------------------
@app.get("/api/v1/tenants/{tenant_id}/accounts/tree")
def account_tree_endpoint(tenant_id: str):
    return ledger.get_account_tree(tenant_id)


class CreateSubLedgerRequest(BaseModel):
    code: str = Field(..., example="4001")
    title: str = Field(..., example="فروشگاه آنلاین زنجیره‌ای")
    sub_ledger_type: str = Field("customer", example="customer")
    phone: Optional[str] = None
    national_id: Optional[str] = None
    dimension: Optional[str] = None


@app.get("/api/v1/tenants/{tenant_id}/sub-ledgers")
def sub_ledgers_endpoint(tenant_id: str, kind: Optional[str] = None):
    sql = ["SELECT * FROM sub_ledgers WHERE tenant_id = ?"]
    params = [tenant_id]
    if kind:
        sql.append("AND sub_ledger_type = ?")
        params.append(kind)
    sql.append("ORDER BY code")
    with ledger.get_connection() as conn:
        rows = conn.execute(" ".join(sql), params).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/v1/tenants/{tenant_id}/sub-ledgers", status_code=status.HTTP_201_CREATED)
def create_sub_ledger_endpoint(tenant_id: str, req: CreateSubLedgerRequest):
    sub_id = ledger.create_sub_ledger(
        tenant_id,
        req.code,
        req.title,
        req.sub_ledger_type,
        phone=req.phone,
        national_id=req.national_id,
        dimension=req.dimension,
    )
    return {"sub_ledger_id": sub_id, "code": req.code}


# ---------------------------------------------------------------------------
# Financial Reports
# ---------------------------------------------------------------------------
@app.get("/api/v1/tenants/{tenant_id}/reports/trial-balance")
def get_trial_balance_endpoint(
    tenant_id: str,
    level: str = "subsidiary",
    fiscal_year_id: Optional[str] = None,
):
    return reports.get_trial_balance(tenant_id, level=level, fiscal_year_id=fiscal_year_id)


@app.get("/api/v1/tenants/{tenant_id}/reports/income-statement")
def get_income_statement_endpoint(tenant_id: str, fiscal_year_id: Optional[str] = None):
    return reports.get_income_statement(tenant_id, fiscal_year_id)


@app.get("/api/v1/tenants/{tenant_id}/reports/balance-sheet")
def get_balance_sheet_endpoint(tenant_id: str, fiscal_year_id: Optional[str] = None):
    return reports.get_balance_sheet(tenant_id, fiscal_year_id)


@app.get("/api/v1/tenants/{tenant_id}/reports/account-statement")
def get_account_statement_endpoint(
    tenant_id: str,
    account_code: str = Query(..., example="1210"),
    fiscal_year_id: Optional[str] = None,
    opening_balance: float = 0.0,
):
    return reports.get_account_statement(
        tenant_id, account_code, fiscal_year_id=fiscal_year_id, opening_balance=opening_balance
    )


# ---------------------------------------------------------------------------
# Treasury & Cheques (خزانه‌داری)
# ---------------------------------------------------------------------------
class ReceiveChequeRequest(BaseModel):
    fiscal_year_id: str
    customer_detail_id: str
    sayyad_id: str = Field(..., example="7123456789012345")
    cheque_number: str = Field(..., example="CHK-9901")
    bank_name: str = Field(..., example="بانک ملت")
    due_date: str = Field(..., example="2026-06-20")
    amount: float = Field(..., gt=0, example=50000000)
    receive_date: str = Field(..., example="2026-04-10")
    branch_name: Optional[str] = None
    description: Optional[str] = None


class DepositChequeRequest(BaseModel):
    bank_account_detail_id: str
    deposit_date: str = Field(..., example="2026-06-18")


class ClearChequeRequest(BaseModel):
    clear_date: str = Field(..., example="2026-06-20")


class ChequeStateRequest(BaseModel):
    date: str = Field(..., example="2026-06-20")
    reason: Optional[str] = None


class IssueChequeRequest(BaseModel):
    fiscal_year_id: str
    payee_detail_id: str
    sayyad_id: str = Field(..., example="7123456789012346")
    cheque_number: str = Field(..., example="CHK-9902")
    bank_name: str = Field(..., example="بانک ملت")
    bank_account_detail_id: str
    due_date: str = Field(..., example="2026-07-20")
    amount: float = Field(..., gt=0)
    issue_date: str = Field(..., example="2026-04-10")
    branch_name: Optional[str] = None
    description: Optional[str] = None


class TransferChequeRequest(BaseModel):
    payee_detail_id: str
    transfer_date: str = Field(..., example="2026-05-01")


class TreasuryTransactionRequest(BaseModel):
    fiscal_year_id: str
    tx_type: str = Field(..., example="receipt")
    method: str = Field("cash", example="cash")
    amount: float = Field(..., gt=0)
    tx_date: str = Field(..., example="2026-04-10")
    party_detail_id: Optional[str] = None
    bank_account_detail_id: Optional[str] = None
    pos_terminal_id: Optional[str] = None
    cheque_id: Optional[str] = None
    account_code: Optional[str] = None
    description: Optional[str] = None


class RasItemRequest(BaseModel):
    amount: float = Field(..., gt=0)
    due_date: str = Field(..., example="2026-05-15")


class CalculateRasRequest(BaseModel):
    base_date: str = Field(..., example="2026-04-01")
    cheques: List[RasItemRequest]


class CreatePosTerminalRequest(BaseModel):
    terminal_no: str = Field(..., example="TERM-01")
    merchant_id: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account_detail_id: Optional[str] = None


@app.post("/api/v1/tenants/{tenant_id}/treasury/cheques/receive", status_code=status.HTTP_201_CREATED)
def receive_cheque_endpoint(tenant_id: str, req: ReceiveChequeRequest):
    try:
        return treasury.receive_cheque(
            tenant_id=tenant_id,
            fiscal_year_id=req.fiscal_year_id,
            customer_detail_id=req.customer_detail_id,
            sayyad_id=req.sayyad_id,
            cheque_number=req.cheque_number,
            bank_name=req.bank_name,
            due_date=req.due_date,
            amount=req.amount,
            receive_date=req.receive_date,
            branch_name=req.branch_name,
            description=req.description,
        )
    except TreasuryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/tenants/{tenant_id}/treasury/cheques")
def list_cheques_endpoint(
    tenant_id: str,
    cheque_type: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    fiscal_year_id: Optional[str] = None,
):
    return treasury.list_cheques(
        tenant_id, cheque_type=cheque_type, status=status_filter, fiscal_year_id=fiscal_year_id
    )


@app.get("/api/v1/tenants/{tenant_id}/treasury/cheques/{cheque_id}")
def get_cheque_endpoint(tenant_id: str, cheque_id: str):
    try:
        return treasury.get_cheque(cheque_id)
    except TreasuryError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/treasury/cheques/{cheque_id}/deposit")
def deposit_cheque_endpoint(tenant_id: str, cheque_id: str, req: DepositChequeRequest):
    try:
        return treasury.deposit_cheque_to_bank(
            cheque_id=cheque_id,
            bank_account_detail_id=req.bank_account_detail_id,
            deposit_date=req.deposit_date,
        )
    except TreasuryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/treasury/cheques/{cheque_id}/clear")
def clear_cheque_endpoint(tenant_id: str, cheque_id: str, req: ClearChequeRequest):
    try:
        return treasury.clear_cheque(cheque_id=cheque_id, clear_date=req.clear_date)
    except TreasuryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/treasury/cheques/{cheque_id}/bounce")
def bounce_cheque_endpoint(tenant_id: str, cheque_id: str, req: ChequeStateRequest):
    try:
        return treasury.bounce_cheque(
            cheque_id, bounce_date=req.date, reason=req.reason
        )
    except TreasuryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/treasury/cheques/{cheque_id}/transfer")
def transfer_cheque_endpoint(tenant_id: str, cheque_id: str, req: TransferChequeRequest):
    try:
        return treasury.transfer_cheque(
            cheque_id, payee_detail_id=req.payee_detail_id, transfer_date=req.transfer_date
        )
    except TreasuryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/treasury/cheques/{cheque_id}/return")
def return_cheque_endpoint(tenant_id: str, cheque_id: str, req: ChequeStateRequest):
    try:
        return treasury.return_cheque(cheque_id, return_date=req.date)
    except TreasuryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post(
    "/api/v1/tenants/{tenant_id}/treasury/cheques/issue",
    status_code=status.HTTP_201_CREATED,
)
def issue_cheque_endpoint(tenant_id: str, req: IssueChequeRequest):
    try:
        return treasury.issue_cheque(
            tenant_id=tenant_id,
            fiscal_year_id=req.fiscal_year_id,
            payee_detail_id=req.payee_detail_id,
            sayyad_id=req.sayyad_id,
            cheque_number=req.cheque_number,
            bank_name=req.bank_name,
            bank_account_detail_id=req.bank_account_detail_id,
            due_date=req.due_date,
            amount=req.amount,
            issue_date=req.issue_date,
            branch_name=req.branch_name,
            description=req.description,
        )
    except TreasuryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/treasury/cheques/{cheque_id}/cancel")
def cancel_cheque_endpoint(tenant_id: str, cheque_id: str, req: ChequeStateRequest):
    try:
        return treasury.cancel_cheque(cheque_id, cancel_date=req.date)
    except TreasuryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/treasury/transactions", status_code=status.HTTP_201_CREATED)
def treasury_transaction_endpoint(tenant_id: str, req: TreasuryTransactionRequest):
    try:
        return treasury.record_transaction(
            tenant_id=tenant_id,
            fiscal_year_id=req.fiscal_year_id,
            tx_type=req.tx_type,
            method=req.method,
            amount=req.amount,
            tx_date=req.tx_date,
            party_detail_id=req.party_detail_id,
            bank_account_detail_id=req.bank_account_detail_id,
            pos_terminal_id=req.pos_terminal_id,
            cheque_id=req.cheque_id,
            account_code=req.account_code,
            description=req.description,
        )
    except TreasuryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/tenants/{tenant_id}/treasury/transactions")
def list_treasury_transactions_endpoint(tenant_id: str, tx_type: Optional[str] = None):
    return treasury.list_transactions(tenant_id, tx_type=tx_type)


@app.post("/api/v1/tenants/{tenant_id}/treasury/pos", status_code=status.HTTP_201_CREATED)
def create_pos_terminal_endpoint(tenant_id: str, req: CreatePosTerminalRequest):
    term_id = treasury.create_pos_terminal(
        tenant_id,
        req.terminal_no,
        merchant_id=req.merchant_id,
        bank_name=req.bank_name,
        bank_account_detail_id=req.bank_account_detail_id,
    )
    return {"pos_terminal_id": term_id}


@app.get("/api/v1/tenants/{tenant_id}/treasury/pos")
def list_pos_terminals_endpoint(tenant_id: str):
    return treasury.list_pos_terminals(tenant_id)


@app.post("/api/v1/tenants/{tenant_id}/treasury/ras")
def calculate_ras_endpoint(tenant_id: str, req: CalculateRasRequest):
    try:
        cheques_dict = [c.model_dump() for c in req.cheques]
        return treasury.calculate_ras(cheques_dict, req.base_date)
    except TreasuryError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Inventory & Warehouses (انبارداری)
# ---------------------------------------------------------------------------
class CreateWarehouseRequest(BaseModel):
    code: str = Field(..., example="01")
    title: str = Field(..., example="انبار مرکزی تهران")
    location: Optional[str] = None
    custodian: Optional[str] = None


class CreateProductRequest(BaseModel):
    sku: str = Field(..., example="PRD-101")
    title: str = Field(..., example="لپ‌تاپ گیمینگ ایسوس")
    unit: str = Field("عدد", example="عدد")
    category: Optional[str] = None
    min_stock_alert: float = Field(5.0, ge=0)
    sale_price: float = Field(0.0, ge=0)
    barcode: Optional[str] = None


class RecordReceiptRequest(BaseModel):
    fiscal_year_id: str
    warehouse_id: str
    product_id: str
    supplier_detail_id: str
    quantity: float = Field(..., gt=0)
    unit_cost: float = Field(..., ge=0)
    tx_date: str = Field(..., example="2026-04-10")
    description: Optional[str] = None


class RecordDeliveryRequest(BaseModel):
    fiscal_year_id: str
    warehouse_id: str
    product_id: str
    quantity: float = Field(..., gt=0)
    tx_date: str = Field(..., example="2026-04-15")
    reference_id: Optional[str] = None
    description: Optional[str] = None


class RecordReturnRequest(BaseModel):
    fiscal_year_id: str
    warehouse_id: str
    product_id: str
    quantity: float = Field(..., gt=0)
    tx_date: str = Field(..., example="2026-04-20")
    supplier_detail_id: Optional[str] = None
    description: Optional[str] = None


class RecordReconciliationRequest(BaseModel):
    fiscal_year_id: str
    warehouse_id: str
    product_id: str
    counted_quantity: float = Field(..., ge=0)
    tx_date: str = Field(..., example="2026-04-25")
    description: Optional[str] = None


@app.post("/api/v1/tenants/{tenant_id}/inventory/warehouses", status_code=status.HTTP_201_CREATED)
def create_warehouse_endpoint(tenant_id: str, req: CreateWarehouseRequest):
    try:
        wh_id = inventory.create_warehouse(tenant_id, req.code, req.title, req.location)
        return {"warehouse_id": wh_id, "message": "انبار با موفقیت ایجاد شد."}
    except InventoryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/tenants/{tenant_id}/inventory/warehouses")
def list_warehouses_endpoint(tenant_id: str):
    return inventory.list_warehouses(tenant_id)


@app.post("/api/v1/tenants/{tenant_id}/inventory/products", status_code=status.HTTP_201_CREATED)
def create_product_endpoint(tenant_id: str, req: CreateProductRequest):
    try:
        prod_id = inventory.create_product(
            tenant_id=tenant_id,
            sku=req.sku,
            title=req.title,
            unit=req.unit,
            min_stock_alert=req.min_stock_alert,
            sale_price=req.sale_price,
            barcode=req.barcode,
        )
        return {"product_id": prod_id, "message": "کالا با موفقیت تعریف شد."}
    except InventoryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/tenants/{tenant_id}/inventory/products")
def list_products_endpoint(tenant_id: str):
    return inventory.list_products(tenant_id)


@app.get("/api/v1/tenants/{tenant_id}/inventory/summary")
def stock_summary_endpoint(tenant_id: str):
    return inventory.get_stock_summary(tenant_id)


@app.post("/api/v1/tenants/{tenant_id}/inventory/receipts", status_code=status.HTTP_201_CREATED)
def record_receipt_endpoint(tenant_id: str, req: RecordReceiptRequest):
    try:
        return inventory.record_receipt(
            tenant_id=tenant_id,
            fiscal_year_id=req.fiscal_year_id,
            warehouse_id=req.warehouse_id,
            product_id=req.product_id,
            supplier_detail_id=req.supplier_detail_id,
            quantity=req.quantity,
            unit_cost=req.unit_cost,
            tx_date=req.tx_date,
            description=req.description,
        )
    except InventoryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/inventory/deliveries", status_code=status.HTTP_201_CREATED)
def record_delivery_endpoint(tenant_id: str, req: RecordDeliveryRequest):
    try:
        return inventory.record_delivery(
            tenant_id=tenant_id,
            fiscal_year_id=req.fiscal_year_id,
            warehouse_id=req.warehouse_id,
            product_id=req.product_id,
            quantity=req.quantity,
            tx_date=req.tx_date,
            reference_id=req.reference_id,
            description=req.description,
        )
    except InsufficientStockError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InventoryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/inventory/sales-returns", status_code=status.HTTP_201_CREATED)
def sales_return_endpoint(tenant_id: str, req: RecordReturnRequest):
    try:
        return inventory.record_sales_return(
            tenant_id=tenant_id,
            fiscal_year_id=req.fiscal_year_id,
            warehouse_id=req.warehouse_id,
            product_id=req.product_id,
            quantity=req.quantity,
            tx_date=req.tx_date,
            description=req.description,
        )
    except InventoryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/inventory/purchase-returns", status_code=status.HTTP_201_CREATED)
def purchase_return_endpoint(tenant_id: str, req: RecordReturnRequest):
    try:
        if not req.supplier_detail_id:
            raise HTTPException(status_code=400, detail="تفصیلی تأمین‌کننده الزامی است.")
        return inventory.record_purchase_return(
            tenant_id=tenant_id,
            fiscal_year_id=req.fiscal_year_id,
            warehouse_id=req.warehouse_id,
            product_id=req.product_id,
            supplier_detail_id=req.supplier_detail_id,
            quantity=req.quantity,
            tx_date=req.tx_date,
            description=req.description,
        )
    except InventoryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/inventory/reconciliation", status_code=status.HTTP_201_CREATED)
def reconciliation_endpoint(tenant_id: str, req: RecordReconciliationRequest):
    try:
        return inventory.record_stock_reconciliation(
            tenant_id=tenant_id,
            fiscal_year_id=req.fiscal_year_id,
            warehouse_id=req.warehouse_id,
            product_id=req.product_id,
            counted_quantity=req.counted_quantity,
            tx_date=req.tx_date,
            description=req.description,
        )
    except InventoryError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/tenants/{tenant_id}/inventory/kardex/{product_id}")
def get_kardex_endpoint(tenant_id: str, product_id: str):
    return inventory.get_stock_kardex(product_id)


@app.get("/api/v1/tenants/{tenant_id}/inventory/low-stock-alerts")
def get_low_stock_alerts_endpoint(tenant_id: str):
    return inventory.get_low_stock_alerts(tenant_id)


# ---------------------------------------------------------------------------
# Invoicing & Taxpayer System (فاکتور فروش و سامانه مؤدیان)
# ---------------------------------------------------------------------------
@app.post("/api/v1/tenants/{tenant_id}/invoices", status_code=status.HTTP_201_CREATED)
def create_invoice_endpoint(tenant_id: str, req: CreateInvoiceRequest):
    try:
        return invoicing.create_invoice(
            tenant_id=tenant_id,
            fiscal_year_id=req.fiscal_year_id,
            customer_detail_id=req.customer_detail_id,
            invoice_date=req.invoice_date,
            items=[i.model_dump() for i in req.items],
            tax_fiscal_id=req.tax_fiscal_id,
            pattern_code=req.pattern_code,
            invoice_type=req.invoice_type,
            payment_status=req.payment_status,
        )
    except InvoicingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/tenants/{tenant_id}/invoices")
def list_invoices_endpoint(tenant_id: str):
    return invoicing.list_invoices(tenant_id)


@app.get("/api/v1/tenants/{tenant_id}/invoices/{invoice_id}")
def get_invoice_endpoint(tenant_id: str, invoice_id: str):
    try:
        return invoicing.get_invoice(invoice_id)
    except InvoicingError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/invoices/{invoice_id}/confirm")
def confirm_invoice_endpoint(tenant_id: str, invoice_id: str):
    try:
        entry_id = invoicing.confirm_and_post_invoice(invoice_id)
        return {"journal_entry_id": entry_id, "message": "فاکتور تایید و سند حسابداری صادر شد."}
    except InvoicingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AccountingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/invoices/{invoice_id}/cancel")
def cancel_invoice_endpoint(tenant_id: str, invoice_id: str, reason: str = "ابطال توسط کاربر"):
    try:
        return invoicing.cancel_invoice(invoice_id, reason=reason)
    except InvoicingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/tenants/{tenant_id}/invoices/{invoice_id}/taxpayer")
def taxpayer_payload_endpoint(tenant_id: str, invoice_id: str):
    try:
        return invoicing.export_taxpayer_system_json(invoice_id)
    except InvoicingError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# Payroll & Statutory Labor (حقوق و دستمزد)
# ---------------------------------------------------------------------------
class RegisterEmployeeRequest(BaseModel):
    national_id: str = Field(...)
    full_name: str = Field(...)
    insurance_number: Optional[str] = None
    job_title: str = Field("کارشناس")
    base_monthly_salary: float = Field(..., gt=0)
    housing_allowance: float = Field(9000000.0, ge=0)
    grocery_allowance: float = Field(14000000.0, ge=0)
    child_count: int = Field(0, ge=0)
    phone: Optional[str] = None
    bank_shaba: Optional[str] = None


class PayrollEmployeeRecord(BaseModel):
    employee_id: str
    worked_days: int = Field(30, ge=1, le=31)
    overtime_hours: float = Field(0.0, ge=0)


class ProcessPayrollRequest(BaseModel):
    fiscal_year_id: str
    month_label: str = Field(...)
    run_date: str = Field(...)
    records: List[PayrollEmployeeRecord]


@app.post("/api/v1/tenants/{tenant_id}/payroll/employees", status_code=status.HTTP_201_CREATED)
def register_employee_endpoint(tenant_id: str, req: RegisterEmployeeRequest):
    try:
        return payroll.register_employee(
            tenant_id=tenant_id,
            national_id=req.national_id,
            full_name=req.full_name,
            insurance_number=req.insurance_number,
            job_title=req.job_title,
            base_monthly_salary=req.base_monthly_salary,
            housing_allowance=req.housing_allowance,
            grocery_allowance=req.grocery_allowance,
            child_count=req.child_count,
            phone=req.phone,
            bank_shaba=req.bank_shaba,
        )
    except PayrollError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/tenants/{tenant_id}/payroll/employees")
def list_employees_endpoint(tenant_id: str):
    return payroll.list_employees(tenant_id)


@app.post("/api/v1/tenants/{tenant_id}/payroll/process", status_code=status.HTTP_201_CREATED)
def process_payroll_endpoint(tenant_id: str, req: ProcessPayrollRequest):
    try:
        records_dict = [r.model_dump() for r in req.records]
        return payroll.process_monthly_payroll(
            tenant_id=tenant_id,
            fiscal_year_id=req.fiscal_year_id,
            month_label=req.month_label,
            run_date=req.run_date,
            records=records_dict,
        )
    except PayrollError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/tenants/{tenant_id}/payroll/runs")
def list_payroll_runs_endpoint(tenant_id: str):
    return payroll.list_payroll_runs(tenant_id)


@app.get("/api/v1/tenants/{tenant_id}/payroll/runs/{run_id}/payslips")
def payslips_endpoint(tenant_id: str, run_id: str):
    return payroll.get_payslips(run_id)


@app.get("/api/v1/tenants/{tenant_id}/payroll/runs/{run_id}/paya")
def export_paya_endpoint(tenant_id: str, run_id: str):
    return payroll.export_bank_payment_paya(run_id)


@app.get("/api/v1/tenants/{tenant_id}/payroll/tax-brackets")
def tax_brackets_endpoint(tenant_id: str):
    return payroll.tax_brackets()


# ---------------------------------------------------------------------------
# AI Financial Copilot (هوش مصنوعی مالی)
# ---------------------------------------------------------------------------
class ExtractInvoiceAIRequest(BaseModel):
    raw_text: str = Field(...)


class VoiceCommandRequest(BaseModel):
    instruction: str = Field(...)


@app.post("/api/v1/tenants/{tenant_id}/ai/extract-invoice")
def extract_invoice_ai_endpoint(tenant_id: str, req: ExtractInvoiceAIRequest):
    return copilot.parse_unstructured_invoice(req.raw_text)


@app.get("/api/v1/tenants/{tenant_id}/ai/cashflow-forecast")
def cashflow_forecast_endpoint(tenant_id: str, days_ahead: int = 30):
    return copilot.predict_cashflow_risks(tenant_id, days_ahead=days_ahead)


@app.post("/api/v1/tenants/{tenant_id}/ai/text-to-voucher")
def text_to_voucher_endpoint(tenant_id: str, req: VoiceCommandRequest):
    return copilot.natural_language_to_voucher(req.instruction)


# ---------------------------------------------------------------------------
# Fixed Assets & Depreciation (اموال، دارایی ثابت و استهلاک ماده ۱۴۹)
# ---------------------------------------------------------------------------
class RegisterAssetRequest(BaseModel):
    asset_code: str = Field(...)
    title: str = Field(...)
    category: str = Field(default="اثاثه و منصوبات")
    purchase_date: str = Field(...)
    purchase_cost: float = Field(...)
    salvage_value: float = Field(default=0.0)
    depreciation_method: str = Field(default="straight_line")
    useful_life_years: int = Field(default=5)
    depreciation_rate: float = Field(default=0.20)
    location: str = Field(default="دفتر مرکزی")
    custodian_name: Optional[str] = None
    asset_account_code: str = Field(default="2010")
    depr_account_code: str = Field(default="2110")
    expense_account_code: str = Field(default="7250")
    post_purchase_voucher: bool = Field(default=False)
    fiscal_year_id: Optional[str] = None
    settlement_account_code: str = Field(default="1010")


class RunDepreciationRequest(BaseModel):
    fiscal_year_id: str = Field(...)
    period_date: str = Field(...)
    period_name: str = Field(default="استهلاک پایان سال مالی")
    months: int = Field(default=12)


class DisposeAssetRequest(BaseModel):
    fiscal_year_id: str = Field(...)
    disposal_date: str = Field(...)
    disposal_type: str = Field(default="sale")
    sale_price: float = Field(default=0.0)
    settlement_account_code: str = Field(default="1010")


@app.get("/api/v1/tenants/{tenant_id}/fixed-assets")
def list_assets_endpoint(tenant_id: str, status: Optional[str] = None):
    return fixed_assets.list_assets(tenant_id, status=status)


@app.post("/api/v1/tenants/{tenant_id}/fixed-assets")
def register_asset_endpoint(tenant_id: str, req: RegisterAssetRequest):
    try:
        return fixed_assets.register_asset(
            tenant_id=tenant_id,
            asset_code=req.asset_code,
            title=req.title,
            category=req.category,
            purchase_date=req.purchase_date,
            purchase_cost=req.purchase_cost,
            salvage_value=req.salvage_value,
            depreciation_method=req.depreciation_method,
            useful_life_years=req.useful_life_years,
            depreciation_rate=req.depreciation_rate,
            location=req.location,
            custodian_name=req.custodian_name,
            asset_account_code=req.asset_account_code,
            depr_account_code=req.depr_account_code,
            expense_account_code=req.expense_account_code,
            post_purchase_voucher=req.post_purchase_voucher,
            fiscal_year_id=req.fiscal_year_id,
            settlement_account_code=req.settlement_account_code,
        )
    except FixedAssetError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/fixed-assets/depreciation/run")
def run_depreciation_endpoint(tenant_id: str, req: RunDepreciationRequest):
    try:
        return fixed_assets.run_depreciation_cycle(
            tenant_id=tenant_id,
            fiscal_year_id=req.fiscal_year_id,
            period_date=req.period_date,
            period_name=req.period_name,
            months=req.months,
        )
    except FixedAssetError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/fixed-assets/{asset_code}/dispose")
def dispose_asset_endpoint(tenant_id: str, asset_code: str, req: DisposeAssetRequest):
    try:
        return fixed_assets.dispose_asset(
            tenant_id=tenant_id,
            fiscal_year_id=req.fiscal_year_id,
            asset_code=asset_code,
            disposal_date=req.disposal_date,
            disposal_type=req.disposal_type,
            sale_price=req.sale_price,
            settlement_account_code=req.settlement_account_code,
        )
    except FixedAssetError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Manufacturing & BOM (تولید، فرمول ساخت و بهای تمام‌شده صنعتی)
# ---------------------------------------------------------------------------
class CreateBOMRequest(BaseModel):
    target_product_id: str = Field(...)
    title: str = Field(...)
    items: List[Dict[str, Any]] = Field(...)
    standard_qty: float = Field(default=1.0)
    direct_labor_rate: float = Field(default=0.0)
    overhead_rate: float = Field(default=0.0)


class CreateProductionOrderRequest(BaseModel):
    order_no: str = Field(...)
    bom_id: str = Field(...)
    planned_qty: float = Field(...)
    start_date: str = Field(...)
    end_date: Optional[str] = None


class StartProductionRequest(BaseModel):
    fiscal_year_id: str = Field(...)
    warehouse_id: str = Field(...)
    issue_date: str = Field(...)


class CompleteProductionRequest(BaseModel):
    fiscal_year_id: str = Field(...)
    warehouse_id: str = Field(...)
    completion_date: str = Field(...)
    actual_qty: Optional[float] = None


@app.get("/api/v1/tenants/{tenant_id}/manufacturing/boms")
def list_boms_endpoint(tenant_id: str):
    return manufacturing.list_boms(tenant_id)


@app.post("/api/v1/tenants/{tenant_id}/manufacturing/boms")
def create_bom_endpoint(tenant_id: str, req: CreateBOMRequest):
    try:
        return manufacturing.create_bom(
            tenant_id=tenant_id,
            target_product_id=req.target_product_id,
            title=req.title,
            items=req.items,
            standard_qty=req.standard_qty,
            direct_labor_rate=req.direct_labor_rate,
            overhead_rate=req.overhead_rate,
        )
    except ManufacturingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/tenants/{tenant_id}/manufacturing/orders")
def list_orders_endpoint(tenant_id: str, status: Optional[str] = None):
    return manufacturing.list_orders(tenant_id, status=status)


@app.post("/api/v1/tenants/{tenant_id}/manufacturing/orders")
def create_order_endpoint(tenant_id: str, req: CreateProductionOrderRequest):
    try:
        return manufacturing.create_production_order(
            tenant_id=tenant_id,
            order_no=req.order_no,
            bom_id=req.bom_id,
            planned_qty=req.planned_qty,
            start_date=req.start_date,
            end_date=req.end_date,
        )
    except ManufacturingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/manufacturing/orders/{order_id}/start")
def start_production_endpoint(tenant_id: str, order_id: str, req: StartProductionRequest):
    try:
        return manufacturing.start_production(
            tenant_id=tenant_id,
            fiscal_year_id=req.fiscal_year_id,
            order_id=order_id,
            warehouse_id=req.warehouse_id,
            issue_date=req.issue_date,
        )
    except ManufacturingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/manufacturing/orders/{order_id}/complete")
def complete_production_endpoint(tenant_id: str, order_id: str, req: CompleteProductionRequest):
    try:
        return manufacturing.complete_production(
            tenant_id=tenant_id,
            fiscal_year_id=req.fiscal_year_id,
            order_id=order_id,
            warehouse_id=req.warehouse_id,
            completion_date=req.completion_date,
            actual_qty=req.actual_qty,
        )
    except ManufacturingError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Contracting & Progress Billings (پیمانکاری، قراردادها و صورت‌وضعیت‌ها)
# ---------------------------------------------------------------------------
class CreateContractRequest(BaseModel):
    contract_no: str = Field(...)
    title: str = Field(...)
    total_amount: float = Field(...)
    start_date: str = Field(...)
    employer_sub_ledger_id: Optional[str] = None
    end_date: Optional[str] = None
    retention_rate: float = Field(default=0.10)
    sso_rate: float = Field(default=0.05)
    advance_received: float = Field(default=0.0)


class SubmitProgressBillingRequest(BaseModel):
    contract_id: str = Field(...)
    billing_no: str = Field(...)
    billing_date: str = Field(...)
    gross_amount: float = Field(...)
    advance_amortization: float = Field(default=0.0)


class ConfirmBillingRequest(BaseModel):
    fiscal_year_id: str = Field(...)


@app.get("/api/v1/tenants/{tenant_id}/contracting/contracts")
def list_contracts_endpoint(tenant_id: str):
    return contracting.list_contracts(tenant_id)


@app.post("/api/v1/tenants/{tenant_id}/contracting/contracts")
def create_contract_endpoint(tenant_id: str, req: CreateContractRequest):
    try:
        return contracting.create_contract(
            tenant_id=tenant_id,
            contract_no=req.contract_no,
            title=req.title,
            total_amount=req.total_amount,
            start_date=req.start_date,
            employer_sub_ledger_id=req.employer_sub_ledger_id,
            end_date=req.end_date,
            retention_rate=req.retention_rate,
            sso_rate=req.sso_rate,
            advance_received=req.advance_received,
        )
    except ContractingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/tenants/{tenant_id}/contracting/billings")
def list_billings_endpoint(tenant_id: str, contract_id: Optional[str] = None):
    return contracting.list_billings(tenant_id, contract_id=contract_id)


@app.post("/api/v1/tenants/{tenant_id}/contracting/billings")
def submit_billing_endpoint(tenant_id: str, req: SubmitProgressBillingRequest):
    try:
        return contracting.submit_progress_billing(
            tenant_id=tenant_id,
            contract_id=req.contract_id,
            billing_no=req.billing_no,
            billing_date=req.billing_date,
            gross_amount=req.gross_amount,
            advance_amortization=req.advance_amortization,
        )
    except ContractingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/tenants/{tenant_id}/contracting/billings/{billing_id}/confirm")
def confirm_billing_endpoint(tenant_id: str, billing_id: str, req: ConfirmBillingRequest):
    try:
        return contracting.confirm_progress_billing(
            tenant_id=tenant_id,
            fiscal_year_id=req.fiscal_year_id,
            billing_id=billing_id,
        )
    except ContractingError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Document Flow & Traceability (ارتباط اسناد و پیگیری زنجیره فرآیندها)
# ---------------------------------------------------------------------------
@app.get("/api/v1/tenants/{tenant_id}/document-flow/recent")
def list_recent_flows_endpoint(tenant_id: str, limit: int = 25):
    """
    لیست اسناد اخیر در تمامی ماژول‌ها جهت بررسی فوری در ارتباط اسناد
    """
    return document_flow.list_recent_flows(tenant_id, limit=limit)


@app.get("/api/v1/tenants/{tenant_id}/document-flow/{entity_type}/{entity_id}")
def get_document_flow_endpoint(tenant_id: str, entity_type: str, entity_id: str):
    """
    دریافت گراف ارتباط اسناد، مراحل ۵ گانه و لاگ‌های سیستمی ردپای عملیات
    """
    try:
        return document_flow.get_document_flow(tenant_id, entity_type, entity_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
