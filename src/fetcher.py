import yfinance as yf

class StockDataFetcher:
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.stock = yf.Ticker(ticker)

    def get_info(self):
        return self.stock.info

    def get_history(self, period="2y"):
        return self.stock.history(period=period)

    def get_financials(self):
        return self.stock.financials # income statement

    def get_cashflow(self):
        return self.stock.cashflow  # cash flow statement