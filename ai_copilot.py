"""
Arbin AI Financial Copilot (دستیار هوشمند مالی و فاکتورخوان آربین)
Next-generation capabilities differentiating Arbin from traditional ERPs:
1. Intelligent Receipt & Invoice Parser (استخراج ساختاریافته اقلام از متن فاکتورهای کاغذی و پیامک‌های بانکی)
2. Predictive Cash-Flow Anomaly & Risk Detector (پیش‌بینی هوشمند کسری نقدینگی و سررسید چک‌ها)
3. Automated Natural-Language Journal Voucher Builder (تبدیل دستور محاوره‌ای به سند دوبل حسابداری)
"""

import re
from datetime import datetime, timedelta, date
from typing import Dict, Any

class AICopilotError(Exception):
    pass

class ArbinAICopilot:
    def __init__(self, ledger):
        self.ledger = ledger

    def parse_unstructured_invoice(self, raw_text: str) -> Dict[str, Any]:
        """
        Parses informal/OCR text from scanned paper invoices or merchant receipts into
        standard Arbin Invoice creation payload.
        """
        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
        
        # 1. Detect Invoice Date (YYYY-MM-DD or YYYY/MM/DD)
        date_match = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", raw_text)
        if date_match:
            inv_date = f"{date_match.group(1)}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
        else:
            inv_date = datetime.now().strftime("%Y-%m-%d")

        # 2. Extract Line Items (e.g. "لپ تاپ ایسوس ۲ عدد هر کدام ۵۰،۰۰۰،۰۰۰")
        extracted_items = []
        ignored_keywords = ["تاریخ", "مجموع", "جمع", "فاکتور", "شماره", "صورتحساب", "تلفن", "آدرس"]

        for line in lines:
            if any(line.startswith(kw) or f"{kw}:" in line for kw in ignored_keywords):
                continue

            # Pattern: Title + Quantity + Unit (عدد/دستگاه/...) + Unit Price
            m = re.search(r"(.+?)\s+(\d+(?:\.\d+)?)\s*(?:عدد|دستگاه|بسته|متر|سرویس|کیلو|تن)\s*(?:فی|نرخ|قیمت|هر کدام)?\s*[:=]?\s*([\d,]+)", line)
            if not m:
                # Secondary pattern: Title + Quantity + Price without explicit unit
                m = re.search(r"(.+?)\s+(\d+(?:\.\d+)?)\s+(?:فی|نرخ|قیمت|هر کدام)\s*[:=]?\s*([\d,]+)", line)

            if m:
                title = m.group(1).strip()
                if any(kw in title for kw in ignored_keywords):
                    continue
                qty = float(m.group(2))
                price_str = m.group(3).replace(",", "").replace("،", "")
                try:
                    unit_price = float(price_str)
                    if unit_price >= 1000: # Realistic commercial price
                        extracted_items.append({
                            "item_code": "2720000" + str(abs(hash(title)) % 1000000).zfill(6),
                            "item_title": title,
                            "unit": "عدد",
                            "quantity": qty,
                            "unit_price": unit_price,
                            "discount": 0.0,
                            "vat_rate": 0.10
                        })
                except ValueError:
                    pass

        # Fallback if specific line regex didn't catch complex table:
        if not extracted_items:
            # Look for total amount in text
            tot_match = re.search(r"(?:جمع کل|مبلغ کل|قابل پرداخت|مجموع)\s*[:=]?\s*([\d,]+)", raw_text)
            if tot_match:
                tot_amount = float(tot_match.group(1).replace(",", "").replace("،", ""))
                extracted_items.append({
                    "item_code": "2720000000000",
                    "item_title": "خرید اقلام متفرقه طبق فاکتور ضمیمه",
                    "unit": "سرویس",
                    "quantity": 1.0,
                    "unit_price": tot_amount,
                    "discount": 0.0,
                    "vat_rate": 0.10
                })

        return {
            "parsed_date": inv_date,
            "detected_items_count": len(extracted_items),
            "items": extracted_items,
            "confidence_score": 0.95 if extracted_items else 0.40,
            "suggested_pattern": "pattern1"
        }

    def predict_cashflow_risks(self, tenant_id: str, days_ahead: int = 30) -> Dict[str, Any]:
        """
        AI Predictive Cash-Flow Risk Assessment:
        Compares currently available liquid cash (accounts starting with '10')
        against upcoming cheque maturities (due within `days_ahead`).
        Detects impending liquidity deficits before they happen.
        """
        today = date.today()
        target_date = today + timedelta(days=days_ahead)
        today_str = today.strftime("%Y-%m-%d")
        target_str = target_date.strftime("%Y-%m-%d")

        with self.ledger.get_connection() as conn:
            # 1. Calculate current liquid cash (Bank + Cash Box: 1010, 1020)
            cash_row = conn.execute("""
                SELECT COALESCE(SUM(ji.debit - ji.credit), 0.0)
                FROM journal_items ji
                JOIN accounts a ON ji.account_id = a.id
                JOIN journal_entries je ON ji.entry_id = je.id
                WHERE a.tenant_id = ? AND a.code IN ('1010', '1020') AND je.status != 'draft'
            """, (tenant_id,)).fetchone()
            current_liquid_cash = float(cash_row[0])

            # 2. Upcoming Cheques due within the window
            cheques = conn.execute("""
                SELECT c.*, d.title as party_name
                FROM cheques c
                JOIN sub_ledgers d ON c.party_detail_id = d.id
                WHERE c.tenant_id = ? AND c.due_date BETWEEN ? AND ? AND c.status NOT IN ('cleared', 'cancelled')
                ORDER BY c.due_date ASC
            """, (tenant_id, today_str, target_str)).fetchall()

            total_incoming = 0.0 # received cheques to collect
            total_outgoing = 0.0 # paid cheques issued to suppliers

            timeline = []
            running_projected_cash = current_liquid_cash

            for chk in cheques:
                amt = float(chk["amount"])
                is_incoming = (chk["cheque_type"] == "received")
                if is_incoming:
                    total_incoming += amt
                    running_projected_cash += amt
                else:
                    total_outgoing += amt
                    running_projected_cash -= amt

                timeline.append({
                    "cheque_number": chk["cheque_number"],
                    "party_name": chk["party_name"],
                    "due_date": chk["due_date"],
                    "type": "دریافتی (وصول)" if is_incoming else "پرداختی (پاس شدن)",
                    "amount": amt,
                    "projected_cash_after": running_projected_cash
                })

            net_projected_liquidity = current_liquid_cash + total_incoming - total_outgoing
            is_deficit = net_projected_liquidity < 0

            risk_level = "CRITICAL_DEFICIT" if is_deficit else ("MODERATE_TIGHT" if net_projected_liquidity < (total_outgoing * 0.2) else "HEALTHY")

            advice = []
            if is_deficit:
                advice.append(f"هشدار کسر نقدینگی! در ۳۰ روز آینده مبلغ {abs(net_projected_liquidity):,.0f} تومان کسری صندوق پیش‌بینی می‌شود.")
                advice.append("پیشنهاد هوش مصنوعی: تسریع در وصول مطالبات مشتریان یا استقراض کوتاه‌مدت بانکی جهت جلوگیری از برگشت چک‌ها.")
            else:
                advice.append(f"وضعیت نقدینگی پایدار است. مازاد نقدی پیش‌بینی‌شده: {net_projected_liquidity:,.0f} تومان.")

            return {
                "current_liquid_cash": current_liquid_cash,
                "total_incoming_cheques": total_incoming,
                "total_outgoing_cheques": total_outgoing,
                "net_projected_liquidity": net_projected_liquidity,
                "risk_level": risk_level,
                "cheques_in_window_count": len(cheques),
                "timeline": timeline,
                "ai_financial_advice": advice
            }

    def natural_language_to_voucher(self, instruction: str) -> Dict[str, Any]:
        """
        Interprets natural Persian spoken accounting instructions into strict double-entry vouchers:
        e.g.: "ثبت کن ۵۰ میلیون تومان واریز به حساب بانک ملت بابت فروش لایسنس به شرکت آریا"
        """
        # Deterministic semantic parsing
        # 1. Extract amount
        amt_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:میلیون|هزار|میلیارد)?\s*(?:تومان|ریال)?", instruction)
        multiplier = 1
        if "میلیارد" in instruction:
            multiplier = 1_000_000_000
        elif "میلیون" in instruction:
            multiplier = 1_000_000
        elif "هزار" in instruction:
            multiplier = 1_000

        amount = 0.0
        if amt_match:
            base_num = float(amt_match.group(1).replace(",", ""))
            amount = base_num * multiplier

        # 2. Detect accounts based on intent
        debit_code = "1010" # بانک پیش‌فرض
        credit_code = "6010" # فروش پیش‌فرض

        if "اجاره" in instruction:
            debit_code = "7210" # هزینه اجاره
            credit_code = "1010" # پرداخت از بانک
        elif "حقوق" in instruction:
            debit_code = "7110"
            credit_code = "1010"
        elif "وصول" in instruction or "دریافت از مشتری" in instruction:
            debit_code = "1010" # واریز به بانک
            credit_code = "1210" # کاهش حساب دریافتنی
        elif "خرید" in instruction:
            debit_code = "1110" # موجودی کالا
            credit_code = "1010"

        return {
            "understood_intent": "automated_voucher",
            "amount": amount,
            "suggested_items": [
                {"account_code": debit_code, "debit": amount, "credit": 0.0, "description": instruction},
                {"account_code": credit_code, "debit": 0.0, "credit": amount, "description": instruction}
            ],
            "confidence": 0.96
        }
