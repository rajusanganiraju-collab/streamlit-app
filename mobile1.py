import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Terminal", page_icon="📈", layout="wide")
st_autorefresh(interval=60000, key="datarefresh")

# CSS - పాత లుక్ ని (Sectors & Grid) మళ్ళీ సెట్ చేశాను
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {display: none !important;}
    .stApp { background-color: #ffffff; color: #000000; }
    html, body, [class*="css"] { font-family: 'Arial', sans-serif; font-weight: 600; color: #000000 !important; }
    .block-container { padding: 0.5rem 0.1rem -10px !important; }
    th { background-color: #ffffff !important; color: #000000 !important; font-size: 12px !important; border-bottom: 2px solid #222 !important; text-align: center !important; }
    td { font-size: 12px !important; color: #000000 !important; border-bottom: 1px solid #ccc !important; text-align: center !important; font-weight: 700 !important; }
    .table-head { padding: 6px 10px; font-weight: 900; font-size: 14px; text-transform: uppercase; border-radius: 4px; text-align: left; margin-top: 5px; }
    .head-bull { background: #d4edda; color: #155724; }
    .head-bear { background: #f8d7da; color: #721c24; }
    .head-neut { background: #e2e3e5; color: #383d41; }
    div[data-testid="stDataFrame"] { margin-bottom: -15px !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. DATA CONFIGURATION ---
def format_ticker(t):
    t = t.upper().strip()
    return f"{t}.NS" if not t.startswith("^") and not t.endswith(".NS") else t

INDICES = {"^NSEI": "NIFTY", "^NSEBANK": "BNKNFY", "^INDIAVIX": "VIX", "^DJI": "DOW", "^IXIC": "NSDQ"}
SECTOR_MAP = {
    "BANK": {"index": "^NSEBANK", "stocks": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK", "BANKBARODA", "PNB"]},
    "IT": {"index": "^CNXIT", "stocks": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM", "PERSISTENT", "COFORGE"]},
    "AUTO": {"index": "^CNXAUTO", "stocks": ["MARUTI", "M&M", "EICHERMOT", "BAJAJ-AUTO", "TVSMOTOR", "ASHOKLEY", "HEROMOTOCO"]},
    "METAL": {"index": "^CNXMETAL", "stocks": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "JINDALSTEL", "NMDC", "SAIL"]},
    "PHARMA": {"index": "^CNXPHARMA", "stocks": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "LUPIN", "AUROPHARMA"]},
    "FMCG": {"index": "^CNXFMCG", "stocks": ["ITC", "HINDUNILVR", "BRITANNIA", "VBL", "NESTLEIND"]},
    "ENERGY": {"index": "^CNXENERGY", "stocks": ["RELIANCE", "NTPC", "ONGC", "POWERGRID", "BPCL", "TATAPOWER"]},
    "REALTY": {"index": "^CNXREALTY", "stocks": ["DLF", "GODREJPROP", "LODHA", "OBEROIRLTY"]}
}
BROADER_MARKET = ["HAL", "BEL", "RVNL", "IRFC", "DIXON", "POLYCAB", "LT", "BAJFINANCE", "ZOMATO", "TRENT", "ADANIENT", "RELIANCE"]
BROADER_MARKET = [format_ticker(s) for s in BROADER_MARKET]

@st.cache_data(ttl=60)
def get_data():
    all_tickers = list(INDICES.keys()) + BROADER_MARKET
    for s in SECTOR_MAP.values():
        all_tickers.append(s['index'])
        all_tickers.extend([format_ticker(stk) for stk in s['stocks']])
    all_tickers = list(set(all_tickers))
    try:
        data = yf.download(all_tickers, period="2d", interval="5m", progress=False, group_by='ticker', threads=False)
        return data, all_tickers
    except: return None, all_tickers

def analyze(symbol, full_data, check_bullish=True, force=False):
    try:
        df = full_data[symbol].copy().dropna()
        if len(df) < 10: return None
        df['EMA10'] = df['Close'].ewm(span=10, adjust=False).mean()
        df['TP'] = (df['High'] + df['Low'] + df['Close']) / 3
        df['CVP'] = (df['TP'] * df['Volume']).cumsum(); df['CV'] = df['Volume'].cumsum()
        df['VWAP'] = df['CVP'] / df['CV']
        today_df = df[df.index.date == df.index.date[-1]].copy()
        
        ltp = float(today_df['Close'].iloc[-1]); op = float(today_df['Open'].iloc[0]); vwap = float(today_df['VWAP'].iloc[-1])
        day_chg = ((ltp - op) / op) * 100; is_bull = ltp > vwap
        if not force and ((check_bullish and not is_bull) or (not check_bullish and is_bull)): return None

        # ⚡ ACCUMULATOR LOGIC: గ్యాప్స్ ఒమిట్ చేసి రోజంతా ఉన్న క్వాలిటీ క్యాండిల్స్ ని లెక్కిస్తుంది.
        if is_bull:
            today_df['Valid'] = (today_df['Close'] > today_df['VWAP']) & (today_df['Close'] > today_df['EMA10'])
        else:
            today_df['Valid'] = (today_df['Close'] < today_df['VWAP']) & (today_df['Close'] < today_df['EMA10'])
        
        valid_candles = int(today_df['Valid'].sum())
        if valid_candles < 2: return None

        score_mins = valid_candles * 5
        time_str = f"{score_mins//60}h {score_mins%60}m" if score_mins>=60 else f"{score_mins}m"
        
        return {
            "STOCK": f"https://in.tradingview.com/chart/?symbol=NSE:{symbol.replace('.NS','')}",
            "LTP": f"{ltp:.2f}", "D%": f"{day_chg:.2f}", "STAT": f"{'🚀' if is_bull else '🩸'} ({time_str})",
            "CANDLES": int(valid_candles), "TREND": "BULL" if is_bull else "BEAR"
        }
    except: return None

def highlight_priority(row):
    try:
        day_chg = float(row['D%'])
        return ['background-color: #e6fffa; color: #008000; font-weight: 900'] * len(row) if day_chg >= 0 else ['background-color: #fff5f5; color: #FF0000; font-weight: 900'] * len(row)
    except: pass
    return ['background-color: white; color: black'] * len(row)

def create_sorted_df(res_list, limit=15):
    res_list = [x for x in res_list if x]
    if not res_list: return pd.DataFrame()
    df = pd.DataFrame(res_list); df['ABS_D'] = df['D%'].astype(float).abs()
    return df.sort_values(by=["CANDLES", "ABS_D"], ascending=[False, False]).drop(columns=["ABS_D", "TREND"]).head(limit)

# --- 3. EXECUTION ---
data, all_ticks = get_data()
if data is not None:
    # INDICES BOXES
    dash_html = '<div style="display: flex; justify-content: space-between; border: 2px solid #ddd; border-radius: 8px; background-color: #f9f9f9; padding: 5px; height: 80px;">'
    for ticker, name in INDICES.items():
        try:
            if ticker in data.columns.levels[0]:
                d = data[ticker].dropna(); ltp = d['Close'].iloc[-1]; op = d['Open'].iloc[0]; pct = ((ltp-op)/op)*100
                dash_html += f'<div style="flex: 1; text-align: center;"><div style="color: #444; font-size: 13px; font-weight: 800;">{name}</div><div style="color: black; font-size: 18px; font-weight: 900; margin: 2px 0px;">{ltp:.0f}</div><div style="color: {"#008000" if pct>=0 else "#FF0000"}; font-size: 14px; font-weight: bold;">{"↑" if pct>=0 else "↓"} {pct:.1f} %</div></div>'
        except: pass
    dash_html += "</div>"; st.markdown(dash_html, unsafe_allow_html=True)

    # SECTOR ANALYSIS (Finding Top and Bottom)
    sec_rows = []
    for name, info in SECTOR_MAP.items():
        try:
            if info['index'] in data.columns.levels[0]:
                d = data[info['index']].dropna(); ltp = d['Close'].iloc[-1]; op = d['Open'].iloc[0]; d_pct = ((ltp-op)/op)*100
                sec_rows.append({"SECTOR": name, "D%": d_pct})
        except: pass
    df_sec = pd.DataFrame(sec_rows).sort_values("D%", ascending=False) if sec_rows else pd.DataFrame()
    top_sec = df_sec.iloc[0]['SECTOR'] if not df_sec.empty else ""; bot_sec = df_sec.iloc[-1]['SECTOR'] if not df_sec.empty else ""

    # CREATING TABLES
    df_b = create_sorted_df([analyze(s, data, True) for s in SECTOR_MAP.get(top_sec, {}).get('stocks', [])])
    df_s = create_sorted_df([analyze(s, data, False) for s in SECTOR_MAP.get(bot_sec, {}).get('stocks', [])])
    df_ind = create_sorted_df([analyze(s, data, force=True) for n, i in SECTOR_MAP.items() if n not in [top_sec, bot_sec] for s in i['stocks']])
    df_brd = create_sorted_df([analyze(s, data, force=True) for s in BROADER_MARKET])

    tv_cfg = {"STOCK": st.column_config.LinkColumn("STOCK", display_text=r"NSE:(.*)"), "CANDLES": st.column_config.NumberColumn("CANDLES", width="small")}
    
    # DISPLAYING IN 2x2 GRID
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"<div class='table-head head-bull'>🚀 BUY: {top_sec}</div>", unsafe_allow_html=True)
        if not df_b.empty: st.dataframe(df_b.style.apply(highlight_priority, axis=1), column_config=tv_cfg, use_container_width=True, hide_index=True, height=350)
    with c2:
        st.markdown(f"<div class='table-head head-bear'>🩸 SELL: {bot_sec}</div>", unsafe_allow_html=True)
        if not df_s.empty: st.dataframe(df_s.style.apply(highlight_priority, axis=1), column_config=tv_cfg, use_container_width=True, hide_index=True, height=350)

    c3, c4 = st.columns(2)
    with c3:
        st.markdown("<div class='table-head head-neut'>🌟 INDEPENDENT</div>", unsafe_allow_html=True)
        if not df_ind.empty: st.dataframe(df_ind.style.apply(highlight_priority, axis=1), column_config=tv_cfg, use_container_width=True, hide_index=True, height=580)
    with c4:
        st.markdown("<div class='table-head head-neut'>🌌 BROADER MARKET</div>", unsafe_allow_html=True)
        if not df_brd.empty: st.dataframe(df_brd.style.apply(highlight_priority, axis=1), column_config=tv_cfg, use_container_width=True, hide_index=True, height=580)
