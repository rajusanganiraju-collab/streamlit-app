import streamlit as st
import yfinance as yf
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
from datetime import datetime, time as dt_time
from streamlit_autorefresh import st_autorefresh

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Market Heatmap", page_icon="📊", layout="wide")

# --- 2. GOOGLE SHEETS CONNECTION ---
@st.cache_resource
def init_connection():
    creds_json = st.secrets["gcp_service_account"]
    creds_dict = json.loads(creds_json)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

client = init_connection()

try:
    db_sheet = client.open("Trading_DB")
    port_ws = db_sheet.worksheet("Portfolio")
    trade_ws = db_sheet.worksheet("TradeBook")
except Exception as e:
    st.error(f"గూగుల్ షీట్ కనెక్ట్ అవ్వలేదు బాస్! Error: {e}")
    st.stop()

# --- 3. DATA LOAD & SAVE FUNCTIONS ---
def load_portfolio():
    try:
        records = port_ws.get_all_records()
        df = pd.DataFrame(records) if records else pd.DataFrame(columns=['Symbol', 'Buy_Price', 'Quantity', 'Date', 'SL', 'T1', 'T2'])
        
        if not df.empty and 'Stock Name' in df.columns:
            df.rename(columns={'Stock Name': 'Symbol', 'Buy Price': 'Buy_Price', 'Buy Date': 'Date'}, inplace=True)
            for col in ['SL', 'T1', 'T2']:
                if col not in df.columns: df[col] = 0.0
            save_portfolio(df)
        return df
    except:
        return pd.DataFrame(columns=['Symbol', 'Buy_Price', 'Quantity', 'Date', 'SL', 'T1', 'T2'])

def load_closed_trades():
    try:
        records = trade_ws.get_all_records()
        df = pd.DataFrame(records) if records else pd.DataFrame(columns=['Sell_Date', 'Symbol', 'Quantity', 'Buy_Price', 'Sell_Price', 'PnL_Rs', 'PnL_Pct'])
        
        if not df.empty and 'Stock Name' in df.columns:
            df.rename(columns={'Stock Name': 'Symbol', 'Buy Price': 'Buy_Price', 'Sell Price': 'Sell_Price', 'Sell Date': 'Sell_Date', 'Profit/Loss': 'PnL_Rs'}, inplace=True)
            if 'PnL_Pct' not in df.columns: df['PnL_Pct'] = 0.0
            save_closed_trades(df)
        return df
    except:
        return pd.DataFrame(columns=['Sell_Date', 'Symbol', 'Quantity', 'Buy_Price', 'Sell_Price', 'PnL_Rs', 'PnL_Pct'])

def save_portfolio(df):
    port_ws.clear()
    df = df.fillna("")
    port_ws.update([df.columns.values.tolist()] + df.values.tolist())

def save_closed_trades(df):
    trade_ws.clear()
    df = df.fillna("")
    trade_ws.update([df.columns.values.tolist()] + df.values.tolist())

# --- 4. AUTO RUN & STATE MANAGEMENT ---
st_autorefresh(interval=150000, key="datarefresh")

if 'pinned_stocks' not in st.session_state:
    st.session_state.pinned_stocks = []

if 'custom_alerts' not in st.session_state:
    st.session_state.custom_alerts = {}

def toggle_pin(symbol):
    if symbol in st.session_state.pinned_stocks:
        st.session_state.pinned_stocks.remove(symbol)
    else:
        st.session_state.pinned_stocks.append(symbol)

