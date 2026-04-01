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
import threading
import concurrent.futures
from dhanhq import dhanhq, marketfeed

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Market Heatmap", page_icon="📊", layout="wide")

# 🔥 ఎల్లో బాక్సులు, స్పిన్నర్లు పక్కాగా మాయం మరియు డిమ్ అవ్వకుండా ఆపుతుంది
st.markdown("""
    <style>
    div[data-testid="stNotification"] { display: none !important; }
    iframe[title="streamlit_autorefresh.st_autorefresh"] { display: none !important; }
    
    /* 🔥 రిఫ్రెష్ అయినప్పుడు చార్ట్స్ బ్రైట్‌నెస్ తగ్గిపోకుండా (డిమ్ అవ్వకుండా) పక్కాగా ఆపుతుంది */
    *[data-stale="true"] { 
        opacity: 1 !important; 
        filter: none !important; 
        transition: none !important; 
    }
    div[data-testid="stElementContainer"] {
        opacity: 1 !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- 2. GOOGLE SHEETS CONNECTION ---
@st.cache_resource(show_spinner=False)
def init_connection():
    creds_json = st.secrets["gcp_service_account"]
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
            save_portfolio(df)
        return df
    except:
        return pd.DataFrame(columns=['Symbol', 'Buy_Price', 'Quantity', 'Date', 'SL', 'T1', 'T2'])

@st.cache_data(ttl=300, show_spinner=False)
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
    load_portfolio.clear()

def save_closed_trades(df):
    trade_ws.clear()
    df = df.fillna("")
    trade_ws.update([df.columns.values.tolist()] + df.values.tolist())
    load_closed_trades.clear()

# --- 4. AUTO RUN & STATE MANAGEMENT ---
if 'pause_refresh' not in st.session_state:
    st.session_state.pause_refresh = False

if not st.session_state.pause_refresh:
    st_autorefresh(interval=5000, key="datarefresh")

if 'pinned_stocks' not in st.session_state:
    st.session_state.pinned_stocks = []
if 'custom_alerts' not in st.session_state:
    st.session_state.custom_alerts = {}
if 'active_sec' not in st.session_state:
    st.session_state.active_sec = None

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
# --- MEGA MUTUAL FUNDS DATABASE (Scanning Universe) ---
MUTUAL_FUNDS = {
    "LARGE CAP": {
        "SBI Bluechip Fund": "0P00005WLZ.BO",
        "ICICI Pru Bluechip Fund": "0P00005V15.BO",
        "Nippon India Large Cap": "0P00005WMT.BO",
        "HDFC Top 100 Fund": "0P00005V17.BO",
        "Axis Bluechip Fund": "0P0000XVUF.BO",
        "Mirae Asset Large Cap": "0P0000XVUK.BO",
        "Kotak Bluechip Fund": "0P00005WZV.BO",
        "DSP Top 100 Equity": "0P00005W5A.BO",
        "Tata Large Cap Fund": "0P00005WZJ.BO",
        "UTI Mastershare Unit": "0P00005WZT.BO",
        "Aditya Birla SL Frontline": "0P00005WZK.BO",
        "Edelweiss Large Cap": "0P00005WZQ.BO",
        "Franklin India Bluechip": "0P00005WZU.BO",
        "Canara Robeco Bluechip": "0P00005WZY.BO",
        "Invesco India Largecap": "0P00005WXX.BO"
    },
    "MID CAP": {
        "HDFC Mid-Cap Opportunities": "0P00005V23.BO",
        "Nippon India Growth Fund": "0P00005WLY.BO",
        "Kotak Emerging Equity": "0P00005WZW.BO",
        "DSP Midcap Fund": "0P00005W5C.BO",
        "Axis Midcap Fund": "0P0000XVUO.BO",
        "SBI Magnum Midcap": "0P00005WMX.BO",
        "Tata Mid Cap Growth": "0P00005WZL.BO",
        "UTI Mid Cap Fund": "0P00005WZM.BO",
        "Motilal Oswal Midcap": "0P0000XVW4.BO",
        "Edelweiss Mid Cap": "0P00005WZR.BO",
        "PGIM India Midcap": "0P0000YWA6.BO",
        "Invesco India Midcap": "0P00005WXY.BO",
        "Sundaram Mid Cap": "0P00005WXZ.BO"
    },
    "SMALL CAP": {
        "Nippon India Small Cap": "0P0000XVW5.BO",
        "SBI Small Cap Fund": "0P0000XW8F.BO",
        "Axis Small Cap Fund": "0P0000YWA5.BO",
        "Kotak Small Cap Fund": "0P00005WZX.BO",
        "DSP Small Cap Fund": "0P00005WZN.BO",
        "HDFC Small Cap Fund": "0P00005WZO.BO",
        "ICICI Pru Smallcap": "0P00005WZP.BO",
        "Tata Small Cap Fund": "0P0000XVU6.BO",
        "UTI Small Cap Fund": "0P00005WZS.BO",
        "Quant Small Cap Fund": "0P00005X00.BO",
        "Franklin India Smaller Cos": "0P00005WZV.BO",
        "Canara Robeco Small Cap": "0P0000XW8G.BO",
        "Edelweiss Small Cap": "0P0000YWA7.BO"
    },
    "FLEXI CAP / MULTI CAP": {
        "Parag Parikh Flexi Cap": "0P0000XVU7.BO",
        "HDFC Flexi Cap Fund": "0P00005V25.BO",
        "Kotak Flexicap Fund": "0P00005V19.BO",
        "UTI Flexi Cap Fund": "0P00005WZU.BO",
        "SBI Flexicap Fund": "0P00005WMA.BO",
        "DSP Flexi Cap Fund": "0P00005W5B.BO",
        "Axis Flexi Cap Fund": "0P0000XVUG.BO",
        "Nippon India Multi Cap": "0P00005WMB.BO",
        "Aditya Birla SL Flexi Cap": "0P00005WZC.BO",
        "Franklin India Flexi Cap": "0P00005WZD.BO"
    },
    "ELSS (TAX SAVER)": {
        "Mirae Asset Tax Saver": "0P0000XVUL.BO",
        "Axis Long Term Equity": "0P0000XVUP.BO",
        "DSP Tax Saver Fund": "0P00005W5E.BO",
        "SBI Long Term Equity": "0P00005WMC.BO",
        "HDFC TaxSaver": "0P00005V24.BO",
        "Kotak Tax Saver": "0P00005WZE.BO",
        "Nippon India Tax Saver": "0P00005WMD.BO",
        "Tata India Tax Savings": "0P00005WZF.BO"
    },
    "SECTORAL (IT / TECH)": {
        "ICICI Pru Technology Fund": "0P00005UZD.BO",
        "SBI Technology Opp Fund": "0P00005WMI.BO",
        "Tata Digital India Fund": "0P0000XVU6.BO",
        "Aditya Birla SL Digital": "0P00005WZK.BO",
        "Franklin India Technology": "0P00005WZU.BO"
    },
    "SECTORAL (PHARMA)": {
        "Nippon India Pharma Fund": "0P00005WMJ.BO",
        "SBI Healthcare Opp Fund": "0P00005WMG.BO",
        "Mirae Asset Healthcare": "0P0000YWA7.BO",
        "DSP Healthcare Fund": "0P0000YWA8.BO"
    },
    "SECTORAL (BANKING)": {
        "Nippon India Banking Fund": "0P00005WLX.BO",
        "ICICI Pru Banking & Fin": "0P00005V13.BO",
        "SBI Banking & Financial": "0P00005WMK.BO",
        "HDFC Banking & Financial": "0P0000YWA9.BO"
    }
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

MIDCAP_STOCKS = [
    "SUZLON", "IREDA", "RVNL", "NHPC", "SJVN", "KPITTECH", "COCHINSHIP", 
    "MAZDOCK", "RAILTEL", "CAMS", "TATAINVEST", "IRB", "J&KBANK", "UCOBANK", 
    "CENTRALBK", "MAHABANK", "SUVENPHAR", "NATCOPHARM", "AJANTPHARM", 
    "PRAJIND", "RENUKA", "EIDPARRY", "TRIVENI", "TEJASNET", "ITI", "MTNL", 
    "HEG", "GRAPHITE", "CEATLTD", "JKTYRE", "AMBER", "KAYNES", "CGPOWER", 
    "AIAENG", "SONACOMS", "OLECTRA", "JBMAUTO", "CHALET", "LEMONTREE", 
    "EASEMYTRIP", "PAYTM", "NYKAA", "PBFINTECH", "DELHIVERY"
]

SMALLCAP_STOCKS = [
    "KALYANKJIL", "TRIDENT", "HFCL", "HCC", "JPPOWER", "RPOWER", "SOUTHBANK",
    "YESBANK", "MAPMYINDIA", "RATEGAIN", "LATENTVIEW", "CEINFO", "DATAATTNS", 
    "KFINTECH", "PRINCEPIPE", "FINCABLES", "KEI", "RRKABEL", "HBLPOWER", 
    "ARE&M", "EQUITASBNK", "UJJIVANSFB", "CSBBANK", "DCBBANK", 
    "KARURVYSYA", "BANKINDIA", "UNIONBANK", "ZENSARTECH", 
    "NBCC", "MARKSANS", "JWL", "NETWEB", "TITAGARH", "TEXRAIL", "KIRLOSENG"
]
# --- DHAN API INITIALIZATION ---
@st.cache_resource
def init_dhan_client():
    try:
        c_id = st.secrets["dhan"]["client_id"]
        a_token = st.secrets["dhan"]["access_token"]
        return dhanhq(c_id, a_token)
    except Exception as e:
        return None

dhan = init_dhan_client()

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
if 'LIVE_PRICES' not in st.session_state:
    st.session_state.LIVE_PRICES = {}

@st.cache_resource
def start_live_ticker():
    try:
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
                    st.session_state.LIVE_PRICES[sym] = float(message['LTP'])
                    
        feed = marketfeed.DhanFeed(c_id, a_token, instruments, "v2", on_connect=on_connect, on_message=on_message)
        t = threading.Thread(target=feed.run_forever, daemon=True)
        t.start()
        return True
    except Exception as e:
        return False

start_live_ticker()

def get_minutes_passed():
    now = datetime.now()
    if now.weekday() >= 5 or now.time() > dt_time(15, 30): return 375
    open_time = now.replace(hour=9, minute=15, second=0)
    return min(375, max(1, int((now - open_time).total_seconds() / 60)))

# --- 5-MIN CACHED FETCH ENGINE (FAST PAGE LOADS) ---
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
                if df['Date'].dt.year.min() < 2010:
                    df['Date'] = pd.to_datetime(df['start_Time'] + 315513000, unit='s') + pd.Timedelta(hours=5, minutes=30)
                df.set_index('Date', inplace=True)
                df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
                for col in ['Open', 'High', 'Low', 'Close', 'Volume']: df[col] = pd.to_numeric(df[col], errors='coerce')
                df.index = df.index.tz_localize(None)
                return symbol, df
    except: pass
    return symbol, pd.DataFrame()

@st.cache_data(ttl=60, show_spinner=False)
def fetch_cached_5m_data(tkrs_list):
    dhan_tasks, yf_tkrs, results_dict = {}, [], {}
    for tkr in tkrs_list:
        clean_sym = tkr.replace(".NS", "")
        if clean_sym in sec_map and not any(idx in tkr for idx in ["^", "=F"]):
            dhan_tasks[tkr] = (clean_sym, sec_map[clean_sym])
        else:
            yf_tkrs.append(tkr)
            
    if dhan and dhan_tasks:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(fetch_single_dhan_5m, tkr, data[1]): tkr for tkr, data in dhan_tasks.items()}
            for future in concurrent.futures.as_completed(futures):
                tkr, df = future.result()
                if not df.empty: results_dict[tkr] = df
                else: yf_tkrs.append(tkr)

    if yf_tkrs:
        yf_data = yf.download(yf_tkrs, period="5d", interval="5m", progress=False, group_by='ticker', threads=10)
        if len(yf_tkrs) == 1:
            if not yf_data.empty: 
                yf_data.index = yf_data.index.tz_localize(None)
                results_dict[yf_tkrs[0]] = yf_data
        else:
            for tkr in yf_tkrs:
                if tkr in yf_data.columns.levels[0]:
                    df = yf_data[tkr].dropna(subset=['Close'])
                    if not df.empty:
                        df.index = df.index.tz_localize(None)
                        results_dict[tkr] = df
    valid_results = {k: v for k, v in results_dict.items() if not v.empty and len(v) > 0}
    if valid_results:
        return pd.concat(valid_results.values(), axis=1, keys=valid_results.keys())
    return pd.DataFrame()
# ==========================================
# 🔥 NEW: HISTORICAL CHARTS CACHE FUNCTION 🔥
# ==========================================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_historical_charts_data(tkrs, timeframe):
    if timeframe == "Weekly Chart":
        return yf.download(tkrs, period="2y", interval="1wk", progress=False, group_by='ticker', threads=20)
    elif timeframe == "Daily Chart":
        return yf.download(tkrs, period="1y", interval="1d", progress=False, group_by='ticker', threads=20)
    return pd.DataFrame()
# --- DAILY DATA FETCH ---
@st.cache_data(ttl=150, show_spinner=False)
def fetch_all_data(market_segment="F&O (Top 200) 🔵"):
    port_df = load_portfolio()
    port_stocks = [str(sym).upper().strip() for sym in port_df['Symbol'].tolist() if str(sym).strip() != ""]
    
    base_stocks = NIFTY_50.copy()
    if market_segment == "F&O (Top 200) 🔵":
        base_stocks += FNO_STOCKS
    elif market_segment == "Mid Cap 🟡":
        base_stocks += MIDCAP_STOCKS
    elif market_segment == "Small Cap 🟢":
        base_stocks += SMALLCAP_STOCKS
    else: # All Combined
        base_stocks += FNO_STOCKS + MIDCAP_STOCKS + SMALLCAP_STOCKS
        
    all_stocks = set(base_stocks + port_stocks)
    tkrs = list(INDICES_MAP.keys()) + list(SECTOR_INDICES_MAP.keys()) + list(COMMODITY_MAP.keys()) + [f"{t}.NS" for t in all_stocks if t]
    
    # 🔥 Threads పెంచాం (15), పీరియడ్ కొద్దిగా తగ్గించాం (15mo is enough for 200 SMA)
    data = yf.download(tkrs, period="15mo", progress=False, group_by='ticker', threads=15)
    
    # డేటా మొత్తం ఫెయిల్ అయితే, ఎర్రర్ రాకుండా ఎంప్టీ యాప్ చూపిస్తుంది
    if data.empty:
        return pd.DataFrame()

    results = []
    minutes = get_minutes_passed()

    # MultiIndex ఎర్రర్ రాకుండా సేఫ్టీ చెక్
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
            
            # MINERVINI METRICS
            sma50_d = float(df['Close'].rolling(window=50).mean().iloc[-1]) if len(df) >= 50 else 0.0
            sma150_d = float(df['Close'].rolling(window=150).mean().iloc[-1]) if len(df) >= 150 else 0.0
            sma200_d = float(df['Close'].rolling(window=200).mean().iloc[-1]) if len(df) >= 200 else 0.0
            high_52w = float(df['High'].rolling(window=252).max().iloc[-1]) if len(df) >= 252 else float(df['High'].max())
            low_52w = float(df['Low'].rolling(window=252).min().iloc[-1]) if len(df) >= 252 else float(df['Low'].min())
            sma200_20d = float(df['Close'].rolling(window=200).mean().iloc[-21]) if len(df) >= 220 else 0.0
            # VCP CONTRACTION & VOLUME DRY-UP LOGIC (Practical & Relaxed)
            vcp_price_contraction = False
            vcp_vol_dry = False
            if len(df) >= 60:
                # 60 Days (3 Months) Range
                max_60 = float(df['High'].iloc[-60:].max()); min_60 = float(df['Low'].iloc[-60:].min())
                range_60 = (max_60 - min_60) / min_60 if min_60 > 0 else 0
                
                # 10 Days (2 Weeks) Tight Range
                max_10 = float(df['High'].iloc[-10:].max()); min_10 = float(df['Low'].iloc[-10:].min())
                range_10 = (max_10 - min_10) / min_10 if min_10 > 0 else 0
                
                # ప్రైస్ కన్సాలిడేషన్: 10 రోజుల రేంజ్ 12% లోపు ఉండాలి & 60 రోజుల రేంజ్ కన్నా తక్కువ ఉండాలి
                if (range_60 > 0) and (range_10 < range_60) and (range_10 <= 0.12):
                    vcp_price_contraction = True
                    
                # వాల్యూమ్ డ్రై అప్: లాస్ట్ 5 రోజుల వాల్యూమ్, 50 రోజుల యావరేజ్ కంటే తక్కువ ఉండాలి
                if 'Volume' in df.columns and len(df) >= 50:
                    vol_avg_5 = float(df['Volume'].iloc[-5:].mean())
                    vol_avg_50 = float(df['Volume'].iloc[-50:].mean())
                    if vol_avg_5 < (vol_avg_50 * 0.85):
                        vcp_vol_dry = True
            
            is_swing = False; is_w_pullback = False
            latest_w_ema10 = 0; latest_w_ema50 = 0
            
            df_w = df.resample('W').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()
            weekly_net_chg = net_chg
            if len(df_w) >= 2: 
                prev_w_c = float(df_w['Close'].iloc[-2])
                if prev_w_c > 0: weekly_net_chg = ((ltp - prev_w_c) / prev_w_c) * 100
                    
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
                "SMA50": sma50_d, "SMA150": sma150_d, "SMA200": sma200_d, "High52W": high_52w, "Low52W": low_52w, "SMA200_20D": sma200_20d,
                "Day_C": day_chg, "C": net_chg, "W_C": float(weekly_net_chg), "S": score, "VolX": vol_x, "Is_Swing": is_swing,
                "Is_W_Pullback": is_w_pullback, "VWAP": vwap,
                "ATR": atr, "Narrow_CPR": is_narrow_cpr,
                "Bull_P": bull_power, "Bear_P": bear_power,
                "Is_Index": is_index, "Is_Sector": is_sector, "Sector": stock_sector, "Is_Commodity": is_commodity
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

        # ఇక్కడ మార్చండి:
        if 'Volume' in df_s.columns:
            df_s['Vol_SMA_375'] = df_s['Volume'].rolling(window=375, min_periods=1).mean()
        else:
            df_s['Vol_SMA_375'] = 0
            
        df_s['TR'] = pd.concat([
            df_s['High'] - df_s['Low'],
            (df_s['High'] - df_s['Close'].shift(1)).abs(),
            (df_s['Low'] - df_s['Close'].shift(1)).abs()
        ], axis=1).max(axis=1)
        df_s['ATR_13'] = df_s['TR'].ewm(span=13, adjust=False).mean()

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
                "Div Yield %": round(info.get('dividendYield', 0) * 100, 2) if info.get('dividendYield') else 0.0,
                "52W High": info.get('fiftyTwoWeekHigh', 0),
                "52W Low": info.get('fiftyTwoWeekLow', 0)
            }
        except: return None

    fund_data = []
    # 🔥 Multi-threading magic here! (15x faster)
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        results = executor.map(get_info, symbols_list)
        for res in results:
            if res is not None:
                fund_data.append(res)
                
    return pd.DataFrame(fund_data)   
@st.cache_data(ttl=86400, show_spinner=False)
def fetch_mf_performance():
    mf_dict = {}
    for cat, funds in MUTUAL_FUNDS.items():
        for name, tkr in funds.items():
            mf_dict[tkr] = {"Name": name, "Category": cat}
    
    tkrs = list(mf_dict.keys())
    data = yf.download(tkrs, period="5y", progress=False, group_by='ticker', threads=20)
    
    results = []
    for tkr in tkrs:
        try:
            df_t = data[tkr]['Close'].dropna() if isinstance(data.columns, pd.MultiIndex) else data['Close'].dropna()
            if df_t.empty: continue
            
            last_price = float(df_t.iloc[-1])
            
            def get_cagr(years):
                try:
                    past_date = df_t.index[-1] - pd.DateOffset(years=years)
                    closest_date = df_t.index[df_t.index <= past_date].max()
                    if pd.isna(closest_date): return "N/A"
                    past_price = float(df_t.loc[closest_date])
                    cagr = ((last_price / past_price) ** (1 / years)) - 1
                    return round(cagr * 100, 2)
                except: return "N/A"
                
            results.append({
                "Category": mf_dict[tkr]["Category"],
                "Fund Name": mf_dict[tkr]["Name"],
                "NAV (₹)": round(last_price, 2),
                "1Y (%)": get_cagr(1),
                "3Y CAGR (%)": get_cagr(3),
                "5Y CAGR (%)": get_cagr(5),
                "10Y CAGR (%)": get_cagr(10),
                "20Y CAGR (%)": get_cagr(20)
            })
        except: continue
        
    df_results = pd.DataFrame(results)
    if not df_results.empty:
        # 🔥 ఫిల్టర్ ఆటోమేటిక్‌గా 5 ఏళ్ల పర్ఫార్మెన్స్ (5Y CAGR) ని బట్టి ర్యాంక్ ఇస్తుంది
        df_results['Sort_Key'] = pd.to_numeric(df_results['5Y CAGR (%)'].replace('N/A', -999))
        df_results = df_results.sort_values(by='Sort_Key', ascending=False)
        
        # 🔥 ఏ కేటగిరీకి ఆ కేటగిరీ టాప్ 10 మాత్రమే తీసుకుంటుంది!
        top_10_dfs = []
        for cat in MUTUAL_FUNDS.keys():
            top_10_dfs.append(df_results[df_results['Category'] == cat].head(10))
            
        df_results = pd.concat(top_10_dfs)
        df_results = df_results.drop(columns=['Sort_Key'])
        
    return df_results

def render_mf_table(df_mf):
    if df_mf.empty: return "<div style='padding:20px; text-align:center;'>No Mutual Fund data available.</div>"
    html = f'<table class="term-table"><thead><tr><th colspan="9" class="term-head-swing" style="background-color: #005a9e; color: white;">🏆 TOP 10 MUTUAL FUNDS SCREEENER (AUTO-RANKED BY 5Y CAGR)</th></tr><tr style="background-color: #21262d;"><th style="width:5%;">RANK</th><th style="text-align:left; width:20%;">FUND NAME</th><th style="width:12%; color:#ffd700;">CATEGORY</th><th style="width:10%;">NAV (₹)</th><th style="width:10%;">1Y RETURN</th><th style="width:10%;">3Y CAGR</th><th style="width:10%;">5Y CAGR</th><th style="width:10%;">10Y CAGR</th><th style="width:10%;">20Y CAGR</th></tr></thead><tbody>'
    
    current_cat = ""
    rank = 1
    for i, (_, row) in enumerate(df_mf.iterrows()):
        if row["Category"] != current_cat:
            current_cat = row["Category"]
            rank = 1 # కేటగిరీ మారగానే ర్యాంక్ మళ్లీ 1 కి వస్తుంది
            
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        
        def colorize(val):
            if val == "N/A": return "<span style='color:#8b949e;'>N/A</span>"
            val_f = float(val)
            if val_f > 20: return f"<span style='color:#00FF00; font-weight:bold;'>{val}%</span>" 
            elif val_f > 12: return f"<span style='color:#3fb950;'>{val}%</span>" 
            elif val_f < 0: return f"<span style='color:#f85149;'>{val}%</span>" 
            return f"{val}%"

        html += f'<tr class="{bg_class}"><td><b>{rank}</b></td><td class="t-symbol">{row["Fund Name"]}</td><td style="font-size:11px; color:#c9d1d9; font-weight:bold;">{row["Category"]}</td><td>₹{row["NAV (₹)"]}</td><td>{colorize(row["1Y (%)"])}</td><td>{colorize(row["3Y CAGR (%)"])}</td><td>{colorize(row["5Y CAGR (%)"])}</td><td>{colorize(row["10Y CAGR (%)"])}</td><td>{colorize(row["20Y CAGR (%)"])}</td></tr>'
        rank += 1
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
        
        live_row = df_stocks[df_stocks['T'] == sym]
        trend_html = "➖"
        
        if not live_row.empty:
            ltp = float(live_row['P'].iloc[0])
            prev_c = float(live_row['Prev_C'].iloc[0])
            fetch_t = live_row['Fetch_T'].iloc[0]
            
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
    
    html += f'<tr class="port-total"><td colspan="7" style="text-align:right; padding-right:15px; font-size:12px;">TOTAL INVESTED: ₹{total_invested:,.0f} &nbsp;|&nbsp; CURRENT: ₹{total_current:,.0f} &nbsp;|&nbsp; OVERALL P&L:</td><td class="{d_color}">{d_sign}₹{total_day_pnl:,.0f}</td><td class="{o_color}">{o_sign}₹{overall_total_pnl:,.0f}</td><td class="{o_color}">{o_sign}{overall_total_pct:.2f}%</td></tr>'
    html += "</tbody></table>"
    return html

def render_portfolio_swing_advice_table(df_port, df_stocks, weekly_trends):
    if df_port.empty: return ""
    html = f'<table class="term-table"><thead><tr><th colspan="8" class="term-head-swing">🤖 PORTFOLIO SWING ADVISOR (ACTION & LEVELS)</th></tr><tr style="background-color: #21262d;"><th style="text-align:left; width:15%;">STOCK</th><th style="width:10%;">AVG PRICE</th><th style="width:10%;">LTP</th><th style="width:10%;">P&L %</th><th style="width:12%;">WK TREND</th><th style="width:13%; color:#f85149;">🛑 TRAILING SL</th><th style="width:13%; color:#3fb950;">🎯 NEXT TARGET</th><th style="width:17%;">💡 ACTION ADVICE</th></tr></thead><tbody>'
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
        advice = ""
        adv_color = ""
        if trend_state == 'Bullish' and is_swing: advice = "🚀 STRONG HOLD"; adv_color = "color:#3fb950; font-weight:bold;"
        elif trend_state == 'Bullish': advice = "🟢 HOLD"; adv_color = "color:#2ea043;"
        elif trend_state == 'Neutral': advice = "🟡 WATCH"; adv_color = "color:#ffd700;"
        else: advice = "🔴 EXIT / SELL"; adv_color = "color:#f85149; font-weight:bold;"
        if trend_state == 'Bearish': sl_val = ltp + (1.5 * atr_val); t1_val = ltp - (1.5 * atr_val)
        else:
            sl_val = ltp - (1.5 * atr_val)
            if pnl_pct > 5 and sl_val < buy_p: sl_val = buy_p + (ltp * 0.005) 
            t1_val = ltp + (3.0 * atr_val)
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
        sl_val = row.get('SL', row["P"] + (1.5 * atr_val) if is_down else row["P"] - (1.5 * atr_val))
        t1_val = row.get('T1', row["P"] - (1.5 * atr_val) if is_down else row["P"] + (1.5 * atr_val))
        t2_val = row.get('T2', row["P"] - (3.0 * atr_val) if is_down else row["P"] + (3.0 * atr_val))
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
        sl_val = row.get('SL', row["P"] + (1.5 * atr_val) if is_down else row["P"] - (1.5 * atr_val))
        t1_val = row.get('T1', row["P"] - (1.5 * atr_val) if is_down else row["P"] + (1.5 * atr_val))
        t2_val = row.get('T2', row["P"] - (3.0 * atr_val) if is_down else row["P"] + (3.0 * atr_val))
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
        sl_val = row.get('SL', row["P"] + (1.5 * atr_val) if is_down else row["P"] - (1.5 * atr_val))
        t1_val = row.get('T1', row["P"] - (1.5 * atr_val) if is_down else row["P"] + (1.5 * atr_val))
        t2_val = row.get('T2', row["P"] - (3.0 * atr_val) if is_down else row["P"] + (3.0 * atr_val))
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
    
    title_html = f"<a href='{tv_link}' target='_blank' style='color:#ffffff; text-decoration:none; line-height:1.2;'><b>{display_sym}</b><br><span style='font-size:12px; color:#cccccc;'>₹{row['P']:.2f} &nbsp;<span style='color:{color_hex};'>({sign}{pct_val:.2f}%)</span></span></a>"
    
    try:
        if not df_chart.empty:
            min_val = df_chart['Low'].min()
            max_val = df_chart['High'].max()
            y_padding = (max_val - min_val) * 0.15 if (max_val - min_val) != 0 else min_val * 0.005 
            chart_times = pd.to_datetime(df_chart.index)
            if chart_times.tz is not None: chart_times = chart_times.tz_convert('Asia/Kolkata')
            else: chart_times = chart_times.tz_localize('UTC').tz_convert('Asia/Kolkata')
                
            hover_data = (
                "🕒 " + chart_times.strftime('%d-%b %I:%M %p') + 
                "<br>🟢 O: ₹" + df_chart['Open'].round(2).astype(str) + 
                "<br>📈 H: ₹" + df_chart['High'].round(2).astype(str) + 
                "<br>📉 L: ₹" + df_chart['Low'].round(2).astype(str) + 
                "<br>🔴 C: ₹" + df_chart['Close'].round(2).astype(str)
            )
            
            def apply_advanced_candles(fig_obj, is_subplot):
                rc = dict(row=1, col=1) if is_subplot else dict()
                has_vol = 'Volume' in df_chart.columns and df_chart['Volume'].sum() > 0
                
                if has_vol:
                    vol_sma = df_chart.get('Vol_SMA_375', df_chart['Volume'].rolling(window=375, min_periods=1).mean())
                    vol = df_chart['Volume']
                    mask_hv = vol > (vol_sma.shift(1) * 1.5)  
                    mask_lv = vol < (vol_sma.shift(1) * 0.618)
                else:
                    mask_hv = pd.Series(False, index=df_chart.index)
                    mask_lv = pd.Series(False, index=df_chart.index)
                    
                mask_norm = ~(mask_hv | mask_lv)
                def am(col, mask): return np.where(mask, df_chart[col], np.nan)
                
                # Normal Vol Candles
                fig_obj.add_trace(go.Candlestick(
                    x=df_chart.index, open=am('Open', mask_norm), high=am('High', mask_norm), low=am('Low', mask_norm), close=am('Close', mask_norm), 
                    increasing_line_color='#2ea043', increasing_fillcolor='#2ea043', increasing_line_width=1,
                    decreasing_line_color='#da3633', decreasing_fillcolor='#da3633', decreasing_line_width=1,
                    showlegend=False, hoverinfo='skip'
                ), **rc)
                
                # 🔥 High Vol Candles
                if mask_hv.any():
                    fig_obj.add_trace(go.Candlestick(
                        x=df_chart.index, open=am('Open', mask_hv), high=am('High', mask_hv), low=am('Low', mask_hv), close=am('Close', mask_hv), 
                        increasing_line_color='#00FF00', increasing_fillcolor='#00FF00', increasing_line_width=2,
                        decreasing_line_color='#FF0000', decreasing_fillcolor='#FF0000', decreasing_line_width=2,
                        showlegend=False, hoverinfo='skip'
                    ), **rc)
                
                # Low Vol Candles
                if mask_lv.any():
                    fig_obj.add_trace(go.Candlestick(
                        x=df_chart.index, open=am('Open', mask_lv), high=am('High', mask_lv), low=am('Low', mask_lv), close=am('Close', mask_lv), 
                        increasing_line_color='#FF9800', increasing_fillcolor='#FF9800', increasing_line_width=1,
                        decreasing_line_color='#7FFFD4', decreasing_fillcolor='#7FFFD4', decreasing_line_width=1,
                        showlegend=False, hoverinfo='skip'
                    ), **rc)

                if mask_hv.any():
                    df_hv = df_chart[mask_hv].copy()
                    if 'EMA_10' in df_chart.columns: ref_line = df_hv['EMA_10']
                    elif 'SMA_50' in df_chart.columns: ref_line = df_hv['SMA_50']
                    elif 'SMA_10' in df_chart.columns: ref_line = df_hv['SMA_10']
                    elif 'VWAP' in df_chart.columns: ref_line = df_hv['VWAP']
                    else: ref_line = df_hv['Close']
                        
                    mask_above = df_hv['Close'] >= ref_line
                    mask_below = df_hv['Close'] < ref_line
                    
                    if not df_hv[mask_above].empty:
                        y_above = df_hv[mask_above]['Low'] - (df_hv[mask_above]['Close'] * 0.0025)
                        fig_obj.add_trace(go.Scatter(x=df_hv[mask_above].index, y=y_above, mode='text', text=['🔥']*len(y_above), textposition='bottom center', textfont=dict(size=10), showlegend=False, hoverinfo='skip'), **rc)
                        
                    if not df_hv[mask_below].empty:
                        y_below = df_hv[mask_below]['High'] + (df_hv[mask_below]['Close'] * 0.0025)
                        fig_obj.add_trace(go.Scatter(x=df_hv[mask_below].index, y=y_below, mode='text', text=['🔥']*len(y_below), textposition='top center', textfont=dict(size=10), showlegend=False, hoverinfo='skip'), **rc)
                
                if has_vol:
                    mask_exhaust = vol > (vol_sma * 4.669)
                    if mask_exhaust.any():
                        df_ex = df_chart[mask_exhaust]
                        fig_obj.add_trace(go.Scatter(x=df_ex.index, y=df_ex['High'] + (df_ex['Close'] * 0.0035), mode='text', text=['🚦']*len(df_ex), textposition='top center', textfont=dict(size=18), showlegend=False, hoverinfo='skip'), **rc)
                
                atr_val = df_chart['ATR_13'] if 'ATR_13' in df_chart.columns else pd.concat([df_chart['High'] - df_chart['Low'], (df_chart['High'] - df_chart['Close'].shift(1)).abs(), (df_chart['Low'] - df_chart['Close'].shift(1)).abs()], axis=1).max(axis=1).ewm(span=13, adjust=False).mean()
                mask_vola = (df_chart['High'] - df_chart['Low']) > (atr_val * 2.718)
                if mask_vola.any():
                    df_vol = df_chart[mask_vola]
                    fig_obj.add_trace(go.Scatter(x=df_vol.index, y=df_vol['Low'] - (df_vol['Close']*0.0035), mode='text', text=['⚡']*len(df_vol), textposition='bottom center', textfont=dict(size=14), showlegend=False, hoverinfo='skip'), **rc)

            if show_vol:
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.02, row_heights=[0.75, 0.25])
                apply_advanced_candles(fig, is_subplot=True)
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['High'], mode='lines', line=dict(color='rgba(0,0,0,0)'), showlegend=False, hoverinfo='text' if show_crosshair else 'skip', text=hover_data, hovertemplate="%{text}<extra></extra>" if show_crosshair else None, name=""), row=1, col=1)
                
                if timeframe == "Daily Chart":
                    if 'SMA_50' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_50'], mode='lines', line=dict(color='#FFD700', width=1.5), name='50 SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
                    if 'SMA_150' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_150'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), name='150 SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
                    if 'SMA_200' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_200'], mode='lines', line=dict(color='#FF4500', width=2), name='200 SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
                elif timeframe == "Weekly Chart":
                    if 'SMA_10' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_10'], mode='lines', line=dict(color='#FFD700', width=1.5), name='10 Wk SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
                    if 'SMA_40' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_40'], mode='lines', line=dict(color='#FF4500', width=2), name='40 Wk SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
                else:
                    # 🔥 SMART ANCHOR & ANTI-COLLISION LOGIC 🔥
                    offset = -4 if len(df_chart) >= 4 else -1
                    tag_idx = df_chart.index[offset]
                    
                    last_close = float(df_chart['Close'].iloc[-1])
                    has_vwap = 'VWAP' in df_chart.columns
                    has_ema = 'EMA_10' in df_chart.columns
                    
                    last_vwap = float(df_chart['VWAP'].iloc[-1]) if has_vwap else 0
                    last_ema = float(df_chart['EMA_10'].iloc[-1]) if has_ema else 0
                    
                    # 🔥 గాల్లో తేలకుండా ఉండటానికి ఆ లైన్ యొక్క కరెక్ట్ (పాత) ప్రైస్ తీసుకుంటున్నాం
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
                        bull = df_chart['Close'].iloc[i] >= df_chart['Open'].iloc[i]
                        hv = df_chart['Volume'].iloc[i] > (vol_sma.iloc[i] * 1.618)
                        lv = df_chart['Volume'].iloc[i] < (vol_sma.iloc[i] * 0.618)
                        if hv: vol_colors.append('#00FF00' if bull else '#FF0000')
                        elif lv: vol_colors.append('#FF9800' if bull else '#7FFFD4')
                        else: vol_colors.append('#2ea043' if bull else '#da3633')
                else:
                    vol_colors = ['#2ea043' if close >= open_p else '#da3633' for close, open_p in zip(df_chart['Close'], df_chart['Open'])]
                
                fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Volume'], marker_color=vol_colors, showlegend=False, hoverinfo='skip'), row=2, col=1)
                
                # 🔥 Margin 'r' పీకేశాం (r=45 if show_crosshair else 5) అప్పుడు చార్ట్ ఫుల్ స్పేస్ తీసుకుంటుంది
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
                apply_advanced_candles(fig, is_subplot=False)
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['High'], mode='lines', line=dict(color='rgba(0,0,0,0)'), showlegend=False, hoverinfo='text' if show_crosshair else 'skip', text=hover_data, hovertemplate="%{text}<extra></extra>" if show_crosshair else None, name=""))
                
                if timeframe == "Daily Chart":
                    if 'SMA_50' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_50'], mode='lines', line=dict(color='#FFD700', width=1.5), name='50 SMA', showlegend=False, hoverinfo='skip'))
                    if 'SMA_150' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_150'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), name='150 SMA', showlegend=False, hoverinfo='skip'))
                    if 'SMA_200' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_200'], mode='lines', line=dict(color='#FF4500', width=2), name='200 SMA', showlegend=False, hoverinfo='skip'))
                elif timeframe == "Weekly Chart":
                    if 'SMA_10' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_10'], mode='lines', line=dict(color='#FFD700', width=1.5), name='10 Wk SMA', showlegend=False, hoverinfo='skip'))
                    if 'SMA_40' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_40'], mode='lines', line=dict(color='#FF4500', width=2), name='40 Wk SMA', showlegend=False, hoverinfo='skip'))
                else:
                    # 🔥 SMART ANCHOR & ANTI-COLLISION LOGIC 🔥
                    offset = -4 if len(df_chart) >= 4 else -1
                    tag_idx = df_chart.index[offset]
                    
                    last_close = float(df_chart['Close'].iloc[-1])
                    has_vwap = 'VWAP' in df_chart.columns
                    has_ema = 'EMA_10' in df_chart.columns
                    
                    last_vwap = float(df_chart['VWAP'].iloc[-1]) if has_vwap else 0
                    last_ema = float(df_chart['EMA_10'].iloc[-1]) if has_ema else 0
                    
                    # 🔥 గాల్లో తేలకుండా ఉండటానికి ఆ లైన్ యొక్క కరెక్ట్ (పాత) ప్రైస్ తీసుకుంటున్నాం
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
                
                # 🔥 Margin 'r' పీకేశాం (r=45 if show_crosshair else 5) అప్పుడు చార్ట్ ఫుల్ స్పేస్ తీసుకుంటుంది
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

# --- 6. FETCH DATA ---
st.markdown("<hr style='margin:10px 0; border-color:#30363d;'>", unsafe_allow_html=True)
market_segment = st.radio("🏢 Select Market Segment (To Reduce Load)", ["F&O (Top 200) 🔵", "Mid Cap 🟡", "Small Cap 🟢", "All Combined 🌐"], horizontal=True)

if True: 
    df = fetch_all_data(market_segment)

if not df.empty and 'LIVE_PRICES' in st.session_state:
    for i, row in df.iterrows():
        clean_sym = str(row['Fetch_T']).replace(".NS", "")
        if clean_sym in st.session_state.LIVE_PRICES:
            new_ltp = st.session_state.LIVE_PRICES[clean_sym]
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

watchlist_mode = st.selectbox("Watchlist", ["Day Trading Stocks 🚀", "🤖 Today's AI Predictions", "High Score Stocks 🔥", "Swing Trading 📈", "Nifty 50 Heatmap", "Terminal Tables 🗃️", "My Portfolio 💼", "Commodity 🛢️", "Fundamentals 🏢", "Mutual Funds 📈"], index=0, label_visibility="collapsed")
view_mode = st.radio("Display", ["Heat Map", "Chart 📈"], horizontal=True, label_visibility="collapsed")

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
        if watchlist_mode in ["Day Trading Stocks 🚀", "🤖 Today's AI Predictions", "High Score Stocks 🔥"]:
            move_type_filter = st.multiselect("Strategy Filter",
                ["All Moves", "🔥 Live Power Mover (Last 2 Candles)", "🚀 All-Day Volume Spikes (Max Fire)", "⚡ Intraday Pro Breakout (Top 5)", "🌊 One Sided Only", "🔄 VWAP Reversal", "🎯 Reversals Only", "🏹 Rubber Band Stretch", "🏄‍♂️ Momentum Ignition", "💥 Narrow CPR Breakout", "🧲 10-EMA Retest (Best Entry)", "📉 FIB Retracement (0.382)", "📈 Minervini Trend Template (VCP)", "🌅 15-Min ORB (Opening Range Breakout)"], 
                default=["🔥 Live Power Mover (Last 2 Candles)", "🚀 All-Day Volume Spikes (Max Fire)", "🌊 One Sided Only"]
            )
        elif watchlist_mode == "Swing Trading 📈":
            move_type_filter = st.multiselect("Strategy Filter", ["All Swing Stocks", "🚀 Pro Breakout Strategy", "🌟 Weekly 10EMA Pro", "📈 Minervini Trend Template (VCP)", "📉 Strict VCP (Price & Vol Contraction)"], default=["All Swing Stocks"])
        elif watchlist_mode == "Fundamentals 🏢":
            fund_filter = st.selectbox("Fundamentals Filter", ["Top Ranked Stocks ⭐", "Swing Trading Candidates 📈", "Nifty 50 Stocks", "My Portfolio 💼"], index=0)
            
    with sc2:
        sort_mode = st.selectbox("Sort By", ["Score Wise Up ⭐", "Custom Sort", "Sector Trending First 📊", "Score Wise Down ⬇️", "🤖 AI Prob Up ⬆️", "% Change Up 🟢", "% Change Down 🔴"], index=0)
        
    with sc3:
        search_stock = st.selectbox("Search Stock", ["-- None --"] + all_names)

    if view_mode == "Chart 📈" or watchlist_mode in ["Swing Trading 📈", "My Portfolio 💼", "Commodity 🛢️"]:
        st.markdown("<hr style='margin:10px 0; border-color:#30363d;'>", unsafe_allow_html=True)
        cc1, cc2, cc3 = st.columns(3)
        with cc1:
            # ✅ ఇప్పుడు అన్ని మోడ్స్ కి టైమ్‌ఫ్రేమ్ ఆప్షన్ కనిపిస్తుంది
            chart_timeframe = st.radio("Timeframe", ["Intraday (5m)", "Daily Chart", "Weekly Chart"], horizontal=True)
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

if not df.empty:
    df_indices = df[df['Is_Index']].copy()
    df_indices['Order'] = df_indices['T'].map({"NIFTY": 1, "BANKNIFTY": 2, "INDIA VIX": 3, "SPX": 4, "DAX": 5, "USD/INR": 6})
    df_indices = df_indices.sort_values('Order')
    
    df_sectors = df[df['Is_Sector']].copy()
    sec_sort_key = "W_C" if chart_timeframe == "Weekly Chart" else "Day_C"
    df_sectors = df_sectors.sort_values(by=sec_sort_key, ascending=False)
    
    # 1. Base Data (All Fetched Stocks)
    df_all_stocks = df[(~df['Is_Index']) & (~df['Is_Sector']) & (~df['Is_Commodity'])].copy()
    df_commodities = df[df['Is_Commodity']].copy()
    
    df_port_saved = load_portfolio()

    # 2. 🔥 STRICT SEGMENT FILTERING (IRON WALL) 🔥
    if market_segment == "F&O (Top 200) 🔵":
        strict_allowed = set(NIFTY_50 + FNO_STOCKS)
    elif market_segment == "Mid Cap 🟡":
        strict_allowed = set(MIDCAP_STOCKS)
    elif market_segment == "Small Cap 🟢":
        strict_allowed = set(SMALLCAP_STOCKS)
    else: # All Combined
        strict_allowed = set(NIFTY_50 + FNO_STOCKS + MIDCAP_STOCKS + SMALLCAP_STOCKS)

    # ఈ ఒక్క లైన్ దెబ్బతో పోర్ట్‌ఫోలియో స్టాక్స్ బైపాస్ అవ్వడం పర్మినెంట్ గా ఆగిపోతుంది!
    df_stocks = df_all_stocks[df_all_stocks['T'].isin(strict_allowed)].copy()
    
    # 3. Sector Calcs (దీనికి ఎప్పుడూ df_all_stocks వాడాలి)
    df_nifty = df_all_stocks[df_all_stocks['T'].isin(NIFTY_50)].copy()
    sector_perf = df_nifty.groupby('Sector')['C'].mean().sort_values(ascending=False)
    valid_sectors = [s for s in sector_perf.index if s != "OTHER"]
    
    if valid_sectors: top_buy_sector, top_sell_sector = valid_sectors[0], valid_sectors[-1]
    else: top_buy_sector, top_sell_sector = "PHARMA", "IT"
        
    df_buy_sector = df_nifty[df_nifty['Sector'] == top_buy_sector].sort_values(by=['S', 'C'], ascending=[False, False])
    df_sell_sector = df_nifty[df_nifty['Sector'] == top_sell_sector].sort_values(by=['S', 'C'], ascending=[False, True])
    df_independent = df_nifty[(~df_nifty['Sector'].isin([top_buy_sector, top_sell_sector])) & (df_nifty['S'] >= 5)].sort_values(by='S', ascending=False).head(8)
    df_broader = df_all_stocks[(df_all_stocks['T'].isin(FNO_STOCKS)) & (~df_all_stocks['T'].isin(NIFTY_50)) & (df_all_stocks['S'] >= 5)].sort_values(by='S', ascending=False).head(8)

    if watchlist_mode == "Terminal Tables 🗃️":
        terminal_tickers = pd.concat([df_buy_sector, df_sell_sector, df_independent, df_broader])['Fetch_T'].unique().tolist()
        df_filtered = df_all_stocks[df_all_stocks['Fetch_T'].isin(terminal_tickers)]
    elif watchlist_mode == "My Portfolio 💼":
        port_tickers = [f"{str(sym).upper().strip()}.NS" for sym in df_port_saved['Symbol'].tolist() if str(sym).strip() != ""]
        df_filtered = df_all_stocks[df_all_stocks['Fetch_T'].isin(port_tickers)]
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
    elif watchlist_mode == "🤖 Today's AI Predictions":
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
        df_filtered = df_filtered[(df_filtered['Strategy_Icon'] != "Neutral") & (df_filtered['S'] >= 11)]
    elif watchlist_mode == "Day Trading Stocks 🚀":
        df_filtered = df_stocks[df_stocks['C'].abs() >= 1.0].copy()
    elif watchlist_mode == "Swing Trading 📈":
        df_filtered = df_stocks.copy()
    else:
        df_filtered = df_stocks[(df_stocks['S'] >= 11) & (df_stocks['VolX'] >= 1.5)]

    all_display_tickers = list(set(df_indices['Fetch_T'].tolist() + df_sectors['Fetch_T'].tolist() + df_filtered['Fetch_T'].tolist() + st.session_state.pinned_stocks))
    
    if st.session_state.get('active_sec'):
        sec_stock_names = TOP_SECTOR_STOCKS.get(st.session_state.active_sec, [])
        sec_tickers = [f"{sym}.NS" for sym in sec_stock_names]
        all_display_tickers = list(set(all_display_tickers + sec_tickers))
    
    if search_stock != "-- None --":
        search_fetch_t = df[df['T'] == search_stock]['Fetch_T'].iloc[0]
        if search_fetch_t not in all_display_tickers: all_display_tickers.append(search_fetch_t)
            
    if True: # 5m fetch
        five_min_data = fetch_cached_5m_data(all_display_tickers)

    processed_charts = {}
    weekly_trends = {}
    alpha_tags = {}
    trend_scores = {}
    retest_tags = {}
    orb_tags = {} 

    nifty_dist_5m = 0.1
    if "^NSEI" in five_min_data.columns.levels[0]:
        n_raw = five_min_data["^NSEI"] if isinstance(five_min_data.columns, pd.MultiIndex) else five_min_data
        n_day = process_5m_data(n_raw)
        if not n_day.empty:
            n_ltp = n_day['Close'].iloc[-1]
            n_vwap = n_day['VWAP'].iloc[-1]
            if n_vwap > 0: nifty_dist_5m = abs(n_ltp - n_vwap) / n_vwap * 100

    for sym in all_display_tickers:
        try: df_raw = five_min_data[sym] if isinstance(five_min_data.columns, pd.MultiIndex) else five_min_data
        except KeyError: df_raw = pd.DataFrame()
            
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
                    if current_gap_pct >= 1.50: one_sided_tag = "🌊Mega-1.5%"; trend_bonus = 7
                    elif current_gap_pct >= 1.00: one_sided_tag = "🌊Super-1.0%"; trend_bonus = 5
                    elif current_gap_pct >= 0.50: one_sided_tag = "🌊Trend-0.5%"; trend_bonus = 3
                    else: one_sided_tag = "🌊Trend"; trend_bonus = 1
            
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
                if "Above" in a_data['type'] and current_ltp >= a_data['price']:
                    st.toast(f"🔔 ALERT: {a_data['name']} is ABOVE ₹{a_data['price']}! (LTP: {current_ltp})", icon="🚀")
                    alerts_triggered_html += f"<div style='background-color:#1e5f29; color:white; padding:10px; border-radius:5px; margin-bottom:5px;'><b>🔔 ALERT:</b> {a_data['name']} crossed ABOVE ₹{a_data['price']}! (LTP: {current_ltp})</div>"
                elif "Below" in a_data['type'] and current_ltp <= a_data['price']:
                    st.toast(f"🔔 ALERT: {a_data['name']} is BELOW ₹{a_data['price']}! (LTP: {current_ltp})", icon="🩸")
                    alerts_triggered_html += f"<div style='background-color:#b52524; color:white; padding:10px; border-radius:5px; margin-bottom:5px;'><b>🔔 ALERT:</b> {a_data['name']} crossed BELOW ₹{a_data['price']}! (LTP: {current_ltp})</div>"

    if alerts_triggered_html: st.markdown(alerts_triggered_html, unsafe_allow_html=True)

    if not df_filtered.empty:
        df_filtered = df_filtered.copy() # 👈 ఈ ఒక్క లైన్ యాడ్ చేయండి బాస్!
        
        df_filtered['AlphaTag'] = df_filtered['Fetch_T'].map(alpha_tags).fillna("")
        df_filtered['Trend_Score'] = df_filtered['Fetch_T'].map(trend_scores).fillna(0)
        df_filtered['Retest_Tag'] = df_filtered['Fetch_T'].map(retest_tags).fillna("") 
        df_filtered['ORB_Tag'] = df_filtered['Fetch_T'].map(orb_tags).fillna("") 
        df_filtered['S'] = df_filtered['S'] + df_filtered['Trend_Score']
        df_filtered['Retest_Tag'] = df_filtered['Fetch_T'].map(retest_tags).fillna("") 
        df_filtered['ORB_Tag'] = df_filtered['Fetch_T'].map(orb_tags).fillna("") 
        df_filtered['S'] = df_filtered['S'] + df_filtered['Trend_Score']
        
        if watchlist_mode in ["Day Trading Stocks 🚀", "🤖 Today's AI Predictions"]:
            sector_abs_perf = sector_perf.abs().sort_values(ascending=False)
            sector_bonus_map = {}
            for rank, (sec, val) in enumerate(sector_abs_perf.items()):
                bonus = max(10 - (rank * 2), 0)
                sector_bonus_map[sec] = bonus
            df_filtered['Sector_Bonus'] = df_filtered['Sector'].map(sector_bonus_map).fillna(0)
        else:
            df_filtered['Sector_Bonus'] = 0
            
        if watchlist_mode == "🤖 Today's AI Predictions" and "🧲 10-EMA Retest (Best Entry)" in move_type_filter:
            df_filtered = df_filtered[
                (df_filtered['Strategy_Icon'].str.contains('UP', na=False) & (df_filtered['Retest_Tag'] == 'BUY_RETEST')) |
                (df_filtered['Strategy_Icon'].str.contains('DOWN', na=False) & (df_filtered['Retest_Tag'] == 'SELL_RETEST'))
            ]
        
        if watchlist_mode in ["Day Trading Stocks 🚀", "High Score Stocks 🔥"]:
            base_buy = (df_filtered['P'] > df_filtered['W_EMA10']) & (df_filtered['P'] > df_filtered['W_EMA50']) & (df_filtered['P'] > df_filtered['VWAP'])
            base_sell = (df_filtered['P'] < df_filtered['W_EMA10']) & (df_filtered['P'] < df_filtered['W_EMA50']) & (df_filtered['P'] < df_filtered['VWAP'])
            
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
                "🔥 Live Power Mover (Last 2 Candles)", "🚀 All-Day Volume Spikes (Max Fire)", "⚡ Intraday Pro Breakout (Top 5)", "🌊 One Sided Only", "🔄 VWAP Reversal", "🎯 Reversals Only", 
                "🏹 Rubber Band Stretch", "🏄‍♂️ Momentum Ignition", "💥 Narrow CPR Breakout", "🧲 10-EMA Retest (Best Entry)", "📉 FIB Retracement (0.382)", "📈 Minervini Trend Template (VCP)", "🌅 15-Min ORB (Opening Range Breakout)"
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
            
            strats_to_run = strategies_list if (not move_type_filter or "All Moves" in move_type_filter) else move_type_filter
            if apply_fib_strict and (len(other_strats_selected) > 0 or "All Moves" in move_type_filter):
                strats_to_run = [s for s in strats_to_run if s != "📉 FIB Retracement (0.382)"]

            all_dfs = []
            for strat in strats_to_run:
                c_buy = pd.Series(False, index=df_filtered.index)
                c_sell = pd.Series(False, index=df_filtered.index)
                icon_str = ""

                if strat == "🔥 Live Power Mover (Last 2 Candles)":
                    buy_mask = pd.Series(False, index=df_filtered.index)
                    sell_mask = pd.Series(False, index=df_filtered.index)
                    
                    for idx, r in df_filtered.iterrows():
                        tkr = r['Fetch_T']
                        if tkr in processed_charts and len(processed_charts[tkr]) >= 2:
                            df_hist = processed_charts[tkr]
                            if 'Volume' in df_hist.columns and 'Vol_SMA_89' in df_hist.columns and 'EMA_10' in df_hist.columns:
                                vol_fire = df_hist['Volume'] > (df_hist['Vol_SMA_89'] * 1.618)
                                
                                # బాస్ చెప్పినట్లు: గ్రీన్/రెడ్ రూల్ తీసేశాను. చార్ట్‌లో ఫైర్ పడితే ఇక్కడ కౌంట్ అవుతుంది!
                                b_cond = vol_fire & (df_hist['Close'] >= df_hist['EMA_10'])
                                s_cond = vol_fire & (df_hist['Close'] < df_hist['EMA_10'])
                                
                                if b_cond.iloc[-2:].sum() >= 1: buy_mask[idx] = True
                                if s_cond.iloc[-2:].sum() >= 1: sell_mask[idx] = True
                                
                    c_buy = base_buy & buy_mask
                    c_sell = base_sell & sell_mask
                    icon_str = "🔥 Live Breakout"

                if strat == "🔥 Live Power Mover (Last 2 Candles)":
                    buy_mask = pd.Series(False, index=df_filtered.index)
                    sell_mask = pd.Series(False, index=df_filtered.index)
                    
                    for idx, r in df_filtered.iterrows():
                        tkr = r['Fetch_T']
                        if tkr in processed_charts and len(processed_charts[tkr]) >= 2:
                            df_hist = processed_charts[tkr]
                            if 'Volume' in df_hist.columns and 'Vol_SMA_375' in df_hist.columns and 'EMA_10' in df_hist.columns:
                                
                                # 375 SMA కన్నా 1.5 రెట్లు వాల్యూమ్
                                vol_fire = df_hist['Volume'] > (df_hist['Vol_SMA_375'].shift(1) * 1.5)
                                
                                # Buy: ముందు క్యాండిల్ పైన క్లోజ్ అవ్వాలి + 10 EMA పైన క్లోజ్ అవ్వాలి
                                b_cond = vol_fire & (df_hist['Close'] > df_hist['Close'].shift(1)) & (df_hist['Close'] >= df_hist['EMA_10'])
                                # Sell: ముందు క్యాండిల్ కింద క్లోజ్ అవ్వాలి + 10 EMA కింద క్లోజ్ అవ్వాలి
                                s_cond = vol_fire & (df_hist['Close'] < df_hist['Close'].shift(1)) & (df_hist['Close'] <= df_hist['EMA_10'])
                                
                                if b_cond.iloc[-2:].sum() >= 1: buy_mask[idx] = True
                                if s_cond.iloc[-2:].sum() >= 1: sell_mask[idx] = True
                                
                    c_buy = base_buy & buy_mask
                    c_sell = base_sell & sell_mask
                    icon_str = "🔥 Live Breakout"

                elif strat == "🚀 All-Day Volume Spikes (Max Fire)":
                    buy_mask = pd.Series(False, index=df_filtered.index)
                    sell_mask = pd.Series(False, index=df_filtered.index)
                    
                    # 1. కేవలం FNO (Nifty Futures) స్టాక్స్ ఫిల్టర్
                    df_fno = df_filtered[df_filtered['T'].isin(FNO_STOCKS)]
                    
                    for idx, r in df_fno.iterrows():
                        tkr = r['Fetch_T']
                        if tkr in processed_charts and len(processed_charts[tkr]) >= 2:
                            df_hist = processed_charts[tkr]
                            
                            if 'Volume' in df_hist.columns and 'Vol_SMA_375' in df_hist.columns and 'EMA_10' in df_hist.columns:
                                ltp = df_hist['Close'].iloc[-1]
                                vwap = df_hist['VWAP'].iloc[-1]
                                ema10 = df_hist['EMA_10'].iloc[-1]
                                
                                # కరెంట్ ప్రైస్ డైరెక్షన్
                                is_buy_trend = (ltp > vwap) and (ltp > ema10)
                                is_sell_trend = (ltp < vwap) and (ltp < ema10)
                                
                                # వాల్యూమ్ కండిషన్ (375 SMA * 1.5)
                                vol_fire = df_hist['Volume'] > (df_hist['Vol_SMA_375'].shift(1) * 1.5)
                                
                                # 🔥 పక్కా ఫైర్ రూల్స్ (Previous Close Break + 10 EMA Alignment)
                                valid_buy_fire = vol_fire & (df_hist['Close'] > df_hist['Close'].shift(1)) & (df_hist['Close'] >= df_hist['EMA_10'])
                                valid_sell_fire = vol_fire & (df_hist['Close'] < df_hist['Close'].shift(1)) & (df_hist['Close'] <= df_hist['EMA_10'])
                                
                                tot_buy = valid_buy_fire.sum()
                                tot_sell = valid_sell_fire.sum()
                                
                                fire_score = 0
                                
                                # నెట్ స్కోర్ లెక్కించడం
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

                    # కనీసం 1% మూమెంట్ (Day Change) ఉంటేనే లిస్ట్‌లోకి రావాలి
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
                    cond4 = df_filtered['P'] > df_filtered['SMA50']
                    cond7 = df_filtered['SMA50'] > df_filtered['SMA150'] 
                    cond5 = df_filtered['P'] >= (df_filtered['Low52W'] * 1.30)
                    cond6 = df_filtered['P'] >= (df_filtered['High52W'] * 0.75)
                    c_buy = base_buy & cond1 & cond2 & cond3 & cond4 & cond7 & cond5 & cond6
                    c_sell = pd.Series(False, index=df_filtered.index)
                    icon_str = "📈 M-VCP"
                elif strat == "📉 Strict VCP (Price & Vol Contraction)":
                    # బేసిక్ Minervini అప్‌ట్రెండ్ రూల్స్
                    cond1 = (df_filtered['P'] > df_filtered['SMA150']) & (df_filtered['P'] > df_filtered['SMA200'])
                    cond2 = df_filtered['SMA150'] > df_filtered['SMA200']
                    cond4 = df_filtered['P'] > df_filtered['SMA50']
                    cond5 = df_filtered['P'] >= (df_filtered['Low52W'] * 1.30)
                    cond6 = df_filtered['P'] >= (df_filtered['High52W'] * 0.75)
                    
                    # 🔥 మనం కొత్తగా కనిపెట్టిన VCP రూల్స్
                    vcp_cond = (df_filtered['VCP_Contract'] == True) & (df_filtered['VCP_Vol_Dry'] == True)
                    
                    c_buy = base_buy & cond1 & cond2 & cond4 & cond5 & cond6 & vcp_cond
                    c_sell = pd.Series(False, index=df_filtered.index)
                    icon_str = "📉 VCP"
                elif strat == "🌅 15-Min ORB (Opening Range Breakout)":
                    c_buy = base_buy & (df_filtered['ORB_Tag'] == "ORB_BUY") & (df_filtered['VolX'] >= 1.2)
                    c_sell = base_sell & (df_filtered['ORB_Tag'] == "ORB_SELL") & (df_filtered['VolX'] >= 1.2)
                    icon_str = "🌅 ORB"

                if apply_fib_strict and strat != "📉 FIB Retracement (0.382)":
                    c_buy = c_buy & fib_buy_mask
                    c_sell = c_sell & fib_sell_mask
                    icon_str = icon_str + " + 📉FIB"

                top_buy = df_filtered[c_buy].sort_values(by=['VolX', 'Day_C'], ascending=[False, False]).head(5).copy()
                if not top_buy.empty: top_buy['Strategy_Icon'] = f"{icon_str} BUY"
                top_sell = df_filtered[c_sell].sort_values(by=['VolX', 'Day_C'], ascending=[False, True]).head(5).copy()
                if not top_sell.empty: top_sell['Strategy_Icon'] = f"{icon_str} SELL"
                
                all_dfs.extend([top_buy, top_sell])
                
            if all_dfs: df_filtered = pd.concat(all_dfs).drop_duplicates(subset=['Fetch_T'])
            else: df_filtered = pd.DataFrame(columns=df_filtered.columns)
            
            if not df_filtered.empty:
                df_filtered['T1'] = np.where(df_filtered['Strategy_Icon'].str.contains('BUY', na=False), round(df_filtered['P'] * 1.008, 2), round(df_filtered['P'] * 0.992, 2))
                df_filtered['T2'] = np.where(df_filtered['Strategy_Icon'].str.contains('BUY', na=False), round(df_filtered['P'] * 1.015, 2), round(df_filtered['P'] * 0.985, 2))
                df_filtered['SL'] = np.where(df_filtered['Strategy_Icon'].str.contains('BUY', na=False), round(df_filtered['P'] * 0.992, 2), round(df_filtered['P'] * 1.008, 2))
        
        elif watchlist_mode == "Swing Trading 📈":
            dfs_to_concat = []
            if "📉 Strict VCP (Price & Vol Contraction)" in move_type_filter:
                cond1 = (df_filtered['P'] > df_filtered['SMA150']) & (df_filtered['P'] > df_filtered['SMA200'])
                cond2 = df_filtered['SMA150'] > df_filtered['SMA200']
                cond4 = df_filtered['P'] > df_filtered['SMA50']
                cond5 = df_filtered['P'] >= (df_filtered['Low52W'] * 1.30)
                cond6 = df_filtered['P'] >= (df_filtered['High52W'] * 0.75)
                vcp_cond = (df_filtered['VCP_Contract'] == True) & (df_filtered['VCP_Vol_Dry'] == True)
                
                df_vcp = df_filtered[cond1 & cond2 & cond4 & cond5 & cond6 & vcp_cond].copy()
                df_vcp['Strategy_Icon'] = "📉 VCP"
                dfs_to_concat.append(df_vcp)
            
            if "All Swing Stocks" in move_type_filter or not move_type_filter:
                dfs_to_concat.append(df_filtered[df_filtered['Is_Swing'] == True])
            
            if "🚀 Pro Breakout Strategy" in move_type_filter:
                top_body = df_filtered['H'] - df_filtered['P']
                total_range = df_filtered['H'] - df_filtered['L']
                breakout_cond = (
                    (df_filtered['P'] > df_filtered['O']) &            
                    (top_body <= (total_range * 0.25)) &             
                    (df_filtered['VolX'] >= 1.5) &                    
                    (df_filtered['Day_C'] >= 2.0) &                    
                    (df_filtered['Is_Swing'] == True)                 
                )
                df_brk = df_filtered[breakout_cond].copy()
                df_brk['Strategy_Icon'] = "🚀"
                dfs_to_concat.append(df_brk)
                
            if "🌟 Weekly 10EMA Pro" in move_type_filter:
                df_ema = df_filtered[df_filtered['Is_W_Pullback'] == True].copy()
                df_ema['Strategy_Icon'] = "🌟"
                dfs_to_concat.append(df_ema)
                
            if "📈 Minervini Trend Template (VCP)" in move_type_filter:
                cond1 = (df_filtered['P'] > df_filtered['SMA150']) & (df_filtered['P'] > df_filtered['SMA200'])
                cond2 = df_filtered['SMA150'] > df_filtered['SMA200']
                cond3 = df_filtered['SMA200'] > df_filtered['SMA200_20D']
                cond4 = df_filtered['P'] > df_filtered['SMA50']
                cond7 = df_filtered['SMA50'] > df_filtered['SMA150'] 
                cond5 = df_filtered['P'] >= (df_filtered['Low52W'] * 1.30)
                cond6 = df_filtered['P'] >= (df_filtered['High52W'] * 0.75)
                df_min = df_filtered[cond1 & cond2 & cond3 & cond4 & cond7 & cond5 & cond6].copy()
                df_min['Strategy_Icon'] = "📈 M-VCP"
                dfs_to_concat.append(df_min)

            if dfs_to_concat:
                df_filtered = pd.concat(dfs_to_concat).drop_duplicates(subset=['Fetch_T'])
            else:
                df_filtered = pd.DataFrame(columns=df_filtered.columns)

    sort_key = "W_C" if chart_timeframe == "Weekly Chart" else "Day_C"
    if 'Sector_Bonus' not in df_filtered.columns: df_filtered['Sector_Bonus'] = 0
    
    if sort_mode == "% Change Up 🟢": df_stocks_display = df_filtered.sort_values(by=sort_key, ascending=False)
    elif sort_mode == "% Change Down 🔴": df_stocks_display = df_filtered.sort_values(by=sort_key, ascending=True)
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
        if watchlist_mode == "🤖 Today's AI Predictions": df_stocks_display = df_filtered.sort_values(by=['AI_Prob', 'VolX'], ascending=[False, False])
        else: df_stocks_display = df_filtered.sort_values(by=['S', 'VolX', sort_key], ascending=[False, False, False])
            
    if watchlist_mode == "Fundamentals 🏢":
        st.markdown(f"<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#d29922;'>🏢 Core Fundamentals ({fund_filter})</div>", unsafe_allow_html=True)
        fund_tickers = df_stocks_display['Fetch_T'].tolist()[:30] if not df_stocks_display.empty else NIFTY_50[:30]
        
        if True:
            df_fund = fetch_fundamentals_data(fund_tickers)
            if not df_fund.empty:
                html_fund = f'<table class="term-table"><thead><tr><th colspan="9" class="term-head-fund" style="background-color: #d29922; color: #161b22;">📊 FUNDAMENTAL & TECHNICAL METRICS</th></tr><tr><th style="text-align:left;">STOCK</th><th>SECTOR</th><th>LTP (₹)</th><th>TECH SCORE</th><th>MKT CAP (Cr)</th><th>P/E RATIO</th><th>DIV YIELD</th><th>52W HIGH</th><th>52W LOW</th></tr></thead><tbody>'
                for _, row in df_fund.iterrows():
                    stock_name = row["Fetch_T"].replace(".NS", "")
                    tech_row = df_stocks_display[df_stocks_display['Fetch_T'] == row["Fetch_T"]]
                    ltp_val, score_val = (float(tech_row['P'].iloc[0]), int(tech_row['S'].iloc[0])) if not tech_row.empty else (0.0, 0)
                    html_fund += f'<tr><td class="t-symbol">{stock_name}</td><td>{row["Sector"]}</td><td>{ltp_val:.2f}</td><td style="color:#ffd700;">⭐ {score_val}</td><td>{row["Market_Cap (Cr)"]:,.2f}</td><td>{row["P/E Ratio"]}</td><td>{row["Div Yield %"]}%</td><td class="text-green">₹{row["52W High"]}</td><td class="text-red">₹{row["52W Low"]}</td></tr>'
                html_fund += '</tbody></table>'
                st.markdown(html_fund, unsafe_allow_html=True)
            else: st.info("Fundamentals data not available at the moment.")
    elif watchlist_mode == "Mutual Funds 📈":
        st.markdown("<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#00BFFF;'>📈 Top 10 Mutual Funds Screener (Auto-Scanned)</div>", unsafe_allow_html=True)
        
        mf_categories = ["All Categories"] + list(MUTUAL_FUNDS.keys())
        selected_mf_cat = st.selectbox("Filter by Market Cap / Sector", mf_categories)
        
        with st.spinner("Scanning Mega Database & Ranking Top Funds..."):
            df_mf_data = fetch_mf_performance()
            
        if not df_mf_data.empty:
            if selected_mf_cat != "All Categories":
                df_mf_data = df_mf_data[df_mf_data['Category'] == selected_mf_cat]
                
            st.markdown(render_mf_table(df_mf_data), unsafe_allow_html=True)
            st.markdown("<p style='font-size:11px; color:#888;'><i>*Note: Funds are auto-ranked based on 5-Year CAGR. Returns > 20% are highlighted in Bright Green. N/A means the fund hasn't completed that many years.</i></p>", unsafe_allow_html=True)
        else:
            st.error("Failed to fetch Mutual Fund data. Yahoo Finance API might be rate-limited.")            
    elif watchlist_mode == "Terminal Tables 🗃️" and view_mode == "Heat Map":
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
        sc1, sc2 = st.columns([0.7, 0.3])
        with sc2: port_sort = st.selectbox("↕️ Sort Portfolio:", ["Default", "Day P&L ⬆️", "Day P&L ⬇️", "Total P&L ⬆️", "Total P&L ⬇️", "P&L % ⬆️", "P&L % ⬇️"], label_visibility="collapsed")
        
        # 🔥 FIX: ఇక్కడ df_stocks కి బదులు df_all_stocks ని వాడాలి! అప్పుడే పోర్ట్‌ఫోలియో కి కరెక్ట్ గా లైవ్ డేటా వస్తుంది!
        st.markdown(render_portfolio_table(df_port_saved, df_all_stocks, weekly_trends, port_sort), unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        
        with st.expander("🤖 View Portfolio Swing Advisor (Action & Levels)", expanded=False):
            # 🔥 FIX: ఇక్కడ కూడా df_all_stocks వాడాలి
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
                    if True:
                        chk_data = yf.download(f"{new_sym}.NS", period="1d", progress=False)
                        if chk_data.empty: st.error(f"❌ '{new_sym}' not found in NSE!")
                        else:
                            new_date_str = new_date.strftime("%d-%b-%Y")
                            if new_sym in df_port_saved['Symbol'].values: 
                                old_row = df_port_saved[df_port_saved['Symbol'] == new_sym].iloc[0]
                                old_qty, old_price = float(old_row['Quantity']), float(old_row['Buy_Price'])
                                total_qty = old_qty + new_qty
                                avg_price = ((old_qty * old_price) + (new_qty * new_price)) / total_qty
                                df_port_saved.loc[df_port_saved['Symbol'] == new_sym, ['Buy_Price', 'Quantity', 'Date', 'SL', 'T1', 'T2']] = [round(avg_price, 2), total_qty, new_date_str, new_sl, new_t1, new_t2]
                                st.success(f"✅ {new_sym} యావరేజ్ చేయబడింది! (New Avg: ₹{round(avg_price, 2)}, Total Qty: {int(total_qty)})")
                            else:
                                new_row = pd.DataFrame({"Symbol": [new_sym], "Buy_Price": [new_price], "Quantity": [new_qty], "Date": [new_date_str], "SL": [new_sl], "T1": [new_t1], "T2": [new_t2]})
                                df_port_saved = pd.concat([df_port_saved, new_row], ignore_index=True)
                                st.success(f"✅ {new_sym} పోర్ట్‌ఫోలియోలో యాడ్ చేయబడింది!")
                            import time
                            save_portfolio(df_port_saved); fetch_all_data.clear(); time.sleep(1.5); st.rerun()
                else: st.warning("Type a symbol first!")
        
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
                if st.button("💾 Save Edited Changes", width="stretch"): save_portfolio(edited_df); fetch_all_data.clear(); st.rerun()

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
                        buy_price, current_qty = float(port_row['Buy_Price']), int(port_row['Quantity'])
                        sell_qty = min(sell_qty, current_qty)
                        pnl_rs = (sell_price - buy_price) * sell_qty
                        pnl_pct = ((sell_price - buy_price) / buy_price) * 100
                        sell_date_str = datetime.now().strftime("%d-%b-%Y")
                        
                        df_closed = load_closed_trades()
                        new_closed_row = pd.DataFrame({"Sell_Date": [sell_date_str], "Symbol": [sell_sym], "Quantity": [sell_qty], "Buy_Price": [buy_price], "Sell_Price": [sell_price], "PnL_Rs": [pnl_rs], "PnL_Pct": [pnl_pct]})
                        df_closed = pd.concat([df_closed, new_closed_row], ignore_index=True)
                        save_closed_trades(df_closed)
                        
                        if sell_qty == current_qty: df_port_saved = df_port_saved[df_port_saved['Symbol'] != sell_sym] 
                        else: df_port_saved.loc[df_port_saved['Symbol'] == sell_sym, 'Quantity'] = current_qty - sell_qty
                        
                        save_portfolio(df_port_saved); fetch_all_data.clear(); st.rerun()

            with st.expander("📜 View Trade Book (Closed P&L Ledger)", expanded=False):
                df_closed_view = load_closed_trades()
                st.markdown(render_closed_trades_table(df_closed_view), unsafe_allow_html=True) 
                
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
                    pct_val = float(row.get('W_C', row['Day_C'])) if chart_timeframe == "Weekly Chart" else float(row['Day_C'])
                    bg = "bull-card" if pct_val > 0 else ("bear-card" if pct_val < 0 else "neut-card")
                    
                    special_icon = f"⭐{int(row['S'])}"
                    if watchlist_mode == "🤖 Today's AI Predictions":
                        if sort_mode == "🤖 AI Prob Up ⬆️": special_icon = f"🤖{int(row.get('AI_Prob', 0))}%"
                        else: special_icon = f"⭐{int(row['S'])}"
                    elif watchlist_mode == "Swing Trading 📈": 
                        strat_name = str(row.get('Strategy_Icon', ''))
                        if strat_name != "": special_icon = strat_name
                        else: special_icon = "🌟" if row.get('Is_W_Pullback', False) else "🚀"
                    elif watchlist_mode == "Day Trading Stocks 🚀": 
                        strat_name = str(row.get('Strategy_Icon', '🚀'))
                        if 'BUY' in strat_name: special_icon = "🟢 BUY"
                        elif 'SELL' in strat_name: special_icon = "🔴 SELL"
                        elif strat_name != "": special_icon = strat_name
                        else: special_icon = "🚀"
                    elif watchlist_mode == "Commodity 🛢️": special_icon = "🛢️"
                        
                    html_stk += f'<a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank" class="stock-card {bg}"><div class="t-score">{special_icon}</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{"+" if pct_val>0 else ""}{pct_val:.2f}%</div></a>'
                st.markdown(html_stk + '</div>', unsafe_allow_html=True)
                
            if not df_buy.empty: render_heatmap_section(df_buy, f"🟢 POSITIVE / BUY ({watchlist_mode})", "#3fb950")
            if not df_sell.empty: render_heatmap_section(df_sell, f"🔴 NEGATIVE / SELL ({watchlist_mode})", "#f85149")
            
            if watchlist_mode == "🤖 Today's AI Predictions":
                with st.expander("🤖 View AI Predictive Radar (Probability Based)", expanded=True): st.markdown(render_highscore_terminal_table(df_stocks_display), unsafe_allow_html=True)
            elif watchlist_mode == "Swing Trading 📈":
                with st.expander("🌊 View Swing Trading Radar (Ranked Table)", expanded=True): st.markdown(render_swing_terminal_table(df_stocks_display), unsafe_allow_html=True)
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
            if search_stock != "-- None --": display_tkrs.append(search_fetch_t)
            if watchlist_mode not in ["Terminal Tables 🗃️", "My Portfolio 💼", "Commodity 🛢️"]:
                display_tkrs.extend(df_indices['Fetch_T'].tolist())
                display_tkrs.extend(df_sectors['Fetch_T'].tolist())
            display_tkrs.extend(st.session_state.pinned_stocks)
            # 🔥 చార్ట్స్ బ్రౌజర్ ని క్రాష్ చేయకుండా Top 30 మాత్రమే తీసుకుంటున్నాం
            display_tkrs.extend(df_stocks_display['Fetch_T'].head(30).tolist())
            display_tkrs = list(set(display_tkrs)) 
            
            if display_tkrs:
                # 🔥 కొత్త క్యాచ్ ఫంక్షన్ ని ఇక్కడ వాడుతున్నాం
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

        if chart_timeframe == "Weekly Chart":
            chart_dict_to_use = weekly_charts
        elif chart_timeframe == "Daily Chart":
            chart_dict_to_use = daily_charts
        else:
            chart_dict_to_use = processed_charts

        if search_stock != "-- None --":
            render_chart_grid(pd.DataFrame([df[df['T'] == search_stock].iloc[0]]), show_pin_option=True, key_prefix="search", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)
            st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        if watchlist_mode not in ["Terminal Tables 🗃️", "My Portfolio 💼", "Fundamentals 🏢", "Commodity 🛢️"]:
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
                        else: pass
                st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)

        pinned_df = df[df['Fetch_T'].isin(st.session_state.pinned_stocks)].copy()
        unpinned_df = df_stocks_display[~df_stocks_display['Fetch_T'].isin(pinned_df['Fetch_T'].tolist())]
        
        if not pinned_df.empty:
            st.markdown("<div style='font-size:16px; font-weight:bold; margin-bottom:5px; color:#ffd700;'>📌 Pinned Priority Charts</div>", unsafe_allow_html=True)
            render_chart_grid(pinned_df, show_pin_option=True, key_prefix="pin", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)
            st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)
        
        if not unpinned_df.empty and watchlist_mode != "Fundamentals 🏢":
            if watchlist_mode == "Day Trading Stocks 🚀":
                # 🔥 .head(12) యాడ్ చేశాం
                df_buy_chart = unpinned_df[unpinned_df['Strategy_Icon'].str.contains('BUY', na=False)].head(12)
                df_sell_chart = unpinned_df[unpinned_df['Strategy_Icon'].str.contains('SELL', na=False)].head(12)
            else:
                df_buy_chart = unpinned_df[unpinned_df[sort_key] >= 0].head(12)
                df_sell_chart = unpinned_df[unpinned_df[sort_key] < 0].head(12)
                
            if not df_buy_chart.empty:
                st.markdown(f"<div style='font-size:16px; font-weight:bold; margin-top:10px; margin-bottom:5px; color:#3fb950;'>🟢 POSITIVE / BUY ({watchlist_mode})</div>", unsafe_allow_html=True)
                render_chart_grid(df_buy_chart, show_pin_option=True, key_prefix="main_buy", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)

            if not df_sell_chart.empty:
                st.markdown(f"<div style='font-size:16px; font-weight:bold; margin-top:20px; margin-bottom:5px; color:#f85149;'>🔴 NEGATIVE / SELL ({watchlist_mode})</div>", unsafe_allow_html=True)
                render_chart_grid(df_sell_chart, show_pin_option=True, key_prefix="main_sell", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)

else: 
    st.markdown("""
        <div style='padding:50px; text-align:center; border: 1px dashed #30363d; border-radius: 10px; background-color: #161b22; margin-top: 20px;'>
            <h3 style='color:#ffd700;'>⏳ Fetching Market Data...</h3>
            <p style='color:#8b949e;'>డేటా లోడ్ అవుతోంది. ఒకవేళ ఎక్కువ సమయం తీసుకుంటే, బహుశా Yahoo Finance API లిమిట్ దాటిపోయి ఉండొచ్చు. దయచేసి కొద్దిసేపు వెయిట్ చేయండి.</p>
        </div>
    """, unsafe_allow_html=True)
