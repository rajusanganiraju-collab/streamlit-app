import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Market Heatmap", page_icon="📈", layout="wide")

# --- 2. AUTO RUN (1 MINUTE) ---
st_autorefresh(interval=60000, key="datarefresh")

# --- 3. CSS FOR WATCHLIST BOXES & MINI CHARTS ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {display: none !important;}
    .stApp { background-color: #0d1117; color: #ffffff; }
    
    /* Heatmap Grid Layout */
    .heatmap-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
        gap: 8px;
        padding: 10px 0;
    }
    
    /* Box Styling - Matching your screenshot */
    .stock-card {
        border-radius: 4px;
        padding: 10px 5px;
        text-align: center;
        text-decoration: none !important;
        color: white !important;
        display: flex;
        flex-direction: column;
        justify-content: center;
        height: 100px;
        border: 1px solid #30363d;
        position: relative;
    }
    
    .bull-card { background-color: #1a4d2e !important; } 
    .bear-card { background-color: #7a1b1b !important; } 
    
    .ticker-name { font-size: 13px; font-weight: 800; color: #e6edf3; margin-bottom: 2px; }
    .ticker-price { font-size: 17px; font-weight: 900; margin-bottom: 2px; }
    .ticker-pct { font-size: 12px; font-weight: bold; }
    .score-badge { 
        position: absolute; top: 2px; right: 4px; 
        font-size: 9px; background: rgba(0,0,0,0.5); 
        padding: 1px 4px; border-radius: 3px; 
    }

    @media screen and (max-width: 600px) {
        .heatmap-grid { grid-template-columns: repeat(3, 1fr); gap: 5px; }
    }
    </style>
""", unsafe_allow_html=True)

# --- 4. SCORE LOGIC & DATA FETCH ---
@st.cache_data(ttl=60)
def get_live_scores():
    tickers = ["HDFCBANK", "ICICIBANK", "SBIN", "RELIANCE", "TCS", "INFY", "ZOMATO", "TATASTEEL", "HAL", "RVNL", "IRFC", "ADANIENT", "DIXON", "TRENT", "BEL", "NMDC", "ITC", "MARUTI"]
    data = yf.download([f"{t}.NS" for t in tickers], period="2d", interval="1m", progress=False, group_by='ticker')
    
    results = []
    now = datetime.now()
    minutes_passed = min(375, max(1, (now - now.replace(hour=9, minute=15, second=0)).total_seconds() / 60))

    for symbol in data.columns.levels[0]:
        try:
            df = data[symbol].dropna()
            if len(df) < 2: continue
            
            ltp, open_p, prev_c = float(df['Close'].iloc[-1]), float(df['Open'].iloc[-1]), float(df['Close'].iloc[-2])
            net_chg = ((ltp - prev_c) / prev_c) * 100
            
            # --- YOUR ORIGINAL SCORE LOGIC ---
            score = 0
            if abs(((ltp - open_p) / open_p) * 100) >= 2.0: score += 3 # Big Move
            if abs(open_p - float(df['Low'].iloc[-1])) <= (ltp * 0.003): score += 3 # O=L
            vol_x = float(df['Volume'].iloc[-1]) / ((df['Volume'].iloc[:-1].mean()/375) * minutes_passed)
            if vol_x > 1.2: score += 4
            
            results.append({"T": symbol.replace(".NS", ""), "P": ltp, "C": net_chg, "S": score})
        except: continue
    return pd.DataFrame(results).sort_values("S", ascending=False)

# --- 5. TOP BAR NAVIGATION ---
c1, c2 = st.columns([0.6, 0.4])
with c1:
    st.selectbox("Watchlist", ["High Score Stocks 🔥", "Nifty 50"], label_visibility="collapsed")
with c2:
    view_mode = st.radio("Display", ["Heat Map", "Chart 📈"], horizontal=True, label_visibility="collapsed")

# --- 6. RENDER CONTENT ---
df = get_live_scores()

if view_mode == "Heat Map":
    html_grid = '<div class="heatmap-grid">'
    for _, row in df.iterrows():
        bg = "bull-card" if row['C'] >= 0 else "bear-card"
        html_grid += f"""
        <a href="https://in.tradingview.com/chart/?symbol=NSE:{row['T']}" target="_blank" class="stock-card {bg}">
            <div class="score-badge">S:{row['S']}</div>
            <div class="ticker-name">{row['T']}</div>
            <div class="ticker-price">{row['P']:.1f}</div>
            <div class="ticker-pct">{'▲' if row['C']>=0 else '▼'} {abs(row['C']):.2f}%</div>
        </a>
        """
    html_grid += '</div>'
    st.markdown(html_grid, unsafe_allow_html=True)
else:
    # --- CHART MODE: ONE BELOW ANOTHER WITH SCORE ---
    for _, row in df.iterrows():
        ticker = row['T']
        st.markdown(f"**{ticker}** | Score: {row['S']} | {row['C']:.2f}%")
        chart_html = f"""
        <div style="border:1px solid #333; border-radius:4px; overflow:hidden; background:#000;">
            <iframe src="https://s.tradingview.com/widgetembed/?symbol=NSE:{ticker}&interval=5&theme=dark&style=3" 
            width="100%" height="250" frameborder="0" scrolling="no"></iframe>
        </div>
        """
        st.components.v1.html(chart_html, height=260)
