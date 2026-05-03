import requests
import time
import json
from datetime import datetime

# ============================================
# CONFIGURATION (Built-in — no config.py needed)
# ============================================

# Telegram (hardcoded)
TELEGRAM_TOKEN = "8664944539:AAGWo-F90tqxwoZukOH2Luvmu8Vl5ATMZqM"
TELEGRAM_CHAT_ID = "6094186912"

# Yahoo Finance symbols
SYMBOLS = {
    "XAUUSD": "GC=F",
    "BTCUSD": "BTC-USD"
}

# Timeframes
BIAS_TF = "1h"
ENTRY_TF = "5m"
DATA_PERIOD = "5d"

# Max signals per day
MAX_SIGNALS_PER_DAY = 3

# ============================================
# IMPORTS
# ============================================
from data import YahooData
from engine import SMCEngine


class EngineXV1Bot:
    def __init__(self):
        self.data = YahooData()
        self.engine = SMCEngine()
        self.base_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

    def send_message(self, chat_id, text, reply_markup=None):
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        try:
            requests.post(f"{self.base_url}/sendMessage", json=payload)
        except Exception as e:
            print(f"Send error: {e}")

    def run_analysis_with_details(self, symbol_name):
        """Run analysis and return signal + breakdown details."""
        yahoo_symbol = SYMBOLS[symbol_name]
        df_bias = self.data.get_candles(yahoo_symbol, BIAS_TF, DATA_PERIOD)
        df_entry = self.data.get_candles(yahoo_symbol, ENTRY_TF, DATA_PERIOD)

        if df_bias.empty or df_entry.empty:
            return None, {"error": "Data fetch failed. Try again later."}

        if len(df_entry) < 50:
            return None, {"error": f"Not enough data. Only {len(df_entry)} candles available."}

        return self.engine.analyze_with_details(df_entry, df_bias, symbol_name)

    def format_signal(self, signal):
        """Format a winning signal message."""
        return (
            f"<b>🚨 ENGINE XV1 SIGNAL</b>\n\n"
            f"📊 Pair: <b>{signal['symbol']}</b>\n"
            f"📈 Direction: <b>{signal['type']}</b>\n"
            f"🔵 Entry: {signal['entry']}\n"
            f"🔴 SL: {signal['sl']}\n"
            f"🟢 TP: {signal['tp']}\n"
            f"⭐ Score: {signal['score']}/10\n\n"
            f"<i>🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
        )

    def format_breakdown(self, symbol_name, details):
        """Format the breakdown when NO signal is generated."""
        if "error" in details:
            return f"⚠️ <b>{details['error']}</b>"

        score = details['score']
        threshold = details['threshold']
        trend = details['trend'].upper()
        sweep = details['sweep_high'] or details['sweep_low']
        bos = details['bos']
        ob = details['ob_touch']

        trend_emoji = "📈" if trend == "BULLISH" else ("📉" if trend == "BEARISH" else "↔️")

        return (
            f"<b>❌ No valid signal for {symbol_name}</b>\n\n"
            f"<b>📊 Analysis Breakdown:</b>\n"
            f"{trend_emoji} Trend: <b>{trend}</b> ({'2' if trend != 'RANGING' else '0'} pts)\n"
            f"💧 Liquidity Sweep: <b>{'Yes' if sweep else 'No'}</b> ({'3' if sweep else '0'} pts)\n"
            f"⚡ Break of Structure: <b>{'Yes' if bos else 'No'}</b> ({'3' if bos else '0'} pts)\n"
            f"🧱 Order Block Touch: <b>{'Yes' if ob else 'No'}</b> ({'2' if ob else '0'} pts)\n\n"
            f"⭐ Total Score: <b>{score}/{threshold}</b> (Need {threshold}+)\n\n"
            f"<i>→ Staying flat. No edge right now.</i>\n"
            f"<i>🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
        )

    def handle_update(self, update):
        if "message" not in update:
            return

        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")

        # /start
        if text == "/start":
            welcome = (
                "👋 <b>Welcome to ENGINE XV1</b>\n\n"
                "I analyze markets using <b>Smart Money Concepts</b>.\n\n"
                "Commands:\n"
                "/work — Analyze XAUUSD or BTCUSD\n"
                "/status — Bot status\n\n"
                "<i>I only send signals when score is 7/10+. No forcing trades.</i>"
            )
            self.send_message(chat_id, welcome)

        # /work - show keyboard
        elif text == "/work":
            keyboard = {
                "keyboard": [
                    [{"text": "🥇 XAUUSD (Gold)"}],
                    [{"text": "₿ BTCUSD (Bitcoin)"}]
                ],
                "resize_keyboard": True,
                "one_time_keyboard": True
            }
            self.send_message(chat_id, "📊 Which pair you want me to analyze?", reply_markup=keyboard)

        # User selected Gold
        elif text == "🥇 XAUUSD (Gold)":
            self.send_message(chat_id, "⏳ Analyzing <b>XAUUSD</b>...\nFetching latest data + running SMC engine.")
            signal, details = self.run_analysis_with_details("XAUUSD")

            if signal:
                self.send_message(chat_id, self.format_signal(signal))
            else:
                self.send_message(chat_id, self.format_breakdown("XAUUSD", details))

        # User selected Bitcoin
        elif text == "₿ BTCUSD (Bitcoin)":
            self.send_message(chat_id, "⏳ Analyzing <b>BTCUSD</b>...\nFetching latest data + running SMC engine.")
            signal, details = self.run_analysis_with_details("BTCUSD")

            if signal:
                self.send_message(chat_id, self.format_signal(signal))
            else:
                self.send_message(chat_id, self.format_breakdown("BTCUSD", details))

        # /status command
        elif text == "/status":
            status_msg = (
                "<b>⚙️ ENGINE XV1 STATUS</b>\n\n"
                "✅ Bot: Online\n"
                "📡 Data: Yahoo Finance\n"
                "🧠 Engine: SMC (v1.0)\n"
                "📊 Pairs: XAUUSD, BTCUSD\n"
                "🎯 Threshold: 7/10\n\n"
                "<i>Use /work to analyze</i>"
            )
            self.send_message(chat_id, status_msg)

        # Fallback
        else:
            self.send_message(chat_id, "👋 Use <b>/work</b> to start analysis\n<b>/status</b> to check bot status")

    def run(self):
        print("🚀 ENGINE XV1 Started (Interactive Mode + Transparency)")
        print(f"🤖 Bot running...")
        last_update_id = 0

        while True:
            try:
                res = requests.get(f"{self.base_url}/getUpdates", params={
                    "offset": last_update_id + 1,
                    "timeout": 30
                })
                updates = res.json().get("result", [])

                for update in updates:
                    last_update_id = update["update_id"]
                    self.handle_update(update)

            except KeyboardInterrupt:
                print("\n👋 Bot stopped.")
                break
            except Exception as e:
                print(f"Error: {e}")
                time.sleep(5)

if __name__ == "__main__":
    bot = EngineXV1Bot()
    bot.run()
