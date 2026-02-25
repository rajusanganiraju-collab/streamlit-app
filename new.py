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

# --- 3. CSS FOR EXACT 10-COLUMN HEATMAP & NORMAL FONTS ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {display: none !important;}
    
    /* Dark Theme Background */
    .stApp { background-color: #0e1117; color: #ffffff; }
    .block-container { padding-top: 1rem !important; padding-bottom: 0rem !important; margin-top: -10px; }
    
    /* Responsive Grid: EXACTLY 10 COLUMNS ON DESKTOP */
    .heatmap-grid {
        display: grid;
        grid-template-columns: repeat(10, 1fr);
        gap: 8px;
        padding: 5px 0;
    }
    
    /* Box Styling */
    .stock-card {
        border-radius: 4px;
        padding: 8px 4px;
        text-align: center;
        text-decoration: none !important;
        color: white !important;
        display: flex;
        flex-direction: column;
        justify-content: center;
        height: 90px;
        position: relative;
        box-shadow: 0 1px 3px rgba(0,0,0,0.3);
        transition: transform 0.2s;
    }
    .stock-card:hover { transform: scale(1.05); z-index: 10; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }
    
    /* Colors */
    .bull-card { background-color: #1e5f29 !important; } /* Dark Green */
    .bear-card { background-color: #b52524 !important; } /* Dark Red */
    .neut-card { background-color: #30363d !important; } /* Grey */
    .idx-card { background-color: #0d47a1 !important; border: 1px solid #1976d2; } /* Dark Blue for Indices */
    
    /* NORMAL TEXT FONTS */
    .t-name { font-size: 13px; font-weight: 500; margin-bottom: 2px; }
    .t-price { font-size: 17px; font-weight: 600; margin-bottom: 2px; }
    .t-pct { font-size: 12px; font-weight: 500; }
    
    /* Score Badge */
    .t-score { 
        position: absolute; top: 3px; left: 3px; 
        font-size: 10px; background: rgba(0,0,0,0.4); 
        padding: 1px 4px; border-radius: 3px; color: #ffd700; font-weight: normal;
    }
    
    /* Auto adjust columns based on screen size */
    @media screen and (max-width: 1400px) { .heatmap-grid { grid-template-columns: repeat(8, 1fr); } }
    @media screen and (max-width: 1100px) { .heatmap-grid { grid-template-columns: repeat(6, 1fr); } }
    @media screen and (max-width: 800px) { .heatmap-grid { grid-template-columns: repeat(4, 1fr); } }
    
    /* MOBILE PHONES */
    @media screen and (max-width: 600px) {
        .heatmap-grid { grid-template-columns: repeat(3, 1fr); gap: 6px; }
        .stock-card { height: 95px; }
        .t-name { font-size: 12px; }
        .t-price { font-size: 16px; }
        .t-pct { font-size: 11px; }
    }
    
    /* Chart Box Styling */
    .chart-box {
        border: 1px solid #30363d;
        border-radius: 8px;
        background: #161b22;
        padding: 10px;
        margin-bottom: 15px;
    }
    
    /* Indicator Labels above chart */
    .ind-labels {
        text-align: center;
        font-size: 10px;
        color: #8b949e;
        margin-bottom: 2px;
    }
    
    /* Custom HR Line */
    .custom-hr {
        border: 0;
        height: 1px;
        background: #30363d;
        margin: 15px 0;
    }
    </style>
""", unsafe_allow_html=True)

# --- 4. STOCK LISTS & INDICES ---
INDICES_MAP = {
    "^NSEI": "NIFTY",
    "^NSEBANK": "BANKNIFTY",
    "^INDIAVIX": "INDIA VIX"
}

TV_INDICES_URL = {
    "^NSEI": "NSE:NIFTY",
    "^NSEBANK": "NSE:BANKNIFTY",
    "^INDIAVIX": "NSE:INDIAVIX"
}

NIFTY_50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO", "BAJFINANCE", 
    "BAJAJFINSV", "BEL", "BHARTIARTL", "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB", "DRREDDY", 
    "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDUNILVR", 
    "ICICIBANK", "INDIGO", "INFY", "ITC", "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI", "NESTLEIND", 
    "NTPC", "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM", 
    "TATAMOTORS", "TATASTEEL", "TCS", "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO"
]

SECTOR_MAP = {
    "BANK": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK", "BANKBARODA", "PNB"],
    "IT": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM", "PERSISTENT", "COFORGE"],
    "AUTO": ["MARUTI", "M&M", "EICHERMOT", "BAJAJ-AUTO", "TVSMOTOR", "ASHOKLEY", "HEROMOTOCO"],
    "METAL": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "JINDALSTEL", "NMDC", "SAIL"],
    "PHARMA": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "LUPIN", "AUROPHARMA"],
    "FMCG": ["ITC", "HINDUNILVR", "BRITANNIA", "VBL", "NESTLEIND"],
    "ENERGY": ["RELIANCE", "NTPC", "ONGC", "POWERGRID", "BPCL", "TATAPOWER"],
    "REALTY": ["DLF", "GODREJPROP", "LODHA", "OBEROIRLTY"]
}

BROADER_MARKET = [
    "HAL", "BDL", "MAZDOCK", "COCHINSHIP", "GRSE", "RVNL", "IRFC", "IRCON", "TITAGARH", "RAILTEL", "RITES",
    "ADANIPOWER", "ADANIGREEN", "NHPC", "SJVN", "BHEL", "CGPOWER", "SUZLON", "PFC", "RECLTD", "IREDA", "IOB", "UCOBANK", "MAHABANK", "CANBK",
    "CHOLAFIN", "JIOFIN", "MUTHOOTFIN", "MANAPPURAM", "M&MFIN", "DIXON", "POLYCAB", "KAYNES", "HAVELLS", "KEI", "RRKABEL",
    "SRF", "TATACHEM", "DEEPAKNTR", "AARTIIND", "PIIND", "FACT", "UPL", "AMBUJACEM", "SHREECEM", "DALBHARAT", "CUMMINSIND", "ABB", "SIEMENS",
    "IDEA", "ZOMATO", "DMART", "PAYTM", "ZENTEC", "ATGL", "AWL", "BOSCHLTD", "MRF", "MOTHERSON", "SONACOMS", "EXIDEIND", "AMARAJABAT", "VEDL", "SAIL"
]

# --- 5. DATA FETCH & SCORE LOGIC ---
def get_minutes_passed():
    now = datetime.now()
    if now.weekday() >= 5 or now.time() > dt_time(15, 30): return 375
    open_time = now.replace(hour=9, minute=15, second=0)
    return min(375, max(1, int((now - open_time).total_seconds() / 60)))

@st.cache_data(ttl=60)
def fetch_all_data():
    all_stocks = set(NIFTY_50 + BROADER_MARKET)
    for stocks in SECTOR_MAP.values():
        all_stocks.update(stocks)
    
    tkrs = list(INDICES_MAP.keys()) + [f"{t}.NS" for t in all_stocks]
    # 🔥 FIX 1: ADDED threads=20 FOR LIGHTNING FAST DOWNLOAD 🔥
    data = yf.download(tkrs, period="5d", progress=False, group_by='ticker', threads=20)
    
    results = []
    minutes = get_minutes_passed()
    for symbol in data.columns.levels[0]:
        try:
            df = data[symbol].dropna(subset=['Close'])
            if len(df) < 2: continue
            ltp, open_p, prev_c, low, high = float(df['Close'].iloc[-1]), float(df['Open'].iloc[-1]), float(df['Close'].iloc[-2]), float(df['Low'].iloc[-1]), float(df['High'].iloc[-1])
            day_chg, net_chg = ((ltp - open_p) / open_p) * 100, ((ltp - prev_c) / prev_c) * 100
            vwap = (high + low + ltp) / 3
            
            if 'Volume' in df.columns and not df['Volume'].isna().all():
                avg_vol = df['Volume'].iloc[:-1].mean()
                curr_vol = float(df['Volume'].iloc[-1])
                vol_x = round(curr_vol / ((avg_vol/375) * minutes), 1) if avg_vol > 0 else 0.0
            else:
                vol_x = 0.0
                
            score = 0
            if abs(day_chg) >= 2.0: score += 3
            if abs(open_p - low) <= (ltp * 0.003) or abs(open_p - high) <= (ltp * 0.003): score += 3
            if vol_x > 1.0: score += 3
            if (ltp >= high * 0.998 and day_chg > 0.5) or (ltp <= low * 1.002 and day_chg < -0.5): score += 1
            if (ltp > (low * 1.01) and ltp > vwap) or (ltp < (high * 0.99) and ltp < vwap): score += 1
            
            disp_name = INDICES_MAP.get(symbol, symbol.replace(".NS", ""))
            results.append({"Fetch_T": symbol, "T": disp_name, "P": ltp, "C": net_chg, "S": score, "Is_Idx": symbol in INDICES_MAP})
        except: continue
    return pd.DataFrame(results)

def render_chart(row, chart_data):
    color = "#2ea043" if row['C'] >= 0 else "#da3633"
    if row['T'] == "INDIA VIX": color = "#da3633" if row['C'] >= 0 else "#2ea043"
    tv_link = f"https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(row['Fetch_T'], 'NSE:'+row['T'])}"
    st.markdown(f"<div class='chart-box'><div style='text-align:center; font-weight:bold; font-size:16px;'><a href='{tv_link}' target='_blank' style='color:white; text-decoration:none;'>{row['T']} <span style='color:{color}'>({row['C']:+.2f}%)</span></a></div><div class='ind-labels'><span style='color:#FFD700;'>--- VWAP</span> | <span style='color:#00BFFF;'>- - 10 EMA</span></div>", unsafe_allow_html=True)
    try:
        df_c = chart_data[row['Fetch_T']].dropna(subset=['Close']).copy() if isinstance(chart_data.columns, pd.MultiIndex) else chart_data.dropna(subset=['Close']).copy()
        if not df_c.empty:
            df_c['EMA_10'] = df_c['Close'].ewm(span=10, adjust=False).mean()
            df_c.index = pd.to_datetime(df_c.index)
            df_c = df_c[df_c.index.date == df_c.index.date.max()]
            df_c['VWAP'] = ((df_c['High']+df_c['Low']+df_c['Close'])/3 * df_c['Volume']).cumsum() / df_c['Volume'].cumsum() if 'Volume' in df_c.columns and df_c['Volume'].sum()>0 else (df_c['High']+df_c['Low']+df_c['Close'])/3
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df_c.index, open=df_c['Open'], high=df_c['High'], low=df_c['Low'], close=df_c['Close'], increasing_line_color='#2ea043', decreasing_line_color='#da3633'))
            fig.add_trace(go.Scatter(x=df_c.index, y=df_c['VWAP'], line=dict(color='#FFD700', width=1.5, dash='dot')))
            fig.add_trace(go.Scatter(x=df_c.index, y=df_c['EMA_10'], line=dict(color='#00BFFF', width=1.5, dash='dash')))
            fig.update_layout(margin=dict(l=0,r=0,t=0,b=0), height=150, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis=dict(visible=False, rangeslider=dict(visible=False)), yaxis=dict(visible=False, range=[min(df_c['Low'].min(), df_c['EMA_10'].min())*0.999, max(df_c['High'].max(), df_c['EMA_10'].max())*1.001]), showlegend=False)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
        else: st.markdown("<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888;'>Data not available</div>", unsafe_allow_html=True)
    except: st.markdown("<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888;'>Error loading chart</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

# --- 6. EXECUTION ---
df = fetch_all_data()
if not df.empty:
    c1, c2 = st.columns([0.6, 0.4])
    with c1: watchlist_mode = st.selectbox("Watchlist", ["High Score Stocks 🔥", "Nifty 50 Heatmap"], label_visibility="collapsed")
    with c2: view_mode = st.radio("Display", ["Heat Map", "Chart 📈"], horizontal=True, label_visibility="collapsed")

    # Order Indices strictly: NIFTY, BANKNIFTY, VIX
    df_idx = df[df['Is_Idx']].set_index('T').reindex(['NIFTY', 'BANKNIFTY', 'INDIA VIX']).reset_index()
    df_stk = df[~df['Is_Idx']].copy()

    # 🔥 FIX 2: CREATE A SINGLE SORTED LIST FOR BOTH HEATMAP AND CHARTS 🔥
    if watchlist_mode == "High Score Stocks 🔥":
        df_filtered = df_stk[(df_stk['S'] >= 7) & (df_stk['S'] <= 10)]
        greens = df_filtered[df_filtered['C'] >= 0].sort_values(by=["S", "C"], ascending=[False, False])
        reds = df_filtered[df_filtered['C'] < 0].sort_values(by=["S", "C"], ascending=[True, True])
        df_stocks_display = pd.concat([greens, reds])
    else:
        df_filtered = df_stk[df_stk['T'].isin(NIFTY_50)]
        greens = df_filtered[df_filtered['C'] >= 0].sort_values(by="C", ascending=False)
        reds = df_filtered[df_filtered['C'] < 0].sort_values(by="C", ascending=False)
        df_stocks_display = pd.concat([greens, reds])

    if view_mode == "Heat Map":
        # Indices Row
        html_idx = '<div class="heatmap-grid">'
        for _, r in df_idx.iterrows():
            bg = "idx-card" if r['T'] != "INDIA VIX" else ("bear-card" if r['C']>=0 else "bull-card")
            html_idx += f'<a href="https://in.tradingview.com/chart/?symbol={TV_INDICES_URL[r["Fetch_T"]]}" target="_blank" class="stock-card {bg}"><div class="t-score">IDX</div><div class="t-name">{r["T"]}</div><div class="t-price">{r["P"]:.2f}</div><div class="t-pct">{r["C"]:+.2f}%</div></a>'
        st.markdown(html_idx + '</div><hr class="custom-hr">', unsafe_allow_html=True)
        
        # Stocks Row (Using the properly sorted df_stocks_display)
        html_stk = '<div class="heatmap-grid">'
        for _, r in df_stocks_display.iterrows():
            bg = "bull-card" if r['C'] >= 0 else "bear-card"
            html_stk += f'<a href="https://in.tradingview.com/chart/?symbol=NSE:{r["T"]}" target="_blank" class="stock-card {bg}"><div class="t-score">⭐{int(r["S"])}</div><div class="t-name">{r["T"]}</div><div class="t-price">{r["P"]:.2f}</div><div class="t-pct">{r["C"]:+.2f}%</div></a>'
        st.markdown(html_stk + '</div>', unsafe_allow_html=True)
        
    else:
        # Charts View
        # Get exactly the top 27 from our ALREADY SORTED list
        top_stocks_for_charts = df_stocks_display.head(27)
        fetch_list = df_idx['Fetch_T'].tolist() + top_stocks_for_charts['Fetch_T'].tolist()
        
        with st.spinner("Loading 5-Min Candlestick Charts (Lightning Speed ⚡)..."):
            # 🔥 FIX 1: ADDED threads=20 FOR LIGHTNING FAST CHART DOWNLOAD 🔥
            chart_data = yf.download(fetch_list, period="5d", interval="5m", progress=False, group_by='ticker', threads=20)
        
        # 1. INDICES SECTION (STRICTLY FIRST)
        st.subheader("Indices")
        idx_cols = st.columns(3)
        for i, (_, r) in enumerate(df_idx.iterrows()):
            with idx_cols[i]: render_chart(r, chart_data)
        
        st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        # 2. STOCKS SECTION (Matches Heatmap Order Exactly)
        st.subheader("High Score Stocks")
        stk_list = [row for _, row in top_stocks_for_charts.iterrows()]
        
        for i in range(0, len(stk_list), 3):
            cols = st.columns(3)
            for j in range(3):
                if i + j < len(stk_list):
                    with cols[j]: render_chart(stk_list[i+j], chart_data)
else:
    st.info("Loading Market Data...")
