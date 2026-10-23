"""
Arbin Payroll & Statutory Labor Law Engine (سیستم حقوق و دستمزد و پرسنلی آربین)
Compliant with:
- Iranian Labor Law (قانون کار جمهوری اسلامی ایران)
- Social Security Organization (سازمان تأمین اجتماعی: ۷٪ سهم بیمه‌شده، ۲۳٪ سهم کارفرما)
- Direct Taxation Act (قانون مالیات‌های مستقیم ماده ۸۴ - محاسبه پلکانی مالیات حقوق)
- Automated Bank Payment Diskette Export (دیسکت پرداخت پایا و ساتنا)
- Automated Double-Entry Voucher Generation
"""

import json
import uuid
from typing import List, Dict, Any, Optional
from decimal import Decimal, ROUND_HALF_UP

class PayrollError(Exception):
    pass


# ---------------------------------------------------------------------------
# ماده ۸۴ قانون مالیات‌های مستقیم - نرخ‌های پلکانی ماهانه (تومان)
# ---------------------------------------------------------------------------
ARTICLE84_BRACKETS = (
    (Decimal("10000000"), Decimal("0.10")),   # تا ۱۰ میلیون          ۱۰٪
    (Decimal("15000000"), Decimal("0.15")),   # تا ۱۵ میلیون          ۱۵٪
    (Decimal("25000000"), Decimal("0.20")),   # تا ۲۵ میلیون          ۲۰٪
    (Decimal("35000000"), Decimal("0.25")),   # تا ۳۵ میلیون          ۲۵٪
    (Decimal("45000000"), Decimal("0.30")),   # تا ۴۵ میلیون          ۳۰٪
    (Decimal("60000000"), Decimal("0.35")),   # تا ۶۰ میلیون          ۳۵٪
    (None, Decimal("0.40")),                  # بیش از ۶۰ میلیون      ۴۰٪
)
# سقف معافیت ماهانه مالیات حقوق (ماده ۸۴) - قابل پیکربندی برای هر سال مالی
TAX_EXEMPTION_CEILING = Decimal("105000000")   # ۱۰۵,۰۰۰,۰۰۰ تومان در ماه

