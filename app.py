# app.py (FINAL PRODUCTION VERSION)
# ---------------------------------------------------------
# IMPORTS
# ---------------------------------------------------------
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Stock, Alert
import requests 
import yfinance as yf 
import json
import os
import time # Needed for caching
import feedparser
import urllib.parse

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key-change-this-in-prod'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize Extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))

# ---------------------------------------------------------
# GLOBAL CACHES
# ---------------------------------------------------------
MARKET_LIST = []
STOCK_DETAILS_CACHE = {} # Stores deep dive data
CACHE_DURATION = 300 # 5 Minutes cache for stock details

def load_market_data():
    """Loads the FULL NSE Master List from local JSON on startup."""
    global MARKET_LIST
    try:
        if os.path.exists('market_data.json'):
            with open('market_data.json', 'r') as f:
                MARKET_LIST = json.load(f)
            print(f"--- ✅ Loaded {len(MARKET_LIST)} stocks from 'market_data.json' ---")
        elif os.path.exists('nifty500.json'):
            with open('nifty500.json', 'r') as f:
                MARKET_LIST = json.load(f)
            print(f"--- ⚠️ Loaded Backup: {len(MARKET_LIST)} stocks from 'nifty500.json' ---")
        else:
            print("--- ❌ No stock list found. Search will be manual only. ---")
    except Exception as e:
        print(f"--- ❌ Error loading JSON: {e} ---")

# Load data when app starts
with app.app_context():
    db.create_all()
    from sqlalchemy import text
    with db.engine.connect() as con:
        con.execute(text("PRAGMA journal_mode=WAL;"))
    
    load_market_data()

# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------
def get_portfolio_data(user_id):
    """Calculates detailed portfolio stats including Daily P&L."""
    stocks = Stock.query.filter_by(user_id=user_id).all()
    data = []
    total_invested = 0
    current_value = 0
    daily_pnl = 0 
    
    for s in stocks:
        live_price = s.current_price if s.current_price > 0 else s.buy_price
        prev_close = s.previous_close if s.previous_close > 0 else s.buy_price 
        
        val = live_price * s.quantity
        cost = s.buy_price * s.quantity
        
        pnl = val - cost
        pnl_pct = (pnl / cost * 100) if cost > 0 else 0
        
        day_change = (live_price - prev_close) * s.quantity
        daily_pnl += day_change
        
        total_invested += cost
        current_value += val
        
        data.append({
            'id': s.id,
            'symbol': s.symbol,
            'qty': s.quantity,
            'buy': s.buy_price,
            'price': round(live_price, 2),
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct, 2)
        })
        
    return data, round(total_invested, 2), round(current_value, 2), round(daily_pnl, 2)

# ---------------------------------------------------------
# ROUTES: DASHBOARD & HTMX
# ---------------------------------------------------------
@app.route('/')
@login_required
def dashboard():
    _, invested, value, daily_pnl = get_portfolio_data(current_user.id)
    total_pnl = value - invested
    
    return render_template('dashboard.html', 
                           invested=invested, 
                           value=value, 
                           pnl=round(total_pnl, 2),
                           daily_pnl=daily_pnl,
                           nifty_stocks=MARKET_LIST) 

@app.route('/htmx/stats')
@login_required
def htmx_stats():
    """Returns ONLY the numbers to update specific IDs (No Flash OOB Swap)"""
    _, invested, value, daily_pnl = get_portfolio_data(current_user.id)
    total_pnl = value - invested
    return render_template('partials/stats_oob.html', 
                           invested=invested, 
                           value=value, 
                           pnl=round(total_pnl, 2),
                           daily_pnl=daily_pnl)

@app.route('/htmx/rows')
@login_required
def htmx_rows():
    """Returns the Stock Table Rows"""
    data, _, _, _ = get_portfolio_data(current_user.id)
    return render_template('partials/stock_rows.html', stocks=data)

# app.py (PARTIAL UPDATE - Replace the stock_details route)

