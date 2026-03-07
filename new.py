import streamlit as st
import yfinance as yf
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION & PRO CSS ---
st.set_page_config(page_title="Pro Trading Terminal", page_icon="💹", layout="wide")

st.markdown("""
    <style>
    /* Ultra-Clean Dark Institutional Theme */
    .stApp { background-color: #0d1117; color: #c9d1d9; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {display: none !important;}
    .block-container { padding-top: 1rem !important; padding-bottom: 0rem !important; margin-top: -10px; }
    
    /* Tabs Styling */
    .stTabs [data-baseweb="tab-list"] { background-color: #161b22; border-radius: 8px; padding: 5px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
    .stTabs [data-baseweb="tab"] { color: #8b949e; font-weight: 600; }
    .stTabs [aria-selected="true"] { color: #58a6ff !important; background-color: #21262d; border-radius: 6px; }
    
    /* Sleek Tables */
    .term-table { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 12px; background-color: #161b22; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
    .term-table th { background-color: #21262d; padding: 10px; border-bottom: 2px solid #30363d; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; text-align: center;}
    .term-table td { padding: 8px 10px; border-bottom: 1px solid #21262d; text-align: center; transition: background-color 0.2s; white-space: nowrap; }
    .term-table tr:hover td { background-color: #1f242c; }
    
    /* Gradients for Category Headers */
    .term-head-buy { background: linear-gradient(90deg, #1e5f29 0%, #0d1117 100%); color: white; text-align: left !important; padding: 8px 15px !important; font-size: 14px;}
    .term-head-sell { background: linear-gradient(90deg, #b52524 0%, #0d1117 100%); color: white; text-align: left !important; padding: 8px 15px !important; font-size: 14px;}
    .term-head-fund { background: linear-gradient(90deg, #d29922 0%, #0d1117 100%); color: white; text-align: left !important; padding: 8px 15px !important; font-size: 14px;}
    .term-head-port { background: linear-gradient(90deg, #4a148c 0%, #0d1117 100%); color: white; text-align: left !important; padding: 8px 15px !important; font-size: 14px;}
    
    /* Text Colors */
    .text-green { color: #3fb950 !important; font-weight: bold; }
    .text-red { color: #f85149 !important; font-weight: bold; }
    .t-symbol { text-align: left !important; font-weight: bold; }
    .t-symbol a { color: #58a6ff; text-decoration: none; border-bottom: 1px dashed rgba(88,166,255,0.4); }
    .t-symbol a:hover { color: #79c0ff !important; border-bottom: 1px solid #79c0ff; }
    
    /* Heatmap Cards */
    .heatmap-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); gap: 8px; padding: 5px 0; }
    .stock-card { border-radius: 6px; padding: 8px 4px; text-align: center; text-decoration: none !important; color: white !important; display: flex; flex-direction: column; justify-content: center; height: 90px; position: relative; box-shadow: 0 2px 4px rgba(0,0,0,0.3); transition: transform 0.2s; }
    .stock-card:hover { transform: scale(1.05); z-index: 10; box-shadow: 0 4px 8px rgba(0,0,0,0.5); border: 1px solid #58a6ff; }
    .bull-card { background-color: #1e5f29 !important; } .bear-card { background-color: #b52524 !important; } .neut-card { background-color: #21262d !important; border: 1px solid #30363d;} 
    .t-name { font-size: 13px; font-weight: normal !important; margin-bottom: 2px; }
    .t-price { font-size: 17px; font-weight: bold !important; margin-bottom: 2px; }
    .t-pct { font-size: 12px; font-weight: normal !important; }
    .t-score { position: absolute; top: 3px; left: 3px; font-size: 10px; background: rgba(0,0,0,0.5); padding: 2px 5px; border-radius: 4px; color: #ffd700; }
    </style>
""", unsafe_allow_html=True)

