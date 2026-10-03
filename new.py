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
import requests
import time
import threading
import concurrent.futures
from datetime import datetime, time as dt_time
import pandas_ta as ta
from dhanhq import dhanhq, marketfeed

try:
    from dhanhq import DhanContext
except ImportError:
    DhanContext = None

# =========================================================
# 🔥 FIX: GLOBAL LIVE PRICES (Thread Safe)
# =========================================================
LIVE_PRICES_GLOBAL = {}
LIVE_PRICES_LOCK = threading.Lock()

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

# --- 2. GOOGLE SHEETS CONNECTION ---
@st.cache_resource(show_spinner=False)
def init_connection():
    try:
        creds_json = st.secrets["gcp_service_account"]
    except KeyError:
        st.error("❌ Missing 'gcp_service_account' in secrets.toml")
        st.stop()
    creds_dict = json.loads(creds_json)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    db_sheet = client.open("Trading_DB")
    p_ws = db_sheet.worksheet("Portfolio")
    t_ws = db_sheet.worksheet("TradeBook")
    return p_ws, t_ws

try:
    port_ws, trade_ws = init_connection()
except Exception as e:
    st.error(f"గూగుల్ షీట్ కనెక్ట్ అవ్వలేదు బాస్! Error: {e}")
    st.stop()

# --- 3. DATA LOAD & SAVE FUNCTIONS ---
@st.cache_data(ttl=300, show_spinner=False)
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
        df = pd.DataFrame(records) if records else pd.DataFrame(columns=['Sell_Date', 'Symbol', 'Quantity', 'Buy_Price', 'Sell_Price', 'PnL_Rs', 'PnL_Pct'])
        if not df.empty and 'Stock Name' in df.columns:
            df.rename(columns={'Stock Name': 'Symbol', 'Buy Price': 'Buy_Price', 'Sell Price': 'Sell_Price', 'Sell Date': 'Sell_Date', 'Profit/Loss': 'PnL_Rs'}, inplace=True)
            if 'PnL_Pct' not in df.columns: df['PnL_Pct'] = 0.0
        return df
    except:
        return pd.DataFrame(columns=['Sell_Date', 'Symbol', 'Quantity', 'Buy_Price', 'Sell_Price', 'PnL_Rs', 'PnL_Pct'])

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

def toggle_pin(symbol):
    if symbol in st.session_state.pinned_stocks:
        st.session_state.pinned_stocks.remove(symbol)
    else:
        st.session_state.pinned_stocks.append(symbol)

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

MIDCAP_150 = [
    "AJANTPHARM", "APARINDS", "BANKINDIA", "CGPOWER", "DELHIVERY", "FORTIS", "INDIANB", "INDIGOPNTS", 
    "IREDA", "KALYANKJIL", "KPITTECH", "LTF", "LODHA", "MAXHEALTH", "MAZDOCK", "NHPC", 
    "NLCINDIA", "OIL", "PAYTM", "PBFINTECH", "PHOENIXLTD", "POONAWALLA", "RVNL", "SJVN", 
    "SONACOMS", "SUNDARMFIN", "SUPREMEIND", "SUZLON", "TATAELXSI", "TORNTPOWER", "UCOBANK", 
    "UNIONBANK", "VIJAYA", "YESBANK"
]

SMALLCAP_250 = [
    "AARTIDRUGS", "AAVAS", "AEGISCHEM", "AFFLE", "AJMERA", "AKZOINDIA", "ALEMBICLTD", "ALKYLAMINE", 
    "ALLCARGO", "ARE&M", "AMBER", "ANANDTHI", "ANURAS", "APLLTD", "APTUS", "ASAHIINDIA", 
    "ASTERDM", "ASTRAZEN", "BAJAJELEC", "BALAMINES", "BALMLAWRIE", "BANARISUG", "BASF", "BDL", 
    "BEML", "BFINVEST", "BHARATRAS", "BIRLACORPN", "BLS", "BOMDYEING", "BRIGADE", "BSOFT", 
    "CAMLINFINE", "CAMS", "CAPLIPOINT", "CARBORUNIV", "CASTROLIND", "CCL", "CEATLTD", "CENTRALBK", 
    "CENTURYPLY", "CENTURYTEX", "CERA", "CESC", "CHALET", "CHEMPLASTS", "CHENNPETRO", "CIGNITITEC", 
    "CUB", "CLEAN", "COFFEEDAY", "CRAFTSMAN", "CREDITACC", "CSBBANK", "CYIENT", 
    "DATAPATTNS", "DCBBANK", "DCMSHRIRAM", "DEEPAKFERT", "DELTACORP", "DHANUKA", "DBL", "DODLA", 
    "ECLERX", "EIDPARRY", "EIHOTEL", "EQUITASBNK", "ERIS", "ESABINDIA", "EVEREADY", "FACT", 
    "FDC", "FILATEX", "FINCABLES", "FINEORG", "FINPIPE", "FSL", "GABRIEL", 
    "GAEL", "GALAXYSURF", "GARFIBRES", "GATEWAY", "GICRE", "GILLETTE", "GLAXO", "GMDCLTD", 
    "GMMPFAUDLR", "GODREJAGRO", "GODREJIND", "GOKEX", "GRAPHITE", "GREAVESCOT", "GREENLAM", "GREENPANEL", 
    "GRINDWELL", "GSFC", "GSPL", "GUJALKALI", "HAPPSTMNDS", "HATHWAY", "HCG", "HEG", 
    "HEIDELBERG", "HERITGFOOD", "HFCL", "HGS", "HIKAL", "HIL", "HIMATSEIDE", "NDLVENTURES", 
    "HINDZINC", "HOMEFIRST", "HONAUT", "HSCL", "IBREALEST", "ICIL", "IDBI", 
    "IFBIND", "IIFL", "INDOCO", "INDORAMA", "INFIBEAM", "INGERRAND", 
    "INOXWIND", "INTELLECT", "IOB", "IONEXCHANG", "IRCON", "ISEC", "ISGEC", "ITI", 
    "J&KBANK", "JAGRAN", "JAICORPLTD", "JAMNAAUTO", "JBCHEPHARM", "JCHAC", "JINDALPOLY", "JINDWORLD", 
    "JKCEMENT", "JKLAKSHMI", "JKPAPER", "JKTYRE", "JMFINANCIL", "JPASSOCIAT", "JPPOWER", 
    "JTEKTINDIA", "JUBLINGEA", "JUBLPHARMA", "JUSTDIAL", "JYOTHYLAB", "KAJARIACER", "KPIL", 
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
    "ROUTE", "RSYSTEMS", "RUCHIRA", "RUPA", "SAFARI", "SAGCEM", "SANGHIIND", "SANGHVIMOV", 
    "SANSERA", "SAPPHIRE", "SARDAEN", "SAREGAMA", "SCHAEFFLER", "SCHAND", "SEAMEC", "SEQUENT", 
    "SFL", "SHALBY", "SHALPAINTS", "SHANKARA", "SHARDACROP", "SHARDAMOTR", "SHILPAMED", "SHOPERSTOP", 
    "SHREYANIND", "SJS", "SKFINDIA", "SNOWMAN", "SOBHA", "SOLARA", "SOMANYCERA", "SONATSOFTW", 
    "SOUTHBANK", "SPANDANA", "SPARC", "STAR", "STARCEMENT", "STCINDIA", "STLTECH", "STOVEKRAFT", 
    "SUBROS", "SUDARSCHEM", "SUMICHEM", "TVSHLDGS", "SUNFLAG", "SUNTECK", "SUPRAJIT", 
    "SURYAROSNI", "SUVENPHAR", "SYMPHONY", "SYRMA", "TASTYBITE", "TCI", "TCIEXP", 
    "TCPLPACK", "TEJASNET", "THANGAMAYL", "THERMAX", "THOMASCOOK", "TIDEWATER", "TIIL", "TIMETECHNO", 
    "TIMKEN", "TIPSIND", "TNPL", "TOKYOPLAST", "TRITURBINE", "TRIVENI", "TTKPRESTIG", 
    "UFO", "UJJIVANSFB", "UNIENTER", "UNIPARTS", "UTIAMC", "VAIBHAVGBL", "VAKRANGEE", "VARROC", 
    "VENKEYS", "VESUVIUS", "VGUARD", "VIDHIING", "VINATIORGA", "VIPIND", "VISAKAIND", "VISHNU", 
    "VTL", "WABAG", "WELCORP", "WELENT", "WELSPUNLIV", "WSTCSTPAPR", "XYLEM", 
    "YATHARTH", "ZENSARTECH", "ZENTEC", "ZYDUSWELL"
]

# --- DHAN API INITIALIZATION ---
if 'shown_dhan_status' not in st.session_state:
    st.session_state.shown_dhan_status = False

@st.cache_resource(show_spinner=False)
def init_dhan_client():
    try:
        c_id = str(st.secrets["dhan"]["client_id"]).strip()
        a_token = str(st.secrets["dhan"]["access_token"]).strip()
        if DhanContext:
            context = DhanContext(c_id, a_token)
            return dhanhq(context)
        else:
            return dhanhq(c_id, a_token)
    except Exception as e:
        return f"ERROR: {e}"

dhan_client = init_dhan_client()

if isinstance(dhan_client, str):
    st.sidebar.error(f"❌ Dhan Config Error: {dhan_client}")
    dhan = None
elif dhan_client:
    if not st.session_state.shown_dhan_status:
        st.toast("Dhan API Connected ✅", icon="🟢")
        st.session_state.shown_dhan_status = True
    dhan = dhan_client
else:
    st.sidebar.error("❌ Dhan API Connection Failed")
    dhan = None

@st.cache_data(ttl=86400)
def get_dhan_security_map():
    try:
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        df = pd.read_csv(url, low_memory=False)
        nse_eq = df[(df['SEM_EXM_EXCH_ID'] == 'NSE') & (df['SEM_INSTRUMENT_NAME'] == 'EQUITY')]
        return dict(zip(nse_eq['SEM_TRADING_SYMBOL'], nse_eq['SEM_SMST_SECURITY_ID'].astype(str)))
    except: return {}

sec_map = get_dhan_security_map()
rev_sec_map = {str(v): k for k, v in sec_map.items()} 

# --- WEBSOCKET LIVE TICKER (BACKGROUND THREAD) ---
@st.cache_resource
def start_live_ticker():
    try:
        if not sec_map:
            return False
        c_id = st.secrets["dhan"]["client_id"]
        a_token = st.secrets["dhan"]["access_token"]
        instruments = [(1, str(sec_id)) for sec_id in list(sec_map.values())[:500]]
        
        def on_connect(instance):
            pass
            
        def on_message(instance, message):
            if 'LTP' in message and 'SecurityId' in message:
                sec_id = str(message['SecurityId'])
                if sec_id in rev_sec_map:
                    sym = rev_sec_map[sec_id]
                    with LIVE_PRICES_LOCK:
                        LIVE_PRICES_GLOBAL[sym] = float(message['LTP'])
                    
        feed = marketfeed.DhanFeed(c_id, a_token, instruments, "v2", on_connect=on_connect, on_message=on_message)
        t = threading.Thread(target=feed.run_forever, daemon=True)
        t.start()
        return True
    except Exception as e:
        return False

start_live_ticker()

def get_minutes_passed():
    now = datetime.now()
    if now.weekday() >= 5: return 375
    if now.time() < dt_time(9, 15): return 1
    if now.time() > dt_time(15, 30): return 375
    open_time = now.replace(hour=9, minute=15, second=0)
    return min(375, max(1, int((now - open_time).total_seconds() / 60)))

# --- DHAN 5-MIN FETCH ---
def fetch_single_dhan_5m(symbol, sec_id):
    try:
        to_date = datetime.now().strftime('%Y-%m-%d')
        from_date = (datetime.now() - pd.Timedelta(days=5)).strftime('%Y-%m-%d')
        res = dhan.intraday_minute_data(symbol=sec_id, exchange_segment='NSE_EQ', instrument_type='EQUITY', from_date=from_date, to_date=to_date)
        if not isinstance(res, dict) or res.get('status') != 'success' or not res.get('data'):
            res = dhan.historical_minute_charts(symbol=sec_id, exchange_segment='NSE_EQ', instrument_type='EQUITY', expiry_code=0, from_date=from_date, to_date=to_date)
        
        if isinstance(res, dict) and res.get('status') == 'success' and res.get('data'):
            df = pd.DataFrame(res['data'])
            if not df.empty:
                try: df['Date'] = pd.to_datetime(df['start_Time'])
                except: df['Date'] = pd.to_datetime(df['start_Time'], unit='s')
                DHAN_EPOCH_OFFSET = 315513000
                if df['Date'].dt.year.min() < 2010:
                    df['Date'] = pd.to_datetime(df['start_Time'] + DHAN_EPOCH_OFFSET, unit='s') + pd.Timedelta(hours=5, minutes=30)
                df.set_index('Date', inplace=True)
                df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
                for col in ['Open', 'High', 'Low', 'Close', 'Volume']: df[col] = pd.to_numeric(df[col], errors='coerce')
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
                return symbol, df
    except: pass
    return symbol, pd.DataFrame()

@st.cache_data(ttl=30, show_spinner=False)
def fetch_cached_5m_data(tkrs_list):
    dhan_tasks, yf_tkrs, results_dict = {}, [], {}
    for tkr in tkrs_list:
        clean_sym = tkr.replace(".NS", "")
        if clean_sym in sec_map and not any(idx in tkr for idx in ["^", "=F"]):
            dhan_tasks[tkr] = (clean_sym, sec_map[clean_sym])
        else:
            yf_tkrs.append(tkr)
            
    if not dhan and dhan_tasks:
        yf_tkrs.extend(list(dhan_tasks.keys()))
        dhan_tasks = {}
        
    if dhan and dhan_tasks:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(fetch_single_dhan_5m, tkr, data[1]): tkr for tkr, data in dhan_tasks.items()}
            for future in concurrent.futures.as_completed(futures):
                tkr, df = future.result()
                if not df.empty: results_dict[tkr] = df
                else: yf_tkrs.append(tkr)

    if yf_tkrs:
        yf_data = yf.download(yf_tkrs, period="5d", interval="5m", progress=False, group_by='ticker', threads=10)
        if not yf_data.empty:
            if len(yf_tkrs) == 1:
                if yf_data.index.tz is not None:
                    yf_data.index = yf_data.index.tz_localize(None)
                results_dict[yf_tkrs[0]] = yf_data
            else:
                if isinstance(yf_data.columns, pd.MultiIndex):
                    for tkr in yf_tkrs:
                        if tkr in yf_data.columns.levels[0]:
                            df = yf_data[tkr].dropna(subset=['Close'])
                            if not df.empty:
                                if df.index.tz is not None:
                                    df.index = df.index.tz_localize(None)
                                results_dict[tkr] = df
                        
    valid_results = {k: v for k, v in results_dict.items() if not v.empty and len(v) > 0}
    if valid_results:
        return pd.concat(valid_results.values(), axis=1, keys=valid_results.keys(), sort=False)
    return pd.DataFrame()

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

# --- DAILY DATA FETCH ---
@st.cache_data(ttl=180, show_spinner=False)
def fetch_all_data():
    port_df = load_portfolio()
    port_stocks = [str(sym).upper().strip() for sym in port_df['Symbol'].tolist() if str(sym).strip() != ""]
    base_stocks = NIFTY_50.copy() + FNO_STOCKS + MIDCAP_150 + SMALLCAP_250
    all_stocks = set(base_stocks + port_stocks)
    tkrs = list(INDICES_MAP.keys()) + list(SECTOR_INDICES_MAP.keys()) + list(COMMODITY_MAP.keys()) + [f"{t}.NS" for t in all_stocks if t]
    
    chunk_size = 200
    data_frames = []
    for i in range(0, len(tkrs), chunk_size):
        chunk = tkrs[i : i + chunk_size]
        temp_data = yf.download(chunk, period="15mo", progress=False, group_by='ticker', threads=5)
        if not temp_data.empty:
            if len(chunk) == 1:
                temp_data.columns = pd.MultiIndex.from_product([chunk, temp_data.columns])
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
            
            df.ta.atr(length=14, append=True)
            atr = float(df['ATRr_14'].iloc[-1]) if 'ATRr_14' in df.columns else 0.0

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

            df.ta.ema(length=50, append=True)
            df.ta.sma(length=20, append=True)
            df.ta.sma(length=50, append=True)
            df.ta.sma(length=150, append=True)
            df.ta.sma(length=200, append=True)
    
            ema50_d = float(df['EMA_50'].iloc[-1]) if ('EMA_50' in df.columns and len(df) >= 50) else 0.0
            sma20_d = float(df['SMA_20'].iloc[-1]) if ('SMA_20' in df.columns and len(df) >= 20) else 0.0
            sma50_d = float(df['SMA_50'].iloc[-1]) if ('SMA_50' in df.columns and len(df) >= 50) else 0.0
            sma150_d = float(df['SMA_150'].iloc[-1]) if ('SMA_150' in df.columns and len(df) >= 150) else 0.0
            sma200_d = float(df['SMA_200'].iloc[-1]) if ('SMA_200' in df.columns and len(df) >= 200) else 0.0
            sma200_20d = float(df['SMA_200'].iloc[-21]) if ('SMA_200' in df.columns and len(df) >= 220) else 0.0
            sma150_20d = float(df['SMA_150'].iloc[-21]) if ('SMA_150' in df.columns and len(df) >= 170) else 0.0
            high_52w = float(df['High'].rolling(window=252).max().iloc[-1]) if len(df) >= 252 else float(df['High'].max())
            low_52w = float(df['Low'].rolling(window=252).min().iloc[-1]) if len(df) >= 252 else float(df['Low'].min())
            sma200_20d = float(df['Close'].rolling(window=200).mean().iloc[-21]) if len(df) >= 220 else 0.0
            sma150_20d = float(df['Close'].rolling(window=150).mean().iloc[-21]) if len(df) >= 170 else 0.0
            
            if len(df) >= 25:
                box_top_20 = float(df['High'].iloc[-13:-1].max())
                box_bot_20 = float(df['Low'].iloc[-13:-1].min())
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
                    vol_avg_5 = float(df['Volume'].iloc[-5:].mean())
                    vol_avg_50 = float(df['Volume'].iloc[-50:].mean())
                    if vol_avg_5 <= (vol_avg_50 * 1.05):
                        vcp_vol_dry = True
            
            is_swing = False; is_w_pullback = False
            latest_w_ema10 = 0; latest_w_ema50 = 0
            
            df_w = df.resample('W').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()
            weekly_net_chg = net_chg
            if len(df_w) >= 2: 
                prev_w_c = float(df_w['Close'].iloc[-2])
                if prev_w_c > 0: weekly_net_chg = ((ltp - prev_w_c) / prev_w_c) * 100
                    
            if len(df_w) >= 40: 
                df_w.ta.ema(length=10, append=True)
                df_w.ta.ema(length=50, append=True)
                latest_w_ema10 = float(df_w['EMA_10'].iloc[-1]) if 'EMA_10' in df_w.columns else 0.0
                latest_w_ema50 = float(df_w['EMA_50'].iloc[-1]) if 'EMA_50' in df_w.columns else 0.0
                
                df_w['Trend_Up'] = np.where(df_w['EMA_10'] > df_w['EMA_50'], 1, 0) if ('EMA_10' in df_w.columns and 'EMA_50' in df_w.columns) else 0
                continuous_4w = df_w['Trend_Up'].rolling(window=4).min().iloc[-1] == 1 if len(df_w) >= 4 else False
                
                df_w.ta.adx(length=14, append=True)
                w_adx = float(df_w['ADX_14'].iloc[-1]) if 'ADX_14' in df_w.columns else 0.0
                recent_w_low = df_w['Low'].iloc[-2:].min()
                touch_ema = recent_w_low <= (latest_w_ema10 * 1.002) 
                bounce = ltp > latest_w_ema10 
                catch_early = ltp <= (latest_w_ema10 * 1.02)
                if continuous_4w and touch_ema and bounce and catch_early and (w_adx >= 15):
                    is_w_pullback = True

            if len(df) >= 100:
                ema20_w = latest_w_ema10 if latest_w_ema10 > 0 else 0
                df.ta.rsi(length=14, append=True)
                current_rsi = float(df['RSI_14'].iloc[-1]) if 'RSI_14' in df.columns else 100.0
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
                "Prev_H": prev_h, "Prev_L": prev_l, "W_EMA10": latest_w_ema10, "W_EMA50": latest_w_ema50, "D_EMA50": ema50_d,
                "SMA20": sma20_d, "SMA50": sma50_d, "SMA150": sma150_d, "SMA200": sma200_d, "High52W": high_52w, "Low52W": low_52w, "SMA200_20D": sma200_20d,
                "Day_C": day_chg, "C": net_chg, "W_C": float(weekly_net_chg), "S": score, "VolX": vol_x, "Is_Swing": is_swing,
                "Is_W_Pullback": is_w_pullback, "VWAP": vwap,
                "ATR": atr, "Narrow_CPR": is_narrow_cpr,
                "Bull_P": bull_power, "Bear_P": bear_power,
                "Is_Index": is_index, "Is_Sector": is_sector, "Sector": stock_sector, "Is_Commodity": is_commodity,
                "SMA150_20D": sma150_20d, "Box_Top20": box_top_20, "Box_Bot20": box_bot_20,
                "Pullback_52W": pullback_52w_pct
            })
        except: continue
    return pd.DataFrame(results)