class ArbinPayroll:
    def __init__(self, ledger):
        self.ledger = ledger

    def register_employee(
        self,
        tenant_id: str,
        national_id: str,
        full_name: str,
        insurance_number: Optional[str] = None,
        job_title: str = "کارشناس",
        base_monthly_salary: float = 120_000_000,
        housing_allowance: float = 9_000_000,    # حق مسکن
        grocery_allowance: float = 14_000_000,   # بن خواربار
        child_count: int = 0,
        phone: Optional[str] = None,
        bank_shaba: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Register a new employee and create their floating detail account in Chart of Accounts.
        """
        with self.ledger.get_connection() as conn:
            dup = conn.execute(
                "SELECT id FROM employees WHERE tenant_id = ? AND national_id = ?",
                (tenant_id, national_id),
            ).fetchone()
            if dup:
                raise PayrollError(
                    f"پرسنلی با کد ملی {national_id} قبلاً در این شرکت ثبت شده است."
                )

        emp_id = str(uuid.uuid4())
        
        # Create Detail Account under personnel type
        det_code = f"9{national_id[-4:]}"
        det_id = self.ledger.create_detail_account(
            tenant_id=tenant_id,
            code=det_code,
            title=f"{full_name} ({job_title})",
            detail_type="personnel",
            phone=phone
        )

        with self.ledger.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO employees (
                    id, tenant_id, sub_ledger_id, national_id, insurance_number, full_name,
                    job_title, base_monthly_salary, housing_allowance, grocery_allowance,
                    child_count, bank_shaba, phone
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    emp_id, tenant_id, det_id, national_id, insurance_number, full_name,
                    job_title, base_monthly_salary, housing_allowance, grocery_allowance,
                    child_count, bank_shaba, phone
                )
            )

        return {
            "employee_id": emp_id,
            "detail_id": det_id,
            "detail_code": det_code,
            "sub_ledger_id": det_id,
            "sub_ledger_code": det_code,
            "full_name": full_name
        }

    @staticmethod
    def calculate_progressive_tax(taxable_income: Decimal) -> Decimal:
        """
        محاسبه پلکانی مالیات حقوق بر اساس ماده ۸۴ قانون مالیات‌های مستقیم
        (نرخ‌های ماهانه: ۱۰٪، ۱۵٪، ۲۰٪، ۲۵٪، ۳۰٪، ۳۵٪، ۴۰٪)
        """
        tax = Decimal("0.0")
        previous = Decimal("0.0")
        remaining = max(Decimal("0.0"), Decimal(str(taxable_income)))
        for cap, rate in ARTICLE84_BRACKETS:
            if remaining <= previous:
                break
            upper = remaining if cap is None else min(remaining, cap)
            if upper > previous:
                tax += (upper - previous) * rate
            previous = cap if cap is not None else remaining
        return tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def calculate_employee_slip(
        base_salary: Decimal,
        housing: Decimal,
        grocery: Decimal,
        child_allowance: Decimal,
        worked_days: int = 30,
        overtime_hours: float = 0.0,
        tax_exemption_ceiling: Optional[Decimal] = None,
    ) -> Dict[str, Any]:
        """
        Pure mathematical salary slip calculation according to Iranian statutory labor formulas:
        1. Daily Wage = Base / 30
        2. Hourly Wage = Daily Wage / 7.33 (approx 220 monthly hours)
        3. Overtime Rate = Hourly Wage * 1.4
        4. Gross Salary = Worked Base + Housing + Grocery + Children + Overtime
        5. Social Security = 7% Employee, 23% Employer (20% main + 3% unemployment)
        6. Income Tax = Article 84 progressive brackets applied to taxable income
           (gross - employee insurance - monthly exemption ceiling)
        """
        ceiling = (
            TAX_EXEMPTION_CEILING if tax_exemption_ceiling is None
            else Decimal(str(tax_exemption_ceiling))
        )
        daily_wage = base_salary / Decimal("30")
        actual_base = (daily_wage * Decimal(str(worked_days))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        hourly_wage = daily_wage / Decimal("7.333")
        overtime_pay = (Decimal(str(overtime_hours)) * hourly_wage * Decimal("1.4")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        gross_salary = actual_base + housing + grocery + child_allowance + overtime_pay

        # Insurance calculation (capped subject items: Base + Grocery + Overtime)
        insurable_earnings = actual_base + grocery + overtime_pay
        employee_insurance = (insurable_earnings * Decimal("0.07")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        employer_insurance = (insurable_earnings * Decimal("0.23")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Income Tax (Article 84 marginal brackets)
        taxable_income = max(Decimal("0.0"), gross_salary - employee_insurance - ceiling)
        income_tax = ArbinPayroll.calculate_progressive_tax(taxable_income)

        net_payable = gross_salary - employee_insurance - income_tax

        return {
            "actual_base": float(actual_base),
            "overtime_pay": float(overtime_pay),
            "housing_allowance": float(housing),
            "grocery_allowance": float(grocery),
            "child_allowance": float(child_allowance),
            "gross_salary": float(gross_salary),
            "employee_insurance_7pct": float(employee_insurance),
            "employer_insurance_23pct": float(employer_insurance),
            "taxable_income": float(taxable_income),
            "tax_exemption_ceiling": float(ceiling),
            "income_tax": float(income_tax),
            "net_payable": float(net_payable)
        }

    def process_monthly_payroll(
        self,
        tenant_id: str,
        fiscal_year_id: str,
        month_label: str,          # e.g. "فروردین ۱۴۰۵"
        run_date: str,             # YYYY-MM-DD
        records: List[Dict[str, Any]], # [{"employee_id": ..., "worked_days": 30, "overtime_hours": 15}]
        user_id: str = "system"
    ) -> Dict[str, Any]:
        """
        Process company-wide monthly payroll run:
        1. Computes all individual pay slips.
        2. Aggregates totals (Gross, Employee/Employer Insurance, Income Tax, Net Pay).
        3. Automatically posts double-entry journal voucher to the ledger:
           - Debit: 7110 (حقوق پایه و دستمزد پرسنل)
           - Debit: 7120 (بیمه سهم کارفرما ۲۳٪)
           - Debit: 7130 (پاداش و مزایای رفاهی / مسکن و بن)
           - Credit: 4040 (حقوق و دستمزد پرداختنی به پرسنل)
           - Credit: 4050 (بیمه پرداختنی به تأمین اجتماعی ۳۰٪)
           - Credit: 4060 (مالیات حقوق پرداختنی به دارایی)
        """
        if not records:
            raise PayrollError("لیست پرسنل برای محاسبه حقوق خالی است.")

        run_id = str(uuid.uuid4())
        tot_gross = Decimal("0.0")
        tot_base = Decimal("0.0")
        tot_benefits = Decimal("0.0")
        tot_emp_ins = Decimal("0.0")
        tot_empr_ins = Decimal("0.0")
        tot_tax = Decimal("0.0")
        tot_net = Decimal("0.0")

        slips_to_insert = []

        with self.ledger.get_connection() as conn:
            for rec in records:
                emp = conn.execute("SELECT * FROM employees WHERE id = ?", (rec["employee_id"],)).fetchone()
                if not emp:
                    continue

                b_sal = Decimal(str(emp["base_monthly_salary"]))
                h_alw = Decimal(str(emp["housing_allowance"]))
                g_alw = Decimal(str(emp["grocery_allowance"]))
                per_child = Decimal(str(emp["family_allowance"] or 0)) or Decimal("5000000")
                c_alw = Decimal(str(emp["child_count"])) * per_child
                w_days = int(rec.get("worked_days", 30))
                ot_hrs = float(rec.get("overtime_hours", 0.0))

                calc = self.calculate_employee_slip(b_sal, h_alw, g_alw, c_alw, w_days, ot_hrs)

                tot_base += Decimal(str(calc["actual_base"] + calc["overtime_pay"]))
                tot_benefits += Decimal(str(calc["housing_allowance"] + calc["grocery_allowance"] + calc["child_allowance"]))
                tot_gross += Decimal(str(calc["gross_salary"]))
                tot_emp_ins += Decimal(str(calc["employee_insurance_7pct"]))
                tot_empr_ins += Decimal(str(calc["employer_insurance_23pct"]))
                tot_tax += Decimal(str(calc["income_tax"]))
                tot_net += Decimal(str(calc["net_payable"]))

                slips_to_insert.append({
                    "id": str(uuid.uuid4()),
                    "employee_id": emp["id"],
                    "calc": calc
                })

            # Insert Payroll Run Header
            conn.execute(
                """
                INSERT INTO payroll_runs (
                    id, tenant_id, fiscal_year_id, month_label, run_date, total_gross,
                    total_employee_insurance, total_employer_insurance, total_tax, total_net_payable
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, tenant_id, fiscal_year_id, month_label, run_date,
                    float(tot_gross), float(tot_emp_ins), float(tot_empr_ins), float(tot_tax), float(tot_net)
                )
            )

            # Insert Individual Pay Slips
            for s in slips_to_insert:
                c = s["calc"]
                conn.execute(
                    """
                    INSERT INTO payroll_slips (
                        id, payroll_run_id, employee_id, gross_salary, employee_insurance,
                        employer_insurance, income_tax, net_payable, breakdown
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (s["id"], run_id, s["employee_id"], c["gross_salary"], c["employee_insurance_7pct"],
                     c["employer_insurance_23pct"], c["income_tax"], c["net_payable"],
                     json.dumps(c, ensure_ascii=False))
                )

        # Generate Automated Double-Entry Voucher
        total_30pct_insurance = float(tot_emp_ins + tot_empr_ins)
        desc = f"ثبت سند حقوق و دستمزد ماهانه پرسنل - {month_label}"

        voucher_items = [
            # Debits (هزینه‌ها)
            {
                "account_code": "7110",
                "detail_code": None,
                "description": f"هزینه حقوق پایه و اضافه کاری پرسنل ({month_label})",
                "debit": float(tot_base),
                "credit": 0
            },
            {
                "account_code": "7120",
                "detail_code": None,
                "description": f"هزینه حق بیمه سهم کارفرما ۲۳٪ ({month_label})",
                "debit": float(tot_empr_ins),
                "credit": 0
            },
            {
                "account_code": "7130",
                "detail_code": None,
                "description": f"هزینه بن، مسکن و مزایای پرسنل ({month_label})",
                "debit": float(tot_benefits),
                "credit": 0
            },
            # Credits (بدهی‌ها و تعهدات پرداختنی)
            {
                "account_code": "4040",
                "detail_code": None,
                "description": f"خالص حقوق پرداختنی به پرسنل ({month_label})",
                "debit": 0,
                "credit": float(tot_net)
            },
            {
                "account_code": "4050",
                "detail_code": None,
                "description": f"کل بیمه پرداختنی به تأمین اجتماعی ۳۰٪ ({month_label})",
                "debit": 0,
                "credit": total_30pct_insurance
            }
        ]

        if float(tot_tax) > 0:
            voucher_items.append({
                "account_code": "4060",
                "detail_code": None,
                "description": f"مالیات حقوق تکلیفی پرداختنی به دارایی ({month_label})",
                "debit": 0,
                "credit": float(tot_tax)
            })

        entry_id = self.ledger.record_journal_entry(
            tenant_id=tenant_id,
            fiscal_year_id=fiscal_year_id,
            entry_date=run_date,
            description=desc,
            items=voucher_items,
            source_module="payroll",
            user_id=user_id
        )

        with self.ledger.get_connection() as conn:
            conn.execute("UPDATE payroll_runs SET journal_entry_id = ? WHERE id = ?", (entry_id, run_id))

        return {
            "payroll_run_id": run_id,
            "month_label": month_label,
            "total_gross": float(tot_gross),
            "total_net_payable": float(tot_net),
            "total_insurance_30pct": total_30pct_insurance,
            "total_tax": float(tot_tax),
            "journal_entry_id": entry_id,
            "employees_count": len(slips_to_insert)
        }

    def export_bank_payment_paya(self, payroll_run_id: str) -> List[Dict[str, Any]]:
        """
        Export bulk payment file for Paya/Satna bank transfer (دیسکت پرداخت گروهی بانک)
        """
        with self.ledger.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT ps.net_payable, e.full_name, e.national_id, e.bank_shaba
                FROM payroll_slips ps
                JOIN employees e ON ps.employee_id = e.id
                WHERE ps.payroll_run_id = ?
                """,
                (payroll_run_id,)
            ).fetchall()

            return [
                {
                    "name": r["full_name"],
                    "national_id": r["national_id"],
                    "shaba": r["bank_shaba"] or "IR000000000000000000000000",
                    "amount": r["net_payable"],
                    "description": "واریز حقوق ماهانه"
                }
                for r in rows
            ]

    # ------------------------------------------------------------------
    # Query helpers (لیست پرسنل، اجراها و فیش‌های حقوقی)
    # ------------------------------------------------------------------
    def list_employees(self, tenant_id: str, include_inactive: bool = False) -> List[Dict[str, Any]]:
        sql = [
            """
            SELECT e.*, s.code AS sub_ledger_code, s.title AS sub_ledger_title
            FROM employees e
            LEFT JOIN sub_ledgers s ON e.sub_ledger_id = s.id
            WHERE e.tenant_id = ?
            """
        ]
        params: List[Any] = [tenant_id]
        if not include_inactive:
            sql.append("AND e.is_active = 1")
        sql.append("ORDER BY e.full_name")
        with self.ledger.get_connection() as conn:
            rows = conn.execute(" ".join(sql), params).fetchall()
        return [dict(r) for r in rows]

    def get_employee(self, employee_id: str) -> Dict[str, Any]:
        with self.ledger.get_connection() as conn:
            row = conn.execute(
                """
                SELECT e.*, s.code AS sub_ledger_code, s.title AS sub_ledger_title
                FROM employees e
                LEFT JOIN sub_ledgers s ON e.sub_ledger_id = s.id
                WHERE e.id = ?
                """,
                (employee_id,),
            ).fetchone()
        if not row:
            raise PayrollError("پرسنل مورد نظر یافت نشد.")
        return dict(row)

    def list_payroll_runs(self, tenant_id: str) -> List[Dict[str, Any]]:
        with self.ledger.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM payroll_runs WHERE tenant_id = ?
                ORDER BY run_date DESC
                """,
                (tenant_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_payslips(self, payroll_run_id: str) -> List[Dict[str, Any]]:
        """فیش‌های حقوقی یک اجرا به هراه محاسبات تفصیلی (breakdown)"""
        with self.ledger.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT ps.*, e.full_name, e.job_title, e.national_id, e.bank_shaba
                FROM payroll_slips ps
                JOIN employees e ON ps.employee_id = e.id
                WHERE ps.payroll_run_id = ?
                ORDER BY e.full_name
                """,
                (payroll_run_id,),
            ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            try:
                item["breakdown"] = json.loads(item["breakdown"]) if item.get("breakdown") else None
            except (TypeError, ValueError):
                item["breakdown"] = None
            out.append(item)
        return out

    @staticmethod
    def tax_brackets() -> List[Dict[str, Any]]:
        """جدول نرخ‌های پلکانی ماده ۸۴ برای نمایش در فیش حقوقی"""
        brackets = []
        previous = Decimal("0.0")
        for cap, rate in ARTICLE84_BRACKETS:
            brackets.append(
                {
                    "from": float(previous),
                    "to": float(cap) if cap is not None else None,
                    "rate": float(rate),
                }
            )
            if cap is None:
                break
            previous = cap
        return brackets
