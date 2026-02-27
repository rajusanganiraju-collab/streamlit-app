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

# --- 3. STATE MANAGEMENT ---
if 'trend_filter' not in st.session_state: st.session_state.trend_filter = 'All'
if 'pinned_stocks' not in st.session_state: st.session_state.pinned_stocks = []

def toggle_pin(symbol):
    if symbol in st.session_state.pinned_stocks: st.session_state.pinned_stocks.remove(symbol)
    else: st.session_state.pinned_stocks.append(symbol)

# --- PORTFOLIO SETUP ---
PORTFOLIO_FILE = "my_portfolio.csv"
def load_portfolio():
    if os.path.exists(PORTFOLIO_FILE):
        df = pd.read_csv(PORTFOLIO_FILE)
        if not df.empty:
            df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce').fillna(1).astype(int)
            df['Buy_Price'] = pd.to_numeric(df['Buy_Price'], errors='coerce').fillna(0.0).astype(float)
            df['Symbol'] = df['Symbol'].astype(str).replace('nan', '')
            df['Date'] = df['Date'].astype(str).replace('nan', '')
        else:
            df['Quantity'], df['Buy_Price'] = pd.Series(dtype=int), pd.Series(dtype=float)
        return df
    return pd.DataFrame(columns=["Symbol", "Buy_Price", "Quantity", "Date"])

def save_portfolio(df_port): df_port.to_csv(PORTFOLIO_FILE, index=False)

# --- 4. CSS ---
st.markdown("""
<style>
#MainMenu, footer, header {visibility: hidden; display: none !important;}
.stApp { background-color: #0e1117; color: #ffffff; }
.block-container { padding-top: 1rem !important; padding-bottom: 0rem !important; margin-top: -10px; }
.t-name { font-size: 13px; font-weight: normal !important; margin-bottom: 2px; }
.t-price { font-size: 17px; font-weight: normal !important; margin-bottom: 2px; }
.t-pct { font-size: 12px; font-weight: normal !important; }
.t-score { position: absolute; top: 3px; left: 3px; font-size: 10px; background: rgba(0,0,0,0.4); padding: 1px 4px; border-radius: 3px; color: #ffd700; }
div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) { display: flex !important; flex-direction: row !important; gap: 6px !important; }
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
.idx-card { background-color: #0d47a1 !important; }
.custom-hr { border: 0; height: 1px; background: #30363d; margin: 15px 0; }
.term-table { width: 100%; border-collapse: collapse; margin-bottom: 15px; font-family: monospace; font-size: 11.5px; color: #e6edf3; background-color: #0e1117; table-layout: fixed; }
.term-table th, .term-table td { padding: 6px 4px; text-align: center; border: 1px solid #30363d; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.term-table a { color: inherit; text-decoration: none; border-bottom: 1px dashed rgba(255,255,255,0.4); } 
.term-table a:hover { color: #58a6ff !important; border-bottom: 1px solid #58a6ff; }
.term-head-buy { background-color: #1e5f29; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
.term-head-sell { background-color: #b52524; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
.term-head-ind { background-color: #9e6a03; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
.term-head-brd { background-color: #0d47a1; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
.term-head-port { background-color: #4a148c; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
.term-head-swing, .term-head-levels { background-color: #005a9e; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
.term-head-high { background-color: #b71c1c; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
.row-dark { background-color: #161b22; } .row-light { background-color: #0e1117; }
.text-green { color: #3fb950; font-weight: bold; } .text-red { color: #f85149; font-weight: bold; }
.t-symbol { text-align: left !important; font-weight: bold; }
.port-total { background-color: #21262d; font-weight: bold; font-size: 13px; }
</style>
""", unsafe_allow_html=True)