def process_5m_data(df_raw):
    try:
        df_s = df_raw.dropna(subset=['Open', 'High', 'Low', 'Close']).copy()
        if df_s.empty: return pd.DataFrame()
        df_s = df_s.sort_index()
        
        df_s.ta.ema(length=10, append=True)
        df_s.ta.ema(length=20, append=True)
        df_s.ta.ema(length=50, append=True)

        if 'Volume' in df_s.columns:
            df_s['Vol_SMA_375'] = df_s['Volume'].rolling(window=375, min_periods=1).mean()
        else:
            df_s['Vol_SMA_375'] = 0
            
        df_s.ta.atr(length=13, append=True)
        if 'ATRr_13' in df_s.columns:
            df_s.rename(columns={'ATRr_13': 'ATR_13'}, inplace=True)

        # (VWAP ప్లేస్ లో ఇది పెట్టండి)
            if 'Volume' in df_day.columns and df_day['Volume'].sum() > 0:
                df_day.ta.vwap(append=True)
                if 'VWAP_D' in df_day.columns:
                    df_day.rename(columns={'VWAP_D': 'VWAP'}, inplace=True)
            else: 
                df_day['VWAP'] = df_day['Typical_Price'].expanding().mean()
            df_day = df_day.bfill().ffill()
            return df_day
        return pd.DataFrame()
    except: return pd.DataFrame()

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
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
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

def render_html_table(df_subset, title, color_class):
    if df_subset.empty: return ""
    html = f'<table class="term-table"><thead><tr><th colspan="7" class="{color_class}">{title}</th></tr><tr style="background-color: #21262d;"><th style="text-align:left; width:20%;">STOCK</th><th style="width:12%;">PRICE</th><th style="width:12%;">DAY%</th><th style="width:12%;">NET%</th><th style="width:10%;">VOL</th><th style="width:26%;">STATUS</th><th style="width:8%;">SCORE</th></tr></thead><tbody>'
    for i, (_, row) in enumerate(df_subset.iterrows()):
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        day_color = "text-green" if row['Day_C'] >= 0 else "text-red"
        net_color = "text-green" if row['C'] >= 0 else "text-red"
        status = generate_status(row)
        html += f'<tr class="{bg_class}"><td class="t-symbol {net_color}"><a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank">{row["T"]}</a></td><td>{row["P"]:.2f}</td><td class="{day_color}">{row["Day_C"]:.2f}%</td><td class="{net_color}">{row["C"]:.2f}%</td><td>{row["VolX"]:.1f}x</td><td style="font-size:10px;">{status}</td><td style="color:#ffd700;">{int(row["S"])}</td></tr>'
    html += "</tbody></table>"
    return html

def render_portfolio_table(df_port, df_stocks, weekly_trends, port_sort="Default"):
    if df_port.empty: return "<div style='padding:20px; text-align:center; color:#8b949e; border: 1px dashed #30363d; border-radius:8px;'>Portfolio is empty. Add a stock using the option below!</div>"
    
    stock_lookup = df_stocks.drop_duplicates(subset=['T'], keep='first').set_index('T').to_dict('index')
    
    rows_data = []
    total_invested, total_current, total_day_pnl = 0, 0, 0
    
    for i, (_, row) in enumerate(df_port.iterrows()):
        sym = str(row['Symbol']).upper().strip()
        try: qty = float(row['Quantity'])
        except: qty = 0
        try: buy_p = float(row['Buy_Price'])
        except: buy_p = 0
        
        date_val = str(row.get('Date', '-'))
        if date_val in ['nan', 'NaN', '']: date_val = '-'
        
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
            'sym': sym, 'date': date_val, 'qty': qty, 'buy_p': buy_p,
            'ltp': ltp, 'trend_html': trend_html, 'invested': invested,
            'overall_pnl': overall_pnl, 'pnl_pct': pnl_pct, 'day_pnl': day_pnl
        })
        
    if port_sort == "Day P&L ⬆️": rows_data.sort(key=lambda x: x['day_pnl'], reverse=True)
    elif port_sort == "Day P&L ⬇️": rows_data.sort(key=lambda x: x['day_pnl'], reverse=False)
    elif port_sort == "Total P&L ⬆️": rows_data.sort(key=lambda x: x['overall_pnl'], reverse=True)
    elif port_sort == "Total P&L ⬇️": rows_data.sort(key=lambda x: x['overall_pnl'], reverse=False)
    elif port_sort == "P&L % ⬆️": rows_data.sort(key=lambda x: x['pnl_pct'], reverse=True)
    elif port_sort == "P&L % ⬇️": rows_data.sort(key=lambda x: x['pnl_pct'], reverse=False)

    html = f'<table class="term-table"><thead><tr><th colspan="10" class="term-head-port">💼 LIVE PORTFOLIO TERMINAL</th></tr><tr style="background-color: #21262d;"><th style="text-align:left; width:12%;">STOCK</th><th style="width:10%;">DATE</th><th style="width:6%;">QTY</th><th style="width:9%;">AVG</th><th style="width:9%;">LTP</th><th style="width:11%;">WK TREND</th><th style="width:13%;">INVESTED (₹)</th><th style="width:10%;">DAY P&L</th><th style="width:10%;">TOT P&L</th><th style="width:10%;">P&L %</th></tr></thead><tbody>'
    
    for i, rd in enumerate(rows_data):
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        tpnl_color = "text-green" if rd['overall_pnl'] >= 0 else "text-red"
        dpnl_color = "text-green" if rd['day_pnl'] >= 0 else "text-red"
        t_sign = "+" if rd['overall_pnl'] > 0 else ""
        d_sign = "+" if rd['day_pnl'] > 0 else ""
        html += f'<tr class="{bg_class}"><td class="t-symbol {tpnl_color}"><a href="https://in.tradingview.com/chart/?symbol=NSE:{rd["sym"]}" target="_blank">{rd["sym"]}</a></td><td>{rd["date"]}</td><td>{int(rd["qty"])}</td><td>{rd["buy_p"]:.2f}</td><td>{rd["ltp"]:.2f}</td><td style="font-size:10px;">{rd["trend_html"]}</td><td>{rd["invested"]:,.0f}</td><td class="{dpnl_color}">{d_sign}{rd["day_pnl"]:,.0f}</td><td class="{tpnl_color}">{t_sign}{rd["overall_pnl"]:,.0f}</td><td class="{tpnl_color}">{t_sign}{rd["pnl_pct"]:.2f}%</td></tr>'
    
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

    html += f'<tr class="port-total"><td colspan="7" style="text-align:right; padding-right:15px; font-size:12px;">TOTAL INVESTED: ₹{total_invested:,.0f} &nbsp;|&nbsp; CURRENT: ₹{total_current:,.0f} &nbsp;|&nbsp; ACTUAL P&L: <span class="{ap_color}">{ap_sign}₹{actual_pnl_value:,.0f}</span> &nbsp;|&nbsp; OVERALL P&L:</td><td class="{d_color}">{d_sign}₹{total_day_pnl:,.0f}</td><td class="{o_color}">{o_sign}₹{overall_total_pnl:,.0f}</td><td class="{o_color}">{o_sign}{overall_total_pct:.2f}%</td></tr>'
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
            st.rerun()
    
    strat_tag = f" <span style='font-size:10px; background:rgba(0,191,255,0.2); border:1px solid #00BFFF; padding:1px 4px; border-radius:3px; color:#00BFFF;'>{row.get('Strategy_Icon', '')}</span>" if row.get('Strategy_Icon') and row.get('Strategy_Icon') != "Neutral" else ""
    
    # 🔥 Dynamic pullback logic (>= 0.1% condition tho)
    if timeframe == "Intraday (5m)":
        day_high = float(row.get('H', 0))
        day_low = float(row.get('L', 0))
        ltp_now = float(row.get('P', 0))
        
        if pct_val >= 0:
            intraday_pb = ((day_high - ltp_now) / day_high) * 100 if day_high > 0 else 0
            # "from Day High" ni "DH" ga marchanu
            pb_tag = f" &nbsp;<span style='color:#FF8C00; font-size:11px;'>📉 -{intraday_pb:.1f}% DH</span>" if intraday_pb >= 0.1 else ""
        else:
            intraday_bounce = ((ltp_now - day_low) / day_low) * 100 if day_low > 0 else 0
            # "from Day Low" ni "DL" ga marchanu
            pb_tag = f" &nbsp;<span style='color:#00BFFF; font-size:11px;'>📈 +{intraday_bounce:.1f}% DL</span>" if intraday_bounce >= 0.1 else ""
    else:
        strat_icon = str(row.get('Strategy_Icon', ''))
        
        # SELL / Weak stocks ki 52-Week Low (52WL) nundi distance live ga calculate cheyadam
        if "🔴" in strat_icon or "SELL" in strat_icon or "Stage 4" in strat_icon or "Breakdown" in strat_icon or "Holy Grail" in strat_icon:
            low_52w = float(row.get('Low52W', 0))
            ltp_now = float(row.get('P', 0))
            dist_52wl = ((ltp_now - low_52w) / low_52w) * 100 if low_52w > 0 else 0
            pb_tag = f" &nbsp;<span style='color:#f85149; font-size:11px;'>🩸 +{dist_52wl:.1f}% 52WL</span>" if dist_52wl >= 0.1 else ""
        else:
            # BUY stocks ki 52-Week High (52WH) nundi distance
            pb_val = float(row.get('Pullback_52W', 0))
            pb_tag = f" &nbsp;<span style='color:#FF8C00; font-size:11px;'>📉 -{pb_val:.1f}% 52WH</span>" if pb_val >= 0.1 else ""
    
    title_html = f"<a href='{tv_link}' target='_blank' style='color:#ffffff; text-decoration:none; line-height:1.2;'><b>{display_sym}</b>{strat_tag}<br><span style='font-size:12px; color:#cccccc;'>₹{row['P']:.2f} &nbsp;<span style='color:{color_hex};'>({sign}{pct_val:.2f}%)</span>{pb_tag}</span></a>"
    
    try:
        if not df_chart.empty and 'Low' in df_chart.columns and 'High' in df_chart.columns:
            min_val = df_chart['Low'].min()
            max_val = df_chart['High'].max()
            y_padding = (max_val - min_val) * 0.15 if (max_val - min_val) != 0 else min_val * 0.005 
            
            # 🔥 PERFECT TIMEZONE FIX 🔥
            df_chart = df_chart.copy()
            if df_chart.index.tz is not None:
                df_chart.index = df_chart.index.tz_convert('Asia/Kolkata').tz_localize(None)
                
            if len(df_chart) > 0:
                first_hour = df_chart.index[0].hour
                # రోజులో ఫస్ట్ క్యాండిల్ 9 AM కి బదులుగా 2 PM (14) పైన వస్తే, దానికి +5:30 యాడ్ అయిందని అర్థం
                if first_hour >= 14:
                    df_chart.index = df_chart.index - pd.Timedelta(hours=5, minutes=30)
                # ఒకవేళ తెల్లవారుజామున 3 లేదా 4 వస్తే, దానికి -5:30 మైనస్ అయిందని అర్థం
                elif first_hour <= 4:
                    df_chart.index = df_chart.index + pd.Timedelta(hours=5, minutes=30)

            chart_times = pd.to_datetime(df_chart.index)
            
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
                    x=df_chart.index, open=am('Open', mask_norm), high=am('High', mask_norm), low=am('Low', mask_norm), close=am('Close', mask_norm), 
                    increasing_line_color='#2ea043', increasing_fillcolor='#2ea043', increasing_line_width=1,
                    decreasing_line_color='#da3633', decreasing_fillcolor='#da3633', decreasing_line_width=1,
                    showlegend=False, hoverinfo='skip'
                ), **rc)
                
                if mask_hv_bull.any():
                    fig_obj.add_trace(go.Candlestick(
                        x=df_chart.index, open=am('Open', mask_hv_bull), high=am('High', mask_hv_bull), low=am('Low', mask_hv_bull), close=am('Close', mask_hv_bull), 
                        increasing_line_color='#00FF00', increasing_fillcolor='#00FF00', increasing_line_width=2,
                        decreasing_line_color='#00FF00', decreasing_fillcolor='#00FF00', decreasing_line_width=2,
                        showlegend=False, hoverinfo='skip'
                    ), **rc)
                    
                if mask_hv_bear.any():
                    fig_obj.add_trace(go.Candlestick(
                        x=df_chart.index, open=am('Open', mask_hv_bear), high=am('High', mask_hv_bear), low=am('Low', mask_hv_bear), close=am('Close', mask_hv_bear), 
                        increasing_line_color='#FF0000', increasing_fillcolor='#FF0000', increasing_line_width=2,
                        decreasing_line_color='#FF0000', decreasing_fillcolor='#FF0000', decreasing_line_width=2,
                        showlegend=False, hoverinfo='skip'
                    ), **rc)

            if show_vol:
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.02, row_heights=[0.75, 0.25])
                apply_standard_candles(fig, is_subplot=True)
                fig.add_trace(go.Scatter(
                    x=df_chart.index, y=df_chart['High'], mode='lines', 
                    line=dict(color='rgba(0,0,0,0)'), showlegend=False, 
                    hoverinfo='text' if show_crosshair else 'skip', 
                    text=hover_data, name="", **hover_kwargs
                ), row=1, col=1)
                
                if timeframe == "Daily Chart":
                    if 'SMA_50' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_50'], mode='lines', line=dict(color='#FFD700', width=1.5), name='50 SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
                    if 'SMA_150' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_150'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), name='150 SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
                    if 'SMA_200' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_200'], mode='lines', line=dict(color='#FF4500', width=2), name='200 SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
                elif timeframe == "Weekly Chart":
                    if 'SMA_10' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_10'], mode='lines', line=dict(color='#FFD700', width=1.5), name='10 Wk SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
                    if 'SMA_40' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_40'], mode='lines', line=dict(color='#FF4500', width=2), name='40 Wk SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
                else:
                    offset = -4 if len(df_chart) >= 4 else -1
                    tag_idx = df_chart.index[offset]
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
                        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['VWAP'], mode='lines', line=dict(color='#FFD700', width=1.5, dash='dot'), showlegend=False, hoverinfo='skip'), row=1, col=1)
                        fig.add_annotation(x=tag_idx, y=tag_y_vwap, text=f"V:{last_vwap:.1f}", showarrow=False, xanchor="right", yanchor=v_anchor, xshift=-5, yshift=v_shift, font=dict(color="#161b22", size=10, family="monospace", weight="bold"), bgcolor="#FFD700", borderpad=2, row=1, col=1)
                        
                    if has_ema: 
                        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA_10'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), showlegend=False, hoverinfo='skip'), row=1, col=1)
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
                
                fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Volume'], marker_color=vol_colors, showlegend=False, hoverinfo='skip'), row=2, col=1)
                
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
                    x=df_chart.index, y=df_chart['High'], mode='lines', 
                    line=dict(color='rgba(0,0,0,0)'), showlegend=False, 
                    hoverinfo='text' if show_crosshair else 'skip', 
                    text=hover_data, name="", **hover_kwargs
                ))
                
                if timeframe == "Daily Chart":
                    if 'SMA_50' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_50'], mode='lines', line=dict(color='#FFD700', width=1.5), name='50 SMA', showlegend=False, hoverinfo='skip'))
                    if 'SMA_150' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_150'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), name='150 SMA', showlegend=False, hoverinfo='skip'))
                    if 'SMA_200' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_200'], mode='lines', line=dict(color='#FF4500', width=2), name='200 SMA', showlegend=False, hoverinfo='skip'))
                elif timeframe == "Weekly Chart":
                    if 'SMA_10' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_10'], mode='lines', line=dict(color='#FFD700', width=1.5), name='10 Wk SMA', showlegend=False, hoverinfo='skip'))
                    if 'SMA_40' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_40'], mode='lines', line=dict(color='#FF4500', width=2), name='40 Wk SMA', showlegend=False, hoverinfo='skip'))
                else:
                    offset = -4 if len(df_chart) >= 4 else -1
                    tag_idx = df_chart.index[offset]
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
                        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['VWAP'], mode='lines', line=dict(color='#FFD700', width=1.5, dash='dot'), showlegend=False, hoverinfo='skip'))
                        fig.add_annotation(x=tag_idx, y=tag_y_vwap, text=f"V:{last_vwap:.1f}", showarrow=False, xanchor="right", yanchor=v_anchor, xshift=-5, yshift=v_shift, font=dict(color="#161b22", size=10, family="monospace", weight="bold"), bgcolor="#FFD700", borderpad=2)
                        
                    if has_ema: 
                        fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA_10'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), showlegend=False, hoverinfo='skip'))
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
                        st.rerun()

def render_closed_trades_table(df_closed):
    if df_closed.empty: return "<div style='padding:20px; text-align:center; color:#8b949e; border:1px dashed #30363d; border-radius:8px;'>No closed trades yet. Sell a stock to book P&L!</div>"
    
    html = f'<table class="term-table"><thead><tr><th colspan="7" style="background-color:#4a148c; color:white; text-align:left; padding-left:10px;">📜 CLOSED TRADES (TRADE BOOK & P&L)</th></tr><tr style="background-color: #21262d;"><th style="width:15%; text-align:left;">SELL DATE</th><th style="width:15%; text-align:left;">STOCK</th><th style="width:10%;">QTY</th><th style="width:15%;">BUY AVG</th><th style="width:15%;">SELL AVG</th><th style="width:15%;">REALIZED P&L (₹)</th><th style="width:15%;">P&L %</th></tr></thead><tbody>'
    
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
        
        sell_date_val = str(row.get("Sell_Date", ""))
        
        html += f'<tr class="{bg_class}"><td style="text-align:left;">{sell_date_val}</td><td class="t-symbol {p_color}" style="text-align:left;"><a href="https://in.tradingview.com/chart/?symbol=NSE:{sym}" target="_blank">{sym}</a></td><td>{qty}</td><td>{buy_p:.2f}</td><td>{sell_p:.2f}</td><td class="{p_color}">{p_sign}{pnl_rs:,.2f}</td><td class="{p_color}">{p_sign}{pnl_pct:.2f}%</td></tr>'
        
    tot_color = "text-green" if total_realized_pnl >= 0 else "text-red"
    tot_sign = "+" if total_realized_pnl > 0 else ""
    html += f'<tr class="port-total"><td colspan="5" style="text-align:right; padding-right:15px; font-size:13px;">NET REALIZED P&L:</td><td colspan="2" class="{tot_color}" style="font-size:14px; text-align:center;">{tot_sign}₹{total_realized_pnl:,.2f}</td></tr>'
    html += "</tbody></table>"
    return html

