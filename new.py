import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Market Heatmap", page_icon="📊", layout="wide")

# --- 2. AUTO RUN (1 MINUTE) ---
st_autorefresh(interval=60000, key="datarefresh")

# --- 3. CSS FOR EXACT 10-COLUMN HEATMAP ---
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
    
    /* Fonts inside the box */
    .t-name { font-size: 13px; font-weight: 800; margin-bottom: 2px; }
    .t-price { font-size: 17px; font-weight: 900; margin-bottom: 2px; }
    .t-pct { font-size: 12px; font-weight: bold; }
    
    /* Score Badge */
    .t-score { 
        position: absolute; top: 3px; left: 3px; 
        font-size: 10px; background: rgba(0,0,0,0.4); 
        padding: 1px 4px; border-radius: 3px; color: #ffd700; 
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
    </style>
""", unsafe_allow_html=True)

# --- 4. STOCK LISTS FROM YOUR MOBILE1.PY ---
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
    "HAL", "BEL", "BDL", "MAZDOCK", "COCHINSHIP", "GRSE", "RVNL", "IRFC", "IRCON", "TITAGARH", "RAILTEL", "RITES",
    "ADANIPOWER", "ADANIGREEN", "NHPC", "SJVN", "BHEL", "CGPOWER", "SUZLON", "PFC", "RECLTD", "IREDA", "IOB", "UCOBANK", "MAHABANK", "CANBK",
    "BAJFINANCE", "CHOLAFIN", "JIOFIN", "MUTHOOTFIN", "MANAPPURAM", "SHRIRAMFIN", "M&MFIN", "DIXON", "POLYCAB", "KAYNES", "HAVELLS", "KEI", "RRKABEL",
    "SRF", "TATACHEM", "DEEPAKNTR", "AARTIIND", "PIIND", "FACT", "UPL", "ULTRACEMCO", "AMBUJACEM", "SHREECEM", "DALBHARAT", "L&T", "CUMMINSIND", "ABB", "SIEMENS",
    "BHARTIARTL", "IDEA", "INDIGO", "ZOMATO", "TRENT", "DMART", "PAYTM", "ZENTEC", "ADANIENT", "ADANIPORTS", "ATGL", "AWL",
    "BOSCHLTD", "MRF", "MOTHERSON", "SONACOMS", "EXIDEIND", "AMARAJABAT"
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
    
    # 🌟 NEW LOGIC: Is_Green column added to group Greens first and Reds next
    df['Is_Green'] = df['C'] >= 0
    
    if watchlist_mode == "Nifty 50 Heatmap":
        # Nifty 50 strictly by Percentage (High Green to Low Red)
        df_display = df[df['T'].isin(NIFTY_50)].sort_values(by="C", ascending=False)
        st.markdown("### Nifty 50 Stocks")
    else:
        # 🌟 HIGH SCORE LOGIC: Sort by Score -> Then Is_Green -> Then Percentage
        # This guarantees: Score 10 Greens -> Score 10 Reds -> Score 9 Greens -> Score 9 Reds...
        df_display = df[df['S'] >= 4].sort_values(by=["S", "Is_Green", "C"], ascending=[False, False, False])
        st.markdown("### 🔥 High Score Stocks (Across All Sectors)")

    if view_mode == "Heat Map":
        # === HEAT MAP GRID ===
        html = '<div class="heatmap-grid">'
        for _, row in df_display.iterrows():
            bg = "bull-card" if row['C'] >= 0 else "bear-card"
            sign = "+" if row['C'] >= 0 else ""
            
            html += f'<a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank" class="stock-card {bg}"><div class="t-score">⭐{row["S"]}</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{sign}{row["C"]:.2f}%</div></a>'
            
        html += '</div>'
        st.markdown(html, unsafe_allow_html=True)
        
    else:
        # === MINI CHARTS (Fixed TradingView Apple Error by using safe widget) ===
        st.markdown("<br>", unsafe_allow_html=True)
        cols = st.columns(3) 
        
        # Limit to top 30 charts to prevent lag
        for idx, row in df_display.head(30).iterrows():
            col = cols[idx % 3]
            with col:
                color = "#2ea043" if row['C'] >= 0 else "#da3633"
                st.markdown(f"<div style='text-align:center; font-weight:bold; font-size:15px; margin-bottom:4px;'>{row['T']} <span style='color:{color}'>({row['C']:.2f}%)</span></div>", unsafe_allow_html=True)
                
                # Using 'Symbol Overview' Widget and 'BSE:' which avoids NSE embedding restrictions
                chart_code = f"""
                <div class="tradingview-widget-container" style="border:1px solid #30363d; border-radius:6px; overflow:hidden; background:#000;">
                  <div class="tradingview-widget-container__widget"></div>
                  <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-symbol-overview.js" async>
                  {{
                    "symbols": [
                      [
                        "BSE:{row['T']}|1D"
                      ]
                    ],
                    "chartOnly": true,
                    "width": "100%",
                    "height": "200",
                    "locale": "in",
                    "colorTheme": "dark",
                    "autosize": false,
                    "showVolume": false,
                    "showMA": false,
                    "hideDateRanges": false,
                    "hideMarketStatus": true,
                    "hideSymbolLogo": true,
                    "scalePosition": "right",
                    "scaleMode": "Normal",
                    "fontFamily": "-apple-system, BlinkMacSystemFont, Trebuchet MS, Roboto, Ubuntu, sans-serif",
                    "fontSize": "10",
                    "noTimeScale": false,
                    "valuesTracking": "1",
                    "changeMode": "price-and-percent",
                    "chartType": "area",
                    "lineWidth": 2,
                    "lineType": 0,
                    "dateRanges": [
                      "1d|1",
                      "1w|15",
                      "1m|30",
                      "3m|60",
                      "12m|1D",
                      "60m|1W",
                      "all|1M"
                    ]
                  }}
                  </script>
                </div>
                <br>
                """
                st.components.v1.html(chart_code, height=220)
else:
    st.info("Loading Market Data...")
