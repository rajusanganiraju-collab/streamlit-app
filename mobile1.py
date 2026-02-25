import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Terminal", page_icon="📈", layout="wide")

# --- 2. AUTO RUN (1 MINUTE) ---
st_autorefresh(interval=60000, key="datarefresh")

# --- CSS FOR HEATMAP CARDS & RESPONSIVE LAYOUT ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {display: none !important;}
    
    .stApp { background-color: #121212; color: #ffffff; }
    html, body, [class*="css"] { font-family: 'Arial', sans-serif; font-weight: 600; }
    
    /* Top Space Reduction */
    .block-container { padding-top: 1rem !important; padding-bottom: 0rem !important; padding-left: 0.5rem !important; padding-right: 0.5rem !important; }
    
    /* SECTION HEADINGS */
    .table-head { padding: 6px 10px; font-weight: 900; font-size: 15px; text-transform: uppercase; margin-top: 15px; margin-bottom: 8px; border-radius: 4px; text-align: left; }
    .head-bull { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
    .head-bear { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
    .head-neut { background: #e2e3e5; color: #383d41; border: 1px solid #d6d8db; }
    
    /* --- HEATMAP CSS GRID --- */
    .grid-container {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); /* Auto adjust based on screen width */
        gap: 8px;
        margin-bottom: 10px;
    }
    
    .stock-card {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 8px 4px;
        border-radius: 6px;
        color: white;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        transition: transform 0.2s ease-in-out;
        text-decoration: none;
        height: 100%;
    }
    .stock-card:hover { transform: scale(1.05); }
    
    /* Text Inside Cards */
    .ticker { font-size: 12px; font-weight: 800; letter-spacing: 0.5px; opacity: 0.95; }
    .price { font-size: 15px; font-weight: 900; margin: 3px 0; }
    .metrics { font-size: 10px; font-weight: 600; background: rgba(0,0,0,0.2); padding: 2px 5px; border-radius: 4px;}
    .status-tags { font-size: 9px; margin-top: 4px; text-align: center; line-height: 1.2;}
    
    /* Mobile Responsive */
    @media (max-width: 600px) {
        .grid-container {
            grid-template-columns: repeat(3, 1fr); /* Always 3 columns on Mobile */
            gap: 5px; 
        }
        .stock-card { padding: 6px 2px; }
        .ticker { font-size: 10px; }
        .price { font-size: 13px; }
        .metrics { font-size: 9px; }
        .status-tags { font-size: 8px; }
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
            "TICKER": stock_name, "STOCK_URL": tv_url, 
            "PRICE": ltp, "DAY_PCT": day_chg, 
            "VOL": f"{vol_x:.1f}x", "STATUS": " ".join(status), 
            "SCORE": score, "VOL_NUM": vol_x
        }
    except: return None

# --- Custom HTML Grid Renderer ---
def render_stock_grid(data_list):
    if not data_list:
        return
        
    html_content = '<div class="grid-container">\n'
    
    for row in data_list:
        ticker = row['TICKER']
        tv_url = row['STOCK_URL']
        price = f"{row['PRICE']:.2f}"
        day_pct = row['DAY_PCT']
        vol = row['VOL']
        status = row['STATUS']
        
        # Determine Box Color
        bg_color = "#2E5A27" if day_pct >= 0 else "#8B1A1A"
        sign = "+" if day_pct >= 0 else ""
        
        # Highlight logic (Gold Border for high priority)
        major_conditions = sum(1 for tag in ["BigMove", "O=L", "O=H", "VOL"] if tag in status)
        border_style = "border: 2px solid #FFD700; box-shadow: 0 0 8px rgba(255, 215, 0, 0.6);" if major_conditions >= 2 else ""
        
        html_content += f"""
        <a href="{tv_url}" target="_blank" style="text-decoration: none;">
            <div class="stock-card" style="background-color: {bg_color}; {border_style}">
                <div class="ticker">{ticker}</div>
                <div class="price">{price}</div>
                <div class="metrics">{sign}{day_pct:.2f}% | V:{vol}</div>
                <div class="status-tags">{status}</div>
            </div>
        </a>\n
        """
        
    html_content += '</div>'
    st.markdown(html_content, unsafe_allow_html=True)

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
            render_stock_grid([search_res])
        else:
            st.warning(f"'{search_query}' కి సంబంధించి బ్రేక్అవుట్ కండిషన్స్ మ్యాచ్ అవ్వలేదు లేదా డేటా దొరకలేదు.")
    except Exception as e:
        st.error("డేటా పొందడంలో లోపం జరిగింది.")

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
    except: return None

loading_msg = st.empty()
loading_msg.info("మార్కెట్ డేటా లోడ్ అవుతోంది... దయచేసి 15 సెకన్లు వేచి ఉండండి ⏳")

data = get_data()
loading_msg.empty()

if data is not None and not data.empty:
    
    # --- DASHBOARD (Top Indices) ---
    dash_left, dash_right = st.columns([0.8, 0.2]) 
    nifty_chg = 0.0
    
    with dash_left:
        dash_html = '<div style="display: flex; justify-content: space-between; align-items: center; border: 1px solid #333; border-radius: 8px; background-color: #1e1e1e; padding: 5px; height: 80px;">'
        for idx, (ticker, name) in enumerate(INDICES.items()):
            try:
                if ticker in data.columns.levels[0]:
                    df = data[ticker].dropna()
                    ltp = float(df['Close'].iloc[-1])
                    pct = ((ltp - float(df['Close'].iloc[-2])) / float(df['Close'].iloc[-2])) * 100
                    
                    arrow = "↑" if pct >= 0 else "↓"
                    txt_color = "#4CAF50" if pct >= 0 else "#FF5252"
                    tv_url = f"https://in.tradingview.com/chart/?symbol={TV_INDICES.get(ticker, '')}"
                    border_style = "border-right: 1px solid #444;" if idx < 4 else ""
                    
                    dash_html += f'<a href="{tv_url}" target="_blank" style="text-decoration: none; flex: 1; text-align: center; {border_style}"><div style="color: #bbb; font-size: 13px; font-weight: 800;">{name}</div><div style="color: white; font-size: 18px; font-weight: 900; margin: 2px 0px;">{ltp:.0f}</div><div style="color: {txt_color}; font-size: 14px; font-weight: bold;">{arrow} {pct:.1f}%</div></a>'
                    
                    if name == "NIFTY":
                        o_now = float(df['Open'].iloc[-1])
                        nifty_chg = ((ltp - o_now) / o_now) * 100
            except: continue
        dash_html += "</div>"
        st.markdown(dash_html, unsafe_allow_html=True)

    with dash_right:
        if nifty_chg >= 0:
            market_trend, trend_bg, trend_txt = "BULLISH 🚀", "#1e4620", "#4CAF50"
        else:
            market_trend, trend_bg, trend_txt = "BEARISH 🩸", "#4a1919", "#FF5252"
            
        st.markdown(f"""
        <div style='display: flex; align-items: center; justify-content: center; height: 80px; border-radius: 8px; border: 2px solid {trend_txt}; background-color: {trend_bg}; color: {trend_txt}; font-size: 18px; font-weight: 900;'>
            {market_trend}
        </div>
        """, unsafe_allow_html=True)
    
    # --- SECTOR RANKS (Kept as simple clean table) ---
    sec_rows = []
    for name, info in SECTOR_MAP.items():
        try:
            if info['index'] in data.columns.levels[0]:
                df = data[info['index']].dropna()
                c_now, c_prev, o_now = float(df['Close'].iloc[-1]), float(df['Close'].iloc[-2]), float(df['Open'].iloc[-1])
                sec_rows.append({"SECTOR": name, "DAY%": ((c_now - o_now) / o_now) * 100})
        except: continue
    
    if sec_rows:
        df_sec = pd.DataFrame(sec_rows).sort_values("DAY%", ascending=False)
        top_sec, bot_sec = df_sec.iloc[0]['SECTOR'], df_sec.iloc[-1]['SECTOR']

    # --- BUY & SELL HEATMAPS ---
    c_buy, c_sell = st.columns(2)
    
    with c_buy:
        st.markdown(f"<div class='table-head head-bull'>🚀 BUY: {top_sec}</div>", unsafe_allow_html=True)
        res_b = [analyze(s, data, True) for s in SECTOR_MAP[top_sec]['stocks']]
        res_b = sorted([x for x in res_b if x], key=lambda x: (x["SCORE"], x["VOL_NUM"]), reverse=True)
        render_stock_grid(res_b)

    with c_sell:
        st.markdown(f"<div class='table-head head-bear'>🩸 SELL: {bot_sec}</div>", unsafe_allow_html=True)
        res_s = [analyze(s, data, False) for s in SECTOR_MAP[bot_sec]['stocks']]
        res_s = sorted([x for x in res_s if x], key=lambda x: (x["SCORE"], x["VOL_NUM"]), reverse=True)
        render_stock_grid(res_s)

    # --- INDEPENDENT & BROADER HEATMAPS ---
    c_ind, c_brd = st.columns(2)
    
    with c_ind:
        st.markdown("<div class='table-head head-neut'>🌟 INDEPENDENT (Top 8)</div>", unsafe_allow_html=True)
        ind_movers = [analyze(s, data, force=True) for name, info in SECTOR_MAP.items() if name not in [top_sec, bot_sec] for s in info['stocks']]
        ind_movers = [r for r in ind_movers if r and (float(r['VOL'][:-1]) >= 1.0 or r['SCORE'] >= 1)]
        ind_movers = sorted(ind_movers, key=lambda x: (x["SCORE"], x["VOL_NUM"]), reverse=True)[:8]
        render_stock_grid(ind_movers)

    with c_brd:
        st.markdown("<div class='table-head head-neut'>🌌 BROADER MARKET (Top 8)</div>", unsafe_allow_html=True)
        res_brd = [analyze(s, data, force=True) for s in BROADER_MARKET]
        res_brd = [x for x in res_brd if x and (float(x['VOL'][:-1]) >= 1.0 or x['SCORE'] >= 1)]
        res_brd = sorted(res_brd, key=lambda x: (x["SCORE"], x["VOL_NUM"]), reverse=True)[:8]
        render_stock_grid(res_brd)

else:
    st.warning("డేటా దొరకలేదు.")
