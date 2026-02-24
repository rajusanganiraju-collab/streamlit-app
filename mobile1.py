import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Terminal", page_icon="🎯", layout="wide")
st_autorefresh(interval=60000, key="datarefresh")

# CSS - పాత డిజైన్ & టేబుల్ స్టైలింగ్
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {display: none !important;}
    .stApp { background-color: #ffffff; color: #000000; }
    html, body, [class*="css"] { font-family: 'Arial', sans-serif; font-weight: 600; color: #000000 !important; }
    .block-container { padding-top: 0.5rem !important; padding-bottom: 0rem !important; padding-left: 0.5rem !important; padding-right: 0.5rem !important; margin-top: -10px; }
    th { background-color: #ffffff !important; color: #000000 !important; font-size: 14px !important; text-align: center !important; border-bottom: 2px solid #222222 !important; border-top: 2px solid #222222 !important; padding: 6px !important; }
    td { font-size: 14px !important; color: #000000 !important; border-bottom: 1px solid #ccc !important; text-align: center !important; padding: 4px !important; font-weight: 700 !important; }
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
    "BANK": {"index": "^NSEBANK", "stocks": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK", "BANKBARODA", "PNB"]},
    "IT": {"index": "^CNXIT", "stocks": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM", "PERSISTENT", "COFORGE"]},
    "AUTO": {"index": "^CNXAUTO", "stocks": ["MARUTI", "M&M", "EICHERMOT", "BAJAJ-AUTO", "TVSMOTOR", "ASHOKLEY", "HEROMOTOCO"]},
    "METAL": {"index": "^CNXMETAL", "stocks": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "JINDALSTEL", "NMDC", "SAIL"]},
    "PHARMA": {"index": "^CNXPHARMA", "stocks": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "LUPIN", "AUROPHARMA"]},
    "FMCG": {"index": "^CNXFMCG", "stocks": ["ITC", "HINDUNILVR", "BRITANNIA", "VBL", "NESTLEIND"]},
    "ENERGY": {"index": "^CNXENERGY", "stocks": ["RELIANCE", "NTPC", "ONGC", "POWERGRID", "BPCL", "TATAPOWER"]}
}

BROADER_MARKET = ["HAL", "BEL", "BDL", "RVNL", "IRFC", "DIXON", "POLYCAB", "LT", "BAJFINANCE", "ZOMATO", "TRENT", "ADANIENT", "RELIANCE"]
BROADER_MARKET = [format_ticker(s) for s in BROADER_MARKET]

@st.cache_data(ttl=60)
def get_data():
    all_tickers = list(INDICES.keys()) + BROADER_MARKET
    for s in SECTOR_MAP.values():
        all_tickers.append(s['index']); all_tickers.extend([format_ticker(stk) for stk in s['stocks']])
    try:
        data = yf.download(list(set(all_tickers)), period="5d", interval="5m", progress=False, group_by='ticker', threads=False)
        return data
    except: return None

def analyze(symbol, full_data, check_bullish=True, force=False):
    try:
        if symbol not in full_data.columns.levels[0]: return None
        df = full_data[symbol].dropna()
        if len(df) < 200: return None
        df['EMA10'] = df['Close'].ewm(span=10, adjust=False).mean()
        df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()
        today_df = df[df.index.date == df.index.date[-1]].copy()
        if today_df.empty: return None
        today_df['TP'] = (today_df['High'] + today_df['Low'] + today_df['Close']) / 3
        today_df['CVP'] = (today_df['TP'] * today_df['Volume']).cumsum(); today_df['CV'] = today_df['Volume'].cumsum()
        today_df['VWAP'] = today_df['CVP'] / today_df['CV']
        ltp, vwap = float(today_df['Close'].iloc[-1]), float(today_df['VWAP'].iloc[-1])
        is_bull = ltp > vwap
        if not force and ((check_bullish and not is_bull) or (not check_bullish and is_bull)): return None
        if is_bull: today_df['Valid'] = (today_df['Close'] > today_df['VWAP']) & (today_df['Close'] > today_df['EMA10']) & (today_df['Close'] > today_df['EMA200'])
        else: today_df['Valid'] = (today_df['Close'] < today_df['VWAP']) & (today_df['Close'] < today_df['EMA10']) & (today_df['Close'] < today_df['EMA200'])
        valid_count = int(today_df['Valid'].sum())
        if valid_count < 1: return None
        time_str = f"{(valid_count*5)//60}h {(valid_count*5)%60}m" if (valid_count*5)>=60 else f"{valid_count*5}m"
        return {"STOCK": f"https://in.tradingview.com/chart/?symbol=NSE:{symbol.replace('.NS','')}", "PRICE": f"{ltp:.2f}", "DAY%": f"{((ltp-float(today_df['Open'].iloc[0]))/float(today_df['Open'].iloc[0]))*100:.2f}", "STAT": f"{'🚀' if is_bull else '🩸'} ({time_str})", "CANDLES": int(valid_count)}
    except: return None

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

    # SECTOR SCREENER LOGIC
    sec_rows = []
    for name, info in SECTOR_MAP.items():
        try:
            if info['index'] in data.columns.levels[0]:
                d = data[info['index']].dropna(); op, ltp = float(d['Open'].iloc[-1]), float(d['Close'].iloc[-1])
                sec_rows.append({"SECTOR": name, "DAY%": ((ltp-op)/op)*100})
        except: pass
    df_sec = pd.DataFrame(sec_rows).sort_values("DAY%", ascending=False) if sec_rows else pd.DataFrame()
    top_sec = df_sec.iloc[0]['SECTOR'] if not df_sec.empty else "BANK"
    bot_sec = df_sec.iloc[-1]['SECTOR'] if not df_sec.empty else "IT"

    # TABLES GRID
    tv_cfg = {"STOCK": st.column_config.LinkColumn("STOCK", display_text=r"NSE:(.*)"), "CANDLES": st.column_config.NumberColumn("CANDLES", width="small")}
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"<div class='table-head head-bull'>🚀 BUY: {top_sec}</div>", unsafe_allow_html=True)
        stocks = SECTOR_MAP.get(top_sec, {}).get('stocks', [])
        df_b = pd.DataFrame([res for s in stocks if (res := analyze(s, data, True))])
        if not df_b.empty: st.dataframe(df_b.sort_values("CANDLES", ascending=False), column_config=tv_cfg, use_container_width=True, hide_index=True)
    with c2:
        st.markdown(f"<div class='table-head head-bear'>🩸 SELL: {bot_sec}</div>", unsafe_allow_html=True)
        stocks = SECTOR_MAP.get(bot_sec, {}).get('stocks', [])
        df_s = pd.DataFrame([res for s in stocks if (res := analyze(s, data, False))])
        if not df_s.empty: st.dataframe(df_s.sort_values("CANDLES", ascending=False), column_config=tv_cfg, use_container_width=True, hide_index=True)

    c3, c4 = st.columns(2)
    with c3:
        st.markdown("<div class='table-head head-neut'>🌟 INDEPENDENT movers</div>", unsafe_allow_html=True)
        ind_stocks = [s for n, i in SECTOR_MAP.items() if n not in [top_sec, bot_sec] for s in i['stocks']]
        df_ind = pd.DataFrame([res for s in ind_stocks if (res := analyze(s, data, force=True))])
        if not df_ind.empty: st.dataframe(df_ind.sort_values("CANDLES", ascending=False).head(15), column_config=tv_cfg, use_container_width=True, hide_index=True)
    with c4:
        st.markdown("<div class='table-head head-neut'>🌌 BROADER MARKET</div>", unsafe_allow_html=True)
        df_brd = pd.DataFrame([res for s in BROADER_MARKET if (res := analyze(s, data, force=True))])
        if not df_brd.empty: st.dataframe(df_brd.sort_values("CANDLES", ascending=False), column_config=tv_cfg, use_container_width=True, hide_index=True)
