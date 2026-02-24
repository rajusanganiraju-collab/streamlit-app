import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Terminal", page_icon="📈", layout="wide")

# --- 2. AUTO RUN (1 MINUTE) ---
st_autorefresh(interval=60000, key="datarefresh")

# CSS Styling - Updated for visibility
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {display: none !important;}
    
    .stApp { background-color: #ffffff; color: #000000; }
    html, body, [class*="css"] { font-family: 'Arial', sans-serif; font-weight: 600; color: #000000 !important; }
    
    .block-container { padding-top: 0.5rem !important; padding-bottom: 0rem !important; padding-left: 0.5rem !important; padding-right: 0.5rem !important; margin-top: -10px; }
    
    /* Table Headers */
    th { background-color: #f1f1f1 !important; color: #000000 !important; font-size: 13px !important; text-align: center !important; border-bottom: 2px solid #222222 !important; border-top: 2px solid #222222 !important; padding: 6px !important; }
    
    /* Table Cells - Score కనిపిచేలా కలర్ ఫిక్స్ చేశాను */
    td { font-size: 14px !important; color: #000000 !important; border-bottom: 1px solid #ccc !important; text-align: center !important; padding: 4px !important; font-weight: 700 !important; }
    
    .table-head { padding: 6px 10px; font-weight: 900; font-size: 15px; text-transform: uppercase; margin-top: 8px; margin-bottom: 2px; border-radius: 4px; text-align: left; }
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
    "METAL": {"index": "^CNXMETAL", "stocks": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "JINDALSTEL", "NMDC", "SAIL"]},
    "ENERGY": {"index": "^CNXENERGY", "stocks": ["RELIANCE", "NTPC", "ONGC", "POWERGRID", "BPCL", "TATAPOWER"]},
    "FMCG": {"index": "^CNXFMCG", "stocks": ["ITC", "HINDUNILVR", "BRITANNIA", "VBL", "NESTLEIND"]},
    "PHARMA": {"index": "^CNXPHARMA", "stocks": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "LUPIN", "AUROPHARMA"]},
    "AUTO": {"index": "^CNXAUTO", "stocks": ["MARUTI", "M&M", "EICHERMOT", "BAJAJ-AUTO", "TVSMOTOR", "ASHOKLEY", "HEROMOTOCO"]},
    "BANK": {"index": "^NSEBANK", "stocks": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK", "BANKBARODA", "PNB"]},
    "REALTY": {"index": "^CNXREALTY", "stocks": ["DLF", "GODREJPROP", "LODHA", "OBEROIRLTY"]},
    "IT": {"index": "^CNXIT", "stocks": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM", "PERSISTENT", "COFORGE"]}
}

BROADER_MARKET = [
    "HAL", "BEL", "BDL", "MAZDOCK", "COCHINSHIP", "GRSE", "RVNL", "IRFC", "IRCON", "TITAGARH", "RAILTEL", "RITES",
    "ADANIPOWER", "ADANIGREEN", "NHPC", "SJVN", "BHEL", "CGPOWER", "SUZLON", "PFC", "RECLTD", "IREDA", "IOB", "UCOBANK", 
    "MAHABANK", "CANBK", "BAJFINANCE", "CHOLAFIN", "JIOFIN", "MUTHOOTFIN", "MANAPPURAM", "SHRIRAMFIN", "M&MFIN", 
    "DIXON", "POLYCAB", "KAYNES", "HAVELLS", "KEI", "RRKABEL", "SRF", "TATACHEM", "DEEPAKNTR", "AARTIIND", "PIIND", "FACT", 
    "UPL", "ULTRACEMCO", "AMBUJACEM", "SHREECEM", "DALBHARAT", "L&T", "CUMMINSIND", "ABB", "SIEMENS", "BHARTIARTL", 
    "IDEA", "INDIGO", "ZOMATO", "TRENT", "DMART", "PAYTM", "ZENTEC", "ADANIENT", "ADANIPORTS", "ATGL", "AWL", 
    "BOSCHLTD", "MRF", "MOTHERSON", "SONACOMS", "EXIDEIND", "AMARAJABAT"
]

for k in SECTOR_MAP: SECTOR_MAP[k]['stocks'] = [format_ticker(s) for s in SECTOR_MAP[k]['stocks']]
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
        all_tickers.append(s['index'])
        all_tickers.extend(s['stocks'])
    all_tickers = list(set(all_tickers))
    try: return yf.download(all_tickers, period="5d", progress=False, group_by='ticker', threads=False)
    except: return None

def analyze(symbol, full_data, check_bullish=True, force=False):
    try:
        if symbol not in full_data.columns.levels[0]: return None
        df = full_data[symbol].dropna()
        if len(df) < 2: return None
        ltp, open_p, prev_c, low, high = float(df['Close'].iloc[-1]), float(df['Open'].iloc[-1]), float(df['Close'].iloc[-2]), float(df['Low'].iloc[-1]), float(df['High'].iloc[-1])
        day_chg = ((ltp - open_p) / open_p) * 100
        net_chg = ((ltp - prev_c) / prev_c) * 100
        todays_move = net_chg - day_chg
        avg_vol = df['Volume'].iloc[:-1].mean()
        curr_vol = float(df['Volume'].iloc[-1])
        vol_x = round(curr_vol / ((avg_vol/375) * get_minutes_passed()), 1) if avg_vol > 0 else 0.0
        vwap = (high + low + ltp) / 3
        if force: check_bullish = day_chg > 0
        status, score = [], 0
        if day_chg >= 2.0: status.append("BigMove🚀"); score += 3
        elif day_chg <= -2.0: status.append("BigMove🩸"); score += 3
        if check_bullish:
            if abs(open_p - low) <= (ltp * 0.003): status.append("O=L🔥"); score += 3
            if vol_x > 1.0: status.append("VOL🟢"); score += 3
            if ltp >= high * 0.998 and day_chg > 0.5: status.append("HB🚀"); score += 1
            if ltp > (low * 1.01) and ltp > vwap: status.append("Rec ⇈"); score += 1
        else:
            if abs(open_p - high) <= (ltp * 0.003): status.append("O=H🩸"); score += 3
            if vol_x > 1.0: status.append("VOL🔴"); score += 3
            if ltp <= low * 1.002 and day_chg < -0.5: status.append("LB📉"); score += 1
            if ltp < (high * 0.99) and ltp < vwap: status.append("PB ⇊"); score += 1
        if not status: return None
        return {"STOCK": f"https://in.tradingview.com/chart/?symbol=NSE:{symbol.replace('.NS','')}", "PRICE": f"{ltp:.2f}", "DAY%": f"{day_chg:.2f}", "NET%": f"{net_chg:.2f}", "MOVE": f"{todays_move:.2f}", "VOL": f"{vol_x:.1f}x", "STATUS": " ".join(status), "SCORE": score, "VOL_NUM": vol_x}
    except: return None

def style_df(df, config):
    return df.style.apply(lambda row: ['background-color: #e6fffa; color: #008000; font-weight: 900' if float(row['DAY%']) >= 0 and any(x in str(row['STATUS']) for x in ["BigMove", "O=L", "VOL"]) else 'background-color: #fff5f5; color: #FF0000; font-weight: 900' if float(row['DAY%']) < 0 and any(x in str(row['STATUS']) for x in ["BigMove", "O=H", "VOL"]) else 'background-color: white; color: black' for _ in row], axis=1).map(lambda v: f"background-color: {'#d4edda' if float(v) >= 0 else '#f8d7da'}; color: {'#155724' if float(v) >= 0 else '#721c24'}; font-weight: 800;" if isinstance(v, str) and "." in v else "", subset=['MOVE']).set_properties(**{'text-align': 'center'})

# --- 5. EXECUTION ---
data = get_data()

if data is not None:
    # Search Stock
    query = st.text_input("🔍 Search Stock:", "").upper().strip()
    if query:
        s_res = analyze(format_ticker(query), yf.download(format_ticker(query), period="5d", progress=False, group_by='ticker'), force=True)
        if s_res:
            c1, c2, c3, c4, c5 = st.columns([1,1,1,1,2])
            c1.metric("LTP", s_res['PRICE']); c2.metric("DAY%", s_res['DAY%']); c3.metric("VOL", s_res['VOL']); c4.metric("SCORE", s_res['SCORE'])
            st.info(f"STATUS: {s_res['STATUS']}")

    # Indices
    d_l, d_r = st.columns([0.8, 0.2])
    with d_l:
        html = '<div style="display: flex; justify-content: space-between; border: 2px solid #ddd; border-radius: 8px; background: #f9f9f9; padding: 5px; height: 80px;">'
        for t, n in INDICES.items():
            if t in data.columns.levels[0]:
                df = data[t].dropna()
                ltp, prev = df['Close'].iloc[-1], df['Close'].iloc[-2]
                pct = ((ltp - prev)/prev)*100
                html += f'<div style="flex: 1; text-align: center;"><div style="font-size: 12px; font-weight: 800;">{n}</div><div style="font-size: 18px; font-weight: 900;">{ltp:.0f}</div><div style="color: {"#008000" if pct >= 0 else "#FF0000"}; font-size: 14px;">{pct:.1f}%</div></div>'
        st.markdown(html + '</div>', unsafe_allow_html=True)
    
    # Tables
    sec_rows = []
    for n, i in SECTOR_MAP.items():
        if i['index'] in data.columns.levels[0]:
            df = data[i['index']].dropna()
            ltp, op, prev = df['Close'].iloc[-1], df['Open'].iloc[-1], df['Close'].iloc[-2]
            d_p, n_p = ((ltp-op)/op)*100, ((ltp-prev)/prev)*100
            sec_rows.append({"SECTOR": n, "DAY%": d_p, "NET%": n_p, "MOVE": n_p - d_p})
    
    if sec_rows:
        df_sec = pd.DataFrame(sec_rows).sort_values("DAY%", ascending=False)
        st.dataframe(df_sec.set_index("SECTOR").T.style.format("{:.2f}").set_properties(**{'text-align': 'center'}), use_container_width=True)
        t_s, b_s = df_sec.iloc[0]['SECTOR'], df_sec.iloc[-1]['SECTOR']
        
        cfg = {"STOCK": st.column_config.LinkColumn("STOCK", display_text=r".*NSE:(.*)")}
        c_b, c_s = st.columns(2)
        with c_b:
            st.markdown(f"<div class='table-head head-bull'>🚀 BUY: {t_s}</div>", unsafe_allow_html=True)
            res = [analyze(s, data, True) for s in SECTOR_MAP[t_s]['stocks']]
            df = pd.DataFrame([r for r in res if r]).sort_values("SCORE", ascending=False).drop(columns="VOL_NUM")
            st.dataframe(style_df(df, cfg), column_config=cfg, use_container_width=True, hide_index=True)
        with c_s:
            st.markdown(f"<div class='table-head head-bear'>🩸 SELL: {b_s}</div>", unsafe_allow_html=True)
            res = [analyze(s, data, False) for s in SECTOR_MAP[b_s]['stocks']]
            df = pd.DataFrame([r for r in res if r]).sort_values("SCORE", ascending=False).drop(columns="VOL_NUM")
            st.dataframe(style_df(df, cfg), column_config=cfg, use_container_width=True, hide_index=True)

        c_i, c_br = st.columns(2)
        with c_i:
            st.markdown("<div class='table-head head-neut'>🌟 INDEPENDENT (Top 8)</div>", unsafe_allow_html=True)
            res = [analyze(s, data, force=True) for n, i in SECTOR_MAP.items() if n not in [t_s, b_s] for s in i['stocks']]
            df = pd.DataFrame([r for r in res if r]).sort_values("SCORE", ascending=False).head(8).drop(columns="VOL_NUM")
            st.dataframe(style_df(df, cfg), column_config=cfg, use_container_width=True, hide_index=True)
        with c_br:
            st.markdown("<div class='table-head head-neut'>🌌 BROADER MARKET (Top 8)</div>", unsafe_allow_html=True)
            res = [analyze(s, data, force=True) for s in BROADER_MARKET]
            df = pd.DataFrame([r for r in res if r]).sort_values("SCORE", ascending=False).head(8).drop(columns="VOL_NUM")
            st.dataframe(style_df(df, cfg), column_config=cfg, use_container_width=True, hide_index=True)
