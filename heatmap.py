import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Market HeatMap", page_icon="📊", layout="wide")

# --- 2. AUTO RUN (1 MINUTE) ---
st_autorefresh(interval=60000, key="datarefresh")

# --- 3. CSS FOR HEATMAP BOXES & RESPONSIVE GRID ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {display: none !important;}
    .stApp { background-color: #000000; color: #ffffff; }
    
    /* HeatMap Grid Layout */
    .heatmap-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
        gap: 8px;
        padding: 10px 0;
    }
    
    /* Stock Card Styling */
    .stock-card {
        background-color: #1a1a1a;
        border-radius: 4px;
        padding: 8px;
        text-align: center;
        border: 1px solid #333;
        transition: transform 0.2s;
        text-decoration: none !important;
        color: white !important;
        display: flex;
        flex-direction: column;
        justify-content: center;
        height: 85px; /* Match the screenshot size approx */
    }
    .stock-card:hover { transform: scale(1.05); background-color: #262626; }
    
    .card-name { font-size: 13px; font-weight: 800; color: #ccc; text-transform: uppercase; }
    .card-price { font-size: 17px; font-weight: 900; margin: 2px 0; }
    .card-pct { font-size: 12px; font-weight: bold; }
    
    /* Color coding */
    .bull-bg { background-color: #1b4332 !important; border-color: #2d6a4f !important; }
    .bear-bg { background-color: #4b1a1a !important; border-color: #7f1d1d !important; }
    
    /* Top Bar Styling */
    .top-bar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background-color: #121212;
        padding: 10px;
        border-bottom: 1px solid #333;
        margin-bottom: 10px;
    }
    
    @media screen and (max-width: 600px) {
        .heatmap-grid { grid-template-columns: repeat(3, 1fr); gap: 5px; }
        .card-price { font-size: 14px; }
        .card-name { font-size: 10px; }
    }
    </style>
""", unsafe_allow_html=True)

# --- 4. LOGIC FUNCTIONS ---
def format_ticker(t):
    t = t.upper().strip()
    return f"{t}.NS" if not t.startswith("^") and not t.endswith(".NS") else t

BROADER_MARKET = [
    "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "TCS", "INFY", "HCLTECH", "RELIANCE", "ITC",
    "SUNPHARMA", "MARUTI", "TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "ZOMATO", "HAL", "RVNL", "IRFC",
    "ADANIENT", "ADANIPOWER", "DIXON", "POLYCAB", "KAYNES", "TRENT", "IDEA", "BHARTIARTL", "NMDC", "BEL"
]

def analyze_stocks(data_full):
    results = []
    minutes = min(375, max(1, (datetime.now() - datetime.now().replace(hour=9, minute=15, second=0)).total_seconds() / 60))
    
    for symbol in data_full.columns.levels[0]:
        try:
            df = data_full[symbol].dropna()
            if len(df) < 2: continue
            ltp, open_p, prev_c = float(df['Close'].iloc[-1]), float(df['Open'].iloc[-1]), float(df['Close'].iloc[-2])
            day_chg = ((ltp - open_p) / open_p) * 100
            net_chg = ((ltp - prev_c) / prev_c) * 100
            
            # Simple Scoring Logic from mobile1.py
            score = 0
            if day_chg >= 2.0 or day_chg <= -2.0: score += 3
            if abs(open_p - float(df['Low'].iloc[-1])) <= (ltp * 0.003): score += 3
            if (float(df['Volume'].iloc[-1]) / ((df['Volume'].iloc[:-1].mean()/375) * minutes)) > 1.0: score += 3
            
            results.append({
                "TICKER": symbol.replace(".NS", ""),
                "PRICE": ltp,
                "CHG": net_chg,
                "SCORE": score,
                "URL": f"https://in.tradingview.com/chart/?symbol=NSE:{symbol.replace('.NS', '')}"
            })
        except: continue
    return pd.DataFrame(results)

# --- 5. TOP NAVIGATION ---
col_l, col_r = st.columns([0.6, 0.4])

with col_l:
    filter_type = st.selectbox("Watchlist", ["Top Scores 🔥", "Nifty 50 Heatmap", "Bullish Stocks", "Bearish Stocks"], label_visibility="collapsed")

with col_r:
    view_type = st.radio("View", ["Cards", "Charts 📈"], horizontal=True, label_visibility="collapsed")

# --- 6. DATA FETCHING ---
with st.spinner("Loading Heatmap..."):
    tickers = [format_ticker(t) for t in BROADER_MARKET]
    data = yf.download(tickers, period="2d", progress=False, group_by='ticker', threads=False)
    df_results = analyze_stocks(data)

# --- 7. RENDER HEATMAP ---
if not df_results.empty:
    # Filter Logic
    if "Bullish" in filter_type:
        df_display = df_results[df_results['CHG'] > 0].sort_values("CHG", ascending=False)
    elif "Bearish" in filter_type:
        df_display = df_results[df_results['CHG'] < 0].sort_values("CHG", ascending=True)
    else:
        df_display = df_results.sort_values("SCORE", ascending=False)

    # HTML Grid Header
    html_grid = '<div class="heatmap-grid">'

    for _, row in df_display.iterrows():
        bg_class = "bull-bg" if row['CHG'] >= 0 else "bear-bg"
        
        if view_type == "Cards":
            # Normal Card View
            html_grid += f"""
            <a href="{row['URL']}" target="_blank" class="stock-card {bg_class}">
                <div class="card-name">{row['TICKER']}</div>
                <div class="card-price">{row['PRICE']:.1f}</div>
                <div class="card-pct">{'▲' if row['CHG']>=0 else '▼'} {abs(row['CHG']):.2f}%</div>
            </a>
            """
        else:
            # Chart View (Embedded Mini Charts)
            chart_html = f"""
            <div style="height: 100px; border-radius: 4px; overflow: hidden; border: 1px solid #444;">
                <iframe src="https://s.tradingview.com/widgetembed/?frameElementId=tradingview_762ae&symbol=NSE:{row['TICKER']}&interval=D&hidesidetoolbar=1&symboledit=0&saveimage=1&toolbarbg=f1f3f6&studies=[]&theme=dark&style=3&timezone=Etc%2FUTC&studies_overrides={{}}&overrides={{}}&enabled_features=[]&disabled_features=[]&locale=in" 
                width="100%" height="100%" frameborder="0" allowtransparency="true" scrolling="no" style="pointer-events: none;"></iframe>
            </div>
            """
            st.write(f"**{row['TICKER']} ({row['CHG']:.1f}%)**")
            st.components.v1.html(chart_html, height=100)

    if view_type == "Cards":
        html_grid += '</div>'
        st.markdown(html_grid, unsafe_allow_html=True)
else:
    st.error("No Data Found.")
