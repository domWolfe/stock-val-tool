from datetime import datetime
from pathlib import Path

import pandas as pd


class CSVExporter:
    """Write StockMetrics + DCF analysis as clean CSVs for data-science use.

    Unlike :class:`ExcelExporter`, which produces a styled workbook, this emits machine-readable tables: raw numeric values (no
    currency symbols or percent strings).Four files are written:

    * ``{ticker}_metrics_{date}.csv`` - one wide row of scalar metrics,
      designed to be stacked into a cross-sectional panel across tickers.
    * ``{ticker}_price_history_{date}.csv`` - the full daily price time series.
    * ``{ticker}_dcf_projection_{date}.csv`` - per-year projected and PV cash flows.
    * ``{ticker}_sensitivity_{date}.csv`` - long-format intrinsic-value grid.
    """

    def __init__(self, data: dict, dcf, output_dir: str = "data"):
        """
        Parameters:
        data (dict): The dict returned by StockMetrics.get_data().
        dcf (DCF): A calculated DCF instance for the same ticker.
        output_dir (str): Folder the CSV files are written into.
        """
        self.data = data
        self.dcf = dcf
        self.ticker = data["ticker"]
        self.output_dir = Path(output_dir)

    def export(self, prefix: str | None = None) -> list[Path]:
        """Write every CSV table and return the list of paths created.

        Parameters:
        prefix (str | None): Filename stem shared by all files. Defaults to ``{ticker}_..._{YYYYMMDD}`` using today's date.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d")
        prefix = prefix or self.ticker

        paths = [
            self._write(self._metrics_row(), f"{prefix}_metrics_{stamp}.csv", index=False),
            self._write(self._price_history(), f"{prefix}_price_history_{stamp}.csv", index=False),
            self._write(self._dcf_projection(), f"{prefix}_dcf_projection_{stamp}.csv", index=False),
            self._write(self._sensitivity_long(), f"{prefix}_sensitivity_{stamp}.csv", index=False),
        ]
        return paths

    # -- tables ---------------------------------------------------------------
    def _metrics_row(self) -> pd.DataFrame:
        """One wide row combining the market snapshot and DCF results.

        Values are kept as raw numbers (prices, ratios, and absolute currency figures) so rows for different tickers can be concatenated into a single
        feature table without the need to re-parse formatted strings.
        """
        s = self.dcf.summary()
        info = self.dcf.info
        pe = self.data["P/E Ratio"]
        vol = self.data["Volatility"]
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        mos = s["margin_of_safety"]

        row = {
            "ticker": self.ticker,
            "generated_date": datetime.now().strftime("%Y-%m-%d"),
            "current_price": price,
            "pe_ttm": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "eps_ttm": info.get("trailingEps"),
            "market_cap": info.get("marketCap"),
            "daily_volatility": vol.get("Daily Volatility"),
            "annualized_volatility": vol.get("Annualized Volatility"),
            "base_fcf": s["base_fcf"],
            "tax_rate": s["tax_rate"],
            "discount_rate": self.dcf.discount_rate,
            "growth_rate": self.dcf.growth_rate,
            "terminal_growth_rate": self.dcf.terminal_growth_rate,
            "projection_years": self.dcf.projection_years,
            "terminal_value": s["terminal_value"],
            "pv_terminal_value": s["pv_terminal_value"],
            "sum_pv_fcfs": sum(s["pv_fcfs"]),
            "enterprise_value": s["enterprise_value"],
            "total_debt": s["total_debt"],
            "cash_and_st_investments": s["cash_and_st_investments"],
            "lt_investments": s["lt_investments"],
            "net_debt": s["net_debt"],
            "net_debt_source": s["net_debt_source"],
            "equity_value": s["equity_value"],
            "shares_outstanding": self.dcf.shares_outstanding,
            "intrinsic_value_per_share": s["intrinsic_value"],
            "margin_of_safety": mos,
            "verdict": "UNDERVALUED" if mos > 0 else "OVERVALUED",
        }
        return pd.DataFrame([row])

    def _price_history(self) -> pd.DataFrame:
        """The full daily price series with a leading ISO ``date`` column."""
        df = self.data["Price Data"].copy()
        df = df.reset_index()
        df.columns = ["date" if i == 0 else str(c) for i, c in enumerate(df.columns)]
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        return df

    def _dcf_projection(self) -> pd.DataFrame:
        """Per-year projected free cash flow and its present value."""
        years = range(1, self.dcf.projection_years + 1)
        return pd.DataFrame({
            "year": list(years),
            "projected_fcf": self.dcf.projected_fcfs,
            "pv_fcf": self.dcf.pv_fcfs,
        })

    def _sensitivity_long(self) -> pd.DataFrame:
        """Sensitivity grid trimmed down to (discount_rate, growth_rate, value) rows."""
        table = self.dcf.sensitivity_table()
        long = (
            table.reset_index()
            .melt(id_vars=table.index.name, var_name="growth_rate", value_name="intrinsic_value_per_share")
            .rename(columns={table.index.name: "discount_rate"})
        )
        return long

    # -- helpers --------------------------------------------------------------
    def _write(self, df: pd.DataFrame, filename: str, index: bool) -> Path:
        path = self.output_dir / filename
        df.to_csv(path, index=index)
        return path
