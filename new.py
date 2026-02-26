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

# --- 4. CSS FOR STYLING (PERFECT ALIGNMENT & RESPONSIVE BUTTONS) ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {display: none !important;}
    .stApp { background-color: #0e1117; color: #ffffff; }
    .block-container { padding-top: 1rem !important; padding-bottom: 0rem !important; margin-top: -10px; }
    
    /* Normal Text Settings */
    .stRadio label, .stRadio p, div[role="radiogroup"] p { color: #ffffff !important; font-weight: 400 !important; }
    div.stButton > button p, div.stButton > button span { color: #ffffff !important; font-weight: 400 !important; font-size: 14px !important; }
    
    .t-name, .t-price, .t-pct { font-weight: 400 !important; }
    .t-score { position: absolute; top: 3px; left: 3px; font-size: 10px; background: rgba(0,0,0,0.4); padding: 1px 4px; border-radius: 3px; color: #ffd700; font-weight: 400 !important; }
    
    /* 🔥 1. BUTTON ALIGNMENT FIX (Desktop & Mobile) 🔥 */
    div[data-testid="stHorizontalBlock"]:has(.filter-marker) {
        align-items: center !important; /* Fixes Desktop misalignment */
        gap: 8px !important;
    }
    
    @media screen and (max-width: 650px) {
        div[data-testid="stHorizontalBlock"]:has(.filter-marker) {
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: nowrap !important; /* Keeps them in one line */
            justify-content: space-between !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.filter-marker) > div[data-testid="column"] {
            width: 24% !important;
            min-width: 0px !important;
            flex: 1 1 auto !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.filter-marker) div.stButton > button p {
            font-size: 9px !important;
        }
    }

    /* 🔥 2. FLUID GRID LOGIC 🔥 */
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) {
        display: grid !important;
        grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)) !important; 
        gap: 12px !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div:nth-child(1) { display: none !important; }
    
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div[data-testid="stVerticalBlock"] {
        background-color: #161b22 !important;
        border: 1px solid #30363d !important;
        border-radius: 8px !important;
        padding: 10px 5px !important;
        position: relative !important;
    }

    /* Pin positioning */
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div[data-testid="stVerticalBlock"] div[data-testid="stCheckbox"] {
        position: absolute !important;
        top: 8px !important;
        left: 8px !important;
        z-index: 100 !important;
    }

    /* Chart box styling */
    .chart-box { padding: 5px; }
    .ind-labels { text-align: center; font-size: 9px; color: #8b949e; margin-bottom: 5px; font-weight: 400 !important; }
    
    /* Heatmap Grids */
    .heatmap-grid { display: grid; grid-template-columns: repeat(10, 1fr); gap: 8px; padding: 5px 0; }
    .stock-card { border-radius: 4px; padding: 8px 4px; text-align: center; text-decoration: none !important; color: white !important; display: flex; flex-direction: column; justify-content: center; height: 90px; position: relative; box-shadow: 0 1px 3px rgba(0,0,0,0.3); }
    
    .bull-card { background-color: #1e5f29 !important; } 
    .bear-card { background-color: #b52524 !important; } 
    .neut-card { background-color: #30363d !important; } 
    .idx-card { background-color: #0d47a1 !important; border: 1px solid #1976d2; } 
    
    @media screen and (max-width: 600px) {
        .heatmap-grid { grid-template-columns: repeat(3, 1fr); }
    }
    
    .custom-hr { border: 0; height: 1px; background: #30363d; margin: 15px 0; }
    </style>
""", unsafe_allow_html=True)

# --- 5. DATA FETCH ---
INDICES_MAP = {"^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY", "^INDIAVIX": "INDIA VIX"}
TV_INDICES_URL = {"^NSEI": "NSE:NIFTY", "^NSEBANK": "NSE:BANKNIFTY", "^INDIAVIX": "NSE:INDIAVIX"}

SECTOR_INDICES_MAP = {
    "^CNXIT": "NIFTY IT", "^CNXAUTO": "NIFTY AUTO", "^CNXMETAL": "NIFTY METAL",
    "^CNXPHARMA": "NIFTY PHARMA", "^CNXFMCG": "NIFTY FMCG", "^CNXENERGY": "NIFTY ENERGY", "^CNXREALTY": "NIFTY REALTY"
}

@st.cache_data(ttl=60)
def fetch_all_data():
    all_tickers = ["ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL", "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB", "DRREDDY", "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDIGO", "INFY", "ITC", "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TCS", "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO", "HAL", "BDL", "MAZDOCK", "COCHINSHIP", "GRSE", "RVNL", "IRFC", "IRCON", "TITAGARH", "RAILTEL", "RITES", "ADANIPOWER", "ADANIGREEN", "NHPC", "SJVN", "BHEL", "CGPOWER", "SUZLON", "PFC", "RECLTD", "IREDA", "IOB", "UCOBANK", "MAHABANK", "CANBK", "CHOLAFIN", "JIOFIN", "MUTHOOTFIN", "MANAPPURAM", "M&MFIN", "DIXON", "POLYCAB", "KAYNES", "HAVELLS", "KEI", "RRKABEL", "SRF", "TATACHEM", "DEEPAKNTR", "AARTIIND", "PIIND", "FACT", "UPL", "AMBUJACEM", "SHREECEM", "DALBHARAT", "CUMMINSIND", "ABB", "SIEMENS", "IDEA", "ZOMATO", "DMART", "PAYTM", "ZENTEC", "ATGL", "AWL", "BOSCHLTD", "MRF", "MOTHERSON", "SONACOMS", "EXIDEIND", "AMARAJABAT", "VEDL", "SAIL"]
    
    tkrs = list(INDICES_MAP.keys()) + list(SECTOR_INDICES_MAP.keys()) + [f"{t}.NS" for t in all_tickers]
    data = yf.download(tkrs, period="5d", progress=False, group_by='ticker', threads=20)
    
    results = []
    minutes = get_minutes_passed()

    for symbol in data.columns.levels[0]:
        try:
            df = data[symbol].dropna(subset=['Close'])
            if len(df) < 2: continue
            ltp, open_p, prev_c = float(df['Close'].iloc[-1]), float(df['Open'].iloc[-1]), float(df['Close'].iloc[-2])
            low, high = float(df['Low'].iloc[-1]), float(df['High'].iloc[-1])
            net_chg = ((ltp - prev_c) / prev_c) * 100
            
            score = 0
            if abs(((ltp - open_p) / open_p) * 100) >= 2.0: score += 3 
            if abs(open_p - low) <= (ltp * 0.003) or abs(open_p - high) <= (ltp * 0.003): score += 3 
            
            is_index, is_sector = symbol in INDICES_MAP, symbol in SECTOR_INDICES_MAP
            disp_name = INDICES_MAP.get(symbol, SECTOR_INDICES_MAP.get(symbol, symbol.replace(".NS", "")))
            results.append({"Fetch_T": symbol, "T": disp_name, "P": ltp, "C": net_chg, "S": score, "Is_Index": is_index, "Is_Sector": is_sector})
        except: continue
    return pd.DataFrame(results)

def get_minutes_passed():
    now = datetime.now()
    if now.weekday() >= 5 or now.time() > dt_time(15, 30): return 375
    open_time = now.replace(hour=9, minute=15, second=0)
    return min(375, max(1, int((now - open_time).total_seconds() / 60)))

def render_chart(row, df_chart, show_pin=True):
    color_hex = "#2ea043" if row['C'] > 0 else "#da3633"
    tv_link = f"https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(row['Fetch_T'], 'NSE:' + row['T'])}"
    
    if show_pin and not row['Is_Index']:
        st.checkbox("pin", value=(row['Fetch_T'] in st.session_state.pinned_stocks), key=f"cb_{row['Fetch_T']}", on_change=toggle_pin, args=(row['Fetch_T'],), label_visibility="collapsed")
    
    st.markdown(f"<div style='text-align:center; font-size:14px;'><a href='{tv_link}' target='_blank' style='color:#ffffff; text-decoration:none;'>{row['T']} <span style='color:{color_hex}'>({row['C']:.2f}%)</span></a></div>", unsafe_allow_html=True)
    st.markdown("<div class='ind-labels'><span style='color:#FFD700;'>--- VWAP</span> | <span style='color:#00BFFF;'>-- 10 EMA</span></div>", unsafe_allow_html=True)
    
    if not df_chart.empty:
        fig = go.Figure(data=[go.Candlestick(x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'], increasing_line_color='#2ea043', decreasing_line_color='#da3633')])
        fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=140, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis=dict(visible=False, fixedrange=True), yaxis=dict(visible=False, fixedrange=True), dragmode=False)
        st.plotly_chart(fig, use_container_width=True, config={'staticPlot': True, 'displayModeBar': False})

# --- 6. RENDER LOGIC ---
df = fetch_all_data()
if not df.empty:
    watchlist_mode = st.selectbox("Watchlist", ["High Score Stocks 🔥", "Nifty 50 Heatmap"], label_visibility="collapsed")
    view_mode = st.radio("Display", ["Heat Map", "Chart 📈"], horizontal=True, label_visibility="collapsed")
    
    df_indices = df[df['Is_Index']].sort_values("T")
    df_filtered = df[(df['S'] >= 6)] if watchlist_mode == "High Score Stocks 🔥" else df[~df['Is_Index'] & ~df['Is_Sector']]

    # 🔥 ALIGNED BUTTONS 🔥
    f1, f2, f3, f4 = st.columns(4)
    with f1: st.markdown("<div class='filter-marker'></div>", unsafe_allow_html=True); st.button(f"All ({len(df_filtered)})", key="btn_all", on_click=setattr, args=(st.session_state, 'trend_filter', 'All'), use_container_width=True)
    with f2: st.button(f"Bullish", key="btn_bull", on_click=setattr, args=(st.session_state, 'trend_filter', 'Bullish'), use_container_width=True)
    with f3: st.button(f"Neutral", key="btn_neut", on_click=setattr, args=(st.session_state, 'trend_filter', 'Neutral'), use_container_width=True)
    with f4: st.button(f"Bearish", key="btn_bear", on_click=setattr, args=(st.session_state, 'trend_filter', 'Bearish'), use_container_width=True)

    if view_mode == "Heat Map":
        st.markdown('<div class="heatmap-grid">' + "".join([f'<div class="stock-card idx-card"><div class="t-name">{r.T}</div><div class="t-price">{r.P:.2f}</div><div class="t-pct">{r.C:.2f}%</div></div>' for _, r in df_indices.iterrows()]) + '</div><hr class="custom-hr">', unsafe_allow_html=True)
        st.markdown('<div class="heatmap-grid">' + "".join([f'<div class="stock-card {"bull-card" if r.C>0 else "bear-card"}"><div class="t-score">⭐{int(r.S)}</div><div class="t-name">{r.T}</div><div class="t-price">{r.P:.2f}</div><div class="t-pct">{r.C:.2f}%</div></div>' for _, r in df_filtered.iterrows()]) + '</div>', unsafe_allow_html=True)
    else:
        chart_tkrs = list(set(df_indices['Fetch_T'].tolist() + df_filtered['Fetch_T'].tolist()))
        chart_data = yf.download(chart_tkrs, period="5d", interval="5m", progress=False, group_by='ticker')
        
        st.markdown("### 📈 Market Indices")
        with st.container():
            st.markdown("<div class='fluid-board'></div>", unsafe_allow_html=True)
            for _, r in df_indices.iterrows():
                with st.container(): render_chart(r, chart_data[r.Fetch_T] if r.Fetch_T in chart_data else pd.DataFrame(), False)
        
        st.markdown("<hr class='custom-hr'> ### Stocks", unsafe_allow_html=True)
        with st.container():
            st.markdown("<div class='fluid-board'></div>", unsafe_allow_html=True)
            for _, r in df_filtered.iterrows():
                with st.container(): render_chart(r, chart_data[r.Fetch_T] if r.Fetch_T in chart_data else pd.DataFrame())
