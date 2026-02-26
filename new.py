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
    
    /* MOOD BOX SPECIFIC STYLES */
    .mood-box {
        grid-column: span 2; /* Takes 2 columns width on desktop */
        border: 2px solid rgba(255,255,255,0.4);
        box-shadow: 0 0 10px rgba(0,0,0,0.5);
    }
    .hide-mobile { grid-column: span 1; } /* Empty gap on desktop */

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
        .hide-mobile { display: none; } /* Remove gap on mobile */
        .mood-box { grid-column: span 3; margin-top: 5px; } /* Full width on mobile */
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
    # 🔥 THREADS=20 ADDED FOR HIGH SPEED DATA FETCH 🔥
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
            is_open_low = abs(open_p - low) <= (ltp * 0.003)
            is_open_high = abs(open_p - high) <= (ltp * 0.003)
            
            if day_chg >= 2.0 or day_chg <= -2.0: score += 3 
            if is_open_low or is_open_high: score += 3 
            if vol_x > 1.0: score += 3 
            if (ltp >= high * 0.998 and day_chg > 0.5) or (ltp <= low * 1.002 and day_chg < -0.5): score += 1
            if (ltp > (low * 1.01) and ltp > vwap) or (ltp < (high * 0.99) and ltp < vwap): score += 1
            
            if symbol in INDICES_MAP:
                disp_name = INDICES_MAP[symbol]
                is_index = True
            else:
                disp_name = symbol.replace(".NS", "")
                is_index = False
            
            results.append({
                "Fetch_T": symbol, "T": disp_name, "P": ltp, "C": net_chg, "S": score, "Is_Index": is_index
            })
        except: continue
        
    return pd.DataFrame(results)

