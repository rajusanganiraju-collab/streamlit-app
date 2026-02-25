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
        padding: 10px 0;
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
    </style>
""", unsafe_allow_html=True)

# --- 4. STOCK LISTS ---
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
    "IDEA", "ZOMATO", "DMART", "PAYTM", "ZENTEC", "ATGL", "AWL", "BOSCHLTD", "MRF", "MOTHERSON", "SONACOMS", "EXIDEIND", "AMARAJABAT"
]

# --- 5. DATA FETCH & SCORE LOGIC ---
def get_minutes_passed():
    now = datetime.now()
    if now.weekday() >= 5 or now.time() > dt_time(15, 30): return 375
    open_time = now.replace(hour=9, minute=15, second=0)
    diff = (now - open_time).total_seconds() / 60
    return min(375, max(1, int(diff)))

@st.cache_data(ttl=60)
def fetch_all_data():
    all_stocks = set(NIFTY_50 + BROADER_MARKET)
    for stocks in SECTOR_MAP.values():
        all_stocks.update(stocks)
    
    tkrs = [f"{t}.NS" for t in all_stocks]
    data = yf.download(tkrs, period="5d", progress=False, group_by='ticker', threads=False)
    
    results = []
    minutes = get_minutes_passed()

    for symbol in data.columns.levels[0]:
        try:
            df = data[symbol].dropna()
            if len(df) < 2: continue
            
            ltp = float(df['Close'].iloc[-1])
            open_p = float(df['Open'].iloc[-1])
            prev_c = float(df['Close'].iloc[-2])
            low = float(df['Low'].iloc[-1])
            high = float(df['High'].iloc[-1])
            
            day_chg = ((ltp - open_p) / open_p) * 100
            net_chg = ((ltp - prev_c) / prev_c) * 100
            
            avg_vol = df['Volume'].iloc[:-1].mean()
            curr_vol = float(df['Volume'].iloc[-1])
            vol_x = round(curr_vol / ((avg_vol/375) * minutes), 1) if avg_vol > 0 else 0.0
            vwap = (high + low + ltp) / 3
            
            score = 0
            is_open_low = abs(open_p - low) <= (ltp * 0.003)
            is_open_high = abs(open_p - high) <= (ltp * 0.003)
            
            if day_chg >= 2.0 or day_chg <= -2.0: score += 3 
            if is_open_low or is_open_high: score += 3 
            if vol_x > 1.0: score += 3 
            if (ltp >= high * 0.998 and day_chg > 0.5) or (ltp <= low * 1.002 and day_chg < -0.5): score += 1
            if (ltp > (low * 1.01) and ltp > vwap) or (ltp < (high * 0.99) and ltp < vwap): score += 1
            
            results.append({
                "T": symbol.replace(".NS", ""), "P": ltp, "C": net_chg, "S": score
            })
        except: continue
        
    return pd.DataFrame(results)

# --- 6. TOP NAVIGATION ---
st.markdown("<div style='background-color:#161b22; padding:10px; border-radius:8px; margin-bottom:15px; border: 1px solid #30363d;'>", unsafe_allow_html=True)
c1, c2 = st.columns([0.6, 0.4])

with c1:
    watchlist_mode = st.selectbox("Watchlist", ["High Score Stocks 🔥", "Nifty 50 Heatmap"], label_visibility="collapsed")
with c2:
    view_mode = st.radio("Display", ["Heat Map", "Chart 📈"], horizontal=True, label_visibility="collapsed")
st.markdown("</div>", unsafe_allow_html=True)

# --- 7. RENDER LOGIC ---
df = fetch_all_data()

if not df.empty:
    
    if watchlist_mode == "Nifty 50 Heatmap":
        df_filtered = df[df['T'].isin(NIFTY_50)]
        greens = df_filtered[df_filtered['C'] >= 0].sort_values(by="C", ascending=False)
        reds = df_filtered[df_filtered['C'] < 0].sort_values(by="C", ascending=False)
        df_display = pd.concat([greens, reds])
        st.markdown("### Nifty 50 Stocks")
    
    else:
        df_filtered = df[df['S'] >= 4]
        greens = df_filtered[df_filtered['C'] > 0].sort_values(by=["S", "C"], ascending=[False, False])
        neuts = df_filtered[df_filtered['C'] == 0].sort_values(by="S", ascending=False)
        reds = df_filtered[df_filtered['C'] < 0].sort_values(by=["S", "C"], ascending=[True, True])
        df_display = pd.concat([greens, neuts, reds])
        st.markdown("### 🔥 High Score Stocks (Across All Sectors)")

    if view_mode == "Heat Map":
        html = '<div class="heatmap-grid">'
        for _, row in df_display.iterrows():
            bg = "bull-card" if row['C'] > 0 else ("bear-card" if row['C'] < 0 else "neut-card")
            sign = "+" if row['C'] > 0 else ""
            
            html += f'<a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank" class="stock-card {bg}"><div class="t-score">⭐{row["S"]}</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{sign}{row["C"]:.2f}%</div></a>'
            
        html += '</div>'
        st.markdown(html, unsafe_allow_html=True)
        
    else:
        st.markdown("<br>", unsafe_allow_html=True)
        cols = st.columns(3) 
        
        top_tickers = df_display.head(30)['T'].tolist()
        fetch_tickers = [f"{t}.NS" for t in top_tickers]
        
        with st.spinner("Loading 5-Min Candlestick Charts with VWAP & EMA..."):
            chart_data = yf.download(fetch_tickers, period="5d", interval="5m", progress=False, group_by='ticker', threads=True)
        
        for idx, row in df_display.head(30).iterrows():
            col = cols[idx % 3]
            ticker = row['T']
            
            with col:
                color_hex = "#2ea043" if row['C'] >= 0 else "#da3633"
                sign = "+" if row['C'] > 0 else ""
                
                st.markdown(f"<div class='chart-box'>", unsafe_allow_html=True)
                st.markdown(f"<div style='text-align:center; font-weight:bold; font-size:16px;'>{ticker} <span style='color:{color_hex}'>({sign}{row['C']:.2f}%)</span></div>", unsafe_allow_html=True)
                # Legend for VWAP & EMA
                st.markdown(f"<div class='ind-labels'><span style='color:#FFD700; font-weight:bold;'>--- VWAP</span> &nbsp;|&nbsp; <span style='color:#00BFFF; font-weight:bold;'>- - 10 EMA</span></div>", unsafe_allow_html=True)
                
                try:
                    if len(fetch_tickers) == 1:
                        df_chart = chart_data.copy()
                    else:
                        df_chart = chart_data[f"{ticker}.NS"].copy()
                        
                    df_chart = df_chart.dropna()
                    
                    if not df_chart.empty:
                        # 1. Calculate 10 EMA continuously over the 5 days for accuracy
                        df_chart['EMA_10'] = df_chart['Close'].ewm(span=10, adjust=False).mean()
                        
                        # 2. Filter to only the LAST trading day
                        df_chart.index = pd.to_datetime(df_chart.index)
                        last_trading_date = df_chart.index.date.max()
                        df_chart = df_chart[df_chart.index.date == last_trading_date]
                        
                        # 3. Calculate VWAP just for the day (Reset daily)
                        df_chart['Typical_Price'] = (df_chart['High'] + df_chart['Low'] + df_chart['Close']) / 3
                        df_chart['VWAP'] = (df_chart['Typical_Price'] * df_chart['Volume']).cumsum() / df_chart['Volume'].cumsum()
                        
                        # Y-axis auto zoom calculation using HIGH and LOW for Candlesticks
                        min_val = df_chart[['Low', 'VWAP', 'EMA_10']].min().min()
                        max_val = df_chart[['High', 'VWAP', 'EMA_10']].max().max()
                        y_padding = (max_val - min_val) * 0.1
                        if y_padding == 0: y_padding = min_val * 0.005 
                        
                        fig = go.Figure()
                        
                        # 🔥 MAIN CANDLESTICK TRACE 🔥
                        fig.add_trace(go.Candlestick(
                            x=df_chart.index,
                            open=df_chart['Open'],
                            high=df_chart['High'],
                            low=df_chart['Low'],
                            close=df_chart['Close'],
                            increasing_line_color='#2ea043', # Green candles
                            decreasing_line_color='#da3633', # Red candles
                            name='Price'
                        ))
                        
                        # VWAP Line (Yellow, Dotted)
                        fig.add_trace(go.Scatter(
                            x=df_chart.index, y=df_chart['VWAP'], mode='lines', 
                            line=dict(color='#FFD700', width=1.5, dash='dot')
                        ))
                        
                        # 10 EMA Line (Blue, Dashed)
                        fig.add_trace(go.Scatter(
                            x=df_chart.index, y=df_chart['EMA_10'], mode='lines', 
                            line=dict(color='#00BFFF', width=1.5, dash='dash')
                        ))
                        
                        fig.update_layout(
                            margin=dict(l=0, r=0, t=0, b=0),
                            height=150, 
                            paper_bgcolor='rgba(0,0,0,0)', 
                            plot_bgcolor='rgba(0,0,0,0)',
                            # Rangeslider MUST be disabled for mini candlestick charts
                            xaxis=dict(visible=False, rangeslider=dict(visible=False)), 
                            yaxis=dict(visible=False, range=[min_val - y_padding, max_val + y_padding]), 
                            hovermode=False,
                            showlegend=False
                        )
                        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
                    else:
                        st.markdown("<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888;'>Data not available</div>", unsafe_allow_html=True)
                except Exception as e:
                    st.markdown("<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888;'>Chart loading error</div>", unsafe_allow_html=True)
                
                st.markdown("</div>", unsafe_allow_html=True)
else:
    st.info("Loading Market Data...")
