import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh
import concurrent.futures

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Terminal", page_icon="📈", layout="wide")

# --- 2. AUTO RUN (1 MINUTE) ---
st_autorefresh(interval=60000, key="datarefresh")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stApp { background-color: #ffffff; color: #000000; }
    div[data-testid="stMetricValue"] { font-size: 18px !important; font-weight: 800; }
    th { background-color: #222222 !important; color: white !important; font-size: 13px !important; }
    td { font-size: 13px !important; color: #000; font-weight: 600; }
    h4 { margin: 15px 0px; font-size: 15px; text-transform: uppercase; border-bottom: 2px solid #333; padding-bottom: 5px; }
    .bull-head { background: #d4edda; color: #155724; padding: 10px; font-weight: bold; margin-bottom: 10px; }
    .bear-head { background: #f8d7da; color: #721c24; padding: 10px; font-weight: bold; margin-bottom: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. DATA & LOGIC (KEEPING YOUR ORIGINAL LOGIC) ---
def format_ticker(t):
    t = t.upper().strip()
    if not t.startswith("^") and not t.endswith(".NS"): return f"{t}.NS"
    return t

INDICES = {"^NSEI": "NIFTY", "^NSEBANK": "BNKNFY", "^INDIAVIX": "VIX", "^DJI": "DOW", "^IXIC": "NSDQ"}

SECTOR_MAP = {
    "BANK": {"index": "^NSEBANK", "stocks": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK"]},
    "IT": {"index": "^CNXIT", "stocks": ["TCS", "INFY", "HCLTECH", "WIPRO"]},
    "AUTO": {"index": "^CNXAUTO", "stocks": ["MARUTI", "M&M", "EICHERMOT", "BAJAJ-AUTO"]},
    "METAL": {"index": "^CNXMETAL", "stocks": ["TATASTEEL", "JSWSTEEL", "HINDALCO"]},
    "PHARMA": {"index": "^CNXPHARMA", "stocks": ["SUNPHARMA", "DRREDDY", "CIPLA"]},
    "FMCG": {"index": "^CNXFMCG", "stocks": ["ITC", "HINDUNILVR", "VBL"]},
    "ENERGY": {"index": "^CNXENERGY", "stocks": ["RELIANCE", "NTPC", "POWERGRID"]},
    "REALTY": {"index": "^CNXREALTY", "stocks": ["DLF", "GODREJPROP"]}
}

BROADER_MARKET = ["HAL", "BEL", "RVNL", "IRFC", "ADANIPOWER", "CGPOWER", "JIOFIN", "DIXON", "L&T", "ZOMATO"]
for k in SECTOR_MAP: SECTOR_MAP[k]['stocks'] = [format_ticker(s) for s in SECTOR_MAP[k]['stocks']]
BROADER_MARKET = [format_ticker(s) for s in BROADER_MARKET]

def get_minutes_passed():
    now = datetime.now()
    if now.weekday() >= 5 or now.time() > dt_time(15, 30): return 375
    open_time = now.replace(hour=9, minute=15, second=0)
    diff = (now - open_time).total_seconds() / 60
    return min(375, max(1, int(diff)))

def fetch_chunk(tickers):
    try: return yf.download(tickers, period="5d", progress=False, group_by='ticker', threads=False)
    except: return pd.DataFrame()

@st.cache_data(ttl=60)
def get_data():
    all_tickers = list(INDICES.keys()) + list(BROADER_MARKET)
    for s in SECTOR_MAP.values():
        all_tickers.append(s['index']); all_tickers.extend(s['stocks'])
    all_tickers = list(set(all_tickers))
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        chunks = [all_tickers[i:i + 20] for i in range(0, len(all_tickers), 20)]
        futures = [executor.submit(fetch_chunk, c) for c in chunks]
        for f in concurrent.futures.as_completed(futures):
            d = f.result()
            if not d.empty: results.append(d)
    return pd.concat(results, axis=1).loc[:, ~pd.concat(results, axis=1).columns.duplicated()] if results else None

def analyze(symbol, full_data, check_bullish=True, force=False):
    try:
        if symbol not in full_data.columns.levels[0]: return None
        df = full_data[symbol].dropna()
        if len(df) < 2: return None
        ltp, open_p, prev_c = df['Close'].iloc[-1], df['Open'].iloc[-1], df['Close'].iloc[-2]
        day_chg = ((ltp - open_p) / open_p) * 100
        net_chg = ((ltp - prev_c) / prev_c) * 100
        vol_x = round(df['Volume'].iloc[-1] / ((df['Volume'].iloc[:-1].mean()/375) * get_minutes_passed()), 1)
        if force: check_bullish = day_chg > 0
        score = 3 if day_chg >= 2.0 or day_chg <= -2.0 else 0
        return {"STOCK": symbol.replace(".NS",""), "PRICE": f"{ltp:.1f}", "DAY%": f"{day_chg:.1f}", "NET%": f"{net_chg:.2f}", "VOL": f"{vol_x}x", "SCORE": score}
    except: return None

# --- 4. DISPLAY EXECUTION (ONE BY ONE) ---
data = get_data()

if data is not None:
    # 1. Dashboard
    st.markdown("#### 📉 DASHBOARD")
    m_cols = st.columns(3) # మొబైల్ లో కూడా 3 మెట్రిక్స్ పట్టేలా
    for idx, (ticker, name) in enumerate(INDICES.items()):
        if ticker in data.columns.levels[0]:
            df = data[ticker].dropna()
            ltp = df['Close'].iloc[-1]
            pct = ((ltp - df['Close'].iloc[-2]) / df['Close'].iloc[-2]) * 100
            m_cols[idx % 3].metric(name, f"{ltp:.0f}", f"{pct:.1f}%")

    st.divider()

    # 2. Sector Ranks
    st.markdown("#### 📋 SECTOR RANKS")
    sec_rows = []
    for name, info in SECTOR_MAP.items():
        if info['index'] in data.columns.levels[0]:
            df = data[info['index']].dropna()
            if not df.empty:
                c, o = df['Close'].iloc[-1], df['Open'].iloc[-1]
                sec_rows.append({"SECTOR": name, "DAY%": ((c - o) / o) * 100})
    if sec_rows:
        df_sec = pd.DataFrame(sec_rows).sort_values("DAY%", ascending=False)
        st.dataframe(df_sec.set_index("SECTOR").style.format("{:.2f}"), use_container_width=True)
        top_s, bot_s = df_sec.index[0], df_sec.index[-1]

    st.divider()

    # 3. Buy & Sell Tables
    st.markdown(f"<div class='bull-head'>🚀 BUY: {top_s}</div>", unsafe_allow_html=True)
    res_b = [analyze(s, data, True) for s in SECTOR_MAP[top_s]['stocks']]
    if [x for x in res_b if x]: st.dataframe(pd.DataFrame([x for x in res_b if x]), use_container_width=True, hide_index=True)

    st.markdown(f"<div class='bear-head'>🩸 SELL: {bot_s}</div>", unsafe_allow_html=True)
    res_s = [analyze(s, data, False) for s in SECTOR_MAP[bot_s]['stocks']]
    if [x for x in res_s if x]: st.dataframe(pd.DataFrame([x for x in res_s if x]), use_container_width=True, hide_index=True)

    st.divider()

    # 4. Independent & Broader
    st.markdown("#### 🌟 INDEPENDENT (Top 8)")
    ind_m = [analyze(s, data, force=True) for s in BROADER_MARKET[:5]]
    if [x for x in ind_m if x]: st.dataframe(pd.DataFrame([x for x in ind_m if x]), use_container_width=True, hide_index=True)

    st.markdown("#### 🌌 BROADER MARKET (Top 8)")
    brd_m = [analyze(s, data, force=True) for s in BROADER_MARKET[5:]]
    if [x for x in brd_m if x]: st.dataframe(pd.DataFrame([x for x in brd_m if x]), use_container_width=True, hide_index=True)

else:
    st.write("Trying to fetch data...")
