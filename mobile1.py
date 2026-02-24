import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Terminal", page_icon="🎯", layout="wide")
st_autorefresh(interval=60000, key="datarefresh")

# CSS 
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {display: none !important;}
    .stApp { background-color: #ffffff; color: #000000; }
    html, body, [class*="css"] { font-family: 'Arial', sans-serif; font-weight: 600; color: #000000 !important; }
    .block-container { padding: 0.5rem 0.1rem -10px !important; }
    th { background-color: #ffffff !important; color: #000000 !important; font-size: 12px !important; border-bottom: 2px solid #222 !important; text-align: center !important; }
    td { font-size: 12px !important; color: #000000 !important; border-bottom: 1px solid #ccc !important; text-align: center !important; font-weight: 700 !important; }
    .table-head { padding: 6px 10px; font-weight: 900; font-size: 14px; border-radius: 4px; text-align: left; }
    .head-bull { background: #d4edda; color: #155724; }
    .head-bear { background: #f8d7da; color: #721c24; }
    div[data-testid="stDataFrame"] { margin-bottom: -15px !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. DATA ---
def format_ticker(t):
    t = t.upper().strip()
    return f"{t}.NS" if not t.startswith("^") and not t.endswith(".NS") else t

BROADER_MARKET = ["HAL", "BEL", "RVNL", "IRFC", "DIXON", "POLYCAB", "LT", "BAJFINANCE", "ZOMATO", "TRENT", "ADANIENT", "RELIANCE"]
BROADER_MARKET = [format_ticker(s) for s in BROADER_MARKET]

@st.cache_data(ttl=60)
def get_data():
    all_tickers = BROADER_MARKET # ఇతర టిక్కర్లు కూడా ఇక్కడ యాడ్ చేయొచ్చు
    try:
        data = yf.download(all_tickers, period="2d", interval="5m", progress=False, group_by='ticker', threads=False)
        return data
    except: return None

def analyze(symbol, full_data):
    try:
        df = full_data[symbol].copy().dropna()
        if len(df) < 10: return None
        
        # EMA & VWAP
        df['EMA10'] = df['Close'].ewm(span=10, adjust=False).mean()
        df['TP'] = (df['High'] + df['Low'] + df['Close']) / 3
        df['CVP'] = (df['TP'] * df['Volume']).cumsum()
        df['CV'] = df['Volume'].cumsum()
        df['VWAP'] = df['CVP'] / df['CV']

        today_df = df[df.index.date == df.index.date[-1]].copy()
        ltp = today_df['Close'].iloc[-1]; op = today_df['Open'].iloc[0]; vwap = today_df['VWAP'].iloc[-1]
        day_chg = ((ltp - op) / op) * 100
        
        is_bull = ltp > vwap # ప్రస్తుతం ప్రైస్ ఎటు ఉందో అది ట్రెండ్

        # ⚡ THE ACCUMULATOR LOGIC (మీరు అడిగిన గ్యాప్-ఒమిట్ లాజిక్)
        # స్టాక్ ప్రస్తుతం ఉన్న ట్రెండ్ సైడ్ లో, ఎన్ని క్యాండిల్స్ ఆ రూల్ ని పాస్ అయ్యాయో మొత్తం లెక్కిస్తుంది.
        if is_bull:
            # బుల్లిష్ క్యాండిల్స్: Close > VWAP మరియు Close > 10 EMA
            today_df['Valid'] = (today_df['Close'] > today_df['VWAP']) & (today_df['Close'] > today_df['EMA10'])
        else:
            # బేరిష్ క్యాండిల్స్: Close < VWAP మరియు Close < 10 EMA
            today_df['Valid'] = (today_df['Close'] < today_df['VWAP']) & (today_df['Close'] < today_df['EMA10'])

        total_valid_candles = int(today_df['Valid'].sum())
        
        if total_valid_candles < 3: return None

        time_str = f"{(total_valid_candles*5)//60}h {(total_valid_candles*5)%60}m" if (total_valid_candles*5)>=60 else f"{total_valid_candles*5}m"
        
        return {
            "STOCK": f"https://in.tradingview.com/chart/?symbol=NSE:{symbol.replace('.NS','')}",
            "LTP": f"{ltp:.2f}", "D%": f"{day_chg:.2f}",
            "STAT": f"{'🚀' if is_bull else '🩸'} ({time_str})",
            "CANDLES": total_valid_candles
        }
    except: return None

# --- 3. EXECUTION ---
data = get_data()
if data is not None:
    results = []
    for s in BROADER_MARKET:
        res = analyze(s, data)
        if res: results.append(res)
    
    if results:
        df_final = pd.DataFrame(results).sort_values("CANDLES", ascending=False)
        st.markdown("<div class='table-head head-bear'>🎯 PURE QUALITY TRACKER (CANDLE COUNT)</div>", unsafe_allow_html=True)
        st.dataframe(df_final, column_config={
            "STOCK": st.column_config.LinkColumn("STOCK", display_text=r"NSE:(.*)"),
            "CANDLES": st.column_config.NumberColumn("CANDLES", width="small")
        }, use_container_width=True, hide_index=True)