# --- HELPER FUNCTION TO DRAW CHARTS ---
def render_chart(row, chart_data):
    fetch_sym = row['Fetch_T']
    display_sym = row['T']
    
    color_hex = "#2ea043" if row['C'] >= 0 else "#da3633"
        
    sign = "+" if row['C'] > 0 else ""
    tv_link = f"https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(fetch_sym, 'NSE:' + display_sym)}"
    
    st.markdown(f"<div class='chart-box'>", unsafe_allow_html=True)
    st.markdown(f"<div style='text-align:center; font-weight:bold; font-size:16px;'><a href='{tv_link}' target='_blank' style='color:#ffffff; text-decoration:none;'>{display_sym} <span style='color:{color_hex}'>({sign}{row['C']:.2f}%)</span></a></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='ind-labels'><span style='color:#FFD700; font-weight:bold;'>--- VWAP</span> &nbsp;|&nbsp; <span style='color:#00BFFF; font-weight:bold;'>- - 10 EMA</span></div>", unsafe_allow_html=True)
    
    try:
        df_chart = chart_data[fetch_sym].copy() if isinstance(chart_data.columns, pd.MultiIndex) else chart_data.copy()
        df_chart = df_chart.dropna(subset=['Close'])
        
        if not df_chart.empty:
            df_chart['EMA_10'] = df_chart['Close'].ewm(span=10, adjust=False).mean()
            df_chart.index = pd.to_datetime(df_chart.index)
            last_trading_date = df_chart.index.date.max()
            df_chart = df_chart[df_chart.index.date == last_trading_date]
            
            df_chart['Typical_Price'] = (df_chart['High'] + df_chart['Low'] + df_chart['Close']) / 3
            if 'Volume' in df_chart.columns and df_chart['Volume'].fillna(0).sum() > 0:
                df_chart['VWAP'] = (df_chart['Typical_Price'] * df_chart['Volume']).cumsum() / df_chart['Volume'].cumsum()
            else:
                df_chart['VWAP'] = df_chart['Typical_Price'].expanding().mean()
            
            min_val, max_val = df_chart[['Low', 'VWAP', 'EMA_10']].min().min(), df_chart[['High', 'VWAP', 'EMA_10']].max().max()
            y_padding = (max_val - min_val) * 0.1 if (max_val - min_val) != 0 else min_val * 0.005 
            
            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'], 
                increasing_line_color='#2ea043', decreasing_line_color='#da3633', name='Price'
            ))
            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['VWAP'], mode='lines', line=dict(color='#FFD700', width=1.5, dash='dot')))
            fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA_10'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash')))
            
            fig.update_layout(
                margin=dict(l=0, r=0, t=0, b=0), height=150, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', 
                xaxis=dict(visible=False, rangeslider=dict(visible=False)), yaxis=dict(visible=False, range=[min_val - y_padding, max_val + y_padding]), 
                hovermode=False, showlegend=False
            )
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
        else:
            st.markdown("<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888;'>Data not available</div>", unsafe_allow_html=True)
    except Exception as e:
        st.markdown("<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888;'>Chart loading error</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


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
    
    # 🌟 SEPARATE INDICES AND STOCKS 🌟
    df_indices = df[df['Is_Index']].copy()
    df_indices['Order'] = df_indices['T'].map({"NIFTY": 1, "BANKNIFTY": 2, "INDIA VIX": 3})
    df_indices = df_indices.sort_values("Order")
    
    df_stocks = df[~df['Is_Index']].copy()
    
    # 🔥 TODAY'S MARKET MOOD LOGIC 🔥
    market_mood_text = "NEUTRAL ⚖️"
    mood_class = "neut-card"
    
    nifty_row = df_indices[df_indices['T'] == 'NIFTY']
    if not nifty_row.empty:
        n_chg = float(nifty_row['C'].iloc[0])
        if n_chg >= 0.10: 
            market_mood_text = "BULLISH 🚀"
            mood_class = "bull-card"
        elif n_chg <= -0.10: 
            market_mood_text = "BEARISH 🩸"
            mood_class = "bear-card"
    
    if watchlist_mode == "Nifty 50 Heatmap":
        df_filtered = df_stocks[df_stocks['T'].isin(NIFTY_50)]
        greens = df_filtered[df_filtered['C'] >= 0].sort_values(by="C", ascending=False)
        reds = df_filtered[df_filtered['C'] < 0].sort_values(by="C", ascending=False)
        df_stocks_display = pd.concat([greens, reds])
    
    else:
        df_filtered = df_stocks[(df_stocks['S'] >= 7) & (df_stocks['S'] <= 10)]
        greens = df_filtered[df_filtered['C'] > 0].sort_values(by=["S", "C"], ascending=[False, False])
        neuts = df_filtered[df_filtered['C'] == 0].sort_values(by="S", ascending=False)
        reds = df_filtered[df_filtered['C'] < 0].sort_values(by=["S", "C"], ascending=[True, True])
        df_stocks_display = pd.concat([greens, neuts, reds])

    if view_mode == "Heat Map":
        
        # 1. RENDER INDICES FIRST + MOOD BOX
        st.markdown("### 📊 Market Indices", unsafe_allow_html=True)
        
        if not df_indices.empty:
            # 🔥 BACK TO PERFECT GRID LAYOUT 🔥
            html_idx = '<div class="heatmap-grid">'
            
            # Print Nifty, BankNifty, Vix
            for _, row in df_indices.iterrows():
                bg = "bull-card" if row['C'] >= 0 else "bear-card"
                badge = "IDX"
                sign = "+" if row['C'] > 0 else ""
                tv_sym = TV_INDICES_URL.get(row['Fetch_T'], "")
                tv_link = f"https://in.tradingview.com/chart/?symbol={tv_sym}"
                
                html_idx += f'<a href="{tv_link}" target="_blank" class="stock-card {bg}"><div class="t-score">{badge}</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{sign}{row["C"]:.2f}%</div></a>'
            
            # GAP (Hidden on Mobile)
            html_idx += '<div class="hide-mobile"></div>'
            
            # 🔥 THE NEW LARGE MOOD BOX 🔥
            html_idx += f'''
            <div class="stock-card mood-box {mood_class}">
                <div style="font-size: 13px; color: #ddd; margin-bottom: 5px; font-weight: bold; letter-spacing: 1px;">TODAY'S MOOD</div>
                <div style="font-size: 22px; font-weight: 900;">{market_mood_text}</div>
            </div>
            '''
            
            html_idx += '</div>'
            st.markdown(html_idx, unsafe_allow_html=True)
            
            st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        # 2. RENDER STOCKS
        st.markdown("### 🔥 High Score Stocks")
        html_stk = '<div class="heatmap-grid">'
        for _, row in df_stocks_display.iterrows():
            bg = "bull-card" if row['C'] >= 0 else "bear-card"
            badge = f"⭐{int(row['S'])}"
            sign = "+" if row['C'] > 0 else ""
            tv_link = f"https://in.tradingview.com/chart/?symbol=NSE:{row['T']}"
            
            html_stk += f'<a href="{tv_link}" target="_blank" class="stock-card {bg}"><div class="t-score">{badge}</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{sign}{row["C"]:.2f}%</div></a>'
        html_stk += '</div>'
        st.markdown(html_stk, unsafe_allow_html=True)
        
    else:
        # === MINI CHARTS ===
        st.markdown("<br>", unsafe_allow_html=True)
        
        top_stocks_for_charts = df_stocks_display.head(27)
        fetch_tickers = df_indices['Fetch_T'].tolist() + top_stocks_for_charts['Fetch_T'].tolist()
        
        with st.spinner("Loading 5-Min Candlestick Charts (Lightning Speed ⚡)..."):
            chart_data = yf.download(fetch_tickers, period="5d", interval="5m", progress=False, group_by='ticker', threads=20)
        
        # 1. RENDER INDICES CHARTS FIRST (NO MOOD BOX HERE)
        st.markdown("### 📈 Market Indices", unsafe_allow_html=True)
        
        if not df_indices.empty:
            idx_list = [row for _, row in df_indices.iterrows()]
            for i in range(0, len(idx_list), 3):
                cols = st.columns(3)
                for j in range(3):
                    if i + j < len(idx_list):
                        with cols[j]:
                            render_chart(idx_list[i + j], chart_data)
                            
        st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        # 2. RENDER STOCKS CHARTS
        st.markdown("### 🔥 High Score Stocks")
        if not top_stocks_for_charts.empty:
            stk_list = [row for _, row in top_stocks_for_charts.iterrows()]
            for i in range(0, len(stk_list), 3):
                cols = st.columns(3)
                for j in range(3):
                    if i + j < len(stk_list):
                        with cols[j]:
                            render_chart(stk_list[i + j], chart_data)

else:
    st.info("Loading Market Data...")
