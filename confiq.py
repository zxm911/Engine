# ============================================
# ENGINE XV1 - Configuration
# ============================================

# Yahoo Finance symbols
SYMBOLS = {
    "XAUUSD": "GC=F",       # Gold Futures
    "BTCUSD": "BTC-USD"     # Bitcoin USD
}

# Timeframes for Yahoo Finance
BIAS_TF = "1h"      # Higher timeframe for trend/bias
ENTRY_TF = "5m"     # Lower timeframe for entries
DATA_PERIOD = "5d"  # How far back to fetch data

# SMC Scoring system
SCORE_THRESHOLD = 7  # Minimum score to fire a signal
SCORES = {
    "trend_aligned": 2,
    "liquidity_sweep": 3,
    "bos": 3,
    "ob_touch": 2
}

# Risk & Trade management
MAX_SIGNALS_PER_DAY = 3
MIN_RR_RATIO = 2.0

# Telegram Bot Token (set via environment variable on Railway)
import os
TELEGRAM_TOKEN = os.environ.get("6094186912", "8664944539:AAGWo-F90tqxwoZukOH2Luvmu8Vl5ATMZqM")