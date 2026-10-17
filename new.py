import streamlit as st
import yfinance as yf
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import time
import threading
import concurrent.futures
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo
import html as _html

try:
    from dhanhq import marketfeed
except Exception:
    marketfeed = None

try:
    from dhanhq import DhanContext
except Exception:
    DhanContext = None

# =========================================================
# 🔥 GLOBAL LIVE PRICES (Thread Safe)
# =========================================================

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Market Heatmap", page_icon="📊", layout="wide")

st.markdown("""
    <style>
    div[data-testid="stNotification"] { display: none !important; }
    iframe[title="streamlit_autorefresh.st_autorefresh"] { display: none !important; }
    *[data-stale="true"] { 
        opacity: 1 !important; 
        filter: none !important; 
        transition: none !important; 
    }
    div[data-testid="stElementContainer"] { opacity: 1 !important; }
    </style>
""", unsafe_allow_html=True)

# =========================================================
# 🔒 SHARED STATE — Streamlit prati rerun ki script re-execute chestundi, kabatti module-level dict reset ayyi
# websocket thread rasina prices UI ki raavu. Anduke cache_resource lo pettali.
# =========================================================
@st.cache_resource
def _shared_state():
    return {'prices': {}, 'lock': threading.Lock(), 'diag_lock': threading.Lock(),
            'diag': {'errors': {}, 'last_error': '', 'last_fetch': {}},
            'ws': {'status': 'not started', 'ticks': 0, 'last_tick': 0.0, 'error': '', 'symbols': 0, 'lib': ''},
            'rl_lock': threading.Lock(), 'rl_last': [0.0], 'deadline': [0.0]}


_SS = _shared_state()
LIVE_PRICES_GLOBAL = _SS['prices']
LIVE_PRICES_LOCK = _SS['lock']

# --- 2. GOOGLE SHEETS CONNECTION ---
@st.cache_resource(show_spinner=False)
def init_connection():
    try:
        creds_json = st.secrets["gcp_service_account"]
    except KeyError:
        st.error("❌ Missing 'gcp_service_account' in secrets.toml")
        st.stop()
    # 🔧 FIX: Streamlit Cloud TOML table (dict) / JSON string రెండింటికీ support
    creds_dict = json.loads(creds_json) if isinstance(creds_json, str) else dict(creds_json)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    db_sheet = client.open("Trading_DB")
    p_ws = db_sheet.worksheet("Portfolio")
    t_ws = db_sheet.worksheet("TradeBook")
    exp_ws = db_sheet.worksheet("Expenses")
    dues_ws = db_sheet.worksheet("Fixed_Dues")
    return p_ws, t_ws, exp_ws, dues_ws

try:
    port_ws, trade_ws, exp_ws, dues_ws = init_connection()
except Exception as e:
    st.error(f"గూగుల్ షీట్ కనెక్ట్ అవ్వలేదు బాస్! Error: {e}")
    st.stop()

# --- 3. DATA LOAD & SAVE FUNCTIONS ---
@st.cache_data(ttl=180, show_spinner=False)
def load_portfolio():
    try:
        records = port_ws.get_all_records()
        df = pd.DataFrame(records) if records else pd.DataFrame(columns=['Symbol', 'Buy_Price', 'Quantity', 'Date', 'SL', 'T1', 'T2'])
        if not df.empty and 'Stock Name' in df.columns:
            df.rename(columns={'Stock Name': 'Symbol', 'Buy Price': 'Buy_Price', 'Buy Date': 'Date'}, inplace=True)
            for col in ['SL', 'T1', 'T2']:
                if col not in df.columns: df[col] = 0.0
        return df
    except:
        return pd.DataFrame(columns=['Symbol', 'Buy_Price', 'Quantity', 'Date', 'SL', 'T1', 'T2'])

@st.cache_data(ttl=30, show_spinner=False)
def load_closed_trades():
    try:
        records = trade_ws.get_all_records()
        df = pd.DataFrame(records) if records else pd.DataFrame(columns=['Buy_Date', 'Sell_Date', 'Symbol', 'Quantity', 'Buy_Price', 'Sell_Price', 'PnL_Rs', 'PnL_Pct'])
        if not df.empty and 'Stock Name' in df.columns:
            df.rename(columns={'Stock Name': 'Symbol', 'Buy Price': 'Buy_Price', 'Sell Price': 'Sell_Price', 'Buy Date': 'Buy_Date', 'Sell Date': 'Sell_Date', 'Profit/Loss': 'PnL_Rs'}, inplace=True)
        if 'Buy_Date' not in df.columns:
            df.insert(0, 'Buy_Date', '-')
        if 'PnL_Pct' not in df.columns:
            df['PnL_Pct'] = 0.0
        return df
    except:
        return pd.DataFrame(columns=['Buy_Date', 'Sell_Date', 'Symbol', 'Quantity', 'Buy_Price', 'Sell_Price', 'PnL_Rs', 'PnL_Pct'])

def save_portfolio(df):
    port_ws.clear()
    df = df.fillna("")
    port_ws.update([df.columns.values.tolist()] + df.values.tolist())
    load_portfolio.clear()

def save_closed_trades(df):
    df = df.dropna(how='all').reset_index(drop=True)
    trade_ws.clear()
    df = df.fillna("")
    trade_ws.update([df.columns.values.tolist()] + df.values.tolist())
    load_closed_trades.clear()

# --- 4. AUTO RUN & STATE MANAGEMENT ---
if 'pause_refresh' not in st.session_state:
    st.session_state.pause_refresh = False
if 'pinned_stocks' not in st.session_state:
    st.session_state.pinned_stocks = []
if 'custom_alerts' not in st.session_state:
    st.session_state.custom_alerts = {}
if 'active_sec' not in st.session_state:
    st.session_state.active_sec = None
if 'alert_triggered' not in st.session_state:
    st.session_state.alert_triggered = set()

TOP_SECTOR_STOCKS = {
    "NIFTY IT": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "COFORGE", "PERSISTENT", "LTIM"],
    "NIFTY AUTO": ["TATAMOTORS", "M&M", "MARUTI", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO", "TVSMOTOR", "ASHOKLEY"],
    "NIFTY METAL": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "NMDC", "SAIL", "JINDALSTEL"],
    "NIFTY PHARMA": ["SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", "LUPIN", "AUROPHARMA", "TORNTPHARM"],
    "NIFTY FMCG": ["ITC", "HINDUNILVR", "NESTLEIND", "BRITANNIA", "TATACONSUM", "DABUR", "GODREJCP", "MARICO"],
    "NIFTY ENERGY": ["RELIANCE", "ONGC", "NTPC", "POWERGRID", "COALINDIA", "BPCL", "TATAPOWER", "IOC"],
    "NIFTY REALTY": ["DLF", "GODREJPROP", "OBEROIRLTY", "PRESTIGE", "MACROTECH", "PHOENIXLTD"]
}


