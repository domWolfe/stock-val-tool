from src.metrics import StockMetrics
from src.dcf import DCF
from src.exporter import ExcelExporter
from src.csv_exporter import CSVExporter
from src.model import begin

def main():
    ticker = input("Enter a stock ticker symbol (e.g., AAPL): ").strip()
    discount = float(input("Discount rate / WACC (e.g. 0.10): "))
    growth = float(input("Assumed FCF growth rate (e.g. 0.05): "))
    include_lt = input("Treat long-term investments as excess cash? " "(Y for cash-rich tech like AAPL, N for holding COs like KO) [y/n]: ").strip().lower() not in ("n", "no")
    try:
        metrics = StockMetrics(ticker)
        data = metrics.get_data()

        print(f"\nMetrics for {data['ticker']}:")
        print("\nPrice Data:")
        print(data["Price Data"].tail())
        print("\nVolatility:")
        for key, value in data["Volatility"].items():
            print(f"  {key}: {value}")
        print("\nP/E Ratio:")
        for key, value in data["P/E Ratio"].items():
            print(f"  {key}: {value}")

        dcf = DCF(ticker, discount_rate=discount, growth_rate=growth, include_lt_investments=include_lt)
        results = dcf.summary()
        print("\nDCF Valuation:")
        print(f"  Projected FCFs:      {[round(f) for f in results['projected_fcfs']]}")
        print(f"  PV of FCFs:          {[round(f) for f in results['pv_fcfs']]}")
        print(f"  Terminal Value:      {results['terminal_value']:,.0f}")
        print(f"  PV Terminal Value:   {results['pv_terminal_value']:,.0f}")
        print(f"  Enterprise Value:    {results['enterprise_value']:,.0f}")
        print("  Equity bridge:")
        print(f"    (-) Total Debt:        {results['total_debt']:,.0f}")
        print(f"    (+) Cash & ST Inv:     {results['cash_and_st_investments']:,.0f}")
        print(f"    (+) LT Investments:    {results['lt_investments']:,.0f}")
        print(f"    Net Debt:              {results['net_debt']:,.0f}  ({results['net_debt_source']})")
        print(f"  Equity Value:        {results['equity_value']:,.0f}")
        print(f"  Intrinsic Value:     {results['intrinsic_value']:,.2f}")
        print(f"  Margin of Safety:    {results['margin_of_safety']:.2%}")

        print("\nSensitivity Table: Intrinsic Value per Share ($):")
        print("(rows = discount rate, columns = projection growth rate)")
        print(dcf.sensitivity_table().to_string())

        path = ExcelExporter(data, dcf).export()
        print(f"\nExcel report saved to: {path.resolve()}")

        csv_paths = CSVExporter(data, dcf).export()
        print("\nCSV data files saved to:")
        for p in csv_paths:
            print(f"  {p.resolve()}")
    except ValueError as e:
        print(e)

if __name__ == "__main__":
    #main()
    begin()