import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Market Terminal", page_icon="📈", layout="wide")

# --- 2. AUTO RUN (1 MINUTE) ---
st_autorefresh(interval=60000, key="datarefresh")

# --- 3. CSS FOR WATCHLIST BOXES & CHART DISPLAY ---
# ఇక్కడ మీ పాత టేబుల్ సెట్టింగ్స్ అన్నీ తీసేసి కొత్త హీట్ మ్యాప్ డిజైన్ పెట్టాను
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {display: none !important;}
    .stApp { background-color: #0d1117; color: #ffffff; }
    
    /* Heatmap Grid Layout */
    .heatmap-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(115px, 1fr));
        gap: 8px;
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
        height: 100px;
        border: 1px solid #30363d;
    }
    
    .bull-card { background-color: #1a4d2e !important; } /* Green */
    .bear-card { background-color: #7a1b1b !important; } /* Red */
    
    .ticker-name { font-size: 14px; font-weight: 800; color: #e6edf3; margin-bottom: 5px; }
    .ticker-price { font-size: 18px; font-weight: 900; margin-bottom: 2px; }
    .ticker-pct { font-size: 12px; font-weight: bold; }
    
    @media screen and (max-width: 600px) {
        .heatmap-grid { grid-template-columns: repeat(3, 1fr); gap: 5px; }
    }
    </style>
""", unsafe_allow_html=True)

# --- 4. FETCH DATA & APPLY YOUR SCORE LOGIC ---
@st.cache_data(ttl=60)
def get_data_with_score():
    # మీరు తరచుగా చూసే స్టాక్స్
    tickers = ["HDFCBANK", "ICICIBANK", "SBIN", "RELIANCE", "TCS", "INFY", "ZOMATO", "TATASTEEL", "HAL", "RVNL", "IRFC", "ADANIENT", "DIXON", "TRENT", "BEL", "NMDC", "ITC", "MARUTI"]
    tickers = [f"{t}.NS" for t in tickers]
    data = yf.download(tickers, period="2d", interval="1m", progress=False, group_by='ticker', threads=False)
    
    results = []
    now = datetime.now()
    m_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    minutes_passed = min(375, max(1, int((now - m_open).total_seconds() / 60)))

    for symbol in data.columns.levels[0]:
        try:
            df = data[symbol].dropna()
            if len(df) < 2: continue
            
            ltp, open_p, prev_c = float(df['Close'].iloc[-1]), float(df['Open'].iloc[-1]), float(df['Close'].iloc[-2])
            net_chg = ((ltp - prev_c) / prev_c) * 100
            
            # --- మీ పాత SCORE logic ---
            score = 0
            if abs(((ltp - open_p) / open_p) * 100) >= 2.0: score += 3
            if abs(open_p - float(df['Low'].iloc[-1])) <= (ltp * 0.003): score += 3 # O=L
            vol_x = float(df['Volume'].iloc[-1]) / ((df['Volume'].iloc[:-1].mean()/375) * minutes_passed)
            if vol_x > 1.2: score += 4
            
            results.append({"T": symbol.replace(".NS", ""), "P": ltp, "C": net_chg, "S": score})
        except: continue
    return pd.DataFrame(results).sort_values("S", ascending=False)

# --- 5. TOP NAVIGATION BAR (As per your screenshot) ---
col_nav_1, col_nav_2 = st.columns([0.6, 0.4])

with col_nav_1:
    watchlist_name = st.selectbox("Indices", ["Top Score Stocks 🔥", "Nifty 50", "Bank Nifty"], label_visibility="collapsed")

with col_nav_2:
    # ఇక్కడ మీరు అడిగిన Chart Option యాడ్ చేశాను
    view_option = st.radio("Display", ["Heat Map", "Chart 📈"], horizontal=True, label_visibility="collapsed")

# --- 6. RENDER THE BOXES OR CHARTS ---
df_market = get_data_with_score()

if not df_market.empty:
    if view_option == "Heat Map":
        # బాక్సుల రూపంలో చూపిస్తుంది
        html_out = '<div class="heatmap-grid">'
        for _, row in df_market.iterrows():
            bg = "bull-card" if row['C'] >= 0 else "bear-card"
            html_out += f"""
            <a href="https://in.tradingview.com/chart/?symbol=NSE:{row['T']}" target="_blank" class="stock-card {bg}">
                <div class="ticker-name">{row['T']}</div>
                <div class="ticker-price">{row['P']:.1f}</div>
                <div class="ticker-pct">{'▲' if row['C']>=0 else '▼'} {abs(row['C']):.2f}%</div>
            </a>
            """
        html_out += '</div>'
        st.markdown(html_out, unsafe_allow_html=True)
    
    else:
        # Chart option సెలెక్ట్ చేస్తే వచ్చే వ్యూ
        st.write("### Today's Charts (Score Based)")
        for _, row in df_market.iterrows():
            ticker = row['T']
            # బాక్సు సైజులోనే చార్ట్ అలైన్మెంట్
            chart_code = f"""
            <div style="border:1px solid #333; border-radius:8px; margin-bottom:15px; background:#000; padding:10px;">
                <div style="display:flex; justify-content:space-between; font-weight:bold; font-size:16px;">
                    <span>{ticker}</span> <span style="color:{'#22c55e' if row['C']>=0 else '#ef4444'}">{row['C']:.2f}%</span>
                </div>
                <iframe src="https://s.tradingview.com/widgetembed/?symbol=NSE:{ticker}&interval=5&theme=dark&style=3" 
                width="100%" height="250" frameborder="0" scrolling="no"></iframe>
            </div>
            """
            st.components.v1.html(chart_code, height=300)
else:
    st.warning("Loading Market Data...")
