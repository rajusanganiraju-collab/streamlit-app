import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Terminal", page_icon="📈", layout="wide")
st_autorefresh(interval=60000, key="datarefresh")

# CSS - Unified Layout Settings
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {display: none !important;}
    .stApp { background-color: #ffffff; color: #000000; }
    html, body, [class*="css"] { font-family: 'Arial', sans-serif; font-weight: 600; color: #000000 !important; }
    .block-container { padding: 0.5rem 0.5rem 0rem !important; margin-top: -10px; }
    th { background-color: #ffffff !important; color: #000000 !important; font-size: 14px !important; text-align: center !important; border-bottom: 2px solid #222 !important; border-top: 2px solid #222 !important; padding: 6px !important; }
    td { font-size: 14px !important; color: #000000 !important; border-bottom: 1px solid #ccc !important; text-align: center !important; font-weight: 700 !important; }
    .table-head { padding: 6px 10px; font-weight: 900; font-size: 15px; text-transform: uppercase; margin-top: 8px; margin-bottom: 2px; border-radius: 4px; text-align: left; }
    .head-bull { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
    .head-bear { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
    .head-neut { background: #e2e3e5; color: #383d41; border: 1px solid #d6d8db; }
    .head-sniper { background: #fff3cd; color: #856404; border: 1px solid #ffeeba; }
    div[data-testid="stDataFrame"] { margin-bottom: -15px !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. DATA CONFIGURATION ---
def format_ticker(t):
    t = t.upper().strip()
    return f"{t}.NS" if not t.startswith("^") and not t.endswith(".NS") else t

INDICES = {"^NSEI": "NIFTY", "^NSEBANK": "BNKNFY", "^INDIAVIX": "VIX", "^DJI": "DOW", "^IXIC": "NSDQ"}
TV_INDICES = {"^NSEI": "NSE:NIFTY", "^NSEBANK": "NSE:BANKNIFTY", "^INDIAVIX": "NSE:INDIAVIX", "^DJI": "TVC:DJI", "^IXIC": "NASDAQ:IXIC"}

SECTOR_MAP = {
    "BANK": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK", "BANKBARODA", "PNB"],
    "IT": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM", "PERSISTENT", "COFORGE"],
    "AUTO": ["MARUTI", "M&M", "EICHERMOT", "BAJAJ-AUTO", "TVSMOTOR", "ASHOKLEY", "HEROMOTOCO"],
    "METAL": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "JINDALSTEL", "NMDC", "SAIL"],
    "PHARMA": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "LUPIN", "AUROPHARMA"],
    "ENERGY": ["RELIANCE", "NTPC", "ONGC", "POWERGRID", "BPCL", "TATAPOWER"]
}

BROADER_MARKET = ["HAL", "BEL", "BDL", "RVNL", "IRFC", "DIXON", "POLYCAB", "LT", "BAJFINANCE", "ZOMATO", "TRENT", "ADANIENT", "RELIANCE"]
BROADER_MARKET = [format_ticker(s) for s in BROADER_MARKET]

@st.cache_data(ttl=60)
def get_data():
    all_stocks = [format_ticker(s) for group in SECTOR_MAP.values() for s in group]
    all_tickers = list(INDICES.keys()) + BROADER_MARKET + all_stocks
    try:
        # 200 EMA కోసం కనీసం 250 క్యాండిల్స్ (దాదాపు 3-4 రోజుల 5m డేటా) ఉండాలి
        data = yf.download(list(set(all_tickers)), period="5d", interval="5m", progress=False, group_by='ticker', threads=False)
        return data
    except: return None

def analyze(symbol, full_data, force=False):
    try:
        if symbol not in full_data.columns.levels[0]: return None
        df = full_data[symbol].dropna()
        if len(df) < 200: return None # 200 EMA కోసం కనీసం 200 డేటా పాయింట్లు ఉండాలి
        
        # ⚡ EMA CALCULATIONS
        df['EMA10'] = df['Close'].ewm(span=10, adjust=False).mean()
        df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()
        
        today_df = df[df.index.date == df.index.date[-1]].copy()
        if today_df.empty: return None
        
        # Daily VWAP Reset
        today_df['TP'] = (today_df['High'] + today_df['Low'] + today_df['Close']) / 3
        today_df['CVP'] = (today_df['TP'] * today_df['Volume']).cumsum()
        today_df['CV'] = today_df['Volume'].cumsum()
        today_df['VWAP'] = today_df['CVP'] / today_df['CV']
        
        ltp, vwap, ema10, ema200 = float(today_df['Close'].iloc[-1]), float(today_df['VWAP'].iloc[-1]), float(today_df['EMA10'].iloc[-1]), float(today_df['EMA200'].iloc[-1])
        is_bull = ltp > vwap
        
        # ⚡ TRIPLE ENGINE ACCUMULATOR (VWAP + 10 EMA + 200 EMA)
        if is_bull: 
            today_df['Valid'] = (today_df['Close'] > today_df['VWAP']) & (today_df['Close'] > today_df['EMA10']) & (today_df['Close'] > today_df['EMA200'])
        else: 
            today_df['Valid'] = (today_df['Close'] < today_df['VWAP']) & (today_df['Close'] < today_df['EMA10']) & (today_df['Close'] < today_df['EMA200'])
        
        valid_candles = int(today_df['Valid'].sum())
        if valid_candles < 1: return None

        time_str = f"{(valid_candles*5)//60}h {(valid_candles*5)%60}m" if (valid_candles*5)>=60 else f"{valid_candles*5}m"
        day_chg = ((ltp - float(today_df['Open'].iloc[0])) / float(today_df['Open'].iloc[0])) * 100
        
        return {"STOCK": f"https://in.tradingview.com/chart/?symbol=NSE:{symbol.replace('.NS','')}", "PRICE": f"{ltp:.2f}", "DAY%": f"{day_chg:.2f}", "STAT": f"{'🚀' if is_bull else '🩸'} ({time_str})", "CANDLES": int(valid_candles)}
    except: return None

def highlight_priority(row):
    try:
        day_chg = float(row['DAY%'])
        return ['background-color: #e6fffa; color: #008000; font-weight: 900'] * len(row) if day_chg >= 0 else ['background-color: #fff5f5; color: #FF0000; font-weight: 900'] * len(row)
    except: return ['background-color: white; color: black'] * len(row)

# --- 3. EXECUTION ---
data = get_data()
if data is not None:
    # INDICES BOXES
    dash_html = '<div style="display: flex; justify-content: space-between; border: 2px solid #ddd; border-radius: 8px; background-color: #f9f9f9; padding: 5px; height: 80px;">'
    for ticker, name in INDICES.items():
        try:
            if ticker in data.columns.levels[0]:
                d = data[ticker].dropna(); ltp = float(d['Close'].iloc[-1]); pct = ((ltp - float(d['Close'].iloc[-2])) / float(d['Close'].iloc[-2])) * 100
                dash_html += f'<div style="flex: 1; text-align: center;"><div style="color: #444; font-size: 13px; font-weight: 800;">{name}</div><div style="color: black; font-size: 18px; font-weight: 900;">{ltp:.0f}</div><div style="color: {"#008000" if pct>=0 else "#FF0000"}; font-size: 14px;">{pct:.1f}%</div></div>'
        except: pass
    st.markdown(dash_html + "</div>", unsafe_allow_html=True)

    # SNIPER SEARCH
    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
    sniper_ticker = st.text_input("🎯 SNIPER SEARCH:", placeholder="Type symbol (e.g. BAJFINANCE)")
    if sniper_ticker:
        res = analyze(format_ticker(sniper_ticker), data, force=True)
        if res:
            st.markdown(f"<div class='table-head head-sniper'>🎯 SNIPER TARGET: {sniper_ticker.upper()}</div>", unsafe_allow_html=True)
            st.dataframe(pd.DataFrame([res]).style.apply(highlight_priority, axis=1), column_config={"STOCK": st.column_config.LinkColumn("STOCK", display_text=r"NSE:(.*)")}, use_container_width=True, hide_index=True)

    # PROCESS & DISPLAY
    all_stocks_list = [format_ticker(s) for group in SECTOR_MAP.values() for s in group]
    all_res = [analyze(s, data) for s in all_stocks_list]
    all_res = [x for x in all_res if x]
    df_all = pd.DataFrame(all_res)
    tv_cfg = {"STOCK": st.column_config.LinkColumn("STOCK", display_text=r"NSE:(.*)"), "CANDLES": st.column_config.NumberColumn("CANDLES", width="small")}

    # 4-TABLE GRID RESTORATION
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='table-head head-bull'>🚀 TOP BUY TRENDS (Triple Engine)</div>", unsafe_allow_html=True)
        if not df_all.empty:
            df_b = df_all[df_all['STAT'].str.contains('🚀')].sort_values("CANDLES", ascending=False).head(15)
            if not df_b.empty: st.dataframe(df_b.style.apply(highlight_priority, axis=1), column_config=tv_cfg, use_container_width=True, hide_index=True, height=350)
    with c2:
        st.markdown("<div class='table-head head-bear'>🩸 TOP SELL TRENDS (Triple Engine)</div>", unsafe_allow_html=True)
        if not df_all.empty:
            df_s = df_all[df_all['STAT'].str.contains('🩸')].sort_values("CANDLES", ascending=False).head(15)
            if not df_s.empty: st.dataframe(df_s.style.apply(highlight_priority, axis=1), column_config=tv_cfg, use_container_width=True, hide_index=True, height=350)

    c3, c4 = st.columns(2)
    with c3:
        st.markdown("<div class='table-head head-neut'>🌟 QUALITY MOVERS (Independent)</div>", unsafe_allow_html=True)
        if not df_all.empty:
            df_q = df_all.sort_values("CANDLES", ascending=False).head(15)
            if not df_q.empty: st.dataframe(df_q.style.apply(highlight_priority, axis=1), column_config=tv_cfg, use_container_width=True, hide_index=True, height=580)
    with c4:
        st.markdown("<div class='table-head head-neut'>🌌 BROADER MARKET TRENDS</div>", unsafe_allow_html=True)
        df_brd_list = [analyze(s, data) for s in BROADER_MARKET]
        df_brd = pd.DataFrame([x for x in df_brd_list if x])
        if not df_brd.empty: st.dataframe(df_brd.sort_values("CANDLES", ascending=False).style.apply(highlight_priority, axis=1), column_config=tv_cfg, use_container_width=True, hide_index=True, height=580)
else: st.error("డేటా లోడ్ అవ్వడం లేదు. ఇంటర్నెట్ చెక్ చేయండి.")