# --- 6. FETCH DATA ---
st.markdown("<hr style='margin:10px 0; border-color:#30363d;'>", unsafe_allow_html=True)

df_cached = fetch_all_data()

all_names = []
if not df_cached.empty:
    all_names = sorted(df_cached[(~df_cached['Is_Sector']) & (~df_cached['Is_Index']) & (~df_cached['Is_Commodity'])]['T'].unique().tolist())
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
# --- 7. UI SETTINGS ---
# =========================================================

watchlist_mode = st.selectbox("Watchlist", [
    "🤖 AI Predictions (F&O)", 
    "🤖 AI Predictions (Mid Cap)", 
    "🤖 AI Predictions (Small Cap)", 
    "High Score Stocks 🔥",
    "Swing Trading 📈", 
    "Legendary Strategy 🏆", 
    "Nifty 50 Heatmap", 
    "Terminal Tables 🗃️",
    "My Portfolio 💼", 
    "Commodity 🛢️", 
    "Fundamentals 🏢", 
    "Mutual Funds 📈", 
    "Month Effect Advantage 📅"
], index=0, label_visibility="collapsed")

# Kotha refresh time (seconds lo)
refresh_sec = 15 if watchlist_mode in ["Swing Trading 📈", "Legendary Strategy 🏆"] else 5

view_mode = st.radio("Display", ["Heat Map", "Chart 📈"], index=1 if watchlist_mode in ["Swing Trading 📈", "Legendary Strategy 🏆"] else 0, horizontal=True, label_visibility="collapsed")
move_type_filter = ["🌊 One Sided Only", "🎯 Reversals Only", "🏹 Rubber Band Stretch"] 
fund_filter = "Top Ranked Stocks ⭐"
sort_mode = "Custom Sort"
chart_timeframe = "Intraday (5m)"
show_crosshair = False
show_vol = False
search_stock = "-- None --"

with st.expander("⚙️ Filters, Sorting, Search & Alerts", expanded=False):
    sc1, sc2, sc3, sc4 = st.columns([3, 2, 2, 1.5])
    with sc4: st.session_state.pause_refresh = st.toggle("⏸️ Pause Data", value=st.session_state.pause_refresh)

    with sc1:
        if "AI Predictions" in watchlist_mode:
                move_type_filter = st.multiselect("Strategy Filter",
                    [
                        "All Moves", 
                        "All Day Trading Moves 🚀", 
                        "🔥 First Hour Vol Breakout (ORB+VWAP)", 
                        "💥 Inside Bar Vol Breakout (NR7)", 
                        "🧲 Intraday Dip & Support Bounce", 
                        "⚡ Sudden VWAP Cross (Any Time)", 
                        "🚀 Gap & Go (Open = Low)", 
                        "💥 PDH / PDL Breakout", 
                        "🧲 VWAP Bounce (Low Risk Entry)", 
                        "🎯 Narrow CPR Trending Day",
                        "🔥 Live Power Mover (Last 2 Candles)", 
                        "🚀 All-Day Volume Spikes (Max Fire)", 
                        "⚡ Intraday Pro Breakout (Top 5)", 
                        "🌊 One Sided Only", 
                        "🔄 VWAP Reversal", 
                        "🎯 Reversals Only", 
                        "🏹 Rubber Band Stretch", 
                        "🏄‍♂️ Momentum Ignition", 
                        "💥 Narrow CPR Breakout", 
                        "🧲 10-EMA Retest (Best Entry)", 
                        "📉 FIB Retracement (0.382)", 
                        "🌅 15-Min ORB (Opening Range Breakout)"
                    ], 
                    default=["All Moves"],
                    key="day_trading_filter_key"
                )
        elif watchlist_mode == "Swing Trading 📈":
            move_type_filter = st.multiselect("Strategy Filter", 
                ["All Swing Stocks", "📈 Minervini Trend Template (VCP)", "📉 Strict VCP (Price & Vol Contraction)", "🔥 Minervini MidCap 150", "🚀 Minervini SmallCap 250"], 
                default=["📈 Minervini Trend Template (VCP)"], 
                key="swing_trading_filter_key" 
            )
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
            move_type_filter = [st.selectbox("Select Strategy", strat_opts, key="legendary_filter_key")]
            
        elif watchlist_mode == "Fundamentals 🏢":
            fund_filter = st.selectbox("Fundamentals Filter", ["Top Ranked Stocks ⭐", "🦅 Warren Buffett Value Stocks", "Swing Trading Candidates 📈", "Nifty 50 Stocks", "My Portfolio 💼"], index=0)
            
    with sc2:
        sort_mode = st.selectbox(
            "Sort By", 
            [
                "Score Wise Up ⭐", 
                "Intraday Pullback Max 📉 (DH / DL)",  # 👈 ఈ కొత్త ఆప్షన్ యాడ్ చేయండి
                "52W Pullback Max 📉 (Deep Discount)", 
                "Custom Sort", 
                "Sector Trending First 📊", 
                "Score Wise Down ⬇️", 
                "🤖 AI Prob Up ⬆️", 
                "% Change Up 🟢", 
                "% Change Down 🔴"
            ], 
            index=0
        )
        
    with sc3:
        search_stock = st.selectbox("Search Stock", ["-- None --"] + all_names)

    if view_mode == "Chart 📈" or watchlist_mode in ["Swing Trading 📈", "Legendary Strategy 🏆", "My Portfolio 💼", "Commodity 🛢️"]:
        st.markdown("<hr style='margin:10px 0; border-color:#30363d;'>", unsafe_allow_html=True)
        cc1, cc2, cc3 = st.columns(3)
        with cc1:
            chart_timeframe = st.radio("Timeframe", ["Intraday (5m)", "Daily Chart", "Weekly Chart"], index=1 if watchlist_mode in ["Swing Trading 📈", "Legendary Strategy 🏆"] else 0, horizontal=True)
        with cc2: show_crosshair = st.toggle("⌖ Show Crosshair", value=False)
        with cc3: show_vol = st.toggle("📊 Show Vol Bars", value=False)

    if not df.empty and (view_mode == "Chart 📈" or watchlist_mode == "Commodity 🛢️"):
        st.markdown("<hr style='margin:10px 0; border-color:#30363d;'>", unsafe_allow_html=True)
        st.markdown("<div style='color:#ffd700; font-size:14px; margin-bottom:5px;'>🔔 Add Custom Price Alert Line</div>", unsafe_allow_html=True)
        ac1, ac2, ac3, ac4, ac5 = st.columns([2, 2, 2, 1, 1])
        with ac1: alert_sym_disp = st.selectbox("Select Stock", ["-- None --"] + all_names + list(COMMODITY_MAP.values()), key="alert_sym_sel", label_visibility="collapsed")
        with ac2: alert_price = st.number_input("Alert Price (₹ / $)", min_value=0.0, value=0.0, step=0.5, label_visibility="collapsed")
        with ac3: alert_cond = st.selectbox("Condition", ["Price Above Line 📈", "Price Below Line 📉"], label_visibility="collapsed")
        with ac4: alert_enable = st.toggle("Enable", value=True, key="alert_en_tog")
        with ac5:
            if st.button("➕ Add", width="stretch"):
                if alert_sym_disp != "-- None --" and alert_price > 0:
                    f_sym = df[df['T'] == alert_sym_disp]['Fetch_T'].iloc[0]
                    st.session_state.custom_alerts[f_sym] = {'price': alert_price, 'type': alert_cond, 'enabled': alert_enable, 'name': alert_sym_disp}
                    st.rerun()

        if st.session_state.custom_alerts:
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

# =========================================================
# --- 8. RENDERING ---
# =========================================================

