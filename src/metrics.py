import pandas as pd
import numpy as np
from .fetcher import StockDataFetcher

class StockMetrics:
    def __init__(self, ticker: str):
        self.ticker = ticker
        self.fetcher = StockDataFetcher(ticker)
        self.info = self.fetcher.get_info()
        self.history = self.fetcher.get_history()
        self.financials = self.fetcher.get_financials()
        self.cashflow = self.fetcher.get_cashflow()

        if self.history.empty:
            raise ValueError(f"No price data returned for ticker '{ticker}'.")
        
        self.price_df = self.calculate_returns(self.history)
        self.price_df = self.calculate_moving_averages(self.price_df)

        self.vol = self.calculate_volatility(self.history)
        self.pe = self.pe_ratios()

    def get_data(self) -> dict:
        """
        Compile all calculated metrics into a single dictionary for output.
        
        Returns:
        dict: A dictionary containing all calculated metrics.
        """
        return {
            'ticker': self.ticker.upper(),
            "Price Data": self.price_df,
            "Volatility": self.vol,
            "P/E Ratio": self.pe
        }
    
    @staticmethod
    def calculate_returns(price_df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate daily returns from price data.
        
        Parameters:
        price_df (pd.DataFrame): DataFrame containing stock prices with a 'Close' column.
        
        Returns:
        pd.DataFrame: DataFrame containing daily returns.
        """
        df = price_df.copy()

        df['Daily Return'] = df['Close'].pct_change()

        df['Cumulative Return'] = (1 + df['Daily Return']).cumprod() - 1
        return df
    
    @staticmethod
    def classify_signal(row):
        if 'MA_50' not in row.index or 'MA_200' not in row.index:
            return 'Insufficient Data'
        if pd.isna(row['MA_50']) or pd.isna(row['MA_200']):
            return 'Insufficient Data'
        return 'Bullish' if row['MA_50'] > row['MA_200'] else 'Bearish'

    def calculate_moving_averages(self, price_df: pd.DataFrame, windows=None) -> pd.DataFrame:
        """
        Calculate moving averages for specified windows.

        Adds 50-day and 200-day simple moving averages to the price DataFrame,
        plus a signal column indicating whether the 50-day is above or below
        the 200-day.

        Note: The first 49 rows of MA_50 and first 199 rows of MA_200 will be
        NaN — this is correct. rolling() requires a full window before computing.
        
        Parameters:
        windows (list): List of integers representing the window sizes for moving averages.
        
        Returns:
        pd.DataFrame: DataFrame containing moving averages.
        """
        if windows is None:
            windows = [20, 50, 200]
        
        df = price_df.copy()
        for window in windows:
            df[f'MA_{window}'] = df['Close'].rolling(window=window).mean()

        df['Signal'] = df.apply(self.classify_signal, axis=1)
        
        return df

    def calculate_volatility(self, history) -> dict:
        """
        Calculate volatility metrics for the stock.
        
        Returns:
        dict: A dictionary containing volatility metrics.
        """
        volatility_metrics = {}
        daily_returns = history['Close'].pct_change().dropna()

        daily_vol = daily_returns.std()
        annual_vol = daily_vol * np.sqrt(252)

        volatility_metrics['Daily Volatility'] = round(daily_vol, 6)
        volatility_metrics['Annualized Volatility'] = round(annual_vol, 6)
        volatility_metrics['Annualized Volatility Pct'] = f"{annual_vol * 100:.2f}%" # Convert to percentage
        
        return volatility_metrics
    
    @staticmethod
    def _safe_round(value, ndigits=2):
        try:
            return round(float(value), ndigits) if value is not None else 'N/A'
        except (TypeError, ValueError):
            return 'N/A'

    @staticmethod
    def _format_market_cap(value) -> str:
        """Converts raw market cap int to readable string."""
        if pd.isna(value) or value is None:
            return 'N/A'
        value = float(value)
        if value >= 1_000_000_000_000:
            return f"${value / 1_000_000_000_000:.2f}T"
        elif value >= 1_000_000_000:
            return f"${value / 1_000_000_000:.2f}B"
        elif value >= 1_000_000:
            return f"${value / 1_000_000:.2f}M"
        return f"${value:,.0f}"

    def pe_ratios(self) -> dict:
        """
        Calculate P/E ratios based on different earnings metrics.
        
        Returns:
        dict: A dictionary containing P/E ratios.
        """
        pe_ratios = {}
        try:
            pe_ratios.update({
                'Price':       self._safe_round(self.info.get('currentPrice') or self.info.get('regularMarketPrice')),
                'P/E (TTM)':   self._safe_round(self.info.get('trailingPE')),
                'Forward P/E': self._safe_round(self.info.get('forwardPE')),
                'EPS (TTM)':   self._safe_round(self.info.get('trailingEps')),
                'Market Cap':  self._format_market_cap(self.info.get('marketCap')),
            })
        except (KeyError, TypeError) as e:
            print(f"Warning: could not fetch P/E data — {e}")
            
        return pe_ratios