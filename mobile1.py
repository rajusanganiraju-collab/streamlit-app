import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh
import concurrent.futures

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Mobile Terminal", page_icon="📈", layout="centered")

# --- 2. AUTO REFRESH (1 MINUTE) ---
st_autorefresh(interval=60000, key="datarefresh")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stApp { background-color: #ffffff; color: #000000; }
    
    /* Metrics Styling - Making them BIGGER for Mobile */
    div[data-testid="stMetricValue"] { font-size: 28px !important; font-weight: 900; color: #111; }
    div[data-testid="stMetricLabel"] { font-size: 14px !important; font-weight: bold; color: #555; }
    
    /* Table Styling for better fit */
    .stDataFrame { width: 100% !important; }
    th { background-color: #222 !important; color: white !important; font-size: 12px !important; }
    td { font-size: 12px !important; font-weight: 600; }
    
    h4 { margin-top: 20px; font-size: 16px; border-left: 5px solid #333; padding-left: 10px; background: #f0f0f0; padding-top: 5px; padding-bottom: 5px; }
    .bull-head { background: #d4edda; color: #155724; padding: 10px; font-weight: bold; margin-top: 15px; border-radius: 5px; }
    .bear-head { background: #f8d7da; color: #721c24; padding: 10px; font-weight: bold; margin-top: 15px; border-radius: 5px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. DATA CONFIGURATION ---
def format_ticker(t):
    t = t.upper().strip()
    if not t.startswith("^") and not t.endswith(".NS"):
        return f"{t}.NS"
    return t

INDICES = {"^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY", "^INDIAVIX": "VIX", "^DJI": "DOW"}

SECTOR_MAP = {
    "BANK": {"index": "^NSEBANK", "stocks": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK"]},
    "IT": {"index": "^CNXIT", "stocks": ["TCS", "INFY", "HCLTECH", "WIPRO"]},
    "AUTO": {"index": "^CNXAUTO", "stocks": ["MARUTI", "M&M", "EICHERMOT", "TVSMOTOR"]},
    "METAL": {"index": "^CNXMETAL", "stocks": ["TATASTEEL", "JSWSTEEL", "HINDALCO"]},
    "PHARMA": {"index": "^CNXPHARMA", "stocks": ["SUNPHARMA", "DRREDDY", "CIPLA"]},
    "FMCG": {"index": "^CNXFMCG", "stocks": ["ITC", "HINDUNILVR", "VBL"]},
    "ENERGY": {"index": "^CNXENERGY", "stocks": ["RELIANCE", "NTPC", "POWERGRID"]},
    "REALTY": {"index": "^CNXREALTY", "stocks": ["DLF", "GODREJPROP"]}
}

BROADER_MARKET = ["HAL", "RVNL", "IRFC", "ADANIPOWER", "BHEL", "CGPOWER", "PFC", "RECLTD", "JIOFIN", "DIXON", "ZOMATO", "L&T"]

for k in SECTOR_MAP:
    SECTOR_MAP[k]['stocks'] = [format_ticker(s) for s in SECTOR_MAP[k]['stocks']]
BROADER_MARKET = [format_ticker(s) for s in BROADER_MARKET]

# --- 4. LOGIC ---
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
        all_tickers.append(s['index'])
        all_tickers.extend(s['stocks'])
    all_tickers = list(set(all_tickers))
    results = []
    chunk_size = 25
    chunks = [all_tickers[i:i + chunk_size] for i in range(0, len(all_tickers), chunk_size)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(fetch_chunk, c) for c in chunks]
        for f in concurrent.futures.as_completed(futures):
            d = f.result()
            if not d.empty: results.append(d)
    if results:
        final_df = pd.concat(results, axis=1)
        return final_df.loc[:, ~final_df.columns.duplicated()]
    return None

def analyze(symbol, full_data, check_bullish=True, force=False):
    try:
        if symbol not in full_data.columns.levels[0]: return None
        df = full_data[symbol].dropna()
        if len(df) < 2: return None
        ltp, open_p, prev_c = df['Close'].iloc[-1], df['Open'].iloc[-1], df['Close'].iloc[-2]
        low, high = df['Low'].iloc[-1], df['High'].iloc[-1]
        day_chg = ((ltp - open_p) / open_p) * 100
        net_chg = ((ltp - prev_c) / prev_c) * 100
        avg_vol = df['Volume'].iloc[:-1].mean()
        curr_vol = df['Volume'].iloc[-1]
        vol_x = round(curr_vol / ((avg_vol/375) * get_minutes_passed()), 1)
        if force: check_bullish = day_chg > 0
        status, score = [], 0
        if day_chg >= 1.5: status.append("🚀"); score += 3
        if check_bullish and abs(open_p - low) < (ltp * 0.002): status.append("O=L"); score += 3
        if vol_x > 1.2: status.append("VOL"); score += 2
        if not status: return None
        return {"STOCK": symbol.replace(".NS",""), "PRICE": f"{ltp:.1f}", "%": f"{day_chg:.1f}", "VOL": f"{vol_x}x", "SCORE": score}
    except: return None

# --- 5. EXECUTION ---
data = get_data()

if data is not None:
    # 1. DASHBOARD (BIG)
    st.markdown("#### 📉 MARKET DASHBOARD")
    for ticker, name in INDICES.items():
        if ticker in data.columns.levels[0]:
            df = data[ticker].dropna()
            ltp = df['Close'].iloc[-1]
            pct = ((ltp - df['Close'].iloc[-2]) / df['Close'].iloc[-2]) * 100
            st.metric(name, f"{ltp:.1f}", f"{pct:.2f}%")
    
    st.divider()

    # 2. SECTOR RANKS
    st.markdown("#### 📋 SECTOR PERFORMANCE")
    sec_rows = []
    for name, info in SECTOR_MAP.items():
        if info['index'] in data.columns.levels[0]:
            df = data[info['index']].dropna()
            if not df.empty:
                c_now, o_now = df['Close'].iloc[-1], df['Open'].iloc[-1]
                sec_rows.append({"SECTOR": name, "DAY%": ((c_now - o_now) / o_now) * 100})
    if sec_rows:
        df_sec = pd.DataFrame(sec_rows).sort_values("DAY%", ascending=False)
        st.table(df_sec.set_index("SECTOR").style.format("{:.2f}"))
        top_s, bot_s = df_sec.iloc[0]['SECTOR'], df_sec.iloc[-1]['SECTOR']
    
    st.divider()

    # 3. BUY & SELL TABLES (One below another)
    st.markdown(f"<div class='bull-head'>🚀 BUY SIGNALS ({top_s})</div>", unsafe_allow_html=True)
    res_b = [analyze(s, data, True) for s in SECTOR_MAP[top_s]['stocks']]
    res_b = [x for x in res_b if x]
    if res_b: st.table(pd.DataFrame(res_b).sort_values("SCORE", ascending=False))
    else: st.write("No signals")

    st.markdown(f"<div class='bear-head'>🩸 SELL SIGNALS ({bot_s})</div>", unsafe_allow_html=True)
    res_s = [analyze(s, data, False) for s in SECTOR_MAP[bot_s]['stocks']]
    res_s = [x for x in res_s if x]
    if res_s: st.table(pd.DataFrame(res_s).sort_values("SCORE", ascending=False))
    else: st.write("No signals")

    # 4. INDEPENDENT & BROADER
    st.markdown("#### 🌟 INDEPENDENT MOVERS")
    ind_m = [analyze(s, data, force=True) for s in BROADER_MARKET[:6]]
    ind_m = [x for x in ind_m if x]
    if ind_m: st.table(pd.DataFrame(ind_m))

    st.markdown("#### 🌌 BROADER MARKET")
    brd_m = [analyze(s, data, force=True) for s in BROADER_MARKET[6:]]
    brd_m = [x for x in brd_m if x]
    if brd_m: st.table(pd.DataFrame(brd_m))

else:
    st.write("Data loading...")
