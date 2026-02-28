import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Market Heatmap", page_icon="📊", layout="wide")

# --- 2. AUTO RUN (1 MINUTE) ---
st_autorefresh(interval=60000, key="datarefresh")

# --- 3. STATE MANAGEMENT FOR FILTERING & PINNING ---
if 'trend_filter' not in st.session_state: st.session_state.trend_filter = 'All'
if 'pinned_stocks' not in st.session_state: st.session_state.pinned_stocks = []

def toggle_pin(symbol):
    if symbol in st.session_state.pinned_stocks: st.session_state.pinned_stocks.remove(symbol)
    else: st.session_state.pinned_stocks.append(symbol)

# --- PORTFOLIO FILE SETUP (HARDCODED FOR CLOUD SAFETY) ---
PORTFOLIO_FILE = "my_portfolio.csv"
def load_portfolio():
    default_data = [
        {"Symbol": "APLAPOLLO", "Buy_Price": 2262.20, "Quantity": 1, "Date": "-"},
        {"Symbol": "CGPOWER", "Buy_Price": 667.00, "Quantity": 10, "Date": "-"},
        {"Symbol": "HDFCBANK", "Buy_Price": 949.27, "Quantity": 4, "Date": "-"},
        {"Symbol": "ITC", "Buy_Price": 310.35, "Quantity": 20, "Date": "-"},
        {"Symbol": "KALYANKJIL", "Buy_Price": 437.18, "Quantity": 11, "Date": "-"},
        {"Symbol": "KPRMILL", "Buy_Price": 979.00, "Quantity": 1, "Date": "-"},
        {"Symbol": "VBL", "Buy_Price": 438.30, "Quantity": 5, "Date": "-"},
        {"Symbol": "ZYDUSLIFE", "Buy_Price": 905.70, "Quantity": 2, "Date": "-"}
    ]
    default_df = pd.DataFrame(default_data)
    if os.path.exists(PORTFOLIO_FILE):
        try:
            df = pd.read_csv(PORTFOLIO_FILE)
            if not df.empty:
                df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce').fillna(1).astype(int)
                df['Buy_Price'] = pd.to_numeric(df['Buy_Price'], errors='coerce').fillna(0.0).astype(float)
                df['Symbol'] = df['Symbol'].astype(str).replace('nan', '')
                return df
        except: pass
    default_df.to_csv(PORTFOLIO_FILE, index=False)
    return default_df

def save_portfolio(df_port): df_port.to_csv(PORTFOLIO_FILE, index=False)

# --- 4. CSS FOR STYLING ---
st.markdown("""
<style>
#MainMenu, footer, header {visibility: hidden; display: none !important;}
.stApp { background-color: #0e1117; color: #ffffff; }
.block-container { padding-top: 1rem !important; padding-bottom: 0rem !important; margin-top: -10px; }
.stRadio label, .stRadio p, div[role="radiogroup"] p { color: #ffffff !important; font-weight: normal !important; }
div.stButton > button p { color: #ffffff !important; font-weight: normal !important; font-size: 14px !important; }
.t-name { font-size: 13px; font-weight: normal !important; margin-bottom: 2px; }
.t-price { font-size: 17px; font-weight: normal !important; margin-bottom: 2px; }
.t-pct { font-size: 12px; font-weight: normal !important; }
.t-score { position: absolute; top: 3px; left: 3px; font-size: 10px; background: rgba(0,0,0,0.4); padding: 1px 4px; border-radius: 3px; color: #ffd700; font-weight: normal !important; }
div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) { display: flex !important; flex-direction: row !important; gap: 6px !important; width: 100% !important; }
div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) > div { flex: 1 1 0px !important; }
div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) div.stButton > button { width: 100% !important; height: 38px !important; }
div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { display: grid !important; gap: 12px !important; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)) !important; }
div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div:nth-child(1) { display: none !important; }
div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div[data-testid="stVerticalBlock"] { background-color: #161b22 !important; border: 1px solid #30363d !important; border-radius: 8px !important; padding: 8px 5px !important; position: relative !important; }
div[data-testid="stCheckbox"] { position: absolute !important; top: 8px !important; left: 10px !important; z-index: 100 !important; }
.heatmap-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; padding: 5px 0; }
.stock-card { border-radius: 4px; padding: 8px 4px; text-align: center; color: white !important; display: flex; flex-direction: column; justify-content: center; height: 90px; position: relative; box-shadow: 0 1px 3px rgba(0,0,0,0.3); transition: transform 0.2s; text-decoration: none !important; }
.stock-card:hover { transform: scale(1.05); z-index: 10; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }
.bull-card { background-color: #1e5f29 !important; } .bear-card { background-color: #b52524 !important; } .neut-card { background-color: #30363d !important; } 
.idx-card { background-color: #0d47a1 !important; border: 1px solid #1976d2; } 
.custom-hr { border: 0; height: 1px; background: #30363d; margin: 15px 0; }
.term-table { width: 100%; border-collapse: collapse; margin-bottom: 15px; font-family: monospace; font-size: 11.5px; color: #e6edf3; background-color: #0e1117; table-layout: fixed; }
.term-table th, .term-table td { padding: 6px 4px; text-align: center; border: 1px solid #30363d; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.term-table a { color: inherit; text-decoration: none; border-bottom: 1px dashed rgba(255,255,255,0.4); } .term-table a:hover { color: #58a6ff !important; border-bottom: 1px solid #58a6ff; } 
.term-head-buy { background-color: #1e5f29; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
.term-head-sell { background-color: #b52524; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
.term-head-ind, .term-head-brd { background-color: #0d47a1; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
.term-head-port { background-color: #4a148c; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
.term-head-swing, .term-head-levels { background-color: #005a9e; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
.term-head-high { background-color: #b71c1c; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
.row-dark { background-color: #161b22; } .row-light { background-color: #0e1117; }
.text-green { color: #3fb950; font-weight: bold; } .text-red { color: #f85149; font-weight: bold; }
.t-symbol { text-align: left !important; font-weight: bold; }
.port-total { background-color: #21262d; font-weight: bold; font-size: 13px; }
</style>
""", unsafe_allow_html=True)

