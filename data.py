import yfinance as yf
import pandas as pd

class YahooData:
    """Fetch clean OHLC data from Yahoo Finance."""

    def get_candles(self, symbol, interval, period="5d"):
        """
        symbol: Yahoo Finance ticker (e.g., 'GC=F', 'BTC-USD')
        interval: '5m', '15m', '1h', '4h', '1d'
        period: '1d', '5d', '1mo' (5m data limited to last ~7 days)
        """
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)

            if df.empty:
                return pd.DataFrame()

            df.reset_index(inplace=True)
            df.rename(columns={
                'Datetime': 'time',
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close'
            }, inplace=True)

            return df[['time', 'open', 'high', 'low', 'close']]

        except Exception as e:
            print(f"Data fetch error for {symbol}: {e}")
            return pd.DataFrame()