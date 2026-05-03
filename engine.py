import pandas as pd
import numpy as np


class SMCEngine:
    """Smart Money Concepts analysis engine."""

    def find_swings(self, df, window=5):
        """Detect swing highs and lows using a rolling window."""
        if len(df) < window * 2:
            return pd.DataFrame(), pd.DataFrame()

        highs = df['high'].rolling(window=window, center=True).max()
        lows = df['low'].rolling(window=window, center=True).min()

        swing_highs = df[(df['high'] == highs) &
                         (df['high'] > df['high'].shift(1)) &
                         (df['high'] > df['high'].shift(-1))].copy()

        swing_lows = df[(df['low'] == lows) &
                        (df['low'] < df['low'].shift(1)) &
                        (df['low'] < df['low'].shift(-1))].copy()

        return swing_highs, swing_lows

    def detect_trend(self, swings_h, swings_l):
        """Bullish (HH, HL) or Bearish (LH, LL) or Ranging."""
        if len(swings_h) < 2 or len(swings_l) < 2:
            return "ranging"

        hh = swings_h['high'].iloc[-1] > swings_h['high'].iloc[-2]
        hl = swings_l['low'].iloc[-1] > swings_l['low'].iloc[-2]

        if hh and hl:
            return "bullish"
        elif not hh and not hl:
            return "bearish"
        else:
            return "ranging"

    def detect_liquidity(self, df, swing_window=5, pool_candles=60, sweep_window=15):
        """
        Detect liquidity sweeps of swing highs/lows (proper SMC approach).
        Uses swing points as liquidity pools, not absolute highs/lows.
        A sweep = wick through a swing level + close back inside.
        pool_candles: how many prior candles to find swing levels in
        sweep_window: how many recent candles to check for sweeps
        """
        min_len = pool_candles + sweep_window + swing_window * 2
        if len(df) < min_len:
            return False, False

        pool_df = df.iloc[-pool_candles - sweep_window: -sweep_window]
        swings_h, swings_l = self.find_swings(pool_df, window=swing_window)

        sweep_high = False
        sweep_low = False

        for i in range(sweep_window, 0, -1):
            candle = df.iloc[-i]

            if not swings_h.empty:
                for level in swings_h['high'].values:
                    if candle['high'] > level and candle['close'] < level:
                        sweep_high = True

            if not swings_l.empty:
                for level in swings_l['low'].values:
                    if candle['low'] < level and candle['close'] > level:
                        sweep_low = True

        return sweep_high, sweep_low

    def detect_bos(self, df_entry, trend):
        """
        Break of Structure on the ENTRY timeframe (M5).
        Checks if price closed beyond the most recent swing high/low on M5.
        """
        swings_h, swings_l = self.find_swings(df_entry)

        if len(swings_h) == 0 or len(swings_l) == 0:
            return False

        if trend == "bullish":
            last_swing_high = swings_h['high'].iloc[-1]
            return df_entry['close'].iloc[-1] > last_swing_high
        elif trend == "bearish":
            last_swing_low = swings_l['low'].iloc[-1]
            return df_entry['close'].iloc[-1] < last_swing_low

        return False

    def find_ob(self, df, trend):
        """Simplified Order Block: last opposite candle before impulse."""
        if len(df) < 3:
            return None, None

        if trend == "bullish":
            bear_mask = df['close'] < df['open']
            if bear_mask.any():
                ob_candle = df[bear_mask].iloc[-1]
                return ob_candle['high'], ob_candle['low']
        elif trend == "bearish":
            bull_mask = df['close'] > df['open']
            if bull_mask.any():
                ob_candle = df[bull_mask].iloc[-1]
                return ob_candle['low'], ob_candle['high']

        return None, None

    def check_ob_touch(self, df, ob_high, ob_low, trend):
        """Check if price has recently touched the order block zone."""
        if ob_high is None or ob_low is None:
            return False

        if trend == "bullish":
            recent_low = df['low'].iloc[-5:].min()
            return ob_low <= recent_low <= ob_high
        elif trend == "bearish":
            recent_high = df['high'].iloc[-5:].max()
            return ob_low <= recent_high <= ob_high

        return False

    def calculate_sl_tp(self, df, trend):
        """Basic SL based on recent swing, TP at 1:2 RR minimum."""
        if trend == "bullish":
            sl = df['low'].iloc[-20:].min()
            tp = df['close'].iloc[-1] + (df['close'].iloc[-1] - sl) * 2
        else:
            sl = df['high'].iloc[-20:].max()
            tp = df['close'].iloc[-1] - (sl - df['close'].iloc[-1]) * 2
        return round(sl, 2), round(tp, 2)

    def analyze_with_details(self, df_entry, df_bias, symbol_name):
        """
        Run full SMC analysis and return (signal, breakdown).

        Returns:
            (signal, breakdown)
            - signal: dict with entry/sl/tp/score if valid, else None
            - breakdown: dict with all analysis details always
        """
        if df_entry.empty or df_bias.empty:
            return None, {"error": "Data is empty. Try again."}

        # 1. Detect trend on H1 bias timeframe
        swings_h_bias, swings_l_bias = self.find_swings(df_bias)
        trend = self.detect_trend(swings_h_bias, swings_l_bias)

        # 2. Liquidity sweep on M5
        sweep_high, sweep_low = self.detect_liquidity(df_entry)

        # 3. Determine effective bias for BOS and OB
        # If H1 is ranging, use the 5m sweep direction as the directional bias
        if trend in ["bullish", "bearish"]:
            effective_bias = trend
        elif sweep_low and not sweep_high:
            effective_bias = "bullish"
        elif sweep_high and not sweep_low:
            effective_bias = "bearish"
        else:
            effective_bias = "ranging"

        # 4. Break of structure using effective bias on M5
        bos = self.detect_bos(df_entry, effective_bias)

        # 5. Order block detection using effective bias
        ob_high, ob_low = self.find_ob(df_entry, effective_bias)
        ob_touch = self.check_ob_touch(df_entry, ob_high, ob_low, effective_bias)

        # 6. Scoring
        SCORE_THRESHOLD = 7
        score = 0

        # H1 trend aligned = 2pts, H1 ranging but sweep gives direction = 1pt
        if trend in ["bullish", "bearish"]:
            score += 2
        elif effective_bias != "ranging":
            score += 1

        # Liquidity sweep in direction of effective bias
        if effective_bias == "bullish" and sweep_low:
            score += 3
        elif effective_bias == "bearish" and sweep_high:
            score += 3

        if bos:
            score += 3
        if ob_touch:
            score += 2

        breakdown = {
            "trend": trend,
            "effective_bias": effective_bias,
            "sweep_high": sweep_high,
            "sweep_low": sweep_low,
            "bos": bos,
            "ob_touch": ob_touch,
            "score": score,
            "threshold": SCORE_THRESHOLD
        }

        if score < SCORE_THRESHOLD:
            return None, breakdown

        # 7. Generate signal
        entry = round(df_entry['close'].iloc[-1], 2)
        sl, tp = self.calculate_sl_tp(df_entry, effective_bias)

        signal = {
            "symbol": symbol_name,
            "type": "BUY" if effective_bias == "bullish" else "SELL",
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "score": score
        }

        return signal, breakdown
