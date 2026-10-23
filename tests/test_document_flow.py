"""
Automated Verification Suite for Arbin Document Flow & Audit Lifecycle Engine
"""

import sys
import os
import tempfile
import sqlite3
from pathlib import Path

# Add core to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ledger import ArbinLedger
from invoicing import ArbinInvoicing
from inventory import ArbinInventory
from treasury import ArbinTreasury
from document_flow import ArbinDocumentFlow
from seed_data import seed_demo_company, DEFAULT_TENANT_ID, DEFAULT_FISCAL_YEAR_ID


def run_tests():
    print("=" * 60)
    print(" ARBIN DOCUMENT FLOW ENGINE — VERIFICATION TESTS")
    print("=" * 60)

    db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_file.close()

    try:
        schema_path = Path(__file__).parent.parent / "schema.sql"
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        conn = sqlite3.connect(db_file.name)
        conn.executescript(schema_sql)
        conn.close()

        ledger = ArbinLedger(db_file.name)
        seed_demo_company(ledger)

        invoicing = ArbinInvoicing(ledger)
        inventory = ArbinInventory(ledger)
        treasury = ArbinTreasury(ledger)
        doc_flow = ArbinDocumentFlow(ledger)

        tenant_id = DEFAULT_TENANT_ID
        fy_id = DEFAULT_FISCAL_YEAR_ID

        with ledger.get_connection() as c:
            cust = c.execute("SELECT id FROM sub_ledgers WHERE code = '4001'").fetchone()[0]
            supp = c.execute("SELECT id FROM sub_ledgers WHERE code = '3001'").fetchone()[0]
            wh = c.execute("SELECT id FROM warehouses LIMIT 1").fetchone()[0]
            prod = c.execute("SELECT id, sku FROM products LIMIT 1").fetchone()

        print("[OK] Test Database seeded with standard chart of accounts, customers, warehouses, and products.")

        # 1. First record receipt so stock exists
        inventory.record_receipt(
            tenant_id=tenant_id,
            fiscal_year_id=fy_id,
            warehouse_id=wh,
            product_id=prod["id"],
            supplier_detail_id=supp,
            quantity=10,
            unit_cost=30_000_000,
            tx_date="2026-04-05",
            description="رسید اولیه انبار مرکزی",
            user_id="انباردار"
        )

        # 2. Create & confirm sales invoice
        inv_res = invoicing.create_invoice(
            tenant_id=tenant_id,
            fiscal_year_id=fy_id,
            customer_detail_id=cust,
            invoice_date="2026-04-10",
            items=[{
                "item_code": prod["sku"],
                "item_title": "اشتراک سازمانی نرم‌افزار آربین",
                "unit": "سال",
                "quantity": 2,
                "unit_price": 50_000_000,
                "discount": 0,
                "vat_rate": 0.10
            }]
        )
        inv_id = inv_res["invoice_id"]
        voucher_id = invoicing.confirm_and_post_invoice(inv_id, user_id="آریا کمالی")
        assert voucher_id is not None
        print(f"[OK] Invoice #{inv_res['invoice_number']} created and Journal Voucher #{voucher_id} posted.")

        # 3. Record warehouse delivery
        deliv = inventory.record_delivery(
            tenant_id=tenant_id,
            fiscal_year_id=fy_id,
            warehouse_id=wh,
            product_id=prod["id"],
            quantity=2,
            tx_date="2026-04-10",
            reference_id=inv_id,
            description="حواله خروج بابت فاکتور فروش",
            user_id="مسئول انبار"
        )
        assert deliv["transaction_id"] is not None
        print(f"[OK] Warehouse delivery #{deliv['transaction_id']} recorded.")

        # 4. Receive Sayyad Cheque
        cheque = treasury.receive_cheque(
            tenant_id=tenant_id,
            fiscal_year_id=fy_id,
            customer_detail_id=cust,
            sayyad_id="1122334455667788",
            cheque_number="789012",
            bank_name="بانک صادرات ایران",
            due_date="2026-07-20",
            amount=110_000_000,
            receive_date="2026-04-10",
            user_id="آریا کمالی"
        )
        assert cheque["cheque_id"] is not None
        print(f"[OK] Sayyad Cheque #{cheque['cheque_id']} received in safe.")

        # 5. Test List Recent Flows
        recent = doc_flow.list_recent_flows(tenant_id)
        assert len(recent) >= 1
        assert any(r["entity_type"] == "invoice" for r in recent)
        print(f"[OK] List recent flows returned {len(recent)} entries.")

        # 6. Test Document Flow from Invoice
        flow_inv = doc_flow.get_document_flow(tenant_id, "invoice", inv_id)
        assert flow_inv["summary"]["amount"] == 110_000_000.0
        assert len(flow_inv["stages"]) == 5
        stages = {s["stage_id"]: s["state"] for s in flow_inv["stages"]}
        assert stages["draft"] == "completed"
        assert stages["inventory"] == "completed"
        assert stages["voucher"] == "completed"
        assert stages["settlement"] == "completed"
        assert stages["taxpayer"] == "completed"

        node_types = [n["type"] for n in flow_inv["nodes"]]
        assert "invoice" in node_types
        assert "inventory" in node_types
        assert "journal_voucher" in node_types
        assert "cheque" in node_types
        assert "taxpayer" in node_types
        print(f"[OK] Invoice flow verified: 5 stages completed, {len(flow_inv['nodes'])} connected nodes.")

        # 7. Test Document Flow from Journal Entry
        flow_je = doc_flow.get_document_flow(tenant_id, "journal_entry", voucher_id)
        assert flow_je["summary"]["node_count"] >= 3
        je_node_types = [n["type"] for n in flow_je["nodes"]]
        assert "journal_voucher" in je_node_types
        assert "invoice" in je_node_types
        print(f"[OK] Journal entry #{voucher_id} reverse-linked correctly to root invoice.")

        print("=" * 60)
        print(" ALL DOCUMENT FLOW TESTS PASSED SUCCESSFULLY! (100%)")
        print("=" * 60)

    finally:
        if os.path.exists(db_file.name):
            os.unlink(db_file.name)


if __name__ == "__main__":
    run_tests()
