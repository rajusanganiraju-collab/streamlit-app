import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Terminal", page_icon="📈", layout="wide")

# --- 2. AUTO RUN (1 MINUTE) ---
st_autorefresh(interval=60000, key="datarefresh")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    button[title="View fullscreen"] {visibility: hidden;}
    [data-testid="stStatusWidget"] {display: none;}
    
    .stApp { background-color: #ffffff; color: #000000; }
    html, body, [class*="css"] { font-family: 'Arial', sans-serif; font-weight: 600; color: #000000 !important; }
    .block-container { padding: 1rem; }
    
    /* Table Styling - Centered */
    th { background-color: #222222 !important; color: white !important; font-size: 13px !important; text-align: center !important; }
    td { font-size: 13px !important; color: #000000 !important; border-bottom: 1px solid #ddd; text-align: center !important; }
    
    h4 { margin: 15px 0px; font-size: 14px; text-transform: uppercase; border-bottom: 2px solid #333; padding-bottom: 5px; color: #000000 !important; }
    .bull-head { background: #d4edda; color: #155724; padding: 8px; font-weight: bold; border: 1px solid #c3e6cb; margin-top: 10px; }
    .bear-head { background: #f8d7da; color: #721c24; padding: 8px; font-weight: bold; border: 1px solid #f5c6cb; margin-top: 10px; }
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

@st.cache_data(ttl=60)
def get_data():
    all_tickers = list(INDICES.keys()) + list(BROADER_MARKET)
    for s in SECTOR_MAP.values():
        all_tickers.append(s['index'])
        all_tickers.extend(s['stocks'])
    all_tickers = list(set(all_tickers))
    
    try:
        data = yf.download(all_tickers, period="5d", progress=False, group_by='ticker', threads=False)
        return data
    except: 
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
        
        is_open_low = abs(open_p - low) <= (ltp * 0.003)
        is_open_high = abs(open_p - high) <= (ltp * 0.003)
        
        if day_chg >= 2.0: status.append("BigMove🚀"); score += 3
        elif day_chg <= -2.0: status.append("BigMove🩸"); score += 3

        if check_bullish:
            if is_open_low: status.append("O=L🔥"); score += 3
            if vol_x > 1.0: status.append("VOL🟢"); score += 3
            if ltp >= high * 0.998 and day_chg > 0.5: status.append("HB🚀"); score += 1
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

# --- Custom Styling ---
def highlight_priority(row):
    score = int(row['SCORE'])
    day_chg = float(row['DAY%'])
    if score >= 9:
        if day_chg >= 0: return ['background-color: #e6fffa; color: #008000; font-weight: 900'] * len(row)
        else: return ['background-color: #fff5f5; color: #FF0000; font-weight: 900'] * len(row)
    return ['background-color: white; color: black'] * len(row)

def style_move_col(val):
    try:
        v = float(val)
        color, text = ('#d4edda', '#155724') if v >= 0 else ('#f8d7da', '#721c24')
        return f'background-color: {color}; color: {text}; font-weight: bold;'
    except: return ''

def style_sector_ranks(val):
    if not isinstance(val, float): return ''
    color, text = ('#d4edda', '#155724') if val >= 0 else ('#f8d7da', '#721c24')
    return f'background-color: {color}; color: {text};'

# --- 5. EXECUTION ---
loading_msg = st.empty()
loading_msg.info("మార్కెట్ డేటా లోడ్ అవుతోంది... దయచేసి 15 సెకన్లు వేచి ఉండండి ⏳")

data = get_data()
loading_msg.empty()

if data is not None and not data.empty:
    # 1. DASHBOARD
    st.markdown("#### 📉 DASHBOARD")
    m_cols = st.columns(5) # 5 కాలమ్స్ ఒకే లైన్‌లో వస్తాయి
    nifty_chg = 0.0
    for idx, (ticker, name) in enumerate(INDICES.items()):
        try:
            if ticker in data.columns.levels[0]:
                df = data[ticker].dropna()
                ltp = float(df['Close'].iloc[-1])
                pct = ((ltp - float(df['Close'].iloc[-2])) / float(df['Close'].iloc[-2])) * 100
                
                # Custom HTML Block (టెక్స్ట్ ఎప్పుడూ నలుపు రంగులో సెంటర్‌లోనే ఉంటుంది)
                arrow = "↑" if pct >= 0 else "↓"
                txt_color = "#008000" if pct >= 0 else "#FF0000"
                m_cols[idx].markdown(f'''
                <div style="text-align: center; padding: 5px; border: 1px solid #ddd; border-radius: 8px; background-color: #f9f9f9;">
                    <div style="color: black; font-size: 13px; font-weight: 800;">{name}</div>
                    <div style="color: black; font-size: 18px; font-weight: 900; margin: 4px 0px;">{ltp:.0f}</div>
                    <div style="color: {txt_color}; font-size: 13px; font-weight: bold;">{arrow} {pct:.1f}%</div>
                </div>
                ''', unsafe_allow_html=True)
                
                if name == "NIFTY":
                    o_now = float(df['Open'].iloc[-1])
                    nifty_chg = ((ltp - o_now) / o_now) * 100
        except: continue
        
    # --- BULLISH / BEARISH INDICATOR (Added back) ---
    if nifty_chg >= 0:
        market_trend = "BULLISH 🚀"
        bg_color, text_color = "#e6fffa", "#008000"
    else:
        market_trend = "BEARISH 🩸"
        bg_color, text_color = "#fff5f5", "#FF0000"
        
    st.markdown(f"""
    <div style='text-align: center; padding: 10px; margin-top: 15px; border-radius: 8px; border: 2px solid {text_color};
                background-color: {bg_color}; color: {text_color}; font-size: 18px; font-weight: 900; box-shadow: 2px 2px 5px rgba(0,0,0,0.1);'>
        {market_trend}
    </div>
    """, unsafe_allow_html=True)
    
    # 2. SECTOR RANKS
    st.markdown("#### 📋 SECTOR RANKS")
    sec_rows = []
    for name, info in SECTOR_MAP.items():
        try:
            if info['index'] in data.columns.levels[0]:
                df = data[info['index']].dropna()
                c_now, c_prev, o_now = float(df['Close'].iloc[-1]), float(df['Close'].iloc[-2]), float(df['Open'].iloc[-1])
                d_pct, n_pct = ((c_now - o_now) / o_now) * 100, ((c_now - c_prev) / c_prev) * 100
                sec_rows.append({"SECTOR": name, "DAY%": d_pct, "NET%": n_pct, "MOVE": n_pct - d_pct})
        except: continue
    
    if sec_rows:
        df_sec = pd.DataFrame(sec_rows).sort_values("DAY%", ascending=False)
        df_sec_t = df_sec.set_index("SECTOR").T
        
        # Sector Rankings ని ఖచ్చితంగా సెంటర్‌కి అలైన్ చేయడం
        styled_sec = df_sec_t.style.format("{:.2f}") \
            .map(style_sector_ranks) \
            .set_properties(**{'text-align': 'center', 'font-weight': '600'}) \
            .set_table_styles([
                {'selector': 'th', 'props': [('text-align', 'center')]},
                {'selector': 'td', 'props': [('text-align', 'center')]}
            ])
            
        st.dataframe(styled_sec, use_container_width=True)
        top_sec = df_sec.iloc[0]['SECTOR']
        bot_sec = df_sec.iloc[-1]['SECTOR']

    st.divider()

    # 3. BUY & SELL TABLES (Score Centered)
    st.markdown(f"<div class='bull-head'>🚀 BUY: {top_sec}</div>", unsafe_allow_html=True)
    res_b = [analyze(s, data, True) for s in SECTOR_MAP[top_sec]['stocks']]
    res_b = [x for x in res_b if x]
    if res_b:
        df_b = pd.DataFrame(res_b).sort_values(by=["SCORE", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"])
        df_b['SCORE'] = df_b['SCORE'].astype(str) # నంబర్‌కి బదులు స్ట్రింగ్‌గా మార్చి సెంటర్ చేస్తున్నాం
        
        styled_b = df_b.style.apply(highlight_priority, axis=1) \
            .map(style_move_col, subset=['MOVE']) \
            .set_properties(**{'text-align': 'center'}) # ప్రతి కాలమ్‌ని సెంటర్ చేయడం
            
        st.dataframe(styled_b, use_container_width=True, hide_index=True)

    st.markdown(f"<div class='bear-head'>🩸 SELL: {bot_sec}</div>", unsafe_allow_html=True)
    res_s = [analyze(s, data, False) for s in SECTOR_MAP[bot_sec]['stocks']]
    res_s = [x for x in res_s if x]
    if res_s:
        df_s = pd.DataFrame(res_s).sort_values(by=["SCORE", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"])
        df_s['SCORE'] = df_s['SCORE'].astype(str)
        
        styled_s = df_s.style.apply(highlight_priority, axis=1) \
            .map(style_move_col, subset=['MOVE']) \
            .set_properties(**{'text-align': 'center'})
            
        st.dataframe(styled_s, use_container_width=True, hide_index=True)

    st.divider()

    # 4. INDEPENDENT & BROADER (Score Centered)
    st.markdown("#### 🌟 INDEPENDENT (Top 8)")
    ind_movers = [analyze(s, data, force=True) for name, info in SECTOR_MAP.items() if name not in [top_sec, bot_sec] for s in info['stocks']]
    ind_movers = [r for r in ind_movers if r and (float(r['VOL'][:-1]) >= 1.0 or r['SCORE'] >= 1)]
    if ind_movers:
        df_ind = pd.DataFrame(ind_movers).sort_values(by=["SCORE", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"]).head(8)
        df_ind['SCORE'] = df_ind['SCORE'].astype(str)
        
        styled_ind = df_ind.style.apply(highlight_priority, axis=1) \
            .map(style_move_col, subset=['MOVE']) \
            .set_properties(**{'text-align': 'center'})
            
        st.dataframe(styled_ind, use_container_width=True, hide_index=True)

    st.markdown("#### 🌌 BROADER MARKET (Top 8)")
    res_brd = [analyze(s, data, force=True) for s in BROADER_MARKET]
    res_brd = [x for x in res_brd if x and (float(x['VOL'][:-1]) >= 1.0 or x['SCORE'] >= 1)]
    if res_brd:
        df_brd = pd.DataFrame(res_brd).sort_values(by=["SCORE", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"]).head(8)
        df_brd['SCORE'] = df_brd['SCORE'].astype(str)
        
        styled_brd = df_brd.style.apply(highlight_priority, axis=1) \
            .map(style_move_col, subset=['MOVE']) \
            .set_properties(**{'text-align': 'center'})
            
        st.dataframe(styled_brd, use_container_width=True, hide_index=True)

else:
    st.warning("స్టాక్ మార్కెట్ డేటా దొరకలేదు. బహుశా ఇంటర్నెట్ లేదా Yahoo Finance సర్వర్ నెమ్మదిగా ఉండి ఉండొచ్చు.")