# --- 5. CONSTANTS & LISTS ---
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
    data = yf.download(tkrs, period="1y", progress=False, group_by='ticker', threads=20)
    
    results, minutes = [], get_minutes_passed()
    for symbol in data.columns.levels[0]:
        try:
            df = data[symbol].dropna(subset=['Close'])
            if len(df) < 2: continue
            
            ltp, open_p, low, high = float(df['Close'].iloc[-1]), float(df['Open'].iloc[-1]), float(df['Low'].iloc[-1]), float(df['High'].iloc[-1])
            prev_c, prev_h, prev_l = float(df['Close'].iloc[-2]), float(df['High'].iloc[-2]), float(df['Low'].iloc[-2])
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
                rsi = (100 - (100 / (1 + (gain / loss)))).fillna(100).iloc[-1]
                v_brk = curr_vol > (1.2 * df['Volume'].iloc[-11:-1].mean()) if len(df)>=11 else False
                if ltp > e50 and e20 > e50 and rsi >= 55 and v_brk and net_chg > 0: is_swing = True

            # BASE SCORE - Only strictly logic based points (no 2% random bonus)
            score = 0
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
        df_s['EMA_20'] = df_s['Close'].ewm(span=20, adjust=False).mean()
        df_s['EMA_50'] = df_s['Close'].ewm(span=50, adjust=False).mean()
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

def generate_status(row):
    st_tags = ""
    p = row['P']
    if row['VolX'] > 1.2: st_tags += "VOL🟢 "
    if abs(row['O'] - row['L']) < (p * 0.002): st_tags += "O=L🔥 "
    if abs(row['O'] - row['H']) < (p * 0.002): st_tags += "O=H🩸 "
    if 'BounceTag' in row and row['BounceTag']: st_tags += f"{row['BounceTag']} "
    return st_tags.strip()

def render_html_table(df_subset, title, color_class):
    if df_subset.empty: return ""
    html = f'<table class="term-table"><thead><tr><th colspan="7" class="{color_class}">{title}</th></tr><tr style="background-color: #21262d;"><th style="text-align:left; width:20%;">STOCK</th><th style="width:12%;">PRICE</th><th style="width:12%;">DAY%</th><th style="width:12%;">NET%</th><th style="width:10%;">VOL</th><th style="width:26%;">STATUS</th><th style="width:8%;">SCORE</th></tr></thead><tbody>'
    for i, (_, row) in enumerate(df_subset.iterrows()):
        dc = "text-green" if row['Day_C'] >= 0 else "text-red"
        nc = "text-green" if row['C'] >= 0 else "text-red"
        html += f'<tr class="{"row-dark" if i%2==0 else "row-light"}"><td class="t-symbol {nc}"><a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank">{row["T"]}</a></td><td>{row["P"]:.2f}</td><td class="{dc}">{row["Day_C"]:.2f}%</td><td class="{nc}">{row["C"]:.2f}%</td><td>{row["VolX"]:.1f}x</td><td style="font-size:10px;">{generate_status(row)}</td><td style="color:#ffd700;">{int(row["S"])}</td></tr>'
    return html + "</tbody></table>"

# --- UI CONTROLS ---
c1, c2, c3 = st.columns([0.4, 0.3, 0.3])
with c1: watchlist_mode = st.selectbox("Watchlist", ["High Score Stocks 🔥", "Swing Trading 📈", "Nifty 50 Heatmap", "Terminal Tables 🗃️", "My Portfolio 💼"], label_visibility="collapsed")
with c2: sort_mode = st.selectbox("Sort By", ["Custom Sort", "% Change Up 🟢", "% Change Down 🔴"], label_visibility="collapsed")
with c3: view_mode = st.radio("Display", ["Heat Map", "Chart 📈"], horizontal=True, label_visibility="collapsed")

df = fetch_all_data()