@st.fragment(run_every=f"{refresh_sec}s")
def render_live_ui(df_live):
    df = df_live.copy() if not df_live.empty else df_live
    
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

        if not df.empty:
            df_indices = df[df['Is_Index']].copy()
        df_indices['Order'] = df_indices['T'].map({"NIFTY": 1, "BANKNIFTY": 2, "INDIA VIX": 3, "SPX": 4, "DAX": 5, "USD/INR": 6}).fillna(99)
        df_indices = df_indices.sort_values('Order')
        
        df_sectors = df[df['Is_Sector']].copy()
        sec_sort_key = "W_C" if chart_timeframe == "Weekly Chart" else "Day_C"
        df_sectors = df_sectors.sort_values(by=sec_sort_key, ascending=False)
        
        df_all_stocks = df[(~df['Is_Index']) & (~df['Is_Sector']) & (~df['Is_Commodity'])].copy()
        df_commodities = df[df['Is_Commodity']].copy()
        df_port_saved = load_portfolio().copy()
    
        if watchlist_mode == "Swing Trading 📈":
            strict_allowed = set(NIFTY_50 + FNO_STOCKS + MIDCAP_150 + SMALLCAP_250)
        elif watchlist_mode == "🤖 AI Predictions (F&O)":
            strict_allowed = set(NIFTY_50 + FNO_STOCKS)
        elif watchlist_mode == "🤖 AI Predictions (Mid Cap)":
            strict_allowed = set(MIDCAP_150)
        elif watchlist_mode == "🤖 AI Predictions (Small Cap)":
            strict_allowed = set(SMALLCAP_250)
        else:
            strict_allowed = set(NIFTY_50 + FNO_STOCKS)
            
        df_stocks = df_all_stocks[df_all_stocks['T'].isin(strict_allowed)].copy()
        
        df_nifty = df_all_stocks[df_all_stocks['T'].isin(NIFTY_50)].copy()
        sector_perf = df_nifty.groupby('Sector')['C'].mean().sort_values(ascending=False)
        valid_sectors = [s for s in sector_perf.index if s != "OTHER"]
        
        if valid_sectors: top_buy_sector, top_sell_sector = valid_sectors[0], valid_sectors[-1]
        else: top_buy_sector, top_sell_sector = "PHARMA", "IT"
            
        df_buy_sector = df_nifty[df_nifty['Sector'] == top_buy_sector].sort_values(by=['S', 'C'], ascending=[False, False])
        df_sell_sector = df_nifty[df_nifty['Sector'] == top_sell_sector].sort_values(by=['S', 'C'], ascending=[False, True])
        df_independent = df_nifty[(~df_nifty['Sector'].isin([top_buy_sector, top_sell_sector])) & (df_nifty['S'] >= 5)].sort_values(by='S', ascending=False).head(8)
        df_broader = df_all_stocks[(df_all_stocks['T'].isin(FNO_STOCKS)) & (~df_all_stocks['T'].isin(NIFTY_50)) & (df_all_stocks['S'] >= 5)].sort_values(by='S', ascending=False).head(8)
    
        df_filtered = pd.DataFrame(columns=df_stocks.columns)
    
        if watchlist_mode == "Terminal Tables 🗃️":
            terminal_tickers = pd.concat([df_buy_sector, df_sell_sector, df_independent, df_broader])['Fetch_T'].unique().tolist()
            df_filtered = df_all_stocks[df_all_stocks['Fetch_T'].isin(terminal_tickers)]
        elif watchlist_mode == "My Portfolio 💼":
            port_tickers = [f"{str(sym).upper().strip()}.NS" for sym in df_port_saved['Symbol'].tolist() if str(sym).strip() != ""]
            df_filtered = df_all_stocks[df_all_stocks['Fetch_T'].isin(port_tickers)]
        elif watchlist_mode == "Commodity 🛢️":
            df_filtered = df_commodities.copy()
        elif watchlist_mode == "Fundamentals 🏢":
            if fund_filter == "Swing Trading Candidates 📈": df_filtered = df_stocks[(df_stocks['Is_Swing'] == True) | (df_stocks['Is_W_Pullback'] == True)]
            elif fund_filter == "Nifty 50 Stocks": df_filtered = df_all_stocks[df_all_stocks['T'].isin(NIFTY_50)]
            elif fund_filter == "My Portfolio 💼":
                port_tickers = [f"{str(sym).upper().strip()}.NS" for sym in df_port_saved['Symbol'].tolist() if str(sym).strip() != ""]
                df_filtered = df_all_stocks[df_all_stocks['Fetch_T'].isin(port_tickers)]
            else: df_filtered = df_stocks[df_stocks['S'] >= 6]
        elif watchlist_mode == "Nifty 50 Heatmap":
            df_filtered = df_all_stocks[df_all_stocks['T'].isin(NIFTY_50)]
        elif "AI Predictions" in watchlist_mode:
            df_filtered = df_stocks.copy()
            ai_predictions, ai_probs = [], []
            for _, row in df_filtered.iterrows():
                up_prob, dn_prob = 0, 0
                if row['P'] > row['VWAP']: up_prob += 25 
                if row['VolX'] >= 1.5: up_prob += 20 
                if row.get('Bull_P', 0) >= 80: up_prob += 30 
                if abs(row['O'] - row['L']) < (row['P'] * 0.002): up_prob += 25 
                if row['P'] < row['VWAP']: dn_prob += 25
                if row['VolX'] >= 1.5: dn_prob += 20
                if row.get('Bear_P', 0) >= 80: dn_prob += 30
                if abs(row['O'] - row['H']) < (row['P'] * 0.002): dn_prob += 25
                
                if up_prob >= 70: ai_predictions.append("🚀 AI PREDICTS: UP"); ai_probs.append(up_prob)
                elif dn_prob >= 70: ai_predictions.append("🩸 AI PREDICTS: DOWN"); ai_probs.append(dn_prob)
                else: ai_predictions.append("Neutral"); ai_probs.append(0)
                    
            df_filtered['Strategy_Icon'] = ai_predictions
            df_filtered['AI_Prob'] = ai_probs
            # స్ట్రాటజీ సెలెక్ట్ చేసినప్పుడు అన్ని స్టాక్స్ (S>=11 లిమిట్ లేకుండా) స్కాన్ అవ్వడానికి
            if "All Moves" in move_type_filter or len(move_type_filter) == 0:
                df_filtered = df_filtered[(df_filtered['Strategy_Icon'] != "Neutral") & (df_filtered['S'] >= 11)]
        elif watchlist_mode == "Day Trading Stocks 🚀":
            df_filtered = df_stocks[df_stocks['C'].abs() >= 1.0].copy()
        elif watchlist_mode == "High Score Stocks 🔥":
            df_filtered = df_stocks[(df_stocks['S'] >= 11) & (df_stocks['VolX'] >= 1.5)].copy()
        elif watchlist_mode == "Swing Trading 📈":
            df_filtered = df_stocks.copy()
            dfs_to_concat = []
            
            cond1 = (df_filtered['P'] > df_filtered['SMA150']) & ((df_filtered['P'] > df_filtered['SMA200']) | (df_filtered['SMA200'] == 0))
            cond2 = (df_filtered['SMA150'] > df_filtered['SMA200']) | (df_filtered['SMA200'] == 0)
            cond3 = (df_filtered['SMA200'] > df_filtered['SMA200_20D']) | (df_filtered['SMA200'] == 0)
            cond4 = df_filtered['P'] > df_filtered['SMA50']
            cond7 = df_filtered['SMA50'] > df_filtered['SMA150'] 
            cond5 = df_filtered['P'] >= (df_filtered['Low52W'] * 1.30)
            cond6 = df_filtered['P'] >= (df_filtered['High52W'] * 0.75)
            vcp_base_cond = cond1 & cond2 & cond3 & cond4 & cond7 & cond5 & cond6
    
            if "📈 Minervini Trend Template (VCP)" in move_type_filter:
                cond_fno = df_filtered['T'].isin(NIFTY_50 + FNO_STOCKS)
                df_min = df_filtered[cond_fno & vcp_base_cond].copy()
                df_min['Strategy_Icon'] = "📈 M-VCP"
                dfs_to_concat.append(df_min)
    
            if "🔥 Minervini MidCap 150" in move_type_filter:
                cond_mid = df_filtered['T'].isin(MIDCAP_150)
                df_mid = df_filtered[cond_mid & vcp_base_cond].copy()
                df_mid['Strategy_Icon'] = "🔥 Mid VCP"
                dfs_to_concat.append(df_mid)
    
            if "🚀 Minervini SmallCap 250" in move_type_filter:
                cond_small = df_filtered['T'].isin(SMALLCAP_250)
                df_small = df_filtered[cond_small & vcp_base_cond].copy()
                df_small['Strategy_Icon'] = "🚀 Small VCP"
                dfs_to_concat.append(df_small)
                
            if "📉 Strict VCP (Price & Vol Contraction)" in move_type_filter:
                cond_fno = df_filtered['T'].isin(NIFTY_50 + FNO_STOCKS)
                strict_vcp_cond = (df_filtered['VCP_Contract'] == True) & (df_filtered['VCP_Vol_Dry'] == True)
                df_vcp = df_filtered[cond_fno & vcp_base_cond & strict_vcp_cond].copy()
                df_vcp['Strategy_Icon'] = "📉 VCP"
                dfs_to_concat.append(df_vcp)
    
            if "All Swing Stocks" in move_type_filter or not move_type_filter:
                dfs_to_concat.append(df_filtered[df_filtered['Is_Swing'] == True])
    
            if dfs_to_concat:
                df_filtered = pd.concat(dfs_to_concat).drop_duplicates(subset=['Fetch_T'], keep='last')
                df_filtered = df_filtered.sort_values(by="Day_C", ascending=False).head(40)
            else:
                df_filtered = pd.DataFrame(columns=df_filtered.columns)
                
        elif watchlist_mode == "Legendary Strategy 🏆":
            strict_allowed = set(NIFTY_50 + FNO_STOCKS + MIDCAP_150)
            df_filtered = df_all_stocks[df_all_stocks['T'].isin(strict_allowed)].copy()
            dfs_to_concat = []
            
            has_history = (df_filtered['SMA200'] > 0) & (df_filtered['SMA150'] > 0)
            min_c1 = df_filtered['P'] > df_filtered['SMA150']  
            min_c2 = df_filtered['P'] > df_filtered['SMA200']
            min_c3 = df_filtered['SMA50'] > df_filtered['SMA200']
            min_c4 = df_filtered['SMA150'] > df_filtered['SMA200']
            min_c5 = df_filtered['SMA200'] > df_filtered['SMA200_20D'] 
            min_c6 = df_filtered['P'] >= (df_filtered['Low52W'] * 1.25) 
            min_c7 = df_filtered['P'] >= (df_filtered['High52W'] * 0.70) 
            vcp_base_cond = has_history & min_c1 & min_c2 & min_c3 & min_c4 & min_c5 & min_c6 & min_c7
            
            strat_selection = move_type_filter[0] if isinstance(move_type_filter, list) else move_type_filter
            is_intraday = (chart_timeframe == "Intraday (5m)")
            is_weekly = (chart_timeframe == "Weekly Chart")
    
            if strat_selection == "All Swing Trading Moves 📈":
                strats_to_run = [
                    "🧲 The 20-EMA Holy Grail Pullback",
                    "📉 RSI(2) Mean Reversion (Larry Connors)",
                    "📈 Minervini Trend Template (VCP)",
                    "📉 Strict VCP (Price & Vol Contraction)",
                    "📦 Nicolas Darvas (Box Breakout)",
                    "📦 Nicolas Darvas Modified",
                    "📈 Stan Weinstein (Stage 2 Uptrend)",
                    "💥 Dan Zanger (Volume Explosion)",
                    "👑 King Strategy (SMA Bounce)"
                ]
            else:
                strats_to_run = [strat_selection]
    
            # --- LOOPING THROUGH STRATEGIES ---
            for strat in strats_to_run:
                if strat == "🔥 First Hour Vol Breakout (ORB+VWAP)":
                    orb_trend = (df_filtered['P'] > df_filtered['VWAP']) & (df_filtered['Day_C'] > 1.0)
                    orb_vol = df_filtered['VolX'] >= 1.5
                    # ORB_Tag ki baduluga Open Drive logic vadutunnam (Error raakunda)
                    orb_breakout = (df_filtered['P'] > df_filtered['O']) & ((df_filtered['O'] - df_filtered['L']) <= (df_filtered['P'] * 0.005))
                    orb_cond = has_history & orb_trend & orb_vol & orb_breakout
                    df_orb = df_filtered[orb_cond].copy()
                    df_orb['Strategy_Icon'] = "🟢 1-Hr Breakout"
                    dfs_to_concat.append(df_orb)
    
                    # Sell logic for ORB - Breakdown
                    orb_sell_trend = (df_filtered['P'] < df_filtered['VWAP']) & (df_filtered['Day_C'] < -1.0)
                    orb_sell_breakdown = (df_filtered['P'] < df_filtered['O']) & ((df_filtered['H'] - df_filtered['O']) <= (df_filtered['P'] * 0.005))
                    orb_sell_cond = has_history & orb_sell_trend & orb_vol & orb_sell_breakdown
                    df_orb_sell = df_filtered[orb_sell_cond].copy()
                    df_orb_sell['Strategy_Icon'] = "🔴 1-Hr Breakout"
                    dfs_to_concat.append(df_orb_sell)
    
                elif strat == "💥 Inside Bar Vol Breakout (NR7)":
                    ib_trend = df_filtered['P'] > df_filtered['SMA50']
                    ib_vol = df_filtered['VolX'] >= 1.2
                    ib_narrow = (df_filtered['H'] - df_filtered['L']) / (df_filtered['L'] + 0.001) <= 0.02
                    ib_break = df_filtered['P'] > df_filtered['O']
                    ib_cond = has_history & ib_trend & ib_vol & ib_narrow & ib_break
                    df_ib = df_filtered[ib_cond].copy()
                    df_ib['Strategy_Icon'] = "🟢 Inside Bar"
                    dfs_to_concat.append(df_ib)
    
                    # Sell logic for Inside Bar - Breakdown
                    ib_sell_trend = df_filtered['P'] < df_filtered['SMA50']
                    ib_sell_break = df_filtered['P'] < df_filtered['O']
                    ib_sell_cond = has_history & ib_sell_trend & ib_vol & ib_narrow & ib_sell_break
                    df_ib_sell = df_filtered[ib_sell_cond].copy()
                    df_ib_sell['Strategy_Icon'] = "🔴 Inside Bar"
                    dfs_to_concat.append(df_ib_sell)
                elif strat == "⚡ Sudden VWAP Cross (Any Time)":
                    buy_mask = pd.Series(False, index=df_filtered.index)
                    sell_mask = pd.Series(False, index=df_filtered.index)
                    
                    # 1. Munduga High Volume (>= 1.3x) unna stocks ni matrame filter cheddam
                    high_vol_stocks = df_filtered[df_filtered['VolX'] >= 1.3]['Fetch_T'].tolist()
                    
                    if high_vol_stocks:
                        # 2. Aa high volume stocks ki matrame 5-min data fetch cheddam (Speed kosam)
                        temp_5m_data = fetch_cached_5m_data(high_vol_stocks)
                        
                        for idx, r in df_filtered.iterrows():
                            tkr = r['Fetch_T']
                            if tkr in high_vol_stocks:
                                try:
                                    df_raw = temp_5m_data[tkr] if isinstance(temp_5m_data.columns, pd.MultiIndex) else temp_5m_data
                                    df_hist = process_5m_data(df_raw)
                                    
                                    if not df_hist.empty and len(df_hist) >= 2:
                                        c1 = df_hist.iloc[-1] # Present 5-min candle
                                        c2 = df_hist.iloc[-2] # Previous 5-min candle
                                        
                                        # --- CROSS UP (BUY) ---
                                        cross_up = (c2['Close'] <= c2['VWAP']) and (c1['Close'] > c1['VWAP'])
                                        cross_up_candle = (c1['Open'] <= c1['VWAP']) and (c1['Close'] > c1['VWAP'])
                                        
                                        # --- CROSS DOWN (SELL) ---
                                        cross_dn = (c2['Close'] >= c2['VWAP']) and (c1['Close'] < c1['VWAP'])
                                        cross_dn_candle = (c1['Open'] >= c1['VWAP']) and (c1['Close'] < c1['VWAP'])
                                        
                                        if cross_up or cross_up_candle: buy_mask[idx] = True
                                        if cross_dn or cross_dn_candle: sell_mask[idx] = True
                                except: pass
                                
                    # 3. Final conditions apply cheyadam
                    c_buy = has_history & buy_mask 
                    c_sell = has_history & sell_mask 
                    
                    df_vwap_cross_buy = df_filtered[c_buy].copy()
                    if not df_vwap_cross_buy.empty:
                        df_vwap_cross_buy['Strategy_Icon'] = "🟢 VWAP Cross"
                        dfs_to_concat.append(df_vwap_cross_buy)
                        
                    df_vwap_cross_sell = df_filtered[c_sell].copy()
                    if not df_vwap_cross_sell.empty:
                        df_vwap_cross_sell['Strategy_Icon'] = "🔴 VWAP Cross"
                        dfs_to_concat.append(df_vwap_cross_sell)
                elif strat == "🧲 Intraday Dip & Support Bounce":
                    # 1. Day high nundi 0.8% nundi 3% varaku dip ayyi undali
                    day_pullback = ((df_filtered['H'] - df_filtered['P']) / df_filtered['H']) * 100
                    dip_in_range = (day_pullback >= 0.8) & (day_pullback <= 3.0)
    
                    # 2. VWAP leda EMA daggara support tisukovali
                    near_vwap = (df_filtered['P'] >= df_filtered['VWAP'] * 0.998) & (df_filtered['L'] <= df_filtered['VWAP'] * 1.002)
                    near_ema10 = (df_filtered['P'] >= df_filtered['W_EMA10'] * 0.998) & (df_filtered['L'] <= df_filtered['W_EMA10'] * 1.002)
                    near_support = near_vwap | near_ema10
    
                    # 3. High volume tho bounce ayyi undali
                    bounce_candle = (df_filtered['P'] > df_filtered['O']) & (df_filtered['Day_C'] > 0)
                    vol_surge = df_filtered['VolX'] >= 1.3
    
                    intra_bounce_cond = has_history & dip_in_range & near_support & bounce_candle & vol_surge
                    df_intra_bounce = df_filtered[intra_bounce_cond].copy()
                    df_intra_bounce['Strategy_Icon'] = "🟢 Dip Bounce"
                    dfs_to_concat.append(df_intra_bounce)
    
                    # Sell logic for Dip Bounce - Resistance Rejection
                    day_rally = ((df_filtered['P'] - df_filtered['L']) / df_filtered['L']) * 100
                    rally_in_range = (day_rally >= 0.8) & (day_rally <= 3.0)
                    near_vwap_resist = (df_filtered['P'] <= df_filtered['VWAP'] * 1.002) & (df_filtered['H'] >= df_filtered['VWAP'] * 0.998)
                    near_ema10_resist = (df_filtered['P'] <= df_filtered['W_EMA10'] * 1.002) & (df_filtered['H'] >= df_filtered['W_EMA10'] * 0.998)
                    near_resistance = near_vwap_resist | near_ema10_resist
                    reject_candle = (df_filtered['P'] < df_filtered['O']) & (df_filtered['Day_C'] < 0)
                    intra_reject_cond = has_history & rally_in_range & near_resistance & reject_candle & vol_surge
                    df_intra_reject = df_filtered[intra_reject_cond].copy()
                    df_intra_reject['Strategy_Icon'] = "🔴 Dip Reject"
                    dfs_to_concat.append(df_intra_reject)
                elif strat == "🧲 The 20-EMA Holy Grail Pullback":
                    hg_trend = (df_filtered['P'] > df_filtered['SMA50']) & (df_filtered['SMA50'] > df_filtered['SMA150'])
                    hg_pullback = (df_filtered['L'] <= df_filtered['W_EMA10'] * 1.02) & (df_filtered['P'] >= df_filtered['W_EMA10'])
                    hg_bounce = (df_filtered['P'] > df_filtered['O']) & (df_filtered['Day_C'] > 0.5)
                    hg_vol = df_filtered['VolX'] >= 1.0
                    hg_cond = has_history & hg_trend & hg_pullback & hg_bounce & hg_vol
                    df_hg = df_filtered[hg_cond].copy()
                    df_hg['Strategy_Icon'] = "🟢 Holy Grail"
                    dfs_to_concat.append(df_hg)
    
                    # Sell logic for Holy Grail - EMA Breakdown
                    hg_sell_trend = (df_filtered['P'] < df_filtered['SMA50']) & (df_filtered['SMA50'] < df_filtered['SMA150'])
                    hg_sell_breakdown = (df_filtered['P'] < df_filtered['W_EMA10'] * 0.98)
                    hg_sell_cond = has_history & hg_sell_trend & hg_sell_breakdown
                    df_hg_sell = df_filtered[hg_sell_cond].copy()
                    df_hg_sell['Strategy_Icon'] = "🔴 Holy Grail"
                    dfs_to_concat.append(df_hg_sell)
    
                elif strat == "📉 RSI(2) Mean Reversion (Larry Connors)":
                    lc_trend = df_filtered['P'] > df_filtered['SMA200']
                    lc_dip = df_filtered['P'] < df_filtered['W_EMA10']
                    lc_reversal = (df_filtered['P'] > df_filtered['O']) & (df_filtered['Day_C'] > 0.5)
                    lc_severe_dip = df_filtered['P'] <= (df_filtered['Box_Top20'] * 0.97)
                    lc_cond = has_history & lc_trend & lc_dip & lc_severe_dip & lc_reversal
                    df_lc = df_filtered[lc_cond].copy()
                    df_lc['Strategy_Icon'] = "🟢 RSI Reversal"
                    dfs_to_concat.append(df_lc)
    
                    # Sell logic for RSI - Overbought Reversal
                    lc_sell_trend = df_filtered['P'] < df_filtered['SMA200']
                    lc_sell_spike = df_filtered['P'] > df_filtered['W_EMA10']
                    lc_sell_down = (df_filtered['P'] < df_filtered['O']) & (df_filtered['Day_C'] < -0.5)
                    lc_sell_severe_spike = df_filtered['P'] >= (df_filtered['Box_Top20'] * 1.03)
                    lc_sell_cond = has_history & lc_sell_trend & lc_sell_spike & lc_sell_down & lc_sell_severe_spike
                    df_lc_sell = df_filtered[lc_sell_cond].copy()
                    df_lc_sell['Strategy_Icon'] = "🔴 RSI Reversal"
                    dfs_to_concat.append(df_lc_sell)
    
                elif strat == "📈 Minervini Trend Template (VCP)":
                    df_min = df_filtered[vcp_base_cond].copy()
                    if not df_min.empty:
                        df_min['Strategy_Icon'] = "🟢 M-VCP"
                        dfs_to_concat.append(df_min)
    
                    # Sell logic for VCP - Downtrend (Stage 4)
                    vcp_sell_c1 = df_filtered['P'] < df_filtered['SMA50']
                    vcp_sell_c2 = df_filtered['SMA50'] < df_filtered['SMA150']
                    vcp_sell_c3 = df_filtered['SMA150'] < df_filtered['SMA200']
                    vcp_sell_cond = has_history & vcp_sell_c1 & vcp_sell_c2 & vcp_sell_c3
                    df_vcp_sell = df_filtered[vcp_sell_cond].copy()
                    if not df_vcp_sell.empty:
                        df_vcp_sell['Strategy_Icon'] = "🔴 M-VCP"
                        dfs_to_concat.append(df_vcp_sell)
                    
                elif strat == "📉 Strict VCP (Price & Vol Contraction)":
                    recent_tightness = ((df_filtered['Box_Top20'] - df_filtered['Box_Bot20']) / (df_filtered['Box_Bot20'] + 0.001)) <= 0.25
                    vcp_vol_dry_strict = df_filtered['VCP_Vol_Dry'] == True
                    vcp_price_ok = df_filtered['P'] >= (df_filtered['High52W'] * 0.80)
                    strict_vcp_cond = (df_filtered['VCP_Contract'] == True) & recent_tightness & vcp_vol_dry_strict & vcp_price_ok
                    df_vcp = df_filtered[vcp_base_cond & strict_vcp_cond].copy()
                    df_vcp['Strategy_Icon'] = "🟢 VCP"
                    dfs_to_concat.append(df_vcp)
    
                    # Sell logic for Strict VCP
                    strict_vcp_sell_c1 = df_filtered['P'] < df_filtered['SMA50']
                    strict_vcp_sell_c2 = df_filtered['SMA50'] < df_filtered['SMA150']
                    strict_vcp_sell_c3 = df_filtered['SMA150'] < df_filtered['SMA200']
                    strict_vcp_sell_cond = has_history & strict_vcp_sell_c1 & strict_vcp_sell_c2 & strict_vcp_sell_c3
                    df_vcp_sell = df_filtered[strict_vcp_sell_cond].copy()
                    df_vcp_sell['Strategy_Icon'] = "🔴 VCP"
                    dfs_to_concat.append(df_vcp_sell)
    
                elif strat == "📦 Nicolas Darvas (Box Breakout)":
                    box_width = ((df_filtered['Box_Top20'] - df_filtered['Box_Bot20']) / (df_filtered['Box_Bot20'] + 0.001)) <= 0.25
                    darvas_trend = df_filtered['P'] > df_filtered['SMA50']
                    # Breakout కి 0.5% దగ్గరలో ఉన్నా క్యాచ్ చేయడానికి (Early Radar)
                    darvas_breakout = df_filtered['P'] >= (df_filtered['Box_Top20'] * 0.995)
                    darvas_high = df_filtered['P'] >= (df_filtered['High52W'] * 0.80)
                    # వాల్యూమ్ ని కొంచెం రిలాక్స్ చేసాము
                    darvas_vol = df_filtered['VolX'] >= 0.8 
                    
                    darvas_cond = has_history & darvas_trend & darvas_breakout & box_width & darvas_high & darvas_vol
                    df_darvas = df_filtered[darvas_cond].copy()
                    if not df_darvas.empty:
                        df_darvas['Strategy_Icon'] = "🟢 Darvas"
                        dfs_to_concat.append(df_darvas)
    
                    # Sell logic for Darvas - Box Breakdown
                    darvas_breakdown = df_filtered['P'] <= (df_filtered['Box_Bot20'] * 1.005)
                    darvas_sell_trend = df_filtered['P'] < df_filtered['SMA50']
                    darvas_sell_cond = has_history & darvas_breakdown & darvas_sell_trend & box_width
                    df_darvas_sell = df_filtered[darvas_sell_cond].copy()
                    if not df_darvas_sell.empty:
                        df_darvas_sell['Strategy_Icon'] = "🔴 Darvas"
                        dfs_to_concat.append(df_darvas_sell)
    
                elif strat == "📦 Nicolas Darvas Modified":
                    darvas_mod_breakout = df_filtered['P'] >= (df_filtered['Box_Top20'] * 0.995)
                    darvas_mod_nochase = df_filtered['P'] <= (df_filtered['Box_Top20'] * 1.020)
                    darvas_mod_vol = df_filtered['VolX'] >= 0.8
                    darvas_mod_trend = df_filtered['P'] > df_filtered['SMA50']
                    
                    darvas_mod_cond = has_history & darvas_mod_trend & darvas_mod_breakout & darvas_mod_nochase & darvas_mod_vol
                    df_darvas_mod = df_filtered[darvas_mod_cond].copy()
                    if not df_darvas_mod.empty:
                        df_darvas_mod['Strategy_Icon'] = "🟢 Darvas Mod"
                        dfs_to_concat.append(df_darvas_mod)
    
                    # Sell logic for Darvas Modified
                    darvas_mod_breakdown = df_filtered['P'] <= (df_filtered['Box_Bot20'] * 1.005)
                    darvas_mod_sell_trend = df_filtered['P'] < df_filtered['SMA50']
                    darvas_mod_sell_cond = has_history & darvas_mod_breakdown & darvas_mod_sell_trend
                    df_darvas_mod_sell = df_filtered[darvas_mod_sell_cond].copy()
                    if not df_darvas_mod_sell.empty:
                        df_darvas_mod_sell['Strategy_Icon'] = "🔴 Darvas Mod"
                        dfs_to_concat.append(df_darvas_mod_sell)
    
                elif strat == "📈 Stan Weinstein (Stage 2 Uptrend)":
                    wein_c1 = df_filtered['P'] > df_filtered['SMA150']
                    wein_c2 = df_filtered['SMA150'] > df_filtered['SMA150_20D']
                    wein_c3 = df_filtered['SMA50'] > df_filtered['SMA150']
                    wein_c4 = df_filtered['P'] >= (df_filtered['High52W'] * 0.75)
                    wein_c5 = df_filtered['P'] >= (df_filtered['Low52W'] * 1.30)
                    weinstein_cond = has_history & wein_c1 & wein_c2 & wein_c3 & wein_c4 & wein_c5
                    df_weinstein = df_filtered[weinstein_cond].copy()
                    df_weinstein['Strategy_Icon'] = "🟢 Stage 2"
                    dfs_to_concat.append(df_weinstein)
    
                    # Sell logic for Stage 4 Downtrend
                    wein_sell_c1 = df_filtered['P'] < df_filtered['SMA150']
                    wein_sell_c2 = df_filtered['SMA150'] < df_filtered['SMA150_20D']
                    wein_sell_c3 = df_filtered['SMA50'] < df_filtered['SMA150']
                    wein_sell_c4 = df_filtered['P'] <= (df_filtered['Low52W'] * 1.10)
                    wein_sell_cond = has_history & wein_sell_c1 & wein_sell_c2 & wein_sell_c3 & wein_sell_c4
                    df_weinstein_sell = df_filtered[wein_sell_cond].copy()
                    df_weinstein_sell['Strategy_Icon'] = "🔴 Stage 4"
                    dfs_to_concat.append(df_weinstein_sell)
                    
                elif strat == "💥 Dan Zanger (Volume Explosion)":
                    zanger_vol = df_filtered['VolX'] >= 1.5
                    zanger_ma = (df_filtered['P'] > df_filtered['SMA50']) & (df_filtered['SMA50'] > df_filtered['SMA150'])
                    bar_range = df_filtered['H'] - df_filtered['L']
                    close_position = (df_filtered['P'] - df_filtered['L']) / (bar_range + 0.001)
                    zanger_close = close_position >= 0.70
                    zanger_breakout = df_filtered['P'] >= (df_filtered['Box_Top20'] * 0.98)
                    zanger_dryup = df_filtered['VCP_Vol_Dry'] == True
                    zanger_cond = has_history & zanger_vol & zanger_ma & zanger_close & zanger_breakout & zanger_dryup
                    df_zanger = df_filtered[zanger_cond].copy()
                    df_zanger['Strategy_Icon'] = "🟢 Zanger"
                    dfs_to_concat.append(df_zanger)
    
                    # Sell logic for Zanger - Reversal
                    zanger_sell_ma = (df_filtered['P'] < df_filtered['SMA50']) & (df_filtered['SMA50'] < df_filtered['SMA150'])
                    zanger_sell_close = close_position <= 0.30
                    zanger_sell_breakdown = df_filtered['P'] <= (df_filtered['Box_Bot20'] * 1.02)
                    zanger_sell_cond = has_history & zanger_sell_ma & zanger_sell_close & zanger_sell_breakdown
                    df_zanger_sell = df_filtered[zanger_sell_cond].copy()
                    df_zanger_sell['Strategy_Icon'] = "🔴 Zanger"
                    dfs_to_concat.append(df_zanger_sell)
                elif strat == "🎯 52WH Pullback & 52WL Breakdown (Top 32)":
                    # --- 🟢 BUY SIDE (Sell logic ki quite opposite - Near 52WH Breakout) ---
                    buy_trend = (df_filtered['P'] > df_filtered['SMA200']) & (df_filtered['Pullback_52W'] <= 15.0)
                    df_52wh_buy = df_filtered[has_history & buy_trend].copy()
                    if not df_52wh_buy.empty:
                        df_52wh_buy['Strategy_Icon'] = "🟢 52WH Pullback"
                        # Strong momentum unna stocks top lo raavadaniki Score ('S') tho sort chestunnam
                        df_52wh_buy = df_52wh_buy.sort_values(by='S', ascending=False).head(32)
                        dfs_to_concat.append(df_52wh_buy)
    
                    # --- 🔴 SELL SIDE (52-Week Low vaipu crash avuthunna weak stocks) ---
                    dist_from_52wl = ((df_filtered['P'] - df_filtered['Low52W']) / df_filtered['Low52W']) * 100
                    sell_trend = (df_filtered['P'] < df_filtered['SMA200']) & (dist_from_52wl <= 15.0)
                    df_52wl_sell = df_filtered[has_history & sell_trend].copy()
                    if not df_52wl_sell.empty:
                        df_52wl_sell['Strategy_Icon'] = "🔴 52WL Breakdown"
                        df_52wl_sell = df_52wl_sell.sort_values(by='Pullback_52W', ascending=False).head(32)
                        dfs_to_concat.append(df_52wl_sell)    
                elif strat == "⏳ Anticipation SMA Base (20/50/150/200)":
                    # 1. Trend condition (SMA 150 > SMA 200 ayyi undali)
                    base_trend = (df_filtered['SMA150'] > df_filtered['SMA200']) | (df_filtered['SMA200'] == 0)
                    base_cond = has_history & base_trend
    
                    # 2. SMA ki 3% range lo support teeskunevi
                    near_20 = (df_filtered['P'] >= df_filtered['SMA20'] * 0.97) & (df_filtered['P'] <= df_filtered['SMA20'] * 1.03)
                    near_50 = (df_filtered['P'] >= df_filtered['SMA50'] * 0.97) & (df_filtered['P'] <= df_filtered['SMA50'] * 1.03)
                    near_150 = (df_filtered['P'] >= df_filtered['SMA150'] * 0.97) & (df_filtered['P'] <= df_filtered['SMA150'] * 1.03)
                    near_200 = (df_filtered['P'] >= df_filtered['SMA200'] * 0.97) & (df_filtered['P'] <= df_filtered['SMA200'] * 1.03)
    
                    # 20 SMA - Exactly 8 stocks
                    df_20 = df_filtered[base_cond & near_20].copy()
                    if not df_20.empty:
                        df_20['Strategy_Icon'] = "🟢 20-SMA Base"
                        dfs_to_concat.append(df_20.sort_values(by='S', ascending=False).head(8))
    
                    # 50 SMA - Exactly 8 stocks (Repeat aveyykunda)
                    df_50 = df_filtered[base_cond & near_50 & ~df_filtered.index.isin(df_20.index)].copy()
                    if not df_50.empty:
                        df_50['Strategy_Icon'] = "🟢 50-SMA Base"
                        dfs_to_concat.append(df_50.sort_values(by='S', ascending=False).head(8))
    
                    # 150 SMA - Exactly 8 stocks
                    df_150 = df_filtered[base_cond & near_150 & ~df_filtered.index.isin(df_20.index) & ~df_filtered.index.isin(df_50.index)].copy()
                    if not df_150.empty:
                        df_150['Strategy_Icon'] = "🟢 150-SMA Base"
                        dfs_to_concat.append(df_150.sort_values(by='S', ascending=False).head(8))
    
                    # 200 SMA - Exactly 8 stocks
                    df_200 = df_filtered[base_cond & near_200 & ~df_filtered.index.isin(df_20.index) & ~df_filtered.index.isin(df_50.index) & ~df_filtered.index.isin(df_150.index)].copy()
                    if not df_200.empty:
                        df_200['Strategy_Icon'] = "🟢 200-SMA Base"
                        dfs_to_concat.append(df_200.sort_values(by='S', ascending=False).head(8))
            
            # ---> FINAL CONCAT BLOCK <---
            if dfs_to_concat:
                df_filtered = pd.concat(dfs_to_concat).drop_duplicates(subset=['Fetch_T'], keep='last')
                sort_metric = "W_C" if chart_timeframe == "Weekly Chart" else "Day_C"
                df_filtered = df_filtered.sort_values(by=sort_metric, ascending=False)
            else:
                df_filtered = pd.DataFrame(columns=df_filtered.columns)
    
        all_display_tickers = list(set(df_indices['Fetch_T'].tolist() + df_sectors['Fetch_T'].tolist() + df_filtered['Fetch_T'].tolist() + st.session_state.pinned_stocks))
        
        if st.session_state.get('active_sec'):
            sec_stock_names = TOP_SECTOR_STOCKS.get(st.session_state.active_sec, [])
            sec_tickers = [f"{sym}.NS" for sym in sec_stock_names]
            all_display_tickers = list(set(all_display_tickers + sec_tickers))
        
        if search_stock != "-- None --" and not df[df['T'] == search_stock].empty:
            search_fetch_t = df[df['T'] == search_stock]['Fetch_T'].iloc[0]
            if search_fetch_t not in all_display_tickers: all_display_tickers.append(search_fetch_t)
                
        five_min_data = fetch_cached_5m_data(all_display_tickers)
    
        processed_charts = {}
        weekly_trends = {}
        alpha_tags = {}
        trend_scores = {}
        retest_tags = {}
        orb_tags = {} 
    
        nifty_dist_5m = 0.1
        fetched_5m_symbols = five_min_data.columns.levels[0] if isinstance(five_min_data.columns, pd.MultiIndex) else five_min_data.columns
    
        if "^NSEI" in fetched_5m_symbols:
            n_raw = five_min_data["^NSEI"] if isinstance(five_min_data.columns, pd.MultiIndex) else five_min_data
            n_day = process_5m_data(n_raw)
            if not n_day.empty:
                n_ltp = n_day['Close'].iloc[-1]
                n_vwap = n_day['VWAP'].iloc[-1]
                if n_vwap > 0: nifty_dist_5m = abs(n_ltp - n_vwap) / n_vwap * 100
    
        df_lookup = df.drop_duplicates(subset=['Fetch_T'], keep='first').set_index('Fetch_T').to_dict('index')
    
        for sym in all_display_tickers:
            try: df_raw = five_min_data[sym] if isinstance(five_min_data.columns, pd.MultiIndex) else five_min_data
            except KeyError: df_raw = pd.DataFrame()
                
            df_day = process_5m_data(df_raw)
            processed_charts[sym] = df_day
            
            try:
                sym_row = df_lookup.get(sym)
                if sym_row:
                    w_ema10 = float(sym_row['W_EMA10'])
                    w_ema50 = float(sym_row['W_EMA50'])
                    last_p = float(sym_row['P'])
                    if last_p > w_ema10 and w_ema10 >= w_ema50: weekly_trends[sym] = 'Bullish'
                    elif last_p < w_ema10 and w_ema10 <= w_ema50: weekly_trends[sym] = 'Bearish'
                    else: weekly_trends[sym] = 'Neutral'
                else:
                    weekly_trends[sym] = 'Neutral'
            except: weekly_trends[sym] = 'Neutral'
                
            if sym in df_filtered['Fetch_T'].tolist() and not df_day.empty:
                last_price = df_day['Close'].iloc[-1]
                last_vwap = df_day['VWAP'].iloc[-1]
                sym_info = df_lookup.get(sym, {})
                net_chg = sym_info.get('C', 0)
                
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
                        if current_gap_pct >= 1.50: one_sided_tag = "🌊Mega-1.5%"; trend_bonus = 7
                        elif current_gap_pct >= 1.00: one_sided_tag = "🌊Super-1.0%"; trend_bonus = 5
                        elif current_gap_pct >= 0.50: one_sided_tag = "🌊Trend-0.5%"; trend_bonus = 3
                        else: one_sided_tag = "🌊Trend"; trend_bonus = 1
                
                trap_tag = ""
                trap_bonus = 0
                if watchlist_mode in ["Day Trading Stocks 🚀", "High Score Stocks 🔥"] and len(df_day) >= 6 and last_vwap > 0:
                    curr_open = float(df_day['Open'].iloc[-1])
                    day_open = sym_info.get('O', 0)
                    day_high = sym_info.get('H', 0)
                    day_low = sym_info.get('L', 0)
                    morning_spike = (day_high - day_open) / day_open * 100 if day_open > 0 else 0
                    morning_drop = (day_open - day_low) / day_open * 100 if day_open > 0 else 0
    
                    if morning_spike >= 1.0 and last_price < last_vwap:
                        if (last_price < curr_open): trap_tag = f"🎯 Reversal Sell 🩸"; trap_bonus = 6 
                    elif morning_drop >= 1.0 and last_price > last_vwap:
                        if (last_price > curr_open): trap_tag = f"🎯 Reversal Buy 🚀"; trap_bonus = 6
    
                alpha_tags[sym] = f"{alpha_tag} {one_sided_tag} {trap_tag}".strip()
                trend_scores[sym] = trend_bonus + trap_bonus
                
                retest_tag = ""
                if watchlist_mode in ["Day Trading Stocks 🚀", "🤖 Today's AI Predictions"] and len(df_day) >= 4:
                    c1 = df_day.iloc[-1] 
                    c2 = df_day.iloc[-2] 
                    if c1['Close'] > c1['VWAP'] and c1['EMA_10'] > c1['VWAP']:
                        if (c2['Low'] <= c2['EMA_10'] * 1.002) and (c2['Close'] >= c2['EMA_10']): 
                            max_allowed_price = c1['EMA_10'] * 1.003
                            if c1['Close'] > c1['Open'] and (c1['EMA_10'] <= c1['Close'] <= max_allowed_price): retest_tag = "BUY_RETEST"
                    elif c1['Close'] < c1['VWAP'] and c1['EMA_10'] < c1['VWAP']:
                        if (c2['High'] >= c2['EMA_10'] * 0.998) and (c2['Close'] <= c2['EMA_10']):
                            min_allowed_price = c1['EMA_10'] * 0.997
                            if c1['Close'] < c1['Open'] and (min_allowed_price <= c1['Close'] <= c1['EMA_10']): retest_tag = "SELL_RETEST"
                retest_tags[sym] = retest_tag
    
                orb_tag = ""
                if watchlist_mode in ["Day Trading Stocks 🚀", "High Score Stocks 🔥", "🤖 Today's AI Predictions"] and len(df_day) >= 3:
                    orb_high = df_day['High'].iloc[0:3].max()
                    orb_low = df_day['Low'].iloc[0:3].min()
                    if last_price > orb_high and last_price > last_vwap:
                        orb_tag = "ORB_BUY"
                    elif last_price < orb_low and last_price < last_vwap:
                        orb_tag = "ORB_SELL"
                orb_tags[sym] = orb_tag
    
        alerts_triggered_html = ""
        for sym, a_data in st.session_state.custom_alerts.items():
            if a_data['enabled']:
                live_r = df[df['Fetch_T'] == sym]
                if not live_r.empty:
                    current_ltp = float(live_r['P'].iloc[0])
                    alert_key = f"{sym}_{a_data['price']}_{a_data['type']}"
                    if "Above" in a_data['type'] and current_ltp >= a_data['price']:
                        if alert_key not in st.session_state.alert_triggered:
                            st.toast(f"🔔 ALERT: {a_data['name']} is ABOVE ₹{a_data['price']}! (LTP: {current_ltp})", icon="🚀")
                            st.session_state.alert_triggered.add(alert_key)
                        alerts_triggered_html += f"<div style='background-color:#1e5f29; color:white; padding:10px; border-radius:5px; margin-bottom:5px;'><b>🔔 ALERT:</b> {a_data['name']} crossed ABOVE ₹{a_data['price']}! (LTP: {current_ltp})</div>"
                    elif "Below" in a_data['type'] and current_ltp <= a_data['price']:
                        if alert_key not in st.session_state.alert_triggered:
                            st.toast(f"🔔 ALERT: {a_data['name']} is BELOW ₹{a_data['price']}! (LTP: {current_ltp})", icon="🩸")
                            st.session_state.alert_triggered.add(alert_key)
                        alerts_triggered_html += f"<div style='background-color:#b52524; color:white; padding:10px; border-radius:5px; margin-bottom:5px;'><b>🔔 ALERT:</b> {a_data['name']} crossed BELOW ₹{a_data['price']}! (LTP: {current_ltp})</div>"
    
        if alerts_triggered_html: st.markdown(alerts_triggered_html, unsafe_allow_html=True)
    
        df_stocks_display = pd.DataFrame(columns=df_filtered.columns)
        sort_key = "W_C" if chart_timeframe == "Weekly Chart" else "Day_C"
    
        if not df_filtered.empty:
            df_filtered = df_filtered.copy()
            
            df_filtered['AlphaTag'] = df_filtered['Fetch_T'].map(alpha_tags).fillna("")
            df_filtered['Trend_Score'] = pd.to_numeric(df_filtered['Fetch_T'].map(trend_scores), errors='coerce').fillna(0).astype(int)
            df_filtered['Retest_Tag'] = df_filtered['Fetch_T'].map(retest_tags).fillna("") 
            df_filtered['ORB_Tag'] = df_filtered['Fetch_T'].map(orb_tags).fillna("") 
            df_filtered['S'] = df_filtered['S'] + df_filtered['Trend_Score']
            
            if watchlist_mode in ["Day Trading Stocks 🚀", "🤖 Today's AI Predictions"]:
                sector_bull_perf = sector_perf[sector_perf > 0].sort_values(ascending=False)
                sector_bonus_map = {}
                for rank, sec in enumerate(sector_bull_perf.index):
                    bonus = max(10 - (rank * 2), 0)
                    sector_bonus_map[sec] = bonus
                df_filtered['Sector_Bonus'] = df_filtered['Sector'].map(sector_bonus_map).fillna(0)
            else:
                df_filtered['Sector_Bonus'] = 0
                
            if watchlist_mode == "🤖 AI Predictions (F&O)" and "🧲 10-EMA Retest (Best Entry)" in move_type_filter:
                df_filtered = df_filtered[
                    (df_filtered['Strategy_Icon'].str.contains('UP', na=False) & (df_filtered['Retest_Tag'] == 'BUY_RETEST')) |
                    (df_filtered['Strategy_Icon'].str.contains('DOWN', na=False) & (df_filtered['Retest_Tag'] == 'SELL_RETEST'))
                ]
            
            if "AI Predictions" in watchlist_mode:
                # W_EMA50 కండిషన్ తీసేసి బేస్ లాజిక్ సింపుల్ చేసాము
                base_buy = (df_filtered['P'] > df_filtered['W_EMA10']) & (df_filtered['P'] > df_filtered['VWAP'])
                base_sell = (df_filtered['P'] < df_filtered['W_EMA10']) & (df_filtered['P'] < df_filtered['VWAP'])
                
                nifty_dist = 0.25 
                nifty_row = df_indices[df_indices['T'] == 'NIFTY']
                if not nifty_row.empty:
                    n_h, n_l, n_p = float(nifty_row['H'].iloc[0]), float(nifty_row['L'].iloc[0]), float(nifty_row['P'].iloc[0])
                    n_vwap = (n_h + n_l + n_p) / 3
                    nifty_dist = min(max(abs(n_p - n_vwap) / n_vwap * 100, 0.25), 0.75)
                
                s_vwap = (df_filtered['H'] + df_filtered['L'] + df_filtered['P']) / 3
                stock_vwap_dist = (df_filtered['P'] - s_vwap).abs() / s_vwap * 100
                
                open_drive_bull = pd.Series(False, index=df_filtered.index)
                open_drive_bear = pd.Series(False, index=df_filtered.index)
                
                for idx, r in df_filtered.iterrows():
                    tkr = r['Fetch_T']
                    if tkr in processed_charts and len(processed_charts[tkr]) >= 2:
                        df_hist = processed_charts[tkr]
                        day_open = df_hist['Open'].iloc[0]
                        low_after_1st = df_hist['Low'].iloc[1:].min()
                        high_after_1st = df_hist['High'].iloc[1:].max()
                        
                        if (day_open - low_after_1st) <= (r['P'] * 0.003):
                            open_drive_bull[idx] = True
                        if (high_after_1st - day_open) <= (r['P'] * 0.003):
                            open_drive_bear[idx] = True
                    else:
                        if (r['O'] - r['L']) <= (r['P'] * 0.003):
                            open_drive_bull[idx] = True
                        if (r['H'] - r['O']) <= (r['P'] * 0.003):
                            open_drive_bear[idx] = True
    
                strategies_list = [
                    "🔥 First Hour Vol Breakout (ORB+VWAP)", "💥 Inside Bar Vol Breakout (NR7)", "⚡ Sudden VWAP Cross (Any Time)", "🧲 Intraday Dip & Support Bounce",
                    "🚀 Gap & Go (Open = Low)", "💥 PDH / PDL Breakout", "🧲 VWAP Bounce (Low Risk Entry)", "🎯 Narrow CPR Trending Day",
                    "🔥 Live Power Mover (Last 2 Candles)", "🚀 All-Day Volume Spikes (Max Fire)", "⚡ Intraday Pro Breakout (Top 5)", "🌊 One Sided Only", "🔄 VWAP Reversal", "🎯 Reversals Only", 
                    "🏹 Rubber Band Stretch", "🏄‍♂️ Momentum Ignition", "💥 Narrow CPR Breakout", "🧲 10-EMA Retest (Best Entry)", "📉 FIB Retracement (0.382)", "🌅 15-Min ORB (Opening Range Breakout)"
                ]
                
                fib_range = (df_filtered['H'] - df_filtered['L'])
                fib_buy_0382 = df_filtered['H'] - (fib_range * 0.382)
                fib_buy_0618 = df_filtered['H'] - (fib_range * 0.618)
                fib_sell_0382 = df_filtered['L'] + (fib_range * 0.382)
                fib_sell_0618 = df_filtered['L'] + (fib_range * 0.618)
    
                fib_buy_mask = (df_filtered['P'] > df_filtered['VWAP']) & (df_filtered['P'] <= fib_buy_0382) & (df_filtered['P'] >= fib_buy_0618) & (fib_range > 0)
                fib_sell_mask = (df_filtered['P'] < df_filtered['VWAP']) & (df_filtered['P'] >= fib_sell_0382) & (df_filtered['P'] <= fib_sell_0618) & (fib_range > 0)
    
                apply_fib_strict = "📉 FIB Retracement (0.382)" in move_type_filter
                other_strats_selected = [s for s in move_type_filter if s not in ["📉 FIB Retracement (0.382)", "All Moves"]]
                
                if "All Day Trading Moves 🚀" in move_type_filter:
                    strats_to_run = [
                        "🔥 First Hour Vol Breakout (ORB+VWAP)", "💥 Inside Bar Vol Breakout (NR7)", 
                        "🧲 Intraday Dip & Support Bounce", "⚡ Sudden VWAP Cross (Any Time)"
                    ]
                else:
                    strats_to_run = strategies_list if (not move_type_filter or "All Moves" in move_type_filter) else move_type_filter
                    
                if apply_fib_strict and (len(other_strats_selected) > 0 or "All Moves" in move_type_filter):
                    strats_to_run = [s for s in strats_to_run if s != "📉 FIB Retracement (0.382)"]
    
                all_dfs = []
                for strat in strats_to_run:
                    c_buy = pd.Series(False, index=df_filtered.index)
                    c_sell = pd.Series(False, index=df_filtered.index)
                    icon_str = ""
                for strat in strats_to_run:
                    c_buy = pd.Series(False, index=df_filtered.index)
                    c_sell = pd.Series(False, index=df_filtered.index)
                    icon_str = ""
    
                    if strat == "🔥 First Hour Vol Breakout (ORB+VWAP)":
                        orb_trend = (df_filtered['P'] > df_filtered['VWAP']) & (df_filtered['Day_C'] > 1.0)
                        orb_vol = df_filtered['VolX'] >= 1.5
                        orb_breakout = (df_filtered['P'] > df_filtered['O']) & ((df_filtered['O'] - df_filtered['L']) <= (df_filtered['P'] * 0.005))
                        c_buy = base_buy & orb_trend & orb_vol & orb_breakout
    
                        orb_sell_trend = (df_filtered['P'] < df_filtered['VWAP']) & (df_filtered['Day_C'] < -1.0)
                        orb_sell_breakdown = (df_filtered['P'] < df_filtered['O']) & ((df_filtered['H'] - df_filtered['O']) <= (df_filtered['P'] * 0.005))
                        c_sell = base_sell & orb_sell_trend & orb_vol & orb_sell_breakdown
                        icon_str = "🚀 1-Hr BO"
    
                    elif strat == "💥 Inside Bar Vol Breakout (NR7)":
                        ib_trend = df_filtered['P'] > df_filtered['SMA50']
                        ib_vol = df_filtered['VolX'] >= 1.2
                        ib_narrow = (df_filtered['H'] - df_filtered['L']) / (df_filtered['L'] + 0.001) <= 0.02
                        ib_break = df_filtered['P'] > df_filtered['O']
                        c_buy = base_buy & ib_trend & ib_vol & ib_narrow & ib_break
    
                        ib_sell_trend = df_filtered['P'] < df_filtered['SMA50']
                        ib_sell_break = df_filtered['P'] < df_filtered['O']
                        c_sell = base_sell & ib_sell_trend & ib_vol & ib_narrow & ib_sell_break
                        icon_str = "💥 NR7 BO"
    
                    elif strat == "⚡ Sudden VWAP Cross (Any Time)":
                        buy_mask = pd.Series(False, index=df_filtered.index)
                        sell_mask = pd.Series(False, index=df_filtered.index)
                        high_vol_stocks = df_filtered[df_filtered['VolX'] >= 1.3]['Fetch_T'].tolist()
                        if high_vol_stocks:
                            temp_5m_data = fetch_cached_5m_data(high_vol_stocks)
                            for idx, r in df_filtered.iterrows():
                                tkr = r['Fetch_T']
                                if tkr in high_vol_stocks:
                                    try:
                                        df_raw = temp_5m_data[tkr] if isinstance(temp_5m_data.columns, pd.MultiIndex) else temp_5m_data
                                        df_hist = process_5m_data(df_raw)
                                        if not df_hist.empty and len(df_hist) >= 2:
                                            c1 = df_hist.iloc[-1]
                                            c2 = df_hist.iloc[-2]
                                            cross_up = (c2['Close'] <= c2['VWAP']) and (c1['Close'] > c1['VWAP'])
                                            cross_up_candle = (c1['Open'] <= c1['VWAP']) and (c1['Close'] > c1['VWAP'])
                                            cross_dn = (c2['Close'] >= c2['VWAP']) and (c1['Close'] < c1['VWAP'])
                                            cross_dn_candle = (c1['Open'] >= c1['VWAP']) and (c1['Close'] < c1['VWAP'])
                                            if cross_up or cross_up_candle: buy_mask[idx] = True
                                            if cross_dn or cross_dn_candle: sell_mask[idx] = True
                                    except: pass
                        c_buy = base_buy & buy_mask
                        c_sell = base_sell & sell_mask
                        icon_str = "⚡ VWAP Cross"
    
                    elif strat == "🧲 Intraday Dip & Support Bounce":
                        day_pullback = ((df_filtered['H'] - df_filtered['P']) / df_filtered['H']) * 100
                        dip_in_range = (day_pullback >= 0.8) & (day_pullback <= 3.0)
                        near_vwap = (df_filtered['P'] >= df_filtered['VWAP'] * 0.998) & (df_filtered['L'] <= df_filtered['VWAP'] * 1.002)
                        near_ema10 = (df_filtered['P'] >= df_filtered['W_EMA10'] * 0.998) & (df_filtered['L'] <= df_filtered['W_EMA10'] * 1.002)
                        near_support = near_vwap | near_ema10
                        bounce_candle = (df_filtered['P'] > df_filtered['O']) & (df_filtered['Day_C'] > 0)
                        vol_surge = df_filtered['VolX'] >= 1.3
                        c_buy = base_buy & dip_in_range & near_support & bounce_candle & vol_surge
    
                        day_rally = ((df_filtered['P'] - df_filtered['L']) / df_filtered['L']) * 100
                        rally_in_range = (day_rally >= 0.8) & (day_rally <= 3.0)
                        near_vwap_resist = (df_filtered['P'] <= df_filtered['VWAP'] * 1.002) & (df_filtered['H'] >= df_filtered['VWAP'] * 0.998)
                        near_ema10_resist = (df_filtered['P'] <= df_filtered['W_EMA10'] * 1.002) & (df_filtered['H'] >= df_filtered['W_EMA10'] * 0.998)
                        near_resistance = near_vwap_resist | near_ema10_resist
                        reject_candle = (df_filtered['P'] < df_filtered['O']) & (df_filtered['Day_C'] < 0)
                        c_sell = base_sell & rally_in_range & near_resistance & reject_candle & vol_surge
                        icon_str = "🧲 Dip Bounce"
    
                    elif strat == "🔥 Live Power Mover (Last 2 Candles)":
                        buy_mask = pd.Series(False, index=df_filtered.index)
                        sell_mask = pd.Series(False, index=df_filtered.index)
                        
                        for idx, r in df_filtered.iterrows():
                            tkr = r['Fetch_T']
                            if tkr in processed_charts and len(processed_charts[tkr]) >= 2:
                                df_hist = processed_charts[tkr]
                                if 'Volume' in df_hist.columns and 'Vol_SMA_375' in df_hist.columns and 'EMA_10' in df_hist.columns:
                                    vol_fire = df_hist['Volume'] > (df_hist['Vol_SMA_375'].shift(1) * 1.5)
                                    b_cond = vol_fire & (df_hist['Close'] > df_hist['Close'].shift(1)) & (df_hist['Close'] >= df_hist['EMA_10'])
                                    s_cond = vol_fire & (df_hist['Close'] < df_hist['Close'].shift(1)) & (df_hist['Close'] <= df_hist['EMA_10'])
                                    if b_cond.iloc[-2:].sum() >= 1: buy_mask[idx] = True
                                    if s_cond.iloc[-2:].sum() >= 1: sell_mask[idx] = True
                                    
                        c_buy = base_buy & buy_mask
                        c_sell = base_sell & sell_mask
                        icon_str = "🔥 Live Breakout"
    
                    elif strat == "🚀 All-Day Volume Spikes (Max Fire)":
                        buy_mask = pd.Series(False, index=df_filtered.index)
                        sell_mask = pd.Series(False, index=df_filtered.index)
                        
                        df_fno = df_filtered[df_filtered['T'].isin(FNO_STOCKS)]
                        
                        for idx, r in df_fno.iterrows():
                            tkr = r['Fetch_T']
                            if tkr in processed_charts and len(processed_charts[tkr]) >= 2:
                                df_hist = processed_charts[tkr]
                                if 'Volume' in df_hist.columns and 'Vol_SMA_375' in df_hist.columns and 'EMA_10' in df_hist.columns:
                                    ltp = df_hist['Close'].iloc[-1]
                                    vwap = df_hist['VWAP'].iloc[-1]
                                    ema10 = df_hist['EMA_10'].iloc[-1]
                                    
                                    is_buy_trend = (ltp > vwap) and (ltp > ema10)
                                    is_sell_trend = (ltp < vwap) and (ltp < ema10)
                                    vol_fire = df_hist['Volume'] > (df_hist['Vol_SMA_375'].shift(1) * 1.5)
                                    
                                    valid_buy_fire = vol_fire & (df_hist['Close'] > df_hist['Close'].shift(1)) & (df_hist['Close'] >= df_hist['EMA_10'])
                                    valid_sell_fire = vol_fire & (df_hist['Close'] < df_hist['Close'].shift(1)) & (df_hist['Close'] <= df_hist['EMA_10'])
                                    
                                    tot_buy = valid_buy_fire.sum()
                                    tot_sell = valid_sell_fire.sum()
                                    fire_score = 0
                                    
                                    if is_buy_trend and tot_buy >= 1 and tot_buy > tot_sell: 
                                        buy_mask[idx] = True
                                        fire_score = (tot_buy - tot_sell) * 10
                                    elif is_sell_trend and tot_sell >= 1 and tot_sell > tot_buy: 
                                        sell_mask[idx] = True
                                        fire_score = (tot_sell - tot_buy) * 10
                                        
                                    if fire_score > 0:
                                        price_score = int(abs(r['Day_C']) * 5)
                                        s_vwap = r.get('VWAP', r['P'])
                                        s_dist = abs(r['P'] - s_vwap) / s_vwap * 100 if s_vwap > 0 else 0
                                        safe_nifty = max(nifty_dist, 0.2) 
                                        rs_score = 0
                                        if s_dist >= (safe_nifty * 4): rs_score = 20
                                        elif s_dist >= (safe_nifty * 3): rs_score = 15
                                        elif s_dist >= (safe_nifty * 2): rs_score = 10
                                        elif s_dist >= (safe_nifty * 1.5): rs_score = 5
                                        
                                        df_filtered.at[idx, 'S'] = df_filtered.at[idx, 'S'] + fire_score + price_score + rs_score
    
                        c_buy = base_buy & buy_mask & (df_filtered['Day_C'] >= 1.0)
                        c_sell = base_sell & sell_mask & (df_filtered['Day_C'] <= -1.0)
                        icon_str = "🚀 Max Fire"
                    elif strat == "⚡ Intraday Pro Breakout (Top 5)":
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
                        c_buy = base_buy & (df_filtered['Narrow_CPR'] == True) & (df_filtered['Day_C'] >= 1.0)
                        c_sell = base_sell & (df_filtered['Narrow_CPR'] == True) & (df_filtered['Day_C'] <= -1.0)
                        icon_str = "💥"
                    elif strat == "🧲 10-EMA Retest (Best Entry)":
                        ai_buy = (df_filtered['P'] > df_filtered['VWAP']) & (df_filtered['VolX'] >= 1.5) & (df_filtered.get('Bull_P', 0) >= 75)
                        ai_sell = (df_filtered['P'] < df_filtered['VWAP']) & (df_filtered['VolX'] >= 1.5) & (df_filtered.get('Bear_P', 0) >= 75)
                        dt_buy = ((df_filtered['Trend_Score'] >= 3) | (df_filtered['Narrow_CPR'] == True) | (df_filtered['AlphaTag'].str.contains("Reversal Buy", na=False)) | (df_filtered['Day_C'] >= 1.5))
                        dt_sell = ((df_filtered['Trend_Score'] >= 3) | (df_filtered['Narrow_CPR'] == True) | (df_filtered['AlphaTag'].str.contains("Reversal Sell", na=False)) | (df_filtered['Day_C'] <= -1.5))
                        c_buy = base_buy & (ai_buy | dt_buy) & (df_filtered['Retest_Tag'] == "BUY_RETEST")
                        c_sell = base_sell & (ai_sell | dt_sell) & (df_filtered['Retest_Tag'] == "SELL_RETEST")
                        icon_str = "🧲"
                    elif strat == "📉 FIB Retracement (0.382)":
                        c_buy = base_buy & fib_buy_mask
                        c_sell = base_sell & fib_sell_mask
                        icon_str = "📉 FIB"
                    elif strat == "📈 Minervini Trend Template (VCP)":
                        cond1 = (df_filtered['P'] > df_filtered['SMA150']) & (df_filtered['P'] > df_filtered['SMA200'])
                        cond2 = df_filtered['SMA150'] > df_filtered['SMA200']
                        cond3 = df_filtered['SMA200'] > df_filtered['SMA200_20D']
                        cond4 = (df_filtered['SMA50'] > df_filtered['SMA150']) & (df_filtered['SMA50'] > df_filtered['SMA200'])
                        cond5 = df_filtered['P'] > df_filtered['SMA50']
                        cond6 = df_filtered['P'] >= (df_filtered['Low52W'] * 1.30)
                        cond7 = df_filtered['P'] >= (df_filtered['High52W'] * 0.75)
                        c_buy = base_buy & cond1 & cond2 & cond3 & cond4 & cond5 & cond6 & cond7
                        
                        # Sell Logic - 50 SMA Breakdown
                        sell_c1 = df_filtered['P'] < df_filtered['SMA50']
                        sell_c2 = df_filtered['SMA50'] < df_filtered['SMA150']
                        c_sell = base_sell & sell_c1 & sell_c2
                        
                        icon_str = "📈 M-VCP"
                    elif strat == "📉 Strict VCP (Price & Vol Contraction)":
                        cond1 = (df_filtered['P'] > df_filtered['SMA150']) & (df_filtered['P'] > df_filtered['SMA200'])
                        cond2 = df_filtered['SMA150'] > df_filtered['SMA200']
                        cond3 = df_filtered['SMA200'] > df_filtered['SMA200_20D']
                        cond4 = (df_filtered['SMA50'] > df_filtered['SMA150']) & (df_filtered['SMA50'] > df_filtered['SMA200'])
                        cond5 = df_filtered['P'] > df_filtered['SMA50']
                        cond6 = df_filtered['P'] >= (df_filtered['Low52W'] * 1.30)
                        cond7 = df_filtered['P'] >= (df_filtered['High52W'] * 0.75)
                        vcp_cond = (df_filtered['VCP_Contract'] == True) & (df_filtered['VCP_Vol_Dry'] == True)
                        c_buy = base_buy & cond1 & cond2 & cond3 & cond4 & cond5 & cond6 & cond7 & vcp_cond
                        c_sell = pd.Series(False, index=df_filtered.index)
                        icon_str = "📉 VCP"
                    elif strat == "🌅 15-Min ORB (Opening Range Breakout)":
                        c_buy = base_buy & (df_filtered['ORB_Tag'] == "ORB_BUY") & (df_filtered['VolX'] >= 1.2)
                        c_sell = base_sell & (df_filtered['ORB_Tag'] == "ORB_SELL") & (df_filtered['VolX'] >= 1.2)
                        icon_str = "🌅 ORB"
    
                    # 1. GAP & GO (OPEN = LOW) STRATEGY
                    elif strat == "🚀 Gap & Go (Open = Low)":
                        open_low_match = (df_filtered['O'] - df_filtered['L']) <= (df_filtered['P'] * 0.002)
                        gap_up = df_filtered['O'] > df_filtered['Prev_C']
                        high_vol = df_filtered['VolX'] >= 1.5
                        c_buy = base_buy & open_low_match & gap_up & high_vol & (df_filtered['Day_C'] > 0.5)
                        c_sell = base_sell & ((df_filtered['H'] - df_filtered['O']) <= (df_filtered['P'] * 0.002)) & (df_filtered['O'] < df_filtered['Prev_C']) & high_vol & (df_filtered['Day_C'] < -0.5)
                        icon_str = "🚀 Gap&Go"
    
                    # 2. PREVIOUS DAY HIGH/LOW BREAKOUT
                    elif strat == "💥 PDH / PDL Breakout":
                        pdh_break = (df_filtered['P'] > df_filtered['Prev_H']) & (df_filtered['P'] > df_filtered['VWAP'])
                        pdl_break = (df_filtered['P'] < df_filtered['Prev_L']) & (df_filtered['P'] < df_filtered['VWAP'])
                        vol_confirm = df_filtered['VolX'] >= 2.0
                        c_buy = base_buy & pdh_break & vol_confirm
                        c_sell = base_sell & pdl_break & vol_confirm
                        icon_str = "💥 PD Break"
    
                    # 3. VWAP BOUNCE (PULLBACK)
                    elif strat == "🧲 VWAP Bounce (Low Risk Entry)":
                        near_vwap_buy = (df_filtered['P'] > df_filtered['VWAP']) & (df_filtered['P'] <= (df_filtered['VWAP'] * 1.003)) & (df_filtered['L'] <= (df_filtered['VWAP'] * 1.001))
                        near_vwap_sell = (df_filtered['P'] < df_filtered['VWAP']) & (df_filtered['P'] >= (df_filtered['VWAP'] * 0.997)) & (df_filtered['H'] >= (df_filtered['VWAP'] * 0.999))
                        overall_trend_up = df_filtered['Day_C'] > 1.0
                        overall_trend_dn = df_filtered['Day_C'] < -1.0
                        c_buy = base_buy & near_vwap_buy & overall_trend_up & (df_filtered['VolX'] > 1.0)
                        c_sell = base_sell & near_vwap_sell & overall_trend_dn & (df_filtered['VolX'] > 1.0)
                        icon_str = "🧲 VWAP Bounce"
    
                    # 4. TRENDING DAY (NARROW CPR + ORB)
                    elif strat == "🎯 Narrow CPR Trending Day":
                        c_buy = base_buy & (df_filtered['Narrow_CPR'] == True) & (df_filtered['ORB_Tag'] == "ORB_BUY") & (df_filtered['VolX'] >= 1.2)
                        c_sell = base_sell & (df_filtered['Narrow_CPR'] == True) & (df_filtered['ORB_Tag'] == "ORB_SELL") & (df_filtered['VolX'] >= 1.2)
                        icon_str = "🎯 CPR Trend"
                    top_buy = df_filtered[c_buy].sort_values(by=['VolX', 'Day_C'], ascending=[False, False]).head(5).copy()
                    if not top_buy.empty: top_buy['Strategy_Icon'] = f"{icon_str} BUY"
                    top_sell = df_filtered[c_sell].sort_values(by=['VolX', 'Day_C'], ascending=[False, True]).head(5).copy()
                    if not top_sell.empty: top_sell['Strategy_Icon'] = f"{icon_str} SELL"
                    
                    all_dfs.extend([top_buy, top_sell])
                    
                if all_dfs: 
                    df_filtered = pd.concat(all_dfs).drop_duplicates(subset=['Fetch_T'])
                else: 
                    df_filtered = pd.DataFrame(columns=df_filtered.columns)
                
                if not df_filtered.empty:
                    is_buy = df_filtered['Strategy_Icon'].str.contains('BUY|VCP', na=False)
                    is_minervini = df_filtered['Strategy_Icon'].str.contains('VCP', na=False)
                    atr_val = df_filtered.get('ATR', df_filtered['P'] * 0.02)
                    risk_amt = np.where(is_minervini, df_filtered['P'] * 0.05, atr_val * 1.5)
                    
                    df_filtered['SL'] = np.where(is_buy, round(df_filtered['P'] - risk_amt, 2), round(df_filtered['P'] + risk_amt, 2))
                    tp1_mult = np.where(is_minervini, 2.0, 1.0)
                    tp2_mult = np.where(is_minervini, 3.0, 2.0)
                    df_filtered['T1'] = np.where(is_buy, round(df_filtered['P'] + (risk_amt * tp1_mult), 2), round(df_filtered['P'] - (risk_amt * tp1_mult), 2))
                    df_filtered['T2'] = np.where(is_buy, round(df_filtered['P'] + (risk_amt * tp2_mult), 2), round(df_filtered['P'] - (risk_amt * tp2_mult), 2))
            
            if 'Sector_Bonus' not in df_filtered.columns: df_filtered['Sector_Bonus'] = 0
            
            # 🔥 Intraday Pullback (DH) & Bounce (DL) Calculations
            df_filtered['Intra_DH_PB'] = np.where(df_filtered['H'] > 0, ((df_filtered['H'] - df_filtered['P']) / df_filtered['H']) * 100, 0.0)
            df_filtered['Intra_DL_Bounce'] = np.where(df_filtered['L'] > 0, ((df_filtered['P'] - df_filtered['L']) / df_filtered['L']) * 100, 0.0)
    
            if sort_mode == "Intraday Pullback Max 📉 (DH / DL)":
                # SELL / Weak stocks ni gurtinche mask
                if df_filtered['Strategy_Icon'].str.contains('🔴|SELL|DOWN|Stage 4|🩸', na=False).any():
                    is_sell_mask = df_filtered['Strategy_Icon'].str.contains('🔴|SELL|DOWN|Stage 4|🩸', na=False)
                else:
                    is_sell_mask = df_filtered['Day_C'] < 0
    
                # BUY side: Day high nundi ekkuva padinavi (DH Pullback Max) top loki vastayi
                buy_subset = df_filtered[~is_sell_mask].sort_values(by=['Intra_DH_PB', 'S'], ascending=[False, False])
                
                # SELL side: Day low nundi ekkuva bounce ayinavi (DL Bounce Max) top loki vastayi
                sell_subset = df_filtered[is_sell_mask].sort_values(by=['Intra_DL_Bounce', 'S'], ascending=[False, False])
                
                df_stocks_display = pd.concat([buy_subset, sell_subset])
    
            elif sort_mode == "52W Pullback Max 📉 (Deep Discount)":
                df_stocks_display = df_filtered.sort_values(by=['Pullback_52W', 'S'], ascending=[False, False])
            elif sort_mode == "% Change Up 🟢": 
                df_stocks_display = df_filtered.sort_values(by=sort_key, ascending=False)
            elif sort_mode == "% Change Down 🔴": 
                df_stocks_display = df_filtered.sort_values(by=sort_key, ascending=True)
            elif sort_mode == "Sector Trending First 📊":
                if "AI_Prob" in df_filtered.columns: df_stocks_display = df_filtered.sort_values(by=['Sector_Bonus', 'AI_Prob', 'VolX'], ascending=[False, False, False])
                else: df_stocks_display = df_filtered.sort_values(by=['Sector_Bonus', 'S', 'VolX'], ascending=[False, False, False])
            elif sort_mode == "🤖 AI Prob Up ⬆️":
                if "AI_Prob" in df_filtered.columns: df_stocks_display = df_filtered.sort_values(by=['AI_Prob', 'VolX', sort_key], ascending=[False, False, False])
                else: df_stocks_display = df_filtered.sort_values(by=['S', 'VolX', sort_key], ascending=[False, False, False])
            elif sort_mode == "Score Wise Up ⭐": 
                df_stocks_display = pd.concat([
                    df_filtered[df_filtered[sort_key] >= 0].sort_values(by=['S', 'VolX', sort_key], ascending=[False, False, False]), 
                    df_filtered[df_filtered[sort_key] < 0].sort_values(by=['S', 'VolX', sort_key], ascending=[False, False, True])
                ])
            elif sort_mode == "Score Wise Down ⬇️": 
                df_stocks_display = pd.concat([
                    df_filtered[df_filtered[sort_key] < 0].sort_values(by=['S', 'VolX', sort_key], ascending=[False, False, True]), 
                    df_filtered[df_filtered[sort_key] >= 0].sort_values(by=['S', 'VolX', sort_key], ascending=[False, False, False])
                ])
            else:
                if "AI Predictions" in watchlist_mode: df_stocks_display = df_filtered.sort_values(by=['AI_Prob', 'VolX'], ascending=[False, False])
                else: df_stocks_display = df_filtered.sort_values(by=['S', 'VolX', sort_key], ascending=[False, False, False])
                
        # ============ FUNDAMENTALS ============
        if watchlist_mode == "Fundamentals 🏢":
            st.markdown(f"<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#d29922;'>🏢 Core Fundamentals ({fund_filter})</div>", unsafe_allow_html=True)
            
            fund_tickers = df_stocks_display['Fetch_T'].tolist()[:50] if not df_stocks_display.empty else [f"{s}.NS" for s in NIFTY_50[:50]]
            df_fund = fetch_fundamentals_data(fund_tickers)
            if not df_fund.empty:
                if fund_filter == "🦅 Warren Buffett Value Stocks":
                    df_fund = df_fund[
                        (df_fund['ROE %'] > 15) &
                        (df_fund['Debt/Equity'] < 0.5) &
                        (df_fund['P/E Ratio'] > 0) &
                        (df_fund['P/E Ratio'] < 25)
                    ]
                
                html_fund = f'<table class="term-table"><thead><tr><th colspan="10" class="term-head-fund" style="background-color: #d29922; color: #161b22;">📊 FUNDAMENTAL & TECHNICAL METRICS</th></tr><tr><th style="text-align:left;">STOCK</th><th>SECTOR</th><th>LTP (₹)</th><th>TECH SCORE</th><th>MKT CAP (Cr)</th><th>P/E</th><th>ROE %</th><th>D/E Ratio</th><th>DIV YIELD</th><th>52W HIGH</th></tr></thead><tbody>'
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
            st.markdown("<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#00BFFF;'>📈 Mutual Funds Screener (Live Morningstar Data)</div>", unsafe_allow_html=True)
            
            c1, c2 = st.columns(2)
            with c1:
                mf_categories = ["All Categories"] + list(MUTUAL_FUNDS.keys())
                selected_mf_cat = st.selectbox("Filter by Category", mf_categories)
            with c2:
                sort_period = st.selectbox("Rank By Performance", ["1Y (%)", "3Y CAGR (%)", "5Y CAGR (%)"], index=2)
                
            with st.spinner("Fetching Live Data from Morningstar..."):
                df_mf_raw = fetch_mf_performance()
                
            if not df_mf_raw.empty:
                df_mf_raw['Sort_Key'] = pd.to_numeric(df_mf_raw[sort_period].replace('N/A', -999))
                df_mf_raw = df_mf_raw.sort_values(by='Sort_Key', ascending=False)
                
                if selected_mf_cat != "All Categories":
                    df_mf_data = df_mf_raw[df_mf_raw['Category'] == selected_mf_cat]
                else:
                    df_mf_data = df_mf_raw
                    
                df_mf_data = df_mf_data.drop(columns=['Sort_Key'], errors='ignore')
                st.markdown(render_mf_table(df_mf_data), unsafe_allow_html=True)
                st.markdown(f"<p style='font-size:11px; color:#888;'><i>*Note: Funds are auto-ranked based on <b>{sort_period}</b>. Returns > 20% are highlighted in Bright Green. Data Source: Morningstar.</i></p>", unsafe_allow_html=True)
            else:
                st.error("Failed to fetch Mutual Fund data from Morningstar.") 
                
        elif watchlist_mode == "Month Effect Advantage 📅":
            st.markdown("<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#00BFFF;'>📅 Month Effect Advantage (First 10 Days vs Rest)</div>", unsafe_allow_html=True)
            st.markdown("<p style='font-size:13px; color:#c9d1d9;'>Top 200 stocks gata 5 yellalo prati nela <b>modati 10 rojullo</b> kachitamga momentum iche best stocks.</p>", unsafe_allow_html=True)
    
            def analyze_month_effect(tickers, years=5):
                results = []
                end_date = datetime.now()
                start_date = end_date - pd.DateOffset(years=years)
                chunk_size = 40
                data_frames = []
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for i in range(0, len(tickers), chunk_size):
                    chunk = tickers[i : i + chunk_size]
                    status_text.write(f"📥 Data download avuthondi... ({min(i+chunk_size, len(tickers))} / {len(tickers)} stocks)")
                    temp_data = yf.download(chunk, start=start_date, end=end_date, progress=False, group_by='ticker', threads=False)
                    if not temp_data.empty:
                        if len(chunk) == 1:
                            temp_data.columns = pd.MultiIndex.from_product([chunk, temp_data.columns])
                        data_frames.append(temp_data)
                    progress_bar.progress(min((i + chunk_size) / len(tickers), 1.0))
                    
                status_text.write("⚙️ Data ni analyze chesthondi... Dayachesi vechi undandi...")
                
                if not data_frames:
                    progress_bar.empty()
                    status_text.empty()
                    return pd.DataFrame()
    
                data = pd.concat(data_frames, axis=1)
    
                for tkr in tickers:
                    try:
                        df_t = data[tkr] if len(tickers) > 1 else data
                        if df_t.empty: continue
                        df_t = df_t.dropna(subset=['Close'])
                        df_t['Month'] = df_t.index.month
                        df_t['Year'] = df_t.index.year
                        df_t['Day'] = df_t.index.day
    
                        monthly_groups = df_t.groupby(['Year', 'Month'])
                        first_10_returns = []
                        rest_returns = []
                        losing_returns = []
                        win_count = 0
                        total_months = 0
    
                        for (y, m), group in monthly_groups:
                            if len(group) < 5: continue
                            first_10 = group[group['Day'] <= 10]
                            rest = group[group['Day'] > 10]
    
                            if not first_10.empty and not rest.empty:
                                f10_ret = (first_10['Close'].iloc[-1] - first_10['Open'].iloc[0]) / first_10['Open'].iloc[0] * 100
                                r_ret = (rest['Close'].iloc[-1] - rest['Open'].iloc[0]) / rest['Open'].iloc[0] * 100
                                first_10_returns.append(f10_ret)
                                rest_returns.append(r_ret)
                                if f10_ret > 0: win_count += 1
                                if f10_ret < 0: losing_returns.append(f10_ret)
                                total_months += 1
    
                        if total_months > 0:
                            avg_f10 = sum(first_10_returns) / len(first_10_returns)
                            avg_rest = sum(rest_returns) / len(rest_returns)
                            avg_loss = sum(losing_returns) / len(losing_returns) if losing_returns else 0.0
                            win_rate = (win_count / total_months) * 100
    
                            results.append({
                                "Stock": tkr.replace(".NS", ""),
                                "Win Rate (1st 10 Days) %": round(win_rate, 2),
                                "Avg 1st-10th Return (%)": round(avg_f10, 2),
                                "Avg Loss on Fail (%)": round(avg_loss, 2), 
                                "Avg Rest Return (%)": round(avg_rest, 2),
                                "Total Months": total_months
                            })
                    except Exception:
                        pass
                
                progress_bar.empty()
                status_text.empty()
                return pd.DataFrame(results)
    
            scan_list = st.radio("Select Universe to Scan:", ["Top 200 (Nifty + Midcap)", "NIFTY 50 Only", "Custom Stock"], horizontal=True)
    
            if scan_list == "Custom Stock":
                cust_stock = st.selectbox("Select Stock", all_names if all_names else NIFTY_50)
                tkr_list = [f"{cust_stock}.NS"]
            elif scan_list == "NIFTY 50 Only":
                tkr_list = [f"{s}.NS" for s in NIFTY_50]
            else:
                tkr_list = [f"{s}.NS" for s in NIFTY_50 + MIDCAP_150]
    
            if st.button("🚀 Run 5-Year Month Effect Analysis", width="stretch"):
                me_df = analyze_month_effect(tkr_list)
                
                if not me_df.empty:
                    strict_condition = (
                        (me_df["Win Rate (1st 10 Days) %"] >= 55) &
                        (me_df["Avg 1st-10th Return (%)"] > 0.5) &
                        (me_df["Avg 1st-10th Return (%)"] > me_df["Avg Rest Return (%)"]) &
                        (me_df["Avg Loss on Fail (%)"] >= -6.0)
                    )
                    me_df = me_df.sort_values(by=["Win Rate (1st 10 Days) %", "Avg 1st-10th Return (%)"], ascending=[False, False])
    
                    st.markdown("### 🏆 Top 10 Best Stocks (High Probability Swing)")
                    st.markdown("<p style='font-size:12px; color:#3fb950;'>Kevalam <b>kaneesam 55% Win Rate mariyu overall positive returns unde stocks</b>.</p>", unsafe_allow_html=True)
                    
                    top_10 = me_df[strict_condition].head(10)
                    if not top_10.empty:
                        st.dataframe(top_10, use_container_width=True, hide_index=True)
                    else:
                        st.info("No stocks matched the strict consistency criteria.")
    
                    st.markdown("### 📊 Full Data Analysis")
                    st.dataframe(me_df, use_container_width=True, hide_index=True)
            
        elif watchlist_mode == "My Portfolio 💼" and view_mode == "Heat Map":
            sc1, sc2 = st.columns([0.7, 0.3])
            with sc2: port_sort = st.selectbox("↕️ Sort Portfolio:", ["Default", "Day P&L ⬆️", "Day P&L ⬇️", "Total P&L ⬆️", "Total P&L ⬇️", "P&L % ⬆️", "P&L % ⬇️"], label_visibility="collapsed")
            
            st.markdown(render_portfolio_table(df_port_saved, df_all_stocks, weekly_trends, port_sort), unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)
            
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
                                avg_price = ((old_qty * old_price) + (new_qty * new_price)) / total_qty
                                base_price = avg_price
                            else:
                                total_qty = new_qty
                                base_price = new_price
    
                            calc_sl = new_sl if new_sl > 0 else round(base_price * 0.95, 2)
                            calc_t1 = new_t1 if new_t1 > 0 else round(base_price * 1.10, 2)
                            calc_t2 = new_t2 if new_t2 > 0 else round(base_price * 1.15, 2)
    
                            if new_sym in df_port_saved['Symbol'].values: 
                                df_port_saved.loc[df_port_saved['Symbol'] == new_sym, ['Buy_Price', 'Quantity', 'Date', 'SL', 'T1', 'T2']] = [round(avg_price, 2), total_qty, new_date_str, calc_sl, calc_t1, calc_t2]
                                st.success(f"✅ {new_sym} యావరేజ్ చేయబడింది! (New Avg: ₹{round(avg_price, 2)}, SL: {calc_sl})")
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
                            new_closed_row = pd.DataFrame({"Sell_Date": [sell_date_str], "Symbol": [sell_sym], "Quantity": [sell_qty], "Buy_Price": [buy_price], "Sell_Price": [sell_price], "PnL_Rs": [pnl_rs], "PnL_Pct": [pnl_pct]})
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
                        st.markdown("<hr style='border-color:#30363d; margin-top:15px;'>", unsafe_allow_html=True)
                        st.markdown("<p style='font-size:12px; color:#ffd700;'>✏️ <b>Edit / Delete Closed Trades:</b> (రో ని సెలెక్ట్ చేసి Delete నొక్కండి, తర్వాత Save నొక్కండి)</p>", unsafe_allow_html=True)
                        
                        edited_closed_df = st.data_editor(
                            df_closed_view, 
                            width="stretch", 
                            hide_index=True,
                            num_rows="dynamic",
                            key="tradebook_editor"
                        )
                        
                        if st.button("💾 Save Trade Book Changes", width="stretch", key="save_tb"): 
                            save_closed_trades(edited_closed_df)
                            st.success("✅ Trade Book అప్డేట్ అయ్యింది!")
                            time.sleep(1)
                            st.rerun()
                    
        elif view_mode == "Heat Map" and watchlist_mode != "Fundamentals 🏢":
            map_sort_key = "W_C" if chart_timeframe == "Weekly Chart" else "Day_C"
    
            if not df_indices.empty and watchlist_mode != "Commodity 🛢️":
                html_idx = '<div class="heatmap-grid">'
                for _, row in df_indices.iterrows():
                    pct_val = float(row.get('W_C', row['Day_C'])) if chart_timeframe == "Weekly Chart" else float(row['Day_C'])
                    bg = "bear-card" if (row['T'] == "INDIA VIX" and pct_val > 0) else ("bull-card" if pct_val > 0 else "neut-card")
                    if row['T'] != "INDIA VIX" and pct_val < 0: bg = "bear-card"
                    html_idx += f'<a href="https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(row["Fetch_T"])}" target="_blank" class="stock-card {bg}"><div class="t-score">IDX</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{"+" if pct_val>0 else ""}{pct_val:.2f}%</div></a>'
                st.markdown(html_idx + '</div><hr class="custom-hr">', unsafe_allow_html=True)
            
            if not df_sectors.empty and watchlist_mode != "Commodity 🛢️":
                df_sectors = df_sectors.sort_values(by=map_sort_key, ascending=False)
                html_sec = '<div class="heatmap-grid">'
                for _, row in df_sectors.iterrows():
                    pct_val = float(row.get('W_C', row['Day_C'])) if chart_timeframe == "Weekly Chart" else float(row['Day_C'])
                    bg = "bull-card" if pct_val > 0 else ("bear-card" if pct_val < 0 else "neut-card")
                    html_sec += f'<a href="https://in.tradingview.com/chart/?symbol={TV_SECTOR_URL.get(row["Fetch_T"], "")}" target="_blank" class="stock-card {bg}"><div class="t-score" style="color:#00BFFF;">SEC</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{"+" if pct_val>0 else ""}{pct_val:.2f}%</div></a>'
                st.markdown(html_sec + '</div><hr class="custom-hr">', unsafe_allow_html=True)
    
            if not df_stocks_display.empty:
                if watchlist_mode in ["Swing Trading 📈", "Legendary Strategy 🏆", "Day Trading Stocks 🚀"] or "AI Predictions" in watchlist_mode:
                    # 🔴 లేదా SELL ఉన్నవి పక్కాగా సెల్ లోకి వెళ్తాయి
                    df_sell = df_stocks_display[df_stocks_display['Strategy_Icon'].str.contains('🔴|SELL|DOWN|Stage 4|🩸', na=False)]
                    # 🔴 లేనివి మరియు 🟢 లేదా BUY ఉన్నవి మాత్రమే బై లోకి వస్తాయి
                    df_buy = df_stocks_display[(~df_stocks_display['Strategy_Icon'].str.contains('🔴|SELL|DOWN|Stage 4|🩸', na=False)) & (df_stocks_display['Strategy_Icon'].str.contains('🟢|📈|🔥|🚀|BUY|UP|Stage 2', na=False))]
                else:
                    df_buy = df_stocks_display[df_stocks_display[sort_key] >= 0]
                    df_sell = df_stocks_display[df_stocks_display[sort_key] < 0]
    
                def render_heatmap_section(df_sec, title, title_color):
                    st.markdown(f"<div style='font-size:16px; font-weight:bold; margin: 15px 0 5px 0; color:{title_color};'>{title}</div>", unsafe_allow_html=True)
                    html_stk = '<div class="heatmap-grid">'
                    for _, row in df_sec.iterrows():
                        pct_val = float(row.get('W_C', row['Day_C'])) if chart_timeframe == "Weekly Chart" else float(row['Day_C'])
                        bg = "bull-card" if pct_val > 0 else ("bear-card" if pct_val < 0 else "neut-card")
                        
                        special_icon = f"⭐{int(row['S'])}"
                        if "AI Predictions" in watchlist_mode:
                            strat_name = str(row.get('Strategy_Icon', '')).strip()
                            if strat_name and strat_name != "Neutral":
                                # పెద్ద పేర్లను చిన్న బ్యాడ్జ్ గా మార్చడం (కార్డ్ లో సరిగ్గా పట్టడానికి)
                                clean_strat = strat_name.replace(" BUY", "").replace(" SELL", "").replace("AI PREDICTS: UP", "🚀 AI").replace("AI PREDICTS: DOWN", "🩸 AI")
                                special_icon = clean_strat
                            elif sort_mode == "🤖 AI Prob Up ⬆️":
                                special_icon = f"🤖{int(row.get('AI_Prob', 0))}%"
                            else:
                                special_icon = f"⭐{int(row['S'])}"
                        elif watchlist_mode == "Swing Trading 📈": 
                            strat_name = str(row.get('Strategy_Icon', ''))
                            if strat_name != "": special_icon = strat_name
                            else: special_icon = "🌟" if row.get('Is_W_Pullback', False) else "🚀"
                        elif watchlist_mode in ["Day Trading Stocks 🚀", "High Score Stocks 🔥"]: 
                            strat_name = str(row.get('Strategy_Icon', '🚀'))
                            if 'BUY' in strat_name: special_icon = "🟢 BUY"
                            elif 'SELL' in strat_name: special_icon = "🔴 SELL"
                            elif strat_name != "": special_icon = strat_name
                            else: special_icon = "🚀"
                                                
                        elif watchlist_mode == "Commodity 🛢️": special_icon = "🛢️"
                            
                        # 52W Pullback పర్సంటేజ్ హీట్ మ్యాప్ లో చూపించడానికి
                        pb_val = row.get('Pullback_52W', 0)
                        pb_html = f" | <span style='color:#FFD700; font-size:11px;'>📉-{pb_val:.0f}%</span>" if pb_val >= 3.0 else ""
                        
                        html_stk += f'<a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank" class="stock-card {bg}"><div class="t-score">{special_icon}</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{"+" if pct_val>0 else ""}{pct_val:.2f}%{pb_html}</div></a>'
                    
                if "AI Predictions" in watchlist_mode:
                    fno_buy = df_buy[df_buy['T'].isin(NIFTY_50 + FNO_STOCKS)]
                    fno_sell = df_sell[df_sell['T'].isin(NIFTY_50 + FNO_STOCKS)]
                    if not fno_buy.empty: render_heatmap_section(fno_buy, "🟢 POSITIVE / BUY (F&O & Nifty 50)", "#3fb950")
                    if not fno_sell.empty: render_heatmap_section(fno_sell, "🔴 NEGATIVE / SELL (F&O & Nifty 50)", "#f85149")
                    
                    mid_buy = df_buy[df_buy['T'].isin(MIDCAP_150)]
                    mid_sell = df_sell[df_sell['T'].isin(MIDCAP_150)]
                    if not mid_buy.empty: render_heatmap_section(mid_buy, "🟢 POSITIVE / BUY (AI Mid Cap)", "#3fb950")
                    if not mid_sell.empty: render_heatmap_section(mid_sell, "🔴 NEGATIVE / SELL (AI Mid Cap)", "#f85149")
                    
                    small_buy = df_buy[df_buy['T'].isin(SMALLCAP_250)]
                    small_sell = df_sell[df_sell['T'].isin(SMALLCAP_250)]
                    if not small_buy.empty: render_heatmap_section(small_buy, "🟢 POSITIVE / BUY (AI Small Cap)", "#3fb950")
                    if not small_sell.empty: render_heatmap_section(small_sell, "🔴 NEGATIVE / SELL (AI Small Cap)", "#f85149")
                else:
                    if not df_buy.empty: render_heatmap_section(df_buy, f"🟢 POSITIVE / BUY ({watchlist_mode})", "#3fb950")
                    if not df_sell.empty: render_heatmap_section(df_sell, f"🔴 NEGATIVE / SELL ({watchlist_mode})", "#f85149")
                
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
                    
                    
                elif watchlist_mode in ["High Score Stocks 🔥", "Day Trading Stocks 🚀"]:
                    with st.expander("🔥 View Day Trading Radar (Ranked Table)", expanded=True): st.markdown(render_highscore_terminal_table(df_stocks_display), unsafe_allow_html=True)
                elif watchlist_mode != "Commodity 🛢️":
                    with st.expander("🎯 View Trading Levels (Targets & Stop Loss)", expanded=True): st.markdown(render_levels_table(df_stocks_display), unsafe_allow_html=True)
    
            
            else: st.info("No items found.")
                
        else: 
            weekly_charts = {}
            daily_charts = {}
            
            if chart_timeframe in ["Weekly Chart", "Daily Chart"]:
                display_tkrs = []
                if search_stock != "-- None --" and not df[df['T'] == search_stock].empty: 
                    display_tkrs.append(df[df['T'] == search_stock]['Fetch_T'].iloc[0])
                if watchlist_mode not in ["Terminal Tables 🗃️", "My Portfolio 💼", "Commodity 🛢️"]:
                    display_tkrs.extend(df_indices['Fetch_T'].tolist())
                    display_tkrs.extend(df_sectors['Fetch_T'].tolist())
                display_tkrs.extend(st.session_state.pinned_stocks)
                display_tkrs.extend(df_stocks_display['Fetch_T'].head(30).tolist())
                display_tkrs = list(set(display_tkrs)) 
                
                if display_tkrs:
                    hist_data = fetch_historical_charts_data(display_tkrs, chart_timeframe)
                    
                    for sym in display_tkrs:
                        try:
                            df_h = hist_data[sym] if isinstance(hist_data.columns, pd.MultiIndex) else hist_data
                            df_h = df_h.dropna(subset=['Close']).copy()
                            if not df_h.empty:
                                if chart_timeframe == "Weekly Chart":
                                    df_h['SMA_10'] = df_h['Close'].rolling(window=10).mean()
                                    df_h['SMA_40'] = df_h['Close'].rolling(window=40).mean()
                                    weekly_charts[sym] = df_h
                                elif chart_timeframe == "Daily Chart":
                                    df_h['SMA_50'] = df_h['Close'].rolling(window=50).mean()
                                    df_h['SMA_150'] = df_h['Close'].rolling(window=150).mean()
                                    df_h['SMA_200'] = df_h['Close'].rolling(window=200).mean()
                                    daily_charts[sym] = df_h
                        except: pass
    
            if chart_timeframe == "Weekly Chart": chart_dict_to_use = weekly_charts
            elif chart_timeframe == "Daily Chart": chart_dict_to_use = daily_charts
            else: chart_dict_to_use = processed_charts
    
            if search_stock != "-- None --" and not df[df['T'] == search_stock].empty:
                render_chart_grid(pd.DataFrame([df[df['T'] == search_stock].iloc[0]]), show_pin_option=True, key_prefix="search", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)
                st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
            
            if watchlist_mode not in ["My Portfolio 💼", "Fundamentals 🏢", "Commodity 🛢️"]:
                st.markdown("<div style='font-size:16px; font-weight:bold; margin-bottom:5px; color:#00BFFF;'>🌍 Global & Main Indices</div>", unsafe_allow_html=True)
                render_chart_grid(df_indices, show_pin_option=False, key_prefix="idx", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)
                st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
                
                if not df_sectors.empty:
                    st.markdown("<div style='margin-top: 12px;'></div>", unsafe_allow_html=True)
                    show_sec_charts = st.toggle("📊 Show Sectoral Indices Charts", value=False)
                    st.markdown("<div style='margin-bottom: 2px;'></div>", unsafe_allow_html=True)
                    
                    if show_sec_charts:
                        render_chart_grid(df_sectors, show_pin_option=False, key_prefix="sec", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol, is_sector=True)
                        if st.session_state.get('active_sec'):
                            st.markdown(f"<div style='font-size:16px; font-weight:bold; margin-top:10px; margin-bottom:5px; color:#ffd700;'>🌟 Top 6 Active Movers in {st.session_state.active_sec}</div>", unsafe_allow_html=True)
                            sec_stock_names = TOP_SECTOR_STOCKS.get(st.session_state.active_sec, [])
                            sec_df = df_stocks[df_stocks['T'].isin(sec_stock_names)].copy()
                            
                            if not sec_df.empty:
                                sort_col = 'W_C' if chart_timeframe == "Weekly Chart" else 'Day_C'
                                sec_trend_row = df_sectors[df_sectors['T'] == st.session_state.active_sec]
                                is_sec_down = float(sec_trend_row[sort_col].iloc[0]) < 0 if not sec_trend_row.empty else False
                                if is_sec_down: sec_df = sec_df.sort_values(by=sort_col, ascending=True).head(6) 
                                else: sec_df = sec_df.sort_values(by=sort_col, ascending=False).head(6) 
                                render_chart_grid(sec_df, show_pin_option=True, key_prefix="sec_top6", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)
                    st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
    
            pinned_df = df[df['Fetch_T'].isin(st.session_state.pinned_stocks)].copy()
            unpinned_df = df_stocks_display[~df_stocks_display['Fetch_T'].isin(pinned_df['Fetch_T'].tolist())] if not df_stocks_display.empty else pd.DataFrame()
            
            if not pinned_df.empty:
                st.markdown("<div style='font-size:16px; font-weight:bold; margin-bottom:5px; color:#ffd700;'>📌 Pinned Priority Charts</div>", unsafe_allow_html=True)
                render_chart_grid(pinned_df, show_pin_option=True, key_prefix="pin", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)
                st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
            
            if not unpinned_df.empty and watchlist_mode != "Fundamentals 🏢":
                if "AI Predictions" in watchlist_mode:
                    df_buy_chart = unpinned_df[unpinned_df['Strategy_Icon'].str.contains('🟢|BUY|UP|VCP|Stage 2|Darvas', na=False)].head(12)
                    df_sell_chart = unpinned_df[unpinned_df['Strategy_Icon'].str.contains('🔴|SELL|DOWN|Stage 4', na=False)].head(12)
                    title_suffix = watchlist_mode.split('(')[-1].replace(')','')
                    
                    if not df_buy_chart.empty:
                        st.markdown(f"<div style='font-size:16px; font-weight:bold; margin-top:10px; margin-bottom:5px; color:#3fb950;'>🟢 POSITIVE / BUY ({title_suffix})</div>", unsafe_allow_html=True)
                        render_chart_grid(df_buy_chart, show_pin_option=True, key_prefix="ai_buy", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)
    
                    if not df_sell_chart.empty:
                        st.markdown(f"<div style='font-size:16px; font-weight:bold; margin-top:20px; margin-bottom:5px; color:#f85149;'>🔴 NEGATIVE / SELL ({title_suffix})</div>", unsafe_allow_html=True)
                        render_chart_grid(df_sell_chart, show_pin_option=True, key_prefix="ai_sell", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)
                    if unpinned_df.empty:
                        st.info("ℹ️ No stocks matched this strategy's strict criteria at the moment. (ఏ స్టాక్స్ ఈ కండిషన్స్ ని మ్యాచ్ చేయలేదు)")
                        
                elif watchlist_mode == "Swing Trading 📈":
                    df_buy_chart = unpinned_df[unpinned_df['Strategy_Icon'].str.contains('🟢|BUY|UP|VCP|Stage 2|Darvas', na=False)].head(12)
                    df_sell_chart = unpinned_df[unpinned_df['Strategy_Icon'].str.contains('🔴|SELL|DOWN|Stage 4', na=False)].head(12)
                    
                    if not df_buy_chart.empty:
                        st.markdown(f"<div style='font-size:16px; font-weight:bold; margin-top:10px; margin-bottom:5px; color:#3fb950;'>🟢 POSITIVE / BUY (Swing Trading)</div>", unsafe_allow_html=True)
                        render_chart_grid(df_buy_chart, show_pin_option=True, key_prefix="swing_buy", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)
    
                    if not df_sell_chart.empty:
                        st.markdown(f"<div style='font-size:16px; font-weight:bold; margin-top:20px; margin-bottom:5px; color:#f85149;'>🔴 NEGATIVE / SELL (Swing Trading)</div>", unsafe_allow_html=True)
                        render_chart_grid(df_sell_chart, show_pin_option=True, key_prefix="swing_sell", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)
    
                elif watchlist_mode == "Day Trading Stocks 🚀":
                    df_buy_chart = unpinned_df[unpinned_df['Strategy_Icon'].str.contains('BUY', na=False)].head(12)
                    df_sell_chart = unpinned_df[unpinned_df['Strategy_Icon'].str.contains('SELL', na=False)].head(12)
                    
                    if not df_buy_chart.empty:
                        st.markdown(f"<div style='font-size:16px; font-weight:bold; margin-top:10px; margin-bottom:5px; color:#3fb950;'>🟢 POSITIVE / BUY ({watchlist_mode})</div>", unsafe_allow_html=True)
                        render_chart_grid(df_buy_chart, show_pin_option=True, key_prefix="day_buy", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)
    
                    if not df_sell_chart.empty:
                        st.markdown(f"<div style='font-size:16px; font-weight:bold; margin-top:20px; margin-bottom:5px; color:#f85149;'>🔴 NEGATIVE / SELL ({watchlist_mode})</div>", unsafe_allow_html=True)
                        render_chart_grid(df_sell_chart, show_pin_option=True, key_prefix="day_sell", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)
                        
                else:
                    if watchlist_mode == "Legendary Strategy 🏆":
                        df_sell_chart = unpinned_df[unpinned_df['Strategy_Icon'].str.contains('🔴|SELL|DOWN|Stage 4|🩸|52WL', na=False)].head(32)
                        df_buy_chart = unpinned_df[(~unpinned_df['Strategy_Icon'].str.contains('🔴|SELL|DOWN|Stage 4|🩸|52WL', na=False)) & (unpinned_df['Strategy_Icon'].str.contains('🟢|📈|🔥|🚀|BUY|UP|Stage 2|52WH', na=False))].head(32)
                    else:
                        df_buy_chart = unpinned_df[unpinned_df[sort_key] >= 0].head(40) # 12 nundi 40 ki
                        df_sell_chart = unpinned_df[unpinned_df[sort_key] < 0].head(40) # 12 nundi 40 ki
                    
                    if not df_buy_chart.empty:
                        st.markdown(f"<div style='font-size:16px; font-weight:bold; margin-top:10px; margin-bottom:5px; color:#3fb950;'>🟢 POSITIVE / BUY ({watchlist_mode})</div>", unsafe_allow_html=True)
                        render_chart_grid(df_buy_chart, show_pin_option=True, key_prefix="main_buy", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)
    
                    if not df_sell_chart.empty:
                        st.markdown(f"<div style='font-size:16px; font-weight:bold; margin-top:20px; margin-bottom:5px; color:#f85149;'>🔴 NEGATIVE / SELL ({watchlist_mode})</div>", unsafe_allow_html=True)
                        render_chart_grid(df_sell_chart, show_pin_option=True, key_prefix="main_sell", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)
    
                    # కింద ఉన్న రెండు లైన్లకు పైన ఉన్న if కండిషన్స్‌కి సరిపడా స్పేస్ ఇవ్వండి
                    if unpinned_df.empty:
                        st.info("ℹ️ No stocks matched this strategy's strict criteria at the moment. (ఏ స్టాక్స్ ఈ కండిషన్స్ ని మ్యాచ్ చేయలేదు)")
    # =========================================================
    # --- 📚 STRATEGY HELP GUIDE IN TELUGU (DYNAMIC) ---
    # =========================================================
    
    if "AI Predictions" in watchlist_mode or watchlist_mode == "Day Trading Stocks 🚀":
        st.markdown("<hr style='border-color:#30363d; margin-top:30px;'>", unsafe_allow_html=True)
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
        st.markdown("<hr style='border-color:#30363d; margin-top:30px;'>", unsafe_allow_html=True)
        with st.expander("📚 ఈ స్వింగ్ ట్రేడింగ్ స్ట్రాటజీలను ఎలా వాడాలి? (Telugu Swing Trading Guide)", expanded=False):
            st.markdown("""
            <div style='background-color:#161b22; padding:15px; border-radius:10px; border: 1px solid #30363d;'>
            <h4 style='color:#00BFFF; margin-top:0px;'>1. 👑 King Strategy (SMA Bounce)</h4>
            <ul style='color:#c9d1d9; font-size:14px;'>
                <li><b>ఎప్పుడు వాడాలి:</b> మంచి క్వాలిటీ స్టాక్స్ ని తక్కువ ధరకు (Buy on Dips) కొనేందుకు.</li>
                <li><b>లాజిక్ & ఎంట్రీ:</b> లాంగ్ టర్మ్ ట్రెండ్ (50 SMA > 150 SMA > 200 SMA) పైన ఉండాలి. స్టాక్ పడుతూ వచ్చి 50, 150 లేదా 200 SMA దగ్గర సపోర్ట్ తీసుకుని లైవ్ లో వాల్యూమ్ తో బౌన్స్ అయితే కొనాలి.</li>
            </ul>
    
            <h4 style='color:#3fb950; margin-top:15px;'>2. 📈 Minervini Trend Template & Strict VCP</h4>
            <ul style='color:#c9d1d9; font-size:14px;'>
                <li><b>ఎప్పుడు వాడాలి:</b> పక్కా అప్‌ట్రెండ్ లో కన్సాలిడేట్ అవుతున్న స్టాక్స్ పట్టుకునేందుకు (Stage 2).</li>
                <li><b>లాజిక్ & ఎంట్రీ:</b> 150 SMA & 200 SMA పైకి వంగి ఉండాలి (స్లోప్). ధర 52-వారాల హైకి 25% లోపలే ఉండాలి. స్ట్రిక్ట్ VCP అయితే గత కొన్ని రోజులుగా వాల్యూమ్ డ్రై అయిపోయి, బాక్స్ రేంజ్ బాగా సన్నబడి (Contraction) బ్రేక్అవుట్ కి రెడీగా ఉండాలి.</li>
            </ul>
    
            <h4 style='color:#FFD700; margin-top:15px;'>3. 📦 Nicolas Darvas & Modified Box</h4>
            <ul style='color:#c9d1d9; font-size:14px;'>
                <li><b>ఎప్పుడు వాడాలి:</b> 52-Week లేదా ఆల్-టైమ్ హై దగ్గర కొనేందుకు (Buy High, Sell Higher).</li>
                <li><b>లాజిక్ & ఎంట్రీ:</b> ధర 50 SMA పైన ఉండాలి. కొన్ని రోజులుగా ఒక బాక్స్ రేంజ్ లో ఉండి, ఈరోజు వాల్యూమ్ తో బాక్స్ పై భాగాన్ని (Box Top) బ్రేక్ చేస్తే కొనాలి. (మోడిఫైడ్ వెర్షన్ అయితే.. బ్రేక్అవుట్ కోసం వెయిట్ చేయకుండా 0.5% దగ్గరలో ఉండగానే అలర్ట్ ఇస్తుంది).</li>
            </ul>
    
            <h4 style='color:#FF8C00; margin-top:15px;'>4. 🧲 The 20-EMA Holy Grail Pullback</h4>
            <ul style='color:#c9d1d9; font-size:14px;'>
                <li><b>ఎప్పుడు వాడాలి:</b> వేగంగా పెరుగుతున్న స్టాక్స్ కొద్దిగా పుల్ బ్యాక్ (వెనక్కి తగ్గినప్పుడు) ఇచ్చినప్పుడు.</li>
                <li><b>లాజిక్ & ఎంట్రీ:</b> ట్రెండ్ బాగుండి (50 SMA > 150 SMA), రీసెంట్ గా పడి 10-Week EMA లేదా 20-Day EMA సపోర్ట్ ని టచ్ చేసి ఈరోజు బౌన్స్ ఇస్తుంటే క్యాచ్ చేయాలి. ఆ సపోర్ట్ కిందే స్టాప్ లాస్.</li>
            </ul>
    
            <h4 style='color:#d29922; margin-top:15px;'>5. 💥 Dan Zanger (Volume Explosion)</h4>
            <ul style='color:#c9d1d9; font-size:14px;'>
                <li><b>ఎప్పుడు వాడాలి:</b> సడెన్ గా ఆపరేటర్లు / ఇన్‌స్టిట్యూషన్స్ ఎంటర్ అయిన స్టాక్స్ పసిగట్టేందుకు.</li>
                <li><b>లాజిక్ & ఎంట్రీ:</b> వాల్యూమ్ డ్రై అయిపోయి ప్రశాంతంగా ఉన్న స్టాక్ లో, ఈరోజు సడెన్ గా 1.5 రెట్ల (1.5x) వాల్యూమ్ తో పేలి బాక్స్ బ్రేక్అవుట్ ఇస్తే వెంటనే ఎంటర్ అవ్వాలి.</li>
            </ul>
    
            <h4 style='color:#f85149; margin-top:15px;'>6. 📉 RSI(2) Mean Reversion (Larry Connors)</h4>
            <ul style='color:#c9d1d9; font-size:14px;'>
                <li><b>ఎప్పుడు వాడాలి:</b> ఫాస్ట్ స్వింగ్స్ కోసం (2-4 రోజులు ట్రేడ్).</li>
                <li><b>లాజిక్ & ఎంట్రీ:</b> 200 SMA పైన సేఫ్ ట్రెండ్ లో ఉన్న స్టాక్, ఏదైనా పానిక్ న్యూస్ వల్ల సడెన్ గా పడి 10-EMA కిందకి వస్తే దాన్ని ఫిల్టర్ చేస్తుంది. ఈరోజు మార్కెట్ ముగిసే టైంకి రికవర్ అయ్యి గ్రీన్ క్యాండిల్ వేస్తుంటే కొనాలి (Buy the Blood). మళ్ళీ ధర 5-Day SMA దాటగానే అమ్మేయాలి.</li>
            </ul>
            </div>
            """, unsafe_allow_html=True)
