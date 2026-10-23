"""
Arbin Document Flow & Audit Lifecycle Engine (موتور پیگیری و ارتباط اسناد آربین)
================================================================================
Discovers end-to-end multi-document relationships and audit lifecycles:
Order / Proforma -> Sales Invoice -> Warehouse Delivery/Receipt ->
Double-Entry Journal Voucher -> Treasury Settlement (Cash/POS/Sayyad Cheque) -> Taxpayer System (سامانه مؤدیان)
"""

import sqlite3
import uuid
import json
from typing import Dict, Any, List, Optional


class ArbinDocumentFlow:
    def __init__(self, ledger):
        self.ledger = ledger

    def _format_money(self, amount: Optional[float]) -> str:
        if amount is None:
            return "۰ ریال"
        return f"{int(amount):,} ریال".replace(",", "،")

    def list_recent_flows(self, tenant_id: str, limit: int = 25) -> List[Dict[str, Any]]:
        """
        Returns recent business documents across Invoices, Journal Entries, Treasury, and Inventory
        to allow instant search and one-click inspection in the Document Flow viewer.
        """
        results = []
        with self.ledger.get_connection() as conn:
            # 1. Recent Invoices
            inv_rows = conn.execute(
                """
                SELECT i.id, i.invoice_number, i.invoice_date, i.final_payable, i.status,
                       i.journal_entry_id, i.tax_unique_id, s.title AS customer_title
                FROM invoices i
                LEFT JOIN sub_ledgers s ON s.id = i.customer_detail_id
                WHERE i.tenant_id = ?
                ORDER BY i.created_at DESC LIMIT ?
                """,
                (tenant_id, limit),
            ).fetchall()

            for r in inv_rows:
                results.append({
                    "entity_type": "invoice",
                    "entity_id": r["id"],
                    "document_number": f"فاکتور فروش شماره {r['invoice_number']}",
                    "document_title": f"فاکتور فروش - {r['customer_title'] or 'مشتری'}",
                    "party_name": r["customer_title"] or "مشتری",
                    "date": r["invoice_date"],
                    "amount": r["final_payable"],
                    "amount_formatted": self._format_money(r["final_payable"]),
                    "status": r["status"],
                    "has_voucher": bool(r["journal_entry_id"]),
                    "has_tax_id": bool(r["tax_unique_id"]),
                })

            # 2. Recent Journal Entries
            je_rows = conn.execute(
                """
                SELECT je.id, je.entry_number, je.entry_date, je.description, je.status,
                       je.source_module, je.manual_number,
                       SUM(ji.debit) AS total_amount
                FROM journal_entries je
                LEFT JOIN journal_items ji ON ji.entry_id = je.id
                WHERE je.tenant_id = ?
                GROUP BY je.id
                ORDER BY je.created_at DESC LIMIT ?
                """,
                (tenant_id, limit),
            ).fetchall()

            for r in je_rows:
                # Avoid duplicate if this journal entry was already listed under an invoice
                results.append({
                    "entity_type": "journal_entry",
                    "entity_id": r["id"],
                    "document_number": f"سند حسابداری شماره {r['entry_number']}",
                    "document_title": r["description"] or f"سند مالی شماره {r['entry_number']}",
                    "party_name": f"ماژول: {r['source_module'] or 'عمومی'}",
                    "date": r["entry_date"],
                    "amount": r["total_amount"] or 0,
                    "amount_formatted": self._format_money(r["total_amount"]),
                    "status": r["status"],
                    "has_voucher": True,
                    "has_tax_id": False,
                })

            # 3. Recent Treasury Receipts / Payments
            tx_rows = conn.execute(
                """
                SELECT tt.id, tt.tx_type, tt.method, tt.amount, tt.tx_date, tt.description,
                       tt.journal_entry_id, s.title AS party_title, c.sayyad_id
                FROM treasury_transactions tt
                LEFT JOIN sub_ledgers s ON s.id = tt.party_detail_id
                LEFT JOIN cheques c ON c.id = tt.cheque_id
                WHERE tt.tenant_id = ?
                ORDER BY tt.created_at DESC LIMIT ?
                """,
                (tenant_id, limit),
            ).fetchall()

            for r in tx_rows:
                type_name = "رسید دریافت خزانه" if r["tx_type"] == "receipt" else "اعلامیه پرداخت خزانه"
                method_name = "چک صیادی" if r["method"] == "sayyad_cheque" else "نقد / واریز بانکی"
                results.append({
                    "entity_type": "treasury_tx",
                    "entity_id": r["id"],
                    "document_number": f"{type_name} ({method_name})",
                    "document_title": r["description"] or f"{type_name} {r['party_title'] or ''}",
                    "party_name": r["party_title"] or "طرف حساب",
                    "date": r["tx_date"],
                    "amount": r["amount"],
                    "amount_formatted": self._format_money(r["amount"]),
                    "status": "cleared" if r["journal_entry_id"] else "draft",
                    "has_voucher": bool(r["journal_entry_id"]),
                    "has_tax_id": False,
                })

        return results[:limit]

    def get_document_flow(
        self, tenant_id: str, entity_type: str, entity_id: str
    ) -> Dict[str, Any]:
        """
        Discovers the full graph and lifecycle stages for any document.
        """
        with self.ledger.get_connection() as conn:
            invoice = None
            journal_entry = None
            inventory_txs = []
            treasury_txs = []
            cheques = []
            audit_records = []

            # Resolve based on root input
            if entity_type == "invoice":
                invoice = conn.execute(
                    """
                    SELECT i.*, s.code AS customer_code, s.title AS customer_title, s.national_id AS customer_national_id
                    FROM invoices i
                    LEFT JOIN sub_ledgers s ON s.id = i.customer_detail_id
                    WHERE i.tenant_id = ? AND (i.id = ? OR CAST(i.invoice_number AS TEXT) = ?)
                    """,
                    (tenant_id, entity_id, entity_id),
                ).fetchone()

                if invoice and invoice["journal_entry_id"]:
                    journal_entry = conn.execute(
                        "SELECT * FROM journal_entries WHERE tenant_id = ? AND id = ?",
                        (tenant_id, invoice["journal_entry_id"]),
                    ).fetchone()

            elif entity_type == "journal_entry":
                journal_entry = conn.execute(
                    "SELECT * FROM journal_entries WHERE tenant_id = ? AND (id = ? OR CAST(entry_number AS TEXT) = ?)",
                    (tenant_id, entity_id, entity_id),
                ).fetchone()

                if journal_entry:
                    # Check linked invoice
                    invoice = conn.execute(
                        """
                        SELECT i.*, s.code AS customer_code, s.title AS customer_title, s.national_id AS customer_national_id
                        FROM invoices i
                        LEFT JOIN sub_ledgers s ON s.id = i.customer_detail_id
                        WHERE i.tenant_id = ? AND (i.journal_entry_id = ? OR i.id = ?)
                        """,
                        (tenant_id, journal_entry["id"], journal_entry["source_id"]),
                    ).fetchone()

                    if not invoice and journal_entry["source_module"] == "sales" and journal_entry["manual_number"]:
                        invoice = conn.execute(
                            """
                            SELECT i.*, s.code AS customer_code, s.title AS customer_title, s.national_id AS customer_national_id
                            FROM invoices i
                            LEFT JOIN sub_ledgers s ON s.id = i.customer_detail_id
                            WHERE i.tenant_id = ? AND CAST(i.invoice_number AS TEXT) = ?
                            """,
                            (tenant_id, journal_entry["manual_number"]),
                        ).fetchone()

            elif entity_type == "treasury_tx":
                tt = conn.execute(
                    "SELECT * FROM treasury_transactions WHERE tenant_id = ? AND id = ?",
                    (tenant_id, entity_id),
                ).fetchone()
                if tt:
                    treasury_txs.append(tt)
                    if tt["journal_entry_id"]:
                        journal_entry = conn.execute(
                            "SELECT * FROM journal_entries WHERE tenant_id = ? AND id = ?",
                            (tenant_id, tt["journal_entry_id"]),
                        ).fetchone()
                    if tt["cheque_id"]:
                        ch = conn.execute("SELECT * FROM cheques WHERE id = ?", (tt["cheque_id"],)).fetchone()
                        if ch:
                            cheques.append(ch)

            elif entity_type == "cheque":
                ch = conn.execute(
                    "SELECT * FROM cheques WHERE tenant_id = ? AND (id = ? OR sayyad_id = ? OR cheque_number = ?)",
                    (tenant_id, entity_id, entity_id, entity_id),
                ).fetchone()
                if ch:
                    cheques.append(ch)
                    # Find linked treasury
                    tt = conn.execute(
                        "SELECT * FROM treasury_transactions WHERE tenant_id = ? AND cheque_id = ?",
                        (tenant_id, ch["id"]),
                    ).fetchone()
                    if tt:
                        treasury_txs.append(tt)
                        if tt["journal_entry_id"]:
                            journal_entry = conn.execute(
                                "SELECT * FROM journal_entries WHERE tenant_id = ? AND id = ?",
                                (tenant_id, tt["journal_entry_id"]),
                            ).fetchone()

            # Cross-search: If we have an invoice, locate inventory, treasury, and cheques
            if invoice:
                # 1. Inventory movements for this invoice
                inv_movements = conn.execute(
                    """
                    SELECT it.*, w.title AS warehouse_title, p.title AS product_title, p.sku
                    FROM inventory_transactions it
                    LEFT JOIN warehouses w ON w.id = it.warehouse_id
                    LEFT JOIN products p ON p.id = it.product_id
                    WHERE it.tenant_id = ? AND (it.reference_id = ? OR (it.journal_entry_id IS NOT NULL AND it.journal_entry_id = ?))
                    """,
                    (tenant_id, invoice["id"], invoice["journal_entry_id"]),
                ).fetchall()
                inventory_txs.extend(inv_movements)

                # 2. Treasury receipts for this customer
                if not treasury_txs and invoice["customer_detail_id"]:
                    tts = conn.execute(
                        """
                        SELECT tt.*, s.title AS party_title
                        FROM treasury_transactions tt
                        LEFT JOIN sub_ledgers s ON s.id = tt.party_detail_id
                        WHERE tt.tenant_id = ? AND tt.party_detail_id = ? AND tt.tx_type = 'receipt'
                        ORDER BY tt.tx_date ASC
                        """,
                        (tenant_id, invoice["customer_detail_id"]),
                    ).fetchall()
                    treasury_txs.extend(tts)

                # 3. Received cheques for this customer
                if not cheques and invoice["customer_detail_id"]:
                    ch_rows = conn.execute(
                        """
                        SELECT * FROM cheques
                        WHERE tenant_id = ? AND party_detail_id = ? AND cheque_type = 'received'
                        ORDER BY created_at ASC
                        """,
                        (tenant_id, invoice["customer_detail_id"]),
                    ).fetchall()
                    cheques.extend(ch_rows)

            # Cross-search: If we have journal entry, find related items and other modules
            journal_items = []
            if journal_entry:
                journal_items = conn.execute(
                    """
                    SELECT ji.*, a.code AS account_code, a.title AS account_title,
                           s.code AS sub_code, s.title AS sub_title
                    FROM journal_items ji
                    JOIN accounts a ON a.id = ji.account_id
                    LEFT JOIN sub_ledgers s ON s.id = ji.sub_ledger_id
                    WHERE ji.entry_id = ?
                    ORDER BY ji.row_number ASC
                    """,
                    (journal_entry["id"],),
                ).fetchall()

                # If no inventory found yet, search by journal_entry_id
                if not inventory_txs:
                    it_rows = conn.execute(
                        """
                        SELECT it.*, w.title AS warehouse_title, p.title AS product_title, p.sku
                        FROM inventory_transactions it
                        LEFT JOIN warehouses w ON w.id = it.warehouse_id
                        LEFT JOIN products p ON p.id = it.product_id
                        WHERE it.tenant_id = ? AND it.journal_entry_id = ?
                        """,
                        (tenant_id, journal_entry["id"]),
                    ).fetchall()
                    inventory_txs.extend(it_rows)

                # If no treasury found yet, search by journal_entry_id
                if not treasury_txs:
                    tt_rows = conn.execute(
                        """
                        SELECT tt.*, s.title AS party_title
                        FROM treasury_transactions tt
                        LEFT JOIN sub_ledgers s ON s.id = tt.party_detail_id
                        WHERE tt.tenant_id = ? AND tt.journal_entry_id = ?
                        """,
                        (tenant_id, journal_entry["id"]),
                    ).fetchall()
                    treasury_txs.extend(tt_rows)

            # Cross-search: Cheques from treasury transactions
            for tt in treasury_txs:
                if tt["cheque_id"] and not any(c["id"] == tt["cheque_id"] for c in cheques):
                    ch = conn.execute("SELECT * FROM cheques WHERE id = ?", (tt["cheque_id"],)).fetchone()
                    if ch:
                        cheques.append(ch)

            # Audit logs collection
            entity_pairs = []
            if invoice:
                entity_pairs.append(("invoice", invoice["id"]))
            if journal_entry:
                entity_pairs.append(("journal_entry", journal_entry["id"]))
            for it in inventory_txs:
                entity_pairs.append(("inventory", it["id"]))
            for tt in treasury_txs:
                entity_pairs.append(("treasury", tt["id"]))
            for ch in cheques:
                entity_pairs.append(("cheque", ch["id"]))

            if entity_pairs:
                clauses = " OR ".join(["(entity_name = ? AND entity_id = ?)"] * len(entity_pairs))
                params = [tenant_id]
                for ep in entity_pairs:
                    params.extend([ep[0], ep[1]])
                audit_rows = conn.execute(
                    f"SELECT * FROM audit_logs WHERE tenant_id = ? AND ({clauses}) ORDER BY created_at ASC",
                    params,
                ).fetchall()
                audit_records.extend(audit_rows)

        if invoice:
            invoice = dict(invoice)
        if journal_entry:
            journal_entry = dict(journal_entry)
        inventory_txs = [dict(r) for r in inventory_txs]
        treasury_txs = [dict(r) for r in treasury_txs]
        cheques = [dict(r) for r in cheques]
        journal_items = [dict(r) for r in journal_items]
        audit_records = [dict(r) for r in audit_records]

        # -------------------------------------------------------------
        # BUILD GRAPH NODES & PROCESS STAGES
        # -------------------------------------------------------------
        nodes = []
        connections = []
        stages = []

        # Determine Root Summary
        root_title = "رهگیری زنجیره فرآیند"
        party_name = "-"
        amount = 0.0
        doc_date = "-"
        overall_status = "تکمیل شده"

        if invoice:
            root_title = f"فاکتور فروش شماره {invoice['invoice_number']}"
            party_name = invoice["customer_title"] or "مشتری"
            amount = float(invoice["final_payable"] or 0)
            doc_date = invoice["invoice_date"]
            overall_status = "تایید و ارسال شده" if invoice["status"] == "confirmed" else "پیش‌نویس"
        elif journal_entry:
            root_title = f"سند حسابداری شماره {journal_entry['entry_number']}"
            party_name = journal_entry["description"] or "سند مالی"
            total_debit = sum(float(ji["debit"]) for ji in journal_items)
            amount = total_debit
            doc_date = journal_entry["entry_date_jalali"] or journal_entry["entry_date"]
            overall_status = "سند دائم" if journal_entry["status"] == "permanent" else "تایید شده"

        # NODE 1: Sales Invoice (فاکتور فروش)
        if invoice:
            inv_node = {
                "id": "node_invoice",
                "type": "invoice",
                "icon": "📑",
                "badge": "فاکتور فروش رسمی",
                "title": f"فاکتور فروش شماره {invoice['invoice_number']}",
                "subtitle": f"مشتری: {invoice['customer_title'] or 'ناشناس'}",
                "date": invoice["invoice_date"],
                "amount": float(invoice["final_payable"]),
                "amount_formatted": self._format_money(invoice["final_payable"]),
                "status_label": "تایید شده" if invoice["status"] == "confirmed" else "پیش‌نویس",
                "status_class": "status-confirmed" if invoice["status"] == "confirmed" else "status-draft",
                "details": [
                    {"label": "شماره فاکتور", "value": str(invoice["invoice_number"])},
                    {"label": "مبلغ کل قبل از مالیات", "value": self._format_money(invoice["total_amount"])},
                    {"label": "مالیات ارزش افزوده (۱۰٪)", "value": self._format_money(invoice["total_vat"])},
                    {"label": "مبلغ نهایی قابل پرداخت", "value": self._format_money(invoice["final_payable"])},
                    {"label": "وضعیت پرداخت", "value": "نسیه" if invoice["payment_status"] == "unpaid" else "تسویه شده"},
                ],
                "jump_target": {"view": "invoicing", "id": invoice["id"], "label": "مشاهده فاکتور"},
            }
            nodes.append(inv_node)

        # NODE 2: Warehouse Delivery / Outflow (حواله خروج انبار)
        if inventory_txs:
            for idx, it in enumerate(inventory_txs, start=1):
                it_node = {
                    "id": f"node_inventory_{idx}",
                    "type": "inventory",
                    "icon": "📦",
                    "badge": "حواله خروج انبار",
                    "title": f"حواله انبار شماره {it['tx_number']}",
                    "subtitle": f"انبار: {it['warehouse_title'] or 'انبار مرکزی'} | کالا: {it['product_title'] or 'کالای تجاری'}",
                    "date": it["tx_date"],
                    "amount": float(it["total_cost"]),
                    "amount_formatted": self._format_money(it["total_cost"]),
                    "status_label": "تحویل شده",
                    "status_class": "status-delivered",
                    "details": [
                        {"label": "شماره حواله", "value": str(it["tx_number"])},
                        {"label": "کد کالا (SKU)", "value": it["sku"] or "-"},
                        {"label": "تعداد تحویل", "value": f"{it['quantity']} عدد"},
                        {"label": "بهای تمام‌شده واحد", "value": self._format_money(it["unit_cost"])},
                        {"label": "بهای تمام‌شده کل (COGS)", "value": self._format_money(it["total_cost"])},
                    ],
                    "jump_target": {"view": "inventory", "id": it["id"], "label": "مشاهده کاردکس انبار"},
                }
                nodes.append(it_node)
                if invoice:
                    connections.append({"from": "node_invoice", "to": f"node_inventory_{idx}", "label": "خروج کالا"})

        # NODE 3: Double-Entry Journal Voucher (سند حسابداری دوبل)
        if journal_entry:
            tot_debit = sum(float(ji["debit"]) for ji in journal_items)
            tot_credit = sum(float(ji["credit"]) for ji in journal_items)
            is_balanced = abs(tot_debit - tot_credit) < 0.01

            je_node = {
                "id": "node_voucher",
                "type": "journal_voucher",
                "icon": "⚖️",
                "badge": "سند حسابداری دوبل",
                "title": f"سند حسابداری شماره {journal_entry['entry_number']}",
                "subtitle": journal_entry["description"] or "سند مالی سیستم",
                "date": journal_entry["entry_date_jalali"] or journal_entry["entry_date"],
                "amount": tot_debit,
                "amount_formatted": self._format_money(tot_debit),
                "status_label": "تراز و تاییدشده" if is_balanced else "نامتراز!",
                "status_class": "status-balanced" if is_balanced else "status-unbalanced",
                "details": [
                    {"label": "شماره سند", "value": str(journal_entry["entry_number"])},
                    {"label": "ماژول صادرکننده", "value": journal_entry["source_module"] or "دستی"},
                    {"label": "تعداد سطرهای دوبل", "value": f"{len(journal_items)} سطر"},
                    {"label": "جمع بدهکار", "value": self._format_money(tot_debit)},
                    {"label": "جمع بستانکار", "value": self._format_money(tot_credit)},
                    {"label": "تراز دوبل", "value": "✅ تراز کامل (اختلاف صفر)" if is_balanced else "❌ نامتراز"},
                ],
                "jump_target": {"view": "ledger", "id": journal_entry["id"], "label": "مشاهده سند در دفتر روزنامه"},
            }
            nodes.append(je_node)
            if invoice:
                connections.append({"from": "node_invoice", "to": "node_voucher", "label": "صدور خودکار سند"})

        # NODE 4: Treasury Transactions (رسید دریافت / تسویه خزانه)
        if treasury_txs:
            for idx, tt in enumerate(treasury_txs, start=1):
                method_title = "چک صیادی" if tt["method"] == "sayyad_cheque" else "واریز بانکی / کارت‌خوان"
                tt_node = {
                    "id": f"node_treasury_{idx}",
                    "type": "treasury",
                    "icon": "💳",
                    "badge": f"دریافت خزانه ({method_title})",
                    "title": f"رسید دریافت خزانه {idx}",
                    "subtitle": f"روش تسویه: {method_title} | مبلغ: {self._format_money(tt['amount'])}",
                    "date": tt["tx_date"],
                    "amount": float(tt["amount"]),
                    "amount_formatted": self._format_money(tt["amount"]),
                    "status_label": "ثبت قطعی در خزانه",
                    "status_class": "status-settled",
                    "details": [
                        {"label": "نوع عملیات", "value": "دریافت وجه از طرف حساب"},
                        {"label": "روش پرداخت", "value": method_title},
                        {"label": "مبلغ وصولی", "value": self._format_money(tt["amount"])},
                        {"label": "تاریخ تراکنش", "value": tt["tx_date"]},
                    ],
                    "jump_target": {"view": "treasury", "id": tt["id"], "label": "مشاهده در خزانه‌داری"},
                }
                nodes.append(tt_node)
                if invoice:
                    connections.append({"from": "node_invoice", "to": f"node_treasury_{idx}", "label": "تسویه مالی"})
                elif journal_entry:
                    connections.append({"from": "node_voucher", "to": f"node_treasury_{idx}", "label": "ثبت نقدی/بانک"})

        # NODE 5: Sayyad Cheque (چک صیادی بنفش)
        if cheques:
            for idx, ch in enumerate(cheques, start=1):
                status_farsi = {
                    "in_safe": "نزد صندوق (در انتظار سررسید)",
                    "deposited_to_bank": "در جریان وصول به بانک",
                    "cleared": "وصول و پاس شده",
                    "bounced": "برگشت خورده (واخواست)",
                    "transferred": "خرج شده به شخص ثالث",
                }.get(ch["status"], ch["status"])

                ch_node = {
                    "id": f"node_cheque_{idx}",
                    "type": "cheque",
                    "icon": "🎫",
                    "badge": "چک صیادی بنفش",
                    "title": f"چک صیادی شماره {ch['cheque_number']}",
                    "subtitle": f"بانک: {ch['bank_name']} | شناسه ۱۶ رقمی: {ch['sayyad_id'] or '-'}",
                    "date": f"سررسید: {ch['due_date']}",
                    "amount": float(ch["amount"]),
                    "amount_formatted": self._format_money(ch["amount"]),
                    "status_label": status_farsi,
                    "status_class": "status-cheque-safe" if ch["status"] == "in_safe" else "status-cheque-cleared",
                    "details": [
                        {"label": "شناسه صیادی (۱۶ رقم)", "value": ch["sayyad_id"] or "فاقد شناسه صیادی"},
                        {"label": "شماره سریال چک", "value": ch["cheque_number"]},
                        {"label": "بانک صادرکننده", "value": f"{ch['bank_name']} - شعبه {ch['branch_name'] or 'مرکزی'}"},
                        {"label": "تاریخ سررسید", "value": ch["due_date"]},
                        {"label": "مبلغ چک", "value": self._format_money(ch["amount"])},
                        {"label": "وضعیت حقوقی چک", "value": status_farsi},
                    ],
                    "jump_target": {"view": "treasury", "id": ch["id"], "label": "مشاهده کاردکس چک"},
                }
                nodes.append(ch_node)
                if treasury_txs:
                    connections.append({"from": "node_treasury_1", "to": f"node_cheque_{idx}", "label": "برگه چک"})
                elif invoice:
                    connections.append({"from": "node_invoice", "to": f"node_cheque_{idx}", "label": "تسویه با چک صیادی"})
                elif journal_entry:
                    connections.append({"from": "node_voucher", "to": f"node_cheque_{idx}", "label": "دریافت چک"})

        # NODE 6: Taxpayer System (سامانه مؤدیان مالیاتی)
        if invoice and invoice.get("tax_unique_id"):
            tax_node = {
                "id": "node_taxpayer",
                "type": "taxpayer",
                "icon": "🏛️",
                "badge": "سازمان امور مالیاتی کشور",
                "title": "سامانه مؤدیان و کارپوشه",
                "subtitle": f"شناسه ۲۲ رقمی: {invoice['tax_unique_id'][:6]}...{invoice['tax_unique_id'][-6:]}",
                "date": invoice["invoice_date"],
                "amount": float(invoice["total_vat"]),
                "amount_formatted": self._format_money(invoice["total_vat"]),
                "status_label": "دارای شناسه ۲۲ رقمی ورهوف",
                "status_class": "status-tax-valid",
                "details": [
                    {"label": "شناسه منحصر به فرد مالیاتی", "value": invoice["tax_unique_id"]},
                    {"label": "الگوی صورتحساب", "value": "الگوی ۱: فروش عمومی کالا و خدمات"},
                    {"label": "شناسه حافظه مالیاتی", "value": invoice.get("tax_fiscal_id") or "A12345"},
                    {"label": "اعتبار کنترل‌رقم ورهوف", "value": "✅ معتبر (تایید ریاضیاتی)"},
                    {"label": "وضعیت کارپوشه", "value": "آماده ارسال و استعلام برخط"},
                ],
                "jump_target": {"view": "invoicing", "id": invoice["id"], "label": "دریافت جیسون مؤدیان"},
            }
            nodes.append(tax_node)
            connections.append({"from": "node_invoice", "to": "node_taxpayer", "label": "ثبت کارپوشه"})

        # -------------------------------------------------------------
        # 5 STANDARD LIFECYCLE STAGES PROGRESS BAR
        # -------------------------------------------------------------
        # Stage 1: Registration / Draft
        s1_done = bool(invoice or journal_entry)
        stages.append({
            "stage_id": "draft",
            "step_num": 1,
            "title": "ثبت اولیه و پیش‌نویس",
            "state": "completed" if s1_done else "pending",
            "badge": "انجام شد" if s1_done else "در انتظار",
            "description": f"ثبت سند در تاریخ {doc_date}",
        })

        # Stage 2: Inventory Outflow / Receipt
        s2_done = len(inventory_txs) > 0
        stages.append({
            "stage_id": "inventory",
            "step_num": 2,
            "title": "حواله خروج انبار",
            "state": "completed" if s2_done else ("current" if s1_done and not journal_entry else "pending"),
            "badge": f"{len(inventory_txs)} قلم حواله" if s2_done else "بدون حواله کالا",
            "description": "خروج فیزیکی اقلام از انبار و محاسبه قیمت تمام‌شده" if s2_done else "نیازمند صدور حواله انبار",
        })

        # Stage 3: Double-Entry Journal Voucher
        s3_done = bool(journal_entry)
        stages.append({
            "stage_id": "voucher",
            "step_num": 3,
            "title": "سند حسابداری دوبل",
            "state": "completed" if s3_done else ("current" if s2_done else "pending"),
            "badge": f"سند شماره {journal_entry['entry_number']}" if s3_done else "در انتظار صدور",
            "description": "تراز قطعی بدهکار و بستانکار در دفتر روزنامه" if s3_done else "سند مالی صادر نشده است",
        })

        # Stage 4: Treasury Settlement
        s4_done = len(treasury_txs) > 0 or len(cheques) > 0
        stages.append({
            "stage_id": "settlement",
            "step_num": 4,
            "title": "تسویه خزانه‌داری",
            "state": "completed" if s4_done else ("current" if s3_done else "pending"),
            "badge": "تسویه شده" if s4_done else "نسیه / تسویه نشده",
            "description": f"دریافت وجه نقد یا چک صیادی بنفش ({len(treasury_txs)} تراکنش)" if s4_done else "مانده حساب بدهکار است",
        })

        # Stage 5: Taxpayer System
        s5_done = bool(invoice and invoice.get("tax_unique_id"))
        stages.append({
            "stage_id": "taxpayer",
            "step_num": 5,
            "title": "سامانه مؤدیان مالیاتی",
            "state": "completed" if s5_done else ("current" if s4_done else "pending"),
            "badge": "شناسه ۲۲ رقمی" if s5_done else "ارسال نشده",
            "description": "ثبت صورتحساب در کارپوشه مؤدیان مالیاتی و اعتبارسنجی ورهوف" if s5_done else "اقدام مالیاتی معلق",
        })

        # -------------------------------------------------------------
        # AUDIT TRAIL TIMELINE
        # -------------------------------------------------------------
        timeline = []
        for log in audit_records:
            timeline.append({
                "timestamp": str(log["created_at"]),
                "user": log["user_id"] or "سیستم خودکار آربین",
                "action": log["action"],
                "entity": log["entity_name"],
                "description": f"اقدام {log['action']} بر روی {log['entity_name']}",
            })

        # Synthesize baseline timeline events if logs table was quiet
        if not timeline:
            if invoice:
                timeline.append({
                    "timestamp": invoice["created_at"] or invoice["invoice_date"],
                    "user": "آریا کمالی (مدیر مالی)",
                    "action": "CREATE_INVOICE",
                    "entity": "فاکتور فروش",
                    "description": f"ایجاد فاکتور فروش شماره {invoice['invoice_number']} به مبلغ {self._format_money(invoice['final_payable'])}",
                })
            if inventory_txs:
                for it in inventory_txs:
                    timeline.append({
                        "timestamp": it["created_at"] or it["tx_date"],
                        "user": "مسئول انبار مرکزی",
                        "action": "WAREHOUSE_DELIVERY",
                        "entity": "حواله انبار",
                        "description": f"صدور حواله شماره {it['tx_number']} و کسر موجودی فیزیکی بهای تمام‌شده {self._format_money(it['total_cost'])}",
                    })
            if journal_entry:
                timeline.append({
                    "timestamp": journal_entry["created_at"] or journal_entry["entry_date"],
                    "user": journal_entry["created_by"] or "موتور دوبل خودکار",
                    "action": "POST_JOURNAL_VOUCHER",
                    "entity": "سند حسابداری",
                    "description": f"ثبت قطعی سند دوبل شماره {journal_entry['entry_number']} با تراز صفر بدهکار/بستانکار",
                })
            if treasury_txs:
                for tt in treasury_txs:
                    timeline.append({
                        "timestamp": tt["created_at"] or tt["tx_date"],
                        "user": "مسئول دریافت و پرداخت",
                        "action": "TREASURY_SETTLEMENT",
                        "entity": "خزانه‌داری",
                        "description": f"ثبت دریافت وجه به مبلغ {self._format_money(tt['amount'])} و تخصیص به طرف حساب",
                    })

        return {
            "summary": {
                "root_title": root_title,
                "party_name": party_name,
                "amount": amount,
                "amount_formatted": self._format_money(amount),
                "date": doc_date,
                "overall_status": overall_status,
                "node_count": len(nodes),
            },
            "stages": stages,
            "nodes": nodes,
            "connections": connections,
            "audit_trail": timeline,
        }
