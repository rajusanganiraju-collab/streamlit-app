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

# --- 2. AUTO RUN (1 MINUTE REFRESH - AS REQUESTED) ---
st_autorefresh(interval=60000, key="datarefresh")

# --- 3. STATE MANAGEMENT ---
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
        df = pd.read_csv(PORTFOLIO_FILE)
        if not df.empty:
            df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce').fillna(1).astype(int)
            df['Buy_Price'] = pd.to_numeric(df['Buy_Price'], errors='coerce').fillna(0.0).astype(float)
            df['Symbol'] = df['Symbol'].astype(str).replace('nan', '')
            df['Date'] = df['Date'].astype(str).replace('nan', '')
        return df
    else:
        return pd.DataFrame(columns=["Symbol", "Buy_Price", "Quantity", "Date"])

def save_portfolio(df_port):
    df_port.to_csv(PORTFOLIO_FILE, index=False)

# --- 4. CSS STYLING ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {display: none !important;}
    .stApp { background-color: #0e1117; color: #ffffff; }
    .block-container { padding-top: 1rem !important; padding-bottom: 0rem !important; margin-top: -10px; }
    .t-score { position: absolute; top: 3px; left: 3px; font-size: 10px; background: rgba(0,0,0,0.4); padding: 1px 4px; border-radius: 3px; color: #ffd700; }
    
    /* TERMINAL TABLE STYLES */
    .term-table { width: 100%; border-collapse: collapse; margin-bottom: 15px; font-family: monospace; font-size: 11.5px; color: #e6edf3; background-color: #0e1117; table-layout: fixed; }
    .term-table th { padding: 6px 4px; text-align: center; border: 1px solid #30363d; font-weight: bold; background-color: #21262d; }
    .term-table td { padding: 6px 4px; text-align: center; border: 1px solid #30363d; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .term-table a { color: inherit; text-decoration: none; border-bottom: 1px dashed rgba(255,255,255,0.4); }
    .term-table a:hover { color: #58a6ff !important; border-bottom: 1px solid #58a6ff; }
    .term-head-high { background-color: #b71c1c; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
    .term-head-swing { background-color: #005a9e; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
    .row-dark { background-color: #161b22; } .row-light { background-color: #0e1117; }
    .text-green { color: #3fb950; font-weight: bold; } .text-red { color: #f85149; font-weight: bold; }
    .t-symbol { text-align: left !important; font-weight: bold; }

    /* Heatmap Layout */
    .heatmap-grid { display: grid; grid-template-columns: repeat(10, 1fr); gap: 8px; padding: 5px 0; }
    .stock-card { border-radius: 4px; padding: 8px 4px; text-align: center; text-decoration: none !important; color: white !important; display: flex; flex-direction: column; justify-content: center; height: 90px; position: relative; }
    .bull-card { background-color: #1e5f29 !important; } .bear-card { background-color: #b52524 !important; } .neut-card { background-color: #30363d !important; } 
    @media screen and (max-width: 600px) { .heatmap-grid { grid-template-columns: repeat(3, 1fr); } }
    </style>
""", unsafe_allow_html=True)

# --- 5. CONSTANTS ---
INDICES_MAP = {"^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY", "^INDIAVIX": "INDIA VIX"}
NIFTY_50 = ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "RELIANCE", "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "ITC", "HINDUNILVR", "TATAMOTORS", "M&M", "MARUTI", "SUNPHARMA", "CIPLA", "DRREDDY", "TATASTEEL", "JSWSTEEL", "ADANIENT", "TITAN", "BHARTIARTL", "LT"]
BROADER_MARKET = ["HAL", "BDL", "MAZDOCK", "RVNL", "IRFC", "BHEL", "CGPOWER", "SUZLON", "DIXON", "POLYCAB", "KAYNES", "ZOMATO", "DMART", "KALYANKJIL"]

# --- 6. CORE DATA FETCHING ---
@st.cache_data(ttl=60)
def fetch_market_data():
    all_tkrs = list(INDICES_MAP.keys()) + [f"{t}.NS" for t in (NIFTY_50 + BROADER_MARKET)]
    # Keeping threads=20 as you found it faster
    data = yf.download(all_tkrs, period="2d", interval="5m", progress=False, group_by='ticker', threads=20)
    return data

# --- 7. PROCESSING & SCORING ---
data = fetch_market_data()

if not data.empty:
    # A. Calculate Nifty VWAP Distance first
    nifty_df = data["^NSEI"].dropna()
    nifty_ltp = nifty_df['Close'].iloc[-1]
    nifty_vwap = ((nifty_df['High'] + nifty_df['Low'] + nifty_df['Close'])/3 * nifty_df['Volume']).cumsum() / nifty_df['Volume'].cumsum()
    nifty_dist = abs(nifty_ltp - nifty_vwap.iloc[-1]) / nifty_vwap.iloc[-1] * 100
    
    results = []
    for ticker in data.columns.levels[0]:
        if ticker in INDICES_MAP or ticker == "NIFTY": continue
        try:
            df = data[ticker].dropna()
            if len(df) < 20: continue
            
            ltp = df['Close'].iloc[-1]
            open_p = df['Open'].iloc[0]
            high = df['High'].max()
            low = df['Low'].min()
            prev_close = df['Close'].iloc[0] # Approximate
            
            net_chg = ((ltp - prev_close) / prev_close) * 100
            day_chg = ((ltp - open_p) / open_p) * 100
            
            # VWAP & EMAs
            tp = (df['High'] + df['Low'] + df['Close']) / 3
            vwap = (tp * df['Volume']).cumsum() / df['Volume'].cumsum()
            curr_vwap = vwap.iloc[-1]
            
            ema10 = df['Close'].ewm(span=10, adjust=False).mean().iloc[-1]
            ema20 = df['Close'].ewm(span=20, adjust=False).mean().iloc[-1]
            ema50 = df['Close'].ewm(span=50, adjust=False).mean().iloc[-1]
            
            # 🔥 NEW ALPHA LOGIC: Nifty VWAP Distance vs Stock VWAP Distance 🔥
            stock_vwap_dist = abs(ltp - curr_vwap) / curr_vwap * 100
            alpha_score = 0
            alpha_tag = ""
            
            if stock_vwap_dist > (nifty_dist * 3):
                alpha_score = 5
                alpha_tag = "🚀Alpha-Mover"
            elif stock_vwap_dist > (nifty_dist * 2):
                alpha_score = 3
                alpha_tag = "💪Nifty-Beater"

            # 1. Base Score (Volume, O=L, etc.)
            score = alpha_score # Start with Alpha score instead of Big Mover
            if abs(open_p - low) <= (ltp * 0.002): score += 3 # O=L
            if abs(open_p - high) <= (ltp * 0.002): score += 3 # O=H
            
            # Volume Logic
            avg_vol = df['Volume'].mean()
            vol_x = df['Volume'].iloc[-1] / avg_vol if avg_vol > 0 else 1
            if vol_x > 1.5: score += 3
            
            # 2. Sniper Bounce Bonus (+5)
            bounce_tag = ""
            if score >= 6:
                d50 = (ltp - ema50) / ema50 * 100
                dvw = (ltp - curr_vwap) / curr_vwap * 100
                d20 = (ltp - ema20) / ema20 * 100
                
                if net_chg > 0 and (ema10 > ema20): # Only if trending up
                    if 0 <= d50 <= 0.4: bounce_tag, score = "🔥50EMA-Bounce", score + 5
                    elif 0 <= dvw <= 0.4: bounce_tag, score = "🔥VWAP-Bounce", score + 5
                    elif 0 <= d20 <= 0.4: bounce_tag, score = "🔥20EMA-Bounce", score + 5

            results.append({
                "T": ticker.replace(".NS", ""), "P": ltp, "Day_C": day_chg, "C": net_chg, "S": score, 
                "VolX": vol_x, "Status": f"{alpha_tag} {bounce_tag}".strip(),
                "Pivot": (high + low + ltp)/3, "R1": (2*((high+low+ltp)/3))-low, "S1": (2*((high+low+ltp)/3))-high
            })
        except: continue

    df_res = pd.DataFrame(results).sort_values(by=["S", "VolX"], ascending=False)

    # --- 8. RENDER INTERFACE ---
    watchlist = st.selectbox("Watchlist", ["High Score Stocks 🔥", "Terminal Tables 🗃️"])
    
    if watchlist == "High Score Stocks 🔥":
        # Heatmap
        st.markdown('<div class="heatmap-grid">', unsafe_allow_html=True)
        for _, row in df_res.head(10).iterrows():
            bg = "bull-card" if row['C'] > 0 else "bear-card"
            st.markdown(f'<div class="stock-card {bg}"><div class="t-score">⭐{int(row["S"])}</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{row["C"]:.2f}%</div></div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Ranked Table
        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("🔥 View High Score Radar (Ranked Table)", expanded=True):
            html = f'<table class="term-table"><thead><tr><th class="term-head-high" colspan="7">🔥 HIGH SCORE RADAR (NIFTY DISTANCE BOOSTED)</th></tr><tr><th>RANK</th><th>STOCK</th><th>LTP</th><th>NET%</th><th>VOL</th><th>STATUS</th><th>SCORE</th></tr></thead><tbody>'
            for i, row in df_res.head(15).iterrows():
                bg_class = "row-dark" if i % 2 == 0 else "row-light"
                html += f'<tr class="{bg_class}"><td>{i+1}</td><td class="t-symbol"><a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank">{row["T"]}</a></td><td>{row["P"]:.2f}</td><td class="text-green">{row["C"]:.2f}%</td><td>{row["VolX"]:.1f}x</td><td>{row["Status"]}</td><td style="color:#ffd700;">{int(row["S"])}</td></tr>'
            st.markdown(html + "</tbody></table>", unsafe_allow_html=True)

else:
    st.warning("Data Loading... Please wait.")
