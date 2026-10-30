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
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:has(div[data-testid="stCheckbox"]),
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) > div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:has(div[data-testid="stCheckbox"]) { margin-bottom: -45px !important; position: relative !important; z-index: 50 !important; }
    div[data-testid="stPopoverBody"] div[data-testid="stElementContainer"]:has(div[data-testid="stCheckbox"]) { margin-bottom: 6px !important; position: static !important; }
    div[data-testid="stPopoverBody"] div[data-testid="stCheckbox"] label { padding: 4px 2px !important; min-height: 24px !important; }
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
    "HUDCO", "ICICIBANK", "ICICIGI", "ICICILIFE", "IDEA", "IDFCFIRSTB", "IEX", "IGL", "INDHOTEL", "INDIACEM",
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
    _ttl = 25 if _m_open else 64800
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
    _global_24h = {"^GSPC", "^GDAXI", "INR=X", "GC=F", "SI=F", "CL=F", "NG=F", "HG=F"}
    missing_tkrs = [
        t for t in clean_req
        if (t not in store) or store[t].empty or ((now_t - ts_map.get(t, 0)) > (25 if (t in _global_24h and now_ist().weekday() < 5) else _ttl))
    ]

    n_yf = 0
    if missing_tkrs:
        yf_data = yf.download(missing_tkrs, period="5d", interval="5m", progress=False, group_by='ticker', threads=10, timeout=10)
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
        if df_s.empty:
            return pd.DataFrame()
        df_s.index = pd.to_datetime(df_s.index)
        if df_s.index.tz is not None:
            df_s.index = df_s.index.tz_convert('Asia/Kolkata').tz_localize(None)
        df_s = df_s[~df_s.index.duplicated(keep='last')].sort_index()

        # Off-market dead flat candles remove cheyadam
        is_flat_dup = (df_s['High'] == df_s['Low']) & (df_s['Close'] == df_s['Close'].shift(1))
        if (~is_flat_dup).sum() >= 20:
            df_s = df_s[~is_flat_dup].copy()

        df_s['EMA_10'] = df_s['Close'].ewm(span=10, adjust=False).mean()
        df_s['EMA_20'] = df_s['Close'].ewm(span=20, adjust=False).mean()
        df_s['EMA_50'] = df_s['Close'].ewm(span=50, adjust=False).mean()
        df_s['EMA_100'] = df_s['Close'].ewm(span=100, adjust=False).mean()
        df_s['EMA_200'] = df_s['Close'].ewm(span=200, adjust=False).mean()

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

        # Keep full 5 Trading Days (~375 candles) & calculate VWAP per daily session
        df_5d = df_s.tail(375).copy()
        if not df_5d.empty:
            df_5d['Typical_Price'] = (df_5d['High'] + df_5d['Low'] + df_5d['Close']) / 3.0
            # Kotha trading session (2 hours = 120 mins kante ekkuva gap) vachinappudu matrame VWAP reset cheyi
            df_5d['_sess_date'] = (df_5d.index.to_series().diff() > pd.Timedelta(minutes=120)).cumsum()
            if 'Volume' in df_5d.columns and df_5d['Volume'].sum() > 0:
                df_5d['_tp_vol'] = df_5d['Typical_Price'] * df_5d['Volume']
                vol_cum = df_5d.groupby('_sess_date')['Volume'].cumsum().replace(0, np.nan)
                tpv_cum = df_5d.groupby('_sess_date')['_tp_vol'].cumsum()
                df_5d['VWAP'] = (tpv_cum / vol_cum).fillna(df_5d['Typical_Price'])
                df_5d.drop(columns=['_tp_vol', '_sess_date'], inplace=True, errors='ignore')
            else:
                df_5d['VWAP'] = df_5d.groupby('_sess_date')['Typical_Price'].transform(lambda x: x.expanding().mean())
                df_5d.drop(columns=['_sess_date'], inplace=True, errors='ignore')
            df_5d = df_5d.bfill().ffill()
            return df_5d
        return pd.DataFrame()
    except Exception:
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
# 📰 NEWS + VOLUME + PRICE CATALYST ENGINE (MULTI-PURPOSE v7)
# ---------------------------------------------------------
#  • Default '🎯 Strategy' Mode: Shows currently selected strategy stocks with Left 30% Mini-Chart + Right 70% News, Q-Results & SL/Targets
#  • 5 Global 24h Filters: All High-Impact, Most Important, Q-Results, Latest Time-Wise, Order Wins
#  • Priority Sorting: Most Important News at Top & Scrolling Ticker -> Remaining in Strict Time-Wise Order
# =========================================================
from email.utils import parsedate_to_datetime
import inspect as _inspect
import re as _re
import textwrap as _textwrap
import urllib.parse
import xml.etree.ElementTree as ET

NEWS_STRAT = "📰 News + Vol + Price Breakout (Only News)"

# Professional News Tables + Default Open Mini-Chart CSS
st.markdown(
    """
<style>
.pro-news-wrap {
    background: #0d1117;
    border: 1px solid #262c36;
    border-radius: 10px;
    overflow: hidden;
    margin-bottom: 18px;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.45);
    font-family: 'Inter', 'Noto Sans Telugu', 'Segoe UI', Roboto, sans-serif;
}
.pro-news-hdr {
    padding: 10px 16px;
    font-size: 14.5px;
    font-weight: 700;
    color: #ffffff;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #262c36;
    letter-spacing: 0.2px;
}
.pro-news-table {
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
    background: #0d1117;
    color: #e6edf3;
    font-family: 'Inter', 'Noto Sans Telugu', 'Segoe UI', Roboto, sans-serif;
}
.pro-news-table th {
    background: #161b22;
    color: #8b949e;
    font-size: 11.5px;
    font-weight: 700;
    text-transform: uppercase;
    padding: 9px 12px;
    border-bottom: 1px solid #262c36;
    text-align: left;
    letter-spacing: 0.4px;
}
.pro-news-table td {
    padding: 12px 12px;
    border-bottom: 1px solid #21262d;
    vertical-align: middle;
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: clip !important;
    line-height: 1.55;
}
.pro-news-table tr:hover td {
    background: rgba(56, 139, 253, 0.05);
}
.mc-inline-card {
    width: 100%;
    background: #0b0e14;
    border: 1.5px solid #30363d;
    border-radius: 8px;
    padding: 7px 8px;
    box-sizing: border-box;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.65);
    transition: border-color 0.2s;
}
.mc-inline-card:hover {
    border-color: #38bdf8;
}
.mc-inline-top {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 4px;
    padding-bottom: 4px;
    border-bottom: 1px solid #161b22;
}
.mc-grid-btn {
    background: #161b22;
    border: 1px solid #30363d;
    color: #38bdf8 !important;
    font-size: 10.5px;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 4px;
    text-decoration: none !important;
    font-family: monospace;
    white-space: nowrap;
}
.mc-grid-btn:hover {
    background: #1f6feb;
    color: #ffffff !important;
    border-color: #58a6ff;
}
.pro-matter-box {
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-height: 210px;
    background: rgba(22, 27, 34, 0.45);
    border: 1px solid #21262d;
    border-radius: 8px;
    padding: 10px 14px;
    box-sizing: border-box;
}
.pro-meta-strip {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    padding-bottom: 8px;
    margin-bottom: 8px;
    border-bottom: 1px dashed #262c36;
}
.pro-meta-chip {
    background: #161b22;
    border: 1px solid #30363d;
    padding: 2px 8px;
    border-radius: 5px;
    font-size: 12px;
    font-weight: 700;
    color: #e6edf3;
}
.pro-pill-imp {
    display: inline-block;
    background: linear-gradient(90deg, #b91c1c 0%, #d97706 100%);
    border: 1px solid #ffd700;
    color: #ffffff;
    font-weight: 800;
    font-size: 11px;
    padding: 2px 9px;
    border-radius: 20px;
    box-shadow: 0 0 8px rgba(255, 215, 0, 0.4);
}
.pro-pill-buy {
    display: inline-block;
    background: rgba(46, 160, 67, 0.18);
    border: 1px solid #2ea043;
    color: #3fb950;
    font-weight: 700;
    font-size: 11.5px;
    padding: 2px 9px;
    border-radius: 20px;
}
.pro-pill-sell {
    display: inline-block;
    background: rgba(248, 81, 73, 0.18);
    border: 1px solid #f85149;
    color: #ff7b72;
    font-weight: 700;
    font-size: 11.5px;
    padding: 2px 9px;
    border-radius: 20px;
}
.pro-pill-neut {
    display: inline-block;
    background: rgba(210, 153, 34, 0.16);
    border: 1px solid #d29922;
    color: #e3b341;
    font-weight: 700;
    font-size: 11.5px;
    padding: 2px 9px;
    border-radius: 20px;
}
.pro-cat-tag {
    display: inline-block;
    background: #21262d;
    color: #ffd700;
    font-size: 11px;
    font-weight: 600;
    padding: 2px 7px;
    border-radius: 4px;
}
.pro-time-badge {
    background: rgba(56, 189, 248, 0.12);
    border: 1px solid #38bdf8;
    color: #79c0ff;
    font-size: 11.5px;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 12px;
    margin-left: auto;
}
.pro-news-hl {
    font-size: 15px;
    font-weight: 700;
    color: #f0f6fc;
    margin-bottom: 6px;
    line-height: 1.45;
}
.pro-news-dtl {
    font-size: 13px;
    color: #c9d1d9;
    line-height: 1.6;
    margin-top: 5px;
    background: rgba(13, 17, 23, 0.85);
    border-left: 3px solid #38bdf8;
    padding: 8px 12px;
    border-radius: 0 6px 6px 0;
}
.pro-qres-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(155px, 1fr));
    gap: 6px;
    margin-top: 6px;
    margin-bottom: 6px;
    background: #0b0e14;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 7px 10px;
}
.pro-qres-cell {
    font-size: 12px;
    color: #c9d1d9;
    line-height: 1.4;
}
.pro-news-mkt {
    font-size: 12.5px;
    color: #79c0ff;
    margin-top: 6px;
    font-weight: 600;
    background: rgba(56, 189, 248, 0.07);
    border-left: 3px solid #eab308;
    padding: 6px 10px;
    border-radius: 0 5px 5px 0;
}
.pro-stk-badge {
    display: inline-block;
    background: #1f2937;
    border: 1px solid #374151;
    color: #58a6ff !important;
    font-weight: 800;
    font-size: 12.5px;
    padding: 3px 8px;
    border-radius: 6px;
    text-decoration: none !important;
    font-family: 'Consolas', monospace;
}
</style>
""",
    unsafe_allow_html=True,
)

_BULL_CATALYSTS = [
    (
        "📰Order-Win",
        [
            "order", "bagged", "contract", "letter of award", "loa",
            "lowest bidder", "l1 bidder", "tender", "deal win", "work order",
            "secures order", "wins order", "mega order", "project win",
        ],
    ),
    (
        "📊Q-Results (Beat)",
        [
            "net profit rises", "profit jumps", "profit surges", "profit up",
            "profit grows", "profit doubles", "pat rises", "pat jumps",
            "ebitda rises", "ebitda jumps", "revenue grows", "revenue rises",
            "margin expands", "beats estimates", "beats street", "strong q1",
            "strong q2", "strong q3", "strong q4", "turnaround", "posts profit",
            "q1 results", "q2 results", "q3 results", "q4 results",
        ],
    ),
    (
        "🚀Broker-Upgrade",
        [
            "buy", "upgrades to buy", "initiates coverage", "overweight", "outperform",
            "raises target", "target price", "hikes target", "top pick",
            "conviction buy", "bullish",
        ],
    ),
    (
        "✅Regulatory-Nod",
        [
            "usfda", "approval", "final approval", "tentative approval", "eir",
            "zero observations", "clean chit", "patent", "dcgi", "nod",
            "clearance", "license", "pli", "subsidy",
        ],
    ),
    (
        "🏭Expansion/M&A",
        [
            "acquisition", "acquires", "joint venture", "mou", "partner",
            "commissioning", "commercial production", "capacity", "launch",
            "new plant", "demerger", "tie-up",
        ],
    ),
    (
        "💰Corp-Action",
        [
            "dividend", "buyback", "bonus", "stock split", "qip",
            "preferential", "rights issue", "fundraise", "record date",
        ],
    ),
    (
        "🤝Institutional-Buy",
        [
            "block deal", "bulk deal", "stake buy", "promoter buys",
            "promoter increases", "fii", "mutual fund buys", "stake",
        ],
    ),
]

_BEAR_CATALYSTS = [
    (
        "📉Q-Results (Miss)",
        [
            "profit falls", "profit drops", "profit declines", "profit plunges",
            "profit slumps", "pat falls", "pat drops", "net loss", "loss widens",
            "misses estimates", "misses street", "weak results", "margin shrinks",
            "margin contracts", "ebitda falls", "revenue falls", "disappointing",
            "q2 loss", "q1 loss", "q3 loss", "q4 loss", "falls %", "slumps",
        ],
    ),
    (
        "🩸Broker-Downgrade",
        [
            "downgrade", "sell call", "underperform", "underweight",
            "cuts target", "target cut", "slashes target", "reduce",
        ],
    ),
    (
        "⚠️Regulatory/Tax",
        [
            "sebi", "penalty", "show cause", "tax demand", "notice",
            "gst", "ed raid", "it raid", "cbi", "probe", "fraud",
            "default", "insolvency", "nclt", "ban",
        ],
    ),
    (
        "🏥USFDA-Alert",
        [
            "form 483", "observations", "warning letter", "import alert",
            "oai status", "recall",
        ],
    ),
    (
        "🚪Stake-Sale/Exit",
        [
            "resigns", "steps down", "auditor resigns", "stake sale",
            "offloads", "sells stake", "promoter sells", "pledge", "ofs",
        ],
    ),
]

_MACRO_BULL_KW = [
    "rate cut", "fii buying", "fii inflow", "gdp grows", "inflation cools",
    "inflation eases", "gst collection rises", "record high", "rbi liquidity",
    "us fed cut", "tariff relief", "trade deal", "crude falls", "crude drops",
    "stimulus", "manufacturing pmi rises", "upgrades india",
]
_MACRO_BEAR_KW = [
    "rate hike", "fii selling", "fii outflow", "inflation rises", "inflation spikes",
    "gdp slows", "crude surges", "crude jumps", "war", "geopolitical", "tariff",
    "sanctions", "recession", "yield spikes", "rupee hits record low", "rupee falls",
    "sebi tightens", "stt hike", "tax hike", "dow plunges", "nasdaq falls",
]
_MACRO_CORE_KW = [
    "rbi", "sebi", "fii", "dii", "inflation", "cpi", "wpi", "gdp", "gst",
    "fiscal deficit", "repo rate", "mpc", "fed ", "federal reserve", "powell",
    "wall street", "nasdaq", "dow jones", "s&p 500", "brent crude", "opec",
    "us treasury", "bond yield", "dollar index", "rupee", "tariff", "exports",
    "imports", "pmi", "iip", "sensex", "nifty",
]

_COMPANY_TO_NSE = {
    "pidilite": "PIDILITIND", "reliance": "RELIANCE", "tcs": "TCS",
    "tata consultancy": "TCS", "infosys": "INFY", "hdfc bank": "HDFCBANK",
    "icici bank": "ICICIBANK", "state bank": "SBIN", "sbi ": "SBIN",
    "bharti airtel": "BHARTIARTL", "airtel": "BHARTIARTL", "larsen": "LT",
    "l&t": "LT", "itc ": "ITC", "hindustan unilever": "HINDUNILVR",
    "hul": "HINDUNILVR", "bajaj finance": "BAJFINANCE", "axis bank": "AXISBANK",
    "kotak mahindra": "KOTAKBANK", "maruti": "MARUTI", "mahindra & mahindra": "M&M",
    "m&m": "M&M", "sun pharma": "SUNPHARMA", "ultratech": "ULTRACEMCO",
    "titan": "TITAN", "ntpc": "NTPC", "tata motors": "TATAMOTORS",
    "tata steel": "TATASTEEL", "power grid": "POWERGRID", "adani enterprises": "ADANIENT",
    "adani ports": "ADANIPORTS", "coal india": "COALINDIA", "asian paints": "ASIANPAINT",
    "hcl tech": "HCLTECH", "wipro": "WIPRO", "bajaj auto": "BAJAJ-AUTO",
    "ongc": "ONGC", "jsw steel": "JSWSTEEL", "hindalco": "HINDALCO",
    "grasim": "GRASIM", "tech mahindra": "TECHM", "cipla": "CIPLA",
    "dr reddy": "DRREDDY", "eicher": "EICHERMOT", "nestle": "NESTLEIND",
    "britannia": "BRITANNIA", "apollo hosp": "APOLLOHOSP", "divi's": "DIVISLAB",
    "divis": "DIVISLAB", "hero motocorp": "HEROMOTOCO", "indusind": "INDUSINDBK",
    "bharat electronics": "BEL", "trent": "TRENT", "shriram finance": "SHRIRAMFIN",
    "vedanta": "VEDL", "hindustan aeronautics": "HAL", "hal ": "HAL",
    "dlf": "DLF", "siemens": "SIEMENS", "polycab": "POLYCAB", "dixon": "DIXON",
    "zomato": "ETERNAL", "eternal": "ETERNAL", "paytm": "PAYTM",
    "suzlon": "SUZLON", "rvnl": "RVNL", "ireda": "IREDA", "mazagon": "MAZDOCK",
    "bhel": "BHEL", "punjab national": "PNB", "bank of baroda": "BANKBARODA",
    "canara bank": "CANBK", "lupin": "LUPIN", "aurobindo": "AUROPHARMA",
    "torrent pharma": "TORNTPHARM", "zydus": "ZYDUSLIFE", "biocon": "BIOCON",
    "gail": "GAIL", "indian oil": "IOC", "bpcl": "BPCL", "hpcl": "HINDPETRO",
    "mrf": "MRF", "ashok leyland": "ASHOKLEY", "tvs motor": "TVSMOTOR",
    "cholamandalam": "CHOLAFIN", "muthoot": "MUTHOOTFIN", "manappuram": "MANAPPURAM",
    "srf ": "SRF", "pi industries": "PIIND", "deepak nitrite": "DEEPAKNTR",
    "aarti ind": "AARTIIND", "astral": "ASTRAL", "supreme ind": "SUPREMEIND",
    "cummins": "CUMMINSIND", "abb ": "ABB", "abb india": "ABB",
    "bharat forge": "BHARATFORG", "coforge": "COFORGE", "persistent": "PERSISTENT",
    "mphasis": "MPHASIS", "ltimindtree": "LTIM", "l&t tech": "LTTS",
    "naukri": "NAUKRI", "info edge": "NAUKRI", "jubilant food": "JUBLFOOD",
    "indian hotels": "INDHOTEL", "indigo": "INDIGO", "interglobe": "INDIGO",
    "irctc": "IRCTC", "irfc": "IRFC", "rec ltd": "RECLTD", "pfc": "PFC",
    "hudco": "HUDCO", "nhpc": "NHPC", "sjvn": "SJVN", "cg power": "CGPOWER",
    "kpit": "KPITTECH", "tata elxsi": "TATAELXSI", "kalyan jewellers": "KALYANKJIL",
    "fortis": "FORTIS", "max health": "MAXHEALTH", "oberoi realty": "OBEROIRLTY",
    "godrej prop": "GODREJPROP", "prestige estates": "PRESTIGE", "lodha": "LODHA",
    "macrotech": "LODHA", "phoenix mills": "PHOENIXLTD", "yes bank": "YESBANK",
    "idfc first": "IDFCFIRSTB", "federal bank": "FEDERALBNK", "bandhan bank": "BANDHANBNK",
    "rbl bank": "RBLBANK", "au small": "AUBANK", "bse ": "BSE", "mcx": "MCX",
    "cdsl": "CDSL", "angel one": "ANGELONE", "cams": "CAMS", "ambuja": "AMBUJACEM",
    "acc ": "ACC", "shree cement": "SHREECEM", "dalmia": "DALBHARAT",
    "tata power": "TATAPOWER", "tata consumer": "TATACONSUM", "tata chem": "TATACHEM",
    "tata comm": "TATACOMM", "dabur": "DABUR", "marico": "MARICO",
    "godrej consumer": "GODREJCP", "colgate": "COLPAL", "united breweries": "UBL",
    "havells": "HAVELLS", "voltas": "VOLTAS", "crompton": "CROMPTON",
    "bata": "BATAINDIA", "page ind": "PAGEIND", "zee ": "ZEEL",
    "sun tv": "SUNTV", "pvr inox": "PVRINOX", "delhivery": "DELHIVERY",
    "rolex rings": "ROLEXRINGS", "industower": "INDUSTOWER", "indus towers": "INDUSTOWER",
    "birlasoft": "BSOFT", "karnataka bank": "KTKBANK", "eclerx": "ECLERX",
    "syrma": "SYRMA", "mas financial": "MASFIN", "dodla": "DODLA",
    "vaibhav global": "VAIBHAVGBL", "heg ": "HEG", "nocil": "NOCIL",
}


def _build_inline_mini_chart_html(
    stk_sym, stock_row=None, df_5m=None, cat_label=""
):
    """Renders the 5m Mini-Chart (Candles + VWAP V: + EMA10 E: + Vol) ALWAYS OPEN inline inside the table cell!"""
    clean_sym = str(stk_sym).replace(".NS", "").strip()
    ft = f"{clean_sym}.NS"

    if df_5m is None or df_5m.empty:
        store_5m = _SS.get("5m_store", {})
        if ft in store_5m and not store_5m[ft].empty:
            df_5m = process_5m_data(store_5m[ft])

    if df_5m is None or df_5m.empty or "Close" not in df_5m.columns:
        return (
            "<div class='mc-inline-card'"
            " style='min-height:190px;display:flex;flex-direction:column;justify-content:center;align-items:center;'>"
            f"<a class='pro-stk-badge' href='?grid_sym={ft}'"
            f" target='_self'>{clean_sym} 📌 Grid Chart</a><span"
            " style='color:#8b949e;font-size:11px;margin-top:6px;'>5m Intraday"
            " Chart</span></div>"
        )

    d = df_5m.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    if d.empty:
        return (
            f"<a class='pro-stk-badge' href='?grid_sym={ft}'"
            f" target='_self'>{clean_sym} 📊</a>"
        )

    sess_id = (d.index.to_series().diff() > pd.Timedelta(minutes=120)).cumsum()
    d = d[sess_id == sess_id.iloc[-1]].tail(75).copy()
    if d.empty:
        return (
            f"<a class='pro-stk-badge' href='?grid_sym={ft}'"
            f" target='_self'>{clean_sym} 📊</a>"
        )

    ltp = (
        float(stock_row["P"])
        if (stock_row is not None and "P" in stock_row)
        else float(d["Close"].iloc[-1])
    )
    day_c = (
        float(stock_row["Day_C"])
        if (stock_row is not None and "Day_C" in stock_row)
        else ((ltp / float(d["Open"].iloc[0]) - 1.0) * 100.0)
    )
    day_h = (
        float(stock_row["H"])
        if (stock_row is not None and "H" in stock_row)
        else float(d["High"].max())
    )
    day_l = (
        float(stock_row["L"])
        if (stock_row is not None and "L" in stock_row)
        else float(d["Low"].min())
    )

    last_i = d.index[-1]
    d.at[last_i, "Close"] = ltp
    if ltp > float(d.at[last_i, "High"]):
        d.at[last_i, "High"] = ltp
    if ltp < float(d.at[last_i, "Low"]) or float(d.at[last_i, "Low"]) <= 0:
        d.at[last_i, "Low"] = ltp

    if "VWAP" not in d.columns:
        tp = (d["High"] + d["Low"] + d["Close"]) / 3.0
        d["VWAP"] = tp.expanding().mean()
    if "EMA_10" not in d.columns:
        d["EMA_10"] = d["Close"].ewm(span=10, adjust=False).mean()

    y_min = min(
        float(d["Low"].min()), float(d["VWAP"].min()), float(d["EMA_10"].min())
    )
    y_max = max(
        float(d["High"].max()), float(d["VWAP"].max()), float(d["EMA_10"].max())
    )
    y_rng = max(y_max - y_min, ltp * 0.002)
    y_low = y_min - y_rng * 0.10
    y_high = y_max + y_rng * 0.12

    W, H_svg = 345, 165
    p_top, p_bot = 6, 126
    v_top, v_bot = 130, 152
    n_bars = len(d)
    step_x = (W - 44) / max(n_bars, 1)
    bar_w = max(2.0, min(5.5, step_x * 0.68))

    def py(val):
        return round(
            p_bot - ((float(val) - y_low) / (y_high - y_low)) * (p_bot - p_top), 1
        )

    vol_s = (
        d["Volume"].fillna(0.0)
        if "Volume" in d.columns
        else pd.Series(0.0, index=d.index)
    )
    vol_max = max(float(vol_s.max()), 1.0)
    vol_sma = vol_s.rolling(20, min_periods=1).mean()

    svg_elems = []
    vwap_pts, ema_pts = [], []

    for idx in range(n_bars):
        cx = round(6 + idx * step_x + step_x * 0.5, 1)
        o_v = float(d["Open"].iloc[idx])
        h_v = float(d["High"].iloc[idx])
        l_v = float(d["Low"].iloc[idx])
        c_v = float(d["Close"].iloc[idx])
        vw_v = float(d["VWAP"].iloc[idx])
        em_v = float(d["EMA_10"].iloc[idx])
        vl_v = float(vol_s.iloc[idx])
        vsma_v = float(vol_sma.iloc[idx])

        is_bull = c_v >= o_v
        is_hv = vl_v > (vsma_v * 1.618) and vsma_v > 0
        if is_hv and is_bull and c_v > vw_v and c_v > em_v:
            c_col = "#00FF00"
        elif is_hv and (not is_bull) and c_v < vw_v and c_v < em_v:
            c_col = "#FF0000"
        else:
            c_col = "#2ea043" if is_bull else "#da3633"

        yh, yl = py(h_v), py(l_v)
        yo, yc = py(o_v), py(c_v)
        b_top = min(yo, yc)
        b_h = max(1.5, abs(yc - yo))

        svg_elems.append(
            f"<line x1='{cx}' y1='{yh}' x2='{cx}' y2='{yl}' stroke='{c_col}'"
            " stroke-width='1.1'/>"
        )
        svg_elems.append(
            f"<rect x='{round(cx - bar_w/2, 1)}' y='{b_top}'"
            f" width='{round(bar_w, 1)}' height='{b_h}' fill='{c_col}'/>"
        )

        if vl_v > 0:
            vh = max(1.0, (vl_v / vol_max) * (v_bot - v_top))
            vy = round(v_bot - vh, 1)
            v_col = (
                "#00FF00"
                if c_col == "#00FF00"
                else (
                    "#FF0000"
                    if c_col == "#FF0000"
                    else (
                        "rgba(46,160,67,0.45)" if is_bull else "rgba(218,54,51,0.45)"
                    )
                )
            )
            svg_elems.append(
                f"<rect x='{round(cx - bar_w/2, 1)}' y='{vy}'"
                f" width='{round(bar_w, 1)}' height='{round(vh, 1)}' fill='{v_col}'/>"
            )

        vwap_pts.append(f"{cx},{py(vw_v)}")
        ema_pts.append(f"{cx},{py(em_v)}")

    svg_elems.append(
        f"<polyline fill='none' stroke='#FFD700' stroke-width='1.5'"
        f" stroke-dasharray='3,3' points='{' '.join(vwap_pts)}'/>"
    )
    svg_elems.append(
        f"<polyline fill='none' stroke='#00BFFF' stroke-width='1.4'"
        f" stroke-dasharray='5,3' points='{' '.join(ema_pts)}'/>"
    )

    last_vw = float(d["VWAP"].iloc[-1])
    last_em = float(d["EMA_10"].iloc[-1])
    tag_pos = max(0, int(n_bars * 0.56))
    tag_x = round(6 + tag_pos * step_x, 1)
    vy_tag = py(float(d["VWAP"].iloc[tag_pos]))
    ey_tag = py(float(d["EMA_10"].iloc[tag_pos]))
    if abs(vy_tag - ey_tag) < 13:
        vy_tag -= 6.5
        ey_tag += 6.5

    svg_elems.append(
        f"<rect x='{tag_x}' y='{vy_tag - 7}' width='46' height='12.5' rx='2'"
        " fill='#FFD700'/><text x='{0}' y='{1}' fill='#161b22' font-size='8.5'"
        " font-family='monospace'"
        f" font-weight='bold'>V:{last_vw:.1f}</text>".format(
            tag_x + 3, vy_tag + 2.5
        )
    )
    svg_elems.append(
        f"<rect x='{tag_x}' y='{ey_tag - 7}' width='46' height='12.5' rx='2'"
        " fill='#00BFFF'/><text x='{0}' y='{1}' fill='#161b22' font-size='8.5'"
        " font-family='monospace'"
        f" font-weight='bold'>E:{last_em:.1f}</text>".format(
            tag_x + 3, ey_tag + 2.5
        )
    )

    svg_elems.append(
        f"<text x='{W - 2}' y='{p_top + 8}' fill='#8b949e' font-size='8.5'"
        f" font-family='monospace' text-anchor='end'>{y_max:.1f}</text>"
    )
    svg_elems.append(
        f"<text x='{W - 2}' y='{p_bot}' fill='#8b949e' font-size='8.5'"
        f" font-family='monospace' text-anchor='end'>{y_min:.1f}</text>"
    )
    t_start = pd.to_datetime(d.index[0]).strftime("%I:%M %p")
    t_end = pd.to_datetime(d.index[-1]).strftime("%I:%M %p")
    svg_elems.append(
        f"<text x='6' y='{H_svg - 2}' fill='#8b949e' font-size='8'"
        f" font-family='monospace'>{t_start}</text>"
    )
    svg_elems.append(
        f"<text x='{W - 40}' y='{H_svg - 2}' fill='#8b949e' font-size='8'"
        f" font-family='monospace' text-anchor='end'>{t_end}</text>"
    )

    pct_col = "#2ea043" if day_c >= 0 else "#da3633"
    sign = "+" if day_c > 0 else ""
    if day_c >= 0:
        pb = ((day_h - ltp) / day_h * 100.0) if day_h > 0 else 0.0
        pb_html = (
            f" <span style='color:#FF8C00;font-size:10px;'>📉-{pb:.1f}% DH</span>"
            if pb >= 0.1
            else ""
        )
    else:
        bnc = ((ltp - day_l) / day_l * 100.0) if day_l > 0 else 0.0
        pb_html = (
            f" <span style='color:#00BFFF;font-size:10px;'>📈+{bnc:.1f}% DL</span>"
            if bnc >= 0.1
            else ""
        )

    strat_span = (
        " <span"
        " style='font-size:9px;background:rgba(0,191,255,0.2);border:1px solid"
        " #00BFFF;padding:0px"
        f" 4px;border-radius:3px;color:#00BFFF;'>{_html.escape(cat_label)}</span>"
        if cat_label
        else ""
    )

    return (
        "<div class='mc-inline-card'>"
        "<div class='mc-inline-top'>"
        "<div style='line-height:1.2;'>"
        f"<b style='color:#fff;font-size:12.5px;'>{clean_sym}</b>{strat_span}<br>"
        f"<span style='font-size:11px;color:#ccc;'>₹{ltp:.2f} "
        f"<span style='color:{pct_col};font-weight:bold;'>({sign}{day_c:.2f}%)</span>{pb_html}</span>"
        "</div>"
        f"<a class='mc-grid-btn' href='?grid_sym={ft}' target='_self' title='Open in Pro Multi-Chart Grid'>📌 Grid Chart</a>"
        "</div>"
        f"<svg width='100%' height='{H_svg}' viewBox='0 0 {W} {H_svg}' preserveAspectRatio='none' style='background:#0b0e14;display:block;border-radius:4px;'>"
        + "".join(svg_elems)
        + "</svg></div>"
    )


def _classify_headline(title_str, is_macro=False):
    t_low = str(title_str).lower()
    for tag, kw_list in _BEAR_CATALYSTS:
        if any(k in t_low for k in kw_list):
            return tag, -1
    for tag, kw_list in _BULL_CATALYSTS:
        if any(k in t_low for k in kw_list):
            return tag, 1
    if is_macro:
        if any(k in t_low for k in _MACRO_BEAR_KW):
            return "🔴Macro-Negative", -1
        if any(k in t_low for k in _MACRO_BULL_KW):
            return "🟢Macro-Positive", 1
        if any(k in t_low for k in _MACRO_CORE_KW):
            return "🏛️Policy/Macro", 1 if any(w in t_low for w in ("rises", "gains", "jumps", "boost", "inflow", "cut")) else (-1 if any(w in t_low for w in ("falls", "drops", "slumps", "outflow", "deficit", "hike")) else 0)
    if any(q in t_low for q in ("q1", "q2", "q3", "q4", "quarter", "net profit", "pat ", "results")):
        if any(w in t_low for w in ("down ", "falls", "drops", "declines", "lower", "loss", "misses", "slumps")):
            return "📉Q-Results (Miss)", -1
        return "📊Q-Results (Beat)", 1
    return "📰News-Catalyst", 0


def _is_most_important_catalyst(cat_tag, title_en="", vol_x=1.0, day_c=0.0, age_h=12.0, is_macro=False):
    if age_h > 24.0:
        return False
    t_low = str(title_en).lower()
    if is_macro:
        hi_macro = ("rbi", "repo rate", "us fed", "federal reserve", "powell", "cpi", "inflation", "gdp", "fii", "sebi", "tariff", "crude", "dow ", "nasdaq")
        return any(k in t_low for k in hi_macro)

    major_cats = ("Q-Results", "Order-Win", "Regulatory", "USFDA", "Expansion/M&A", "Sell-The-News", "Short-Squeeze")
    is_major_cat = any(mc.lower() in str(cat_tag).lower() for mc in major_cats)
    if is_major_cat and vol_x >= 1.8 and abs(day_c) >= 1.5:
        return True
    if vol_x >= 2.8 and abs(day_c) >= 2.5:
        return True
    return False


_JUNK_NEWS_WORDS = (
    "stocks to watch", "stocks in news", "live updates", "live blog",
    "share price live", "stock market live", "check details", "know why",
    "here's why", "here is why", "top gainers", "top losers", "market wrap",
    "closing bell", "opening bell", "buy or sell", "stocks to buy",
    "buzzing stocks", "trade setup", "what should investors do",
    "share price today", "stock split history", "dividend history",
    "how to trade", "picks for today", "intraday picks",
)


def _clean_en_headline(title_str):
    t = str(title_str or "").strip()
    if " - " in t:
        parts = t.split(" - ")
        if len(parts[-1]) < 40:
            t = " - ".join(parts[:-1]).strip()
    return t


def _strip_html_tags(raw_html, main_title=""):
    if not raw_html:
        return ""
    txt = _re.sub(r"<[^>]+>", " | ", str(raw_html))
    txt = _html.unescape(txt)
    main_low = _clean_en_headline(main_title).lower()[:35]
    parts = []
    for seg in txt.split("|"):
        s = _clean_en_headline(seg.strip())
        s_low = s.lower()
        if len(s) >= 20 and not s_low.startswith("view full"):
            if main_low and (main_low in s_low or s_low[:35] in main_low):
                continue
            if not _is_clear_factual_news(s):
                continue
            if s not in parts:
                parts.append(s)
    return " • ".join(parts[:3])


def _is_clear_factual_news(title_str):
    t_low = str(title_str or "").lower()
    if len(t_low) < 18:
        return False
    if any(jw in t_low for jw in _JUNK_NEWS_WORDS):
        return False
    return True


def _has_real_market_impact(title_str, is_macro=False):
    if not _is_clear_factual_news(title_str):
        return False
    tag, bias = _classify_headline(title_str, is_macro=is_macro)
    if bias != 0:
        return True
    if is_macro:
        t_low = str(title_str).lower()
        return any(k in t_low for k in _MACRO_CORE_KW)
    return False


def _extract_stock_from_headline(title_en):
    t_clean = _clean_en_headline(title_en)
    t_low = f" {t_clean.lower()} "

    m_nse = _re.search(r"NSE\s*:\s*([A-Z0-9&\-]{2,15})", t_clean.upper())
    if m_nse:
        return m_nse.group(1).strip(), True

    for comp_kw, nse_sym in _COMPANY_TO_NSE.items():
        if comp_kw in t_low:
            return nse_sym, True

    all_known = set(NIFTY_50 + FNO_STOCKS + MIDCAP_150 + SMALLCAP_250)
    words_up = _re.findall(r"[A-Z&]{3,15}", t_clean.upper())
    for w in words_up:
        if w in all_known and w not in (
            "NSE", "BSE", "RBI", "SEBI", "USD", "INR", "CEO", "CFO", "IPO", "ETF", "PSU"
        ):
            return w, True

    for sym in all_known:
        if len(sym) >= 6 and sym[:6].lower() in t_low:
            return sym, True

    m = _re.match(
        r"^([A-Z][A-Za-z0-9&\.\-\s]{2,28}?)\s+(?:Q[1-4]|FY\d{2}|net"
        r" profit|profit|revenue|results|shares|stock|bags|wins|gets|announces|declares|reports|posts|board|acquires|signs|receives)",
        t_clean,
    )
    if m:
        comp_name = m.group(1).strip()
        if len(comp_name) >= 3 and comp_name.upper() not in (
            "INDIA", "INDIAN", "MARKET", "SENSEX", "NIFTY", "STOCK", "SHARES"
        ):
            return comp_name.upper()[:16], False

    return "NSE CORP", False


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_pro_qresults_summary(sym, headline_en="", bias=0, day_c=0.0, vol_x=1.0):
    """
    Fetches actual quarterly financial metrics (Revenue, Net Profit, EBITDA, OPM%,
    YoY%, QoQ%, EPS Estimate vs Reported Beat/Miss) for professional traders.
    """
    clean_s = str(sym).replace(".NS", "").strip()
    if not clean_s or clean_s in ("NSE CORP", "🇮🇳 INDIA MKT", "🌍 GLOBAL", "MARKET"):
        return ""

    rev_cr, rev_yoy, rev_qoq = None, None, None
    pat_cr, pat_yoy, pat_qoq = None, None, None
    ebitda_cr, opm_pct, opm_yoy_bps = None, None, None
    eps_est, eps_act, eps_surp = None, None, None
    q_label = "Latest Qtr"

    try:
        tkr = yf.Ticker(f"{clean_s}.NS")
        q_inc = tkr.quarterly_income_stmt
        if q_inc is None or q_inc.empty:
            q_inc = tkr.quarterly_financials

        if q_inc is not None and not q_inc.empty and len(q_inc.columns) >= 1:
            cols = list(q_inc.columns)
            try:
                q_label = pd.to_datetime(cols[0]).strftime("%b-%Y")
            except Exception:
                q_label = "Latest Qtr"

            def _get_row_series(keys_list):
                for k in keys_list:
                    for idx_name in q_inc.index:
                        if k.lower() == str(idx_name).lower() or k.lower() in str(idx_name).lower():
                            return pd.to_numeric(q_inc.loc[idx_name], errors="coerce")
                return None

            s_rev = _get_row_series(["Total Revenue", "Operating Revenue", "Revenue"])
            s_pat = _get_row_series(["Net Income", "Net Income Common Stockholders", "Profit After Tax"])
            s_ebitda = _get_row_series(["EBITDA", "Normalized EBITDA", "Operating Income", "EBIT"])

            if s_rev is not None and pd.notna(s_rev.iloc[0]) and float(s_rev.iloc[0]) != 0:
                r0 = float(s_rev.iloc[0])
                rev_cr = r0 / 1e7
                if len(s_rev) >= 2 and pd.notna(s_rev.iloc[1]) and float(s_rev.iloc[1]) != 0:
                    r1 = float(s_rev.iloc[1])
                    rev_qoq = ((r0 - r1) / abs(r1)) * 100.0
                if len(s_rev) >= 5 and pd.notna(s_rev.iloc[4]) and float(s_rev.iloc[4]) != 0:
                    r4 = float(s_rev.iloc[4])
                    rev_yoy = ((r0 - r4) / abs(r4)) * 100.0

            if s_pat is not None and pd.notna(s_pat.iloc[0]):
                p0 = float(s_pat.iloc[0])
                pat_cr = p0 / 1e7
                if len(s_pat) >= 2 and pd.notna(s_pat.iloc[1]) and float(s_pat.iloc[1]) != 0:
                    p1 = float(s_pat.iloc[1])
                    pat_qoq = ((p0 - p1) / abs(p1)) * 100.0
                if len(s_pat) >= 5 and pd.notna(s_pat.iloc[4]) and float(s_pat.iloc[4]) != 0:
                    p4 = float(s_pat.iloc[4])
                    pat_yoy = ((p0 - p4) / abs(p4)) * 100.0

            if s_ebitda is not None and pd.notna(s_ebitda.iloc[0]):
                eb0 = float(s_ebitda.iloc[0])
                ebitda_cr = eb0 / 1e7
                if rev_cr and rev_cr > 0:
                    opm_pct = (ebitda_cr / rev_cr) * 100.0
                    if len(s_ebitda) >= 5 and len(s_rev) >= 5 and pd.notna(s_ebitda.iloc[4]) and pd.notna(s_rev.iloc[4]) and float(s_rev.iloc[4]) > 0:
                        opm_prev = (float(s_ebitda.iloc[4]) / float(s_rev.iloc[4])) * 100.0
                        opm_yoy_bps = int(round((opm_pct - opm_prev) * 100))

        try:
            ed = tkr.earnings_dates
            if ed is not None and not ed.empty:
                ed_valid = ed.dropna(subset=["Reported EPS", "EPS Estimate"], how="any")
                if not ed_valid.empty:
                    latest_e = ed_valid.iloc[0]
                    eps_est = float(latest_e.get("EPS Estimate", 0))
                    eps_act = float(latest_e.get("Reported EPS", 0))
                    if "Surprise(%)" in latest_e and pd.notna(latest_e["Surprise(%)"]):
                        eps_surp = float(latest_e["Surprise(%)"]) * (100.0 if abs(float(latest_e["Surprise(%)"])) <= 1.5 else 1.0)
                    elif eps_est != 0:
                        eps_surp = ((eps_act - eps_est) / abs(eps_est)) * 100.0
        except Exception:
            pass
    except Exception:
        pass

    if rev_cr is None and pat_cr is None and eps_surp is None:
        return ""

    if rev_cr is not None:
        r_yoy_s = f"<span style='color:{'#3fb950' if (rev_yoy or 0)>=0 else '#f85149'};font-weight:bold;'>{rev_yoy:+.1f}% YoY</span>" if rev_yoy is not None else ""
        r_qoq_s = f" | <span style='color:{'#3fb950' if (rev_qoq or 0)>=0 else '#f85149'};'>{rev_qoq:+.1f}% QoQ</span>" if rev_qoq is not None else ""
        rev_html = f"<div class='pro-qres-cell'>💰 <b>ఆదాయం (Revenue):</b><br>₹{rev_cr:,.0f} Cr ({r_yoy_s}{r_qoq_s})</div>"
    else:
        rev_html = ""

    if pat_cr is not None:
        p_col = "#3fb950" if pat_cr >= 0 else "#f85149"
        p_yoy_s = f"<span style='color:{'#3fb950' if (pat_yoy or 0)>=0 else '#f85149'};font-weight:bold;'>{pat_yoy:+.1f}% YoY</span>" if pat_yoy is not None else ""
        p_qoq_s = f" | <span style='color:{'#3fb950' if (pat_qoq or 0)>=0 else '#f85149'};'>{pat_qoq:+.1f}% QoQ</span>" if pat_qoq is not None else ""
        pat_html = f"<div class='pro-qres-cell'>📈 <b>నికర లాభం (Net PAT):</b><br><span style='color:{p_col};font-weight:bold;'>₹{pat_cr:,.0f} Cr</span> ({p_yoy_s}{p_qoq_s})</div>"
    else:
        pat_html = ""

    if ebitda_cr is not None:
        opm_s = f" | OPM: <b>{opm_pct:.1f}%</b>" if opm_pct is not None else ""
        bps_s = f" (<span style='color:{'#3fb950' if opm_yoy_bps>=0 else '#f85149'};'>{opm_yoy_bps:+d} bps YoY</span>)" if opm_yoy_bps is not None else ""
        eb_html = f"<div class='pro-qres-cell'>⚙️ <b>EBITDA & మార్జిన్:</b><br>₹{ebitda_cr:,.0f} Cr{opm_s}{bps_s}</div>"
    else:
        eb_html = ""

    if eps_surp is not None and eps_est is not None and eps_act is not None:
        if eps_surp >= 2.0:
            exp_badge = f"<span style='color:#00FF00;font-weight:bold;'>✅ BEAT (+{eps_surp:.1f}%)</span>"
            exp_desc = f"మార్కెట్ అంచనా (EPS ₹{eps_est:.1f}) కంటే వాస్తవ ఫలితం (EPS ₹{eps_act:.1f}) మెరుగ్గా వచ్చింది."
        elif eps_surp <= -2.0:
            exp_badge = f"<span style='color:#ff5252;font-weight:bold;'>❌ MISS ({eps_surp:.1f}%)</span>"
            exp_desc = f"మార్కెట్ అంచనా (EPS ₹{eps_est:.1f}) కంటే వాస్తవ ఫలితం (EPS ₹{eps_act:.1f}) తక్కువగా వచ్చింది."
        else:
            exp_badge = f"<span style='color:#ffd700;font-weight:bold;'>⚖️ IN-LINE ({eps_surp:+.1f}%)</span>"
            exp_desc = f"మార్కెట్ అంచనాలకు (EPS ₹{eps_est:.1f}) తగ్గట్టుగానే ఫలితం (EPS ₹{eps_act:.1f}) ఉంది."
    else:
        yoy_p = pat_yoy if pat_yoy is not None else 0.0
        if (yoy_p >= 15.0 or bias > 0) and day_c >= 0.5:
            exp_badge = "<span style='color:#00FF00;font-weight:bold;'>✅ BEAT (అంచనాలను మించింది)</span>"
            exp_desc = f"బలమైన లాభాల వృద్ధి + {vol_x:.1f}x వాల్యూమ్‌తో ఇన్‌స్టిట్యూషనల్ బయింగ్ జరుగుతోంది."
        elif (yoy_p >= 10.0 or bias > 0) and day_c <= -1.0:
            exp_badge = "<span style='color:#ffd700;font-weight:bold;'>⚠️ SELL-ON-NEWS (మార్జిన్/గైడెన్స్ ఒత్తిడి)</span>"
            exp_desc = "లాభం పెరిగినప్పటికీ మార్కెట్ ఆశించిన స్థాయిలో లేకపోవడంతో ప్రాఫిట్ బుకింగ్ కనిపిస్తోంది."
        elif yoy_p < -5.0 or bias < 0:
            exp_badge = "<span style='color:#ff5252;font-weight:bold;'>❌ BELOW EXPECTATIONS (నిరాశపరిచిన ఫలితం)</span>"
            exp_desc = "మార్కెట్ అంచనాల కంటే ఫలితాలు బలహీనంగా ఉండటంతో సెల్లింగ్ ప్రెషర్ ఉంది."
        else:
            exp_badge = "<span style='color:#79c0ff;font-weight:bold;'>⚖️ IN-LINE (అంచనాలకు అనుగుణంగా)</span>"
            exp_desc = "మార్కెట్ ఊహించిన స్థాయిలోనే క్వార్టర్లీ ఫలితాలు నమోదయ్యాయి."

    exp_html = f"<div class='pro-qres-cell'>🎯 <b>మార్కెట్ అంచనా (Street View):</b><br>{exp_badge}<br><span style='font-size:11px;color:#8b949e;'>{exp_desc}</span></div>"

    return (
        f"<div style='margin-top:6px;'><span style='color:#ffd700;font-size:12px;font-weight:bold;'>"
        f"📊 ప్రొఫెషనల్ Q-Results విశ్లేషణ ({q_label}):</span>"
        f"<div class='pro-qres-grid'>{rev_html}{pat_html}{eb_html}{exp_html}</div></div>"
    )


@st.cache_data(ttl=3600, show_spinner=False)
def _translate_to_telugu(text_en):
    clean_en = str(text_en or "").strip()
    if not clean_en:
        return ""
    try:
        q_tr = urllib.parse.quote(clean_en[:900])
        tr_url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=te&dt=t&q={q_tr}"
        r_tr = requests.get(
            tr_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3.0
        )
        if r_tr.status_code == 200:
            j_tr = r_tr.json()
            te_out = "".join(seg[0] for seg in j_tr[0] if seg and seg[0])
            return te_out.strip() if te_out else clean_en
    except Exception:
        pass
    return clean_en


def _translate_batch_to_telugu(texts_list):
    if not texts_list:
        return {}
    unique_texts = list(dict.fromkeys([t for t in texts_list if t]))
    out_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(_translate_to_telugu, t): t for t in unique_texts}
        for f in concurrent.futures.as_completed(futs):
            orig_t = futs[f]
            try:
                out_map[orig_t] = f.result()
            except Exception:
                out_map[orig_t] = _clean_en_headline(orig_t)
    return out_map


def _wrap_hover_text(txt, width=32):
    """Wraps Telugu/English headline into short lines so Mini-Chart hover popup never gets clipped!"""
    clean_t = str(txt or "").strip()
    if not clean_t:
        return ""
    lines = _textwrap.wrap(clean_t, width=width)
    return "\n".join(lines[:4])


@st.cache_data(ttl=300, show_spinner=False)
def fetch_live_stock_news_batch(symbols_tuple, max_age_hours=24):
    """
    Fetches stock news within `max_age_hours` (default 24h), translates to Telugu,
    and wraps `title` cleanly so Mini-Chart hover tooltips never get cut off.
    """
    now_utc = datetime.now(ZoneInfo("UTC"))
    unique_syms = tuple(dict.fromkeys(symbols_tuple))

    def _fetch_one(fetch_sym):
        clean_sym = str(fetch_sym).replace(".NS", "").strip()
        headlines = []
        when_str = "1d" if max_age_hours <= 24 else "7d"

        try:
            q = urllib.parse.quote(f'"{clean_sym}" share OR stock NSE when:{when_str}')
            rss_url = (
                f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
            )
            resp = requests.get(
                rss_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3.5
            )
            if resp.status_code == 200 and resp.content:
                root = ET.fromstring(resp.content)
                for item in root.findall("./channel/item")[:6]:
                    title = _clean_en_headline(item.findtext("title") or "")
                    if not _is_clear_factual_news(title):
                        continue
                    desc_raw = item.findtext("description") or ""
                    desc_clean = _strip_html_tags(desc_raw, title)
                    link = (item.findtext("link") or "").strip()
                    pub_str = (item.findtext("pubDate") or "").strip()
                    age_hr = 6.0
                    if pub_str:
                        try:
                            dt_pub = parsedate_to_datetime(pub_str)
                            if dt_pub.tzinfo is None:
                                dt_pub = dt_pub.replace(tzinfo=ZoneInfo("UTC"))
                            age_hr = (
                                now_utc - dt_pub.astimezone(ZoneInfo("UTC"))
                            ).total_seconds() / 3600.0
                        except Exception:
                            age_hr = 6.0
                    if 0 <= age_hr <= max_age_hours:
                        headlines.append((age_hr, title, desc_clean, link))
        except Exception:
            pass

        if not headlines:
            try:
                yf_news = yf.Ticker(fetch_sym).news or []
                for n_item in yf_news[:5]:
                    if isinstance(n_item, dict) and isinstance(
                        n_item.get("content"), dict
                    ):
                        c_obj = n_item["content"]
                        title = _clean_en_headline(c_obj.get("title", ""))
                        summary = _strip_html_tags(
                            c_obj.get("summary") or c_obj.get("description") or "", title
                        )
                        link = str((c_obj.get("canonicalUrl") or {}).get("url", "")).strip()
                        pub_iso = c_obj.get("pubDate", "")
                        age_hr = 6.0
                        if pub_iso:
                            try:
                                dt_pub = pd.to_datetime(pub_iso, utc=True).to_pydatetime()
                                age_hr = (now_utc - dt_pub).total_seconds() / 3600.0
                            except Exception:
                                age_hr = 6.0
                    else:
                        title = _clean_en_headline(n_item.get("title", ""))
                        summary = _strip_html_tags(n_item.get("summary", ""), title)
                        link = str(n_item.get("link", "")).strip()
                        ts = n_item.get("providerPublishTime", 0)
                        age_hr = (
                            ((now_utc.timestamp() - float(ts)) / 3600.0) if ts else 6.0
                        )
                    if title and (0 <= age_hr <= max_age_hours) and _is_clear_factual_news(title):
                        headlines.append((age_hr, title, summary, link))
            except Exception:
                pass

        if not headlines:
            return fetch_sym, None

        headlines.sort(key=lambda x: x[0])
        best_age, best_title, best_desc, best_link = headlines[0]
        cat_tag, sentiment_bias = _classify_headline(best_title, is_macro=False)

        if sentiment_bias == 0 and len(headlines) > 1:
            for age_h, t_str, d_str, l_str in headlines[1:]:
                c_tag, s_bias = _classify_headline(t_str, is_macro=False)
                if s_bias != 0:
                    best_age, best_title, best_desc, best_link = age_h, t_str, d_str, l_str
                    cat_tag, sentiment_bias = c_tag, s_bias
                    break

        extra_points = []
        if best_desc:
            for seg in best_desc.split(" • "):
                if (
                    seg.lower()[:30] not in best_title.lower()
                    and seg not in extra_points
                ):
                    extra_points.append(seg)
        for _, t_other, _, _ in headlines[1:4]:
            if (
                t_other.lower()[:30] not in best_title.lower()
                and t_other not in extra_points
                and _is_clear_factual_news(t_other)
            ):
                extra_points.append(t_other)

        details_en = ". ".join(extra_points[:2]).strip()
        te_title = _translate_to_telugu(best_title)
        te_dtl = _translate_to_telugu(details_en) if details_en else ""
        combined_hover_te = te_title + (f" || {te_dtl}" if te_dtl else "")

        return fetch_sym, {
            "title": combined_hover_te,
            "title_te_full": te_title,
            "title_en": best_title,
            "details_en": details_en,
            "link": (
                best_link
                or f"https://www.google.com/search?q={clean_sym}+share+news&tbm=nws"
            ),
            "age_h": round(max(0.1, best_age), 1),
            "tag": cat_tag,
            "bias": sentiment_bias,
            "count": len(headlines),
        }

    out = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(_fetch_one, s) for s in unique_syms]
        for f in concurrent.futures.as_completed(futs):
            try:
                k, val = f.result()
                if val is not None:
                    out[k] = val
            except Exception:
                continue
    return out


def run_news_vol_price_strategy(
    df_candidates,
    processed_charts,
    min_volx=1.2,
    min_move_pct=0.75,
    cat_filter="ALL",
):
    if df_candidates is None or df_candidates.empty:
        return pd.DataFrame(), []

    df_clean_cand = df_candidates.drop_duplicates(
        subset=["T"], keep="first"
    ).copy()

    active_mask = (df_clean_cand["VolX"] >= min_volx) & (
        (df_clean_cand["Day_C"].abs() >= min_move_pct)
        | (df_clean_cand["C"].abs() >= 1.0)
    )
    df_pre = df_clean_cand[active_mask].copy()
    if df_pre.empty:
        return pd.DataFrame(), []

    df_pre["_intensity"] = df_pre["VolX"] * (
        df_pre["Day_C"].abs() + df_pre["C"].abs()
    )
    df_pre = (
        df_pre.sort_values("_intensity", ascending=False)
        .drop_duplicates(subset=["T"], keep="first")
        .head(45)
    )

    news_map = fetch_live_stock_news_batch(
        tuple(df_pre["Fetch_T"].tolist()), max_age_hours=24
    )
    if not news_map:
        return pd.DataFrame(), []

    matched_fts = [
        ft
        for ft in news_map.keys()
        if ft not in processed_charts or processed_charts[ft].empty
    ]
    if matched_fts:
        extra_5m = fetch_cached_5m_data(matched_fts)
        if not extra_5m.empty:
            for m_ft in matched_fts:
                try:
                    raw_m = (
                        extra_5m[m_ft]
                        if isinstance(extra_5m.columns, pd.MultiIndex)
                        else extra_5m
                    )
                    processed_charts[m_ft] = process_5m_data(raw_m)
                except Exception:
                    pass

    texts_to_tr = []
    for v in news_map.values():
        if v and v.get("details_en"):
            texts_to_tr.append(v["details_en"])
    te_map = _translate_batch_to_telugu(texts_to_tr)

    matched_rows = []
    feed_records = []
    important_flash_list = []
    seen_stocks = set()

    for _, row in df_pre.iterrows():
        stk_name = str(row["T"]).strip()
        ft = row["Fetch_T"]
        if stk_name in seen_stocks or ft not in news_map:
            continue

        n_info = news_map[ft]
        age_h_val = float(n_info.get("age_h", 12.0))
        if age_h_val > 24.0:
            continue

        ltp = float(row["P"])
        vwap = float(row["VWAP"])
        open_p = float(row["O"])
        prev_c = float(row["Prev_C"])
        day_c = float(row["Day_C"])
        net_c = float(row["C"])
        vol_x = float(row["VolX"])
        w_ema10 = float(row["W_EMA10"])
        high_52w = float(row.get("High52W", ltp))

        df_5m = processed_charts.get(ft, pd.DataFrame())
        intra_ema10 = (
            float(df_5m["EMA_10"].iloc[-1])
            if (not df_5m.empty and "EMA_10" in df_5m.columns)
            else vwap
        )
        vwap_live = (
            float(df_5m["VWAP"].iloc[-1])
            if (not df_5m.empty and "VWAP" in df_5m.columns)
            else vwap
        )

        is_bull_price = (
            (ltp > vwap_live)
            and (ltp >= intra_ema10)
            and (day_c >= min_move_pct or net_c >= 1.2)
        )
        is_bear_price = (
            (ltp < vwap_live)
            and (ltp <= intra_ema10)
            and (day_c <= -min_move_pct or net_c <= -1.2)
        )

        if not (is_bull_price or is_bear_price):
            continue

        cat_tag = n_info["tag"]
        bias = n_info["bias"]
        raw_en_title = n_info.get("title_en", n_info["title"])

        if bias == 0:
            if vol_x >= 1.8 and abs(day_c) >= 1.5:
                cat_tag = "📰High-Vol Breakout🔥" if is_bull_price else "📰High-Vol Breakdown🩸"
            elif cat_filter != "ALL":
                continue

        if is_bull_price:
            side_icon = "📰 News BUY"
            if bias == -1:
                cat_tag = "📰Short-Squeeze🔥"
        else:
            side_icon = "📰 News SELL"
            if bias == 1 and open_p > prev_c * 1.005:
                cat_tag = "📰Sell-The-News🩸"

        is_most_imp = _is_most_important_catalyst(
            cat_tag, raw_en_title, vol_x, day_c, age_h_val, is_macro=False
        )
        is_qres = "Q-Results" in cat_tag or any(
            w in raw_en_title.lower()
            for w in ("q1", "q2", "q3", "q4", "profit", "revenue", "ebitda", "results")
        )

        if cat_filter == "IMP" and not is_most_imp:
            continue
        if cat_filter == "QRES" and not is_qres:
            continue
        if cat_filter == "ORDER" and not any(
            k in cat_tag for k in ("Order-Win", "Regulatory", "Expansion", "Corp-Action", "Institutional")
        ):
            continue

        seen_stocks.add(stk_name)

        score = 58
        if vol_x >= 2.5:
            score += 18
        elif vol_x >= 1.8:
            score += 13
        elif vol_x >= 1.3:
            score += 8

        if abs(day_c) >= 2.5:
            score += 12
        elif abs(day_c) >= 1.5:
            score += 8
        else:
            score += 4

        if age_h_val <= 3.0:
            score += 9
        elif age_h_val <= 12.0:
            score += 5

        if is_bull_price and bias == 1:
            score += 8
        elif is_bear_price and bias == -1:
            score += 8

        final_prob = min(99, int(score))
        te_headline = n_info.get("title_te_full") or _translate_to_telugu(raw_en_title)
        te_details = (
            te_map.get(n_info["details_en"], "") if n_info.get("details_en") else ""
        )

        qres_html = ""
        if is_qres:
            qres_html = fetch_pro_qresults_summary(
                stk_name, raw_en_title, bias, day_c, vol_x
            )

        vwap_status = (
            f"VWAP (₹{vwap_live:.1f}) & 10-EMA (₹{intra_ema10:.1f}) పైన బుల్లిష్‌గా"
            if ltp >= vwap_live
            else f"VWAP (₹{vwap_live:.1f}) & 10-EMA (₹{intra_ema10:.1f}) కింద బేరిష్‌గా"
        )
        pb_52 = ((high_52w - ltp) / high_52w * 100.0) if high_52w > 0 else 0.0
        mkt_summary_te = (
            f"📊 చార్ట్ & టెక్నికల్ విశ్లేషణ: ప్రస్తుతం ₹{ltp:.2f} వద్ద"
            f" ({day_c:+.2f}%), సాధారణం కంటే {vol_x:.1f}x రెట్ల వాల్యూమ్‌తో"
            f" {vwap_status} ట్రేడ్ అవుతోంది (52W గరిష్టం ₹{high_52w:.1f} నుండి"
            f" {pb_52:.1f}% దూరం)."
        )

        row_copy = row.copy()
        row_copy["Strategy_Icon"] = side_icon
        row_copy["AI_Prob"] = final_prob
        row_copy["S"] = max(int(row_copy.get("S", 10)), int(final_prob // 3))
        row_copy["AlphaTag"] = (
            f"{'🔥IMP ' if is_most_imp else ''}{cat_tag} ({age_h_val:.1f}h)"
        )
        row_copy["News_Headline"] = te_headline
        row_copy["News_Cat"] = cat_tag
        row_copy["News_Age"] = f"{age_h_val:.1f}గం. క్రితం"
        row_copy["News_Link"] = n_info["link"]
        row_copy["_imp_rank"] = 0 if (is_most_imp and cat_filter != "LATEST") else 1
        row_copy["_age_h"] = age_h_val
        matched_rows.append(row_copy)

        sig_txt = "🟢 BUY" if is_bull_price else "🔴 SELL"
        inline_chart_html = _build_inline_mini_chart_html(
            stk_name, row, df_5m, cat_tag
        )

        feed_records.append({
            "Stock": stk_name,
            "Inline_Chart": inline_chart_html,
            "Signal": sig_txt,
            "Catalyst": cat_tag,
            "Is_Imp": is_most_imp,
            "Is_QRes": is_qres,
            "LTP": ltp,
            "Day%": day_c,
            "VolX": vol_x,
            "Score": final_prob,
            "Age_H": age_h_val,
            "Age": f"{age_h_val:.1f}గం. క్రితం",
            "Headline_TE": te_headline,
            "Details_TE": te_details,
            "QRes_HTML": qres_html,
            "Mkt_TE": mkt_summary_te,
            "Headline_EN": _clean_en_headline(raw_en_title),
            "Link": n_info["link"],
        })

        if is_most_imp:
            sig_col_hex = "#3fb950" if is_bull_price else "#ff5252"
            important_flash_list.append((
                age_h_val,
                f"🔥 <b style='color:#00BFFF;'>{stk_name}</b> <span"
                f" style='color:{sig_col_hex};font-weight:bold;'>({day_c:+.1f}%, Vol"
                f" {vol_x:.1f}x | {sig_txt})</span>: <b"
                f" style='color:#ffd700;'>{_html.escape(te_headline)}</b> <span"
                f" style='color:#79c0ff;font-size:12px;'>({age_h_val:.1f}గం. క్రితం)</span>"
            ))

    if important_flash_list:
        important_flash_list.sort(key=lambda x: x[0])
        _SS["latest_stock_flash_te"] = [x[1] for x in important_flash_list[:6]]

    if not matched_rows:
        return pd.DataFrame(), []

    df_out = (
        pd.DataFrame(matched_rows)
        .drop_duplicates(subset=["T"], keep="first")
        .sort_values(by=["_imp_rank", "_age_h"], ascending=[True, True])
        .drop(columns=["_imp_rank", "_age_h"], errors="ignore")
    )
    if cat_filter == "LATEST":
        feed_records.sort(key=lambda x: x.get("Age_H", 99.0))
    else:
        feed_records.sort(key=lambda x: (0 if x.get("Is_Imp") else 1, x.get("Age_H", 99.0)))
    return df_out, feed_records


def _build_strategy_news_feed_records(df_strat_stocks, processed_charts):
    """
    Takes the exact stocks from the user's currently selected strategy (`df_stocks_display`)
    and builds the split view (Left 30% Mini-Chart + Right 70% News, Pro Q-Results, SL/Targets & Technicals).
    """
    if df_strat_stocks is None or df_strat_stocks.empty:
        return []

    df_sub = df_strat_stocks.drop_duplicates(subset=["T"], keep="first").head(36).copy()
    fts = df_sub["Fetch_T"].tolist()

    missing_5m = [
        ft for ft in fts if ft not in processed_charts or processed_charts[ft].empty
    ]
    if missing_5m:
        extra_5m = fetch_cached_5m_data(missing_5m)
        if not extra_5m.empty:
            for m_ft in missing_5m:
                try:
                    raw_m = (
                        extra_5m[m_ft]
                        if isinstance(extra_5m.columns, pd.MultiIndex)
                        else extra_5m
                    )
                    processed_charts[m_ft] = process_5m_data(raw_m)
                except Exception:
                    pass

    # Search up to 7 days of news for the selected strategy stocks so any recent catalyst appears
    news_map = fetch_live_stock_news_batch(tuple(fts), max_age_hours=168)
    texts_to_tr = []
    for v in news_map.values():
        if v and v.get("details_en"):
            texts_to_tr.append(v["details_en"])
    te_map = _translate_batch_to_telugu(texts_to_tr)

    records = []
    for _, row in df_sub.iterrows():
        stk_name = str(row["T"]).strip()
        ft = row["Fetch_T"]
        ltp = float(row["P"])
        day_c = float(row.get("Day_C", 0.0))
        vol_x = float(row.get("VolX", 1.0))
        vwap = float(row.get("VWAP", ltp))
        high_52w = float(row.get("High52W", ltp))
        strat_icon = str(row.get("Strategy_Icon", "") or "").strip()
        alpha_tag = str(row.get("AlphaTag", "") or "").strip()
        score_val = int(row.get("AI_Prob", row.get("S", 75)))

        df_5m = processed_charts.get(ft, pd.DataFrame())
        intra_ema10 = (
            float(df_5m["EMA_10"].iloc[-1])
            if (not df_5m.empty and "EMA_10" in df_5m.columns)
            else vwap
        )
        vwap_live = (
            float(df_5m["VWAP"].iloc[-1])
            if (not df_5m.empty and "VWAP" in df_5m.columns)
            else vwap
        )

        is_sell = any(
            k in strat_icon
            for k in ("🔴", "SELL", "DOWN", "Stage 4", "🩸", "52WL")
        ) or (not strat_icon and day_c < 0)
        sig_txt = "🔴 SELL" if is_sell else "🟢 BUY"

        atr_val = float(row.get("ATR", ltp * 0.02))
        default_sl = (ltp + 1.5 * atr_val) if is_sell else (ltp - 1.5 * atr_val)
        default_t1 = (ltp - 1.5 * atr_val) if is_sell else (ltp + 1.5 * atr_val)
        default_t2 = (ltp - 3.0 * atr_val) if is_sell else (ltp + 3.0 * atr_val)
        sl_v = float(row.get("SL", default_sl))
        t1_v = float(row.get("T1", default_t1))
        t2_v = float(row.get("T2", default_t2))

        n_info = news_map.get(ft)
        if n_info:
            age_h_val = float(n_info.get("age_h", 12.0))
            age_str = (
                f"{age_h_val:.1f}గం. క్రితం"
                if age_h_val <= 24.0
                else f"{age_h_val / 24.0:.1f} రోజుల క్రితం"
            )
            cat_tag = f"{strat_icon} • {n_info['tag']}" if strat_icon else n_info["tag"]
            raw_en_title = n_info.get("title_en", n_info["title"])
            te_headline = n_info.get("title_te_full") or _translate_to_telugu(raw_en_title)
            te_details = (
                te_map.get(n_info["details_en"], "") if n_info.get("details_en") else ""
            )
            link_url = n_info["link"]
            bias = n_info.get("bias", 0)
            is_most_imp = _is_most_important_catalyst(
                n_info["tag"], raw_en_title, vol_x, day_c, age_h_val, is_macro=False
            )
        else:
            age_h_val = 99.0
            age_str = "Live Setup"
            cat_tag = strat_icon if strat_icon else "🎯 Strategy Setup"
            raw_en_title = f"{stk_name} Technical Breakout Setup ({cat_tag})"
            te_headline = (
                f"🎯 {stk_name} — సెలెక్ట్ చేసిన స్ట్రాటజీ ({cat_tag}) కండిషన్స్‌తో"
                f" లైవ్‌లో యాక్టివ్‌గా ఉంది (Vol: {vol_x:.1f}x)."
            )
            te_details = (
                f"ట్రేడింగ్ లెవెల్స్: 🛑 స్టాప్ లాస్ (SL): ₹{sl_v:.2f}  |  🎯 టార్గెట్ 1 (T1): ₹{t1_v:.2f}  |  🎯 టార్గెట్ 2 (T2): ₹{t2_v:.2f}"
                + (f"  |  సిగ్నల్ ట్యాగ్స్: {alpha_tag}" if alpha_tag else "")
            )
            link_url = f"https://www.google.com/search?q={stk_name}+share+news&tbm=nws"
            bias = -1 if is_sell else 1
            is_most_imp = (vol_x >= 2.5 and abs(day_c) >= 2.0)

        # Fetch Pro Q-Results Table for the strategy stock
        qres_html = fetch_pro_qresults_summary(
            stk_name, raw_en_title, bias, day_c, vol_x
        )

        vwap_status = (
            f"VWAP (₹{vwap_live:.1f}) & 10-EMA (₹{intra_ema10:.1f}) పైన బుల్లిష్‌గా"
            if ltp >= vwap_live
            else f"VWAP (₹{vwap_live:.1f}) & 10-EMA (₹{intra_ema10:.1f}) కింద బేరిష్‌గా"
        )
        pb_52 = ((high_52w - ltp) / high_52w * 100.0) if high_52w > 0 else 0.0
        mkt_summary_te = (
            f"📊 చార్ట్ & ట్రేడ్ లెవెల్స్: ప్రస్తుతం ₹{ltp:.2f} ({day_c:+.2f}%) వద్ద,"
            f" వాల్యూమ్ {vol_x:.1f}x తో {vwap_status} ట్రేడ్ అవుతోంది. "
            f"[🛑 SL: ₹{sl_v:.2f} | 🎯 T1: ₹{t1_v:.2f} | 🎯 T2: ₹{t2_v:.2f} | 52W High నుండి {pb_52:.1f}% దూరం]"
        )

        inline_chart_html = _build_inline_mini_chart_html(
            stk_name, row, df_5m, strat_icon or cat_tag
        )

        records.append({
            "Stock": stk_name,
            "Inline_Chart": inline_chart_html,
            "Signal": sig_txt,
            "Catalyst": cat_tag,
            "Is_Imp": is_most_imp,
            "LTP": ltp,
            "Day%": day_c,
            "VolX": vol_x,
            "Score": score_val,
            "Age_H": age_h_val,
            "Age": age_str,
            "Headline_TE": te_headline,
            "Details_TE": te_details,
            "QRes_HTML": qres_html,
            "Mkt_TE": mkt_summary_te,
            "Headline_EN": _clean_en_headline(raw_en_title),
            "Link": link_url,
        })

    return records


def render_news_catalyst_banner(feed_records, banner_title=None):
    """Renders Left 30% Default-Open Mini-Chart + Right 70% Full Telugu News, Q-Results & Technical Levels"""
    if not feed_records:
        return ""
    rows_html = ""
    seen = set()
    for r in feed_records:
        stk = r["Stock"]
        if stk in seen:
            continue
        seen.add(stk)

        imp_badge_html = (
            "<span class='pro-pill-imp'>🔥 MOST IMPORTANT</span>"
            if r.get("Is_Imp")
            else ""
        )
        pill_cls = "pro-pill-buy" if "BUY" in r["Signal"] else "pro-pill-sell"
        day_col = "#3fb950" if r["Day%"] >= 0 else "#f85149"
        safe_te = _html.escape(r.get("Headline_TE", ""))
        safe_dtl = _html.escape(r.get("Details_TE", ""))
        safe_mkt = _html.escape(r.get("Mkt_TE", ""))
        safe_en = _html.escape(r.get("Headline_EN", ""))
        qres_block = r.get("QRes_HTML", "")

        dtl_block = (
            f"<div class='pro-news-dtl'>🔹 <b>ముఖ్యాంశాలు:</b> {safe_dtl}</div>"
            if safe_dtl
            else ""
        )
        mkt_block = f"<div class='pro-news-mkt'>{safe_mkt}</div>"
        chart_box = r.get("Inline_Chart") or _build_inline_mini_chart_html(stk)

        rows_html += (
            f"<tr><td style='width:30%;'>{chart_box}</td><td style='width:70%;'"
            f" title='{safe_en}'><div class='pro-matter-box'><div><div"
            f" class='pro-meta-strip'>{imp_badge_html}<span class='{pill_cls}'>{r['Signal']}</span>"
            f"<span class='pro-cat-tag'>{r['Catalyst']}</span>"
            f"<span class='pro-meta-chip'>ధర: ₹{r['LTP']:,.2f} <span"
            f" style='color:{day_col};'>({r['Day%']:+.2f}%)</span></span>"
            "<span class='pro-meta-chip' style='color:#38bdf8;'>VOL:"
            f" {r['VolX']:.1f}x</span>"
            f"<span class='pro-meta-chip' style='color:#ffd700;'>Score: {r['Score']}</span>"
            f"<span class='pro-time-badge'>🕒 {r['Age']}</span></div><div class='pro-news-hl'>📰"
            f" {safe_te}</div>{qres_block}{dtl_block}{mkt_block}</div><div"
            f" style='margin-top:8px;text-align:right;'><a href='{r['Link']}'"
            " target='_blank'"
            " style='color:#58a6ff;font-size:12px;text-decoration:none;font-weight:700;'>🔗"
            " పూర్తి వార్త చదవండి ↗</a></div></div></td></tr>"
        )

    hdr_text = (
        banner_title
        or "📰 24h హై-ఇంపాక్ట్ స్టాక్ బ్రేకింగ్ న్యూస్ + వాల్యూమ్ + ప్రైస్ స్కానర్ (🔥 Most Important First • 🕒 24h Time-Wise Order)"
    )
    return (
        "<div class='pro-news-wrap'><div class='pro-news-hdr'"
        " style='background:linear-gradient(90deg, #0f2942 0%, #0d1117"
        f" 100%);border-left:4px solid #38bdf8;'><span>{hdr_text}</span><span"
        " style='font-size:12px;color:#79c0ff;background:#161b22;padding:2px"
        " 9px;border-radius:12px;border:1px solid"
        f" #30363d;'>{len(seen)} స్టాక్స్</span></div><table"
        " class='pro-news-table'><thead><tr><th style='width:30%;'>📈 లైవ్ మినీ"
        " చార్ట్ (5m INTRADAY + VWAP + EMA)</th><th style='width:70%;'>📢"
        " సిగ్నల్, Q-Results డేటా, ట్రేడ్ లెవెల్స్ & తెలుగు బ్రేకింగ్ న్యూస్"
        "</th></tr></thead><tbody>"
        + rows_html
        + "</tbody></table></div>"
    )


@st.cache_data(ttl=240, show_spinner=False)
def _fetch_market_news_raw():
    """Fetches High-Impact Corporate Q-Results/Orders, Indian Macro & Global Macro News across Full 24 Hours"""
    now_utc = datetime.now(ZoneInfo("UTC"))
    queries = {
        "india": (
            '("RBI" OR "SEBI" OR "FII" OR "inflation" OR "GDP" OR "GST collection"'
            ' OR "repo rate" OR "Nifty" OR "Sensex" OR "fiscal deficit") when:1d'
        ),
        "global": (
            '("US Fed" OR "Federal Reserve" OR "Wall Street" OR "Dow Jones" OR "Nasdaq"'
            ' OR "Brent crude" OR "OPEC" OR "US inflation" OR "tariff" OR "bond yield") when:1d'
        ),
        "stocks": (
            '("net profit" OR "Q1" OR "Q2" OR "Q3" OR "Q4" OR "bagged order"'
            ' OR "order win" OR "USFDA" OR "acquires" OR "dividend" OR "beats estimates") NSE when:1d'
        ),
    }
    out = {"india": [], "global": [], "stocks": []}

    def _pull_rss(key, q_str, limit_n=15):
        items_by_key = {}
        is_macro_feed = key in ("india", "global")
        try:
            q = urllib.parse.quote(q_str)
            url = (
                f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
            )
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4.0)
            if r.status_code == 200 and r.content:
                root = ET.fromstring(r.content)
                for it in root.findall("./channel/item"):
                    raw_title = (it.findtext("title") or "").strip()
                    clean_t = _clean_en_headline(raw_title)
                    if not _has_real_market_impact(clean_t, is_macro=is_macro_feed):
                        continue

                    tag, bias = _classify_headline(clean_t, is_macro=is_macro_feed)
                    stk_sym, is_nse = _extract_stock_from_headline(clean_t)

                    if key == "stocks" and (not is_nse or bias == 0):
                        continue
                    if key == "india" and not is_nse:
                        stk_sym = "🇮🇳 INDIA MKT"
                    elif key == "global" and not is_nse:
                        stk_sym = "🌍 GLOBAL"

                    desc_clean = _strip_html_tags(
                        it.findtext("description") or "", clean_t
                    )
                    link = (it.findtext("link") or "").strip()
                    pub_s = (it.findtext("pubDate") or "").strip()
                    age_h = 4.0
                    if pub_s:
                        try:
                            dt_p = parsedate_to_datetime(pub_s)
                            if dt_p.tzinfo is None:
                                dt_p = dt_p.replace(tzinfo=ZoneInfo("UTC"))
                            age_h = max(
                                0.1,
                                (now_utc - dt_p.astimezone(ZoneInfo("UTC"))).total_seconds()
                                / 3600.0,
                            )
                        except Exception:
                            age_h = 4.0

                    if age_h <= 24.0:
                        is_imp_m = _is_most_important_catalyst(
                            tag, clean_t, vol_x=2.5, day_c=2.5, age_h=age_h, is_macro=is_macro_feed
                        )
                        dedup_k = (
                            stk_sym
                            if (
                                is_nse
                                or stk_sym not in ("NSE CORP", "🇮🇳 INDIA MKT", "🌍 GLOBAL")
                            )
                            else clean_t[:35].lower()
                        )
                        if dedup_k in items_by_key:
                            existing = items_by_key[dedup_k]
                            if age_h < existing["age_h"]:
                                existing["age_h"] = round(age_h, 1)
                            if (
                                clean_t.lower()[:30] not in existing["title_en"].lower()
                                and clean_t not in existing["extra_en"]
                            ):
                                existing["extra_en"].append(clean_t)
                            continue

                        extra_pts = []
                        if desc_clean:
                            for seg in desc_clean.split(" • "):
                                if seg.lower()[:30] not in clean_t.lower():
                                    extra_pts.append(seg)

                        items_by_key[dedup_k] = {
                            "stock": stk_sym,
                            "is_nse": is_nse,
                            "title_en": clean_t,
                            "extra_en": extra_pts[:2],
                            "link": link,
                            "age_h": round(age_h, 1),
                            "tag": tag,
                            "bias": bias,
                            "is_imp": is_imp_m,
                        }
                        if len(items_by_key) >= limit_n:
                            break
        except Exception:
            pass
        items_list = list(items_by_key.values())
        items_list.sort(key=lambda x: (0 if x.get("is_imp") else 1, x["age_h"]))
        return key, items_list

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(_pull_rss, k, q, 15) for k, q in queries.items()]
        for f in concurrent.futures.as_completed(futs):
            try:
                k, lst = f.result()
                out[k] = lst
            except Exception:
                pass

    all_en = []
    for k in ("india", "global", "stocks"):
        for it in out[k]:
            all_en.append(it["title_en"])
            if it.get("extra_en"):
                it["details_en_str"] = ". ".join(it["extra_en"])
                all_en.append(it["details_en_str"])
            else:
                it["details_en_str"] = ""

    te_dict = _translate_batch_to_telugu(all_en)
    for k in ("india", "global", "stocks"):
        for it in out[k]:
            it["title"] = te_dict.get(it["title_en"], it["title_en"])
            it["details_te"] = (
                te_dict.get(it["details_en_str"], "")
                if it.get("details_en_str")
                else ""
            )
    return out


def fetch_indian_and_global_market_news():
    """Builds Top Scrolling Flash Ticker ONLY from Most Important Stock & Macro News (24h)"""
    base_news = _fetch_market_news_raw()
    out = dict(base_news)

    flash_parts = []
    stock_flashes = _SS.get("latest_stock_flash_te", [])
    if stock_flashes:
        flash_parts.extend(stock_flashes[:5])

    macro_pool = [
        it for it in (out.get("india", []) + out.get("global", []))
        if it.get("is_imp") and it.get("age_h", 99) <= 24.0
    ]
    macro_pool.sort(key=lambda x: x["age_h"])
    for mp in macro_pool[:4]:
        stk_lbl = (
            f" [{mp.get('stock', '')}]"
            if mp.get("stock")
            and mp.get("stock") not in ("🇮🇳 INDIA MKT", "🌍 GLOBAL", "NSE CORP")
            else ""
        )
        if mp["bias"] > 0:
            imp_badge = f"<span style='color:#3fb950;font-weight:bold;'>[🔥 IMPORTANT • 🟢 పాజిటివ్{stk_lbl}]</span>"
        elif mp["bias"] < 0:
            imp_badge = f"<span style='color:#ff5252;font-weight:bold;'>[🔥 IMPORTANT • 🔴 నెగటివ్{stk_lbl}]</span>"
        else:
            imp_badge = f"<span style='color:#00BFFF;font-weight:bold;'>[🔥 IMPORTANT • 🇮🇳 మార్కెట్{stk_lbl}]</span>"
        te_txt = _html.escape(mp["title"])
        flash_parts.append(
            f"{imp_badge} <b style='color:#ffd700;'>{te_txt}</b> <span"
            f" style='color:#79c0ff;font-size:12px;'>({mp['age_h']:.1f}గం."
            " క్రితం)</span>"
        )

    out["flash_ticker"] = " &nbsp;&nbsp;&nbsp;✦&nbsp;&nbsp;&nbsp; ".join(
        flash_parts
    )
    return out


def render_market_news_hub(df_all_stocks, processed_charts, df_strategy_stocks=None, watchlist_mode_name=""):
    """
    Multi-Purpose News & Strategy Hub:
      • Default '🎯 Strategy' Option (index=5): Displays the exact stocks from the user's currently selected strategy
        with Left 30% Mini-Chart + Right 70% Full News, Q-Results & Technical Levels!
      • Other 5 Options: Scans the full market across 24 Hours (All High-Impact, Most Important, Q-Results, Latest Time-Wise, Order Wins).
    """
    # Automatically grab `df_stocks_display` & `watchlist_mode` from caller (`render_live_ui`) if not passed explicitly
    if df_strategy_stocks is None:
        try:
            caller_locals = _inspect.currentframe().f_back.f_locals
            df_strategy_stocks = caller_locals.get("df_stocks_display")
            if not watchlist_mode_name:
                watchlist_mode_name = str(caller_locals.get("watchlist_mode", ""))
        except Exception:
            df_strategy_stocks = df_all_stocks

    filter_options = [
        "🔥 All High-Impact (24h)",
        "🚨 Most Important Only (24h)",
        "📊 Q-Results Only (24h)",
        "⚡ Latest Time-Wise (24h)",
        "📰 Order Wins & Approvals (24h)",
        "🎯 Strategy",
    ]
    news_cat_pick = st.radio(
        "🔎 24-Hour News & Strategy Filter:",
        filter_options,
        index=5,  # 🎯 Strategy is Default!
        horizontal=True,
        key="pro_news_cat_filter_v7",
    )

    # =========================================================
    # 🎯 MODE 1: STRATEGY VIEW (DEFAULT) — Shows Selected Strategy Stocks with Charts + Full Details
    # =========================================================
    if news_cat_pick == "🎯 Strategy":
        strat_records = _build_strategy_news_feed_records(
            df_strategy_stocks, processed_charts
        )
        if strat_records:
            buy_recs = [r for r in strat_records if "BUY" in r["Signal"]]
            sell_recs = [r for r in strat_records if "SELL" in r["Signal"]]
            wl_lbl = f" ({watchlist_mode_name})" if watchlist_mode_name else ""

            if buy_recs:
                st.markdown(
                    render_news_catalyst_banner(
                        buy_recs,
                        banner_title=f"🟢 POSITIVE / BUY — 🎯 సెలెక్ట్ చేసిన స్ట్రాటజీ స్టాక్స్ పూర్తి విశ్లేషణ{wl_lbl}",
                    ),
                    unsafe_allow_html=True,
                )
            if sell_recs:
                st.markdown(
                    render_news_catalyst_banner(
                        sell_recs,
                        banner_title=f"🔴 NEGATIVE / SELL — 🎯 సెలెక్ట్ చేసిన స్ట్రాటజీ స్టాక్స్ పూర్తి విశ్లేషణ{wl_lbl}",
                    ),
                    unsafe_allow_html=True,
                )
        else:
            st.info(
                "ℹ️ ప్రస్తుతం మీరు సెలెక్ట్ చేసిన స్ట్రాటజీలో స్టాక్స్ ఏవీ లేవు. కుడివైపు మరో స్ట్రాటజీ టిక్ చేయండి లేదా పైన ఉన్న 24h న్యూస్ ఫిల్టర్లను క్లిక్ చేయండి."
            )
        return

    # =========================================================
    # 🌍 MODE 2: 24-HOUR MARKET-WIDE NEWS FILTERS (5 OPTIONS)
    # =========================================================
    cat_code = "ALL"
    if "Most Important" in news_cat_pick:
        cat_code = "IMP"
    elif "Q-Results" in news_cat_pick:
        cat_code = "QRES"
    elif "Latest Time-Wise" in news_cat_pick:
        cat_code = "LATEST"
    elif "Order Wins" in news_cat_pick:
        cat_code = "ORDER"

    m_news = fetch_indian_and_global_market_news()
    _, stock_feed = run_news_vol_price_strategy(
        df_all_stocks,
        processed_charts,
        min_volx=1.3,
        min_move_pct=0.75,
        cat_filter=cat_code,
    )

    stk_lu = {}
    if df_all_stocks is not None and not df_all_stocks.empty:
        stk_lu = (
            df_all_stocks.drop_duplicates(subset=["T"])
            .set_index("T")
            .to_dict("index")
        )

    if stock_feed:
        st.markdown(render_news_catalyst_banner(stock_feed), unsafe_allow_html=True)

    raw_stocks_list = m_news.get("stocks", [])
    filtered_corp_stocks = []
    for it in raw_stocks_list:
        s_n = str(it.get("stock", "")).strip()
        s_d = stk_lu.get(s_n)
        s_vx = float(s_d.get("VolX", 1.5)) if s_d is not None else 1.5
        s_dc = float(s_d.get("Day_C", 1.0)) if s_d is not None else 1.0

        if s_d is not None and s_vx < 1.2 and abs(s_dc) < 0.75:
            continue

        age_v = float(it.get("age_h", 12.0))
        if age_v > 24.0:
            continue
        tag_v = str(it.get("tag", ""))
        is_imp_v = _is_most_important_catalyst(
            tag_v, it.get("title_en", ""), s_vx, s_dc, age_v, is_macro=False
        )
        is_q_v = "Q-Results" in tag_v or any(
            w in str(it.get("title_en", "")).lower()
            for w in ("q1", "q2", "q3", "q4", "profit", "revenue", "ebitda", "results")
        )
        if cat_code == "IMP" and not is_imp_v:
            continue
        if cat_code == "QRES" and not is_q_v:
            continue
        if cat_code == "ORDER" and not any(
            k in tag_v for k in ("Order-Win", "Regulatory", "Expansion", "Corp-Action", "Institutional")
        ):
            continue

        it_copy = dict(it)
        it_copy["is_imp"] = is_imp_v
        filtered_corp_stocks.append(it_copy)

    if cat_code == "LATEST":
        filtered_corp_stocks.sort(key=lambda x: x.get("age_h", 99.0))
    else:
        filtered_corp_stocks.sort(
            key=lambda x: (0 if x.get("is_imp") else 1, x.get("age_h", 99.0))
        )

    q_nse_fts = [
        f"{it['stock']}.NS"
        for it in filtered_corp_stocks
        if f"{it['stock']}.NS" not in processed_charts
    ]
    if q_nse_fts:
        extra_q_5m = fetch_cached_5m_data(q_nse_fts)
        if not extra_q_5m.empty:
            for q_ft in q_nse_fts:
                try:
                    raw_q = (
                        extra_q_5m[q_ft]
                        if isinstance(extra_q_5m.columns, pd.MultiIndex)
                        else extra_q_5m
                    )
                    processed_charts[q_ft] = process_5m_data(raw_q)
                except Exception:
                    pass

    def _build_pro_news_table(
        items, box_title, accent_col, hdr_grad, with_mini_chart=True
    ):
        if not items:
            return ""
        rows = ""
        seen_keys = set()
        for it in items:
            stk_name = str(it.get("stock", "MARKET")).strip()
            t_en_raw = str(it.get("title_en", ""))
            dedup_id = (
                stk_name
                if (
                    stk_name not in ("NSE CORP", "🇮🇳 INDIA MKT", "🌍 GLOBAL", "MARKET")
                )
                else t_en_raw[:40].lower()
            )
            if dedup_id in seen_keys:
                continue
            seen_keys.add(dedup_id)

            imp_Top_pill = (
                "<span class='pro-pill-imp'>🔥 MOST IMPORTANT</span> "
                if it.get("is_imp")
                else ""
            )
            if it["bias"] > 0:
                imp_pill = "<span class='pro-pill-buy'>🟢 పాజిటివ్ ఇంపాక్ట్ (Bullish)</span>"
            elif it["bias"] < 0:
                imp_pill = "<span class='pro-pill-sell'>🔴 నెగటివ్ ఇంపాక్ట్ (Bearish)</span>"
            else:
                imp_pill = "<span class='pro-pill-neut'>🟡 మార్కెట్ ఇంపాక్ట్</span>"

            t_te = _html.escape(it.get("title", ""))
            dtl_te = _html.escape(it.get("details_te", ""))
            t_en = _html.escape(t_en_raw)

            s_d = stk_lu.get(stk_name)
            df_5m_stk = processed_charts.get(f"{stk_name}.NS", pd.DataFrame())
            has_chart = (it.get("is_nse") or s_d is not None) and (
                not df_5m_stk.empty
            )

            price_chip = ""
            mkt_ctx_html = ""
            s_dc, s_vx = 0.0, 1.0
            if s_d is not None:
                s_p, s_dc, s_vx = (
                    float(s_d["P"]),
                    float(s_d["Day_C"]),
                    float(s_d["VolX"]),
                )
                s_vw = float(s_d.get("VWAP", s_p))
                s_h52 = float(s_d.get("High52W", s_p))
                dc_col = "#3fb950" if s_dc >= 0 else "#f85149"
                vw_txt = "VWAP పైన బుల్లిష్‌గా" if s_p >= s_vw else "VWAP కింద బేరిష్‌గా"
                price_chip = (
                    f"<span class='pro-meta-chip'>₹{s_p:,.2f} <span"
                    f" style='color:{dc_col};'>({s_dc:+.2f}%)</span> | Vol:"
                    f" {s_vx:.1f}x</span>"
                )
                mkt_ctx_html = (
                    f"<div class='pro-news-mkt'>📊 <b>{stk_name}</b> లైవ్ టెక్నికల్ రియాక్షన్:"
                    f" ప్రస్తుతం ₹{s_p:,.2f} ({s_dc:+.2f}%) వద్ద, వాల్యూమ్"
                    f" <b>{s_vx:.1f}x</b> తో {vw_txt} (VWAP: ₹{s_vw:.1f}, 52W High:"
                    f" ₹{s_h52:.1f}) ట్రేడ్ అవుతోంది.</div>"
                )

            qres_html = ""
            if with_mini_chart and (it.get("is_nse") or s_d is not None):
                if "Q-Results" in str(it.get("tag", "")) or any(w in t_en_raw.lower() for w in ("q1", "q2", "q3", "q4", "profit", "revenue", "ebitda", "results", "quarter")):
                    qres_html = fetch_pro_qresults_summary(stk_name, t_en_raw, it["bias"], s_dc, s_vx)

            dtl_html = (
                f"<div class='pro-news-dtl'>🔹 <b>ముఖ్యాంశాలు:</b> {dtl_te}</div>"
                if (dtl_te and dtl_te[:25] not in t_te)
                else ""
            )

            if with_mini_chart:
                if has_chart or it.get("is_nse") or s_d is not None:
                    left_cell = _build_inline_mini_chart_html(
                        stk_name, s_d, df_5m_stk, it.get("tag", "")
                    )
                else:
                    left_cell = (
                        "<div class='mc-inline-card'"
                        " style='min-height:185px;display:flex;flex-direction:column;justify-content:center;align-items:center;'>"
                        "<span class='pro-stk-badge'"
                        f" style='color:#e6edf3 !important;'>{_html.escape(stk_name)}</span>"
                        "<span style='color:#8b949e;font-size:11px;margin-top:6px;'>కార్పొరేట్"
                        " ప్రకటన</span></div>"
                    )
                rows += (
                    f"<tr><td style='width:30%;'>{left_cell}</td><td style='width:70%;'"
                    f" title='{t_en}'><div class='pro-matter-box'><div><div"
                    " class='pro-meta-strip'><span"
                    f" class='pro-stk-badge'>{_html.escape(stk_name)}</span>{imp_Top_pill}{imp_pill}<span"
                    f" class='pro-cat-tag'>{it.get('tag', '')}</span>{price_chip}"
                    f"<span class='pro-time-badge'>🕒 {it['age_h']}గం. క్రితం</span></div><div class='pro-news-hl'>📰"
                    f" {t_te}</div>{qres_html}{dtl_html}{mkt_ctx_html}</div><div"
                    f" style='margin-top:8px;text-align:right;'><a href='{it['link']}'"
                    " target='_blank'"
                    " style='color:#58a6ff;font-size:12px;text-decoration:none;font-weight:700;'>🔗"
                    f" పూర్తి వార్త లింక్ ({t_en[:60]}...) ↗</a></div></div></td></tr>"
                )
            else:
                rows += (
                    "<tr><td style='width:20%;'>"
                    f"{imp_Top_pill}{imp_pill}<br><span class='pro-cat-tag'"
                    f" style='margin-top:6px;'>{it.get('tag', '')}</span>"
                    "<div style='color:#79c0ff;font-weight:bold;font-size:11.5px;margin-top:6px;'>🕒"
                    f" {it['age_h']}గం. క్రితం</div>"
                    "</td>"
                    f"<td style='width:80%;' title='{t_en}'>"
                    f"<div class='pro-news-hl'>📰 {t_te}</div>"
                    f"{dtl_html}{mkt_ctx_html}"
                    f"<div style='margin-top:5px;'><a href='{it['link']}'"
                    " target='_blank'"
                    " style='color:#58a6ff;font-size:11.5px;text-decoration:none;font-weight:600;'>🔗"
                    f" పూర్తి వార్త లింక్ ({t_en[:65]}...) ↗</a></div>"
                    "</td></tr>"
                )

        if with_mini_chart:
            thead_html = (
                "<tr><th style='width:30%;'>📈 లైవ్ మినీ చార్ట్ (5m INTRADAY)</th><th"
                " style='width:70%;'>📢 కంపెనీ క్వార్టర్లీ రిజల్ట్స్ (🔥 Most Important First • 🕒 24h Time-Wise Order)</th></tr>"
            )
        else:
            thead_html = (
                "<tr><th style='width:20%;'>ఇంపార్టెన్స్ & సమయం</th><th"
                " style='width:80%;'>📢 హై-ఇంపాక్ట్ వార్త & మార్కెట్ విశ్లేషణ"
                " (🔥 Most Important First • 🕒 24h Time-Wise)</th></tr>"
            )

        return (
            "<div class='pro-news-wrap'><div class='pro-news-hdr'"
            f" style='background:{hdr_grad};border-left:4px solid"
            f" {accent_col};'><span>{box_title}</span><span"
            " style='font-size:12px;color:#c9d1d9;background:#161b22;padding:2px"
            " 9px;border-radius:12px;border:1px solid"
            f" #30363d;'>{len(seen_keys)} వార్తలు</span></div><table"
            f" class='pro-news-table'><thead>{thead_html}</thead><tbody>{rows}</tbody></table></div>"
        )

    if filtered_corp_stocks:
        st.markdown(
            _build_pro_news_table(
                filtered_corp_stocks,
                "🏢 24h క్వార్టర్లీ రిజల్ట్స్ (Q-Results) & ముఖ్య కార్పొరేట్ ప్రకటనలు (🔥 Most Important First • 🕒 Time-Wise)",
                "#2ea043",
                "linear-gradient(90deg, #112a1c 0%, #0d1117 100%)",
                with_mini_chart=True,
            ),
            unsafe_allow_html=True,
        )

    if cat_code in ("ALL", "IMP", "LATEST"):
        india_list = list(m_news.get("india", []))
        global_list = list(m_news.get("global", []))
        if cat_code == "IMP":
            india_list = [x for x in india_list if x.get("is_imp")]
            global_list = [x for x in global_list if x.get("is_imp")]
        elif cat_code == "LATEST":
            india_list.sort(key=lambda x: x.get("age_h", 99.0))
            global_list.sort(key=lambda x: x.get("age_h", 99.0))

        if india_list:
            st.markdown(
                _build_pro_news_table(
                    india_list,
                    "🇮🇳 ఇండియన్ స్టాక్ మార్కెట్‌పై ప్రభావం చూపే ముఖ్య వార్తలు (24h • 🔥 Most Important First • 🕒 Time-Wise)",
                    "#38bdf8",
                    "linear-gradient(90deg, #0f2942 0%, #0d1117 100%)",
                    with_mini_chart=False,
                ),
                unsafe_allow_html=True,
            )

        if global_list:
            st.markdown(
                _build_pro_news_table(
                    global_list,
                    "🌍 గ్లోబల్ మార్కెట్స్‌పై ప్రభావం చూపే వార్తలు (24h • 🔥 Most Important First • 🕒 Time-Wise)",
                    "#a371f7",
                    "linear-gradient(90deg, #27143a 0%, #0d1117 100%)",
                    with_mini_chart=False,
                ),
                unsafe_allow_html=True,
            )


@st.cache_data(ttl=600, show_spinner=False)
def fetch_portfolio_news_and_results(port_syms_tuple):
    now_utc = datetime.now(ZoneInfo("UTC"))

    def _fetch_port_one(sym):
        clean_s = str(sym).replace(".NS", "").strip()
        items = []
        try:
            q = urllib.parse.quote(
                f'"{clean_s}" (results OR profit OR quarter OR Q1 OR Q2 OR Q3 OR Q4'
                " OR dividend OR order OR upgrade OR downgrade OR target OR usfda) when:14d"
            )
            url = (
                f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
            )
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4.0)
            if r.status_code == 200 and r.content:
                root = ET.fromstring(r.content)
                for it in root.findall("./channel/item")[:8]:
                    raw_t = (it.findtext("title") or "").strip()
                    title = _clean_en_headline(raw_t)
                    if not _has_real_market_impact(title, is_macro=False):
                        continue
                    desc_c = _strip_html_tags(it.findtext("description") or "", title)
                    link = (it.findtext("link") or "").strip()
                    pub_s = (it.findtext("pubDate") or "").strip()
                    age_d = 2.0
                    if pub_s:
                        try:
                            dt_p = parsedate_to_datetime(pub_s)
                            if dt_p.tzinfo is None:
                                dt_p = dt_p.replace(tzinfo=ZoneInfo("UTC"))
                            age_d = max(
                                0.05,
                                (now_utc - dt_p.astimezone(ZoneInfo("UTC"))).total_seconds()
                                / 86400.0,
                            )
                        except Exception:
                            age_d = 2.0
                    tag, bias = _classify_headline(title, is_macro=False)
                    if bias == 0:
                        continue
                    is_res = any(
                        w in title.lower()
                        for w in (
                            "q1", "q2", "q3", "q4", "quarter", "net profit",
                            "revenue", "ebitda", "fy26", "fy27", "results",
                        )
                    )
                    items.append((
                        0 if is_res else 1,
                        age_d,
                        title,
                        desc_c,
                        link,
                        tag,
                        bias,
                        is_res,
                    ))
        except Exception:
            pass

        if not items:
            return clean_s, None
        items.sort(key=lambda x: (x[0], x[1]))
        _, best_age_d, best_t, best_desc, best_l, best_tag, best_bias, is_res = (
            items[0]
        )

        extra_pts = []
        if best_desc:
            extra_pts.append(best_desc)
        for _, _, t_other, _, _, _, _, _ in items[1:3]:
            if t_other.lower()[:30] not in best_t.lower() and t_other not in extra_pts:
                extra_pts.append(t_other)
        full_dtl_en = ". ".join(extra_pts[:2]).strip()

        age_str = (
            f"{best_age_d * 24:.1f}గం. క్రితం"
            if best_age_d < 1.0
            else f"{best_age_d:.0f} రోజుల క్రితం"
        )
        return clean_s, {
            "title_en": best_t,
            "title": _translate_to_telugu(best_t),
            "details_te": _translate_to_telugu(full_dtl_en) if full_dtl_en else "",
            "link": best_l,
            "age": age_str,
            "age_d": best_age_d,
            "tag": best_tag,
            "bias": best_bias,
            "is_result": is_res,
        }

    out = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(_fetch_port_one, s) for s in port_syms_tuple]
        for f in concurrent.futures.as_completed(futs):
            try:
                k, v = f.result()
                if v:
                    out[k] = v
            except Exception:
                pass
    return out


def render_portfolio_news_and_results_table(df_port, df_stocks, weekly_trends):
    """Renders Default-Open Mini-Chart on Left (29%) + Pro Q-Results & Impact News (55%) + Hold/Sell Advice (16%)"""
    if df_port is None or df_port.empty:
        return ""
    stock_lookup = (
        df_stocks.drop_duplicates(subset=["T"], keep="first")
        .set_index("T")
        .to_dict("index")
    )
    port_syms = tuple(
        sorted(
            list(
                set(
                    str(r["Symbol"]).upper().strip()
                    for _, r in df_port.iterrows()
                    if str(r.get("Symbol", "")).strip()
                )
            )
        )
    )
    if not port_syms:
        return ""

    store_5m = _SS.get("5m_store", {})
    missing_port_5m = [
        f"{s}.NS"
        for s in port_syms
        if f"{s}.NS" not in store_5m or store_5m[f"{s}.NS"].empty
    ]
    if missing_port_5m:
        fetch_cached_5m_data(missing_port_5m)

    p_news_map = fetch_portfolio_news_and_results(port_syms)
    seen_port_syms = set()
    port_items = []

    for _, row in df_port.iterrows():
        sym = str(row["Symbol"]).upper().strip()
        if not sym or sym in seen_port_syms:
            continue
        seen_port_syms.add(sym)
        n_item = p_news_map.get(sym)
        age_sort = float(n_item["age_d"]) if n_item and "age_d" in n_item else 999.0
        has_imp = 0 if (n_item and n_item.get("is_result")) else (1 if n_item else 2)
        port_items.append((has_imp, age_sort, sym, row, n_item))

    port_items.sort(key=lambda x: (x[0], x[1]))
    rows_html = ""

    for _, _, sym, row, n_item in port_items:
        try:
            buy_p = float(row["Buy_Price"])
        except Exception:
            buy_p = 0.0
        try:
            qty_v = int(float(row.get("Quantity", 0)))
        except Exception:
            qty_v = 0

        live_d = stock_lookup.get(sym)
        if live_d is None:
            continue
        ltp = float(live_d["P"])
        day_c = float(live_d.get("Day_C", 0))
        vol_x = float(live_d.get("VolX", 1.0))
        vwap_v = float(live_d.get("VWAP", ltp))
        pnl_pct = ((ltp - buy_p) / buy_p * 100.0) if buy_p > 0 else 0.0
        pnl_rs = (ltp - buy_p) * qty_v
        wk_trend = weekly_trends.get(live_d["Fetch_T"], "Neutral")
        sma50 = float(live_d.get("SMA50", 0))
        sma200 = float(live_d.get("SMA200", 0))
        high_52w = float(live_d.get("High52W", ltp))

        cat_str = n_item["tag"] if n_item else "📊 Latest Q-Results"
        bias = n_item["bias"] if n_item else 0
        age_s = n_item["age"] if n_item else "Live"

        if bias > 0 or (bias == 0 and day_c >= 1.5):
            imp_pill = "<span class='pro-pill-buy'>🟢 పాజిటివ్ (+)</span>"
        elif bias < 0 or (bias == 0 and day_c <= -1.5):
            imp_pill = "<span class='pro-pill-sell'>🔴 నెగటివ్ (-)</span>"
        else:
            imp_pill = "<span class='pro-pill-neut'>🟡 న్యూట్రల్</span>"

        qres_html = fetch_pro_qresults_summary(
            sym, n_item["title_en"] if n_item else "", bias, day_c, vol_x
        )

        sma_status = (
            f"50-SMA (₹{sma50:.1f}) పైన బుల్లిష్ సపోర్ట్‌తో"
            if ltp >= sma50
            else f"50-SMA (₹{sma50:.1f}) కింద బలహీనంగా"
        )
        vw_status = (
            f"VWAP (₹{vwap_v:.1f}) పైన"
            if ltp >= vwap_v
            else f"VWAP (₹{vwap_v:.1f}) కింద"
        )
        tech_summary_te = (
            f"📊 <b>టెక్నికల్ & పోర్ట్‌ఫోలియో విశ్లేషణ:</b> మీ కొనుగోలు ధర"
            f" <b>₹{buy_p:.2f}</b> కాగా ప్రస్తుతం <b>₹{ltp:.2f}</b> వద్ద"
            f" ({vw_status}, {sma_status}) ట్రేడ్ అవుతోంది. వీక్లీ ట్రెండ్:"
            f" <b>{wk_trend}</b> | వాల్యూమ్: <b>{vol_x:.1f}x</b> | 52W High:"
            f" <b>₹{high_52w:.1f}</b>."
        )

        if n_item:
            t_te = _html.escape(n_item["title"])
            dtl_te = _html.escape(n_item.get("details_te", ""))
            dtl_sub = (
                f"<div class='pro-news-dtl'>🔹 <b>ముఖ్యాంశాలు:</b> {dtl_te}</div>"
                if (dtl_te and dtl_te[:25] not in t_te)
                else ""
            )
            news_body_html = (
                f"<div class='pro-news-hl'>📰 {t_te}</div>"
                f"{qres_html}{dtl_sub}"
                f"<div class='pro-news-mkt'>{tech_summary_te}</div>"
                f"<div style='margin-top:6px;text-align:right;'><a href='{n_item['link']}' target='_blank' style='color:#58a6ff;font-size:11.5px;text-decoration:none;font-weight:700;'>🔗 పూర్తి వార్త చదవండి ↗</a></div>"
            )
        else:
            news_body_html = (
                "<div class='pro-news-hl' style='color:#c9d1d9;'>📌 గత 14 రోజుల్లో"
                " కొత్త బ్రేకింగ్ వార్తలు లేవు — కంపెనీ క్వార్టర్లీ ఫలితాలు & టెక్నికల్ లెవెల్స్ కింద చూడండి:</div>"
                f"{qres_html}<div class='pro-news-mkt'>{tech_summary_te}</div>"
            )

        above_lt_ma = (ltp >= sma50) or (ltp >= sma200 and sma200 > 0)
        if bias < 0 and (wk_trend == "Bearish" or ltp < sma50):
            advice_txt = "🔴 SELL / EXIT<br><span style='font-size:11.5px;font-weight:normal;color:#ff7b72;'>(నెగటివ్ వార్త + వీక్ ట్రెండ్)</span>"
            adv_box_style = "background:rgba(248,81,73,0.12);border:1px solid #f85149;color:#ff7b72;"
        elif bias < 0 and pnl_pct > 8.0:
            advice_txt = "⚠️ 50% లాభం బుక్ చేయండి<br><span style='font-size:11.5px;font-weight:normal;color:#e3b341;'>(నెగటివ్ వార్త)</span>"
            adv_box_style = "background:rgba(210,153,34,0.12);border:1px solid #d29922;color:#ffd700;"
        elif pnl_pct <= -7.0 and wk_trend == "Bearish":
            advice_txt = "🔴 SELL / CUT LOSS<br><span style='font-size:11.5px;font-weight:normal;color:#ff7b72;'>(సపోర్ట్ కింద ఉంది)</span>"
            adv_box_style = "background:rgba(248,81,73,0.12);border:1px solid #f85149;color:#ff7b72;"
        elif bias > 0 and above_lt_ma:
            advice_txt = "🚀 STRONG HOLD / ADD<br><span style='font-size:11.5px;font-weight:normal;color:#7ee787;'>(పాజిటివ్ రిజల్ట్/వార్త)</span>"
            adv_box_style = "background:rgba(46,160,67,0.15);border:1px solid #2ea043;color:#3fb950;"
        elif pnl_pct >= 12.0 and wk_trend == "Bullish":
            advice_txt = "🟢 HOLD & TRAIL SL<br><span style='font-size:11.5px;font-weight:normal;color:#7ee787;'>(మంచి లాభంలో ఉంది)</span>"
            adv_box_style = "background:rgba(46,160,67,0.15);border:1px solid #2ea043;color:#3fb950;"
        elif above_lt_ma or wk_trend == "Bullish":
            advice_txt = "🟢 HOLD<br><span style='font-size:11.5px;font-weight:normal;color:#7ee787;'>(ట్రెండ్ బాగుంది)</span>"
            adv_box_style = "background:rgba(46,160,67,0.12);border:1px solid #2ea043;color:#3fb950;"
        else:
            advice_txt = "🟡 HOLD WITH SL<br><span style='font-size:11.5px;font-weight:normal;color:#e3b341;'>(స్టాప్ లాస్ తో వేచి చూడండి)</span>"
            adv_box_style = "background:rgba(210,153,34,0.12);border:1px solid #d29922;color:#ffd700;"

        d_col = "#3fb950" if day_c >= 0 else "#f85149"
        p_col = "#3fb950" if pnl_pct >= 0 else "#f85149"
        inline_chart = _build_inline_mini_chart_html(sym, live_d, None, cat_str)

        rows_html += (
            f"<tr><td style='width:29%;'>{inline_chart}</td><td"
            " style='width:55%;'><div class='pro-matter-box'><div><div"
            f" class='pro-meta-strip'>{imp_pill}<span"
            f" class='pro-cat-tag'>{cat_str}</span><span class='pro-meta-chip'>LTP:"
            f" ₹{ltp:,.1f} <span"
            f" style='color:{d_col};'>({day_c:+.1f}%)</span></span><span"
            f" class='pro-meta-chip'>Avg: ₹{buy_p:,.1f}</span><span"
            f" class='pro-meta-chip' style='color:{p_col};'>P&L: {pnl_pct:+.2f}%"
            f" (₹{pnl_rs:+,.0f})</span>"
            f"<span class='pro-time-badge'>🕒 {age_s}</span></div>{news_body_html}</div></div></td><td"
            " style='width:16%;'><div"
            f" style='{adv_box_style}padding:14px 10px;border-radius:8px;text-align:center;font-weight:800;font-size:13px;line-height:1.45;'>"
            f"{advice_txt}</div></td></tr>"
        )

    return (
        "<div class='pro-news-wrap'><div class='pro-news-hdr'"
        " style='background:linear-gradient(90deg, #0d47a1 0%, #0d1117"
        " 100%);border-left:4px solid #58a6ff;'><span>📰 నా పోర్ట్‌ఫోలియో స్టాక్స్"
        " — డిఫాల్ట్ మినీ చార్ట్, ప్రొఫెషనల్ Q-Results (Beat/Miss) & HOLD / SELL సలహా"
        " (Time-Wise Order)</span></div><table class='pro-news-table'><thead><tr><th"
        " style='width:29%;'>📈 లైవ్ మినీ చార్ట్ (5m INTRADAY)</th><th"
        " style='width:55%;'>📢 పోర్ట్‌ఫోలియో P&L, ప్రొఫెషనల్ Q-Results & టెక్నికల్"
        " విశ్లేషణ</th><th style='width:16%;text-align:center;'>💡"
        " HOLD / SELL సలహా</th></tr></thead><tbody>"
        + rows_html
        + "</tbody></table></div>"
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
                          "FEDERALBNK HDFCAMC HDFCBANK HDFCLIFE HUDCO ICICIBANK ICICIGI ICICILIFE IDFCFIRSTB IEX INDUSINDBK IRFC KOTAKBANK LICHSGFIN "
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
                  "DLF DMART GAIL GODREJCP HAVELLS HAL ICICIGI ICICILIFE INDHOTEL INDIGO IOC IRCTC IRFC JINDALSTEL JIOFIN LICI LODHA LTIM MARICO MAZDOCK "
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
    if df_subset is None or df_subset.empty:
        return "<div style='padding:20px; text-align:center; color:#8b949e; border: 1px dashed #30363d; border-radius:8px;'>No High Score Stocks (Score >= 10) found right now.</div>"
    
    df_valid = df_subset.copy()
    if df_valid.empty:
        return "<div style='padding:20px; text-align:center; color:#8b949e; border: 1px dashed #30363d; border-radius:8px;'>Prastutam Score >= 10 unna stocks levu.</div>"
    
    is_ai = 'AI_Prob' in df_valid.columns
    if is_ai:
        col_span = 12
        headers = '<th style="width:6%; color:#00BFFF;">🤖 AI</th><th style="width:6%;">SCORE</th>'
    else:
        col_span = 11
        headers = '<th style="width:7%;">SCORE</th>'

    if 'Strategy_Icon' in df_valid.columns and df_valid['Strategy_Icon'].astype(str).str.contains('🔴|SELL|DOWN|Stage 4|🩸|52WL', na=False).any():
        sell_mask = df_valid['Strategy_Icon'].astype(str).str.contains('🔴|SELL|DOWN|Stage 4|🩸|52WL', na=False)
    else:
        sell_mask = df_valid['Day_C'] < 0

    df_buy = df_valid[~sell_mask].reset_index(drop=True)
    df_sell = df_valid[sell_mask].reset_index(drop=True)

    def _build_hs_subtable(df_part, title_text, head_bg):
        if df_part.empty:
            return ""
        sub_html = f'<table class="term-table"><thead><tr><th colspan="{col_span}" class="term-head-high" style="background-color:{head_bg};">{title_text}</th></tr><tr style="background-color: #21262d;"><th style="width:4%;">RANK</th><th style="text-align:left; width:12%;">STOCK</th><th style="width:9%; color:#ffd700;">SECTOR</th><th style="width:8%;">LTP</th><th style="width:7%;">DAY%</th><th style="width:6%;">VOL</th><th style="width:17%;">STATUS</th><th style="width:10%; color:#f85149;">🛑 SL</th><th style="width:10%; color:#3fb950;">🎯 T1</th><th style="width:10%; color:#3fb950;">🎯 T2</th>{headers}</tr></thead><tbody>'
        for i, row in df_part.iterrows():
            bg_class = "row-dark" if i % 2 == 0 else "row-light"
            day_color = "text-green" if row['Day_C'] >= 0 else "text-red"
            strat_icon = str(row.get('Strategy_Icon', ''))
            base_status = generate_status(row)
            custom_status = f"{strat_icon} | {base_status}".strip() if strat_icon else base_status
            is_down = row['Day_C'] < 0
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
            sub_html += row_str
        sub_html += "</tbody></table>"
        return sub_html

    html_out = _build_hs_subtable(df_buy, "🟢 POSITIVE / BUY — HIGH SCORE RADAR (SCORE >= 10)", "#1e5f29")
    html_out += _build_hs_subtable(df_sell, "🔴 NEGATIVE / SELL — HIGH SCORE RADAR (SCORE >= 10)", "#b52524")
    return html_out

def render_levels_table(df_subset):
    if df_subset is None or df_subset.empty:
        return "<div style='padding:20px; text-align:center; color:#8b949e; border: 1px dashed #30363d; border-radius:8px;'>No Stocks found right now.</div>"
    
    df_valid = df_subset.copy()
    if df_valid.empty:
        return "<div style='padding:20px; text-align:center; color:#8b949e; border: 1px dashed #30363d; border-radius:8px;'>Prastutam Score >= 10 unna stocks levu.</div>"

    sell_mask = df_valid['Day_C'] < 0
    df_buy = df_valid[~sell_mask].reset_index(drop=True)
    df_sell = df_valid[sell_mask].reset_index(drop=True)

    def _build_lvl_subtable(df_part, title_text, head_bg):
        if df_part.empty:
            return ""
        sub_html = f'<table class="term-table"><thead><tr><th colspan="10" class="term-head-levels" style="background-color:{head_bg};">{title_text}</th></tr><tr style="background-color: #21262d;"><th style="width:4%;">RANK</th><th style="text-align:left; width:13%;">STOCK</th><th style="width:9%;">LTP</th><th style="width:9%;">DAY%</th><th style="width:8%;">VOL</th><th style="width:17%;">STATUS</th><th style="width:11%; color:#f85149;">🛑 STOP LOSS</th><th style="width:11%; color:#3fb950;">🎯 TARGET 1</th><th style="width:11%; color:#3fb950;">🎯 TARGET 2</th><th style="width:7%;">SCORE</th></tr></thead><tbody>'
        for i, row in df_part.iterrows():
            bg_class = "row-dark" if i % 2 == 0 else "row-light"
            day_color = "text-green" if row['Day_C'] >= 0 else "text-red"
            strat_icon = str(row.get('Strategy_Icon', ''))
            base_status = generate_status(row)
            custom_status = f"{strat_icon} | {base_status}".strip() if strat_icon else base_status
            is_down = row['Day_C'] < 0
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
            sub_html += row_str
        sub_html += "</tbody></table>"
        return sub_html

    html_out = _build_lvl_subtable(df_buy, "🟢 POSITIVE / BUY — INTRADAY TRADING LEVELS", "#004d40")
    html_out += _build_lvl_subtable(df_sell, "🔴 NEGATIVE / SELL — INTRADAY TRADING LEVELS", "#7f1d1d")
    return html_out

def render_chart(row, df_chart, show_pin=True, key_suffix="", timeframe="Intraday (5m)", show_crosshair=False, show_vol=False):
    display_sym = row['T']
    fetch_sym = row['Fetch_T']
    pct_val = float(row.get('W_C', row['Day_C'])) if timeframe == "Weekly Chart" else float(row['Day_C'])
    color_hex = "#da3633" if pct_val < 0 else "#2ea043"
    sign = "+" if pct_val > 0 else ""
    tv_link = f"https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(fetch_sym, 'NSE:' + display_sym)}"
    
    if show_pin and display_sym not in ["NIFTY", "BANKNIFTY", "INDIA VIX", "SPX", "DAX", "USD/INR"] and not row.get('Is_Commodity'):
        cb_key = f"cb_{fetch_sym}_{key_suffix}" if key_suffix else f"cb_{fetch_sym}"
        is_pinned = fetch_sym in st.session_state.pinned_stocks
        pin_val = st.checkbox("pin", value=is_pinned, key=cb_key, label_visibility="collapsed")
        if pin_val != is_pinned:
            if pin_val:
                if fetch_sym not in st.session_state.pinned_stocks: st.session_state.pinned_stocks.append(fetch_sym)
            else:
                if fetch_sym in st.session_state.pinned_stocks: st.session_state.pinned_stocks.remove(fetch_sym)
            st.rerun(scope="fragment")
    
    strat_tag = f" <span style='font-size:10px; background:rgba(0,191,255,0.2); border:1px solid #00BFFF; padding:1px 4px; border-radius:3px; color:#00BFFF;'>{row.get('Strategy_Icon', '')}</span>" if row.get('Strategy_Icon') and row.get('Strategy_Icon') != "Neutral" else ""
    
    if timeframe == "Intraday (5m)":
        day_high = float(row.get('H', 0))
        day_low = float(row.get('L', 0))
        ltp_now = float(row.get('P', 0))
        
        if pct_val >= 0:
            intraday_pb = ((day_high - ltp_now) / day_high) * 100 if day_high > 0 else 0
            pb_tag = f" &nbsp;<span style='color:#FF8C00; font-size:11px;'>📉 -{intraday_pb:.1f}% DH</span>" if intraday_pb >= 0.1 else ""
        else:
            intraday_bounce = ((ltp_now - day_low) / day_low) * 100 if day_low > 0 else 0
            pb_tag = f" &nbsp;<span style='color:#00BFFF; font-size:11px;'>📈 +{intraday_bounce:.1f}% DL</span>" if intraday_bounce >= 0.1 else ""
    else:
        strat_icon = str(row.get('Strategy_Icon', ''))
        if "🔴" in strat_icon or "SELL" in strat_icon or "Stage 4" in strat_icon or "Breakdown" in strat_icon or "Holy Grail" in strat_icon:
            low_52w = float(row.get('Low52W', 0))
            ltp_now = float(row.get('P', 0))
            dist_52wl = ((ltp_now - low_52w) / low_52w) * 100 if low_52w > 0 else 0
            pb_tag = f" &nbsp;<span style='color:#f85149; font-size:11px;'>🩸 +{dist_52wl:.1f}% 52WL</span>" if dist_52wl >= 0.1 else ""
        else:
            pb_val = float(row.get('Pullback_52W', 0))
            pb_tag = f" &nbsp;<span style='color:#FF8C00; font-size:11px;'>📉 -{pb_val:.1f}% 52WH</span>" if pb_val >= 0.1 else ""
    
    title_html = f"<a href='{tv_link}' target='_blank' style='color:#ffffff; text-decoration:none; line-height:1.2;'><b>{display_sym}</b>{strat_tag}<br><span style='font-size:12px; color:#cccccc;'>₹{row['P']:.2f} &nbsp;<span style='color:{color_hex};'>({sign}{pct_val:.2f}%)</span>{pb_tag}</span></a>"
    
    try:
        if not df_chart.empty and 'Low' in df_chart.columns and 'High' in df_chart.columns:
            df_chart = df_chart.copy()
            if timeframe == "Intraday (5m)":
                df_chart = df_chart.tail(75)
            min_val = df_chart['Low'].min()
            max_val = df_chart['High'].max()
            y_padding = (max_val - min_val) * 0.15 if (max_val - min_val) != 0 else min_val * 0.005 
            
            if df_chart.index.tz is not None:
                df_chart.index = df_chart.index.tz_convert('Asia/Kolkata').tz_localize(None)

            chart_times = pd.to_datetime(df_chart.index)
            # Sequential integer X-axis valla SPX, USD/INR mariyu holidays lo etuvanti empty space raadu
            x_idx = list(range(len(df_chart)))
            
            hover_data = (
                "🕒 " + chart_times.strftime('%d-%b %I:%M %p') + 
                "<br>🟢 O: ₹" + df_chart['Open'].round(2).astype(str) + 
                "<br>📈 H: ₹" + df_chart['High'].round(2).astype(str) + 
                "<br>📉 L: ₹" + df_chart['Low'].round(2).astype(str) + 
                "<br>🔴 C: ₹" + df_chart['Close'].round(2).astype(str)
            )
            
            hover_kwargs = {}
            if show_crosshair:
                hover_kwargs = {"hovertemplate": "%{text}<extra></extra>"}
            
            def apply_standard_candles(fig_obj, is_subplot):
                rc = dict(row=1, col=1) if is_subplot else dict()
                
                if 'Volume' in df_chart.columns:
                    vol_sma = df_chart.get('Vol_SMA_89', df_chart['Volume'].rolling(window=20, min_periods=1).mean())
                    hv_mask = df_chart['Volume'] > (vol_sma * 1.618)
                    
                    vwap_val = df_chart.get('VWAP', pd.Series(0, index=df_chart.index))
                    ema10_val = df_chart.get('EMA_10', pd.Series(0, index=df_chart.index))
                    
                    strong_up = (df_chart['Close'] > vwap_val) & (df_chart['Close'] > ema10_val)
                    strong_down = (df_chart['Close'] < vwap_val) & (df_chart['Close'] < ema10_val)
                    
                    bull = df_chart['Close'] >= df_chart['Open']
                    bear = df_chart['Close'] < df_chart['Open']
                    
                    mask_hv_bull = hv_mask & strong_up & bull
                    mask_hv_bear = hv_mask & strong_down & bear
                    mask_norm = ~(mask_hv_bull | mask_hv_bear)
                else:
                    mask_hv_bull = pd.Series(False, index=df_chart.index)
                    mask_hv_bear = pd.Series(False, index=df_chart.index)
                    mask_norm = pd.Series(True, index=df_chart.index)

                def am(col, mask): return np.where(mask, df_chart[col], np.nan)

                fig_obj.add_trace(go.Candlestick(
                    x=x_idx, open=am('Open', mask_norm), high=am('High', mask_norm), low=am('Low', mask_norm), close=am('Close', mask_norm), 
                    increasing_line_color='#2ea043', increasing_fillcolor='#2ea043', increasing_line_width=1,
                    decreasing_line_color='#da3633', decreasing_fillcolor='#da3633', decreasing_line_width=1,
                    showlegend=False, hoverinfo='skip'
                ), **rc)
                
                if mask_hv_bull.any():
                    fig_obj.add_trace(go.Candlestick(
                        x=x_idx, open=am('Open', mask_hv_bull), high=am('High', mask_hv_bull), low=am('Low', mask_hv_bull), close=am('Close', mask_hv_bull), 
                        increasing_line_color='#00FF00', increasing_fillcolor='#00FF00', increasing_line_width=2,
                        decreasing_line_color='#00FF00', decreasing_fillcolor='#00FF00', decreasing_line_width=2,
                        showlegend=False, hoverinfo='skip'
                    ), **rc)
                    
                if mask_hv_bear.any():
                    fig_obj.add_trace(go.Candlestick(
                        x=x_idx, open=am('Open', mask_hv_bear), high=am('High', mask_hv_bear), low=am('Low', mask_hv_bear), close=am('Close', mask_hv_bear), 
                        increasing_line_color='#FF0000', increasing_fillcolor='#FF0000', increasing_line_width=2,
                        decreasing_line_color='#FF0000', decreasing_fillcolor='#FF0000', decreasing_line_width=2,
                        showlegend=False, hoverinfo='skip'
                    ), **rc)

            if show_vol:
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.02, row_heights=[0.75, 0.25])
                apply_standard_candles(fig, is_subplot=True)
                fig.add_trace(go.Scatter(
                    x=x_idx, y=df_chart['High'], mode='lines', 
                    line=dict(color='rgba(0,0,0,0)'), showlegend=False, 
                    hoverinfo='text' if show_crosshair else 'skip', 
                    text=hover_data, name="", **hover_kwargs
                ), row=1, col=1)
                
                if timeframe == "Daily Chart":
                    if 'SMA_50' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_50'], mode='lines', line=dict(color='#FFD700', width=1.5), name='50 SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
                    if 'SMA_150' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_150'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), name='150 SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
                    if 'SMA_200' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_200'], mode='lines', line=dict(color='#FF4500', width=2), name='200 SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
                elif timeframe == "Weekly Chart":
                    if 'SMA_10' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_10'], mode='lines', line=dict(color='#FFD700', width=1.5), name='10 Wk SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
                    if 'SMA_40' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_40'], mode='lines', line=dict(color='#FF4500', width=2), name='40 Wk SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
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
                    if has_vwap and has_ema and abs(tag_y_vwap - tag_y_ema) / (tag_y_vwap + 0.001) < 0.008:
                        if tag_y_vwap >= tag_y_ema:
                            v_anchor, v_shift = "bottom", 6
                            e_anchor, e_shift = "top", -6
                        else:
                            v_anchor, v_shift = "top", -6
                            e_anchor, e_shift = "bottom", 6

                    if has_vwap and has_ema and abs(tag_y_vwap - tag_y_ema) / (tag_y_vwap + 0.001) < 0.005:
                        if tag_y_vwap >= tag_y_ema:
                            v_anchor, v_shift = "bottom", 6
                            e_anchor, e_shift = "top", -6
                        else:
                            v_anchor, v_shift = "top", -6
                            e_anchor, e_shift = "bottom", 6

                    if has_vwap: 
                        fig.add_trace(go.Scatter(x=x_idx, y=df_chart['VWAP'], mode='lines', line=dict(color='#FFD700', width=1.5, dash='dot'), showlegend=False, hoverinfo='skip'), row=1, col=1)
                        fig.add_annotation(x=tag_idx, y=tag_y_vwap, text=f"V:{last_vwap:.1f}", showarrow=False, xanchor="right", yanchor=v_anchor, xshift=-5, yshift=v_shift, font=dict(color="#161b22", size=10, family="monospace", weight="bold"), bgcolor="#FFD700", borderpad=2, row=1, col=1)
                        
                    if has_ema: 
                        fig.add_trace(go.Scatter(x=x_idx, y=df_chart['EMA_10'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), showlegend=False, hoverinfo='skip'), row=1, col=1)
                        fig.add_annotation(x=tag_idx, y=tag_y_ema, text=f"E:{last_ema:.1f}", showarrow=False, xanchor="right", yanchor=e_anchor, xshift=-5, yshift=e_shift, font=dict(color="#161b22", size=10, family="monospace", weight="bold"), bgcolor="#00BFFF", borderpad=2, row=1, col=1)
            
                vol_colors = []
                if 'Volume' in df_chart.columns:
                    vol_sma = df_chart.get('Vol_SMA_89', df_chart['Volume'].rolling(window=20, min_periods=1).mean())
                    for i in range(len(df_chart)):
                        close_p = df_chart['Close'].iloc[i]
                        open_px = df_chart['Open'].iloc[i]
                        bull = close_p >= open_px
                        hv = df_chart['Volume'].iloc[i] > (vol_sma.iloc[i] * 1.618)
                        
                        vwap_val = df_chart['VWAP'].iloc[i] if 'VWAP' in df_chart.columns else 0
                        ema10_val = df_chart['EMA_10'].iloc[i] if 'EMA_10' in df_chart.columns else 0
                        
                        is_strong_up = (close_p > vwap_val) and (close_p > ema10_val)
                        is_strong_down = (close_p < vwap_val) and (close_p < ema10_val)

                        if hv:
                            if is_strong_up and bull: vol_colors.append('#00FF00')
                            elif is_strong_down and not bull: vol_colors.append('#8B0000')
                            else: vol_colors.append('#FFD700' if bull else '#FF8C00')
                        else:
                            vol_colors.append('rgba(46, 160, 67, 0.4)' if bull else 'rgba(218, 54, 51, 0.4)')
                else:
                    vol_colors = ['rgba(46, 160, 67, 0.4)' if c >= o else 'rgba(218, 54, 51, 0.4)' 
                                  for c, o in zip(df_chart['Close'], df_chart['Open'])]
                
                fig.add_trace(go.Bar(x=x_idx, y=df_chart['Volume'], marker_color=vol_colors, showlegend=False, hoverinfo='skip'), row=2, col=1)
                
                fig.update_layout(margin=dict(l=0, r=45 if show_crosshair else 5, t=0, b=0), height=275, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_rangeslider_visible=False)
                fig.add_annotation(text=title_html, xref="paper", yref="paper", x=0, xanchor="left", xshift=35, y=0.98, yanchor="top", showarrow=False, font=dict(size=13, color="#ffffff"), bgcolor="rgba(0,0,0,0)", borderwidth=0)

                if fetch_sym in st.session_state.custom_alerts:
                    alert_data = st.session_state.custom_alerts[fetch_sym]
                    if alert_data['enabled']:
                        line_c = "#3fb950" if "Above" in alert_data['type'] else "#f85149"
                        fig.add_hline(y=alert_data['price'], line_dash="dash", line_color=line_c, line_width=1.5, opacity=0.8, row=1, col=1)

                if show_crosshair:
                    fig.update_layout(hovermode='x', dragmode=False, hoverlabel=dict(bgcolor="#161b22", font_size=12, font_color="#ffffff", bordercolor="#30363d"))
                    fig.update_xaxes(showspikes=True, spikemode='across', spikethickness=1, spikedash='dot', spikecolor="rgba(255, 255, 255, 0.4)", showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True)
                    fig.update_yaxes(showspikes=True, spikemode='across', spikethickness=1, spikedash='dot', spikecolor="rgba(255, 255, 255, 0.4)", showgrid=False, zeroline=False, showticklabels=True, side='right', tickfont=dict(color="#ffffff", size=10), showline=False, fixedrange=True, range=[min_val - y_padding, max_val + (y_padding * 2.5)], row=1, col=1)
                    fig.update_yaxes(showspikes=False, showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True, row=2, col=1)
                else:
                    fig.update_layout(hovermode=False, dragmode=False)
                    fig.update_xaxes(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True)
                    fig.update_yaxes(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True, range=[min_val - y_padding, max_val + (y_padding * 2.5)], row=1, col=1)
                    fig.update_yaxes(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True, row=2, col=1)

            else:
                fig = go.Figure()
                apply_standard_candles(fig, is_subplot=False)
                fig.add_trace(go.Scatter(
                    x=x_idx, y=df_chart['High'], mode='lines', 
                    line=dict(color='rgba(0,0,0,0)'), showlegend=False, 
                    hoverinfo='text' if show_crosshair else 'skip', 
                    text=hover_data, name="", **hover_kwargs
                ))
                
                if timeframe == "Daily Chart":
                    if 'SMA_50' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_50'], mode='lines', line=dict(color='#FFD700', width=1.5), name='50 SMA', showlegend=False, hoverinfo='skip'))
                    if 'SMA_150' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_150'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), name='150 SMA', showlegend=False, hoverinfo='skip'))
                    if 'SMA_200' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_200'], mode='lines', line=dict(color='#FF4500', width=2), name='200 SMA', showlegend=False, hoverinfo='skip'))
                elif timeframe == "Weekly Chart":
                    if 'SMA_10' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_10'], mode='lines', line=dict(color='#FFD700', width=1.5), name='10 Wk SMA', showlegend=False, hoverinfo='skip'))
                    if 'SMA_40' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_40'], mode='lines', line=dict(color='#FF4500', width=2), name='40 Wk SMA', showlegend=False, hoverinfo='skip'))
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

                    if has_vwap and has_ema and abs(tag_y_vwap - tag_y_ema) / (tag_y_vwap + 0.001) < 0.005:
                        if tag_y_vwap >= tag_y_ema:
                            v_anchor, v_shift = "bottom", 6
                            e_anchor, e_shift = "top", -6
                        else:
                            v_anchor, v_shift = "top", -6
                            e_anchor, e_shift = "bottom", 6

                    if has_vwap: 
                        fig.add_trace(go.Scatter(x=x_idx, y=df_chart['VWAP'], mode='lines', line=dict(color='#FFD700', width=1.5, dash='dot'), showlegend=False, hoverinfo='skip'))
                        fig.add_annotation(x=tag_idx, y=tag_y_vwap, text=f"V:{last_vwap:.1f}", showarrow=False, xanchor="right", yanchor=v_anchor, xshift=-5, yshift=v_shift, font=dict(color="#161b22", size=10, family="monospace", weight="bold"), bgcolor="#FFD700", borderpad=2)
                        
                    if has_ema: 
                        fig.add_trace(go.Scatter(x=x_idx, y=df_chart['EMA_10'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), showlegend=False, hoverinfo='skip'))
                        fig.add_annotation(x=tag_idx, y=tag_y_ema, text=f"E:{last_ema:.1f}", showarrow=False, xanchor="right", yanchor=e_anchor, xshift=-5, yshift=e_shift, font=dict(color="#161b22", size=10, family="monospace", weight="bold"), bgcolor="#00BFFF", borderpad=2)
            
                fig.update_layout(margin=dict(l=0, r=45 if show_crosshair else 5, t=0, b=0), height=235, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', showlegend=False, xaxis_rangeslider_visible=False)
                fig.add_annotation(text=title_html, xref="paper", yref="paper", x=0, xanchor="left", xshift=35, y=0.98, yanchor="top", showarrow=False, font=dict(size=13, color="#ffffff"), bgcolor="rgba(0,0,0,0)", borderwidth=0)

                if fetch_sym in st.session_state.custom_alerts:
                    alert_data = st.session_state.custom_alerts[fetch_sym]
                    if alert_data['enabled']:
                        line_c = "#3fb950" if "Above" in alert_data['type'] else "#f85149"
                        fig.add_hline(y=alert_data['price'], line_dash="dash", line_color=line_c, line_width=1.5, opacity=0.8)

                if show_crosshair:
                    fig.update_layout(hovermode='x', dragmode=False, hoverlabel=dict(bgcolor="#161b22", font_size=12, font_color="#ffffff", bordercolor="#30363d"))
                    fig.update_yaxes(showspikes=True, spikemode='across', spikethickness=0.2, spikedash='solid', spikecolor="rgba(255,255,255,0.4)", showgrid=False, zeroline=False, showticklabels=True, side='right', tickfont=dict(color="#ffffff", size=10), showline=False, fixedrange=True, range=[min_val - y_padding, max_val + (y_padding * 2.5)])
                    fig.update_xaxes(showspikes=False, showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True)
                else:
                    fig.update_layout(hovermode=False, dragmode=False)
                    fig.update_yaxes(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True, range=[min_val - y_padding, max_val + (y_padding * 2.5)])
                    fig.update_xaxes(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True)

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
    st.session_state.wl_sort_col = None
if 'wl_sort_asc' not in st.session_state:
    st.session_state.wl_sort_asc = False
if 'selected_ai_strats' not in st.session_state:
    st.session_state.selected_ai_strats = [ADAPTIVE_STRAT, "All Day Trading Moves 🚀", NEWS_STRAT]
if 'selected_sw_strats' not in st.session_state:
    st.session_state.selected_sw_strats = ["📈 Minervini Trend Template (VCP)"]

# --- CSS: ZERO SIDE MARGINS + EXCEL WATCHLIST + COMPACT MULTI-CHART GRID ---
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

    /* 2. Fix Select Strategies Popover Checkbox Overlap */
    div[data-testid="stVerticalBlock"] > div[data-testid="stElementContainer"]:has(div[data-testid="stCheckbox"]) {
        margin-bottom: 0px !important;
        position: static !important;
    }
    div[data-testid="stPopoverBody"] div[data-testid="stElementContainer"]:has(div[data-testid="stCheckbox"]) {
        margin-bottom: 6px !important;
        position: static !important;
    }
    div[data-testid="stPopoverBody"] div[data-testid="stCheckbox"] label {
        padding: 4px 2px !important;
        min-height: 24px !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div:nth-child(1) {
        display: block !important;
    }

    /* 3. Deep Black Mini-Chart Grid (Auto-Adjusts up to 8 Charts on Hide/Zoom & 3 Charts on Mobile) */
    .stApp { background-color: #0b0e14 !important; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) {
        display: grid !important;
        gap: 6px !important;
        align-items: start !important;
        width: 100% !important;
    }
    div[data-testid="stElementContainer"]:has(.pro-mini-board) { display: none !important; }

    /* Desktop & Laptop: 5 charts in 80% view -> 6-7 charts when 20% hidden -> up to 8 charts on Zoom Out */
    @media screen and (min-width: 769px) {
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) {
            grid-template-columns: repeat(auto-fill, minmax(max(190px, calc((100% - 48px) / 8)), 1fr)) !important;
            gap: 6px !important;
        }
    }

    /* Mobile: Default 2 Charts per row -> Becomes 3 Charts per row when Right Panel is Hidden */
    @media screen and (max-width: 768px) {
        /* 1. Default Mobile View (65:35 Split): 2 Charts per row */
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) {
            grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
            gap: 4px !important;
        }

        /* 2. Full-Screen Mobile View (After clicking Hide 20% / ▶ HIDE): 3 Charts per row */
        div[data-testid="stColumn"][style*="100%"] div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board),
        body.hide-right-20 div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) {
            grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
            gap: 3px !important;
        }

        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) > div div[data-testid="stElementContainer"]:has(div[data-testid="stCheckbox"]) {
            transform: scale(0.82);
            transform-origin: top left;
            top: 4px !important;
            left: 3px !important;
        }
    }

    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) > div {
        background-color: #0b0e14 !important;
        border: 1px solid #161b22 !important;
        border-radius: 6px !important;
        padding: 2px !important;
        position: relative !important;
        width: 100% !important;
        min-width: 0 !important;
        max-width: 100% !important;
        overflow: hidden !important;
        box-sizing: border-box !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) div[data-testid="stPlotlyChart"],
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) .js-plotly-plot,
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) .plot-container,
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) .svg-container {
        width: 100% !important;
        max-width: 100% !important;
        min-width: 0 !important;
        overflow: hidden !important;
    }

    /* 🔥 FIX: Bring Pin Checkbox & Stock Name on the exact same top line inside Mini-Charts */
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-mini-board) > div div[data-testid="stElementContainer"]:has(div[data-testid="stCheckbox"]) {
        margin-bottom: -42px !important;
        position: relative !important;
        top: 6px !important;
        left: 6px !important;
        z-index: 100 !important;
        width: 24px !important;
    }
    /* Auto-Fit Height (100vh) for Both 15-inch Laptop & 22-inch Desktop */
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.right-panel-marker) {
        height: calc(100vh - 14px) !important;
        max-height: calc(100vh - 14px) !important;
    }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.left-main-scroll-marker) {
        height: calc(100vh - 46px) !important;
        max-height: calc(100vh - 46px) !important;
    }
    div[data-testid="stExpanderDetails"]:has(.tv-sort-hdr-marker) div[data-testid="stVerticalBlockBorderWrapper"] {
        height: calc(100vh - 360px) !important;
        max-height: calc(100vh - 360px) !important;
        min-height: 220px !important;
    }

    /* Pro Grid Charts Auto-Scale Height on 22-inch & 15-inch Monitors */
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-grid-1row) iframe {
        height: calc(92vh - 42px) !important;
        min-height: 550px !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-grid-2row) iframe {
        height: calc(46vh - 24px) !important;
        min-height: 310px !important;
    }

    /* 4. Right 20% Panel Compact Spacing & Single-Line Pro Grid */
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) {
        gap: 4px !important;
    }
    div[data-testid="stElementContainer"]:has(.right-panel-marker),
    div[data-testid="stElementContainer"]:has(.left-main-scroll-marker),
    div[data-testid="stElementContainer"]:has(.pro-grid-1row),
    div[data-testid="stElementContainer"]:has(.pro-grid-2row) { display: none !important; }

    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) div[data-testid="stRadio"] {
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        justify-content: space-between !important;
        background: #161b22 !important;
        border: 1px solid #30363d !important;
        border-radius: 6px !important;
        padding: 3px 8px !important;
        margin: 0px !important;
        min-height: 30px !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) div[data-testid="stRadio"] > label {
        margin-bottom: 0px !important;
        white-space: nowrap !important;
        font-size: 11.5px !important;
        color: #58a6ff !important;
        font-weight: bold !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) div[data-testid="stRadio"] div[role="radiogroup"] {
        gap: 6px !important;
        flex-wrap: nowrap !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) div[data-testid="stExpander"] summary {
        padding: 4px 8px !important;
        min-height: 30px !important;
    }
    div[data-testid="stExpanderDetails"]:has(.tv-sort-hdr-marker) {
        padding: 2px 2px 4px 2px !important;
    }

    /* 5. Excel-Style Sortable Table Header (Symbol | Last | Chg | Chg%) — Fixed for Mobile & Desktop */
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-sort-hdr-marker) div[data-testid="stHorizontalBlock"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        align-items: center !important;
        gap: 0px !important;
        border-top: 1px solid #30363d !important;
        border-bottom: 1px solid #30363d !important;
        background-color: #161b22 !important;
        padding: 4px 0px !important;
        width: 100% !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-sort-hdr-marker) div[data-testid="stColumn"]:nth-child(1) {
        width: 36% !important; flex: 0 0 36% !important; min-width: 0 !important; padding: 0px 0px 0px 6px !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-sort-hdr-marker) div[data-testid="stColumn"]:nth-child(2) {
        width: 22% !important; flex: 0 0 22% !important; min-width: 0 !important; padding: 0px 6px 0px 0px !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-sort-hdr-marker) div[data-testid="stColumn"]:nth-child(3) {
        width: 20% !important; flex: 0 0 20% !important; min-width: 0 !important; padding: 0px 6px 0px 0px !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-sort-hdr-marker) div[data-testid="stColumn"]:nth-child(4) {
        width: 22% !important; flex: 0 0 22% !important; min-width: 0 !important; padding: 0px 6px 0px 0px !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-sort-hdr-marker) div.stButton > button {
        background-color: transparent !important;
        border: none !important;
        height: 20px !important;
        min-height: 20px !important;
        padding: 0px !important;
        margin: 0px !important;
        width: 100% !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-sort-hdr-marker) div[data-testid="stColumn"]:nth-child(1) div.stButton > button p {
        text-align: left !important; width: 100% !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-sort-hdr-marker) div[data-testid="stColumn"]:nth-child(n+2) div.stButton > button p {
        text-align: right !important; width: 100% !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-sort-hdr-marker) div.stButton > button p {
        font-family: 'Consolas', monospace !important;
        font-size: 11px !important;
        font-weight: 700 !important;
        color: #58a6ff !important;
        margin: 0px !important;
        white-space: nowrap !important;
    }
    div[data-testid="stElementContainer"]:has(.tv-sort-hdr-marker) { display: none !important; }

    /* 7. Hidden Close Trigger & Single-Line Unified Top Toolbar */
    div[data-testid="stElementContainer"]:has(.hidden-close-trigger),
    div[data-testid="stElementContainer"]:has(.hidden-close-trigger) + div[data-testid="stElementContainer"] {
        height: 0px !important;
        min-height: 0px !important;
        max-height: 0px !important;
        margin: 0px !important;
        padding: 0px !important;
        overflow: hidden !important;
        opacity: 0 !important;
        position: absolute !important;
        pointer-events: none !important;
    }
    div[data-testid="stColumn"]:has(.pro-ActionBar) div.stButton > button {
        background-color: #21262d !important;
        border: 1px solid #30363d !important;
        color: #e6edf3 !important;
        height: 28px !important;
        min-height: 28px !important;
        padding: 0px 6px !important;
        margin: 0px !important;
        border-radius: 5px !important;
        font-size: 11.5px !important;
    }
    div[data-testid="stColumn"]:has(.pro-ActionBar) div.stButton > button:hover {
        background-color: #30363d !important;
        border-color: #58a6ff !important;
    }
    div[data-testid="stColumn"]:has(.pro-ActionBar) div[data-testid="stSelectbox"] {
        margin: 0px !important;
    }
    div[data-testid="stColumn"]:has(.pro-ActionBar) div[data-testid="stSelectbox"] > div > div {
        min-height: 28px !important;
        height: 28px !important;
        font-size: 11.5px !important;
        padding-top: 0px !important;
        padding-bottom: 0px !important;
        background-color: #161b22 !important;
        border: 1px solid #30363d !important;
        border-radius: 5px !important;
    }
    div[data-testid="stElementContainer"]:has(.pro-ActionBar) { display: none !important; }

    /* Mobile Responsive Fix: 65:35 Split + Ultra-Compact Right 35% Panel + Full X-Axis Time Visibility */
    @media screen and (max-width: 768px) {
        div[data-testid="stHorizontalBlock"]:has(.right-panel-marker) {
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            align-items: flex-start !important;
            gap: 3px !important;
            width: 100% !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.right-panel-marker) > div[data-testid="stColumn"]:nth-child(1) {
            width: 64% !important;
            flex: 0 0 64% !important;
            max-width: 64% !important;
            min-width: 0 !important;
        }
        div[data-testid="stHorizontalBlock"]:has(.right-panel-marker) > div[data-testid="stColumn"]:nth-child(2) {
            width: 36% !important;
            flex: 0 0 36% !important;
            max-width: 36% !important;
            min-width: 0 !important;
        }

        /* Fix Chart Container & Iframe Height on Mobile so Bottom Date & Time Fits Default Without Scrolling */
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.left-main-scroll-marker) {
            height: calc(100dvh - 165px) !important;
            max-height: calc(100dvh - 165px) !important;
            overflow: hidden !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-grid-1row) iframe {
            height: calc(100dvh - 180px) !important;
            min-height: 340px !important;
            max-height: calc(100dvh - 180px) !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .pro-grid-2row) iframe {
            height: calc(42dvh - 30px) !important;
            min-height: 210px !important;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.right-panel-marker) {
            padding: 3px !important;
            height: calc(100dvh - 95px) !important;
            max-height: calc(100dvh - 95px) !important;
        }
        /* Ultra-Compact Right 35% Panel Controls (Fixes H-e-a-t-M-a-p vertical text wrapping) */
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.right-panel-marker) {
            padding: 3px !important;
            height: calc(100vh - 10px) !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) div[data-testid="stSelectbox"] > div > div,
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) div[data-testid="stPopover"] button {
            min-height: 26px !important;
            height: auto !important;
            padding: 2px 4px !important;
            font-size: 9.5px !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) div[data-testid="stPopover"] button p {
            font-size: 9.5px !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) div[data-testid="stRadio"] {
            flex-direction: column !important;
            align-items: flex-start !important;
            padding: 2px 4px !important;
            gap: 2px !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) div[data-testid="stRadio"] > label {
            display: none !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) div[data-testid="stRadio"] div[role="radiogroup"] {
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: wrap !important;
            gap: 4px !important;
            width: 100% !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) div[data-testid="stRadio"] label {
            margin: 0px !important;
            padding: 0px !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) div[data-testid="stRadio"] p {
            font-size: 9.5px !important;
            white-space: nowrap !important;
            word-break: keep-all !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) div[data-testid="stExpander"] summary p {
            font-size: 9.5px !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
        }

        /* Compact Watchlist Table inside 35% Mobile Panel (Hide Chg pts column on mobile so Symbol, Last & Chg% fit cleanly!) */
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-sort-hdr-marker) div[data-testid="stHorizontalBlock"] {
            flex-direction: row !important;
            flex-wrap: nowrap !important;
            padding: 2px 0px !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-sort-hdr-marker) div[data-testid="stColumn"]:nth-child(1) {
            width: 44% !important; flex: 0 0 44% !important; padding-left: 2px !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-sort-hdr-marker) div[data-testid="stColumn"]:nth-child(2) {
            width: 28% !important; flex: 0 0 28% !important; padding-right: 2px !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-sort-hdr-marker) div[data-testid="stColumn"]:nth-child(3) {
            display: none !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-sort-hdr-marker) div[data-testid="stColumn"]:nth-child(4) {
            width: 28% !important; flex: 0 0 28% !important; padding-right: 2px !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .tv-sort-hdr-marker) div.stButton > button p {
            font-size: 9px !important;
        }

        /* Watchlist HTML Table Rows on Mobile */
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) .term-table {
            font-size: 9px !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) .term-table td {
            padding: 4px 1px !important;
            font-size: 9px !important;
            text-overflow: clip !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) .term-table td:nth-child(1) {
            width: 44% !important; padding-left: 2px !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) .term-table td:nth-child(2) {
            width: 28% !important; padding-right: 2px !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) .term-table td:nth-child(3) {
            display: none !important;
        }
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .right-panel-marker) .term-table td:nth-child(4) {
            width: 28% !important; padding-right: 2px !important;
        }

        /* Top Action Bar (Paper, Qty, Mini, Theme, Clear) Compact Grid on Mobile */
        div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"] .pro-ActionBar) {
            display: flex !important;
            flex-direction: row !important;
            flex-wrap: wrap !important;
            gap: 2px !important;
        }
        div[data-testid="stHorizontalBlock"]:has(> div[data-testid="stColumn"] .pro-ActionBar) > div[data-testid="stColumn"] {
            flex: 1 1 30% !important;
            min-width: 65px !important;
            width: auto !important;
        }
    }

    /* 🔥 HIDE 20% RIGHT PANEL -> EXPAND 80% CHARTS TO 100% FULL WIDTH (DESKTOP & MOBILE) */
    body.hide-right-20 div[data-testid="stHorizontalBlock"]:has(.right-panel-marker) > div[data-testid="stColumn"]:nth-child(2) {
        display: none !important;
        width: 0px !important;
        flex: 0 0 0px !important;
        max-width: 0px !important;
        min-width: 0px !important;
        overflow: hidden !important;
        padding: 0px !important;
        margin: 0px !important;
    }
    body.hide-right-20 div[data-testid="stHorizontalBlock"]:has(.right-panel-marker) > div[data-testid="stColumn"]:nth-child(1) {
        width: 100% !important;
        flex: 0 0 100% !important;
        max-width: 100% !important;
        min-width: 100% !important;
    }

    /* Floating Right-Edge Handle (Works on Desktop & Mobile to Hide/Show 20% Panel Anytime) */
    #rp-edge-toggle {
        position: fixed;
        right: 0px;
        top: 50%;
        transform: translateY(-50%);
        z-index: 999999;
        background: #1f6feb;
        color: #ffffff;
        border: 1px solid #58a6ff;
        border-right: none;
        border-radius: 6px 0 0 6px;
        padding: 8px 4px;
        font-size: 11px;
        font-weight: bold;
         font-family: monospace;
        cursor: pointer;
        box-shadow: -2px 0 8px rgba(0,0,0,0.6);
        user-select: none;
        writing-mode: vertical-rl;
        text-orientation: mixed;
        letter-spacing: 1px;
        transition: 0.15s;
    }
    #rp-edge-toggle:hover {
        background: #388bfd;
        padding-right: 7px;
    }
    /* 📰 Mini-Chart Full-Box News Overlay on Hover (Fixed Top Names & Smooth Inner Scroll) */
    div[data-testid="stElementContainer"]:has(.mc-card-news-zone),
    div[data-testid="stElementContainer"]:has(.mc-card-news-zone) > div,
    div[data-testid="stElementContainer"]:has(.mc-card-news-zone) div[data-testid="stMarkdown"],
    div[data-testid="stElementContainer"]:has(.mc-card-news-zone) div[data-testid="stMarkdownContainer"] {
        position: static !important;
        margin: -16px 0px 0px 0px !important;
        padding: 0px !important;
        height: 0px !important;
        min-height: 0px !important;
        max-height: 0px !important;
        line-height: 0px !important;
        overflow: visible !important;
        z-index: 95 !important;
    }
    .mc-card-news-zone {
        position: static !important;
        margin: 0px !important;
        padding: 0px !important;
        height: 0px !important;
    }
    .mc-news-trigger {
        position: absolute !important;
        top: 2px !important;
        left: 30px !important;
        right: 4px !important;
        height: 42px !important;
        z-index: 92 !important;
        cursor: pointer !important;
        background: transparent !important;
    }
    .mc-full-overlay {
        display: none;
        position: absolute !important;
        top: 0px !important;
        left: 0px !important;
        right: 0px !important;
        bottom: 0px !important;
        width: 100% !important;
        height: 100% !important;
        max-height: 100% !important;
        min-height: 0px !important;
        background: rgba(11, 14, 20, 0.98) !important;
        border: 1.5px solid #38bdf8 !important;
        border-radius: 6px !important;
        padding: 7px 9px !important;
        box-sizing: border-box !important;
        z-index: 98 !important;
        flex-direction: column !important;
        justify-content: space-between !important;
        overflow: hidden !important;
        box-shadow: 0 6px 20px rgba(0, 0, 0, 0.95) !important;
        font-family: 'Inter', 'Noto Sans Telugu', 'Segoe UI', sans-serif !important;
        line-height: 1.45 !important;
        pointer-events: auto !important;
    }
    .mc-overlay-body {
        flex: 1 1 auto !important;
        min-height: 0px !important;
        overflow-y: auto !important;
        overflow-x: hidden !important;
        padding-right: 5px !important;
        margin: 4px 0px !important;
        pointer-events: auto !important;
        overscroll-behavior: contain !important;
    }
    .mc-overlay-body::-webkit-scrollbar {
        width: 5px !important;
    }
    .mc-overlay-body::-webkit-scrollbar-track {
        background: #161b22 !important;
        border-radius: 3px !important;
    }
    .mc-overlay-body::-webkit-scrollbar-thumb {
        background: #38bdf8 !important;
        border-radius: 3px !important;
    }
    .mc-card-news-zone:hover .mc-full-overlay,
    .mc-full-overlay:hover {
        display: flex !important;
    }
    @keyframes flashScroll {
        0% { transform: translateX(0%); }
        100% { transform: translateX(-50%); }
    }
    .flash-ticker-wrap {
        flex: 1 1 100% !important;
        width: 100% !important;
        max-width: 100% !important;
        overflow: hidden;
        white-space: nowrap;
        background: rgba(255, 215, 0, 0.10);
        border-left: 3px solid #ffd700;
        border-right: 3px solid #ffd700;
        border-radius: 4px;
        padding: 3px 12px;
        margin: 0 6px;
    }
    .flash-ticker-move {
        display: inline-block;
        /* 95s valla news chala slow ga, chadavadaniki spastanga scroll avutundi */
        animation: flashScroll 95s linear infinite;
        font-size: 14.5px !important;
        font-weight: 700 !important;
        color: #ffffff;
        letter-spacing: 0.3px;
    }
    .flash-ticker-wrap:hover .flash-ticker-move {
        animation-play-state: paused;
    }
    /* Top Action Bar height kuda 38px ki penchadam */
    div[data-testid="stColumn"]:has(.pro-ActionBar) div.stButton > button,
    div[data-testid="stColumn"]:has(.pro-ActionBar) div[data-testid="stSelectbox"] > div > div {
        height: 38px !important;
        min-height: 38px !important;
        font-size: 13px !important;
    }
    </style>
""", unsafe_allow_html=True)


# --- IST TIMEZONE CONVERTER FOR 5-MIN CHARTS ---
def _fix_ist_df(df_in):
    if df_in is None or df_in.empty:
        return pd.DataFrame()
    d = df_in.copy()
    d.index = pd.to_datetime(d.index)
    if d.index.tz is not None:
        d.index = d.index.tz_convert('Asia/Kolkata').tz_localize(None)
    else:
        if len(d.index) > 0 and (3 <= d.index.hour.min() <= 4) and (d.index.hour.max() <= 11):
            d.index = d.index + pd.Timedelta(hours=5, minutes=30)
    return d[~d.index.duplicated(keep='last')].sort_index()


# --- CALLBACK HELPERS ---
if 'ui' not in _SS:
    _SS['ui'] = {
        'pinned_stocks': [],
        'grid_layout_mode': 'Off',
        'pro_grid_theme': 'Light (White)',
        'inspected_stock': 'NIFTY',
        'wl_sort_col': None,
        'wl_sort_asc': False,
        'watchlist_mode': '🤖 AI Predictions (F&O)',
        'sort_mode': 'Score Wise Up ⭐',
        'chart_timeframe': 'Intraday (5m)',
        'view_mode': 'Chart 📈',
        'selected_ai_strats': [ADAPTIVE_STRAT, "All Day Trading Moves 🚀", NEWS_STRAT],
        'selected_sw_strats': ["📈 Minervini Trend Template (VCP)"]
    }

_UI = _SS['ui']

for _k, _v in _UI.items():
    if _k not in st.session_state:
        st.session_state[_k] = list(_v) if isinstance(_v, list) else _v

def _calc_grid_mode(cnt):
    if cnt <= 0: return "Off"
    if cnt == 1: return "1"
    if cnt == 2: return "2"
    if cnt <= 4: return "4"
    return "6"

if "grid_sym" in st.query_params:
    _g_sym = st.query_params["grid_sym"]
    st.query_params.clear()
    _p_list = list(_UI.get('pinned_stocks', []))
    if _g_sym in _p_list:
        _p_list.remove(_g_sym)
    else:
        if len(_p_list) >= 6:
            _p_list.pop(0)
        _p_list.append(_g_sym)
    _UI['pinned_stocks'] = _p_list
    st.session_state.pinned_stocks = list(_p_list)
    _UI['inspected_stock'] = _g_sym.replace(".NS", "")
    st.session_state.inspected_stock = _UI['inspected_stock']
    _new_m = _calc_grid_mode(len(_p_list))
    _UI['grid_layout_mode'] = _new_m
    st.session_state.grid_layout_mode = _new_m
    st.session_state.pro_grid_radio_key = _new_m

def _toggle_wl_stock(s_ft, s_disp):
    st.session_state.inspected_stock = s_disp
    _UI['inspected_stock'] = s_disp
    if s_ft in st.session_state.pinned_stocks:
        st.session_state.pinned_stocks.remove(s_ft)
    else:
        if len(st.session_state.pinned_stocks) >= 6:
            st.session_state.pinned_stocks.pop(0)
        st.session_state.pinned_stocks.append(s_ft)
    _UI['pinned_stocks'] = list(st.session_state.pinned_stocks)
    new_mode = _calc_grid_mode(len(st.session_state.pinned_stocks))
    st.session_state.grid_layout_mode = new_mode
    st.session_state.pro_grid_radio_key = new_mode
    _UI['grid_layout_mode'] = new_mode
# --- CHART TRADING ENGINE (PAPER TRADING GOOGLE SHEETS + DHAN LIVE/SUPER ORDER API + TRADINGVIEW LINES) ---
if 'chart_trades' not in _SS:
    _SS['chart_trades'] = {}
if 'paper_loaded' not in _SS:
    _SS['paper_loaded'] = False
if 'trade_qty' not in _UI:
    _UI['trade_qty'] = 10
if 'trade_mode' not in _UI:
    _UI['trade_mode'] = "📝 Paper Trading"
if 'trade_prod' not in _UI:
    _UI['trade_prod'] = "INTRADAY"

@st.cache_resource(show_spinner=False)
def init_paper_sheets():
    """Trading_DB Google Sheet lo Paper_Portfolio mariyu Paper_TradeBook tabs auto-create/connect chestundi"""
    try:
        sh = port_ws.spreadsheet
        try:
            pp_ws = sh.worksheet("Paper_Portfolio")
        except Exception:
            pp_ws = sh.add_worksheet(title="Paper_Portfolio", rows=200, cols=12)
            pp_ws.update([["Symbol", "Side", "Prod", "Quantity", "Entry_Price", "SL", "Target", "Date_Time", "Mode"]])
        try:
            pt_ws = sh.worksheet("Paper_TradeBook")
        except Exception:
            pt_ws = sh.add_worksheet(title="Paper_TradeBook", rows=500, cols=12)
            pt_ws.update([["Entry_Time", "Exit_Time", "Symbol", "Side", "Prod", "Quantity", "Entry_Price", "Exit_Price", "PnL_Rs", "PnL_Pct", "Mode"]])
        return pp_ws, pt_ws
    except Exception:
        return None, None

@st.cache_data(ttl=60, show_spinner=False)
def load_paper_portfolio():
    cols = ["Symbol", "Side", "Prod", "Quantity", "Entry_Price", "SL", "Target", "Date_Time", "Mode"]
    try:
        pp_ws, _ = init_paper_sheets()
        if pp_ws is None:
            return pd.DataFrame(columns=cols)
        recs = pp_ws.get_all_records()
        df_p = pd.DataFrame(recs) if recs else pd.DataFrame(columns=cols)
        for c in cols:
            if c not in df_p.columns:
                df_p[c] = ""
        return df_p[cols]
    except Exception:
        return pd.DataFrame(columns=cols)

@st.cache_data(ttl=60, show_spinner=False)
def load_paper_tradebook():
    cols = ["Entry_Time", "Exit_Time", "Symbol", "Side", "Prod", "Quantity", "Entry_Price", "Exit_Price", "PnL_Rs", "PnL_Pct", "Mode"]
    try:
        _, pt_ws = init_paper_sheets()
        if pt_ws is None:
            return pd.DataFrame(columns=cols)
        recs = pt_ws.get_all_records()
        df_t = pd.DataFrame(recs) if recs else pd.DataFrame(columns=cols)
        for c in cols:
            if c not in df_t.columns:
                df_t[c] = ""
        return df_t[cols]
    except Exception:
        return pd.DataFrame(columns=cols)

def save_paper_portfolio_df(df_p):
    try:
        pp_ws, _ = init_paper_sheets()
        if pp_ws is not None:
            pp_ws.clear()
            df_clean = df_p.fillna("")
            pp_ws.update([df_clean.columns.values.tolist()] + df_clean.values.tolist())
            load_paper_portfolio.clear()
    except Exception:
        pass

def save_paper_tradebook_df(df_t):
    try:
        _, pt_ws = init_paper_sheets()
        if pt_ws is not None:
            df_clean = df_t.dropna(how='all').reset_index(drop=True).fillna("")
            pt_ws.clear()
            pt_ws.update([df_clean.columns.values.tolist()] + df_clean.values.tolist())
            load_paper_tradebook.clear()
    except Exception:
        pass

def _sync_chart_trades_to_sheet():
    """_SS['chart_trades'] lo unna active trades annitini Google Sheet Paper_Portfolio lo save chestundi"""
    rows = []
    for f_sym, tr in _SS['chart_trades'].items():
        rows.append({
            "Symbol": str(f_sym).replace(".NS", ""),
            "Side": tr.get("side", "BUY"),
            "Prod": tr.get("prod", "INTRADAY"),
            "Quantity": int(tr.get("qty", 1)),
            "Entry_Price": round(float(tr.get("entry", 0)), 2),
            "SL": round(float(tr.get("sl", 0)), 2),
            "Target": round(float(tr.get("target", 0)), 2),
            "Date_Time": str(tr.get("time", "")),
            "Mode": str(tr.get("mode", "📝 Paper Trading"))
        })
    cols = ["Symbol", "Side", "Prod", "Quantity", "Entry_Price", "SL", "Target", "Date_Time", "Mode"]
    save_paper_portfolio_df(pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols))

# Startup lo Google Sheet nundi active paper trades chart meedaki load cheyadam
if not _SS['paper_loaded']:
    try:
        _df_init_pp = load_paper_portfolio()
        if not _df_init_pp.empty:
            for _, _r in _df_init_pp.iterrows():
                _s_clean = str(_r.get("Symbol", "")).strip().upper()
                if not _s_clean:
                    continue
                _f_sym = _s_clean if (_s_clean.startswith("^") or "=" in _s_clean or _s_clean.endswith(".NS")) else f"{_s_clean}.NS"
                _SS['chart_trades'][_f_sym] = {
                    'side': str(_r.get("Side", "BUY")).upper(),
                    'prod': str(_r.get("Prod", "INTRADAY")).upper(),
                    'qty': int(float(_r.get("Quantity", 10) or 10)),
                    'entry': round(float(_r.get("Entry_Price", 0) or 0), 2),
                    'sl': round(float(_r.get("SL", 0) or 0), 2),
                    'target': round(float(_r.get("Target", 0) or 0), 2),
                    'time': str(_r.get("Date_Time", "-")),
                    'mode': str(_r.get("Mode", "📝 Paper Trading"))
                }
    except Exception:
        pass
    _SS['paper_loaded'] = True

def _place_dhan_free_order(clean_sym, side, qty, prod_type="INTRADAY", sl_p=0.0, tg_p=0.0, use_super=False, order_type="MARKET", limit_p=0.0):
    """Dhan Orders API (/v2/orders) leda Super Order API (/v2/super/orders) dwara MARKET leda LIMIT order vestundi"""
    cid, tok = _dhan_creds()
    if not cid or not tok:
        return False, "secrets.toml lo [dhan] client_id / access_token ledu! (Paper Trade matrame save ayyindi)", "", False
    s_map = get_dhan_security_map()
    sec_id = s_map.get(clean_sym)
    if not sec_id:
        return False, f"Dhan Scrip Master lo '{clean_sym}' securityId dorkaledu", "", False

    dhan_prod = "INTRADAY" if prod_type == "INTRADAY" else "CNC"
    dhan_otype = "LIMIT" if (str(order_type).upper() == "LIMIT" and limit_p > 0) else "MARKET"
    dhan_price = round(float(limit_p), 2) if dhan_otype == "LIMIT" else 0
    corr_id = f"st_{int(time.time())}"

    # 1. Try Dhan Super Order API (Entry + Target + SL together)
    if use_super and sl_p > 0 and tg_p > 0:
        super_payload = {
            "dhanClientId": str(cid),
            "correlationId": corr_id,
            "transactionType": side,
            "exchangeSegment": "NSE_EQ",
            "productType": dhan_prod,
            "orderType": dhan_otype,
            "securityId": str(sec_id),
            "quantity": int(qty),
            "price": dhan_price,
            "targetPrice": round(float(tg_p), 2),
            "stopLossPrice": round(float(sl_p), 2),
            "trailingJump": 0
        }
        try:
            rs = requests.post(f"{DHAN_REST}/super/orders", json=super_payload, headers=_dhan_headers(cid, tok), timeout=8)
            js = rs.json() if rs.content else {}
            if rs.status_code in (200, 201) and js.get("orderId"):
                oid = str(js.get("orderId"))
                return True, f"✅ Dhan Super {dhan_otype} Order Placed! ID: {oid}", oid, True
        except Exception:
            pass

    # 2. Standard Dhan v2 Order (/v2/orders) — Supports MARKET & LIMIT
    payload = {
        "dhanClientId": str(cid),
        "correlationId": corr_id,
        "transactionType": side,
        "exchangeSegment": "NSE_EQ",
        "productType": dhan_prod,
        "orderType": dhan_otype,
        "validity": "DAY",
        "securityId": str(sec_id),
        "quantity": int(qty),
        "disclosedQuantity": 0,
        "price": dhan_price,
        "triggerPrice": 0,
        "afterMarketOrder": False,
        "amoTime": "OPEN",
        "boProfitValue": 0,
        "boStopLossValue": 0
    }
    try:
        r = requests.post(f"{DHAN_REST}/orders", json=payload, headers=_dhan_headers(cid, tok), timeout=8)
        j = r.json() if r.content else {}
        if r.status_code in (200, 201) and j.get("orderId"):
            oid = str(j.get("orderId"))
            return True, f"✅ Dhan {dhan_otype} Order Placed! ID: {oid} ({j.get('orderStatus', 'TRANSIT')})", oid, False
        err_msg = j.get("errorMessage") or j.get("internalErrorMessage") or _dhan_classify(r.status_code, r.text, j)
        return False, f"⚠️ Dhan Rejected: {err_msg}", "", False
    except Exception as e:
        return False, f"⚠️ Network error: {e}", "", False


def _modify_dhan_order_or_super(order_id, is_super, new_ent=0.0, new_sl=0.0, new_tg=0.0, qty=1, order_type="LIMIT"):
    """Chart meeda Buy Price (LIMIT), SL leda Target marchinappudu Dhan App lo modify chestundi"""
    cid, tok = _dhan_creds()
    if not cid or not tok or not order_id:
        return False, "No active Dhan Order ID"

    headers = _dhan_headers(cid, tok)
    dhan_otype = "LIMIT" if (str(order_type).upper() == "LIMIT" and new_ent > 0) else "MARKET"

    if is_super:
        url = f"{DHAN_REST}/super/orders/{order_id}"
        msgs = []
        ok_any = False

        # Modify ENTRY_LEG (if pending, updates Limit Price + SL + Target together)
        if new_ent > 0:
            ent_payload = {
                "dhanClientId": str(cid),
                "orderId": str(order_id),
                "legName": "ENTRY_LEG",
                "orderType": dhan_otype,
                "quantity": int(qty),
                "price": round(float(new_ent), 2) if dhan_otype == "LIMIT" else 0,
                "stopLossPrice": round(float(new_sl), 2) if new_sl > 0 else 0,
                "targetPrice": round(float(new_tg), 2) if new_tg > 0 else 0,
                "trailingJump": 0
            }
            try:
                r_ent = requests.put(url, json=ent_payload, headers=headers, timeout=8)
                if r_ent.status_code in (200, 201, 202):
                    ok_any = True
                    msgs.append(f"Entry({dhan_otype})→₹{new_ent:.2f}")
            except Exception:
                pass

        if new_sl > 0:
            sl_payload = {
                "dhanClientId": str(cid),
                "orderId": str(order_id),
                "legName": "STOP_LOSS_LEG",
                "stopLossPrice": round(float(new_sl), 2),
                "trailingJump": 0
            }
            try:
                r_sl = requests.put(url, json=sl_payload, headers=headers, timeout=8)
                if r_sl.status_code in (200, 201, 202):
                    ok_any = True
                    msgs.append(f"SL→₹{new_sl:.2f}")
            except Exception:
                pass

        if new_tg > 0:
            tg_payload = {
                "dhanClientId": str(cid),
                "orderId": str(order_id),
                "legName": "TARGET_LEG",
                "targetPrice": round(float(new_tg), 2)
            }
            try:
                r_tg = requests.put(url, json=tg_payload, headers=headers, timeout=8)
                if r_tg.status_code in (200, 201, 202):
                    ok_any = True
                    msgs.append(f"TGT→₹{new_tg:.2f}")
            except Exception:
                pass

        if ok_any:
            return True, f"✅ Dhan Super Order Modified ({', '.join(msgs)})!"
        return False, "⚠️ Dhan Super Order Modify Failed"
    else:
        # Standard Order Modify (/v2/orders/{order-id}) -> Converts/Updates Pending Order to LIMIT Price
        url = f"{DHAN_REST}/orders/{order_id}"
        mod_payload = {
            "dhanClientId": str(cid),
            "orderId": str(order_id),
            "orderType": dhan_otype,
            "legName": "ENTRY_LEG",
            "quantity": int(qty),
            "price": round(float(new_ent), 2) if dhan_otype == "LIMIT" else 0,
            "disclosedQuantity": 0,
            "triggerPrice": 0,
            "validity": "DAY"
        }
        try:
            r_m = requests.put(url, json=mod_payload, headers=headers, timeout=8)
            if r_m.status_code in (200, 201, 202):
                return True, f"✅ Dhan Order Modified to {dhan_otype} @ ₹{new_ent:.2f}!"
        except Exception as e:
            return False, f"⚠️ Modify err: {e}"
        return False, "⚠️ Dhan Order already traded or cannot be modified"


def _toggle_trade_prod():
    cur = _UI.get('trade_prod', 'INTRADAY')
    _UI['trade_prod'] = 'CNC' if cur == 'INTRADAY' else 'INTRADAY'


def _update_chart_sl_tg(fetch_sym, new_ent, new_sl, new_tg, order_type="LIMIT"):
    if fetch_sym in _SS['chart_trades']:
        tr = _SS['chart_trades'][fetch_sym]
        old_ent = float(tr.get('entry', 0))
        if new_ent > 0:
            if abs(new_ent - old_ent) >= 0.01:
                tr['order_type'] = "LIMIT"
            tr['entry'] = round(float(new_ent), 2)
        if order_type in ("LIMIT", "MARKET"):
            tr['order_type'] = order_type
        if new_sl > 0:
            tr['sl'] = round(float(new_sl), 2)
        if new_tg > 0:
            tr['target'] = round(float(new_tg), 2)

        tr['mode'] = f"{_UI.get('trade_mode', '📝 Paper Trading')} ({tr.get('order_type', 'MARKET')})"
        _sync_chart_trades_to_sheet()

        clean_sym = str(fetch_sym).replace(".NS", "")
        mode = _UI.get('trade_mode', "📝 Paper Trading")
        oid = tr.get('order_id', '')
        otype_now = tr.get('order_type', 'LIMIT')

        if "Dhan" in mode:
            if oid:
                ok, d_msg = _modify_dhan_order_or_super(
                    oid, tr.get('is_super', False),
                    new_ent=tr['entry'], new_sl=tr['sl'], new_tg=tr['target'],
                    qty=tr.get('qty', 1), order_type=otype_now
                )
                st.toast(f"{d_msg} | Google Sheets Updated!", icon="🚀" if ok else "⚠️")
            else:
                # Place fresh LIMIT order in Dhan at the moved Entry Price
                use_sup = "Super" in mode
                ok, d_msg, new_oid, is_sup = _place_dhan_free_order(
                    clean_sym, tr.get('side', 'BUY'), tr.get('qty', 1),
                    tr.get('prod', 'INTRADAY'), tr['sl'], tr['target'],
                    use_super=use_sup, order_type=otype_now, limit_p=tr['entry']
                )
                tr['order_id'] = new_oid
                tr['is_super'] = is_sup
                st.toast(f"{d_msg} | Saved to Google Sheets!", icon="🟢" if ok else "⚠️")
        else:
            st.toast(
                f"💾 Saved [{otype_now}] Entry: ₹{tr['entry']:.2f} | SL: ₹{tr['sl']:.2f} | TGT: ₹{tr['target']:.2f} to Google Sheets!",
                icon="✅"
            )


def _exec_chart_trade(fetch_sym, side, ltp_p, sl_p, tg_p):
    clean_sym = str(fetch_sym).replace(".NS", "")
    qty = max(1, int(_UI.get('trade_qty', 10)))
    mode = _UI.get('trade_mode', "📝 Paper Trading")
    prod_type = _UI.get('trade_prod', "INTRADAY")
    prod_label = "INTRADAY" if prod_type == "INTRADAY" else "LONGTERM (CNC)"
    now_str = now_ist().strftime('%d-%b %I:%M:%S %p')

    if side == "EXIT":
        old_tr = _SS['chart_trades'].pop(fetch_sym, None)
        _sync_chart_trades_to_sheet()
        if old_tr:
            t_side = old_tr.get('side', 'BUY')
            t_qty = int(old_tr.get('qty', qty))
            t_ent = float(old_tr.get('entry', ltp_p))
            t_prod = old_tr.get('prod', 'INTRADAY')
            pnl_rs = round(((ltp_p - t_ent) * t_qty) if t_side == "BUY" else ((t_ent - ltp_p) * t_qty), 2)
            pnl_pct = round((((ltp_p - t_ent) / t_ent * 100.0) if t_side == "BUY" else ((t_ent - ltp_p) / t_ent * 100.0)), 2) if t_ent > 0 else 0.0

            df_tb = load_paper_tradebook()
            new_closed = pd.DataFrame([{
                "Entry_Time": old_tr.get('time', '-'),
                "Exit_Time": now_str,
                "Symbol": clean_sym,
                "Side": t_side,
                "Prod": t_prod,
                "Quantity": t_qty,
                "Entry_Price": t_ent,
                "Exit_Price": round(float(ltp_p), 2),
                "PnL_Rs": pnl_rs,
                "PnL_Pct": pnl_pct,
                "Mode": old_tr.get('mode', mode)
            }])
            save_paper_tradebook_df(pd.concat([df_tb, new_closed], ignore_index=True))

            if "Dhan" in mode:
                opp_side = "SELL" if t_side == "BUY" else "BUY"
                ok, msg, _, _ = _place_dhan_free_order(clean_sym, opp_side, t_qty, t_prod)
                st.toast(f"EXIT {clean_sym} (PnL: ₹{pnl_rs:+,.2f}): {msg}", icon="✅" if ok else "⚠️")
            else:
                st.toast(f"🏳️ Closed {clean_sym} @ ₹{ltp_p:.2f} | PnL: ₹{pnl_rs:+,.2f} ({pnl_pct:+.2f}%) saved to Google Sheets!", icon="📊")
        return

    oid, is_sup = "", False
    if "Dhan" in mode:
        use_sup = "Super" in mode
        ok, msg, oid, is_sup = _place_dhan_free_order(clean_sym, side, qty, prod_type, sl_p, tg_p, use_super=use_sup, order_type="MARKET", limit_p=ltp_p)
        st.toast(f"{side} [{prod_label}] {clean_sym} ({qty} Qty): {msg}", icon="🟢" if ok else "⚠️")
    else:
        st.toast(f"📝 Paper {side} [{prod_label}] {clean_sym} ({qty} Qty @ ₹{ltp_p:.2f}) saved to Google Sheets!", icon="🚀")

    _SS['chart_trades'][fetch_sym] = {
        'side': side,
        'qty': qty,
        'prod': prod_type,
        'order_type': 'MARKET',
        'entry': round(float(ltp_p), 2),
        'sl': round(float(sl_p), 2),
        'target': round(float(tg_p), 2),
        'time': now_str,
        'mode': f"{mode} (MARKET)",
        'order_id': oid,
        'is_super': is_sup
    }
    _sync_chart_trades_to_sheet()

def _on_trade_cfg_change():
    _UI['trade_qty'] = int(st.session_state.get('tr_qty_key', 10))
    _UI['trade_mode'] = st.session_state.get('tr_mode_key', "📝 Paper Trading")

def render_paper_trading_terminal(df_all_stocks):
    """Renders Dedicated Paper Trading Page (Active Positions + Closed TradeBook from Google Sheets)"""
    df_pp = load_paper_portfolio()
    df_pt = load_paper_tradebook()
    lu = {}
    if df_all_stocks is not None and not df_all_stocks.empty:
        lu = df_all_stocks.drop_duplicates(subset=['T']).set_index('T')['P'].to_dict()

    tot_inv, tot_cur, tot_unreal = 0.0, 0.0, 0.0
    active_rows_html = ""
    for i, (_, r) in enumerate(df_pp.iterrows()):
        sym = str(r.get('Symbol', '')).upper().strip()
        if not sym:
            continue
        side = str(r.get('Side', 'BUY')).upper()
        prod = str(r.get('Prod', 'INTRADAY')).upper()
        try: qty = int(float(r.get('Quantity', 1)))
        except: qty = 1
        try: ent = float(r.get('Entry_Price', 0))
        except: ent = 0.0
        try: sl_v = float(r.get('SL', 0))
        except: sl_v = 0.0
        try: tg_v = float(r.get('Target', 0))
        except: tg_v = 0.0
        dt_str = str(r.get('Date_Time', '-'))
        mode_str = str(r.get('Mode', '📝 Paper'))

        ltp = float(lu.get(sym, ent) or ent)
        inv = ent * qty
        cur_val = ltp * qty
        pnl_rs = ((ltp - ent) * qty) if side == "BUY" else ((ent - ltp) * qty)
        pnl_pct = (pnl_rs / inv * 100.0) if inv > 0 else 0.0

        tot_inv += inv
        tot_cur += cur_val
        tot_unreal += pnl_rs

        bg = "row-dark" if i % 2 == 0 else "row-light"
        s_col = "text-green" if side == "BUY" else "text-red"
        p_col = "text-green" if pnl_rs >= 0 else "text-red"
        p_sign = "+" if pnl_rs > 0 else ""

        active_rows_html += (
            f"<tr class='{bg}'>"
            f"<td class='t-symbol'><a href='?grid_sym={sym}.NS' target='_self'>{sym} 📌</a></td>"
            f"<td>{dt_str}</td>"
            f"<td class='{s_col}'>{side}</td>"
            f"<td style='color:#38bdf8;font-weight:bold;'>{prod}</td>"
            f"<td>{qty}</td>"
            f"<td>₹{ent:.2f}</td>"
            f"<td style='color:#ffd700;font-weight:bold;'>₹{ltp:.2f}</td>"
            f"<td style='color:#f85149;font-weight:bold;'>₹{sl_v:.2f}</td>"
            f"<td style='color:#3fb950;font-weight:bold;'>₹{tg_v:.2f}</td>"
            f"<td class='{p_col}'>{p_sign}₹{pnl_rs:,.2f}</td>"
            f"<td class='{p_col}'>{p_sign}{pnl_pct:.2f}%</td>"
            f"<td style='font-size:10px;color:#8b949e;'>{mode_str}</td>"
            f"</tr>"
        )

    realized_pnl = float(pd.to_numeric(df_pt['PnL_Rs'], errors='coerce').sum()) if not df_pt.empty else 0.0
    net_total_pnl = tot_unreal + realized_pnl

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("📝 Active Capital Used", f"₹{tot_inv:,.0f}")
    k2.metric("📊 Live Open P&L", f"₹{tot_unreal:+,.2f}")
    k3.metric("📜 Realized Paper P&L", f"₹{realized_pnl:+,.2f}")
    k4.metric("🏆 Net Paper P&L", f"₹{net_total_pnl:+,.2f}")

    if active_rows_html:
        st.markdown(
            "<table class='term-table'><thead>"
            "<tr><th colspan='12' class='term-head-port' style='background:#0d47a1;'>📝 ACTIVE PAPER & CHART TRADES (SAVED IN GOOGLE SHEETS: Paper_Portfolio)</th></tr>"
            "<tr style='background:#21262d;'>"
            "<th style='text-align:left;width:10%;'>STOCK</th><th style='width:11%;'>TIME</th><th style='width:6%;'>SIDE</th>"
            "<th style='width:8%;'>TYPE</th><th style='width:5%;'>QTY</th><th style='width:8%;'>ENTRY</th><th style='width:8%;'>LTP</th>"
            "<th style='width:8%;color:#f85149;'>🛑 SL</th><th style='width:8%;color:#3fb950;'>🎯 TGT</th>"
            "<th style='width:9%;'>LIVE P&L</th><th style='width:8%;'>P&L %</th><th style='width:11%;'>MODE</th>"
            "</tr></thead><tbody>" + active_rows_html + "</tbody></table>",
            unsafe_allow_html=True
        )
        ec1, ec2 = st.columns([3, 1])
        with ec1:
            exit_pick = st.selectbox("Select Active Trade to Square-Off / Exit:", ["-- Select Stock --"] + df_pp['Symbol'].tolist(), key="pp_exit_sel", label_visibility="collapsed")
        with ec2:
            if st.button("🏳️ Square-Off Selected Trade", width="stretch", key="pp_exit_btn") and exit_pick != "-- Select Stock --":
                f_s = f"{exit_pick}.NS"
                cur_p = float(lu.get(exit_pick, 0) or _SS['chart_trades'].get(f_s, {}).get('entry', 0))
                _exec_chart_trade(f_s, "EXIT", cur_p, 0, 0)
                st.rerun(scope="fragment")
    else:
        st.info("📝 No active paper trades right now. Open any chart in Grid (1, 2, 4, 6) and click BUY or SELL!")

    with st.expander("📜 Closed Paper Trades Ledger (Google Sheet: Paper_TradeBook)", expanded=True):
        if not df_pt.empty:
            st.dataframe(df_pt.iloc[::-1], use_container_width=True, hide_index=True)
            if st.button("🗑️ Clear Closed Paper TradeBook", key="clr_pt_btn"):
                save_paper_tradebook_df(pd.DataFrame(columns=df_pt.columns))
                st.rerun(scope="fragment")
        else:
            st.caption("No closed paper trades yet.")

def _back_to_mini_charts():
    st.session_state.grid_layout_mode = "Off"
    st.session_state.pro_grid_radio_key = "Off"
    _UI['grid_layout_mode'] = "Off"

def _clear_all_pro_charts():
    st.session_state.pinned_stocks = []
    _UI['pinned_stocks'] = []
    st.session_state.grid_layout_mode = "Off"
    st.session_state.pro_grid_radio_key = "Off"
    _UI['grid_layout_mode'] = "Off"

def _on_pro_theme_change():
    _UI['pro_grid_theme'] = st.session_state.get('pro_theme_sel_key', 'Light (White)')
    st.session_state.pro_grid_theme = _UI['pro_grid_theme']

def _close_pro_chart(s_ft, current_grid_syms):
    active_list = list(st.session_state.pinned_stocks)
    if not active_list and current_grid_syms:
        active_list = list(current_grid_syms)
    if s_ft in active_list:
        active_list.remove(s_ft)
    st.session_state.pinned_stocks = active_list
    _UI['pinned_stocks'] = list(active_list)
    new_mode = _calc_grid_mode(len(active_list))
    st.session_state.grid_layout_mode = new_mode
    st.session_state.pro_grid_radio_key = new_mode
    _UI['grid_layout_mode'] = new_mode

def _on_pin_checkbox_change(fetch_sym, display_sym, cb_key):
    pin_val = st.session_state.get(cb_key, False)
    if pin_val:
        if fetch_sym not in st.session_state.pinned_stocks:
            if len(st.session_state.pinned_stocks) >= 6:
                st.session_state.pinned_stocks.pop(0)
            st.session_state.pinned_stocks.append(fetch_sym)
        st.session_state.inspected_stock = display_sym
        _UI['inspected_stock'] = display_sym
    else:
        if fetch_sym in st.session_state.pinned_stocks:
            st.session_state.pinned_stocks.remove(fetch_sym)
    _UI['pinned_stocks'] = list(st.session_state.pinned_stocks)
    new_mode = _calc_grid_mode(len(st.session_state.pinned_stocks))
    st.session_state.grid_layout_mode = new_mode
    st.session_state.pro_grid_radio_key = new_mode
    _UI['grid_layout_mode'] = new_mode

def _set_wl_sort(col_name):
    if st.session_state.wl_sort_col == col_name:
        st.session_state.wl_sort_asc = not st.session_state.wl_sort_asc
    else:
        st.session_state.wl_sort_col = col_name
        st.session_state.wl_sort_asc = True if col_name == "Symbol" else False
    _UI['wl_sort_col'] = st.session_state.wl_sort_col
    _UI['wl_sort_asc'] = st.session_state.wl_sort_asc

def _on_filter_sort_change():
    st.session_state.wl_sort_col = None
    _UI['wl_sort_col'] = None
    _UI['sort_mode'] = st.session_state.get('main_sort_sel', 'Score Wise Up ⭐')

def _on_grid_radio_change():
    sel_g = st.session_state.get('pro_grid_radio_key', 'Off')
    st.session_state.grid_layout_mode = sel_g
    _UI['grid_layout_mode'] = sel_g


# --- MINI-CHART GRID & SINGLE CHART (WITH TICK ON ALL INDICES, VOL BARS & 12-HOUR IST TIME) ---
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
                    show_pin=True,
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

    strat_tag = f" <span style='font-size:9.5px; background:rgba(0,191,255,0.2); border:1px solid #00BFFF; padding:0px 3px; border-radius:3px; color:#00BFFF;'>{row.get('Strategy_Icon', '')}</span>" if row.get('Strategy_Icon') and row.get('Strategy_Icon') != "Neutral" else ""

    if timeframe == "Intraday (5m)":
        day_high, day_low, ltp_now = float(row.get('H', 0)), float(row.get('L', 0)), float(row.get('P', 0))
        if pct_val >= 0:
            intraday_pb = ((day_high - ltp_now) / day_high) * 100 if day_high > 0 else 0
            pb_tag = f" <span style='color:#FF8C00; font-size:10px;'>📉-{intraday_pb:.1f}%</span>" if intraday_pb >= 0.1 else ""
        else:
            intraday_bounce = ((ltp_now - day_low) / day_low) * 100 if day_low > 0 else 0
            pb_tag = f" <span style='color:#00BFFF; font-size:10px;'>📈+{intraday_bounce:.1f}%</span>" if intraday_bounce >= 0.1 else ""
    else:
        pb_val = float(row.get('Pullback_52W', 0))
        pb_tag = f" <span style='color:#FF8C00; font-size:10px;'>📉-{pb_val:.1f}%</span>" if pb_val >= 0.1 else ""

    title_html = (
        f"<a href='{tv_link}' target='_blank' style='color:#ffffff; text-decoration:none; line-height:1.15;'>"
        f"<b>{display_sym}</b>{strat_tag}<br>"
        f"<span style='font-size:11px; color:#cccccc;'>₹{row['P']:.2f} "
        f"<span style='color:{color_hex};'>({sign}{pct_val:.2f}%)</span>{pb_tag}</span></a>"
    )

    try:
        if not df_chart.empty and 'Low' in df_chart.columns and 'High' in df_chart.columns:
            df_chart = _fix_ist_df(df_chart) if timeframe == "Intraday (5m)" else df_chart.copy()

            if timeframe == "Intraday (5m)":
                _sess_id = (df_chart.index.to_series().diff() > pd.Timedelta(minutes=120)).cumsum()
                df_chart = df_chart[_sess_id == _sess_id.iloc[-1]].copy()

                if not df_chart.empty and float(row.get('P', 0)) > 0:
                    _live_p = float(row['P'])
                    _last_i = df_chart.index[-1]
                    df_chart.at[_last_i, 'Close'] = _live_p
                    if _live_p > float(df_chart.at[_last_i, 'High']):
                        df_chart.at[_last_i, 'High'] = _live_p
                    if _live_p < float(df_chart.at[_last_i, 'Low']) or float(df_chart.at[_last_i, 'Low']) <= 0:
                        df_chart.at[_last_i, 'Low'] = _live_p

            _y_lows = [float(df_chart['Low'].min())]
            _y_highs = [float(df_chart['High'].max())]
            if 'VWAP' in df_chart.columns and not df_chart['VWAP'].dropna().empty:
                _y_lows.append(float(df_chart['VWAP'].min()))
                _y_highs.append(float(df_chart['VWAP'].max()))
            if 'EMA_10' in df_chart.columns and not df_chart['EMA_10'].dropna().empty:
                _y_lows.append(float(df_chart['EMA_10'].min()))
                _y_highs.append(float(df_chart['EMA_10'].max()))
            min_val, max_val = min(_y_lows), max(_y_highs)
            y_padding = (max_val - min_val) * 0.16 if (max_val - min_val) != 0 else min_val * 0.005

            chart_times = pd.to_datetime(df_chart.index)
            x_labels = chart_times.strftime('%I:%M %p') if timeframe == "Intraday (5m)" else chart_times.strftime('%d-%b')
            n_bars = len(df_chart)
            x_idx = list(range(n_bars))

            hover_data = (
                "🕒 " + chart_times.strftime('%d-%b %I:%M %p IST') +
                "<br>O: ₹" + df_chart['Open'].round(2).astype(str) +
                " | H: ₹" + df_chart['High'].round(2).astype(str) +
                "<br>L: ₹" + df_chart['Low'].round(2).astype(str) +
                " | C: ₹" + df_chart['Close'].round(2).astype(str)
            )

            rc = dict(row=1, col=1) if show_vol else dict()
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.02, row_heights=[0.75, 0.25]) if show_vol else go.Figure()

            if 'Volume' in df_chart.columns:
                vol_sma = df_chart['Volume'].rolling(window=20, min_periods=1).mean()
                hv_mask = df_chart['Volume'] > (vol_sma * 1.618)
                vwap_s = df_chart.get('VWAP', pd.Series(0, index=df_chart.index))
                ema10_s = df_chart.get('EMA_10', pd.Series(0, index=df_chart.index))
                bull = df_chart['Close'] >= df_chart['Open']
                bear = df_chart['Close'] < df_chart['Open']
                mask_hv_bull = (hv_mask & (df_chart['Close'] > vwap_s) & (df_chart['Close'] > ema10_s) & bull).fillna(False)
                mask_hv_bear = (hv_mask & (df_chart['Close'] < vwap_s) & (df_chart['Close'] < ema10_s) & bear).fillna(False)
            else:
                mask_hv_bull = pd.Series(False, index=df_chart.index)
                mask_hv_bear = pd.Series(False, index=df_chart.index)

            fig.add_trace(go.Candlestick(
                x=x_idx,
                open=df_chart['Open'].tolist(),
                high=df_chart['High'].tolist(),
                low=df_chart['Low'].tolist(),
                close=df_chart['Close'].tolist(),
                increasing_line_color='#2ea043', increasing_fillcolor='#2ea043', increasing_line_width=1,
                decreasing_line_color='#da3633', decreasing_fillcolor='#da3633', decreasing_line_width=1,
                showlegend=False, hoverinfo='skip'
            ), **rc)

            if mask_hv_bull.any():
                _b_idx = [i for i, v in enumerate(mask_hv_bull.tolist()) if v]
                _b_df = df_chart[mask_hv_bull]
                fig.add_trace(go.Candlestick(
                    x=_b_idx,
                    open=_b_df['Open'].tolist(),
                    high=_b_df['High'].tolist(),
                    low=_b_df['Low'].tolist(),
                    close=_b_df['Close'].tolist(),
                    increasing_line_color='#00FF00', increasing_fillcolor='#00FF00', increasing_line_width=1.8,
                    decreasing_line_color='#00FF00', decreasing_fillcolor='#00FF00', decreasing_line_width=1.8,
                    showlegend=False, hoverinfo='skip'
                ), **rc)

            if mask_hv_bear.any():
                _s_idx = [i for i, v in enumerate(mask_hv_bear.tolist()) if v]
                _s_df = df_chart[mask_hv_bear]
                fig.add_trace(go.Candlestick(
                    x=_s_idx,
                    open=_s_df['Open'].tolist(),
                    high=_s_df['High'].tolist(),
                    low=_s_df['Low'].tolist(),
                    close=_s_df['Close'].tolist(),
                    increasing_line_color='#FF0000', increasing_fillcolor='#FF0000', increasing_line_width=1.8,
                    decreasing_line_color='#FF0000', decreasing_fillcolor='#FF0000', decreasing_line_width=1.8,
                    showlegend=False, hoverinfo='skip'
                ), **rc)

            fig.add_trace(go.Scatter(
                x=x_idx, y=df_chart['Close'], mode='lines', line=dict(color='rgba(0,0,0,0)'),
                showlegend=False, hoverinfo='text' if show_crosshair else 'skip',
                text=hover_data, hovertemplate="%{text}<extra></extra>" if show_crosshair else None
            ), **rc)

            if timeframe == "Daily Chart":
                if 'SMA_50' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_50'], mode='lines', line=dict(color='#FFD700', width=1.3), showlegend=False, hoverinfo='skip'), **rc)
                if 'SMA_150' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_150'], mode='lines', line=dict(color='#00BFFF', width=1.3, dash='dash'), showlegend=False, hoverinfo='skip'), **rc)
                if 'SMA_200' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_200'], mode='lines', line=dict(color='#FF4500', width=1.6), showlegend=False, hoverinfo='skip'), **rc)
            elif timeframe == "Weekly Chart":
                if 'SMA_10' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_10'], mode='lines', line=dict(color='#FFD700', width=1.3), showlegend=False, hoverinfo='skip'), **rc)
                if 'SMA_40' in df_chart.columns: fig.add_trace(go.Scatter(x=x_idx, y=df_chart['SMA_40'], mode='lines', line=dict(color='#FF4500', width=1.6), showlegend=False, hoverinfo='skip'), **rc)
            else:
                tag_pos = max(0, int(n_bars * 0.60))
                tag_idx = x_idx[tag_pos]
                last_close = float(df_chart['Close'].iloc[-1])
                has_vwap = 'VWAP' in df_chart.columns
                has_ema = 'EMA_10' in df_chart.columns
                last_vwap = float(df_chart['VWAP'].iloc[-1]) if has_vwap else 0
                last_ema = float(df_chart['EMA_10'].iloc[-1]) if has_ema else 0
                tag_y_vwap = float(df_chart['VWAP'].iloc[tag_pos]) if has_vwap else 0
                tag_y_ema = float(df_chart['EMA_10'].iloc[tag_pos]) if has_ema else 0

                v_anchor = "bottom" if last_close <= last_vwap else "top"
                e_anchor = "bottom" if last_close <= last_ema else "top"
                v_shift = 5 if v_anchor == "bottom" else -5
                e_shift = 5 if e_anchor == "bottom" else -5

                if has_vwap and has_ema and abs(tag_y_vwap - tag_y_ema) / (tag_y_vwap + 0.001) < 0.008:
                    if tag_y_vwap >= tag_y_ema:
                        v_anchor, v_shift = "bottom", 5
                        e_anchor, e_shift = "top", -5
                    else:
                        v_anchor, v_shift = "top", -5
                        e_anchor, e_shift = "bottom", 5

                if has_vwap:
                    fig.add_trace(go.Scatter(x=x_idx, y=df_chart['VWAP'], mode='lines', line=dict(color='#FFD700', width=1.4, dash='dot'), showlegend=False, hoverinfo='skip'), **rc)
                    fig.add_annotation(x=tag_idx, y=tag_y_vwap, text=f"V:{last_vwap:.1f}", showarrow=False, xanchor="right", yanchor=v_anchor, yshift=v_shift, font=dict(color="#161b22", size=8.5, family="monospace", weight="bold"), bgcolor="#FFD700", borderpad=1, **rc)
                if has_ema:
                    fig.add_trace(go.Scatter(x=x_idx, y=df_chart['EMA_10'], mode='lines', line=dict(color='#00BFFF', width=1.4, dash='dash'), showlegend=False, hoverinfo='skip'), **rc)
                    fig.add_annotation(x=tag_idx, y=tag_y_ema, text=f"E:{last_ema:.1f}", showarrow=False, xanchor="right", yanchor=e_anchor, yshift=e_shift, font=dict(color="#161b22", size=8.5, family="monospace", weight="bold"), bgcolor="#00BFFF", borderpad=1, **rc)

            if show_vol and 'Volume' in df_chart.columns:
                vol_colors = [
                    '#00FF00' if mask_hv_bull.iloc[i] else ('#FF0000' if mask_hv_bear.iloc[i] else ('rgba(46, 160, 67, 0.45)' if df_chart['Close'].iloc[i] >= df_chart['Open'].iloc[i] else 'rgba(218, 54, 51, 0.45)'))
                    for i in range(n_bars)
                ]
                fig.add_trace(go.Bar(x=x_idx, y=df_chart['Volume'], marker_color=vol_colors, showlegend=False, hoverinfo='skip'), row=2, col=1)
                fig.update_yaxes(showspikes=False, showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True, row=2, col=1)

            _right_pad = max(3.5, float(n_bars) * 0.065)
            x_full_range = [-0.8, float(n_bars) + _right_pad]

            fig.update_layout(
                autosize=True,
                margin=dict(l=2, r=38 if show_crosshair else 12, t=2, b=16 if show_crosshair else 2),
                height=240 if show_vol else 205,
                paper_bgcolor='#0b0e14', plot_bgcolor='#0b0e14',
                showlegend=False, xaxis_rangeslider_visible=False,
                hovermode='closest' if show_crosshair else False, dragmode=False
            )
            fig.add_annotation(
                text=title_html, xref="paper", yref="paper",
                x=0, xanchor="left", xshift=28, y=0.98, yanchor="top",
                showarrow=False, font=dict(size=11.5, color="#ffffff"),
                bgcolor="rgba(0,0,0,0)", borderwidth=0
            )

            if show_crosshair:
                t_step = max(1, n_bars // 4)
                fig.update_xaxes(
                    range=x_full_range, autorange=False,
                    showspikes=True, spikemode='across+toaxis', spikesnap='cursor', spikethickness=1, spikedash='dash', spikecolor='#8b949e',
                    tickvals=x_idx[::t_step], ticktext=list(x_labels[::t_step]), tickfont=dict(color='#8b949e', size=8.5),
                    showgrid=False, zeroline=False, showticklabels=True, fixedrange=True
                )
                fig.update_yaxes(
                    showspikes=True, spikemode='across+toaxis', spikesnap='cursor', spikethickness=1, spikedash='dash', spikecolor='#8b949e',
                    showgrid=False, zeroline=False, showticklabels=True, side='right', tickfont=dict(color="#ffffff", size=9),
                    fixedrange=True, range=[min_val - y_padding, max_val + (y_padding * 2.6)], **rc
                )
            else:
                fig.update_xaxes(range=x_full_range, autorange=False, showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True)
                fig.update_yaxes(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True, range=[min_val - y_padding, max_val + (y_padding * 2.6)], **rc)

            st.plotly_chart(fig, width="stretch", key=f"plot_{fetch_sym}_{key_suffix}_{timeframe}_{show_vol}_{show_crosshair}")

            # 📰 Render Full-Box News Overlay AFTER Plotly Chart so top stock names are NEVER cut off!
            news_hl = str(row.get('News_Headline', '') or '').strip().replace('\n', ' ')
            if news_hl and news_hl not in ('nan', 'None'):
                if " || " in news_hl:
                    hl_main, hl_dtl = news_hl.split(" || ", 1)
                else:
                    hl_main, hl_dtl = news_hl, ""
                n_cat = _html.escape(str(row.get('News_Cat', '📰 News')))
                n_age = _html.escape(str(row.get('News_Age', '')))
                n_txt = _html.escape(hl_main.strip())
                n_dtl_html = (
                    f"<div style='color:#c9d1d9;font-size:11px;line-height:1.45;margin-top:6px;padding:5px 7px;background:rgba(22,27,34,0.85);border-left:2.5px solid #38bdf8;border-radius:3px;'>"
                    f"🔹 <b>ముఖ్యాంశాలు:</b> {_html.escape(hl_dtl.strip())}</div>"
                    if hl_dtl.strip() else ""
                )
                atr_v = float(row.get('ATR', float(row['P']) * 0.02))
                is_dn = pct_val < 0
                sl_p = float(row.get('SL', (float(row['P']) + 1.5 * atr_v) if is_dn else (float(row['P']) - 1.5 * atr_v)))
                t1_p = float(row.get('T1', (float(row['P']) - 1.5 * atr_v) if is_dn else (float(row['P']) + 1.5 * atr_v)))
                lvls_html = (
                    f"<div style='color:#79c0ff;font-size:10.5px;margin-top:6px;padding:4px 6px;background:rgba(56,189,248,0.08);border-radius:3px;'>"
                    f"📊 <b>Levels:</b> <span style='color:#f87171;'>🛑 SL: ₹{sl_p:.1f}</span> &nbsp;|&nbsp; <span style='color:#4ade80;'>🎯 T1: ₹{t1_p:.1f}</span> &nbsp;|&nbsp; Vol: <b>{float(row.get('VolX', 1.0)):.1f}x</b></div>"
                )
                n_lnk = str(row.get('News_Link', '#') or '#')
                st.markdown(
                    f"<div class='mc-card-news-zone'>"
                    f"<div class='mc-news-trigger' title='Hover to read full news'></div>"
                    f"<div class='mc-full-overlay'>"
                    f"<div style='display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #262c36;padding-bottom:4px;padding-left:22px;flex-shrink:0;'>"
                    f"<b style='color:#fff;font-size:11.5px;'>{display_sym} <span style='color:{color_hex};'>({sign}{pct_val:.2f}%)</span></b>"
                    f"<span style='background:#1e293b;color:#ffd700;font-size:9px;padding:1px 5px;border-radius:4px;border:1px solid #38bdf8;'>{n_cat}</span>"
                    f"</div>"
                    f"<div class='mc-overlay-body'>"
                    f"<div style='color:#f0f6fc;font-size:11.5px;font-weight:700;line-height:1.45;white-space:normal;word-break:break-word;'>📰 {n_txt}</div>"
                    f"{n_dtl_html}{lvls_html}"
                    f"</div>"
                    f"<div style='display:flex;justify-content:space-between;align-items:center;border-top:1px dashed #262c36;padding-top:4px;font-size:10px;flex-shrink:0;'>"
                    f"<span style='color:#79c0ff;font-weight:bold;'>🕒 {n_age}</span>"
                    f"<div>"
                    f"<a href='{tv_link}' target='_blank' style='color:#3fb950;text-decoration:none;font-weight:bold;margin-right:8px;'>📈 TV Chart ↗</a>"
                    f"<a href='{n_lnk}' target='_blank' style='color:#58a6ff;text-decoration:none;font-weight:bold;'>🔗 News Link ↗</a>"
                    f"</div>"
                    f"</div>"
                    f"</div>"
                    f"</div>",
                    unsafe_allow_html=True
                )
    except Exception as e:
        st.markdown(f"<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888;'>Chart error: {e}</div>", unsafe_allow_html=True)


# --- SUPERTREND & PINE SCRIPT V6 HELPERS ---
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

def _wma_series(s, length):
    length = max(2, int(length))
    weights = np.arange(1, length + 1, dtype=float)
    return s.rolling(length, min_periods=1).apply(lambda x: np.dot(x, weights[-len(x):]) / weights[-len(x):].sum(), raw=True)

def _compute_pinescript_suite(df_p):
    """Computes attached Pine Script v6: Swing Ribbon + Breakout + Big Trader + MTF + Avoid Zone + Trend Speed Analyzer"""
    c = df_p['Close'].astype(float)
    o = df_p['Open'].astype(float)
    h = df_p['High'].astype(float)
    l = df_p['Low'].astype(float)
    v = df_p['Volume'].fillna(0.0).astype(float) if 'Volume' in df_p.columns else pd.Series(0.0, index=df_p.index)

    fast_ma = _wma_series(c, 25)
    slow_ma = _wma_series(c, 35)
    fast_d = np.sign(fast_ma.diff(2).fillna(0.0))
    slow_d = np.sign(slow_ma.diff(2).fillna(0.0))
    close_p = c - fast_ma

    rib_colors = []
    for fd, sd, cp in zip(fast_d, slow_d, close_p):
        if fd > 0:
            col = ("#22c55e" if cp > 0 else "#b1c154") if sd > 0 else "#eab308"
        elif fd < 0:
            col = ("#ef4444" if cp < 0 else "#f97316") if sd < 0 else "#eab308"
        else:
            col = "#eab308"
        rib_colors.append(col)

    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    atr20 = tr.ewm(alpha=1/20, adjust=False).mean()
    atr20_sma = atr20.rolling(20, min_periods=5).mean()
    is_comp = atr20 < atr20_sma

    ltf_basis = c.rolling(20, min_periods=5).mean()
    ltf_dev = 0.5 * c.rolling(20, min_periods=5).std().fillna(0.0)
    ltf_upper = ltf_basis + ltf_dev
    ltf_lower = ltf_basis - ltf_dev

    htf_ema21 = c.ewm(span=21 * 6, adjust=False).mean()
    htf_up = c > htf_ema21
    htf_dn = c < htf_ema21
    mtf_ema20 = c.ewm(span=20, adjust=False).mean()
    mtf_ema100 = c.ewm(span=100, adjust=False).mean()
    mtf_ema200 = c.ewm(span=200, adjust=False).mean()

    t_mins = df_p.index.hour * 60 + df_p.index.minute
    in_avoid = ((t_mins >= 555) & (t_mins < 570)) | ((t_mins >= 900) & (t_mins < 930))
    vol_spike = v > (v.rolling(20, min_periods=5).mean() * 2.0)
    near_high = c >= (h.rolling(20, min_periods=5).max() * 0.98)
    near_low = c <= (l.rolling(20, min_periods=5).min() * 1.02)

    turn_buy = vol_spike & near_low & htf_up & (~in_avoid)
    turn_sell = vol_spike & near_high & htf_dn & (~in_avoid)

    max_len = 50.0
    accel_mult = 5.0
    max_abs_c = c.abs().rolling(200, min_periods=1).max().replace(0, 1.0)
    c_norm = (c + max_abs_c) / (2.0 * max_abs_c)
    dyn_len = 5.0 + c_norm * (max_len - 5.0)

    delta_c = c.diff().abs().fillna(0.0)
    max_delta_c = delta_c.rolling(200, min_periods=1).max().replace(0, 1.0)
    accel_fac = delta_c / max_delta_c
    alpha_s = ((2.0 / (dyn_len + 1.0)) * (1.0 + accel_fac * accel_mult)).clip(upper=1.0)

    dyn_ema = np.zeros(len(c))
    c_vals = c.values
    a_vals = alpha_s.values
    for i in range(len(c_vals)):
        dyn_ema[i] = c_vals[i] if i == 0 else (a_vals[i] * c_vals[i] + (1.0 - a_vals[i]) * dyn_ema[i - 1])
    dyn_ema_s = pd.Series(dyn_ema, index=df_p.index)
    wma2 = _wma_series(c, 2)
    dyn_col = np.where(wma2 > dyn_ema_s, "#00ff00", "#ff0000")

    c_rma = c.ewm(alpha=1/10, adjust=False).mean().values
    o_rma = o.ewm(alpha=1/10, adjust=False).mean().values
    speed_arr = np.zeros(len(c_vals))
    bull_waves, bear_waves = [], []
    cur_spd = 0.0
    for i in range(len(c_vals)):
        if i > 0:
            if c_vals[i] > dyn_ema[i] and c_vals[i - 1] <= dyn_ema[i - 1]:
                if cur_spd < 0: bear_waves.append(abs(cur_spd))
                cur_spd = c_rma[i] - o_rma[i]
            elif c_vals[i] < dyn_ema[i] and c_vals[i - 1] >= dyn_ema[i - 1]:
                if cur_spd > 0: bull_waves.append(abs(cur_spd))
                cur_spd = c_rma[i] - o_rma[i]
        cur_spd += (c_rma[i] - o_rma[i])
        speed_arr[i] = cur_spd

    spd_s = pd.Series(speed_arr, index=df_p.index)
    min_spd = spd_s.rolling(100, min_periods=5).min()
    max_spd = spd_s.rolling(100, min_periods=5).max()
    norm_spd = ((spd_s - min_spd) / (max_spd - min_spd).replace(0, 1.0)).fillna(0.5)
    spd_colors = [
        ("#00ff00" if ns > 0.75 else "#82ffc3") if sp >= 0 else ("#ff0000" if ns < 0.25 else "#f78c8c")
        for sp, ns in zip(speed_arr, norm_spd)
    ]

    bull_avg = float(np.mean(bull_waves[-100:])) if bull_waves else 1.0
    bear_avg = float(np.mean(bear_waves[-100:])) if bear_waves else 1.0
    bull_max = float(np.max(bull_waves[-100:])) if bull_waves else 1.0
    bear_max = float(np.max(bear_waves[-100:])) if bear_waves else 1.0
    cur_w = float(speed_arr[-1]) if len(speed_arr) > 0 else 0.0
    cur_rat_avg = round(cur_w / (bull_avg if cur_w >= 0 else bear_avg), 2)
    cur_rat_max = round(cur_w / (bull_max if cur_w >= 0 else bear_max), 2)
    dom_avg_ratio = round(bull_avg / max(bear_avg, 0.001), 2) if bull_avg >= bear_avg else round(bear_avg / max(bull_avg, 0.001), 2)
    dom_avg_txt = f"Bullish +{dom_avg_ratio}x" if bull_avg >= bear_avg else f"Bearish -{dom_avg_ratio}x"
    dom_col = "#00ff00" if bull_avg >= bear_avg else "#ff4d4d"

    return {
        'fast_ma': fast_ma, 'slow_ma': slow_ma, 'rib_col': rib_colors,
        'ltf_up': ltf_upper, 'ltf_lo': ltf_lower, 'ltf_mid': ltf_basis,
        'mtf20': mtf_ema20, 'mtf100': mtf_ema100, 'mtf200': mtf_ema200,
        'turn_buy': turn_buy, 'turn_sell': turn_sell,
        'dyn_ema': dyn_ema_s, 'dyn_col': dyn_col, 'spd_col': spd_colors,
        'wave_tbl': {'rat_avg': f"{cur_rat_avg}x", 'rat_max': f"{cur_rat_max}x", 'dom': dom_avg_txt, 'col': dom_col}
    }


# --- PRO GRID CHART ENGINE (DRAGGABLE BUY/SELL LIMIT LINE + SL/TGT + FREEHAND FIBONACCI) ---
def render_pro_grid_chart(fetch_sym, row_data, df_c, timeframe, theme_mode, active_inds, chart_height=330, key_idx=0, current_grid_syms=None):
    disp_sym = row_data.get('T', fetch_sym.replace('.NS', ''))
    tf_short = "5m (5D)" if timeframe == "Intraday (5m)" else ("1D" if timeframe == "Daily Chart" else "1W")
    ltp_v = float(row_data.get('P', 0))
    chg_v = float(row_data.get('Day_C', 0))
    c_col = "#4ade80" if chg_v >= 0 else "#f87171"
    if current_grid_syms is None:
        current_grid_syms = []

    # Check if JS sent updated Entry (LIMIT) / SL / TGT via query_params
    if "upd_sltg" in st.query_params:
        try:
            _parts = str(st.query_params["upd_sltg"]).split("|")
            st.query_params.clear()
            if len(_parts) >= 5:
                _u_sym, _u_ent, _u_sl, _u_tg, _u_ot = _parts[0], float(_parts[1]), float(_parts[2]), float(_parts[3]), _parts[4]
                _update_chart_sl_tg(_u_sym, _u_ent, _u_sl, _u_tg, _u_ot)
            elif len(_parts) == 3:
                _u_sym, _u_sl, _u_tg = _parts[0], float(_parts[1]), float(_parts[2])
                _update_chart_sl_tg(_u_sym, 0.0, _u_sl, _u_tg, "MARKET")
        except Exception:
            pass

    prod_mode = _UI.get('trade_prod', 'INTRADAY')
    prod_badge_txt = "⚡ INTRADAY" if prod_mode == "INTRADAY" else "📦 LONGTERM"
    prod_badge_col = "#0284c7" if prod_mode == "INTRADAY" else "#7c3aed"

    atr_v = float(row_data.get('ATR', 0))
    if atr_v <= 0:
        atr_v = max(ltp_v * 0.01, 1.0)
    risk_pts = round(max(atr_v * 1.2, ltp_v * 0.005), 2)
    rew_pts = round(risk_pts * 2.0, 2)

    buy_sl, buy_tg = round(ltp_v - risk_pts, 2), round(ltp_v + rew_pts, 2)
    sell_sl, sell_tg = round(ltp_v + risk_pts, 2), round(ltp_v - rew_pts, 2)

    close_token = f"CLOSE_{fetch_sym}_{key_idx}"
    buy_token = f"BUY_{fetch_sym}_{key_idx}"
    sell_token = f"SELL_{fetch_sym}_{key_idx}"
    exit_token = f"EXIT_{fetch_sym}_{key_idx}"
    prod_token = f"PROD_{fetch_sym}_{key_idx}"

    st.markdown("<div class='hidden-close-trigger'></div>", unsafe_allow_html=True)
    st.button(close_token, key=f"close_x_{fetch_sym}_{key_idx}", on_click=_close_pro_chart, args=(fetch_sym, current_grid_syms))

    st.markdown("<div class='hidden-close-trigger'></div>", unsafe_allow_html=True)
    st.button(buy_token, key=f"buy_btn_{fetch_sym}_{key_idx}", on_click=_exec_chart_trade, args=(fetch_sym, "BUY", ltp_v, buy_sl, buy_tg))

    st.markdown("<div class='hidden-close-trigger'></div>", unsafe_allow_html=True)
    st.button(sell_token, key=f"sell_btn_{fetch_sym}_{key_idx}", on_click=_exec_chart_trade, args=(fetch_sym, "SELL", ltp_v, sell_sl, sell_tg))

    st.markdown("<div class='hidden-close-trigger'></div>", unsafe_allow_html=True)
    st.button(exit_token, key=f"exit_btn_{fetch_sym}_{key_idx}", on_click=_exec_chart_trade, args=(fetch_sym, "EXIT", ltp_v, 0, 0))

    st.markdown("<div class='hidden-close-trigger'></div>", unsafe_allow_html=True)
    st.button(prod_token, key=f"prod_btn_{fetch_sym}_{key_idx}", on_click=_toggle_trade_prod)

    if df_c is None or df_c.empty:
        st.info(f"⏳ Loading chart data for {disp_sym}...")
        return

    df_p = _fix_ist_df(df_c) if timeframe == "Intraday (5m)" else df_c.dropna(subset=['Open', 'High', 'Low', 'Close']).copy()
    df_p = df_p.tail(375 if timeframe == "Intraday (5m)" else 500).copy()
    if df_p.empty:
        st.info(f"No valid candles for {disp_sym}")
        return

    # 🔥 Sync Live LTP (ltp_v) into the Last Candle every 30s so Candle & Indicators move live!
    if ltp_v > 0:
        _last_idx = df_p.index[-1]
        df_p.at[_last_idx, 'Close'] = ltp_v
        if ltp_v > float(df_p.at[_last_idx, 'High']):
            df_p.at[_last_idx, 'High'] = ltp_v
        if ltp_v < float(df_p.at[_last_idx, 'Low']) or float(df_p.at[_last_idx, 'Low']) <= 0:
            df_p.at[_last_idx, 'Low'] = ltp_v

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

    pine_res = _compute_pinescript_suite(df_p)

    ph = float(row_data.get('Prev_H', df_p['High'].max()))
    pl = float(row_data.get('Prev_L', df_p['Low'].min()))
    pc = float(row_data.get('Prev_C', df_p['Close'].iloc[0]))
    piv = round((ph + pl + pc) / 3.0, 2)
    r1 = round(2 * piv - pl, 2)
    s1 = round(2 * piv - ph, 2)
    sr_high = round(float(df_p['High'].max()), 2)
    sr_low = round(float(df_p['Low'].min()), 2)

    active_tr = _SS['chart_trades'].get(fetch_sym)
    pos_js = "null"
    exit_btn_html = ""
    ent_lbl_html = "🔵 BUY:"
    if active_tr:
        t_side = active_tr['side']
        t_qty = int(active_tr['qty'])
        t_prod = active_tr.get('prod', 'INTRADAY')
        t_otype = active_tr.get('order_type', 'MARKET')
        t_ent = float(active_tr['entry'])
        t_sl = float(active_tr['sl'])
        t_tg = float(active_tr['target'])
        ent_lbl_html = "🟢 BUY:" if t_side == "BUY" else "🔴 SELL:"
        pnl_val = (ltp_v - t_ent) * t_qty if t_side == "BUY" else (t_ent - ltp_v) * t_qty
        pnl_pct = ((ltp_v - t_ent) / t_ent * 100.0) if t_side == "BUY" else ((t_ent - ltp_v) / t_ent * 100.0)
        pnl_sign = "+" if pnl_val >= 0 else ""
        pnl_col = "#22c55e" if pnl_val >= 0 else "#ef4444"
        pos_obj = {
            "sym": fetch_sym,
            "side": t_side,
            "prod": "INTRADAY" if t_prod == "INTRADAY" else "LONGTERM",
            "orderType": t_otype,
            "qty": t_qty,
            "entry": t_ent,
            "sl": t_sl,
            "target": t_tg,
            "ltp": ltp_v,
            "pnlVal": round(pnl_val, 2),
            "pnlPct": round(pnl_pct, 2),
            "entryColor": "#38bdf8" if t_otype == "LIMIT" else ("#22c55e" if pnl_val >= 0 else "#f97316")
        }
        pos_js = json.dumps(pos_obj)
        exit_btn_html = (
            f"<span style='background:{pnl_col};color:#fff;padding:0px 5px;border-radius:3px;font-size:9.5px;font-weight:bold;'>"
            f"{pnl_sign}₹{pnl_val:,.1f} ({pnl_sign}{pnl_pct:.1f}%)</span>"
            f"<span class='tr-btn exit-b' onclick=\"exitChartTrade('{fetch_sym}', '{exit_token}')\" title='Exit / Square-Off & Save to Paper_TradeBook'>EXIT</span>"
        )

    candles_js, spd_candles_js, vol_js, vwap_js, ema10_js, ema20_js, kal_js, st_js, bb_u_js, bb_d_js = [], [], [], [], [], [], [], [], [], []
    p_fast_js, p_slow_js, p_up_js, p_lo_js, p_mid_js, mtf20_js, mtf100_js, mtf200_js, dyn_ema_js, markers_js = [], [], [], [], [], [], [], [], [], []
    seen_ts = set()

    for idx_i, (dt_idx, r) in enumerate(df_p.iterrows()):
        ts = int(calendar.timegm(pd.Timestamp(dt_idx).timetuple()))
        if ts in seen_ts:
            continue
        seen_ts.add(ts)
        o, h, l, c = round(float(r['Open']), 2), round(float(r['High']), 2), round(float(r['Low']), 2), round(float(r['Close']), 2)
        v = float(r.get('Volume', 0)) if pd.notna(r.get('Volume', 0)) else 0.0
        candles_js.append({'time': ts, 'open': o, 'high': h, 'low': l, 'close': c})
        sc = pine_res['spd_col'][idx_i]
        spd_candles_js.append({'time': ts, 'open': o, 'high': h, 'low': l, 'close': c, 'color': sc, 'wickColor': sc, 'borderColor': sc})
        vol_js.append({'time': ts, 'value': v, 'color': 'rgba(20, 184, 166, 0.45)' if c >= o else 'rgba(239, 68, 68, 0.45)'})

        if pd.notna(r.get('VWAP')): vwap_js.append({'time': ts, 'value': round(float(r['VWAP']), 2)})
        if pd.notna(r.get('EMA10')): ema10_js.append({'time': ts, 'value': round(float(r['EMA10']), 2)})
        if pd.notna(r.get('EMA20')): ema20_js.append({'time': ts, 'value': round(float(r['EMA20']), 2)})
        if pd.notna(r.get('KALMAN')): kal_js.append({'time': ts, 'value': round(float(r['KALMAN']), 2)})
        if pd.notna(r.get('ST')): st_js.append({'time': ts, 'value': round(float(r['ST']), 2)})
        if pd.notna(r.get('BB_UP')): bb_u_js.append({'time': ts, 'value': round(float(r['BB_UP']), 2)})
        if pd.notna(r.get('BB_DN')): bb_d_js.append({'time': ts, 'value': round(float(r['BB_DN']), 2)})

        if pd.notna(pine_res['fast_ma'].iloc[idx_i]):
            p_fast_js.append({'time': ts, 'value': round(float(pine_res['fast_ma'].iloc[idx_i]), 2), 'color': pine_res['rib_col'][idx_i]})
        if pd.notna(pine_res['slow_ma'].iloc[idx_i]):
            p_slow_js.append({'time': ts, 'value': round(float(pine_res['slow_ma'].iloc[idx_i]), 2)})
        if pd.notna(pine_res['ltf_up'].iloc[idx_i]):
            p_up_js.append({'time': ts, 'value': round(float(pine_res['ltf_up'].iloc[idx_i]), 2)})
            p_lo_js.append({'time': ts, 'value': round(float(pine_res['ltf_lo'].iloc[idx_i]), 2)})
            p_mid_js.append({'time': ts, 'value': round(float(pine_res['ltf_mid'].iloc[idx_i]), 2), 'color': pine_res['rib_col'][idx_i]})
        if pd.notna(pine_res['mtf20'].iloc[idx_i]):
            mtf20_js.append({'time': ts, 'value': round(float(pine_res['mtf20'].iloc[idx_i]), 2)})
            mtf100_js.append({'time': ts, 'value': round(float(pine_res['mtf100'].iloc[idx_i]), 2)})
            mtf200_js.append({'time': ts, 'value': round(float(pine_res['mtf200'].iloc[idx_i]), 2)})
        if pd.notna(pine_res['dyn_ema'].iloc[idx_i]):
            dyn_ema_js.append({'time': ts, 'value': round(float(pine_res['dyn_ema'].iloc[idx_i]), 2), 'color': str(pine_res['dyn_col'][idx_i])})

        if bool(pine_res['turn_buy'].iloc[idx_i]):
            markers_js.append({'time': ts, 'position': 'belowBar', 'color': '#22c55e', 'shape': 'arrowUp', 'text': 'BIG BULL'})
        elif bool(pine_res['turn_sell'].iloc[idx_i]):
            markers_js.append({'time': ts, 'position': 'aboveBar', 'color': '#ef4444', 'shape': 'arrowDown', 'text': 'BIG BEAR'})

    is_light = "Light" in theme_mode
    bg_hex = "#ffffff" if is_light else "#0b0e14"
    txt_hex = "#111827" if is_light else "#d1d5db"
    grid_hex = "#f1f5f9" if is_light else "#141923"
    chart_dom_id = f"tv_lw_{key_idx}"
    bar_sp = 4.5 if len(current_grid_syms) >= 2 else 6.5
    wtbl = pine_res['wave_tbl']

    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
    <style>
        body {{
            margin: 0; padding: 0; background: {bg_hex};
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
            overflow: hidden; border: 1px solid #2b313f; border-radius: 6px;
            height: 100vh; display: flex; flex-direction: column; box-sizing: border-box;
        }}
        .hdr-bar {{
            background: #111622; color: #fff; padding: 3px 6px; display: flex; justify-content: space-between; align-items: center;
            border-bottom: 1px solid #2b313f; font-size: 11px; user-select: none; min-height: 25px; height: auto;
            flex: 0 0 auto; flex-wrap: wrap; gap: 3px; box-sizing: border-box; z-index: 50;
        }}
        .stk-info {{ display: flex; align-items: center; gap: 4px; flex-wrap: wrap; overflow: visible; }}
        .chart-stage {{ position: relative; flex: 1 1 auto; width: 100%; min-height: 0; overflow: hidden; }}
        @media (max-width: 640px) {{
            .ind-bar {{ width: 100%; justify-content: flex-end; border-top: 1px solid #1e293b; padding-top: 2px; }}
            .ohlc-overlay {{ top: 3px !important; left: 4px !important; font-size: 8.5px !important; }}
            .sltg-box {{ top: 20px !important; left: 4px !important; flex-wrap: wrap !important; gap: 3px !important; max-width: 95vw !important; padding: 2px 4px !important; }}
            .sltg-inp {{ width: 44px !important; font-size: 9px !important; }}
            .draw-menu {{ top: 52px !important; left: 4px !important; right: auto !important; }}
            .ind-menu {{ top: 52px !important; right: 4px !important; }}
        }}
            
        .ind-bar {{ display: flex; gap: 4px; flex-wrap: nowrap; align-items: center; position: relative; }}
        .tr-btn {{
            padding: 1px 6px; border-radius: 3px; font-size: 9.5px; font-weight: 800; cursor: pointer;
            color: #ffffff; transition: 0.12s; white-space: nowrap; letter-spacing: 0.3px;
        }}
        .prod-b {{ background: {prod_badge_col}; border: 1px solid rgba(255,255,255,0.25); font-size: 9px; padding: 1px 5px; }}
        .prod-b:hover {{ opacity: 0.9; }}
        .buy-b {{ background: #16a34a; border: 1px solid #22c55e; }}
        .buy-b:hover {{ background: #15803d; transform: scale(1.04); }}
        .sell-b {{ background: #dc2626; border: 1px solid #ef4444; }}
        .sell-b:hover {{ background: #b91c1c; transform: scale(1.04); }}
        .exit-b {{ background: #eab308; color: #111827; border: 1px solid #facc15; }}
        .exit-b:hover {{ background: #ca8a04; color: #fff; }}

        .ind-drop-btn {{
            background: #1e293b; color: #38bdf8; border: 1px solid #334155; border-radius: 4px;
            padding: 1px 7px; font-size: 10px; font-weight: bold; cursor: pointer; white-space: nowrap;
        }}
        .ind-drop-btn:hover, .ind-drop-btn.active-tool {{ background: #2563eb; color: #fff; border-color: #38bdf8; }}
        .ind-menu {{
            display: none; position: fixed; top: 26px; right: 28px; z-index: 9999;
            background: #111622; border: 1px solid #374151; border-radius: 6px; padding: 6px 8px;
            width: 235px; box-shadow: 0 8px 20px rgba(0,0,0,0.75); color: #e5e7eb; font-size: 10.5px;
        }}
        .draw-menu {{
            display: none; position: fixed; top: 26px; right: 155px; z-index: 9999;
            background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 0px;
            width: 235px; box-shadow: 0 8px 24px rgba(0,0,0,0.65); color: #0f172a; font-size: 12px;
        }}
        .ind-menu.open, .draw-menu.open {{ display: block; }}
        .ind-row {{
            display: flex; align-items: center; gap: 6px; padding: 3px 4px; cursor: pointer; border-radius: 4px;
        }}
        .ind-row:hover {{ background: #1f2937; }}
        .draw-item {{
            padding: 7px 14px; cursor: pointer; font-weight: 500; display: flex; justify-content: space-between; align-items: center;
        }}
        .draw-item:hover {{ background: #e2e8f0; }}
        .draw-item.active {{ background: #dbeafe; color: #1d4ed8; font-weight: 700; }}
        .draw-clear {{
            padding: 6px 14px 4px 14px; text-align: right; color: #475569; text-decoration: underline;
            cursor: pointer; font-size: 11.5px; border-top: 1px solid #e2e8f0; margin-top: 4px;
        }}
        .draw-clear:hover {{ color: #dc2626; }}
        .ind-sec-lbl {{ font-size: 9px; color: #9ca3af; font-weight: bold; margin: 4px 0 2px 2px; text-transform: uppercase; letter-spacing: 0.5px; }}

        .close-btn {{
            background: #dc2626; color: #ffffff; border: 1px solid #ef4444; border-radius: 3px;
            padding: 0px 5px; font-size: 10px; font-weight: bold; cursor: pointer;
            margin-left: 2px; line-height: 16px; display: inline-block;
        }}
        .close-btn:hover {{ background: #b91c1c; }}
        .ohlc-overlay {{
            position: absolute; top: 4px; left: 6px; z-index: 20; font-size: 10px;
            color: {txt_hex}; background: {'rgba(255,255,255,0.85)' if is_light else 'rgba(11,14,20,0.85)'};
            padding: 1px 5px; border-radius: 4px; pointer-events: none; font-family: monospace;
        }}
        .draw-status-badge {{
            position: absolute; top: 27px; left: 50%; transform: translateX(-50%); z-index: 65;
            background: #2563eb; color: #fff; padding: 2px 10px; border-radius: 12px; font-size: 10px;
            font-weight: bold; display: none; box-shadow: 0 2px 8px rgba(0,0,0,0.5); cursor: pointer;
        }}
        .sltg-box {{
            position: absolute; top: 24px; left: 6px; z-index: 30; display: none; align-items: center; gap: 5px;
            background: rgba(17, 22, 34, 0.94); border: 1px solid #374151; border-radius: 5px;
            padding: 2px 7px; font-size: 10px; color: #fff; font-family: monospace; box-shadow: 0 2px 6px rgba(0,0,0,0.45);
        }}
        .sltg-inp {{
            width: 56px; background: #0b0e14; color: #fff; border: 1px solid #4b5563; border-radius: 3px;
            font-size: 10px; font-family: monospace; font-weight: bold; padding: 1px 3px; text-align: right;
        }}
        .sltg-inp:focus {{ outline: none; border-color: #38bdf8; }}
        .otype-badge {{
            padding: 1px 5px; border-radius: 3px; font-size: 9px; font-weight: bold;
            background: #16a34a; color: #fff; letter-spacing: 0.3px;
        }}
        .save-sltg-btn {{
            background: #2563eb; color: #fff; border: 1px solid #38bdf8; border-radius: 3px;
            padding: 1px 6px; font-size: 9.5px; font-weight: bold; cursor: pointer;
        }}
        .save-sltg-btn:hover {{ background: #1d4ed8; }}
        .line-hover-tip {{
            position: absolute; display: none; z-index: 80; pointer-events: none;
            background: rgba(15, 23, 42, 0.96); border: 1px solid #38bdf8; color: #ffffff;
            padding: 4px 8px; border-radius: 5px; font-size: 10.5px; font-family: monospace;
            white-space: nowrap; box-shadow: 0 4px 12px rgba(0,0,0,0.6);
        }}
        .wave-tbl {{
            position: absolute; top: 28px; right: 62px; z-index: 25; display: none;
            background: rgba(17, 22, 34, 0.90); border: 1px solid #374151; border-radius: 5px;
            padding: 3px 7px; font-size: 9.5px; color: #e5e7eb; font-family: monospace;
        }}
        #draw_svg_{chart_dom_id} {{
            position: absolute; top: 0; left: 0; width: 100%; height: 100%;
            z-index: 15; pointer-events: none; overflow: hidden;
        }}
    </style>
    </head>
    <body>
        <div class="hdr-bar">
            <div class="stk-info">
                <span style="font-weight:800; font-size:11.5px; color:#ffffff;">{disp_sym}</span>
                <span style="background:#1e293b; color:#38bdf8; padding:0px 4px; border-radius:3px; font-size:9px; font-weight:bold;">{tf_short}</span>
                <span style="font-weight:700; font-size:11.5px; color:#ffd700;">₹{ltp_v:,.2f}</span>
                <span style="font-weight:700; font-size:10px; color:{c_col};">({chg_v:+.2f}%)</span>
                <span class="tr-btn prod-b" onclick="triggerStBtn('{prod_token}')" title="Switch Intraday (MIS) / Longterm (CNC)">{prod_badge_txt}</span>
                <span class="tr-btn buy-b" onclick="startNewTrade('{fetch_sym}', '{buy_token}')" title="Buy {disp_sym} ({prod_mode}) @ ₹{ltp_v:.2f}">BUY</span>
                <span class="tr-btn sell-b" onclick="startNewTrade('{fetch_sym}', '{sell_token}')" title="Sell {disp_sym} ({prod_mode}) @ ₹{ltp_v:.2f}">SELL</span>
                {exit_btn_html}
            </div>
            <div class="ind-bar">
                <!-- ✏️ Drawing Tools Menu -->
                <span id="draw_btn_{chart_dom_id}" class="ind-drop-btn" onclick="toggleDrawMenu(event)" title="Drawing Tools">✏️ Draw ▾</span>
                <div id="draw_menu_{chart_dom_id}" class="draw-menu" onclick="event.stopPropagation()">
                    <div id="ditem_hline" class="draw-item" onclick="selectDrawTool('hline')"><span>Horizontal Line</span><span style="color:#64748b;font-size:10px;">━</span></div>
                    <div id="ditem_vline" class="draw-item" onclick="selectDrawTool('vline')"><span>Vertical Line</span><span style="color:#64748b;font-size:10px;">┃</span></div>
                    <div id="ditem_tl_hl" class="draw-item" onclick="selectDrawTool('tl_hl')"><span>Trendline (High/Low)</span><span style="color:#64748b;font-size:10px;">╱</span></div>
                    <div id="ditem_tl_free" class="draw-item" onclick="selectDrawTool('tl_free')"><span>Trendline (FreeHand)</span><span style="color:#64748b;font-size:10px;">✍️</span></div>
                    <div id="ditem_fib" class="draw-item" onclick="selectDrawTool('fib')"><span>Fibonacci (High/Low) <b id="fib_cnt_{chart_dom_id}">(0)</b></span><span style="color:#64748b;font-size:10px;">☰</span></div>
                    <div id="ditem_fib_free" class="draw-item" onclick="selectDrawTool('fib_free')"><span>Fibonacci (FreeHand)</span><span style="color:#2563eb;font-size:10px;">✍️☰</span></div>
                    <div class="draw-clear" onclick="clearAllDrawings()">Clear all</div>
                </div>

                <!-- 📊 Select Indicator Menu -->
                <span class="ind-drop-btn" onclick="toggleIndMenu(event)">📊 Select Indicator ▾</span>
                <div id="ind_menu_{chart_dom_id}" class="ind-menu" onclick="event.stopPropagation()">
                    <div class="ind-sec-lbl">Default Indicators (Active)</div>
                    <label class="ind-row"><input type="checkbox" id="chk_ema" {'checked' if 'EMAs' in active_inds else ''} onchange="toggleInd('ema')"> <span>EMAs (10, 20)</span></label>
                    <label class="ind-row"><input type="checkbox" id="chk_sr" {'checked' if 'S&R' in active_inds else ''} onchange="toggleInd('sr')"> <span>Support & Resistance (S&R)</span></label>
                    <label class="ind-row"><input type="checkbox" id="chk_piv" {'checked' if 'Pivots(R1,S1)' in active_inds else ''} onchange="toggleInd('piv')"> <span>Pivots (P, R1, S1)</span></label>
                    <label class="ind-row"><input type="checkbox" id="chk_vwap" {'checked' if 'VWAP' in active_inds else ''} onchange="toggleInd('vwap')"> <span>VWAP Line</span></label>
                    <label class="ind-row"><input type="checkbox" id="chk_bb" {'checked' if 'BB' in active_inds else ''} onchange="toggleInd('bb')"> <span>Bollinger Bands (BB)</span></label>
                    <label class="ind-row"><input type="checkbox" id="chk_kal" {'checked' if 'Kalman' in active_inds else ''} onchange="toggleInd('kal')"> <span>Kalman Filter</span></label>
                    <label class="ind-row"><input type="checkbox" id="chk_st" {'checked' if 'ST(7,3)' in active_inds else ''} onchange="toggleInd('st')"> <span>Supertrend ST(7,3)</span></label>
                    <hr style="border:0; border-top:1px solid #374151; margin:4px 0;">
                    <div class="ind-sec-lbl" style="color:#4ade80;">🌲 Pine Script v6 Suite</div>
                    <label class="ind-row"><input type="checkbox" id="chk_pine_all" onchange="togglePineAll(this.checked)"> <b style="color:#38bdf8;">⚡ Enable Full Pine Script</b></label>
                    <label class="ind-row"><input type="checkbox" id="chk_pine_rib" onchange="toggleInd('pine_rib')"> <span>Swing Ribbon + Breakout</span></label>
                    <label class="ind-row"><input type="checkbox" id="chk_pine_big" onchange="toggleInd('pine_big')"> <span>Big Trader Arrows + MTF EMA</span></label>
                    <label class="ind-row"><input type="checkbox" id="chk_pine_tsa" onchange="toggleInd('pine_tsa')"> <span>Trend Speed + Wave Table</span></label>
                </div>
                <span class="close-btn" onclick="triggerStBtn('{close_token}')" title="Close {disp_sym}">✖</span>
            </div>
        </div>

        <div class="chart-stage">
            <div id="ohlc_{chart_dom_id}" class="ohlc-overlay">Move cursor to inspect OHLCV</div>
            <div id="draw_badge_{chart_dom_id}" class="draw-status-badge" onclick="cancelDrawTool()" title="Click to exit drawing mode"></div>

            <!-- Pine Script v6 Wave Dominance Table -->
            <div id="wtbl_{chart_dom_id}" class="wave-tbl">
                <div>Wave Avg: <b style="color:{wtbl['col']};">{wtbl['rat_avg']}</b> | Max: <b>{wtbl['rat_max']}</b></div>
                <div>Dominance: <b style="color:{wtbl['col']};">{wtbl['dom']}</b></div>
            </div>

            <!-- Floating Entry (BUY/SELL) + SL + TGT Editor Box -->
            <div id="sltg_bar_{chart_dom_id}" class="sltg-box">
                <span id="ent_lbl_{chart_dom_id}" style="color:#38bdf8;font-weight:bold;">{ent_lbl_html}</span>
                <input id="inp_ent_{chart_dom_id}" class="sltg-inp" type="number" step="0.5" onchange="onManualSLTG('ENT')" oninput="onManualSLTG('ENT')">
                <span id="otype_badge_{chart_dom_id}" class="otype-badge">MKT</span>
                <span style="color:#f87171;font-weight:bold;margin-left:3px;">🛑 SL:</span>
                <input id="inp_sl_{chart_dom_id}" class="sltg-inp" type="number" step="0.5" onchange="onManualSLTG('SL')" oninput="onManualSLTG('SL')">
                <span style="color:#4ade80;font-weight:bold;margin-left:3px;">🎯 TGT:</span>
                <input id="inp_tg_{chart_dom_id}" class="sltg-inp" type="number" step="0.5" onchange="onManualSLTG('TG')" oninput="onManualSLTG('TG')">
                <span class="save-sltg-btn" onclick="saveSLTGToSheet()" title="Save Entry (Limit), SL & Target to Google Sheets & Dhan">💾 Save</span>
            </div>

            <!-- Hover Tooltip for Entry / SL / Target Percentage & Amount -->
            <div id="line_tip_{chart_dom_id}" class="line-hover-tip"></div>

            <!-- SVG Overlay & Full-Height Chart Container -->
            <svg id="draw_svg_{chart_dom_id}"></svg>
            <div id="{chart_dom_id}" style="width: 100%; height: 100%;"></div>
        </div>

        <script>
        const SYM_KEY = "{fetch_sym}";
        window.parent._customSLTG = window.parent._customSLTG || {{}};
        window.parent._savedIndState = window.parent._savedIndState || null;
        window.parent._savedDrawings = window.parent._savedDrawings || {{}};
        window.parent._savedDrawings[SYM_KEY] = window.parent._savedDrawings[SYM_KEY] || [];

        window.toggleIndMenu = function(e) {{
            e.stopPropagation();
            document.getElementById('draw_menu_{chart_dom_id}').classList.remove('open');
            document.getElementById('ind_menu_{chart_dom_id}').classList.toggle('open');
        }};
        window.toggleDrawMenu = function(e) {{
            e.stopPropagation();
            document.getElementById('ind_menu_{chart_dom_id}').classList.remove('open');
            document.getElementById('draw_menu_{chart_dom_id}').classList.toggle('open');
        }};
        document.addEventListener('click', () => {{
            const m1 = document.getElementById('ind_menu_{chart_dom_id}');
            const m2 = document.getElementById('draw_menu_{chart_dom_id}');
            if (m1) m1.classList.remove('open');
            if (m2) m2.classList.remove('open');
        }});

        window.triggerStBtn = function(tokenStr) {{
            const btns = window.parent.document.querySelectorAll('button');
            for (const b of btns) {{
                if (b.textContent && b.textContent.trim() === tokenStr) {{
                    b.click();
                    return;
                }}
            }}
        }};

        window.startNewTrade = function(sym, tokenStr) {{
            delete window.parent._customSLTG[sym];
            window.triggerStBtn(tokenStr);
        }};

        window.exitChartTrade = function(sym, tokenStr) {{
            delete window.parent._customSLTG[sym];
            window.triggerStBtn(tokenStr);
        }};

        const cData = {json.dumps(candles_js)};
        const spdCandles = {json.dumps(spd_candles_js)};
        const vData = {json.dumps(vol_js)};
        const vwapData = {json.dumps(vwap_js)};
        const ema10Data = {json.dumps(ema10_js)};
        const ema20Data = {json.dumps(ema20_js)};
        const kalData = {json.dumps(kal_js)};
        const stData = {json.dumps(st_js)};
        const bbUpData = {json.dumps(bb_u_js)};
        const bbDnData = {json.dumps(bb_d_js)};

        const pFastData = {json.dumps(p_fast_js)};
        const pSlowData = {json.dumps(p_slow_js)};
        const pUpData = {json.dumps(p_up_js)};
        const pLoData = {json.dumps(p_lo_js)};
        const pMidData = {json.dumps(p_mid_js)};
        const mtf20Data = {json.dumps(mtf20_js)};
        const mtf100Data = {json.dumps(mtf100_js)};
        const mtf200Data = {json.dumps(mtf200_js)};
        const dynEmaData = {json.dumps(dyn_ema_js)};
        const bigMarkers = {json.dumps(markers_js)};
        const activePos = {pos_js};

        const candleMap = Object.fromEntries(cData.map(b => [b.time, b]));
        const container = document.getElementById('{chart_dom_id}');
        const drawSvg = document.getElementById('draw_svg_{chart_dom_id}');
        const drawBadge = document.getElementById('draw_badge_{chart_dom_id}');
        const drawBtn = document.getElementById('draw_btn_{chart_dom_id}');
        const fibCntEl = document.getElementById('fib_cnt_{chart_dom_id}');
        const ohlcBox = document.getElementById('ohlc_{chart_dom_id}');
        const sltgBar = document.getElementById('sltg_bar_{chart_dom_id}');
        const inpEnt = document.getElementById('inp_ent_{chart_dom_id}');
        const inpSL = document.getElementById('inp_sl_{chart_dom_id}');
        const inpTG = document.getElementById('inp_tg_{chart_dom_id}');
        const otypeBadge = document.getElementById('otype_badge_{chart_dom_id}');
        const lineTip = document.getElementById('line_tip_{chart_dom_id}');
        const wTbl = document.getElementById('wtbl_{chart_dom_id}');

        const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
        function fmtIST(ts) {{
            const d = new Date(ts * 1000);
            const dd = String(d.getUTCDate()).padStart(2, '0');
            const mm = months[d.getUTCMonth()];
            let H = d.getUTCHours();
            const ampm = H >= 12 ? 'PM' : 'AM';
            H = H % 12 || 12;
            const hh = String(H).padStart(2, '0');
            const mn = String(d.getUTCMinutes()).padStart(2, '0');
            return `${{dd}} ${{mm}} ${{hh}}:${{mn}} ${{ampm}} IST`;
        }}

        const chart = LightweightCharts.createChart(container, {{
            layout: {{ background: {{ type: 'solid', color: '{bg_hex}' }}, textColor: '{txt_hex}', fontSize: 10.5 }},
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
                rightOffset: 3, barSpacing: {bar_sp},
                tickMarkFormatter: (time, tickMarkType, locale) => {{
                    const d = new Date(time * 1000);
                    const dd = String(d.getUTCDate()).padStart(2, '0');
                    const mm = months[d.getUTCMonth()];
                    let H = d.getUTCHours();
                    const mn = String(d.getUTCMinutes()).padStart(2, '0');
                    if (H === 9 && mn === '15') return `${{dd}} ${{mm}}`;
                    const ampm = H >= 12 ? 'PM' : 'AM';
                    H = H % 12 || 12;
                    return `${{H}}:${{mn}} ${{ampm}}`;
                }}
            }}
        }});

        const candleSeries = chart.addCandlestickSeries({{
            upColor: '#15803d', downColor: '#b91c1c',
            borderUpColor: '#15803d', borderDownColor: '#b91c1c',
            wickUpColor: '#15803d', wickDownColor: '#b91c1c'
        }});
        candleSeries.setData(cData);

        const volSeries = chart.addHistogramSeries({{
            priceFormat: {{ type: 'volume' }},
            priceScaleId: 'vol_scale',
            lastValueVisible: false,
            priceLineVisible: false
        }});
        chart.priceScale('vol_scale').applyOptions({{
            scaleMargins: {{ top: 0.82, bottom: 0.0 }}
        }});
        volSeries.setData(vData);
        // Default ga Last 1 Day (75 candles) matrame chupinchu; Zoom-Out / Scroll cheste 5 Days kanipistayi
        if ("{timeframe}" === "Intraday (5m)" && cData.length > 75) {{
            chart.timeScale().setVisibleLogicalRange({{
                from: cData.length - 75,
                to: cData.length + 2
            }});
        }} else {{
            chart.timeScale().fitContent();
        }}

        // =========================================================
        // ✏️ INTERACTIVE DRAWING ENGINE
        // =========================================================
        let currentTool = null;
        let pendingPt = null;
        let isFreeDrawing = false;
        let isFibFreeDragging = false;
        let freePts = [];
        let hLineObjs = [];

        function getClosestTime(xCoord) {{
            const t = chart.timeScale().coordinateToTime(xCoord);
            if (t !== null) return t;
            if (cData.length === 0) return 0;
            const logical = chart.timeScale().coordinateToLogical(xCoord);
            if (logical === null) return cData[cData.length - 1].time;
            const idx = Math.max(0, Math.min(cData.length - 1, Math.round(logical)));
            return cData[idx].time;
        }}

        function snapHighLow(timeVal, rawPrice) {{
            const bar = candleMap[timeVal];
            if (!bar) return rawPrice;
            const distH = Math.abs(rawPrice - bar.high);
            const distL = Math.abs(rawPrice - bar.low);
            return distH <= distL ? bar.high : bar.low;
        }}

        window.selectDrawTool = function(toolName) {{
            currentTool = toolName;
            pendingPt = null;
            freePts = [];
            isFreeDrawing = false;
            isFibFreeDragging = false;
            document.getElementById('draw_menu_{chart_dom_id}').classList.remove('open');
            ['hline','vline','tl_hl','tl_free','fib','fib_free'].forEach(k => {{
                const el = document.getElementById('ditem_' + k);
                if (el) el.className = 'draw-item' + (k === toolName ? ' active' : '');
            }});
            const names = {{
                hline: '━ Click on chart to place Horizontal Line (Click here to exit)',
                vline: '┃ Click on chart to place Vertical Line (Click here to exit)',
                tl_hl: '╱ Click Point 1 & Point 2 for High/Low Trendline (Click here to exit)',
                tl_free: '✍️ Drag on chart for FreeHand Trendline (Click here to exit)',
                fib: '☰ Click Swing High & Swing Low for Fibonacci (Click here to exit)',
                fib_free: '✍️☰ Drag freely (or Click 2 points) anywhere for FreeHand Fibonacci (Click here to exit)'
            }};
            drawBadge.innerHTML = names[toolName] || '';
            drawBadge.style.display = 'block';
            drawBtn.classList.add('active-tool');
            container.style.cursor = 'crosshair';
        }};

        window.cancelDrawTool = function() {{
            currentTool = null;
            pendingPt = null;
            isFreeDrawing = false;
            isFibFreeDragging = false;
            freePts = [];
            drawBadge.style.display = 'none';
            drawBtn.classList.remove('active-tool');
            container.style.cursor = 'default';
            chart.applyOptions({{ handleScroll: true, handleScale: true }});
            ['hline','vline','tl_hl','tl_free','fib','fib_free'].forEach(k => {{
                const el = document.getElementById('ditem_' + k);
                if (el) el.className = 'draw-item';
            }});
        }};

        window.clearAllDrawings = function() {{
            window.parent._savedDrawings[SYM_KEY] = [];
            hLineObjs.forEach(l => candleSeries.removePriceLine(l));
            hLineObjs = [];
            renderAllDrawings();
            cancelDrawTool();
            document.getElementById('draw_menu_{chart_dom_id}').classList.remove('open');
        }};

        function rebuildHPriceLines() {{
            hLineObjs.forEach(l => candleSeries.removePriceLine(l));
            hLineObjs = [];
            const list = window.parent._savedDrawings[SYM_KEY] || [];
            list.forEach(d => {{
                if (d.type === 'hline') {{
                    hLineObjs.push(candleSeries.createPriceLine({{
                        price: d.price,
                        color: '#38bdf8',
                        lineWidth: 1.5,
                        lineStyle: LightweightCharts.LineStyle.Solid,
                        axisLabelVisible: true,
                        title: 'H-Line'
                    }}));
                }}
            }});
        }}

        function renderAllDrawings(previewPt = null) {{
            const list = window.parent._savedDrawings[SYM_KEY] || [];
            const rect = container.getBoundingClientRect();
            let svgHtml = '';
            let fibCount = 0;

            const allItems = [...list];
            if (pendingPt && previewPt && (currentTool === 'tl_hl' || currentTool === 'fib' || currentTool === 'fib_free')) {{
                const pType = (currentTool === 'fib_free') ? 'fib' : currentTool;
                allItems.push({{ type: pType, p1: pendingPt, p2: previewPt, preview: true }});
            }}
            if (isFreeDrawing && freePts.length > 1) {{
                allItems.push({{ type: 'free_path', pts: freePts, preview: true }});
            }}

            allItems.forEach(d => {{
                if (d.type === 'vline') {{
                    const x = chart.timeScale().timeToCoordinate(d.time);
                    if (x !== null && x >= 0 && x <= rect.width) {{
                        svgHtml += `<line x1="${{x}}" y1="0" x2="${{x}}" y2="${{rect.height}}" stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="4,4" />`;
                    }}
                }} else if (d.type === 'tl_hl' || d.type === 'tl_free') {{
                    const x1 = chart.timeScale().timeToCoordinate(d.p1.time);
                    const y1 = candleSeries.priceToCoordinate(d.p1.price);
                    const x2 = chart.timeScale().timeToCoordinate(d.p2.time);
                    const y2 = candleSeries.priceToCoordinate(d.p2.price);
                    if (x1 !== null && y1 !== null && x2 !== null && y2 !== null) {{
                        const col = d.type === 'tl_hl' ? '#38bdf8' : '#a855f7';
                        svgHtml += `<line x1="${{x1}}" y1="${{y1}}" x2="${{x2}}" y2="${{y2}}" stroke="${{col}}" stroke-width="2" />`;
                        svgHtml += `<circle cx="${{x1}}" cy="${{y1}}" r="3.5" fill="${{col}}" />`;
                        svgHtml += `<circle cx="${{x2}}" cy="${{y2}}" r="3.5" fill="${{col}}" />`;
                    }}
                }} else if (d.type === 'free_path' && d.pts && d.pts.length > 1) {{
                    const ptsStr = d.pts.map(pt => {{
                        const px = chart.timeScale().timeToCoordinate(pt.time);
                        const py = candleSeries.priceToCoordinate(pt.price);
                        return (px !== null && py !== null) ? `${{px}},${{py}}` : null;
                    }}).filter(Boolean).join(' ');
                    if (ptsStr) {{
                        svgHtml += `<polyline fill="none" stroke="#a855f7" stroke-width="2" points="${{ptsStr}}" />`;
                    }}
                }} else if (d.type === 'fib') {{
                    if (!d.preview) fibCount++;
                    const x1 = chart.timeScale().timeToCoordinate(d.p1.time);
                    const x2 = chart.timeScale().timeToCoordinate(d.p2.time);
                    const y1 = candleSeries.priceToCoordinate(d.p1.price);
                    const y2 = candleSeries.priceToCoordinate(d.p2.price);
                    if (x1 !== null && x2 !== null) {{
                        const leftX = Math.min(x1, x2);
                        const rightX = Math.max(x1, x2, leftX + 135);
                        if (y1 !== null && y2 !== null) {{
                            svgHtml += `<line x1="${{x1}}" y1="${{y1}}" x2="${{x2}}" y2="${{y2}}" stroke="#64748b" stroke-width="1" stroke-dasharray="2,2" />`;
                        }}
                        const diff = d.p2.price - d.p1.price;
                        const fibLevels = [
                            {{ lvl: 0.0, col: '#94a3b8' }},
                            {{ lvl: 0.236, col: '#ef4444' }},
                            {{ lvl: 0.382, col: '#f59e0b' }},
                            {{ lvl: 0.5, col: '#22c55e' }},
                            {{ lvl: 0.618, col: '#06b6d4' }},
                            {{ lvl: 0.786, col: '#3b82f6' }},
                            {{ lvl: 1.0, col: '#94a3b8' }}
                        ];
                        fibLevels.forEach(fl => {{
                            const lvlPrice = d.p2.price - (diff * fl.lvl);
                            const y = candleSeries.priceToCoordinate(lvlPrice);
                            if (y !== null) {{
                                svgHtml += `<line x1="${{leftX}}" y1="${{y}}" x2="${{rightX}}" y2="${{y}}" stroke="${{fl.col}}" stroke-width="1.4" stroke-dasharray="3,2" />`;
                                svgHtml += `<text x="${{leftX + 4}}" y="${{y - 3}}" fill="${{fl.col}}" font-size="9.5" font-family="monospace" font-weight="bold">${{(fl.lvl * 100).toFixed(1)}}% (₹${{lvlPrice.toFixed(1)}})</text>`;
                            }}
                        }});
                    }}
                }}
            }});

            drawSvg.innerHTML = svgHtml;
            if (fibCntEl) fibCntEl.innerText = `(${{fibCount}})`;
        }}

        rebuildHPriceLines();
        setTimeout(() => renderAllDrawings(), 80);
        chart.timeScale().subscribeVisibleLogicalRangeChange(() => renderAllDrawings());
        chart.timeScale().subscribeVisibleTimeRangeChange(() => renderAllDrawings());

        container.addEventListener('mousedown', (e) => {{
            if (!currentTool) return;
            const rect = container.getBoundingClientRect();
            const mx = e.clientX - rect.left;
            const my = e.clientY - rect.top;
            const tVal = getClosestTime(mx);
            const pVal = candleSeries.coordinateToPrice(my);
            if (!tVal || pVal === null) return;

            if (currentTool === 'hline') {{
                window.parent._savedDrawings[SYM_KEY].push({{ type: 'hline', price: Math.round(pVal * 20) / 20 }});
                rebuildHPriceLines();
                cancelDrawTool();
            }} else if (currentTool === 'vline') {{
                window.parent._savedDrawings[SYM_KEY].push({{ type: 'vline', time: tVal }});
                renderAllDrawings();
                cancelDrawTool();
            }} else if (currentTool === 'tl_hl') {{
                const snappedP = snapHighLow(tVal, pVal);
                if (!pendingPt) {{
                    pendingPt = {{ time: tVal, price: snappedP }};
                    drawBadge.innerHTML = '╱ Now click Point 2 on chart (High/Low Snap)';
                }} else {{
                    window.parent._savedDrawings[SYM_KEY].push({{ type: 'tl_hl', p1: pendingPt, p2: {{ time: tVal, price: snappedP }} }});
                    renderAllDrawings();
                    cancelDrawTool();
                }}
            }} else if (currentTool === 'fib') {{
                const snappedP = snapHighLow(tVal, pVal);
                if (!pendingPt) {{
                    pendingPt = {{ time: tVal, price: snappedP }};
                    drawBadge.innerHTML = '☰ Now click Point 2 on chart for Fibonacci (High/Low)';
                }} else {{
                    window.parent._savedDrawings[SYM_KEY].push({{ type: 'fib', p1: pendingPt, p2: {{ time: tVal, price: snappedP }} }});
                    renderAllDrawings();
                    cancelDrawTool();
                }}
            }} else if (currentTool === 'fib_free') {{
                chart.applyOptions({{ handleScroll: false, handleScale: false }});
                if (!pendingPt) {{
                    pendingPt = {{ time: tVal, price: pVal }};
                    isFibFreeDragging = true;
                    drawBadge.innerHTML = '✍️☰ Drag & Release (or Click 2nd point) for FreeHand Fibonacci';
                }} else {{
                    window.parent._savedDrawings[SYM_KEY].push({{ type: 'fib', p1: pendingPt, p2: {{ time: tVal, price: pVal }} }});
                    renderAllDrawings();
                    cancelDrawTool();
                }}
            }} else if (currentTool === 'tl_free') {{
                chart.applyOptions({{ handleScroll: false, handleScale: false }});
                isFreeDrawing = true;
                freePts = [{{ time: tVal, price: pVal }}];
            }}
        }});

        // =========================================================
        // 🔥 DRAGGABLE BUY/SELL ENTRY LINE (AUTO LIMIT ORDER) + SL & TGT LINES
        // =========================================================
        let entryLineObj = null, slLineObj = null, tgLineObj = null;
        let curEnt = 0, curSL = 0, curTG = 0, curOType = 'MARKET', draggingMode = null;

        function calcMetrics(priceVal) {{
            const diff = activePos.side === 'BUY' ? (priceVal - curEnt) : (curEnt - priceVal);
            const pct = curEnt > 0 ? (diff / curEnt) * 100.0 : 0.0;
            const rs = diff * activePos.qty;
            const sign = rs >= 0 ? '+' : '-';
            return {{ diff, pct, rs, sign }};
        }}

        function fmtEntTitle(entPrice, oType) {{
            const liveDiff = activePos.side === 'BUY' ? (activePos.ltp - entPrice) : (entPrice - activePos.ltp);
            const livePct = entPrice > 0 ? (liveDiff / entPrice) * 100.0 : 0.0;
            const liveRs = liveDiff * activePos.qty;
            const sign = liveRs >= 0 ? '+' : '-';
            const modeTag = oType === 'LIMIT' ? '⏳ LIMIT' : (activePos.side === 'BUY' ? '🟢' : '🔴');
            return `${{modeTag}} ${{activePos.side}} [${{activePos.prod}}] ${{activePos.qty}} @ ₹${{entPrice.toFixed(2)}} | ${{sign}}${{Math.abs(livePct).toFixed(2)}}% (${{sign}}₹${{Math.abs(liveRs).toFixed(2)}}) ↕`;
        }}

        function fmtSLTitle(slPrice) {{
            const m = calcMetrics(slPrice);
            return `🛑 SL ₹${{slPrice.toFixed(2)}} | ${{m.sign}}${{Math.abs(m.pct).toFixed(2)}}% (${{m.sign}}₹${{Math.abs(m.rs).toFixed(0)}}) ↕`;
        }}

        function fmtTGTitle(tgPrice) {{
            const m = calcMetrics(tgPrice);
            return `🎯 TGT ₹${{tgPrice.toFixed(2)}} | ${{m.sign}}${{Math.abs(m.pct).toFixed(2)}}% (${{m.sign}}₹${{Math.abs(m.rs).toFixed(0)}}) ↕`;
        }}

        function updateOTypeBadge() {{
            if (!otypeBadge) return;
            if (curOType === 'LIMIT') {{
                otypeBadge.innerText = 'LIMIT';
                otypeBadge.style.background = '#d97706';
            }} else {{
                otypeBadge.innerText = 'MKT';
                otypeBadge.style.background = '#16a34a';
            }}
        }}

        window.saveSLTGToSheet = function() {{
            const vEnt = parseFloat(inpEnt.value) || curEnt;
            const vSL = parseFloat(inpSL.value) || curSL;
            const vTG = parseFloat(inpTG.value) || curTG;
            const url = new URL(window.parent.location.href);
            url.searchParams.set('upd_sltg', `${{SYM_KEY}}|${{vEnt}}|${{vSL}}|${{vTG}}|${{curOType}}`);
            window.parent.location.href = url.toString();
        }};

        if (activePos) {{
            const saved = window.parent._customSLTG[activePos.sym];
            curEnt = (saved && saved.entry > 0) ? saved.entry : activePos.entry;
            curSL = (saved && saved.sl > 0) ? saved.sl : activePos.sl;
            curTG = (saved && saved.tg > 0) ? saved.tg : activePos.target;
            curOType = (saved && saved.orderType) ? saved.orderType : (activePos.orderType || 'MARKET');

            sltgBar.style.display = 'flex';
            inpEnt.value = curEnt.toFixed(2);
            inpSL.value = curSL.toFixed(2);
            inpTG.value = curTG.toFixed(2);
            updateOTypeBadge();

            entryLineObj = candleSeries.createPriceLine({{
                price: curEnt,
                color: curOType === 'LIMIT' ? '#38bdf8' : activePos.entryColor,
                lineWidth: 2,
                lineStyle: LightweightCharts.LineStyle.Solid,
                axisLabelVisible: true,
                title: fmtEntTitle(curEnt, curOType)
            }});
            tgLineObj = candleSeries.createPriceLine({{
                price: curTG,
                color: '#16a34a',
                lineWidth: 2,
                lineStyle: LightweightCharts.LineStyle.Dashed,
                axisLabelVisible: true,
                title: fmtTGTitle(curTG)
            }});
            slLineObj = candleSeries.createPriceLine({{
                price: curSL,
                color: '#dc2626',
                lineWidth: 2,
                lineStyle: LightweightCharts.LineStyle.Dashed,
                axisLabelVisible: true,
                title: fmtSLTitle(curSL)
            }});

            window.onManualSLTG = function(changedField) {{
                const vEnt = parseFloat(inpEnt.value);
                const vSL = parseFloat(inpSL.value);
                const vTG = parseFloat(inpTG.value);
                if (!isNaN(vEnt) && vEnt > 0) {{
                    if (changedField === 'ENT' && Math.abs(vEnt - curEnt) >= 0.01) {{
                        curOType = 'LIMIT';
                        updateOTypeBadge();
                    }}
                    curEnt = vEnt;
                    entryLineObj.applyOptions({{
                        price: curEnt,
                        color: curOType === 'LIMIT' ? '#38bdf8' : activePos.entryColor,
                        title: fmtEntTitle(curEnt, curOType)
                    }});
                }}
                if (!isNaN(vSL) && vSL > 0) {{
                    curSL = vSL;
                }}
                if (!isNaN(vTG) && vTG > 0) {{
                    curTG = vTG;
                }}
                slLineObj.applyOptions({{ price: curSL, title: fmtSLTitle(curSL) }});
                tgLineObj.applyOptions({{ price: curTG, title: fmtTGTitle(curTG) }});
                window.parent._customSLTG[activePos.sym] = {{ entry: curEnt, sl: curSL, tg: curTG, orderType: curOType }};
            }};

            container.addEventListener('mousedown', (e) => {{
                if (currentTool) return;
                const rect = container.getBoundingClientRect();
                const mouseY = e.clientY - rect.top;
                const entY = candleSeries.priceToCoordinate(curEnt);
                const slY = candleSeries.priceToCoordinate(curSL);
                const tgY = candleSeries.priceToCoordinate(curTG);

                if (entY !== null && Math.abs(mouseY - entY) <= 18) {{
                    draggingMode = 'ENT';
                    chart.applyOptions({{ handleScroll: false, handleScale: false }});
                    e.preventDefault();
                }} else if (slY !== null && Math.abs(mouseY - slY) <= 18) {{
                    draggingMode = 'SL';
                    chart.applyOptions({{ handleScroll: false, handleScale: false }});
                    e.preventDefault();
                }} else if (tgY !== null && Math.abs(mouseY - tgY) <= 18) {{
                    draggingMode = 'TG';
                    chart.applyOptions({{ handleScroll: false, handleScale: false }});
                    e.preventDefault();
                }}
            }});
        }}

        window.addEventListener('mousemove', (e) => {{
            const rect = container.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;

            if (currentTool) {{
                const tVal = getClosestTime(mouseX);
                const pVal = candleSeries.coordinateToPrice(mouseY);
                if (tVal && pVal !== null) {{
                    if (isFreeDrawing) {{
                        freePts.push({{ time: tVal, price: pVal }});
                        renderAllDrawings();
                    }} else if (pendingPt) {{
                        const snapP = (currentTool === 'tl_hl' || currentTool === 'fib') ? snapHighLow(tVal, pVal) : pVal;
                        renderAllDrawings({{ time: tVal, price: snapP }});
                    }}
                }}
                return;
            }}

            if (!activePos) return;

            if (!draggingMode) {{
                const entY = candleSeries.priceToCoordinate(curEnt);
                const slY = candleSeries.priceToCoordinate(curSL);
                const tgY = candleSeries.priceToCoordinate(curTG);

                if (slY !== null && Math.abs(mouseY - slY) <= 12) {{
                    container.style.cursor = 'ns-resize';
                    const m = calcMetrics(curSL);
                    lineTip.style.display = 'block';
                    lineTip.style.borderColor = '#ef4444';
                    lineTip.style.left = Math.min(mouseX + 14, rect.width - 260) + 'px';
                    lineTip.style.top = Math.max(28, slY - 28) + 'px';
                    lineTip.innerHTML = `🛑 <b>STOP LOSS: ₹${{curSL.toFixed(2)}}</b> | Move: <b style="color:#f87171;">${{m.sign}}${{Math.abs(m.pct).toFixed(2)}}%</b> | Amt: <b style="color:#f87171;">${{m.sign}}₹${{Math.abs(m.rs).toFixed(2)}}</b>`;
                }} else if (tgY !== null && Math.abs(mouseY - tgY) <= 12) {{
                    container.style.cursor = 'ns-resize';
                    const m = calcMetrics(curTG);
                    lineTip.style.display = 'block';
                    lineTip.style.borderColor = '#22c55e';
                    lineTip.style.left = Math.min(mouseX + 14, rect.width - 260) + 'px';
                    lineTip.style.top = Math.max(28, tgY - 28) + 'px';
                    lineTip.innerHTML = `🎯 <b>TARGET: ₹${{curTG.toFixed(2)}}</b> | Move: <b style="color:#4ade80;">${{m.sign}}${{Math.abs(m.pct).toFixed(2)}}%</b> | Profit: <b style="color:#4ade80;">${{m.sign}}₹${{Math.abs(m.rs).toFixed(2)}}</b>`;
                }} else if (entY !== null && Math.abs(mouseY - entY) <= 12) {{
                    container.style.cursor = 'ns-resize';
                    const mSL = calcMetrics(curSL);
                    const mTG = calcMetrics(curTG);
                    lineTip.style.display = 'block';
                    lineTip.style.borderColor = '#38bdf8';
                    lineTip.style.left = Math.min(mouseX + 14, rect.width - 330) + 'px';
                    lineTip.style.top = Math.max(28, entY - 36) + 'px';
                    lineTip.innerHTML = `<b>${{curOType}} ${{activePos.side}} [${{activePos.prod}}] ${{activePos.qty}} Qty @ ₹${{curEnt.toFixed(2)}}</b> (↕ Drag for Limit Order)<br><span style="color:#f87171;">🛑 SL: ${{mSL.sign}}${{Math.abs(mSL.pct).toFixed(2)}}% (${{mSL.sign}}₹${{Math.abs(mSL.rs).toFixed(0)}})</span> &nbsp;|&nbsp; <span style="color:#4ade80;">🎯 TGT: ${{mTG.sign}}${{Math.abs(mTG.pct).toFixed(2)}}% (${{mTG.sign}}₹${{Math.abs(mTG.rs).toFixed(0)}})</span>`;
                }} else {{
                    container.style.cursor = 'default';
                    lineTip.style.display = 'none';
                }}
                return;
            }}

            const rawPrice = candleSeries.coordinateToPrice(mouseY);
            if (rawPrice === null || rawPrice <= 0) return;
            const newP = Math.round(rawPrice * 20) / 20;

            if (draggingMode === 'ENT') {{
                curEnt = newP;
                curOType = 'LIMIT';
                inpEnt.value = curEnt.toFixed(2);
                updateOTypeBadge();
                entryLineObj.applyOptions({{
                    price: curEnt,
                    color: '#38bdf8',
                    title: fmtEntTitle(curEnt, 'LIMIT')
                }});
                slLineObj.applyOptions({{ price: curSL, title: fmtSLTitle(curSL) }});
                tgLineObj.applyOptions({{ price: curTG, title: fmtTGTitle(curTG) }});
                lineTip.style.display = 'block';
                lineTip.style.borderColor = '#38bdf8';
                lineTip.innerHTML = `⏳ <b>LIMIT ${{activePos.side}}: ₹${{curEnt.toFixed(2)}}</b> (Click 💾 Save to update order)`;
            }} else if (draggingMode === 'SL') {{
                curSL = newP;
                inpSL.value = curSL.toFixed(2);
                slLineObj.applyOptions({{ price: curSL, title: fmtSLTitle(curSL) }});
                const m = calcMetrics(curSL);
                lineTip.style.display = 'block';
                lineTip.innerHTML = `🛑 <b>SL: ₹${{curSL.toFixed(2)}}</b> | <b style="color:#f87171;">${{m.sign}}${{Math.abs(m.pct).toFixed(2)}}% (${{m.sign}}₹${{Math.abs(m.rs).toFixed(2)}})</b>`;
            }} else if (draggingMode === 'TG') {{
                curTG = newP;
                inpTG.value = curTG.toFixed(2);
                tgLineObj.applyOptions({{ price: curTG, title: fmtTGTitle(curTG) }});
                const m = calcMetrics(curTG);
                lineTip.style.display = 'block';
                lineTip.innerHTML = `🎯 <b>TGT: ₹${{curTG.toFixed(2)}}</b> | <b style="color:#4ade80;">${{m.sign}}${{Math.abs(m.pct).toFixed(2)}}% (${{m.sign}}₹${{Math.abs(m.rs).toFixed(2)}})</b>`;
            }}
            window.parent._customSLTG[activePos.sym] = {{ entry: curEnt, sl: curSL, tg: curTG, orderType: curOType }};
        }});

        window.addEventListener('mouseup', (e) => {{
            if (isFreeDrawing) {{
                isFreeDrawing = false;
                if (freePts.length > 1) {{
                    window.parent._savedDrawings[SYM_KEY].push({{ type: 'free_path', pts: [...freePts] }});
                }}
                renderAllDrawings();
                cancelDrawTool();
            }} else if (isFibFreeDragging && currentTool === 'fib_free' && pendingPt) {{
                const rect = container.getBoundingClientRect();
                const mx = e.clientX - rect.left;
                const my = e.clientY - rect.top;
                const tVal = getClosestTime(mx);
                const pVal = candleSeries.coordinateToPrice(my);
                if (tVal && pVal !== null && Math.abs(pVal - pendingPt.price) > (pendingPt.price * 0.0005)) {{
                    window.parent._savedDrawings[SYM_KEY].push({{ type: 'fib', p1: pendingPt, p2: {{ time: tVal, price: pVal }} }});
                    renderAllDrawings();
                    cancelDrawTool();
                }}
                isFibFreeDragging = false;
            }}
            if (draggingMode) {{
                draggingMode = null;
                container.style.cursor = 'default';
                chart.applyOptions({{ handleScroll: true, handleScale: true }});
            }}
        }});

        // Default Indicators
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

        // 🌲 Pine Script v6 Indicator Series
        const pineFastSeries = chart.addLineSeries({{ lineWidth: 2, priceLineVisible: false, visible: false, title: 'FastWMA' }});
        pineFastSeries.setData(pFastData);
        const pineSlowSeries = chart.addLineSeries({{ color: '#64748b', lineWidth: 1, priceLineVisible: false, visible: false }});
        pineSlowSeries.setData(pSlowData);
        const pineUpBand = chart.addLineSeries({{ color: '#f97316', lineWidth: 1, lineStyle: 2, priceLineVisible: false, visible: false }});
        pineUpBand.setData(pUpData);
        const pineLoBand = chart.addLineSeries({{ color: '#f97316', lineWidth: 1, lineStyle: 2, priceLineVisible: false, visible: false }});
        pineLoBand.setData(pLoData);
        const pineMidBand = chart.addLineSeries({{ lineWidth: 3, priceLineVisible: false, visible: false }});
        pineMidBand.setData(pMidData);

        const pineMtf20 = chart.addLineSeries({{ color: '#f97316', lineWidth: 2, priceLineVisible: false, visible: false, title: 'EMA20' }});
        pineMtf20.setData(mtf20Data);
        const pineMtf100 = chart.addLineSeries({{ color: '#3b82f6', lineWidth: 2, priceLineVisible: false, visible: false, title: 'EMA100' }});
        pineMtf100.setData(mtf100Data);
        const pineMtf200 = chart.addLineSeries({{ color: '#a855f7', lineWidth: 2, priceLineVisible: false, visible: false, title: 'EMA200' }});
        pineMtf200.setData(mtf200Data);

        const pineDynSeries = chart.addLineSeries({{ lineWidth: 2, priceLineVisible: false, visible: false, title: 'DynTrend' }});
        pineDynSeries.setData(dynEmaData);

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

        const defaultState = {{
            ema: {'true' if 'EMAs' in active_inds else 'false'},
            sr: {'true' if 'S&R' in active_inds else 'false'},
            piv: {'true' if 'Pivots(R1,S1)' in active_inds else 'false'},
            vwap: {'true' if 'VWAP' in active_inds else 'false'},
            bb: {'true' if 'BB' in active_inds else 'false'},
            kal: {'true' if 'Kalman' in active_inds else 'false'},
            st: {'true' if 'ST(7,3)' in active_inds else 'false'},
            pine_rib: false,
            pine_big: false,
            pine_tsa: false
        }};
        const state = Object.assign({{}}, defaultState, window.parent._savedIndState || {{}});

        function applyAllIndStates() {{
            vwapSeries.applyOptions({{ visible: state.vwap }});
            ema10Series.applyOptions({{ visible: state.ema }});
            ema20Series.applyOptions({{ visible: state.ema }});
            kalSeries.applyOptions({{ visible: state.kal }});
            stSeries.applyOptions({{ visible: state.st }});
            bbUpSeries.applyOptions({{ visible: state.bb }});
            bbDnSeries.applyOptions({{ visible: state.bb }});
            drawSR(state.sr);
            drawPiv(state.piv);

            pineFastSeries.applyOptions({{ visible: state.pine_rib }});
            pineSlowSeries.applyOptions({{ visible: state.pine_rib }});
            pineUpBand.applyOptions({{ visible: state.pine_rib }});
            pineLoBand.applyOptions({{ visible: state.pine_rib }});
            pineMidBand.applyOptions({{ visible: state.pine_rib }});

            pineMtf20.applyOptions({{ visible: state.pine_big }});
            pineMtf100.applyOptions({{ visible: state.pine_big }});
            pineMtf200.applyOptions({{ visible: state.pine_big }});
            candleSeries.setMarkers(state.pine_big ? bigMarkers : []);

            pineDynSeries.applyOptions({{ visible: state.pine_tsa }});
            candleSeries.setData(state.pine_tsa ? spdCandles : cData);
            wTbl.style.display = state.pine_tsa ? 'block' : 'none';

            ['ema','sr','piv','vwap','bb','kal','st','pine_rib','pine_big','pine_tsa'].forEach(k => {{
                const el = document.getElementById('chk_' + k);
                if (el) el.checked = !!state[k];
            }});
            const allEl = document.getElementById('chk_pine_all');
            if (allEl) allEl.checked = (state.pine_rib && state.pine_big && state.pine_tsa);
        }}

        applyAllIndStates();

        window.toggleInd = function(k) {{
            state[k] = !state[k];
            window.parent._savedIndState = Object.assign({{}}, state);
            applyAllIndStates();
        }};

        window.togglePineAll = function(on) {{
            state.pine_rib = on;
            state.pine_big = on;
            state.pine_tsa = on;
            window.parent._savedIndState = Object.assign({{}}, state);
            applyAllIndStates();
        }};

        const volLookup = Object.fromEntries(vData.map(x => [x.time, x.value]));
        function updateLegend(bar) {{
            if (!bar) return;
            const chg = (bar.close - bar.open).toFixed(2);
            const pct = ((bar.close - bar.open) / bar.open * 100).toFixed(2);
            const col = bar.close >= bar.open ? '#16a34a' : '#dc2626';
            const v = volLookup[bar.time] || 0;
            const vStr = v > 0 ? (v >= 1000000 ? '&nbsp;Vol <b>'+(v/1000000).toFixed(2)+'M</b>' : '&nbsp;Vol <b>'+(v/1000).toFixed(1)+'K</b>') : '';
            const tStr = fmtIST(bar.time);
            ohlcBox.innerHTML = `🕒 <b>${{tStr}}</b> &nbsp; O<b>${{bar.open}}</b> H<b>${{bar.high}}</b> L<b>${{bar.low}}</b> C<b>${{bar.close}}</b> <span style="color:${{col}};font-weight:bold;">${{chg>=0?'+'+chg:chg}} (${{pct>=0?'+'+pct:pct}}%)</span> ${{vStr}}`;
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

        // 📱 MOBILE TOUCH SUPPORT (Finger Drag for BUY/SL/TGT Lines & Drawing Tools)
        container.addEventListener('touchstart', (e) => {{
            if (!e.touches || e.touches.length === 0) return;
            const touch = e.touches[0];
            const rect = container.getBoundingClientRect();
            const my = touch.clientY - rect.top;

            let nearLine = false;
            if (activePos) {{
                const entY = candleSeries.priceToCoordinate(curEnt);
                const slY = candleSeries.priceToCoordinate(curSL);
                const tgY = candleSeries.priceToCoordinate(curTG);
                if ((entY !== null && Math.abs(my - entY) <= 18) ||
                    (slY !== null && Math.abs(my - slY) <= 18) ||
                    (tgY !== null && Math.abs(my - tgY) <= 18)) {{
                    nearLine = true;
                }}
            }}

            if (nearLine || currentTool) {{
                e.preventDefault();
                container.dispatchEvent(new MouseEvent('mousedown', {{
                    clientX: touch.clientX, clientY: touch.clientY, bubbles: true
                }}));
            }}
        }}, {{ passive: false }});

        window.addEventListener('touchmove', (e) => {{
            if (!draggingMode && !isFreeDrawing && !isFibFreeDragging && !currentTool) return;
            if (!e.touches || e.touches.length === 0) return;
            e.preventDefault();
            const touch = e.touches[0];
            window.dispatchEvent(new MouseEvent('mousemove', {{
                clientX: touch.clientX, clientY: touch.clientY, bubbles: true
            }}));
        }}, {{ passive: false }});

        window.addEventListener('touchend', (e) => {{
            if (!draggingMode && !isFreeDrawing && !isFibFreeDragging && !currentTool) return;
            const touch = (e.changedTouches && e.changedTouches.length > 0) ? e.changedTouches[0] : null;
            window.dispatchEvent(new MouseEvent('mouseup', {{
                clientX: touch ? touch.clientX : 0, clientY: touch ? touch.clientY : 0, bubbles: true
            }}));
        }}, {{ passive: false }});
        const stageEl = container.parentElement || container;
        let _initialScrollDone = false;
        function syncChartSize() {{
            const w = stageEl.clientWidth || container.clientWidth;
            const h = Math.max(180, (stageEl.clientHeight || container.clientHeight) - 8);
            const isMob = w < 420;
            chart.applyOptions({{
                width: w,
                height: h,
                timeScale: {{ rightOffset: isMob ? 4 : 3, barSpacing: isMob ? 3.5 : {bar_sp} }}
            }});
            if (!_initialScrollDone && cData.length > 0) {{
                const visBars = isMob ? Math.min(cData.length, 55) : Math.min(cData.length, 75);
                chart.timeScale().setVisibleLogicalRange({{
                    from: Math.max(0, cData.length - visBars),
                    to: cData.length + (isMob ? 4 : 2)
                }});
                _initialScrollDone = true;
            }}
            renderAllDrawings();
        }}
        setTimeout(syncChartSize, 50);
        setTimeout(syncChartSize, 250);
        new ResizeObserver(() => syncChartSize()).observe(stageEl);
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
            _core_set = set(list(INDICES_MAP.keys()) + list(SECTOR_INDICES_MAP.keys()) + list(COMMODITY_MAP.keys()) + [f"{s}.NS" for s in (set(NIFTY_50 + FNO_STOCKS + MIDCAP_150) - _SKIP_BAD_SYMS)])
            target_list = [t for t in tkrs_tuple if t in _core_set]
        else:
            target_list = list(INDICES_MAP.keys()) + list(COMMODITY_MAP.keys())
        q_data = yf.download(target_list, period="7d", interval="1d", progress=False, group_by='ticker', threads=10, timeout=5)
        if q_data.empty:
            return {}
        if isinstance(q_data.columns, pd.MultiIndex) and ('Close' in q_data.columns.levels[0] or 'Open' in q_data.columns.levels[0]):
            q_data = q_data.swaplevel(axis=1)
        out = {}
        minutes = get_minutes_passed()
        syms = q_data.columns.levels[0] if isinstance(q_data.columns, pd.MultiIndex) else []
        for s in syms:
            sdf = q_data[s].dropna(subset=['Close'])
            if not sdf.empty:
                ltp = float(sdf['Close'].iloc[-1])
                op = float(sdf['Open'].iloc[-1])
                hi = float(sdf['High'].iloc[-1])
                lo = float(sdf['Low'].iloc[-1])
                pc = float(sdf['Close'].iloc[-2]) if len(sdf) >= 2 else op
                vx = None
                if 'Volume' in sdf.columns and len(sdf) >= 6:
                    avg_v5 = float(sdf['Volume'].iloc[-6:-1].mean())
                    cur_v = float(sdf['Volume'].iloc[-1])
                    if avg_v5 > 0 and cur_v > 0:
                        vx = round(cur_v / ((avg_v5 / 375.0) * minutes), 1)
                out[s] = (ltp, op, hi, lo, pc, vx)
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
    col_main_80, col_side_20 = st.columns([4.02, 1.22], gap="small")

    # ---------------------------------------------------------
    # 👉 RIGHT 20% PANEL: COMPACT CONTROLS + EXCEL WATCHLIST
    # ---------------------------------------------------------
    with col_side_20:
        right_panel_box = st.container(height=720, border=True)
        with right_panel_box:
            st.markdown("<div class='right-panel-marker'></div>", unsafe_allow_html=True)
            _wl_modes = [
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
                "📝 Paper Trading 💼",
                "Commodity 🛢️",
                "Fundamentals 🏢",
                "Mutual Funds 📈",
                "Month Effect Advantage 📅"
            ]
            _saved_wl = _UI.get('watchlist_mode', _wl_modes[0])
            _wl_idx = _wl_modes.index(_saved_wl) if _saved_wl in _wl_modes else 0
            watchlist_mode = st.selectbox("Watchlist / Strategy", _wl_modes, index=_wl_idx, label_visibility="collapsed")
            _UI['watchlist_mode'] = watchlist_mode

            move_type_filter = ["All Day Trading Moves 🚀"]
            fund_filter = "Top Ranked Stocks ⭐"

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
                        _UI['selected_ai_strats'] = list(st.session_state.selected_ai_strats)
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
                        _UI['selected_sw_strats'] = list(st.session_state.selected_sw_strats)
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
            view_mode = st.radio("Mode:", ["Heat Map", "Chart 📈", "News 📰"], index=default_view_idx, horizontal=True)
            _UI['view_mode'] = view_mode

            _grid_opts = ["Off", "1", "2", "4", "6"]
            _cur_g = _UI.get('grid_layout_mode', 'Off')
            if 'pro_grid_radio_key' not in st.session_state or st.session_state.pro_grid_radio_key != _cur_g:
                st.session_state.pro_grid_radio_key = _cur_g if _cur_g in _grid_opts else "Off"

            sel_grid = st.radio("📐 Grid:", _grid_opts, key="pro_grid_radio_key", horizontal=True, on_change=_on_grid_radio_change)
            st.session_state.grid_layout_mode = sel_grid
            _UI['grid_layout_mode'] = sel_grid

            with st.expander("⚙️ Filters, Sort & Search", expanded=False):
                st.session_state.pause_refresh = st.toggle("⏸️ Pause Refresh", value=st.session_state.pause_refresh)
                _sort_opts = [
                    "Score: High to Low ⭐ (Top First)",
                    "Intraday Pullback Max 📉 (DH / DL)",
                    "52W Pullback Max 📉 (Deep Discount)",
                    "% Change: High to Low 🟢",
                    "% Change: Low to High 🔴",
                    "Score: Low to High ⬆️"
                ]
                _saved_sort = _UI.get('sort_mode', _sort_opts[0])
                _sort_idx = _sort_opts.index(_saved_sort) if _saved_sort in _sort_opts else 0
                sort_mode = st.selectbox(
                    "Sort By",
                    _sort_opts,
                    index=_sort_idx,
                    key="main_sort_sel",
                    on_change=_on_filter_sort_change
                )
                _UI['sort_mode'] = sort_mode
                search_stock = st.selectbox("Search Stock", ["-- None --"] + all_names)
                _tf_opts = ["Intraday (5m)", "Daily Chart", "Weekly Chart"]
                _default_tf = 1 if watchlist_mode in ["Swing Trading 📈", "Legendary Strategy 🏆"] else 0
                chart_timeframe = st.radio("Timeframe", _tf_opts, index=_default_tf)
                _UI['chart_timeframe'] = chart_timeframe
                show_crosshair = st.toggle("⌖ Mini-Chart Crosshair (Price/Time)", value=False)
                show_vol = st.toggle("📊 Mini-Chart Vol Bars", value=False)

            side_watchlist_slot = st.container()

    # ---------------------------------------------------------
    # 👉 FAST DATA ENGINE (FIXED: LIVE VOLX, TRUE 5M VWAP/EMA10, NR7 & BULL/BEAR POWER)
    # ---------------------------------------------------------
    if st.session_state.pause_refresh:
        with col_main_80:
            st.info("⏸️ Data refresh is paused.")
        return

    df_live = (
        fetch_all_data()
        .drop_duplicates(subset=['T'], keep='first')
        .reset_index(drop=True)
        .copy()
    )
    _m_open_top = is_market_open()

    if not df_live.empty:
        _fast_quotes = fetch_fast_live_quotes(tuple(df_live['Fetch_T'].tolist()), _m_open_top)
        with LIVE_PRICES_LOCK:
            _live_snap = dict(LIVE_PRICES_GLOBAL)
        for _i, _r in df_live.iterrows():
            _ft = str(_r['Fetch_T'])
            _csym = _ft.replace(".NS", "")
            if _ft in _fast_quotes:
                _ltp, _op, _hi, _lo, _pc, _vx = _fast_quotes[_ft]
                df_live.at[_i, 'P'], df_live.at[_i, 'O'], df_live.at[_i, 'H'], df_live.at[_i, 'L'] = _ltp, _op, _hi, _lo
                df_live.at[_i, 'Prev_C'] = _pc
                if _vx is not None and _vx > 0:
                    df_live.at[_i, 'VolX'] = _vx
            if _csym in _live_snap:
                _nltp = _live_snap[_csym]
                df_live.at[_i, 'P'] = _nltp
                if _nltp > df_live.at[_i, 'H']: df_live.at[_i, 'H'] = _nltp
                if _nltp < df_live.at[_i, 'L'] or df_live.at[_i, 'L'] == 0: df_live.at[_i, 'L'] = _nltp

            # Live Recalculation of Day_C, Net_C, Bull_P, Bear_P & 52W Pullback
            _p_now = float(df_live.at[_i, 'P'])
            _o_now = float(df_live.at[_i, 'O'])
            _h_now = float(df_live.at[_i, 'H'])
            _l_now = float(df_live.at[_i, 'L'])
            _pc_now = float(df_live.at[_i, 'Prev_C'])
            _h52_now = float(df_live.at[_i, 'High52W'])

            if _o_now > 0: df_live.at[_i, 'Day_C'] = ((_p_now - _o_now) / _o_now) * 100.0
            if _pc_now > 0: df_live.at[_i, 'C'] = ((_p_now - _pc_now) / _pc_now) * 100.0
            if _h52_now > 0: df_live.at[_i, 'Pullback_52W'] = ((_h52_now - _p_now) / _h52_now) * 100.0
            _rng_now = _h_now - _l_now
            if _rng_now > 0:
                df_live.at[_i, 'Bull_P'] = ((_p_now - _l_now) / _rng_now) * 100.0
                df_live.at[_i, 'Bear_P'] = ((_h_now - _p_now) / _rng_now) * 100.0

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
    core_tkrs = tuple(sorted(list(set(df_indices['Fetch_T'].tolist() + df_sectors['Fetch_T'].tolist() + df_commodities['Fetch_T'].tolist() + df_stocks['Fetch_T'].tolist() + st.session_state.pinned_stocks))))
    processed_charts, nifty_intra_html, sniper_cached_res = _fast_5m_and_sniper_cache(core_tkrs)

    # 🔥 TRUE 5-MIN VWAP & 5-MIN EMA_10 SYNC INTO DATAFRAMES
    _true_vwap_map = {}
    _intra_ema10_map = {}
    for _sym_k, _df_5m in processed_charts.items():
        if _df_5m is not None and not _df_5m.empty:
            if 'VWAP' in _df_5m.columns and pd.notna(_df_5m['VWAP'].iloc[-1]) and float(_df_5m['VWAP'].iloc[-1]) > 0:
                _true_vwap_map[_sym_k] = float(_df_5m['VWAP'].iloc[-1])
            if 'EMA_10' in _df_5m.columns and pd.notna(_df_5m['EMA_10'].iloc[-1]) and float(_df_5m['EMA_10'].iloc[-1]) > 0:
                _intra_ema10_map[_sym_k] = float(_df_5m['EMA_10'].iloc[-1])

    for _target_df in (df_live, df_all_stocks, df_stocks):
        _target_df['VWAP'] = _target_df['Fetch_T'].map(_true_vwap_map).fillna(_target_df['VWAP'])
        _target_df['Intra_EMA10'] = _target_df['Fetch_T'].map(_intra_ema10_map).fillna(_target_df['VWAP'])

    df_lookup = df_live.drop_duplicates(subset=['Fetch_T'], keep='first').set_index('Fetch_T').to_dict('index')
    weekly_trends = {}
    for sym, sym_row in df_lookup.items():
        w_ema10, w_ema50, last_p = float(sym_row.get('W_EMA10', 0)), float(sym_row.get('W_EMA50', 0)), float(sym_row.get('P', 0))
        weekly_trends[sym] = 'Bullish' if (last_p > w_ema10 and w_ema10 >= w_ema50) else ('Bearish' if (last_p < w_ema10 and w_ema10 <= w_ema50) else 'Neutral')

    # 🔥 1. TODAY PERFORMING SECTOR POINTS (Buy & Sell Sectors ki Extra Points)
    df_nifty = df_all_stocks[df_all_stocks['T'].isin(NIFTY_50)].copy()
    sector_perf = df_nifty.groupby('Sector')['C'].mean().sort_values(ascending=False)
    sector_perf = sector_perf[sector_perf.index != "OTHER"]

    sector_bull_perf = sector_perf[sector_perf > 0].sort_values(ascending=False)
    bull_bonus_map = {sec: max(10 - (rank * 2), 0) for rank, sec in enumerate(sector_bull_perf.index)}

    sector_bear_perf = sector_perf[sector_perf < 0].sort_values(ascending=True)
    bear_bonus_map = {sec: max(10 - (rank * 2), 0) for rank, sec in enumerate(sector_bear_perf.index)}

    # 🔥 2. 5-MIN TREND SCORE & ALPHA TAGS
    alpha_tags, trend_scores = {}, {}
    nifty_dist_5m = 0.25
    if "^NSEI" in processed_charts and not processed_charts["^NSEI"].empty:
        _nd = processed_charts["^NSEI"]
        _nltp, _nvwap = float(_nd['Close'].iloc[-1]), float(_nd['VWAP'].iloc[-1])
        if _nvwap > 0:
            nifty_dist_5m = max(abs(_nltp - _nvwap) / _nvwap * 100.0, 0.25)

    for sym, df_day in processed_charts.items():
        if df_day is None or df_day.empty:
            continue
        last_price = float(df_day['Close'].iloc[-1])
        last_vwap = float(df_day['VWAP'].iloc[-1])
        sym_info = df_lookup.get(sym, {})
        net_chg = float(sym_info.get('C', 0))

        alpha_tag = ""
        if len(df_day) >= 50 and last_vwap > 0:
            stock_dist_5m = abs(last_price - last_vwap) / last_vwap * 100.0
            if stock_dist_5m > (nifty_dist_5m * 3): alpha_tag = "🚀Alpha-Mover"
            elif stock_dist_5m > (nifty_dist_5m * 2): alpha_tag = "💪Nifty-Beater"

        one_sided_tag, trend_bonus = "", 0
        if len(df_day) >= 12 and last_vwap > 0:
            trend_candles = (df_day['Low'] >= df_day['VWAP']).sum() if net_chg > 0 else (df_day['High'] <= df_day['VWAP']).sum()
            if (trend_candles / len(df_day)) >= 0.85:
                current_gap_pct = abs(last_price - last_vwap) / last_vwap * 100.0
                if current_gap_pct >= 1.50: one_sided_tag, trend_bonus = "🌊Mega-1.5%", 7
                elif current_gap_pct >= 1.00: one_sided_tag, trend_bonus = "🌊Super-1.0%", 5
                elif current_gap_pct >= 0.50: one_sided_tag, trend_bonus = "🌊Trend-0.5%", 3
                else: one_sided_tag, trend_bonus = "🌊Trend", 1

        trap_tag, trap_bonus = "", 0
        if len(df_day) >= 6 and last_vwap > 0:
            curr_open = float(df_day['Open'].iloc[-1])
            day_open, day_high, day_low = float(sym_info.get('O', 0)), float(sym_info.get('H', 0)), float(sym_info.get('L', 0))
            morning_spike = (day_high - day_open) / day_open * 100.0 if day_open > 0 else 0
            morning_drop = (day_open - day_low) / day_open * 100.0 if day_open > 0 else 0
            if morning_spike >= 1.0 and last_price < last_vwap and last_price < curr_open:
                trap_tag, trap_bonus = "🎯 Reversal Sell 🩸", 6
            elif morning_drop >= 1.0 and last_price > last_vwap and last_price > curr_open:
                trap_tag, trap_bonus = "🎯 Reversal Buy 🚀", 6

        alpha_tags[sym] = f"{alpha_tag} {one_sided_tag} {trap_tag}".strip()
        trend_scores[sym] = trend_bonus + trap_bonus

    # 🔥 3. ADD SECTOR BONUS & TREND SCORE ONLY FOR TERMINAL TABLES, HIGH SCORE & DAY TRADING
    for _tdf in (df_all_stocks, df_stocks):
        _tdf['AlphaTag'] = _tdf['Fetch_T'].map(alpha_tags).fillna("")
        if watchlist_mode in ["Terminal Tables 🗃️", "High Score Stocks 🔥", "Day Trading Stocks 🚀"]:
            _tdf['Trend_Score'] = pd.to_numeric(_tdf['Fetch_T'].map(trend_scores), errors='coerce').fillna(0).astype(int)
            _tdf['Sector_Bonus'] = np.where(
                _tdf['Day_C'] >= 0,
                _tdf['Sector'].map(bull_bonus_map).fillna(0),
                _tdf['Sector'].map(bear_bonus_map).fillna(0)
            ).astype(int)
            _tdf['S'] = _tdf['S'] + _tdf['Trend_Score'] + _tdf['Sector_Bonus']
        else:
            _tdf['Trend_Score'] = 0
            _tdf['Sector_Bonus'] = 0

    df_filtered = df_stocks.copy()
    sort_key = "W_C" if chart_timeframe == "Weekly Chart" else "Day_C"

    if watchlist_mode == "My Portfolio 💼":
        port_tickers = [f"{str(sym).upper().strip()}.NS" for sym in df_port_saved['Symbol'].tolist() if str(sym).strip() != ""]
        df_filtered = df_all_stocks[df_all_stocks['Fetch_T'].isin(port_tickers)].copy()
    elif watchlist_mode == "📝 Paper Trading 💼":
        pp_df_now = load_paper_portfolio()
        pp_tickers = [f"{str(sym).upper().strip()}.NS" for sym in pp_df_now['Symbol'].tolist() if str(sym).strip() != ""] if not pp_df_now.empty else []
        df_filtered = df_all_stocks[df_all_stocks['Fetch_T'].isin(pp_tickers)].copy()
    elif watchlist_mode == "Commodity 🛢️":
        df_filtered = df_commodities.copy()
    elif watchlist_mode == "F&O + Top 200 Heatmap 🗺️":
        df_filtered = df_all_stocks[df_all_stocks['T'].isin(set(NIFTY_50 + FNO_STOCKS))].copy()
    elif watchlist_mode == "Day Trading Stocks 🚀":
        df_filtered = df_stocks[df_stocks['C'].abs() >= 1.0].copy()
        df_filtered['Strategy_Icon'] = np.where(df_filtered['Day_C'] >= 0, "🚀 BUY", "🩸 SELL")
    elif watchlist_mode in ["High Score Stocks 🔥", "Terminal Tables 🗃️"]:
        df_filtered = df_stocks[df_stocks['S'] >= 10].copy()
    elif "AI Predictions" in watchlist_mode:
        # ✅ BUG #1 FIXED: Uses 5-min Intra_EMA10 & True 5-min VWAP instead of Weekly W_EMA10
        intra_ema = df_filtered['Intra_EMA10'].where(df_filtered['Intra_EMA10'] > 0, df_filtered['VWAP'])
        base_buy = (df_filtered['P'] > intra_ema) & (df_filtered['P'] > df_filtered['VWAP'])
        base_sell = (df_filtered['P'] < intra_ema) & (df_filtered['P'] < df_filtered['VWAP'])

        ai_strats_to_run = list(move_type_filter) if isinstance(move_type_filter, list) else [move_type_filter]
        if "All Day Trading Moves 🚀" in ai_strats_to_run:
            for _core_s in [
                "🔥 First Hour Vol Breakout (ORB+VWAP)",
                "💥 Inside Bar Vol Breakout (NR7)",
                "🧲 Intraday Dip & Support Bounce",
                "⚡ Sudden VWAP Cross (Any Time)",
                "🚀 Gap & Go (Open = Low)",
                "💥 PDH / PDL Breakout"
            ]:
                if _core_s not in ai_strats_to_run:
                    ai_strats_to_run.append(_core_s)

        all_dfs = []
        for strat in ai_strats_to_run:
            if strat == "All Day Trading Moves 🚀":
                continue

            # 1. 🧠 ORDER-FLOW SNIPER (Pure 5-Pillar Quant Score)
            if strat == ADAPTIVE_STRAT:
                for _side, _label in (('buy', 'BUY'), ('sell', 'SELL')):
                    _rows = sniper_cached_res.get(_side, [])
                    if not _rows:
                        continue
                    _m = {r['sym']: r for r in _rows}
                    _sub = df_filtered[df_filtered['Fetch_T'].isin(list(_m.keys()))].copy()
                    if _sub.empty:
                        continue
                    _sub['AI_Prob'] = _sub['Fetch_T'].map(lambda s: int(_m[s]['score']))
                    _sub = _sub.sort_values('AI_Prob', ascending=False)
                    _sub['Strategy_Icon'] = f"🎯 Sniper {_label}"
                    _sub['AlphaTag'] = _sub['Fetch_T'].map(lambda s: f"🎯{_m[s]['tag']} ({_m[s]['score']}%)")
                    _sub['S'] = [35 - 2 * _k for _k in range(len(_sub))]
                    all_dfs.append(_sub)

            # 2. 📰 NEWS + VOL + PRICE CATALYST (Pure News Score)
            elif strat == NEWS_STRAT:
                _df_news, _ = run_news_vol_price_strategy(df_filtered, processed_charts, min_volx=1.2, min_move_pct=0.75)
                if not _df_news.empty:
                    all_dfs.append(_df_news)

            # 3. 🔥 FIRST HOUR VOL BREAKOUT (ORB + VWAP)
            elif strat == "🔥 First Hour Vol Breakout (ORB+VWAP)":
                orb_vol = df_filtered['VolX'] >= 1.5
                c_buy = base_buy & (df_filtered['Day_C'] > 1.0) & orb_vol & (df_filtered['P'] > df_filtered['O']) & ((df_filtered['O'] - df_filtered['L']) <= (df_filtered['P'] * 0.005))
                c_sell = base_sell & (df_filtered['Day_C'] < -1.0) & orb_vol & (df_filtered['P'] < df_filtered['O']) & ((df_filtered['H'] - df_filtered['O']) <= (df_filtered['P'] * 0.005))
                for _mask, _lbl, _asc in [(c_buy, "🚀 1-Hr BO BUY", False), (c_sell, "🩸 1-Hr BO SELL", True)]:
                    _sub = df_filtered[_mask].sort_values(by=['VolX', 'Day_C'], ascending=[False, _asc]).head(5).copy()
                    if not _sub.empty:
                        _sub['S'] = (14 + np.clip(_sub['VolX'] * 3.0, 2, 10) + np.clip(_sub['Day_C'].abs() * 1.5, 1, 6)).astype(int)
                        _sub['AI_Prob'] = np.clip(65 + _sub['S'], 72, 97).astype(int)
                        _sub['Strategy_Icon'] = _lbl
                        all_dfs.append(_sub)

            # 4. 💥 INSIDE BAR VOL BREAKOUT (NR7) — ✅ BUG #4 FIXED
            elif strat == "💥 Inside Bar Vol Breakout (NR7)":
                ib_vol = df_filtered['VolX'] >= 1.2
                prev_range_pct = (df_filtered['Prev_H'] - df_filtered['Prev_L']) / (df_filtered['Prev_L'] + 0.001)
                ib_narrow_prev = (prev_range_pct <= 0.022) | (df_filtered['Narrow_CPR'] == True)
                c_buy = base_buy & ib_vol & ib_narrow_prev & (df_filtered['P'] > df_filtered['O']) & ((df_filtered['P'] > df_filtered['Prev_H']) | (df_filtered['Day_C'] >= 0.75))
                c_sell = base_sell & ib_vol & ib_narrow_prev & (df_filtered['P'] < df_filtered['O']) & ((df_filtered['P'] < df_filtered['Prev_L']) | (df_filtered['Day_C'] <= -0.75))
                for _mask, _lbl, _asc in [(c_buy, "💥 NR7 BO BUY", False), (c_sell, "🩸 NR7 BO SELL", True)]:
                    _sub = df_filtered[_mask].sort_values(by=['VolX', 'Day_C'], ascending=[False, _asc]).head(5).copy()
                    if not _sub.empty:
                        _prev_r = (_sub['Prev_H'] - _sub['Prev_L']) / (_sub['Prev_L'] + 0.001) * 100.0
                        _tight_pts = np.clip((3.0 - _prev_r) * 3.5, 2, 10)
                        _sub['S'] = (13 + _tight_pts + np.clip(_sub['VolX'] * 2.5, 2, 8)).astype(int)
                        _sub['AI_Prob'] = np.clip(65 + _sub['S'], 72, 96).astype(int)
                        _sub['Strategy_Icon'] = _lbl
                        all_dfs.append(_sub)

            # 5. 🧲 INTRADAY DIP & SUPPORT BOUNCE — ✅ BUG #1 FIXED (Uses 5m Intra_EMA10)
            elif strat == "🧲 Intraday Dip & Support Bounce":
                day_pb = ((df_filtered['H'] - df_filtered['P']) / (df_filtered['H'] + 0.001)) * 100.0
                dip_ok = (day_pb >= 0.8) & (day_pb <= 3.0)
                near_vwap_b = (df_filtered['P'] >= df_filtered['VWAP'] * 0.998) & (df_filtered['L'] <= df_filtered['VWAP'] * 1.003)
                near_ema_b = (df_filtered['P'] >= intra_ema * 0.998) & (df_filtered['L'] <= intra_ema * 1.003)
                c_buy = base_buy & dip_ok & (near_vwap_b | near_ema_b) & (df_filtered['P'] > df_filtered['O']) & (df_filtered['Day_C'] > 0) & (df_filtered['VolX'] >= 1.2)

                day_rl = ((df_filtered['P'] - df_filtered['L']) / (df_filtered['L'] + 0.001)) * 100.0
                rally_ok = (day_rl >= 0.8) & (day_rl <= 3.0)
                near_vwap_s = (df_filtered['P'] <= df_filtered['VWAP'] * 1.002) & (df_filtered['H'] >= df_filtered['VWAP'] * 0.997)
                near_ema_s = (df_filtered['P'] <= intra_ema * 1.002) & (df_filtered['H'] >= intra_ema * 0.997)
                c_sell = base_sell & rally_ok & (near_vwap_s | near_ema_s) & (df_filtered['P'] < df_filtered['O']) & (df_filtered['Day_C'] < 0) & (df_filtered['VolX'] >= 1.2)

                for _mask, _lbl, _asc in [(c_buy, "🧲 Dip Bounce BUY", False), (c_sell, "🩸 Dip Reject SELL", True)]:
                    _sub = df_filtered[_mask].sort_values(by=['VolX', 'Day_C'], ascending=[False, _asc]).head(5).copy()
                    if not _sub.empty:
                        _prox_pts = np.clip(10.0 - ((_sub['P'] - _sub['VWAP']).abs() / (_sub['VWAP'] + 0.01) * 1500.0), 2, 10)
                        _sub['S'] = (14 + _prox_pts + np.clip(_sub['VolX'] * 2.0, 1, 6)).astype(int)
                        _sub['AI_Prob'] = np.clip(66 + _sub['S'], 74, 96).astype(int)
                        _sub['Strategy_Icon'] = _lbl
                        all_dfs.append(_sub)

            # 6. ⚡ SUDDEN VWAP CROSS (ANY TIME)
            elif strat == "⚡ Sudden VWAP Cross (Any Time)":
                buy_mask = pd.Series(False, index=df_filtered.index)
                sell_mask = pd.Series(False, index=df_filtered.index)
                for idx, r in df_filtered[df_filtered['VolX'] >= 1.3].iterrows():
                    df_hist = processed_charts.get(r['Fetch_T'], pd.DataFrame())
                    if not df_hist.empty and len(df_hist) >= 2 and 'VWAP' in df_hist.columns:
                        c1, c2 = df_hist.iloc[-1], df_hist.iloc[-2]
                        if ((c2['Close'] <= c2['VWAP']) and (c1['Close'] > c1['VWAP'])) or ((c1['Open'] <= c1['VWAP']) and (c1['Close'] > c1['VWAP'])):
                            buy_mask.loc[idx] = True
                        if ((c2['Close'] >= c2['VWAP']) and (c1['Close'] < c1['VWAP'])) or ((c1['Open'] >= c1['VWAP']) and (c1['Close'] < c1['VWAP'])):
                            sell_mask.loc[idx] = True
                for _mask, _lbl, _asc in [(base_buy & buy_mask, "⚡ VWAP Cross BUY", False), (base_sell & sell_mask, "🩸 VWAP Cross SELL", True)]:
                    _sub = df_filtered[_mask].sort_values(by=['VolX', 'Day_C'], ascending=[False, _asc]).head(5).copy()
                    if not _sub.empty:
                        _sub['S'] = (15 + np.clip(_sub['VolX'] * 3.5, 3, 12)).astype(int)
                        _sub['AI_Prob'] = np.clip(66 + _sub['S'], 75, 97).astype(int)
                        _sub['Strategy_Icon'] = _lbl
                        all_dfs.append(_sub)

            # 7. 🚀 GAP & GO (OPEN = LOW / OPEN = HIGH)
            elif strat == "🚀 Gap & Go (Open = Low)":
                high_vol = df_filtered['VolX'] >= 1.5
                c_buy = base_buy & ((df_filtered['O'] - df_filtered['L']) <= (df_filtered['P'] * 0.002)) & (df_filtered['O'] > df_filtered['Prev_C']) & high_vol & (df_filtered['Day_C'] > 0.5)
                c_sell = base_sell & ((df_filtered['H'] - df_filtered['O']) <= (df_filtered['P'] * 0.002)) & (df_filtered['O'] < df_filtered['Prev_C']) & high_vol & (df_filtered['Day_C'] < -0.5)
                for _mask, _lbl, _asc in [(c_buy, "🚀 Gap&Go BUY", False), (c_sell, "🩸 Gap&Go SELL", True)]:
                    _sub = df_filtered[_mask].sort_values(by=['VolX', 'Day_C'], ascending=[False, _asc]).head(5).copy()
                    if not _sub.empty:
                        _pwr_b = np.where((_sub.get('Bull_P', 0) >= 80) | (_sub.get('Bear_P', 0) >= 80), 5, 2)
                        _sub['S'] = (16 + np.clip(_sub['VolX'] * 3.0, 3, 10) + _pwr_b).astype(int)
                        _sub['AI_Prob'] = np.clip(67 + _sub['S'], 76, 98).astype(int)
                        _sub['Strategy_Icon'] = _lbl
                        all_dfs.append(_sub)

            # 8. 💥 PDH / PDL BREAKOUT
            elif strat == "💥 PDH / PDL Breakout":
                vol_confirm = df_filtered['VolX'] >= 1.8
                c_buy = base_buy & (df_filtered['P'] > df_filtered['Prev_H']) & vol_confirm
                c_sell = base_sell & (df_filtered['P'] < df_filtered['Prev_L']) & vol_confirm
                for _mask, _lbl, _asc in [(c_buy, "💥 PD Break BUY", False), (c_sell, "🩸 PD Break SELL", True)]:
                    _sub = df_filtered[_mask].sort_values(by=['VolX', 'Day_C'], ascending=[False, _asc]).head(5).copy()
                    if not _sub.empty:
                        _sub['S'] = (15 + np.clip(_sub['VolX'] * 3.5, 3, 12) + np.clip(_sub['Day_C'].abs() * 1.2, 1, 5)).astype(int)
                        _sub['AI_Prob'] = np.clip(66 + _sub['S'], 75, 98).astype(int)
                        _sub['Strategy_Icon'] = _lbl
                        all_dfs.append(_sub)

            # 9. 🤖 ALL MOVES (Pure AI Probability >= 70%)
            elif strat == "All Moves":
                up_prob = (
                    np.where(df_filtered['P'] > df_filtered['VWAP'], 25, 0) +
                    np.where(df_filtered['VolX'] >= 1.5, 20, 0) +
                    np.where(df_filtered.get('Bull_P', 0) >= 80, 30, 0) +
                    np.where((df_filtered['O'] - df_filtered['L']).abs() < (df_filtered['P'] * 0.002), 25, 0)
                )
                dn_prob = (
                    np.where(df_filtered['P'] < df_filtered['VWAP'], 25, 0) +
                    np.where(df_filtered['VolX'] >= 1.5, 20, 0) +
                    np.where(df_filtered.get('Bear_P', 0) >= 80, 30, 0) +
                    np.where((df_filtered['O'] - df_filtered['H']).abs() < (df_filtered['P'] * 0.002), 25, 0)
                )
                _sub_b = df_filtered[(up_prob >= 70) & (df_filtered['S'] >= 11)].copy()
                if not _sub_b.empty:
                    _sub_b['AI_Prob'] = up_prob[(up_prob >= 70) & (df_filtered['S'] >= 11)]
                    _sub_b['Strategy_Icon'] = "🚀 AI PREDICTS: UP"
                    all_dfs.append(_sub_b)
                _sub_s = df_filtered[(dn_prob >= 70) & (df_filtered['S'] >= 11)].copy()
                if not _sub_s.empty:
                    _sub_s['AI_Prob'] = dn_prob[(dn_prob >= 70) & (df_filtered['S'] >= 11)]
                    _sub_s['Strategy_Icon'] = "🩸 AI PREDICTS: DOWN"
                    all_dfs.append(_sub_s)

        if all_dfs:
            df_filtered = pd.concat(all_dfs).drop_duplicates(subset=['Fetch_T'], keep='first')
        else:
            df_filtered = pd.DataFrame(columns=df_filtered.columns)

        if not df_filtered.empty:
            is_sell_sig = df_filtered['Strategy_Icon'].astype(str).str.contains('🔴|SELL|DOWN|🩸', na=False)
            is_buy = ~is_sell_sig
            atr_val = df_filtered.get('ATR', df_filtered['P'] * 0.02)
            risk_amt = atr_val * 1.5
            df_filtered['SL'] = np.where(is_buy, (df_filtered['P'] - risk_amt).round(2), (df_filtered['P'] + risk_amt).round(2))
            df_filtered['T1'] = np.where(is_buy, (df_filtered['P'] + risk_amt).round(2), (df_filtered['P'] - risk_amt).round(2))
            df_filtered['T2'] = np.where(is_buy, (df_filtered['P'] + risk_amt * 2.0).round(2), (df_filtered['P'] - risk_amt * 2.0).round(2))

    elif watchlist_mode in ["Swing Trading 📈", "Legendary Strategy 🏆"]:
        has_history = (df_filtered['SMA200'] > 0) & (df_filtered['SMA150'] > 0)
        min_c1 = (df_filtered['P'] > df_filtered['SMA150']) & (df_filtered['P'] > df_filtered['SMA200'])
        min_c2 = (df_filtered['SMA50'] > df_filtered['SMA150']) & (df_filtered['SMA150'] > df_filtered['SMA200'])
        min_c3 = df_filtered['SMA200'] > df_filtered['SMA200_20D']
        min_c4 = df_filtered['P'] > df_filtered['SMA50']
        min_c5 = (df_filtered['P'] >= df_filtered['Low52W'] * 1.30) & (df_filtered['P'] >= df_filtered['High52W'] * 0.75)
        vcp_base_cond = has_history & min_c1 & min_c2 & min_c3 & min_c4 & min_c5

        strats_to_run = move_type_filter if isinstance(move_type_filter, list) else [move_type_filter]
        if "All Swing Trading Moves 📈" in strats_to_run or "All Swing Stocks" in strats_to_run:
            strats_to_run = [
                "📈 Minervini Trend Template (VCP)", "📉 Strict VCP (Price & Vol Contraction)",
                "🧲 The 20-EMA Holy Grail Pullback", "📉 RSI(2) Mean Reversion (Larry Connors)",
                "📦 Nicolas Darvas (Box Breakout)", "📦 Nicolas Darvas Modified",
                "📈 Stan Weinstein (Stage 2 Uptrend)", "💥 Dan Zanger (Volume Explosion)",
                "👑 King Strategy (SMA Bounce)"
            ]

        dfs_to_concat = []
        for strat in strats_to_run:
            if strat in ["📈 Minervini Trend Template (VCP)", "🔥 Minervini MidCap 150", "🚀 Minervini SmallCap 250"]:
                sub_df = df_filtered[vcp_base_cond].copy()
                if not sub_df.empty:
                    # 🏆 Minervini Author Score: Nearness to 52W High + Tightness + Volume
                    near_52h_pts = np.clip((25.0 - sub_df['Pullback_52W']) * 0.6, 2, 12)
                    vcp_bonus = np.where(sub_df['VCP_Contract'], 5, 0) + np.where(sub_df['VCP_Vol_Dry'], 4, 0)
                    sub_df['S'] = (10 + near_52h_pts + vcp_bonus).astype(int)
                    sub_df['Strategy_Icon'] = "🟢 M-VCP"
                    dfs_to_concat.append(sub_df)

            elif strat == "📉 Strict VCP (Price & Vol Contraction)":
                strict_c = vcp_base_cond & (df_filtered['VCP_Contract'] == True) & (df_filtered['VCP_Vol_Dry'] == True)
                sub_df = df_filtered[strict_c].copy()
                if not sub_df.empty:
                    # 🏆 Strict VCP Author Score: Rewards tighter contraction & proximity to pivot
                    box_tight_pts = np.clip((15.0 - ((sub_df['Box_Top20'] - sub_df['Box_Bot20']) / (sub_df['Box_Bot20'] + 0.01) * 100)) * 1.2, 2, 12)
                    sub_df['S'] = (15 + box_tight_pts).astype(int)
                    sub_df['Strategy_Icon'] = "🟢 Strict VCP"
                    dfs_to_concat.append(sub_df)

            elif strat == "🧲 The 20-EMA Holy Grail Pullback":
                hg_c = has_history & (df_filtered['P'] > df_filtered['SMA50']) & (df_filtered['SMA50'] > df_filtered['SMA150']) & (df_filtered['L'] <= df_filtered['EMA20'] * 1.015) & (df_filtered['P'] >= df_filtered['EMA20'] * 0.995) & (df_filtered['Day_C'] > 0)
                sub_df = df_filtered[hg_c].copy()
                if not sub_df.empty:
                    # 🏆 Holy Grail Author Score: Closer to 20-EMA + stronger bounce
                    ema_prox_pts = np.clip(10 - ((sub_df['P'] - sub_df['EMA20']).abs() / sub_df['EMA20'] * 300), 2, 10)
                    sub_df['S'] = (12 + ema_prox_pts + np.clip(sub_df['VolX'] * 2, 0, 6)).astype(int)
                    sub_df['Strategy_Icon'] = "🟢 Holy Grail"
                    dfs_to_concat.append(sub_df)

            elif strat == "📉 RSI(2) Mean Reversion (Larry Connors)":
                lc_c = has_history & (df_filtered['P'] > df_filtered['SMA200']) & (df_filtered['P'] < df_filtered['SMA20']) & ((df_filtered['RSI2'] <= 10.0) | ((df_filtered['RSI2'] <= 25.0) & (df_filtered['P'] > df_filtered['O'])))
                sub_df = df_filtered[lc_c].copy()
                if not sub_df.empty:
                    # 🏆 Larry Connors Author Score: Lower RSI(2) = Higher Mean-Reversion Edge!
                    rsi_edge_pts = np.clip((30.0 - sub_df['RSI2']) * 0.6, 2, 16)
                    sub_df['S'] = (10 + rsi_edge_pts).astype(int)
                    sub_df['Strategy_Icon'] = "🟢 RSI(2) Reversal"
                    dfs_to_concat.append(sub_df)

            elif strat in ["📦 Nicolas Darvas (Box Breakout)", "📦 Nicolas Darvas Modified"]:
                box_w = ((df_filtered['Box_Top20'] - df_filtered['Box_Bot20']) / (df_filtered['Box_Bot20'] + 0.001)) <= 0.22
                d_trend = has_history & min_c1 & min_c2 & min_c3 & (df_filtered['P'] >= df_filtered['High52W'] * 0.85) & box_w
                if "Modified" in strat:
                    d_bo = (df_filtered['P'] >= df_filtered['Box_Top20'] * 0.975) & (df_filtered['P'] <= df_filtered['Box_Top20'] * 1.01)
                    icon_lbl = "🟢 Darvas Anticipation"
                else:
                    d_bo = (df_filtered['P'] >= df_filtered['Box_Top20'] * 0.998) & (df_filtered['VolX'] >= 1.2)
                    icon_lbl = "🟢 Darvas Breakout"
                sub_df = df_filtered[d_trend & d_bo].copy()
                if not sub_df.empty:
                    # 🏆 Darvas Author Score: Box tightness + Volume power
                    sub_df['S'] = (14 + np.clip(sub_df['VolX'] * 3, 1, 12)).astype(int)
                    sub_df['Strategy_Icon'] = icon_lbl
                    dfs_to_concat.append(sub_df)

            elif strat == "📈 Stan Weinstein (Stage 2 Uptrend)":
                w_c = has_history & (df_filtered['P'] > df_filtered['SMA150']) & (df_filtered['SMA50'] > df_filtered['SMA150']) & (df_filtered['SMA150'] > df_filtered['SMA150_20D']) & (df_filtered['P'] <= df_filtered['SMA150'] * 1.20) & (df_filtered['P'] >= df_filtered['High52W'] * 0.75)
                sub_df = df_filtered[w_c].copy()
                if not sub_df.empty:
                    # 🏆 Weinstein Stage 2 Score: Freshness of breakout above rising 30-wk (150d) MA
                    slope_pts = np.clip(((sub_df['SMA150'] - sub_df['SMA150_20D']) / (sub_df['SMA150_20D'] + 0.01)) * 200, 2, 10)
                    sub_df['S'] = (12 + slope_pts + np.clip(sub_df['VolX'] * 2, 0, 6)).astype(int)
                    sub_df['Strategy_Icon'] = "🟢 Stage 2"
                    dfs_to_concat.append(sub_df)

            elif strat == "💥 Dan Zanger (Volume Explosion)":
                bar_r = df_filtered['H'] - df_filtered['L']
                close_pos = (df_filtered['P'] - df_filtered['L']) / (bar_r + 0.001)
                z_c = has_history & (df_filtered['VolX'] >= 1.8) & min_c1 & min_c2 & (df_filtered['P'] >= df_filtered['High52W'] * 0.80) & (close_pos >= 0.70) & (df_filtered['P'] >= df_filtered['Box_Top20'] * 0.99)
                sub_df = df_filtered[z_c].copy()
                if not sub_df.empty:
                    # 🏆 Dan Zanger Author Score: RVOL Explosion weight
                    sub_df['S'] = (15 + np.clip(sub_df['VolX'] * 4, 4, 15)).astype(int)
                    sub_df['Strategy_Icon'] = "🟢 Zanger Explosion"
                    dfs_to_concat.append(sub_df)

            elif strat == "👑 King Strategy (SMA Bounce)":
                k_trend = has_history & min_c2
                t_50 = (df_filtered['L'] <= df_filtered['SMA50'] * 1.02) & (df_filtered['P'] >= df_filtered['SMA50'] * 0.99)
                t_150 = (df_filtered['L'] <= df_filtered['SMA150'] * 1.02) & (df_filtered['P'] >= df_filtered['SMA150'] * 0.99)
                sub_df = df_filtered[k_trend & (t_50 | t_150) & (df_filtered['Day_C'] > 0)].copy()
                if not sub_df.empty:
                    sub_df['S'] = (14 + np.clip(sub_df['Day_C'] * 2 + sub_df['VolX'] * 2, 2, 12)).astype(int)
                    sub_df['Strategy_Icon'] = "🟢 King SMA Bounce"
                    dfs_to_concat.append(sub_df)

            elif strat == "🎯 52WH Pullback & 52WL Breakdown (Top 32)":
                b_52 = df_filtered[has_history & (df_filtered['P'] > df_filtered['SMA200']) & (df_filtered['Pullback_52W'] <= 15.0)].copy()
                if not b_52.empty:
                    b_52['Strategy_Icon'] = "🟢 52WH Pullback"
                    b_52['S'] = (15 + np.clip(15.0 - b_52['Pullback_52W'], 1, 15)).astype(int)
                    dfs_to_concat.append(b_52.sort_values(by='S', ascending=False).head(32))
                dist_52l = ((df_filtered['P'] - df_filtered['Low52W']) / (df_filtered['Low52W'] + 0.01)) * 100
                s_52 = df_filtered[has_history & (df_filtered['P'] < df_filtered['SMA200']) & (dist_52l <= 15.0)].copy()
                if not s_52.empty:
                    s_52['Strategy_Icon'] = "🔴 52WL Breakdown"
                    s_52['S'] = (15 + np.clip(15.0 - dist_52l, 1, 15)).astype(int)
                    dfs_to_concat.append(s_52.sort_values(by='S', ascending=False).head(32))

            elif strat == "⏳ Anticipation SMA Base (20/50/150/200)":
                b_cond = has_history & (df_filtered['SMA150'] > df_filtered['SMA200'])
                for sma_col, lbl in [('SMA20', '🟢 20-SMA Base'), ('SMA50', '🟢 50-SMA Base'), ('SMA150', '🟢 150-SMA Base'), ('SMA200', '🟢 200-SMA Base')]:
                    near_m = (df_filtered[sma_col] > 0) & (df_filtered['P'] >= df_filtered[sma_col] * 0.975) & (df_filtered['P'] <= df_filtered[sma_col] * 1.025)
                    sub_df = df_filtered[b_cond & near_m].copy()
                    if not sub_df.empty:
                        prox_pts = np.clip(10 - ((sub_df['P'] - sub_df[sma_col]).abs() / sub_df[sma_col] * 400), 1, 10)
                        sub_df['S'] = (12 + prox_pts).astype(int)
                        sub_df['Strategy_Icon'] = lbl
                        dfs_to_concat.append(sub_df.sort_values(by='S', ascending=False).head(8))

        if dfs_to_concat:
            df_filtered = pd.concat(dfs_to_concat).drop_duplicates(subset=['Fetch_T'], keep='first')
        else:
            df_filtered = pd.DataFrame(columns=df_filtered.columns)

    # 🔥 UNIFIED SORTING: Watchlist Table & Charts 100% Same Order
    if not df_filtered.empty:
        df_filtered = df_filtered.copy()
        df_filtered['Chg_Pts'] = np.where(
            df_filtered['O'] > 0,
            df_filtered['P'] - df_filtered['O'],
            df_filtered['P'] * df_filtered['Day_C'] / 100.0
        )
        df_filtered['Intra_DH_PB'] = np.where(df_filtered['H'] > 0, ((df_filtered['H'] - df_filtered['P']) / df_filtered['H']) * 100, 0.0)
        df_filtered['Intra_DL_Bounce'] = np.where(df_filtered['L'] > 0, ((df_filtered['P'] - df_filtered['L']) / df_filtered['L']) * 100, 0.0)

        scol = st.session_state.wl_sort_col
        sasc = st.session_state.wl_sort_asc
        _tie_cols = ['S', 'AI_Prob', 'VolX', sort_key] if 'AI_Prob' in df_filtered.columns else ['S', 'VolX', sort_key]
        _tie_desc = [False] * len(_tie_cols)
        _tie_asc = [True, True, False, True] if 'AI_Prob' in df_filtered.columns else [True, False, True]

        if scol == "Symbol":
            df_sorted_base = df_filtered.sort_values(by='T', ascending=sasc)
        elif scol == "Last":
            df_sorted_base = df_filtered.sort_values(by='P', ascending=sasc)
        elif scol == "Chg":
            df_sorted_base = df_filtered.sort_values(by='Chg_Pts', ascending=sasc)
        elif scol == "Chg%":
            df_sorted_base = df_filtered.sort_values(by=sort_key, ascending=sasc)
        else:
            if sort_mode == "Intraday Pullback Max 📉 (DH / DL)":
                is_sell_m = df_filtered['Day_C'] < 0
                df_sorted_base = pd.concat([
                    df_filtered[~is_sell_m].sort_values(by=['Intra_DH_PB', 'S'], ascending=[False, False]),
                    df_filtered[is_sell_m].sort_values(by=['Intra_DL_Bounce', 'S'], ascending=[False, False])
                ])
            elif sort_mode == "52W Pullback Max 📉 (Deep Discount)":
                df_sorted_base = df_filtered.sort_values(by=['Pullback_52W', 'S'], ascending=[False, False])
            elif sort_mode in ("% Change: High to Low 🟢", "% Change Up 🟢"):
                df_sorted_base = df_filtered.sort_values(by=sort_key, ascending=False)
            elif sort_mode in ("% Change: Low to High 🔴", "% Change Down 🔴"):
                df_sorted_base = df_filtered.sort_values(by=sort_key, ascending=True)
            elif sort_mode == "Score: Low to High ⬆️":
                df_sorted_base = df_filtered.sort_values(by=_tie_cols, ascending=_tie_asc)
            else:
                # Default for ALL Strategies: Strictly HIGH SCORE to LOW SCORE (35 -> 13)
                df_sorted_base = df_filtered.sort_values(by=_tie_cols, ascending=_tie_desc)

        if scol is not None:
            df_stocks_display = df_sorted_base.reset_index(drop=True)
        else:
            if "AI Predictions" in watchlist_mode or watchlist_mode in ["Swing Trading 📈", "Legendary Strategy 🏆", "Day Trading Stocks 🚀"]:
                _sell_mask = df_sorted_base['Strategy_Icon'].astype(str).str.contains('🔴|SELL|DOWN|Stage 4|🩸|52WL', na=False)
            else:
                _sell_mask = df_sorted_base[sort_key] < 0

            df_stocks_display = pd.concat([df_sorted_base[~_sell_mask], df_sorted_base[_sell_mask]], ignore_index=True)

        if search_stock != "-- None --" and search_stock in df_stocks_display['T'].values:
            _srch_row = df_stocks_display[df_stocks_display['T'] == search_stock]
            _rest_rows = df_stocks_display[df_stocks_display['T'] != search_stock]
            df_stocks_display = pd.concat([_srch_row, _rest_rows], ignore_index=True)
    else:
        df_stocks_display = df_filtered.copy()
        # 🔥 1) Filter out stale/old-date stocks (like old ICICIPRULI) & 2) Attach News Headlines for Mini-Chart Hover
    if not df_stocks_display.empty and chart_timeframe == "Intraday (5m)" and "^NSEI" in processed_charts and not processed_charts["^NSEI"].empty:
        _mkt_latest_dt = processed_charts["^NSEI"].index.date[-1]
        _valid_today_fts = [
            ft for ft in df_stocks_display['Fetch_T']
            if (ft in processed_charts and not processed_charts[ft].empty and processed_charts[ft].index.date[-1] == _mkt_latest_dt)
        ]
        if _valid_today_fts:
            df_stocks_display = df_stocks_display[df_stocks_display['Fetch_T'].isin(_valid_today_fts)].reset_index(drop=True)

    if not df_stocks_display.empty:
        _top_news_map = fetch_live_stock_news_batch(tuple(df_stocks_display['Fetch_T'].head(30).tolist()))
        df_stocks_display['News_Headline'] = df_stocks_display['Fetch_T'].map(lambda s: (_top_news_map.get(s) or {}).get('title', ''))
        df_stocks_display['News_Cat'] = df_stocks_display['Fetch_T'].map(lambda s: (_top_news_map.get(s) or {}).get('tag', '📰 News'))
        df_stocks_display['News_Age'] = df_stocks_display['Fetch_T'].map(lambda s: f"{(_top_news_map.get(s) or {}).get('age_h', 0):.1f}h ago" if s in _top_news_map else '')
        df_stocks_display['News_Link'] = df_stocks_display['Fetch_T'].map(lambda s: (_top_news_map.get(s) or {}).get('link', '#'))

    # ---------------------------------------------------------
    # 👉 POPULATE RIGHT 20% WATCHLIST (EXCEL HTML TABLE) & INSPECTOR
    # ---------------------------------------------------------
    with side_watchlist_slot:
        with st.expander("📋 Watchlist Table (Click Headers to Sort)", expanded=True):
            st.markdown("<div class='tv-sort-hdr-marker'></div>", unsafe_allow_html=True)
            sh1, sh2, sh3, sh4 = st.columns([0.36, 0.22, 0.20, 0.22], gap="small")
            arr = "▲" if st.session_state.wl_sort_asc else "▼"
            with sh1:
                st.button(f"Symbol{arr if st.session_state.wl_sort_col=='Symbol' else ''}", key="s_sym", width="stretch", on_click=_set_wl_sort, args=("Symbol",))
            with sh2:
                st.button(f"Last{arr if st.session_state.wl_sort_col=='Last' else ''}", key="s_lst", width="stretch", on_click=_set_wl_sort, args=("Last",))
            with sh3:
                st.button(f"Chg{arr if st.session_state.wl_sort_col=='Chg' else ''}", key="s_chg", width="stretch", on_click=_set_wl_sort, args=("Chg",))
            with sh4:
                st.button(f"Chg%{arr if st.session_state.wl_sort_col=='Chg%' else ''}", key="s_pct", width="stretch", on_click=_set_wl_sort, args=("Chg%",))

            with st.container(height=235, border=False):
                wl_rows = [sr for _, sr in df_stocks_display.head(48).iterrows()]

                wl_html = '<table class="term-table" style="margin-top:0px; border-top:none;"><tbody>'
                for i, r_item in enumerate(wl_rows):
                    bg_class = "row-dark" if i % 2 == 0 else "row-light"
                    s_ft = r_item['Fetch_T']
                    s_name = str(r_item['T'])[:8]
                    s_ltp = float(r_item['P'])
                    s_chg_pct = float(r_item['Day_C'])
                    s_open = float(r_item.get('O', 0))
                    s_chg_pts = (s_ltp - s_open) if s_open > 0 else (s_ltp * s_chg_pct / 100.0)

                    p_str = f"{s_ltp:.1f}" if s_ltp < 10000 else f"{s_ltp:.0f}"
                    c_str = f"{s_chg_pts:+.1f}" if abs(s_chg_pts) < 100 else f"{s_chg_pts:+.0f}"
                    pct_str = f"{s_chg_pct:+.2f}%"

                    c_col = "text-green" if s_chg_pct >= 0 else "text-red"
                    grid_link = f"?grid_sym={s_ft}"
                    is_in_grid = s_ft in st.session_state.pinned_stocks
                    pin_dot = "📌" if is_in_grid else ""
                    name_style = "color:#00BFFF; font-weight:bold;" if is_in_grid else "text-decoration:none;"

                    wl_html += f'<tr class="{bg_class}">'
                    wl_html += f'<td class="t-symbol" style="width:36%; text-align:left; padding-left:8px;"><a href="{grid_link}" target="_self" style="{name_style}">{pin_dot}{s_name}</a></td>'
                    wl_html += f'<td style="width:22%; text-align:right; color:#ffd700; font-weight:bold; padding-right:8px; border-left:none;">{p_str}</td>'
                    wl_html += f'<td class="{c_col}" style="width:20%; text-align:right; padding-right:8px; border-left:none;">{c_str}</td>'
                    wl_html += f'<td class="{c_col}" style="width:22%; text-align:right; padding-right:8px; border-left:none;">{pct_str}</td>'
                    wl_html += '</tr>'
                wl_html += '</tbody></table>'
                st.markdown(wl_html, unsafe_allow_html=True)

        if search_stock != "-- None --":
            insp_sym = search_stock
        elif st.session_state.get('inspected_stock') and st.session_state.inspected_stock in df_live['T'].values:
            insp_sym = st.session_state.inspected_stock
        elif len(wl_rows) > 0:
            insp_sym = wl_rows[0]['T']
        else:
            insp_sym = "NIFTY"

        insp_df = df_live[df_live['T'] == insp_sym]
        insp_row = insp_df.iloc[0] if not insp_df.empty else None

        if insp_row is not None:
            i_p = float(insp_row['P'])
            i_pct = float(insp_row['Day_C'])
            i_open = float(insp_row.get('O', 0))
            i_pts = (i_p - i_open) if i_open > 0 else (i_p * i_pct / 100.0)
            i_h, i_l = float(insp_row.get('H', i_p)), float(insp_row.get('L', i_p))
            i_vx = float(insp_row.get('VolX', 1.0))
            i_sec = str(insp_row.get('Sector', 'NSE EQUITY'))
            i_strat = str(insp_row.get('Strategy_Icon', 'Active'))
            pos_pct = min(100, max(5, int(((i_p - i_l) / (i_h - i_l + 0.001)) * 100)))
            c_hex = "#3fb950" if i_pct >= 0 else "#f85149"

            st.markdown(
                f"<div style='background:#111622; border:1px solid #30363d; padding:5px 8px; margin-top:2px; border-radius:6px;'>"
                f"<div style='display:flex; justify-content:space-between; align-items:center;'>"
                f"<span style='font-weight:bold; font-size:12px; color:#fff;'>🔍 {insp_row['T']}</span>"
                f"<span style='font-size:9px; background:#1e293b; color:#38bdf8; padding:1px 5px; border-radius:4px;'>{i_strat}</span></div>"
                f"<div style='font-size:15px; font-weight:bold; color:#fff; font-family:monospace; margin-top:1px;'>₹{i_p:,.2f} "
                f"<span style='font-size:11px; color:{c_hex};'>{i_pts:+.2f} ({i_pct:+.2f}%)</span></div>"
                f"<div style='display:flex; justify-content:space-between; font-size:9px; color:#8b949e; margin-top:2px;'>"
                f"<span>L: ₹{i_l:.1f}</span><span>Day Range ({i_sec})</span><span>H: ₹{i_h:.1f}</span></div>"
                f"<div style='width:100%; background:#21262d; height:4px; border-radius:3px; margin-top:2px;'>"
                f"<div style='width:{pos_pct}%; background:{c_hex}; height:4px; border-radius:3px;'></div></div>"
                f"<div style='display:flex; justify-content:space-between; font-size:9.5px; color:#c9d1d9; margin-top:2px;'>"
                f"<span>RVOL: <b style='color:#00BFFF;'>{i_vx:.1f}x</b></span>"
                f"<span>VWAP: <b style='color:#ffd700;'>₹{float(insp_row.get('VWAP', i_p)):.1f}</b></span></div>"
                f"</div>",
                unsafe_allow_html=True
            )

    # ---------------------------------------------------------
    # 👉 LEFT 80% COLUMN: 1-LINE UNIFIED TOP BAR + MAX-SPACE CHARTS
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
            if 47.0 <= _buy_pct <= 53.0 or _above_vwap == _below_vwap:
                _mkt_dir_text, _mkt_dir_bg, _mkt_dir_border = f"⚖️ NEUTRAL {_above_vwap}/{_tot_stocks} ({_buy_pct:.0f}%)", "#484f58", "#8b949e"
            elif _above_vwap > _below_vwap:
                if _buy_pct >= 75.0:
                    _mkt_dir_text, _mkt_dir_bg, _mkt_dir_border = f"🚀 ULTRA BUY {_above_vwap}/{_tot_stocks} ({_buy_pct:.0f}%)", "#009624", "#00e676"
                elif _buy_pct >= 65.0:
                    _mkt_dir_text, _mkt_dir_bg, _mkt_dir_border = f"🔥 STRONG BUY {_above_vwap}/{_tot_stocks} ({_buy_pct:.0f}%)", "#238636", "#3fb950"
                else:
                    _mkt_dir_text, _mkt_dir_bg, _mkt_dir_border = f"🟢 BUY 📈 {_above_vwap}/{_tot_stocks} ({_buy_pct:.0f}%)", "#1e5f29", "#2ea043"
            else:
                if _sell_pct >= 75.0:
                    _mkt_dir_text, _mkt_dir_bg, _mkt_dir_border = f"💀 ULTRA SELL {_below_vwap}/{_tot_stocks} ({_sell_pct:.0f}%)", "#b71c1c", "#ff1744"
                elif _sell_pct >= 65.0:
                    _mkt_dir_text, _mkt_dir_bg, _mkt_dir_border = f"🩸 STRONG SELL {_below_vwap}/{_tot_stocks} ({_sell_pct:.0f}%)", "#c62828", "#ff5252"
                else:
                    _mkt_dir_text, _mkt_dir_bg, _mkt_dir_border = f"🔴 SELL 📉 {_below_vwap}/{_tot_stocks} ({_sell_pct:.0f}%)", "#b52524", "#f85149"

        _dir_box_html = f"<span style='background:{_mkt_dir_bg};border:1px solid {_mkt_dir_border};color:#ffffff;padding:3px 10px;border-radius:5px;font-weight:bold;font-size:13.5px;white-space:nowrap;'>{_mkt_dir_text}</span>"
        _status_border = "#238636" if _m_open_top else "#f85149"
        _status_title = "🟢 <b style='font-size:14px;'>LIVE</b>" if _m_open_top else "🔴 <b style='font-size:14px;'>CLOSED</b>"

        _flash_str = fetch_indian_and_global_market_news().get("flash_ticker", "")
        _flash_html = f"<div class='flash-ticker-wrap'><div id='flash-ticker-el' class='flash-ticker-move'>📢 <b>తెలుగు మార్కెట్ వార్తలు:</b> {_flash_str} &nbsp;&nbsp;&nbsp;✦&nbsp;&nbsp;&nbsp; 📢 <b>తెలుగు మార్కెట్ వార్తలు:</b> {_flash_str}</div></div>" if _flash_str else ""

        _status_bar_html = (
            f"<div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:nowrap;gap:8px;"
            f"background:#161b22;border:1.5px solid {_status_border};border-radius:6px;padding:0px 12px;"
            f"height:38px;margin-bottom:4px;font-size:14px;overflow:hidden;white-space:nowrap;'>"
            f"<div style='display:flex;align-items:center;gap:8px;flex-shrink:0;'>{_status_title}{_dir_box_html}</div>"
            f"{_flash_html}"
            f"<span id='live-cd-badge' data-ts='{_run_ts}' style='background:#21262d;border:1px solid #30363d;color:#00BFFF;"
            f"padding:2px 8px;border-radius:4px;font-weight:bold;font-size:13px;font-family:monospace;flex-shrink:0;'>⏳ {_effective_refresh}s</span>"
            f"</div>"
        )

        # 🔥 ONE-LINE UNIFIED HEADER (Wider Status Bar so Telugu Flash News is clearly visible even in Grid Mode)
        if st.session_state.grid_layout_mode != "Off":
            tb_status, tb_mode, tb_qty, tb_back, tb_theme, tb_clear = st.columns([5.5, 1.1, 0.65, 0.75, 0.9, 0.7], gap="small")
            with tb_status:
                st.markdown(_status_bar_html, unsafe_allow_html=True)
            with tb_mode:
                st.markdown("<div class='pro-ActionBar'></div>", unsafe_allow_html=True)
                _t_modes = ["📝 Paper Trading", "⚡ Dhan Live Order", "🚀 Dhan Super Order (SL+TGT)"]
                _cur_tm = _UI.get('trade_mode', "📝 Paper Trading")
                _tm_idx = _t_modes.index(_cur_tm) if _cur_tm in _t_modes else 0
                st.selectbox(
                    "Trade Mode", _t_modes,
                    index=_tm_idx,
                    key="tr_mode_key",
                    label_visibility="collapsed",
                    on_change=_on_trade_cfg_change
                )
            with tb_qty:
                st.markdown("<div class='pro-ActionBar'></div>", unsafe_allow_html=True)
                st.selectbox(
                    "Qty", [1, 5, 10, 25, 50, 100, 250, 500],
                    index=[1, 5, 10, 25, 50, 100, 250, 500].index(_UI.get('trade_qty', 10)) if _UI.get('trade_qty', 10) in [1, 5, 10, 25, 50, 100, 250, 500] else 2,
                    key="tr_qty_key",
                    label_visibility="collapsed",
                    on_change=_on_trade_cfg_change
                )
            with tb_back:
                st.markdown("<div class='pro-ActionBar'></div>", unsafe_allow_html=True)
                st.button("🔙 Mini", key="btn_back_mini", width="stretch", on_click=_back_to_mini_charts)
            with tb_theme:
                st.markdown("<div class='pro-ActionBar'></div>", unsafe_allow_html=True)
                st.selectbox(
                    "Theme", ["Light (White)", "Dark (Terminal)"],
                    index=0 if "Light" in st.session_state.pro_grid_theme else 1,
                    key="pro_theme_sel_key",
                    label_visibility="collapsed",
                    on_change=_on_pro_theme_change
                )
            with tb_clear:
                st.markdown("<div class='pro-ActionBar'></div>", unsafe_allow_html=True)
                st.button("🗑️ Clear", key="btn_clear_all", width="stretch", on_click=_clear_all_pro_charts)
        else:
            st.markdown(_status_bar_html, unsafe_allow_html=True)

        components.html(
            f"""<!-- refresh_{_run_ts} -->
            <script>
            (function() {{
                const parentWin = window.parent;
                const parentDoc = parentWin.document;

                parentWin._isRight20Hidden = !!parentWin._isRight20Hidden;

                parentWin.applyRight20State = function(forceResize) {{
                    const hidden = !!parentWin._isRight20Hidden;

                    // 1. Direct ga Right 20% Column & Left 80% Column ni pattukuni Hide / 100% Expand cheyadam
                    const marker = parentDoc.querySelector('.right-panel-marker');
                    const col20 = marker ? marker.closest('[data-testid="stColumn"], [data-testid="column"]') : null;
                    const rowBlock = col20 ? col20.parentElement : null;
                    const col80 = rowBlock ? rowBlock.firstElementChild : null;

                    if (col20 && col80 && col20 !== col80) {{
                        if (hidden) {{
                            col20.style.setProperty('display', 'none', 'important');
                            col20.style.setProperty('width', '0px', 'important');
                            col20.style.setProperty('flex', '0 0 0px', 'important');
                            col80.style.setProperty('width', '100%', 'important');
                            col80.style.setProperty('flex', '1 1 100%', 'important');
                            col80.style.setProperty('max-width', '100%', 'important');
                        }} else {{
                            col20.style.removeProperty('display');
                            col20.style.removeProperty('width');
                            col20.style.removeProperty('flex');
                            col80.style.removeProperty('width');
                            col80.style.removeProperty('flex');
                            col80.style.removeProperty('max-width');
                        }}
                    }}

                    // 2. Live Line lo unna 'Hide 20%' button ki click event jodinchatam
                    const topBtn = parentDoc.getElementById('top-rp-btn');
                    if (topBtn) {{
                        topBtn.innerHTML = hidden ? '⏪ Show 20%' : '⏩ Hide 20%';
                        topBtn.style.background = hidden ? '#238636' : '#1f6feb';
                        topBtn.onclick = function(e) {{
                            e.preventDefault();
                            e.stopPropagation();
                            parentWin.toggleRight20Panel();
                        }};
                    }}

                    // 3. Right Edge lo unna floating 'HIDE / PANEL' button
                    let edgeTab = parentDoc.getElementById('rp-edge-toggle');
                    if (!edgeTab) {{
                        edgeTab = parentDoc.createElement('div');
                        edgeTab.id = 'rp-edge-toggle';
                        parentDoc.body.appendChild(edgeTab);
                    }}
                    edgeTab.innerHTML = hidden ? '◀ PANEL' : '▶ HIDE';
                    edgeTab.style.background = hidden ? '#238636' : '#1f6feb';
                    edgeTab.onclick = function(e) {{
                        e.preventDefault();
                        e.stopPropagation();
                        parentWin.toggleRight20Panel();
                    }};

                    if (forceResize) {{
                        setTimeout(() => parentWin.dispatchEvent(new Event('resize')), 30);
                        setTimeout(() => parentWin.dispatchEvent(new Event('resize')), 200);
                    }}
                }};

                parentWin.toggleRight20Panel = function() {{
                    parentWin._isRight20Hidden = !parentWin._isRight20Hidden;
                    parentWin.applyRight20State(true);
                }};

                parentWin.applyRight20State(true);

                // Streamlit prati sari update ayinappudu button click & hide state pookunda kapadutundi
                if (parentWin._rpSyncInterval) clearInterval(parentWin._rpSyncInterval);
                parentWin._rpSyncInterval = setInterval(() => parentWin.applyRight20State(false), 400);

                // Keep Flash News scrolling smoothly without resetting on 30s Streamlit refresh!
                if (!parentWin._flashEpoch) parentWin._flashEpoch = Date.now();
                const flashEl = parentDoc.getElementById('flash-ticker-el');
                if (flashEl) {{
                    const elapsedSec = ((Date.now() - parentWin._flashEpoch) / 1000) % 95;
                    flashEl.style.animationDelay = (-elapsedSec) + 's';
                }}
                // 4. Live Countdown Timer
                if (parentWin._stCdInterval) clearInterval(parentWin._stCdInterval);
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
                parentWin._stCdInterval = setInterval(updateBadge, 1000);
            }})();
            </script>""",
            height=0,
        )

        left_main_box = st.container(height=695, border=False)
        with left_main_box:
            st.markdown("<div class='left-main-scroll-marker'></div>", unsafe_allow_html=True)
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
                max_charts = int(st.session_state.grid_layout_mode)
                if st.session_state.pinned_stocks:
                    grid_syms = list(st.session_state.pinned_stocks)[:max_charts]
                else:
                    grid_syms = df_stocks_display['Fetch_T'].head(max_charts).tolist()
                    st.session_state.pinned_stocks = list(grid_syms)
                    _UI['pinned_stocks'] = list(grid_syms)

                n_cols = 1 if len(grid_syms) == 1 else (2 if max_charts <= 4 else 3)
                row_cls = "pro-grid-1row" if len(grid_syms) <= 2 else "pro-grid-2row"
                st.markdown(f"<div class='{row_cls}'></div>", unsafe_allow_html=True)
                c_height = 650 if len(grid_syms) <= 2 else 330

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
                if view_mode == "News 📰":
                    render_market_news_hub(df_all_stocks, processed_charts)
                elif watchlist_mode == "Fundamentals 🏢":
                
                    st.markdown(f"<div style='font-size:16px; font-weight:bold; margin-bottom:8px; color:#d29922;'>🏢 Core Fundamentals ({fund_filter})</div>", unsafe_allow_html=True)
                    fund_tickers = df_stocks_display['Fetch_T'].tolist()[:50] if not df_stocks_display.empty else [f"{s}.NS" for s in NIFTY_50[:50]]
                    df_fund = fetch_fundamentals_data(fund_tickers)
                    if not df_fund.empty:
                        if fund_filter == "🦅 Warren Buffett Value Stocks":
                            df_fund = df_fund[(df_fund['ROE %'] > 15) & (df_fund['Debt/Equity'] < 0.5) & (df_fund['P/E Ratio'] > 0) & (df_fund['P/E Ratio'] < 25)]
                        html_fund = '<table class="term-table"><thead><tr><th colspan="10" class="term-head-fund" style="background-color: #d29922; color: #161b22;">📊 FUNDAMENTAL & TECHNICAL METRICS</th></tr><tr><th style="text-align:left;">STOCK</th><th>SECTOR</th><th>LTP (₹)</th><th>TECH SCORE</th><th>MKT CAP (Cr)</th><th>P/E</th><th>ROE %</th><th>D/E Ratio</th><th>DIV YIELD</th><th>52W HIGH</th></tr></thead><tbody>'
                        for _, row in df_fund.iterrows():
                            stock_name = row["Fetch_T"].replace(".NS", "")
                            tech_row = df_stocks_display[df_stocks_display['Fetch_T'] == row["Fetch_T"]]
                            ltp_val, score_val = (float(tech_row['P'].iloc[0]), int(tech_row['S'].iloc[0])) if not tech_row.empty else (0.0, 0)
                            html_fund += f'<tr><td class="t-symbol">{stock_name}</td><td>{row["Sector"]}</td><td>{ltp_val:.2f}</td><td style="color:#ffd700;">⭐ {score_val}</td><td>{row["Market_Cap (Cr)"]:,.2f}</td><td>{row["P/E Ratio"]}</td><td class="text-green">{row["ROE %"]}%</td><td>{row["Debt/Equity"]}</td><td>{row["Div Yield %"]}%</td><td class="text-green">₹{row["52W High"]}</td></tr>'
                        html_fund += '</tbody></table>'
                        st.markdown(html_fund, unsafe_allow_html=True)
                    else:
                        st.info("Fundamentals data not available at the moment.")

                elif watchlist_mode == "Mutual Funds 📈":
                    st.markdown("<div style='font-size:16px; font-weight:bold; margin-bottom:8px; color:#00BFFF;'>📈 Mutual Funds Screener (Live Morningstar Data)</div>", unsafe_allow_html=True)
                    mc1, mc2 = st.columns(2)
                    with mc1:
                        selected_mf_cat = st.selectbox("Filter by Category", ["All Categories"] + list(MUTUAL_FUNDS.keys()))
                    with mc2:
                        sort_period = st.selectbox("Rank By Performance", ["1Y (%)", "3Y CAGR (%)", "5Y CAGR (%)"], index=2)
                    with st.spinner("Fetching Live Data from Morningstar..."):
                        df_mf_raw = fetch_mf_performance()
                    if not df_mf_raw.empty:
                        df_mf_raw['Sort_Key'] = pd.to_numeric(df_mf_raw[sort_period].replace('N/A', -999))
                        df_mf_raw = df_mf_raw.sort_values(by='Sort_Key', ascending=False)
                        df_mf_data = df_mf_raw[df_mf_raw['Category'] == selected_mf_cat] if selected_mf_cat != "All Categories" else df_mf_raw
                        df_mf_data = df_mf_data.drop(columns=['Sort_Key'], errors='ignore')
                        st.markdown(render_mf_table(df_mf_data), unsafe_allow_html=True)
                        st.markdown(f"<p style='font-size:11px; color:#888;'><i>*Note: Funds are auto-ranked based on <b>{sort_period}</b>. Returns > 20% are highlighted in Bright Green.</i></p>", unsafe_allow_html=True)
                    else:
                        st.error("Failed to fetch Mutual Fund data.")

                elif watchlist_mode == "Month Effect Advantage 📅":
                    st.markdown("<div style='font-size:16px; font-weight:bold; margin-bottom:8px; color:#00BFFF;'>📅 Month Effect Advantage (First 10 Days vs Rest)</div>", unsafe_allow_html=True)
                    st.markdown("<p style='font-size:13px; color:#c9d1d9;'>Top 200 stocks gata 5 yellalo prati nela <b>modati 10 rojullo</b> kachitamga momentum iche best stocks.</p>", unsafe_allow_html=True)
                    scan_list = st.radio("Select Universe to Scan:", ["Top 200 (Nifty + Midcap)", "NIFTY 50 Only", "Custom Stock"], horizontal=True)
                    if scan_list == "Custom Stock":
                        cust_stock = st.selectbox("Select Stock", all_names if all_names else NIFTY_50)
                        tkr_list = [f"{cust_stock}.NS"]
                    elif scan_list == "NIFTY 50 Only":
                        tkr_list = [f"{s}.NS" for s in NIFTY_50]
                    else:
                        tkr_list = [f"{s}.NS" for s in NIFTY_50 + MIDCAP_150]

                    if st.button("🚀 Run 5-Year Month Effect Analysis", width="stretch"):
                        end_dt = datetime.now()
                        start_dt = end_dt - pd.DateOffset(years=5)
                        m_data = yf.download(tkr_list, start=start_dt, end=end_dt, progress=False, group_by='ticker', threads=10)
                        me_res = []
                        for tkr in tkr_list:
                            try:
                                df_t = m_data[tkr] if len(tkr_list) > 1 else m_data
                                df_t = df_t.dropna(subset=['Close']).copy()
                                if df_t.empty: continue
                                df_t['Year'], df_t['Month'], df_t['Day'] = df_t.index.year, df_t.index.month, df_t.index.day
                                f10_rets, rest_rets, losing_rets, wins, tot_m = [], [], [], 0, 0
                                for _, grp in df_t.groupby(['Year', 'Month']):
                                    if len(grp) < 5: continue
                                    f10, rst = grp[grp['Day'] <= 10], grp[grp['Day'] > 10]
                                    if not f10.empty and not rst.empty:
                                        r1 = (f10['Close'].iloc[-1] - f10['Open'].iloc[0]) / f10['Open'].iloc[0] * 100
                                        r2 = (rst['Close'].iloc[-1] - rst['Open'].iloc[0]) / rst['Open'].iloc[0] * 100
                                        f10_rets.append(r1); rest_rets.append(r2)
                                        if r1 > 0: wins += 1
                                        if r1 < 0: losing_rets.append(r1)
                                        tot_m += 1
                                if tot_m > 0:
                                    avg_loss = sum(losing_rets) / len(losing_rets) if losing_rets else 0.0
                                    me_res.append({
                                        "Stock": tkr.replace(".NS", ""),
                                        "Win Rate (1st 10 Days) %": round(wins / tot_m * 100, 2),
                                        "Avg 1st-10th Return (%)": round(sum(f10_rets) / len(f10_rets), 2),
                                        "Avg Loss on Fail (%)": round(avg_loss, 2),
                                        "Avg Rest Return (%)": round(sum(rest_rets) / len(rest_rets), 2),
                                        "Total Months": tot_m
                                    })
                            except Exception:
                                pass
                        if me_res:
                            me_df = pd.DataFrame(me_res).sort_values(by=["Win Rate (1st 10 Days) %", "Avg 1st-10th Return (%)"], ascending=[False, False])
                            strict_cond = (
                                (me_df["Win Rate (1st 10 Days) %"] >= 55) &
                                (me_df["Avg 1st-10th Return (%)"] > 0.5) &
                                (me_df["Avg 1st-10th Return (%)"] > me_df["Avg Rest Return (%)"]) &
                                (me_df["Avg Loss on Fail (%)"] >= -6.0)
                            )
                            st.markdown("### 🏆 Top 10 Best Stocks (High Probability Swing)")
                            top_10 = me_df[strict_cond].head(10)
                            if not top_10.empty:
                                st.dataframe(top_10, use_container_width=True, hide_index=True)
                            st.markdown("### 📊 Full Data Analysis")
                            st.dataframe(me_df, use_container_width=True, hide_index=True)

                elif watchlist_mode == "Terminal Tables 🗃️" and view_mode == "Heat Map":
                    st.markdown(render_highscore_terminal_table(df_stocks_display), unsafe_allow_html=True)
                    st.markdown(render_levels_table(df_stocks_display), unsafe_allow_html=True)

                elif watchlist_mode == "📝 Paper Trading 💼":
                    render_paper_trading_terminal(df_all_stocks)
                elif watchlist_mode == "My Portfolio 💼" and view_mode == "Heat Map":
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

                    with st.expander("📊 Portfolio Allocation (Sector • Market-cap • Stock weights)", expanded=True):
                        try:
                            render_portfolio_allocation(df_port_saved, df_all_stocks)
                        except Exception as _pe:
                            st.caption(f"Allocation render error: {_pe}")

                    _avail_dates = ["All Dates"] + sorted(list(set(df_port_saved['Date'].dropna().astype(str).tolist()))) if not df_port_saved.empty and 'Date' in df_port_saved.columns else ["All Dates"]
                    sc1, sc2, sc3 = st.columns([0.4, 0.3, 0.3])
                    with sc2:
                        port_date_filter = st.selectbox("📅 Date Filter:", _avail_dates, label_visibility="collapsed")
                    with sc3:
                        port_sort = st.selectbox("↕️ Sort Portfolio:", ["Default", "Date (Newest) ⬇️", "Date (Oldest) ⬆️", "Days Held ⬆️", "Days Held ⬇️", "Day P&L ⬆️", "Day P&L ⬇️", "Total P&L ⬆️", "Total P&L ⬇️", "P&L % ⬆️", "P&L % ⬇️"], label_visibility="collapsed")

                    df_port_view = df_port_saved[df_port_saved['Date'].astype(str) == port_date_filter].copy() if (port_date_filter != "All Dates" and not df_port_saved.empty) else df_port_saved.copy()
                    st.markdown(render_portfolio_table(df_port_view, df_all_stocks, weekly_trends, port_sort), unsafe_allow_html=True)
                    st.markdown("<br>", unsafe_allow_html=True)

                    st.markdown(render_portfolio_news_and_results_table(df_port_saved, df_all_stocks, weekly_trends), unsafe_allow_html=True)
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

                        if submit_btn:
                            if new_sym:
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
                                        st.success(f"✅ {new_sym} యావరేజ్ చేయబడింది! (New Avg: ₹{round(base_price, 2)}, SL: {calc_sl})")
                                    else:
                                        new_row = pd.DataFrame({"Symbol": [new_sym], "Buy_Price": [new_price], "Quantity": [new_qty], "Date": [new_date_str], "SL": [calc_sl], "T1": [calc_t1], "T2": [calc_t2]})
                                        df_port_saved = pd.concat([df_port_saved, new_row], ignore_index=True)
                                        st.success(f"✅ {new_sym} పోర్ట్‌ఫోలియోలో యాడ్ చేయబడింది! (SL: {calc_sl}, T1: {calc_t1})")
                                    save_portfolio(df_port_saved)
                                    fetch_all_data.clear()
                                    load_portfolio.clear()
                                    time.sleep(1)
                                    st.rerun()
                            else:
                                st.warning("Type a symbol first!")

                    if not df_port_saved.empty:
                        with st.expander("✏️ Edit Existing Holdings (Targets, Qty, Price)", expanded=False):
                            st.markdown("<p style='font-size:12px; color:#888;'><i>Modify your SL, Targets, or Buy Price directly in the table below and click Save.</i></p>", unsafe_allow_html=True)
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
                                    try: current_qty = int(float(port_row['Quantity']))
                                    except: current_qty = 0
                                    sell_qty = min(sell_qty, current_qty)
                                    pnl_rs = (sell_price - buy_price) * sell_qty
                                    pnl_pct = ((sell_price - buy_price) / buy_price) * 100
                                    sell_date_str = datetime.now().strftime("%d-%b-%Y")
                                    df_closed = load_closed_trades()
                                    buy_date_str = str(port_row.get('Date', '-'))
                                    new_closed_row = pd.DataFrame({"Buy_Date": [buy_date_str], "Sell_Date": [sell_date_str], "Symbol": [sell_sym], "Quantity": [sell_qty], "Buy_Price": [buy_price], "Sell_Price": [sell_price], "PnL_Rs": [pnl_rs], "PnL_Pct": [pnl_pct]})
                                    df_closed = pd.concat([df_closed, new_closed_row], ignore_index=True)
                                    save_closed_trades(df_closed)
                                    df_port_saved = df_port_saved.copy()
                                    if sell_qty == current_qty: df_port_saved = df_port_saved[df_port_saved['Symbol'] != sell_sym]
                                    else: df_port_saved.loc[df_port_saved['Symbol'] == sell_sym, 'Quantity'] = current_qty - sell_qty
                                    save_portfolio(df_port_saved)
                                    fetch_all_data.clear()
                                    st.rerun()

                        with st.expander("📜 View Trade Book (Closed P&L Ledger)", expanded=False):
                            df_closed_view = load_closed_trades()
                            st.markdown(render_closed_trades_table(df_closed_view), unsafe_allow_html=True)
                            if not df_closed_view.empty:
                                st.download_button("📥 Download Trade Book (CSV)", data=df_closed_view.to_csv(index=False).encode('utf-8'), file_name="trade_book.csv", mime="text/csv")
                                st.markdown("<hr style='border-color:#30363d; margin-top:15px;'>", unsafe_allow_html=True)
                                st.markdown("<p style='font-size:12px; color:#ffd700;'>✏️ <b>Edit / Delete Closed Trades:</b> (రో ని సెలెక్ట్ చేసి Delete నొక్కండి, తర్వాత Save నొక్కండి)</p>", unsafe_allow_html=True)
                                edited_closed_df = st.data_editor(
                                    df_closed_view, width="stretch", hide_index=True,
                                    num_rows="dynamic", key="tradebook_editor"
                                )
                                if st.button("💾 Save Trade Book Changes", width="stretch", key="save_tb"):
                                    save_closed_trades(edited_closed_df)
                                    st.success("✅ Trade Book అప్డేట్ అయ్యింది!")
                                    time.sleep(1)
                                    st.rerun()

                elif view_mode == "Heat Map":
                    map_sort_key = "W_C" if chart_timeframe == "Weekly Chart" else "Day_C"
                    if not df_indices.empty and watchlist_mode != "Commodity 🛢️":
                        html_idx = '<div class="heatmap-grid">'
                        for _, row in df_indices.iterrows():
                            pct_val = float(row.get('W_C', row['Day_C'])) if chart_timeframe == "Weekly Chart" else float(row['Day_C'])
                            bg = "bear-card" if (row['T'] == "INDIA VIX" and pct_val > 0) else ("bull-card" if pct_val > 0 else "neut-card")
                            if row['T'] != "INDIA VIX" and pct_val < 0: bg = "bear-card"
                            html_idx += f'<a href="https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(row["Fetch_T"])}" target="_blank" class="stock-card {bg}"><div class="t-score">IDX</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{pct_val:+.2f}%</div></a>'
                        st.markdown(html_idx + '</div><hr class="custom-hr">', unsafe_allow_html=True)

                    if not df_sectors.empty and watchlist_mode != "Commodity 🛢️":
                        df_sectors_hm = df_sectors.sort_values(by=map_sort_key, ascending=False)
                        html_sec = '<div class="heatmap-grid">'
                        for _, row in df_sectors_hm.iterrows():
                            pct_val = float(row.get('W_C', row['Day_C'])) if chart_timeframe == "Weekly Chart" else float(row['Day_C'])
                            bg = card_bg_class(pct_val)
                            html_sec += f'<a href="https://in.tradingview.com/chart/?symbol={TV_SECTOR_URL.get(row["Fetch_T"], "")}" target="_blank" class="stock-card {bg}"><div class="t-score" style="color:#00BFFF;">SEC</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{pct_val:+.2f}%</div></a>'
                        st.markdown(html_sec + '</div><hr class="custom-hr">', unsafe_allow_html=True)

                    if not df_stocks_display.empty:
                        if watchlist_mode in ["Swing Trading 📈", "Legendary Strategy 🏆", "Day Trading Stocks 🚀"] or "AI Predictions" in watchlist_mode:
                            df_sell = df_stocks_display[df_stocks_display['Strategy_Icon'].str.contains('🔴|SELL|DOWN|Stage 4|🩸', na=False)]
                            df_buy = df_stocks_display[~df_stocks_display['Strategy_Icon'].str.contains('🔴|SELL|DOWN|Stage 4|🩸', na=False)]
                        else:
                            df_buy = df_stocks_display[df_stocks_display[sort_key] >= 0]
                            df_sell = df_stocks_display[df_stocks_display[sort_key] < 0]

                        for df_sec, title, col in [(df_buy, f"🟢 POSITIVE / BUY ({watchlist_mode})", "#3fb950"), (df_sell, f"🔴 NEGATIVE / SELL ({watchlist_mode})", "#f85149")]:
                            if not df_sec.empty:
                                st.markdown(f"<div style='font-size:15px; font-weight:bold; margin: 10px 0 4px 0; color:{col};'>{title}</div>", unsafe_allow_html=True)
                                html_stk = '<div class="heatmap-grid">'
                                for _, row in df_sec.iterrows():
                                    pct_val = float(row.get('W_C', row['Day_C'])) if chart_timeframe == "Weekly Chart" else float(row['Day_C'])
                                    bg = card_bg_class(pct_val)
                                    pb_val = row.get('Pullback_52W', 0)
                                    pb_html = f" | <span style='color:#FFD700; font-size:10px;'>📉-{pb_val:.0f}%</span>" if pb_val >= 3.0 else ""
                                    html_stk += f'<a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank" class="stock-card {bg}"><div class="t-score">⭐{int(row["S"])}</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{pct_val:+.2f}%{pb_html}</div></a>'
                                st.markdown(html_stk + '</div>', unsafe_allow_html=True)

                        st.markdown("<br>", unsafe_allow_html=True)
                        if "AI Predictions" in watchlist_mode:
                            with st.expander("🤖 View AI Predictive Radar (Probability Based)", expanded=True):
                                st.markdown(render_highscore_terminal_table(df_stocks_display), unsafe_allow_html=True)
                        elif watchlist_mode in ["Swing Trading 📈", "Legendary Strategy 🏆"]:
                            with st.expander(f"🌊 View {watchlist_mode} Radar (Ranked Table)", expanded=True):
                                st.markdown(render_swing_terminal_table(df_stocks_display), unsafe_allow_html=True)
                        elif watchlist_mode in ["High Score Stocks 🔥", "Day Trading Stocks 🚀"]:
                            with st.expander("🔥 View Day Trading Radar (Ranked Table)", expanded=True):
                                st.markdown(render_highscore_terminal_table(df_stocks_display), unsafe_allow_html=True)
                        elif watchlist_mode != "Commodity 🛢️":
                            with st.expander("🎯 View Trading Levels (Targets & Stop Loss)", expanded=True):
                                st.markdown(render_levels_table(df_stocks_display), unsafe_allow_html=True)
                    else:
                        st.info("No items found.")

                else:
                    if search_stock != "-- None --" and not df_live[df_live['T'] == search_stock].empty:
                        render_chart_grid(pd.DataFrame([df_live[df_live['T'] == search_stock].iloc[0]]), True, "search", chart_timeframe, chart_dict_to_use, show_crosshair, show_vol)
                        st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)

                    if watchlist_mode not in ["My Portfolio 💼", "Commodity 🛢️"]:
                        with st.expander("🌍 Global & Sectoral Indices Charts (Click to Expand / Minimize)", expanded=False):
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

                    pinned_df = df_live[
                        df_live['Fetch_T'].isin(st.session_state.pinned_stocks)
                    ].copy()
                    _exclude_fts = set(pinned_df['Fetch_T'].tolist())
                    if search_stock != '-- None --':
                      _exclude_fts.add(f'{search_stock}.NS')
                    unpinned_df = (
                        df_stocks_display[
                            ~df_stocks_display['Fetch_T'].isin(_exclude_fts)
                        ].drop_duplicates(subset=['T'], keep='first')
                        if not df_stocks_display.empty
                        else pd.DataFrame()
                    )

                    if not pinned_df.empty and watchlist_mode != "My Portfolio 💼":
                        st.markdown("<div style='font-size:15px; font-weight:bold; margin:6px 0 4px 0; color:#ffd700;'>📌 Pinned Priority Charts</div>", unsafe_allow_html=True)
                        render_chart_grid(pinned_df, True, "pin", chart_timeframe, chart_dict_to_use, show_crosshair, show_vol)
                        st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)

                    if watchlist_mode == "My Portfolio 💼":
                        if not df_stocks_display.empty:
                            st.markdown("<div style='font-size:15px; font-weight:bold; margin-bottom:4px; color:#00BFFF;'>📈 My Portfolio Stock Charts</div>", unsafe_allow_html=True)
                            render_chart_grid(df_stocks_display, True, "port_only_charts", chart_timeframe, chart_dict_to_use, show_crosshair, show_vol)
                        else:
                            st.info("ℹ️ Portfolio is empty.")
                    elif not unpinned_df.empty:
                        if "AI Predictions" in watchlist_mode or watchlist_mode in ["Swing Trading 📈", "Legendary Strategy 🏆", "Day Trading Stocks 🚀"]:
                            df_sell_chart = unpinned_df[unpinned_df['Strategy_Icon'].str.contains('🔴|SELL|DOWN|Stage 4|🩸|52WL', na=False)].head(24)
                            df_buy_chart = unpinned_df[~unpinned_df['Strategy_Icon'].str.contains('🔴|SELL|DOWN|Stage 4|🩸|52WL', na=False)].head(24)
                        else:
                            df_buy_chart = unpinned_df[unpinned_df[sort_key] >= 0].head(32)
                            df_sell_chart = unpinned_df[unpinned_df[sort_key] < 0].head(32)

                        if not df_buy_chart.empty:
                            st.markdown(f"<div style='font-size:15px; font-weight:bold; margin:6px 0 4px 0; color:#3fb950;'>🟢 POSITIVE / BUY ({watchlist_mode})</div>", unsafe_allow_html=True)
                            render_chart_grid(df_buy_chart, True, "main_buy", chart_timeframe, chart_dict_to_use, show_crosshair, show_vol)

                        if not df_sell_chart.empty:
                            st.markdown(f"<div style='font-size:15px; font-weight:bold; margin:14px 0 4px 0; color:#f85149;'>🔴 NEGATIVE / SELL ({watchlist_mode})</div>", unsafe_allow_html=True)
                            render_chart_grid(df_sell_chart, True, "main_sell", chart_timeframe, chart_dict_to_use, show_crosshair, show_vol)
                    elif df_stocks_display.empty:
                        st.info("ℹ️ No stocks matched this strategy's strict criteria at the moment. (ఏ స్టాక్స్ ఈ కండిషన్స్ ని మ్యాచ్ చేయలేదు)")

                # =========================================================
                # --- 📚 STRATEGY HELP GUIDE IN TELUGU (DYNAMIC) ---
                # =========================================================
                if "AI Predictions" in watchlist_mode or watchlist_mode == "Day Trading Stocks 🚀":
                    st.markdown("<hr style='border-color:#30363d; margin-top:20px;'>", unsafe_allow_html=True)
                    with st.expander("📚 ఈ డే ట్రేడింగ్ స్ట్రాటజీలను ఎలా వాడాలి? (Telugu Day Trading Guide)", expanded=False):
                        st.markdown("""
                        <div style='background-color:#161b22; padding:15px; border-radius:10px; border: 1px solid #30363d;'>
                        <h4 style='color:#00BFFF; margin-top:0px;'>🤖 AI Predictions Core Logic</h4>
                        <p style='color:#c9d1d9; font-size:14px; margin-bottom:15px;'>ఆల్గారిథమ్ వాల్యూమ్, VWAP దూరం, బుల్స్/బేర్స్ పవర్ (Bulls Power > 80), మరియు ఓపెన్=లో (O=L) లాంటి కండిషన్స్ ని చెక్ చేసి లైవ్ లో ఒక స్కోర్ ఇస్తుంది. ఈ స్కోర్ 70% దాటితేనే "🚀 AI PREDICTS: UP" లేదా "🩸 AI PREDICTS: DOWN" అని చూపిస్తుంది.</p>

                        <h4 style='color:#3fb950; margin-top:15px;'>1. 🔥 First Hour Vol Breakout (ORB+VWAP)</h4>
                        <ul style='color:#c9d1d9; font-size:14px;'>
                            <li><b>ఎప్పుడు వాడాలి:</b> మార్నింగ్ 9:30 AM నుండి 10:30 AM మధ్యలో.</li>
                            <li><b>లాజిక్ & ఎంట్రీ:</b> స్టాక్ కచ్చితంగా VWAP పైన ఉండాలి. ఉదయం ఓపెన్ అయిన ప్రైస్ కిందకి పడకుండా (Open Drive) పైకి వెళ్తూ, 1.5 రెట్ల (1.5x) వాల్యూమ్ తో బ్రేక్అవుట్ ఇస్తుంటే కొనాలి. VWAP కింద స్టాప్ లాస్.</li>
                        </ul>

                        <h4 style='color:#FFD700; margin-top:15px;'>2. ⚡ Sudden VWAP Cross (Any Time)</h4>
                        <ul style='color:#c9d1d9; font-size:14px;'>
                            <li><b>ఎప్పుడు వాడాలి:</b> రోజంతా ఎప్పుడైనా (ముఖ్యంగా మధ్యాహ్నం 1:00 PM తర్వాత బెస్ట్).</li>
                            <li><b>లాజిక్ & ఎంట్రీ:</b> అప్పటిదాకా VWAP కింద నెగటివ్ లో ఉన్న స్టాక్, సడెన్ గా పెద్ద వాల్యూమ్ తో (>= 1.3x) ఒకే 5-నిమిషాల క్యాండిల్ లో VWAP ని కింద నుండి పైకి క్రాస్ చేస్తే కొనాలి. క్రాస్ చేసిన క్యాండిల్ కిందే స్టాప్ లాస్.</li>
                        </ul>

                        <h4 style='color:#FF8C00; margin-top:15px;'>3. 🧲 Intraday Dip & Support Bounce</h4>
                        <ul style='color:#c9d1d9; font-size:14px;'>
                            <li><b>ఎప్పుడు వాడాలి:</b> మార్నింగ్ పెరిగి కాస్త వెనక్కి తగ్గినప్పుడు (Low Risk Entry కోసం).</li>
                            <li><b>లాజిక్ & ఎంట్రీ:</b> డే హై నుండి స్టాక్ 1% నుండి 3% వరకు పడి, కరెక్ట్ గా VWAP లైన్ లేదా 10-EMA లైన్ దగ్గర సపోర్ట్ తీసుకుని గ్రీన్ క్యాండిల్ వేస్తూ బౌన్స్ అవుతుంటే కొనాలి. సపోర్ట్ కిందే స్టాప్ లాస్.</li>
                        </ul>

                        <h4 style='color:#d29922; margin-top:15px;'>4. 💥 Inside Bar Vol Breakout (NR7)</h4>
                        <ul style='color:#c9d1d9; font-size:14px;'>
                            <li><b>ఎప్పుడు వాడాలి:</b> మొమెంటం బ్రేక్అవుట్స్ క్యాచ్ చేయడానికి.</li>
                            <li><b>లాజిక్ & ఎంట్రీ:</b> నిన్న ఒకే చిన్న రేంజ్ లో కదలకుండా ఉన్న (Inside Bar / Narrow Range) స్టాక్, ఈరోజు ఆ రేంజ్ ని వాల్యూమ్ తో బ్రేక్ చేస్తుంటే బ్రేక్అవుట్ ఎంట్రీ తీసుకోవాలి.</li>
                        </ul>

                        <h4 style='color:#2ea043; margin-top:15px;'>5. 🚀 Gap & Go (Open = Low)</h4>
                        <ul style='color:#c9d1d9; font-size:14px;'>
                            <li><b>ఎప్పుడు వాడాలి:</b> స్ట్రాంగ్ పాజిటివ్ ట్రెండ్ ఉన్న రోజుల్లో.</li>
                            <li><b>లాజిక్ & ఎంట్రీ:</b> గ్యాప్ అప్ తో ఓపెన్ అయిన స్టాక్, ఆ ఓపెన్ ప్రైస్ నే కనిష్టంగా (Open = Low) మార్చుకుని కిందకి రాకుండా పైకే వెళ్తుంటే ఈ స్కానర్ చూపిస్తుంది. ఈ స్టాక్స్ రోజంతా ట్రెండింగ్ లో ఉంటాయి.</li>
                        </ul>
                        </div>
                        """, unsafe_allow_html=True)

                elif watchlist_mode == "Legendary Strategy 🏆" or watchlist_mode == "Swing Trading 📈":
                    st.markdown("<hr style='border-color:#30363d; margin-top:20px;'>", unsafe_allow_html=True)
                    with st.expander("📚 ఈ స్వింగ్ ట్రేడింగ్ స్ట్రాటజీలను ఎలా వాడాలి? (Telugu Swing Trading Guide)", expanded=False):
                        st.markdown("""
                        <div style='background-color:#161b22; padding:15px; border-radius:10px; border: 1px solid #30363d;'>
                        <h4 style='color:#00BFFF; margin-top:0px;'>1. 👑 King Strategy (SMA Bounce)</h4>
                        <ul style='color:#c9d1d9; font-size:14px;'>
                            <li><b>ఎప్పుడు వాడాలి:</b> మంచి క్వాలిటీ స్టాక్స్ ని తక్కువ ధరకు (Buy on Dips) కొనేందుకు.</li>
                            <li><b>లాజిక్ & ఎంట్రీ:</b> లాంగ్ టర్మ్ ట్రెండ్ (50 SMA > 150 SMA > 200 SMA) పైన ఉండాలి. స్టాక్ పడుతూ వచ్చి 50 లేదా 150 SMA దగ్గర సపోర్ట్ తీసుకుని 1.2x వాల్యూమ్ తో బౌన్స్ అయితే కొనాలి.</li>
                        </ul>

                        <h4 style='color:#3fb950; margin-top:15px;'>2. 📈 Minervini Trend Template & Strict VCP</h4>
                        <ul style='color:#c9d1d9; font-size:14px;'>
                            <li><b>ఎప్పుడు వాడాలి:</b> పక్కా అప్‌ట్రెండ్ లో కన్సాలిడేట్ అవుతున్న స్టాక్స్ పట్టుకునేందుకు.</li>
                            <li><b>లాజిక్ & ఎంట్రీ:</b> 50 SMA > 150 SMA > 200 SMA ఉండాలి, 200 SMA పైకి వంగి ఉండాలి. ధర 52W Low కంటే 30% పైన మరియు 52W High కి 25% లోపలే ఉండాలి.</li>
                        </ul>

                        <h4 style='color:#FFD700; margin-top:15px;'>3. 📦 Nicolas Darvas & Modified Box</h4>
                        <ul style='color:#c9d1d9; font-size:14px;'>
                            <li><b>ఎప్పుడు వాడాలి:</b> 20-రోజుల బాక్స్ బ్రేక్అవుట్ దగ్గర కొనేందుకు (Buy High, Sell Higher).</li>
                            <li><b>లాజిక్ & ఎంట్రీ:</b> ధర 50 SMA పైన ఉండి, గత 20 రోజుల బాక్స్ రేంజ్ పై భాగాన్ని (Box Top) 1.5x వాల్యూమ్ తో బ్రేక్ చేస్తే కొనాలి.</li>
                        </ul>

                        <h4 style='color:#FF8C00; margin-top:15px;'>4. 🧲 The 20-EMA Holy Grail Pullback</h4>
                        <ul style='color:#c9d1d9; font-size:14px;'>
                            <li><b>ఎప్పుడు వాడాలి:</b> వేగంగా పెరుగుతున్న స్టాక్స్ కొద్దిగా పుల్ బ్యాక్ ఇచ్చినప్పుడు.</li>
                            <li><b>లాజిక్ & ఎంట్రీ:</b> ట్రెండ్ బాగుండి (Price > 50 SMA > 150 SMA), రీసెంట్ గా పడి <b>20-Day EMA</b> సపోర్ట్ ని టచ్ చేసి ఈరోజు గ్రీన్ క్యాండిల్ తో బౌన్స్ ఇస్తుంటే క్యాచ్ చేయాలి.</li>
                        </ul>

                        <h4 style='color:#d29922; margin-top:15px;'>5. 💥 Dan Zanger (Volume Explosion)</h4>
                        <ul style='color:#c9d1d9; font-size:14px;'>
                            <li><b>ఎప్పుడు వాడాలి:</b> సడెన్ గా ఇన్‌స్టిట్యూషన్స్ ఎంటర్ అయిన స్టాక్స్ పసిగట్టేందుకు.</li>
                            <li><b>లాజిక్ & ఎంట్రీ:</b> వాల్యూమ్ డ్రై అయిపోయి ప్రశాంతంగా ఉన్న స్టాక్ లో, ఈరోజు సడెన్ గా <b>2.0 రెట్ల (2.0x) వాల్యూమ్</b> తో పేలి 20-రోజుల బాక్స్ బ్రేక్అవుట్ ఇచ్చి క్యాండిల్ టాప్ 20% లో క్లోజ్ అయితే ఎంటర్ అవ్వాలి.</li>
                        </ul>

                        <h4 style='color:#f85149; margin-top:15px;'>6. 📉 RSI(2) Mean Reversion (Larry Connors)</h4>
                        <ul style='color:#c9d1d9; font-size:14px;'>
                            <li><b>ఎప్పుడు వాడాలి:</b> ఫాస్ట్ స్వింగ్స్ కోసం (2-5 రోజుల ట్రేడ్).</li>
                            <li><b>లాజిక్ & ఎంట్రీ:</b> 200 SMA పైన అప్‌ట్రెండ్ లో ఉన్న స్టాక్, సడెన్ సెల్లింగ్ వల్ల <b>2-Period RSI <= 10</b> కి పడిపోయి ఈరోజు గ్రీన్ క్యాండిల్ వేస్తుంటే కొనాలి.</li>
                        </ul>

                        <h4 style='color:#a371f7; margin-top:15px;'>7. 📈 Stan Weinstein (Stage 2 Uptrend)</h4>
                        <ul style='color:#c9d1d9; font-size:14px;'>
                            <li><b>ఎప్పుడు వాడాలి:</b> బేస్ నుండి కొత్త బుల్ రన్ (Stage 2) ప్రారంభమయ్యే స్టాక్స్ కోసం.</li>
                            <li><b>లాజిక్ & ఎంట్రీ:</b> ధర 150-Day SMA (30-Week MA) పైన ఉండాలి, 150 SMA పైకి స్లోప్ అవుతూ ఉండాలి.</li>
                        </ul>
                        </div>
                        """, unsafe_allow_html=True)

render_live_ui()
