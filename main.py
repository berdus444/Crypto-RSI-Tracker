import os
import json
import requests
import pandas as pd
import numpy as np
import talib as ta
import websocket
import threading
import time
from flask import Flask

# ---------------- CONFIG ----------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
APP_URL = os.getenv("APP_URL")  # Railway veya başka bir yerdeki URL

INTERVAL = "3m"
RSI_PERIOD = 6
RSI_ALERT_THRESHOLD = 92
RSI_RESET_THRESHOLD = 88

latest_data = {}
alerts_status = {}

# ---------------- TELEGRAM ----------------
def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("❌ Telegram bilgileri eksik (.env dosyasını kontrol et)")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        print("Telegram gönderim hatası:", e)

# ---------------- SYMBOL LİSTESİ ----------------
def get_symbols():
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    try:
        data = requests.get(url, timeout=5).json()
        symbols = [
            s["symbol"]
            for s in data["symbols"]
            if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"
        ]
        print(f"💠 {len(symbols)} adet USDT sembolü bulundu.")
        return symbols
    except Exception as e:
        print("Sembol listesi alınamadı:", e)
        return []

# ---------------- BAŞLANGIÇ VERİLERİ ----------------
def get_initial_data(symbol):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={INTERVAL}&limit=100"
    try:
        data = requests.get(url, timeout=5).json()
        closes = [float(x[4]) for x in data]
        return closes
    except Exception:
        return [0.0] * 100

# ---------------- MESAJ ALMA ----------------
def on_message(ws, message, symbol):
    global latest_data, alerts_status
    try:
        data = json.loads(message)
        kline = data["k"]
        close_price = float(kline["c"])
        latest_data[symbol][-1] = close_price

        rsi = ta.RSI(np.array(latest_data[symbol]), timeperiod=RSI_PERIOD)[-1]

        if rsi > RSI_ALERT_THRESHOLD and not alerts_status[symbol]["alerted"]:
            msg = f"⚠️ {symbol} RSI(6) = {rsi:.2f} (> {RSI_ALERT_THRESHOLD})"
            send_telegram_message(msg)
            print(msg)
            alerts_status[symbol]["alerted"] = True

        elif rsi < RSI_RESET_THRESHOLD and alerts_status[symbol]["alerted"]:
            alerts_status[symbol]["alerted"] = False
            print(f"{symbol} resetlendi (RSI < {RSI_RESET_THRESHOLD})")

    except Exception as e:
        print(f"{symbol} veri işleme hatası:", e)

# ---------------- WEBSOCKET ----------------
def start_socket(symbol):
    stream_name = f"{symbol.lower()}@kline_{INTERVAL}"
    ws_url = f"wss://fstream.binance.com/ws/{stream_name}"

    ws = websocket.WebSocketApp(
        ws_url,
        on_message=lambda ws, msg: on_message(ws, msg, symbol),
    )

    while True:
        try:
            ws.run_forever()
        except Exception as e:
            print(f"{symbol} bağlantı hatası: {e}")
            time.sleep(5)

# ---------------- ANA BOT FONKSİYONU ----------------
def run_rsi_tracker():
    global latest_data, alerts_status
    symbols = get_symbols()
    if not symbols:
        print("❌ Sembol listesi alınamadı, çıkılıyor...")
        return

    latest_data = {}
    alerts_status = {s: {"alerted": False} for s in symbols}

    print("📊 Gerçek zamanlı RSI(6) takibi başladı...")

    for symbol in symbols:
        closes = get_initial_data(symbol)
        closes.append(closes[-1])
        latest_data[symbol] = closes
        threading.Thread(target=start_socket, args=(symbol,), daemon=True).start()
        time.sleep(0.15)

    while True:
        time.sleep(10)

# ---------------- FLASK (Railway için keep-alive) ----------------
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ Binance RSI Tracker çalışıyor."

tracker_started = False

def start_tracker():
    global tracker_started
    if not tracker_started:
        tracker_started = True
        print("📡 RSI Tracker başlatılıyor...")
        threading.Thread(target=run_rsi_tracker, daemon=True).start()

# ---------------- SELF-PING (Her 5 dakikada bir) ----------------
def self_ping():
    while True:
        if APP_URL:
            try:
                requests.get(APP_URL, timeout=5)
                print("🔄 Self-ping gönderildi.")
            except Exception as e:
                print("Self-ping hatası:", e)
        time.sleep(600)  # 300 saniye = 5 dakika

# Başlatıcı thread
threading.Thread(target=self_ping, daemon=True).start()

# İlk HTTP isteğinde tracker'ı başlat
@app.before_request
def before_request():
    start_tracker()

if __name__ == "__main__":
    start_tracker()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))