@app.route('/htmx/stock_details/<symbol>')
@login_required
def stock_details(symbol):
    try:
        current_time = time.time()
        
        # 1. CHECK CACHE (Reduce duration to 60s for "Live" feel)
        if symbol in STOCK_DETAILS_CACHE:
            cached_entry = STOCK_DETAILS_CACHE[symbol]
            if current_time - cached_entry['timestamp'] < 60: # 1 Minute Cache
                print(f"--- ⚡ Serving {symbol} from Cache ---")
                return render_template('partials/stock_details_modal.html', stock=cached_entry['data'])

        # 2. FETCH LIVE INTRADAY DATA
        print(f"--- 📡 Fetching Intraday data for {symbol}... ---")
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        # Fetch 1 Day of data with 5-minute intervals
        history = ticker.history(period="1d", interval="5m")
        
        # Fallback for weekends/holidays: If today is empty, get last 5 days
        if history.empty:
            history = ticker.history(period="5d", interval="60m")

        # Process Chart Data (Time Format: HH:MM)
        # We convert to IST (approx) by just taking the string time from the index
        chart_labels = [date.strftime('%H:%M') for date in history.index]
        chart_prices = [round(price, 2) for price in history['Close'].tolist()]

        details = {
            "name": info.get('longName', symbol),
            "symbol": symbol,
            "sector": info.get('sector', 'Equity'),
            "current_price": info.get('currentPrice', info.get('regularMarketPrice', 0)),
            
            # Ranges
            "day_high": info.get('dayHigh', 0),
            "day_low": info.get('dayLow', 0),
            "prev_close": info.get('previousClose', 0),
            "volume": info.get('volume', 0),
            "year_high": info.get('fiftyTwoWeekHigh', 0),
            "year_low": info.get('fiftyTwoWeekLow', 0),
            
            # Valuation
            "market_cap": info.get('marketCap', 0),
            "pe_ratio": info.get('trailingPE', 0),
            "dividend_yield": info.get('dividendYield', 0) * 100 if info.get('dividendYield') else 0,
            
            # INTRADAY CHART DATA
            "chart_labels": chart_labels,
            "chart_prices": chart_prices
        }
        
        # Format Market Cap
        mc = details['market_cap']
        if mc > 10**12: details['fmt_market_cap'] = f"₹{round(mc/10**12, 2)}T"
        elif mc > 10**7: details['fmt_market_cap'] = f"₹{round(mc/10**7, 2)} Cr"
        else: details['fmt_market_cap'] = f"₹{mc}"

        # 3. SAVE TO CACHE
        STOCK_DETAILS_CACHE[symbol] = {
            "data": details,
            "timestamp": current_time
        }

        return render_template('partials/stock_details_modal.html', stock=details)

    except Exception as e:
        print(f"Error fetching details: {e}")
        return f"<div class='p-8 text-center text-red-500 font-bold'>Error fetching data. Please try again later.</div>"

@app.route('/api/chart_data')
@login_required
def chart_data():
    """Returns JSON data for the Portfolio Doughnut Chart"""
    stocks, _, value, _ = get_portfolio_data(current_user.id)
    labels = [s['symbol'] for s in stocks]
    data_points = [round((s['price'] * s['qty']), 2) for s in stocks]
    return jsonify({
        'labels': labels,
        'data': data_points,
        'total_value': value
    })

# --- NEW ROUTE: PORTFOLIO NEWS ---
@app.route('/htmx/news')
@login_required
def portfolio_news():
    try:
        # 1. Get User's Stocks
        stocks = Stock.query.filter_by(user_id=current_user.id).all()
        if not stocks:
            return "<div class='text-gray-400 text-sm text-center p-4'>Add stocks to see relevant news.</div>"

        # 2. Identify Top 3 Holdings
        stocks.sort(key=lambda s: s.quantity * (s.current_price if s.current_price > 0 else s.buy_price), reverse=True)
        top_stocks = stocks[:3] 

        all_news = []
        print(f"--- 📰 Fetching News for: {[s.symbol for s in top_stocks]} ---")

        for stock in top_stocks:
            # CLEAN SYMBOL: Remove .NS for better Google News results
            clean_symbol = stock.symbol.replace('.NS', '').replace('.BO', '')
            
            # --- STRATEGY A: Google News RSS (More Reliable for India) ---
            try:
                # We search for "Stock Name + Share Price" to get financial news
                query = urllib.parse.quote(f"{clean_symbol} share news india")
                rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
                
                feed = feedparser.parse(rss_url)
                
                for entry in feed.entries[:2]: # Get top 2
                    # Google RSS doesn't give images easily, so we use a fallback icon
                    published_parsed = entry.published_parsed
                    timestamp = time.mktime(published_parsed) if published_parsed else time.time()
                    
                    # Time formatting
                    time_diff = int(time.time() - timestamp)
                    if time_diff < 3600: time_str = f"{int(time_diff/60)}m ago"
                    elif time_diff < 86400: time_str = f"{int(time_diff/3600)}h ago"
                    else: time_str = f"{int(time_diff/86400)}d ago"

                    all_news.append({
                        'symbol': stock.symbol,
                        'title': entry.title,
                        'publisher': entry.source.title if hasattr(entry, 'source') else 'Google News',
                        'link': entry.link,
                        'time': time_str,
                        'timestamp': timestamp,
                        'thumbnail': None # We will handle None in template
                    })
                    
            except Exception as e:
                print(f"RSS Failed for {stock.symbol}: {e}")
                
                # --- STRATEGY B: Fallback to Yahoo Finance (If RSS fails) ---
                try:
                    ticker = yf.Ticker(stock.symbol)
                    news_items = ticker.news
                    for item in news_items[:2]:
                        publish_time = item.get('providerPublishTime', 0)
                        all_news.append({
                            'symbol': stock.symbol,
                            'title': item.get('title'),
                            'publisher': item.get('publisher'),
                            'link': item.get('link'),
                            'time': "Recent",
                            'timestamp': publish_time,
                            'thumbnail': item.get('thumbnail', {}).get('resolutions', [{}])[0].get('url')
                        })
                except:
                    pass

        # 3. Sort & Dedup
        # Remove duplicates based on title
        seen_titles = set()
        unique_news = []
        for news in all_news:
            if news['title'] not in seen_titles:
                unique_news.append(news)
                seen_titles.add(news['title'])

        unique_news.sort(key=lambda x: x['timestamp'], reverse=True)
        return render_template('partials/news_feed.html', news_list=unique_news[:6])

    except Exception as e:
        print(f"News Error: {e}")
        return "<div class='text-red-400 text-sm p-4 text-center'>News feed temporarily unavailable.</div>"

