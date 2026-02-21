import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh
import concurrent.futures

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Terminal", page_icon="📈", layout="wide")

# --- 2. AUTO RUN (1 MINUTE) & HIDE REFRESH BUTTON ---
st_autorefresh(interval=60000, key="datarefresh")

# CSS DESIGN CHANGES ADDED HERE
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    button[title="View fullscreen"] {visibility: hidden;}
    [data-testid="stStatusWidget"] {display: none;}
    
    .stApp { background-color: #ffffff; color: #000000; }
    html, body, [class*="css"] { font-family: 'Arial', sans-serif; color: #000000; }
    .block-container { padding: 1rem; }
    
    /* 🔥 Table Styling - Updated to White Headers, Bold Text & No Word Wrap */
    th { 
        background-color: #ffffff !important; 
        color: #000000 !important; 
        font-size: 13px !important; 
        font-weight: 900 !important; 
        text-align: left !important; 
        padding: 8px 10px !important; 
        border-bottom: 2px solid #000000 !important;
        white-space: nowrap !important;
    }
    td { 
        font-size: 13px !important; 
        font-weight: 700 !important; /* Bold text for tables */
        color: #000000 !important; 
        border-bottom: 1px solid #eeeeee !important; 
        text-align: left !important; 
        padding: 6px 10px !important; 
        white-space: nowrap !important; /* Prevents table expanding width weirdly */
    }
    
    /* 🔥 Dashboard Single Line Fix */
    [data-testid="column"] {
        min-width: max-content !important;
        flex: 1 1 auto !important;
    }
    
    /* Metrics Styling */
    div[data-testid="stMetricValue"] { font-size: 15px !important; font-weight: 800; }
    div[data-testid="stMetricLabel"] { font-size: 10px; font-weight: bold; color: #444; }
    
    h4 { margin: 5px 0px; font-size: 13px; text-transform: uppercase; border-bottom: 2px solid #333; padding-bottom: 5px; }
    .bull-head { background: #d4edda; color: #155724; padding: 5px; font-weight: bold; border: 1px solid #c3e6cb; }
    .bear-head { background: #f8d7da; color: #721c24; padding: 5px; font-weight: bold; border: 1px solid #f5c6cb; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. DATA CONFIGURATION ---
def format_ticker(t):
    t = t.upper().strip()
    if not t.startswith("^") and not t.endswith(".NS"):
        return f"{t}.NS"
    return t

INDICES = {
    "^NSEI": "NIFTY",
    "^NSEBANK": "BNKNFY",
    "^INDIAVIX": "VIX",
    "^DJI": "DOW",
    "^IXIC": "NSDQ"
}

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

BROADER_MARKET = [
    "HAL", "BEL", "BDL", "MAZDOCK", "COCHINSHIP", "GRSE",
    "RVNL", "IRFC", "IRCON", "TITAGARH", "RAILTEL", "RITES",
    "ADANIPOWER", "ADANIGREEN", "NHPC", "SJVN", "BHEL", "CGPOWER", "SUZLON",
    "PFC", "RECLTD", "IREDA", "IOB", "UCOBANK", "MAHABANK", "CANBK",
    "BAJFINANCE", "CHOLAFIN", "JIOFIN", "MUTHOOTFIN", "MANAPPURAM", "SHRIRAMFIN", "M&MFIN",
    "DIXON", "POLYCAB", "KAYNES", "HAVELLS", "KEI", "RRKABEL",
    "SRF", "TATACHEM", "DEEPAKNTR", "AARTIIND", "PIIND", "FACT", "UPL",
    "ULTRACEMCO", "AMBUJACEM", "SHREECEM", "DALBHARAT", "L&T", "CUMMINSIND", "ABB", "SIEMENS",
    "BHARTIARTL", "IDEA", "INDIGO", "ZOMATO", "TRENT", "DMART", "PAYTM", "ZENTEC",
    "ADANIENT", "ADANIPORTS", "ATGL", "AWL",
    "BOSCHLTD", "MRF", "MOTHERSON", "SONACOMS", "EXIDEIND", "AMARAJABAT"
]

for k in SECTOR_MAP:
    SECTOR_MAP[k]['stocks'] = [format_ticker(s) for s in SECTOR_MAP[k]['stocks']]
BROADER_MARKET = [format_ticker(s) for s in BROADER_MARKET]

# --- 4. LOGIC ---
def get_minutes_passed():
    now = datetime.now()
    if now.weekday() >= 5 or now.time() > dt_time(15, 30):
        return 375
    open_time = now.replace(hour=9, minute=15, second=0)
    diff = (now - open_time).total_seconds() / 60
    return min(375, max(1, int(diff)))

def fetch_chunk(tickers):
    try:
        return yf.download(tickers, period="5d", progress=False, group_by='ticker', threads=False)
    except: return pd.DataFrame()

@st.cache_data(ttl=60)
def get_data():
    all_tickers = list(INDICES.keys()) + list(BROADER_MARKET)
    for s in SECTOR_MAP.values():
        all_tickers.append(s['index'])
        all_tickers.extend(s['stocks'])
    all_tickers = list(set(all_tickers))
    chunk_size = 20
    chunks = [all_tickers[i:i + chunk_size] for i in range(0, len(all_tickers), chunk_size)]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_chunk = {executor.submit(fetch_chunk, chunk): chunk for chunk in chunks}
        for future in concurrent.futures.as_completed(future_to_chunk):
            try:
                data = future.result()
                if not data.empty: results.append(data)
            except: continue
    if results:
        final_df = pd.concat(results, axis=1)
        return final_df.loc[:, ~final_df.columns.duplicated()]
    return None

def analyze(symbol, full_data, check_bullish=True, force=False):
    try:
        if symbol not in full_data.columns.levels[0]: return None
        df = full_data[symbol].dropna()
        if len(df) < 2: return None
        
        ltp = float(df['Close'].iloc[-1])
        open_p = float(df['Open'].iloc[-1])
        prev_c = float(df['Close'].iloc[-2])
        low = float(df['Low'].iloc[-1])
        high = float(df['High'].iloc[-1])
        
        day_chg = ((ltp - open_p) / open_p) * 100
        net_chg = ((ltp - prev_c) / prev_c) * 100
        todays_move = net_chg - day_chg

        avg_vol = df['Volume'].iloc[:-1].mean()
        curr_vol = float(df['Volume'].iloc[-1])
        minutes = get_minutes_passed()
        vol_x = round(curr_vol / ((avg_vol/375) * minutes), 1) if avg_vol > 0 else 0.0
        vwap = (high + low + ltp) / 3

        if force: check_bullish = day_chg > 0
        sl, tgt = (low, ltp * 1.02) if check_bullish else (high, ltp * 0.98)
        status, score = [], 0
        
        # 0.3% Buffer
        is_open_low = abs(open_p - low) <= (ltp * 0.003)
        is_open_high = abs(open_p - high) <= (ltp * 0.003)
        
        # Scoring
        if day_chg >= 2.0: status.append("BigMove🚀"); score += 3
        elif day_chg <= -2.0: status.append("BigMove🩸"); score += 3

        if check_bullish:
            if is_open_low: status.append("O=L🔥"); score += 3
            if vol_x > 1.0: status.append("VOL🟢"); score += 3
            if ltp >= high * 0.998 and day_chg > 0.5: status.append("HB🚀"); score += 1
            
            try:
                df_5m = yf.download(symbol, period="1d", interval="5m", progress=False)
                if isinstance(df_5m.columns, pd.MultiIndex): df_5m.columns = df_5m.columns.droplevel(1)
                if not df_5m.empty and len(df_5m) >= 20:
                    df_5m['EMA_10'] = df_5m['Close'].ewm(span=10, adjust=False).mean()
                    df_5m['EMA_20'] = df_5m['Close'].ewm(span=20, adjust=False).mean()
                    ema_10, ema_20 = float(df_5m['EMA_10'].iloc[-1]), float(df_5m['EMA_20'].iloc[-1])
                    current_close, recent_low = float(df_5m['Close'].iloc[-1]), float(df_5m['Low'].iloc[-3:].min())
                    if (recent_low <= ema_10 * 1.003) and (recent_low >= ema_10 * 0.997) and current_close > ema_10:
                        status.append("10EMA Bounce🟢"); score += 1
                    if (recent_low <= ema_20 * 1.003) and (recent_low >= ema_20 * 0.997) and current_close > ema_20:
                        status.append("20EMA Bounce🟢"); score += 1
            except: pass
            if ltp > (low * 1.01) and ltp > vwap: status.append("Rec ⇈"); score += 1
        else:
            if is_open_high: status.append("O=H🩸"); score += 3
            if vol_x > 1.0: status.append("VOL🔴"); score += 3
            if ltp <= low * 1.002 and day_chg < -0.5: status.append("LB📉"); score += 1
            if ltp < (high * 0.99) and ltp < vwap: status.append("PB ⇊"); score += 1
            
        if not status: return None
        return {
            "STOCK": symbol.replace(".NS", ""), "PRICE": f"{ltp:.2f}", "DAY%": f"{day_chg:.2f}",
            "NET%": f"{net_chg:.2f}", "MOVE": f"{todays_move:.2f}", "SL": f"{sl:.2f}",
            "TGT": f"{tgt:.2f}", "VOL": f"{vol_x:.1f}x", "STATUS": " ".join(status), "SCORE": score,
            "VOL_NUM": vol_x
        }
    except: return None

# --- Custom Styling: Highlight ONLY if Score >= 9 ---
def highlight_priority(row):
    score = int(row['SCORE'])
    day_chg = float(row['DAY%'])
    if score >= 9:
        if day_chg >= 0: return ['background-color: #e6fffa; color: #008000; font-weight: 900'] * len(row)
        else: return ['background-color: #fff5f5; color: #FF0000; font-weight: 900'] * len(row)
    return ['background-color: white; color: black; font-weight: 700'] * len(row)

def style_move_col(val):
    try:
        v = float(val)
        color, text = ('#d4edda', '#155724') if v >= 0 else ('#f8d7da', '#721c24')
        return f'background-color: {color}; color: {text}; font-weight: bold'
    except: return ''

def style_sector_ranks(val):
    if not isinstance(val, float): return ''
    color, text = ('#d4edda', '#155724') if val >= 0 else ('#f8d7da', '#721c24')
    return f'background-color: {color}; color: {text}; font-weight: bold'

# --- 5. EXECUTION ---
with st.spinner("Fetching Market Data..."):
    data = get_data()

if data is not None and not data.empty:
    
    # 1. DASHBOARD SECTION (Full width)
    st.markdown("#### 📉 DASHBOARD")
    m_cols = st.columns(5) # Keeping this so metrics stay in one line
    nifty_chg = 0.0
    
    for idx, (ticker, name) in enumerate(INDICES.items()):
        try:
            if ticker in data.columns.levels[0]:
                df = data[ticker].dropna()
                if not df.empty:
                    ltp = float(df['Close'].iloc[-1])
                    pct = ((ltp - float(df['Close'].iloc[-2])) / float(df['Close'].iloc[-2])) * 100
                    m_cols[idx].metric(f"{name}", f"{ltp:.0f}", f"{pct:.1f}%{'🟢' if pct >= 0 else '🔴'}")
                    
                    if name == "NIFTY":
                        o_now = float(df['Open'].iloc[-1])
                        nifty_chg = ((ltp - o_now) / o_now) * 100
        except: continue
        
    if nifty_chg >= 0:
        market_trend = "BULLISH 🚀"
        bg_color, text_color = "#e6fffa", "#008000"
    else:
        market_trend = "BEARISH 🩸"
        bg_color, text_color = "#fff5f5", "#FF0000"
        
    st.markdown(f"""
    <div style='text-align: center; padding: 15px 10px; margin-top: 15px; border-radius: 8px; border: 2px solid {text_color};
                background-color: {bg_color}; color: {text_color}; font-size: 20px; font-weight: 900; box-shadow: 2px 2px 5px rgba(0,0,0,0.1);'>
        {market_trend}
    </div>
    """, unsafe_allow_html=True)
    
    st.divider()

    # 2. SECTOR RANKS SECTION (Full width, right below Dashboard)
    st.markdown("#### 📋 SECTOR RANKS")
    sec_rows = []
    for name, info in SECTOR_MAP.items():
        try:
            if info['index'] in data.columns.levels[0] and not data[info['index']].dropna().empty:
                df = data[info['index']].dropna()
                c_now, c_prev, o_now = float(df['Close'].iloc[-1]), float(df['Close'].iloc[-2]), float(df['Open'].iloc[-1])
                d_pct, n_pct = ((c_now - o_now) / o_now) * 100, ((c_now - c_prev) / c_prev) * 100
                sec_rows.append({"SECTOR": name, "DAY%": d_pct, "NET%": n_pct, "MOVE": n_pct - d_pct})
            else:
                stocks = info['stocks'][:3]
                d_sum, n_sum, count = 0, 0, 0
                for s in stocks:
                    if s in data.columns.levels[0]:
                        sdf = data[s].dropna()
                        if not sdf.empty and len(sdf) > 1:
                            sc_now, sc_prev, so_now = float(sdf['Close'].iloc[-1]), float(sdf['Close'].iloc[-2]), float(sdf['Open'].iloc[-1])
                            d_sum += ((sc_now - so_now) / so_now) * 100
                            n_sum += ((sc_now - sc_prev) / sc_prev) * 100
                            count += 1
                if count > 0: sec_rows.append({"SECTOR": name, "DAY%": d_sum/count, "NET%": n_sum/count, "MOVE": (n_sum/count)-(d_sum/count)})
        except: continue
    
    if sec_rows:
        df_sec = pd.DataFrame(sec_rows).sort_values("DAY%", ascending=False)
        df_sec.set_index("SECTOR", inplace=True)
        st.dataframe(df_sec.T.style.map(style_sector_ranks).format("{:.2f}"), use_container_width=True)
        top_sec, bot_sec = df_sec.index[0], df_sec.index[-1]
    else: df_sec = pd.DataFrame()

    st.divider()
    
    if not df_sec.empty:
        # 3. BUY SECTION (Full width)
        st.markdown(f"<div class='bull-head'>🚀 BUY: {top_sec}</div>", unsafe_allow_html=True)
        res = [analyze(s, data, True) for s in SECTOR_MAP[top_sec]['stocks']]
        res = [x for x in res if x]
        if res: 
            df_to_show = pd.DataFrame(res).sort_values(by=["SCORE", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"]).head(10)
            st.dataframe(df_to_show.style.apply(highlight_priority, axis=1).map(style_move_col, subset=['MOVE']), use_container_width=True, hide_index=True)
        else: st.info("No Signals")
        
        st.divider()

        # 4. SELL SECTION (Full width)
        st.markdown(f"<div class='bear-head'>🩸 SELL: {bot_sec}</div>", unsafe_allow_html=True)
        res = [analyze(s, data, False) for s in SECTOR_MAP[bot_sec]['stocks']]
        res = [x for x in res if x]
        if res: 
            df_to_show = pd.DataFrame(res).sort_values(by=["SCORE", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"]).head(10)
            st.dataframe(df_to_show.style.apply(highlight_priority, axis=1).map(style_move_col, subset=['MOVE']), use_container_width=True, hide_index=True)
        else: st.info("No Signals")
        
    st.divider()
    
    # 5. INDEPENDENT SECTION (Full width)
    st.markdown("#### 🌟 INDEPENDENT (Top 8)")
    ind_movers = [analyze(s, data, force=True) for name, info in SECTOR_MAP.items() if name not in [top_sec, bot_sec] for s in info['stocks']]
    ind_movers = [r for r in ind_movers if r and (float(r['VOL'][:-1]) >= 1.0 or r['SCORE'] >= 1)]
    if ind_movers: 
        df_to_show = pd.DataFrame(ind_movers).sort_values(by=["SCORE", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"]).head(8)
        st.dataframe(df_to_show.style.apply(highlight_priority, axis=1).map(style_move_col, subset=['MOVE']), use_container_width=True, hide_index=True)
    else: st.info("No movers")
    
    st.divider()

    # 6. BROADER MARKET SECTION (Full width)
    st.markdown("#### 🌌 BROADER MARKET (Top 8)")
    res = [analyze(s, data, force=True) for s in BROADER_MARKET]
    res = [x for x in res if x and (float(x['VOL'][:-1]) >= 1.0 or x['SCORE'] >= 1)]
    if res: 
        df_to_show = pd.DataFrame(res).sort_values(by=["SCORE", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"]).head(8)
        st.dataframe(df_to_show.style.apply(highlight_priority, axis=1).map(style_move_col, subset=['MOVE']), use_container_width=True, hide_index=True)
    else: st.info("No signals")

else:
    st.write("Trying to fetch data...")