# --- 5. CONSTANTS ---
INDICES_MAP = {"^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY", "^INDIAVIX": "INDIA VIX"}
TV_INDICES_URL = {"^NSEI": "NSE:NIFTY", "^NSEBANK": "NSE:BANKNIFTY", "^INDIAVIX": "NSE:INDIAVIX"}
SECTOR_INDICES_MAP = {"^CNXIT": "NIFTY IT", "^CNXAUTO": "NIFTY AUTO", "^CNXMETAL": "NIFTY METAL", "^CNXPHARMA": "NIFTY PHARMA", "^CNXFMCG": "NIFTY FMCG", "^CNXENERGY": "NIFTY ENERGY", "^CNXREALTY": "NIFTY REALTY"}
TV_SECTOR_URL = {"^CNXIT": "NSE:CNXIT", "^CNXAUTO": "NSE:CNXAUTO", "^CNXMETAL": "NSE:CNXMETAL", "^CNXPHARMA": "NSE:CNXPHARMA", "^CNXFMCG": "NSE:CNXFMCG", "^CNXENERGY": "NSE:CNXENERGY", "^CNXREALTY": "NSE:CNXREALTY"}

NIFTY_50_SECTORS = {
    "PHARMA": ["SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", "APOLLOHOSP"],
    "IT": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM"],
    "BANK": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK"],
    "ENERGY": ["RELIANCE", "ONGC", "NTPC", "POWERGRID", "COALINDIA", "BPCL"],
    "AUTO": ["TATAMOTORS", "M&M", "MARUTI", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO"],
    "METAL": ["TATASTEEL", "JSWSTEEL", "HINDALCO"],
    "FMCG": ["ITC", "HINDUNILVR", "NESTLEIND", "BRITANNIA", "TATACONSUM"]
}
NIFTY_50 = [stock for sec in NIFTY_50_SECTORS.values() for stock in sec] + ["LARSEN", "BAJFINANCE", "ASIANPAINT", "TITAN", "ADANIENT"]
BROADER_MARKET = ["HAL", "BDL", "MAZDOCK", "RVNL", "IRFC", "BHEL", "CGPOWER", "SUZLON", "PFC", "RECLTD", "DIXON", "POLYCAB", "KAYNES", "ZOMATO", "DMART", "MANAPPURAM", "MUTHOOTFIN", "KEI", "APLAPOLLO"]

def get_minutes_passed():
    now = datetime.now()
    if now.weekday() >= 5 or now.time() > dt_time(15, 30): return 375
    open_time = now.replace(hour=9, minute=15, second=0)
    return min(375, max(1, int((now - open_time).total_seconds() / 60)))

@st.cache_data(ttl=60)
def fetch_all_data():
    port_df = load_portfolio()
    port_stocks = [str(sym).upper().strip() for sym in port_df['Symbol'].tolist() if str(sym).strip() != ""]
    all_stocks = set(NIFTY_50 + BROADER_MARKET + port_stocks)
    tkrs = list(INDICES_MAP.keys()) + list(SECTOR_INDICES_MAP.keys()) + [f"{t}.NS" for t in all_stocks if t]
    
    # 🔥 FIX: Reduced threads to 5 so Streamlit Cloud doesn't drop index data
    data = yf.download(tkrs, period="1y", progress=False, group_by='ticker', threads=5)
    if data.empty or (isinstance(data.columns, pd.Index) and not isinstance(data.columns, pd.MultiIndex)): 
        return pd.DataFrame() # Safe exit if Yahoo fails
        
    results, minutes = [], get_minutes_passed()
    nifty_dist = 0.1
    if "^NSEI" in data.columns.levels[0]:
        try:
            n_df = data["^NSEI"].dropna(subset=['Close'])
            if not n_df.empty:
                n_ltp = float(n_df['Close'].iloc[-1])
                n_vwap = (float(n_df['High'].iloc[-1]) + float(n_df['Low'].iloc[-1]) + n_ltp) / 3
                if n_vwap > 0: nifty_dist = abs(n_ltp - n_vwap) / n_vwap * 100
        except: pass

    for symbol in data.columns.levels[0]:
        try:
            df = data[symbol].dropna(subset=['Close'])
            if len(df) < 2: continue
            
            ltp, open_p = float(df['Close'].iloc[-1]), float(df['Open'].iloc[-1])
            prev_c, prev_h, prev_l = float(df['Close'].iloc[-2]), float(df['High'].iloc[-2]), float(df['Low'].iloc[-2])
            low, high = float(df['Low'].iloc[-1]), float(df['High'].iloc[-1])
            day_chg, net_chg = ((ltp - open_p) / open_p) * 100, ((ltp - prev_c) / prev_c) * 100
            pivot = (prev_h + prev_l + prev_c) / 3
            
            vol_x = 0.0
            if 'Volume' in df.columns and len(df) >= 6:
                avg_vol_5d, curr_vol = df['Volume'].iloc[-6:-1].mean(), float(df['Volume'].iloc[-1])
                if avg_vol_5d > 0: vol_x = round(curr_vol / ((avg_vol_5d/375) * minutes), 1)
                
            vwap = (high + low + ltp) / 3
            is_swing = False
            if len(df) >= 50:
                e20, e50 = df['Close'].ewm(span=20, adjust=False).mean().iloc[-1], df['Close'].ewm(span=50, adjust=False).mean().iloc[-1]
                delta = df['Close'].diff()
                gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
                loss = -delta.clip(upper=0).ewm(alpha=1/14, adjust=False).mean().replace(0, np.nan)
                current_rsi = (100 - (100 / (1 + (gain / loss)))).fillna(100).iloc[-1]
                v_brk = curr_vol > (1.2 * df['Volume'].iloc[-11:-1].mean()) if len(df) >= 11 else False
                if (ltp > e50) and (e20 > e50) and (current_rsi >= 55) and v_brk and (net_chg > 0): is_swing = True

            score = 0
            stock_dist = abs(ltp - vwap) / vwap * 100 if vwap > 0 else 0
            if stock_dist > (nifty_dist * 3): score += 5
            elif stock_dist > (nifty_dist * 2): score += 3
            
            if abs(open_p - low) <= (ltp * 0.003) or abs(open_p - high) <= (ltp * 0.003): score += 3 
            if vol_x > 1.0: score += 3 
            if (ltp >= high * 0.998 and day_chg > 0.5) or (ltp <= low * 1.002 and day_chg < -0.5): score += 1
            if (ltp > (low * 1.01) and ltp > vwap) or (ltp < (high * 0.99) and ltp < vwap): score += 1
            
            is_index, is_sector = symbol in INDICES_MAP, symbol in SECTOR_INDICES_MAP
            disp_name = INDICES_MAP.get(symbol, SECTOR_INDICES_MAP.get(symbol, symbol.replace(".NS", "")))
            stock_sector = next((sec for sec, stocks in NIFTY_50_SECTORS.items() if disp_name in stocks), "OTHER")
                
            results.append({
                "Fetch_T": symbol, "T": disp_name, "P": ltp, "O": open_p, "H": high, "L": low, "Prev_C": prev_c,
                "Day_C": day_chg, "C": net_chg, "S": score, "VolX": vol_x, "Is_Swing": is_swing,
                "Pivot": pivot, "R1": (2*pivot)-prev_l, "R2": pivot+(prev_h-prev_l), "S1": (2*pivot)-prev_h, "S2": pivot-(prev_h-prev_l),
                "Is_Index": is_index, "Is_Sector": is_sector, "Sector": stock_sector
            })
        except: continue
    return pd.DataFrame(results)

def process_5m_data(df_raw):
    try:
        df_s = df_raw.dropna(subset=['Close']).copy()
        if df_s.empty: return pd.DataFrame()
        df_s['EMA_10'] = df_s['Close'].ewm(span=10, adjust=False).mean()
        df_s.index = pd.to_datetime(df_s.index)
        df_day = df_s[df_s.index.date == df_s.index.date.max()].copy()
        if not df_day.empty:
            df_day['Typical_Price'] = (df_day['High'] + df_day['Low'] + df_day['Close']) / 3
            if 'Volume' in df_day.columns and df_day['Volume'].fillna(0).sum() > 0:
                df_day['VWAP'] = (df_day['Typical_Price'] * df_day['Volume']).cumsum() / df_day['Volume'].cumsum()
            else: df_day['VWAP'] = df_day['Typical_Price'].expanding().mean()
            return df_day
        return pd.DataFrame()
    except: return pd.DataFrame()

# --- TABLES HTML GENERATORS ---
def generate_status(row):
    status, p = "", row['P']
    if row['VolX'] > 1.2: status += "VOL🟢 "
    if abs(row['O'] - row['L']) < (p * 0.002): status += "O=L🔥 "
    if abs(row['O'] - row['H']) < (p * 0.002): status += "O=H🩸 "
    if 'AlphaTag' in row and row['AlphaTag']: status += f"{row['AlphaTag']} "
    if row['C'] > 0 and row['Day_C'] > 0 and row['VolX'] > 1: status += "Rec ⇈ "
    return status.strip()

def render_html_table(df_subset, title, color_class):
    if df_subset.empty: return ""
    html = f'<table class="term-table"><thead><tr><th colspan="7" class="{color_class}">{title}</th></tr><tr style="background-color: #21262d;"><th style="text-align:left; width:20%;">STOCK</th><th style="width:12%;">PRICE</th><th style="width:12%;">DAY%</th><th style="width:12%;">NET%</th><th style="width:10%;">VOL</th><th style="width:26%;">STATUS</th><th style="width:8%;">SCORE</th></tr></thead><tbody>'
    for i, (_, row) in enumerate(df_subset.iterrows()):
        dc = "text-green" if row['Day_C'] >= 0 else "text-red"
        nc = "text-green" if row['C'] >= 0 else "text-red"
        html += f'<tr class="{"row-dark" if i%2==0 else "row-light"}"><td class="t-symbol {nc}"><a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank">{row["T"]}</a></td><td>{row["P"]:.2f}</td><td class="{dc}">{row["Day_C"]:.2f}%</td><td class="{nc}">{row["C"]:.2f}%</td><td>{row["VolX"]:.1f}x</td><td style="font-size:10px;">{generate_status(row)}</td><td style="color:#ffd700;">{int(row["S"])}</td></tr>'
    return html + "</tbody></table>"

# --- TOP NAVIGATION & SEARCH ---
c1, c2, c3 = st.columns([0.4, 0.3, 0.3])
with c1: watchlist_mode = st.selectbox("Watchlist", ["High Score Stocks 🔥", "Swing Trading 📈", "Nifty 50 Heatmap", "One Sided Moves 🚀", "Terminal Tables 🗃️", "My Portfolio 💼"], label_visibility="collapsed")
with c2: sort_mode = st.selectbox("Sort By", ["Custom Sort", "Heatmap Marks Up ⭐", "Heatmap Marks Down ⬇️", "% Change Up 🟢", "% Change Down 🔴"], label_visibility="collapsed")
with c3: view_mode = st.radio("Display", ["Heat Map", "Chart 📈"], horizontal=True, label_visibility="collapsed")

df = fetch_all_data()

if not df.empty:
    all_names = sorted(df[~df['Is_Sector']]['T'].tolist())
    search_stock = st.selectbox("🔍 Search & View Chart", ["-- None --"] + all_names)
    
    df_indices = df[df['Is_Index']].copy().sort_values("Order" if "Order" in df.columns else "C", ascending=False)
    df_sectors = df[df['Is_Sector']].copy().sort_values(by="C", ascending=False)
    df_stocks = df[(~df['Is_Index']) & (~df['Is_Sector'])].copy()
    
    df_nifty = df_stocks[df_stocks['T'].isin(NIFTY_50)].copy()
    sector_perf = df_nifty.groupby('Sector')['C'].mean().sort_values(ascending=False)
    valid_sectors = [s for s in sector_perf.index if s != "OTHER"]
    top_buy_sector, top_sell_sector = (valid_sectors[0], valid_sectors[-1]) if valid_sectors else ("PHARMA", "IT")
        
    df_buy_sector = df_nifty[df_nifty['Sector'] == top_buy_sector].sort_values(by=['S', 'C'], ascending=[False, False])
    df_sell_sector = df_nifty[df_nifty['Sector'] == top_sell_sector].sort_values(by=['S', 'C'], ascending=[False, True])
    df_independent = df_nifty[(~df_nifty['Sector'].isin([top_buy_sector, top_sell_sector])) & (df_nifty['S'] >= 5)].sort_values(by='S', ascending=False).head(8)
    df_broader = df_stocks[(df_stocks['T'].isin(BROADER_MARKET)) & (df_stocks['S'] >= 5)].sort_values(by='S', ascending=False).head(8)

    df_port_saved = load_portfolio()

    if watchlist_mode == "Terminal Tables 🗃️":
        terminal_tickers = pd.concat([df_buy_sector, df_sell_sector, df_independent, df_broader])['Fetch_T'].unique().tolist()
        df_filtered = df_stocks[df_stocks['Fetch_T'].isin(terminal_tickers)]
    elif watchlist_mode == "My Portfolio 💼":
        port_tickers = [f"{str(sym).upper().strip()}.NS" for sym in df_port_saved['Symbol'].tolist() if str(sym).strip() != ""]
        df_filtered = df_stocks[df_stocks['Fetch_T'].isin(port_tickers)]
    elif watchlist_mode == "Nifty 50 Heatmap": df_filtered = df_stocks[df_stocks['T'].isin(NIFTY_50)]
    elif watchlist_mode == "One Sided Moves 🚀": df_filtered = df_stocks[df_stocks['C'].abs() >= 1.0]
    elif watchlist_mode == "Swing Trading 📈": df_filtered = df_stocks[df_stocks['Is_Swing'] == True]
    else: 
        # 🔥 FIX: Lowered threshold to 5 so stocks appear even without bounce points! 🔥
        df_filtered = df_stocks[(df_stocks['S'] >= 5)]

    all_display_tickers = list(set(df_indices['Fetch_T'].tolist() + df_filtered['Fetch_T'].tolist() + st.session_state.pinned_stocks))
    if search_stock != "-- None --": all_display_tickers.append(df[df['T'] == search_stock]['Fetch_T'].iloc[0])
            
    with st.spinner("Analyzing VWAP & Pure Price Action (Alpha Mode)..."):
        # 🔥 FIX: threads=5 to avoid Cloud Crash
        five_min_data = yf.download(all_display_tickers, period="5d", interval="5m", progress=False, group_by='ticker', threads=5)

    processed_charts, stock_trends, alpha_tags = {}, {}, {}

    nifty_dist_5m = 0.1
    if "^NSEI" in five_min_data.columns.levels[0]:
        n_raw = five_min_data["^NSEI"] if isinstance(five_min_data.columns, pd.MultiIndex) else five_min_data
        n_day = process_5m_data(n_raw)
        if not n_day.empty:
            n_vwap = n_day['VWAP'].iloc[-1]
            if n_vwap > 0: nifty_dist_5m = abs(n_day['Close'].iloc[-1] - n_vwap) / n_vwap * 100

    for sym in all_display_tickers:
        df_raw = five_min_data[sym] if isinstance(five_min_data.columns, pd.MultiIndex) else five_min_data
        df_day = process_5m_data(df_raw)
        processed_charts[sym] = df_day
        
        if sym in df_filtered['Fetch_T'].tolist() and not df_day.empty:
            last_price, last_vwap = df_day['Close'].iloc[-1], df_day['VWAP'].iloc[-1]
            net_chg = df[df['Fetch_T'] == sym]['C'].iloc[0]
            
            alpha_tag = ""
            if len(df_day) >= 50 and last_vwap > 0:
                stock_dist_5m = abs(last_price - last_vwap) / last_vwap * 100
                if stock_dist_5m > (nifty_dist_5m * 3): alpha_tag = "🚀Alpha-Mover"
                elif stock_dist_5m > (nifty_dist_5m * 2): alpha_tag = "💪Nifty-Beater"
            
            alpha_tags[sym] = alpha_tag
            stock_trends[sym] = 'Bullish' if (net_chg > 0 and last_price >= last_vwap) else ('Bearish' if (net_chg < 0 and last_price <= last_vwap) else 'Neutral')

    if not df_filtered.empty:
        df_filtered['AlphaTag'] = df_filtered['Fetch_T'].map(alpha_tags).fillna("")

    bull_cnt = sum(1 for sym in df_filtered['Fetch_T'] if stock_trends.get(sym) == 'Bullish')
    bear_cnt = sum(1 for sym in df_filtered['Fetch_T'] if stock_trends.get(sym) == 'Bearish')
    neut_cnt = sum(1 for sym in df_filtered['Fetch_T'] if stock_trends.get(sym) == 'Neutral')

    with st.container():
        st.markdown("<div class='filter-marker'></div>", unsafe_allow_html=True)
        if st.button(f"📊 All ({len(df_filtered)})"): st.session_state.trend_filter = 'All'
        if st.button(f"🟢 Bullish ({bull_cnt})"): st.session_state.trend_filter = 'Bullish'
        if st.button(f"⚪ Neutral ({neut_cnt})"): st.session_state.trend_filter = 'Neutral'
        if st.button(f"🔴 Bearish ({bear_cnt})"): st.session_state.trend_filter = 'Bearish'

    st.markdown(f"<div style='text-align:right; font-size:12px; color:#ffd700; margin-bottom: 10px;'>Showing: <b>{st.session_state.trend_filter}</b> Stocks</div>", unsafe_allow_html=True)

    if st.session_state.trend_filter != 'All':
        df_filtered = df_filtered[df_filtered['Fetch_T'].apply(lambda x: stock_trends.get(x) == st.session_state.trend_filter)]

    # 🔥 FIX: Perfectly formatted sorting logic to prevent syntax errors 🔥
    if sort_mode == "% Change Up 🟢": 
        df_stocks_display = df_filtered.sort_values(by="C", ascending=False)
    elif sort_mode == "% Change Down 🔴": 
        df_stocks_display = df_filtered.sort_values(by="C", ascending=True)
    elif sort_mode == "Heatmap Marks Up ⭐": 
        df_stocks_display = pd.concat([
            df_filtered[df_filtered['C'] >= 0].sort_values(by=["S", "C"], ascending=[False, False]), 
            df_filtered[df_filtered['C'] < 0].sort_values(by=["S", "C"], ascending=[False, True])
        ])
    elif sort_mode == "Heatmap Marks Down ⬇️": 
        df_stocks_display = pd.concat([
            df_filtered[df_filtered['C'] < 0].sort_values(by=["S", "C"], ascending=[False, True]), 
            df_filtered[df_filtered['C'] >= 0].sort_values(by=["S", "C"], ascending=[False, False])
        ])
    else:
        if st.session_state.trend_filter == 'Bullish': 
            df_stocks_display = df_filtered.sort_values(by=["S", "C"], ascending=[False, False])
        elif st.session_state.trend_filter == 'Bearish': 
            df_stocks_display = df_filtered.sort_values(by=["S", "C"], ascending=[False, True])
        elif st.session_state.trend_filter == 'Neutral': 
            df_stocks_display = df_filtered.sort_values(by=["S", "C"], ascending=[False, False])
        else: 
            df_stocks_display = pd.concat([
                df_filtered[df_filtered['C'] >= 0].sort_values(by=["S", "C"], ascending=[False, False]), 
                df_filtered[df_filtered['C'] < 0].sort_values(by=["S", "C"], ascending=[True, True])
            ])

    if watchlist_mode == "Terminal Tables 🗃️" and view_mode == "Heat Map":
        st.markdown(f"<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#e6edf3;'>🗃️ Professional Terminal View</div>", unsafe_allow_html=True)
        if st.session_state.trend_filter != 'All':
            df_buy_sector = df_buy_sector[df_buy_sector['Fetch_T'].isin(df_filtered['Fetch_T'])]
            df_sell_sector = df_sell_sector[df_sell_sector['Fetch_T'].isin(df_filtered['Fetch_T'])]
            df_independent = df_independent[df_independent['Fetch_T'].isin(df_filtered['Fetch_T'])]
            df_broader = df_broader[df_broader['Fetch_T'].isin(df_filtered['Fetch_T'])]

        st.markdown(render_html_table(df_buy_sector, f"🚀 BUY LEADER: {top_buy_sector}", "term-head-buy"), unsafe_allow_html=True)
        st.markdown(render_html_table(df_sell_sector, f"🩸 SELL LAGGARD: {top_sell_sector}", "term-head-sell"), unsafe_allow_html=True)
        st.markdown(render_html_table(df_independent, "🌟 INDEPENDENT MOVERS", "term-head-ind"), unsafe_allow_html=True)
        st.markdown(render_html_table(df_broader, "🌌 BROADER MARKET", "term-head-brd"), unsafe_allow_html=True)

    elif watchlist_mode == "My Portfolio 💼" and view_mode == "Heat Map":
        html_port = f'<table class="term-table"><thead><tr><th colspan="10" class="term-head-port">💼 LIVE PORTFOLIO TERMINAL</th></tr><tr style="background-color: #21262d;"><th style="text-align:left; width:11%;">STOCK</th><th style="width:9%;">DATE</th><th style="width:6%;">QTY</th><th style="width:8%;">AVG</th><th style="width:8%;">LTP</th><th style="width:10%;">TREND</th><th style="width:18%;">STATUS</th><th style="width:10%;">DAY P&L</th><th style="width:10%;">TOT P&L</th><th style="width:10%;">P&L %</th></tr></thead><tbody>'
        t_inv, t_cur, t_day = 0, 0, 0
        for i, (_, r) in enumerate(df_port_saved.iterrows()):
            sym, qty, buy_p = str(r['Symbol']).upper().strip(), float(r.get('Quantity', 0)), float(r.get('Buy_Price', 0))
            lr = df_stocks[df_stocks['T'] == sym]
            if not lr.empty:
                ltp, p_c = float(lr['P'].iloc[0]), float(lr['Prev_C'].iloc[0])
                st_h = generate_status(lr.iloc[0])
                tr_s = stock_trends.get(lr['Fetch_T'].iloc[0], "Neutral")
                tr_h = "🟢 Bullish" if tr_s == 'Bullish' else ("🔴 Bearish" if tr_s == 'Bearish' else "⚪ Neutral")
            else: ltp, p_c, st_h, tr_h = buy_p, buy_p, "N/A", "➖"
            inv, cur = buy_p * qty, ltp * qty
            o_pnl, p_pct, d_pnl = cur - inv, ((cur - inv) / inv * 100) if inv > 0 else 0, (ltp - p_c) * qty
            t_inv += inv; t_cur += cur; t_day += d_pnl
            tc = "text-green" if o_pnl >= 0 else "text-red"
            dc = "text-green" if d_pnl >= 0 else "text-red"
            html_port += f'<tr class="{"row-dark" if i%2==0 else "row-light"}"><td class="t-symbol {tc}"><a href="https://in.tradingview.com/chart/?symbol=NSE:{sym}" target="_blank">{sym}</a></td><td>{r.get("Date","-")}</td><td>{int(qty)}</td><td>{buy_p:.2f}</td><td>{ltp:.2f}</td><td style="font-size:10px;">{tr_h}</td><td style="font-size:10px;">{st_h}</td><td class="{dc}">{"+" if d_pnl>0 else ""}{d_pnl:,.0f}</td><td class="{tc}">{"+" if o_pnl>0 else ""}{o_pnl:,.0f}</td><td class="{tc}">{"+" if o_pnl>0 else ""}{p_pct:.2f}%</td></tr>'
        to_pnl = t_cur - t_inv
        to_pct = (to_pnl / t_inv * 100) if t_inv > 0 else 0
        oc = "text-green" if to_pnl >= 0 else "text-red"
        odc = "text-green" if t_day >= 0 else "text-red"
        html_port += f'<tr class="port-total"><td colspan="7" style="text-align:right; padding-right:15px; font-size:12px;">INVESTED: ₹{t_inv:,.0f} | CURRENT: ₹{t_cur:,.0f} | P&L:</td><td class="{odc}">{"+" if t_day>0 else ""}₹{t_day:,.0f}</td><td class="{oc}">{"+" if to_pnl>0 else ""}₹{to_pnl:,.0f}</td><td class="{oc}">{"+" if to_pnl>0 else ""}{to_pct:.2f}%</td></tr></tbody></table>'
        st.markdown(html_port, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)

    elif view_mode == "Heat Map":
        if not df_indices.empty:
            html_idx = '<div class="heatmap-grid">'
            for _, r in df_indices.iterrows():
                bg = "bear-card" if (r['T'] == "INDIA VIX" and r['C'] > 0) or (r['T'] != "INDIA VIX" and r['C'] < 0) else "bull-card"
                html_idx += f'<a href="https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(r["Fetch_T"])}" target="_blank" class="stock-card {bg}"><div class="t-score">IDX</div><div class="t-name">{r["T"]}</div><div class="t-price">{r["P"]:.2f}</div><div class="t-pct">{"+" if r["C"]>0 else ""}{r["C"]:.2f}%</div></a>'
            st.markdown(html_idx + '</div><hr class="custom-hr">', unsafe_allow_html=True)
        
        if not df_sectors.empty:
            html_sec = '<div class="heatmap-grid">'
            for _, r in df_sectors.iterrows():
                bg = "bull-card" if r['C'] > 0 else ("bear-card" if r['C'] < 0 else "neut-card")
                html_sec += f'<a href="https://in.tradingview.com/chart/?symbol={TV_SECTOR_URL.get(r["Fetch_T"], "")}" target="_blank" class="stock-card {bg}"><div class="t-score" style="color:#00BFFF;">SEC</div><div class="t-name">{r["T"]}</div><div class="t-price">{r["P"]:.2f}</div><div class="t-pct">{"+" if r["C"]>0 else ""}{r["C"]:.2f}%</div></a>'
            st.markdown(html_sec + '</div><hr class="custom-hr">', unsafe_allow_html=True)

        if not df_stocks_display.empty:
            html_stk = '<div class="heatmap-grid">'
            for _, r in df_stocks_display.iterrows():
                bg = "bull-card" if r['C'] > 0 else ("bear-card" if r['C'] < 0 else "neut-card")
                ic = "🌊" if watchlist_mode == "Swing Trading 📈" else ("🚀" if watchlist_mode == "One Sided Moves 🚀" else f"⭐{int(r['S'])}")
                html_stk += f'<a href="https://in.tradingview.com/chart/?symbol=NSE:{r["T"]}" target="_blank" class="stock-card {bg}"><div class="t-score">{ic}</div><div class="t-name">{r["T"]}</div><div class="t-price">{r["P"]:.2f}</div><div class="t-pct">{"+" if r["C"]>0 else ""}{r["C"]:.2f}%</div></a>'
            st.markdown(html_stk + '</div><br>', unsafe_allow_html=True)
            
            if watchlist_mode == "Swing Trading 📈":
                html = f'<table class="term-table"><thead><tr><th colspan="10" class="term-head-swing">🌊 SWING TRADING RADAR</th></tr><tr style="background-color: #21262d;"><th>RANK</th><th style="text-align:left;">STOCK</th><th>LTP</th><th>DAY%</th><th>VOL</th><th>STATUS</th><th style="color:#f85149;">🛑 SL</th><th style="color:#3fb950;">🎯 TGT 1</th><th style="color:#3fb950;">🎯 TGT 2</th><th>SCORE</th></tr></thead><tbody>'
                for i, r in df_stocks_display.iterrows():
                    tr = stock_trends.get(r['Fetch_T'], "Neutral")
                    st_h = generate_status(r) + (" 🟢Trend" if tr=='Bullish' else (" 🔴Trend" if tr=='Bearish' else ""))
                    sl, t1, t2 = (r["R1"], r["S1"], r["S2"]) if (tr=='Bearish' or r['C']<0) else (r["S1"], r["R1"], r["R2"])
                    dc = "text-green" if r['Day_C'] >= 0 else "text-red"
                    html += f'<tr class="{"row-dark" if i%2==0 else "row-light"}"><td><b>{"🏆 1" if i==0 else i+1}</b></td><td class="t-symbol"><a href="https://in.tradingview.com/chart/?symbol=NSE:{r["T"]}" target="_blank">{r["T"]}</a></td><td>{r["P"]:.2f}</td><td class="{dc}">{r["Day_C"]:.2f}%</td><td>{r["VolX"]:.1f}x</td><td style="font-size:10px;">{st_h}</td><td style="color:#f85149; font-weight:bold;">{sl:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t1:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t2:.2f}</td><td style="color:#ffd700;">{int(r["S"])}</td></tr>'
                with st.expander("🌊 View Swing Trading Radar (Ranked Table)", expanded=True): st.markdown(html + "</tbody></table>", unsafe_allow_html=True)
            elif watchlist_mode == "High Score Stocks 🔥":
                html = f'<table class="term-table"><thead><tr><th colspan="10" class="term-head-high">🔥 HIGH SCORE RADAR (ALPHA MOVERS)</th></tr><tr style="background-color: #21262d;"><th>RANK</th><th style="text-align:left;">STOCK</th><th>LTP</th><th>DAY%</th><th>VOL</th><th>STATUS</th><th style="color:#f85149;">🛑 SL</th><th style="color:#3fb950;">🎯 TGT 1</th><th style="color:#3fb950;">🎯 TGT 2</th><th>SCORE</th></tr></thead><tbody>'
                for i, r in df_stocks_display.iterrows():
                    tr = stock_trends.get(r['Fetch_T'], "Neutral")
                    st_h = generate_status(r) + (" 🟢Trend" if tr=='Bullish' else (" 🔴Trend" if tr=='Bearish' else ""))
                    sl, t1, t2 = (r["R1"], r["S1"], r["S2"]) if (tr=='Bearish' or r['C']<0) else (r["S1"], r["R1"], r["R2"])
                    dc = "text-green" if r['Day_C'] >= 0 else "text-red"
                    html += f'<tr class="{"row-dark" if i%2==0 else "row-light"}"><td><b>{"🏆 1" if i==0 else i+1}</b></td><td class="t-symbol"><a href="https://in.tradingview.com/chart/?symbol=NSE:{r["T"]}" target="_blank">{r["T"]}</a></td><td>{r["P"]:.2f}</td><td class="{dc}">{r["Day_C"]:.2f}%</td><td>{r["VolX"]:.1f}x</td><td style="font-size:10px;">{st_h}</td><td style="color:#f85149; font-weight:bold;">{sl:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t1:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t2:.2f}</td><td style="color:#ffd700;">{int(r["S"])}</td></tr>'
                with st.expander("🔥 View High Score Radar (Ranked Table)", expanded=True): st.markdown(html + "</tbody></table>", unsafe_allow_html=True)
            else:
                html = f'<table class="term-table"><thead><tr><th colspan="8" class="term-head-levels">🎯 TRADING LEVELS (TARGETS & STOP LOSS)</th></tr><tr style="background-color: #21262d;"><th style="text-align:left;">STOCK</th><th>TREND</th><th>LTP</th><th>PIVOT</th><th style="color:#f85149;">STOP LOSS</th><th style="color:#3fb950;">TARGET 1</th><th style="color:#3fb950;">TARGET 2</th><th>EXTREME TGT/SL</th></tr></thead><tbody>'
                for i, r in df_stocks_display.iterrows():
                    tr = stock_trends.get(r['Fetch_T'], "Neutral")
                    tr_h = "🟢 Bullish" if tr=='Bullish' else ("🔴 Bearish" if tr=='Bearish' else "⚪ Neutral")
                    sl, t1, t2, ext = (r["R1"], r["S1"], r["S2"], r["R2"]) if (tr=='Bearish' or r['C']<0) else (r["S1"], r["R1"], r["R2"], r["S2"])
                    html += f'<tr class="{"row-dark" if i%2==0 else "row-light"}"><td class="t-symbol"><a href="https://in.tradingview.com/chart/?symbol=NSE:{r["T"]}" target="_blank">{r["T"]}</a></td><td style="font-size:10px;">{tr_h}</td><td>{r["P"]:.2f}</td><td style="color:#8b949e;">{r["Pivot"]:.2f}</td><td style="color:#f85149; font-weight:bold;">{sl:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t1:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t2:.2f}</td><td style="color:#8b949e;">{ext:.2f}</td></tr>'
                with st.expander("🎯 View Trading Levels (Targets & Stop Loss)", expanded=True): st.markdown(html + "</tbody></table>", unsafe_allow_html=True)
        else: st.info(f"No {st.session_state.trend_filter} stocks found.")
            
    else: # CHART VIEW
        st.markdown("<br>", unsafe_allow_html=True)
        def render_c(r, d, sp=True, ks=""):
            ds, fs = r['T'], r['Fetch_T']
            cx = "#da3633" if (ds=="INDIA VIX" and r['C']>0) or (ds!="INDIA VIX" and r['C']<0) else "#2ea043"
            if sp and ds not in ["NIFTY", "BANKNIFTY", "INDIA VIX"]: st.checkbox("pin", value=(fs in st.session_state.pinned_stocks), key=f"cb_{fs}_{ks}", on_change=toggle_pin, args=(fs,), label_visibility="collapsed")
            st.markdown(f"<div style='text-align:center; font-size:15px; margin-top:2px;'><a href='{TV_INDICES_URL.get(fs, 'NSE:'+ds)}' target='_blank' style='color:#fff; text-decoration:none;'>{ds} <span style='color:{cx};'>({'+' if r['C']>0 else ''}{r['C']:.2f}%)</span></a></div><div style='text-align:center; font-size:10px; color:#8b949e; margin-bottom:5px;'><span style='color:#FFD700;'>--- VWAP</span> &nbsp;|&nbsp; <span style='color:#00BFFF;'>- - 10 EMA</span></div>", unsafe_allow_html=True)
            if not d.empty:
                min_v, max_v = d[['Low', 'VWAP', 'EMA_10']].min().min(), d[['High', 'VWAP', 'EMA_10']].max().max()
                yp = (max_v - min_v)*0.1 if max_v!=min_v else min_v*0.005
                fig = go.Figure(data=[go.Candlestick(x=d.index, open=d['Open'], high=d['High'], low=d['Low'], close=d['Close'], increasing_line_color='#2ea043', decreasing_line_color='#da3633'), go.Scatter(x=d.index, y=d['VWAP'], line=dict(color='#FFD700', width=1.5, dash='dot')), go.Scatter(x=d.index, y=d['EMA_10'], line=dict(color='#00BFFF', width=1.5, dash='dash'))])
                fig.update_layout(margin=dict(l=0,r=0,t=0,b=0), height=150, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis=dict(visible=False, fixedrange=True), yaxis=dict(visible=False, range=[min_v-yp, max_v+yp], fixedrange=True), hovermode=False, showlegend=False, dragmode=False)
                st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False, 'staticPlot': True})
            else: st.markdown("<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888;'>Data not available</div>", unsafe_allow_html=True)
            
        if search_stock != "-- None --":
            st.markdown(f"<div style='font-size:18px; font-weight:bold; margin-bottom:5px; color:#ffd700;'>🔍 Searched Chart: {search_stock}</div>", unsafe_allow_html=True)
            with st.container():
                st.markdown("<div class='fluid-board'></div>", unsafe_allow_html=True)
                with st.container(): render_c(df[df['T']==search_stock].iloc[0], processed_charts.get(df[df['T']==search_stock]['Fetch_T'].iloc[0], pd.DataFrame()), sp=True, ks="sch")
            st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        if watchlist_mode not in ["Terminal Tables 🗃️", "My Portfolio 💼"]:
            st.markdown("<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#e6edf3;'>📈 Market Indices</div>", unsafe_allow_html=True)
            with st.container():
                st.markdown("<div class='fluid-board'></div>", unsafe_allow_html=True)
                for j, (_, r) in enumerate(df_indices.iterrows()):
                    with st.container(): render_c(r, processed_charts.get(r['Fetch_T'], pd.DataFrame()), sp=False, ks=f"idx_{j}")
            st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        pinned_df = df[df['Fetch_T'].isin(st.session_state.pinned_stocks)].copy()
        unpinned_df = df_stocks_display[~df_stocks_display['Fetch_T'].isin(pinned_df['Fetch_T'].tolist())]
        
        if not pinned_df.empty:
            st.markdown("<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#ffd700;'>📌 Pinned Priority Charts</div>", unsafe_allow_html=True)
            with st.container():
                st.markdown("<div class='fluid-board'></div>", unsafe_allow_html=True)
                for j, (_, r) in enumerate(pinned_df.iterrows()):
                    with st.container(): render_c(r, processed_charts.get(r['Fetch_T'], pd.DataFrame()), sp=True, ks=f"pin_{j}")
            st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        if not unpinned_df.empty:
            st.markdown(f"<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#e6edf3;'>{watchlist_mode} ({st.session_state.trend_filter})</div>", unsafe_allow_html=True)
            with st.container():
                st.markdown("<div class='fluid-board'></div>", unsafe_allow_html=True)
                for j, (_, r) in enumerate(unpinned_df.iterrows()):
                    with st.container(): render_c(r, processed_charts.get(r['Fetch_T'], pd.DataFrame()), sp=True, ks=f"main_{j}")

else: st.info("Loading Market Data...")
