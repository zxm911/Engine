import yfinance as yf
import pandas as pd
import time

class YahooData:
    """Fetch clean OHLC data from Yahoo Finance with anti-blocking measures."""

    def __init__(self):
        pass

    def get_candles(self, symbol, interval, period="5d", max_retries=3):
        """
        Fetch OHLC data with retry logic.
        
        symbol: Yahoo Finance ticker (e.g., 'GC=F' for Gold, 'BTC-USD' for Bitcoin)
        interval: '5m', '15m', '1h', '1d'
        period: '1d', '5d', '1mo'
        """
        for attempt in range(1, max_retries + 1):
            try:
                ticker = yf.Ticker(symbol)
                df = ticker.history(period=period, interval=interval)

                if not df.empty:
                    # Success — clean and return
                    df.reset_index(inplace=True)
                    df.rename(columns={
                        'Datetime': 'time',
                        'Open': 'open',
                        'High': 'high',
                        'Low': 'low',
                        'Close': 'close'
                    }, inplace=True)
                    return df[['time', 'open', 'high', 'low', 'close']]

                else:
                    print(f"⚠️ {symbol}: Empty data (attempt {attempt}/{max_retries})")
                    if attempt < max_retries:
                        time.sleep(2 * attempt)  # Wait longer each retry
                        continue
                    else:
                        print(f"❌ {symbol}: No data after {max_retries} attempts")
                        return pd.DataFrame()

            except Exception as e:
                print(f"❌ {symbol} fetch error (attempt {attempt}): {e}")
                if attempt < max_retries:
                    time.sleep(2 * attempt)
                    continue
                else:
                    return pd.DataFrame()

        return pd.DataFrame()
