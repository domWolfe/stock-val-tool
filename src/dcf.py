import pandas as pd
from .fetcher import StockDataFetcher

class DCF:
    _OCF_LABELS: tuple[str, ...] = ('Operating Cash Flow', 'Total Cash From Operating Activities')
    _CAPEX_LABELS: tuple[str, ...] = ('Capital Expenditure', 'Capital Expenditures')

    # Interest add-back: OCF is reported net of interest paid (US GAAP puts interest in the
    # operating section), so adding back after-tax interest converts OCF-CapEx into an
    # unlevered (FCFF) figure consistent with a WACC discount and the EV to equity bridge.
    _INTEREST_CF_LABELS: tuple[str, ...] = ('Interest Paid Supplemental Data', 'Cash Paid For Interest')
    _INTEREST_IS_LABELS: tuple[str, ...] = ('Interest Expense', 'Interest Expense Non Operating')

    # Effective tax rate sources on the income statement, then a sensible default.
    _TAX_RATE_LABELS: tuple[str, ...] = ('Tax Rate For Calcs',)
    _TAX_PROVISION_LABELS: tuple[str, ...] = ('Tax Provision', 'Income Tax Expense')
    _PRETAX_LABELS: tuple[str, ...] = ('Pretax Income', 'Income Before Tax')
    _DEFAULT_TAX_RATE: float = 0.21

    # Balance-sheet rows for the enterprise-value to equity-value bridge.
    # labels vary by company, so each item is tried in priority order.
    _TOTAL_DEBT_LABELS: tuple[str, ...] = ('Total Debt',)
    _LONG_DEBT_LABELS: tuple[str, ...] = ('Long Term Debt', 'Long Term Debt And Capital Lease Obligation')
    _CURRENT_DEBT_LABELS: tuple[str, ...] = ('Current Debt', 'Current Debt And Capital Lease Obligation')
    _CASH_ST_LABELS: tuple[str, ...] = ('Cash Cash Equivalents And Short Term Investments',)
    _CASH_LABELS: tuple[str, ...] = ('Cash And Cash Equivalents', 'Cash And Cash Equivalents At Carrying Value')
    _ST_INV_LABELS: tuple[str, ...] = ('Other Short Term Investments', 'Short Term Investments')

    # Non-operating long-term financial assets (excess cash held as securities).
    _LT_INV_LABELS: tuple[str, ...] = ( 'Available For Sale Securities', 'Investmentin Financial Assets', 'Long Term Investments', 'Investments And Advances', 'Other Investments',)

    def __init__(self, ticker: str, discount_rate: float = 0.1, growth_rate: float = 0.05, terminal_growth_rate: float = 0.02, projection_years: int = 5, include_lt_investments: bool = True, tax_rate: float | None = None) -> None:
        """Build a discounted cash flow valuation for a single ticker.

        Fetches company info and the cash flow statement, derives a base unlevered free cash flow (FCFF) from the average of the last 3 years of 
        (Operating Cash Flow - Capital Expenditure + after-tax interest), then runs the full valuation via calculate().  The interest add-back makes 
        the cash flow pre-financing so it is consistent with discounting at WACC and bridging enterprise value to equity value via net debt.

        Parameters:
        ticker (str): Stock ticker symbol to value (e.g. 'AAPL').
        discount_rate (float): Annual rate used to discount future cash flows to present value (the WACC / required return). Defaults to 0.10.
        growth_rate (float): Annual growth rate applied to the base FCF over the projection window. Defaults to 0.05.
        terminal_growth_rate (float): Perpetual growth rate used in the terminal value. Must be less than discount_rate. Defaults to 0.02.
        projection_years (int): Number of years to explicitly project before the terminal value. Defaults to 5.
        include_lt_investments (bool): Whether to treat non-operating long-term investments (marketable securities) as excess cash in the equity
            bridge. Appropriate for cash-rich firms holding securities (AAPL, GOOGL); set False for holding companies whose 'investments' are
            operating / equity-method stakes (e.g. KO's bottlers). Defaults to True.
        tax_rate (float | None): Effective tax rate used to compute the after-tax interest add-back. When None (the default), it is
            derived from the income statement, falling back to 21% if unavailable.

        Raises:
        ValueError: If terminal_growth_rate >= discount_rate, or if shares outstanding cannot be retrieved for the ticker.
        KeyError: If the cash flow statement lacks a recognized operating cash flow or capital expenditure row.
        """
        if terminal_growth_rate >= discount_rate:
            raise ValueError("terminal_growth_rate must be less than discount_rate " f"(got {terminal_growth_rate} >= {discount_rate}).")

        self.ticker = ticker
        self.fetcher = StockDataFetcher(ticker)
        self.info = self.fetcher.get_info()
        self.cashflow = self.fetcher.get_cashflow()
        self.balance_sheet = self.fetcher.get_balance_sheet()
        self.financials = self.fetcher.get_financials()

        ocf = self._lookup_cashflow(self._OCF_LABELS)
        capex = self._lookup_cashflow(self._CAPEX_LABELS) # Negative number, so add it to OCF to get FCF.

        # Convert OCF-CapEx (which is net of interest paid) into an unlevered FCFF by adding back after-tax interest.
        self.tax_rate = tax_rate if tax_rate is not None else self._effective_tax_rate()
        interest = self._interest_series().reindex(ocf.index).fillna(0.0)
        after_tax_interest = interest * (1 - self.tax_rate)

        years = min(3, len(ocf)) # Average last 3 years instead of just most recent.
        self.base_fcf = float((ocf.iloc[:years] - capex.iloc[:years].abs() + after_tax_interest.iloc[:years]).mean())

        self.discount_rate = discount_rate
        self.growth_rate = growth_rate
        self.terminal_growth_rate = terminal_growth_rate
        self.projection_years = projection_years
        self.include_lt_investments = include_lt_investments
        self.shares_outstanding = self.info.get('sharesOutstanding')
        if not self.shares_outstanding:
            raise ValueError(f"Could not retrieve shares outstanding for '{ticker}'.")

        # Net debt is independent of the rate assumptions, so compute it once here rather than on every calculate()/sensitivity sweep.
        self.net_debt_components = self._calculate_net_debt()
        self.net_debt = self.net_debt_components['net_debt']

        self.calculate()

    def calculate(self) -> float:
        """Run the full valuation using the current parameters.

        Populates the projection, present values, enterprise/equity value, and
        per-share results. Safe to call again after changing any input.
        """
        self.projected_fcfs = self.project_cash_flows()
        self.pv_fcfs = self.calculate_pv_fcfs(self.projected_fcfs)
        self.terminal_value = (self.projected_fcfs[-1] * (1 + self.terminal_growth_rate) / (self.discount_rate - self.terminal_growth_rate))
        self.pv_terminal_value = (self.terminal_value / ((1 + self.discount_rate) ** self.projection_years))
        self.enterprise_value = sum(self.pv_fcfs) + self.pv_terminal_value

        self.equity_value = self.enterprise_value - self.net_debt
        self.intrinsic_value_per_share = self.equity_value / self.shares_outstanding

        current_price = self.info.get('currentPrice', 0)
        self.margin_of_safety = ((self.intrinsic_value_per_share - current_price) / self.intrinsic_value_per_share)

        return self.intrinsic_value_per_share

    def recalculate(self, growth_rate: float) -> float:
        """Re-run the valuation with a new projection growth rate."""
        self.growth_rate = growth_rate
        return self.calculate()

    def sensitivity_table(self, growth_rates: list[float] | None = None, discount_rates: list[float] | None = None) -> pd.DataFrame:
        """Return a grid of intrinsic values per share across input assumptions.

        Rows are discount rates, columns are projection growth rates, and each cell is the resulting intrinsic value per share. Cells where the
        terminal growth rate is not less than the discount rate are left as NaN (the terminal value formula is undefined there). The DCF's original
        parameters and results are restored before returning, so the object is left unchanged.

        Parameters:
        growth_rates (list[float]): Projection growth rates to sweep. Defaults to the current rate +/- 2 percentage points.
        discount_rates (list[float]): Discount rates to sweep. Defaults to the current rate +/- 2 percentage points.
        """
        if growth_rates is None:
            growth_rates = [round(self.growth_rate + d, 4) for d in (-0.02, -0.01, 0.0, 0.01, 0.02)]
        if discount_rates is None:
            discount_rates = [round(self.discount_rate + d, 4) for d in (-0.02, -0.01, 0.0, 0.01, 0.02)]

        original_growth = self.growth_rate
        original_discount = self.discount_rate

        data: list[list[float]] = []
        for discount in discount_rates:
            row: list[float] = []
            for growth in growth_rates:
                if self.terminal_growth_rate >= discount:
                    row.append(float('nan'))
                    continue
                self.discount_rate = discount
                self.growth_rate = growth
                self.calculate()
                row.append(round(self.intrinsic_value_per_share, 2))
            data.append(row)

        self.growth_rate = original_growth
        self.discount_rate = original_discount
        self.calculate()

        table = pd.DataFrame(data, index=[f"{d:.0%}" for d in discount_rates], columns=[f"{g:.0%}" for g in growth_rates],)
        table.index.name = "Discount \\ Growth"
        return table

    def summary(self) -> dict:
        """Return the full set of valuation results as a dictionary."""
        return {
            'base_fcf':                self.base_fcf,
            'tax_rate':                self.tax_rate,
            'projected_fcfs':          self.projected_fcfs,
            'pv_fcfs':                 self.pv_fcfs,
            'terminal_value':          self.terminal_value,
            'pv_terminal_value':       self.pv_terminal_value,
            'enterprise_value':        self.enterprise_value,
            'total_debt':              self.net_debt_components['total_debt'],
            'cash_and_st_investments': self.net_debt_components['cash_and_st_investments'],
            'lt_investments':          self.net_debt_components['lt_investments'],
            'net_debt':                self.net_debt,
            'net_debt_source':         self.net_debt_components['source'],
            'equity_value':            self.equity_value,
            'intrinsic_value':         self.intrinsic_value_per_share,
            'margin_of_safety':        self.margin_of_safety,
        }

    def _lookup_balance(self, labels: tuple[str, ...]) -> tuple[float | None, str | None]:
        """Return the most recent value for the first matching balance-sheet row.

        Returns (value, label) where label is the row name that matched, or (None, None) if no label is present or every value is missing.
        """
        if self.balance_sheet is None or self.balance_sheet.empty:
            return None, None
        for label in labels:
            if label in self.balance_sheet.index:
                series = self.balance_sheet.loc[label].dropna()
                if not series.empty:
                    return float(series.iloc[0]), label
        return None, None

    def _calculate_net_debt(self) -> dict:
        """Build the net-debt figure for the enterprise -> equity bridge.

        Net debt = total debt - cash & equivalents - short-term investments - non-operating long-term investments (marketable securities held as
        excess cash). Pulls from the balance sheet when available and falls back to the most-recent-quarter figures in ``info`` otherwise. Returns the
        components so the bridge can be shown transparently in the report.

        Long-term investments are treated as non-operating excess assets only when ``include_lt_investments`` is True (the default). This is
        appropriate for cash-rich firms holding marketable securities (e.g. AAPL, GOOGL) but would overstate equity value for holding companies
        whose 'investments' are operating/equity-method stakes; pass ``include_lt_investments=False`` for those.
        """
        info_debt = self.info.get('totalDebt') or 0.0
        info_cash = self.info.get('totalCash') or 0.0

        if self.balance_sheet is None or self.balance_sheet.empty:
            return {
                'total_debt': float(info_debt),
                'cash_and_st_investments': float(info_cash),
                'lt_investments': 0.0,
                'net_debt': float(info_debt - info_cash),
                'source': 'info (most recent quarter)',
            }

        total_debt, _ = self._lookup_balance(self._TOTAL_DEBT_LABELS)
        if total_debt is None:
            long_debt, _ = self._lookup_balance(self._LONG_DEBT_LABELS)
            curr_debt, _ = self._lookup_balance(self._CURRENT_DEBT_LABELS)
            if long_debt is not None or curr_debt is not None:
                total_debt = (long_debt or 0.0) + (curr_debt or 0.0)
            else:
                total_debt = float(info_debt)

        cash_st, _ = self._lookup_balance(self._CASH_ST_LABELS)
        if cash_st is None:
            cash, _ = self._lookup_balance(self._CASH_LABELS)
            st_inv, _ = self._lookup_balance(self._ST_INV_LABELS)
            if cash is not None or st_inv is not None:
                cash_st = (cash or 0.0) + (st_inv or 0.0)
            else:
                cash_st = float(info_cash)

        if self.include_lt_investments:
            lt_inv, _ = self._lookup_balance(self._LT_INV_LABELS)
            lt_inv = lt_inv or 0.0
        else:
            lt_inv = 0.0

        net_debt = total_debt - cash_st - lt_inv
        return {
            'total_debt': total_debt,
            'cash_and_st_investments': cash_st,
            'lt_investments': lt_inv,
            'net_debt': net_debt,
            'source': 'balance sheet (annual)',
        }

    def _lookup_cashflow(self, labels: tuple[str, ...]) -> pd.Series:
        """Return the cash flow row matching the first known label."""
        for label in labels:
            if label in self.cashflow.index:
                return self.cashflow.loc[label]
        raise KeyError(f"None of {labels} found in cash flow statement for '{self.ticker}'. "f"Available rows: {list(self.cashflow.index)}")

    @staticmethod
    def _first_row(df: pd.DataFrame | None, labels: tuple[str, ...]) -> pd.Series | None:
        """Return the first matching row of ``df`` (as a Series), or None if absent/empty."""
        if df is None or df.empty:
            return None
        for label in labels:
            if label in df.index:
                series = df.loc[label]
                if series.notna().any():
                    return series
        return None

    def _interest_series(self) -> pd.Series:
        """Return a per-year interest series for the after-tax add-back.

        Prefers actual cash interest paid (matches OCF's cash basis), falls back to income-statement interest expense, and returns 
        an empty Series when neither is available (no add-back). Values are taken as magnitudes so the add-back is always additive regardless of reported sign.
        """
        series = self._first_row(self.cashflow, self._INTEREST_CF_LABELS)
        if series is None:
            series = self._first_row(self.financials, self._INTEREST_IS_LABELS)
        if series is None:
            return pd.Series(dtype=float)
        return series.abs()

    def _effective_tax_rate(self) -> float:
        """Derive the effective tax rate from the income statement, defaulting to 21%.

        Uses yfinance's precomputed 'Tax Rate For Calcs' when present, otherwise Tax Provision / Pretax
        Income from the most recent year. Falls back to the default when data is missing or implausible
        (outside [0, 1)), which guards against negative pretax income producing a nonsensical rate.
        """
        rate_row = self._first_row(self.financials, self._TAX_RATE_LABELS)
        if rate_row is not None:
            rate = float(rate_row.dropna().iloc[0])
            if 0.0 <= rate < 1.0:
                return rate

        provision = self._first_row(self.financials, self._TAX_PROVISION_LABELS)
        pretax = self._first_row(self.financials, self._PRETAX_LABELS)
        if provision is not None and pretax is not None:
            prov_val = float(provision.dropna().iloc[0])
            pretax_val = float(pretax.dropna().iloc[0])
            if pretax_val > 0:
                rate = prov_val / pretax_val
                if 0.0 <= rate < 1.0:
                    return rate

        return self._DEFAULT_TAX_RATE

    def project_cash_flows(self) -> list[float]:
        projected_fcfs: list[float] = []
        for year in range(1, self.projection_years + 1):
            growth_factor = (1 + self.growth_rate) ** year
            projected_fcfs.append(self.base_fcf * growth_factor)
        return projected_fcfs

    def calculate_pv_fcfs(self, projected_fcfs: list[float]) -> list[float]:
        pv_fcfs: list[float] = []
        for year, fcf in enumerate(projected_fcfs, start=1):
            pv_fcf = fcf / ((1 + self.discount_rate) ** year)
            pv_fcfs.append(pv_fcf)
        return pv_fcfs
