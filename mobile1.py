import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Terminal", page_icon="📈", layout="wide")

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
    
    th { background-color: #ffffff !important; color: #000000 !important; font-size: 12px !important; text-align: center !important; border-bottom: 2px solid #222222 !important; border-top: 2px solid #222222 !important; padding: 4px 2px !important; }
    td { font-size: 12px !important; color: #000000 !important; border-bottom: 1px solid #ccc !important; text-align: center !important; padding: 4px 2px !important; font-weight: 700 !important; }
    
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
    "SRF", "TATACHEM", "DEEPAKNTR", "AARTIIND", "PIIND", "FACT", "UPL", "ULTRACEMCO", "AMBUJACEM", "SHREECEM", "DALBHARAT", "L&T", "CUMMINSIND", "ABB", "SIEMENS",
    "BHARTIARTL", "IDEA", "INDIGO", "ZOMATO", "TRENT", "DMART", "PAYTM", "ZENTEC", "ADANIENT", "ADANIPORTS", "ATGL", "AWL",
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
        # పక్కా 5-నిమిషాల డేటా (5-minute timeframe)
        data = yf.download(all_tickers, period="5d", interval="5m", progress=False, group_by='ticker', threads=True)
        return data
    except: 
        return None

def analyze(symbol, full_data, check_bullish=True, force=False):
    try:
        if symbol not in full_data.columns.levels[0]: return None
        df = full_data[symbol].dropna()
        if len(df) < 200: return None # EMA 200 కోసం కనీసం 200 5m క్యాండిల్స్ కావాలి
        
        # డేటాని ఈరోజుకి మరియు నిన్నటికి విడదీయడం (For Gaps & Day High/Low)
        df['Date'] = df.index.date
        current_date = df['Date'].iloc[-1]
        today_data = df[df['Date'] == current_date].copy()
        prev_data = df[df['Date'] < current_date]
        
        if len(today_data) == 0 or len(prev_data) == 0: return None
        
        ltp = float(today_data['Close'].iloc[-1])
        open_p = float(today_data['Open'].iloc[0]) # ఈరోజు 9:15 క్యాండిల్ ఓపెన్ ప్రైస్
        prev_c = float(prev_data['Close'].iloc[-1]) # నిన్నటి 3:25 క్యాండిల్ క్లోజింగ్ ప్రైస్
        low = float(today_data['Low'].min())
        high = float(today_data['High'].max())
        
        day_chg = ((ltp - open_p) / open_p) * 100
        net_chg = ((ltp - prev_c) / prev_c) * 100
        todays_move = net_chg - day_chg

        # డైలీ వాల్యూమ్ క్యాలిక్యులేషన్
        avg_daily_vol = prev_data['Volume'].sum() / prev_data['Date'].nunique()
        curr_vol = today_data['Volume'].sum()
        minutes = get_minutes_passed()
        vol_x = round(curr_vol / ((avg_daily_vol/375) * minutes), 1) if avg_daily_vol > 0 else 0.0
        
        # ---------------------------------------------------------
        # PINE SCRIPT INTRADAY INDICATORS (5-Minute Timeframe)
        # ---------------------------------------------------------
        # 1. LIVE INTRADAY VWAP (ప్రతిరోజూ ఉదయం రీసెట్ అవుతుంది)
        today_data['Typical_Price'] = (today_data['High'] + today_data['Low'] + today_data['Close']) / 3
        today_data['Cum_Vol_Price'] = (today_data['Typical_Price'] * today_data['Volume']).cumsum()
        today_data['Cum_Vol'] = today_data['Volume'].cumsum()
        vwap = float(today_data['Cum_Vol_Price'].iloc[-1] / today_data['Cum_Vol'].iloc[-1]) if today_data['Cum_Vol'].iloc[-1] > 0 else ltp

        # 2. 5-Min EMAs (50 & 200)
        df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
        df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()
        
        # 3. 5-Min RSI (25 Length)
        delta = df['Close'].diff()
        gain = delta.where(delta > 0, 0).ewm(alpha=1/25, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/25, adjust=False).mean()
        rs = gain / loss
        df['RSI25'] = 100 - (100 / (1 + rs))
        
        ema50 = float(df['EMA50'].iloc[-1])
        ema200 = float(df['EMA200'].iloc[-1])
        rsi25 = float(df['RSI25'].iloc[-1])
        
        # 4. Gap Strategy (0.50% Threshold)
        actual_gap_percent = abs(open_p - prev_c) / prev_c * 100
        is_gap_up = (open_p > prev_c) and (actual_gap_percent >= 0.50)
        is_gap_down = (open_p < prev_c) and (actual_gap_percent >= 0.50)
        # ---------------------------------------------------------

        if force: check_bullish = day_chg > 0
        status, score = [], 0
        
        is_open_low = abs(open_p - low) <= (ltp * 0.003)
        is_open_high = abs(open_p - high) <= (ltp * 0.003)
        
        if day_chg >= 2.0: status.append("BM🚀"); score += 2
        elif day_chg <= -2.0: status.append("BM🩸"); score += 2

        if check_bullish:
            # Basic Price Action
            if is_open_low: status.append("O=L🔥"); score += 2
            if vol_x > 1.0: status.append("V🟢"); score += 2
            if ltp >= high * 0.998 and day_chg > 0.5: status.append("HB🚀"); score += 1
            
            # --- 5-MIN PINE SCRIPT BULLISH CONDITIONS ---
            if ltp > ema50: status.append("E50🟢"); score += 1
            if ltp > ema200: status.append("E200🟢"); score += 1
            if rsi25 > 14: score += 1 # RSI Condition
            
            # ఇంట్రాడే గ్యాప్ జాక్‌పాట్: గ్యాప్ డౌన్ + VWAP పైన ఉంటే..
            if is_gap_down and ltp > vwap:
                status.append("GapBuy🔥"); score += 4
                
        else:
            # Basic Price Action
            if is_open_high: status.append("O=H🩸"); score += 2
            if vol_x > 1.0: status.append("V🔴"); score += 2
            if ltp <= low * 1.002 and day_chg < -0.5: status.append("LB📉"); score += 1
            
            # --- 5-MIN PINE SCRIPT BEARISH CONDITIONS ---
            if ltp < ema50: status.append("E50🔴"); score += 1
            if ltp < ema200: status.append("E200🔴"); score += 1
            if rsi25 < 86: score += 1
            
            # ఇంట్రాడే గ్యాప్ జాక్‌పాట్: గ్యాప్ అప్ + VWAP కింద ఉంటే..
            if is_gap_up and ltp < vwap:
                status.append("GapSell🩸"); score += 4
            
        if not status: return None
        
        stock_name = symbol.replace(".NS", "")
        tv_url = f"https://in.tradingview.com/chart/?symbol=NSE:{stock_name}"
        
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
    if "GapBuy" in status_str or "GapSell" in status_str: major_conditions += 2 
    
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
loading_msg.info("5-Min ఇంట్రాడే డేటా (EMA, RSI, VWAP) లోడ్ అవుతోంది... దయచేసి వేచి ఉండండి ⏳")

data = get_data()
loading_msg.empty()

if data is not None and not data.empty:
    
    sec_rows = []
    for name, info in SECTOR_MAP.items():
        try:
            if info['index'] in data.columns.levels[0]:
                df = data[info['index']].dropna()
                if len(df) < 2: continue
                # సెక్టార్ కి కూడా 5 నిమిషాల డేటా తీసుకుంటున్నాం
                df['Date'] = df.index.date
                current_date = df['Date'].iloc[-1]
                today_data = df[df['Date'] == current_date]
                prev_data = df[df['Date'] < current_date]
                if len(today_data) == 0 or len(prev_data) == 0: continue
                
                c_now = float(today_data['Close'].iloc[-1])
                o_now = float(today_data['Open'].iloc[0])
                c_prev = float(prev_data['Close'].iloc[-1])
                
                d_pct = ((c_now - o_now) / o_now) * 100
                n_pct = ((c_now - c_prev) / c_prev) * 100
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

    dash_left, dash_right = st.columns([0.8, 0.2]) 
    
    with dash_left:
        dash_html = '<div style="display: flex; justify-content: space-between; align-items: center; border: 2px solid #ddd; border-radius: 8px; background-color: #f9f9f9; padding: 5px; height: 80px;">'
        
        for idx, (ticker, name) in enumerate(INDICES.items()):
            try:
                if ticker in data.columns.levels[0]:
                    df = data[ticker].dropna()
                    if len(df) < 2: continue
                    df['Date'] = df.index.date
                    current_date = df['Date'].iloc[-1]
                    today_data = df[df['Date'] == current_date]
                    prev_data = df[df['Date'] < current_date]
                    if len(today_data) == 0 or len(prev_data) == 0: continue
                    
                    ltp = float(today_data['Close'].iloc[-1])
                    c_prev = float(prev_data['Close'].iloc[-1])
                    pct = ((ltp - c_prev) / c_prev) * 100
                    
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
        "STAT": st.column_config.TextColumn("STAT", width="small")
    }

    c_buy, c_sell = st.columns(2)
    
    with c_buy:
        st.markdown(f"<div class='table-head head-bull'>🚀 BUY: {top_sec}</div>", unsafe_allow_html=True)
        if not df_b.empty:
            styled_b = df_b.style.apply(highlight_priority, axis=1) \
                .map(style_move_col, subset=['M%']) \
                .set_properties(**{'text-align': 'center', 'font-size': '12px', 'padding': '6px 1px'}) \
                .set_table_styles([{'selector': 'th', 'props': [('background-color', 'white'), ('color', 'black'), ('font-size', '12px'), ('padding', '4px 1px')]}])
            st.dataframe(styled_b, column_config=tv_link_config, use_container_width=True, hide_index=True)

    with c_sell:
        st.markdown(f"<div class='table-head head-bear'>🩸 SELL: {bot_sec}</div>", unsafe_allow_html=True)
        if not df_s.empty:
            styled_s = df_s.style.apply(highlight_priority, axis=1) \
                .map(style_move_col, subset=['M%']) \
                .set_properties(**{'text-align': 'center', 'font-size': '12px', 'padding': '6px 1px'}) \
                .set_table_styles([{'selector': 'th', 'props': [('background-color', 'white'), ('color', 'black'), ('font-size', '12px'), ('padding', '4px 1px')]}])
            st.dataframe(styled_s, column_config=tv_link_config, use_container_width=True, hide_index=True)

    c_ind, c_brd = st.columns(2)
    
    with c_ind:
        st.markdown("<div class='table-head head-neut'>🌟 INDEPENDENT (Top 8)</div>", unsafe_allow_html=True)
        if not df_ind.empty:
            styled_ind = df_ind.style.apply(highlight_priority, axis=1) \
                .map(style_move_col, subset=['M%']) \
                .set_properties(**{'text-align': 'center', 'font-size': '12px', 'padding': '6px 1px'}) \
                .set_table_styles([{'selector': 'th', 'props': [('background-color', 'white'), ('color', 'black'), ('font-size', '12px'), ('padding', '4px 1px')]}])
            st.dataframe(styled_ind, column_config=tv_link_config, use_container_width=True, hide_index=True)

    with c_brd:
        st.markdown("<div class='table-head head-neut'>🌌 BROADER MARKET (Top 8)</div>", unsafe_allow_html=True)
        if not df_brd.empty:
            styled_brd = df_brd.style.apply(highlight_priority, axis=1) \
                .map(style_move_col, subset=['M%']) \
                .set_properties(**{'text-align': 'center', 'font-size': '12px', 'padding': '6px 1px'}) \
                .set_table_styles([{'selector': 'th', 'props': [('background-color', 'white'), ('color', 'black'), ('font-size', '12px'), ('padding', '4px 1px')]}])
            st.dataframe(styled_brd, column_config=tv_link_config, use_container_width=True, hide_index=True)

else:
    st.warning("స్టాక్ మార్కెట్ డేటా దొరకలేదు. బహుశా ఇంటర్నెట్ లేదా Yahoo Finance సర్వర్ నెమ్మదిగా ఉండి ఉండొచ్చు.")
