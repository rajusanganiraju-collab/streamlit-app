import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Market Heatmap", page_icon="📊", layout="wide")

# --- 2. AUTO RUN (1 MINUTE) ---
st_autorefresh(interval=60000, key="datarefresh")

# --- 3. CSS FOR HEATMAP BOXES & MINI CHARTS (DARK THEME) ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {display: none !important;}
    
    /* Dark Theme Background */
    .stApp { background-color: #0d1117; color: #ffffff; }
    .block-container { padding-top: 1rem !important; padding-bottom: 0rem !important; margin-top: -10px; }
    
    /* Responsive Grid for Heatmap */
    .heatmap-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
        gap: 10px;
        padding: 10px 0;
    }
    
    /* Box Styling */
    .stock-card {
        border-radius: 6px;
        padding: 12px 5px;
        text-align: center;
        text-decoration: none !important;
        color: white !important;
        display: flex;
        flex-direction: column;
        justify-content: center;
        height: 105px;
        position: relative;
        transition: transform 0.2s;
    }
    .stock-card:hover { transform: scale(1.03); z-index: 10; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }
    
    /* Colors for Profit and Loss */
    .bull-card { background-color: #1a4d2e !important; border: 1px solid #2ea043; } 
    .bear-card { background-color: #7a1b1b !important; border: 1px solid #da3633; } 
    .neut-card { background-color: #21262d !important; border: 1px solid #30363d; }
    
    /* Fonts inside the box */
    .t-name { font-size: 14px; font-weight: 800; color: #e6edf3; margin-bottom: 4px; }
    .t-price { font-size: 18px; font-weight: 900; margin-bottom: 2px; }
    .t-pct { font-size: 13px; font-weight: bold; }
    
    /* Score Badge */
    .t-score { 
        position: absolute; top: 4px; left: 4px; 
        font-size: 11px; background: rgba(0,0,0,0.6); 
        padding: 2px 5px; border-radius: 4px; color: #ffd700; font-weight: bold;
    }
    
    /* Mobile specific adjustments */
    @media screen and (max-width: 600px) {
        .heatmap-grid { grid-template-columns: repeat(3, 1fr); gap: 6px; }
        .stock-card { height: 95px; }
        .t-name { font-size: 12px; }
        .t-price { font-size: 15px; }
        .t-pct { font-size: 11px; }
    }
    </style>
""", unsafe_allow_html=True)

# --- 4. SCORE LOGIC & DATA FETCH ---
def get_minutes_passed():
    now = datetime.now()
    if now.weekday() >= 5 or now.time() > dt_time(15, 30): return 375
    open_time = now.replace(hour=9, minute=15, second=0)
    diff = (now - open_time).total_seconds() / 60
    return min(375, max(1, int(diff)))

@st.cache_data(ttl=60)
def fetch_and_score_data():
    # 🔥 FULL NIFTY 50 STOCKS LIST 🔥
    nifty50_tickers = [
        "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO", "BAJFINANCE", 
        "BAJAJFINSV", "BEL", "BHARTIARTL", "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB", "DRREDDY", 
        "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDUNILVR", 
        "ICICIBANK", "INDIGO", "INFY", "ITC", "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI", "NESTLEIND", 
        "NTPC", "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM", 
        "TATAMOTORS", "TATASTEEL", "TCS", "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO"
    ]
    tkrs = [f"{t}.NS" for t in nifty50_tickers]
    data = yf.download(tkrs, period="2d", interval="1m", progress=False, group_by='ticker', threads=False)
    
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
            
            # --- SCORE LOGIC ---
            score = 0
            if abs(day_chg) >= 2.0: score += 3 
            if abs(open_p - low) <= (ltp * 0.003) or abs(open_p - high) <= (ltp * 0.003): score += 3 
            if vol_x > 1.2: score += 4 
            
            results.append({
                "T": symbol.replace(".NS", ""), 
                "P": ltp, 
                "C": net_chg, 
                "S": score
            })
        except: continue
        
    return pd.DataFrame(results)

# --- 5. TOP NAVIGATION BAR ---
st.markdown("<div style='background-color:#161b22; padding:10px; border-radius:8px; margin-bottom:10px; border: 1px solid #30363d;'>", unsafe_allow_html=True)
c1, c2 = st.columns([0.6, 0.4])

with c1:
    # Dropdown 
    watchlist_mode = st.selectbox("Watchlist", ["Nifty 50 Heatmap", "High Score Stocks 🔥"], label_visibility="collapsed")
with c2:
    view_mode = st.radio("Display", ["Heat Map", "Chart 📈"], horizontal=True, label_visibility="collapsed")
st.markdown("</div>", unsafe_allow_html=True)

# --- 6. RENDER THE CONTENT ---
df = fetch_and_score_data()

if not df.empty:
    # 🎯 APPLY DROPDOWN LOGIC 🎯
    if watchlist_mode == "High Score Stocks 🔥":
        # స్కోర్ 3 లేదా అంతకంటే ఎక్కువ ఉన్నవి మాత్రమే చూపిస్తుంది (స్కోర్ వైజ్ సార్టింగ్)
        df_display = df[df['S'] >= 3].sort_values(by=["S", "C"], ascending=[False, False])
    else:
        # Nifty 50 లో అన్ని స్టాక్స్ పర్సంటేజ్ (% Change) ప్రకారం సార్టింగ్ (గ్రీన్ అంతా ఒకేచోట వస్తుంది)
        df_display = df.sort_values(by="C", ascending=False)

    if view_mode == "Heat Map":
        # === HEAT MAP VIEW ===
        html = '<div class="heatmap-grid">'
        for _, row in df_display.iterrows():
            bg = "bull-card" if row['C'] > 0 else ("bear-card" if row['C'] < 0 else "neut-card")
            sign = "+" if row['C'] > 0 else ""
            
            html += f'<a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank" class="stock-card {bg}"><div class="t-score">⭐ {row["S"]}</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.1f}</div><div class="t-pct">{sign}{row["C"]:.2f}%</div></a>'
            
        html += '</div>'
        st.markdown(html, unsafe_allow_html=True)
        
    else:
        # === MINI CHARTS VIEW (FIXED TRADINGVIEW ERROR) ===
        st.markdown("<br>", unsafe_allow_html=True)
        cols = st.columns(3) 
        
        # We limit to top 30 charts to prevent browser from hanging
        for idx, row in df_display.head(30).iterrows():
            col = cols[idx % 3]
            with col:
                color = "#2ea043" if row['C'] > 0 else "#da3633"
                st.markdown(f"<div style='text-align:center; font-weight:bold; font-size:15px; margin-bottom:4px;'>{row['T']} <span style='color:{color}'>({row['C']:.2f}%)</span> - Score: {row['S']}</div>", unsafe_allow_html=True)
                
                # 🔥 OFFICIAL TRADINGVIEW WIDGET (Solves the Apple Chart / Error Issue) 🔥
                chart_code = f"""
                <div class="tradingview-widget-container" style="border:1px solid #30363d; border-radius:6px; overflow:hidden; background:#000;">
                  <div id="tv_{row['T']}" style="height:200px;"></div>
                  <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
                  <script type="text/javascript">
                  new TradingView.widget({{
                    "autosize": true,
                    "symbol": "NSE:{row['T']}",
                    "interval": "5",
                    "timezone": "Asia/Kolkata",
                    "theme": "dark",
                    "style": "3",
                    "locale": "in",
                    "enable_publishing": false,
                    "hide_top_toolbar": true,
                    "hide_legend": true,
                    "save_image": false,
                    "container_id": "tv_{row['T']}"
                  }});
                  </script>
                </div>
                <br>
                """
                st.components.v1.html(chart_code, height=220)
else:
    st.info("Loading Market Data...")
