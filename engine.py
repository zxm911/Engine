import pandas as pd
import numpy as np
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import SCORE_THRESHOLD, SCORES


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

    def detect_liquidity(self, df, threshold=0.0002):
        """Detect equal highs/lows and liquidity sweeps."""
        if len(df) < 3:
            return False, False

        eq_high = abs(df['high'].iloc[-1] - df['high'].iloc[-2]) < (df['high'].iloc[-2] * threshold)
        eq_low = abs(df['low'].iloc[-1] - df['low'].iloc[-2]) < (df['low'].iloc[-2] * threshold)

        sweep_high = False
        sweep_low = False

        if eq_high:
            recent_highs = df['high'].iloc[-3:]
            recent_closes = df['close'].iloc[-3:]
            if any(recent_highs > df['high'].iloc[-2] + (df['high'].iloc[-2] * threshold)):
                if all(c < df['high'].iloc[-2] for c in recent_closes):
                    sweep_high = True

        if eq_low:
            recent_lows = df['low'].iloc[-3:]
            recent_closes = df['close'].iloc[-3:]
            if any(recent_lows < df['low'].iloc[-2] - (df['low'].iloc[-2] * threshold)):
                if all(c > df['low'].iloc[-2] for c in recent_closes):
                    sweep_low = True

        return sweep_high, sweep_low

    def detect_bos(self, df, swings_h, swings_l, trend):
        """Break of structure: close beyond last swing point."""
        if len(swings_h) == 0 or len(swings_l) == 0:
            return False

        if trend == "bullish":
            last_swing_high = swings_h['high'].iloc[-1]
            return df['close'].iloc[-1] > last_swing_high
        elif trend == "bearish":
            last_swing_low = swings_l['low'].iloc[-1]
            return df['close'].iloc[-1] < last_swing_low
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
            recent_low = df['low'].iloc[-3:].min()
            return recent_low <= ob_high and recent_low >= ob_low
        elif trend == "bearish":
            recent_high = df['high'].iloc[-3:].max()
            return recent_high >= ob_low and recent_high <= ob_high
        return False

    def calculate_sl_tp(self, df, trend):
        """Basic SL based on recent swing, TP at 1:2 RR minimum."""
        if trend == "bullish":
            sl = df['low'].min()
            tp = df['close'].iloc[-1] + (df['close'].iloc[-1] - sl) * 2
        else:
            sl = df['high'].max()
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

        # 1. Detect trend on H1
        swings_h, swings_l = self.find_swings(df_bias)
        trend = self.detect_trend(swings_h, swings_l)

        # 2. Liquidity sweep on M5
        sweep_high, sweep_low = self.detect_liquidity(df_entry)

        # 3. Break of structure on M5
        bos = self.detect_bos(df_entry, swings_h, swings_l, trend)

        # 4. Order block detection
        ob_high, ob_low = self.find_ob(df_entry, trend)
        ob_touch = self.check_ob_touch(df_entry, ob_high, ob_low, trend)

        # 5. Scoring (using top-level imports)
        score = 0

        if trend in ["bullish", "bearish"]:
            score += SCORES["trend_aligned"]

        if trend == "bullish" and sweep_low:
            score += SCORES["liquidity_sweep"]
        elif trend == "bearish" and sweep_high:
            score += SCORES["liquidity_sweep"]

        if bos:
            score += SCORES["bos"]
        if ob_touch:
            score += SCORES["ob_touch"]

        # Build breakdown (always returned for transparency)
        breakdown = {
            "trend": trend,
            "sweep_high": sweep_high,
            "sweep_low": sweep_low,
            "bos": bos,
            "ob_touch": ob_touch,
            "score": score,
            "threshold": SCORE_THRESHOLD
        }

        # If score too low, return breakdown only (no signal)
        if score < SCORE_THRESHOLD:
            return None, breakdown

        # 6. Generate signal
        entry = round(df_entry['close'].iloc[-1], 2)
        sl, tp = self.calculate_sl_tp(df_entry, trend)

        signal = {
            "symbol": symbol_name,
            "type": "BUY" if trend == "bullish" else "SELL",
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "score": score
        }

        return signal, breakdown
