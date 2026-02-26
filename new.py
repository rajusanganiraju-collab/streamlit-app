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

# --- 4. CSS FOR STYLING (RESTORED TO THE 100% SUCCESSFUL VERSION) ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {display: none !important;}
    .stApp { background-color: #0e1117; color: #ffffff; }
    .block-container { padding-top: 1rem !important; padding-bottom: 0rem !important; margin-top: -10px; }
    
    /* 🔥 1. ALL TEXT TO NORMAL (UNBOLD) 🔥 */
    .stRadio label, .stRadio p, div[role="radiogroup"] p { color: #ffffff !important; font-weight: normal !important; }
    div.stButton > button p, div.stButton > button span { color: #ffffff !important; font-weight: normal !important; font-size: 14px !important; }
    
    .t-name { font-size: 13px; font-weight: normal !important; margin-bottom: 2px; }
    .t-price { font-size: 17px; font-weight: normal !important; margin-bottom: 2px; }
    .t-pct { font-size: 12px; font-weight: normal !important; }
    .t-score { position: absolute; top: 3px; left: 3px; font-size: 10px; background: rgba(0,0,0,0.4); padding: 1px 4px; border-radius: 3px; color: #ffd700; font-weight: normal !important; }
    
    /* 🔥 2. THE SUCCESSFUL HORIZONTAL BUTTONS FIX (NO COLUMNS HACK) 🔥 */
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) {
        display: flex !important;
        flex-direction: row !important; 
        flex-wrap: nowrap !important; 
        justify-content: center !important; 
        align-items: center !important;
        gap: 8px !important; 
        width: 100% !important;
    }
    
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) > div[data-testid="stElementContainer"]:has(.filter-marker) {
        display: none !important;
    }
    
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) > div[data-testid="stElementContainer"] {
        width: auto !important;
        flex: 0 0 auto !important; 
    }
    
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) div.stButton > button {
        width: max-content !important;
        height: 35px !important;
        padding: 0px 12px !important;
    }
    
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) div.stButton > button p {
        font-size: 12px !important;
        white-space: nowrap !important; 
        margin: 0 !important;
    }
    
    @media screen and (max-width: 650px) {
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) { gap: 4px !important; }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) div.stButton > button { padding: 0px 8px !important; }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) div.stButton > button p { font-size: 10.5px !important; }
    }
    
    /* 🔥 3. THE SUCCESSFUL FLUID GRID FOR CHARTS 🔥 */
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) {
        display: grid !important;
        gap: 12px !important;
        align-items: start !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div:nth-child(1) {
        display: none !important; 
    }
    
    @media screen and (min-width: 1700px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(8, 1fr) !important; } }
    @media screen and (min-width: 1400px) and (max-width: 1699px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(6, 1fr) !important; } }
    @media screen and (min-width: 1100px) and (max-width: 1399px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(5, 1fr) !important; } }
    @media screen and (min-width: 850px) and (max-width: 1099px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(4, 1fr) !important; } }
    @media screen and (min-width: 651px) and (max-width: 849px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(3, 1fr) !important; } }
    @media screen and (max-width: 650px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(2, 1fr) !important; gap: 6px !important; } }
    
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div[data-testid="stVerticalBlock"] {
        background-color: #161b22 !important;
        border: 1px solid #30363d !important;
        border-radius: 8px !important;
        padding: 8px 5px 5px 5px !important;
        position: relative !important;
        width: 100% !important;
    }

    /* 🔥 4. PERFECT PIN BOX 🔥 */
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div[data-testid="stVerticalBlock"] div[data-testid="stCheckbox"] {
        position: absolute !important;
        top: 8px !important;
        left: 10px !important;
        z-index: 100 !important;
    }
    div[data-testid="stCheckbox"] label { padding: 0 !important; min-height: 0 !important; }
    
    div.stButton > button {
        border-radius: 8px !important;
        border: 1px solid #30363d !important;
        background-color: #161b22 !important;
        height: 45px !important;
    }
    
    /* Heatmap Layout */
    .heatmap-grid { display: grid; grid-template-columns: repeat(10, 1fr); gap: 8px; padding: 5px 0; }
    .stock-card { border-radius: 4px; padding: 8px 4px; text-align: center; text-decoration: none !important; color: white !important; display: flex; flex-direction: column; justify-content: center; height: 90px; position: relative; box-shadow: 0 1px 3px rgba(0,0,0,0.3); transition: transform 0.2s; }
    .stock-card:hover { transform: scale(1.05); z-index: 10; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }
    
    .bull-card { background-color: #1e5f29 !important; } 
    .bear-card { background-color: #b52524 !important; } 
    .neut-card { background-color: #30363d !important; } 
    .idx-card { background-color: #0d47a1 !important; border: 1px solid #1976d2; } 
    
    @media screen and (max-width: 1400px) { .heatmap-grid { grid-template-columns: repeat(8, 1fr); } }
    @media screen and (max-width: 1100px) { .heatmap-grid { grid-template-columns: repeat(6, 1fr); } }
    @media screen and (max-width: 800px) { .heatmap-grid { grid-template-columns: repeat(4, 1fr); } }
    @media screen and (max-width: 600px) { .heatmap-grid { grid-template-columns: repeat(3, 1fr); gap: 6px; } .stock-card { height: 95px; } .t-name { font-size: 12px; } .t-price { font-size: 16px; } .t-pct { font-size: 11px; } }
    
    .custom-hr { border: 0; height: 1px; background: #30363d; margin: 15px 0; }
    </style>
""", unsafe_allow_html=True)

# --- 5. DATA SETUP ---
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

NIFTY_50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO", "BAJFINANCE", 
    "BAJAJFINSV", "BEL", "BHARTIARTL", "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB", "DRREDDY", 
    "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDUNILVR", 
    "ICICIBANK", "INDIGO", "INFY", "ITC", "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI", "NESTLEIND", 
    "NTPC", "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM", 
    "TATAMOTORS", "TATASTEEL", "TCS", "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO"
]

BROADER_MARKET = [
    "HAL", "BDL", "MAZDOCK", "COCHINSHIP", "GRSE", "RVNL", "IRFC", "IRCON", "TITAGARH", "RAILTEL", "RITES",
    "ADANIPOWER", "ADANIGREEN", "NHPC", "SJVN", "BHEL", "CGPOWER", "SUZLON", "PFC", "RECLTD", "IREDA", "IOB", "UCOBANK", "MAHABANK", "CANBK",
    "CHOLAFIN", "JIOFIN", "MUTHOOTFIN", "MANAPPURAM", "M&MFIN", "DIXON", "POLYCAB", "KAYNES", "HAVELLS", "KEI", "RRKABEL",
    "SRF", "TATACHEM", "DEEPAKNTR", "AARTIIND", "PIIND", "FACT", "UPL", "AMBUJACEM", "SHREECEM", "DALBHARAT", "CUMMINSIND", "ABB", "SIEMENS",
    "IDEA", "ZOMATO", "DMART", "PAYTM", "ZENTEC", "ATGL", "AWL", "BOSCHLTD", "MRF", "MOTHERSON", "SONACOMS", "EXIDEIND", "AMARAJABAT", "VEDL", "SAIL"
]

def get_minutes_passed():
    now = datetime.now()
    if now.weekday() >= 5 or now.time() > dt_time(15, 30): return 375
    open_time = now.replace(hour=9, minute=15, second=0)
    return min(375, max(1, int((now - open_time).total_seconds() / 60)))

@st.cache_data(ttl=60)
def fetch_all_data():
    all_stocks = set(NIFTY_50 + BROADER_MARKET)
    tkrs = list(INDICES_MAP.keys()) + list(SECTOR_INDICES_MAP.keys()) + [f"{t}.NS" for t in all_stocks]
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
            else:
                vol_x = 0.0
                
            vwap = (high + low + ltp) / 3
            score = 0
            if abs(day_chg) >= 2.0: score += 3 
            if abs(open_p - low) <= (ltp * 0.003) or abs(open_p - high) <= (ltp * 0.003): score += 3 
            if vol_x > 1.0: score += 3 
            if (ltp >= high * 0.998 and day_chg > 0.5) or (ltp <= low * 1.002 and day_chg < -0.5): score += 1
            if (ltp > (low * 1.01) and ltp > vwap) or (ltp < (high * 0.99) and ltp < vwap): score += 1
            
            is_index = False
            is_sector = False
            
            if symbol in INDICES_MAP:
                disp_name = INDICES_MAP[symbol]
                is_index = True
            elif symbol in SECTOR_INDICES_MAP:
                disp_name = SECTOR_INDICES_MAP[symbol]
                is_sector = True
            else:
                disp_name = symbol.replace(".NS", "")
                
            results.append({
                "Fetch_T": symbol, "T": disp_name, "P": ltp, "C": net_chg, "S": score, 
                "Is_Index": is_index, "Is_Sector": is_sector
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
            else:
                df_day['VWAP'] = df_day['Typical_Price'].expanding().mean()
            return df_day
        return pd.DataFrame()
    except: return pd.DataFrame()

# --- HELPER FUNCTION TO DRAW CHARTS ---
def render_chart(row, df_chart, show_pin=True):
    display_sym = row['T']
    fetch_sym = row['Fetch_T']
    
    if display_sym == "INDIA VIX": 
        color_hex = "#da3633" if row['C'] > 0 else ("#2ea043" if row['C'] < 0 else "#8b949e")
    else:
        color_hex = "#2ea043" if row['C'] > 0 else ("#da3633" if row['C'] < 0 else "#8b949e")
        
    sign = "+" if row['C'] > 0 else ""
    tv_link = f"https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(fetch_sym, 'NSE:' + display_sym)}"
    
    if show_pin and display_sym not in ["NIFTY", "BANKNIFTY", "INDIA VIX"]:
        st.checkbox("pin", value=(fetch_sym in st.session_state.pinned_stocks), key=f"cb_{fetch_sym}", on_change=toggle_pin, args=(fetch_sym,), label_visibility="collapsed")
    
    st.markdown(f"""
        <div style='text-align:center; font-size:15px; margin-top:2px;'>
            <a href='{tv_link}' target='_blank' style='color:#ffffff; text-decoration:none; font-weight:normal !important;'>
                {display_sym} <span style='color:{color_hex}; font-weight:normal !important;'>({sign}{row['C']:.2f}%)</span>
            </a>
        </div>
        <div style='text-align:center; font-size:10px; color:#8b949e; margin-top:2px; margin-bottom:5px; font-weight:normal !important;'>
            <span style='color:#FFD700;'>--- VWAP</span> &nbsp;|&nbsp; <span style='color:#00BFFF;'>- - 10 EMA</span>
        </div>
    """, unsafe_allow_html=True)
    
    try:
        if not df_chart.empty:
            min_val, max_val = df_chart[['Low', 'VWAP', 'EMA_10']].min().min(), df_chart[['High', 'VWAP', 'EMA_10']].max().max()
            y_padding = (max_val - min_val) * 0.1 if (max_val - min_val) != 0 else min_val * 0.005 
            
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'], increasing_line_color='#2ea043', decreasing_line_color='#da3633', name='Price'))
            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['VWAP'], mode='lines', line=dict(color='#FFD700', width=1.5, dash='dot')))
            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA_10'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash')))
            
            fig.update_layout(
                margin=dict(l=0, r=0, t=0, b=0), 
                height=150, 
                paper_bgcolor='rgba(0,0,0,0)', 
                plot_bgcolor='rgba(0,0,0,0)', 
                xaxis=dict(visible=False, rangeslider=dict(visible=False), fixedrange=True), 
                yaxis=dict(visible=False, range=[min_val - y_padding, max_val + y_padding], fixedrange=True), 
                hovermode=False, 
                showlegend=False,
                dragmode=False 
            )
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False, 'staticPlot': True})
        else:
            st.markdown("<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888; font-weight:normal !important;'>Data not available</div>", unsafe_allow_html=True)
    except Exception as e:
        st.markdown("<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888; font-weight:normal !important;'>Chart error</div>", unsafe_allow_html=True)

# --- 6. TOP NAVIGATION & SEARCH ---
c1, c2 = st.columns([0.6, 0.4])
with c1: watchlist_mode = st.selectbox("Watchlist", ["High Score Stocks 🔥", "Nifty 50 Heatmap", "One Sided Moves 🚀"], label_visibility="collapsed")
with c2: view_mode = st.radio("Display", ["Heat Map", "Chart 📈"], horizontal=True, label_visibility="collapsed")

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
    
    # 🔥 FILTER LOGIC 🔥
    if watchlist_mode == "Nifty 50 Heatmap":
        df_filtered = df_stocks[df_stocks['T'].isin(NIFTY_50)]
    elif watchlist_mode == "One Sided Moves 🚀":
        df_filtered = df_stocks[df_stocks['C'].abs() >= 1.0]
    else:
        df_filtered = df_stocks[(df_stocks['S'] >= 7) & (df_stocks['S'] <= 10)]

    all_display_tickers = list(set(df_indices['Fetch_T'].tolist() + df_filtered['Fetch_T'].tolist() + st.session_state.pinned_stocks))
    
    if search_stock != "-- None --":
        search_fetch_t = df[df['T'] == search_stock]['Fetch_T'].iloc[0]
        if search_fetch_t not in all_display_tickers:
            all_display_tickers.append(search_fetch_t)
            
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
            
            if last_price > last_vwap and last_price > last_ema:
                stock_trends[sym] = 'Bullish'
            elif last_price < last_vwap and last_price < last_ema:
                stock_trends[sym] = 'Bearish'
            else:
                stock_trends[sym] = 'Neutral'
                
            # 🔥 NEW LOGIC: ONE SIDED MOVES (70% ABOVE/BELOW) 🔥
            total_candles = len(df_day)
            if total_candles >= 3:
                bull_cond = (df_day['Close'] > df_day['VWAP']) & (df_day['Close'] > df_day['EMA_10'])
                bear_cond = (df_day['Close'] < df_day['VWAP']) & (df_day['Close'] < df_day['EMA_10'])
                bull_ratio = bull_cond.sum() / total_candles
                bear_ratio = bear_cond.sum() / total_candles
                
                if bull_ratio >= 0.70 and stock_trends[sym] == 'Bullish':
                    one_sided_tickers.append(sym)
                elif bear_ratio >= 0.70 and stock_trends[sym] == 'Bearish':
                    one_sided_tickers.append(sym)

    if watchlist_mode == "One Sided Moves 🚀":
        df_filtered = df_filtered[df_filtered['Fetch_T'].isin(one_sided_tickers)]

    bull_cnt = sum(1 for sym in df_filtered['Fetch_T'] if stock_trends.get(sym) == 'Bullish')
    bear_cnt = sum(1 for sym in df_filtered['Fetch_T'] if stock_trends.get(sym) == 'Bearish')
    neut_cnt = sum(1 for sym in df_filtered['Fetch_T'] if stock_trends.get(sym) == 'Neutral')

    # --- 🔥 THE SUCCESSFUL INLINE BUTTONS (NO COLUMNS!) 🔥 ---
    with st.container():
        st.markdown("<div class='filter-marker'></div>", unsafe_allow_html=True)
        if st.button(f"📊 All ({len(df_filtered)})"): st.session_state.trend_filter = 'All'
        if st.button(f"🟢 Bullish ({bull_cnt})"): st.session_state.trend_filter = 'Bullish'
        if st.button(f"⚪ Neutral ({neut_cnt})"): st.session_state.trend_filter = 'Neutral'
        if st.button(f"🔴 Bearish ({bear_cnt})"): st.session_state.trend_filter = 'Bearish'

    st.markdown(f"<div style='text-align:right; font-size:12px; color:#ffd700; margin-bottom: 10px; font-weight:normal !important;'>Showing: <b>{st.session_state.trend_filter}</b> Stocks</div>", unsafe_allow_html=True)

    if st.session_state.trend_filter != 'All':
        df_filtered = df_filtered[df_filtered['Fetch_T'].apply(lambda x: stock_trends.get(x) == st.session_state.trend_filter)]

    # SORTING LOGIC 
    if st.session_state.trend_filter == 'Bullish':
        df_stocks_display = df_filtered.sort_values(by=["S", "C"], ascending=[False, False])
    elif st.session_state.trend_filter == 'Bearish':
        df_stocks_display = df_filtered.sort_values(by=["S", "C"], ascending=[False, True])
    elif st.session_state.trend_filter == 'Neutral':
        df_stocks_display = df_filtered.sort_values(by=["S", "C"], ascending=[False, False])
    else:
        greens = df_filtered[df_filtered['C'] >= 0].sort_values(by=["S", "C"], ascending=[False, False])
        reds = df_filtered[df_filtered['C'] < 0].sort_values(by=["S", "C"], ascending=[True, True])
        df_stocks_display = pd.concat([greens, reds])

    # --- RENDER VIEWS ---
    if view_mode == "Heat Map":
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
                tv_sym = TV_SECTOR_URL.get(row['Fetch_T'], "")
                tv_link = f"https://in.tradingview.com/chart/?symbol={tv_sym}"
                html_sec += f'<a href="{tv_link}" target="_blank" class="stock-card {bg}"><div class="t-score" style="color:#00BFFF;">SEC</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{"+" if row["C"]>0 else ""}{row["C"]:.2f}%</div></a>'
            st.markdown(html_sec + '</div><hr class="custom-hr">', unsafe_allow_html=True)

        if not df_stocks_display.empty:
            html_stk = '<div class="heatmap-grid">'
            for _, row in df_stocks_display.iterrows():
                bg = "bull-card" if row['C'] > 0 else ("bear-card" if row['C'] < 0 else "neut-card")
                
                special_icon = "🚀" if watchlist_mode == "One Sided Moves 🚀" else f"⭐{int(row['S'])}"
                
                html_stk += f'<a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank" class="stock-card {bg}"><div class="t-score">{special_icon}</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{"+" if row["C"]>0 else ""}{row["C"]:.2f}%</div></a>'
            st.markdown(html_stk + '</div>', unsafe_allow_html=True)
        else:
            st.info(f"No {st.session_state.trend_filter} stocks found in this list.")
            
    else:
        st.markdown("<br>", unsafe_allow_html=True)
        
        # 1. RENDER SEARCHED CHART
        if search_stock != "-- None --":
            st.markdown(f"<div style='font-size:18px; font-weight:bold; margin-bottom:5px; color:#ffd700;'>🔍 Searched Chart: {search_stock}</div>", unsafe_allow_html=True)
            searched_row = df[df['T'] == search_stock].iloc[0]
            
            # 🔥 THE SUCCESSFUL FLUID BOARD CSS HACK 🔥
            with st.container():
                st.markdown("<div class='fluid-board'></div>", unsafe_allow_html=True)
                with st.container():
                    render_chart(searched_row, processed_charts.get(searched_row['Fetch_T'], pd.DataFrame()), show_pin=False)
            st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        # 2. RENDER INDICES CHARTS
        st.markdown("<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#e6edf3;'>📈 Market Indices</div>", unsafe_allow_html=True)
        if not df_indices.empty:
            with st.container():
                st.markdown("<div class='fluid-board'></div>", unsafe_allow_html=True)
                for _, row in df_indices.iterrows():
                    with st.container():
                        render_chart(row, processed_charts.get(row['Fetch_T'], pd.DataFrame()), show_pin=False)
        st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        # 3. RENDER ALL PINNED & SEARCHED STOCKS HERE (PRIORITY ROW)
        pinned_df = df[df['Fetch_T'].isin(st.session_state.pinned_stocks)].copy()
        
        if search_stock != "-- None --":
            searched_row = df[df['T'] == search_stock].iloc[0]
            if searched_row['Fetch_T'] not in st.session_state.pinned_stocks:
                 pinned_df = pd.concat([pd.DataFrame([searched_row]), pinned_df])
        
        unpinned_df = df_stocks_display[~df_stocks_display['Fetch_T'].isin(pinned_df['Fetch_T'].tolist())]
        
        if not pinned_df.empty:
            st.markdown("<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#ffd700;'>📌 Pinned Priority Charts</div>", unsafe_allow_html=True)
            with st.container():
                st.markdown("<div class='fluid-board'></div>", unsafe_allow_html=True)
                for _, row in pinned_df.iterrows():
                    with st.container():
                        render_chart(row, processed_charts.get(row['Fetch_T'], pd.DataFrame()), show_pin=True)
            st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        # 4. RENDER REMAINING STOCKS
        if not unpinned_df.empty:
            st.markdown(f"<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#e6edf3;'>{watchlist_mode} ({st.session_state.trend_filter})</div>", unsafe_allow_html=True)
            
            with st.container():
                st.markdown("<div class='fluid-board'></div>", unsafe_allow_html=True)
                for _, row in unpinned_df.iterrows():
                    with st.container():
                        render_chart(row, processed_charts.get(row['Fetch_T'], pd.DataFrame()), show_pin=True)

else:
    st.info("Loading Market Data...")