# --- 2. GOOGLE SHEETS CONNECTION ---
@st.cache_resource
def init_connection():
    try:
        creds_json = st.secrets["gcp_service_account"]
        creds_dict = json.loads(creds_json)
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)
    except Exception:
        return None

client = init_connection()

if client:
    try:
        db_sheet = client.open("Trading_DB")
        port_ws = db_sheet.worksheet("Portfolio")
        trade_ws = db_sheet.worksheet("TradeBook")
    except Exception as e:
        st.error(f"గూగుల్ షీట్ కనెక్ట్ అవ్వలేదు బాస్! Error: {e}")
        st.stop()
else:
    st.error("గూగుల్ షీట్ సీక్రెట్స్ దొరకలేదు.")
    st.stop()

def load_portfolio():
    try:
        records = port_ws.get_all_records()
        df = pd.DataFrame(records) if records else pd.DataFrame(columns=['Symbol', 'Buy_Price', 'Quantity', 'Date', 'SL', 'T1', 'T2'])
        if not df.empty and 'Stock Name' in df.columns:
            df.rename(columns={'Stock Name': 'Symbol', 'Buy Price': 'Buy_Price', 'Buy Date': 'Date'}, inplace=True)
            for col in ['SL', 'T1', 'T2']:
                if col not in df.columns: df[col] = 0.0
        return df
    except: return pd.DataFrame(columns=['Symbol', 'Buy_Price', 'Quantity', 'Date', 'SL', 'T1', 'T2'])

# --- 3. STATE & AUTO REFRESH ---
st_autorefresh(interval=150000, key="datarefresh")

if 'pinned_stocks' not in st.session_state: st.session_state.pinned_stocks = []

# --- 4. DATA LISTS ---
INDICES_MAP = {"^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY", "^INDIAVIX": "INDIA VIX"}
SECTOR_INDICES_MAP = {"^CNXIT": "NIFTY IT", "^CNXAUTO": "NIFTY AUTO", "^CNXMETAL": "NIFTY METAL"}

