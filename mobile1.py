import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Terminal", page_icon="📈", layout="wide")

# --- 2. AUTO RUN (1 MINUTE) ---
st_autorefresh(interval=60000, key="datarefresh")

# పైన స్పేస్ తగ్గించడానికి, మొబైల్ ఆప్టిమైజేషన్ కి CSS
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {display: none !important;}
    
    .stApp { background-color: #ffffff; color: #000000; }
    html, body, [class*="css"] { font-family: 'Arial', sans-serif; font-weight: 600; color: #000000 !important; }
    
    /* మొబైల్ కోసం మార్జిన్స్ బాగా తగ్గించబడ్డాయి */
    .block-container { padding-top: 0.5rem !important; padding-bottom: 0rem !important; padding-left: 0.1rem !important; padding-right: 0.1rem !important; margin-top: -10px; }
    
    /* Table Styling - Centered */
    th { background-color: #ffffff !important; color: #000000 !important; font-size: 12px !important; text-align: center !important; border-bottom: 2px solid #222222 !important; border-top: 2px solid #222222 !important; padding: 4px 2px !important; }
    td { font-size: 12px !important; color: #000000 !important; border-bottom: 1px solid #ccc !important; text-align: center !important; padding: 4px 2px !important; font-weight: 700 !important; }
    
    /* UNIFIED TABLE HEADINGS */
    .table-head { padding: 6px 10px; font-weight: 900; font-size: 14px; text-transform: uppercase; margin-top: 8px; margin-bottom: 2px; border-radius: 4px; text-align: left; }
    .head-bull { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
    .head-bear { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
    .head-neut { background: #e2e3e5; color: #383d41; border: 1px solid #d6d8db; }
    
    div[data-testid="stDataFrame"] { margin-bottom: -15px !important; }
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
        status, score = [], 0
        
        is_open_low = abs(open_p - low) <= (ltp * 0.003)
        is_open_high = abs(open_p - high) <= (ltp * 0.003)
        
        # ఇక్కడ టెక్స్ట్‌ని చిన్నగా మార్చాను
        if day_chg >= 2.0: status.append("BM🚀"); score += 3
        elif day_chg <= -2.0: status.append("BM🩸"); score += 3

        if check_bullish:
            if is_open_low: status.append("O=L🔥"); score += 3
            if vol_x > 1.0: status.append("V🟢"); score += 3
            if ltp >= high * 0.998 and day_chg > 0.5: status.append("HB🚀"); score += 1
            if ltp > (low * 1.01) and ltp > vwap: status.append("R⇈"); score += 1
        else:
            if is_open_high: status.append("O=H🩸"); score += 3
            if vol_x > 1.0: status.append("V🔴"); score += 3
            if ltp <= low * 1.002 and day_chg < -0.5: status.append("LB📉"); score += 1
            if ltp < (high * 0.99) and ltp < vwap: status.append("P⇊"); score += 1
            
        if not status: return None
        
        stock_name = symbol.replace(".NS", "")
        tv_url = f"https://in.tradingview.com/chart/?symbol=NSE:{stock_name}"
        
        # ఇక్కడ హెడ్డింగ్ పేర్లను షార్ట్ కట్ లో (LTP, D%, N%, M%, STAT, SCR) మార్చాను
        return {
            "STOCK": tv_url, "LTP": f"{ltp:.2f}", "D%": f"{day_chg:.2f}",
            "N%": f"{net_chg:.2f}", "M%": f"{todays_move:.2f}", 
            "VOL": f"{vol_x:.1f}x", "STAT": " ".join(status), "SCR": score,
            "VOL_NUM": vol_x, "TREND": "BULL" if check_bullish else "BEAR"
        }
    except: return None

# --- Custom Styling ---
def highlight_priority(row):
    status_str = str(row['STAT'])
    day_chg = float(row['D%'])
    
    major_conditions = 0
    if "BM" in status_str: major_conditions += 1
    if "O=L" in status_str or "O=H" in status_str: major_conditions += 1
    if "V🟢" in status_str or "V🔴" in status_str: major_conditions += 1
    
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

# --- 5. EXECUTION ---
loading_msg = st.empty()
loading_msg.info("మార్కెట్ డేటా లోడ్ అవుతోంది... దయచేసి 15 సెకన్లు వేచి ఉండండి ⏳")

data = get_data()
loading_msg.empty()

if data is not None and not data.empty:
    
    # ----------------------------------------------------------------------
    # 1. డేటాను ముందుగానే క్యాలిక్యులేట్ చేయడం (Buy/Sell కౌంట్ కోసం)
    # ----------------------------------------------------------------------
    
    sec_rows = []
    for name, info in SECTOR_MAP.items():
        try:
            if info['index'] in data.columns.levels[0]:
                df = data[info['index']].dropna()
                c_now, c_prev, o_now = float(df['Close'].iloc[-1]), float(df['Close'].iloc[-2]), float(df['Open'].iloc[-1])
                d_pct, n_pct = ((c_now - o_now) / o_now) * 100, ((c_now - c_prev) / c_prev) * 100
                sec_rows.append({"SECTOR": name, "D%": d_pct, "N%": n_pct, "M%": n_pct - d_pct})
        except: continue
    
    if sec_rows:
        df_sec = pd.DataFrame(sec_rows).sort_values("D%", ascending=False)
        top_sec = df_sec.iloc[0]['SECTOR']
        bot_sec = df_sec.iloc[-1]['SECTOR']
    else:
        top_sec, bot_sec, df_sec = "", "", pd.DataFrame()

    res_b = [analyze(s, data, True) for s in SECTOR_MAP.get(top_sec, {}).get('stocks', [])] if top_sec else []
    res_b = [x for x in res_b if x]
    df_b = pd.DataFrame(res_b).sort_values(by=["SCR", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"]).head(8) if res_b else pd.DataFrame()

    res_s = [analyze(s, data, False) for s in SECTOR_MAP.get(bot_sec, {}).get('stocks', [])] if bot_sec else []
    res_s = [x for x in res_s if x]
    df_s = pd.DataFrame(res_s).sort_values(by=["SCR", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"]).head(8) if res_s else pd.DataFrame()

    ind_movers = [analyze(s, data, force=True) for name, info in SECTOR_MAP.items() if name not in [top_sec, bot_sec] for s in info['stocks']]
    ind_movers = [r for r in ind_movers if r and (float(r['VOL'][:-1]) >= 1.0 or r['SCR'] >= 1)]
    df_ind = pd.DataFrame(ind_movers).sort_values(by=["SCR", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"]).head(8) if ind_movers else pd.DataFrame()

    res_brd = [analyze(s, data, force=True) for s in BROADER_MARKET]
    res_brd = [x for x in res_brd if x and (float(x['VOL'][:-1]) >= 1.0 or x['SCR'] >= 1)]
    df_brd = pd.DataFrame(res_brd).sort_values(by=["SCR", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"]).head(8) if res_brd else pd.DataFrame()

    total_bulls = 0
    total_bears = 0
    
    for df_ in [df_b, df_s, df_ind, df_brd]:
        if not df_.empty and "TREND" in df_.columns:
            total_bulls += (df_['TREND'] == 'BULL').sum()
            total_bears += (df_['TREND'] == 'BEAR').sum()
            df_.drop(columns=["TREND"], inplace=True)
            df_['SCR'] = df_['SCR'].astype(str)

    # ----------------------------------------------------------------------
    # 2. DASHBOARD - 80% & 20% Layout
    # ----------------------------------------------------------------------
    dash_left, dash_right = st.columns([0.8, 0.2]) 
    
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
            except: continue
            
        dash_html += "</div>"
        st.markdown(dash_html, unsafe_allow_html=True)

    with dash_right:
        if total_bulls >= total_bears:
            market_trend = "BULLISH 🚀"
            trend_bg, trend_txt = "#e6fffa", "#008000"
            count_color = "#155724"
        else:
            market_trend = "BEARISH 🩸"
            trend_bg, trend_txt = "#fff5f5", "#FF0000"
            count_color = "#721c24"
            
        st.markdown(f"""
        <div style='display: flex; flex-direction: column; align-items: center; justify-content: center; height: 80px; border-radius: 8px; border: 2px solid {trend_txt}; background-color: {trend_bg}; color: {trend_txt}; box-shadow: 2px 2px 5px rgba(0,0,0,0.1);'>
            <div style='font-size: 18px; font-weight: 900;'>{market_trend}</div>
            <div style='font-size: 11px; font-weight: 800; margin-top: 3px; color: {count_color};'>BUYS: {total_bulls} | SELLS: {total_bears}</div>
        </div>
        """, unsafe_allow_html=True)
    
    # ----------------------------------------------------------------------
    # 3. SECTOR RANKS DISPLAY
    # ----------------------------------------------------------------------
    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
    if not df_sec.empty:
        df_sec_t = df_sec.set_index("SECTOR").T
        styled_sec = df_sec_t.style.format("{:.2f}") \
            .map(style_sector_ranks) \
            .set_properties(**{'text-align': 'center', 'font-size': '12px', 'font-weight': '600'}) \
            .set_table_styles([
                {'selector': 'th', 'props': [('text-align', 'center'), ('background-color', 'white'), ('color', 'black'), ('font-size', '12px')]},
                {'selector': 'td', 'props': [('text-align', 'center')]}
            ])
        st.dataframe(styled_sec, use_container_width=True)

    tv_link_config = {
        "STOCK": st.column_config.LinkColumn("STOCK", display_text=r".*NSE:(.*)"),
    }

    # ----------------------------------------------------------------------
    # 4. BUY & SELL TABLES 
    # ----------------------------------------------------------------------
    c_buy, c_sell = st.columns(2)
    
    with c_buy:
        st.markdown(f"<div class='table-head head-bull'>🚀 BUY: {top_sec}</div>", unsafe_allow_html=True)
        if not df_b.empty:
            styled_b = df_b.style.apply(highlight_priority, axis=1) \
                .map(style_move_col, subset=['M%']) \
                .set_properties(**{'text-align': 'center', 'font-size': '12px', 'padding': '6px 2px'}) \
                .set_table_styles([{'selector': 'th', 'props': [('background-color', 'white'), ('color', 'black'), ('font-size', '12px'), ('padding', '4px 2px')]}])
            st.dataframe(styled_b, column_config=tv_link_config, use_container_width=True, hide_index=True)

    with c_sell:
        st.markdown(f"<div class='table-head head-bear'>🩸 SELL: {bot_sec}</div>", unsafe_allow_html=True)
        if not df_s.empty:
            styled_s = df_s.style.apply(highlight_priority, axis=1) \
                .map(style_move_col, subset=['M%']) \
                .set_properties(**{'text-align': 'center', 'font-size': '12px', 'padding': '6px 2px'}) \
                .set_table_styles([{'selector': 'th', 'props': [('background-color', 'white'), ('color', 'black'), ('font-size', '12px'), ('padding', '4px 2px')]}])
            st.dataframe(styled_s, column_config=tv_link_config, use_container_width=True, hide_index=True)

    # ----------------------------------------------------------------------
    # 5. INDEPENDENT & BROADER
    # ----------------------------------------------------------------------
    c_ind, c_brd = st.columns(2)
    
    with c_ind:
        st.markdown("<div class='table-head head-neut'>🌟 INDEPENDENT (Top 8)</div>", unsafe_allow_html=True)
        if not df_ind.empty:
            styled_ind = df_ind.style.apply(highlight_priority, axis=1) \
                .map(style_move_col, subset=['M%']) \
                .set_properties(**{'text-align': 'center', 'font-size': '12px', 'padding': '6px 2px'}) \
                .set_table_styles([{'selector': 'th', 'props': [('background-color', 'white'), ('color', 'black'), ('font-size', '12px'), ('padding', '4px 2px')]}])
            st.dataframe(styled_ind, column_config=tv_link_config, use_container_width=True, hide_index=True)

    with c_brd:
        st.markdown("<div class='table-head head-neut'>🌌 BROADER MARKET (Top 8)</div>", unsafe_allow_html=True)
        if not df_brd.empty:
            styled_brd = df_brd.style.apply(highlight_priority, axis=1) \
                .map(style_move_col, subset=['M%']) \
                .set_properties(**{'text-align': 'center', 'font-size': '12px', 'padding': '6px 2px'}) \
                .set_table_styles([{'selector': 'th', 'props': [('background-color', 'white'), ('color', 'black'), ('font-size', '12px'), ('padding', '4px 2px')]}])
            st.dataframe(styled_brd, column_config=tv_link_config, use_container_width=True, hide_index=True)

else:
    st.warning("స్టాక్ మార్కెట్ డేటా దొరకలేదు. బహుశా ఇంటర్నెట్ లేదా Yahoo Finance సర్వర్ నెమ్మదిగా ఉండి ఉండొచ్చు.")
