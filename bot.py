import requests
import time
import json
import threading
from datetime import datetime, timedelta, timezone

# ============================================
# CONFIGURATION
# ============================================

TELEGRAM_TOKEN = "8664944539:AAGWo-F90tqxwoZukOH2Luvmu8Vl5ATMZqM"
TELEGRAM_CHAT_ID = "6094186912"

SYMBOLS = {
    "XAUUSD": "GC=F",
    "BTCUSD": "BTC-USD"
}

BIAS_TF = "1h"
ENTRY_TF = "5m"
DATA_PERIOD = "5d"

SCAN_INTERVAL = 30        # seconds between each scan
MAX_SIGNALS = 2           # signals before cooldown
COOLDOWN_HOURS = 1        # hours to pause after MAX_SIGNALS

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

        # Auto-scanner state
        self.signals_sent = 0
        self.cooldown_until = None
        self.last_signal = {}  # {symbol: entry_price} — avoids duplicate sends per candle

    # ==========================================
    # TELEGRAM
    # ==========================================

    def send_message(self, chat_id, text, reply_markup=None):
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        try:
            requests.post(f"{self.base_url}/sendMessage", json=payload)
        except Exception as e:
            print(f"Send error: {e}")

    # ==========================================
    # ANALYSIS
    # ==========================================

    def run_analysis_with_details(self, symbol_name, silent=False):
        """
        Run SMC analysis. If silent=True, stale/error conditions return (None, None)
        without an error dict so the auto-scanner stays quiet.
        """
        yahoo_symbol = SYMBOLS[symbol_name]
        df_bias = self.data.get_candles(yahoo_symbol, BIAS_TF, DATA_PERIOD)
        df_entry = self.data.get_candles(yahoo_symbol, ENTRY_TF, DATA_PERIOD)

        if df_bias.empty or df_entry.empty:
            if silent:
                return None, None
            return None, {"error": "Data fetch failed. Try again later."}

        if len(df_entry) < 50:
            if silent:
                return None, None
            return None, {"error": f"Not enough data. Only {len(df_entry)} candles available."}

        # Stale data check (last candle older than 2 hours = market closed)
        last_candle_time = df_entry['time'].iloc[-1].to_pydatetime()
        if last_candle_time.tzinfo is not None:
            last_candle_time = last_candle_time.astimezone(timezone.utc).replace(tzinfo=None)
        age_hours = (datetime.now(timezone.utc).replace(tzinfo=None) - last_candle_time) / timedelta(hours=1)
        if age_hours > 2:
            if silent:
                return None, None
            return None, {"error": (
                f"⚠️ Market appears closed or data is stale.\n"
                f"Last candle: {df_entry['time'].iloc[-1]}\n"
                f"Try again during market hours (Mon–Fri)."
            )}

        return self.engine.analyze_with_details(df_entry, df_bias, symbol_name)

    # ==========================================
    # FORMATTERS
    # ==========================================

    def format_signal(self, signal, source="manual"):
        tag = "🤖 <b>AUTO-SIGNAL</b>" if source == "auto" else "<b>🚨 ENGINE XV1 SIGNAL</b>"
        return (
            f"{tag}\n\n"
            f"📊 Pair: <b>{signal['symbol']}</b>\n"
            f"📈 Direction: <b>{signal['type']}</b>\n"
            f"🔵 Entry: {signal['entry']}\n"
            f"🔴 SL: {signal['sl']}\n"
            f"🟢 TP: {signal['tp']}\n"
            f"⭐ Score: {signal['score']}/10\n\n"
            f"<i>🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
        )

    def format_breakdown(self, symbol_name, details):
        if "error" in details:
            return f"⚠️ <b>{details['error']}</b>"

        score = details['score']
        threshold = details['threshold']
        trend = details['trend'].upper()
        effective_bias = details.get('effective_bias', trend).upper()
        sweep_high = details['sweep_high']
        sweep_low = details['sweep_low']
        sweep = sweep_high or sweep_low
        bos = details['bos']
        ob = details['ob_touch']

        trend_emoji = "📈" if effective_bias == "BULLISH" else ("📉" if effective_bias == "BEARISH" else "↔️")
        trend_pts = 2 if trend in ("BULLISH", "BEARISH") else (1 if effective_bias != "RANGING" else 0)
        sweep_pts = 3 if sweep else 0
        bos_pts = 3 if bos else 0
        ob_pts = 2 if ob else 0

        bias_line = f"{trend_emoji} H1 Trend: <b>{trend}</b>"
        if trend == "RANGING" and effective_bias != "RANGING":
            bias_line += f" → Bias from sweep: <b>{effective_bias}</b>"
        bias_line += f" ({trend_pts} pts)"

        sweep_detail = " (high swept)" if sweep_high else (" (low swept)" if sweep_low else "")

        return (
            f"<b>❌ No valid signal for {symbol_name}</b>\n\n"
            f"<b>📊 Analysis Breakdown:</b>\n"
            f"{bias_line}\n"
            f"💧 Liquidity Sweep: <b>{'Yes' if sweep else 'No'}</b>{sweep_detail} ({sweep_pts} pts)\n"
            f"⚡ Break of Structure: <b>{'Yes' if bos else 'No'}</b> ({bos_pts} pts)\n"
            f"🧱 Order Block Touch: <b>{'Yes' if ob else 'No'}</b> ({ob_pts} pts)\n\n"
            f"⭐ Total Score: <b>{score}/{threshold}</b> (Need {threshold}+)\n\n"
            f"<i>→ Staying flat. No edge right now.</i>\n"
            f"<i>🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
        )

    # ==========================================
    # AUTO SCANNER
    # ==========================================

    def auto_scan(self):
        """
        Background thread: scans both pairs every 30 seconds.
        - Silent when no signal (no message sent)
        - Sends signal automatically when score >= 7
        - After 2 signals sent → 1 hour cooldown, then resets and resumes
        - Skips duplicate signals (same entry price already sent)
        """
        print(f"🔍 Auto-scanner started — checking every {SCAN_INTERVAL}s")

        while True:
            now = datetime.utcnow()

            # Check if in cooldown
            if self.cooldown_until:
                if now < self.cooldown_until:
                    remaining = int((self.cooldown_until - now).total_seconds() / 60)
                    print(f"⏸ Auto-scan on cooldown — {remaining}m remaining")
                    time.sleep(SCAN_INTERVAL)
                    continue
                else:
                    # Cooldown expired — reset and resume
                    self.cooldown_until = None
                    self.signals_sent = 0
                    self.last_signal = {}
                    self.send_message(TELEGRAM_CHAT_ID, "🔄 <b>Auto-scan resumed.</b> Cooldown over — watching markets again.")
                    print("🔄 Cooldown over. Auto-scan resumed.")

            # Scan each symbol
            for symbol_name in SYMBOLS:
                try:
                    signal, details = self.run_analysis_with_details(symbol_name, silent=True)

                    if signal:
                        entry = signal['entry']
                        # Skip if we already sent this exact signal (same entry price)
                        if self.last_signal.get(symbol_name) == entry:
                            continue

                        self.last_signal[symbol_name] = entry
                        self.signals_sent += 1
                        self.send_message(TELEGRAM_CHAT_ID, self.format_signal(signal, source="auto"))
                        print(f"📡 Auto-signal #{self.signals_sent} sent: {symbol_name} {signal['type']} @ {entry}")

                        # Hit max signals — enter cooldown
                        if self.signals_sent >= MAX_SIGNALS:
                            self.cooldown_until = datetime.utcnow() + timedelta(hours=COOLDOWN_HOURS)
                            self.send_message(
                                TELEGRAM_CHAT_ID,
                                f"⏸ <b>{MAX_SIGNALS} signals sent.</b>\n"
                                f"Auto-scan paused for <b>{COOLDOWN_HOURS} hour</b> to avoid spam.\n"
                                f"Resumes at: {self.cooldown_until.strftime('%H:%M UTC')}"
                            )
                            print(f"⏸ Cooldown active until {self.cooldown_until}")
                            break

                except Exception as e:
                    print(f"⚠️ Auto-scan error ({symbol_name}): {e}")

            time.sleep(SCAN_INTERVAL)

    # ==========================================
    # TELEGRAM COMMAND HANDLER
    # ==========================================

    def handle_update(self, update):
        if "message" not in update:
            return

        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")

        if text == "/start":
            welcome = (
                "👋 <b>Welcome to ENGINE XV1</b>\n\n"
                "I analyze markets using <b>Smart Money Concepts</b>.\n\n"
                "<b>Commands:</b>\n"
                "/work — Manually analyze XAUUSD or BTCUSD\n"
                "/status — Bot + auto-scan status\n\n"
                "🤖 <b>Auto-scan is always running</b> — I scan both pairs every 30s "
                "and alert you automatically when I find a valid signal. "
                "After 2 signals I pause for 1 hour to avoid spam.\n\n"
                "<i>Threshold: 7/10. No forcing trades.</i>"
            )
            self.send_message(chat_id, welcome)

        elif text == "/work":
            keyboard = {
                "keyboard": [
                    [{"text": "🥇 XAUUSD (Gold)"}],
                    [{"text": "₿ BTCUSD (Bitcoin)"}]
                ],
                "resize_keyboard": True,
                "one_time_keyboard": True
            }
            self.send_message(chat_id, "📊 Which pair do you want to analyze?", reply_markup=keyboard)

        elif text == "🥇 XAUUSD (Gold)":
            self.send_message(chat_id, "⏳ Analyzing <b>XAUUSD</b>...\nFetching data + running SMC engine.")
            signal, details = self.run_analysis_with_details("XAUUSD")
            if signal:
                self.send_message(chat_id, self.format_signal(signal))
            else:
                self.send_message(chat_id, self.format_breakdown("XAUUSD", details))

        elif text == "₿ BTCUSD (Bitcoin)":
            self.send_message(chat_id, "⏳ Analyzing <b>BTCUSD</b>...\nFetching data + running SMC engine.")
            signal, details = self.run_analysis_with_details("BTCUSD")
            if signal:
                self.send_message(chat_id, self.format_signal(signal))
            else:
                self.send_message(chat_id, self.format_breakdown("BTCUSD", details))

        elif text == "/status":
            # Auto-scan state
            now = datetime.utcnow()
            if self.cooldown_until and now < self.cooldown_until:
                remaining = int((self.cooldown_until - now).total_seconds() / 60)
                scan_status = f"⏸ On cooldown — {remaining}m left (resumes at {self.cooldown_until.strftime('%H:%M UTC')})"
            else:
                scan_status = f"✅ Active — scanning every {SCAN_INTERVAL}s ({self.signals_sent}/{MAX_SIGNALS} signals sent)"

            status_msg = (
                "<b>⚙️ ENGINE XV1 STATUS</b>\n\n"
                "✅ Bot: Online\n"
                "📡 Data: Yahoo Finance\n"
                "🧠 Engine: SMC (v1.0)\n"
                "📊 Pairs: XAUUSD, BTCUSD\n"
                "🎯 Threshold: 7/10\n\n"
                f"<b>🔍 Auto-scan:</b> {scan_status}\n\n"
                "<i>Use /work to manually analyze</i>"
            )
            self.send_message(chat_id, status_msg)

        else:
            self.send_message(chat_id, "👋 Use <b>/work</b> to analyze\n<b>/status</b> to check scanner status")

    # ==========================================
    # MAIN RUN LOOP
    # ==========================================

    def run(self):
        print("🚀 ENGINE XV1 Started")
        print(f"🔍 Auto-scan: every {SCAN_INTERVAL}s | Max {MAX_SIGNALS} signals then {COOLDOWN_HOURS}h cooldown")

        # Start auto-scanner in background thread
        scanner = threading.Thread(target=self.auto_scan, daemon=True)
        scanner.start()

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