NIFTY_50_SECTORS = {
    "PHARMA": ["SUNPHARMA", "CIPLA", "DRREDDY", "APOLLOHOSP"],
    "IT": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM"],
    "BANK": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK"],
    "ENERGY": ["RELIANCE", "ONGC", "NTPC", "POWERGRID", "COALINDIA", "BPCL"],
    "AUTO": ["TATAMOTORS", "M&M", "MARUTI", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO"],
    "METAL": ["TATASTEEL", "JSWSTEEL", "HINDALCO"],
    "FMCG": ["ITC", "HINDUNILVR", "NESTLEIND", "BRITANNIA", "TATACONSUM"],
    "INFRA_CEMENT": ["LT", "ULTRACEMCO", "GRASIM"],
    "OTHERS": ["BHARTIARTL", "ASIANPAINT", "TITAN", "ADANIENT", "ADANIPORTS", "TRENT", "BEL"]
}
NIFTY_50 = [stock for sector in NIFTY_50_SECTORS.values() for stock in sector]

# (NOTE: Place your full FNO list here)
FNO_STOCKS = [
    "AARTIIND", "ABB", "ABBOTINDIA", "ABCAPITAL", "ABFRL", "ACC", "ADANIENSOL", "ADANIENT", "ADANIPORTS",
    "ALKEM", "AMBUJACEM", "ANGELONE", "APOLLOHOSP", "APOLLOTYRE", "ASHOKLEY", "ASIANPAINT", "ASTRAL", "ATUL",
    "AUBANK", "AUROPHARMA", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE", "BALKRISIND", "BALRAMCHIN"
]

# --- 5. MODULAR DATA ENGINE ---
@st.cache_data(ttl=150)
def download_daily_data(tickers):
    return yf.download(tickers, period="1y", progress=False, group_by='ticker', threads=20)

@st.cache_data(ttl=86400)
def fetch_fundamentals(symbols_list):
    fund_data = []
    for sym in symbols_list:
        try:
            tkr = yf.Ticker(f"{sym}.NS")
            info = tkr.info
            fund_data.append({
                "Symbol": sym,
                "Sector": info.get('sector', 'N/A'),
                "Market_Cap (Cr)": round(info.get('marketCap', 0) / 10000000, 2) if info.get('marketCap') else 0,
                "P/E Ratio": round(info.get('trailingPE', 0), 2) if info.get('trailingPE') else 0,
                "Div Yield %": round(info.get('dividendYield', 0) * 100, 2) if info.get('dividendYield') else 0.0,
                "52W High": info.get('fiftyTwoWeekHigh', 0),
                "52W Low": info.get('fiftyTwoWeekLow', 0)
            })
        except: continue
    return pd.DataFrame(fund_data)

@st.cache_data(ttl=150)
def process_market_radar():
    port_df = load_portfolio()
    port_stocks = [str(sym).upper().strip() for sym in port_df['Symbol'].tolist() if str(sym).strip() != ""]
    all_stocks = set(NIFTY_50 + FNO_STOCKS + port_stocks)
    tkrs = list(INDICES_MAP.keys()) + list(SECTOR_INDICES_MAP.keys()) + [f"{t}.NS" for t in all_stocks if t]
    
    data = download_daily_data(tkrs)
    results = []
    
    for symbol in data.columns.levels[0]:
        try:
            df = data[symbol].dropna(subset=['Close'])
            if len(df) < 20: continue
            
            ltp = float(df['Close'].iloc[-1])
            open_p = float(df['Open'].iloc[-1])
            prev_c = float(df['Close'].iloc[-2])
            high = float(df['High'].iloc[-1])
            low = float(df['Low'].iloc[-1])
            
            day_chg = ((ltp - open_p) / open_p) * 100 if open_p > 0 else 0
            net_chg = ((ltp - prev_c) / prev_c) * 100 if prev_c > 0 else 0
            vwap = (high + low + ltp) / 3
            vol_x = float(df['Volume'].iloc[-1]) / df['Volume'].iloc[-6:-1].mean() if df['Volume'].iloc[-6:-1].mean() > 0 else 0
            
            is_index = symbol in INDICES_MAP
            is_sector = symbol in SECTOR_INDICES_MAP
            disp_name = INDICES_MAP.get(symbol, SECTOR_INDICES_MAP.get(symbol, symbol.replace(".NS", "")))
            
            score = 0
            if not is_index and not is_sector:
                stock_dist = abs(ltp - vwap) / vwap * 100 if vwap > 0 else 0
                if stock_dist > 0.75: score += 5
                elif stock_dist > 0.50: score += 3
                if abs(open_p - low) <= (ltp * 0.003) or abs(open_p - high) <= (ltp * 0.003): score += 3 
                if vol_x > 1.0: score += 3 
            
            results.append({
                "Fetch_T": symbol, "T": disp_name, "P": ltp, "O": open_p, "H": high, "L": low, "Prev_C": prev_c,
                "Day_C": day_chg, "C": net_chg, "S": score, "VolX": vol_x, "VWAP": vwap,
                "Is_Index": is_index, "Is_Sector": is_sector
            })
        except: continue
    return pd.DataFrame(results)

# --- 6. PLOTLY CHART RENDERER (PERFECT CROSSHAIR) ---
def render_pro_chart(df_chart, display_sym, pct_val):
    if df_chart.empty: 
        st.warning("Chart Data Unavailable")
        return

    color_hex = "#f85149" if pct_val < 0 else "#3fb950"
    sign = "+" if pct_val > 0 else ""
    
    st.markdown(f"<div style='font-size:15px; font-weight:bold; padding-left:10px; margin-bottom:5px;'>{display_sym} <span style='color:{color_hex}; font-size:13px;'>({sign}{pct_val:.2f}%)</span></div>", unsafe_allow_html=True)
    
    min_val = df_chart['Low'].min()
    max_val = df_chart['High'].max()
    y_padding = (max_val - min_val) * 0.1

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.02, row_heights=[0.8, 0.2])
    
    # 1. Main Candlestick
    fig.add_trace(go.Candlestick(
        x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'], 
        increasing_line_color='#3fb950', decreasing_line_color='#f85149', showlegend=False, 
        hoverinfo='skip', name=""
    ), row=1, col=1)
    
    # 2. INVISIBLE SCATTER: High and Low tooltip only!
    hover_data = "High: ₹" + df_chart['High'].round(2).astype(str) + "<br>Low: ₹" + df_chart['Low'].round(2).astype(str)
    fig.add_trace(go.Scatter(
        x=df_chart.index, y=df_chart['High'], mode='lines', line=dict(color='rgba(0,0,0,0)'), 
        showlegend=False, hoverinfo='text', text=hover_data, 
        hovertemplate="%{text}<extra></extra>", name=""
    ), row=1, col=1)

    # 3. Volume Bars
    colors = ['#3fb950' if close >= open_p else '#f85149' for close, open_p in zip(df_chart['Close'], df_chart['Open'])]
    fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Volume'], marker_color=colors, showlegend=False, hoverinfo='skip'), row=2, col=1)

    # MAGIC LAYOUT: Thin Crosshair
    fig.update_layout(
        margin=dict(l=0, r=0, t=0, b=0), height=350, 
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', 
        xaxis_rangeslider_visible=False, hovermode='x unified', dragmode=False
    )
    
    # EXACT CROSSHAIR CODE: spikesnap='cursor' and spikethickness=0.2
    fig.update_yaxes(
        showspikes=True, spikesnap='cursor', spikemode='across', spikethickness=0.2, spikedash='solid', spikecolor="rgba(255,255,255,0.4)", 
        showgrid=False, zeroline=False, showticklabels=True, side='right', tickfont=dict(color="#8b949e", size=10), showline=False, 
        fixedrange=True, range=[min_val - y_padding, max_val + y_padding], row=1, col=1
    )
    fig.update_xaxes(showspikes=False, showgrid=False, zeroline=False, showticklabels=False, row=1, col=1)
    
    fig.update_yaxes(visible=False, fixedrange=True, row=2, col=1)
    fig.update_xaxes(showgrid=False, zeroline=False, showticklabels=True, tickfont=dict(color="#8b949e", size=10), row=2, col=1)

    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})


