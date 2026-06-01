from src.metrics import StockMetrics

def main():
    ticker = input("Enter a stock ticker symbol (e.g., AAPL): ").strip()
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
    except ValueError as e:
        print(e)

if __name__ == "__main__":
    main()