# ---------------------------------------------------------
# ROUTES: ACTIONS
# ---------------------------------------------------------
@app.route('/add_stock', methods=['POST'])
@login_required
def add_stock():
    symbol = request.form.get('symbol').upper()
    if not symbol.endswith('.NS') and not symbol.endswith('.BO'):
        symbol += '.NS'
    
    new_stock = Stock(
        symbol=symbol, 
        buy_price=float(request.form.get('price')), 
        quantity=float(request.form.get('qty')),
        current_price=0.0,      
        previous_close=0.0,     
        user_id=current_user.id
    )
    db.session.add(new_stock)
    db.session.commit()
    flash(f"Added {symbol}")
    return redirect(url_for('dashboard'))

@app.route('/delete_stock/<int:stock_id>', methods=['POST'])
@login_required
def delete_stock(stock_id):
    stock = Stock.query.get_or_404(stock_id)
    if stock.user_id == current_user.id:
        db.session.delete(stock)
        db.session.commit()
        flash(f"Removed {stock.symbol}")
    return redirect(url_for('dashboard'))

@app.route('/set_alert', methods=['POST'])
@login_required
def set_alert():
    symbol = request.form.get('symbol').upper()
    symbol = symbol.strip()
    if not symbol.endswith('.NS') and not symbol.endswith('.BO'):
        symbol += '.NS'

    target = float(request.form.get('target'))
    manual_condition = request.form.get('condition')
    
    current_price = 0
    stock = Stock.query.filter_by(user_id=current_user.id, symbol=symbol).first()
    
    if stock and stock.current_price > 0:
        current_price = stock.current_price
    else:
        try:
            ticker = yf.Ticker(symbol)
            data = ticker.history(period="1d")
            if not data.empty:
                current_price = data['Close'].iloc[-1]
        except:
            current_price = target 

    condition = "ABOVE" 
    if manual_condition == "AUTO":
        if current_price > target:
            condition = "BELOW"
    else:
        condition = manual_condition
    
    new_alert = Alert(symbol=symbol, target_price=target, condition=condition, user_id=current_user.id)
    db.session.add(new_alert)
    db.session.commit()
    
    flash(f"Alert set: {symbol} {condition} {target}")
    return redirect(url_for('alerts_page'))

@app.route('/delete_alert/<int:alert_id>', methods=['POST'])
@login_required
def delete_alert(alert_id):
    alert = Alert.query.get_or_404(alert_id)
    if alert.user_id == current_user.id:
        db.session.delete(alert)
        db.session.commit()
    return redirect(url_for('alerts_page'))

# ---------------------------------------------------------
# ROUTES: SETTINGS ACTIONS
# ---------------------------------------------------------
@app.route('/update_telegram', methods=['POST'])
@login_required
def update_telegram():
    current_user.telegram_chat_id = request.form.get('chat_id')
    db.session.commit()
    flash("Telegram ID Updated")
    return redirect(url_for('settings_page'))

@app.route('/test_telegram', methods=['POST'])
@login_required
def test_telegram():
    token = "8566308729:AAHo8FVGyur2icKIGjVcfKKcWQwi2w14Ijc" 
    chat_id = current_user.telegram_chat_id
    if not chat_id:
        flash("Save Chat ID first!")
        return redirect(url_for('settings_page'))
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": "🔔 Narad Muni here! Connection Successful."})
        if resp.status_code == 200:
            flash("Message sent! Check your Telegram.")
        else:
            flash(f"Failed: {resp.text}")
    except Exception as e:
        flash(f"Error: {e}")
    return redirect(url_for('settings_page'))

@app.route('/delete_account', methods=['POST'])
@login_required
def delete_account():
    user = User.query.get(current_user.id)
    Stock.query.filter_by(user_id=user.id).delete()
    Alert.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    logout_user()
    return redirect(url_for('login'))

# ---------------------------------------------------------
# AUTH ROUTES
# ---------------------------------------------------------
@app.route('/alerts')
@login_required
def alerts_page():
    user_alerts = Alert.query.filter_by(user_id=current_user.id).all()
    return render_template('alerts.html', alerts=user_alerts)

@app.route('/settings')
@login_required
def settings_page():
    return render_template('settings.html', user=current_user)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password_hash, request.form.get('password')):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        hashed_pw = generate_password_hash(request.form.get('password'), method='scrypt')
        new_user = User(username=request.form.get('username'), password_hash=hashed_pw)
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        return redirect(url_for('dashboard'))
    return render_template('login.html', is_signup=True)

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)