if not df.empty:
    search_stock = st.selectbox("🔍 Search & View Chart", ["-- None --"] + sorted(df[~df['Is_Sector']]['T'].tolist()))
    
    df_indices = df[df['Is_Index']].copy().sort_values("Order" if "Order" in df.columns else "C", ascending=False)
    df_sectors = df[df['Is_Sector']].copy().sort_values("C", ascending=False)
    df_stocks = df[(~df['Is_Index']) & (~df['Is_Sector'])].copy()
    
    if watchlist_mode == "Nifty 50 Heatmap": df_filtered = df_stocks[df_stocks['T'].isin(NIFTY_50)]
    elif watchlist_mode == "Swing Trading 📈": df_filtered = df_stocks[df_stocks['Is_Swing'] == True]
    elif watchlist_mode == "My Portfolio 💼": 
        pt = [f"{str(s).upper().strip()}.NS" for s in load_portfolio()['Symbol'].tolist() if str(s).strip()]
        df_filtered = df_stocks[df_stocks['Fetch_T'].isin(pt)]
    else: df_filtered = df_stocks.copy() 

    all_display_tickers = list(set(df_indices['Fetch_T'].tolist() + df_filtered['Fetch_T'].tolist() + st.session_state.pinned_stocks))
    if search_stock != "-- None --": all_display_tickers.append(df[df['T'] == search_stock]['Fetch_T'].iloc[0])
            
    with st.spinner("Analyzing Nifty Strength & Pullbacks (Sniper Mode)..."):
        # Threads=20 as you requested for speed
        five_min_data = yf.download(all_display_tickers, period="5d", interval="5m", progress=False, group_by='ticker', threads=20)

    processed_charts, stock_trends, bounce_tags, bounce_scores = {}, {}, {}, {}

    # 🔥 1. NIFTY DISTANCE CALCULATION 🔥
    nifty_dist = 0.1 
    if "^NSEI" in five_min_data.columns.levels[0]:
        ndf = process_5m_data(five_min_data["^NSEI"])
        if not ndf.empty:
            n_ltp, n_vwap = ndf['Close'].iloc[-1], ndf['VWAP'].iloc[-1]
            nifty_dist = abs(n_ltp - n_vwap) / n_vwap * 100 if n_vwap > 0 else 0.1

    for sym in all_display_tickers:
        df_raw = five_min_data[sym] if isinstance(five_min_data.columns, pd.MultiIndex) else five_min_data
        df_day = process_5m_data(df_raw)
        processed_charts[sym] = df_day
        
        if sym in df_filtered['Fetch_T'].tolist() and not df_day.empty:
            last_price, vwap = df_day['Close'].iloc[-1], df_day['VWAP'].iloc[-1]
            ema10, ema20, ema50 = df_day['EMA_10'].iloc[-1], df_day['EMA_20'].iloc[-1], df_day['EMA_50'].iloc[-1]
            net_chg = df[df['Fetch_T'] == sym]['C'].iloc[0]
            base_score = int(df_filtered[df_filtered['Fetch_T'] == sym]['S'].iloc[0])
            tag, b_score, alpha_tag = "", 0, ""
            
            # 🔥 2. NIFTY-BEATER / ALPHA LOGIC 🔥
            if len(df_day) >= 50:
                stock_dist = abs(last_price - vwap) / vwap * 100 if vwap > 0 else 0
                if stock_dist > (nifty_dist * 3):
                    alpha_tag, b_score = "🚀Alpha-Mover", b_score + 5
                elif stock_dist > (nifty_dist * 2):
                    alpha_tag, b_score = "💪Nifty-Beater", b_score + 3
            
            # Update base_score temporarily to check if it passes Sniper Guard
            temp_score = base_score + b_score 
            
            # 🔥 3. SNIPER BOUNCE LOGIC (Only if score >= 6) 🔥
            if len(df_day) >= 50 and temp_score >= 6: 
                if net_chg > 0 and (ema10 >= ema20) and (ema20 >= ema50):
                    d50, dvw = (last_price - ema50)/ema50*100 if ema50>0 else -1, (last_price - vwap)/vwap*100 if vwap>0 else -1
                    d20, d10 = (last_price - ema20)/ema20*100 if ema20>0 else -1, (last_price - ema10)/ema10*100 if ema10>0 else -1
                    if 0<=d50<=0.4: tag, b_score = "🔥50EMA-Bounce", b_score + 5
                    elif 0<=dvw<=0.4: tag, b_score = "🔥VWAP-Bounce", b_score + 5
                    elif 0<=d20<=0.4: tag, b_score = "🔥20EMA-Bounce", b_score + 5
                    elif 0<=d10<=0.3: tag, b_score = "🔥10EMA-Bounce", b_score + 5
                elif net_chg < 0 and (ema10 <= ema20) and (ema20 <= ema50):
                    d50, dvw = (ema50 - last_price)/last_price*100 if last_price>0 else -1, (vwap - last_price)/last_price*100 if last_price>0 else -1
                    d20, d10 = (ema20 - last_price)/last_price*100 if last_price>0 else -1, (ema10 - last_price)/last_price*100 if last_price>0 else -1
                    if 0<=d50<=0.4: tag, b_score = "🩸50EMA-Reject", b_score + 5
                    elif 0<=dvw<=0.4: tag, b_score = "🩸VWAP-Reject", b_score + 5
                    elif 0<=d20<=0.4: tag, b_score = "🩸20EMA-Reject", b_score + 5
                    elif 0<=d10<=0.3: tag, b_score = "🩸10EMA-Reject", b_score + 5

            final_tag = f"{alpha_tag} {tag}".strip()
            bounce_tags[sym] = final_tag
            bounce_scores[sym] = b_score
            
            if (net_chg > 0) and (last_price >= vwap): stock_trends[sym] = 'Bullish'
            elif (net_chg < 0) and (last_price <= vwap): stock_trends[sym] = 'Bearish'
            else: stock_trends[sym] = 'Neutral'

    if not df_filtered.empty:
        df_filtered['BounceTag'] = df_filtered['Fetch_T'].map(bounce_tags).fillna("")
        df_filtered['S'] = df_filtered.apply(lambda row: row['S'] + bounce_scores.get(row['Fetch_T'], 0), axis=1)

    # FINAL HIGH SCORE FILTER
    if watchlist_mode == "High Score Stocks 🔥":
        df_filtered = df_filtered[df_filtered['S'] >= 7]

    bull_c = sum(1 for s in df_filtered['Fetch_T'] if stock_trends.get(s) == 'Bullish')
    bear_c = sum(1 for s in df_filtered['Fetch_T'] if stock_trends.get(s) == 'Bearish')
    neut_c = sum(1 for s in df_filtered['Fetch_T'] if stock_trends.get(s) == 'Neutral')

    st.markdown("<div class='filter-marker'></div>", unsafe_allow_html=True)
    if st.button(f"📊 All ({len(df_filtered)})"): st.session_state.trend_filter = 'All'
    if st.button(f"🟢 Bullish ({bull_c})"): st.session_state.trend_filter = 'Bullish'
    if st.button(f"⚪ Neutral ({neut_c})"): st.session_state.trend_filter = 'Neutral'
    if st.button(f"🔴 Bearish ({bear_c})"): st.session_state.trend_filter = 'Bearish'

    if st.session_state.trend_filter != 'All':
        df_filtered = df_filtered[df_filtered['Fetch_T'].apply(lambda x: stock_trends.get(x) == st.session_state.trend_filter)]

    if sort_mode == "% Change Up 🟢": df_stocks_display = df_filtered.sort_values(by="C", ascending=False)
    elif sort_mode == "% Change Down 🔴": df_stocks_display = df_filtered.sort_values(by="C", ascending=True)
    else: df_stocks_display = df_filtered.sort_values(by=["S", "VolX", "C"], ascending=[False, False, False])

    # HEATMAP VIEW
    if view_mode == "Heat Map":
        if watchlist_mode == "Terminal Tables 🗃️":
            st.markdown(render_html_table(df_stocks_display.head(15), "🗃️ LIVE TERMINAL RANKING", "term-head-high"), unsafe_allow_html=True)
        else:
            if not df_indices.empty:
                h = '<div class="heatmap-grid">'
                for _, r in df_indices.iterrows():
                    bg = "bear-card" if (r['T']=="INDIA VIX" and r['C']>0) or (r['T']!="INDIA VIX" and r['C']<0) else "bull-card"
                    h += f'<a href="https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(r["Fetch_T"])}" target="_blank" class="stock-card {bg}"><div class="t-score">IDX</div><div class="t-name">{r["T"]}</div><div class="t-price">{r["P"]:.2f}</div><div class="t-pct">{r["C"]:.2f}%</div></a>'
                st.markdown(h + '</div><hr class="custom-hr">', unsafe_allow_html=True)

            if not df_stocks_display.empty:
                h = '<div class="heatmap-grid">'
                for _, r in df_stocks_display.iterrows():
                    bg = "bull-card" if r['C']>0 else "bear-card"
                    ic = "🌊" if watchlist_mode=="Swing Trading 📈" else f"⭐{int(r['S'])}"
                    h += f'<a href="https://in.tradingview.com/chart/?symbol=NSE:{r["T"]}" target="_blank" class="stock-card {bg}"><div class="t-score">{ic}</div><div class="t-name">{r["T"]}</div><div class="t-price">{r["P"]:.2f}</div><div class="t-pct">{r["C"]:.2f}%</div></a>'
                st.markdown(h + '</div>', unsafe_allow_html=True)
                
                st.markdown("<br>", unsafe_allow_html=True)
                with st.expander("🔥 View High Score Radar (Ranked Intraday Table)", expanded=True):
                    st.markdown(render_html_table(df_stocks_display, "🔥 HIGH SCORE RADAR (ALPHA BOOSTED)", "term-head-high"), unsafe_allow_html=True)
            else: st.info(f"No {st.session_state.trend_filter} stocks found.")
            
    # CHART VIEW
    else:
        st.markdown("<br>", unsafe_allow_html=True)
        def render_chart(row, df_chart):
            dsym, fsym = row['T'], row['Fetch_T']
            c_hex = "#da3633" if (dsym=="INDIA VIX" and row['C']>0) or (dsym!="INDIA VIX" and row['C']<0) else "#2ea043"
            link = f"https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(fsym, 'NSE:'+dsym)}"
            if dsym not in ["NIFTY", "BANKNIFTY", "INDIA VIX"]: st.checkbox("pin", value=(fsym in st.session_state.pinned_stocks), key=f"cb_{fsym}", on_change=toggle_pin, args=(fsym,), label_visibility="collapsed")
            st.markdown(f"<div style='text-align:center;'><a href='{link}' target='_blank' style='color:#fff; text-decoration:none;'>{dsym} <span style='color:{c_hex};'>({row['C']:.2f}%)</span></a></div>", unsafe_allow_html=True)
            if not df_chart.empty:
                min_v, max_v = df_chart[['Low','VWAP','EMA_10']].min().min(), df_chart[['High','VWAP','EMA_10']].max().max()
                fig = go.Figure()
                fig.add_trace(go.Candlestick(x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'], increasing_line_color='#2ea043', decreasing_line_color='#da3633'))
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['VWAP'], line=dict(color='#FFD700', width=1.5, dash='dot')))
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA_10'], line=dict(color='#00BFFF', width=1.5, dash='dash')))
                fig.update_layout(margin=dict(l=0,r=0,t=0,b=0), height=150, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis=dict(visible=False), yaxis=dict(visible=False, range=[min_v, max_v]), showlegend=False)
                st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
            else: st.markdown("<div style='height:150px; display:flex; align-items:center; justify-content:center;'>No Data</div>", unsafe_allow_html=True)
            
        st.markdown("<div class='fluid-board'></div>", unsafe_allow_html=True)
        if search_stock != "-- None --":
            with st.container(): render_chart(df[df['T']==search_stock].iloc[0], processed_charts.get(df[df['T']==search_stock]['Fetch_T'].iloc[0], pd.DataFrame()))
        for _, row in df_stocks_display.iterrows():
            with st.container(): render_chart(row, processed_charts.get(row['Fetch_T'], pd.DataFrame()))

else: st.info("Loading Market Data...")