st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .block-container { padding-top: 3.5rem !important; padding-bottom: 1rem !important; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .sticky-header) { position: sticky !important; top: 0 !important; z-index: 9999 !important; background-color: #0e1117 !important; padding-top: 15px !important; padding-bottom: 5px !important; border-bottom: 1px solid #30363d !important; }
    .stRadio label, .stRadio p, div[role="radiogroup"] p { color: #ffffff !important; font-weight: normal !important; }
    div.stButton > button p, div.stButton > button span { color: #ffffff !important; font-weight: normal !important; font-size: 14px !important; }
    .t-name { font-size: 13px; font-weight: normal !important; margin-bottom: 2px; }
    .t-price { font-size: 17px; font-weight: normal !important; margin-bottom: 2px; }
    .t-pct { font-size: 12px; font-weight: normal !important; }
    .t-score { position: absolute; top: 3px; left: 3px; font-size: 10px; background: rgba(0,0,0,0.4); padding: 1px 4px; border-radius: 3px; color: #ffd700; font-weight: normal !important; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) { display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important; justify-content: space-between !important; align-items: center !important; gap: 6px !important; width: 100% !important; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) > div[data-testid="stElementContainer"]:has(.filter-marker) { display: none !important; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) > div[data-testid="stElementContainer"] { flex: 1 1 0px !important; min-width: 0 !important; width: 100% !important; }
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
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div[data-testid="stVerticalBlock"] { background-color: #161b22 !important; border: 1px solid #30363d !important; border-radius: 8px !important; padding: 5px !important; position: relative !important; width: 100% !important; }
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div[data-testid="stVerticalBlock"] div[data-testid="stCheckbox"] { position: absolute !important; top: 10px !important; left: 10px !important; z-index: 100 !important; }
    div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:has(div[data-testid="stCheckbox"]) { margin-bottom: -45px !important; position: relative !important; z-index: 50 !important; }
    div[data-testid="stCheckbox"] label { padding: 0 !important; min-height: 0 !important; }
    div.stButton > button { border-radius: 8px !important; border: 1px solid #30363d !important; background-color: #161b22 !important; height: 45px !important; }
    .heatmap-grid { display: grid; grid-template-columns: repeat(10, 1fr); gap: 8px; padding: 5px 0; }
    .stock-card { border-radius: 4px; padding: 8px 4px; text-align: center; text-decoration: none !important; color: white !important; display: flex; flex-direction: column; justify-content: center; height: 90px; position: relative; box-shadow: 0 1px 3px rgba(0,0,0,0.3); transition: transform 0.2s; }
    .stock-card:hover { transform: scale(1.05); z-index: 10; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }
    .bull-card { background-color: #1e5f29 !important; } .bear-card { background-color: #b52524 !important; } .neut-card { background-color: #30363d !important; } 
    .bull-card-2 { background-color: #238636 !important; } .bull-card-3 { background-color: #2ea043 !important; box-shadow: 0 0 10px rgba(46,160,67,0.55); }
    .bear-card-2 { background-color: #d63633 !important; } .bear-card-3 { background-color: #ff4d4d !important; box-shadow: 0 0 10px rgba(248,81,73,0.55); }
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
    .term-head-fund { background-color: #d29922; color: #161b22; text-align: left !important; padding-left: 10px !important; font-size:14px; }
    .row-dark { background-color: #161b22; } .row-light { background-color: #0e1117; }
    .text-green { color: #3fb950; font-weight: bold; } .text-red { color: #f85149; font-weight: bold; }
    .t-symbol { text-align: left !important; font-weight: bold; }
    .port-total { background-color: #21262d; font-weight: bold; font-size: 13px; }
    </style>
""", unsafe_allow_html=True)

# --- 5. DATA SETUP & SECTOR MAPPING ---
INDICES_MAP = {"^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY", "^INDIAVIX": "INDIA VIX", "^GSPC": "SPX", "^GDAXI": "DAX", "INR=X": "USD/INR"}
TV_INDICES_URL = {"^NSEI": "NSE:NIFTY", "^NSEBANK": "NSE:BANKNIFTY", "^INDIAVIX": "NSE:INDIAVIX", "^GSPC": "SP:SPX", "^GDAXI": "XETR:DAX", "INR=X": "FX_IDC:USDINR"}

SECTOR_INDICES_MAP = {
    "^CNXIT": "NIFTY IT", "^CNXAUTO": "NIFTY AUTO", "^CNXMETAL": "NIFTY METAL",
    "^CNXPHARMA": "NIFTY PHARMA", "^CNXFMCG": "NIFTY FMCG", "^CNXENERGY": "NIFTY ENERGY", "^CNXREALTY": "NIFTY REALTY"
}
TV_SECTOR_URL = {
    "^CNXIT": "NSE:CNXIT", "^CNXAUTO": "NSE:CNXAUTO", "^CNXMETAL": "NSE:CNXMETAL",
    "^CNXPHARMA": "NSE:CNXPHARMA", "^CNXFMCG": "NSE:CNXFMCG", "^CNXENERGY": "NSE:CNXENERGY", "^CNXREALTY": "NSE:CNXREALTY"
}
COMMODITY_MAP = { "GC=F": "GOLD", "SI=F": "SILVER", "CL=F": "CRUDE OIL", "NG=F": "NATURAL GAS", "HG=F": "COPPER" }

MUTUAL_FUNDS = {
    "🏆 2026 MORNINGSTAR AWARD WINNERS": [
        "Nippon India Large Cap Fund Direct Growth", "Parag Parikh Flexi Cap Fund Direct Growth",
        "HDFC Mid-Cap Opportunities Fund Direct Growth", "ICICI Prudential Short Term Fund Direct Growth",
        "Kotak Corporate Bond Fund Direct Growth", "ICICI Prudential All Seasons Bond Fund Direct Growth"
    ],
    "⭐ MORNINGSTAR BEST OF BREED (Top Picks)": [
        "Nippon India Large Cap Fund Direct Growth", "Mirae Asset Large & Midcap Fund Direct Growth",
        "Kotak Equity Opportunities Fund Direct Growth", "Franklin India Flexi Cap Fund Direct Growth",
        "Nippon India Multi Cap Fund Direct Growth"
    ],
    "🔥 AGGRESSIVE SMALL CAP (Highest CAGR)": [
        "Quant Small Cap Fund Direct Growth", "Nippon India Small Cap Fund Direct Growth",
        "SBI Small Cap Fund Direct Growth", "Axis Small Cap Fund Direct Growth",
        "Tata Small Cap Fund Direct Growth", "Kotak Small Cap Fund Direct Growth",
        "HDFC Small Cap Fund Direct Growth", "DSP Small Cap Fund Direct Plan Growth",
        "Bandhan Emerging Businesses Fund Direct Growth", "Edelweiss Small Cap Fund Direct Growth"
    ],
    "🚀 HIGH GROWTH MID CAP": [
        "Motilal Oswal Midcap Fund Direct Growth", "Quant Mid Cap Fund Direct Growth",
        "Nippon India Growth Fund Direct Growth", "HDFC Mid-Cap Opportunities Fund Direct Growth",
        "Kotak Emerging Equity Fund Direct Growth", "SBI Magnum Midcap Fund Direct Growth",
        "DSP Midcap Fund Direct Plan Growth", "Axis Midcap Fund Direct Growth",
        "Tata Mid Cap Growth Fund Direct Growth", "Edelweiss Mid Cap Fund Direct Growth"
    ],
    "🌟 CONSISTENT FLEXI & MULTI CAP": [
        "Parag Parikh Flexi Cap Fund Direct Growth", "Quant Active Fund Direct Growth",
        "Quant Flexi Cap Fund Direct Growth", "HDFC Flexi Cap Fund Direct Growth",
        "SBI Flexicap Fund Direct Growth", "Kotak Flexicap Fund Direct Growth",
        "UTI Flexi Cap Fund Direct Growth", "DSP Flexi Cap Fund Direct Plan Growth",
        "Axis Flexi Cap Fund Direct Growth"
    ],
    "🏭 THEMATIC & SECTORAL (Alpha Generators)": [
        "Quant Infrastructure Fund Direct Growth", "SBI PSU Fund Direct Growth",
        "ICICI Prudential Technology Fund Direct Growth", "Tata Digital India Fund Direct Growth",
        "Nippon India Pharma Fund Direct Growth", "ICICI Prudential Infrastructure Fund Direct Growth",
        "SBI Healthcare Opportunities Fund Direct Growth", "Aditya Birla Sun Life PSU Equity Fund Direct Growth",
        "HDFC Defence Fund Direct Growth", "CPSE ETF"
    ],
    "🏛️ STABLE LARGE CAP & VALUE FUNDS": [
        "SBI Contra Fund Direct Growth", "ICICI Prudential Bluechip Fund Direct Growth",
        "SBI Bluechip Fund Direct Growth", "HDFC Top 100 Fund Direct Growth",
        "Mirae Asset Large Cap Fund Direct Growth", "Axis Bluechip Fund Direct Growth",
        "Kotak Bluechip Fund Direct Growth", "Bandhan Sterling Value Fund Direct Growth",
        "Tata Large Cap Fund Direct Growth"
    ]
}

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_mf_performance():
    tasks = []
    for cat, funds_list in MUTUAL_FUNDS.items():
        for name in funds_list:
            tasks.append((name, cat))
            
    def fetch_single(name, cat):
        short_name = name.replace(" Direct Plan Growth", "").replace(" Direct Growth", "")
        try:
            search_url = f"https://api.mfapi.in/mf/search?q={name}"
            search_res = requests.get(search_url, timeout=10).json()
            if not search_res: raise ValueError("Not Found")
            
            direct_results = [r for r in search_res if 'direct' in r['schemeName'].lower() and 'growth' in r['schemeName'].lower()]
            code = direct_results[0]['schemeCode'] if direct_results else search_res[0]['schemeCode']
            
            url = f"https://api.mfapi.in/mf/{code}"
            res = requests.get(url, timeout=12)
            if res.status_code == 200:
                data = res.json()
                nav_data = data.get("data", [])
                if not nav_data: raise ValueError("No Data")
                
                df = pd.DataFrame(nav_data)
                df['date'] = pd.to_datetime(df['date'], dayfirst=True, errors='coerce')
                df['nav'] = pd.to_numeric(df['nav'], errors='coerce')
                df = df.dropna(subset=['nav', 'date'])
                df = df[df['nav'] > 0]
                if df.empty: raise ValueError("Empty")
                
                df = df.sort_values('date').set_index('date')
                last_price = float(df['nav'].iloc[-1])
                
                def get_cagr(years):
                    try:
                        target_date = df.index[-1] - pd.DateOffset(years=years)
                        closest_date = df.index[df.index <= target_date].max()
                        if pd.isna(closest_date): return "N/A"
                        past_price = float(df.loc[closest_date, 'nav'])
                        cagr = ((last_price / past_price) ** (1 / years)) - 1
                        return round(cagr * 100, 2)
                    except: return "N/A"
                
                return {"Category": cat, "Fund Name": short_name, "NAV (₹)": round(last_price, 2),
                    "1Y (%)": get_cagr(1), "3Y CAGR (%)": get_cagr(3), "5Y CAGR (%)": get_cagr(5)}
        except Exception:
            pass
        return {"Category": cat, "Fund Name": short_name, "NAV (₹)": "N/A",
            "1Y (%)": "N/A", "3Y CAGR (%)": "N/A", "5Y CAGR (%)": "N/A"}

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(fetch_single, name, cat) for name, cat in tasks]
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res: results.append(res)
    return pd.DataFrame(results)

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
    "GLENMARK", "GMRAIRPORT", "GNFC", "GODREJCP", "GODREJPROP", "GRANULES", "GRASIM", "GUJGASLTD", "HAL", "HAVELLS",
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
    "UBL", "ULTRACEMCO", "UPL", "VEDL", "VOLTAS", "WIPRO", "ZEEL", "ETERNAL", "ZYDUSLIFE"
]

MIDCAP_150 = [
    "AJANTPHARM", "APARINDS", "BANKINDIA", "CGPOWER", "DELHIVERY", "FORTIS", "INDIANB", "INDIGOPNTS", 
    "IREDA", "KALYANKJIL", "KPITTECH", "LTF", "LODHA", "MAXHEALTH", "MAZDOCK", "NHPC", 
    "NLCINDIA", "OIL", "PAYTM", "PBFINTECH", "PHOENIXLTD", "POONAWALLA", "RVNL", "SJVN", 
    "SONACOMS", "SUNDARMFIN", "SUPREMEIND", "SUZLON", "TATAELXSI", "TORNTPOWER", "UCOBANK", 
    "UNIONBANK", "VIJAYA", "YESBANK"
]

SMALLCAP_250 = [
    "AARTIDRUGS", "AAVAS", "AEGISLOG", "AFFLE", "AJMERA", "AKZOINDIA", "ALEMBICLTD", "ALKYLAMINE", 
    "ALLCARGO", "ARE&M", "AMBER", "ANANDRATHI", "ANURAS", "APLLTD", "APTUS", "ASAHIINDIA", 
    "ASTERDM", "ASTRAZEN", "BAJAJELEC", "BALAMINES", "BALMLAWRIE", "BANARISUG", "BASF", "BDL", 
    "BEML", "BFINVEST", "BHARATRAS", "BIRLACORPN", "BLS", "BOMDYEING", "BRIGADE", "BSOFT", 
    "CAMLINFINE", "CAMS", "CAPLIPOINT", "CARBORUNIV", "CASTROLIND", "CCL", "CEATLTD", "CENTRALBK", 
    "CENTURYPLY", "ABREL", "CERA", "CESC", "CHALET", "CHEMPLASTS", "CHENNPETRO", "CIGNITITEC", 
    "CUB", "CLEAN", "CRAFTSMAN", "CREDITACC", "CSBBANK", "CYIENT", 
    "DATAPATTNS", "DCBBANK", "DCMSHRIRAM", "DEEPAKFERT", "DELTACORP", "DHANUKA", "DBL", "DODLA", 
    "ECLERX", "EIDPARRY", "EIHOTEL", "EQUITASBNK", "ERIS", "ESABINDIA", "EVEREADY", "FACT", 
    "FDC", "FILATEX", "FINCABLES", "FINEORG", "FINPIPE", "FSL", "GABRIEL", 
    "GAEL", "GALAXYSURF", "GARFIBRES", "GATEWAY", "GICRE", "GILLETTE", "GLAXO", "GMDCLTD", 
    "GMMPFAUDLR", "GODREJAGRO", "GODREJIND", "GOKEX", "GRAPHITE", "GREAVESCOT", "GREENLAM", "GREENPANEL", 
    "GRINDWELL", "GSFC", "GSPL", "GUJALKALI", "HAPPSTMNDS", "HATHWAY", "HCG", "HEG", 
    "HEIDELBERG", "HERITGFOOD", "HFCL", "HGS", "HIKAL", "BIRLANU", "HIMATSEIDE", 
    "HINDZINC", "HOMEFIRST", "HONAUT", "HSCL", "EMBDL", "ICIL", "IDBI", 
    "IFBIND", "IIFL", "INDOCO", "INDORAMA", "INFIBEAM", "INGERRAND", 
    "INOXWIND", "INTELLECT", "IOB", "IONEXCHANG", "IRCON", "ISGEC", "ITI", 
    "J&KBANK", "JAGRAN", "JAICORPLTD", "JAMNAAUTO", "JBCHEPHARM", "JCHAC", "JINDALPOLY", "JINDWORLD", 
    "JKCEMENT", "JKLAKSHMI", "JKPAPER", "JKTYRE", "JMFINANCIL", "JPPOWER", 
    "JTEKTINDIA", "JUBLINGREA", "JUBLPHARMA", "JUSTDIAL", "JYOTHYLAB", "KAJARIACER", "KPIL", 
    "KANSAINER", "KARURVYSYA", "KEC", "KEI", "KNRCON", "KOLTEPATIL", "KOPRAN", "KPRMILL", 
    "KRBL", "KSB", "KTKBANK", "LAOPALA", "LATENTVIEW", "LMW", "LEMONTREE", "LINDEINDIA", 
    "LUXIND", "MAHABANK", "CIEINDIA", "MAHLIFE", "MAHLOG", "MAHSCOOTER", "MAITHANALL", "MANALIPETC", 
    "MANINFRA", "MARKSANS", "MASFIN", "MASTEK", "MATRIMONY", "MAYURUNIQ", "MAZDA", "EPIGRAL", 
    "MHRIL", "MIDHANI", "MINDACORP", "UNOMINDA", "MOLDTKPAC", "MONTECARLO", "MOREPENLAB", "MRPL", 
    "MSTCLTD", "MTARTECH", "MUKANDLTD", "NATCOPHARM", "NAVA", "NAVKARCORP", "NAVNETEDUL", "NEOGEN", 
    "NESCO", "NETWORK18", "NEULANDLAB", "NEWGEN", "NFL", "NILKAMAL", "NIPPOBATRY", "NIRAJ", 
    "NOCIL", "NRBBEARING", "NUCLEUS", "OLECTRA", "OMAXE", "ORIENTCEM", "ORIENTELEC", "PCBL", 
    "PCJEWELLER", "PNCINFRA", "POLYMED", "POLYPLEX", "PRAKASH", "PRAXIS", "PRECAM", "PRINCEPIPE", 
    "PRSMJOHNSN", "PSPPROJECT", "PTC", "PUNJABCHEM", "PURVA", "QUESS", "RADICO", "RAILTEL", 
    "RAIN", "RALLIS", "RAMASTEEL", "RAMCOIND", "RAMCOSYS", "RATNAMANI", "RAYMOND", "RBA", 
    "RCF", "REDINGTON", "RELAXO", "REPCOHOME", "RITES", "RKFORGE", "ROLEXRINGS", "ROSSARI", 
    "ROUTE", "RSYSTEMS", "RUCHIRA", "RUPA", "SAFARI", "SAGCEM", "SANGHVIMOV", 
    "SANSERA", "SAPPHIRE", "SARDAEN", "SAREGAMA", "SCHAEFFLER", "SCHAND", "SEAMEC", "SEQUENT", 
    "SFL", "SHALBY", "SHALPAINTS", "SHANKARA", "SHARDACROP", "SHARDAMOTR", "SHILPAMED", "SHOPERSTOP", 
    "SHREYANIND", "SJS", "SKFINDIA", "SNOWMAN", "SOBHA", "SOLARA", "SOMANYCERA", "SONATSOFTW", 
    "SOUTHBANK", "SPANDANA", "SPARC", "STAR", "STARCEMENT", "STCINDIA", "STLTECH", "STOVEKRAFT", 
    "SUBROS", "SUDARSCHEM", "SUMICHEM", "TVSHLDGS", "SUNFLAG", "SUNTECK", "SUPRAJIT", 
    "SURYAROSNI", "COHANCE", "SYMPHONY", "SYRMA", "TASTYBITE", "TCI", "TCIEXP", 
    "TCPLPACK", "TEJASNET", "THANGAMAYL", "THERMAX", "THOMASCOOK", "TIDEWATER", "TIIL", "TIMETECHNO", 
    "TIMKEN", "TIPSMUSIC", "TNPL", "TOKYOPLAST", "TRITURBINE", "TRIVENI", "TTKPRESTIG", 
    "UFO", "UJJIVANSFB", "UNIENTER", "UNIPARTS", "UTIAMC", "VAIBHAVGBL", "VAKRANGEE", "VARROC", 
    "VENKEYS", "VESUVIUS", "VGUARD", "VIDHIING", "VINATIORGA", "VIPIND", "VISAKAIND", "VISHNU", 
    "VTL", "WABAG", "WELCORP", "WELENT", "WELSPUNLIV", "WSTCSTPAPR", 
    "YATHARTH", "ZENSARTECH", "ZENTEC", "ZYDUSWELL"
]

# =========================================================
# 📡 DHAN LAYER (v4) — REST based, real connection check, diagnostics
# ---------------------------------------------------------
#  • "Connected ✅" toast ippudu nijanga token + Data API check chesaake matrame
#  • 5-min candles: /v2/charts/intraday (columnar response: open/high/low/close/volume/timestamp)
#  • Rate limit (≈5 req/sec) respect + 20 sec time budget (migata stocks yfinance nundi)
#  • WebSocket: library version tho sambandham lekunda connect (MarketFeed/DhanFeed), correct keys
#  • Anni errors UI lo kanipistayi (silent `except: pass` ledu)
# =========================================================
DHAN_REST = "https://api.dhan.co/v2"
DHAN_BUDGET_SEC = 20     # Dhan 5-min fetch ki max time per refresh — migata stocks yfinance nundi
DHAN_MIN_GAP = 0.22      # Data API limit ~5 req/sec

if 'shown_dhan_status' not in st.session_state:
    st.session_state.shown_dhan_status = False


def _dhan_creds():
    try:
        s = st.secrets["dhan"]
        cid = str(s["client_id"]).strip().strip('"').strip("'")
        tok = str(s["access_token"]).strip().strip('"').strip("'")
        return cid, tok
    except Exception:
        return "", ""


def _dhan_headers(cid, tok):
    return {"access-token": tok, "client-id": cid, "Content-Type": "application/json", "Accept": "application/json"}


def _dhan_classify(status, body_text, j=None):
    """Dhan error ni artham ayye hint tho cheppadam"""
    code, msg = "", ""
    if isinstance(j, dict):
        code = str(j.get('errorCode') or j.get('error_code') or '')
        msg = str(j.get('errorMessage') or j.get('error_message') or j.get('remarks') or j.get('message') or '')
        data = j.get('data')
        if not msg and isinstance(data, dict):
            msg = "; ".join(f"{k}: {v}" for k, v in data.items())
    blob = f"{code} {msg} {str(body_text)[:120]}".lower()
    if any(x in blob for x in ('dh-902', '806', 'not subscribed', 'data api')):          # mundu check — idi kuda 401 tho vastundi
        hint = "Data API subscription ledu — historical/live data kosam Dhan lo 'Data APIs' plan activate cheyyali"
    elif status in (401, 403) or any(x in blob for x in ('dh-901', 'invalid_authentication', 'expired', 'invalid token')):
        hint = "TOKEN expired/invalid — Dhan lo kotha access token generate chesi secrets lo update cheyyandi (token 24 gantalu matrame)"
    elif status == 429 or any(x in blob for x in ('dh-904', '805', 'too many', 'rate limit')):
        hint = "Rate limit (5 req/sec) cross ayyindi"
    else:
        hint = ""
    return (f"HTTP {status} {code} {msg}".strip() + (f" → {hint}" if hint else ""))[:260]


def _diag_add(kind, msg=""):
    with _SS['diag_lock']:
        d = _SS['diag']
        k = str(kind)[:70]
        d['errors'][k] = d['errors'].get(k, 0) + 1
        if msg:
            d['last_error'] = str(msg)[:260]


def _dhan_rate_wait():
    with _SS['rl_lock']:
        wait = _SS['rl_last'][0] + DHAN_MIN_GAP - time.time()
        if wait > 0:
            time.sleep(wait)
        _SS['rl_last'][0] = time.time()


@st.cache_data(ttl=300, show_spinner=False)
def dhan_health_check(cid, tok):
    out = {'ok': False, 'msg': '', 'expiry': '', 'data_plan': '', 'data_valid': '',
           'checked': datetime.now(ZoneInfo("Asia/Kolkata")).strftime('%H:%M:%S')}
    if not cid or not tok:
        out['msg'] = "secrets.toml lo [dhan] client_id / access_token ledu"
        return out
    last = ""
    for path in ("/profile", "/fundlimit"):
        try:
            r = requests.get(DHAN_REST + path, headers=_dhan_headers(cid, tok), timeout=8)
        except requests.RequestException as e:
            out['msg'] = f"Network error: {type(e).__name__}"
            return out
        if r.status_code == 200:
            out['ok'] = True
            out['msg'] = "Token valid ✅"
            if path == "/profile":
                try:
                    j = r.json()
                    out['expiry'] = str(j.get('tokenValidity', ''))
                    out['data_plan'] = str(j.get('dataPlan', ''))
                    out['data_valid'] = str(j.get('dataValidity', ''))
                except Exception:
                    pass
            return out
        try:
            j = r.json()
        except Exception:
            j = None
        last = _dhan_classify(r.status_code, r.text, j)
        if r.status_code in (401, 403):
            break
    out['msg'] = last or "Unknown error"
    return out


def _dhan_parse_candles(data):
    """Dhan v2 columnar response -> OHLCV DataFrame (naive IST index)"""
    try:
        if isinstance(data, dict) and 'open' in data:
            n = len(data['open'])
            df_ = pd.DataFrame({'Open': data['open'], 'High': data['high'], 'Low': data['low'], 'Close': data['close'],
                                'Volume': data.get('volume') or [0] * n})
            ts_raw = data.get('timestamp') or data.get('start_Time') or data.get('start_time')
            ts = pd.to_numeric(pd.Series(ts_raw if ts_raw is not None else []), errors='coerce')
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            raw = pd.DataFrame(data)
            raw.columns = [str(c).lower() for c in raw.columns]
            tcol = next((c for c in ('timestamp', 'start_time') if c in raw.columns), None)
            if tcol is None:
                return None, "Timestamp column ledu"
            df_ = raw.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'})[
                ['Open', 'High', 'Low', 'Close', 'Volume']]
            ts = pd.to_numeric(raw[tcol], errors='coerce')
        else:
            return None, "Candles ledu (empty response)"
        if len(df_) == 0 or len(ts) != len(df_):
            return None, "Candles ledu / timestamp mismatch"
        base = pd.to_datetime(ts, unit='s', errors='coerce')
        if base.dt.year.min() < 2010:                                    # legacy 1980-epoch (IST) format
            base = pd.to_datetime(ts + 315513000, unit='s', errors='coerce')
        best = None
        for shift in (pd.Timedelta(hours=5, minutes=30), pd.Timedelta(0)):   # NSE candles 09:15 tho start avvali
            cand = base + shift
            mod = cand.dt.hour * 60 + cand.dt.minute
            if 540 <= mod.min() <= 570 and mod.max() <= 935:
                best = cand
                break
        if best is None:
            best = base + pd.Timedelta(hours=5, minutes=30)
        df_.index = pd.DatetimeIndex(best, name='Date')
        for c in ['Open', 'High', 'Low', 'Close', 'Volume']:
            df_[c] = pd.to_numeric(df_[c], errors='coerce')
        df_ = df_.dropna(subset=['Open', 'High', 'Low', 'Close'])
        df_ = df_[~df_.index.isna()].sort_index()
        df_ = df_[~df_.index.duplicated(keep='last')]
        if df_.empty:
            return None, "Valid candles ledu"
        return df_, ""
    except Exception as e:
        return None, f"Parse error: {type(e).__name__}: {str(e)[:80]}"


def _dhan_intraday_df(cid, tok, sec_id, days=7):
    now = datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)
    payload = {"securityId": str(sec_id), "exchangeSegment": "NSE_EQ", "instrument": "EQUITY", "interval": "5", "oi": False,
               "fromDate": (now - pd.Timedelta(days=days)).strftime("%Y-%m-%d 09:15:00"),
               "toDate": now.strftime("%Y-%m-%d %H:%M:%S")}
    r = None
    for attempt in (1, 2):
        _dhan_rate_wait()
        try:
            r = requests.post(f"{DHAN_REST}/charts/intraday", json=payload, headers=_dhan_headers(cid, tok), timeout=12)
        except requests.RequestException as e:
            return None, f"Network error: {type(e).__name__}"
        if r.status_code == 200:
            break
        if attempt == 1 and r.status_code == 429:
            time.sleep(1.0)
            continue
        try:
            j = r.json()
        except Exception:
            j = None
        return None, _dhan_classify(r.status_code, r.text, j)
    try:
        j = r.json()
    except Exception:
        return None, "Response JSON kaadu"
    if isinstance(j, dict) and str(j.get('status', '')).lower() == 'failure':
        return None, _dhan_classify(200, r.text, j)
    data = j.get('data', j) if isinstance(j, dict) else j
    return _dhan_parse_candles(data)


@st.cache_data(ttl=86400, show_spinner=False)
def _load_dhan_sec_map():
    # NOTE: failure ayithe exception raise avvali — appudu cache avvadu (ikkada {} cache ayithe 24 gantalu Dhan vadadu)
    df_ = pd.read_csv("https://images.dhan.co/api-data/api-scrip-master.csv", low_memory=False)
    nse_eq = df_[(df_['SEM_EXM_EXCH_ID'] == 'NSE') & (df_['SEM_INSTRUMENT_NAME'] == 'EQUITY')]
    if 'SEM_SERIES' in nse_eq.columns:
        nse_eq = nse_eq.assign(_p=(nse_eq['SEM_SERIES'] == 'EQ').astype(int)).sort_values('_p')   # duplicates unte EQ series win avvali
    m = dict(zip(nse_eq['SEM_TRADING_SYMBOL'], nse_eq['SEM_SMST_SECURITY_ID'].astype(str)))
    if len(m) < 100:
        raise ValueError(f"Scrip master chala takkuva ({len(m)})")
    return m


def get_dhan_security_map():
    try:
        return _load_dhan_sec_map()
    except Exception as e:
        _diag_add("scrip-master load fail", f"Scrip master: {type(e).__name__}: {str(e)[:100]}")
        return {}


@st.cache_data(ttl=300, show_spinner=False)
def dhan_data_probe(cid, tok, sec_id):
    """Real test: RELIANCE 5-min candles Dhan nundi vastunnaya?"""
    out = {'ok': False, 'msg': '', 'n': 0, 'first': '', 'last': ''}
    df_, err = _dhan_intraday_df(cid, tok, sec_id, days=5)
    if df_ is None:
        out['msg'] = err
        return out
    out.update({'ok': True, 'msg': 'Data API OK ✅', 'n': int(len(df_)),
                'first': df_.index.min().strftime('%d-%b %H:%M'), 'last': df_.index.max().strftime('%d-%b %H:%M')})
    return out


DHAN_USABLE = False     # ⚡ False ఉన్నప్పుడు అసలు Dhan API / 20MB CSV డౌన్‌లోడ్ అవ్వదు
dhan = False
if DHAN_USABLE:
    _DH_CID, _DH_TOK = _dhan_creds()
    _DH_HEALTH = dhan_health_check(_DH_CID, _DH_TOK)
    sec_map = get_dhan_security_map()
    rev_sec_map = {str(v): k for k, v in sec_map.items()}
    _DH_PROBE = dhan_data_probe(_DH_CID, _DH_TOK, sec_map.get("RELIANCE", "2885")) if _DH_HEALTH['ok'] else {'ok': False, 'msg': 'skipped', 'n': 0, 'first': '', 'last': ''}
else:
    _DH_CID, _DH_TOK = "", ""
    _DH_HEALTH = {'ok': False, 'msg': 'Disabled'}
    _DH_PROBE = {'ok': False, 'msg': 'Disabled', 'n': 0, 'first': '', 'last': ''}
    sec_map, rev_sec_map = {}, {}

# if not st.session_state.shown_dhan_status:
#     if DHAN_USABLE:
#         st.toast("Dhan LIVE ✅ (token + Data API verified)", icon="🟢")
#     else:
#         st.toast(f"Dhan ❌ → yfinance vadutunnam: {(_DH_HEALTH['msg'] if not _DH_HEALTH['ok'] else _DH_PROBE['msg'])[:90]}", icon="🔴")
#     st.session_state.shown_dhan_status = True


# --- WEBSOCKET LIVE TICKER (BACKGROUND THREAD) ---
def _ws_handle(msg):
    if not isinstance(msg, dict):
        return
    sid = msg.get('security_id', msg.get('SecurityId', msg.get('securityId')))
    ltp = msg.get('LTP', msg.get('ltp', msg.get('last_price')))
    if sid is None or ltp in (None, ''):
        return
    sym = rev_sec_map.get(str(sid).split('.')[0])
    if not sym:
        return
    try:
        price = float(ltp)
    except Exception:
        return
    if price <= 0:
        return
    with LIVE_PRICES_LOCK:
        LIVE_PRICES_GLOBAL[sym] = price
        n_sym = len(LIVE_PRICES_GLOBAL)
    ws = _SS['ws']
    ws['ticks'] += 1
    ws['last_tick'] = time.time()
    ws['symbols'] = n_sym


def _make_feed(cid, tok, instruments):
    """Library version edaina sare — MarketFeed/DhanFeed, context/legacy rendu try chestundi"""
    if marketfeed is None:
        raise RuntimeError("dhanhq library import avvaledu (requirements.txt lo dhanhq undali)")
    classes = [getattr(marketfeed, n) for n in ('MarketFeed', 'DhanFeed') if hasattr(marketfeed, n)]
    if not classes:
        raise RuntimeError("marketfeed lo MarketFeed/DhanFeed ledu")
    errs = []
    if DhanContext is not None:
        for cls in classes:
            try:
                return cls(DhanContext(cid, tok), instruments, "v2")
            except TypeError as e:
                errs.append(str(e)[:60])
    for cls in classes:
        try:
            return cls(cid, tok, instruments, "v2")
        except TypeError as e:
            errs.append(str(e)[:60])
    raise RuntimeError("Feed create avvaledu: " + " | ".join(errs))


@st.cache_resource(show_spinner=False)
def start_live_ticker(usable, cid, tok, n_sec):
    ws = _SS['ws']
    try:
        import importlib.metadata as _im
        ws['lib'] = _im.version('dhanhq')
    except Exception:
        ws['lib'] = '?'
    if not usable:
        ws['status'] = 'skipped (Dhan token / Data API OK kaadu)'
        return False
    if not sec_map:
        ws['status'] = 'skipped (security map ledu)'
        return False
    nse = getattr(marketfeed, 'NSE', 1) if marketfeed else 1
    tick = getattr(marketfeed, 'Ticker', 15) if marketfeed else 15
    _ws_universe = list(dict.fromkeys(NIFTY_50 + FNO_STOCKS + MIDCAP_150))
    instruments = [(nse, str(sec_map[s]), tick) for s in _ws_universe if s in sec_map][:500]
    chunks = [instruments[i:i + 100] for i in range(0, len(instruments), 100)]
    if not chunks:
        ws['status'] = 'skipped (instruments ledu)'
        return False

    def _worker():
        import asyncio
        backoff = 5
        while True:
            try:
                try:
                    asyncio.set_event_loop(asyncio.new_event_loop())
                except Exception:
                    pass
                ws['status'] = 'connecting…'
                feed = _make_feed(cid, tok, chunks[0])
                feed.run_forever()
                for ch in chunks[1:]:
                    try:
                        feed.subscribe_symbols(ch)
                    except Exception as e:
                        ws['error'] = f"subscribe: {type(e).__name__}: {str(e)[:80]}"
                        break
                ws['status'] = 'connected ✅'
                backoff = 5
                while True:
                    feed.run_forever()
                    _ws_handle(feed.get_data())
            except Exception as e:
                ws['status'] = 'reconnecting…'
                ws['error'] = f"{type(e).__name__}: {str(e)[:120]}"
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)

    threading.Thread(target=_worker, daemon=True).start()
    ws['status'] = 'starting…'
    return True


start_live_ticker(DHAN_USABLE, _DH_CID, _DH_TOK, len(sec_map))


def render_dhan_status():
    """Top status line + diagnostics expander"""
    h, p, ws, dg = _DH_HEALTH, _DH_PROBE, _SS['ws'], _SS['diag']
    lf = dg.get('last_fetch', {})
    if DHAN_USABLE:
        col, icon, head = "#238636", "🟢", "DHAN LIVE"
        why = f"token valid{(' till ' + h['expiry']) if h.get('expiry') else ''}"
    elif h['ok']:
        col, icon, head = "#d29922", "🟡", "DHAN login OK, Data API fail → yfinance"
        why = p['msg']
    else:
        col, icon, head = "#f85149", "🔴", "DHAN not connected → yfinance"
        why = h['msg']
    src = f"5-min: Dhan {lf.get('dhan', 0)} • yfinance {lf.get('yf', 0)}" if lf else "5-min: (fetch inka avvaledu)"
    age = (time.time() - ws['last_tick']) if ws.get('last_tick') else None
    tick = f"Live ticks: {ws.get('symbols', 0)} sym" + (f" ({age:.0f}s ago)" if age is not None else " (market closed / no tick)")
    st.markdown(
        f"<div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;background:#161b22;border:1px solid {col};"
        f"border-radius:8px;padding:6px 12px;margin-bottom:8px;font-size:12.5px;'>"
        f"<span>{icon} <b>{head}</b> <span style='color:#8b949e;'>— {why[:150]}</span></span>"
        f"<span style='color:#8b949e;'>📡 {src} &nbsp;•&nbsp; {tick}</span></div>", unsafe_allow_html=True)
    with st.expander("🔧 Dhan Diagnostics (connection debug)", expanded=not DHAN_USABLE):
        rows = [
            ("1. Credentials (secrets.toml [dhan])", "✅" if (_DH_CID and _DH_TOK) else "❌", f"client_id: {_DH_CID[:3]}…{_DH_CID[-2:]} | token len: {len(_DH_TOK)}" if _DH_CID else "ledu"),
            ("2. Login / token valid", "✅" if h['ok'] else "❌", f"{h['msg']} {('| expiry: ' + h['expiry']) if h.get('expiry') else ''} {('| dataPlan: ' + h['data_plan'] + ' (' + h['data_valid'] + ')') if h.get('data_plan') else ''}"),
            ("3. Scrip master (symbol→ID)", "✅" if sec_map else "❌", f"{len(sec_map)} NSE equity symbols"),
            ("4. 5-min candles (RELIANCE test)", "✅" if p['ok'] else "❌", f"{p['msg']} {('| ' + str(p['n']) + ' candles ' + p['first'] + ' → ' + p['last']) if p['ok'] else ''}"),
            ("5. WebSocket live ticks", "✅" if str(ws.get('status', '')).startswith('connected') else "⚠️", f"{ws.get('status', '-')} | ticks: {ws.get('ticks', 0)} | lib: {ws.get('lib', '?')} {('| err: ' + ws['error']) if ws.get('error') else ''}"),
            ("6. Last 5-min fetch", "ℹ️", f"Dhan {lf.get('dhan', 0)} / yfinance {lf.get('yf', 0)} of {lf.get('total', 0)} in {lf.get('sec', 0)}s @ {lf.get('when', '-')}" if lf else "-"),
        ]
        _wrap = "white-space:normal;word-break:break-word;"
        html_rows = "".join(f"<tr><td style='text-align:left;{_wrap}'>{a}</td><td>{b}</td><td style='text-align:left;color:#c9d1d9;{_wrap}'>{_html.escape(str(c))}</td></tr>" for a, b, c in rows)
        st.markdown(f"<table class='term-table'><thead><tr><th style='text-align:left;width:26%;'>CHECK</th><th style='width:6%;'>OK?</th><th style='text-align:left;'>DETAIL</th></tr></thead><tbody>{html_rows}</tbody></table>", unsafe_allow_html=True)
        if dg.get('errors'):
            st.caption("Errors (ee session lo): " + " • ".join(f"{k} ×{v}" for k, v in list(dg['errors'].items())[:6]))
        st.caption("💡 Dhan access token 24 gantalu matrame valid. Prati roju kotha token generate chesi Streamlit secrets lo update cheyyandi. "
                   "Historical/live data kosam Dhan lo 'Data APIs' plan kuda activate undali. Edi fail ayina app yfinance tho pani chestundi.")
        if st.button("🔄 Re-test Dhan now", key="dhan_retest"):
            dhan_health_check.clear()
            dhan_data_probe.clear()
            fetch_cached_5m_data.clear()
            st.rerun()

def now_ist():
    # 🔧 FIX: Streamlit Cloud server UTC లో run అవుతుంది — అన్ని time checks IST లోనే చేయాలి
    return datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)

def is_market_open():
    n = now_ist()
    return n.weekday() < 5 and dt_time(9, 15) <= n.time() <= dt_time(15, 30)

def get_minutes_passed():
    now = now_ist()
    if now.weekday() >= 5: return 375
    if now.time() < dt_time(9, 15): return 1
    if now.time() > dt_time(15, 30): return 375
    open_time = now.replace(hour=9, minute=15, second=0)
    return min(375, max(1, int((now - open_time).total_seconds() / 60)))

# --- DHAN 5-MIN FETCH ---
def fetch_single_dhan_5m(symbol, sec_id, cid, tok):
    if time.time() > _SS['deadline'][0]:
        return symbol, pd.DataFrame()          # time budget aipoyindi -> yfinance fallback
    df_, err = _dhan_intraday_df(cid, tok, sec_id, days=7)
    if df_ is None:
        _diag_add(err[:60] or "unknown", f"{symbol}: {err}")
        return symbol, pd.DataFrame()
    return symbol, df_


def _sanitize_5m_df(df_in, tkr=None):
    if df_in is None or not isinstance(df_in, pd.DataFrame) or df_in.empty:
        return pd.DataFrame()
    d = df_in.copy()
    if isinstance(d.columns, pd.MultiIndex):
        if tkr and tkr in d.columns.get_level_values(0):
            d = d[tkr].copy()
        elif tkr and tkr in d.columns.get_level_values(-1):
            d = d.xs(tkr, axis=1, level=-1).copy()
        else:
            d.columns = d.columns.get_level_values(-1)
    d = d.loc[:, ~d.columns.duplicated()]
    if 'Close' not in d.columns:
        return pd.DataFrame()
    d = d.dropna(subset=['Close'])
    if d.empty:
        return pd.DataFrame()
    d.index = pd.to_datetime(d.index)
    if d.index.tz is not None:
        d.index = d.index.tz_localize(None)
    d = d[~d.index.duplicated(keep='last')].sort_index()
    return d

def fetch_cached_5m_data(tkrs_list):
    import os
    t0 = time.time()
    _m_open = is_market_open()
    _ttl = 180 if _m_open else 64800
    _cache_5m_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "intraday_5m_cache.pkl")
    _bad_syms = globals().get('_SKIP_BAD_SYMS', {"PBFINTECH", "GUJGASLTD", "TVSHLDGS", "TATAMOTORS", "PEL", "LTIM", "JCHAC", "SEAMEC", "TIDEWATER"})

    if '5m_store' not in _SS:
        _SS['5m_store'] = {}
        _SS['5m_ts'] = {}
        if os.path.exists(_cache_5m_file):
            try:
                if (time.time() - os.path.getmtime(_cache_5m_file)) < _ttl:
                    _saved = pd.read_pickle(_cache_5m_file)
                    if isinstance(_saved, dict) and _saved:
                        _SS['5m_store'] = {k: _sanitize_5m_df(v, k) for k, v in _saved.items()}
                        _now_init = time.time()
                        _SS['5m_ts'] = {k: _now_init for k in _SS['5m_store'] if not _SS['5m_store'][k].empty}
            except Exception:
                pass

    store = _SS['5m_store']
    ts_map = _SS['5m_ts']
    now_t = time.time()

    clean_req = [t for t in dict.fromkeys(tkrs_list) if str(t).replace(".NS", "") not in _bad_syms]
    missing_tkrs = [t for t in clean_req if (t not in store) or store[t].empty or ((now_t - ts_map.get(t, 0)) > _ttl)]

    n_yf = 0
    if missing_tkrs:
        yf_data = yf.download(missing_tkrs, period="2d", interval="5m", progress=False, group_by='ticker', threads=25, timeout=5)
        if not yf_data.empty:
            if len(missing_tkrs) == 1:
                df_clean = _sanitize_5m_df(yf_data, missing_tkrs[0])
                if not df_clean.empty:
                    store[missing_tkrs[0]] = df_clean
                    ts_map[missing_tkrs[0]] = now_t
                    n_yf = 1
            elif isinstance(yf_data.columns, pd.MultiIndex):
                lvl0 = yf_data.columns.get_level_values(0).unique()
                for tkr in missing_tkrs:
                    if tkr in lvl0:
                        df_clean = _sanitize_5m_df(yf_data[tkr], tkr)
                        if not df_clean.empty:
                            store[tkr] = df_clean
                            ts_map[tkr] = now_t
                            n_yf += 1

        for tkr in missing_tkrs:
            if tkr not in ts_map:
                ts_map[tkr] = now_t

        if n_yf > 0:
            try:
                pd.to_pickle(store, _cache_5m_file)
            except Exception:
                pass

    with _SS['diag_lock']:
        _SS['diag']['last_fetch'] = {
            'dhan': 0, 'yf': n_yf, 'total': len(clean_req),
            'sec': round(time.time() - t0, 2),
            'when': datetime.now(ZoneInfo("Asia/Kolkata")).strftime('%H:%M:%S')
        }

    valid_results = {}
    for t in clean_req:
        if t in store and not store[t].empty:
            df_c = _sanitize_5m_df(store[t], t)
            if not df_c.empty:
                store[t] = df_c
                valid_results[t] = df_c

    if valid_results:
        return pd.concat(valid_results.values(), axis=1, keys=valid_results.keys(), sort=False)
    return pd.DataFrame()

fetch_cached_5m_data.clear = lambda: _SS.pop('5m_store', None)

# --- చార్ట్స్ కోసం డేటా (YFINANCE - FAST METHOD) ---
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_historical_charts_data(tkrs, timeframe):
    idx_list = [t for t in tkrs if "^" in t or "=" in t]
    stk_list = [t for t in tkrs if t not in idx_list]
    
    p, i = ("5y", "1wk") if timeframe == "Weekly Chart" else ("2y", "1d")
    
    res = []
    if idx_list: res.append(yf.download(idx_list, period=p, interval=i, progress=False, group_by='ticker', threads=5))
    if stk_list: res.append(yf.download(stk_list, period=p, interval=i, progress=False, group_by='ticker', threads=5))
    
    if not res: return pd.DataFrame()
    
    if len(res) == 2:
        df = pd.concat(res, axis=1)
    else:
        df = res[0]
    
    if df.empty: return df
    
    if len(tkrs) == 1 and not isinstance(df.columns, pd.MultiIndex):
        df.columns = pd.MultiIndex.from_product([tkrs, df.columns])
    return df

# --- DAILY DATA FETCH (YFINANCE - SUPER FAST METHOD) ---
import os

# CMD lo HTTP Error 404 istunna symbols ni automatic ga skip chese list
_SKIP_BAD_SYMS = {"PBFINTECH", "GUJGASLTD", "TVSHLDGS", "TATAMOTORS", "PEL", "LTIM", "JCHAC", "SEAMEC", "TIDEWATER"}

@st.cache_data(ttl=900, show_spinner=False)
def fetch_all_data():
    # ⚡ FAST DISK CACHE: Okasari save ayyaka 18 gantala varaku 0.1 sec lone disk nundi load avtundi
    _cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daily_base_cache.pkl")
    if os.path.exists(_cache_file):
        try:
            if (time.time() - os.path.getmtime(_cache_file)) < 64800:  # 18 Hours valid
                _cached_df = pd.read_pickle(_cache_file)
                if not _cached_df.empty:
                    return _cached_df
        except Exception:
            pass

    port_df = load_portfolio()
    port_stocks = [str(sym).upper().strip() for sym in port_df['Symbol'].tolist() if str(sym).strip() != ""]
    base_stocks = NIFTY_50.copy() + FNO_STOCKS + MIDCAP_150 + SMALLCAP_250
    all_stocks = set(base_stocks + port_stocks) - _SKIP_BAD_SYMS
    tkrs = list(INDICES_MAP.keys()) + list(SECTOR_INDICES_MAP.keys()) + list(COMMODITY_MAP.keys()) + [f"{t}.NS" for t in all_stocks if t]
    
    chunk_size = 250
    data_frames = []
    for i in range(0, len(tkrs), chunk_size):
        chunk = tkrs[i : i + chunk_size]
        # timeout=5 valla ye okka stock daggara internet stuck avvadhu
        temp_data = yf.download(chunk, period="15mo", progress=False, group_by='ticker', threads=10, timeout=5)
        if not temp_data.empty:
            if len(chunk) == 1 and not isinstance(temp_data.columns, pd.MultiIndex):
                temp_data.columns = pd.MultiIndex.from_product([chunk, temp_data.columns])
            elif isinstance(temp_data.columns, pd.MultiIndex) and ('Close' in temp_data.columns.levels[0] or 'Open' in temp_data.columns.levels[0]):
                temp_data = temp_data.swaplevel(axis=1)
            data_frames.append(temp_data)
            
    if not data_frames: return pd.DataFrame()
    data = pd.concat(data_frames, axis=1)
    if data.empty: return pd.DataFrame()

    results = []
    minutes = get_minutes_passed()
    fetched_symbols = data.columns.levels[0] if isinstance(data.columns, pd.MultiIndex) else data.columns

    nifty_dist = 0.1
    if "^NSEI" in fetched_symbols:
        try:
            n_df = data["^NSEI"].dropna(subset=['Close'])
            if not n_df.empty:
                n_ltp = float(n_df['Close'].iloc[-1])
                n_vwap = (float(n_df['High'].iloc[-1]) + float(n_df['Low'].iloc[-1]) + n_ltp) / 3
                if n_vwap > 0: nifty_dist = abs(n_ltp - n_vwap) / n_vwap * 100
        except: pass

    for symbol in fetched_symbols:  # 🔧 FIX: MultiIndex లేకపోయినా crash అవ్వకూడదు
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
            
            day_chg = ((ltp - open_p) / open_p) * 100 if open_p > 0 else 0
            net_chg = ((ltp - prev_c) / prev_c) * 100 if prev_c > 0 else 0
            
            p_pivot = (prev_h + prev_l + prev_c) / 3
            p_bc = (prev_h + prev_l) / 2
            p_tc = (p_pivot - p_bc) + p_pivot
            cpr_width_pct = abs(p_tc - p_bc) / p_pivot * 100 if p_pivot > 0 else 0
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
                vol_x = 0.0; curr_vol = 0.0
                
            vwap = (high + low + ltp) / 3
            high_low_range = high - low
            bull_power = 0; bear_power = 0
            if high_low_range > 0:
                bull_power = ((ltp - low) / high_low_range) * 100
                bear_power = ((high - ltp) / high_low_range) * 100

            ema50_d = float(df['Close'].ewm(span=50, adjust=False).mean().iloc[-1]) if len(df) >= 50 else 0.0
            sma20_d = float(df['Close'].rolling(window=20).mean().iloc[-1]) if len(df) >= 20 else 0.0
            sma50_d = float(df['Close'].rolling(window=50).mean().iloc[-1]) if len(df) >= 50 else 0.0
            sma150_d = float(df['Close'].rolling(window=150).mean().iloc[-1]) if len(df) >= 150 else 0.0
            sma200_d = float(df['Close'].rolling(window=200).mean().iloc[-1]) if len(df) >= 200 else 0.0
            high_52w = float(df['High'].rolling(window=252).max().iloc[-1]) if len(df) >= 252 else float(df['High'].max())
            low_52w = float(df['Low'].rolling(window=252).min().iloc[-1]) if len(df) >= 252 else float(df['Low'].min())
            sma200_20d = float(df['Close'].rolling(window=200).mean().iloc[-21]) if len(df) >= 220 else 0.0
            sma150_20d = float(df['Close'].rolling(window=150).mean().iloc[-21]) if len(df) >= 170 else 0.0
            
            # 🔥 NEW: EMA 20 and Larry Connors RSI(2) & RSI(14) Calculations
            ema20_d = float(df['Close'].ewm(span=20, adjust=False).mean().iloc[-1]) if len(df) >= 20 else 0.0
            
            if len(df) >= 14:
                delta_d = df['Close'].diff()
                # 14-period RSI
                gain_14 = delta_d.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
                loss_14 = -delta_d.clip(upper=0).ewm(alpha=1/14, adjust=False).mean()
                rs_14 = gain_14 / loss_14.replace(0, np.nan)
                current_rsi14 = float((100 - (100 / (1 + rs_14))).fillna(50).iloc[-1])
                
                # 2-period RSI (For Larry Connors)
                gain_2 = delta_d.clip(lower=0).ewm(alpha=1/2, adjust=False).mean()
                loss_2 = -delta_d.clip(upper=0).ewm(alpha=1/2, adjust=False).mean()
                rs_2 = gain_2 / loss_2.replace(0, np.nan)
                current_rsi2 = float((100 - (100 / (1 + rs_2))).fillna(50).iloc[-1])
            else:
                current_rsi14 = 50.0
                current_rsi2 = 50.0
            # 🔥 END OF NEW CALCULATIONS
            
            if len(df) >= 25:
                # 20 trading days (4 weeks) base for Darvas & Zanger
                box_top_20 = float(df['High'].iloc[-21:-1].max())
                box_bot_20 = float(df['Low'].iloc[-21:-1].min())
            else:
                box_top_20 = high_52w
                box_bot_20 = low_52w
            pullback_52w_pct = ((high_52w - ltp) / high_52w) * 100 if high_52w > 0 else 0

            vcp_price_contraction = False
            vcp_vol_dry = False
            if len(df) >= 60:
                max_60 = float(df['High'].iloc[-60:].max()); min_60 = float(df['Low'].iloc[-60:].min())
                range_60 = (max_60 - min_60) / min_60 if min_60 > 0 else 0
                max_10 = float(df['High'].iloc[-10:].max()); min_10 = float(df['Low'].iloc[-10:].min())
                range_10 = (max_10 - min_10) / min_10 if min_10 > 0 else 0
                if (range_60 > 0) and (range_10 <= (range_60 * 0.75)) and (range_10 <= 0.15):
                    vcp_price_contraction = True
                if 'Volume' in df.columns and len(df) >= 50:
                    vol_avg_5 = float(df['Volume'].iloc[-6:-1].mean())
                    vol_avg_50 = float(df['Volume'].iloc[-50:].mean())
                    if vol_avg_5 <= (vol_avg_50 * 1.05):
                        vcp_vol_dry = True
            
            is_swing = False; is_w_pullback = False
            latest_w_ema10 = 0; latest_w_ema50 = 0
            
            df_w = df.resample('W-FRI').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()
            weekly_net_chg = net_chg
            if len(df_w) >= 2: 
                prev_w_c = float(df_w['Close'].iloc[-2])
                if prev_w_c > 0: weekly_net_chg = ((ltp - prev_w_c) / prev_w_c) * 100
                    
            if len(df_w) >= 40:
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
            if bull_power >= 85 and day_chg > 1.0: score += 3 
            if bear_power >= 85 and day_chg < -1.0: score += 3
            
            is_index = symbol in INDICES_MAP
            is_sector = symbol in SECTOR_INDICES_MAP
            is_commodity = symbol in COMMODITY_MAP
            disp_name = INDICES_MAP.get(symbol, SECTOR_INDICES_MAP.get(symbol, COMMODITY_MAP.get(symbol, symbol.replace(".NS", ""))))
            
            stock_sector = "OTHER"
            if not is_index and not is_sector and not is_commodity:
                for sec, stocks in NIFTY_50_SECTORS.items():
                    if disp_name in stocks:
                        stock_sector = sec
                        break
            
            results.append({
                "VCP_Contract": vcp_price_contraction, "VCP_Vol_Dry": vcp_vol_dry,
                "Fetch_T": symbol, "T": disp_name, "P": ltp, "O": open_p, "H": high, "L": low, "Prev_C": prev_c,
                "Prev_H": prev_h, "Prev_L": prev_l, "W_EMA10": latest_w_ema10, "W_EMA50": latest_w_ema50, 
                "D_EMA50": ema50_d, "EMA20": ema20_d,
                "SMA20": sma20_d, "SMA50": sma50_d, "SMA150": sma150_d, "SMA200": sma200_d, 
                "High52W": high_52w, "Low52W": low_52w, "SMA200_20D": sma200_20d,
                "Day_C": day_chg, "C": net_chg, "W_C": float(weekly_net_chg), "S": score, "VolX": vol_x, 
                "Is_Swing": is_swing, "Is_W_Pullback": is_w_pullback, "VWAP": vwap,
                "ATR": atr, "Narrow_CPR": is_narrow_cpr, 
                "Bull_P": bull_power, "Bear_P": bear_power,
                "Is_Index": is_index, "Is_Sector": is_sector, "Sector": stock_sector, "Is_Commodity": is_commodity,
                "SMA150_20D": sma150_20d, "Box_Top20": box_top_20, "Box_Bot20": box_bot_20,
                "Pullback_52W": pullback_52w_pct,
                "RSI2": current_rsi2, "RSI14": current_rsi14
            })
        except: continue
    _final_df = pd.DataFrame(results)
    if not _final_df.empty:
        try: _final_df.to_pickle("daily_base_cache.pkl")
        except Exception: pass
    return _final_df

def process_5m_data(df_raw):
    try:
        df_s = df_raw.dropna(subset=['Open', 'High', 'Low', 'Close']).copy()
        if df_s.empty: return pd.DataFrame()
        df_s.index = pd.to_datetime(df_s.index)
        if df_s.index.tz is not None:
            df_s.index = df_s.index.tz_convert('Asia/Kolkata').tz_localize(None)
        df_s = df_s[~df_s.index.duplicated(keep='last')].sort_index()

        # USD/INR lanti 24h charts lo off-market dead flat candles ni remove cheyadam
        is_flat_dup = (df_s['High'] == df_s['Low']) & (df_s['Close'] == df_s['Close'].shift(1))
        if (~is_flat_dup).sum() >= 20:
            df_s = df_s[~is_flat_dup].copy()

        df_s['EMA_10'] = df_s['Close'].ewm(span=10, adjust=False).mean()
        df_s['EMA_20'] = df_s['Close'].ewm(span=20, adjust=False).mean()
        df_s['EMA_50'] = df_s['Close'].ewm(span=50, adjust=False).mean()

        if 'Volume' in df_s.columns:
            df_s['Vol_SMA_75'] = df_s['Volume'].rolling(window=75, min_periods=1).mean()
        else:
            df_s['Vol_SMA_75'] = 0

        df_s['TR'] = pd.concat([
            df_s['High'] - df_s['Low'],
            (df_s['High'] - df_s['Close'].shift(1)).abs(),
            (df_s['Low'] - df_s['Close'].shift(1)).abs()
        ], axis=1).max(axis=1)
        df_s['ATR_13'] = df_s['TR'].ewm(span=13, adjust=False).mean()

        # Midnight date cut kakunda Session gap (> 3 hours) batti latest trading session teesukovadam
        time_diff = df_s.index.to_series().diff()
        session_ids = (time_diff > pd.Timedelta(hours=3)).cumsum()
        df_day = df_s[session_ids == session_ids.iloc[-1]].copy()

        first_t = df_day.index[0].time() if not df_day.empty else dt_time(0, 0)
        is_nse_session = (dt_time(9, 0) <= first_t <= dt_time(9, 30))
        if not is_nse_session and len(df_day) < 35:
            df_day = df_s.tail(75).copy()
        elif len(df_day) > 75:
            df_day = df_day.tail(75).copy()

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
    except:
        return pd.DataFrame()

# =========================================================
# 🧠 ADAPTIVE LIVE ENGINE v3 (Self-Learning, Cost-Aware)
# ---------------------------------------------------------
# Fixed rules ledu. Prathi refresh lo (market open lo 30s):
#  1. QUALITY FILTER : illiquid / bid-ask-bounce noisy stocks ni universe nundi teesestundi
#  2. FEATURES       : 17 stock features (momentum, VWAP, EMA, RSI, ORB, volume, range, Nifty-RS ...)
#                      + Nifty trend-strength / volatility + interactions (regime ki taggattu)
#  3. LEARNING       : last 5 days 5-min data nundi "next 30 min move" ni weighted ridge regression tho
#                      nerchukuntundi (ee time-of-day ki daggara + recent data ki ekkuva weight)
#  4. WALK-FORWARD   : prathi roju ni "chudani" test day ga pettukuni (train: appati varaku data) ->
#                      IC, top-signals hit-rate, COST taruvata net expectancy lekkistundi.
#                      Edge/profit ledu ante -> recommend cheyyadu
#  5. TREND GUARD    : confirmed strong trend ki ethirega signal ivvadu
#                      (ex: VWAP & EMA pai + volume surge unna stock ni SELL cheyyadu)
#  6. TIME GUARD     : market open lo 9:30–15:00 madhya matrame signals
# =========================================================
# =========================================================
# 🎯 INSTITUTIONAL ORDER-FLOW & ALPHA SNIPER ENGINE (PRO)
# ---------------------------------------------------------
# 5-Pillar Intraday Quant Scoring (0 to 100):
#  1. Institutional VWAP Control & EMA Ribbon (9 > 21 > VWAP) [25 pts]
#  2. Order-Flow / Cumulative Volume Delta (CVD Buying/Selling Pressure) [25 pts]
#  3. Relative Strength (Alpha) vs Nifty (Full Day + Last 30m) [20 pts]
#  4. Relative Volume (RVOL) & Intraday Breakout Structure [15 pts]
#  5. Non-Exhaustion RSI & Extension Guard (No Top-Buying) [15 pts]
# =========================================================
# =========================================================
# 📰 NEWS + VOLUME + PRICE CATALYST ENGINE (ONLY NEWS STOCKS)
# =========================================================
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
import urllib.parse

NEWS_STRAT = "📰 News + Vol + Price Breakout (Only News)"

_BULL_CATALYSTS = [
    ("📰Order-Win", ["order", "bagged", "contract", "letter of award", "loa", "lowest bidder", "l1 bidder", "tender", "deal win"]),
    ("📰Q-Results", ["net profit rises", "profit jumps", "profit surges", "q1", "q2", "q3", "q4", "ebitda", "revenue grows", "margin expands", "beats estimates"]),
    ("📰Upgrade", ["buy", "overweight", "outperform", "target price", "raises target", "upgrade", "bullish", "top pick"]),
    ("📰Approval", ["usfda", "approval", "eir", "clean chit", "patent", "nod", "clearance", "license"]),
    ("📰Expansion/JV", ["acquisition", "acquires", "joint venture", "mou", "partner", " commissioning", "capacity", "launch", "new plant"]),
    ("📰Corp-Action", ["dividend", "buyback", "bonus", "stock split", "fundraise", "qip", "preferential"]),
    ("📰Stake-Buy", ["block deal", "bulk deal", "stake buy", "promoter buys", "fii", "mutual fund buys"])
]

_BEAR_CATALYSTS = [
    ("📰Result-Miss", ["profit falls", "profit drops", "net loss", "widens", "misses estimates", "weak results", "margin shrinks", "declines"]),
    ("📰Downgrade", ["downgrade", "sell call", "underperform", "underweight", "cuts target", "target cut", "reduce"]),
    ("📰Reg-Alert", ["sebi", "penalty", "notice", "tax demand", "gst", "ed raid", "probe", "show cause", "ban", "default"]),
    ("📰USFDA-Issue", ["form 483", "observations", "warning letter", "import alert", "recall"]),
    ("📰Exit/Sale", ["resigns", "steps down", "stake sale", "offloads", "sells stake", "pledge"])
]


def _classify_headline(title_str):
    t_low = str(title_str).lower()
    for tag, kw_list in _BEAR_CATALYSTS:
        if any(k in t_low for k in kw_list):
            return tag, -1
    for tag, kw_list in _BULL_CATALYSTS:
        if any(k in t_low for k in kw_list):
            return tag, 1
    return "📰News-Buzz", 0


@st.cache_data(ttl=300, show_spinner=False)
def fetch_live_stock_news_batch(symbols_tuple, max_age_hours=36):
    """Fetches fresh news (last 36h) for active F&O stocks using yfinance + Google News RSS fallback."""
    now_utc = datetime.now(ZoneInfo("UTC"))

    def _fetch_one(fetch_sym):
        clean_sym = str(fetch_sym).replace(".NS", "").strip()
        headlines = []

        # 1. Try Google News RSS (Fastest & most accurate for Indian NSE stocks)
        try:
            q = urllib.parse.quote(f'"{clean_sym}" share OR stock NSE when:2d')
            rss_url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
            resp = requests.get(rss_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3.5)
            if resp.status_code == 200 and resp.content:
                root = ET.fromstring(resp.content)
                for item in root.findall("./channel/item")[:4]:
                    title = (item.findtext("title") or "").strip()
                    link = (item.findtext("link") or "").strip()
                    pub_str = (item.findtext("pubDate") or "").strip()
                    if not title:
                        continue
                    age_hr = 12.0
                    if pub_str:
                        try:
                            dt_pub = parsedate_to_datetime(pub_str)
                            if dt_pub.tzinfo is None:
                                dt_pub = dt_pub.replace(tzinfo=ZoneInfo("UTC"))
                            age_hr = (now_utc - dt_pub.astimezone(ZoneInfo("UTC"))).total_seconds() / 3600.0
                        except Exception:
                            age_hr = 12.0
                    if 0 <= age_hr <= max_age_hours:
                        headlines.append((age_hr, title, link))
        except Exception:
            pass

        # 2. Fallback: yfinance Ticker.news
        if not headlines:
            try:
                yf_news = yf.Ticker(fetch_sym).news or []
                for n_item in yf_news[:4]:
                    if isinstance(n_item, dict) and 'content' in n_item and isinstance(n_item['content'], dict):
                        c_obj = n_item['content']
                        title = str(c_obj.get('title', '')).strip()
                        link = str((c_obj.get('canonicalUrl') or {}).get('url', '')).strip()
                        pub_iso = c_obj.get('pubDate', '')
                        age_hr = 12.0
                        if pub_iso:
                            try:
                                dt_pub = pd.to_datetime(pub_iso, utc=True).to_pydatetime()
                                age_hr = (now_utc - dt_pub).total_seconds() / 3600.0
                            except Exception:
                                age_hr = 12.0
                    else:
                        title = str(n_item.get('title', '')).strip()
                        link = str(n_item.get('link', '')).strip()
                        ts = n_item.get('providerPublishTime', 0)
                        age_hr = ((now_utc.timestamp() - float(ts)) / 3600.0) if ts else 12.0

                    if title and (0 <= age_hr <= max_age_hours):
                        headlines.append((age_hr, title, link))
            except Exception:
                pass

        if not headlines:
            return fetch_sym, None

        # Pick freshest / highest-impact headline
        headlines.sort(key=lambda x: x[0])
        best_age, best_title, best_link = headlines[0]
        cat_tag, sentiment_bias = _classify_headline(best_title)

        # If first headline is generic, check if another recent headline has a specific catalyst
        if sentiment_bias == 0 and len(headlines) > 1:
            for age_h, t_str, l_str in headlines[1:]:
                c_tag, s_bias = _classify_headline(t_str)
                if s_bias != 0:
                    best_age, best_title, best_link = age_h, t_str, l_str
                    cat_tag, sentiment_bias = c_tag, s_bias
                    break

        return fetch_sym, {
            "title": best_title,
            "link": best_link or f"https://www.google.com/search?q={clean_sym}+share+news&tbm=nws",
            "age_h": round(max(0.1, best_age), 1),
            "tag": cat_tag,
            "bias": sentiment_bias,
            "count": len(headlines)
        }

    out = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(_fetch_one, s) for s in symbols_tuple]
        for f in concurrent.futures.as_completed(futs):
            try:
                k, val = f.result()
                if val is not None:
                    out[k] = val
            except Exception:
                 continue
    return out


def run_news_vol_price_strategy(df_candidates, processed_charts, min_volx=1.2, min_move_pct=0.75):
    """
    Filters ONLY stocks that have:
      1. Verified Fresh News (last 36h)
      2. Volume surge (VolX >= min_volx)
      3. Price + VWAP + 5m Order-Flow Confirmation (with 'Sell the News' Trap Guard)
    """
    if df_candidates is None or df_candidates.empty:
        return pd.DataFrame(), []

    # Step 1: Pre-filter stocks showing Volume + Price activity today
    active_mask = (
        (df_candidates['VolX'] >= min_volx) &
        ((df_candidates['Day_C'].abs() >= min_move_pct) | (df_candidates['C'].abs() >= 1.0))
    )
    df_pre = df_candidates[active_mask].copy()
    if df_pre.empty:
        return pd.DataFrame(), []

    # Sort by Volume * Move intensity and check top 45 active stocks for fresh news
    df_pre['_intensity'] = df_pre['VolX'] * (df_pre['Day_C'].abs() + df_pre['C'].abs())
    df_pre = df_pre.sort_values('_intensity', ascending=False).head(45)

    news_map = fetch_live_stock_news_batch(tuple(df_pre['Fetch_T'].tolist()))
    if not news_map:
        return pd.DataFrame(), []

    matched_rows = []
    feed_records = []

    for idx, row in df_pre.iterrows():
        ft = row['Fetch_T']
        if ft not in news_map:
            continue  # ❌ STRICT RULE: No Fresh News -> Skip!

        n_info = news_map[ft]
        ltp = float(row['P'])
        vwap = float(row['VWAP'])
        open_p = float(row['O'])
        prev_c = float(row['Prev_C'])
        day_c = float(row['Day_C'])
        net_c = float(row['C'])
        vol_x = float(row['VolX'])
        w_ema10 = float(row['W_EMA10'])

        # 5-min Intraday EMA10 & Last Candle check
        df_5m = processed_charts.get(ft, pd.DataFrame())
        intra_ema10 = float(df_5m['EMA_10'].iloc[-1]) if (not df_5m.empty and 'EMA_10' in df_5m.columns) else vwap
        vwap_live = float(df_5m['VWAP'].iloc[-1]) if (not df_5m.empty and 'VWAP' in df_5m.columns) else vwap

        # Check Price + Volume Direction
        is_bull_price = (ltp > vwap_live) and (ltp >= intra_ema10) and (day_c >= min_move_pct or net_c >= 1.2)
        is_bear_price = (ltp < vwap_live) and (ltp <= intra_ema10) and (day_c <= -min_move_pct or net_c <= -1.2)

        if not (is_bull_price or is_bear_price):
            continue

        # Score Calculation (0 to 99)
        score = 55
        if vol_x >= 2.5: score += 18
        elif vol_x >= 1.8: score += 13
        elif vol_x >= 1.3: score += 8

        if abs(day_c) >= 2.5: score += 12
        elif abs(day_c) >= 1.5: score += 8
        else: score += 4

        if n_info['age_h'] <= 6.0: score += 8   # Breaking intraday/morning news
        elif n_info['age_h'] <= 18.0: score += 5

        cat_tag = n_info['tag']
        bias = n_info['bias']

        if is_bull_price:
            side_icon = "📰 News BUY"
            if bias == 1:
                score += 10
            elif bias == -1:
                cat_tag = "📰Short-Squeeze🔥"  # Bad news absorbed, buyers squeezing shorts above VWAP!
                score += 6
            if ltp > w_ema10:
                score += 4
        else:
            side_icon = "📰 News SELL"
            if bias == -1:
                score += 10
            elif bias == 1 and open_p > prev_c * 1.005:
                cat_tag = "📰Sell-The-News🩸"  # Good news Gap-Up dumped below VWAP by Institutions!
                score += 8
            if ltp < w_ema10:
                score += 4

        final_prob = min(99, int(score))
        row_copy = row.copy()
        row_copy['Strategy_Icon'] = side_icon
        row_copy['AI_Prob'] = final_prob
        row_copy['S'] = max(int(row_copy.get('S', 10)), int(final_prob // 3))
        row_copy['AlphaTag'] = f"{cat_tag} ({n_info['age_h']:.0f}h) | {row_copy.get('AlphaTag', '')}".strip(" |")
        matched_rows.append(row_copy)

        feed_records.append({
            "Stock": row['T'],
            "Signal": "🟢 BUY" if is_bull_price else "🔴 SELL",
            "Catalyst": cat_tag,
            "LTP": ltp,
            "Day%": day_c,
            "VolX": vol_x,
            "Score": final_prob,
            "Age": f"{n_info['age_h']:.1f}h ago",
            "Headline": n_info['title'],
            "Link": n_info['link']
        })

    if not matched_rows:
        return pd.DataFrame(), []

    df_out = pd.DataFrame(matched_rows).sort_values(by=['AI_Prob', 'VolX'], ascending=[False, False])
    feed_records.sort(key=lambda x: (-x['Score'], -x['VolX']))
    return df_out, feed_records


def render_news_catalyst_banner(feed_records):
    if not feed_records:
        return ""
    rows_html = ""
    for i, r in enumerate(feed_records):
        bg = "row-dark" if i % 2 == 0 else "row-light"
        sig_col = "text-green" if "BUY" in r['Signal'] else "text-red"
        day_col = "text-green" if r['Day%'] >= 0 else "text-red"
        safe_title = _html.escape(r['Headline'])
        rows_html += (
            f"<tr class='{bg}'>"
            f"<td class='t-symbol'><a href='https://in.tradingview.com/chart/?symbol=NSE:{r['Stock']}' target='_blank'>{r['Stock']}</a></td>"
            f"<td class='{sig_col}'>{r['Signal']}</td>"
            f"<td style='color:#ffd700;font-weight:bold;'>{r['Catalyst']}</td>"
            f"<td>₹{r['LTP']:.2f}</td>"
            f"<td class='{day_col}'>{r['Day%']:+.2f}%</td>"
            f"<td style='color:#00BFFF;font-weight:bold;'>{r['VolX']:.1f}x</td>"
            f"<td style='color:#3fb950;font-weight:bold;'>{r['Score']}%</td>"
            f"<td style='color:#8b949e;'>{r['Age']}</td>"
            f"<td style='text-align:left;white-space:normal;line-height:1.3;'>"
            f"<a href='{r['Link']}' target='_blank' style='color:#e6edf3;'>{safe_title} 🔗</a></td>"
            f"</tr>"
        )
    return (
        "<table class='term-table'><thead>"
        "<tr><th colspan='9' class='term-head-brd' style='background:#1f6feb;'>📰 LIVE NEWS + VOLUME + PRICE CATALYST SCANNER (ONLY FRESH NEWS STOCKS)</th></tr>"
        "<tr style='background:#21262d;'>"
        "<th style='width:9%;text-align:left;'>STOCK</th><th style='width:7%;'>SIGNAL</th><th style='width:11%;'>CATALYST</th>"
        "<th style='width:7%;'>LTP</th><th style='width:7%;'>DAY%</th><th style='width:6%;'>VOL</th>"
        "<th style='width:6%;'>AI%</th><th style='width:7%;'>TIME</th><th style='width:40%;text-align:left;'>BREAKING HEADLINE (CLICK TO READ)</th>"
        "</tr></thead><tbody>" + rows_html + "</tbody></table>"
    )
ADAPTIVE_STRAT = "🧠 Adaptive Live Engine (Self-Learning)"
_AE_COST_PCT = 0.05


def _ae_clean(df_raw):
    d = df_raw.dropna(subset=['Open', 'High', 'Low', 'Close']).sort_index()
    d.index = pd.to_datetime(d.index)
    return d[~d.index.duplicated(keep='last')]


def adaptive_live_engine(five_min_data, candidates, top_n=8, min_edge=60):
    """Institutional Order-Flow & Alpha Sniper Engine. Returns (res, info)"""
    res = {'buy': [], 'sell': []}
    info = {
        'active': True, 'tier': 'A', 'status': 'Institutional Order-Flow Active ✅',
        'ic': 0.0, 'hit': 75.0, 'net': 0.0, 'folds': '5-Pillar Quant Confluence',
        'n': 0, 'drivers': 'VWAP Control • Order-Flow CVD • Nifty Alpha RS • RVOL Breakout',
        'dropped': 0, 'mkt': 'Scanning live 5-min institutional footprints...'
    }
    try:
        if five_min_data is None or five_min_data.empty or not isinstance(five_min_data.columns, pd.MultiIndex):
            info['active'] = False
            info['status'] = '5-min data load avvaledu'
            return res, info

        lvl0 = list(five_min_data.columns.levels[0])

        # --- Nifty Benchmark Calculation ---
        n_day_ret, n_30m_ret = 0.0, 0.0
        if "^NSEI" in lvl0:
            try:
                nd = _ae_clean(five_min_data["^NSEI"])
                if not nd.empty:
                    nd_dates = sorted(list(set(nd.index.date)))
                    nd_today = nd[nd.index.date == nd_dates[-1]]
                    if len(nd_today) >= 2:
                        n_day_ret = (float(nd_today['Close'].iloc[-1]) / float(nd_today['Open'].iloc[0]) - 1.0) * 100.0
                        lookback_idx = max(0, len(nd_today) - 7)
                        n_30m_ret = (float(nd_today['Close'].iloc[-1]) / float(nd_today['Close'].iloc[lookback_idx]) - 1.0) * 100.0
                        bias = "🟢 Bullish" if n_day_ret > 0.15 else ("🔴 Bearish" if n_day_ret < -0.15 else "⚪ Sideways")
                        info['mkt'] = f"Nifty Intraday: {n_day_ret:+.2f}% | Last 30m: {n_30m_ret:+.2f}% ({bias})"
            except Exception:
                pass

        min_score = float(min_edge) if min_edge is not None else 60.0
        cand_set = set(candidates)
        syms = [s for s in lvl0 if s in cand_set and '^' not in str(s) and '=' not in str(s)]

        buy_items, sell_items = [], []
        scanned = 0

        for s in syms:
            try:
                d = _ae_clean(five_min_data[s])
                if len(d) < 25:
                    info['dropped'] += 1
                    continue

                if 'Volume' not in d.columns:
                    d = d.assign(Volume=0.0)
                d = d[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)

                # Indicators on 5-min series
                c, hi, lo, op, vol = d['Close'], d['High'], d['Low'], d['Open'], d['Volume'].fillna(0.0)
                ema9 = c.ewm(span=9, adjust=False).mean()
                ema21 = c.ewm(span=21, adjust=False).mean()

                prev_c = c.shift(1)
                tr = pd.concat([hi - lo, (hi - prev_c).abs(), (lo - prev_c).abs()], axis=1).max(axis=1)
                atr14 = tr.ewm(span=14, adjust=False).mean()

                delta = c.diff()
                gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
                loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
                rsi14 = (100.0 - (100.0 / (1.0 + gain / loss.replace(0, np.nan)))).fillna(50.0)

                # Isolate latest trading day
                u_dates = sorted(list(set(d.index.date)))
                today_df = d[d.index.date == u_dates[-1]].copy()
                if len(today_df) < 3:
                    continue

                scanned += 1
                tp = (today_df['High'] + today_df['Low'] + today_df['Close']) / 3.0
                v_cum = today_df['Volume'].cumsum()
                vwap_s = ((tp * today_df['Volume']).cumsum() / v_cum.replace(0, np.nan)).fillna(tp)

                ltp = float(today_df['Close'].iloc[-1])
                day_open = float(today_df['Open'].iloc[0])
                day_high = float(today_df['High'].max())
                day_low = float(today_df['Low'].min())
                vwap_now = float(vwap_s.iloc[-1])
                e9_now = float(ema9.iloc[-1])
                e21_now = float(ema21.iloc[-1])
                atr_now = max(float(atr14.iloc[-1]), ltp * 0.002)
                rsi_now = float(rsi14.iloc[-1])

                # 1. VWAP Control & Trend Structure (Max 25 pts)
                pct_above_vwap = float((today_df['Close'] > vwap_s).mean())
                pct_below_vwap = float((today_df['Close'] < vwap_s).mean())

                # 2. Order-Flow CVD Proxy (Buying vs Selling Volume Pressure - Max 25 pts)
                rng = (today_df['High'] - today_df['Low']).replace(0, np.nan)
                clv = ((today_df['Close'] - today_df['Low']) / rng).fillna(0.5)  # 0 to 1
                last_n = min(len(today_df), 12)  # Last 60 mins order flow
                recent_vol = today_df['Volume'].iloc[-last_n:]
                recent_clv = clv.iloc[-last_n:]
                buy_vol_ratio = float((recent_vol * recent_clv).sum() / recent_vol.sum()) if recent_vol.sum() > 0 else 0.5

                # 3. Relative Strength vs Nifty (Max 20 pts)
                s_day_ret = (ltp / day_open - 1.0) * 100.0 if day_open > 0 else 0.0
                lb_idx = max(0, len(today_df) - 7)
                s_30m_ret = (ltp / float(today_df['Close'].iloc[lb_idx]) - 1.0) * 100.0
                rs_day = s_day_ret - n_day_ret
                rs_30m = s_30m_ret - n_30m_ret

                # 4. RVOL & Micro-Breakout (Max 15 pts)
                vol_base = float(vol.iloc[-25:-3].mean()) if len(vol) >= 25 else float(vol.mean())
                vol_rec = float(today_df['Volume'].iloc[-3:].mean())
                rvol = (vol_rec / vol_base) if vol_base > 0 else 1.0

                orb_h = float(today_df['High'].iloc[:3].max())
                orb_l = float(today_df['Low'].iloc[:3].min())
                near_day_high = ltp >= (day_high * 0.993)
                near_day_low = ltp <= (day_low * 1.007)

                # --- BUY SCORING (0 to 100) ---
                if ltp > vwap_now and e9_now >= e21_now and ltp >= e21_now:
                    b_score = 0.0
                    tags = []
                    # Pillar 1: VWAP + EMA Ribbon (25)
                    b_score += 12.0 if (ltp > e9_now > e21_now > vwap_now) else 7.0
                    if pct_above_vwap >= 0.75:
                        b_score += 13.0
                        tags.append("VWAP-Hold")
                    elif pct_above_vwap >= 0.60:
                        b_score += 8.0

                    # Pillar 2: Order-Flow CVD (25)
                    if buy_vol_ratio >= 0.62:
                        b_score += 25.0
                        tags.append("CVD-Buy🔥")
                    elif buy_vol_ratio >= 0.54:
                        b_score += 16.0
                    elif buy_vol_ratio >= 0.48:
                        b_score += 8.0

                    # Pillar 3: Nifty Alpha RS (20)
                    if rs_day >= 1.0 and rs_30m >= 0.25:
                        b_score += 20.0
                        tags.append("Alpha+RS")
                    elif rs_day >= 0.4 or rs_30m >= 0.15:
                        b_score += 13.0
                    elif rs_day > 0:
                        b_score += 6.0

                    # Pillar 4: RVOL & Structure (15)
                    if rvol >= 1.4:
                        b_score += 8.0
                        tags.append(f"RVOL {rvol:.1f}x")
                    elif rvol >= 1.0:
                        b_score += 4.0
                    if ltp > orb_h or near_day_high:
                        b_score += 7.0

                    # Pillar 5: Sweet-Spot Non-Exhaustion Guard (15)
                    ext_atr = (ltp - e9_now) / atr_now
                    if 54.0 <= rsi_now <= 76.0 and ext_atr <= 2.2:
                        b_score += 15.0
                    elif 48.0 <= rsi_now <= 82.0 and ext_atr <= 3.0:
                        b_score += 8.0

                    if b_score >= min_score:
                        exp_move = round(max(0.25, (atr_now / ltp * 100.0) * 1.8 * (b_score / 80.0)), 2)
                        buy_items.append(dict(
                            sym=s, exp=exp_move, atr=atr_now, side='buy',
                            score=int(min(99, round(b_score))),
                            tag=" ".join(tags[:2]) if tags else "Inst-Buy"
                        ))

                # --- SELL SCORING (0 to 100) ---
                elif ltp < vwap_now and e9_now <= e21_now and ltp <= e21_now:
                    s_score = 0.0
                    tags = []
                    # Pillar 1: VWAP + EMA Ribbon (25)
                    s_score += 12.0 if (ltp < e9_now < e21_now < vwap_now) else 7.0
                    if pct_below_vwap >= 0.75:
                        s_score += 13.0
                        tags.append("VWAP-Rej")
                    elif pct_below_vwap >= 0.60:
                        s_score += 8.0

                    # Pillar 2: Order-Flow CVD Selling Pressure (25)
                    sell_vol_ratio = 1.0 - buy_vol_ratio
                    if sell_vol_ratio >= 0.62:
                        s_score += 25.0
                        tags.append("CVD-Sell🩸")
                    elif sell_vol_ratio >= 0.54:
                        s_score += 16.0
                    elif sell_vol_ratio >= 0.48:
                        s_score += 8.0

                    # Pillar 3: Nifty Negative Alpha (20)
                    if rs_day <= -1.0 and rs_30m <= -0.25:
                        s_score += 20.0
                        tags.append("Weak-RS")
                    elif rs_day <= -0.4 or rs_30m <= -0.15:
                        s_score += 13.0
                    elif rs_day < 0:
                        s_score += 6.0

                    # Pillar 4: RVOL & Breakdown (15)
                    if rvol >= 1.4:
                        s_score += 8.0
                        tags.append(f"RVOL {rvol:.1f}x")
                    elif rvol >= 1.0:
                        s_score += 4.0
                    if ltp < orb_l or near_day_low:
                        s_score += 7.0

                    # Pillar 5: Non-Exhaustion Guard (15)
                    ext_atr = (e9_now - ltp) / atr_now
                    if 24.0 <= rsi_now <= 46.0 and ext_atr <= 2.2:
                        s_score += 15.0
                    elif 18.0 <= rsi_now <= 52.0 and ext_atr <= 3.0:
                        s_score += 8.0

                    if s_score >= min_score:
                        exp_move = -round(max(0.25, (atr_now / ltp * 100.0) * 1.8 * (s_score / 80.0)), 2)
                        sell_items.append(dict(
                            sym=s, exp=exp_move, atr=atr_now, side='sell',
                            score=int(min(99, round(s_score))),
                            tag=" ".join(tags[:2]) if tags else "Inst-Sell"
                        ))
            except Exception:
                continue

        res['buy'] = sorted(buy_items, key=lambda x: (-x['score'], -x['exp']))[:top_n]
        res['sell'] = sorted(sell_items, key=lambda x: (-x['score'], x['exp']))[:top_n]
        info['n'] = scanned
        all_scores = [x['score'] for x in res['buy'] + res['sell']]
        info['hit'] = float(np.mean(all_scores)) if all_scores else 70.0
        info['status'] = f"Active ✅ ({len(res['buy'])} BUY • {len(res['sell'])} SELL setups found)"
        return res, info
    except Exception as e:
        info['active'] = False
        info['status'] = f'Error: {e}'
        return res, info


def adaptive_status_html(info):
    col = "#238636" if info.get('active') else "#f85149"
    return (
        f"<div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;"
        f"background:#161b22;border:1px solid {col};border-radius:6px;padding:4px 10px;margin:2px 0;font-size:11.5px;'>"
        f"<span>🎯 <b> Order-Flow Sniper:</b> {info.get('status', '')} &nbsp;|&nbsp; "
        f"<span style='color:#ffd700;'>{info.get('mkt', '')}</span></span>"
        f"<span style='color:#8b949e;'>Scanned: <b>{info.get('n', 0)}</b> • Avg Score: <b>{info.get('hit', 0):.0f}/100</b></span>"
        f"</div>"
    )


def card_bg_class(pct_val):
    # 🎨 % change intensity ప్రకారం gradient color (TradingView style)
    if pct_val >= 3.0: return "bull-card-3"
    if pct_val >= 1.5: return "bull-card-2"
    if pct_val > 0: return "bull-card"
    if pct_val <= -3.0: return "bear-card-3"
    if pct_val <= -1.5: return "bear-card-2"
    if pct_val < 0: return "bear-card"
    return "neut-card"

def generate_status(row):
    status = ""
    p = row.get('P', 0)
    if row.get('Bull_P', 0) >= 80: status += f"🐂Bulls {int(row['Bull_P'])}% "
    elif row.get('Bear_P', 0) >= 80: status += f"🐻Bears {int(row['Bear_P'])}% "
    if 'AlphaTag' in row and row['AlphaTag']: status += f"{row['AlphaTag']} "
    if 'O' in row and 'L' in row and abs(row['O'] - row['L']) < (p * 0.002): status += "O=L🔥 "
    if 'O' in row and 'H' in row and abs(row['O'] - row['H']) < (p * 0.002): status += "O=H🩸 "
    if row.get('C', 0) > 0 and row.get('Day_C', 0) > 0 and row.get('VolX', 0) > 1.5: status += "Rec⇈ "
    if row.get('VolX', 0) > 1.5: status += "VOL🟢 "
    return status.strip()

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_fundamentals_data(symbols_list):
    def get_info(sym):
        try:
            tkr = yf.Ticker(f"{sym}")
            info = tkr.info
            return {
                "Fetch_T": sym,
                "Sector": info.get('sector', 'N/A'),
                "Market_Cap (Cr)": round(info.get('marketCap', 0) / 10000000, 2) if info.get('marketCap') else 0,
                "P/E Ratio": round(info.get('trailingPE', 0), 2) if info.get('trailingPE') else 0,
                "ROE %": round(info.get('returnOnEquity', 0) * 100, 2) if info.get('returnOnEquity') else 0,
                "Debt/Equity": round(info.get('debtToEquity', 0) / 100, 2) if info.get('debtToEquity') else 0,
                "Div Yield %": round(info.get('dividendYield', 0) * 100, 2) if info.get('dividendYield') else 0.0,
                "52W High": info.get('fiftyTwoWeekHigh', 0),
                "52W Low": info.get('fiftyTwoWeekLow', 0)
            }
        except: return None
   
    fund_data = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:  # 🔧 PERF: rate-limit తగ్గడానికి
        results = executor.map(get_info, symbols_list)
        for res in results:
            if res is not None:
                fund_data.append(res)
    return pd.DataFrame(fund_data)   

# --- RENDER FUNCTIONS ---



def render_mf_table(df_mf):
    if df_mf.empty: return "<div style='padding:20px; text-align:center;'>No Mutual Fund data available.</div>"
    html = f'<table class="term-table"><thead><tr><th colspan="7" class="term-head-swing" style="background-color: #005a9e; color: white;">🏆 MUTUAL FUNDS SCREENER (LIVE PERFORMANCE)</th></tr><tr style="background-color: #21262d;"><th style="width:5%;">RANK</th><th style="text-align:left; width:25%;">FUND NAME</th><th style="width:15%; color:#ffd700;">CATEGORY</th><th style="width:10%;">NAV (₹)</th><th style="width:15%;">1Y RETURN</th><th style="width:15%;">3Y CAGR</th><th style="width:15%;">5Y CAGR</th></tr></thead><tbody>'
    for i, (_, row) in enumerate(df_mf.iterrows()):
        rank = i + 1 
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        def colorize(val):
            if val == "N/A": return "<span style='color:#8b949e;'>N/A</span>"
            val_f = float(val)
            if val_f > 20: return f"<span style='color:#00FF00; font-weight:bold;'>{val}%</span>" 
            elif val_f > 12: return f"<span style='color:#3fb950;'>{val}%</span>" 
            elif val_f < 0: return f"<span style='color:#f85149;'>{val}%</span>" 
            return f"{val}%"
        html += f'<tr class="{bg_class}"><td><b>{rank}</b></td><td class="t-symbol">{row["Fund Name"]}</td><td style="font-size:11px; color:#c9d1d9; font-weight:bold;">{row["Category"]}</td><td>₹{row["NAV (₹)"]}</td><td>{colorize(row["1Y (%)"])}</td><td>{colorize(row["3Y CAGR (%)"])}</td><td>{colorize(row["5Y CAGR (%)"])}</td></tr>'
    html += "</tbody></table>"
    return html



# =========================================================
# 📊 PORTFOLIO ALLOCATION (Sector • Market-cap • Stock weights) — Zerodha Console style
# ---------------------------------------------------------
#  • Sector: static map (F&O + Midcap universe) -> sheet 'Sector' column override -> yfinance fallback -> Others
#  • Cap: Nifty 50 + Next 50 = Large, Midcap/F&O = Mid, migata = Small (approx; sheet lo 'Cap' column tho override cheyyochchu)
#  • Concentration alerts: single stock > 20% / sector > 35%
# =========================================================
_PF_SECTOR_GROUPS = {
    "Financial Services": "ABCAPITAL ANGELONE AUBANK AXISBANK BAJAJFINSV BAJFINANCE BANDHANBNK BANKBARODA BSE CANBK CANFINHOME CDSL CHOLAFIN CUB "
                          "FEDERALBNK HDFCAMC HDFCBANK HDFCLIFE HUDCO ICICIBANK ICICIGI ICICIPRULI IDFCFIRSTB IEX INDUSINDBK IRFC KOTAKBANK LICHSGFIN "
                          "M&MFIN MANAPPURAM MCX MFSL MUTHOOTFIN PEL PFC PNB RBLBANK RECLTD SBICARD SBILIFE SBIN SHRIRAMFIN BANKINDIA INDIANB IREDA LTF "
                          "PAYTM PBFINTECH POONAWALLA SUNDARMFIN UCOBANK UNIONBANK YESBANK",
    "IT & Software": "COFORGE HCLTECH INDIAMART INFY LTIM LTTS MPHASIS NAUKRI OFSS PERSISTENT TCS TECHM WIPRO KPITTECH TATAELXSI",
    "Healthcare": "ABBOTINDIA ALKEM APOLLOHOSP AUROPHARMA BIOCON CIPLA DIVISLAB DRREDDY GLENMARK GRANULES IPCALAB LALPATHLAB LAURUSLABS LUPIN "
                  "METROPOLIS SUNPHARMA SYNGENE TORNTPHARM ZYDUSLIFE AJANTPHARM FORTIS MAXHEALTH VIJAYA",
    "Metals & Mining": "HINDALCO HINDCOPPER JINDALSTEL JSWSTEEL NATIONALUM NMDC SAIL TATASTEEL VEDL",
    "Energy": "BPCL COALINDIA GAIL GUJGASLTD HINDPETRO IGL IOC MGL ONGC PETRONET RELIANCE OIL",
    "Power & Utilities": "ADANIENSOL NTPC POWERGRID TATAPOWER NHPC NLCINDIA SJVN TORNTPOWER",
    "Automobiles": "APOLLOTYRE ASHOKLEY BAJAJ-AUTO BALKRISIND BHARATFORG BOSCHLTD EICHERMOT ESCORTS EXIDEIND HEROMOTOCO M&M MARUTI MOTHERSON MRF "
                   "TATAMOTORS TVSMOTOR SONACOMS",
    "FMCG": "BALRAMCHIN BRITANNIA COLPAL DABUR GODREJCP HINDUNILVR ITC MARICO NESTLEIND TATACONSUM UBL",
    "Consumer & Retail": "ABFRL ASIANPAINT BATAINDIA BERGEPAINT CROMPTON DIXON HAVELLS INDHOTEL INDIGO IRCTC JUBLFOOD PAGEIND PVRINOX TITAN TRENT VOLTAS "
                         "ZOMATO KALYANKJIL INDIGOPNTS",
    "Engineering & Capital Goods": "ABB BEL BHEL CUMMINSIND HAL POLYCAB SIEMENS APARINDS CGPOWER MAZDOCK SUZLON",
    "Infrastructure & Construction": "ADANIENT ADANIPORTS CONCOR GMRINFRA LT NCC RVNL DELHIVERY",
    "Cement & Building Materials": "ACC AMBUJACEM ASTRAL DALBHARAT GRASIM INDIACEM RAMCOCEM SHREECEM ULTRACEMCO SUPREMEIND",
    "Chemicals & Fertilizers": "AARTIIND ATUL CHAMBLFERT COROMANDEL DEEPAKNTR GNFC NAVINFLUOR PIDILITIND PIIND SRF TATACHEM UPL",
    "Real Estate": "DLF GODREJPROP OBEROIRLTY PRESTIGE LODHA PHOENIXLTD",
    "Telecom & Media": "BHARTIARTL IDEA INDUSTOWER SUNTV TATACOMM ZEEL",
}
PF_SECTOR_MAP = {_s: _sec for _sec, _names in _PF_SECTOR_GROUPS.items() for _s in _names.split()}
_PF_NEXT50 = set(("ABB ADANIENSOL ADANIGREEN ADANIPOWER AMBUJACEM BAJAJHLDNG BANKBARODA BERGEPAINT BOSCHLTD CANBK CGPOWER CHOLAFIN COLPAL DABUR DIVISLAB "
                  "DLF DMART GAIL GODREJCP HAVELLS HAL ICICIGI ICICIPRULI INDHOTEL INDIGO IOC IRCTC IRFC JINDALSTEL JIOFIN LICI LODHA LTIM MARICO MAZDOCK "
                  "MOTHERSON NAUKRI PFC PIDILITIND PNB RECLTD SHREECEM SIEMENS SRF TATAPOWER TORNTPHARM TVSMOTOR UNITDSPR VBL VEDL ZYDUSLIFE ZOMATO").split())
_PF_COLORS = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#a371f7", "#39c5cf", "#db61a2", "#ff9248", "#7ee787", "#79c0ff", "#e3b341", "#8b949e"]


@st.cache_data(ttl=7 * 86400, show_spinner=False)
def _pf_yf_sector_raw(sym):
    info = yf.Ticker(f"{sym}.NS").info or {}
    sec, ind = str(info.get('sector', '')), str(info.get('industry', '')).lower()
    if sec == 'Basic Materials':
        if any(k in ind for k in ('steel', 'aluminum', 'copper', 'gold', 'silver', 'metal', 'coal', 'mining')):
            return "Metals & Mining"
        if any(k in ind for k in ('cement', 'building', 'construction materials')):
            return "Cement & Building Materials"
        return "Chemicals & Fertilizers"
    if sec == 'Industrials':
        if any(k in ind for k in ('engineering & construction', 'infrastructure', 'airport', 'marine', 'railroad', 'trucking', 'freight')):
            return "Infrastructure & Construction"
        return "Engineering & Capital Goods"
    if sec == 'Consumer Cyclical':
        return "Automobiles" if 'auto' in ind else "Consumer & Retail"
    mp = {'Financial Services': "Financial Services", 'Technology': "IT & Software", 'Healthcare': "Healthcare", 'Energy': "Energy",
          'Utilities': "Power & Utilities", 'Consumer Defensive': "FMCG", 'Real Estate': "Real Estate", 'Communication Services': "Telecom & Media"}
    if sec not in mp:
        raise ValueError("sector unknown")          # cache avvakunda
    return mp[sec]


def _pf_clean_sym(sym):
    return str(sym).upper().replace(".NS", "").strip()


def pf_sector(sym, override=""):
    ov = str(override or "").strip()
    if ov and ov.lower() not in ("nan", "none"):
        return ov
    sym = _pf_clean_sym(sym)
    if sym in PF_SECTOR_MAP:
        return PF_SECTOR_MAP[sym]
    try:
        return _pf_yf_sector_raw(sym)
    except Exception:
        return "Others"


def pf_cap(sym, override=""):
    ov = str(override or "").strip()
    if ov and ov.lower() not in ("nan", "none"):
        return ov
    sym = _pf_clean_sym(sym)
    if sym in NIFTY_50 or sym in _PF_NEXT50:
        return "Large Cap"
    if sym in MIDCAP_150 or sym in FNO_STOCKS:
        return "Mid Cap"
    return "Small Cap"


def build_portfolio_alloc_df(df_port, df_all_stocks):
    if df_port is None or df_port.empty:
        return pd.DataFrame()
    lu = {}
    if df_all_stocks is not None and not df_all_stocks.empty:
        lu = df_all_stocks.drop_duplicates(subset=['T']).set_index('T')[['P', 'Prev_C']].to_dict('index')
    rows = []
    for _, r in df_port.iterrows():
        sym = _pf_clean_sym(r.get('Symbol', ''))
        try:
            qty, bp = float(r['Quantity']), float(r['Buy_Price'])
        except Exception:
            continue
        if not sym or qty <= 0:
            continue
        ltp = float(lu.get(sym, {}).get('P', bp) or bp)
        pc = float(lu.get(sym, {}).get('Prev_C', ltp) or ltp)
        rows.append({'Symbol': sym, 'Qty': qty, 'Invested': bp * qty, 'Current': ltp * qty, 'Day': (ltp - pc) * qty,
                     'Sector': pf_sector(sym, r.get('Sector', '')), 'Cap': pf_cap(sym, r.get('Cap', ''))})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.groupby(['Symbol', 'Sector', 'Cap'], as_index=False)[['Qty', 'Invested', 'Current', 'Day']].sum()


def _pf_donut(labels, values, center_text):
    fig = go.Figure(go.Pie(
        labels=list(labels), values=list(values), hole=0.64, sort=False, direction='clockwise',
        marker=dict(colors=[_PF_COLORS[i % len(_PF_COLORS)] for i in range(len(labels))], line=dict(color='#0e1117', width=2)),
        textinfo='none', hovertemplate='<b>%{label}</b><br>₹%{value:,.0f}<br>%{percent}<extra></extra>'))
    fig.update_layout(height=230, margin=dict(l=0, r=0, t=4, b=4), showlegend=False,
                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                      annotations=[dict(text=center_text, x=0.5, y=0.5, showarrow=False, font=dict(size=13, color='#c9d1d9'))])
    return fig


def _pf_legend_html(labels, values):
    tot = float(sum(values)) or 1.0
    out = "<div style='font-size:12.5px;line-height:1.85;'>"
    for i, (l, v) in enumerate(zip(labels, values)):
        c = _PF_COLORS[i % len(_PF_COLORS)]
        out += (f"<div style='display:flex;justify-content:space-between;border-bottom:1px solid #21262d;'>"
                f"<span><span style='color:{c};'>●</span> {_html.escape(str(l))}</span>"
                f"<span style='color:#c9d1d9;'><b>{v / tot * 100:.2f}%</b></span></div>")
    return out + "</div>"


def render_portfolio_allocation(df_port, df_all_stocks):
    adf = build_portfolio_alloc_df(df_port, df_all_stocks)
    if adf.empty:
        st.info("Portfolio lo stocks add cheste allocation kanipistundi.")
        return
    basis = st.radio("Allocation basis", ["Current value", "Invested"], horizontal=True, key="pf_alloc_basis", label_visibility="collapsed")
    col = "Current" if basis == "Current value" else "Invested"
    total = float(adf[col].sum()) or 1.0

    sec = adf.groupby('Sector')[col].sum().sort_values(ascending=False)
    cap = adf.groupby('Cap')[col].sum().reindex(['Large Cap', 'Mid Cap', 'Small Cap']).dropna()
    stk = adf.set_index('Symbol')[col].sort_values(ascending=False)
    top = stk.head(8)
    if len(stk) > 8:
        top = pd.concat([top, pd.Series({'Others': float(stk.iloc[8:].sum())})])

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**🏭 Sectors**")
        st.plotly_chart(_pf_donut(sec.index, sec.values, f"{len(sec)}<br>Sectors"), use_container_width=True, key="pf_don_sec", config={'displayModeBar': False})
        st.markdown(_pf_legend_html(sec.index, sec.values), unsafe_allow_html=True)
    with c2:
        st.markdown("**📏 Market Cap**")
        st.plotly_chart(_pf_donut(cap.index, cap.values, f"₹{total / 1e5:,.2f}L<br>{basis}"), use_container_width=True, key="pf_don_cap", config={'displayModeBar': False})
        st.markdown(_pf_legend_html(cap.index, cap.values), unsafe_allow_html=True)
        st.caption("Cap classification approx (Nifty100 = Large, Midcap/F&O = Mid, migata Small). Sheet lo 'Cap' column pedithe adi vadutundi.")
    with c3:
        st.markdown("**📦 Top Holdings**")
        st.plotly_chart(_pf_donut(top.index, top.values, f"{len(stk)}<br>Stocks"), use_container_width=True, key="pf_don_stk", config={'displayModeBar': False})
        st.markdown(_pf_legend_html(top.index, top.values), unsafe_allow_html=True)

    # ⚠️ Concentration alerts
    alerts = []
    for s, v in stk.head(3).items():
        if v / total > 0.20:
            alerts.append(f"⚠️ <b>{_html.escape(s)}</b> = {v / total * 100:.1f}% of portfolio (single-stock risk, 20% kante ekkuva)")
    for s, v in sec.items():
        if s not in ("Others",) and v / total > 0.35:
            alerts.append(f"⚠️ <b>{_html.escape(s)}</b> sector = {v / total * 100:.1f}% (35% kante ekkuva — diversification chudandi)")
    if alerts:
        st.markdown("<div style='background:#2d1f0e;border:1px solid #d29922;border-radius:8px;padding:8px 12px;margin:8px 0;font-size:13px;'>"
                    + "<br>".join(alerts) + "</div>", unsafe_allow_html=True)

    # 📋 Sector table
    g = adf.groupby('Sector').agg(Stocks=('Symbol', 'nunique'), Invested=('Invested', 'sum'), Current=('Current', 'sum'), Day=('Day', 'sum'))
    g['Weight'] = g[col] / total * 100
    g = g.sort_values('Weight', ascending=False)
    rows = ""
    for s, r in g.iterrows():
        pnl = r['Current'] - r['Invested']
        pct = (pnl / r['Invested'] * 100) if r['Invested'] > 0 else 0
        cc = "text-green" if pnl >= 0 else "text-red"
        dc = "text-green" if r['Day'] >= 0 else "text-red"
        rows += (f"<tr><td style='text-align:left;'>{_html.escape(str(s))}</td><td>{int(r['Stocks'])}</td><td><b>{r['Weight']:.2f}%</b></td>"
                 f"<td>₹{r['Invested']:,.0f}</td><td>₹{r['Current']:,.0f}</td><td class='{cc}'>₹{pnl:,.0f} ({pct:+.2f}%)</td><td class='{dc}'>₹{r['Day']:,.0f}</td></tr>")
    st.markdown("<table class='term-table'><thead><tr><th colspan='7' class='term-head-port'>🏭 SECTOR-WISE ALLOCATION</th></tr>"
                "<tr style='background-color:#21262d;'><th style='text-align:left;'>SECTOR</th><th>STOCKS</th><th>WEIGHT</th><th>INVESTED</th><th>CURRENT</th><th>P&L</th><th>DAY P&L</th></tr></thead>"
                f"<tbody>{rows}</tbody></table>", unsafe_allow_html=True)



def render_portfolio_table(df_port, df_stocks, weekly_trends, port_sort="Default"):
    if df_port.empty: return "<div style='padding:20px; text-align:center; color:#8b949e; border: 1px dashed #30363d; border-radius:8px;'>Portfolio is empty. Add a stock using the option below!</div>"
    
    stock_lookup = df_stocks.drop_duplicates(subset=['T'], keep='first').set_index('T').to_dict('index')
    
    rows_data = []
    total_invested, total_current, total_day_pnl = 0, 0, 0
    today_dt = now_ist().date()
    
    for i, (_, row) in enumerate(df_port.iterrows()):
        sym = str(row['Symbol']).upper().strip()
        try: qty = float(row['Quantity'])
        except: qty = 0
        try: buy_p = float(row['Buy_Price'])
        except: buy_p = 0
        
        date_val = str(row.get('Date', '-')).strip()
        if date_val in ['nan', 'NaN', '']: date_val = '-'
        
        # Purchase nundi enni rojulu ayyindo calculate cheyadam (No. of Days)
        parsed_dt = pd.to_datetime(date_val, errors='coerce')
        if pd.notna(parsed_dt):
            days_held = max(0, (today_dt - parsed_dt.date()).days)
            sort_dt = parsed_dt.toordinal()
        else:
            days_held = 0
            sort_dt = 0
        
        live_row = stock_lookup.get(sym, None)
        trend_html = "➖"
        
        if live_row is not None:
            ltp = float(live_row['P'])
            prev_c = float(live_row['Prev_C'])
            fetch_t = live_row['Fetch_T']
            trend_state = weekly_trends.get(fetch_t, "Neutral")
            if trend_state == 'Bullish': trend_html = "🟢 Bullish"
            elif trend_state == 'Bearish': trend_html = "🔴 Bearish"
            else: trend_html = "⚪ Neutral"
        else:
            ltp, prev_c = buy_p, buy_p
            
        invested = buy_p * qty
        current = ltp * qty
        overall_pnl = current - invested
        pnl_pct = (overall_pnl / invested * 100) if invested > 0 else 0
        day_pnl = (ltp - prev_c) * qty
        
        total_invested += invested
        total_current += current
        total_day_pnl += day_pnl
        
        rows_data.append({
            'sym': sym, 'date': date_val, 'days_held': days_held, 'sort_dt': sort_dt,
            'qty': qty, 'buy_p': buy_p, 'ltp': ltp, 'trend_html': trend_html,
            'invested': invested, 'overall_pnl': overall_pnl, 'pnl_pct': pnl_pct, 'day_pnl': day_pnl
        })
        
    if port_sort == "Day P&L ⬆️": rows_data.sort(key=lambda x: x['day_pnl'], reverse=True)
    elif port_sort == "Day P&L ⬇️": rows_data.sort(key=lambda x: x['day_pnl'], reverse=False)
    elif port_sort == "Total P&L ⬆️": rows_data.sort(key=lambda x: x['overall_pnl'], reverse=True)
    elif port_sort == "Total P&L ⬇️": rows_data.sort(key=lambda x: x['overall_pnl'], reverse=False)
    elif port_sort == "P&L % ⬆️": rows_data.sort(key=lambda x: x['pnl_pct'], reverse=True)
    elif port_sort == "P&L % ⬇️": rows_data.sort(key=lambda x: x['pnl_pct'], reverse=False)
    elif port_sort == "Date (Newest) ⬇️": rows_data.sort(key=lambda x: x['sort_dt'], reverse=True)
    elif port_sort == "Date (Oldest) ⬆️": rows_data.sort(key=lambda x: x['sort_dt'], reverse=False)
    elif port_sort == "Days Held ⬆️": rows_data.sort(key=lambda x: x['days_held'], reverse=True)
    elif port_sort == "Days Held ⬇️": rows_data.sort(key=lambda x: x['days_held'], reverse=False)

    html = f'<table class="term-table"><thead><tr><th colspan="11" class="term-head-port">💼 LIVE PORTFOLIO TERMINAL</th></tr><tr style="background-color: #21262d;"><th style="text-align:left; width:11%;">STOCK</th><th style="width:9%;">BUY DATE</th><th style="width:6%; color:#ffd700;">DAYS</th><th style="width:5%;">QTY</th><th style="width:8%;">AVG</th><th style="width:8%;">LTP</th><th style="width:10%;">WK TREND</th><th style="width:12%;">INVESTED (₹)</th><th style="width:10%;">DAY P&L</th><th style="width:11%;">TOT P&L</th><th style="width:10%;">P&L %</th></tr></thead><tbody>'
    
    for i, rd in enumerate(rows_data):
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        tpnl_color = "text-green" if rd['overall_pnl'] >= 0 else "text-red"
        dpnl_color = "text-green" if rd['day_pnl'] >= 0 else "text-red"
        t_sign = "+" if rd['overall_pnl'] > 0 else ""
        d_sign = "+" if rd['day_pnl'] > 0 else ""
        days_str = f"{rd['days_held']}d" if rd['date'] != '-' else "-"
        html += f'<tr class="{bg_class}"><td class="t-symbol {tpnl_color}"><a href="https://in.tradingview.com/chart/?symbol=NSE:{rd["sym"]}" target="_blank">{rd["sym"]}</a></td><td>{rd["date"]}</td><td style="color:#ffd700; font-weight:bold;">{days_str}</td><td>{int(rd["qty"])}</td><td>{rd["buy_p"]:.2f}</td><td>{rd["ltp"]:.2f}</td><td style="font-size:10px;">{rd["trend_html"]}</td><td>{rd["invested"]:,.0f}</td><td class="{dpnl_color}">{d_sign}{rd["day_pnl"]:,.0f}</td><td class="{tpnl_color}">{t_sign}{rd["overall_pnl"]:,.0f}</td><td class="{tpnl_color}">{t_sign}{rd["pnl_pct"]:.2f}%</td></tr>'
    
    overall_total_pnl = total_current - total_invested
    overall_total_pct = (overall_total_pnl / total_invested * 100) if total_invested > 0 else 0
    o_color = "text-green" if overall_total_pnl >= 0 else "text-red"
    o_sign = "+" if overall_total_pnl > 0 else ""
    d_color = "text-green" if total_day_pnl >= 0 else "text-red"
    d_sign = "+" if total_day_pnl > 0 else ""
    
    try:
        df_closed = load_closed_trades()
        total_realized_pnl = pd.to_numeric(df_closed['PnL_Rs'], errors='coerce').sum() if not df_closed.empty else 0
    except:
        total_realized_pnl = 0
        
    actual_pnl_value = overall_total_pnl + total_realized_pnl
    ap_color = "text-green" if actual_pnl_value >= 0 else "text-red"
    ap_sign = "+" if actual_pnl_value > 0 else ""

    html += f'<tr class="port-total"><td colspan="8" style="text-align:right; padding-right:15px; font-size:12px;">TOTAL INVESTED: ₹{total_invested:,.0f} &nbsp;|&nbsp; CURRENT: ₹{total_current:,.0f} &nbsp;|&nbsp; ACTUAL P&L: <span class="{ap_color}">{ap_sign}₹{actual_pnl_value:,.0f}</span> &nbsp;|&nbsp; OVERALL P&L:</td><td class="{d_color}">{d_sign}₹{total_day_pnl:,.0f}</td><td class="{o_color}">{o_sign}₹{overall_total_pnl:,.0f}</td><td class="{o_color}">{o_sign}{overall_total_pct:.2f}%</td></tr>'
    html += "</tbody></table>"
    return html

def render_portfolio_swing_advice_table(df_port, df_stocks, weekly_trends):
    if df_port.empty: return ""
    
    stock_lookup = df_stocks.drop_duplicates(subset=['T'], keep='first').set_index('T').to_dict('index')
    
    html = f'<table class="term-table"><thead><tr><th colspan="8" class="term-head-swing">🤖 PORTFOLIO SWING ADVISOR (ACTION & LEVELS)</th></tr><tr style="background-color: #21262d;"><th style="text-align:left; width:15%;">STOCK</th><th style="width:10%;">AVG PRICE</th><th style="width:10%;">LTP</th><th style="width:10%;">P&L %</th><th style="width:12%;">WK TREND</th><th style="width:13%; color:#f85149;">🛑 TRAILING SL</th><th style="width:13%; color:#3fb950;">🎯 NEXT TARGET</th><th style="width:17%;">💡 ACTION ADVICE</th></tr></thead><tbody>'
    
    for i, (_, row) in enumerate(df_port.iterrows()):
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        sym = str(row['Symbol']).upper().strip()
        try: buy_p = float(row['Buy_Price'])
        except: buy_p = 0
        
        live_data = stock_lookup.get(sym, None)
        if live_data is None: continue
        ltp = float(live_data['P'])
        
        pnl_pct = ((ltp - buy_p) / buy_p * 100) if buy_p > 0 else 0
        pnl_color = "text-green" if pnl_pct >= 0 else "text-red"
        t_sign = "+" if pnl_pct > 0 else ""
        trend_state = weekly_trends.get(live_data['Fetch_T'], "Neutral")
        
        if pnl_pct >= 15:
            sl_val = buy_p * 1.10
            t1_val = buy_p * 1.25
            advice = "🔥 FREE RIDE (Hold)"; adv_color = "color:#00BFFF; font-weight:bold;"
        elif pnl_pct >= 10:
            sl_val = buy_p * 1.02
            t1_val = buy_p * 1.15
            advice = "🚀 BOOK 50% & TRAIL"; adv_color = "color:#3fb950; font-weight:bold;"
        elif pnl_pct >= 5:
            sl_val = buy_p * 0.98
            t1_val = buy_p * 1.10
            advice = "🟢 HOLD STRONG"; adv_color = "color:#2ea043;"
        elif pnl_pct <= -5:
            sl_val = buy_p * 0.95
            t1_val = buy_p * 1.10
            advice = "🔴 CUT LOSSES NOW!"; adv_color = "color:#f85149; font-weight:bold;"
        else:
            sl_val = buy_p * 0.95
            t1_val = buy_p * 1.10
            advice = "🟡 WATCH (In Zone)"; adv_color = "color:#ffd700;"

        if trend_state == 'Bearish' and pnl_pct < 0:
            advice = "🩸 BEARISH (Exit on Bounce)"; adv_color = "color:#f85149;"

        if trend_state == 'Bullish': trend_html = "🟢 Bull"
        elif trend_state == 'Bearish': trend_html = "🔴 Bear"
        else: trend_html = "⚪ Neut"
        
        row_str = f'<tr class="{bg_class}"><td class="t-symbol"><a href="https://in.tradingview.com/chart/?symbol=NSE:{sym}" target="_blank">{sym}</a></td>'
        row_str += f'<td>{buy_p:.2f}</td><td>{ltp:.2f}</td><td class="{pnl_color}">{t_sign}{pnl_pct:.2f}%</td><td style="font-size:10px;">{trend_html}</td>'
        row_str += f'<td style="color:#f85149; font-weight:bold;">{sl_val:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t1_val:.2f}</td><td style="{adv_color}">{advice}</td></tr>'
        html += row_str
        
    html += "</tbody></table>"
    return html

def render_swing_terminal_table(df_subset):
    if df_subset.empty: return "<div style='padding:20px; text-align:center; color:#8b949e; border: 1px dashed #30363d; border-radius:8px;'>No Swing Trading Setups found right now.</div>"
    df_sorted = df_subset.reset_index(drop=True)
    html = f'<table class="term-table"><thead><tr><th colspan="10" class="term-head-swing">🌊 SWING TRADING RADAR (RANKED ALGORITHM)</th></tr><tr style="background-color: #21262d;"><th style="width:4%;">RANK</th><th style="text-align:left; width:13%;">STOCK</th><th style="width:9%;">LTP</th><th style="width:9%;">DAY%</th><th style="width:8%;">VOL</th><th style="width:17%;">STATUS</th><th style="width:11%; color:#f85149;">🛑 STOP LOSS</th><th style="width:11%; color:#3fb950;">🎯 TARGET 1</th><th style="width:11%; color:#3fb950;">🎯 TARGET 2</th><th style="width:7%;">SCORE</th></tr></thead><tbody>'
    for i, row in df_sorted.iterrows():
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        day_color = "text-green" if row['Day_C'] >= 0 else "text-red"
        strat_icon = str(row.get('Strategy_Icon', ''))
        base_status = generate_status(row)
        custom_status = f"{strat_icon} | {base_status}".strip() if strat_icon else base_status
        w_ema10 = float(row['W_EMA10'])
        w_ema50 = float(row['W_EMA50'])
        ltp = float(row['P'])
        if ltp > w_ema10 and w_ema10 >= w_ema50: trend_state = 'Bullish'
        elif ltp < w_ema10 and w_ema10 <= w_ema50: trend_state = 'Bearish'
        else: trend_state = 'Neutral'
        is_down = trend_state == 'Bearish' or (trend_state == 'Neutral' and row['C'] < 0)
        if trend_state == 'Bullish': custom_status += " 🟢Trend"
        elif trend_state == 'Bearish': custom_status += " 🔴Trend"
        atr_val = row.get("ATR", row["P"] * 0.02)
        default_sl = (row["P"] + (1.5 * atr_val)) if is_down else (row["P"] - (1.5 * atr_val))
        default_t1 = (row["P"] - (1.5 * atr_val)) if is_down else (row["P"] + (1.5 * atr_val))
        default_t2 = (row["P"] - (3.0 * atr_val)) if is_down else (row["P"] + (3.0 * atr_val))
        sl_val = row.get('SL', default_sl)
        t1_val = row.get('T1', default_t1)
        t2_val = row.get('T2', default_t2)
        rank_badge = f"🏆 1" if i == 0 else f"{i+1}"
        row_str = f'<tr class="{bg_class}"><td><b>{rank_badge}</b></td><td class="t-symbol"><a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank">{row["T"]}</a></td>'
        row_str += f'<td>{row["P"]:.2f}</td><td class="{day_color}">{row["Day_C"]:.2f}%</td><td>{row["VolX"]:.1f}x</td><td style="font-size:10px; cursor:help;" title="{custom_status}">{custom_status}</td>'
        row_str += f'<td style="color:#f85149; font-weight:bold;">{sl_val:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t1_val:.2f}</td>'
        row_str += f'<td style="color:#3fb950; font-weight:bold;">{t2_val:.2f}</td><td style="color:#ffd700;">{int(row["S"])}</td></tr>'
        html += row_str 
    html += "</tbody></table>"
    return html

def render_highscore_terminal_table(df_subset):
    if df_subset.empty: return "<div style='padding:20px; text-align:center; color:#8b949e; border: 1px dashed #30363d; border-radius:8px;'>No High Score Stocks found right now.</div>"
    is_ai = 'AI_Prob' in df_subset.columns
    if is_ai: headers = '<th style="width:7%; color:#00BFFF;">🤖 AI</th><th style="width:5%;">SCORE</th>'
    else: headers = '<th style="width:6%;">SCORE</th>'
    df_sorted = df_subset.reset_index(drop=True)
    html = f'<table class="term-table"><thead><tr><th colspan="12" class="term-head-high">🔥 HIGH SCORE RADAR (RANKED INTRADAY MOVERS)</th></tr><tr style="background-color: #21262d;"><th style="width:4%;">RANK</th><th style="text-align:left; width:12%;">STOCK</th><th style="width:9%; color:#ffd700;">SECTOR</th><th style="width:7%;">LTP</th><th style="width:7%;">DAY%</th><th style="width:6%;">VOL</th><th style="width:16%;">STATUS</th><th style="width:10%; color:#f85149;">🛑 SL</th><th style="width:10%; color:#3fb950;">🎯 T1</th><th style="width:10%; color:#3fb950;">🎯 T2</th>{headers}</tr></thead><tbody>'
    for i, row in df_sorted.iterrows():
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        day_color = "text-green" if row['Day_C'] >= 0 else "text-red"
        strat_icon = str(row.get('Strategy_Icon', ''))
        base_status = generate_status(row)
        custom_status = f"{strat_icon} | {base_status}".strip() if strat_icon else base_status
        is_down = row['C'] < 0
        atr_val = row.get("ATR", row["P"] * 0.02)
        default_sl = (row["P"] + (1.5 * atr_val)) if is_down else (row["P"] - (1.5 * atr_val))
        default_t1 = (row["P"] - (1.5 * atr_val)) if is_down else (row["P"] + (1.5 * atr_val))
        default_t2 = (row["P"] - (3.0 * atr_val)) if is_down else (row["P"] + (3.0 * atr_val))
        sl_val = row.get('SL', default_sl)
        t1_val = row.get('T1', default_t1)
        t2_val = row.get('T2', default_t2)
        rank_badge = f"🏆 1" if i == 0 else f"{i+1}"
        row_str = f'<tr class="{bg_class}"><td><b>{rank_badge}</b></td><td class="t-symbol"><a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank">{row["T"]}</a></td>'
        sec_name = row.get("Sector", "OTHER")
        sec_pts = int(row.get("Sector_Bonus", 0))
        if sec_pts > 0: sec_display = f"{sec_name}<br><span style='color:#00BFFF;'>({sec_pts} Pts)</span>"
        else: sec_display = f"{sec_name}"
        row_str += f'<td style="font-size:10px; color:#c9d1d9; font-weight:bold;">{sec_display}</td>'
        row_str += f'<td>{row["P"]:.2f}</td><td class="{day_color}">{row["Day_C"]:.2f}%</td><td>{row["VolX"]:.1f}x</td><td style="font-size:10px; cursor:help;" title="{custom_status}">{custom_status}</td>'
        row_str += f'<td style="color:#f85149; font-weight:bold;">{sl_val:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t1_val:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t2_val:.2f}</td>'
        if is_ai: row_str += f'<td style="color:#00BFFF; font-weight:bold; font-size:13px;">{int(row["AI_Prob"])}%</td><td style="color:#ffd700;">{int(row["S"])}</td></tr>'
        else: row_str += f'<td style="color:#ffd700;">{int(row["S"])}</td></tr>'
        html += row_str
    html += "</tbody></table>"
    return html

def render_levels_table(df_subset):
    if df_subset.empty: return "<div style='padding:20px; text-align:center; color:#8b949e; border: 1px dashed #30363d; border-radius:8px;'>No Stocks found right now.</div>"
    df_sorted = df_subset.reset_index(drop=True)
    html = f'<table class="term-table"><thead><tr><th colspan="10" class="term-head-levels">🎯 INTRADAY TRADING LEVELS (SUPPORT & RESISTANCE)</th></tr><tr style="background-color: #21262d;"><th style="width:4%;">RANK</th><th style="text-align:left; width:13%;">STOCK</th><th style="width:9%;">LTP</th><th style="width:9%;">DAY%</th><th style="width:8%;">VOL</th><th style="width:17%;">STATUS</th><th style="width:11%; color:#f85149;">🛑 STOP LOSS</th><th style="width:11%; color:#3fb950;">🎯 TARGET 1</th><th style="width:11%; color:#3fb950;">🎯 TARGET 2</th><th style="width:7%;">SCORE</th></tr></thead><tbody>'
    for i, row in df_sorted.iterrows():
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        day_color = "text-green" if row['Day_C'] >= 0 else "text-red"
        strat_icon = str(row.get('Strategy_Icon', ''))
        base_status = generate_status(row)
        custom_status = f"{strat_icon} | {base_status}".strip() if strat_icon else base_status
        is_down = row['C'] < 0
        atr_val = row.get("ATR", row["P"] * 0.02)
        default_sl = (row["P"] + (1.5 * atr_val)) if is_down else (row["P"] - (1.5 * atr_val))
        default_t1 = (row["P"] - (1.5 * atr_val)) if is_down else (row["P"] + (1.5 * atr_val))
        default_t2 = (row["P"] - (3.0 * atr_val)) if is_down else (row["P"] + (3.0 * atr_val))
        sl_val = row.get('SL', default_sl)
        t1_val = row.get('T1', default_t1)
        t2_val = row.get('T2', default_t2)
        rank_badge = f"🏆 1" if i == 0 else f"{i+1}"
        row_str = f'<tr class="{bg_class}"><td><b>{rank_badge}</b></td><td class="t-symbol"><a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank">{row["T"]}</a></td>'
        row_str += f'<td>{row["P"]:.2f}</td><td class="{day_color}">{row["Day_C"]:.2f}%</td><td>{row["VolX"]:.1f}x</td><td style="font-size:10px; cursor:help;" title="{custom_status}">{custom_status}</td>'
        row_str += f'<td style="color:#f85149; font-weight:bold;">{sl_val:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t1_val:.2f}</td>'
        row_str += f'<td style="color:#3fb950; font-weight:bold;">{t2_val:.2f}</td><td style="color:#ffd700;">{int(row["S"])}</td></tr>'
        html += row_str
    html += "</tbody></table>"
    return html

# --- MINI-CHART RENDERER (NO V/E OVERLAP + EXPAND & SCREENSHOT BUTTONS + 12H IST) ---
def render_chart(row, df_chart, show_pin=True, key_suffix="", timeframe="Intraday (5m)", show_crosshair=False, show_vol=False):
    display_sym = row['T']
    fetch_sym = row['Fetch_T']
    pct_val = float(row.get('W_C', row['Day_C'])) if timeframe == "Weekly Chart" else float(row['Day_C'])
    color_hex = "#da3633" if pct_val < 0 else "#2ea043"
    sign = "+" if pct_val > 0 else ""
    tv_link = f"https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(fetch_sym, 'NSE:' + display_sym)}"

    if show_pin:
        cb_key = f"cb_{fetch_sym}_{key_suffix}" if key_suffix else f"cb_{fetch_sym}"
        is_pinned = fetch_sym in st.session_state.pinned_stocks
        st.checkbox(
            "pin", value=is_pinned, key=cb_key, label_visibility="collapsed",
            on_change=_on_pin_checkbox_change, args=(fetch_sym, display_sym, cb_key)
        )

    strat_tag = f" <span style='font-size:10px; background:rgba(0,191,255,0.2); border:1px solid #00BFFF; padding:1px 4px; border-radius:3px; color:#00BFFF;'>{row.get('Strategy_Icon', '')}</span>" if row.get('Strategy_Icon') and row.get('Strategy_Icon') != "Neutral" else ""

    if timeframe == "Intraday (5m)":
        day_high, day_low, ltp_now = float(row.get('H', 0)), float(row.get('L', 0)), float(row.get('P', 0))
        if pct_val >= 0:
            intraday_pb = ((day_high - ltp_now) / day_high) * 100 if day_high > 0 else 0
            pb_tag = f" &nbsp;<span style='color:#FF8C00; font-size:11px;'>📉 -{intraday_pb:.1f}% DH</span>" if intraday_pb >= 0.1 else ""
        else:
            intraday_bounce = ((ltp_now - day_low) / day_low) * 100 if day_low > 0 else 0
            pb_tag = f" &nbsp;<span style='color:#00BFFF; font-size:11px;'>📈 +{intraday_bounce:.1f}% DL</span>" if intraday_bounce >= 0.1 else ""
    else:
        pb_val = float(row.get('Pullback_52W', 0))
        pb_tag = f" &nbsp;<span style='color:#FF8C00; font-size:11px;'>📉 -{pb_val:.1f}% 52WH</span>" if pb_val >= 0.1 else ""

    title_html = f"<a href='{tv_link}' target='_blank' style='color:#ffffff; text-decoration:none; line-height:1.2;'><b>{display_sym}</b>{strat_tag}<br><span style='font-size:12px; color:#cccccc;'>₹{row['P']:.2f} &nbsp;<span style='color:{color_hex};'>({sign}{pct_val:.2f}%)</span>{pb_tag}</span></a>"

    try:
        if not df_chart.empty and 'Low' in df_chart.columns and 'High' in df_chart.columns:
            df_chart = _fix_ist_df(df_chart) if timeframe == "Intraday (5m)" else df_chart.copy()
            if timeframe == "Intraday (5m)":
                df_chart = df_chart.tail(75)
            min_val, max_val = df_chart['Low'].min(), df_chart['High'].max()
            y_padding = (max_val - min_val) * 0.15 if (max_val - min_val) != 0 else min_val * 0.005

            chart_times = pd.to_datetime(df_chart.index)
            x_labels = chart_times.strftime('%I:%M %p') if timeframe == "Intraday (5m)" else chart_times.strftime('%d-%b')
            x_idx = list(range(len(df_chart)))

            hover_data = (
                "🕒 " + chart_times.strftime('%d-%b %I:%M %p IST') +
                "<br>🟢 O: ₹" + df_chart['Open'].round(2).astype(str) +
                "<br>📈 H: ₹" + df_chart['High'].round(2).astype(str) +
                "<br>📉 L: ₹" + df_chart['Low'].round(2).astype(str) +
                "<br>🔴 C: ₹" + df_chart['Close'].round(2).astype(str)
            )

            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=x_idx, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'],
                increasing_line_color='#2ea043', increasing_fillcolor='#2ea043', increasing_line_width=1,
                decreasing_line_color='#da3633', decreasing_fillcolor='#da3633', decreasing_line_width=1,
                showlegend=False, hoverinfo='skip'
            ))
            fig.add_trace(go.Scatter(
                x=x_idx, y=df_chart['Close'], mode='lines', line=dict(color='rgba(0,0,0,0)'),
                showlegend=False, hoverinfo='text' if show_crosshair else 'skip',
                text=hover_data, hovertemplate="%{text}<extra></extra>" if show_crosshair else None
            ))

            if timeframe == "Daily Chart":
                if 'SMA_50' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_50'], mode='lines', line=dict(color='#FFD700', width=1.5), showlegend=False, hoverinfo='skip'))
                if 'SMA_150' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_150'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), showlegend=False, hoverinfo='skip'))
                if 'SMA_200' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_200'], mode='lines', line=dict(color='#FF4500', width=2), showlegend=False, hoverinfo='skip'))
            elif timeframe == "Weekly Chart":
                if 'SMA_10' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_10'], mode='lines', line=dict(color='#FFD700', width=1.5), showlegend=False, hoverinfo='skip'))
                if 'SMA_40' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_40'], mode='lines', line=dict(color='#FF4500', width=2), showlegend=False, hoverinfo='skip'))
            else:
                offset = -4 if len(df_chart) >= 4 else -1
                tag_idx = x_idx[offset]
                last_close = float(df_chart['Close'].iloc[-1])
                has_vwap = 'VWAP' in df_chart.columns
                has_ema = 'EMA_10' in df_chart.columns
                last_vwap = float(df_chart['VWAP'].iloc[-1]) if has_vwap else 0
                last_ema = float(df_chart['EMA_10'].iloc[-1]) if has_ema else 0
                tag_y_vwap = float(df_chart['VWAP'].iloc[offset]) if has_vwap else 0
                tag_y_ema = float(df_chart['EMA_10'].iloc[offset]) if has_ema else 0

                v_anchor = "bottom" if last_close <= last_vwap else "top"
                e_anchor = "bottom" if last_close <= last_ema else "top"
                v_shift = 7 if v_anchor == "bottom" else -7
                e_shift = 7 if e_anchor == "bottom" else -7

                # OLD CODE ANTI-OVERLAP LOGIC: Keeps V: and E: boxes separate!
                if has_vwap and has_ema and abs(tag_y_vwap - tag_y_ema) / (max_val - min_val + 0.001) < 0.18:
                    if tag_y_vwap >= tag_y_ema:
                        v_anchor, v_shift = "bottom", 9
                        e_anchor, e_shift = "top", -9
                    else:
                        v_anchor, v_shift = "top", -9
                        e_anchor, e_shift = "bottom", 9

                if has_vwap:
                    fig.add_trace(go.Scatter(x=x_idx, y=df_chart['VWAP'], mode='lines', line=dict(color='#FFD700', width=1.5, dash='dot'), showlegend=False, hoverinfo='skip'))
                    fig.add_annotation(x=tag_idx, y=tag_y_vwap, text=f"V:{last_vwap:.1f}", showarrow=False, xanchor="right", yanchor=v_anchor, xshift=-5, yshift=v_shift, font=dict(color="#161b22", size=10, family="monospace", weight="bold"), bgcolor="#FFD700", borderpad=2)
                if has_ema:
                    fig.add_trace(go.Scatter(x=x_idx, y=df_chart['EMA_10'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), showlegend=False, hoverinfo='skip'))
                    fig.add_annotation(x=tag_idx, y=tag_y_ema, text=f"E:{last_ema:.1f}", showarrow=False, xanchor="right", yanchor=e_anchor, xshift=-5, yshift=e_shift, font=dict(color="#161b22", size=10, family="monospace", weight="bold"), bgcolor="#00BFFF", borderpad=2)

            fig.update_layout(
                margin=dict(l=0, r=46 if show_crosshair else 5, t=0, b=16 if show_crosshair else 0),
                height=230, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                showlegend=False, xaxis_rangeslider_visible=False,
                hovermode='closest' if show_crosshair else False, dragmode=False
            )
            fig.add_annotation(text=title_html, xref="paper", yref="paper", x=0, xanchor="left", xshift=35, y=0.98, yanchor="top", showarrow=False, font=dict(size=13, color="#ffffff"), bgcolor="rgba(0,0,0,0)", borderwidth=0)

            if show_crosshair:
                t_step = max(1, len(x_idx) // 4)
                fig.update_xaxes(
                    showspikes=True, spikemode='across+toaxis', spikesnap='cursor', spikethickness=1, spikedash='dash', spikecolor='#8b949e',
                    tickvals=x_idx[::t_step], ticktext=list(x_labels[::t_step]), tickfont=dict(color='#8b949e', size=9),
                    showgrid=False, zeroline=False, showticklabels=True, fixedrange=True
                )
                fig.update_yaxes(
                    showspikes=True, spikemode='across+toaxis', spikesnap='cursor', spikethickness=1, spikedash='dash', spikecolor='#8b949e',
                    showgrid=False, zeroline=False, showticklabels=True, side='right', tickfont=dict(color="#ffffff", size=9.5),
                    fixedrange=True, range=[min_val - y_padding, max_val + (y_padding * 2.5)]
                )
            else:
                fig.update_xaxes(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True)
                fig.update_yaxes(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True, range=[min_val - y_padding, max_val + (y_padding * 2.5)])

            # Removed displayModeBar:False so Camera (Screenshot) & Expand icons appear!
            st.plotly_chart(fig, width="stretch", key=f"plot_{fetch_sym}_{key_suffix}_{timeframe}_{show_vol}_{show_crosshair}")
    except Exception as e:
        st.markdown(f"<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888;'>Chart error: {e}</div>", unsafe_allow_html=True)

def render_chart_grid(df_grid, show_pin_option, key_prefix, timeframe="Intraday (5m)", chart_dict=None, show_crosshair=False, show_vol=False, is_sector=False):
    if df_grid.empty: return
    if chart_dict is None: chart_dict = {}
    with st.container():
        st.markdown("<div class='fluid-board'></div>", unsafe_allow_html=True)
        for _, row in df_grid.iterrows():
            with st.container():
                render_chart(row, chart_dict.get(row['Fetch_T'], pd.DataFrame()), show_pin=show_pin_option, key_suffix=key_prefix, timeframe=timeframe, show_crosshair=show_crosshair, show_vol=show_vol)
                
                if is_sector:
                    btn_lbl = f"🔽 View Stocks" if st.session_state.active_sec != row['T'] else f"🔼 Hide Stocks"
                    if st.button(btn_lbl, key=f"btn_sec_{row['Fetch_T']}", width="stretch"):
                        if st.session_state.active_sec == row['T']:
                            st.session_state.active_sec = None
                        else:
                            st.session_state.active_sec = row['T']
                        st.rerun(scope="fragment")  # 🔧 PERF

def render_closed_trades_table(df_closed):
    if df_closed.empty: return "<div style='padding:20px; text-align:center; color:#8b949e; border:1px dashed #30363d; border-radius:8px;'>No closed trades yet. Sell a stock to book P&L!</div>"
    
    html = f'<table class="term-table"><thead><tr><th colspan="8" style="background-color:#4a148c; color:white; text-align:left; padding-left:10px;">📜 CLOSED TRADES (TRADE BOOK & P&L)</th></tr><tr style="background-color: #21262d;"><th style="width:12%; text-align:left;">BUY DATE</th><th style="width:12%; text-align:left;">SELL DATE</th><th style="width:14%; text-align:left;">STOCK</th><th style="width:8%;">QTY</th><th style="width:13%;">BUY AVG</th><th style="width:13%;">SELL AVG</th><th style="width:15%;">REALIZED P&L (₹)</th><th style="width:13%;">P&L %</th></tr></thead><tbody>'
    
    total_realized_pnl = 0
    for i, (_, row) in enumerate(df_closed.iterrows()):
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        sym_raw = row.get('Symbol', '')
        sym = '' if pd.isna(sym_raw) else str(sym_raw)
        
        try: qty = int(float(row.get('Quantity', 0)))
        except: qty = 0
        try: buy_p = float(row.get('Buy_Price', 0))
        except: buy_p = 0.0
        try: sell_p = float(row.get('Sell_Price', 0))
        except: sell_p = 0.0
        try: pnl_rs = float(row.get('PnL_Rs', 0))
        except: pnl_rs = 0.0
        try: pnl_pct = float(row.get('PnL_Pct', 0))
        except: pnl_pct = 0.0
        
        total_realized_pnl += pnl_rs
        p_color = "text-green" if pnl_rs >= 0 else "text-red"
        p_sign = "+" if pnl_rs > 0 else ""
        
        buy_date_val = str(row.get("Buy_Date", "-"))
        if buy_date_val in ["nan", "NaN", ""]: buy_date_val = "-"
        sell_date_val = str(row.get("Sell_Date", "-"))
        
        html += f'<tr class="{bg_class}"><td style="text-align:left;">{buy_date_val}</td><td style="text-align:left;">{sell_date_val}</td><td class="t-symbol {p_color}" style="text-align:left;"><a href="https://in.tradingview.com/chart/?symbol=NSE:{sym}" target="_blank">{sym}</a></td><td>{qty}</td><td>{buy_p:.2f}</td><td>{sell_p:.2f}</td><td class="{p_color}">{p_sign}{pnl_rs:,.2f}</td><td class="{p_color}">{p_sign}{pnl_pct:.2f}%</td></tr>'
        
    tot_color = "text-green" if total_realized_pnl >= 0 else "text-red"
    tot_sign = "+" if total_realized_pnl > 0 else ""
    html += f'<tr class="port-total"><td colspan="6" style="text-align:right; padding-right:15px; font-size:13px;">NET REALIZED P&L:</td><td colspan="2" class="{tot_color}" style="font-size:14px; text-align:center;">{tot_sign}₹{total_realized_pnl:,.2f}</td></tr>'
    html += "</tbody></table>"
    return html

# --- 6. FETCH DATA ---
st.markdown("<hr style='margin:10px 0; border-color:#30363d;'>", unsafe_allow_html=True)

df = fetch_all_data()

if not df.empty:
    with LIVE_PRICES_LOCK:
        live_prices_snapshot = dict(LIVE_PRICES_GLOBAL)
    for i, row in df.iterrows():
        clean_sym = str(row['Fetch_T']).replace(".NS", "")
        if clean_sym in live_prices_snapshot:
            new_ltp = live_prices_snapshot[clean_sym]
            df.at[i, 'P'] = new_ltp
            open_p = df.at[i, 'O']
            prev_c = df.at[i, 'Prev_C']
            if open_p > 0: df.at[i, 'Day_C'] = ((new_ltp - open_p) / open_p) * 100
            if prev_c > 0: df.at[i, 'C'] = ((new_ltp - prev_c) / prev_c) * 100

all_names = []
if not df.empty:
    all_names = sorted(df[(~df['Is_Sector']) & (~df['Is_Index']) & (~df['Is_Commodity'])]['T'].unique().tolist())

# =========================================================
# --- 7. UI SETTINGS & TRADINGVIEW PRO GRID ENGINE (COMPLETE) ---
# =========================================================
import streamlit.components.v1 as components
import calendar

if 'grid_layout_mode' not in st.session_state:
    st.session_state.grid_layout_mode = "Off"  # "Off", "1", "2", "4", "6"
if 'pro_grid_theme' not in st.session_state:
    st.session_state.pro_grid_theme = "Light (White)"
if 'pro_grid_inds' not in st.session_state:
    st.session_state.pro_grid_inds = ["VWAP", "EMAs", "Pivots(R1,S1)", "S&R"]
if 'inspected_stock' not in st.session_state:
    st.session_state.inspected_stock = "NIFTY"
if 'wl_sort_col' not in st.session_state:
    st.session_state.wl_sort_col = "Chg%"
if 'wl_sort_asc' not in st.session_state:
    st.session_state.wl_sort_asc = False
if 'selected_ai_strats' not in st.session_state:
    st.session_state.selected_ai_strats = [ADAPTIVE_STRAT, "All Day Trading Moves 🚀", NEWS_STRAT]
if 'selected_sw_strats' not in st.session_state:
    st.session_state.selected_sw_strats = ["📈 Minervini Trend Template (VCP)"]

# --- CSS: ZERO 1-INCH SIDE MARGINS + SORTABLE WATCHLIST + PRO GRID ---
st.markdown("""
    <style>
    /* 1. Eliminate 1-inch Left & Right Margins across all Streamlit containers */
    header[data-testid="stHeader"] { height: 0.5rem !important; background: transparent !important; }
    .block-container,
    div[data-testid="stAppViewBlockContainer"],
    div[data-testid="stMainBlockContainer"],
    .main .block-container,
    section.main > div {
        padding-top: 0.15rem !important;
        padding-bottom: 0.15rem !important;
        padding-left: 0.15rem !important;
        padding-right: 0.15rem !important;
        max-width: 100% !important;
        width: 100% !important;
    }
    .block-container > div > div > div > hr { display: none !important; }

    /* 2. Prevent old Line 148 (.fluid-board) from hiding Left 80% Container */
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div:nth-child(1) {
        display: block !important;
    }

    /* 3. Safe Mini-Chart Grid using .pro-mini-board */
    /* Fix overlapping checkboxes inside Select Strategies */
    div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:has(div[data-testid="stCheckbox"]) {
        margin-bottom: 0px !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) > div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:has(div[data-testid="stCheckbox"]) {
        margin-bottom: -45px !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) {
        display: grid !important;
        gap: 8px !important;
        align-items: start !important;
    }
    div[data-testid="stElementContainer"]:has(.pro-mini-board) { display: none !important; }
    @media screen and (min-width: 1600px) {
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) { grid-template-columns: repeat(6, 1fr) !important; }
    }
    @media screen and (min-width: 1200px) and (max-width: 1599px) {
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) { grid-template-columns: repeat(5, 1fr) !important; }
    }
    @media screen and (min-width: 900px) and (max-width: 1199px) {
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) { grid-template-columns: repeat(4, 1fr) !important; }
    }
    @media screen and (min-width: 650px) and (max-width: 899px) {
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) { grid-template-columns: repeat(3, 1fr) !important; }
    }
    @media screen and (max-width: 649px) {
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) { grid-template-columns: repeat(2, 1fr) !important; gap: 6px !important; }
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) > div[data-testid="stVerticalBlock"] {
        background-color: #161b22 !important;
        border: 1px solid #30363d !important;
        border-radius: 8px !important;
        padding: 4px !important;
        position: relative !important;
        width: 100% !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) > div[data-testid="stVerticalBlock"] div[data-testid="stCheckbox"] {
        position: absolute !important;
        top: 8px !important;
        left: 8px !important;
        z-index: 100 !important;
    }

    /* 4. Clickable Sort Header Buttons (Symbol | Last | Chg | Chg%) */
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-sort-hdr-marker) div.stButton > button {
        background-color: #161b22 !important;
        border: none !important;
        border-top: 1px solid #30363d !important;
        border-bottom: 1px solid #30363d !important;
        border-radius: 0px !important;
        height: 30px !important;
        min-height: 30px !important;
        padding: 0px 4px !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-sort-hdr-marker) div.stButton > button p {
        font-family: 'Consolas', monospace !important;
        font-size: 12px !important;
        font-weight: bold !important;
        color: #58a6ff !important;
        margin: 0px !important;
    }
    div[data-testid="stElementContainer"]:has(.tv-sort-hdr-marker) { display: none !important; }

    /* 5. TradingView Flat Watchlist Rows (Bigger Font & Bright Colors) */
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-wl-marker) div.stButton > button {
        background-color: transparent !important;
        border: none !important;
        border-bottom: 1px solid #21262d !important;
        border-radius: 0px !important;
        height: 32px !important;
        min-height: 32px !important;
        padding: 0px 4px !important;
        margin: 0px !important;
        width: 100% !important;
        display: flex !important;
        justify-content: flex-start !important;
        text-align: left !important;
        padding-left: 0px !important;
        align-items: center !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-wl-marker) div.stButton > button:hover {
        background-color: #1f2937 !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-wl-marker) div.stButton > button p {
        font-family: 'Consolas', 'Courier New', monospace !important;
        font-size: 12.5px !important;
        font-weight: bold !important;
        color: #ffffff !important;
        white-space: pre !important;
        text-align: left !important;
        margin: 0px !important;
        width: 100% !important;
        letter-spacing: -0.3px !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-wl-marker) { gap: 0px !important; }
    div[data-testid="stElementContainer"]:has(.tv-wl-marker) { display: none !important; }

    /* Red Close [X] Button Styling */
    div[data-testid="stElementContainer"]:has(.close-x-marker) + div div.stButton > button {
        background-color: #dc2626 !important;
        border: 1px solid #ef4444 !important;
        color: #ffffff !important;
        height: 28px !important;
        min-height: 28px !important;
        padding: 0px !important;
        font-weight: bold !important;
    }
    div[data-testid="stElementContainer"]:has(.close-x-marker) { display: none !important; }

    @media screen and (max-width: 768px) {
        div[data-testid="stHorizontalBlock"] { flex-direction: column-reverse !important; }
        div[data-testid="stColumn"] { width: 100% !important; flex: 1 1 100% !important; }
    }
    </style>
""", unsafe_allow_html=True)


# --- IST TIMEZONE CONVERTER FOR 5-MIN CHARTS (FIXES UTC 03:45 -> IST 09:15) ---
def _fix_ist_df(df_in):
    if df_in is None or df_in.empty:
        return pd.DataFrame()
    d = df_in.copy()
    d.index = pd.to_datetime(d.index)
    if d.index.tz is not None:
        d.index = d.index.tz_convert('Asia/Kolkata').tz_localize(None)
    else:
        # Cached yfinance 5m data stripped UTC without adding +5:30 (starts at 03:45 instead of 09:15)
        if len(d.index) > 0 and (3 <= d.index.hour.min() <= 4) and (d.index.hour.max() <= 11):
            d.index = d.index + pd.Timedelta(hours=5, minutes=30)
    return d[~d.index.duplicated(keep='last')].sort_index()


# --- CALLBACK HELPERS ---
def _toggle_wl_stock(s_ft, s_disp):
    st.session_state.inspected_stock = s_disp
    if s_ft in st.session_state.pinned_stocks:
        st.session_state.pinned_stocks.remove(s_ft)
    else:
        if len(st.session_state.pinned_stocks) >= 6:
            st.session_state.pinned_stocks.pop(0)
        st.session_state.pinned_stocks.append(s_ft)
    if st.session_state.pinned_stocks:
        cnt = len(st.session_state.pinned_stocks)
        st.session_state.grid_layout_mode = "1" if cnt == 1 else ("2" if cnt == 2 else ("4" if cnt <= 4 else "6"))
    else:
        st.session_state.grid_layout_mode = "Off"


def _close_pro_chart(s_ft, current_grid_syms):
    active_list = list(st.session_state.pinned_stocks) if st.session_state.pinned_stocks else list(current_grid_syms)
    if s_ft in active_list:
        active_list.remove(s_ft)
    st.session_state.pinned_stocks = active_list
    if not active_list:
        st.session_state.grid_layout_mode = "Off"
    else:
        cnt = len(active_list)
        st.session_state.grid_layout_mode = "1" if cnt == 1 else ("2" if cnt == 2 else ("4" if cnt <= 4 else "6"))


def _on_pin_checkbox_change(fetch_sym, display_sym, cb_key):
    pin_val = st.session_state.get(cb_key, False)
    if pin_val:
        if fetch_sym not in st.session_state.pinned_stocks:
            if len(st.session_state.pinned_stocks) >= 6:
                st.session_state.pinned_stocks.pop(0)
            st.session_state.pinned_stocks.append(fetch_sym)
        st.session_state.inspected_stock = display_sym
        cnt = len(st.session_state.pinned_stocks)
        st.session_state.grid_layout_mode = "1" if cnt == 1 else ("2" if cnt == 2 else ("4" if cnt <= 4 else "6"))
    else:
        if fetch_sym in st.session_state.pinned_stocks:
            st.session_state.pinned_stocks.remove(fetch_sym)
        if not st.session_state.pinned_stocks:
            st.session_state.grid_layout_mode = "Off"


def _set_wl_sort(col_name):
    if st.session_state.wl_sort_col == col_name:
        st.session_state.wl_sort_asc = not st.session_state.wl_sort_asc
    else:
        st.session_state.wl_sort_col = col_name
        st.session_state.wl_sort_asc = True if col_name == "Symbol" else False


# --- MINI-CHART GRID & SINGLE CHART (WITH TICK ON ALL INDICES & IST TIME) ---
def render_chart_grid(df_grid, show_pin_option, key_prefix, timeframe="Intraday (5m)", chart_dict=None, show_crosshair=False, show_vol=False, is_sector=False):
    if df_grid is None or df_grid.empty:
        return
    if chart_dict is None:
        chart_dict = {}
    with st.container():
        st.markdown("<div class='pro-mini-board'></div>", unsafe_allow_html=True)
        for _, row in df_grid.iterrows():
            with st.container():
                render_chart(
                    row, chart_dict.get(row['Fetch_T'], pd.DataFrame()),
                    show_pin=True,  # Tick enabled on ALL Indices, Sectors & Stocks!
                    key_suffix=key_prefix,
                    timeframe=timeframe, show_crosshair=show_crosshair, show_vol=show_vol
                )
                if is_sector:
                    btn_lbl = "🔽 View Stocks" if st.session_state.active_sec != row['T'] else "🔼 Hide Stocks"
                    if st.button(btn_lbl, key=f"btn_sec_{row['Fetch_T']}", width="stretch"):
                        st.session_state.active_sec = None if st.session_state.active_sec == row['T'] else row['T']


def render_chart(row, df_chart, show_pin=True, key_suffix="", timeframe="Intraday (5m)", show_crosshair=False, show_vol=False):
    display_sym = row['T']
    fetch_sym = row['Fetch_T']
    pct_val = float(row.get('W_C', row['Day_C'])) if timeframe == "Weekly Chart" else float(row['Day_C'])
    color_hex = "#da3633" if pct_val < 0 else "#2ea043"
    sign = "+" if pct_val > 0 else ""
    tv_link = f"https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(fetch_sym, 'NSE:' + display_sym)}"

    if show_pin:
        cb_key = f"cb_{fetch_sym}_{key_suffix}" if key_suffix else f"cb_{fetch_sym}"
        is_pinned = fetch_sym in st.session_state.pinned_stocks
        st.checkbox(
            "pin", value=is_pinned, key=cb_key, label_visibility="collapsed",
            on_change=_on_pin_checkbox_change, args=(fetch_sym, display_sym, cb_key)
        )

    strat_tag = f" <span style='font-size:10px; background:rgba(0,191,255,0.2); border:1px solid #00BFFF; padding:1px 4px; border-radius:3px; color:#00BFFF;'>{row.get('Strategy_Icon', '')}</span>" if row.get('Strategy_Icon') and row.get('Strategy_Icon') != "Neutral" else ""

    if timeframe == "Intraday (5m)":
        day_high, day_low, ltp_now = float(row.get('H', 0)), float(row.get('L', 0)), float(row.get('P', 0))
        if pct_val >= 0:
            intraday_pb = ((day_high - ltp_now) / day_high) * 100 if day_high > 0 else 0
            pb_tag = f" &nbsp;<span style='color:#FF8C00; font-size:11px;'>📉 -{intraday_pb:.1f}% DH</span>" if intraday_pb >= 0.1 else ""
        else:
            intraday_bounce = ((ltp_now - day_low) / day_low) * 100 if day_low > 0 else 0
            pb_tag = f" &nbsp;<span style='color:#00BFFF; font-size:11px;'>📈 +{intraday_bounce:.1f}% DL</span>" if intraday_bounce >= 0.1 else ""
    else:
        pb_val = float(row.get('Pullback_52W', 0))
        pb_tag = f" &nbsp;<span style='color:#FF8C00; font-size:11px;'>📉 -{pb_val:.1f}% 52WH</span>" if pb_val >= 0.1 else ""

    title_html = f"<a href='{tv_link}' target='_blank' style='color:#ffffff; text-decoration:none; line-height:1.2;'><b>{display_sym}</b>{strat_tag}<br><span style='font-size:12px; color:#cccccc;'>₹{row['P']:.2f} &nbsp;<span style='color:{color_hex};'>({sign}{pct_val:.2f}%)</span>{pb_tag}</span></a>"

    try:
        if not df_chart.empty and 'Low' in df_chart.columns and 'High' in df_chart.columns:
            df_chart = _fix_ist_df(df_chart) if timeframe == "Intraday (5m)" else df_chart.copy()
            if timeframe == "Intraday (5m)":
                df_chart = df_chart.tail(75)
            min_val, max_val = df_chart['Low'].min(), df_chart['High'].max()
            y_padding = (max_val - min_val) * 0.15 if (max_val - min_val) != 0 else min_val * 0.005

            chart_times = pd.to_datetime(df_chart.index)
            x_labels = chart_times.strftime('%I:%M %p') if timeframe == "Intraday (5m)" else chart_times.strftime('%d-%b')
            x_idx = list(range(len(df_chart)))

            hover_data = (
                "🕒 " + chart_times.strftime('%d-%b %I:%M %p IST') +
                "<br>O: ₹" + df_chart['Open'].round(2).astype(str) +
                " | H: ₹" + df_chart['High'].round(2).astype(str) +
                "<br>L: ₹" + df_chart['Low'].round(2).astype(str) +
                " | C: ₹" + df_chart['Close'].round(2).astype(str)
            )

            fig = go.Figure()
            fig.add_trace(go.Candlestick(
                x=x_idx, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'],
                increasing_line_color='#2ea043', increasing_fillcolor='#2ea043', increasing_line_width=1,
                decreasing_line_color='#da3633', decreasing_fillcolor='#da3633', decreasing_line_width=1,
                showlegend=False, hoverinfo='skip'
            ))
            fig.add_trace(go.Scatter(
                x=x_idx, y=df_chart['Close'], mode='lines', line=dict(color='rgba(0,0,0,0)'),
                showlegend=False, hoverinfo='text' if show_crosshair else 'skip',
                text=hover_data, hovertemplate="%{text}<extra></extra>" if show_crosshair else None
            ))

            if timeframe == "Daily Chart":
                if 'SMA_50' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_50'], mode='lines', line=dict(color='#FFD700', width=1.5), showlegend=False, hoverinfo='skip'))
                if 'SMA_150' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_150'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), showlegend=False, hoverinfo='skip'))
                if 'SMA_200' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_200'], mode='lines', line=dict(color='#FF4500', width=2), showlegend=False, hoverinfo='skip'))
            elif timeframe == "Weekly Chart":
                if 'SMA_10' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_10'], mode='lines', line=dict(color='#FFD700', width=1.5), showlegend=False, hoverinfo='skip'))
                if 'SMA_40' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_40'], mode='lines', line=dict(color='#FF4500', width=2), showlegend=False, hoverinfo='skip'))
            else:
                offset = -4 if len(df_chart) >= 4 else -1
                tag_idx = x_idx[offset]
                last_close = float(df_chart['Close'].iloc[-1])
                has_vwap = 'VWAP' in df_chart.columns
                has_ema = 'EMA_10' in df_chart.columns
                last_vwap = float(df_chart['VWAP'].iloc[-1]) if has_vwap else 0
                last_ema = float(df_chart['EMA_10'].iloc[-1]) if has_ema else 0
                tag_y_vwap = float(df_chart['VWAP'].iloc[offset]) if has_vwap else 0
                tag_y_ema = float(df_chart['EMA_10'].iloc[offset]) if has_ema else 0

                v_anchor = "bottom" if last_close <= last_vwap else "top"
                e_anchor = "bottom" if last_close <= last_ema else "top"
                v_shift = 6 if v_anchor == "bottom" else -6
                e_shift = 6 if e_anchor == "bottom" else -6

                if has_vwap:
                    fig.add_trace(go.Scatter(x=x_idx, y=df_chart['VWAP'], mode='lines', line=dict(color='#FFD700', width=1.5, dash='dot'), showlegend=False, hoverinfo='skip'))
                    fig.add_annotation(x=tag_idx, y=tag_y_vwap, text=f"V:{last_vwap:.1f}", showarrow=False, xanchor="right", yanchor=v_anchor, xshift=-5, yshift=v_shift, font=dict(color="#161b22", size=10, family="monospace", weight="bold"), bgcolor="#FFD700", borderpad=2)
                if has_ema:
                    fig.add_trace(go.Scatter(x=x_idx, y=df_chart['EMA_10'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), showlegend=False, hoverinfo='skip'))
                    fig.add_annotation(x=tag_idx, y=tag_y_ema, text=f"E:{last_ema:.1f}", showarrow=False, xanchor="right", yanchor=e_anchor, xshift=-5, yshift=e_shift, font=dict(color="#161b22", size=10, family="monospace", weight="bold"), bgcolor="#00BFFF", borderpad=2)

            fig.update_layout(
                margin=dict(l=0, r=46 if show_crosshair else 5, t=0, b=16 if show_crosshair else 0),
                height=225, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                showlegend=False, xaxis_rangeslider_visible=False,
                hovermode='closest' if show_crosshair else False, dragmode=False
            )
            fig.add_annotation(text=title_html, xref="paper", yref="paper", x=0, xanchor="left", xshift=35, y=0.98, yanchor="top", showarrow=False, font=dict(size=13, color="#ffffff"), bgcolor="rgba(0,0,0,0)", borderwidth=0)

            if show_crosshair:
                t_step = max(1, len(x_idx) // 4)
                fig.update_xaxes(
                    showspikes=True, spikemode='across+toaxis', spikesnap='cursor', spikethickness=1, spikedash='dash', spikecolor='#8b949e',
                    tickvals=x_idx[::t_step], ticktext=list(x_labels[::t_step]), tickfont=dict(color='#8b949e', size=9),
                    showgrid=False, zeroline=False, showticklabels=True, fixedrange=True
                )
                fig.update_yaxes(
                    showspikes=True, spikemode='across+toaxis', spikesnap='cursor', spikethickness=1, spikedash='dash', spikecolor='#8b949e',
                    showgrid=False, zeroline=False, showticklabels=True, side='right', tickfont=dict(color="#ffffff", size=9.5),
                    fixedrange=True, range=[min_val - y_padding, max_val + (y_padding * 2.5)]
                )
            else:
                fig.update_xaxes(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True)
                fig.update_yaxes(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True, range=[min_val - y_padding, max_val + (y_padding * 2.5)])

            st.plotly_chart(fig, width="stretch", key=f"plot_{fetch_sym}_{key_suffix}_{timeframe}_{show_vol}_{show_crosshair}", config={'displayModeBar': False})
    except Exception as e:
        st.markdown(f"<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888;'>Chart error: {e}</div>", unsafe_allow_html=True)


# --- SUPERTREND HELPER ---
def _calc_supertrend(df_c, period=7, mult=3.0):
    try:
        hl2 = (df_c['High'] + df_c['Low']) / 2.0
        tr = pd.concat([df_c['High'] - df_c['Low'], (df_c['High'] - df_c['Close'].shift(1)).abs(), (df_c['Low'] - df_c['Close'].shift(1)).abs()], axis=1).max(axis=1)
        atr = tr.ewm(span=period, adjust=False).mean()
        up, dn = hl2 - (mult * atr), hl2 + (mult * atr)
        st_line = pd.Series(index=df_c.index, dtype=float)
        trend = 1
        for i in range(len(df_c)):
            if i == 0:
                st_line.iloc[i] = up.iloc[i]
                continue
            if df_c['Close'].iloc[i - 1] > up.iloc[i - 1]: up.iloc[i] = max(up.iloc[i], up.iloc[i - 1])
            if df_c['Close'].iloc[i - 1] < dn.iloc[i - 1]: dn.iloc[i] = min(dn.iloc[i], dn.iloc[i - 1])
            if df_c['Close'].iloc[i] > dn.iloc[i - 1]: trend = 1
            elif df_c['Close'].iloc[i] < up.iloc[i - 1]: trend = -1
            st_line.iloc[i] = up.iloc[i] if trend == 1 else dn.iloc[i]
        return st_line
    except Exception:
        return pd.Series(dtype=float)


# --- PRO GRID CHART ENGINE WITH IST TIMINGS + RED CLOSE [X] BUTTON ---
def render_pro_grid_chart(fetch_sym, row_data, df_c, timeframe, theme_mode, active_inds, chart_height=370, key_idx=0, current_grid_syms=None):
    disp_sym = row_data.get('T', fetch_sym.replace('.NS', ''))
    tf_short = "5m" if timeframe == "Intraday (5m)" else ("1D" if timeframe == "Daily Chart" else "1W")
    if current_grid_syms is None:
        current_grid_syms = []

    hc1, hc2 = st.columns([11.0, 1.0], gap="small")
    with hc1:
        ltp_v = float(row_data.get('P', 0))
        chg_v = float(row_data.get('Day_C', 0))
        c_col = "#3fb950" if chg_v >= 0 else "#f85149"
        st.markdown(
            f"<div style='background:#111622; border:1px solid #2b313f; border-radius:6px; padding:4px 10px; "
            f"display:flex; justify-content:space-between; align-items:center;'>"
            f"<span style='font-weight:bold; font-size:13px; color:#fff; font-family:monospace;'>"
            f"{disp_sym} <span style='background:#1e293b; color:#38bdf8; padding:1px 6px; border-radius:4px; font-size:11px;'>{tf_short}</span></span>"
            f"<span style='font-family:monospace; font-size:12.5px; color:#fff;'>₹{ltp_v:,.2f} "
            f"<b style='color:{c_col};'>({chg_v:+.2f}%)</b></span></div>",
            unsafe_allow_html=True
        )
    with hc2:
        st.markdown("<div class='close-x-marker'></div>", unsafe_allow_html=True)
        st.button(
            "✖", key=f"close_x_{fetch_sym}_{key_idx}",
            help=f"Close {disp_sym} Chart", width="stretch",
            on_click=_close_pro_chart, args=(fetch_sym, current_grid_syms)
        )

    if df_c is None or df_c.empty:
        st.info(f"⏳ Loading chart data for {disp_sym}...")
        return

    df_p = _fix_ist_df(df_c) if timeframe == "Intraday (5m)" else df_c.dropna(subset=['Open', 'High', 'Low', 'Close']).copy()
    df_p = df_p.tail(110).copy()
    if df_p.empty:
        st.info(f"No valid candles for {disp_sym}")
        return

    if 'VWAP' not in df_p.columns:
        tp = (df_p['High'] + df_p['Low'] + df_p['Close']) / 3.0
        df_p['VWAP'] = tp.expanding().mean()
    df_p['EMA10'] = df_p['Close'].ewm(span=10, adjust=False).mean()
    df_p['EMA20'] = df_p['Close'].ewm(span=20, adjust=False).mean()
    df_p['KALMAN'] = df_p['Close'].ewm(span=8, adjust=False).mean().ewm(span=5, adjust=False).mean()
    df_p['ST'] = _calc_supertrend(df_p, 7, 3.0)
    sma20 = df_p['Close'].rolling(20, min_periods=5).mean()
    std20 = df_p['Close'].rolling(20, min_periods=5).std()
    df_p['BB_UP'] = sma20 + 2.0 * std20
    df_p['BB_DN'] = sma20 - 2.0 * std20

    ph = float(row_data.get('Prev_H', df_p['High'].max()))
    pl = float(row_data.get('Prev_L', df_p['Low'].min()))
    pc = float(row_data.get('Prev_C', df_p['Close'].iloc[0]))
    piv = round((ph + pl + pc) / 3.0, 2)
    r1 = round(2 * piv - pl, 2)
    s1 = round(2 * piv - ph, 2)
    sr_high = round(float(df_p['High'].max()), 2)
    sr_low = round(float(df_p['Low'].min()), 2)

    candles_js, vol_js, vwap_js, ema10_js, ema20_js, kal_js, st_js, bb_u_js, bb_d_js = [], [], [], [], [], [], [], [], []
    seen_ts = set()
    for dt_idx, r in df_p.iterrows():
        # calendar.timegm maps naive IST datetime directly to UTC epoch so LightweightCharts displays exact IST (09:15 - 15:30)!
        ts = int(calendar.timegm(pd.Timestamp(dt_idx).timetuple()))
        if ts in seen_ts:
            continue
        seen_ts.add(ts)
        o, h, l, c = round(float(r['Open']), 2), round(float(r['High']), 2), round(float(r['Low']), 2), round(float(r['Close']), 2)
        v = float(r.get('Volume', 0)) if pd.notna(r.get('Volume', 0)) else 0.0
        candles_js.append({'time': ts, 'open': o, 'high': h, 'low': l, 'close': c})
        vol_js.append({'time': ts, 'value': v, 'color': 'rgba(20, 184, 166, 0.45)' if c >= o else 'rgba(239, 68, 68, 0.45)'})
        if pd.notna(r.get('VWAP')): vwap_js.append({'time': ts, 'value': round(float(r['VWAP']), 2)})
        if pd.notna(r.get('EMA10')): ema10_js.append({'time': ts, 'value': round(float(r['EMA10']), 2)})
        if pd.notna(r.get('EMA20')): ema20_js.append({'time': ts, 'value': round(float(r['EMA20']), 2)})
        if pd.notna(r.get('KALMAN')): kal_js.append({'time': ts, 'value': round(float(r['KALMAN']), 2)})
        if pd.notna(r.get('ST')): st_js.append({'time': ts, 'value': round(float(r['ST']), 2)})
        if pd.notna(r.get('BB_UP')): bb_u_js.append({'time': ts, 'value': round(float(r['BB_UP']), 2)})
        if pd.notna(r.get('BB_DN')): bb_d_js.append({'time': ts, 'value': round(float(r['BB_DN']), 2)})

    is_light = "Light" in theme_mode
    bg_hex = "#ffffff" if is_light else "#0e1117"
    txt_hex = "#111827" if is_light else "#d1d5db"
    grid_hex = "#f1f5f9" if is_light else "#1e293b"
    rsi_val = round(float(row_data.get('RSI14', 50.0)), 1)
    chart_dom_id = f"tv_lw_{key_idx}"

    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        body {{ margin: 0; padding: 0; background: {bg_hex}; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace; overflow: hidden; border: 1px solid #2b313f; border-radius: 6px; }}
        .hdr-bar {{
            background: #111622; color: #fff; padding: 4px 8px; display: flex; justify-content: space-between; align-items: center;
            border-bottom: 1px solid #2b313f; font-size: 11px; user-select: none;
        }}
        .ind-bar {{ display: flex; gap: 3px; flex-wrap: wrap; align-items: center; }}
        .ibtn {{
            padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: bold; cursor: pointer;
            background: #1f2937; color: #9ca3af; border: 1px solid #374151; transition: 0.12s;
        }}
        .ibtn.active-vwap {{ background: #2563eb; color: #fff; border-color: #2563eb; }}
        .ibtn.active-sr {{ background: #16a34a; color: #fff; border-color: #16a34a; }}
        .ibtn.active-piv {{ background: #d97706; color: #fff; border-color: #d97706; }}
        .ibtn.active-ema {{ background: #7c3aed; color: #fff; border-color: #7c3aed; }}
        .ibtn.active-kal {{ background: #0d9488; color: #fff; border-color: #0d9488; }}
        .ibtn.active-st {{ background: #15803d; color: #fff; border-color: #15803d; }}
        .ohlc-overlay {{
            position: absolute; top: 30px; left: 8px; z-index: 20; font-size: 11px;
            color: {txt_hex}; background: {'rgba(255,255,255,0.85)' if is_light else 'rgba(14,17,23,0.85)'};
            padding: 2px 6px; border-radius: 4px; pointer-events: none; font-family: monospace;
        }}
    </style>
    </head>
    <body>
        <div class="hdr-bar">
            <span style="color:#a855f7; font-weight:bold;">RSI(14): {rsi_val} &nbsp;|&nbsp; IST Timings</span>
            <div class="ind-bar">
                <span id="btn_ema" class="ibtn {'active-ema' if 'EMAs' in active_inds else ''}" onclick="toggleInd('ema')">EMAs</span>
                <span id="btn_sr" class="ibtn {'active-sr' if 'S&R' in active_inds else ''}" onclick="toggleInd('sr')">S&R</span>
                <span id="btn_piv" class="ibtn {'active-piv' if 'Pivots(R1,S1)' in active_inds else ''}" onclick="toggleInd('piv')">Pivots(R1,S1)</span>
                <span id="btn_vwap" class="ibtn {'active-vwap' if 'VWAP' in active_inds else ''}" onclick="toggleInd('vwap')">VWAP</span>
                <span id="btn_bb" class="ibtn {'active-vwap' if 'BB' in active_inds else ''}" onclick="toggleInd('bb')">BB</span>
                <span id="btn_kal" class="ibtn {'active-kal' if 'Kalman' in active_inds else ''}" onclick="toggleInd('kal')">Kalman</span>
                <span id="btn_st" class="ibtn {'active-st' if 'ST(7,3)' in active_inds else ''}" onclick="toggleInd('st')">ST(7,3)</span>
            </div>
        </div>
        <div id="ohlc_{chart_dom_id}" class="ohlc-overlay">Move cursor to inspect OHLCV</div>
        <div id="{chart_dom_id}" style="width: 100%; height: {chart_height - 28}px;"></div>

        <script>
        const cData = {json.dumps(candles_js)};
        const vData = {json.dumps(vol_js)};
        const vwapData = {json.dumps(vwap_js)};
        const ema10Data = {json.dumps(ema10_js)};
        const ema20Data = {json.dumps(ema20_js)};
        const kalData = {json.dumps(kal_js)};
        const stData = {json.dumps(st_js)};
        const bbUpData = {json.dumps(bb_u_js)};
        const bbDnData = {json.dumps(bb_d_js)};

        const container = document.getElementById('{chart_dom_id}');
        const ohlcBox = document.getElementById('ohlc_{chart_dom_id}');

        const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
        function fmtIST(ts) {{
            const d = new Date(ts * 1000);
            const dd = String(d.getUTCDate()).padStart(2, '0');
            const mm = months[d.getUTCMonth()];
            let hh = d.getUTCHours();
            const ampm = hh >= 12 ? 'PM' : 'AM';
            hh = hh % 12;
            if (hh === 0) hh = 12;
            const mn = String(d.getUTCMinutes()).padStart(2, '0');
            return `${{dd}} ${{mm}} ${{hh}}:${{mn}} ${{ampm}}`;
        }}

        const chart = LightweightCharts.createChart(container, {{
            layout: {{ background: {{ type: 'solid', color: '{bg_hex}' }}, textColor: '{txt_hex}', fontSize: 11 }},
            localization: {{ timeFormatter: fmtIST }},
            grid: {{ vertLines: {{ color: '{grid_hex}' }}, horzLines: {{ color: '{grid_hex}' }} }},
            crosshair: {{
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: {{ width: 1, color: '#6b7280', style: LightweightCharts.LineStyle.Dashed, labelBackgroundColor: '#111827' }},
                horzLine: {{ width: 1, color: '#6b7280', style: LightweightCharts.LineStyle.Dashed, labelBackgroundColor: '#111827' }}
            }},
            rightPriceScale: {{ borderColor: '#cbd5e1', scaleMargins: {{ top: 0.08, bottom: 0.22 }} }},
            timeScale: {{
                borderColor: '#cbd5e1', timeVisible: true, secondsVisible: false,
                rightOffset: 4, barSpacing: 7,
                tickMarkFormatter: (time) => {{
                    const d = new Date(time * 1000);
                    let hh = d.getUTCHours();
                    const ampm = hh >= 12 ? 'PM' : 'AM';
                    hh = hh % 12;
                    if (hh === 0) hh = 12;
                    const mn = String(d.getUTCMinutes()).padStart(2, '0');
                    return `${{hh}}:${{mn}} ${{ampm}}`;
                }}
            }}

        const candleSeries = chart.addCandlestickSeries({{
            upColor: '#15803d', downColor: '#b91c1c',
            borderUpColor: '#15803d', borderDownColor: '#b91c1c',
            wickUpColor: '#15803d', wickDownColor: '#b91c1c'
        }});
        candleSeries.setData(cData);

        const volSeries = chart.addHistogramSeries({{
            priceFormat: {{ type: 'volume' }},
            priceScaleId: '',
            scaleMargins: {{ top: 0.80, bottom: 0 }}
        }});
        volSeries.setData(vData);

        const vwapSeries = chart.addLineSeries({{ color: '#eab308', lineWidth: 2, title: 'VWAP', visible: {'true' if 'VWAP' in active_inds else 'false'} }});
        vwapSeries.setData(vwapData);

        const ema10Series = chart.addLineSeries({{ color: '#2563eb', lineWidth: 1, priceLineVisible: false, visible: {'true' if 'EMAs' in active_inds else 'false'} }});
        ema10Series.setData(ema10Data);
        const ema20Series = chart.addLineSeries({{ color: '#9333ea', lineWidth: 1, lineStyle: 2, priceLineVisible: false, visible: {'true' if 'EMAs' in active_inds else 'false'} }});
        ema20Series.setData(ema20Data);

        const kalSeries = chart.addLineSeries({{ color: '#0d9488', lineWidth: 2, priceLineVisible: false, visible: {'true' if 'Kalman' in active_inds else 'false'} }});
        kalSeries.setData(kalData);

        const stSeries = chart.addLineSeries({{ color: '#16a34a', lineWidth: 2, lineStyle: 1, priceLineVisible: false, visible: {'true' if 'ST(7,3)' in active_inds else 'false'} }});
        stSeries.setData(stData);

        const bbUpSeries = chart.addLineSeries({{ color: 'rgba(37,99,235,0.4)', lineWidth: 1, priceLineVisible: false, visible: {'true' if 'BB' in active_inds else 'false'} }});
        bbUpSeries.setData(bbUpData);
        const bbDnSeries = chart.addLineSeries({{ color: 'rgba(37,99,235,0.4)', lineWidth: 1, priceLineVisible: false, visible: {'true' if 'BB' in active_inds else 'false'} }});
        bbDnSeries.setData(bbDnData);

        let srLines = [];
        let pivLines = [];
        function drawSR(show) {{
            srLines.forEach(l => candleSeries.removePriceLine(l));
            srLines = [];
            if (show) {{
                srLines.push(candleSeries.createPriceLine({{ price: {sr_high}, color: '#16a34a', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'Res' }}));
                srLines.push(candleSeries.createPriceLine({{ price: {sr_low}, color: '#dc2626', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'Sup' }}));
            }}
        }}
        function drawPiv(show) {{
            pivLines.forEach(l => candleSeries.removePriceLine(l));
            pivLines = [];
            if (show) {{
                pivLines.push(candleSeries.createPriceLine({{ price: {piv}, color: '#d97706', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'P' }}));
                pivLines.push(candleSeries.createPriceLine({{ price: {r1}, color: '#16a34a', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'R1' }}));
                pivLines.push(candleSeries.createPriceLine({{ price: {s1}, color: '#dc2626', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'S1' }}));
            }}
        }}
        drawSR({'true' if 'S&R' in active_inds else 'false'});
        drawPiv({'true' if 'Pivots(R1,S1)' in active_inds else 'false'});

        const state = {{
            ema: {'true' if 'EMAs' in active_inds else 'false'},
            sr: {'true' if 'S&R' in active_inds else 'false'},
            piv: {'true' if 'Pivots(R1,S1)' in active_inds else 'false'},
            vwap: {'true' if 'VWAP' in active_inds else 'false'},
            bb: {'true' if 'BB' in active_inds else 'false'},
            kal: {'true' if 'Kalman' in active_inds else 'false'},
            st: {'true' if 'ST(7,3)' in active_inds else 'false'}
        }};

        window.toggleInd = function(k) {{
            state[k] = !state[k];
            if (k === 'vwap') {{ vwapSeries.applyOptions({{ visible: state.vwap }}); document.getElementById('btn_vwap').className = 'ibtn ' + (state.vwap ? 'active-vwap' : ''); }}
            if (k === 'ema') {{ ema10Series.applyOptions({{ visible: state.ema }}); ema20Series.applyOptions({{ visible: state.ema }}); document.getElementById('btn_ema').className = 'ibtn ' + (state.ema ? 'active-ema' : ''); }}
            if (k === 'kal') {{ kalSeries.applyOptions({{ visible: state.kal }}); document.getElementById('btn_kal').className = 'ibtn ' + (state.kal ? 'active-kal' : ''); }}
            if (k === 'st') {{ stSeries.applyOptions({{ visible: state.st }}); document.getElementById('btn_st').className = 'ibtn ' + (state.st ? 'active-st' : ''); }}
            if (k === 'bb') {{ bbUpSeries.applyOptions({{ visible: state.bb }}); bbDnSeries.applyOptions({{ visible: state.bb }}); document.getElementById('btn_bb').className = 'ibtn ' + (state.bb ? 'active-vwap' : ''); }}
            if (k === 'sr') {{ drawSR(state.sr); document.getElementById('btn_sr').className = 'ibtn ' + (state.sr ? 'active-sr' : ''); }}
            if (k === 'piv') {{ drawPiv(state.piv); document.getElementById('btn_piv').className = 'ibtn ' + (state.piv ? 'active-piv' : ''); }}
        }};

        const volLookup = Object.fromEntries(vData.map(x => [x.time, x.value]));
        function updateLegend(bar) {{
            if (!bar) return;
            const chg = (bar.close - bar.open).toFixed(2);
            const pct = ((bar.close - bar.open) / bar.open * 100).toFixed(2);
            const col = bar.close >= bar.open ? '#16a34a' : '#dc2626';
            const v = volLookup[bar.time] || 0;
            const vStr = v >= 1000000 ? (v/1000000).toFixed(2)+'M' : (v/1000).toFixed(1)+'K';
            const tStr = fmtIST(bar.time);
            ohlcBox.innerHTML = `🕒 <b>${{tStr}}</b> &nbsp; O<b>${{bar.open}}</b> H<b>${{bar.high}}</b> L<b>${{bar.low}}</b> C<b>${{bar.close}}</b> <span style="color:${{col}};font-weight:bold;">${{chg>=0?'+'+chg:chg}} (${{pct>=0?'+'+pct:pct}}%)</span> &nbsp;Vol <b>${{vStr}}</b>`;
        }}
        if (cData.length > 0) updateLegend(cData[cData.length - 1]);
        chart.subscribeCrosshairMove(param => {{
            if (param && param.time) {{
                const d = param.seriesData.get(candleSeries);
                if (d) updateLegend(d);
            }} else if (cData.length > 0) {{
                updateLegend(cData[cData.length - 1]);
            }}
        }});

        new ResizeObserver(entries => {{
            if (entries.length === 0) return;
            const {{ width, height }} = entries[0].contentRect;
            chart.applyOptions({{ width, height }});
        }}).observe(container);
        </script>
    </body>
    </html>
    """
    components.html(html_code, height=chart_height)


# =========================================================
# --- 8. FAST CACHED ENGINE & LIVE UI RENDERING ---
# =========================================================
@st.cache_data(ttl=25, show_spinner=False)
def fetch_fast_live_quotes(tkrs_tuple, market_open):
    try:
        if market_open:
            _core_set = set(list(INDICES_MAP.keys()) + list(SECTOR_INDICES_MAP.keys()) + list(COMMODITY_MAP.keys()) + [f"{s}.NS" for s in (set(NIFTY_50 + FNO_STOCKS) - _SKIP_BAD_SYMS)])
            target_list = [t for t in tkrs_tuple if t in _core_set]
        else:
            target_list = list(INDICES_MAP.keys()) + list(COMMODITY_MAP.keys())
        q_data = yf.download(target_list, period="2d", interval="1d", progress=False, group_by='ticker', threads=10, timeout=5)
        if q_data.empty:
            return {}
        if isinstance(q_data.columns, pd.MultiIndex) and ('Close' in q_data.columns.levels[0] or 'Open' in q_data.columns.levels[0]):
            q_data = q_data.swaplevel(axis=1)
        out = {}
        syms = q_data.columns.levels[0] if isinstance(q_data.columns, pd.MultiIndex) else []
        for s in syms:
            sdf = q_data[s].dropna(subset=['Close'])
            if not sdf.empty:
                ltp = float(sdf['Close'].iloc[-1])
                op = float(sdf['Open'].iloc[-1])
                hi = float(sdf['High'].iloc[-1])
                lo = float(sdf['Low'].iloc[-1])
                pc = float(sdf['Close'].iloc[-2]) if len(sdf) >= 2 else op
                out[s] = (ltp, op, hi, lo, pc)
        return out
    except Exception:
        return {}


@st.cache_data(ttl=30, show_spinner=False)
def _fast_5m_and_sniper_cache(tickers_tuple):
    five_min_data = fetch_cached_5m_data(list(tickers_tuple))
    processed_charts = {}
    nifty_intra_html = ""
    fetched_5m = five_min_data.columns.levels[0] if isinstance(five_min_data.columns, pd.MultiIndex) else five_min_data.columns

    if "^NSEI" in fetched_5m:
        try:
            n_raw = five_min_data["^NSEI"] if isinstance(five_min_data.columns, pd.MultiIndex) else five_min_data
            n_day = _fix_ist_df(process_5m_data(n_raw))
            if not n_day.empty and len(n_day) >= 2:
                n_day_ret = (float(n_day['Close'].iloc[-1]) / float(n_day['Open'].iloc[0]) - 1.0) * 100.0
                lb_idx = max(0, len(n_day) - 7)
                n_30m_ret = (float(n_day['Close'].iloc[-1]) / float(n_day['Close'].iloc[lb_idx]) - 1.0) * 100.0
                n_bias = "🟢 Bullish" if n_day_ret > 0.10 else ("🔴 Bearish" if n_day_ret < -0.10 else "⚪ Sideways")
                nifty_intra_html = (
                    f"<span style='color:#ffd700; font-weight:bold; font-size:13px; background:#21262d; "
                    f"border:1px solid #30363d; padding:2px 9px; border-radius:4px;'>"
                    f"Nifty Intraday: {n_day_ret:+.2f}% &nbsp;|&nbsp; Last 30m: {n_30m_ret:+.2f}% ({n_bias})</span>"
                )
        except Exception:
            pass

    for sym in tickers_tuple:
        try:
            df_raw = five_min_data[sym] if isinstance(five_min_data.columns, pd.MultiIndex) else five_min_data
            processed_charts[sym] = _fix_ist_df(process_5m_data(df_raw))
        except Exception:
            processed_charts[sym] = pd.DataFrame()

    sniper_res, _ = adaptive_live_engine(five_min_data, list(tickers_tuple), top_n=12, min_edge=60)
    return processed_charts, nifty_intra_html, sniper_res


_effective_refresh = 30

@st.fragment(run_every=f"{_effective_refresh}s")
def render_live_ui():
    # 80% LEFT & 20% RIGHT COLUMNS AT VERY TOP (Market Closed inside 80%, AI Predictions at very top of 20%!)
    col_main_80, col_side_20 = st.columns([4.02, 1.22], gap="small")

    # ---------------------------------------------------------
    # 👉 RIGHT 20% PANEL: MOVED ALL THE WAY TO THE TOP
    # ---------------------------------------------------------
    with col_side_20:
        right_panel_box = st.container(height=720, border=True)
        with right_panel_box:
            watchlist_mode = st.selectbox("Watchlist / Strategy", [
                "🤖 AI Predictions (F&O)",
                "🤖 AI Predictions (Mid Cap)",
                "🤖 AI Predictions (Small Cap)",
                "High Score Stocks 🔥",
                "Day Trading Stocks 🚀",
                "Swing Trading 📈",
                "Legendary Strategy 🏆",
                "F&O + Top 200 Heatmap 🗺️",
                "Terminal Tables 🗃️",
                "My Portfolio 💼",
                "Commodity 🛢️",
                "Fundamentals 🏢",
                "Mutual Funds 📈",
                "Month Effect Advantage 📅"
            ], index=0, label_visibility="collapsed")

            move_type_filter = ["All Day Trading Moves 🚀"]
            fund_filter = "Top Ranked Stocks ⭐"

            # MULTI-STRATEGY TICK SELECTION POPOVER (Checkboxes for multiple strategies!)
            if "AI Predictions" in watchlist_mode:
                ai_strat_options = [
                    ADAPTIVE_STRAT,
                    "All Day Trading Moves 🚀",
                    NEWS_STRAT,
                    "🔥 First Hour Vol Breakout (ORB+VWAP)",
                    "💥 Inside Bar Vol Breakout (NR7)",
                    "🧲 Intraday Dip & Support Bounce",
                    "⚡ Sudden VWAP Cross (Any Time)",
                    "🚀 Gap & Go (Open = Low)",
                    "💥 PDH / PDL Breakout",
                    "All Moves"
                ]
                with st.popover(f"🎯 Select Strategies ({len(st.session_state.selected_ai_strats)} Ticked)", use_container_width=True):
                    st.caption("Tick multiple strategies below:")
                    new_sel_ai = []
                    for s_opt in ai_strat_options:
                        chk = st.checkbox(s_opt, value=(s_opt in st.session_state.selected_ai_strats), key=f"chk_ai_{s_opt}")
                        if chk:
                            new_sel_ai.append(s_opt)
                    if new_sel_ai != st.session_state.selected_ai_strats:
                        st.session_state.selected_ai_strats = new_sel_ai if new_sel_ai else ["All Moves"]
                        st.rerun(scope="fragment")
                move_type_filter = st.session_state.selected_ai_strats

            elif watchlist_mode == "Swing Trading 📈":
                sw_strat_options = [
                    "📈 Minervini Trend Template (VCP)",
                    "📉 Strict VCP (Price & Vol Contraction)",
                    "🔥 Minervini MidCap 150",
                    "🚀 Minervini SmallCap 250",
                    "All Swing Stocks"
                ]
                with st.popover(f"📈 Swing Strategies ({len(st.session_state.selected_sw_strats)} Ticked)", use_container_width=True):
                    new_sel_sw = []
                    for s_opt in sw_strat_options:
                        chk = st.checkbox(s_opt, value=(s_opt in st.session_state.selected_sw_strats), key=f"chk_sw_{s_opt}")
                        if chk:
                            new_sel_sw.append(s_opt)
                    if new_sel_sw != st.session_state.selected_sw_strats:
                        st.session_state.selected_sw_strats = new_sel_sw if new_sel_sw else ["All Swing Stocks"]
                        st.rerun(scope="fragment")
                move_type_filter = st.session_state.selected_sw_strats

            elif watchlist_mode == "Legendary Strategy 🏆":
                strat_opts = [
                    "All Swing Trading Moves 📈",
                    "🎯 52WH Pullback & 52WL Breakdown (Top 32)",
                    "🧲 The 20-EMA Holy Grail Pullback",
                    "📉 RSI(2) Mean Reversion (Larry Connors)",
                    "📈 Minervini Trend Template (VCP)",
                    "📉 Strict VCP (Price & Vol Contraction)",
                    "📦 Nicolas Darvas (Box Breakout)",
                    "📦 Nicolas Darvas Modified",
                    "📈 Stan Weinstein (Stage 2 Uptrend)",
                    "💥 Dan Zanger (Volume Explosion)",
                    "👑 King Strategy (SMA Bounce)",
                    "⏳ Anticipation SMA Base (20/50/150/200)"
                ]
                move_type_filter = [st.selectbox("Select Strategy", strat_opts, label_visibility="collapsed", key="legendary_filter_key")]

            elif watchlist_mode == "Fundamentals 🏢":
                fund_filter = st.selectbox("Fundamentals Filter", ["Top Ranked Stocks ⭐", "🦅 Warren Buffett Value Stocks", "Swing Trading Candidates 📈", "Nifty 50 Stocks", "My Portfolio 💼"], index=0, label_visibility="collapsed")

            default_view_idx = 0 if watchlist_mode in ["My Portfolio 💼", "F&O + Top 200 Heatmap 🗺️"] else 1
            view_mode = st.radio("Display", ["Heat Map", "Chart 📈"], index=default_view_idx, horizontal=True, label_visibility="collapsed")

            g_lbl_col, g_rad_col = st.columns([1.05, 2.95], gap="small")
            with g_lbl_col:
                st.markdown("<div style='font-size:12px; font-weight:bold; color:#58a6ff; padding-top:5px;'>📐 Grid:</div>", unsafe_allow_html=True)
            with g_rad_col:
                grid_opts = ["Off", "1", "2", "4", "6"]
                curr_g_idx = grid_opts.index(st.session_state.grid_layout_mode) if st.session_state.grid_layout_mode in grid_opts else 0
                sel_grid = st.radio("Pro Grid", grid_opts, index=curr_g_idx, horizontal=True, label_visibility="collapsed")
                st.session_state.grid_layout_mode = sel_grid

            with st.expander("⚙️ Filters, Sort & Search", expanded=False):
                st.session_state.pause_refresh = st.toggle("⏸️ Pause Refresh", value=st.session_state.pause_refresh)
                sort_mode = st.selectbox(
                    "Sort By",
                    [
                        "Score Wise Up ⭐",
                        "Intraday Pullback Max 📉 (DH / DL)",
                        "52W Pullback Max 📉 (Deep Discount)",
                        "% Change Up 🟢",
                        "% Change Down 🔴",
                        "Score Wise Down ⬇️"
                    ],
                    index=0
                )
                search_stock = st.selectbox("Search Stock", ["-- None --"] + all_names)
                chart_timeframe = st.radio("Timeframe", ["Intraday (5m)", "Daily Chart", "Weekly Chart"], index=1 if watchlist_mode in ["Swing Trading 📈", "Legendary Strategy 🏆"] else 0)
                show_crosshair = st.toggle("⌖ Mini-Chart Crosshair (Price/Time)", value=True)
                show_vol = st.toggle("📊 Mini-Chart Vol Bars", value=False)

            side_watchlist_slot = st.container()

    # ---------------------------------------------------------
    # 👉 FAST DATA ENGINE
    # ---------------------------------------------------------
    if st.session_state.pause_refresh:
        with col_main_80:
            st.info("⏸️ Data refresh is paused.")
        return

    df_live = fetch_all_data().copy()
    _m_open_top = is_market_open()

    if not df_live.empty:
        _fast_quotes = fetch_fast_live_quotes(tuple(df_live['Fetch_T'].tolist()), _m_open_top)
        with LIVE_PRICES_LOCK:
            _live_snap = dict(LIVE_PRICES_GLOBAL)
        for _i, _r in df_live.iterrows():
            _ft = str(_r['Fetch_T'])
            _csym = _ft.replace(".NS", "")
            if _csym in _live_snap:
                _nltp = _live_snap[_csym]
                df_live.at[_i, 'P'] = _nltp
                if df_live.at[_i, 'O'] > 0: df_live.at[_i, 'Day_C'] = ((_nltp - df_live.at[_i, 'O']) / df_live.at[_i, 'O']) * 100.0
                if df_live.at[_i, 'Prev_C'] > 0: df_live.at[_i, 'C'] = ((_nltp - df_live.at[_i, 'Prev_C']) / df_live.at[_i, 'Prev_C']) * 100.0
            elif _ft in _fast_quotes:
                _ltp, _op, _hi, _lo, _pc = _fast_quotes[_ft]
                df_live.at[_i, 'P'], df_live.at[_i, 'O'], df_live.at[_i, 'H'], df_live.at[_i, 'L'] = _ltp, _op, _hi, _lo
                df_live.at[_i, 'Prev_C'] = _pc
                df_live.at[_i, 'VWAP'] = (_hi + _lo + _ltp) / 3.0
                if _op > 0: df_live.at[_i, 'Day_C'] = ((_ltp - _op) / _op) * 100.0
                if _pc > 0: df_live.at[_i, 'C'] = ((_ltp - _pc) / _pc) * 100.0

    if df_live.empty:
        return

    df_indices = df_live[df_live['Is_Index']].copy()
    df_indices['Order'] = df_indices['T'].map({"NIFTY": 1, "BANKNIFTY": 2, "INDIA VIX": 3, "SPX": 4, "DAX": 5, "USD/INR": 6}).fillna(99)
    df_indices = df_indices.sort_values('Order')

    df_sectors = df_live[df_live['Is_Sector']].copy()
    sec_sort_key = "W_C" if chart_timeframe == "Weekly Chart" else "Day_C"
    df_sectors = df_sectors.sort_values(by=sec_sort_key, ascending=False)

    df_all_stocks = df_live[(~df_live['Is_Index']) & (~df_live['Is_Sector']) & (~df_live['Is_Commodity'])].copy()
    df_commodities = df_live[df_live['Is_Commodity']].copy()
    df_port_saved = load_portfolio().copy()

    if watchlist_mode == "Swing Trading 📈": strict_allowed = set(NIFTY_50 + FNO_STOCKS + MIDCAP_150 + SMALLCAP_250)
    elif watchlist_mode == "🤖 AI Predictions (Mid Cap)": strict_allowed = set(MIDCAP_150)
    elif watchlist_mode == "🤖 AI Predictions (Small Cap)": strict_allowed = set(SMALLCAP_250)
    else: strict_allowed = set(NIFTY_50 + FNO_STOCKS)

    df_stocks = df_all_stocks[df_all_stocks['T'].isin(strict_allowed)].copy()
    df_filtered = df_stocks.copy()

    core_tkrs = tuple(sorted(list(set(df_indices['Fetch_T'].tolist() + df_sectors['Fetch_T'].tolist() + df_stocks['Fetch_T'].tolist() + st.session_state.pinned_stocks))))
    processed_charts, nifty_intra_html, sniper_cached_res = _fast_5m_and_sniper_cache(core_tkrs)

    df_lookup = df_live.drop_duplicates(subset=['Fetch_T'], keep='first').set_index('Fetch_T').to_dict('index')
    weekly_trends = {}
    for sym, sym_row in df_lookup.items():
        w_ema10, w_ema50, last_p = float(sym_row.get('W_EMA10', 0)), float(sym_row.get('W_EMA50', 0)), float(sym_row.get('P', 0))
        weekly_trends[sym] = 'Bullish' if (last_p > w_ema10 and w_ema10 >= w_ema50) else ('Bearish' if (last_p < w_ema10 and w_ema10 <= w_ema50) else 'Neutral')

    sort_key = "W_C" if chart_timeframe == "Weekly Chart" else "Day_C"

    if watchlist_mode == "My Portfolio 💼":
        port_tickers = [f"{str(sym).upper().strip()}.NS" for sym in df_port_saved['Symbol'].tolist() if str(sym).strip() != ""]
        df_filtered = df_all_stocks[df_all_stocks['Fetch_T'].isin(port_tickers)].copy()
    elif watchlist_mode == "Commodity 🛢️":
        df_filtered = df_commodities.copy()
    elif watchlist_mode == "F&O + Top 200 Heatmap 🗺️":
        df_filtered = df_all_stocks[df_all_stocks['T'].isin(set(NIFTY_50 + FNO_STOCKS))].copy()
    elif watchlist_mode == "Day Trading Stocks 🚀":
        df_filtered = df_stocks[df_stocks['C'].abs() >= 1.0].copy()
        df_filtered['Strategy_Icon'] = np.where(df_filtered['Day_C'] >= 0, "🚀 BUY", "🩸 SELL")
    elif watchlist_mode == "High Score Stocks 🔥":
        df_filtered = df_stocks[(df_stocks['S'] >= 11) & (df_stocks['VolX'] >= 1.5)].copy()
    elif "AI Predictions" in watchlist_mode:
        base_buy = (df_filtered['P'] > df_filtered['W_EMA10']) & (df_filtered['P'] > df_filtered['VWAP'])
        base_sell = (df_filtered['P'] < df_filtered['W_EMA10']) & (df_filtered['P'] < df_filtered['VWAP'])
        all_dfs = []
        for strat in move_type_filter:
            if strat == ADAPTIVE_STRAT:
                for _side, _label in (('buy', 'BUY'), ('sell', 'SELL')):
                    _rows = sniper_cached_res.get(_side, [])
                    if not _rows: continue
                    _m = {r['sym']: r for r in _rows}
                    _sub = df_filtered[df_filtered['Fetch_T'].isin(list(_m.keys()))].copy()
                    if _sub.empty: continue
                    _sub['AI_Prob'] = _sub['Fetch_T'].map(lambda s: _m[s]['score'])
                    _sub = _sub.sort_values('AI_Prob', ascending=False)
                    _sub['Strategy_Icon'] = f"🎯 Sniper {_label}"
                    _sub['S'] = [35 - 2 * _k for _k in range(len(_sub))]
                    all_dfs.append(_sub)
            elif strat == NEWS_STRAT:
                _df_news, _ = run_news_vol_price_strategy(df_filtered, processed_charts, min_volx=1.2, min_move_pct=0.75)
                if not _df_news.empty: all_dfs.append(_df_news)
            else:
                c_buy = base_buy & (df_filtered['Day_C'] > 0.6) & (df_filtered['VolX'] >= 1.1)
                c_sell = base_sell & (df_filtered['Day_C'] < -0.6) & (df_filtered['VolX'] >= 1.1)
                tb = df_filtered[c_buy].sort_values(by=['VolX', 'Day_C'], ascending=[False, False]).head(12).copy()
                if not tb.empty: tb['Strategy_Icon'] = "🚀 BUY"; all_dfs.append(tb)
                ts = df_filtered[c_sell].sort_values(by=['VolX', 'Day_C'], ascending=[False, True]).head(12).copy()
                if not ts.empty: ts['Strategy_Icon'] = "🩸 SELL"; all_dfs.append(ts)
        if all_dfs:
            df_filtered = pd.concat(all_dfs).drop_duplicates(subset=['Fetch_T'])
        else:
            df_filtered['Strategy_Icon'] = np.where(df_filtered['Day_C'] >= 0, "🚀 BUY", "🩸 SELL")
            df_filtered = df_filtered.sort_values(by='S', ascending=False).head(24)

    elif watchlist_mode in ["Swing Trading 📈", "Legendary Strategy 🏆"]:
        has_history = (df_filtered['SMA200'] > 0) & (df_filtered['SMA150'] > 0)
        vcp_c = has_history & (df_filtered['P'] > df_filtered['SMA150']) & (df_filtered['P'] > df_filtered['SMA50']) & (df_filtered['SMA50'] > df_filtered['SMA150'])
        df_filtered = df_filtered[vcp_c].copy()
        df_filtered['Strategy_Icon'] = "🟢 M-VCP"

    if not df_filtered.empty:
        df_filtered = df_filtered.copy()
        df_filtered['Chg_Pts'] = np.where(
            (df_filtered['Prev_C'] > 0) & ((df_filtered['P'] - df_filtered['Prev_C']).abs() > 0.01),
            df_filtered['P'] - df_filtered['Prev_C'],
            df_filtered['P'] * df_filtered['Day_C'] / 100.0
        )
        scol = st.session_state.wl_sort_col
        sasc = st.session_state.wl_sort_asc
        if scol == "Symbol":
            df_stocks_display = df_filtered.sort_values(by='T', ascending=sasc)
        elif scol == "Last":
            df_stocks_display = df_filtered.sort_values(by='P', ascending=sasc)
        elif scol == "Chg":
            df_stocks_display = df_filtered.sort_values(by='Chg_Pts', ascending=sasc)
        elif scol == "Chg%":
            df_stocks_display = df_filtered.sort_values(by=sort_key, ascending=sasc)
        else:
            df_stocks_display = df_filtered.sort_values(by=['S', 'VolX', sort_key], ascending=[False, False, False])
    else:
        df_stocks_display = df_filtered.copy()

    # ---------------------------------------------------------
    # 👉 POPULATE RIGHT 20% WATCHLIST (EXACT COLUMN ALIGNMENT + NO GAP)
    # ---------------------------------------------------------
    with side_watchlist_slot:
        st.markdown("<div class='tv-sort-hdr-marker'></div>", unsafe_allow_html=True)
        sh1, sh2, sh3, sh4 = st.columns([1.35, 0.95, 0.85, 0.95], gap="small")
        arr = "▲" if st.session_state.wl_sort_asc else "▼"
        with sh1:
            st.button(f"Symbol{arr if st.session_state.wl_sort_col=='Symbol' else ''}", key="s_sym", width="stretch", on_click=_set_wl_sort, args=("Symbol",))
        with sh2:
            st.button(f"Last{arr if st.session_state.wl_sort_col=='Last' else ''}", key="s_lst", width="stretch", on_click=_set_wl_sort, args=("Last",))
        with sh3:
            st.button(f"Chg{arr if st.session_state.wl_sort_col=='Chg' else ''}", key="s_chg", width="stretch", on_click=_set_wl_sort, args=("Chg",))
        with sh4:
            st.button(f"Chg%{arr if st.session_state.wl_sort_col=='Chg%' else ''}", key="s_pct", width="stretch", on_click=_set_wl_sort, args=("Chg%",))

        # Height 240px so Bottom NIFTY/Stock Inspector Table is 100% visible without getting cut!
        with st.container(height=240, border=False):
            st.markdown("<div class='tv-wl-marker'></div>", unsafe_allow_html=True)
            wl_rows = []
            for idx_sym in ["NIFTY", "BANKNIFTY"]:
                ir = df_indices[df_indices['T'] == idx_sym]
                if not ir.empty: wl_rows.append(ir.iloc[0])
            for _, sr in df_stocks_display.head(45).iterrows():
                wl_rows.append(sr)

            for r_item in wl_rows:
                s_ft = r_item['Fetch_T']
                s_name = str(r_item['T'])[:8]
                s_ltp = float(r_item['P'])
                s_chg_pct = float(r_item['Day_C'])
                s_prev = float(r_item.get('Prev_C', 0))
                s_chg_pts = (s_ltp - s_prev) if (s_prev > 0 and abs(s_ltp - s_prev) > 0.01) else (s_ltp * s_chg_pct / 100.0)
                is_sel = s_ft in st.session_state.pinned_stocks
                ico = "☑" if is_sel else ("🟢" if s_chg_pct >= 0 else "🔴")
                col_tag = "green" if s_chg_pct >= 0 else "red"

                # Exact column spacing matching Symbol | Last | Chg | Chg%
                row_label = f"{ico}{s_name:<8} {s_ltp:>7.1f} :{col_tag}[{s_chg_pts:>+6.1f}] :{col_tag}[{s_chg_pct:>+5.1f}%]"
                st.button(
                    row_label, key=f"tv_wl_{s_ft}", width="stretch",
                    on_click=_toggle_wl_stock, args=(s_ft, r_item['T'])
                )

        # Bottom Stock Inspector Card (Compact so it is 100% visible)
        insp_sym = st.session_state.inspected_stock
        insp_df = df_live[df_live['T'] == insp_sym]
        insp_row = insp_df.iloc[0] if not insp_df.empty else (df_stocks_display.iloc[0] if not df_stocks_display.empty else None)

        if insp_row is not None:
            i_p = float(insp_row['P'])
            i_pct = float(insp_row['Day_C'])
            i_pc = float(insp_row.get('Prev_C', 0))
            i_pts = (i_p - i_pc) if (i_pc > 0 and abs(i_p - i_pc) > 0.01) else (i_p * i_pct / 100.0)
            i_h, i_l = float(insp_row.get('H', i_p)), float(insp_row.get('L', i_p))
            i_vx = float(insp_row.get('VolX', 1.0))
            i_sec = str(insp_row.get('Sector', 'INDEX'))
            i_strat = str(insp_row.get('Strategy_Icon', 'Active'))
            pos_pct = min(100, max(5, int(((i_p - i_l) / (i_h - i_l + 0.001)) * 100)))
            c_hex = "#3fb950" if i_pct >= 0 else "#f85149"

            st.markdown(
                f"<div style='background:#111622; border:1px solid #30363d; padding:6px 8px; margin-top:2px; border-radius:6px;'>"
                f"<div style='display:flex; justify-content:space-between; align-items:center;'>"
                f"<span style='font-weight:bold; font-size:13px; color:#fff;'>🔍 {insp_row['T']}</span>"
                f"<span style='font-size:10px; background:#1e293b; color:#38bdf8; padding:1px 5px; border-radius:4px;'>{i_strat}</span></div>"
                f"<div style='font-size:16.5px; font-weight:bold; color:#fff; font-family:monospace; margin-top:1px;'>₹{i_p:,.2f} "
                f"<span style='font-size:11.5px; color:{c_hex};'>{i_pts:+.2f} ({i_pct:+.2f}%)</span></div>"
                f"<div style='display:flex; justify-content:space-between; font-size:9.5px; color:#8b949e; margin-top:3px;'>"
                f"<span>L: ₹{i_l:.1f}</span><span>Range ({i_sec})</span><span>H: ₹{i_h:.1f}</span></div>"
                f"<div style='width:100%; background:#21262d; height:4px; border-radius:3px; margin-top:2px;'>"
                f"<div style='width:{pos_pct}%; background:{c_hex}; height:4px; border-radius:3px;'></div></div>"
                f"<div style='display:flex; justify-content:space-between; font-size:10.5px; color:#c9d1d9; margin-top:4px;'>"
                f"<span>RVOL: <b style='color:#00BFFF;'>{i_vx:.1f}x</b></span>"
                f"<span>VWAP: <b style='color:#ffd700;'>₹{float(insp_row.get('VWAP', i_p)):.1f}</b></span></div>"
                f"</div>",
                unsafe_allow_html=True
            )

    # ---------------------------------------------------------
    # 👉 LEFT 80% COLUMN: MARKET STATUS BAR + SCROLLABLE CHARTS
    # ---------------------------------------------------------
    with col_main_80:
        _now_str_top = now_ist().strftime('%d-%b %I:%M:%S %p')
        _run_ts = int(time.time() * 1000)
        _mkt_dir_text, _mkt_dir_bg, _mkt_dir_border = "NEUTRAL ⚖️", "#30363d", "#8b949e"

        _unique_universe = set(NIFTY_50).union(set(FNO_STOCKS))
        _df_mkt = df_live[(~df_live['Is_Index']) & (~df_live['Is_Sector']) & (~df_live['Is_Commodity']) & (df_live['T'].isin(_unique_universe))].drop_duplicates(subset=['T'], keep='first')
        _tot_stocks = len(_df_mkt)
        if _tot_stocks > 0:
            _above_vwap = int((_df_mkt['P'] > _df_mkt['VWAP']).sum())
            _below_vwap = int((_df_mkt['P'] < _df_mkt['VWAP']).sum())
            _buy_pct = (_above_vwap / _tot_stocks) * 100.0
            _sell_pct = (_below_vwap / _tot_stocks) * 100.0
            if 49.0 <= _buy_pct <= 51.0 or _above_vwap == _below_vwap:
                _mkt_dir_text, _mkt_dir_bg, _mkt_dir_border = f"NEUTRAL ⚖️ {_above_vwap}/{_tot_stocks} ({_buy_pct:.0f}%)", "#484f58", "#8b949e"
            elif _above_vwap > _below_vwap:
                _mkt_dir_text, _mkt_dir_bg, _mkt_dir_border = f"BUY 📈 {_above_vwap}/{_tot_stocks} ({_buy_pct:.0f}%)", "#1e5f29", "#2ea043"
            else:
                _mkt_dir_text, _mkt_dir_bg, _mkt_dir_border = f"SELL 📉 {_below_vwap}/{_tot_stocks} ({_sell_pct:.0f}%)", "#b52524", "#f85149"

        _dir_box_html = f"<span style='background:{_mkt_dir_bg};border:1px solid {_mkt_dir_border};color:#ffffff;padding:2px 10px;border-radius:4px;font-weight:bold;font-size:13px;'>MARKET: {_mkt_dir_text}</span>"
        _status_border = "#238636" if _m_open_top else "#f85149"
        _status_title = "🟢 <b>MARKET LIVE</b> (NSE)" if _m_open_top else "🔴 <b>MARKET CLOSED</b> (Showing Last Data)"

        st.markdown(
            f"<div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;"
            f"background:#161b22;border:1px solid {_status_border};border-radius:6px;padding:5px 12px;"
            f"margin-bottom:6px;font-size:13.5px;'>"
            f"<span>{_status_title}</span>"
            f"<div style='display:flex;align-items:center;gap:8px;flex-wrap:wrap;'>{_dir_box_html}{nifty_intra_html}</div>"
            f"<span style='color:#c9d1d9;font-size:12.5px;'>🕒 {_now_str_top} IST &nbsp;|&nbsp; "
            f"<span id='live-cd-badge' data-ts='{_run_ts}' style='background:#21262d;border:1px solid #30363d;color:#00BFFF;"
            f"padding:2px 7px;border-radius:4px;font-weight:bold;font-family:monospace;'>⏳ {_effective_refresh}s</span></span></div>",
            unsafe_allow_html=True
        )

        components.html(
            f"""<!-- refresh_{_run_ts} -->
            <script>
            (function() {{
                const parentDoc = window.parent.document;
                if (window.parent._stCdInterval) clearInterval(window.parent._stCdInterval);
                let secLeft = {_effective_refresh};
                const updateBadge = () => {{
                    const el = parentDoc.getElementById('live-cd-badge');
                    if (!el) return;
                    if (secLeft > 0) {{
                        el.innerHTML = '⏳ ' + secLeft + 's';
                        el.style.color = secLeft <= 5 ? '#ffd700' : '#00BFFF';
                        secLeft -= 1;
                    }} else {{
                        el.innerHTML = '🔄 Updating...';
                        el.style.color = '#3fb950';
                    }}
                }};
                updateBadge();
                window.parent._stCdInterval = setInterval(updateBadge, 1000);
            }})();
            </script>""",
            height=0,
        )

        left_main_box = st.container(height=670, border=False)
        with left_main_box:
            weekly_charts, daily_charts = {}, {}
            if chart_timeframe in ["Weekly Chart", "Daily Chart"]:
                display_tkrs = list(set(df_indices['Fetch_T'].tolist() + st.session_state.pinned_stocks + df_stocks_display['Fetch_T'].head(40).tolist()))
                if display_tkrs:
                    hist_data = fetch_historical_charts_data(display_tkrs, chart_timeframe)
                    for sym in display_tkrs:
                        try:
                            df_h = hist_data[sym] if isinstance(hist_data.columns, pd.MultiIndex) else hist_data
                            df_h = df_h.dropna(subset=['Close']).copy()
                            if not df_h.empty:
                                if chart_timeframe == "Weekly Chart":
                                    df_h['SMA_10'] = df_h['Close'].rolling(10).mean()
                                    df_h['SMA_40'] = df_h['Close'].rolling(40).mean()
                                    weekly_charts[sym] = df_h
                                else:
                                    df_h['SMA_50'] = df_h['Close'].rolling(50).mean()
                                    df_h['SMA_150'] = df_h['Close'].rolling(150).mean()
                                    df_h['SMA_200'] = df_h['Close'].rolling(200).mean()
                                    daily_charts[sym] = df_h
                        except Exception:
                            pass

            chart_dict_to_use = weekly_charts if chart_timeframe == "Weekly Chart" else (daily_charts if chart_timeframe == "Daily Chart" else processed_charts)

            # =========================================================
            # 🔥 MODE A: PRO MULTI-CHART GRID (1, 2, 4, 6 STOCKS)
            # =========================================================
            if st.session_state.grid_layout_mode != "Off":
                gbar1, gbar2, gbar3 = st.columns([1.2, 1.4, 1.0], gap="small")
                with gbar1:
                    if st.button("🔙 Back to Mini-Charts", width="stretch"):
                        st.session_state.grid_layout_mode = "Off"
                        st.rerun(scope="fragment")
                with gbar2:
                    st.session_state.pro_grid_theme = st.selectbox(
                        "Theme", ["Light (White)", "Dark (Terminal)"],
                        index=0 if "Light" in st.session_state.pro_grid_theme else 1,
                        label_visibility="collapsed"
                    )
                with gbar3:
                    if st.button("🗑️ Clear All Charts", width="stretch"):
                        st.session_state.pinned_stocks = []
                        st.session_state.grid_layout_mode = "Off"
                        st.rerun(scope="fragment")

                max_charts = int(st.session_state.grid_layout_mode)
                fallback_candidates = ["^NSEBANK", "^NSEI"] + df_stocks_display['Fetch_T'].tolist()
                combined_syms = list(dict.fromkeys(st.session_state.pinned_stocks + fallback_candidates))
                grid_syms = combined_syms[:max_charts]

                n_cols = 1 if max_charts == 1 else (2 if max_charts <= 4 else 3)
                c_height = 510 if max_charts == 1 else (340 if max_charts <= 4 else 320)
                rows_chunks = [grid_syms[i:i + n_cols] for i in range(0, len(grid_syms), n_cols)]
                for r_idx, chunk_syms in enumerate(rows_chunks):
                    g_cols = st.columns(n_cols, gap="small")
                    for c_idx, g_sym in enumerate(chunk_syms):
                        with g_cols[c_idx]:
                            r_info = df_lookup.get(g_sym, {'T': g_sym.replace('.NS', ''), 'Fetch_T': g_sym})
                            df_c_sym = chart_dict_to_use.get(g_sym, pd.DataFrame())
                            render_pro_grid_chart(
                                g_sym, r_info, df_c_sym, chart_timeframe,
                                st.session_state.pro_grid_theme, st.session_state.pro_grid_inds,
                                chart_height=c_height, key_idx=(r_idx * 10 + c_idx),
                                current_grid_syms=grid_syms
                            )

            # =========================================================
            # 📊 MODE B: DEFAULT MINI-CHARTS / PORTFOLIO / HEATMAP
            # =========================================================
            else:
                if watchlist_mode == "Fundamentals 🏢":
                    st.markdown(f"<div style='font-size:16px; font-weight:bold; margin-bottom:8px; color:#d29922;'>🏢 Core Fundamentals ({fund_filter})</div>", unsafe_allow_html=True)
                    fund_tickers = df_stocks_display['Fetch_T'].tolist()[:50] if not df_stocks_display.empty else [f"{s}.NS" for s in NIFTY_50[:50]]
                    df_fund = fetch_fundamentals_data(fund_tickers)
                    if not df_fund.empty:
                        if fund_filter == "🦅 Warren Buffett Value Stocks":
                            df_fund = df_fund[(df_fund['ROE %'] > 15) & (df_fund['Debt/Equity'] < 0.5) & (df_fund['P/E Ratio'] > 0) & (df_fund['P/E Ratio'] < 25)]
                        st.dataframe(df_fund, use_container_width=True, hide_index=True)

                elif watchlist_mode == "Mutual Funds 📈":
                    st.markdown("<div style='font-size:16px; font-weight:bold; margin-bottom:8px; color:#00BFFF;'>📈 Mutual Funds Screener (Live Morningstar Data)</div>", unsafe_allow_html=True)
                    mc1, mc2 = st.columns(2)
                    with mc1:
                        selected_mf_cat = st.selectbox("Filter by Category", ["All Categories"] + list(MUTUAL_FUNDS.keys()))
                    with mc2:
                        sort_period = st.selectbox("Rank By Performance", ["1Y (%)", "3Y CAGR (%)", "5Y CAGR (%)"], index=2)
                    df_mf_raw = fetch_mf_performance()
                    if not df_mf_raw.empty:
                        df_mf_raw['Sort_Key'] = pd.to_numeric(df_mf_raw[sort_period].replace('N/A', -999))
                        df_mf_raw = df_mf_raw.sort_values(by='Sort_Key', ascending=False)
                        df_mf_data = df_mf_raw[df_mf_raw['Category'] == selected_mf_cat] if selected_mf_cat != "All Categories" else df_mf_raw
                        df_mf_data = df_mf_data.drop(columns=['Sort_Key'], errors='ignore')
                        st.markdown(render_mf_table(df_mf_data), unsafe_allow_html=True)

                elif watchlist_mode == "Month Effect Advantage 📅":
                    st.markdown("<div style='font-size:16px; font-weight:bold; margin-bottom:8px; color:#00BFFF;'>📅 Month Effect Advantage (First 10 Days vs Rest)</div>", unsafe_allow_html=True)
                    scan_list = st.radio("Select Universe to Scan:", ["Top 200 (Nifty + Midcap)", "NIFTY 50 Only", "Custom Stock"], horizontal=True)
                    tkr_list = [f"{s}.NS" for s in (NIFTY_50 if scan_list == "NIFTY 50 Only" else (NIFTY_50 + MIDCAP_150))]
                    if st.button("🚀 Run 5-Year Month Effect Analysis", width="stretch"):
                        end_dt = datetime.now()
                        start_dt = end_dt - pd.DateOffset(years=5)
                        m_data = yf.download(tkr_list, start=start_dt, end=end_dt, progress=False, group_by='ticker', threads=10)
                        me_res = []
                        for tkr in tkr_list:
                            try:
                                df_t = m_data[tkr].dropna(subset=['Close']).copy()
                                if df_t.empty: continue
                                df_t['Year'], df_t['Month'], df_t['Day'] = df_t.index.year, df_t.index.month, df_t.index.day
                                f10_rets, rest_rets, wins, tot_m = [], [], 0, 0
                                for _, grp in df_t.groupby(['Year', 'Month']):
                                    if len(grp) < 5: continue
                                    f10, rst = grp[grp['Day'] <= 10], grp[grp['Day'] > 10]
                                    if not f10.empty and not rst.empty:
                                        r1 = (f10['Close'].iloc[-1] - f10['Open'].iloc[0]) / f10['Open'].iloc[0] * 100
                                        r2 = (rst['Close'].iloc[-1] - rst['Open'].iloc[0]) / rst['Open'].iloc[0] * 100
                                        f10_rets.append(r1); rest_rets.append(r2)
                                        if r1 > 0: wins += 1
                                        tot_m += 1
                                if tot_m > 0:
                                    me_res.append({"Stock": tkr.replace(".NS", ""), "Win Rate (1st 10d) %": round(wins / tot_m * 100, 1), "Avg 1st-10th Return %": round(sum(f10_rets) / len(f10_rets), 2), "Avg Rest Return %": round(sum(rest_rets) / len(rest_rets), 2), "Months": tot_m})
                            except Exception:
                                pass
                        if me_res:
                            st.dataframe(pd.DataFrame(me_res).sort_values(by="Win Rate (1st 10d) %", ascending=False), use_container_width=True, hide_index=True)

                elif watchlist_mode == "Terminal Tables 🗃️":
                    st.markdown(render_highscore_terminal_table(df_stocks_display), unsafe_allow_html=True)
                    st.markdown(render_levels_table(df_stocks_display), unsafe_allow_html=True)

                elif watchlist_mode == "My Portfolio 💼" and view_mode == "Heat Map":
                    # ALWAYS SHOW PORTFOLIO KPI, TABLE, ADD, EDIT, SELL & TRADEBOOK (Both in Heat Map & Chart mode!)
                    try:
                        if not df_port_saved.empty:
                            _lu = df_all_stocks.drop_duplicates(subset=['T']).set_index('T')[['P', 'Prev_C']].to_dict('index')
                            _inv = _cur = _dpnl = 0.0
                            for _, _r in df_port_saved.iterrows():
                                _sym = str(_r['Symbol']).upper().strip()
                                try:
                                    _qty, _bp = float(_r['Quantity']), float(_r['Buy_Price'])
                                except Exception:
                                    continue
                                _ltp = float(_lu.get(_sym, {}).get('P', _bp) or _bp)
                                _pc = float(_lu.get(_sym, {}).get('Prev_C', _bp) or _bp)
                                _inv += _bp * _qty
                                _cur += _ltp * _qty
                                _dpnl += (_ltp - _pc) * _qty
                            _tpnl = _cur - _inv
                            _tpct = (_tpnl / _inv * 100) if _inv > 0 else 0
                            _df_cl = load_closed_trades()
                            _realized_pnl = float(pd.to_numeric(_df_cl['PnL_Rs'], errors='coerce').sum()) if not _df_cl.empty else 0.0
                            _actual_pnl = _tpnl + _realized_pnl
                            _k1, _k2, _k3, _k4, _k5 = st.columns(5)
                            _k1.metric("💰 Invested", f"₹{_inv:,.0f}")
                            _k2.metric("📈 Current Value", f"₹{_cur:,.0f}")
                            _k3.metric("📅 Day P&L", f"₹{_dpnl:,.0f}")
                            _k4.metric("🏆 Total P&L", f"₹{_tpnl:,.0f}", delta=f"{_tpct:+.2f}%")
                            _k5.metric("💎 Actual P&L", f"₹{_actual_pnl:,.0f}", delta=f"TradeBook: {_realized_pnl:+,.0f}")
                    except Exception:
                        pass

                    with st.expander("📊 Portfolio Allocation (Sector • Market-cap • Stock weights)", expanded=False):
                        render_portfolio_allocation(df_port_saved, df_all_stocks)

                    _avail_dates = ["All Dates"] + sorted(list(set(df_port_saved['Date'].dropna().astype(str).tolist()))) if not df_port_saved.empty and 'Date' in df_port_saved.columns else ["All Dates"]
                    sc1, sc2, sc3 = st.columns([0.4, 0.3, 0.3])
                    with sc2:
                        port_date_filter = st.selectbox("📅 Date Filter:", _avail_dates, label_visibility="collapsed")
                    with sc3:
                        port_sort = st.selectbox("↕️ Sort Portfolio:", ["Default", "Date (Newest) ⬇️", "Date (Oldest) ⬆️", "Days Held ⬆️", "Days Held ⬇️", "Day P&L ⬆️", "Day P&L ⬇️", "Total P&L ⬆️", "Total P&L ⬇️", "P&L % ⬆️", "P&L % ⬇️"], label_visibility="collapsed")

                    df_port_view = df_port_saved[df_port_saved['Date'].astype(str) == port_date_filter].copy() if (port_date_filter != "All Dates" and not df_port_saved.empty) else df_port_saved.copy()
                    st.markdown(render_portfolio_table(df_port_view, df_all_stocks, weekly_trends, port_sort), unsafe_allow_html=True)

                    with st.expander("🤖 View Portfolio Swing Advisor (Action & Levels)", expanded=False):
                        st.markdown(render_portfolio_swing_advice_table(df_port_saved, df_all_stocks, weekly_trends), unsafe_allow_html=True)

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
                                submit_btn = st.form_submit_button("➕ Verify & Add", width="stretch")

                        if submit_btn and new_sym:
                            chk_data = yf.download(f"{new_sym}.NS", period="1d", progress=False)
                            if chk_data.empty:
                                st.error(f"❌ '{new_sym}' not found in NSE!")
                            else:
                                new_date_str = new_date.strftime("%d-%b-%Y")
                                df_port_saved = df_port_saved.copy()
                                if new_sym in df_port_saved['Symbol'].values:
                                    old_row = df_port_saved[df_port_saved['Symbol'] == new_sym].iloc[0]
                                    old_qty, old_price = float(old_row['Quantity']), float(old_row['Buy_Price'])
                                    total_qty = old_qty + new_qty
                                    base_price = ((old_qty * old_price) + (new_qty * new_price)) / total_qty
                                else:
                                    total_qty, base_price = new_qty, new_price
                                calc_sl = new_sl if new_sl > 0 else round(base_price * 0.95, 2)
                                calc_t1 = new_t1 if new_t1 > 0 else round(base_price * 1.10, 2)
                                calc_t2 = new_t2 if new_t2 > 0 else round(base_price * 1.15, 2)
                                if new_sym in df_port_saved['Symbol'].values:
                                    df_port_saved.loc[df_port_saved['Symbol'] == new_sym, ['Buy_Price', 'Quantity', 'Date', 'SL', 'T1', 'T2']] = [round(base_price, 2), total_qty, new_date_str, calc_sl, calc_t1, calc_t2]
                                else:
                                    new_row = pd.DataFrame({"Symbol": [new_sym], "Buy_Price": [new_price], "Quantity": [new_qty], "Date": [new_date_str], "SL": [calc_sl], "T1": [calc_t1], "T2": [calc_t2]})
                                    df_port_saved = pd.concat([df_port_saved, new_row], ignore_index=True)
                                save_portfolio(df_port_saved)
                                fetch_all_data.clear()
                                load_portfolio.clear()
                                st.rerun()

                    if not df_port_saved.empty:
                        with st.expander("✏️ Edit Existing Holdings (Targets, Qty, Price)", expanded=False):
                            edited_df = st.data_editor(
                                df_port_saved, width="stretch", hide_index=True,
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
                            if st.button("💾 Save Edited Changes", width="stretch"):
                                save_portfolio(edited_df)
                                fetch_all_data.clear()
                                st.rerun()

                        with st.expander("💸 Sell Stock & Book Profit/Loss", expanded=False):
                            with st.form("portfolio_sell_form"):
                                rc1, rc2, rc3, rc4 = st.columns([2, 1, 2, 2])
                                with rc1: sell_sym = st.selectbox("Select Stock to Sell", ["-- Select --"] + df_port_saved['Symbol'].tolist())
                                with rc2: sell_qty = st.number_input("Qty to Sell", min_value=1, value=1)
                                with rc3: sell_price = st.number_input("Exit Price (₹)", min_value=0.0, value=0.0)
                                with rc4:
                                    st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
                                    sell_btn = st.form_submit_button("💸 Confirm Sell", width="stretch")
                                if sell_btn and sell_sym != "-- Select --" and sell_price > 0:
                                    port_row = df_port_saved[df_port_saved['Symbol'] == sell_sym].iloc[0]
                                    buy_price = float(port_row['Buy_Price'])
                                    current_qty = int(float(port_row.get('Quantity', 0)))
                                    sell_qty = min(sell_qty, current_qty)
                                    pnl_rs = (sell_price - buy_price) * sell_qty
                                    pnl_pct = ((sell_price - buy_price) / buy_price) * 100
                                    sell_date_str = datetime.now().strftime("%d-%b-%Y")
                                    df_closed = load_closed_trades()
                                    buy_date_str = str(port_row.get('Date', '-'))
                                    new_closed_row = pd.DataFrame({"Buy_Date": [buy_date_str], "Sell_Date": [sell_date_str], "Symbol": [sell_sym], "Quantity": [sell_qty], "Buy_Price": [buy_price], "Sell_Price": [sell_price], "PnL_Rs": [pnl_rs], "PnL_Pct": [pnl_pct]})
                                    df_closed = pd.concat([df_closed, new_closed_row], ignore_index=True)
                                    save_closed_trades(df_closed)
                                    df_port_saved = df_port_saved[df_port_saved['Symbol'] != sell_sym] if sell_qty == current_qty else df_port_saved.assign(Quantity=np.where(df_port_saved['Symbol'] == sell_sym, current_qty - sell_qty, df_port_saved['Quantity']))
                                    save_portfolio(df_port_saved)
                                    fetch_all_data.clear()
                                    st.rerun()

                        with st.expander("📜 View Trade Book (Closed P&L Ledger)", expanded=False):
                            df_closed_view = load_closed_trades()
                            st.markdown(render_closed_trades_table(df_closed_view), unsafe_allow_html=True)
                            if not df_closed_view.empty:
                                st.download_button("📥 Download Trade Book (CSV)", data=df_closed_view.to_csv(index=False).encode('utf-8'), file_name="trade_book.csv", mime="text/csv")
                                edited_closed_df = st.data_editor(df_closed_view, width="stretch", hide_index=True, num_rows="dynamic", key="tradebook_editor")
                                if st.button("💾 Save Trade Book Changes", width="stretch", key="save_tb"):
                                    save_closed_trades(edited_closed_df)
                                    st.rerun()

                    

                elif view_mode == "Heat Map":
                    if not df_indices.empty and watchlist_mode != "Commodity 🛢️":
                        html_idx = '<div class="heatmap-grid">'
                        for _, row in df_indices.iterrows():
                            pct_val = float(row.get('W_C', row['Day_C'])) if chart_timeframe == "Weekly Chart" else float(row['Day_C'])
                            bg = "bear-card" if (row['T'] == "INDIA VIX" and pct_val > 0) else ("bull-card" if pct_val > 0 else "neut-card")
                            if row['T'] != "INDIA VIX" and pct_val < 0: bg = "bear-card"
                            html_idx += f'<a href="https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(row["Fetch_T"])}" target="_blank" class="stock-card {bg}"><div class="t-score">IDX</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{pct_val:+.2f}%</div></a>'
                        st.markdown(html_idx + '</div><hr class="custom-hr">', unsafe_allow_html=True)

                    if not df_stocks_display.empty:
                        df_buy = df_stocks_display[df_stocks_display[sort_key] >= 0]
                        df_sell = df_stocks_display[df_stocks_display[sort_key] < 0]
                        for df_sec, title, col in [(df_buy, f"🟢 POSITIVE / BUY ({watchlist_mode})", "#3fb950"), (df_sell, f"🔴 NEGATIVE / SELL ({watchlist_mode})", "#f85149")]:
                            if not df_sec.empty:
                                st.markdown(f"<div style='font-size:15px; font-weight:bold; margin: 6px 0 4px 0; color:{col};'>{title}</div>", unsafe_allow_html=True)
                                html_stk = '<div class="heatmap-grid">'
                                for _, row in df_sec.iterrows():
                                    pct_val = float(row.get('W_C', row['Day_C'])) if chart_timeframe == "Weekly Chart" else float(row['Day_C'])
                                    bg = card_bg_class(pct_val)
                                    html_stk += f'<a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank" class="stock-card {bg}"><div class="t-score">⭐{int(row["S"])}</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{pct_val:+.2f}%</div></a>'
                                st.markdown(html_stk + '</div>', unsafe_allow_html=True)

                else:
                    if search_stock != "-- None --" and not df_live[df_live['T'] == search_stock].empty:
                        render_chart_grid(pd.DataFrame([df_live[df_live['T'] == search_stock].iloc[0]]), True, "search", chart_timeframe, chart_dict_to_use, show_crosshair, show_vol)
                        st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)

                    if watchlist_mode not in ["My Portfolio 💼", "Commodity 🛢️"]:
                        with st.expander("🌍 Global & Main Indices (Click to Expand / Minimize)", expanded=True):
                            render_chart_grid(df_indices, True, "idx", chart_timeframe, chart_dict_to_use, show_crosshair, show_vol)
                            show_sec_charts = st.toggle("📊 Show Sectoral Indices Charts", value=False)
                            if show_sec_charts and not df_sectors.empty:
                                render_chart_grid(df_sectors, True, "sec", chart_timeframe, chart_dict_to_use, show_crosshair, show_vol, is_sector=True)
                                if st.session_state.get('active_sec'):
                                    st.markdown(f"<div style='font-size:15px; font-weight:bold; margin:8px 0 4px 0; color:#ffd700;'>🌟 Top 6 Active Movers in {st.session_state.active_sec}</div>", unsafe_allow_html=True)
                                    sec_stock_names = TOP_SECTOR_STOCKS.get(st.session_state.active_sec, [])
                                    sec_df = df_stocks[df_stocks['T'].isin(sec_stock_names)].copy()
                                    if not sec_df.empty:
                                        render_chart_grid(sec_df.head(6), True, "sec_top6", chart_timeframe, chart_dict_to_use, show_crosshair, show_vol)

                    if not df_stocks_display.empty:
                        if "AI Predictions" in watchlist_mode or watchlist_mode in ["Swing Trading 📈", "Legendary Strategy 🏆", "Day Trading Stocks 🚀"]:
                            df_sell_chart = df_stocks_display[df_stocks_display['Strategy_Icon'].str.contains('🔴|SELL|DOWN|Stage 4|🩸|52WL', na=False)].head(24)
                            df_buy_chart = df_stocks_display[~df_stocks_display['Strategy_Icon'].str.contains('🔴|SELL|DOWN|Stage 4|🩸|52WL', na=False)].head(24)
                        else:
                            df_buy_chart = df_stocks_display[df_stocks_display[sort_key] >= 0].head(24)
                            df_sell_chart = df_stocks_display[df_stocks_display[sort_key] < 0].head(24)

                        if not df_buy_chart.empty:
                            st.markdown(f"<div style='font-size:15px; font-weight:bold; margin:6px 0 4px 0; color:#3fb950;'>🟢 POSITIVE / BUY ({watchlist_mode})</div>", unsafe_allow_html=True)
                            render_chart_grid(df_buy_chart, True, "main_buy", chart_timeframe, chart_dict_to_use, show_crosshair, show_vol)

                        if not df_sell_chart.empty:
                            st.markdown(f"<div style='font-size:15px; font-weight:bold; margin:14px 0 4px 0; color:#f85149;'>🔴 NEGATIVE / SELL ({watchlist_mode})</div>", unsafe_allow_html=True)
                            render_chart_grid(df_sell_chart, True, "main_sell", chart_timeframe, chart_dict_to_use, show_crosshair, show_vol)
                    else:
                        st.info("ℹ️ No stocks matched this strategy's strict criteria at the moment.")

render_live_ui()