# --- 7. MAIN UI & TABS LAYOUT ---
st.markdown("<h3 style='text-align: center; color: #58a6ff; margin-bottom: 20px;'>🚀 INSTITUTIONAL TRADING TERMINAL</h3>", unsafe_allow_html=True)

tabs = st.tabs(["📈 Live Market Radar", "🏢 Fundamentals & Breakouts", "💼 My Portfolio", "⚙️ Pro Charting"])

df_radar = process_market_radar()

# --- TAB 1: LIVE MARKET RADAR ---
with tabs[0]:
    if not df_radar.empty:
        c1, c2 = st.columns([0.6, 0.4])
        with c1:
            radar_mode = st.radio("Select Radar Mode:", ["Heatmap View", "Top Movers (Table)"], horizontal=True, label_visibility="collapsed")
        
        df_stocks = df_radar[(~df_radar['Is_Index']) & (~df_radar['Is_Sector'])].sort_values(by="VolX", ascending=False)
        
        if radar_mode == "Heatmap View":
            st.markdown("<div style='margin-top:15px; color:#c9d1d9; font-weight:bold; margin-bottom:10px;'>🔥 Top Momentum Stocks</div>", unsafe_allow_html=True)
            
            # PERFECT SINGLE-LINE HTML STRING TO PREVENT RENDERING BUGS
            html_stk = '<div class="heatmap-grid">'
            for _, row in df_stocks.head(40).iterrows():
                bg = "bull-card" if row['C'] > 0 else "bear-card"
                html_stk += f'<a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank" class="stock-card {bg}"><div class="t-score">⭐{int(row["S"])}</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{"+" if row["C"]>0 else ""}{row["C"]:.2f}%</div></a>'
            html_stk += '</div>'
            
            st.markdown(html_stk, unsafe_allow_html=True)
            
        else:
            st.dataframe(
                df_stocks[['T', 'P', 'C', 'Day_C', 'VolX', 'S']].head(20).style.background_gradient(cmap='RdYlGn', subset=['C']),
                use_container_width=True, hide_index=True
            )
    else:
        st.info("Loading Live Data...")

