"""
Arbin Financial Reporting Engine (موتور گزارش‌گیری مالی آربین)
Generates:
- 4-Column & 2-Column Trial Balance (تراز آزمایشی ۴ ستونی)
- General & Subsidiary Ledgers / Account Statement (دفتر کل، دفتر معین، صورت حساب)
- Income Statement (صورت سود و زیان)
- Balance Sheet (ترازنامه)

Canonical chart groups:
  1 دارایی جاری، 2 دارایی غیرجاری، 4 بدهی‌ها، 5 حقوق صاحبان سهام،
  6 درآمدها، 7 بهای تمام شده و هزینه‌ها (زیرمجموعه 70 = بهای تمام شده)
"""

from typing import Any, Dict, List, Optional


class ArbinReports:
    def __init__(self, ledger):
        self.ledger = ledger

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _fy_clause(fiscal_year_id: Optional[str], alias: str = "je") -> tuple:
        if fiscal_year_id:
            return f"AND {alias}.fiscal_year_id = ?", [fiscal_year_id]
        return "", []

    def _sum_where(
        self,
        tenant_id: str,
        code_prefix: str,
        direction: str,          # 'debit_net' or 'credit_net'
        fiscal_year_id: Optional[str] = None,
        level: Optional[str] = None,
        exclude_prefix: Optional[str] = None,
    ) -> float:
        """Net balance of accounts matching a code prefix (draft entries excluded)."""
        expr = (
            "SUM(ji.debit - ji.credit)" if direction == "debit_net"
            else "SUM(ji.credit - ji.debit)"
        )
        sql = [
            f"SELECT COALESCE({expr}, 0.0) FROM journal_items ji",
            "JOIN accounts a ON ji.account_id = a.id",
            "JOIN journal_entries je ON ji.entry_id = je.id",
            "WHERE a.tenant_id = ? AND je.tenant_id = ? AND je.status != 'draft'",
            "AND a.code LIKE ?",
        ]
        params: List[Any] = [tenant_id, tenant_id, f"{code_prefix}%"]
        if exclude_prefix:
            sql.append("AND a.code NOT LIKE ?")
            params.append(f"{exclude_prefix}%")
        if level:
            sql.append("AND a.level = ?")
            params.append(level)
        fy_sql, fy_params = self._fy_clause(fiscal_year_id)
        if fy_sql:
            sql.append(fy_sql)
            params.extend(fy_params)
        with self.ledger.get_connection() as conn:
            row = conn.execute(" ".join(sql), params).fetchone()
        return float(row[0] or 0.0)

    # ------------------------------------------------------------------
    # Trial Balance (تراز آزمایشی)
    # ------------------------------------------------------------------
    def get_trial_balance(
        self,
        tenant_id: str,
        level: str = "subsidiary",
        fiscal_year_id: Optional[str] = None,
        include_drafts: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        4-Column Trial Balance (تراز آزمایشی ۴ ستونی)
        Columns: Code, Title, Turnover Debit, Turnover Credit, Balance Debit, Balance Credit
        Aggregates hierarchical balances for group & general levels.
        """
        if level == "subsidiary":
            sql = [
                """
                SELECT a.code, a.title, a.level, a.nature,
                       COALESCE(s.total_debit, 0.0) AS total_debit,
                       COALESCE(s.total_credit, 0.0) AS total_credit
                FROM accounts a
                LEFT JOIN (
                    SELECT ji.account_id,
                           SUM(ji.debit) AS total_debit,
                           SUM(ji.credit) AS total_credit
                    FROM journal_items ji
                    JOIN journal_entries je ON ji.entry_id = je.id
                    WHERE ji.tenant_id = ? AND je.tenant_id = ?
                """
            ]
            params: List[Any] = [tenant_id, tenant_id]
            if not include_drafts:
                sql.append("AND je.status != 'draft'")
            if fiscal_year_id:
                sql.append("AND je.fiscal_year_id = ?")
                params.append(fiscal_year_id)
            sql.append("GROUP BY ji.account_id")
            sql.append(") s ON s.account_id = a.id")
            sql.append("WHERE a.tenant_id = ? AND a.level = ?")
            params.extend([tenant_id, level])
            sql.append("ORDER BY a.code ASC")
        else:
            sql = [
                """
                SELECT a.code, a.title, a.level, a.nature,
                       COALESCE(SUM(ji.debit), 0.0) AS total_debit,
                       COALESCE(SUM(ji.credit), 0.0) AS total_credit
                FROM accounts a
                LEFT JOIN accounts child ON child.tenant_id = a.tenant_id AND child.code LIKE (a.code || '%')
                LEFT JOIN journal_items ji ON ji.account_id = child.id AND ji.tenant_id = a.tenant_id
                LEFT JOIN journal_entries je ON ji.entry_id = je.id AND je.tenant_id = a.tenant_id
                """
            ]
            params = []
            extra_je = []
            if not include_drafts:
                extra_je.append("AND je.status != 'draft'")
            if fiscal_year_id:
                extra_je.append("AND je.fiscal_year_id = ?")
                params.append(fiscal_year_id)
            sql.extend(extra_je)
            sql.append("WHERE a.tenant_id = ? AND a.level = ?")
            params.extend([tenant_id, level])
            sql.append("GROUP BY a.id, a.code, a.title, a.level, a.nature")
            sql.append("ORDER BY a.code ASC")

        with self.ledger.get_connection() as conn:
            rows = conn.execute(" ".join(sql), params).fetchall()

        report = []
        for r in rows:
            t_debit = float(r["total_debit"])
            t_credit = float(r["total_credit"])
            net = t_debit - t_credit
            report.append(
                {
                    "code": r["code"],
                    "title": r["title"],
                    "level": r["level"],
                    "nature": r["nature"],
                    "total_debit": t_debit,
                    "total_credit": t_credit,
                    "balance_debit": net if net > 0 else 0.0,
                    "balance_credit": -net if net < 0 else 0.0,
                }
            )
        return report

    # ------------------------------------------------------------------
    # Income Statement (صورت سود و زیان)
    # ------------------------------------------------------------------
    def get_income_statement(
        self, tenant_id: str, fiscal_year_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Income Statement (صورت سود و زیان استاندارد)
        Revenue (6) - COGS (70) = Gross Profit
        Gross Profit - Operating Expenses (71..79) = Net Profit
        """
        total_revenue = self._sum_where(tenant_id, "6", "credit_net", fiscal_year_id)
        total_cogs = self._sum_where(
            tenant_id, "70", "debit_net", fiscal_year_id, level="subsidiary"
        )
        gross_profit = total_revenue - total_cogs

        with self.ledger.get_connection() as conn:
            sql = [
                """
                SELECT a.code, a.title, COALESCE(SUM(ji.debit - ji.credit), 0.0) AS amount
                FROM journal_items ji
                JOIN accounts a ON ji.account_id = a.id
                JOIN journal_entries je ON ji.entry_id = je.id
                WHERE a.tenant_id = ? AND je.tenant_id = ? AND je.status != 'draft'
                  AND a.code LIKE '7%' AND a.code NOT LIKE '70%'
                  AND a.level = 'subsidiary'
                GROUP BY a.id, a.code, a.title
                HAVING ABS(amount) > 0.005
                """
            ]
            params: List[Any] = [tenant_id, tenant_id]
            if fiscal_year_id:
                sql.append("AND je.fiscal_year_id = ?")
                params.append(fiscal_year_id)
            sql.append("ORDER BY a.code")
            exp_rows = conn.execute(" ".join(sql), params).fetchall()

        expenses_breakdown = [
            {"code": r["code"], "title": r["title"], "amount": float(r["amount"])}
            for r in exp_rows
        ]
        total_expenses = sum(item["amount"] for item in expenses_breakdown)
        net_profit = gross_profit - total_expenses

        return {
            "total_revenue": total_revenue,
            "total_cogs": total_cogs,
            "gross_profit": gross_profit,
            "operating_expenses": expenses_breakdown,
            "total_expenses": total_expenses,
            "net_profit": net_profit,
        }

    # ------------------------------------------------------------------
    # Balance Sheet (ترازنامه)
    # ------------------------------------------------------------------
    def get_balance_sheet(
        self, tenant_id: str, fiscal_year_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Balance Sheet (ترازنامه - وضعیت مالی)
        Assets (1 + 2) == Liabilities (4) + Equity (5) + Current Year Net Profit
        """
        current_assets = self._sum_where(tenant_id, "1", "debit_net", fiscal_year_id)
        fixed_assets = self._sum_where(tenant_id, "2", "debit_net", fiscal_year_id)
        total_assets = current_assets + fixed_assets

        total_liabilities = self._sum_where(tenant_id, "4", "credit_net", fiscal_year_id)
        # گروه ۵ بدون 5120 (سود/زیان جاری - از صورت سود و زیان اضافه می‌شود)
        # و بدون 5210 (خلاصه سود و زیان - حساب میانی اختتامیه)
        base_equity = self._sum_where(
            tenant_id, "5", "credit_net", fiscal_year_id, exclude_prefix="5120"
        )
        base_equity -= self._sum_where(
            tenant_id, "5210", "credit_net", fiscal_year_id
        )

        inc = self.get_income_statement(tenant_id, fiscal_year_id)
        current_profit = inc["net_profit"]
        total_equity = base_equity + current_profit
        total_liab_equity = total_liabilities + total_equity

        return {
            "current_assets": current_assets,
            "fixed_assets": fixed_assets,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "base_equity": base_equity,
            "current_year_profit": current_profit,
            "total_equity_and_liabilities": total_liab_equity,
            "is_balanced": abs(total_assets - total_liab_equity) < 0.01,
        }

    # ------------------------------------------------------------------
    # Account statement (صورت حساب / دفتر معین)
    # ------------------------------------------------------------------
    def get_account_statement(
        self,
        tenant_id: str,
        account_code: str,
        fiscal_year_id: Optional[str] = None,
        opening_balance: float = 0.0,
    ) -> Dict[str, Any]:
        """Chronological account movement with a running balance (صورت حساب معین)."""
        sql = [
            """
            SELECT je.id AS entry_id, je.entry_number, je.entry_date, je.entry_date_jalali, je.description,
                   je.status, ji.row_number, ji.debit, ji.credit,
                   s.code AS sub_ledger_code, s.title AS sub_ledger_title
            FROM journal_items ji
            JOIN journal_entries je ON ji.entry_id = je.id
            JOIN accounts a ON ji.account_id = a.id
            LEFT JOIN sub_ledgers s ON ji.sub_ledger_id = s.id
            WHERE a.tenant_id = ? AND je.tenant_id = ? AND a.code = ?
              AND je.status != 'draft'
            """
        ]
        params: List[Any] = [tenant_id, tenant_id, account_code]
        if fiscal_year_id:
            sql.append("AND je.fiscal_year_id = ?")
            params.append(fiscal_year_id)
        sql.append("ORDER BY je.entry_date, je.entry_number, ji.row_number")

        with self.ledger.get_connection() as conn:
            meta = conn.execute(
                "SELECT code, title FROM accounts WHERE tenant_id = ? AND code = ?",
                (tenant_id, account_code),
            ).fetchone()
            rows = conn.execute(" ".join(sql), params).fetchall()

        running = float(opening_balance)
        lines = []
        total_debit = 0.0
        total_credit = 0.0
        for r in rows:
            debit = float(r["debit"] or 0)
            credit = float(r["credit"] or 0)
            total_debit += debit
            total_credit += credit
            running += debit - credit
            lines.append(
                {
                    "entry_id": r["entry_id"],
                    "entry_number": r["entry_number"],
                    "entry_date": r["entry_date"],
                    "entry_date_jalali": r["entry_date_jalali"],
                    "status": r["status"],
                    "description": r["description"],
                    "sub_ledger_code": r["sub_ledger_code"],
                    "sub_ledger_title": r["sub_ledger_title"],
                    "debit": debit,
                    "credit": credit,
                    "running_balance": round(running, 2),
                }
            )

        return {
            "account_code": account_code,
            "account_title": meta["title"] if meta else None,
            "opening_balance": float(opening_balance),
            "lines": lines,
            "total_debit": total_debit,
            "total_credit": total_credit,
            "closing_balance": round(running, 2),
        }

    # ------------------------------------------------------------------
    # Dashboard KPIs (شاخص‌های داشبورد مدیریتی)
    # ------------------------------------------------------------------
    def get_dashboard(
        self, tenant_id: str, fiscal_year_id: Optional[str] = None
    ) -> Dict[str, Any]:
        income = self.get_income_statement(tenant_id, fiscal_year_id)
        balance = self.get_balance_sheet(tenant_id, fiscal_year_id)
        with self.ledger.get_connection() as conn:
            sql = [
                """
                SELECT
                    (SELECT COALESCE(SUM(ji.debit - ji.credit), 0.0)
                       FROM journal_items ji
                       JOIN accounts a ON ji.account_id = a.id
                       JOIN journal_entries je ON ji.entry_id = je.id
                      WHERE a.tenant_id = ? AND a.code IN ('1010', '1020') AND je.status != 'draft'
                ) AS cash_and_bank,
                    (SELECT COALESCE(SUM(ji.debit - ji.credit), 0.0)
                       FROM journal_items ji
                       JOIN accounts a ON ji.account_id = a.id
                       JOIN journal_entries je ON ji.entry_id = je.id
                      WHERE a.tenant_id = ? AND a.code LIKE '1%' AND je.status != 'draft'
                ) AS current_assets,
                    (SELECT COALESCE(SUM(ji.credit - ji.debit), 0.0)
                       FROM journal_items ji
                       JOIN accounts a ON ji.account_id = a.id
                       JOIN journal_entries je ON ji.entry_id = je.id
                      WHERE a.tenant_id = ? AND a.code LIKE '4%' AND je.status != 'draft'
                ) AS current_liabilities,
                    (SELECT COUNT(*) FROM invoices WHERE tenant_id = ?) AS invoice_count,
                    (SELECT COUNT(*) FROM cheques WHERE tenant_id = ?) AS cheque_count
                """
            ]
            params: List[Any] = [
                tenant_id, tenant_id, tenant_id, tenant_id, tenant_id
            ]
            row = conn.execute(" ".join(sql), params).fetchone()

        return {
            "net_profit": income["net_profit"],
            "gross_profit": income["gross_profit"],
            "total_revenue": income["total_revenue"],
            "total_expenses": income["total_expenses"],
            "total_assets": balance["total_assets"],
            "total_liabilities": balance["total_liabilities"],
            "cash_and_bank": float(row["cash_and_bank"] or 0),
            "current_assets": float(row["current_assets"] or 0),
            "current_liabilities": float(row["current_liabilities"] or 0),
            "invoice_count": int(row["invoice_count"] or 0),
            "cheque_count": int(row["cheque_count"] or 0),
            "is_balanced": balance["is_balanced"],
        }
