import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Terminal", page_icon="📈", layout="wide")

# --- 2. AUTO RUN (1 MINUTE) ---
st_autorefresh(interval=60000, key="datarefresh")

# --- CSS FOR PERFECT RESPONSIVE LAYOUT ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {display: none !important;}
    
    .stApp { background-color: #ffffff; color: #000000; }
    html, body, [class*="css"] { font-family: 'Arial', sans-serif; font-weight: 600; color: #000000 !important; }
    
    /* Top Space Reduction */
    .block-container { padding-top: 0.5rem !important; padding-bottom: 0rem !important; padding-left: 0.5rem !important; padding-right: 0.5rem !important; margin-top: -10px; }
    
    /* UNIFIED TABLE HEADINGS */
    .table-head { padding: 6px 10px; font-weight: 900; font-size: 15px; text-transform: uppercase; margin-top: 8px; margin-bottom: 0px; border-radius: 4px; text-align: left; display: block; width: 100%; box-sizing: border-box; }
    .head-bull { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; border-bottom: none; }
    .head-bear { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; border-bottom: none; }
    .head-neut { background: #e2e3e5; color: #383d41; border: 1px solid #d6d8db; border-bottom: none; }
    
    /* HTML Table Settings */
    .custom-table { width: 100% !important; min-width: 100% !important; border-collapse: collapse; }
    
    /* ----------------------------------------------------
       THE ULTIMATE FIX FOR MOBILE & DESKTOP SPLIT SCREEN
       ---------------------------------------------------- */
    @media screen and (max-width: 1200px) {
        div[data-testid="stHorizontalBlock"] {
            flex-direction: column !important;
            display: flex !important;
        }
        div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
            width: 100% !important;
            max-width: 100% !important;
            min-width: 100% !important;
            flex: none !important;
            display: block !important;
            margin-bottom: 10px !important;
        }
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
    "^NSEI": "NIFTY", "^NSEBANK": "BNKNFY", "^INDIAVIX": "VIX",
    "^DJI": "DOW", "^IXIC": "NSDQ"
}

TV_INDICES = {
    "^NSEI": "NSE:NIFTY", "^NSEBANK": "NSE:BANKNIFTY", "^INDIAVIX": "NSE:INDIAVIX",
    "^DJI": "TVC:DJI", "^IXIC": "NASDAQ:IXIC"
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
    if now.weekday() >= 5 or now.time() > dt_time(15, 30): return 375
    open_time = now.replace(hour=9, minute=15, second=0)
    diff = (now - open_time).total_seconds() / 60
    return min(375, max(1, int(diff)))

def analyze(symbol, full_data, check_bullish=True, force=False):
    try:
        if symbol not in full_data.columns.levels[0]: return None
        df = full_data[symbol].dropna()
        if len(df) < 2: return None
        
        ltp, open_p, prev_c = float(df['Close'].iloc[-1]), float(df['Open'].iloc[-1]), float(df['Close'].iloc[-2])
        low, high = float(df['Low'].iloc[-1]), float(df['High'].iloc[-1])
        
        day_chg, net_chg = ((ltp - open_p) / open_p) * 100, ((ltp - prev_c) / prev_c) * 100
        todays_move = net_chg - day_chg
        avg_vol, curr_vol = df['Volume'].iloc[:-1].mean(), float(df['Volume'].iloc[-1])
        
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
            "VOL": f"{vol_x:.1f}x", "STATUS": " ".join(status), "SCORE": score, "VOL_NUM": vol_x
        }
    except: return None

# --- HTML TABLE GENERATORS (WITH SCROLL WRAPPERS) ---
def render_html_table(df):
    if df.empty: return ""
    # Add overflow-x wrapper so it doesn't stretch the page
    html = '<div style="width: 100%; overflow-x: auto;">'
    html += '<table class="custom-table" style="font-size: 11px; text-align: center; margin-bottom: 15px; font-family: Arial, sans-serif;">'
    
    # Headers
    html += '<thead><tr style="border-bottom: 2px solid #222; border-top: 2px solid #222; background-color: #fff;">'
    for col in df.columns:
        html += f'<th style="padding: 6px 2px; font-weight: 900; color: #000; white-space: nowrap;">{col}</th>'
    html += '</tr></thead><tbody>'
    
    # Rows
    for _, row in df.iterrows():
        is_highlight = False
        hl_bg, hl_text = "", ""
        try:
            if int(row['SCORE']) >= 2:
                is_highlight = True
                if float(row['DAY%']) >= 0: hl_bg, hl_text = "#e6fffa", "#008000"
                else: hl_bg, hl_text = "#fff5f5", "#FF0000"
        except: pass
        
        html += '<tr>'
        for col in df.columns:
            val = str(row[col])
            td_style = "padding: 5px 2px; border-bottom: 1px solid #ddd; font-weight: 700; white-space: nowrap;"
            
            if is_highlight: td_style += f" background-color: {hl_bg}; color: {hl_text}; font-weight: 900;"
            else: td_style += " background-color: #fff; color: #000;"
            
            if col == "STOCK":
                ticker = val.split("NSE:")[-1] if "NSE:" in val else val
                val = f'<a href="{row["STOCK"]}" target="_blank" style="text-decoration:none; color:inherit;">{ticker}</a>'
            elif col == "MOVE":
                try:
                    v = float(val)
                    if v >= 0: td_style += " background-color: #d4edda !important; color: #155724 !important;"
                    else: td_style += " background-color: #f8d7da !important; color: #721c24 !important;"
                except: pass
            
            html += f'<td style="{td_style}">{val}</td>'
        html += '</tr>'
        
    html += '</tbody></table></div>'
    return html

def render_sector_table(df):
    if df.empty: return ""
    # Add overflow-x wrapper so it doesn't stretch the page
    html = '<div style="width: 100%; overflow-x: auto;">'
    html += '<table class="custom-table" style="font-size: 12px; text-align: center; margin-bottom: 15px; font-family: Arial, sans-serif;">'
    html += '<thead><tr style="border-bottom: 2px solid #222; border-top: 2px solid #222; background-color: #fff;">'
    html += '<th style="padding: 6px; color: #000;"></th>'
    for col in df.columns: html += f'<th style="padding: 6px 2px; font-weight: 900; color: #000; white-space: nowrap;">{col}</th>'
    html += '</tr></thead><tbody>'
    
    for idx, row in df.iterrows():
        html += '<tr>'
        html += f'<td style="padding: 6px; font-weight: 900; border-bottom: 1px solid #ddd; background-color: #fff; color: #000; text-align: left; white-space: nowrap;">{idx}</td>'
        for col in df.columns:
            val = row[col]
            td_style = "padding: 6px 2px; font-weight: 800; border-bottom: 1px solid #ddd; white-space: nowrap;"
            try:
                v = float(val)
                if v >= 0: td_style += " background-color: #d4edda; color: #155724;"
                else: td_style += " background-color: #f8d7da; color: #721c24;"
                val_str = f"{v:.2f}"
            except: val_str = str(val)
            html += f'<td style="{td_style}">{val_str}</td>'
        html += '</tr>'
    html += '</tbody></table></div>'
    return html

# -------------------------------------------------------------
# 5. SEARCH BAR FEATURE
# -------------------------------------------------------------
search_query = st.text_input("🔍 సెర్చ్ స్టాక్ (ఉదాహరణకు: RELIANCE, ZOMATO):", "").strip().upper()

if search_query:
    search_symbol = format_ticker(search_query)
    try:
        search_data = yf.download([search_symbol, "^NSEI"], period="5d", progress=False, group_by='ticker', threads=False)
        search_res = analyze(search_symbol, search_data, force=True)
        
        if search_res:
            st.markdown(f"<div class='table-head head-neut'>🎯 SEARCH RESULT: {search_query}</div>", unsafe_allow_html=True)
            df_search = pd.DataFrame([search_res])
            if "VOL_NUM" in df_search.columns: df_search = df_search.drop(columns=["VOL_NUM"])
            st.markdown(render_html_table(df_search), unsafe_allow_html=True)
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
    try: return yf.download(list(set(all_tickers)), period="5d", progress=False, group_by='ticker', threads=False)
    except: return None

loading_msg = st.empty()
loading_msg.info("మార్కెట్ డేటా లోడ్ అవుతోంది... దయచేసి 15 సెకన్లు వేచి ఉండండి ⏳")

data = get_data()
loading_msg.empty()

if data is not None and not data.empty:
    
    # DASHBOARD
    dash_left, dash_right = st.columns([0.8, 0.2]) 
    nifty_chg = 0.0
    
    with dash_left:
        # Added flex-wrap: wrap here to fix the main issue!
        dash_html = '<div style="display: flex; flex-wrap: wrap; gap: 5px; justify-content: space-between; align-items: center; border: 2px solid #ddd; border-radius: 8px; background-color: #f9f9f9; padding: 5px; min-height: 80px;">'
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
                    
                    dash_html += f'<a href="{tv_url}" target="_blank" style="text-decoration: none; flex: 1 1 80px; text-align: center; {border_style}"><div style="color: #444; font-size: 13px; font-weight: 800;">{name}</div><div style="color: black; font-size: 18px; font-weight: 900; margin: 2px 0px;">{ltp:.0f}</div><div style="color: {txt_color}; font-size: 14px; font-weight: bold;">{arrow} {pct:.1f}%</div></a>'
                    
                    if name == "NIFTY":
                        o_now = float(df['Open'].iloc[-1])
                        nifty_chg = ((ltp - o_now) / o_now) * 100
            except: continue
        dash_html += "</div>"
        st.markdown(dash_html, unsafe_allow_html=True)

    with dash_right:
        if nifty_chg >= 0: market_trend, trend_bg, trend_txt = "BULLISH 🚀", "#e6fffa", "#008000"
        else: market_trend, trend_bg, trend_txt = "BEARISH 🩸", "#fff5f5", "#FF0000"
            
        st.markdown(f"<div style='display: flex; align-items: center; justify-content: center; min-height: 80px; height: 100%; border-radius: 8px; border: 2px solid {trend_txt}; background-color: {trend_bg}; color: {trend_txt}; font-size: 18px; font-weight: 900; box-shadow: 2px 2px 5px rgba(0,0,0,0.1);'>{market_trend}</div>", unsafe_allow_html=True)
    
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
        st.markdown(render_sector_table(df_sec.set_index("SECTOR").T), unsafe_allow_html=True)
        top_sec, bot_sec = df_sec.iloc[0]['SECTOR'], df_sec.iloc[-1]['SECTOR']

    # BUY & SELL TABLES
    c_buy, c_sell = st.columns(2)
    with c_buy:
        st.markdown(f"<div class='table-head head-bull'>🚀 BUY: {top_sec}</div>", unsafe_allow_html=True)
        res_b = [x for x in [analyze(s, data, True) for s in SECTOR_MAP[top_sec]['stocks']] if x]
        if res_b:
            df_b = pd.DataFrame(res_b).sort_values(by=["SCORE", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"])
            st.markdown(render_html_table(df_b), unsafe_allow_html=True)

    with c_sell:
        st.markdown(f"<div class='table-head head-bear'>🩸 SELL: {bot_sec}</div>", unsafe_allow_html=True)
        res_s = [x for x in [analyze(s, data, False) for s in SECTOR_MAP[bot_sec]['stocks']] if x]
        if res_s:
            df_s = pd.DataFrame(res_s).sort_values(by=["SCORE", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"])
            st.markdown(render_html_table(df_s), unsafe_allow_html=True)

    # INDEPENDENT & BROADER
    c_ind, c_brd = st.columns(2)
    with c_ind:
        st.markdown("<div class='table-head head-neut'>🌟 INDEPENDENT (Top 8)</div>", unsafe_allow_html=True)
        ind_movers = [r for r in [analyze(s, data, force=True) for name, info in SECTOR_MAP.items() if name not in [top_sec, bot_sec] for s in info['stocks']] if r and (float(r['VOL'][:-1]) >= 1.0 or r['SCORE'] >= 1)]
        if ind_movers:
            df_ind = pd.DataFrame(ind_movers).sort_values(by=["SCORE", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"]).head(8)
            st.markdown(render_html_table(df_ind), unsafe_allow_html=True)

    with c_brd:
        st.markdown("<div class='table-head head-neut'>🌌 BROADER MARKET (Top 8)</div>", unsafe_allow_html=True)
        res_brd = [x for x in [analyze(s, data, force=True) for s in BROADER_MARKET] if x and (float(x['VOL'][:-1]) >= 1.0 or x['SCORE'] >= 1)]
        if res_brd:
            df_brd = pd.DataFrame(res_brd).sort_values(by=["SCORE", "VOL_NUM"], ascending=[False, False]).drop(columns=["VOL_NUM"]).head(8)
            st.markdown(render_html_table(df_brd), unsafe_allow_html=True)

else:
    st.warning("స్టాక్ మార్కెట్ డేటా దొరకలేదు. బహుశా ఇంటర్నెట్ లేదా Yahoo Finance సర్వర్ నెమ్మదిగా ఉండి ఉండొచ్చు.")
