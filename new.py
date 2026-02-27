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

# --- PORTFOLIO FILE SETUP ---
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
    else:
        df = pd.DataFrame(columns=["Symbol", "Buy_Price", "Quantity", "Date"])
        df['Quantity'], df['Buy_Price'] = df['Quantity'].astype(int), df['Buy_Price'].astype(float)
        return df

def save_portfolio(df_port): df_port.to_csv(PORTFOLIO_FILE, index=False)

# --- 4. CSS FOR STYLING ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {display: none !important;}
    .stApp { background-color: #0e1117; color: #ffffff; }
    .block-container { padding-top: 1rem !important; padding-bottom: 0rem !important; margin-top: -10px; }
    .stRadio label, .stRadio p, div[role="radiogroup"] p { color: #ffffff !important; font-weight: normal !important; }
    div.stButton > button p, div.stButton > button span { color: #ffffff !important; font-weight: normal !important; font-size: 14px !important; }
    .t-name { font-size: 13px; font-weight: normal !important; margin-bottom: 2px; }
    .t-price { font-size: 17px; font-weight: normal !important; margin-bottom: 2px; }
    .t-pct { font-size: 12px; font-weight: normal !important; }
    .t-score { position: absolute; top: 3px; left: 3px; font-size: 10px; background: rgba(0,0,0,0.4); padding: 1px 4px; border-radius: 3px; color: #ffd700; font-weight: normal !important; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) { display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important; justify-content: space-between !important; align-items: center !important; gap: 6px !important; width: 100% !important; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) > div[data-testid="stElementContainer"]:has(.filter-marker) { display: none !important; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) > div[data-testid="stElementContainer"] { flex: 1 1 0px !important; min-width: 0 !important; width: 100% !important; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) div.stButton > button { width: 100% !important; height: 38px !important; padding: 0px !important; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) div.stButton > button p { font-size: clamp(9px, 2.5vw, 13px) !important; white-space: nowrap !important; margin: 0 !important; }
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { display: grid !important; gap: 12px !important; align-items: start !important; }
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div:nth-child(1) { display: none !important; }
    @media screen and (min-width: 1700px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(8, 1fr) !important; } }
    @media screen and (min-width: 1400px) and (max-width: 1699px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(6, 1fr) !important; } }
    @media screen and (min-width: 1100px) and (max-width: 1399px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(5, 1fr) !important; } }
    @media screen and (min-width: 850px) and (max-width: 1099px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(4, 1fr) !important; } }
    @media screen and (min-width: 651px) and (max-width: 849px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(3, 1fr) !important; } }
    @media screen and (max-width: 650px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(2, 1fr) !important; gap: 6px !important; } }
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div[data-testid="stVerticalBlock"] { background-color: #161b22 !important; border: 1px solid #30363d !important; border-radius: 8px !important; padding: 8px 5px 5px 5px !important; position: relative !important; width: 100% !important; }
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div[data-testid="stVerticalBlock"] div[data-testid="stCheckbox"] { position: absolute !important; top: 8px !important; left: 10px !important; z-index: 100 !important; }
    div[data-testid="stCheckbox"] label { padding: 0 !important; min-height: 0 !important; }
    div.stButton > button { border-radius: 8px !important; border: 1px solid #30363d !important; background-color: #161b22 !important; height: 45px !important; }
    .heatmap-grid { display: grid; grid-template-columns: repeat(10, 1fr); gap: 8px; padding: 5px 0; }
    .stock-card { border-radius: 4px; padding: 8px 4px; text-align: center; text-decoration: none !important; color: white !important; display: flex; flex-direction: column; justify-content: center; height: 90px; position: relative; box-shadow: 0 1px 3px rgba(0,0,0,0.3); transition: transform 0.2s; }
    .stock-card:hover { transform: scale(1.05); z-index: 10; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }
    .bull-card { background-color: #1e5f29 !important; } .bear-card { background-color: #b52524 !important; } .neut-card { background-color: #30363d !important; } 
    .idx-card { background-color: #0d47a1 !important; border: 1px solid #1976d2; } 
    @media screen and (max-width: 1400px) { .heatmap-grid { grid-template-columns: repeat(8, 1fr); } }
    @media screen and (max-width: 1100px) { .heatmap-grid { grid-template-columns: repeat(6, 1fr); } }
    @media screen and (max-width: 800px) { .heatmap-grid { grid-template-columns: repeat(4, 1fr); } }
    @media screen and (max-width: 600px) { .heatmap-grid { grid-template-columns: repeat(3, 1fr); gap: 6px; } .stock-card { height: 95px; } .t-name { font-size: 12px; } .t-price { font-size: 16px; } .t-pct { font-size: 11px; } }
    .custom-hr { border: 0; height: 1px; background: #30363d; margin: 15px 0; }
    .term-table { width: 100%; border-collapse: collapse; margin-bottom: 15px; font-family: monospace; font-size: 11.5px; color: #e6edf3; background-color: #0e1117; table-layout: fixed; }
    .term-table th { padding: 6px 4px; text-align: center; border: 1px solid #30363d; font-weight: bold; overflow: hidden; }
    .term-table td { padding: 6px 4px; text-align: center; border: 1px solid #30363d; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .term-table a { color: inherit; text-decoration: none; border-bottom: 1px dashed rgba(255,255,255,0.4); } 
    .term-table a:hover { color: #58a6ff !important; text-decoration: none; border-bottom: 1px solid #58a6ff; } 
    .term-head-buy { background-color: #1e5f29; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
    .term-head-sell { background-color: #b52524; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
    .term-head-ind { background-color: #9e6a03; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
    .term-head-brd { background-color: #0d47a1; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
    .term-head-port { background-color: #4a148c; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
    .term-head-swing { background-color: #005a9e; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
    .term-head-high { background-color: #b71c1c; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
    .term-head-levels { background-color: #004d40; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
    .row-dark { background-color: #161b22; } .row-light { background-color: #0e1117; }
    .text-green { color: #3fb950; font-weight: bold; } .text-red { color: #f85149; font-weight: bold; }
    .t-symbol { text-align: left !important; font-weight: bold; }
    .port-total { background-color: #21262d; font-weight: bold; font-size: 13px; }
    </style>
""", unsafe_allow_html=True)

# --- 5. DATA SETUP & SECTOR MAPPING ---
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
NIFTY_50 = [stock for sector in NIFTY_50_SECTORS.values() for stock in sector] + ["LARSEN", "BAJFINANCE", "ASIANPAINT", "TITAN", "ADANIENT"]
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
    data = yf.download(tkrs, period="1y", progress=False, group_by='ticker', threads=10)
    
    results = []
    minutes = get_minutes_passed()

    # 🔥 NEW: GET NIFTY VWAP DISTANCE FIRST 🔥
    nifty_vwap_dist = 0.05 
    try:
        if '^NSEI' in data.columns.levels[0]:
            ndf = data['^NSEI'].dropna(subset=['Close'])
            if len(ndf) > 0:
                n_ltp = float(ndf['Close'].iloc[-1])
                n_h = float(ndf['High'].iloc[-1])
                n_l = float(ndf['Low'].iloc[-1])
                n_vwap = (n_h + n_l + n_ltp) / 3
                nifty_vwap_dist = abs(n_ltp - n_vwap) / n_vwap * 100
                if nifty_vwap_dist < 0.05: nifty_vwap_dist = 0.05 # Prevent very small Nifty distance from giving false signals
    except: pass

    for symbol in data.columns.levels[0]:
        try:
            df = data[symbol].dropna(subset=['Close'])
            if len(df) < 2: continue
            
            ltp, open_p, prev_c = float(df['Close'].iloc[-1]), float(df['Open'].iloc[-1]), float(df['Close'].iloc[-2])
            prev_h, prev_l = float(df['High'].iloc[-2]), float(df['Low'].iloc[-2])
            low, high = float(df['Low'].iloc[-1]), float(df['High'].iloc[-1])
            day_chg, net_chg = ((ltp - open_p) / open_p) * 100, ((ltp - prev_c) / prev_c) * 100
            
            pivot = (prev_h + prev_l + prev_c) / 3
            r1, s1 = (2 * pivot) - prev_l, (2 * pivot) - prev_h
            r2, s2 = pivot + (prev_h - prev_l), pivot - (prev_h - prev_l)
            
            avg_vol_5d = df['Volume'].iloc[-6:-1].mean() if 'Volume' in df.columns and len(df) >= 6 else 0
            curr_vol = float(df['Volume'].iloc[-1]) if avg_vol_5d > 0 else 0
            vol_x = round(curr_vol / ((avg_vol_5d/375) * minutes), 1) if avg_vol_5d > 0 else 0.0
            vwap = (high + low + ltp) / 3
            stock_vwap_dist = abs(ltp - vwap) / vwap * 100 if vwap > 0 else 0
            
            is_swing = False
            if len(df) >= 50:
                ema20, ema50 = df['Close'].ewm(span=20, adjust=False).mean().iloc[-1], df['Close'].ewm(span=50, adjust=False).mean().iloc[-1]
                delta = df['Close'].diff()
                gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
                loss = -delta.clip(upper=0).ewm(alpha=1/14, adjust=False).mean().replace(0, np.nan)
                current_rsi = (100 - (100 / (1 + (gain / loss)))).fillna(100).iloc[-1]
                avg_vol_10d = df['Volume'].iloc[-11:-1].mean() if len(df) >= 11 else 0
                if (ltp > ema50) and (ema20 > ema50) and (current_rsi >= 55) and (curr_vol > (1.2 * avg_vol_10d)) and (net_chg > 0): is_swing = True

            # 🔥 NEW ALPHA SCORING LOGIC 🔥
            score = 0
            is_alpha = False
            
            # Replaced absolute 2% move with Nifty-Beater Logic
            if stock_vwap_dist > (3 * nifty_vwap_dist) and stock_vwap_dist > 0.3:
                score += 5
                is_alpha = True
            elif stock_vwap_dist > (2 * nifty_vwap_dist) and stock_vwap_dist > 0.2:
                score += 3
                is_alpha = True
                
            if abs(open_p - low) <= (ltp * 0.003) or abs(open_p - high) <= (ltp * 0.003): score += 3 
            if vol_x > 1.0: score += 3 
            if (ltp >= high * 0.998 and day_chg > 0.5) or (ltp <= low * 1.002 and day_chg < -0.5): score += 1
            if (ltp > (low * 1.01) and ltp > vwap) or (ltp < (high * 0.99) and ltp < vwap): score += 1
            
            is_index, is_sector = symbol in INDICES_MAP, symbol in SECTOR_INDICES_MAP
            disp_name = INDICES_MAP.get(symbol, SECTOR_INDICES_MAP.get(symbol, symbol.replace(".NS", "")))
            stock_sector = "OTHER"
            if not is_index and not is_sector:
                for sec, stocks in NIFTY_50_SECTORS.items():
                    if disp_name in stocks: stock_sector = sec; break
                
            results.append({
                "Fetch_T": symbol, "T": disp_name, "P": ltp, "O": open_p, "H": high, "L": low, "Prev_C": prev_c,
                "Day_C": day_chg, "C": net_chg, "S": score, "VolX": vol_x, "Is_Swing": is_swing, "Is_Alpha": is_alpha,
                "Pivot": pivot, "R1": r1, "R2": r2, "S1": s1, "S2": s2,
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
            if 'Volume' in df_day.columns and df_day['Volume'].fillna(0).sum() > 0: df_day['VWAP'] = (df_day['Typical_Price'] * df_day['Volume']).cumsum() / df_day['Volume'].cumsum()
            else: df_day['VWAP'] = df_day['Typical_Price'].expanding().mean()
            return df_day
        return pd.DataFrame()
    except: return pd.DataFrame()

# --- TABLES HTML GENERATORS ---
def generate_status(row):
    status = ""
    p = row['P']
    if row['VolX'] > 1.2: status += "VOL🟢 "
    if abs(row['O'] - row['L']) < (p * 0.002): status += "O=L🔥 "
    if abs(row['O'] - row['H']) < (p * 0.002): status += "O=H🩸 "
    if row.get('Is_Alpha', False): status += "🚀Alpha "
    if 'BounceTag' in row and row['BounceTag']: status += f"{row['BounceTag']} "
    if row['C'] > 0 and row['Day_C'] > 0 and row['VolX'] > 1: status += "Rec ⇈ "
    return status.strip()

def render_html_table(df_subset, title, color_class):
    if df_subset.empty: return ""
    html = f'<table class="term-table"><thead><tr><th colspan="7" class="{color_class}">{title}</th></tr><tr style="background-color: #21262d;"><th style="text-align:left; width:20%;">STOCK</th><th style="width:12%;">PRICE</th><th style="width:12%;">DAY%</th><th style="width:12%;">NET%</th><th style="width:10%;">VOL</th><th style="width:26%;">STATUS</th><th style="width:8%;">SCORE</th></tr></thead><tbody>'
    for i, (_, row) in enumerate(df_subset.iterrows()):
        bg_class, d_col, n_col = "row-dark" if i % 2 == 0 else "row-light", "text-green" if row['Day_C'] >= 0 else "text-red", "text-green" if row['C'] >= 0 else "text-red"
        html += f'<tr class="{bg_class}"><td class="t-symbol {n_col}"><a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank">{row["T"]}</a></td><td>{row["P"]:.2f}</td><td class="{d_col}">{row["Day_C"]:.2f}%</td><td class="{n_col}">{row["C"]:.2f}%</td><td>{row["VolX"]:.1f}x</td><td style="font-size:10px;">{generate_status(row)}</td><td style="color:#ffd700;">{int(row["S"])}</td></tr>'
    return html + "</tbody></table>"

def render_portfolio_table(df_port, df_stocks, stock_trends):
    if df_port.empty: return "<div style='padding:20px; text-align:center; color:#8b949e; border: 1px dashed #30363d; border-radius:8px;'>Portfolio is empty. Add a stock using the option below!</div>"
    html = f'<table class="term-table"><thead><tr><th colspan="10" class="term-head-port">💼 LIVE PORTFOLIO TERMINAL</th></tr><tr style="background-color: #21262d;"><th style="text-align:left; width:11%;">STOCK</th><th style="width:9%;">DATE</th><th style="width:6%;">QTY</th><th style="width:8%;">AVG</th><th style="width:8%;">LTP</th><th style="width:10%;">TREND</th><th style="width:18%;">STATUS</th><th style="width:10%;">DAY P&L</th><th style="width:10%;">TOT P&L</th><th style="width:10%;">P&L %</th></tr></thead><tbody>'
    tot_inv, tot_cur, tot_dpnl = 0, 0, 0
    for i, (_, row) in enumerate(df_port.iterrows()):
        bg_class, sym = "row-dark" if i % 2 == 0 else "row-light", str(row['Symbol']).upper().strip()
        qty, buy_p = float(row.get('Quantity', 0)), float(row.get('Buy_Price', 0))
        date_val = str(row.get('Date', '-')).replace('nan', '-').replace('NaN', '-')
        live_row = df_stocks[df_stocks['T'] == sym]
        if not live_row.empty:
            ltp, prev_c, status_html = float(live_row['P'].iloc[0]), float(live_row['Prev_C'].iloc[0]), generate_status(live_row.iloc[0])
            t_s = stock_trends.get(live_row['Fetch_T'].iloc[0], "Neutral")
            trend_html = "🟢 Bullish" if t_s == 'Bullish' else "🔴 Bearish" if t_s == 'Bearish' else "⚪ Neutral"
        else: ltp, prev_c, status_html, trend_html = buy_p, buy_p, "Search Error", "➖"
        inv, cur = buy_p * qty, ltp * qty
        opnl, dpnl = cur - inv, (ltp - prev_c) * qty
        tot_inv, tot_cur, tot_dpnl = tot_inv + inv, tot_cur + cur, tot_dpnl + dpnl
        t_col, d_col = "text-green" if opnl >= 0 else "text-red", "text-green" if dpnl >= 0 else "text-red"
        html += f'<tr class="{bg_class}"><td class="t-symbol {t_col}"><a href="https://in.tradingview.com/chart/?symbol=NSE:{sym}" target="_blank">{sym}</a></td><td>{date_val}</td><td>{int(qty)}</td><td>{buy_p:.2f}</td><td>{ltp:.2f}</td><td style="font-size:10px;">{trend_html}</td><td style="font-size:10px;">{status_html}</td><td class="{d_col}">{"+" if dpnl>0 else ""}{dpnl:,.0f}</td><td class="{t_col}">{"+" if opnl>0 else ""}{opnl:,.0f}</td><td class="{t_col}">{"+" if opnl>0 else ""}{(opnl/inv*100) if inv>0 else 0:.2f}%</td></tr>'
    o_pnl = tot_cur - tot_inv
    html += f'<tr class="port-total"><td colspan="7" style="text-align:right; padding-right:15px; font-size:12px;">INVESTED: ₹{tot_inv:,.0f} | CURRENT: ₹{tot_cur:,.0f} | OVERALL P&L:</td><td class="{"text-green" if tot_dpnl>=0 else "text-red"}">{"+" if tot_dpnl>0 else ""}₹{tot_dpnl:,.0f}</td><td class="{"text-green" if o_pnl>=0 else "text-red"}">{"+" if o_pnl>0 else ""}₹{o_pnl:,.0f}</td><td class="{"text-green" if o_pnl>=0 else "text-red"}">{"+" if o_pnl>0 else ""}{(o_pnl/tot_inv*100) if tot_inv>0 else 0:.2f}%</td></tr></tbody></table>'
    return html

def render_levels_table(df_subset, stock_trends):
    if df_subset.empty: return ""
    html = f'<table class="term-table"><thead><tr><th colspan="8" class="term-head-levels">🎯 TRADING LEVELS (TARGETS & STOP LOSS)</th></tr><tr style="background-color: #21262d;"><th style="text-align:left; width:15%;">STOCK</th><th style="width:10%;">TREND</th><th style="width:12%;">LTP</th><th style="width:12%;">PIVOT</th><th style="width:12%; color:#f85149;">STOP LOSS</th><th style="width:12%; color:#3fb950;">TARGET 1</th><th style="width:12%; color:#3fb950;">TARGET 2</th><th style="width:15%;">EXTREME TGT/SL</th></tr></thead><tbody>'
    for i, (_, row) in enumerate(df_subset.iterrows()):
        ts = stock_trends.get(row['Fetch_T'], "Neutral")
        is_down = ts == 'Bearish' or (ts == 'Neutral' and row['C'] < 0)
        t_html = "🟢 Bullish" if ts == 'Bullish' else "🔴 Bearish" if ts == 'Bearish' else "⚪ Neutral"
        sl, t1, t2, ext = (row["R1"], row["S1"], row["S2"], row["R2"]) if is_down else (row["S1"], row["R1"], row["R2"], row["S2"])
        html += f'<tr class="{"row-dark" if i%2==0 else "row-light"}"><td class="t-symbol"><a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank">{row["T"]}</a></td><td style="font-size:10px;">{t_html}</td><td>{row["P"]:.2f}</td><td style="color:#8b949e;">{row["Pivot"]:.2f}</td><td style="color:#f85149; font-weight:bold;">{sl:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t1:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t2:.2f}</td><td style="color:#8b949e;">{ext:.2f}</td></tr>'
    return html + "</tbody></table>"

def render_swing_terminal_table(df_subset, stock_trends):
    if df_subset.empty: return "<div style='padding:20px; text-align:center; color:#8b949e; border: 1px dashed #30363d; border-radius:8px;'>No Swing Trading Setups found right now.</div>"
    df_sorted = df_subset.sort_values(by=['S', 'VolX', 'C'], ascending=[False, False, False]).reset_index(drop=True)
    html = f'<table class="term-table"><thead><tr><th colspan="10" class="term-head-swing">🌊 SWING TRADING RADAR (RANKED ALGORITHM)</th></tr><tr style="background-color: #21262d;"><th style="width:5%;">RANK</th><th style="text-align:left; width:13%;">STOCK</th><th style="width:8%;">LTP</th><th style="width:8%;">DAY%</th><th style="width:8%;">VOL</th><th style="width:16%;">STATUS</th><th style="width:11%; color:#f85149;">🛑 STOP LOSS</th><th style="width:11%; color:#3fb950;">🎯 TARGET 1</th><th style="width:11%; color:#3fb950;">🎯 TARGET 2</th><th style="width:9%;">SCORE</th></tr></thead><tbody>'
    for i, row in df_sorted.iterrows():
        ts = stock_trends.get(row['Fetch_T'], "Neutral")
        is_down = ts == 'Bearish' or (ts == 'Neutral' and row['C'] < 0)
        status = generate_status(row) + (" 🟢Trend" if ts == 'Bullish' else " 🔴Trend" if ts == 'Bearish' else "")
        sl, t1, t2 = (row["R1"], row["S1"], row["S2"]) if is_down else (row["S1"], row["R1"], row["R2"])
        html += f'<tr class="{"row-dark" if i%2==0 else "row-light"}"><td><b>{"🏆 1" if i==0 else f"{i+1}"}</b></td><td class="t-symbol"><a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank">{row["T"]}</a></td><td>{row["P"]:.2f}</td><td class="{"text-green" if row["Day_C"]>=0 else "text-red"}">{row["Day_C"]:.2f}%</td><td>{row["VolX"]:.1f}x</td><td style="font-size:10px;">{status}</td><td style="color:#f85149; font-weight:bold;">{sl:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t1:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t2:.2f}</td><td style="color:#ffd700;">{int(row["S"])}</td></tr>'
    return html + "</tbody></table>"

def render_highscore_terminal_table(df_subset, stock_trends):
    if df_subset.empty: return "<div style='padding:20px; text-align:center; color:#8b949e; border: 1px dashed #30363d; border-radius:8px;'>No High Score Stocks found right now.</div>"
    df_sorted = df_subset.sort_values(by=['S', 'VolX', 'C'], ascending=[False, False, False]).reset_index(drop=True)
    html = f'<table class="term-table"><thead><tr><th colspan="10" class="term-head-high">🔥 HIGH SCORE RADAR (RANKED INTRADAY MOVERS)</th></tr><tr style="background-color: #21262d;"><th style="width:5%;">RANK</th><th style="text-align:left; width:13%;">STOCK</th><th style="width:8%;">LTP</th><th style="width:8%;">DAY%</th><th style="width:8%;">VOL</th><th style="width:16%;">STATUS</th><th style="width:11%; color:#f85149;">🛑 STOP LOSS</th><th style="width:11%; color:#3fb950;">🎯 TARGET 1</th><th style="width:11%; color:#3fb950;">🎯 TARGET 2</th><th style="width:9%;">SCORE</th></tr></thead><tbody>'
    for i, row in df_sorted.iterrows():
        ts = stock_trends.get(row['Fetch_T'], "Neutral")
        is_down = ts == 'Bearish' or (ts == 'Neutral' and row['C'] < 0)
        status = generate_status(row) + (" 🟢Trend" if ts == 'Bullish' else " 🔴Trend" if ts == 'Bearish' else "")
        sl, t1, t2 = (row["R1"], row["S1"], row["S2"]) if is_down else (row["S1"], row["R1"], row["R2"])
        html += f'<tr class="{"row-dark" if i%2==0 else "row-light"}"><td><b>{"🏆 1" if i==0 else f"{i+1}"}</b></td><td class="t-symbol"><a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank">{row["T"]}</a></td><td>{row["P"]:.2f}</td><td class="{"text-green" if row["Day_C"]>=0 else "text-red"}">{row["Day_C"]:.2f}%</td><td>{row["VolX"]:.1f}x</td><td style="font-size:10px;">{status}</td><td style="color:#f85149; font-weight:bold;">{sl:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t1:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t2:.2f}</td><td style="color:#ffd700;">{int(row["S"])}</td></tr>'
    return html + "</tbody></table>"

def render_chart(row, df_chart, show_pin=True, key_suffix=""):
    d_sym, f_sym = row['T'], row['Fetch_T']
    color_hex = "#da3633" if (d_sym == "INDIA VIX" and row['C'] > 0) or (d_sym != "INDIA VIX" and row['C'] < 0) else "#2ea043"
    if show_pin and d_sym not in ["NIFTY", "BANKNIFTY", "INDIA VIX"]: st.checkbox("pin", value=(f_sym in st.session_state.pinned_stocks), key=f"cb_{f_sym}_{key_suffix}", on_change=toggle_pin, args=(f_sym,), label_visibility="collapsed")
    st.markdown(f"<div style='text-align:center; font-size:15px; margin-top:2px;'><a href='https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(f_sym, 'NSE:' + d_sym)}' target='_blank' style='color:#ffffff; text-decoration:none;'>{d_sym} <span style='color:{color_hex};'>({'+' if row['C']>0 else ''}{row['C']:.2f}%)</span></a></div><div style='text-align:center; font-size:10px; color:#8b949e; margin-bottom:5px;'><span style='color:#FFD700;'>--- VWAP</span> &nbsp;|&nbsp; <span style='color:#00BFFF;'>- - 10 EMA</span></div>", unsafe_allow_html=True)
    try:
        if not df_chart.empty:
            mi, ma = df_chart[['Low', 'VWAP', 'EMA_10']].min().min(), df_chart[['High', 'VWAP', 'EMA_10']].max().max()
            yp = (ma - mi) * 0.1 if (ma - mi) != 0 else mi * 0.005 
            fig = go.Figure(data=[go.Candlestick(x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'], increasing_line_color='#2ea043', decreasing_line_color='#da3633'), go.Scatter(x=df_chart.index, y=df_chart['VWAP'], mode='lines', line=dict(color='#FFD700', width=1.5, dash='dot')), go.Scatter(x=df_chart.index, y=df_chart['EMA_10'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'))])
            fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=150, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis=dict(visible=False, fixedrange=True), yaxis=dict(visible=False, range=[mi - yp, ma + yp], fixedrange=True), hovermode=False, showlegend=False, dragmode=False)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False, 'staticPlot': True})
        else: st.markdown("<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888;'>Data not available</div>", unsafe_allow_html=True)
    except: st.markdown("<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888;'>Chart error</div>", unsafe_allow_html=True)

def render_chart_grid(df_grid, show_pin_option, key_prefix):
    if df_grid.empty: return
    with st.container():
        st.markdown("<div class='fluid-board'></div>", unsafe_allow_html=True)
        for j, (_, row) in enumerate(df_grid.iterrows()):
            with st.container(): render_chart(row, processed_charts.get(row['Fetch_T'], pd.DataFrame()), show_pin=show_pin_option, key_suffix=f"{key_prefix}_{j}")

# --- 6. TOP NAVIGATION ---
c1, c2, c3 = st.columns([0.4, 0.3, 0.3])
with c1: watchlist_mode = st.selectbox("Watchlist", ["High Score Stocks 🔥", "Swing Trading 📈", "Nifty 50 Heatmap", "One Sided Moves 🚀", "Terminal Tables 🗃️", "My Portfolio 💼"], label_visibility="collapsed")
with c2: sort_mode = st.selectbox("Sort By", ["Custom Sort", "Heatmap Marks Up ⭐", "Heatmap Marks Down ⬇️", "% Change Up 🟢", "% Change Down 🔴"], label_visibility="collapsed")
with c3: view_mode = st.radio("Display", ["Heat Map", "Chart 📈"], horizontal=True, label_visibility="collapsed")

# --- 7. MAIN LOGIC ---
df = fetch_all_data()

if not df.empty:
    all_names = sorted(df[~df['Is_Sector']]['T'].tolist())
    search_stock = st.selectbox("🔍 Search & View Chart", ["-- None --"] + all_names)
    
    df_indices = df[df['Is_Index']].copy().sort_values(by="T", key=lambda x: x.map({"NIFTY": 1, "BANKNIFTY": 2, "INDIA VIX": 3}))
    df_sectors = df[df['Is_Sector']].copy().sort_values(by="C", ascending=False)
    df_stocks = df[(~df['Is_Index']) & (~df['Is_Sector'])].copy()
    
    df_nifty = df_stocks[df_stocks['T'].isin(NIFTY_50)].copy()
    valid_sectors = [s for s in df_nifty.groupby('Sector')['C'].mean().sort_values(ascending=False).index if s != "OTHER"]
    top_buy_sector, top_sell_sector = (valid_sectors[0], valid_sectors[-1]) if valid_sectors else ("PHARMA", "IT")
        
    df_buy_sector = df_nifty[df_nifty['Sector'] == top_buy_sector].sort_values(by=['S', 'C'], ascending=[False, False])
    df_sell_sector = df_nifty[df_nifty['Sector'] == top_sell_sector].sort_values(by=['S', 'C'], ascending=[False, True])
    df_independent = df_nifty[(~df_nifty['Sector'].isin([top_buy_sector, top_sell_sector])) & (df_nifty['S'] >= 6)].sort_values(by='S', ascending=False).head(8)
    df_broader = df_stocks[(df_stocks['T'].isin(BROADER_MARKET)) & (df_stocks['S'] >= 6)].sort_values(by='S', ascending=False).head(8)
    df_port_saved = load_portfolio()

    if watchlist_mode == "Terminal Tables 🗃️": df_filtered = df_stocks[df_stocks['Fetch_T'].isin(pd.concat([df_buy_sector, df_sell_sector, df_independent, df_broader])['Fetch_T'].unique())]
    elif watchlist_mode == "My Portfolio 💼": df_filtered = df_stocks[df_stocks['Fetch_T'].isin([f"{str(sym).upper().strip()}.NS" for sym in df_port_saved['Symbol'].tolist() if str(sym).strip() != ""])]
    elif watchlist_mode == "Nifty 50 Heatmap": df_filtered = df_stocks[df_stocks['T'].isin(NIFTY_50)]
    elif watchlist_mode == "One Sided Moves 🚀": df_filtered = df_stocks[df_stocks['C'].abs() >= 1.0]
    elif watchlist_mode == "Swing Trading 📈": df_filtered = df_stocks[df_stocks['Is_Swing'] == True]
    else: df_filtered = df_stocks[(df_stocks['S'] >= 6)]

    all_display_tickers = list(set(df_indices['Fetch_T'].tolist() + df_filtered['Fetch_T'].tolist() + st.session_state.pinned_stocks))
    if search_stock != "-- None --": 
        s_f_t = df[df['T'] == search_stock]['Fetch_T'].iloc[0]
        if s_f_t not in all_display_tickers: all_display_tickers.append(s_f_t)
            
    with st.spinner("Analyzing VWAP & EMA Intraday Pullbacks (Sniper Mode)..."):
        five_min_data = yf.download(all_display_tickers, period="5d", interval="5m", progress=False, group_by='ticker', threads=False)

    processed_charts, stock_trends, bounce_tags, bounce_scores = {}, {}, {}, {}

    for sym in all_display_tickers:
        df_raw = five_min_data[sym] if isinstance(five_min_data.columns, pd.MultiIndex) else five_min_data
        df_day = process_5m_data(df_raw)
        processed_charts[sym] = df_day
        
        if sym in df_filtered['Fetch_T'].tolist() and not df_day.empty:
            last_price, last_vwap, last_ema = df_day['Close'].iloc[-1], df_day['VWAP'].iloc[-1], df_day['EMA_10'].iloc[-1]
            net_chg = df[df['Fetch_T'] == sym]['C'].iloc[0]
            base_score = int(df_filtered[df_filtered['Fetch_T'] == sym]['S'].iloc[0])
            tag, b_score = "", 0
            
            if len(df_day) >= 50 and base_score >= 6: 
                ema10, ema20, ema50, vwap = df_day['EMA_10'].iloc[-1], df_day['EMA_20'].iloc[-1], df_day['EMA_50'].iloc[-1], df_day['VWAP'].iloc[-1]
                if net_chg > 0: 
                    if (ema10 >= ema20) and (ema20 >= ema50):
                        d50 = (last_price - ema50) / ema50 * 100 if ema50 > 0 else -1
                        dvw = (last_price - vwap) / vwap * 100 if vwap > 0 else -1
                        d20 = (last_price - ema20) / ema20 * 100 if ema20 > 0 else -1
                        d10 = (last_price - ema10) / ema10 * 100 if ema10 > 0 else -1
                        if 0 <= d50 <= 0.4: tag, b_score = "🔥50EMA-Bounce", 5
                        elif 0 <= dvw <= 0.4: tag, b_score = "🔥VWAP-Bounce", 5
                        elif 0 <= d20 <= 0.4: tag, b_score = "🔥20EMA-Bounce", 5
                        elif 0 <= d10 <= 0.3: tag, b_score = "🔥10EMA-Bounce", 5
                else: 
                    if (ema10 <= ema20) and (ema20 <= ema50):
                        d50 = (ema50 - last_price) / last_price * 100 if last_price > 0 else -1
                        dvw = (vwap - last_price) / last_price * 100 if last_price > 0 else -1
                        d20 = (ema20 - last_price) / last_price * 100 if last_price > 0 else -1
                        d10 = (ema10 - last_price) / last_price * 100 if last_price > 0 else -1
                        if 0 <= d50 <= 0.4: tag, b_score = "🩸50EMA-Reject", 5
                        elif 0 <= dvw <= 0.4: tag, b_score = "🩸VWAP-Reject", 5
                        elif 0 <= d20 <= 0.4: tag, b_score = "🩸20EMA-Reject", 5
                        elif 0 <= d10 <= 0.3: tag, b_score = "🩸10EMA-Reject", 5

            bounce_tags[sym], bounce_scores[sym] = tag, b_score
            stock_trends[sym] = 'Bullish' if (net_chg > 0 and last_price >= last_vwap) else 'Bearish' if (net_chg < 0 and last_price <= last_vwap) else 'Neutral'

    if not df_filtered.empty:
        df_filtered['BounceTag'] = df_filtered['Fetch_T'].map(bounce_tags).fillna("")
        df_filtered['S'] = df_filtered.apply(lambda row: row['S'] + bounce_scores.get(row['Fetch_T'], 0), axis=1)

    if watchlist_mode == "One Sided Moves 🚀":
        one_sided = []
        for sym, d_d in processed_charts.items():
            if not d_d.empty and len(d_d) >= 3 and stock_trends.get(sym) != 'Neutral':
                cond = (d_d['Close'] > d_d['VWAP']) & (d_d['Close'] > d_d['EMA_10']) if stock_trends[sym] == 'Bullish' else (d_d['Close'] < d_d['VWAP']) & (d_d['Close'] < d_d['EMA_10'])
                if (cond.sum() / len(d_d)) >= 0.70: one_sided.append(sym)
        df_filtered = df_filtered[df_filtered['Fetch_T'].isin(one_sided)]

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

    if st.session_state.trend_filter != 'All': df_filtered = df_filtered[df_filtered['Fetch_T'].apply(lambda x: stock_trends.get(x) == st.session_state.trend_filter)]

    if sort_mode == "% Change Up 🟢": df_stocks_display = df_filtered.sort_values(by="C", ascending=False)
    elif sort_mode == "% Change Down 🔴": df_stocks_display = df_filtered.sort_values(by="C", ascending=True)
    elif sort_mode == "Heatmap Marks Up ⭐": df_stocks_display = pd.concat([df_filtered[df_filtered['C'] >= 0].sort_values(by=["S", "C"], ascending=[False, False]), df_filtered[df_filtered['C'] < 0].sort_values(by=["S", "C"], ascending=[False, True])])
    elif sort_mode == "Heatmap Marks Down ⬇️": df_stocks_display = pd.concat([df_filtered[df_filtered['C'] < 0].sort_values(by=["S", "C"], ascending=[False, True]), df_filtered[df_filtered['C'] >= 0].sort_values(by=["S", "C"], ascending=[False, False])])
    else: df_stocks_display = df_filtered.sort_values(by=["S", "C"], ascending=[False, False]) if st.session_state.trend_filter in ['Bullish', 'Neutral'] else df_filtered.sort_values(by=["S", "C"], ascending=[False, True]) if st.session_state.trend_filter == 'Bearish' else pd.concat([df_filtered[df_filtered['C'] >= 0].sort_values(by=["S", "C"], ascending=[False, False]), df_filtered[df_filtered['C'] < 0].sort_values(by=["S", "C"], ascending=[True, True])])

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
        st.markdown(render_portfolio_table(df_port_saved, df_stocks, stock_trends), unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("➕ Search & Add Stock to Portfolio", expanded=False):
            with st.form("portfolio_add_form", clear_on_submit=True):
                c1, c2, c3, c4, c5 = st.columns([2.5, 1.5, 2, 2, 2])
                new_sym = c1.text_input("🔍 NSE Symbol", placeholder="Type Symbol...").upper().strip()
                new_qty = c2.number_input("📦 Quantity", min_value=1, value=10)
                new_price = c3.number_input("💰 Buy Price (₹)", min_value=0.0, value=100.0)
                new_date = c4.date_input("📅 Purchase Date")
                c5.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
                if c5.form_submit_button("➕ Verify & Add", use_container_width=True):
                    if new_sym:
                        chk_data = yf.download(f"{new_sym}.NS", period="1d", progress=False)
                        if chk_data.empty: st.error(f"❌ '{new_sym}' not found in NSE!")
                        else:
                            new_date_str = new_date.strftime("%d-%b-%Y")
                            if new_sym in df_port_saved['Symbol'].values: df_port_saved.loc[df_port_saved['Symbol'] == new_sym, ['Buy_Price', 'Quantity', 'Date']] = [new_price, new_qty, new_date_str]
                            else: df_port_saved = pd.concat([df_port_saved, pd.DataFrame({"Symbol": [new_sym], "Buy_Price": [new_price], "Quantity": [new_qty], "Date": [new_date_str]})], ignore_index=True)
                            save_portfolio(df_port_saved)
                            fetch_all_data.clear()
                            st.rerun()
                    else: st.warning("Type a symbol first!")
        if not df_port_saved.empty:
            with st.expander("✏️ Edit Existing Holdings", expanded=False):
                edited_df = st.data_editor(df_port_saved, use_container_width=True, hide_index=True, column_config={"Symbol": st.column_config.TextColumn(disabled=True), "Quantity": st.column_config.NumberColumn(min_value=1, step=1), "Buy_Price": st.column_config.NumberColumn(min_value=0.0, format="%.2f")})
                if st.button("💾 Save Edited Changes", use_container_width=True): save_portfolio(edited_df); fetch_all_data.clear(); st.rerun()
            with st.expander("🗑️ Remove Stock from Portfolio", expanded=False):
                with st.form("portfolio_remove_form"):
                    rc1, rc2, rc3 = st.columns([3, 2, 5])
                    del_sym = rc1.selectbox("Select Stock", ["-- Select --"] + df_port_saved['Symbol'].tolist(), label_visibility="collapsed")
                    if rc2.form_submit_button("❌ Remove", use_container_width=True) and del_sym != "-- Select --":
                        save_portfolio(df_port_saved[df_port_saved['Symbol'] != del_sym])
                        fetch_all_data.clear()
                        st.rerun()

    elif view_mode == "Heat Map":
        if not df_indices.empty:
            html_idx = '<div class="heatmap-grid">'
            for _, row in df_indices.iterrows(): html_idx += f'<a href="https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(row["Fetch_T"])}" target="_blank" class="stock-card {"bear-card" if (row["T"] == "INDIA VIX" and row["C"] > 0) or (row["T"] != "INDIA VIX" and row["C"] < 0) else ("bull-card" if row["C"] > 0 else "neut-card")}"><div class="t-score">IDX</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{"+" if row["C"]>0 else ""}{row["C"]:.2f}%</div></a>'
            st.markdown(html_idx + '</div><hr class="custom-hr">', unsafe_allow_html=True)
        
        if not df_sectors.empty:
            html_sec = '<div class="heatmap-grid">'
            for _, row in df_sectors.iterrows(): html_sec += f'<a href="https://in.tradingview.com/chart/?symbol={TV_SECTOR_URL.get(row["Fetch_T"], "")}" target="_blank" class="stock-card {"bull-card" if row["C"] > 0 else ("bear-card" if row["C"] < 0 else "neut-card")}"><div class="t-score" style="color:#00BFFF;">SEC</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{"+" if row["C"]>0 else ""}{row["C"]:.2f}%</div></a>'
            st.markdown(html_sec + '</div><hr class="custom-hr">', unsafe_allow_html=True)

        if not df_stocks_display.empty:
            html_stk = '<div class="heatmap-grid">'
            for _, row in df_stocks_display.iterrows(): html_stk += f'<a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank" class="stock-card {"bull-card" if row["C"] > 0 else ("bear-card" if row["C"] < 0 else "neut-card")}"><div class="t-score">{"🌊" if watchlist_mode == "Swing Trading 📈" else ("🚀" if watchlist_mode == "One Sided Moves 🚀" else f"⭐{int(row['S'])}")}</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{"+" if row["C"]>0 else ""}{row["C"]:.2f}%</div></a>'
            st.markdown(html_stk + '</div><br>', unsafe_allow_html=True)
            
            if watchlist_mode == "Swing Trading 📈":
                with st.expander("🌊 View Swing Trading Radar (Ranked Table)", expanded=True): st.markdown(render_swing_terminal_table(df_stocks_display, stock_trends), unsafe_allow_html=True)
            elif watchlist_mode == "High Score Stocks 🔥":
                with st.expander("🔥 View High Score Radar (Ranked Intraday Table)", expanded=True): st.markdown(render_highscore_terminal_table(df_stocks_display, stock_trends), unsafe_allow_html=True)
            else:
                with st.expander("🎯 View Trading Levels (Targets & Stop Loss)", expanded=True): st.markdown(render_levels_table(df_stocks_display, stock_trends), unsafe_allow_html=True)
        else: st.info(f"No {st.session_state.trend_filter} stocks found.")
            
    else:
        st.markdown("<br>", unsafe_allow_html=True)
        if search_stock != "-- None --":
            st.markdown(f"<div style='font-size:18px; font-weight:bold; margin-bottom:5px; color:#ffd700;'>🔍 Searched Chart: {search_stock}</div>", unsafe_allow_html=True)
            render_chart_grid(pd.DataFrame([df[df['T'] == search_stock].iloc[0]]), show_pin_option=True, key_prefix="search")
            st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        if watchlist_mode not in ["Terminal Tables 🗃️", "My Portfolio 💼"]:
            st.markdown("<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#e6edf3;'>📈 Market Indices</div>", unsafe_allow_html=True)
            render_chart_grid(df_indices, show_pin_option=False, key_prefix="idx")
            st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        pinned_df = df[df['Fetch_T'].isin(st.session_state.pinned_stocks)].copy()
        unpinned_df = df_stocks_display[~df_stocks_display['Fetch_T'].isin(pinned_df['Fetch_T'].tolist())]
        
        if not pinned_df.empty:
            st.markdown("<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#ffd700;'>📌 Pinned Priority Charts</div>", unsafe_allow_html=True)
            render_chart_grid(pinned_df, show_pin_option=True, key_prefix="pin")
            st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        if not unpinned_df.empty:
            st.markdown(f"<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#e6edf3;'>{watchlist_mode} ({st.session_state.trend_filter})</div>", unsafe_allow_html=True)
            render_chart_grid(unpinned_df, show_pin_option=True, key_prefix="main")

else: st.info("Loading Market Data...")
