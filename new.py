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

# --- 3. CSS FOR STYLING ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {display: none !important;}
    .stApp { background-color: #0e1117; color: #ffffff; }
    .block-container { padding-top: 1rem !important; padding-bottom: 0rem !important; margin-top: -10px; }
    
    /* Grid for stocks */
    .heatmap-grid { display: grid; grid-template-columns: repeat(10, 1fr); gap: 8px; padding: 5px 0; }
    
    /* Standard Stock Card */
    .stock-card {
        border-radius: 4px; padding: 8px 4px; text-align: center; text-decoration: none !important;
        color: white !important; display: flex; flex-direction: column; justify-content: center;
        height: 90px; position: relative; box-shadow: 0 1px 3px rgba(0,0,0,0.3); transition: transform 0.2s;
    }
    .stock-card:hover { transform: scale(1.05); z-index: 10; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }
    
    /* Styles for the LARGE MOOD BOX in Heatmap */
    .large-mood-box {
        height: 90px; /* Match stock card height for alignment */
        display: flex; flex-direction: column; justify-content: center; align-items: center;
        border-radius: 6px; border: 2px solid rgba(255,255,255,0.2);
        box-shadow: 0 4px 10px rgba(0,0,0,0.5);
        text-align: center;
    }
    .large-mood-title { font-size: 13px; color: #ddd; letter-spacing: 1px; margin-bottom: 5px; font-weight: 600;}
    .large-mood-value { font-size: 24px; font-weight: 900; line-height: 1.2; }

    /* Colors */
    .bull-card { background-color: #1e5f29 !important; }
    .bear-card { background-color: #b52524 !important; }
    .neut-card { background-color: #30363d !important; }
    
    /* Fonts & Badges */
    .t-name { font-size: 13px; font-weight: 500; margin-bottom: 2px; }
    .t-price { font-size: 17px; font-weight: 600; margin-bottom: 2px; }
    .t-pct { font-size: 12px; font-weight: 500; }
    .t-score { position: absolute; top: 3px; left: 3px; font-size: 10px; background: rgba(0,0,0,0.4); padding: 1px 4px; border-radius: 3px; color: #ffd700; }

    /* Responsive */
    @media screen and (max-width: 1400px) { .heatmap-grid { grid-template-columns: repeat(8, 1fr); } }
    @media screen and (max-width: 1100px) { .heatmap-grid { grid-template-columns: repeat(6, 1fr); } }
    @media screen and (max-width: 800px) { .heatmap-grid { grid-template-columns: repeat(4, 1fr); } }
    @media screen and (max-width: 600px) { .heatmap-grid { grid-template-columns: repeat(3, 1fr); gap: 6px; } .stock-card { height: 95px; } }

    /* Chart Styles */
    .chart-box { border: 1px solid #30363d; border-radius: 8px; background: #161b22; padding: 10px; margin-bottom: 15px; }
    .ind-labels { text-align: center; font-size: 10px; color: #8b949e; margin-bottom: 2px; }
    .custom-hr { border: 0; height: 1px; background: #30363d; margin: 15px 0; }
    </style>
""", unsafe_allow_html=True)

# --- 4. DATA SETUP ---
INDICES_MAP = {"^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY", "^INDIAVIX": "INDIA VIX"}
TV_INDICES_URL = {"^NSEI": "NSE:NIFTY", "^NSEBANK": "NSE:BANKNIFTY", "^INDIAVIX": "NSE:INDIAVIX"}
NIFTY_50 = ["ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL", "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB", "DRREDDY", "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDIGO", "INFY", "ITC", "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TCS", "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO"]
SECTOR_MAP = {"BANK": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK", "BANKBARODA", "PNB"], "IT": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM", "PERSISTENT", "COFORGE"], "AUTO": ["MARUTI", "M&M", "EICHERMOT", "BAJAJ-AUTO", "TVSMOTOR", "ASHOKLEY", "HEROMOTOCO"], "METAL": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "JINDALSTEL", "NMDC", "SAIL"], "PHARMA": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "LUPIN", "AUROPHARMA"], "FMCG": ["ITC", "HINDUNILVR", "BRITANNIA", "VBL", "NESTLEIND"], "ENERGY": ["RELIANCE", "NTPC", "ONGC", "POWERGRID", "BPCL", "TATAPOWER"], "REALTY": ["DLF", "GODREJPROP", "LODHA", "OBEROIRLTY"]}
BROADER_MARKET = ["HAL", "BDL", "MAZDOCK", "COCHINSHIP", "GRSE", "RVNL", "IRFC", "IRCON", "TITAGARH", "RAILTEL", "RITES", "ADANIPOWER", "ADANIGREEN", "NHPC", "SJVN", "BHEL", "CGPOWER", "SUZLON", "PFC", "RECLTD", "IREDA", "IOB", "UCOBANK", "MAHABANK", "CANBK", "CHOLAFIN", "JIOFIN", "MUTHOOTFIN", "MANAPPURAM", "M&MFIN", "DIXON", "POLYCAB", "KAYNES", "HAVELLS", "KEI", "RRKABEL", "SRF", "TATACHEM", "DEEPAKNTR", "AARTIIND", "PIIND", "FACT", "UPL", "AMBUJACEM", "SHREECEM", "DALBHARAT", "CUMMINSIND", "ABB", "SIEMENS", "IDEA", "ZOMATO", "DMART", "PAYTM", "ZENTEC", "ATGL", "AWL", "BOSCHLTD", "MRF", "MOTHERSON", "SONACOMS", "EXIDEIND", "AMARAJABAT", "VEDL", "SAIL"]

# --- 5. DATA FETCH ---
def get_minutes_passed():
    now = datetime.now()
    if now.weekday() >= 5 or now.time() > dt_time(15, 30): return 375
    open_time = now.replace(hour=9, minute=15, second=0)
    return min(375, max(1, int((now - open_time).total_seconds() / 60)))

@st.cache_data(ttl=60)
def fetch_all_data():
    all_stocks = set(NIFTY_50 + BROADER_MARKET)
    for stocks in SECTOR_MAP.values(): all_stocks.update(stocks)
    tkrs = list(INDICES_MAP.keys()) + [f"{t}.NS" for t in all_stocks]
    data = yf.download(tkrs, period="5d", progress=False, group_by='ticker', threads=20)
    results = []
    minutes = get_minutes_passed()
    for symbol in data.columns.levels[0]:
        try:
            df = data[symbol].dropna(subset=['Close'])
            if len(df) < 2: continue
            ltp, open_p, prev_c, low, high = float(df['Close'].iloc[-1]), float(df['Open'].iloc[-1]), float(df['Close'].iloc[-2]), float(df['Low'].iloc[-1]), float(df['High'].iloc[-1])
            day_chg, net_chg = ((ltp - open_p) / open_p) * 100, ((ltp - prev_c) / prev_c) * 100
            vol_x = round(float(df['Volume'].iloc[-1]) / ((df['Volume'].iloc[:-1].mean()/375) * minutes), 1) if 'Volume' in df.columns and not df['Volume'].isna().all() and df['Volume'].iloc[:-1].mean() > 0 else 0.0
            vwap = (high + low + ltp) / 3
            score = 0
            if abs(day_chg) >= 2.0: score += 3
            if abs(open_p - low) <= (ltp * 0.003) or abs(open_p - high) <= (ltp * 0.003): score += 3
            if vol_x > 1.0: score += 3
            if (ltp >= high * 0.998 and day_chg > 0.5) or (ltp <= low * 1.002 and day_chg < -0.5): score += 1
            if (ltp > (low * 1.01) and ltp > vwap) or (ltp < (high * 0.99) and ltp < vwap): score += 1
            results.append({"Fetch_T": symbol, "T": INDICES_MAP.get(symbol, symbol.replace(".NS", "")), "P": ltp, "C": net_chg, "S": score, "Is_Index": symbol in INDICES_MAP})
        except: continue
    return pd.DataFrame(results)

def render_chart(row, chart_data):
    color = "#2ea043" if row['C'] >= 0 else "#da3633"
    tv_link = f"https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(row['Fetch_T'], 'NSE:'+row['T'])}"
    st.markdown(f"<div class='chart-box'><div style='text-align:center; font-weight:bold; font-size:16px;'><a href='{tv_link}' target='_blank' style='color:white; text-decoration:none;'>{row['T']} <span style='color:{color}'>({row['C']:+.2f}%)</span></a></div><div class='ind-labels'><span style='color:#FFD700;'>--- VWAP</span> | <span style='color:#00BFFF;'>- - 10 EMA</span></div>", unsafe_allow_html=True)
    try:
        df_c = chart_data[row['Fetch_T']].dropna(subset=['Close']).copy() if isinstance(chart_data.columns, pd.MultiIndex) else chart_data.dropna(subset=['Close']).copy()
        if not df_c.empty:
            df_c['EMA_10'] = df_c['Close'].ewm(span=10, adjust=False).mean()
            df_c.index = pd.to_datetime(df_c.index)
            df_c = df_c[df_c.index.date == df_c.index.date.max()]
            df_c['VWAP'] = ((df_c['High']+df_c['Low']+df_c['Close'])/3 * df_c['Volume']).cumsum() / df_c['Volume'].cumsum() if 'Volume' in df_c.columns and df_c['Volume'].sum()>0 else (df_c['High']+df_c['Low']+df_c['Close'])/3
            min_v, max_v = df_c[['Low','VWAP','EMA_10']].min().min(), df_c[['High','VWAP','EMA_10']].max().max()
            pad = (max_v - min_v) * 0.1 if (max_v - min_v) != 0 else min_v*0.005
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=df_c.index, open=df_c['Open'], high=df_c['High'], low=df_c['Low'], close=df_c['Close'], increasing_line_color='#2ea043', decreasing_line_color='#da3633'))
            fig.add_trace(go.Scatter(x=df_c.index, y=df_c['VWAP'], line=dict(color='#FFD700', width=1.5, dash='dot')))
            fig.add_trace(go.Scatter(x=df_c.index, y=df_c['EMA_10'], line=dict(color='#00BFFF', width=1.5, dash='dash')))
            fig.update_layout(margin=dict(l=0,r=0,t=0,b=0), height=150, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis=dict(visible=False, rangeslider=dict(visible=False)), yaxis=dict(visible=False, range=[min_v-pad, max_v+pad]), showlegend=False)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
        else: st.markdown("<div style='height:150px;center;color:#888;'>No Data</div>", unsafe_allow_html=True)
    except: st.markdown("<div style='height:150px;center;color:#888;'>Error</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

# --- 6. MAIN APP ---
df = fetch_all_data()
if not df.empty:
    c1, c2 = st.columns([0.6, 0.4])
    with c1: watchlist_mode = st.selectbox("Watchlist", ["High Score Stocks 🔥", "Nifty 50 Heatmap"], label_visibility="collapsed")
    with c2: view_mode = st.radio("Display", ["Heat Map", "Chart 📈"], horizontal=True, label_visibility="collapsed")

    df_idx = df[df['Is_Index']].set_index('T').reindex(['NIFTY', 'BANKNIFTY', 'INDIA VIX']).reset_index()
    df_stk = df[~df['Is_Index']].copy()

    mood_text, mood_class = "NEUTRAL ⚖️", "neut-card"
    if not df_idx.empty:
        n_chg = float(df_idx[df_idx['T']=='NIFTY']['C'].iloc[0])
        if n_chg >= 0.10: mood_text, mood_class = "BULLISH 🚀", "bull-card"
        elif n_chg <= -0.10: mood_text, mood_class = "BEARISH 🩸", "bear-card"

    if watchlist_mode == "Nifty 50 Heatmap":
        df_filt = df_stk[df_stk['T'].isin(NIFTY_50)]
        df_disp = pd.concat([df_filt[df_filt['C']>=0].sort_values(by="C", ascending=False), df_filt[df_filt['C']<0].sort_values(by="C", ascending=False)])
    else:
        df_filt = df_stk[(df_stk['S'] >= 7)]
        df_disp = pd.concat([df_filt[df_filt['C']>0].sort_values(by=["S","C"], ascending=[False,False]), df_filt[df_filt['C']==0].sort_values(by="S", ascending=False), df_filt[df_filt['C']<0].sort_values(by=["S","C"], ascending=[True,True])])

    if view_mode == "Heat Map":
        st.markdown("### 📊 Market Indices", unsafe_allow_html=True)
        if not df_idx.empty:
            # 🔥 CUSTOM COLUMNS FOR INDICES + GAP + LARGE MOOD BOX 🔥
            # Ratios: 3 small indices, 1 empty gap, 1 wide mood box
            i_cols = st.columns([1.5, 1.5, 1.5, 0.3, 3.5]) 
            idx_rows = [row for _, row in df_idx.iterrows()]
            
            for i in range(3): # Render Nifty, BN, Vix
                with i_cols[i]:
                    r = idx_rows[i]
                    bg = "bull-card" if r['C'] >= 0 else "bear-card"
                    sign = "+" if r['C'] > 0 else ""
                    st.markdown(f'<a href="https://in.tradingview.com/chart/?symbol={TV_INDICES_URL[r["Fetch_T"]]}" target="_blank" class="stock-card {bg}"><div class="t-score">IDX</div><div class="t-name">{r["T"]}</div><div class="t-price">{r["P"]:.2f}</div><div class="t-pct">{sign}{r["C"]:.2f}%</div></a>', unsafe_allow_html=True)
            
            # Skip i_cols[3] for the GAP
            
            with i_cols[4]: # Render Large Mood Box
                st.markdown(f'<div class="large-mood-box {mood_class}"><div class="large-mood-title">TODAY\'S MARKET MOOD</div><div class="large-mood-value">{mood_text}</div></div>', unsafe_allow_html=True)
            
            st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)

        st.markdown("### 🔥 High Score Stocks")
        html_stk = '<div class="heatmap-grid">'
        for _, r in df_disp.iterrows():
            bg = "bull-card" if r['C'] >= 0 else "bear-card"
            sign = "+" if r['C'] > 0 else ""
            html_stk += f'<a href="https://in.tradingview.com/chart/?symbol=NSE:{r["T"]}" target="_blank" class="stock-card {bg}"><div class="t-score">⭐{int(r["S"])}</div><div class="t-name">{r["T"]}</div><div class="t-price">{r["P"]:.2f}</div><div class="t-pct">{sign}{r["C"]:.2f}%</div></a>'
        st.markdown(html_stk + '</div>', unsafe_allow_html=True)
        
    else:
        st.markdown("<br>", unsafe_allow_html=True)
        top_stks = df_disp.head(27)
        with st.spinner("Loading Charts (Lightning Speed ⚡)..."):
            chart_data = yf.download(df_idx['Fetch_T'].tolist() + top_stks['Fetch_T'].tolist(), period="5d", interval="5m", progress=False, group_by='ticker', threads=20)
        
        # 🔥 INDICES CHARTS ONLY (Mood box removed from here) 🔥
        st.markdown("### 📈 Market Indices", unsafe_allow_html=True)
        if not df_idx.empty:
            idx_cols = st.columns(3)
            for i, (_, r) in enumerate(df_idx.iterrows()):
                with idx_cols[i]: render_chart(r, chart_data)
        st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        st.markdown("### 🔥 High Score Stocks")
        if not top_stks.empty:
            stk_list = [row for _, row in top_stocks.iterrows()]
            for i in range(0, len(stk_list), 3):
                cols = st.columns(3)
                for j in range(3):
                    if i + j < len(stk_list):
                        with cols[j]: render_chart(stk_list[i+j], chart_data)
else: st.info("Loading Market Data...")
