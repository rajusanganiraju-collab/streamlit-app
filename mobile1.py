import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Terminal", page_icon="📈", layout="wide")

# --- 2. AUTO RUN (1 MINUTE) ---
st_autorefresh(interval=60000, key="datarefresh")

# --- CSS FOR RESPONSIVE TABLES ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {display: none !important;}
    
    .stApp { background-color: #ffffff; color: #000000; }
    html, body, [class*="css"] { font-family: 'Arial', sans-serif; font-weight: 600; color: #000000 !important; }
    
    /* Top Space Reduction */
    .block-container { padding-top: 0.5rem !important; padding-bottom: 0rem !important; padding-left: 0.5rem !important; padding-right: 0.5rem !important; margin-top: -10px; }
    
    /* Table Default Styling */
    th { background-color: #ffffff !important; color: #000000 !important; font-size: 14px !important; text-align: center !important; border-bottom: 2px solid #222222 !important; border-top: 2px solid #222222 !important; padding: 6px !important; }
    td { font-size: 14px !important; color: #000000 !important; border-bottom: 1px solid #ccc !important; text-align: center !important; padding: 4px !important; font-weight: 700 !important; }
    table { width: 100% !important; }
    div[data-testid="stDataFrame"] { margin-bottom: -15px !important; width: 100% !important; }
    
    /* UNIFIED TABLE HEADINGS */
    .table-head { padding: 6px 10px; font-weight: 900; font-size: 15px; text-transform: uppercase; margin-top: 8px; margin-bottom: 2px; border-radius: 4px; text-align: left; }
    .head-bull { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
    .head-bear { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
    .head-neut { background: #e2e3e5; color: #383d41; border: 1px solid #d6d8db; }
    
    /* ---------------------------------------------------- */
    /* RESPONSIVE DESIGN (Desktop Split Screen vs Mobile)   */
    /* ---------------------------------------------------- */
    
    /* 1. Desktop & Tablet (Screen > 550px) - FORCE SIDE-BY-SIDE */
    @media screen and (min-width: 551px) {
        div[data-testid="stHorizontalBlock"] {
            flex-direction: row !important;
            flex-wrap: nowrap !important; /* Forces columns to stay side-by-side */
        }
        div[data-testid="column"] {
            min-width: 0 !important; /* Allows columns to shrink so they fit inside screen */
        }
    }

    /* 2. Desktop Split Screen (551px to 1200px) - SHRINK FONTS TO FIT ALL COLUMNS */
    @media screen and (min-width: 551px) and (max-width: 1200px) {
        th, td { font-size: 11px !important; padding: 3px 1px !important; }
        .table-head { font-size: 13px !important; padding: 5px !important; }
    }

    /* 3. Mobile Phones (Screen < 550px) - FORCE STACKED (ONE BELOW OTHER) */
    @media screen and (max-width: 550px) {
        div[data-testid="stHorizontalBlock"] {
            flex-direction: column !important; /* Forces columns one below the other */
        }
        div[data-testid="column"] {
            width: 100% !important;
            max-width: 100% !important;
            margin-bottom: 15px !important;
        }
        th, td { font-size: 12px !important; padding: 3px !important; }
    }
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

TV_INDICES = {
    "^NSEI": "NSE:NIFTY",
    "^NSEBANK": "NSE:BANKNIFTY",
    "^INDIAVIX": "NSE:INDIAVIX",
    "^DJI": "TVC:DJI",
    "^IXIC": "NASDAQ:IXIC"
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
        
        stock_name = symbol.replace(".NS", "")
        tv_url = f"https://in.tradingview.com/chart/?symbol=NSE:{stock_name}"
        
        return {
            "STOCK": tv_url, "PRICE": f"{ltp:.2f}", "DAY%": f"{day_chg:.2f}",
            "NET%": f"{net_chg:.2f}", "MOVE": f"{todays_move:.2f}", 
            "VOL": f"{vol_x:.1f}x", "STATUS": " ".join(status), "SCORE": score,
            "VOL_NUM": vol_x
        }
    except: return None

# --- Custom Styling ---
def highlight_priority(row):
    status_str = str(row['STATUS'])
    day_chg = float(row['DAY%'])
    
    major_conditions = 0
    if "BigMove" in status_str: major_conditions += 1
    if "O=L" in status_str or "O=H" in status_str: major_conditions += 1
    if "VOL" in status_str: major_conditions += 1
    
    if major_conditions >= 2:
        if day_chg >= 0: return ['background-color: #e6fffa; color: #008000; font-weight: 900'] * len(row)
        else: return ['background-color: #fff5f5; color: #FF0000; font-weight: 900'] * len(row)
        
    return ['background-color: white; color: black'] * len(row)

def style_move_col(val):
    try:
        v = float(val)
        color, text = ('#d4edda', '#155724') if v >= 0 else ('#f8d7da', '#721c24')
        return f'background-color: {color}; color: {text}; font-weight: 800;'
    except: return ''

def style_sector_ranks(val):
    if not isinstance(val, float): return ''
    color, text = ('#d4edda', '#155724') if val >= 0 else ('#f8d7da', '#721c24')
    return f'background-color: {color}; color: {text}; font-weight: 700;'

tv_link_config = {"STOCK": st.column_config.LinkColumn("STOCK", display_text=r".*NSE:(.*)")}

# -------------------------------------------------------------
# 5. SEARCH BAR FEATURE
# -------------------------------------------------------------
search_query = st.text_input("🔍 సెర్చ్ స్టాక్ (ఉదాహరణకు: RELIANCE, ZOMATO, IDEA):", "").strip().upper()

if search_query:
    search_symbol = format_ticker(search_query)
    try:
        search_data = yf.download([search_symbol, "^NSEI"], period="5d", progress=False, group_by='ticker', threads=False)
        search_res = analyze(search_symbol, search_data, force=True)
        
        if search_res:
            st.markdown(f"<div class='table-head head-neut'>🎯 SEARCH RESULT: {search_query}</div>", unsafe_allow_html=True)
            df_search = pd.DataFrame([search_res])
            if "VOL_NUM" in df_search.columns:
                df_search = df_search.drop(columns=["VOL_NUM"])
            df_search['SCORE'] = df_search['SCORE'].astype(str)
            
            styled_search = df_search.style.apply(highlight_priority, axis=1) \
                .map(style_move_col, subset=['MOVE']) \
                .set_properties(**{'text-align': 'center', 'font-size': '14px'}) \
                .set_table_styles([{'selector': 'th', 'props': [('background-color', 'white'), ('color', 'black'), ('font-size', '14px')]}])
            
            st.dataframe(styled_search, column_config=tv_link_config, use_container_width=True, hide_index=True)
        else:
            st.warning(f"'{search_query}' కి సంబంధించి ఎటువంటి బ్రేక్అవుట్/కండిషన్స్ మ్యాచ్ అవ్వలేదు లేదా డేటా దొరకలేదు.")
    except Exception as e:
        st.error("డేటా పొందడంలో లోపం జరిగింది. దయచేసి సరైన సింబల్ ఇవ్వండి.")

st.markdown("<hr style='margin-top: 5px; margin-bottom: 10px;'>", unsafe_allow_html=True)

# -------------------------------------------------------------
# 6. FETCH ALL DATA & DASHBOARD
# -------------------------------------------------------------
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

loading_msg = st.empty()
loading_msg.info("మార్కెట్ డేటా లోడ్ అవుతోంది... దయచేసి 15 సెకన్లు వేచి ఉండండి ⏳")

data = get_data()
loading_msg.empty()

if data is not None and not data.empty:
    
    # DASHBOARD
    dash_left, dash_right = st.columns([0.8, 0.2]) 
    nifty_chg = 0.0
    
    with dash_left:
        dash_html = '<div style="display: flex; justify-content: space-between; align-items: center; border: 2px solid #ddd; border-radius: 8px; background-color: #f9f9f9; padding: 5px; height: 80px;">'
        for idx, (ticker, name) in enumerate(INDICES.items()):
            try:
                if ticker in data.columns.levels[0]:
                    df = data[ticker].dropna()
                    ltp = float(df['Close'].iloc[-1])
                    pct = ((ltp - float(df['Close'].iloc[-2])) / float(df['Close'].iloc[-2])) * 100
                    
                    arrow = "↑" if pct >= 0 else "↓"
                    txt_color = "#008000" if pct >= 0 else "#FF0000"
                    tv_symbol = TV_INDICES.get(ticker, "")
                    tv_url = f"https://in.tradingview.com/chart/?symbol={tv_symbol}"
                    border_style = "border-right: 1px solid #ddd;" if idx < 4 else ""
                    
                    dash_html += f'<a href="{tv_url}" target="_blank" style="text-decoration: none; flex: 1; text-align: center; {border_style}"><div style="color: #444; font-size: 13px; font-weight: 800;">{name}</div><div style="color: black; font-size: 18px; font-weight: 900; margin: 2px 0px;">{ltp:.0f}</div><div style="color: {txt_color}; font-size: 14px; font-weight: bold;">{arrow} {pct:.1f}%</div></a>'
                    
                    if name == "NIFTY":
                        o_now = float(df['Open'].iloc[-1])
                        nifty_chg = ((ltp - o_now) / o_now) * 100
            except: continue
        dash_html += "</div>"
        st.markdown(dash_html, unsafe_allow_html=True)

    with dash_right:
        if nifty_chg >= 0:
            market_trend = "BULLISH 🚀"
            trend_bg, trend_txt = "#e6fffa", "#008000"
        else:
            market_trend = "BEARISH 🩸"
            trend_bg, trend_txt = "#fff5f5", "#FF0000"
            
        st.markdown(f"""
        <div style='display: flex; align-items: center; justify-content: center; height: 80px; border-radius: 8px; border: 2px solid {trend_txt}; background-color: {trend_bg}; color: {trend_txt}; font-size: 18px; font-weight: 900; box-shadow: 2px 2px 5px rgba(0,0,0,0.1);'>
            {market_trend}
        </div>
        """, unsafe_allow_html=True)
    
    # SECTOR RANKS
    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
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
        
        styled_sec = df_sec_t.style.format("{:.2f}") \
            .map(style_sector_ranks) \
            .set_properties(**{'text-align': 'center', 'font-size': '14px', 'font-weight': '600'}) \
            .set_table_styles([
                {'selector': 'th', 'props': [('text-align', 'center'), ('background-color', 'white'), ('color', 'black'), ('font-size', '14px')]},
                {'selector': 'td', 'props': [('text-align', 'center')]}
            ])
            
        st.dataframe(styled_sec, use_container_width=True)
        top_sec = df_sec.iloc[0]['SECTOR']
        bot_sec = df_sec.iloc[-1]['SECTOR']

    # BUY & SELL TABLES
    c_buy, c_sell = st.columns(2)
    
    with c_buy:
        st.markdown(f"<div class='table-head head-bull'>🚀 BUY: {top_sec}</div>", unsafe_allow_html=True)
        res_b = [analyze(s, data, True) for s in SECTOR_MAP[top_sec]['stocks']]
        res_b = [x for x in res_b if x]
        if res_b:
            df_b = pd.DataFrame(res_b).sort_values(by=["SCORE", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"])
            df_b['SCORE'] = df_b['SCORE'].astype(str) 
            
            styled_b = df_b.style.apply(highlight_priority, axis=1) \
                .map(style_move_col, subset=['MOVE']) \
                .set_properties(**{'text-align': 'center', 'font-size': '14px'}) \
                .set_table_styles([{'selector': 'th', 'props': [('background-color', 'white'), ('color', 'black'), ('font-size', '14px')]}])
                
            st.dataframe(styled_b, column_config=tv_link_config, use_container_width=True, hide_index=True)

    with c_sell:
        st.markdown(f"<div class='table-head head-bear'>🩸 SELL: {bot_sec}</div>", unsafe_allow_html=True)
        res_s = [analyze(s, data, False) for s in SECTOR_MAP[bot_sec]['stocks']]
        res_s = [x for x in res_s if x]
        if res_s:
            df_s = pd.DataFrame(res_s).sort_values(by=["SCORE", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"])
            df_s['SCORE'] = df_s['SCORE'].astype(str)
            
            styled_s = df_s.style.apply(highlight_priority, axis=1) \
                .map(style_move_col, subset=['MOVE']) \
                .set_properties(**{'text-align': 'center', 'font-size': '14px'}) \
                .set_table_styles([{'selector': 'th', 'props': [('background-color', 'white'), ('color', 'black'), ('font-size', '14px')]}])
                
            st.dataframe(styled_s, column_config=tv_link_config, use_container_width=True, hide_index=True)

    # INDEPENDENT & BROADER
    c_ind, c_brd = st.columns(2)
    
    with c_ind:
        st.markdown("<div class='table-head head-neut'>🌟 INDEPENDENT (Top 8)</div>", unsafe_allow_html=True)
        ind_movers = [analyze(s, data, force=True) for name, info in SECTOR_MAP.items() if name not in [top_sec, bot_sec] for s in info['stocks']]
        ind_movers = [r for r in ind_movers if r and (float(r['VOL'][:-1]) >= 1.0 or r['SCORE'] >= 1)]
        if ind_movers:
            df_ind = pd.DataFrame(ind_movers).sort_values(by=["SCORE", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"]).head(8)
            df_ind['SCORE'] = df_ind['SCORE'].astype(str)
            
            styled_ind = df_ind.style.apply(highlight_priority, axis=1) \
                .map(style_move_col, subset=['MOVE']) \
                .set_properties(**{'text-align': 'center', 'font-size': '14px'}) \
                .set_table_styles([{'selector': 'th', 'props': [('background-color', 'white'), ('color', 'black'), ('font-size', '14px')]}])
                
            st.dataframe(styled_ind, column_config=tv_link_config, use_container_width=True, hide_index=True)

    with c_brd:
        st.markdown("<div class='table-head head-neut'>🌌 BROADER MARKET (Top 8)</div>", unsafe_allow_html=True)
        res_brd = [analyze(s, data, force=True) for s in BROADER_MARKET]
        res_brd = [x for x in res_brd if x and (float(x['VOL'][:-1]) >= 1.0 or x['SCORE'] >= 1)]
        if res_brd:
            df_brd = pd.DataFrame(res_brd).sort_values(by=["SCORE", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"]).head(8)
            df_brd['SCORE'] = df_brd['SCORE'].astype(str)
            
            styled_brd = df_brd.style.apply(highlight_priority, axis=1) \
                .map(style_move_col, subset=['MOVE']) \
                .set_properties(**{'text-align': 'center', 'font-size': '14px'}) \
                .set_table_styles([{'selector': 'th', 'props': [('background-color', 'white'), ('color', 'black'), ('font-size', '14px')]}])
                
            st.dataframe(styled_brd, column_config=tv_link_config, use_container_width=True, hide_index=True)

else:
    st.warning("స్టాక్ మార్కెట్ డేటా దొరకలేదు. బహుశా ఇంటర్నెట్ లేదా Yahoo Finance సర్వర్ నెమ్మదిగా ఉండి ఉండొచ్చు.")
