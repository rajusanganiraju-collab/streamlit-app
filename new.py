import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Market Heatmap", page_icon="📊", layout="wide")

# --- 2. AUTO RUN (1 MINUTE) ---
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

# --- 4. CSS (MOBILE FORCED HORIZONTAL & NO BOLD) ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {display: none !important;}
    .stApp { background-color: #0e1117; color: #ffffff; }
    .block-container { padding-top: 1rem !important; padding-bottom: 0rem !important; margin-top: -10px; }
    
    /* ALL TEXT TO NORMAL (UNBOLD) */
    .stRadio label, .stRadio p, div[role="radiogroup"] p { color: #ffffff !important; font-weight: 400 !important; }
    div.stButton > button p, div.stButton > button span { color: #ffffff !important; font-weight: 400 !important; }
    
    .t-name { font-size: 13px; font-weight: 400 !important; margin-bottom: 2px; }
    .t-price { font-size: 17px; font-weight: 400 !important; margin-bottom: 2px; }
    .t-pct { font-size: 12px; font-weight: 400 !important; }
    
    /* 🔥 FORCED HORIZONTAL BUTTONS FOR MOBILE 🔥 */
    div.filter-box {
        display: flex !important;
        flex-direction: row !important;
        justify-content: space-between !important;
        gap: 5px !important;
        margin-bottom: 15px !important;
        width: 100% !important;
    }
    div.filter-box button {
        flex: 1 !important;
        padding: 5px 2px !important;
        font-size: 10px !important;
        white-space: nowrap !important;
        border-radius: 6px !important;
        border: 1px solid #30363d !important;
        background-color: #161b22 !important;
        color: white !important;
        height: 40px !important;
    }

    /* FLUID GRID FOR CHARTS */
    div.chart-grid {
        display: grid !important;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)) !important;
        gap: 15px !important;
        margin-bottom: 20px !important;
    }

    .chart-card {
        background-color: #161b22 !important;
        border: 1px solid #30363d !important;
        border-radius: 8px !important;
        padding: 10px !important;
        position: relative !important;
    }
    
    .pin-chk {
        position: absolute !important;
        top: 5px !important;
        left: 5px !important;
        z-index: 100 !important;
    }

    .heatmap-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; padding: 5px 0; }
    .stock-card { border-radius: 4px; padding: 8px 4px; text-align: center; color: white !important; height: 90px; }
    .bull-card { background-color: #1e5f29 !important; } 
    .bear-card { background-color: #b52524 !important; } 
    .neut-card { background-color: #30363d !important; } 
    </style>
""", unsafe_allow_html=True)

# --- 5. DATA FETCH ---
INDICES_MAP = {"^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY", "^INDIAVIX": "INDIA VIX"}
TV_INDICES_URL = {"^NSEI": "NSE:NIFTY", "^NSEBANK": "NSE:BANKNIFTY", "^INDIAVIX": "NSE:INDIAVIX"}

NIFTY_50 = ["VEDL", "HEROMOTOCO", "AUROPHARMA", "BOSCHLTD", "POLYCAB", "BAJAJ-AUTO", "SONACOMS", "DIVISLAB", "M&MFIN", "KEI", "MAHABANK", "TVSMOTOR", "SAIL", "HCLTECH"] # Simplified for demo

@st.cache_data(ttl=60)
def fetch_data():
    tkrs = list(INDICES_MAP.keys()) + [f"{t}.NS" for t in NIFTY_50]
    data = yf.download(tkrs, period="2d", interval="5m", group_by='ticker', threads=10)
    results = []
    for t in tkrs:
        try:
            df = data[t].dropna()
            ltp = df['Close'].iloc[-1]
            chg = ((ltp - df['Close'].iloc[-2]) / df['Close'].iloc[-2]) * 100
            vwap = (df['High'] + df['Low'] + df['Close']).mean()
            ema = df['Close'].ewm(span=10).mean().iloc[-1]
            trend = 'Bullish' if ltp > vwap and ltp > ema else ('Bearish' if ltp < vwap and ltp < ema else 'Neutral')
            results.append({'T': INDICES_MAP.get(t, t.replace(".NS","")), 'Fetch_T': t, 'P': ltp, 'C': chg, 'Trend': trend, 'Is_Idx': t in INDICES_MAP})
        except: continue
    return pd.DataFrame(results)

df_all = fetch_data()

# --- 6. NAVIGATION ---
c1, c2 = st.columns([0.6, 0.4])
with c1: watchlist = st.selectbox("Watchlist", ["High Score Stocks 🔥"], label_visibility="collapsed")
with c2: view_mode = st.radio("Mode", ["Heat Map", "Chart 📈"], horizontal=True, label_visibility="collapsed")

# --- 7. FORCED HORIZONTAL BUTTONS (HTML/CSS ONLY) ---
bull_cnt = len(df_all[df_all['Trend'] == 'Bullish'])
neut_cnt = len(df_all[df_all['Trend'] == 'Neutral'])
bear_cnt = len(df_all[df_all['Trend'] == 'Bearish'])

st.markdown(f"""
    <div class="filter-box">
        <button onclick="window.location.reload()">📊 All ({len(df_all)})</button>
        <button style="border-bottom: 3px solid #1e5f29">🟢 Bullish ({bull_cnt})</button>
        <button style="border-bottom: 3px solid #888">⚪ Neutral ({neut_cnt})</button>
        <button style="border-bottom: 3px solid #b52524">🔴 Bearish ({bear_cnt})</button>
    </div>
""", unsafe_allow_html=True)

# --- 8. RENDER ---
if view_mode == "Heat Map":
    # Simple Heatmap Logic
    st.markdown('<div class="heatmap-grid">', unsafe_allow_html=True)
    for _, row in df_all.iterrows():
        bg = "bull-card" if row['C'] > 0 else "bear-card"
        st.markdown(f'<div class="stock-card {bg}">{row["T"]}<br>{row["P"]:.2f}<br>{row["C"]:.2f}%</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
else:
    # Chart Logic with Fixed Scrolling
    for sym in df_all['T']:
        fig = go.Figure(go.Scatter(y=[1,3,2,4], mode='lines')) # Simplified chart
        fig.update_layout(height=150, margin=dict(l=0,r=0,t=0,b=0), dragmode=False, xaxis_fixedrange=True, yaxis_fixedrange=True)
        st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True, 'displayModeBar': False})

