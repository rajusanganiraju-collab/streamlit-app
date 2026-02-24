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
        data = yf.download(all_tickers, period="5d", interval="5m", progress=False, group_by='ticker', threads=False)
        return data, all_tickers
    except: 
        return None, all_tickers

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

        avg_daily_vol = prev_data['Volume'].sum() / prev_data['Date'].nunique()
        curr_vol = today_data['Volume'].sum()
        minutes = get_minutes_passed()
        vol_x = round(curr_vol / ((avg_daily_vol/375) * minutes), 1) if avg_daily_vol > 0 else 0.0
        
        # VWAP CALCULATION
        today_data['Typical_Price'] = (today_data['High'] + today_data['Low'] + today_data['Close']) / 3
        today_data['Cum_Vol_Price'] = (today_data['Typical_Price'] * today_data['Volume']).cumsum()
        today_data['Cum_Vol'] = today_data['Volume'].cumsum()
        today_data['VWAP'] = today_data['Cum_Vol_Price'] / today_data['Cum_Vol']

        curr_close = today_data['Close'].iloc[-1]
        curr_vwap = today_data['VWAP'].iloc[-1]
        
        is_bullish_trend = curr_close > curr_vwap
        
        if not force:
            if check_bullish and not is_bullish_trend: return None
            if not check_bullish and is_bullish_trend: return None

        # ⚡ NEW: STRICT CLOSE BASIS LOGIC ⚡
        # కేవలం Close ప్రైస్ మాత్రమే పక్కాగా VWAP మరియు 10EMA కంటే పైన/కింద ఉండాలి.
        
        today_data['Bull_Candle'] = (today_data['Close'] > today_data['VWAP']) & (today_data['Close'] > today_data['EMA10'])
        today_data['Bear_Candle'] = (today_data['Close'] < today_data['VWAP']) & (today_data['Close'] < today_data['EMA10'])

        if is_bullish_trend:
            valid_candles = int(today_data['Bull_Candle'].sum())
        else:
            valid_candles = int(today_data['Bear_Candle'].sum())
            
        score_mins = valid_candles * 5
        score = score_mins 
        
        # THE KILL SWITCH (VWAP Break)
        closes = today_data['Close'].values
        vwaps = today_data['VWAP'].values
        
        streak = 0
        for i in range(len(closes)-1, -1, -1):
            if is_bullish_trend:
                if closes[i] > vwaps[i]: streak += 1
                else: break
            else:
                if closes[i] < vwaps[i]: streak += 1
                else: break 
                
        # కనీసం 3 క్యాండిల్స్ (15 నిమిషాలు) కంటిన్యూస్ గా VWAP కింద లేకపోతే లిస్ట్ లోంచి అవుట్!
        if streak < 3: 
            return None
            
        # Trap Identifier (తొలి క్యాండిల్ ఎక్కడ క్లోజ్ అయిందో చూసి డిసైడ్ చేస్తుంది)
        first_close = today_data['Close'].iloc[0]
        first_vwap = today_data['VWAP'].iloc[0]
        
        if is_bullish_trend:
            if first_close < first_vwap: tag = "VWAP-Trap"
            else: tag = "VWAP-Pure"
        else:
            if first_close > first_vwap: tag = "VWAP-Trap"
            else: tag = "VWAP-Pure"

        # Time Formatting
        hrs = score_mins // 60
        mins = score_mins % 60
        time_str = f"{hrs}h" if mins == 0 else f"{hrs}h {mins}m"
        if hrs == 0: time_str = f"{mins}m"

        if is_bullish_trend:
            status_text = f"🚀 {tag} ({time_str})"
        else:
            status_text = f"🩸 {tag} ({time_str})"
            
        stock_name = symbol.replace(".NS", "")
        tv_url = f"https://in.tradingview.com/chart/?symbol=NSE:{stock_name}"
        
        return {
            "STOCK": tv_url, "LTP": f"{ltp:.2f}", "D%": f"{day_chg:.2f}",
            "N%": f"{net_chg:.2f}", "M%": f"{todays_move:.2f}", 
            "VOL": f"{vol_x:.1f}x", "STAT": status_text, "SCORE": int(score),
            "VOL_NUM": vol_x, "TREND": "BULL" if is_bullish_trend else "BEAR"
        }
    except: return None

def highlight_priority(row):
    status_str = str(row['STAT'])
    day_chg = float(row['D%'])
        
    if "VWAP" in status_str:
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

def create_sorted_df(res_list, limit=15):
    res_list = [x for x in res_list if x]
    if not res_list: return pd.DataFrame()
    df = pd.DataFrame(res_list)
    df['ABS_D'] = df['D%'].astype(float).abs()
    return df.sort_values(by=["SCORE", "ABS_D"], ascending=[False, False]).drop(columns=["VOL_NUM", "ABS_D"]).head(limit)

