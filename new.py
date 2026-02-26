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
    .neut-card { background-color: #30363d !important; } /* Grey Neutral */
    
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
def render_chart(row, df_chart):
    display_sym = row['T']
    fetch_sym = row['Fetch_T']
    
    # Text Color Logic
    if display_sym == "INDIA VIX": 
        color_hex = "#da3633" if row['C'] > 0 else ("#2ea043" if row['C'] < 0 else "#8b949e")
    else:
        color_hex = "#2ea043" if row['C'] > 0 else ("#da3633" if row['C'] < 0 else "#8b949e")
        
    sign = "+" if row['C'] > 0 else ""
    tv_link = f"https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(fetch_sym, 'NSE:' + display_sym)}"
    
    st.markdown(f"<div class='chart-box'>", unsafe_allow_html=True)
    st.markdown(f"<div style='text-align:center; font-weight:bold; font-size:16px;'><a href='{tv_link}' target='_blank' style='color:#ffffff; text-decoration:none;'>{display_sym} <span style='color:{color_hex}'>({sign}{row['C']:.2f}%)</span></a></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='ind-labels'><span style='color:#FFD700; font-weight:bold;'>--- VWAP</span> &nbsp;|&nbsp; <span style='color:#00BFFF; font-weight:bold;'>- - 10 EMA</span></div>", unsafe_allow_html=True)
    
    try:
        if not df_chart.empty:
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
    
    df_indices = df[df['Is_Index']].copy()
    df_indices['Order'] = df_indices['T'].map({"NIFTY": 1, "BANKNIFTY": 2, "INDIA VIX": 3})
    df_indices = df_indices.sort_values("Order")
    
    df_stocks = df[~df['Is_Index']].copy()
    
    if watchlist_mode == "Nifty 50 Heatmap":
        df_filtered = df_stocks[df_stocks['T'].isin(NIFTY_50)]
        greens = df_filtered[df_filtered['C'] >= 0].sort_values(by="C", ascending=False)
        reds = df_filtered[df_filtered['C'] < 0].sort_values(by="C", ascending=False)
        df_stocks_display = pd.concat([greens, reds])
    else:
        df_filtered = df_stocks[(df_stocks['S'] >= 7) & (df_stocks['S'] <= 10)]
        greens = df_filtered[df_filtered['C'] >= 0].sort_values(by=["S", "C"], ascending=[False, False])
        reds = df_filtered[df_filtered['C'] < 0].sort_values(by=["S", "C"], ascending=[True, True])
        df_stocks_display = pd.concat([greens, reds])

    # 🔥 FETCH 5-MIN DATA ONCE FOR BOTH TOP BOXES AND CHARTS 🔥
    all_display_tickers = df_indices['Fetch_T'].tolist() + df_stocks_display['Fetch_T'].tolist()
    
    with st.spinner("Analyzing VWAP & EMA Trends..."):
        five_min_data = yf.download(all_display_tickers, period="5d", interval="5m", progress=False, group_by='ticker', threads=20)

    # 🌟 YOUR EXACT LOGIC FOR TOP TREND BOXES 🌟
    bull_cnt = 0
    bear_cnt = 0
    neut_cnt = 0
    
    # We will process 5-min data and store it so we don't have to calculate VWAP twice
    processed_charts = {}

    for sym in all_display_tickers:
        try:
            df_s = five_min_data[sym].dropna(subset=['Close']).copy() if isinstance(five_min_data.columns, pd.MultiIndex) else five_min_data.dropna(subset=['Close']).copy()
            if df_s.empty: 
                processed_charts[sym] = pd.DataFrame()
                continue
            
            df_s['EMA_10'] = df_s['Close'].ewm(span=10, adjust=False).mean()
            df_s.index = pd.to_datetime(df_s.index)
            last_date = df_s.index.date.max()
            df_day = df_s[df_s.index.date == last_date].copy()
            
            if not df_day.empty:
                df_day['Typical_Price'] = (df_day['High'] + df_day['Low'] + df_day['Close']) / 3
                if 'Volume' in df_day.columns and df_day['Volume'].fillna(0).sum() > 0:
                    df_day['VWAP'] = (df_day['Typical_Price'] * df_day['Volume']).cumsum() / df_day['Volume'].cumsum()
                else:
                    df_day['VWAP'] = df_day['Typical_Price'].expanding().mean()
                
                processed_charts[sym] = df_day
                
                # Check VWAP & EMA Logic ONLY for Stocks (Not Indices) to show in the boxes
                if sym in df_stocks_display['Fetch_T'].tolist():
                    last_price = df_day['Close'].iloc[-1]
                    last_vwap = df_day['VWAP'].iloc[-1]
                    last_ema = df_day['EMA_10'].iloc[-1]
                    
                    if last_price > last_vwap and last_price > last_ema:
                        bull_cnt += 1
                    elif last_price < last_vwap and last_price < last_ema:
                        bear_cnt += 1
                    else:
                        neut_cnt += 1
            else:
                processed_charts[sym] = pd.DataFrame()
        except:
            processed_charts[sym] = pd.DataFrame()

    # --- TOP TREND BOXES DISPLAY ---
    st.markdown(f"""
    <div style='display:flex; justify-content:space-between; margin-bottom: 15px; gap: 8px;'>
        <div style='flex:1; background-color:rgba(30, 95, 41, 0.4); border: 1px solid #1e5f29; padding:8px; border-radius:6px; text-align:center; font-weight:bold; font-size:15px;'>
            🟢 Bullish : {bull_cnt}
        </div>
        <div style='flex:1; background-color:rgba(48, 54, 61, 0.4); border: 1px solid #30363d; padding:8px; border-radius:6px; text-align:center; font-weight:bold; font-size:15px;'>
            ⚪ Neutral : {neut_cnt}
        </div>
        <div style='flex:1; background-color:rgba(181, 37, 36, 0.4); border: 1px solid #b52524; padding:8px; border-radius:6px; text-align:center; font-weight:bold; font-size:15px;'>
            🔴 Bearish : {bear_cnt}
        </div>
    </div>
    """, unsafe_allow_html=True)


    if view_mode == "Heat Map":
        
        # 1. RENDER INDICES FIRST
        if not df_indices.empty:
            html_idx = '<div class="heatmap-grid">'
            for _, row in df_indices.iterrows():
                if row['T'] == "INDIA VIX":
                    if row['C'] > 0: bg = "bear-card"
                    elif row['C'] < 0: bg = "bull-card"
                    else: bg = "neut-card"
                else:
                    if row['C'] > 0: bg = "bull-card"
                    elif row['C'] < 0: bg = "bear-card"
                    else: bg = "neut-card"
                    
                badge = "IDX"
                sign = "+" if row['C'] > 0 else ""
                tv_sym = TV_INDICES_URL.get(row['Fetch_T'], "")
                tv_link = f"https://in.tradingview.com/chart/?symbol={tv_sym}"
                
                html_idx += f'<a href="{tv_link}" target="_blank" class="stock-card {bg}"><div class="t-score">{badge}</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{sign}{row["C"]:.2f}%</div></a>'
            html_idx += '</div>'
            st.markdown(html_idx, unsafe_allow_html=True)
            
            st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        # 2. RENDER STOCKS
        html_stk = '<div class="heatmap-grid">'
        for _, row in df_stocks_display.iterrows():
            if row['C'] > 0: bg = "bull-card"
            elif row['C'] < 0: bg = "bear-card"
            else: bg = "neut-card"
            
            badge = f"⭐{int(row['S'])}"
            sign = "+" if row['C'] > 0 else ""
            tv_link = f"https://in.tradingview.com/chart/?symbol=NSE:{row['T']}"
            
            html_stk += f'<a href="{tv_link}" target="_blank" class="stock-card {bg}"><div class="t-score">{badge}</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{sign}{row["C"]:.2f}%</div></a>'
        html_stk += '</div>'
        st.markdown(html_stk, unsafe_allow_html=True)
        
    else:
        # === MINI CHARTS ===
        st.markdown("<br>", unsafe_allow_html=True)
        
        # 1. RENDER INDICES CHARTS FIRST
        st.markdown("<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#e6edf3;'>📈 Market Indices</div>", unsafe_allow_html=True)
        if not df_indices.empty:
            idx_list = [row for _, row in df_indices.iterrows()]
            for i in range(0, len(idx_list), 3):
                cols = st.columns(3)
                for j in range(3):
                    if i + j < len(idx_list):
                        with cols[j]:
                            row_data = idx_list[i + j]
                            render_chart(row_data, processed_charts.get(row_data['Fetch_T'], pd.DataFrame()))
                            
        st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        # 2. RENDER STOCKS CHARTS
        st.markdown(f"<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#e6edf3;'>{watchlist_mode}</div>", unsafe_allow_html=True)
        if not df_stocks_display.empty:
            stk_list = [row for _, row in df_stocks_display.iterrows()]
            for i in range(0, len(stk_list), 3):
                cols = st.columns(3)
                for j in range(3):
                    if i + j < len(stk_list):
                        with cols[j]:
                            row_data = stk_list[i + j]
                            render_chart(row_data, processed_charts.get(row_data['Fetch_T'], pd.DataFrame()))

else:
    st.info("Loading Market Data...")
