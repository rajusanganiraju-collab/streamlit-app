import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
import os
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Market Heatmap", page_icon="📊", layout="wide")

# --- 2. AUTO RUN (1 MINUTE) ---
st_autorefresh(interval=60000, key="datarefresh")

# --- 3. STATE MANAGEMENT FOR FILTERING & PINNING ---
if 'trend_filter' not in st.session_state:
    st.session_state.trend_filter = 'All'
if 'pinned_stocks' not in st.session_state:
    st.session_state.pinned_stocks = []

def toggle_pin(symbol):
    if symbol in st.session_state.pinned_stocks:
        st.session_state.pinned_stocks.remove(symbol)
    else:
        st.session_state.pinned_stocks.append(symbol)

# --- PORTFOLIO FILE SETUP ---
PORTFOLIO_FILE = "my_portfolio.csv"
def load_portfolio():
    if os.path.exists(PORTFOLIO_FILE):
        return pd.read_csv(PORTFOLIO_FILE)
    else:
        return pd.DataFrame(columns=["Symbol", "Buy_Price", "Quantity", "Date"])

def save_portfolio(df_port):
    df_port.to_csv(PORTFOLIO_FILE, index=False)

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
    
    /* HORIZONTAL BUTTONS FIX */
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) {
        display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important; 
        justify-content: space-between !important; align-items: center !important; gap: 6px !important; width: 100% !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) > div[data-testid="stElementContainer"]:has(.filter-marker) { display: none !important; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) > div[data-testid="stElementContainer"] {
        flex: 1 1 0px !important; min-width: 0 !important; width: 100% !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) div.stButton > button { width: 100% !important; height: 38px !important; padding: 0px !important; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) div.stButton > button p { font-size: clamp(9px, 2.5vw, 13px) !important; white-space: nowrap !important; margin: 0 !important; }
    
    /* FLUID GRID FOR CHARTS */
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { display: grid !important; gap: 12px !important; align-items: start !important; }
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div:nth-child(1) { display: none !important; }
    @media screen and (min-width: 1700px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(8, 1fr) !important; } }
    @media screen and (min-width: 1400px) and (max-width: 1699px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(6, 1fr) !important; } }
    @media screen and (min-width: 1100px) and (max-width: 1399px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(5, 1fr) !important; } }
    @media screen and (min-width: 850px) and (max-width: 1099px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(4, 1fr) !important; } }
    @media screen and (min-width: 651px) and (max-width: 849px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(3, 1fr) !important; } }
    @media screen and (max-width: 650px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(2, 1fr) !important; gap: 6px !important; } }
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div[data-testid="stVerticalBlock"] {
        background-color: #161b22 !important; border: 1px solid #30363d !important; border-radius: 8px !important;
        padding: 8px 5px 5px 5px !important; position: relative !important; width: 100% !important;
    }

    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div[data-testid="stVerticalBlock"] div[data-testid="stCheckbox"] {
        position: absolute !important; top: 8px !important; left: 10px !important; z-index: 100 !important;
    }
    div[data-testid="stCheckbox"] label { padding: 0 !important; min-height: 0 !important; }
    div.stButton > button { border-radius: 8px !important; border: 1px solid #30363d !important; background-color: #161b22 !important; height: 45px !important; }
    
    /* Heatmap Layout */
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

    /* 🔥 TERMINAL & PORTFOLIO TABLE STYLES 🔥 */
    .term-table { width: 100%; border-collapse: collapse; margin-bottom: 15px; font-family: monospace; font-size: 11.5px; color: #e6edf3; background-color: #0e1117; table-layout: fixed; }
    .term-table th { padding: 6px 4px; text-align: center; border: 1px solid #30363d; font-weight: bold; overflow: hidden; }
    .term-table td { padding: 6px 4px; text-align: center; border: 1px solid #30363d; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .term-head-buy { background-color: #1e5f29; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
    .term-head-sell { background-color: #b52524; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
    .term-head-ind { background-color: #9e6a03; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
    .term-head-brd { background-color: #0d47a1; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
    .term-head-port { background-color: #4a148c; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
    .row-dark { background-color: #161b22; } .row-light { background-color: #0e1117; }
    .text-green { color: #3fb950; font-weight: bold; } .text-red { color: #f85149; font-weight: bold; }
    .t-symbol { text-align: left !important; font-weight: bold; }
    .port-total { background-color: #21262d; font-weight: bold; font-size: 13px; }
    </style>
""", unsafe_allow_html=True)

# --- 5. DATA SETUP & SECTOR MAPPING ---
INDICES_MAP = {"^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY", "^INDIAVIX": "INDIA VIX"}
TV_INDICES_URL = {"^NSEI": "NSE:NIFTY", "^NSEBANK": "NSE:BANKNIFTY", "^INDIAVIX": "NSE:INDIAVIX"}

SECTOR_INDICES_MAP = {
    "^CNXIT": "NIFTY IT", "^CNXAUTO": "NIFTY AUTO", "^CNXMETAL": "NIFTY METAL",
    "^CNXPHARMA": "NIFTY PHARMA", "^CNXFMCG": "NIFTY FMCG", "^CNXENERGY": "NIFTY ENERGY", "^CNXREALTY": "NIFTY REALTY"
}

TV_SECTOR_URL = {
    "^CNXIT": "NSE:CNXIT", "^CNXAUTO": "NSE:CNXAUTO", "^CNXMETAL": "NSE:CNXMETAL",
    "^CNXPHARMA": "NSE:CNXPHARMA", "^CNXFMCG": "NSE:CNXFMCG", "^CNXENERGY": "NSE:CNXENERGY", "^CNXREALTY": "NSE:CNXREALTY"
}

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
BROADER_MARKET = ["HAL", "BDL", "MAZDOCK", "RVNL", "IRFC", "BHEL", "CGPOWER", "SUZLON", "PFC", "RECLTD", "DIXON", "POLYCAB", "KAYNES", "ZOMATO", "DMART", "MANAPPURAM", "MUTHOOTFIN", "KEI"]

def get_minutes_passed():
    now = datetime.now()
    if now.weekday() >= 5 or now.time() > dt_time(15, 30): return 375
    open_time = now.replace(hour=9, minute=15, second=0)
    return min(375, max(1, int((now - open_time).total_seconds() / 60)))

@st.cache_data(ttl=60)
def fetch_all_data():
    port_df = load_portfolio()
    # Pull dynamic portfolio stocks
    port_stocks = [str(sym).upper().strip() for sym in port_df['Symbol'].tolist() if str(sym).strip() != ""]
    
    all_stocks = set(NIFTY_50 + BROADER_MARKET + port_stocks)
    tkrs = list(INDICES_MAP.keys()) + list(SECTOR_INDICES_MAP.keys()) + [f"{t}.NS" for t in all_stocks if t]
    data = yf.download(tkrs, period="5d", progress=False, group_by='ticker', threads=20)
    
    results = []
    minutes = get_minutes_passed()

    for symbol in data.columns.levels[0]:
        try:
            df = data[symbol].dropna(subset=['Close'])
            if len(df) < 2: continue
            
            ltp = float(df['Close'].iloc[-1])
            open_p = float(df['Open'].iloc[-1])
            prev_c = float(df['Close'].iloc[-2])
            low = float(df['Low'].iloc[-1])
            high = float(df['High'].iloc[-1])
            
            day_chg = ((ltp - open_p) / open_p) * 100
            net_chg = ((ltp - prev_c) / prev_c) * 100
            
            if 'Volume' in df.columns and not df['Volume'].isna().all():
                avg_vol = df['Volume'].iloc[:-1].mean()
                curr_vol = float(df['Volume'].iloc[-1])
                vol_x = round(curr_vol / ((avg_vol/375) * minutes), 1) if avg_vol > 0 else 0.0
            else: vol_x = 0.0
                
            vwap = (high + low + ltp) / 3
            score = 0
            if abs(day_chg) >= 2.0: score += 3 
            if abs(open_p - low) <= (ltp * 0.003) or abs(open_p - high) <= (ltp * 0.003): score += 3 
            if vol_x > 1.0: score += 3 
            if (ltp >= high * 0.998 and day_chg > 0.5) or (ltp <= low * 1.002 and day_chg < -0.5): score += 1
            if (ltp > (low * 1.01) and ltp > vwap) or (ltp < (high * 0.99) and ltp < vwap): score += 1
            
            is_index = symbol in INDICES_MAP
            is_sector = symbol in SECTOR_INDICES_MAP
            disp_name = INDICES_MAP.get(symbol, SECTOR_INDICES_MAP.get(symbol, symbol.replace(".NS", "")))
            
            stock_sector = "OTHER"
            if not is_index and not is_sector:
                for sec, stocks in NIFTY_50_SECTORS.items():
                    if disp_name in stocks:
                        stock_sector = sec
                        break
                
            results.append({
                "Fetch_T": symbol, "T": disp_name, "P": ltp, "O": open_p, "H": high, "L": low, "Prev_C": prev_c,
                "Day_C": day_chg, "C": net_chg, "S": score, "VolX": vol_x,
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
    status = ""
    p = row['P']
    if row['VolX'] > 1.2: status += "VOL🟢 "
    if abs(row['O'] - row['L']) < (p * 0.002): status += "O=L🔥 "
    if abs(row['O'] - row['H']) < (p * 0.002): status += "O=H🩸 "
    if abs(row['C']) >= 2.0: status += "BigMove🚀 " if row['C'] > 0 else "BigMove🩸 "
    if row['C'] > 0 and row['Day_C'] > 0 and row['VolX'] > 1: status += "Rec ⇈ "
    return status.strip()

def render_html_table(df_subset, title, color_class):
    if df_subset.empty: return ""
    html = f'<table class="term-table"><thead><tr><th colspan="7" class="{color_class}">{title}</th></tr><tr style="background-color: #21262d;"><th style="text-align:left; width:20%;">STOCK</th><th style="width:12%;">PRICE</th><th style="width:12%;">DAY%</th><th style="width:12%;">NET%</th><th style="width:10%;">VOL</th><th style="width:26%;">STATUS</th><th style="width:8%;">SCORE</th></tr></thead><tbody>'
    for i, (_, row) in enumerate(df_subset.iterrows()):
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        day_color = "text-green" if row['Day_C'] >= 0 else "text-red"
        net_color = "text-green" if row['C'] >= 0 else "text-red"
        status = generate_status(row)
        html += f'<tr class="{bg_class}"><td class="t-symbol {net_color}">{row["T"]}</td><td>{row["P"]:.2f}</td><td class="{day_color}">{row["Day_C"]:.2f}%</td><td class="{net_color}">{row["C"]:.2f}%</td><td>{row["VolX"]:.1f}x</td><td style="font-size:10px;">{status}</td><td style="color:#ffd700;">{int(row["S"])}</td></tr>'
    html += "</tbody></table>"
    return html

# 🔥 NEW: COLORFUL TERMINAL PORTFOLIO TABLE 🔥
def render_portfolio_table(df_port, df_stocks, stock_trends):
    if df_port.empty: return "<div style='padding:20px; text-align:center; color:#8b949e; border: 1px dashed #30363d; border-radius:8px;'>Portfolio is empty. Add a stock using the search bar above!</div>"
    
    html = f'<table class="term-table"><thead><tr><th colspan="9" class="term-head-port">💼 LIVE PORTFOLIO TERMINAL</th></tr><tr style="background-color: #21262d;"><th style="text-align:left; width:13%;">STOCK</th><th style="width:7%;">QTY</th><th style="width:9%;">AVG</th><th style="width:9%;">LTP</th><th style="width:11%;">TREND</th><th style="width:20%;">STATUS</th><th style="width:10%;">DAY P&L</th><th style="width:11%;">TOT P&L</th><th style="width:10%;">P&L %</th></tr></thead><tbody>'
    
    total_invested = 0
    total_current = 0
    total_day_pnl = 0
    
    for i, (_, row) in enumerate(df_port.iterrows()):
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        sym = str(row['Symbol']).upper().strip()
        qty = float(row['Quantity'])
        buy_p = float(row['Buy_Price'])
        
        live_row = df_stocks[df_stocks['T'] == sym]
        status_html = ""
        trend_html = "➖"
        
        if not live_row.empty:
            ltp = float(live_row['P'].iloc[0])
            prev_c = float(live_row['Prev_C'].iloc[0])
            status_html = generate_status(live_row.iloc[0])
            
            fetch_t = live_row['Fetch_T'].iloc[0]
            trend_state = stock_trends.get(fetch_t, "Neutral")
            if trend_state == 'Bullish': trend_html = "🟢 Bullish"
            elif trend_state == 'Bearish': trend_html = "🔴 Bearish"
            else: trend_html = "⚪ Neutral"
        else:
            ltp = buy_p
            prev_c = buy_p
            status_html = "Search Error"
            
        invested = buy_p * qty
        current = ltp * qty
        overall_pnl = current - invested
        pnl_pct = (overall_pnl / invested * 100) if invested > 0 else 0
        day_pnl = (ltp - prev_c) * qty
        
        total_invested += invested
        total_current += current
        total_day_pnl += day_pnl
        
        tpnl_color = "text-green" if overall_pnl >= 0 else "text-red"
        dpnl_color = "text-green" if day_pnl >= 0 else "text-red"
        t_sign = "+" if overall_pnl > 0 else ""
        d_sign = "+" if day_pnl > 0 else ""
        
        html += f'<tr class="{bg_class}"><td class="t-symbol {tpnl_color}">{sym}</td><td>{int(qty)}</td><td>{buy_p:.2f}</td><td>{ltp:.2f}</td><td style="font-size:10px;">{trend_html}</td><td style="font-size:10px;">{status_html}</td><td class="{dpnl_color}">{d_sign}{day_pnl:,.0f}</td><td class="{tpnl_color}">{t_sign}{overall_pnl:,.0f}</td><td class="{tpnl_color}">{t_sign}{pnl_pct:.2f}%</td></tr>'
    
    overall_total_pnl = total_current - total_invested
    overall_total_pct = (overall_total_pnl / total_invested * 100) if total_invested > 0 else 0
    o_color = "text-green" if overall_total_pnl >= 0 else "text-red"
    o_sign = "+" if overall_total_pnl > 0 else ""
    d_color = "text-green" if total_day_pnl >= 0 else "text-red"
    d_sign = "+" if total_day_pnl > 0 else ""
    
    html += f'<tr class="port-total"><td colspan="6" style="text-align:right; padding-right:15px; font-size:12px;">INVESTED: ₹{total_invested:,.0f} &nbsp;|&nbsp; CURRENT: ₹{total_current:,.0f} &nbsp;|&nbsp; OVERALL P&L:</td><td class="{d_color}">{d_sign}₹{total_day_pnl:,.0f}</td><td class="{o_color}">{o_sign}₹{overall_total_pnl:,.0f}</td><td class="{o_color}">{o_sign}{overall_total_pct:.2f}%</td></tr>'
    html += "</tbody></table>"
    return html

# --- HELPER FUNCTION TO DRAW CHARTS ---
def render_chart(row, df_chart, show_pin=True, key_suffix=""):
    display_sym = row['T']
    fetch_sym = row['Fetch_T']
    color_hex = "#da3633" if (display_sym == "INDIA VIX" and row['C'] > 0) or (display_sym != "INDIA VIX" and row['C'] < 0) else "#2ea043"
    sign = "+" if row['C'] > 0 else ""
    tv_link = f"https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(fetch_sym, 'NSE:' + display_sym)}"
    
    if show_pin and display_sym not in ["NIFTY", "BANKNIFTY", "INDIA VIX"]:
        cb_key = f"cb_{fetch_sym}_{key_suffix}" if key_suffix else f"cb_{fetch_sym}"
        st.checkbox("pin", value=(fetch_sym in st.session_state.pinned_stocks), key=cb_key, on_change=toggle_pin, args=(fetch_sym,), label_visibility="collapsed")
    
    st.markdown(f"""
        <div style='text-align:center; font-size:15px; margin-top:2px;'>
            <a href='{tv_link}' target='_blank' style='color:#ffffff; text-decoration:none;'>
                {display_sym} <span style='color:{color_hex};'>({sign}{row['C']:.2f}%)</span>
            </a>
        </div>
        <div style='text-align:center; font-size:10px; color:#8b949e; margin-bottom:5px;'>
            <span style='color:#FFD700;'>--- VWAP</span> &nbsp;|&nbsp; <span style='color:#00BFFF;'>- - 10 EMA</span>
        </div>
    """, unsafe_allow_html=True)
    
    try:
        if not df_chart.empty:
            min_val, max_val = df_chart[['Low', 'VWAP', 'EMA_10']].min().min(), df_chart[['High', 'VWAP', 'EMA_10']].max().max()
            y_padding = (max_val - min_val) * 0.1 if (max_val - min_val) != 0 else min_val * 0.005 
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'], increasing_line_color='#2ea043', decreasing_line_color='#da3633'))
            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['VWAP'], mode='lines', line=dict(color='#FFD700', width=1.5, dash='dot')))
            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA_10'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash')))
            fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=150, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis=dict(visible=False, fixedrange=True), yaxis=dict(visible=False, range=[min_val - y_padding, max_val + y_padding], fixedrange=True), hovermode=False, showlegend=False, dragmode=False)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False, 'staticPlot': True})
        else: st.markdown("<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888;'>Data not available</div>", unsafe_allow_html=True)
    except: st.markdown("<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888;'>Chart error</div>", unsafe_allow_html=True)

def render_chart_grid(df_grid, show_pin_option, key_prefix):
    if df_grid.empty: return
    with st.container():
        st.markdown("<div class='fluid-board'></div>", unsafe_allow_html=True)
        for j, (_, row) in enumerate(df_grid.iterrows()):
            with st.container():
                render_chart(row, processed_charts.get(row['Fetch_T'], pd.DataFrame()), show_pin=show_pin_option, key_suffix=f"{key_prefix}_{j}")


# --- 6. TOP NAVIGATION & SEARCH ---
c1, c2, c3 = st.columns([0.4, 0.3, 0.3])
with c1: 
    watchlist_mode = st.selectbox("Watchlist", ["High Score Stocks 🔥", "Nifty 50 Heatmap", "One Sided Moves 🚀", "Terminal Tables 🗃️", "My Portfolio 💼"], label_visibility="collapsed")
with c2: 
    sort_mode = st.selectbox("Sort By", ["Custom Sort", "Heatmap Marks Up ⭐", "Heatmap Marks Down ⬇️", "% Change Up 🟢", "% Change Down 🔴"], label_visibility="collapsed")
with c3: 
    view_mode = st.radio("Display", ["Heat Map", "Chart 📈"], horizontal=True, label_visibility="collapsed")


# --- 7. RENDER LOGIC & TREND ANALYSIS ---
df = fetch_all_data()

if not df.empty:
    all_names = sorted(df[~df['Is_Sector']]['T'].tolist())
    search_stock = st.selectbox("🔍 Search & View Chart", ["-- None --"] + all_names)
    
    df_indices = df[df['Is_Index']].copy()
    df_indices['Order'] = df_indices['T'].map({"NIFTY": 1, "BANKNIFTY": 2, "INDIA VIX": 3})
    df_indices = df_indices.sort_values("Order")
    
    df_sectors = df[df['Is_Sector']].copy()
    df_sectors = df_sectors.sort_values(by="C", ascending=False)
    
    df_stocks = df[(~df['Is_Index']) & (~df['Is_Sector'])].copy()
    
    df_nifty = df_stocks[df_stocks['T'].isin(NIFTY_50)].copy()
    sector_perf = df_nifty.groupby('Sector')['C'].mean().sort_values(ascending=False)
    valid_sectors = [s for s in sector_perf.index if s != "OTHER"]
    
    if valid_sectors:
        top_buy_sector = valid_sectors[0]
        top_sell_sector = valid_sectors[-1]
    else:
        top_buy_sector = "PHARMA" 
        top_sell_sector = "IT" 
        
    df_buy_sector = df_nifty[df_nifty['Sector'] == top_buy_sector].sort_values(by=['S', 'C'], ascending=[False, False])
    df_sell_sector = df_nifty[df_nifty['Sector'] == top_sell_sector].sort_values(by=['S', 'C'], ascending=[False, True])
    df_independent = df_nifty[(~df_nifty['Sector'].isin([top_buy_sector, top_sell_sector])) & (df_nifty['S'] >= 6)].sort_values(by='S', ascending=False).head(8)
    df_broader = df_stocks[(df_stocks['T'].isin(BROADER_MARKET)) & (df_stocks['S'] >= 6)].sort_values(by='S', ascending=False).head(8)

    # Load Portfolio
    df_port_saved = load_portfolio()

    # Watchlist Filtering
    if watchlist_mode == "Terminal Tables 🗃️":
        terminal_tickers = pd.concat([df_buy_sector, df_sell_sector, df_independent, df_broader])['Fetch_T'].unique().tolist()
        df_filtered = df_stocks[df_stocks['Fetch_T'].isin(terminal_tickers)]
    elif watchlist_mode == "My Portfolio 💼":
        port_tickers = [f"{str(sym).upper().strip()}.NS" for sym in df_port_saved['Symbol'].tolist() if str(sym).strip() != ""]
        df_filtered = df_stocks[df_stocks['Fetch_T'].isin(port_tickers)]
    elif watchlist_mode == "Nifty 50 Heatmap":
        df_filtered = df_stocks[df_stocks['T'].isin(NIFTY_50)]
    elif watchlist_mode == "One Sided Moves 🚀":
        df_filtered = df_stocks[df_stocks['C'].abs() >= 1.0]
    else:
        df_filtered = df_stocks[(df_stocks['S'] >= 7) & (df_stocks['S'] <= 10)]

    all_display_tickers = list(set(df_indices['Fetch_T'].tolist() + df_filtered['Fetch_T'].tolist() + st.session_state.pinned_stocks))
    
    if search_stock != "-- None --":
        search_fetch_t = df[df['T'] == search_stock]['Fetch_T'].iloc[0]
        if search_fetch_t not in all_display_tickers: all_display_tickers.append(search_fetch_t)
            
    with st.spinner("Analyzing VWAP & 10 EMA Trends (Lightning Speed ⚡)..."):
        five_min_data = yf.download(all_display_tickers, period="5d", interval="5m", progress=False, group_by='ticker', threads=20)

    processed_charts = {}
    stock_trends = {}
    one_sided_tickers = []

    for sym in all_display_tickers:
        df_raw = five_min_data[sym] if isinstance(five_min_data.columns, pd.MultiIndex) else five_min_data
        df_day = process_5m_data(df_raw)
        processed_charts[sym] = df_day
        
        if sym in df_filtered['Fetch_T'].tolist() and not df_day.empty:
            last_price = df_day['Close'].iloc[-1]
            last_vwap = df_day['VWAP'].iloc[-1]
            last_ema = df_day['EMA_10'].iloc[-1]
            day_open = df_day['Open'].iloc[0]
            
            net_chg = df[df['Fetch_T'] == sym]['C'].iloc[0]
            
            is_bullish = (net_chg > 0) and (last_price >= day_open) and (last_price > last_vwap) and (last_price > last_ema)
            is_bearish = (net_chg < 0) and (last_price <= day_open) and (last_price < last_vwap) and (last_price < last_ema)
            
            if is_bullish: stock_trends[sym] = 'Bullish'
            elif is_bearish: stock_trends[sym] = 'Bearish'
            else: stock_trends[sym] = 'Neutral'
                
            total_candles = len(df_day)
            if total_candles >= 3:
                bull_cond = (df_day['Close'] > df_day['VWAP']) & (df_day['Close'] > df_day['EMA_10'])
                bear_cond = (df_day['Close'] < df_day['VWAP']) & (df_day['Close'] < df_day['EMA_10'])
                if (bull_cond.sum() / total_candles) >= 0.70 and stock_trends[sym] == 'Bullish': one_sided_tickers.append(sym)
                elif (bear_cond.sum() / total_candles) >= 0.70 and stock_trends[sym] == 'Bearish': one_sided_tickers.append(sym)

    if watchlist_mode == "One Sided Moves 🚀":
        df_filtered = df_filtered[df_filtered['Fetch_T'].isin(one_sided_tickers)]

    bull_cnt = sum(1 for sym in df_filtered['Fetch_T'] if stock_trends.get(sym) == 'Bullish')
    bear_cnt = sum(1 for sym in df_filtered['Fetch_T'] if stock_trends.get(sym) == 'Bearish')
    neut_cnt = sum(1 for sym in df_filtered['Fetch_T'] if stock_trends.get(sym) == 'Neutral')

    # --- BUTTONS ---
    with st.container():
        st.markdown("<div class='filter-marker'></div>", unsafe_allow_html=True)
        if st.button(f"📊 All ({len(df_filtered)})"): st.session_state.trend_filter = 'All'
        if st.button(f"🟢 Bullish ({bull_cnt})"): st.session_state.trend_filter = 'Bullish'
        if st.button(f"⚪ Neutral ({neut_cnt})"): st.session_state.trend_filter = 'Neutral'
        if st.button(f"🔴 Bearish ({bear_cnt})"): st.session_state.trend_filter = 'Bearish'

    st.markdown(f"<div style='text-align:right; font-size:12px; color:#ffd700; margin-bottom: 10px;'>Showing: <b>{st.session_state.trend_filter}</b> Stocks</div>", unsafe_allow_html=True)

    if st.session_state.trend_filter != 'All':
        df_filtered = df_filtered[df_filtered['Fetch_T'].apply(lambda x: stock_trends.get(x) == st.session_state.trend_filter)]

    # SORTING LOGIC 
    if sort_mode == "% Change Up 🟢": df_stocks_display = df_filtered.sort_values(by="C", ascending=False)
    elif sort_mode == "% Change Down 🔴": df_stocks_display = df_filtered.sort_values(by="C", ascending=True)
    elif sort_mode == "Heatmap Marks Up ⭐": df_stocks_display = pd.concat([df_filtered[df_filtered['C'] >= 0].sort_values(by=["S", "C"], ascending=[False, False]), df_filtered[df_filtered['C'] < 0].sort_values(by=["S", "C"], ascending=[False, True])])
    elif sort_mode == "Heatmap Marks Down ⬇️": df_stocks_display = pd.concat([df_filtered[df_filtered['C'] < 0].sort_values(by=["S", "C"], ascending=[False, True]), df_filtered[df_filtered['C'] >= 0].sort_values(by=["S", "C"], ascending=[False, False])])
    else:
        if st.session_state.trend_filter == 'Bullish': df_stocks_display = df_filtered.sort_values(by=["S", "C"], ascending=[False, False])
        elif st.session_state.trend_filter == 'Bearish': df_stocks_display = df_filtered.sort_values(by=["S", "C"], ascending=[False, True])
        elif st.session_state.trend_filter == 'Neutral': df_stocks_display = df_filtered.sort_values(by=["S", "C"], ascending=[False, False])
        else: df_stocks_display = pd.concat([df_filtered[df_filtered['C'] >= 0].sort_values(by=["S", "C"], ascending=[False, False]), df_filtered[df_filtered['C'] < 0].sort_values(by=["S", "C"], ascending=[True, True])])

    # --- RENDER VIEWS ---
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

    # 🔥 THE FIX: PROFESSIONAL ONLINE SEARCH & ENTRY FOR PORTFOLIO 🔥
    elif watchlist_mode == "My Portfolio 💼" and view_mode == "Heat Map":
        
        # 1. LIVE SEARCH ADD BOX
        st.markdown("<div style='background-color:#161b22; padding:15px; border-radius:8px; border:1px solid #30363d; margin-bottom:15px;'>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:14px; font-weight:bold; color:#ffd700; margin-bottom:10px;'>➕ Search & Add Stock to Portfolio</div>", unsafe_allow_html=True)
        
        c1, c2, c3, c4 = st.columns([3, 2, 2, 3])
        with c1:
            new_sym = st.text_input("🔍 NSE Symbol (e.g. itc, zomato)", key="new_sym", label_visibility="collapsed", placeholder="Type Symbol...").upper().strip()
        with c2:
            new_qty = st.number_input("📦 Quantity", min_value=1, value=10, key="new_qty", label_visibility="collapsed")
        with c3:
            new_price = st.number_input("💰 Buy Price (₹)", min_value=0.0, value=100.0, key="new_prc", label_visibility="collapsed")
        with c4:
            if st.button("➕ Verify & Add", use_container_width=True):
                if new_sym:
                    with st.spinner(f"Searching NSE for {new_sym}..."):
                        chk_data = yf.download(f"{new_sym}.NS", period="1d", progress=False)
                        if chk_data.empty:
                            st.error(f"❌ '{new_sym}' not found! Please check spelling.")
                        else:
                            if new_sym in df_port_saved['Symbol'].values:
                                df_port_saved.loc[df_port_saved['Symbol'] == new_sym, ['Buy_Price', 'Quantity']] = [new_price, new_qty]
                            else:
                                new_row = pd.DataFrame({"Symbol": [new_sym], "Buy_Price": [new_price], "Quantity": [new_qty], "Date": [""]})
                                df_port_saved = pd.concat([df_port_saved, new_row], ignore_index=True)
                            save_portfolio(df_port_saved)
                            st.success(f"✅ {new_sym} Added to Portfolio!")
                            st.rerun()
                else:
                    st.warning("Type a symbol first!")
        st.markdown("</div>", unsafe_allow_html=True)
        
        # 2. REMOVE BOX (Side by side with Table if needed, but let's keep it clean)
        if not df_port_saved.empty:
            rc1, rc2, rc3 = st.columns([3, 2, 5])
            with rc1:
                del_sym = st.selectbox("🗑️ Remove Stock", ["-- Select --"] + df_port_saved['Symbol'].tolist(), label_visibility="collapsed")
            with rc2:
                if st.button("❌ Remove", use_container_width=True):
                    if del_sym != "-- Select --":
                        df_port_saved = df_port_saved[df_port_saved['Symbol'] != del_sym]
                        save_portfolio(df_port_saved)
                        st.rerun()

        # 3. COLORFUL TERMINAL TABLE RENDER
        st.markdown(render_portfolio_table(df_port_saved, df_stocks, stock_trends), unsafe_allow_html=True)

    elif view_mode == "Heat Map":
        if not df_indices.empty:
            html_idx = '<div class="heatmap-grid">'
            for _, row in df_indices.iterrows():
                bg = "bear-card" if (row['T'] == "INDIA VIX" and row['C'] > 0) else ("bull-card" if row['C'] > 0 else "neut-card")
                if row['T'] != "INDIA VIX" and row['C'] < 0: bg = "bear-card"
                html_idx += f'<a href="https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(row["Fetch_T"])}" target="_blank" class="stock-card {bg}"><div class="t-score">IDX</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{"+" if row["C"]>0 else ""}{row["C"]:.2f}%</div></a>'
            st.markdown(html_idx + '</div><hr class="custom-hr">', unsafe_allow_html=True)
        
        if not df_sectors.empty:
            html_sec = '<div class="heatmap-grid">'
            for _, row in df_sectors.iterrows():
                bg = "bull-card" if row['C'] > 0 else ("bear-card" if row['C'] < 0 else "neut-card")
                html_sec += f'<a href="https://in.tradingview.com/chart/?symbol={TV_SECTOR_URL.get(row["Fetch_T"], "")}" target="_blank" class="stock-card {bg}"><div class="t-score" style="color:#00BFFF;">SEC</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{"+" if row["C"]>0 else ""}{row["C"]:.2f}%</div></a>'
            st.markdown(html_sec + '</div><hr class="custom-hr">', unsafe_allow_html=True)

        if not df_stocks_display.empty:
            html_stk = '<div class="heatmap-grid">'
            for _, row in df_stocks_display.iterrows():
                bg = "bull-card" if row['C'] > 0 else ("bear-card" if row['C'] < 0 else "neut-card")
                special_icon = "🚀" if watchlist_mode == "One Sided Moves 🚀" else f"⭐{int(row['S'])}"
                html_stk += f'<a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank" class="stock-card {bg}"><div class="t-score">{special_icon}</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{"+" if row["C"]>0 else ""}{row["C"]:.2f}%</div></a>'
            st.markdown(html_stk + '</div>', unsafe_allow_html=True)
        else: st.info(f"No {st.session_state.trend_filter} stocks found.")
            
    else: # CHART VIEW
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
