import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Terminal", page_icon="🎯", layout="wide")

# --- 2. AUTO RUN (1 MINUTE) ---
st_autorefresh(interval=60000, key="datarefresh")

# CSS 
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {display: none !important;}
    .stApp { background-color: #ffffff; color: #000000; }
    html, body, [class*="css"] { font-family: 'Arial', sans-serif; font-weight: 600; color: #000000 !important; }
    .block-container { padding-top: 0.5rem !important; padding-bottom: 0rem !important; padding-left: 0.1rem !important; padding-right: 0.1rem !important; margin-top: -10px; }
    th { background-color: #ffffff !important; color: #000000 !important; font-size: 12px !important; text-align: center !important; border-bottom: 2px solid #222222 !important; border-top: 2px solid #222222 !important; padding: 4px 1px !important; }
    td { font-size: 12px !important; color: #000000 !important; border-bottom: 1px solid #ccc !important; text-align: center !important; padding: 4px 1px !important; font-weight: 700 !important; }
    .table-head { padding: 6px 10px; font-weight: 900; font-size: 14px; text-transform: uppercase; margin-top: 8px; margin-bottom: 2px; border-radius: 4px; text-align: left; }
    .head-bull { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
    .head-bear { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
    .head-neut { background: #e2e3e5; color: #383d41; border: 1px solid #d6d8db; }
    .head-sniper { background: #fff3cd; color: #856404; border: 1px solid #ffeeba; }
    div[data-testid="stDataFrame"] { margin-bottom: -15px !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. DATA CONFIGURATION ---
def format_ticker(t):
    t = t.upper().strip()
    if not t.startswith("^") and not t.endswith(".NS"):
        return f"{t}.NS"
    return t

INDICES = {"^NSEI": "NIFTY", "^NSEBANK": "BNKNFY", "^INDIAVIX": "VIX", "^DJI": "DOW", "^IXIC": "NSDQ"}
TV_INDICES = {"^NSEI": "NSE:NIFTY", "^NSEBANK": "NSE:BANKNIFTY", "^INDIAVIX": "NSE:INDIAVIX", "^DJI": "TVC:DJI", "^IXIC": "NASDAQ:IXIC"}

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
    "HAL", "BEL", "BDL", "MAZDOCK", "COCHINSHIP", "GRSE", "RVNL", "IRFC", "IRCON", "TITAGARH", "RAILTEL", "RITES",
    "ADANIPOWER", "ADANIGREEN", "NHPC", "SJVN", "BHEL", "CGPOWER", "SUZLON", "PFC", "RECLTD", "IREDA", "IOB", "UCOBANK", "MAHABANK", "CANBK",
    "BAJFINANCE", "CHOLAFIN", "JIOFIN", "MUTHOOTFIN", "MANAPPURAM", "SHRIRAMFIN", "M&MFIN", "DIXON", "POLYCAB", "KAYNES", "HAVELLS", "KEI", "RRKABEL",
    "SRF", "TATACHEM", "DEEPAKNTR", "AARTIIND", "PIIND", "FACT", "UPL", "ULTRACEMCO", "AMBUJACEM", "SHREECEM", "DALBHARAT", "LT", "CUMMINSIND", "ABB", "SIEMENS",
    "BHARTIARTL", "IDEA", "INDIGO", "ZOMATO", "TRENT", "DMART", "PAYTM", "ZENTEC", "ADANIENT", "ADANIPORTS", "ATGL", "AWL",
    "BOSCHLTD", "MRF", "MOTHERSON", "SONACOMS", "EXIDEIND", "AMARAJABAT"
]

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

@st.cache_data(ttl=60)
def get_data():
    all_tickers = list(INDICES.keys()) + list(BROADER_MARKET)
    for s in SECTOR_MAP.values():
        all_tickers.append(s['index']); all_tickers.extend(s['stocks'])
    all_tickers = list(set(all_tickers))
    try:
        data = yf.download(all_tickers, period="5d", interval="5m", progress=False, group_by='ticker', threads=False)
        return data, all_tickers
    except: return None, all_tickers

def analyze(symbol, full_data, check_bullish=True, force=False):
    try:
        if isinstance(full_data.columns, pd.MultiIndex):
            if symbol not in full_data.columns.levels[0]: return None
            df = full_data[symbol].copy().dropna()
        else:
            df = full_data.copy().dropna()
            
        if len(df) < 10: return None 
        df['EMA10'] = df['Close'].ewm(span=10, adjust=False).mean()
        df['Date'] = df.index.date
        current_date = df['Date'].iloc[-1]
        today_data = df[df['Date'] == current_date].copy()
        prev_data = df[df['Date'] < current_date]
        
        if len(today_data) == 0 or len(prev_data) == 0: return None
        ltp = float(today_data['Close'].iloc[-1])
        open_p = float(today_data['Open'].iloc[0]) 
        prev_c = float(prev_data['Close'].iloc[-1]) 
        
        day_chg = ((ltp - open_p) / open_p) * 100
        net_chg = ((ltp - prev_c) / prev_c) * 100
        todays_move = net_chg - day_chg
        
        # VWAP CALCULATION
        today_data['TP'] = (today_data['High'] + today_data['Low'] + today_data['Close']) / 3
        today_data['CVP'] = (today_data['TP'] * today_data['Volume']).cumsum()
        today_data['CV'] = today_data['Volume'].cumsum()
        today_data['VWAP'] = today_data['CVP'] / today_data['CV']

        curr_close = ltp
        curr_vwap = today_data['VWAP'].iloc[-1]
        is_bullish_trend = curr_close > curr_vwap
        
        if not force:
            if check_bullish and not is_bullish_trend: return None
            if not check_bullish and is_bullish_trend: return None

        # ⚡ TREND-SPECIFIC CANDLE COUNTING (The Fix)
        # ఇక్కడ ఆపోజిట్ సైడ్ క్యాండిల్స్ ని అస్సలు లెక్కించదు.
        if is_bullish_trend:
            today_data['Valid'] = (today_data['Close'] > today_data['VWAP']) & (today_data['Close'] > today_data['EMA10'])
        else:
            today_data['Valid'] = (today_data['Close'] < today_data['VWAP']) & (today_data['Close'] < today_data['EMA10'])

        valid_candles = int(today_data['Valid'].sum())
        score = valid_candles 

        # KILL SWITCH
        closes = today_data['Close'].values; vwaps = today_data['VWAP'].values
        streak = 0
        for i in range(len(closes)-1, -1, -1):
            if (is_bullish_trend and closes[i] > vwaps[i]) or (not is_bullish_trend and closes[i] < vwaps[i]): streak += 1
            else: break
        if streak < 3: return None
            
        first_c = today_data['Close'].iloc[0]; first_v = today_data['VWAP'].iloc[0]
        tag = "VWAP-Trap" if (is_bullish_trend and first_c < first_v) or (not is_bullish_trend and first_c > first_v) else "VWAP-Pure"

        time_str = f"{ (valid_candles*5)//60 }h { (valid_candles*5)%60 }m" if (valid_candles*5) >= 60 else f"{valid_candles*5}m"
        status_text = f"{'🚀' if is_bullish_trend else '🩸'} {tag} ({time_str})"
        
        stock_name = symbol.replace(".NS", "")
        return {
            "STOCK": f"https://in.tradingview.com/chart/?symbol=NSE:{stock_name}", "LTP": f"{ltp:.2f}", "D%": f"{day_chg:.2f}",
            "N%": f"{net_chg:.2f}", "M%": f"{todays_move:.2f}", "STAT": status_text, "SCORE": int(score), "TREND": "BULL" if is_bullish_trend else "BEAR"
        }
    except: return None

def highlight_priority(row):
    try:
        day_chg = float(row['D%'])
        if "VWAP" in str(row['STAT']):
            return ['background-color: #e6fffa; color: #008000; font-weight: 900'] * len(row) if day_chg >= 0 else ['background-color: #fff5f5; color: #FF0000; font-weight: 900'] * len(row)
    except: pass
    return ['background-color: white; color: black'] * len(row)

def style_move_col(val):
    try:
        v = float(val)
        return f'background-color: {"#d4edda" if v>=0 else "#f8d7da"}; color: {"#155724" if v>=0 else "#721c24"}; font-weight: 800;'
    except: return ''

def create_sorted_df(res_list, limit=15):
    res_list = [x for x in res_list if x]
    if not res_list: return pd.DataFrame()
    df = pd.DataFrame(res_list)
    df['ABS_D'] = df['D%'].astype(float).abs()
    return df.sort_values(by=["SCORE", "ABS_D"], ascending=[False, False]).drop(columns=["ABS_D"]).head(limit)

# --- 5. EXECUTION ---
loading_msg = st.empty(); loading_msg.info("🎯 Trend-Specific Engine (VWAP + 10 EMA) లోడ్ అవుతోంది... ⏳")
data, all_tickers = get_data(); loading_msg.empty()

if data is not None and not data.empty:
    dash_left, dash_right = st.columns([0.8, 0.2]) 
    with dash_left:
        dash_html = '<div style="display: flex; justify-content: space-between; align-items: center; border: 2px solid #ddd; border-radius: 8px; background-color: #f9f9f9; padding: 5px; height: 80px;">'
        for ticker, name in INDICES.items():
            try:
                if ticker in data.columns.levels[0]:
                    today = data[ticker].dropna(); ltp = today['Close'].iloc[-1]; op = today['Open'].iloc[0]; pct = ((ltp-op)/op)*100
                    dash_html += f'<div style="flex: 1; text-align: center;"><div style="color: #444; font-size: 13px; font-weight: 800;">{name}</div><div style="color: black; font-size: 18px; font-weight: 900;">{ltp:.0f}</div><div style="color: {"#008000" if pct>=0 else "#FF0000"}; font-size: 14px; font-weight: bold;">{"↑" if pct>=0 else "↓"} {pct:.1f}%</div></div>'
            except: pass
        dash_html += "</div>"; st.markdown(dash_html, unsafe_allow_html=True)

    sec_rows = []
    for name, info in SECTOR_MAP.items():
        try:
            if info['index'] in data.columns.levels[0]:
                d = data[info['index']].dropna(); ltp = d['Close'].iloc[-1]; op = d['Open'].iloc[0]; d_pct = ((ltp-op)/op)*100
                sec_rows.append({"SECTOR": name, "D%": d_pct})
        except: pass
    df_sec = pd.DataFrame(sec_rows).sort_values("D%", ascending=False) if sec_rows else pd.DataFrame()
    top_sec = df_sec.iloc[0]['SECTOR'] if not df_sec.empty else ""; bot_sec = df_sec.iloc[-1]['SECTOR'] if not df_sec.empty else ""

    df_b = create_sorted_df([analyze(s, data, True) for s in SECTOR_MAP.get(top_sec, {}).get('stocks', [])], 15)
    df_s = create_sorted_df([analyze(s, data, False) for s in SECTOR_MAP.get(bot_sec, {}).get('stocks', [])], 15)
    df_ind = create_sorted_df([analyze(s, data, force=True) for n, i in SECTOR_MAP.items() if n not in [top_sec, bot_sec] for s in i['stocks']], 15)
    df_brd = create_sorted_df([analyze(s, data, force=True) for s in BROADER_MARKET], 15)

    with dash_right:
        st.markdown(f"<div style='height: 80px; border-radius: 8px; border: 2px solid #000; display: flex; align-items: center; justify-content: center; font-size: 18px; font-weight: 900;'>MARKET TRACKER</div>", unsafe_allow_html=True)
    
    # SNIPER SEARCH
    st.markdown("<hr style='margin: 10px 0px;'>", unsafe_allow_html=True)
    sn_ticker = st.text_input("🎯 SNIPER SEARCH (Type symbol like BAJFINANCE):")
    if sn_ticker:
        s_sym = format_ticker(sn_ticker); s_obj = yf.Ticker(s_sym); s_data = s_obj.history(period="5d", interval="5m")
        if not s_data.empty:
            res = analyze(s_sym, s_data, force=True)
            if res:
                st.dataframe(pd.DataFrame([res]).rename(columns={"SCORE": "CANDLES"}), use_container_width=True, hide_index=True)
            else: st.warning("Trend not found or VWAP broken.")

    tv_cfg = {"STOCK": st.column_config.LinkColumn("STOCK", display_text=r".*NSE:(.*)"), "STAT": st.column_config.TextColumn("STAT", width="medium"), "SCORE": st.column_config.TextColumn("CANDLES", width="small")}

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"<div class='table-head head-bull'>🚀 BUY: {top_sec}</div>", unsafe_allow_html=True)
        if not df_b.empty: st.dataframe(df_b.rename(columns={"SCORE": "CANDLES"}).style.apply(highlight_priority, axis=1).map(style_move_col, subset=['M%']), column_config=tv_cfg, use_container_width=True, hide_index=True, height=350)
    with c2:
        st.markdown(f"<div class='table-head head-bear'>🩸 SELL: {bot_sec}</div>", unsafe_allow_html=True)
        if not df_s.empty: st.dataframe(df_s.rename(columns={"SCORE": "CANDLES"}).style.apply(highlight_priority, axis=1).map(style_move_col, subset=['M%']), column_config=tv_cfg, use_container_width=True, hide_index=True, height=350)

    c3, c4 = st.columns(2)
    with c3:
        st.markdown("<div class='table-head head-neut'>🌟 INDEPENDENT</div>", unsafe_allow_html=True)
        if not df_ind.empty: st.dataframe(df_ind.rename(columns={"SCORE": "CANDLES"}).style.apply(highlight_priority, axis=1).map(style_move_col, subset=['M%']), column_config=tv_cfg, use_container_width=True, hide_index=True, height=580)
    with c4:
        st.markdown("<div class='table-head head-neut'>🌌 BROADER MARKET</div>", unsafe_allow_html=True)
        if not df_brd.empty: st.dataframe(df_brd.rename(columns={"SCORE": "CANDLES"}).style.apply(highlight_priority, axis=1).map(style_move_col, subset=['M%']), column_config=tv_cfg, use_container_width=True, hide_index=True, height=580)
else:
    st.warning("Data not found. Check connection.")
