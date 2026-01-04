# fetch_market.py (BATTLESHIP EDITION: 40+ ALIASES)
import requests
import pandas as pd
import io
import json

# 1. THE OFFICIAL SOURCE
URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"

# 2. THE BRAIN: Manually Mapped "Confusing" Stocks 🧠
# NSE Name (Legal) -> What Humans Call It
ALIAS_MAP = {
    # --- NEW AGE TECH / STARTUPS ---
    "PAYTM": "Paytm (One 97)",
    "NYKAA": "Nykaa (FSN E-Commerce)",
    "ZOMATO": "Zomato",
    "POLICYBZR": "PolicyBazaar (PB Fintech)",
    "DELHIVERY": "Delhivery",
    "CARTRADE": "CarTrade",
    "NAUKRI": "Naukri (Info Edge)",
    "EASEMYTRIP": "EaseMyTrip (Easy Trip)",
    "MAPMYINDIA": "MapMyIndia (C.E. Info)",
    "RATEGAIN": "RateGain Travel",
    "IDEAFORGE": "ideaForge Drones",
    "HONASA": "Mamaearth (Honasa)",
    "YATHARTH": "Yatharth Hospitals",
    "NETWEB": "Netweb Technologies",
    "SENCO": "Senco Gold",
    "CYIENTDLM": "Cyient DLM",
    "IKIO": "IKIO Lighting",
    "KFINTECH": "KFin Tech",
    "ELIN": "Elin Electronics",
    "LANDMARK": "Landmark Cars",
    "SULA": "Sula Vineyards",
    "DREAMFOLKS": "DreamFolks Services",
    "SYRMA": "Syrma SGS",
    "CAMPUS": "Campus Shoes",
    "RAINBOW": "Rainbow Hospitals",
    
    # --- OLD GIANTS / REBRANDS ---
    "M&M": "Mahindra & Mahindra",
    "BAJFINANCE": "Bajaj Finance",
    "BAJAJFINSV": "Bajaj Finserv",
    "SAIL": "Steel Authority of India",
    "TATAMOTORS": "Tata Motors",
    "TATASTEEL": "Tata Steel",
    "TITAN": "Titan Company (Tanishq/Fastrack)",
    "ASIANPAINT": "Asian Paints",
    "BRITANNIA": "Britannia Industries",
    "HINDUNILVR": "HUL (Hindustan Unilever)",
    "NESTLEIND": "Nestle India (Maggi)",
    "MARUTI": "Maruti Suzuki",
    "HEROMOTOCO": "Hero Motocorp",
    "EICHERMOT": "Eicher Motors (Royal Enfield)",
    "MOTHERSON": "Motherson Sumi",
    "JUBLFOOD": "Jubilant (Domino's Pizza)",
    "WESTLIFE": "Westlife (McDonald's)",
    "DEVYANI": "Devyani (KFC/Pizza Hut)",
    "SAPPHIRE": "Sapphire Foods (KFC/Pizza Hut)",
    "PAGEIND": "Page Industries (Jockey)",
    "ABFRL": "Aditya Birla Fashion (Pantaloons)",
    "TRENT": "Trent (Westside/Zudio)",
    "DMART": "DMart (Avenue Supermarts)",
    "VBL": "Varun Beverages (Pepsi)",
    "IRCTC": "IRCTC (Indian Railways)",
    "HAL": "HAL (Hindustan Aeronautics)",
    "BEL": "Bharat Electronics",
    "BHEL": "BHEL (Bharat Heavy Electricals)"
}

print(f"--- 📡 Connecting to NSE Archives... ---")

try:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    response = requests.get(URL, headers=headers)
    
    if response.status_code == 200:
        print("--- ✅ Download Successful. Parsing... ---")
        
        csv_data = io.StringIO(response.content.decode('utf-8'))
        df = pd.read_csv(csv_data)
        
        # Filter for Equity only
        df = df[df[' SERIES'].isin(['EQ', 'BE'])]
        
        stock_list = []
        
        for index, row in df.iterrows():
            symbol = row['SYMBOL']
            legal_name = row['NAME OF COMPANY']
            
            # 1. Format Symbol for Yahoo Finance
            yf_symbol = f"{symbol}.NS"
            
            # 2. Smart Naming Logic 🧠
            # Default to legal name
            display_name = legal_name.title().replace(" Limited", "").replace(" Ltd", "").replace(" (India)", "")
            
            # If we know this stock (it's in our map), OVERRIDE or APPEND the common name
            if symbol in ALIAS_MAP:
                common_name = ALIAS_MAP[symbol]
                
                # If the common name is totally different (e.g. One 97 vs Paytm), use the common name
                # This ensures searching "Paytm" shows "Paytm (One 97)"
                display_name = common_name
            
            # 3. Add to list
            stock_list.append({
                "symbol": yf_symbol,
                "name": display_name
            })
            
        # 4. Save to JSON
        with open('market_data.json', 'w') as f:
            json.dump(stock_list, f, indent=4)
            
        print(f"--- 🚀 SUCCESS! Saved {len(stock_list)} stocks. ---")
        print(f"--- Try searching for 'Domino's', 'Jockey', 'Maggi', or 'Paytm'! ---")
        
    else:
        print(f"--- ❌ Download Failed. Status: {response.status_code} ---")

except Exception as e:
    print(f"--- ⚠️ ERROR: {e} ---")