# monitor.py (DAILY P&L + ALERTS)
import time
import sqlite3
import requests
import yfinance as yf
from datetime import datetime, timedelta, timezone, time as dt_time
import pandas as pd

# --- CONFIGURATION ---
DB_PATH = "instance/database.db"
TELEGRAM_BOT_TOKEN = "YOUR-TELEGRAM-BOT-TOKEN"
TEST_MODE = False 

# --- CONSTANTS ---
MARKET_OPEN = dt_time(9, 15)
MARKET_CLOSE = dt_time(15, 30)
COOLDOWN_SECONDS = 120 

def get_ist_time():
    return datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)

def send_telegram_msg(chat_id, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=10)
    except: pass

def update_prices_and_alerts():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    print(f"--- 🧘 Narad Muni Started (Tracking Daily Change) ---")
    
    while True:
        try:
            now_ist = get_ist_time()
            if TEST_MODE:
                market_is_open = True
            else:
                is_weekend = now_ist.weekday() >= 5
                current_time = now_ist.time()
                market_is_open = (not is_weekend) and (MARKET_OPEN <= current_time <= MARKET_CLOSE)

            cursor.execute("SELECT COUNT(*) FROM stock WHERE current_price = 0")
            missing_data_count = cursor.fetchone()[0]
            should_fetch = market_is_open or (missing_data_count > 0)

            if should_fetch:
                cursor.execute("SELECT DISTINCT symbol FROM stock")
                symbols = [row[0] for row in cursor.fetchall()]
                
                if symbols:
                    try:
                        # FETCH 5 DAYS (To safely get previous close)
                        # We need >1 day to know yesterday's close
                        data = yf.download(symbols, period="5d", interval="1d", progress=False)
                        
                        # We also fetch live price separately for precision if needed, 
                        # but '1d' interval data['Close'][-1] is usually current price.
                        # For better live accuracy, let's stick to your old live fetch method,
                        # BUT we extract 'previous_close' from this history data.
                        
                        prev_closes = {}
                        current_prices = {}

                        # Extract Data
                        if len(symbols) == 1:
                            # Single Stock Logic
                            try:
                                df = data
                                if not df.empty:
                                    # Current Price = Last Row Close
                                    current_prices[symbols[0]] = df['Close'].iloc[-1].item()
                                    # Prev Close = Second Last Row Close (if exists)
                                    if len(df) >= 2:
                                        prev_closes[symbols[0]] = df['Close'].iloc[-2].item()
                                    else:
                                        prev_closes[symbols[0]] = df['Open'].iloc[-1].item() # Fallback
                            except: pass
                        else:
                            # Multi Stock Logic
                            for sym in symbols:
                                try:
                                    series = data['Close'][sym].dropna()
                                    if not series.empty:
                                        current_prices[sym] = series.iloc[-1]
                                        if len(series) >= 2:
                                            prev_closes[sym] = series.iloc[-2]
                                        else:
                                            prev_closes[sym] = current_prices[sym] # Fallback
                                except: pass

                        # Update DB
                        alert_count = 0
                        for sym, price in current_prices.items():
                            p_close = prev_closes.get(sym, price) # Default to current if missing
                            
                            cursor.execute("UPDATE stock SET current_price = ?, previous_close = ?, last_updated = ? WHERE symbol = ?", 
                                           (float(price), float(p_close), datetime.now(), sym))
                            
                            # --- ALERTS (Same as before) ---
                            cursor.execute("""
                                SELECT a.id, a.target_price, a.condition, a.last_triggered, u.telegram_chat_id 
                                FROM alert a
                                JOIN user u ON a.user_id = u.id
                                WHERE a.symbol = ? AND a.is_active = 1 AND u.telegram_chat_id IS NOT NULL
                            """, (sym,))
                            
                            for alert in cursor.fetchall():
                                a_id, target, cond, last_trig, chat_id = alert
                                triggered = False
                                if cond == "ABOVE" and price >= target: triggered = True
                                if cond == "BELOW" and price <= target: triggered = True
                                
                                if triggered:
                                    can_send = True
                                    if last_trig:
                                        last_time = datetime.strptime(last_trig, '%Y-%m-%d %H:%M:%S.%f')
                                        if (datetime.now() - last_time).total_seconds() < COOLDOWN_SECONDS:
                                            can_send = False
                                    
                                    if can_send:
                                        msg = f"Narayan... Narayan... 🙏\n\nPrabhu, {sym} is moving!\n✨ Price: ₹{price:.2f} (Target: {target})\n\nJay Ho! 🕉️"
                                        send_telegram_msg(chat_id, msg)
                                        cursor.execute("UPDATE alert SET last_triggered = ? WHERE id = ?", (datetime.now(), a_id))
                                        alert_count += 1

                        conn.commit()
                        print(f"✅ Live Update: {len(current_prices)} stocks. Alerts: {alert_count}", end='\r')

                    except Exception as e:
                        print(f"\n⚠️ Fetch Error: {e}")
                
                time.sleep(10) # 1d interval doesn't need 2s polling. 10s is plenty fast.

            else:
                print(f"💤 Sleeping...", end='\r')
                time.sleep(10)

        except Exception as e:
            print(f"\nCRITICAL ERROR: {e}")
            time.sleep(5)

if __name__ == "__main__":
    update_prices_and_alerts()