# --- 5. EXECUTION ---
loading_msg = st.empty()
loading_msg.info("🎯 Strict Close Basis Engine (VWAP + 10 EMA) లోడ్ అవుతోంది... ⏳")

data, all_tickers = get_data()
loading_msg.empty()

if data is not None and not data.empty:
    
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
                    if len(today_data) == 0: continue
                    
                    ltp = float(today_data['Close'].iloc[-1])
                    o_today = float(today_data['Open'].iloc[0]) 
                    pct = ((ltp - o_today) / o_today) * 100
                    
                    arrow = "↑" if pct >= 0 else "↓"
                    txt_color = "#008000" if pct >= 0 else "#FF0000"
                    tv_symbol = TV_INDICES.get(ticker, "")
                    tv_url = f"https://in.tradingview.com/chart/?symbol={tv_symbol}"
                    
                    border_style = "border-right: 1px solid #ddd;" if idx < 4 else ""
                    dash_html += f'<a href="{tv_url}" target="_blank" style="text-decoration: none; flex: 1; text-align: center; {border_style}"><div style="color: #444; font-size: 13px; font-weight: 800;">{name}</div><div style="color: black; font-size: 18px; font-weight: 900; margin: 2px 0px;">{ltp:.0f}</div><div style="color: {txt_color}; font-size: 14px; font-weight: bold;">{arrow} {pct:.1f}%</div></a>'
            except: continue
        dash_html += "</div>"
        st.markdown(dash_html, unsafe_allow_html=True)

    sec_rows = []
    for name, info in SECTOR_MAP.items():
        try:
            if info['index'] in data.columns.levels[0]:
                df = data[info['index']].dropna()
                if len(df) < 2: continue
                df['Date'] = df.index.date
                current_date = df['Date'].iloc[-1]
                today_data = df[df['Date'] == current_date]
                if len(today_data) == 0: continue
                
                ltp = float(today_data['Close'].iloc[-1])
                o_today = float(today_data['Open'].iloc[0]) 
                d_pct = ((ltp - o_today) / o_today) * 100
                sec_rows.append({"SECTOR": name, "D%": d_pct, "N%": d_pct, "M%": d_pct})
        except: continue
    
    if sec_rows:
        df_sec = pd.DataFrame(sec_rows).sort_values("D%", ascending=False)
        top_sec = df_sec.iloc[0]['SECTOR']
        bot_sec = df_sec.iloc[-1]['SECTOR']
    else:
        top_sec, bot_sec, df_sec = "", "", pd.DataFrame()

    raw_b = [analyze(s, data, True) for s in SECTOR_MAP.get(top_sec, {}).get('stocks', [])] if top_sec else []
    df_b = create_sorted_df(raw_b, 15)

    raw_s = [analyze(s, data, False) for s in SECTOR_MAP.get(bot_sec, {}).get('stocks', [])] if bot_sec else []
    df_s = create_sorted_df(raw_s, 15)

    raw_ind = [analyze(s, data, force=True) for name, info in SECTOR_MAP.items() if name not in [top_sec, bot_sec] for s in info['stocks']]
    df_ind = create_sorted_df(raw_ind, 15)

    raw_brd = [analyze(s, data, force=True) for s in BROADER_MARKET]
    df_brd = create_sorted_df(raw_brd, 15)

    total_bulls = 0
    total_bears = 0
    for df_ in [df_b, df_s, df_ind, df_brd]:
        if not df_.empty and "TREND" in df_.columns:
            total_bulls += (df_['TREND'] == 'BULL').sum()
            total_bears += (df_['TREND'] == 'BEAR').sum()
            df_.drop(columns=["TREND"], inplace=True)
            df_['SCORE'] = df_['SCORE'].astype(str)

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
    
    st.markdown("<hr style='margin: 10px 0px;'>", unsafe_allow_html=True)
    sniper_col1, sniper_col2 = st.columns([0.3, 0.7])
    with sniper_col1:
        sniper_ticker = st.text_input("🎯 SNIPER SEARCH:", placeholder="Type symbol here (e.g. LT)")
    
    with sniper_col2:
        if sniper_ticker:
            s_sym = format_ticker(sniper_ticker)
            try:
                s_ticker_obj = yf.Ticker(s_sym)
                s_data = s_ticker_obj.history(period="5d", interval="5m")
                
                if not s_data.empty:
                    s_res = analyze(s_sym, s_data, force=True)
                    if s_res:
                        st.markdown(f"<div class='table-head head-sniper'>🎯 SNIPER TARGET: {s_sym.replace('.NS', '')}</div>", unsafe_allow_html=True)
                        if "TREND" in s_res: del s_res["TREND"]
                        df_s_disp = pd.DataFrame([s_res])
                        styled_s_disp = df_s_disp.style.apply(highlight_priority, axis=1) \
                            .map(style_move_col, subset=['M%']) \
                            .set_properties(**{'text-align': 'center', 'font-size': '12px', 'padding': '6px 1px'}) \
                            .set_table_styles([{'selector': 'th', 'props': [('background-color', '#fff3cd'), ('color', '#856404'), ('font-size', '12px')]}])
                        
                        tv_link_config_sniper = {
                            "STOCK": st.column_config.LinkColumn("STOCK", display_text=r".*NSE:(.*)"),
                            "STAT": st.column_config.TextColumn("STAT", width="medium"),
                            "SCORE": st.column_config.TextColumn("MINS", width="small")
                        }
                        st.dataframe(styled_s_disp, column_config=tv_link_config_sniper, use_container_width=True, hide_index=True)
                    else:
                        st.warning(f"⚠️ {sniper_ticker.upper()} కి ఇప్పుడు సరైన ట్రెండ్ లేదు, లేదా VWAP బ్రేక్ అయ్యింది.")
                else:
                    st.error(f"⚠️ {s_sym} డేటా రాలేదు! బహుశా ఈ స్టాక్ పేరు తప్పు అయ్యుండొచ్చు.")
            except Exception as e:
                st.error("⚠️ Yahoo Finance సర్వర్ ఎర్రర్. మళ్లీ ట్రై చేయండి.")
    st.markdown("<hr style='margin: 10px 0px;'>", unsafe_allow_html=True)

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
        "STAT": st.column_config.TextColumn("STAT", width="medium"),
        "SCORE": st.column_config.TextColumn("MINS", width="small")
    }

    c_buy, c_sell = st.columns(2)
    with c_buy:
        st.markdown(f"<div class='table-head head-bull'>🚀 BUY: {top_sec}</div>", unsafe_allow_html=True)
        if not df_b.empty:
            styled_b = df_b.style.apply(highlight_priority, axis=1).map(style_move_col, subset=['M%']).set_properties(**{'text-align': 'center', 'font-size': '12px', 'padding': '6px 1px'})
            st.dataframe(styled_b, column_config=tv_link_config, use_container_width=True, hide_index=True, height=350)

    with c_sell:
        st.markdown(f"<div class='table-head head-bear'>🩸 SELL: {bot_sec}</div>", unsafe_allow_html=True)
        if not df_s.empty:
            styled_s = df_s.style.apply(highlight_priority, axis=1).map(style_move_col, subset=['M%']).set_properties(**{'text-align': 'center', 'font-size': '12px', 'padding': '6px 1px'})
            st.dataframe(styled_s, column_config=tv_link_config, use_container_width=True, hide_index=True, height=350)

    c_ind, c_brd = st.columns(2)
    with c_ind:
        st.markdown("<div class='table-head head-neut'>🌟 INDEPENDENT (Top 15)</div>", unsafe_allow_html=True)
        if not df_ind.empty:
            styled_ind = df_ind.style.apply(highlight_priority, axis=1).map(style_move_col, subset=['M%']).set_properties(**{'text-align': 'center', 'font-size': '12px', 'padding': '6px 1px'})
            st.dataframe(styled_ind, column_config=tv_link_config, use_container_width=True, hide_index=True, height=580)

    with c_brd:
        st.markdown("<div class='table-head head-neut'>🌌 BROADER MARKET (Top 15)</div>", unsafe_allow_html=True)
        if not df_brd.empty:
            styled_brd = df_brd.style.apply(highlight_priority, axis=1).map(style_move_col, subset=['M%']).set_properties(**{'text-align': 'center', 'font-size': '12px', 'padding': '6px 1px'})
            st.dataframe(styled_brd, column_config=tv_link_config, use_container_width=True, hide_index=True, height=580)

    if isinstance(data.columns, pd.MultiIndex):
        downloaded = data.columns.levels[0]
        missing_stocks = [t.replace(".NS", "") for t in all_tickers if t not in downloaded]
        if missing_stocks:
            st.markdown(f"<div style='text-align: center; color: #ff4b4b; font-size: 11px; margin-top: 20px;'>⚠️ <b>Yahoo Finance Failed to Download:</b> {', '.join(missing_stocks)}</div>", unsafe_allow_html=True)

else:
    st.warning("స్టాక్ మార్కెట్ డేటా దొరకలేదు. బహుశా ఇంటర్నెట్ లేదా Yahoo Finance సర్వర్ నెమ్మదిగా ఉండి ఉండొచ్చు.")