# --- TAB 2: FUNDAMENTALS ---
with tabs[1]:
    st.markdown("<div style='color:#8b949e; margin-bottom:10px;'>Analyze the intrinsic value of NIFTY 50 and FNO stocks. Data is cached to load instantly.</div>", unsafe_allow_html=True)
    
    if st.button("🔄 Fetch Top 30 Market Fundamentals"):
        with st.spinner("Fetching Institutional Data from Exchange..."):
            # Fetching for top 30 stocks for speed. 
            df_fund = fetch_fundamentals(NIFTY_50[:30]) 
            if not df_fund.empty:
                html_fund = f'<table class="term-table"><thead><tr><th colspan="7" class="term-head-fund">🏢 FUNDAMENTAL METRICS & 52W LEVELS</th></tr><tr><th>STOCK</th><th>SECTOR</th><th>MKT CAP (₹ Cr)</th><th>P/E RATIO</th><th>DIV YIELD</th><th>52W HIGH</th><th>52W LOW</th></tr></thead><tbody>'
                for _, row in df_fund.iterrows():
                    html_fund += f'<tr><td class="t-symbol">{row["Symbol"]}</td><td>{row["Sector"]}</td><td>{row["Market_Cap (Cr)"]:,.2f}</td><td>{row["P/E Ratio"]}</td><td>{row["Div Yield %"]}%</td><td class="text-green">₹{row["52W High"]}</td><td class="text-red">₹{row["52W Low"]}</td></tr>'
                html_fund += '</tbody></table>'
                st.markdown(html_fund, unsafe_allow_html=True)

# --- TAB 3: PORTFOLIO ---
with tabs[2]:
    df_port = load_portfolio()
    st.markdown("### 💼 Live Portfolio Analytics")
    
    if not df_port.empty:
        st.dataframe(df_port, use_container_width=True, hide_index=True)
    else:
        st.info("Portfolio is empty. Database connected successfully.")

# --- TAB 4: PRO CHARTING ---
with tabs[3]:
    st.markdown("<div style='color:#8b949e; margin-bottom:15px;'>Search and plot High-Resolution Institutional Charts with custom crosshair logic.</div>", unsafe_allow_html=True)
    
    all_names = sorted(df_radar['T'].unique().tolist()) if not df_radar.empty else NIFTY_50
    search_stock = st.selectbox("🔍 Select Stock to Chart", ["-- None --"] + all_names)
    
    if search_stock != "-- None --":
        with st.spinner(f"Loading high-res chart for {search_stock}..."):
            fetch_sym = df_radar[df_radar['T'] == search_stock]['Fetch_T'].iloc[0] if not df_radar.empty else f"{search_stock}.NS"
            chart_raw = yf.download(fetch_sym, period="5d", interval="15m", progress=False)
            
            if not chart_raw.empty:
                chart_data = chart_raw.copy()
                pct_change = ((chart_data['Close'].iloc[-1] - chart_data['Close'].iloc[-2]) / chart_data['Close'].iloc[-2]) * 100
                render_pro_chart(chart_data, search_stock, pct_change)
            else:
                st.warning("Chart data not available right now.")