# --- CSS FOR STYLING ---
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {display: none !important;}
    .stApp { background-color: #0e1117; color: #ffffff; }
    .block-container { padding-top: 1rem !important; padding-bottom: 0rem !important; margin-top: -10px; }
    
    .stRadio label, .stRadio p, div[role="radiogroup"] p { color: #ffffff !important; font-weight: normal !important; }
    div.stButton > button p, div.stButton > button span { color: #ffffff !important; font-weight: normal !important; font-size: 14px !important; }
    
    .t-name { font-size: 13px; font-weight: normal !important; margin-bottom: 2px; }
    .t-price { font-size: 17px; font-weight: normal !important; margin-bottom: 2px; }
    .t-pct { font-size: 12px; font-weight: normal !important; }
    .t-score { position: absolute; top: 3px; left: 3px; font-size: 10px; background: rgba(0,0,0,0.4); padding: 1px 4px; border-radius: 3px; color: #ffd700; font-weight: normal !important; }
    
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) {
        display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important; 
        justify-content: space-between !important; align-items: center !important; gap: 6px !important; width: 100% !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) > div[data-testid="stElementContainer"]:has(.filter-marker) { display: none !important; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) > div[data-testid="stElementContainer"] {
        flex: 1 1 0px !important; min-width: 0 !important; width: 100% !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) div.stButton > button { width: 100% !important; height: 38px !important; padding: 0px !important; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) div.stButton > button p { font-size: clamp(9px, 2.5vw, 13px) !important; white-space: nowrap !important; margin: 0 !important; }
    
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { display: grid !important; gap: 12px !important; align-items: start !important; }
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div:nth-child(1) { display: none !important; }
    @media screen and (min-width: 1700px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(8, 1fr) !important; } }
    @media screen and (min-width: 1400px) and (max-width: 1699px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(6, 1fr) !important; } }
    @media screen and (min-width: 1100px) and (max-width: 1399px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(5, 1fr) !important; } }
    @media screen and (min-width: 850px) and (max-width: 1099px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(4, 1fr) !important; } }
    @media screen and (min-width: 651px) and (max-width: 849px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(3, 1fr) !important; } }
    @media screen and (max-width: 650px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(2, 1fr) !important; gap: 6px !important; } }
    
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div[data-testid="stVerticalBlock"] {
        background-color: #161b22 !important; border: 1px solid #30363d !important; border-radius: 8px !important;
        padding: 5px !important; position: relative !important; width: 100% !important;
    }

    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div[data-testid="stVerticalBlock"] div[data-testid="stCheckbox"] {
        position: absolute !important; top: 10px !important; left: 10px !important; z-index: 100 !important;
    }
    div[data-testid="stCheckbox"] label { padding: 0 !important; min-height: 0 !important; }
    div.stButton > button { border-radius: 8px !important; border: 1px solid #30363d !important; background-color: #161b22 !important; height: 45px !important; }
    
    .heatmap-grid { display: grid; grid-template-columns: repeat(10, 1fr); gap: 8px; padding: 5px 0; }
    .stock-card { border-radius: 4px; padding: 8px 4px; text-align: center; text-decoration: none !important; color: white !important; display: flex; flex-direction: column; justify-content: center; height: 90px; position: relative; box-shadow: 0 1px 3px rgba(0,0,0,0.3); transition: transform 0.2s; }
    .stock-card:hover { transform: scale(1.05); z-index: 10; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }
    .bull-card { background-color: #1e5f29 !important; } .bear-card { background-color: #b52524 !important; } .neut-card { background-color: #30363d !important; } 
    .idx-card { background-color: #0d47a1 !important; border: 1px solid #1976d2; } 
    @media screen and (max-width: 1400px) { .heatmap-grid { grid-template-columns: repeat(8, 1fr); } }
    @media screen and (max-width: 1100px) { .heatmap-grid { grid-template-columns: repeat(6, 1fr); } }
    @media screen and (max-width: 800px) { .heatmap-grid { grid-template-columns: repeat(4, 1fr); } }
    @media screen and (max-width: 600px) { .heatmap-grid { grid-template-columns: repeat(3, 1fr); gap: 6px; } .stock-card { height: 95px; } .t-name { font-size: 12px; } .t-price { font-size: 16px; } .t-pct { font-size: 11px; } }
    .custom-hr { border: 0; height: 1px; background: #30363d; margin: 15px 0; }

    .term-table { width: 100%; border-collapse: collapse; margin-bottom: 15px; font-family: monospace; font-size: 11.5px; color: #e6edf3; background-color: #0e1117; table-layout: fixed; }
    .term-table th { padding: 6px 4px; text-align: center; border: 1px solid #30363d; font-weight: bold; overflow: hidden; }
    .term-table td { padding: 6px 4px; text-align: center; border: 1px solid #30363d; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .term-table a { color: inherit; text-decoration: none; border-bottom: 1px dashed rgba(255,255,255,0.4); } 
    .term-table a:hover { color: #58a6ff !important; text-decoration: none; border-bottom: 1px solid #58a6ff; } 
    
    .term-head-buy { background-color: #1e5f29; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
    .term-head-sell { background-color: #b52524; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
    .term-head-ind { background-color: #9e6a03; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
    .term-head-brd { background-color: #0d47a1; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
    .term-head-port { background-color: #4a148c; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
    .term-head-swing { background-color: #005a9e; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
    .term-head-high { background-color: #b71c1c; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
    .term-head-levels { background-color: #004d40; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
    .row-dark { background-color: #161b22; } .row-light { background-color: #0e1117; }
    .text-green { color: #3fb950; font-weight: bold; } .text-red { color: #f85149; font-weight: bold; }
    .t-symbol { text-align: left !important; font-weight: bold; }
    .port-total { background-color: #21262d; font-weight: bold; font-size: 13px; }
    </style>
""", unsafe_allow_html=True)

# --- 5. DATA SETUP & SECTOR MAPPING ---
INDICES_MAP = {"^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY", "^INDIAVIX": "INDIA VIX", "^DJI": "DOW", "^IXIC": "NSDQ"}
TV_INDICES_URL = {"^NSEI": "NSE:NIFTY", "^NSEBANK": "NSE:BANKNIFTY", "^INDIAVIX": "NSE:INDIAVIX", "^DJI": "CAPITALCOM:DOWJONES", "^IXIC": "NASDAQ:IXIC"}

SECTOR_INDICES_MAP = {
    "^CNXIT": "NIFTY IT", "^CNXAUTO": "NIFTY AUTO", "^CNXMETAL": "NIFTY METAL",
    "^CNXPHARMA": "NIFTY PHARMA", "^CNXFMCG": "NIFTY FMCG", "^CNXENERGY": "NIFTY ENERGY", "^CNXREALTY": "NIFTY REALTY"
}

TV_SECTOR_URL = {
    "^CNXIT": "NSE:CNXIT", "^CNXAUTO": "NSE:CNXAUTO", "^CNXMETAL": "NSE:CNXMETAL",
    "^CNXPHARMA": "NSE:CNXPHARMA", "^CNXFMCG": "NSE:CNXFMCG", "^CNXENERGY": "NSE:CNXENERGY", "^CNXREALTY": "NSE:CNXREALTY"
}

NIFTY_50_SECTORS = {
    "PHARMA": ["SUNPHARMA", "CIPLA", "DRREDDY", "APOLLOHOSP"],
    "IT": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM"],
    "BANK": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK"],
    "FINANCE": ["BAJFINANCE", "BAJAJFINSV", "HDFCLIFE", "SBILIFE", "SHRIRAMFIN"],
    "ENERGY": ["RELIANCE", "ONGC", "NTPC", "POWERGRID", "COALINDIA", "BPCL"],
    "AUTO": ["TATAMOTORS", "M&M", "MARUTI", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO"],
    "METAL": ["TATASTEEL", "JSWSTEEL", "HINDALCO"],
    "FMCG": ["ITC", "HINDUNILVR", "NESTLEIND", "BRITANNIA", "TATACONSUM"],
    "INFRA_CEMENT": ["LT", "ULTRACEMCO", "GRASIM"],
    "OTHERS": ["BHARTIARTL", "ASIANPAINT", "TITAN", "ADANIENT", "ADANIPORTS", "TRENT", "BEL"]
}

NIFTY_50 = [stock for sector in NIFTY_50_SECTORS.values() for stock in sector]

FNO_STOCKS = [
    "AARTIIND", "ABB", "ABBOTINDIA", "ABCAPITAL", "ABFRL", "ACC", "ADANIENSOL", "ADANIENT", "ADANIPORTS",
    "ALKEM", "AMBUJACEM", "ANGELONE", "APOLLOHOSP", "APOLLOTYRE", "ASHOKLEY", "ASIANPAINT", "ASTRAL", "ATUL",
    "AUBANK", "AUROPHARMA", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE", "BALKRISIND", "BALRAMCHIN",
    "BANDHANBNK", "BANKBARODA", "BATAINDIA", "BEL", "BERGEPAINT", "BHARATFORG", "BHARTIARTL", "BHEL", "BIOCON",
    "BOSCHLTD", "BPCL", "BRITANNIA", "BSE", "CANBK", "CANFINHOME", "CDSL", "CHAMBLFERT", "CHOLAFIN", "CIPLA",
    "COALINDIA", "COFORGE", "COLPAL", "CONCOR", "COROMANDEL", "CROMPTON", "CUB", "CUMMINSIND", "DABUR", "DALBHARAT",
    "DEEPAKNTR", "DIVISLAB", "DIXON", "DLF", "DRREDDY", "EICHERMOT", "ESCORTS", "EXIDEIND", "FEDERALBNK", "GAIL",
    "GLENMARK", "GMRINFRA", "GNFC", "GODREJCP", "GODREJPROP", "GRANULES", "GRASIM", "GUJGASLTD", "HAL", "HAVELLS",
    "HCLTECH", "HDFCAMC", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDCOPPER", "HINDPETRO", "HINDUNILVR",
    "HUDCO", "ICICIBANK", "ICICIGI", "ICICIPRULI", "IDEA", "IDFCFIRSTB", "IEX", "IGL", "INDHOTEL", "INDIACEM",
    "INDIAMART", "INDIGO", "INDUSINDBK", "INDUSTOWER", "INFY", "IOC", "IPCALAB", "IRCTC", "IRFC", "ITC", "JINDALSTEL",
    "JSWSTEEL", "JUBLFOOD", "KOTAKBANK", "LALPATHLAB", "LAURUSLABS", "LICHSGFIN", "LT", "LTIM", "LTTS", "LUPIN",
    "M&M", "M&MFIN", "MANAPPURAM", "MARICO", "MARUTI", "MCX", "METROPOLIS", "MFSL", "MGL", "MOTHERSON", "MPHASIS",
    "MRF", "MUTHOOTFIN", "NATIONALUM", "NAUKRI", "NAVINFLUOR", "NCC", "NESTLEIND", "NMDC", "NTPC", "OBEROIRLTY",
    "OFSS", "ONGC", "PAGEIND", "PEL", "PERSISTENT", "PETRONET", "PFC", "PIDILITIND", "PIIND", "PNB", "POLYCAB",
    "POWERGRID", "PRESTIGE", "PVRINOX", "RAMCOCEM", "RBLBANK", "RECLTD", "RELIANCE", "SAIL", "SBICARD", "SBILIFE",
    "SBIN", "SHREECEM", "SHRIRAMFIN", "SIEMENS", "SRF", "SUNPHARMA", "SUNTV", "SYNGENE", "TATACHEM", "TATACOMM",
    "TATACONSUM", "TATAMOTORS", "TATAPOWER", "TATASTEEL", "TCS", "TECHM", "TITAN", "TORNTPHARM", "TRENT", "TVSMOTOR",
    "UBL", "ULTRACEMCO", "UPL", "VEDL", "VOLTAS", "WIPRO", "ZEEL", "ZOMATO", "ZYDUSLIFE"
]

def get_minutes_passed():
    now = datetime.now()
    if now.weekday() >= 5 or now.time() > dt_time(15, 30): return 375
    open_time = now.replace(hour=9, minute=15, second=0)
    return min(375, max(1, int((now - open_time).total_seconds() / 60)))

@st.cache_data(ttl=150)
def fetch_all_data():
    port_df = load_portfolio()
    port_stocks = [str(sym).upper().strip() for sym in port_df['Symbol'].tolist() if str(sym).strip() != ""]
    
    all_stocks = set(NIFTY_50 + FNO_STOCKS + port_stocks)
    tkrs = list(INDICES_MAP.keys()) + list(SECTOR_INDICES_MAP.keys()) + [f"{t}.NS" for t in all_stocks if t]
    
    data = yf.download(tkrs, period="2y", progress=False, group_by='ticker', threads=20)
    
    results = []
    minutes = get_minutes_passed()

    nifty_dist = 0.1
    if "^NSEI" in data.columns.levels[0]:
        try:
            n_df = data["^NSEI"].dropna(subset=['Close'])
            if not n_df.empty:
                n_ltp = float(n_df['Close'].iloc[-1])
                n_vwap = (float(n_df['High'].iloc[-1]) + float(n_df['Low'].iloc[-1]) + n_ltp) / 3
                if n_vwap > 0:
                    nifty_dist = abs(n_ltp - n_vwap) / n_vwap * 100
        except:
            pass

    for symbol in data.columns.levels[0]:
        try:
            df = data[symbol].dropna(subset=['Close'])
            if len(df) < 2: continue
            
            ltp = float(df['Close'].iloc[-1])
            open_p = float(df['Open'].iloc[-1])
            prev_c = float(df['Close'].iloc[-2])
            prev_h = float(df['High'].iloc[-2])
            prev_l = float(df['Low'].iloc[-2])
            low = float(df['Low'].iloc[-1])
            high = float(df['High'].iloc[-1])
            
            day_chg = ((ltp - open_p) / open_p) * 100
            net_chg = ((ltp - prev_c) / prev_c) * 100
            
            p_pivot = (prev_h + prev_l + prev_c) / 3
            p_bc = (prev_h + prev_l) / 2
            p_tc = (p_pivot - p_bc) + p_pivot
            cpr_width_pct = abs(p_tc - p_bc) / p_pivot * 100
            is_narrow_cpr = bool(cpr_width_pct <= 0.30) 
            
            high_low = df['High'] - df['Low']
            high_prev_close = (df['High'] - df['Close'].shift(1)).abs()
            low_prev_close = (df['Low'] - df['Close'].shift(1)).abs()
            tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
            atr = tr.ewm(span=14, adjust=False).mean().iloc[-1]

            if 'Volume' in df.columns and not df['Volume'].isna().all() and len(df) >= 6:
                avg_vol_5d = df['Volume'].iloc[-6:-1].mean()
                curr_vol = float(df['Volume'].iloc[-1])
                vol_x = round(curr_vol / ((avg_vol_5d/375) * minutes), 1) if avg_vol_5d > 0 else 0.0
            else: 
                vol_x = 0.0
                curr_vol = 0.0
                
            vwap = (high + low + ltp) / 3
            ema50_d = float(df['Close'].ewm(span=50, adjust=False).mean().iloc[-1]) if len(df) >= 50 else 0.0
            
            is_swing = False
            is_w_pullback = False
            
            latest_w_ema10 = 0
            latest_w_ema50 = 0
            
            df_w = df.resample('W').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()
            
            weekly_net_chg = net_chg
            if len(df_w) >= 2: 
                prev_w_c = float(df_w['Close'].iloc[-2])
                if prev_w_c > 0:
                    weekly_net_chg = ((ltp - prev_w_c) / prev_w_c) * 100
                    
            if len(df_w) >= 75: 
                df_w['EMA_10'] = df_w['Close'].ewm(span=10, adjust=False).mean()
                df_w['EMA_50'] = df_w['Close'].ewm(span=50, adjust=False).mean()
                
                latest_w_ema10 = float(df_w['EMA_10'].iloc[-1])
                latest_w_ema50 = float(df_w['EMA_50'].iloc[-1])
                
                df_w['Trend_Up'] = np.where(df_w['EMA_10'] > df_w['EMA_50'], 1, 0)
                continuous_4w = df_w['Trend_Up'].rolling(window=4).min().iloc[-1] == 1
                
                w_tr = pd.concat([df_w['High'] - df_w['Low'], (df_w['High'] - df_w['Close'].shift(1)).abs(), (df_w['Low'] - df_w['Close'].shift(1)).abs()], axis=1).max(axis=1)
                w_atr14 = w_tr.ewm(alpha=1/14, adjust=False).mean()
                
                w_plus_dm = df_w['High'].diff()
                w_minus_dm = df_w['Low'].shift(1) - df_w['Low']
                
                w_plus_dm = w_plus_dm.where((w_plus_dm > w_minus_dm) & (w_plus_dm > 0), 0.0)
                w_minus_dm = w_minus_dm.where((w_minus_dm > w_plus_dm) & (w_minus_dm > 0), 0.0)
                
                w_plus_di = 100 * (w_plus_dm.ewm(alpha=1/14, adjust=False).mean() / w_atr14)
                w_minus_di = 100 * (w_minus_dm.ewm(alpha=1/14, adjust=False).mean() / w_atr14)
                
                w_dx = (w_plus_di - w_minus_di).abs() / (w_plus_di + w_minus_di) * 100
                w_adx = w_dx.ewm(alpha=1/14, adjust=False).mean().iloc[-1]
                
                recent_w_low = df_w['Low'].iloc[-2:].min()
                touch_ema = recent_w_low <= (latest_w_ema10 * 1.002) 
                bounce = ltp > latest_w_ema10 
                catch_early = ltp <= (latest_w_ema10 * 1.02)
                
                if continuous_4w and touch_ema and bounce and catch_early and (w_adx >= 15):
                    is_w_pullback = True

            if len(df) >= 100:
                ema20_w = latest_w_ema10 if latest_w_ema10 > 0 else 0
                delta = df['Close'].diff()
                gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
                loss = -delta.clip(upper=0).ewm(alpha=1/14, adjust=False).mean()
                loss = loss.replace(0, np.nan)
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs))
                current_rsi = rsi.fillna(100).iloc[-1]
                
                if (ltp > ema50_d) and (ltp > ema20_w) and (current_rsi >= 55) and (net_chg > 0):
                    is_swing = True

            score = 0
            stock_dist = abs(ltp - vwap) / vwap * 100 if vwap > 0 else 0
            effective_nifty = max(nifty_dist, 0.25) 
            
            if stock_dist > (effective_nifty * 3): score += 5
            elif stock_dist > (effective_nifty * 2): score += 3
            
            if abs(open_p - low) <= (ltp * 0.003) or abs(open_p - high) <= (ltp * 0.003): score += 3 
            if vol_x > 1.0: score += 3 
            if (ltp >= high * 0.998 and day_chg > 0.5) or (ltp <= low * 1.002 and day_chg < -0.5): score += 1
            if (ltp > (low * 1.01) and ltp > vwap) or (ltp < (high * 0.99) and ltp < vwap): score += 1
            
            is_index = symbol in INDICES_MAP
            is_sector = symbol in SECTOR_INDICES_MAP
            disp_name = INDICES_MAP.get(symbol, SECTOR_INDICES_MAP.get(symbol, symbol.replace(".NS", "")))
            
            stock_sector = "OTHER"
            if not is_index and not is_sector:
                for sec, stocks in NIFTY_50_SECTORS.items():
                    if disp_name in stocks:
                        stock_sector = sec
                        break
                
            results.append({
                "Fetch_T": symbol, "T": disp_name, "P": ltp, "O": open_p, "H": high, "L": low, "Prev_C": prev_c,
                "Prev_H": prev_h, "Prev_L": prev_l, "W_EMA10": latest_w_ema10, "W_EMA50": latest_w_ema50, "D_EMA50": ema50_d,
                "Day_C": day_chg, "C": net_chg, "W_C": float(weekly_net_chg), "S": score, "VolX": vol_x, "Is_Swing": is_swing,
                "Is_W_Pullback": is_w_pullback, "VWAP": vwap,
                "ATR": atr, "Narrow_CPR": is_narrow_cpr,
                "Is_Index": is_index, "Is_Sector": is_sector, "Sector": stock_sector
            })
        except: continue
    return pd.DataFrame(results)

def process_5m_data(df_raw):
    try:
        df_s = df_raw.dropna(subset=['Open', 'High', 'Low', 'Close']).copy()
        if df_s.empty: return pd.DataFrame()
        
        df_s['EMA_10'] = df_s['Close'].ewm(span=10, adjust=False).mean()
        df_s['EMA_20'] = df_s['Close'].ewm(span=20, adjust=False).mean()
        df_s['EMA_50'] = df_s['Close'].ewm(span=50, adjust=False).mean()
        df_s.index = pd.to_datetime(df_s.index)
        
        unique_dates = sorted(list(set(df_s.index.date)))
        target_date = unique_dates[-1] 
        
        df_day = df_s[df_s.index.date == target_date].copy()
        
        if not df_day.empty:
            df_day['Typical_Price'] = (df_day['High'] + df_day['Low'] + df_day['Close']) / 3
            if 'Volume' in df_day.columns and df_day['Volume'].sum() > 0:
                vol_cumsum = df_day['Volume'].cumsum()
                df_day['VWAP'] = (df_day['Typical_Price'] * df_day['Volume']).cumsum() / vol_cumsum.replace(0, np.nan)
                df_day['VWAP'] = df_day['VWAP'].fillna(df_day['Typical_Price'].expanding().mean())
            else: 
                df_day['VWAP'] = df_day['Typical_Price'].expanding().mean()
            
            df_day = df_day.bfill().ffill()
            return df_day
            
        return pd.DataFrame()
    except: return pd.DataFrame()

@st.cache_data(ttl=1800)
def get_news_tag(fetch_sym):
    try:
        tkr = yf.Ticker(fetch_sym)
        news_data = tkr.news
        
        default_link = f"https://finance.yahoo.com/quote/{fetch_sym}"
        
        if news_data and len(news_data) > 0:
            title = news_data[0].get('title', '')
            link = news_data[0].get('link', default_link)
            
            if not link or link == '#': 
                link = default_link
                
            t_low = title.lower()
            tags = "📰"
            
            if any(w in t_low for w in ['result', 'q1', 'q2', 'q3', 'q4', 'earning', 'profit', 'revenue']): tags = "📊"
            elif any(w in t_low for w in ['rbi', 'repo', 'inflation', 'rate']): tags = "🏦"
            elif any(w in t_low for w in ['dividend', 'bonus', 'split']): tags = "💰"
            elif any(w in t_low for w in ['fda', 'usfda', 'us']): tags = "🇺🇸"
            elif any(w in t_low for w in ['order', 'deal', 'win', 'contract', 'pact']): tags = "📝"
            elif any(w in t_low for w in ['budget', 'tax', 'govt', 'policy', 'tariff']): tags = "🏛️"
            elif any(w in t_low for w in ['plunge', 'crash', 'scam', 'fraud', 'sebi', 'probe', 'slump']): tags = "🚨"
            elif any(w in t_low for w in ['surge', 'jump', 'soar', 'buyback', 'rally', 'high']): tags = "🚀"
            
            short_title = (title[:22] + "..") if len(title) > 22 else title
            return f"<a href='{link}' target='_blank' style='color:#58a6ff; text-decoration:none;' title='{title}'>{tags} {short_title}</a>"
        
        return f"<a href='{default_link}' target='_blank' style='color:#8b949e; text-decoration:none;'>🔍 Check News</a>"
    except:
        default_link = f"https://finance.yahoo.com/quote/{fetch_sym}"
        return f"<a href='{default_link}' target='_blank' style='color:#8b949e; text-decoration:none;'>🔍 Check News</a>"

def generate_status(row):
    status = ""
    p = row['P']
    if 'AlphaTag' in row and row['AlphaTag']: status += f"{row['AlphaTag']} "
    if abs(row['O'] - row['L']) < (p * 0.002): status += "O=L🔥 "
    if abs(row['O'] - row['H']) < (p * 0.002): status += "O=H🩸 "
    if row['C'] > 0 and row['Day_C'] > 0 and row['VolX'] > 1.5: status += "Rec⇈ "
    if row['VolX'] > 1.5: status += "VOL🟢 "
    return status.strip()

def render_html_table(df_subset, title, color_class):
    if df_subset.empty: return ""
    html = f'<table class="term-table"><thead><tr><th colspan="8" class="{color_class}">{title}</th></tr><tr style="background-color: #21262d;"><th style="text-align:left; width:16%;">STOCK</th><th style="width:10%;">PRICE</th><th style="width:10%;">DAY%</th><th style="width:10%;">NET%</th><th style="width:8%;">VOL</th><th style="width:20%;">STATUS</th><th style="width:20%;">📰 LATEST NEWS</th><th style="width:6%;">SCORE</th></tr></thead><tbody>'
    for i, (_, row) in enumerate(df_subset.iterrows()):
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        day_color = "text-green" if row['Day_C'] >= 0 else "text-red"
        net_color = "text-green" if row['C'] >= 0 else "text-red"
        status = generate_status(row)
        news_html = get_news_tag(row['Fetch_T'])
        html += f'<tr class="{bg_class}"><td class="t-symbol {net_color}"><a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank">{row["T"]}</a></td><td>{row["P"]:.2f}</td><td class="{day_color}">{row["Day_C"]:.2f}%</td><td class="{net_color}">{row["C"]:.2f}%</td><td>{row["VolX"]:.1f}x</td><td style="font-size:10px;">{status}</td><td style="font-size:10px; text-align:left;">{news_html}</td><td style="color:#ffd700;">{int(row["S"])}</td></tr>'
    html += "</tbody></table>"
    return html

def render_portfolio_table(df_port, df_stocks, weekly_trends):
    if df_port.empty: return "<div style='padding:20px; text-align:center; color:#8b949e; border: 1px dashed #30363d; border-radius:8px;'>Portfolio is empty. Add a stock using the option below!</div>"
    
    html = f'<table class="term-table"><thead><tr><th colspan="11" class="term-head-port">💼 LIVE PORTFOLIO TERMINAL</th></tr><tr style="background-color: #21262d;"><th style="text-align:left; width:10%;">STOCK</th><th style="width:8%;">DATE</th><th style="width:5%;">QTY</th><th style="width:7%;">AVG</th><th style="width:7%;">LTP</th><th style="width:10%;">WK TREND</th><th style="width:9%;">STATUS</th><th style="width:16%;">📰 LATEST NEWS</th><th style="width:9%;">DAY P&L</th><th style="width:9%;">TOT P&L</th><th style="width:10%;">P&L %</th></tr></thead><tbody>'
    
    total_invested, total_current, total_day_pnl = 0, 0, 0
    
    for i, (_, row) in enumerate(df_port.iterrows()):
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        sym = str(row['Symbol']).upper().strip()
        try: qty = float(row['Quantity'])
        except: qty = 0
        try: buy_p = float(row['Buy_Price'])
        except: buy_p = 0
        
        date_val = str(row.get('Date', '-'))
        if date_val in ['nan', 'NaN', '']: date_val = '-'
        
        live_row = df_stocks[df_stocks['T'] == sym]
        status_html, trend_html = "", "➖"
        news_html = "-"
        
        if not live_row.empty:
            ltp = float(live_row['P'].iloc[0])
            prev_c = float(live_row['Prev_C'].iloc[0])
            status_html = generate_status(live_row.iloc[0])
            fetch_t = live_row['Fetch_T'].iloc[0]
            news_html = get_news_tag(fetch_t)
            
            trend_state = weekly_trends.get(fetch_t, "Neutral")
            if trend_state == 'Bullish': trend_html = "🟢 Bullish"
            elif trend_state == 'Bearish': trend_html = "🔴 Bearish"
            else: trend_html = "⚪ Neutral"
        else:
            ltp, prev_c = buy_p, buy_p
            status_html = "Search Error"
            
        invested = buy_p * qty
        current = ltp * qty
        overall_pnl = current - invested
        pnl_pct = (overall_pnl / invested * 100) if invested > 0 else 0
        day_pnl = (ltp - prev_c) * qty
        
        total_invested += invested
        total_current += current
        total_day_pnl += day_pnl
        
        tpnl_color = "text-green" if overall_pnl >= 0 else "text-red"
        dpnl_color = "text-green" if day_pnl >= 0 else "text-red"
        t_sign = "+" if overall_pnl > 0 else ""
        d_sign = "+" if day_pnl > 0 else ""
        
        html += f'<tr class="{bg_class}"><td class="t-symbol {tpnl_color}"><a href="https://in.tradingview.com/chart/?symbol=NSE:{sym}" target="_blank">{sym}</a></td><td>{date_val}</td><td>{int(qty)}</td><td>{buy_p:.2f}</td><td>{ltp:.2f}</td><td style="font-size:10px;">{trend_html}</td><td style="font-size:10px;">{status_html}</td><td style="font-size:10px; text-align:left;">{news_html}</td><td class="{dpnl_color}">{d_sign}{day_pnl:,.0f}</td><td class="{tpnl_color}">{t_sign}{overall_pnl:,.0f}</td><td class="{tpnl_color}">{t_sign}{pnl_pct:.2f}%</td></tr>'
    
    overall_total_pnl = total_current - total_invested
    overall_total_pct = (overall_total_pnl / total_invested * 100) if total_invested > 0 else 0
    o_color = "text-green" if overall_total_pnl >= 0 else "text-red"
    o_sign = "+" if overall_total_pnl > 0 else ""
    d_color = "text-green" if total_day_pnl >= 0 else "text-red"
    d_sign = "+" if total_day_pnl > 0 else ""
    
    html += f'<tr class="port-total"><td colspan="8" style="text-align:right; padding-right:15px; font-size:12px;">INVESTED: ₹{total_invested:,.0f} &nbsp;|&nbsp; CURRENT: ₹{total_current:,.0f} &nbsp;|&nbsp; OVERALL P&L:</td><td class="{d_color}">{d_sign}₹{total_day_pnl:,.0f}</td><td class="{o_color}">{o_sign}₹{overall_total_pnl:,.0f}</td><td class="{o_color}">{o_sign}{overall_total_pct:.2f}%</td></tr>'
    html += "</tbody></table>"
    return html

def render_portfolio_swing_advice_table(df_port, df_stocks, weekly_trends):
    if df_port.empty: return ""
    html = f'<table class="term-table"><thead><tr><th colspan="9" class="term-head-swing">🤖 PORTFOLIO SWING ADVISOR (ACTION & LEVELS)</th></tr><tr style="background-color: #21262d;"><th style="text-align:left; width:13%;">STOCK</th><th style="width:8%;">AVG PRICE</th><th style="width:8%;">LTP</th><th style="width:8%;">P&L %</th><th style="width:10%;">WK TREND</th><th style="width:15%;">📰 LATEST NEWS</th><th style="width:12%; color:#f85149;">🛑 TRAILING SL</th><th style="width:12%; color:#3fb950;">🎯 NEXT TARGET</th><th style="width:14%;">💡 ACTION ADVICE</th></tr></thead><tbody>'

    for i, (_, row) in enumerate(df_port.iterrows()):
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        sym = str(row['Symbol']).upper().strip()
        try: buy_p = float(row['Buy_Price'])
        except: buy_p = 0

        live_row = df_stocks[df_stocks['T'] == sym]
        if live_row.empty: continue
        live_data = live_row.iloc[0]

        ltp = float(live_data['P'])
        pnl_pct = ((ltp - buy_p) / buy_p * 100) if buy_p > 0 else 0
        pnl_color = "text-green" if pnl_pct >= 0 else "text-red"
        t_sign = "+" if pnl_pct > 0 else ""

        trend_state = weekly_trends.get(live_data['Fetch_T'], "Neutral")
        is_swing = live_data['Is_Swing']
        atr_val = live_data.get("ATR", ltp * 0.02)
        news_html = get_news_tag(live_data['Fetch_T'])

        advice = ""
        adv_color = ""

        if trend_state == 'Bullish' and is_swing:
            advice = "🚀 STRONG HOLD"
            adv_color = "color:#3fb950; font-weight:bold;"
        elif trend_state == 'Bullish':
            advice = "🟢 HOLD"
            adv_color = "color:#2ea043;"
        elif trend_state == 'Neutral':
            advice = "🟡 WATCH"
            adv_color = "color:#ffd700;"
        else:
            advice = "🔴 EXIT / SELL"
            adv_color = "color:#f85149; font-weight:bold;"

        if trend_state == 'Bearish':
            sl_val = ltp + (1.5 * atr_val)
            t1_val = ltp - (1.5 * atr_val)
        else:
            sl_val = ltp - (1.5 * atr_val)
            if pnl_pct > 5 and sl_val < buy_p: sl_val = buy_p + (ltp * 0.005) 
            t1_val = ltp + (3.0 * atr_val)

        if trend_state == 'Bullish': trend_html = "🟢 Bull"
        elif trend_state == 'Bearish': trend_html = "🔴 Bear"
        else: trend_html = "⚪ Neut"

        row_str = f'<tr class="{bg_class}"><td class="t-symbol"><a href="https://in.tradingview.com/chart/?symbol=NSE:{sym}" target="_blank">{sym}</a></td>'
        row_str += f'<td>{buy_p:.2f}</td><td>{ltp:.2f}</td><td class="{pnl_color}">{t_sign}{pnl_pct:.2f}%</td><td style="font-size:10px;">{trend_html}</td>'
        row_str += f'<td style="font-size:10px; text-align:left;">{news_html}</td><td style="color:#f85149; font-weight:bold;">{sl_val:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t1_val:.2f}</td><td style="{adv_color}">{advice}</td></tr>'
        html += row_str

    html += "</tbody></table>"
    return html

def render_swing_terminal_table(df_subset):
    if df_subset.empty: return "<div style='padding:20px; text-align:center; color:#8b949e; border: 1px dashed #30363d; border-radius:8px;'>No Swing Trading Setups found right now.</div>"
    
    df_sorted = df_subset.reset_index(drop=True)
    html = f'<table class="term-table"><thead><tr><th colspan="11" class="term-head-swing">🌊 SWING TRADING RADAR (RANKED ALGORITHM)</th></tr><tr style="background-color: #21262d;"><th style="width:4%;">RANK</th><th style="text-align:left; width:11%;">STOCK</th><th style="width:7%;">LTP</th><th style="width:7%;">DAY%</th><th style="width:7%;">VOL</th><th style="width:13%;">STATUS</th><th style="width:17%;">📰 LATEST NEWS</th><th style="width:9%; color:#f85149;">🛑 STOP LOSS</th><th style="width:9%; color:#3fb950;">🎯 TARGET 1</th><th style="width:9%; color:#3fb950;">🎯 TARGET 2</th><th style="width:7%;">SCORE</th></tr></thead><tbody>'
    for i, row in df_sorted.iterrows():
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        day_color = "text-green" if row['Day_C'] >= 0 else "text-red"
        status = generate_status(row)
        news_html = get_news_tag(row['Fetch_T'])
        
        w_ema10 = float(row['W_EMA10'])
        w_ema50 = float(row['W_EMA50'])
        ltp = float(row['P'])
        if ltp > w_ema10 and w_ema10 >= w_ema50: trend_state = 'Bullish'
        elif ltp < w_ema10 and w_ema10 <= w_ema50: trend_state = 'Bearish'
        else: trend_state = 'Neutral'

        is_down = trend_state == 'Bearish' or (trend_state == 'Neutral' and row['C'] < 0)
        
        if trend_state == 'Bullish': status += " 🟢Trend"
        elif trend_state == 'Bearish': status += " 🔴Trend"
        
        atr_val = row.get("ATR", row["P"] * 0.02)
        sl_val = row.get('SL', row["P"] + (1.5 * atr_val) if is_down else row["P"] - (1.5 * atr_val))
        t1_val = row.get('T1', row["P"] - (1.5 * atr_val) if is_down else row["P"] + (1.5 * atr_val))
        t2_val = row.get('T2', row["P"] - (3.0 * atr_val) if is_down else row["P"] + (3.0 * atr_val))
            
        rank_badge = f"🏆 1" if i == 0 else f"{i+1}"
        row_str = f'<tr class="{bg_class}"><td><b>{rank_badge}</b></td><td class="t-symbol"><a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank">{row["T"]}</a></td>'
        row_str += f'<td>{row["P"]:.2f}</td><td class="{day_color}">{row["Day_C"]:.2f}%</td><td>{row["VolX"]:.1f}x</td><td style="font-size:10px; cursor:help;" title="{status}">{status}</td>'
        row_str += f'<td style="font-size:10px; text-align:left;">{news_html}</td><td style="color:#f85149; font-weight:bold;">{sl_val:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t1_val:.2f}</td>'
        row_str += f'<td style="color:#3fb950; font-weight:bold;">{t2_val:.2f}</td><td style="color:#ffd700;">{int(row["S"])}</td></tr>'
        html += row_str 
        
    html += "</tbody></table>"
    return html

def render_highscore_terminal_table(df_subset):
    if df_subset.empty: return "<div style='padding:20px; text-align:center; color:#8b949e; border: 1px dashed #30363d; border-radius:8px;'>No High Score Stocks found right now.</div>"
    
    df_sorted = df_subset.reset_index(drop=True)
    html = f'<table class="term-table"><thead><tr><th colspan="11" class="term-head-high">🔥 HIGH SCORE RADAR (RANKED INTRADAY MOVERS)</th></tr><tr style="background-color: #21262d;"><th style="width:4%;">RANK</th><th style="text-align:left; width:11%;">STOCK</th><th style="width:7%;">LTP</th><th style="width:7%;">DAY%</th><th style="width:7%;">VOL</th><th style="width:13%;">STATUS</th><th style="width:17%;">📰 LATEST NEWS</th><th style="width:9%; color:#f85149;">🛑 STOP LOSS</th><th style="width:9%; color:#3fb950;">🎯 TARGET 1</th><th style="width:9%; color:#3fb950;">🎯 TARGET 2</th><th style="width:7%;">SCORE</th></tr></thead><tbody>'
    for i, row in df_sorted.iterrows():
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        day_color = "text-green" if row['Day_C'] >= 0 else "text-red"
        
        custom_status = str(row.get('Strategy_Icon', ''))
        if custom_status == "": custom_status = generate_status(row)
        news_html = get_news_tag(row['Fetch_T'])
        
        is_down = row['C'] < 0
        atr_val = row.get("ATR", row["P"] * 0.02)
        sl_val = row.get('SL', row["P"] + (1.5 * atr_val) if is_down else row["P"] - (1.5 * atr_val))
        t1_val = row.get('T1', row["P"] - (1.5 * atr_val) if is_down else row["P"] + (1.5 * atr_val))
        t2_val = row.get('T2', row["P"] - (3.0 * atr_val) if is_down else row["P"] + (3.0 * atr_val))
            
        rank_badge = f"🏆 1" if i == 0 else f"{i+1}"
        row_str = f'<tr class="{bg_class}"><td><b>{rank_badge}</b></td><td class="t-symbol"><a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank">{row["T"]}</a></td>'
        row_str += f'<td>{row["P"]:.2f}</td><td class="{day_color}">{row["Day_C"]:.2f}%</td><td>{row["VolX"]:.1f}x</td><td style="font-size:10px; cursor:help;" title="{custom_status}">{custom_status}</td>'
        row_str += f'<td style="font-size:10px; text-align:left;">{news_html}</td><td style="color:#f85149; font-weight:bold;">{sl_val:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t1_val:.2f}</td>'
        row_str += f'<td style="color:#3fb950; font-weight:bold;">{t2_val:.2f}</td><td style="color:#ffd700;">{int(row["S"])}</td></tr>'
        html += row_str
    html += "</tbody></table>"
    return html

def render_levels_table(df_subset):
    if df_subset.empty: return "<div style='padding:20px; text-align:center; color:#8b949e; border: 1px dashed #30363d; border-radius:8px;'>No Stocks found right now.</div>"
    
    df_sorted = df_subset.reset_index(drop=True)
    html = f'<table class="term-table"><thead><tr><th colspan="11" class="term-head-levels">🎯 INTRADAY TRADING LEVELS (SUPPORT & RESISTANCE)</th></tr><tr style="background-color: #21262d;"><th style="width:4%;">RANK</th><th style="text-align:left; width:11%;">STOCK</th><th style="width:7%;">LTP</th><th style="width:7%;">DAY%</th><th style="width:7%;">VOL</th><th style="width:13%;">STATUS</th><th style="width:17%;">📰 LATEST NEWS</th><th style="width:9%; color:#f85149;">🛑 STOP LOSS</th><th style="width:9%; color:#3fb950;">🎯 TARGET 1</th><th style="width:9%; color:#3fb950;">🎯 TARGET 2</th><th style="width:7%;">SCORE</th></tr></thead><tbody>'
    for i, row in df_sorted.iterrows():
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        day_color = "text-green" if row['Day_C'] >= 0 else "text-red"
        
        custom_status = str(row.get('Strategy_Icon', ''))
        if custom_status == "": custom_status = generate_status(row)
        news_html = get_news_tag(row['Fetch_T'])
        is_down = row['C'] < 0
        
        atr_val = row.get("ATR", row["P"] * 0.02)
        sl_val = row.get('SL', row["P"] + (1.5 * atr_val) if is_down else row["P"] - (1.5 * atr_val))
        t1_val = row.get('T1', row["P"] - (1.5 * atr_val) if is_down else row["P"] + (1.5 * atr_val))
        t2_val = row.get('T2', row["P"] - (3.0 * atr_val) if is_down else row["P"] + (3.0 * atr_val))
            
        rank_badge = f"🏆 1" if i == 0 else f"{i+1}"
        row_str = f'<tr class="{bg_class}"><td><b>{rank_badge}</b></td><td class="t-symbol"><a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank">{row["T"]}</a></td>'
        row_str += f'<td>{row["P"]:.2f}</td><td class="{day_color}">{row["Day_C"]:.2f}%</td><td>{row["VolX"]:.1f}x</td><td style="font-size:10px; cursor:help;" title="{custom_status}">{custom_status}</td>'
        row_str += f'<td style="font-size:10px; text-align:left;">{news_html}</td><td style="color:#f85149; font-weight:bold;">{sl_val:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t1_val:.2f}</td>'
        row_str += f'<td style="color:#3fb950; font-weight:bold;">{t2_val:.2f}</td><td style="color:#ffd700;">{int(row["S"])}</td></tr>'
        html += row_str
    html += "</tbody></table>"
    return html

# 🔥 RENDER CHART (PERFECT WORKING CODE + FIX FOR HIGH/LOW SNAPPING) 🔥
def render_chart(row, df_chart, show_pin=True, key_suffix="", timeframe="Day", show_crosshair=False, show_vol=False):
    display_sym = row['T']
    fetch_sym = row['Fetch_T']
    
    pct_val = float(row.get('W_C', row['C'])) if timeframe == "Weekly Chart" else float(row['C'])
    color_hex = "#da3633" if pct_val < 0 else "#2ea043"
    sign = "+" if pct_val > 0 else ""
    tv_link = f"https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(fetch_sym, 'NSE:' + display_sym)}"
    
    if show_pin and display_sym not in ["NIFTY", "BANKNIFTY", "INDIA VIX", "DOW", "NSDQ"]:
        cb_key = f"cb_{fetch_sym}_{key_suffix}" if key_suffix else f"cb_{fetch_sym}"
        st.checkbox("pin", value=(fetch_sym in st.session_state.pinned_stocks), key=cb_key, on_change=toggle_pin, args=(fetch_sym,), label_visibility="collapsed")
    
    st.markdown(f"""
        <div style='text-align:left; font-size:14px; font-weight:bold; margin-top:3px; margin-bottom:5px; padding-left:30px;'>
            <a href='{tv_link}' target='_blank' style='color:#ffffff; text-decoration:none;'>
                {display_sym} &nbsp;&nbsp; <span style='color:#ffffff;'>₹{row['P']:.2f}</span> &nbsp;&nbsp; <span style='color:{color_hex}; font-size:12px;'>({sign}{pct_val:.2f}%)</span>
            </a>
        </div>
    """, unsafe_allow_html=True)
    
    try:
        if not df_chart.empty:
            min_val = df_chart['Low'].min()
            max_val = df_chart['High'].max()
            y_padding = (max_val - min_val) * 0.1 if (max_val - min_val) != 0 else min_val * 0.005 
            
            my_hover = 'y' if show_crosshair else 'skip'
            
            if show_vol:
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.02, row_heights=[0.75, 0.25])
                
                fig.add_trace(go.Candlestick(
                    x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'], 
                    increasing_line_color='#2ea043', decreasing_line_color='#da3633', showlegend=False, 
                    hoverinfo='skip', name=""
                ), row=1, col=1)
                
                # 🔥 The Fix: Two invisible marker traces. 
                # Plotly's 'closest' hovermode will snap to High when mouse is up, and Low when mouse is down! 🔥
                fig.add_trace(go.Scatter(
                    x=df_chart.index, y=df_chart['High'], mode='markers', marker=dict(color='rgba(0,0,0,0)', size=1), 
                    showlegend=False, hoverinfo=my_hover, name=""
                ), row=1, col=1)
                fig.add_trace(go.Scatter(
                    x=df_chart.index, y=df_chart['Low'], mode='markers', marker=dict(color='rgba(0,0,0,0)', size=1), 
                    showlegend=False, hoverinfo=my_hover, name=""
                ), row=1, col=1)
                
                if timeframe == "Weekly Chart":
                    if 'EMA_10' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA_10'], mode='lines', line=dict(color='#FFD700', width=1.5), showlegend=False, hoverinfo='skip'), row=1, col=1)
                    if 'EMA_50' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA_50'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), showlegend=False, hoverinfo='skip'), row=1, col=1)
                else:
                    if 'VWAP' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['VWAP'], mode='lines', line=dict(color='#FFD700', width=1.5, dash='dot'), showlegend=False, hoverinfo='skip'), row=1, col=1)
                    if 'EMA_10' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA_10'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), showlegend=False, hoverinfo='skip'), row=1, col=1)
                
                colors = ['#2ea043' if close >= open_p else '#da3633' for close, open_p in zip(df_chart['Close'], df_chart['Open'])]
                fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Volume'], marker_color=colors, showlegend=False, hoverinfo='skip'), row=2, col=1)
                
                fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=230, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_rangeslider_visible=False)
                
                if fetch_sym in st.session_state.custom_alerts:
                    alert_data = st.session_state.custom_alerts[fetch_sym]
                    if alert_data['enabled']:
                        line_c = "#3fb950" if "Above" in alert_data['type'] else "#f85149"
                        fig.add_hline(y=alert_data['price'], line_dash="dash", line_color=line_c, line_width=1.5, opacity=0.8, row=1, col=1)

                if show_crosshair:
                    fig.update_layout(hovermode='closest', dragmode='crosshair', hoverlabel=dict(bgcolor="#161b22", font_size=12, font_color="#ffffff", bordercolor="#30363d"))
                    fig.update_yaxes(showspikes=True, spikemode='across', spikesnap='cursor', showspikelabels=True, spikethickness=1, spikedash='dot', spikecolor="rgba(255,255,255,0.7)", showgrid=False, zeroline=False, showticklabels=True, side='right', tickfont=dict(color="#ffffff", size=10), showline=False, fixedrange=True, range=[min_val - y_padding, max_val + y_padding], row=1, col=1)
                    fig.update_xaxes(showspikes=False, showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True, row=1, col=1)
                    
                    fig.update_yaxes(visible=False, fixedrange=True, row=2, col=1)
                    fig.update_xaxes(visible=False, fixedrange=True, row=2, col=1)
                else:
                    fig.update_layout(hovermode=False, dragmode=False)
                    fig.update_yaxes(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True, range=[min_val - y_padding, max_val + y_padding], row=1, col=1)
                    fig.update_xaxes(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True, row=1, col=1)
                    
                    fig.update_yaxes(visible=False, fixedrange=True, row=2, col=1)
                    fig.update_xaxes(visible=False, fixedrange=True, row=2, col=1)

            else:
                fig = go.Figure()
                fig.add_trace(go.Candlestick(
                    x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'], 
                    increasing_line_color='#2ea043', decreasing_line_color='#da3633', showlegend=False, hoverinfo='skip', name=""
                ))
                
                # 🔥 The Fix: Two invisible marker traces. 
                fig.add_trace(go.Scatter(
                    x=df_chart.index, y=df_chart['High'], mode='markers', marker=dict(color='rgba(0,0,0,0)', size=1), 
                    showlegend=False, hoverinfo=my_hover, name=""
                ))
                fig.add_trace(go.Scatter(
                    x=df_chart.index, y=df_chart['Low'], mode='markers', marker=dict(color='rgba(0,0,0,0)', size=1), 
                    showlegend=False, hoverinfo=my_hover, name=""
                ))
                
                if timeframe == "Weekly Chart":
                    if 'EMA_10' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA_10'], mode='lines', line=dict(color='#FFD700', width=1.5), hoverinfo='skip'))
                    if 'EMA_50' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA_50'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), hoverinfo='skip'))
                else:
                    if 'VWAP' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['VWAP'], mode='lines', line=dict(color='#FFD700', width=1.5, dash='dot'), hoverinfo='skip'))
                    if 'EMA_10' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA_10'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), hoverinfo='skip'))
                    
                fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=190, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', showlegend=False, xaxis_rangeslider_visible=False)

                if fetch_sym in st.session_state.custom_alerts:
                    alert_data = st.session_state.custom_alerts[fetch_sym]
                    if alert_data['enabled']:
                        line_c = "#3fb950" if "Above" in alert_data['type'] else "#f85149"
                        fig.add_hline(y=alert_data['price'], line_dash="dash", line_color=line_c, line_width=1.5, opacity=0.8)

                if show_crosshair:
                    fig.update_layout(hovermode='closest', dragmode='crosshair', hoverlabel=dict(bgcolor="#161b22", font_size=12, font_color="#ffffff", bordercolor="#30363d"))
                    fig.update_yaxes(showspikes=True, spikemode='across', spikesnap='cursor', showspikelabels=True, spikethickness=1, spikedash='dot', spikecolor="rgba(255,255,255,0.7)", showgrid=False, zeroline=False, showticklabels=True, side='right', tickfont=dict(color="#ffffff", size=10), showline=False, fixedrange=True, range=[min_val - y_padding, max_val + y_padding])
                    fig.update_xaxes(showspikes=False, showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True)
                else:
                    fig.update_layout(hovermode=False, dragmode=False)
                    fig.update_yaxes(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True, range=[min_val - y_padding, max_val + y_padding])
                    fig.update_xaxes(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True)

            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False}, key=f"plot_{fetch_sym}_{key_suffix}_{timeframe}_{show_vol}_{show_crosshair}")
        else: 
            st.markdown("<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888;'>Data not available</div>", unsafe_allow_html=True)
    except Exception as e: 
        st.markdown(f"<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888;'>Chart error</div>", unsafe_allow_html=True)

def render_chart_grid(df_grid, show_pin_option, key_prefix, timeframe="Day", chart_dict=None, show_crosshair=False, show_vol=False):
    if df_grid.empty: return
    if chart_dict is None: chart_dict = {}
    with st.container():
        st.markdown("<div class='fluid-board'></div>", unsafe_allow_html=True)
        for j, (_, row) in enumerate(df_grid.iterrows()):
            with st.container():
                render_chart(row, chart_dict.get(row['Fetch_T'], pd.DataFrame()), show_pin=show_pin_option, key_suffix=f"{key_prefix}_{j}", timeframe=timeframe, show_crosshair=show_crosshair, show_vol=show_vol)

def render_closed_trades_table(df_closed):
    if df_closed.empty: return "<div style='padding:20px; text-align:center; color:#8b949e; border: 1px dashed #30363d; border-radius:8px;'>No closed trades yet. Sell a stock to book P&L!</div>"
    
    html = f'<table class="term-table"><thead><tr><th colspan="7" style="background-color:#4a148c; color:white; text-align:left; padding-left:10px;">📜 CLOSED TRADES (TRADE BOOK & P&L)</th></tr><tr style="background-color: #21262d;"><th style="width:15%; text-align:left;">SELL DATE</th><th style="width:15%; text-align:left;">STOCK</th><th style="width:10%;">QTY</th><th style="width:15%;">BUY AVG</th><th style="width:15%;">SELL AVG</th><th style="width:15%;">REALIZED P&L (₹)</th><th style="width:15%;">P&L %</th></tr></thead><tbody>'
    
    total_realized_pnl = 0
    for i, (_, row) in enumerate(df_closed.iterrows()):
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        sym = row['Symbol']
        qty = int(row['Quantity'])
        buy_p = float(row['Buy_Price'])
        sell_p = float(row['Sell_Price'])
        pnl_rs = float(row['PnL_Rs'])
        pnl_pct = float(row['PnL_Pct'])
        
        total_realized_pnl += pnl_rs
        p_color = "text-green" if pnl_rs >= 0 else "text-red"
        p_sign = "+" if pnl_rs > 0 else ""
        
        html += f'<tr class="{bg_class}"><td style="text-align:left;">{row["Sell_Date"]}</td><td class="t-symbol {p_color}" style="text-align:left;">{sym}</td><td>{qty}</td><td>{buy_p:.2f}</td><td>{sell_p:.2f}</td><td class="{p_color}">{p_sign}{pnl_rs:,.2f}</td><td class="{p_color}">{p_sign}{pnl_pct:.2f}%</td></tr>'
        
    tot_color = "text-green" if total_realized_pnl >= 0 else "text-red"
    tot_sign = "+" if total_realized_pnl > 0 else ""
    html += f'<tr class="port-total"><td colspan="5" style="text-align:right; padding-right:15px; font-size:13px;">NET REALIZED P&L:</td><td colspan="2" class="{tot_color}" style="font-size:14px; text-align:center;">{tot_sign}₹{total_realized_pnl:,.2f}</td></tr>'
    html += "</tbody></table>"
    return html

# --- 6. TOP NAVIGATION & SEARCH ---
c1, c2, c3 = st.columns([0.4, 0.3, 0.3])
with c1: 
    watchlist_mode = st.selectbox("Watchlist", ["High Score Stocks 🔥", "Swing Trading 📈", "Nifty 50 Heatmap", "Day Trading Stocks 🚀", "Terminal Tables 🗃️", "My Portfolio 💼"], index=3, label_visibility="collapsed")
with c2: 
    sort_mode = st.selectbox("Sort By", ["Custom Sort", "Heatmap Marks Up ⭐", "Heatmap Marks Down ⬇️", "% Change Up 🟢", "% Change Down 🔴"], label_visibility="collapsed")
with c3: 
    view_mode = st.radio("Display", ["Heat Map", "Chart 📈"], horizontal=True, label_visibility="collapsed")

# --- UI FOR CHART OPTIONS (Timeframe triggers dynamic sorting) ---
chart_timeframe = "Day Chart"
show_crosshair = False
show_vol = False

if view_mode == "Chart 📈" or watchlist_mode in ["Swing Trading 📈", "My Portfolio 💼"]:
    st.markdown("<div style='padding: 10px; background-color:#161b22; border-radius:8px; border:1px solid #30363d; margin-bottom: 5px; display:flex; justify-content:space-around; align-items:center;'>", unsafe_allow_html=True)
    c_opt1, c_opt2, c_opt3 = st.columns(3)
    with c_opt1:
        if watchlist_mode in ["Swing Trading 📈", "My Portfolio 💼"]:
            chart_timeframe = st.radio("⏳ Timeframe:", ["Day Chart", "Weekly Chart"], horizontal=True, label_visibility="collapsed")
    with c_opt2:
        if view_mode == "Chart 📈": show_crosshair = st.toggle("⌖ Show Crosshair Price")
    with c_opt3:
        if view_mode == "Chart 📈": show_vol = st.toggle("📊 Show Volume Bars")
    st.markdown("</div>", unsafe_allow_html=True)

# --- 7. RENDER LOGIC & TREND ANALYSIS ---
df = fetch_all_data()

if not df.empty:
    all_names = sorted(df[(~df['Is_Sector']) & (~df['Is_Index'])]['T'].unique().tolist())
    
    # 🔥 CUSTOM PRICE ALERT EXPANDER 🔥
    if view_mode == "Chart 📈":
        with st.expander("🔔 Add Custom Price Alert Line", expanded=False):
            ac1, ac2, ac3, ac4, ac5 = st.columns([2, 2, 2, 1, 1])
            with ac1: alert_sym_disp = st.selectbox("Select Stock", ["-- None --"] + all_names, key="alert_sym_sel", label_visibility="collapsed")
            with ac2: alert_price = st.number_input("Alert Price (₹)", min_value=0.0, value=0.0, step=0.5, label_visibility="collapsed")
            with ac3: alert_cond = st.selectbox("Condition", ["Price Above Line 📈", "Price Below Line 📉"], label_visibility="collapsed")
            with ac4: alert_enable = st.toggle("Enable", value=True, key="alert_en_tog")
            with ac5:
                if st.button("➕ Add", use_container_width=True):
                    if alert_sym_disp != "-- None --" and alert_price > 0:
                        f_sym = df[df['T'] == alert_sym_disp]['Fetch_T'].iloc[0]
                        st.session_state.custom_alerts[f_sym] = {'price': alert_price, 'type': alert_cond, 'enabled': alert_enable, 'name': alert_sym_disp}
                        st.rerun()

            if st.session_state.custom_alerts:
                st.markdown("<hr style='margin:10px 0; border-color:#30363d;'>", unsafe_allow_html=True)
                for s_key, a_data in list(st.session_state.custom_alerts.items()):
                    col_a, col_b, col_c = st.columns([4, 1, 1])
                    col_a.write(f"**{a_data['name']}** - Alert if {a_data['type']} **₹{a_data['price']}**")
                    with col_b:
                        if st.button("Toggle", key=f"tog_{s_key}"):
                            st.session_state.custom_alerts[s_key]['enabled'] = not st.session_state.custom_alerts[s_key]['enabled']
                            st.rerun()
                    with col_c:
                        if st.button("Delete", key=f"del_{s_key}"):
                            del st.session_state.custom_alerts[s_key]
                            st.rerun()

    c_search, c_type, c_emp = st.columns([0.4, 0.3, 0.3])
    with c_search:
        search_stock = st.selectbox("🔍 Search & View Chart", ["-- None --"] + all_names)
    
    move_type_filter = "All Moves"
    with c_type:
        if watchlist_mode == "Day Trading Stocks 🚀":
            move_type_filter = st.selectbox("🎯 Strategy Filter", [
                "All Moves", 
                "⚡ Intraday Pro Breakout (Top 5)",
                "🌊 One Sided Only", 
                "🔄 VWAP Reversal",   
                "🎯 Reversals Only", 
                "🏹 Rubber Band Stretch",
                "🏄‍♂️ Momentum Ignition",
                "💥 Narrow CPR Breakout"
            ], index=0)
        elif watchlist_mode == "Swing Trading 📈":
            move_type_filter = st.selectbox("📈 Strategy Filter", ["All Swing Stocks", "🚀 Pro Breakout Strategy", "🌟 Weekly 10EMA Pro"], index=0)
            
    df_indices = df[df['Is_Index']].copy()
    df_indices['Order'] = df_indices['T'].map({"NIFTY": 1, "BANKNIFTY": 2, "INDIA VIX": 3, "DOW": 4, "NSDQ": 5})
    df_indices = df_indices.sort_values('Order')
    
    df_sectors = df[df['Is_Sector']].copy()
    if "Day_C" in df_sectors.columns:
        df_sectors = df_sectors.sort_values(by="Day_C", ascending=False)
    else:
        df_sectors = df_sectors.sort_values(by="C", ascending=False)
    
    df_stocks = df[(~df['Is_Index']) & (~df['Is_Sector'])].copy()
    df_nifty = df_stocks[df_stocks['T'].isin(NIFTY_50)].copy()
    sector_perf = df_nifty.groupby('Sector')['C'].mean().sort_values(ascending=False)
    valid_sectors = [s for s in sector_perf.index if s != "OTHER"]
    
    if valid_sectors:
        top_buy_sector = valid_sectors[0]
        top_sell_sector = valid_sectors[-1]
    else:
        top_buy_sector = "PHARMA" 
        top_sell_sector = "IT" 
        
    df_buy_sector = df_nifty[df_nifty['Sector'] == top_buy_sector].sort_values(by=['S', 'C'], ascending=[False, False])
    df_sell_sector = df_nifty[df_nifty['Sector'] == top_sell_sector].sort_values(by=['S', 'C'], ascending=[False, True])
    df_independent = df_nifty[(~df_nifty['Sector'].isin([top_buy_sector, top_sell_sector])) & (df_nifty['S'] >= 5)].sort_values(by='S', ascending=False).head(8)
    df_broader = df_stocks[(df_stocks['T'].isin(FNO_STOCKS)) & (~df_stocks['T'].isin(NIFTY_50)) & (df_stocks['S'] >= 5)].sort_values(by='S', ascending=False).head(8)

    df_port_saved = load_portfolio()

    if watchlist_mode == "Terminal Tables 🗃️":
        terminal_tickers = pd.concat([df_buy_sector, df_sell_sector, df_independent, df_broader])['Fetch_T'].unique().tolist()
        df_filtered = df_stocks[df_stocks['Fetch_T'].isin(terminal_tickers)]
    elif watchlist_mode == "My Portfolio 💼":
        port_tickers = [f"{str(sym).upper().strip()}.NS" for sym in df_port_saved['Symbol'].tolist() if str(sym).strip() != ""]
        df_filtered = df_stocks[df_stocks['Fetch_T'].isin(port_tickers)]
    elif watchlist_mode == "Nifty 50 Heatmap":
        df_filtered = df_stocks[df_stocks['T'].isin(NIFTY_50)]
    elif watchlist_mode == "Day Trading Stocks 🚀":
        df_filtered = df_stocks[df_stocks['C'].abs() >= 1.0].copy()
    elif watchlist_mode == "Swing Trading 📈":
        df_filtered = df_stocks[(df_stocks['Is_Swing'] == True) | (df_stocks['Is_W_Pullback'] == True)]
    else:
        df_filtered = df_stocks[(df_stocks['S'] >= 11) & (df_stocks['VolX'] >= 1.5)]

    all_display_tickers = list(set(df_indices['Fetch_T'].tolist() + df_filtered['Fetch_T'].tolist() + st.session_state.pinned_stocks))
    
    if search_stock != "-- None --":
        search_fetch_t = df[df['T'] == search_stock]['Fetch_T'].iloc[0]
        if search_fetch_t not in all_display_tickers: all_display_tickers.append(search_fetch_t)
            
    with st.spinner("Fetching Live Market Data & Validating Trends..."):
        five_min_data = yf.download(all_display_tickers, period="5d", interval="5m", progress=False, group_by='ticker', threads=20)

    processed_charts = {}
    weekly_trends = {}
    alpha_tags = {}
    trend_scores = {}

    nifty_dist_5m = 0.1
    if "^NSEI" in five_min_data.columns.levels[0]:
        n_raw = five_min_data["^NSEI"] if isinstance(five_min_data.columns, pd.MultiIndex) else five_min_data
        n_day = process_5m_data(n_raw)
        if not n_day.empty:
            n_ltp = n_day['Close'].iloc[-1]
            n_vwap = n_day['VWAP'].iloc[-1]
            if n_vwap > 0: nifty_dist_5m = abs(n_ltp - n_vwap) / n_vwap * 100

    for sym in all_display_tickers:
        try:
            df_raw = five_min_data[sym] if isinstance(five_min_data.columns, pd.MultiIndex) else five_min_data
        except KeyError:
            df_raw = pd.DataFrame()
            
        df_day = process_5m_data(df_raw)
        processed_charts[sym] = df_day
        
        try:
            sym_row = df[df['Fetch_T'] == sym].iloc[0]
            w_ema10 = float(sym_row['W_EMA10'])
            w_ema50 = float(sym_row['W_EMA50'])
            last_p = float(sym_row['P'])
            
            if last_p > w_ema10 and w_ema10 >= w_ema50: weekly_trends[sym] = 'Bullish'
            elif last_p < w_ema10 and w_ema10 <= w_ema50: weekly_trends[sym] = 'Bearish'
            else: weekly_trends[sym] = 'Neutral'
        except: weekly_trends[sym] = 'Neutral'
            
        if sym in df_filtered['Fetch_T'].tolist() and not df_day.empty:
            last_price = df_day['Close'].iloc[-1]
            last_vwap = df_day['VWAP'].iloc[-1]
            net_chg = df[df['Fetch_T'] == sym]['C'].iloc[0]
            
            alpha_tag = ""
            if len(df_day) >= 50:
                stock_dist_5m = abs(last_price - last_vwap) / last_vwap * 100 if last_vwap > 0 else 0
                effective_nifty_5m = max(nifty_dist_5m, 0.25) 
                if stock_dist_5m > (effective_nifty_5m * 3): alpha_tag = "🚀Alpha-Mover"
                elif stock_dist_5m > (effective_nifty_5m * 2): alpha_tag = "💪Nifty-Beater"
            
            one_sided_tag = ""
            trend_bonus = 0
            
            if len(df_day) >= 12 and last_vwap > 0:
                if net_chg > 0: trend_candles = (df_day['Low'] >= df_day['VWAP']).sum()
                else: trend_candles = (df_day['High'] <= df_day['VWAP']).sum()
                
                total_candles = len(df_day)
                
                if (trend_candles / total_candles) >= 0.85:
                    current_gap_pct = abs(last_price - last_vwap) / last_vwap * 100
                    if current_gap_pct >= 1.50:
                        one_sided_tag = "🌊Mega-1.5%"
                        trend_bonus = 7
                    elif current_gap_pct >= 1.00:
                        one_sided_tag = "🌊Super-1.0%"
                        trend_bonus = 5
                    elif current_gap_pct >= 0.50:
                        one_sided_tag = "🌊Trend-0.5%"
                        trend_bonus = 3
                    else:
                        one_sided_tag = "🌊Trend"
                        trend_bonus = 1
            
            trap_tag = ""
            trap_bonus = 0
            
            if watchlist_mode in ["Day Trading Stocks 🚀", "High Score Stocks 🔥"] and len(df_day) >= 6 and last_vwap > 0:
                curr_open = float(df_day['Open'].iloc[-1])
                day_open = df[df['Fetch_T'] == sym]['O'].iloc[0]
                day_high = df[df['Fetch_T'] == sym]['H'].iloc[0]
                day_low = df[df['Fetch_T'] == sym]['L'].iloc[0]

                morning_spike = (day_high - day_open) / day_open * 100 if day_open > 0 else 0
                morning_drop = (day_open - day_low) / day_open * 100 if day_open > 0 else 0

                if morning_spike >= 1.0 and last_price < last_vwap:
                    if (last_price < curr_open):
                        trap_tag = f"🎯 Reversal Sell 🩸"
                        trap_bonus = 6 

                elif morning_drop >= 1.0 and last_price > last_vwap:
                    if (last_price > curr_open):
                        trap_tag = f"🎯 Reversal Buy 🚀"
                        trap_bonus = 6

            alpha_tags[sym] = f"{alpha_tag} {one_sided_tag} {trap_tag}".strip()
            trend_scores[sym] = trend_bonus + trap_bonus   

    # 🔥 CHECK CUSTOM ALERTS GLOBALLY 🔥
    alerts_triggered_html = ""
    for sym, a_data in st.session_state.custom_alerts.items():
        if a_data['enabled']:
            live_r = df[df['Fetch_T'] == sym]
            if not live_r.empty:
                current_ltp = float(live_r['P'].iloc[0])
                if "Above" in a_data['type'] and current_ltp >= a_data['price']:
                    st.toast(f"🔔 ALERT: {a_data['name']} is ABOVE ₹{a_data['price']}! (LTP: {current_ltp})", icon="🚀")
                    alerts_triggered_html += f"<div style='background-color:#1e5f29; color:white; padding:10px; border-radius:5px; margin-bottom:5px;'><b>🔔 ALERT:</b> {a_data['name']} crossed ABOVE ₹{a_data['price']}! (LTP: {current_ltp})</div>"
                elif "Below" in a_data['type'] and current_ltp <= a_data['price']:
                    st.toast(f"🔔 ALERT: {a_data['name']} is BELOW ₹{a_data['price']}! (LTP: {current_ltp})", icon="🩸")
                    alerts_triggered_html += f"<div style='background-color:#b52524; color:white; padding:10px; border-radius:5px; margin-bottom:5px;'><b>🔔 ALERT:</b> {a_data['name']} crossed BELOW ₹{a_data['price']}! (LTP: {current_ltp})</div>"

    if alerts_triggered_html:
        st.markdown(alerts_triggered_html, unsafe_allow_html=True)

    if not df_filtered.empty:
        df_filtered['AlphaTag'] = df_filtered['Fetch_T'].map(alpha_tags).fillna("")
        df_filtered['Trend_Score'] = df_filtered['Fetch_T'].map(trend_scores).fillna(0)
        df_filtered['S'] = df_filtered['S'] + df_filtered['Trend_Score']
        
        if watchlist_mode == "Day Trading Stocks 🚀":
            base_buy = (
                (df_filtered['P'] > df_filtered['W_EMA10']) & 
                (df_filtered['P'] > df_filtered['W_EMA50']) & 
                (df_filtered['P'] > df_filtered['VWAP']) & 
                (df_filtered['P'] > df_filtered['Prev_C']) & 
                (df_filtered['VolX'] >= 0.8)
            )
            
            base_sell = (
                (df_filtered['P'] < df_filtered['W_EMA10']) & 
                (df_filtered['P'] < df_filtered['W_EMA50']) & 
                (df_filtered['P'] < df_filtered['VWAP']) & 
                (df_filtered['P'] < df_filtered['Prev_C']) & 
                (df_filtered['VolX'] >= 0.8)
            )

            nifty_dist = 0.25 
            nifty_row = df_indices[df_indices['T'] == 'NIFTY']
            if not nifty_row.empty:
                n_h, n_l, n_p = float(nifty_row['H'].iloc[0]), float(nifty_row['L'].iloc[0]), float(nifty_row['P'].iloc[0])
                n_vwap = (n_h + n_l + n_p) / 3
                nifty_dist = min(max(abs(n_p - n_vwap) / n_vwap * 100, 0.25), 0.75)
            
            s_vwap = (df_filtered['H'] + df_filtered['L'] + df_filtered['P']) / 3
            stock_vwap_dist = (df_filtered['P'] - s_vwap).abs() / s_vwap * 100
            
            open_drive_bull = (df_filtered['O'] - df_filtered['L'] <= df_filtered['P'] * 0.003)
            open_drive_bear = (df_filtered['H'] - df_filtered['O'] <= df_filtered['P'] * 0.003)

            strategies_list = [
                "⚡ Intraday Pro Breakout (Top 5)",
                "🌊 One Sided Only", 
                "🔄 VWAP Reversal",   
                "🎯 Reversals Only", 
                "🏹 Rubber Band Stretch",
                "🏄‍♂️ Momentum Ignition",
                "💥 Narrow CPR Breakout"
            ]
            
            strats_to_run = strategies_list if move_type_filter == "All Moves" else [move_type_filter]
            all_dfs = []
            
            for strat in strats_to_run:
                c_buy = pd.Series(False, index=df_filtered.index)
                c_sell = pd.Series(False, index=df_filtered.index)
                icon_str = ""

                if strat == "⚡ Intraday Pro Breakout (Top 5)":
                    c_buy = base_buy & (df_filtered['P'] > df_filtered['O']) & ((df_filtered['H'] - df_filtered['P']) <= (df_filtered['H'] - df_filtered['L']) * 0.30)
                    c_sell = base_sell & (df_filtered['P'] < df_filtered['O']) & ((df_filtered['P'] - df_filtered['L']) <= (df_filtered['H'] - df_filtered['L']) * 0.30)
                    icon_str = "⚡"
                    
                elif strat == "🌊 One Sided Only":
                    c_buy = base_buy & (~df_filtered['AlphaTag'].str.contains("Reversal", na=False)) & (df_filtered['Day_C'] >= 1.5) & (stock_vwap_dist >= (nifty_dist * 1.5)) & (df_filtered['Trend_Score'] >= 3) & open_drive_bull
                    c_sell = base_sell & (~df_filtered['AlphaTag'].str.contains("Reversal", na=False)) & (df_filtered['Day_C'] <= -1.5) & (stock_vwap_dist >= (nifty_dist * 1.5)) & (df_filtered['Trend_Score'] >= 3) & open_drive_bear
                    icon_str = "🌊"
                    
                elif strat == "🔄 VWAP Reversal":
                    c_buy = base_buy & (df_filtered['AlphaTag'].str.contains("Reversal Buy", na=False)) & (df_filtered['Day_C'] >= 1.5) & (stock_vwap_dist >= (nifty_dist * 1.5))
                    c_sell = base_sell & (df_filtered['AlphaTag'].str.contains("Reversal Sell", na=False)) & (df_filtered['Day_C'] <= -1.5) & (stock_vwap_dist >= (nifty_dist * 1.5))
                    icon_str = "🔄"
                    
                elif strat == "🎯 Reversals Only":
                    c_buy = base_buy & (df_filtered['AlphaTag'].str.contains("Reversal Buy", na=False)) & (df_filtered['Day_C'] >= 1.0)
                    c_sell = base_sell & (df_filtered['AlphaTag'].str.contains("Reversal Sell", na=False)) & (df_filtered['Day_C'] <= -1.0)
                    icon_str = "🎯"

                elif strat == "🏹 Rubber Band Stretch":
                    c_buy = base_buy & (~df_filtered['AlphaTag'].str.contains("Reversal", na=False)) & (df_filtered['Day_C'] >= 2.5)
                    c_sell = base_sell & (~df_filtered['AlphaTag'].str.contains("Reversal", na=False)) & (df_filtered['Day_C'] <= -2.5)
                    icon_str = "🏹"

                elif strat == "🏄‍♂️ Momentum Ignition":
                    c_buy = base_buy & (~df_filtered['AlphaTag'].str.contains("Reversal", na=False)) & (df_filtered['P'] > df_filtered['O']) & (df_filtered['Day_C'] >= 2.0) & ((df_filtered['H'] - df_filtered['P']) <= (df_filtered['H'] - df_filtered['L']) * 0.15)
                    c_sell = base_sell & (~df_filtered['AlphaTag'].str.contains("Reversal", na=False)) & (df_filtered['P'] < df_filtered['O']) & (df_filtered['Day_C'] <= -2.0) & ((df_filtered['P'] - df_filtered['L']) <= (df_filtered['H'] - df_filtered['L']) * 0.15)
                    icon_str = "🏄‍♂️"

                elif strat == "💥 Narrow CPR Breakout":
                    c_buy = base_buy & (df_filtered['Narrow_CPR'] == True) & (~df_filtered['AlphaTag'].str.contains("Reversal", na=False)) & (df_filtered['Day_C'] >= 1.0)
                    c_sell = base_sell & (df_filtered['Narrow_CPR'] == True) & (~df_filtered['AlphaTag'].str.contains("Reversal", na=False)) & (df_filtered['Day_C'] <= -1.0)
                    icon_str = "💥"

                top_buy = df_filtered[c_buy].sort_values(by=['VolX', 'Day_C'], ascending=[False, False]).head(5).copy()
                if not top_buy.empty: top_buy['Strategy_Icon'] = f"{icon_str} BUY"
                
                top_sell = df_filtered[c_sell].sort_values(by=['VolX', 'Day_C'], ascending=[False, True]).head(5).copy()
                if not top_sell.empty: top_sell['Strategy_Icon'] = f"{icon_str} SELL"
                
                all_dfs.append(top_buy)
                all_dfs.append(top_sell)
                
            if all_dfs:
                df_filtered = pd.concat(all_dfs).drop_duplicates(subset=['Fetch_T'])
            else:
                df_filtered = pd.DataFrame(columns=df_filtered.columns)
            
            if not df_filtered.empty:
                df_filtered['T1'] = np.where(df_filtered['Strategy_Icon'].str.contains('BUY', na=False), round(df_filtered['P'] * 1.008, 2), round(df_filtered['P'] * 0.992, 2))
                df_filtered['T2'] = np.where(df_filtered['Strategy_Icon'].str.contains('BUY', na=False), round(df_filtered['P'] * 1.015, 2), round(df_filtered['P'] * 0.985, 2))
                df_filtered['SL'] = np.where(df_filtered['Strategy_Icon'].str.contains('BUY', na=False), round(df_filtered['P'] * 0.992, 2), round(df_filtered['P'] * 1.008, 2))
        
        elif watchlist_mode == "Swing Trading 📈":
            if move_type_filter == "🚀 Pro Breakout Strategy":
                top_body = df_filtered['H'] - df_filtered['P']
                total_range = df_filtered['H'] - df_filtered['L']
                
                breakout_cond = (
                    (df_filtered['P'] > df_filtered['O']) &           
                    (top_body <= (total_range * 0.25)) &              
                    (df_filtered['VolX'] >= 1.5) &                    
                    (df_filtered['Day_C'] >= 2.0) &                   
                    (df_filtered['Is_Swing'] == True)                 
                )
                df_filtered = df_filtered[breakout_cond]
                
            elif move_type_filter == "🌟 Weekly 10EMA Pro":
                df_filtered = df_filtered[df_filtered['Is_W_Pullback'] == True]

    # 🔥 STRICT DYNAMIC SORTING 🔥
    sort_key = "W_C" if chart_timeframe == "Weekly Chart" else "C"
    sort_col = "S"
    
    if sort_mode == "% Change Up 🟢": 
        df_stocks_display = df_filtered.sort_values(by=sort_key, ascending=False)
    elif sort_mode == "% Change Down 🔴": 
        df_stocks_display = df_filtered.sort_values(by=sort_key, ascending=True)
    elif sort_mode == "Heatmap Marks Up ⭐": 
        df_stocks_display = pd.concat([
            df_filtered[df_filtered[sort_key] >= 0].sort_values(by=[sort_col, 'VolX', sort_key], ascending=[False, False, False]), 
            df_filtered[df_filtered[sort_key] < 0].sort_values(by=[sort_col, 'VolX', sort_key], ascending=[False, False, True])
        ])
    elif sort_mode == "Heatmap Marks Down ⬇️": 
        df_stocks_display = pd.concat([
            df_filtered[df_filtered[sort_key] < 0].sort_values(by=[sort_col, 'VolX', sort_key], ascending=[False, False, True]), 
            df_filtered[df_filtered[sort_key] >= 0].sort_values(by=[sort_col, 'VolX', sort_key], ascending=[False, False, False])
        ])
    else:
        df_stocks_display = df_filtered.sort_values(by=[sort_col, 'VolX', sort_key], ascending=[False, False, False])
            
    if watchlist_mode == "Terminal Tables 🗃️" and view_mode == "Heat Map":
        st.markdown(f"<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#e6edf3;'>🗃️ Professional Terminal View</div>", unsafe_allow_html=True)
        
        for df_temp in [df_buy_sector, df_sell_sector, df_independent, df_broader]:
            if not df_temp.empty:
                df_temp['AlphaTag'] = df_temp['Fetch_T'].map(alpha_tags).fillna("")
                df_temp['S'] = df_temp['S'] + df_temp['Fetch_T'].map(trend_scores).fillna(0)
        
        df_buy_sector = df_buy_sector.sort_values(by=['S', 'C'], ascending=[False, False])
        df_sell_sector = df_sell_sector.sort_values(by=['S', 'C'], ascending=[False, True])
        df_independent = df_independent.sort_values(by=['S', 'C'], ascending=[False, False])
        df_broader = df_broader.sort_values(by=['S', 'C'], ascending=[False, False])

        st.markdown(render_html_table(df_buy_sector, f"🚀 BUY LEADER: {top_buy_sector}", "term-head-buy"), unsafe_allow_html=True)
        st.markdown(render_html_table(df_sell_sector, f"🩸 SELL LAGGARD: {top_sell_sector}", "term-head-sell"), unsafe_allow_html=True)
        st.markdown(render_html_table(df_independent, "🌟 INDEPENDENT MOVERS", "term-head-ind"), unsafe_allow_html=True)
        st.markdown(render_html_table(df_broader, "🌌 BROADER MARKET", "term-head-brd"), unsafe_allow_html=True)
        
    elif watchlist_mode == "My Portfolio 💼" and view_mode == "Heat Map":
        st.markdown(render_portfolio_table(df_port_saved, df_stocks, weekly_trends), unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        
        with st.expander("🤖 View Portfolio Swing Advisor (Action & Levels)", expanded=False):
            st.markdown(render_portfolio_swing_advice_table(df_port_saved, df_stocks, weekly_trends), unsafe_allow_html=True)
        
        with st.expander("➕ Search & Add Stock to Portfolio", expanded=False):
            with st.form("portfolio_add_form", clear_on_submit=True):
                c1, c2, c3, c4 = st.columns(4)
                with c1: new_sym = st.text_input("🔍 NSE Symbol", placeholder="e.g. ITC").upper().strip()
                with c2: new_qty = st.number_input("📦 Quantity", min_value=1, value=10)
                with c3: new_price = st.number_input("💰 Buy Price (₹)", min_value=0.0, value=100.0)
                with c4: new_date = st.date_input("📅 Purchase Date")
                
                c5, c6, c7, c8 = st.columns(4)
                with c5: new_sl = st.number_input("🛑 Fixed SL", min_value=0.0, value=0.0)
                with c6: new_t1 = st.number_input("🎯 Target 1", min_value=0.0, value=0.0)
                with c7: new_t2 = st.number_input("🎯 Target 2", min_value=0.0, value=0.0)
                with c8:
                    st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
                    submit_btn = st.form_submit_button("➕ Verify & Add", use_container_width=True)

            if submit_btn:
                if new_sym:
                    with st.spinner(f"Searching NSE for {new_sym}..."):
                        chk_data = yf.download(f"{new_sym}.NS", period="1d", progress=False)
                        if chk_data.empty: st.error(f"❌ '{new_sym}' not found in NSE!")
                        else:
                            new_date_str = new_date.strftime("%d-%b-%Y")
                            if new_sym in df_port_saved['Symbol'].values: 
                                df_port_saved.loc[df_port_saved['Symbol'] == new_sym, ['Buy_Price', 'Quantity', 'Date', 'SL', 'T1', 'T2']] = [new_price, new_qty, new_date_str, new_sl, new_t1, new_t2]
                            else:
                                new_row = pd.DataFrame({"Symbol": [new_sym], "Buy_Price": [new_price], "Quantity": [new_qty], "Date": [new_date_str], "SL": [new_sl], "T1": [new_t1], "T2": [new_t2]})
                                df_port_saved = pd.concat([df_port_saved, new_row], ignore_index=True)
                            save_portfolio(df_port_saved); fetch_all_data.clear(); st.rerun()
                else: st.warning("Type a symbol first!")
        
        if not df_port_saved.empty:
            with st.expander("✏️ Edit Existing Holdings (Targets, Qty, Price)", expanded=False):
                st.markdown("<p style='font-size:12px; color:#888;'><i>Modify your SL, Targets, or Buy Price directly in the table below and click Save.</i></p>", unsafe_allow_html=True)
                edited_df = st.data_editor(
                    df_port_saved, use_container_width=True, hide_index=True,
                    column_config={
                        "Symbol": st.column_config.TextColumn("Stock Symbol", disabled=True),
                        "Quantity": st.column_config.NumberColumn("Quantity", min_value=1, step=1),
                        "Buy_Price": st.column_config.NumberColumn("Buy Average (₹)", min_value=0.0, format="%.2f"),
                        "SL": st.column_config.NumberColumn("Fixed SL", min_value=0.0, format="%.2f"),
                        "T1": st.column_config.NumberColumn("Fixed T1", min_value=0.0, format="%.2f"),
                        "T2": st.column_config.NumberColumn("Fixed T2", min_value=0.0, format="%.2f"),
                        "Date": st.column_config.TextColumn("Date")
                    }
                )
                if st.button("💾 Save Edited Changes", use_container_width=True): save_portfolio(edited_df); fetch_all_data.clear(); st.rerun()

            with st.expander("💸 Sell Stock & Book Profit/Loss", expanded=False):
                with st.form("portfolio_sell_form"):
                    rc1, rc2, rc3, rc4 = st.columns([2, 1, 2, 2])
                    with rc1: sell_sym = st.selectbox("Select Stock to Sell", ["-- Select --"] + df_port_saved['Symbol'].tolist())
                    with rc2: sell_qty = st.number_input("Qty to Sell", min_value=1, value=1)
                    with rc3: sell_price = st.number_input("Exit Price (₹)", min_value=0.0, value=0.0)
                    with rc4: 
                        st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
                        sell_btn = st.form_submit_button("💸 Confirm Sell", use_container_width=True)
                    
                    if sell_btn and sell_sym != "-- Select --" and sell_price > 0:
                        port_row = df_port_saved[df_port_saved['Symbol'] == sell_sym].iloc[0]
                        buy_price = float(port_row['Buy_Price'])
                        current_qty = int(port_row['Quantity'])
                        sell_qty = min(sell_qty, current_qty)
                        
                        pnl_rs = (sell_price - buy_price) * sell_qty
                        pnl_pct = ((sell_price - buy_price) / buy_price) * 100
                        sell_date_str = datetime.now().strftime("%d-%b-%Y")
                        
                        df_closed = load_closed_trades()
                        new_closed_row = pd.DataFrame({"Sell_Date": [sell_date_str], "Symbol": [sell_sym], "Quantity": [sell_qty], "Buy_Price": [buy_price], "Sell_Price": [sell_price], "PnL_Rs": [pnl_rs], "PnL_Pct": [pnl_pct]})
                        df_closed = pd.concat([df_closed, new_closed_row], ignore_index=True)
                        save_closed_trades(df_closed)
                        
                        if sell_qty == current_qty:
                            df_port_saved = df_port_saved[df_port_saved['Symbol'] != sell_sym] 
                        else:
                            df_port_saved.loc[df_port_saved['Symbol'] == sell_sym, 'Quantity'] = current_qty - sell_qty
                        
                        save_portfolio(df_port_saved)
                        fetch_all_data.clear()
                        st.rerun()

            with st.expander("📜 View Trade Book (Closed P&L Ledger)", expanded=False):
                df_closed_view = load_closed_trades()
                st.markdown(render_closed_trades_table(df_closed_view), unsafe_allow_html=True) 
    elif view_mode == "Heat Map":
        if not df_indices.empty:
            html_idx = '<div class="heatmap-grid">'
            for _, row in df_indices.iterrows():
                pct_val = float(row.get('W_C', row['C'])) if chart_timeframe == "Weekly Chart" else float(row['C'])
                bg = "bear-card" if (row['T'] == "INDIA VIX" and pct_val > 0) else ("bull-card" if pct_val > 0 else "neut-card")
                if row['T'] != "INDIA VIX" and pct_val < 0: bg = "bear-card"
                html_idx += f'<a href="https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(row["Fetch_T"])}" target="_blank" class="stock-card {bg}"><div class="t-score">IDX</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{"+" if pct_val>0 else ""}{pct_val:.2f}%</div></a>'
            st.markdown(html_idx + '</div><hr class="custom-hr">', unsafe_allow_html=True)
        
        if not df_sectors.empty:
            html_sec = '<div class="heatmap-grid">'
            for _, row in df_sectors.iterrows():
                pct_val = float(row.get('W_C', row['C'])) if chart_timeframe == "Weekly Chart" else float(row['C'])
                bg = "bull-card" if pct_val > 0 else ("bear-card" if pct_val < 0 else "neut-card")
                html_sec += f'<a href="https://in.tradingview.com/chart/?symbol={TV_SECTOR_URL.get(row["Fetch_T"], "")}" target="_blank" class="stock-card {bg}"><div class="t-score" style="color:#00BFFF;">SEC</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{"+" if pct_val>0 else ""}{pct_val:.2f}%</div></a>'
            st.markdown(html_sec + '</div><hr class="custom-hr">', unsafe_allow_html=True)

        if not df_stocks_display.empty:
            if watchlist_mode == "Day Trading Stocks 🚀":
                df_buy = df_stocks_display[df_stocks_display['Strategy_Icon'].str.contains('BUY', na=False)]
                df_sell = df_stocks_display[df_stocks_display['Strategy_Icon'].str.contains('SELL', na=False)]
            else:
                df_buy = df_stocks_display[df_stocks_display[sort_key] >= 0]
                df_sell = df_stocks_display[df_stocks_display[sort_key] < 0]

            def render_heatmap_section(df_sec, title, title_color):
                st.markdown(f"<div style='font-size:16px; font-weight:bold; margin: 15px 0 5px 0; color:{title_color};'>{title}</div>", unsafe_allow_html=True)
                html_stk = '<div class="heatmap-grid">'
                for _, row in df_sec.iterrows():
                    pct_val = float(row.get('W_C', row['C'])) if chart_timeframe == "Weekly Chart" else float(row['C'])
                    bg = "bull-card" if pct_val > 0 else ("bear-card" if pct_val < 0 else "neut-card")
                    
                    special_icon = f"⭐{int(row['S'])}"
                    if watchlist_mode == "Swing Trading 📈": 
                        special_icon = "🌟" if row.get('Is_W_Pullback', False) else "🚀"
                    elif watchlist_mode == "Day Trading Stocks 🚀": 
                        strat_name = str(row.get('Strategy_Icon', '🚀'))
                        if 'BUY' in strat_name: special_icon = "🟢 BUY"
                        elif 'SELL' in strat_name: special_icon = "🔴 SELL"
                        elif strat_name != "": special_icon = strat_name
                        else: special_icon = "🚀"
                        
                    html_stk += f'<a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank" class="stock-card {bg}"><div class="t-score">{special_icon}</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{"+" if pct_val>0 else ""}{pct_val:.2f}%</div></a>'
                st.markdown(html_stk + '</div>', unsafe_allow_html=True)

            if not df_buy.empty: render_heatmap_section(df_buy, f"🟢 BUY STOCKS ({watchlist_mode})", "#3fb950")
            if not df_sell.empty: render_heatmap_section(df_sell, f"🔴 SELL STOCKS ({watchlist_mode})", "#f85149")
            
            st.markdown('<br>', unsafe_allow_html=True)
            
            if watchlist_mode == "Swing Trading 📈":
                with st.expander("🌊 View Swing Trading Radar (Ranked Table)", expanded=True): st.markdown(render_swing_terminal_table(df_stocks_display), unsafe_allow_html=True)
            elif watchlist_mode == "High Score Stocks 🔥" or watchlist_mode == "Day Trading Stocks 🚀":
                with st.expander("🔥 View Day Trading Radar (Ranked Table)", expanded=True): st.markdown(render_highscore_terminal_table(df_stocks_display), unsafe_allow_html=True)
            else:
                with st.expander("🎯 View Trading Levels (Targets & Stop Loss)", expanded=True): st.markdown(render_levels_table(df_stocks_display), unsafe_allow_html=True)
        else: st.info("No stocks found.")
            
    else: # CHART VIEW
        st.markdown("<br>", unsafe_allow_html=True)
        
        weekly_charts = {}
        if chart_timeframe == "Weekly Chart":
            with st.spinner("Fetching Weekly Chart Data..."):
                display_tkrs = []
                if search_stock != "-- None --": display_tkrs.append(search_fetch_t)
                if watchlist_mode not in ["Terminal Tables 🗃️", "My Portfolio 💼"]:
                    display_tkrs.extend(df_indices['Fetch_T'].tolist())
                display_tkrs.extend(st.session_state.pinned_stocks)
                display_tkrs.extend(df_stocks_display['Fetch_T'].tolist())
                
                display_tkrs = list(set(display_tkrs)) 
                
                if display_tkrs:
                    wk_data = yf.download(display_tkrs, period="2y", interval="1wk", progress=False, group_by='ticker', threads=20)
                    for sym in display_tkrs:
                        try:
                            df_w = wk_data[sym] if isinstance(wk_data.columns, pd.MultiIndex) else wk_data
                            df_w = df_w.dropna(subset=['Close']).copy()
                            if not df_w.empty:
                                df_w['EMA_10'] = df_w['Close'].ewm(span=10, adjust=False).mean()
                                df_w['EMA_50'] = df_w['Close'].ewm(span=50, adjust=False).mean()
                                weekly_charts[sym] = df_w
                        except: pass

        chart_dict_to_use = weekly_charts if chart_timeframe == "Weekly Chart" else processed_charts

        if search_stock != "-- None --":
            render_chart_grid(pd.DataFrame([df[df['T'] == search_stock].iloc[0]]), show_pin_option=True, key_prefix="search", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)
            st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        if watchlist_mode not in ["Terminal Tables 🗃️", "My Portfolio 💼"]:
            render_chart_grid(df_indices, show_pin_option=False, key_prefix="idx", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)
            st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        pinned_df = df[df['Fetch_T'].isin(st.session_state.pinned_stocks)].copy()
        unpinned_df = df_stocks_display[~df_stocks_display['Fetch_T'].isin(pinned_df['Fetch_T'].tolist())]
        
        if not pinned_df.empty:
            st.markdown("<div style='font-size:16px; font-weight:bold; margin-bottom:5px; color:#ffd700;'>📌 Pinned Priority Charts</div>", unsafe_allow_html=True)
            render_chart_grid(pinned_df, show_pin_option=True, key_prefix="pin", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)
            st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        if not unpinned_df.empty:
            if watchlist_mode == "Day Trading Stocks 🚀":
                df_buy_chart = unpinned_df[unpinned_df['Strategy_Icon'].str.contains('BUY', na=False)]
                df_sell_chart = unpinned_df[unpinned_df['Strategy_Icon'].str.contains('SELL', na=False)]
            else:
                df_buy_chart = unpinned_df[unpinned_df[sort_key] >= 0]
                df_sell_chart = unpinned_df[unpinned_df[sort_key] < 0]
                
            if not df_buy_chart.empty:
                st.markdown(f"<div style='font-size:16px; font-weight:bold; margin-top:10px; margin-bottom:5px; color:#3fb950;'>🟢 BUY STOCKS ({watchlist_mode})</div>", unsafe_allow_html=True)
                render_chart_grid(df_buy_chart, show_pin_option=True, key_prefix="main_buy", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)

            if not df_sell_chart.empty:
                st.markdown(f"<div style='font-size:16px; font-weight:bold; margin-top:20px; margin-bottom:5px; color:#f85149;'>🔴 SELL STOCKS ({watchlist_mode})</div>", unsafe_allow_html=True)
                render_chart_grid(df_sell_chart, show_pin_option=True, key_prefix="main_sell", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)

else: st.info("Loading Market Data...")
