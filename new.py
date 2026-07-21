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
from datetime import datetime, timedelta
from functools import lru_cache
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Market Heatmap", page_icon="📊", layout="wide")

st.markdown("""
    <style>
    div[data-testid="stNotification"] { display: none !important; }
    iframe[title="streamlit_autorefresh.st_autorefresh"] { display: none !important; }
    *[data-stale="true"] { opacity: 1 !important; filter: none !important; transition: none !important; }
    div[data-testid="stElementContainer"] { opacity: 1 !important; }
    .stApp { background-color: #0e1117; color: #ffffff; }
    .block-container { padding-top: 3.5rem !important; padding-bottom: 1rem !important; }
    .stRadio label, .stRadio p, div[role="radiogroup"] p { color: #ffffff !important; font-weight: normal !important; }
    div.stButton > button p, div.stButton > button span { color: #ffffff !important; font-weight: normal !important; font-size: 14px !important; }
    .t-name { font-size: 13px; font-weight: normal !important; margin-bottom: 2px; }
    .t-price { font-size: 17px; font-weight: normal !important; margin-bottom: 2px; }
    .t-pct { font-size: 12px; font-weight: normal !important; }
    .stock-card { border-radius: 4px; padding: 8px 4px; text-align: center; color: white !important; 
                  display: flex; flex-direction: column; justify-content: center; height: 90px; 
                  position: relative; box-shadow: 0 1px 3px rgba(0,0,0,0.3); transition: transform 0.2s; }
    .stock-card:hover { transform: scale(1.05); z-index: 10; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }
    .bull-card { background-color: #1e5f29 !important; }
    .bear-card { background-color: #b52524 !important; }
    .neut-card { background-color: #30363d !important; }
    .idx-card { background-color: #0d47a1 !important; border: 1px solid #1976d2; }
    .heatmap-grid { display: grid; grid-template-columns: repeat(10, 1fr); gap: 8px; padding: 5px 0; }
    @media screen and (max-width: 1400px) { .heatmap-grid { grid-template-columns: repeat(8, 1fr); } }
    @media screen and (max-width: 1100px) { .heatmap-grid { grid-template-columns: repeat(6, 1fr); } }
    @media screen and (max-width: 800px) { .heatmap-grid { grid-template-columns: repeat(4, 1fr); } }
    @media screen and (max-width: 600px) { .heatmap-grid { grid-template-columns: repeat(3, 1fr); gap: 6px; } .stock-card { height: 95px; } }
    </style>
""", unsafe_allow_html=True)

# --- 2. SECRETS MANAGEMENT ---
def get_gcp_credentials():
    try:
        creds_json = st.secrets["gcp_service_account"]
        if isinstance(creds_json, str):
            return json.loads(creds_json)
        return dict(creds_json)
    except Exception as e:
        st.error("❌ GCP credentials error")
        st.stop()

# --- 3. GOOGLE SHEETS CONNECTION ---
@st.cache_resource(show_spinner=False)
def init_connection():
    try:
        creds_dict = get_gcp_credentials()
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        db_sheet = client.open("Trading_DB")
        return {'portfolio': db_sheet.worksheet("Portfolio"), 'trades': db_sheet.worksheet("TradeBook")}
    except Exception as e:
        st.error(f"❌ Google Sheets error: {e}")
        st.stop()

# --- 4. DATA MANAGER ---
class DataManager:
    def __init__(self, sheets):
        self.port_ws = sheets['portfolio']
        self.trade_ws = sheets['trades']
    
    def _backup_sheet(self, ws):
        try:
            return ws.get_all_values()
        except:
            return None
    
    def _restore_sheet(self, ws, backup):
        try:
            if backup:
                ws.clear()
                ws.update(backup)
                return True
        except:
            return False
    
    @st.cache_data(ttl=300, show_spinner=False)
    def load_portfolio(_self):
        try:
            records = _self.port_ws.get_all_records()
            if not records:
                return pd.DataFrame(columns=['Symbol', 'Buy_Price', 'Quantity', 'Date', 'SL', 'T1', 'T2'])
            df = pd.DataFrame(records)
            column_map = {'Stock Name': 'Symbol', 'Buy Price': 'Buy_Price', 'Buy Date': 'Date'}
            df.rename(columns={k: v for k, v in column_map.items() if k in df.columns}, inplace=True)
            for col in ['SL', 'T1', 'T2']:
                if col not in df.columns:
                    df[col] = 0.0
            return df
        except:
            return pd.DataFrame(columns=['Symbol', 'Buy_Price', 'Quantity', 'Date', 'SL', 'T1', 'T2'])
    
    @st.cache_data(ttl=300, show_spinner=False)
    def load_closed_trades(_self):
        try:
            records = _self.trade_ws.get_all_records()
            if not records:
                return pd.DataFrame(columns=['Sell_Date', 'Symbol', 'Quantity', 'Buy_Price', 'Sell_Price', 'PnL_Rs', 'PnL_Pct'])
            df = pd.DataFrame(records)
            column_map = {'Stock Name': 'Symbol', 'Buy Price': 'Buy_Price', 'Sell Price': 'Sell_Price', 'Sell Date': 'Sell_Date', 'Profit/Loss': 'PnL_Rs'}
            df.rename(columns={k: v for k, v in column_map.items() if k in df.columns}, inplace=True)
            if 'PnL_Pct' not in df.columns:
                df['PnL_Pct'] = 0.0
            return df
        except:
            return pd.DataFrame(columns=['Sell_Date', 'Symbol', 'Quantity', 'Buy_Price', 'Sell_Price', 'PnL_Rs', 'PnL_Pct'])
    
    def save_portfolio(self, df):
        backup = self._backup_sheet(self.port_ws)
        try:
            self.port_ws.clear()
            df_clean = df.fillna("").astype(str)
            self.port_ws.update([df_clean.columns.tolist()] + df_clean.values.tolist())
            self.load_portfolio.clear()
            return True
        except Exception as e:
            if backup:
                self._restore_sheet(self.port_ws, backup)
            st.error(f"❌ Save failed: {e}")
            return False
    
    def save_closed_trades(self, df):
        backup = self._backup_sheet(self.trade_ws)
        try:
            self.trade_ws.clear()
            df_clean = df.fillna("").astype(str)
            self.trade_ws.update([df_clean.columns.tolist()] + df_clean.values.tolist())
            self.load_closed_trades.clear()
            return True
        except Exception as e:
            if backup:
                self._restore_sheet(self.trade_ws, backup)
            st.error(f"❌ Save failed: {e}")
            return False

# --- 5. FAST YAHOO FINANCE (Batch + Parallel) ---
@st.cache_data(ttl=60, show_spinner=False)
def fetch_stock_batch(symbols, period="1d", interval="1m"):
    """Batch fetch with parallel processing"""
    if not symbols:
        return None
    
    try:
        # Ensure proper suffixes
        symbols_ns = []
        for s in symbols:
            if isinstance(s, str):
                if not s.endswith(('.NS', '.BO', '.NSE', '.BSE')) and not s.startswith('^') and s not in ['INR=X']:
                    symbols_ns.append(f"{s}.NS")
                else:
                    symbols_ns.append(s)
        
        # Single API call for all symbols - MUCH FASTER
        data = yf.download(
            symbols_ns,
            period=period,
            interval=interval,
            group_by='ticker',
            progress=False,
            threads=True,  # 🔥 Parallel downloading
            prepost=False
        )
        return data
    except Exception as e:
        logger.error(f"YF batch fetch failed: {e}")
        return None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_stock_info_batch(symbols):
    """Fetch info for multiple stocks in parallel"""
    info_data = {}
    
    def fetch_single_info(symbol):
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            return symbol, {
                'name': info.get('longName', symbol),
                'sector': info.get('sector', 'Unknown'),
                'market_cap': info.get('marketCap', 0)
            }
        except:
            return symbol, {'name': symbol, 'sector': 'Unknown', 'market_cap': 0}
    
    # Parallel execution
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_single_info, s): s for s in symbols}
        for future in as_completed(futures):
            symbol, data = future.result()
            info_data[symbol] = data
    
    return info_data

# --- 6. FAST MUTUAL FUNDS API (Cached + Parallel) ---
class MutualFundAPI:
    BASE_URL = "https://api.mfapi.in/mf"
    RATE_LIMIT_DELAY = 0.5
    
    def __init__(self):
        self._last_request = 0
        self._scheme_cache = {}
    
    def _rate_limit(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.RATE_LIMIT_DELAY:
            time.sleep(self.RATE_LIMIT_DELAY - elapsed)
        self._last_request = time.time()
    
    @lru_cache(maxsize=200)
    def get_scheme_code(self, fund_name):
        """Cached scheme lookup - NO REPEATED API CALLS"""
        try:
            self._rate_limit()
            url = f"{self.BASE_URL}/search?q={requests.utils.quote(fund_name)}"
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            data = res.json()
            if not data:
                return None
            
            # Exact match first
            for item in data:
                if fund_name.lower() == item.get('schemeName', '').lower():
                    return item['schemeCode']
            return data[0]['schemeCode']
        except:
            return None
    
    def fetch_nav_history(self, scheme_code):
        try:
            self._rate_limit()
            url = f"{self.BASE_URL}/{scheme_code}"
            res = requests.get(url, timeout=12)
            res.raise_for_status()
            return res.json()
        except:
            return None
    
    def process_nav_data(self, raw_data):
        try:
            nav_data = raw_data.get("data", [])
            if not nav_data:
                return None
            df = pd.DataFrame(nav_data)
            df['date'] = pd.to_datetime(df['date'], format='mixed', dayfirst=True, errors='coerce')
            df['nav'] = pd.to_numeric(df['nav'], errors='coerce')
            df = df.dropna(subset=['nav', 'date'])
            df = df[df['nav'] > 0]
            if df.empty:
                return None
            return df.sort_values('date').set_index('date')
        except:
            return None
    
    def calculate_returns(self, df_nav):
        if df_nav is None or df_nav.empty:
            return {}
        try:
            latest_nav = df_nav['nav'].iloc[-1]
            returns = {'latest_nav': latest_nav}
            
            periods = {'1D': 1, '1W': 7, '1M': 30, '3M': 90, '6M': 180, '1Y': 365, '3Y': 1095}
            for name, days in periods.items():
                target = df_nav.index[-1] - timedelta(days=days)
                past = df_nav[df_nav.index <= target]
                if not past.empty:
                    ret = ((latest_nav - past['nav'].iloc[-1]) / past['nav'].iloc[-1]) * 100
                    returns[f'{name}_return'] = round(ret, 2)
            
            first_nav, first_date = df_nav['nav'].iloc[0], df_nav.index[0]
            years = (df_nav.index[-1] - first_date).days / 365.25
            if years > 0:
                returns['cagr'] = round((((latest_nav / first_nav) ** (1/years)) - 1) * 100, 2)
            
            return returns
        except:
            return {}
    
    def fetch_fund_parallel(self, fund_name, category):
        """Process single fund"""
        try:
            code = self.get_scheme_code(fund_name)
            if not code:
                return None
            
            raw = self.fetch_nav_history(code)
            if not raw:
                return None
            
            df_nav = self.process_nav_data(raw)
            if df_nav is None:
                return None
            
            returns = self.calculate_returns(df_nav)
            returns['fund_name'] = fund_name
            returns['category'] = category
            return returns
        except:
            return None

# --- 7. DATA SETUP ---
INDICES_MAP = {"^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY", "^INDIAVIX": "INDIA VIX", "^GSPC": "SPX", "^GDAXI": "DAX", "INR=X": "USD/INR"}
SECTOR_INDICES_MAP = {"^CNXIT": "NIFTY IT", "^CNXAUTO": "NIFTY AUTO", "^CNXMETAL": "NIFTY METAL", "^CNXPHARMA": "NIFTY PHARMA", "^CNXFMCG": "NIFTY FMCG", "^CNXENERGY": "NIFTY ENERGY", "^CNXREALTY": "NIFTY REALTY"}
COMMODITY_MAP = {"GC=F": "GOLD", "SI=F": "SILVER", "CL=F": "CRUDE OIL", "NG=F": "NATURAL GAS", "HG=F": "COPPER"}

TOP_SECTOR_STOCKS = {
    "NIFTY IT": ["TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS", "COFORGE.NS", "PERSISTENT.NS", "LTIM.NS"],
    "NIFTY AUTO": ["TATAMOTORS.NS", "M&M.NS", "MARUTI.NS", "BAJAJ-AUTO.NS", "EICHERMOT.NS", "HEROMOTOCO.NS", "TVSMOTOR.NS", "ASHOKLEY.NS"],
    "NIFTY METAL": ["TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS", "VEDL.NS", "NMDC.NS", "SAIL.NS", "JINDALSTEL.NS"],
    "NIFTY PHARMA": ["SUNPHARMA.NS", "CIPLA.NS", "DRREDDY.NS", "DIVISLAB.NS", "LUPIN.NS", "AUROPHARMA.NS", "TORNTPHARM.NS"],
    "NIFTY FMCG": ["ITC.NS", "HINDUNILVR.NS", "NESTLEIND.NS", "BRITANNIA.NS", "TATACONSUM.NS", "DABUR.NS", "GODREJCP.NS", "MARICO.NS"],
    "NIFTY ENERGY": ["RELIANCE.NS", "ONGC.NS", "NTPC.NS", "POWERGRID.NS", "COALINDIA.NS", "BPCL.NS", "TATAPOWER.NS", "IOC.NS"],
    "NIFTY REALTY": ["DLF.NS", "GODREJPROP.NS", "OBEROIRLTY.NS", "PRESTIGE.NS", "MACROTECH.NS", "PHOENIXLTD.NS"]
}

MUTUAL_FUNDS = {
    "🏆 2026 MORNINGSTAR AWARD WINNERS": [
        "Nippon India Large Cap Fund Direct Growth",
        "Parag Parikh Flexi Cap Fund Direct Growth",
        "HDFC Mid-Cap Opportunities Fund Direct Growth",
        "ICICI Prudential Short Term Fund Direct Growth",
        "Kotak Corporate Bond Fund Direct Growth",
        "ICICI Prudential All Seasons Bond Fund Direct Growth"
    ],
    "⭐ MORNINGSTAR BEST OF BREED": [
        "Nippon India Large Cap Fund Direct Growth",
        "Mirae Asset Large & Midcap Fund Direct Growth",
        "Kotak Equity Opportunities Fund Direct Growth",
        "Franklin India Flexi Cap Fund Direct Growth",
        "Nippon India Multi Cap Fund Direct Growth"
    ],
    "🔥 AGGRESSIVE SMALL CAP": [
        "Quant Small Cap Fund Direct Growth",
        "Nippon India Small Cap Fund Direct Growth",
        "SBI Small Cap Fund Direct Growth",
        "Axis Small Cap Fund Direct Growth",
        "Tata Small Cap Fund Direct Growth",
        "Kotak Small Cap Fund Direct Growth",
        "HDFC Small Cap Fund Direct Growth",
        "DSP Small Cap Fund Direct Plan Growth",
        "Bandhan Emerging Businesses Fund Direct Growth",
        "Edelweiss Small Cap Fund Direct Growth"
    ],
    "🚀 HIGH GROWTH MID CAP": [
        "Motilal Oswal Midcap Fund Direct Growth",
        "Quant Mid Cap Fund Direct Growth",
        "Nippon India Growth Fund Direct Growth",
        "HDFC Mid-Cap Opportunities Fund Direct Growth",
        "Kotak Emerging Equity Fund Direct Growth",
        "SBI Magnum Midcap Fund Direct Growth",
        "DSP Midcap Fund Direct Plan Growth",
        "Axis Midcap Fund Direct Growth",
        "Tata Mid Cap Growth Fund Direct Growth",
        "Edelweiss Mid Cap Fund Direct Growth"
    ],
    "🌟 CONSISTENT FLEXI & MULTI CAP": [
        "Parag Parikh Flexi Cap Fund Direct Growth",
        "Quant Active Fund Direct Growth",
        "Quant Flexi Cap Fund Direct Growth",
        "HDFC Flexi Cap Fund Direct Growth",
        "SBI Flexicap Fund Direct Growth",
        "Kotak Flexicap Fund Direct Growth",
        "UTI Flexi Cap Fund Direct Growth",
        "DSP Flexi Cap Fund Direct Plan Growth",
        "Axis Flexi Cap Fund Direct Growth"
    ],
    "🏭 THEMATIC & SECTORAL": [
        "Quant Infrastructure Fund Direct Growth",
        "SBI PSU Fund Direct Growth",
        "ICICI Prudential Technology Fund Direct Growth",
        "Tata Digital India Fund Direct Growth",
        "Nippon India Pharma Fund Direct Growth",
        "ICICI Prudential Infrastructure Fund Direct Growth",
        "SBI Healthcare Opportunities Fund Direct Growth",
        "Aditya Birla Sun Life PSU Equity Fund Direct Growth",
        "HDFC Defence Fund Direct Growth",
        "CPSE ETF"
    ],
    "🏛️ STABLE LARGE CAP & VALUE": [
        "SBI Contra Fund Direct Growth",
        "ICICI Prudential Bluechip Fund Direct Growth",
        "SBI Bluechip Fund Direct Growth",
        "HDFC Top 100 Fund Direct Growth",
        "Mirae Asset Large Cap Fund Direct Growth",
        "Axis Bluechip Fund Direct Growth",
        "Kotak Bluechip Fund Direct Growth",
        "Bandhan Sterling Value Fund Direct Growth",
        "Tata Large Cap Fund Direct Growth"
    ]
}

# --- 8. SESSION STATE ---
def init_session_state():
    defaults = {
        'pause_refresh': False,
        'pinned_stocks': [],
        'custom_alerts': {},
        'active_sec': None,
        'last_refresh': datetime.now(),
        'selected_tab': 'Dashboard',
        'mf_cache': {}  # 🔥 In-memory cache for MF data
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# --- 9. MAIN APP ---
def main():
    init_session_state()
    
    try:
        sheets = init_connection()
        data_mgr = DataManager(sheets)
        mf_api = MutualFundAPI()
    except Exception as e:
        st.error(f"❌ Initialization failed: {e}")
        st.stop()
    
    # Sidebar
    with st.sidebar:
        st.title("📊 Market Heatmap")
        selected_tab = st.radio("Navigation", ["Dashboard", "Portfolio", "TradeBook", "Mutual Funds", "Sectors", "Settings"])
        st.session_state.selected_tab = selected_tab
        
        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔄 Refresh", use_container_width=True):
                st.cache_data.clear()
                st.rerun()
        with col2:
            st.session_state.pause_refresh = st.toggle("⏸️ Pause", value=st.session_state.pause_refresh)
    
    # Route to pages
    if selected_tab == "Dashboard":
        render_dashboard()
    elif selected_tab == "Portfolio":
        render_portfolio(data_mgr)
    elif selected_tab == "TradeBook":
        render_tradebook(data_mgr)
    elif selected_tab == "Mutual Funds":
        render_mutual_funds_fast(mf_api)  # 🔥 Fast version
    elif selected_tab == "Sectors":
        render_sectors_fast()  # 🔥 Fast version
    elif selected_tab == "Settings":
        render_settings()

# --- 10. FAST DASHBOARD ---
def render_dashboard():
    st.header("📈 Market Dashboard")
    
    # 🔥 Single API call for ALL indices
    all_symbols = list(INDICES_MAP.keys()) + list(SECTOR_INDICES_MAP.keys())
    
    with st.spinner("Loading market data..."):
        data = fetch_stock_batch(all_symbols, period="5d", interval="1d")
    
    if data is not None:
        # Indices row
        st.subheader("🌍 Global Indices")
        cols = st.columns(len(INDICES_MAP))
        for idx, (symbol, name) in enumerate(INDICES_MAP.items()):
            with cols[idx]:
                try:
                    if isinstance(data.columns, pd.MultiIndex) and symbol in data.columns:
                        price = data[symbol]['Close'].iloc[-1]
                        prev = data[symbol]['Close'].iloc[-2]
                    else:
                        price = data['Close'].iloc[-1]
                        prev = data['Close'].iloc[-2]
                    
                    change = ((price - prev) / prev) * 100
                    color = "#1e5f29" if change >= 0 else "#b52524"
                    
                    st.markdown(f"""
                        <div style="background-color: {color}; padding: 15px; border-radius: 8px; text-align: center;">
                            <div style="font-size: 12px; opacity: 0.8;">{name}</div>
                            <div style="font-size: 20px; font-weight: bold;">{price:,.2f}</div>
                            <div style="font-size: 14px;">{'+' if change >= 0 else ''}{change:.2f}%</div>
                        </div>
                    """, unsafe_allow_html=True)
                except:
                    st.error(name)
        
        # Sectors row
        st.markdown("---")
        st.subheader("🏭 Sector Performance")
        sec_cols = st.columns(len(SECTOR_INDICES_MAP))
        for idx, (symbol, name) in enumerate(SECTOR_INDICES_MAP.items()):
            with sec_cols[idx]:
                try:
                    if isinstance(data.columns, pd.MultiIndex) and symbol in data.columns:
                        price = data[symbol]['Close'].iloc[-1]
                        prev = data[symbol]['Close'].iloc[-2]
                    else:
                        continue
                    
                    change = ((price - prev) / prev) * 100
                    color = "#1e5f29" if change >= 0 else "#b52524"
                    
                    st.markdown(f"""
                        <div style="background-color: {color}; padding: 10px; border-radius: 8px; text-align: center;">
                            <div style="font-size: 11px;">{name}</div>
                            <div style="font-size: 16px; font-weight: bold;">{change:+.2f}%</div>
                        </div>
                    """, unsafe_allow_html=True)
                except:
                    pass

# --- 11. FAST PORTFOLIO ---
def render_portfolio(data_mgr):
    st.header("💼 Portfolio")
    
    df_portfolio = data_mgr.load_portfolio()
    
    if df_portfolio.empty:
        st.info("📭 Portfolio is empty.")
        with st.form("add_stock"):
            c1, c2, c3 = st.columns(3)
            symbol = c1.text_input("Symbol", placeholder="RELIANCE").upper()
            buy_price = c2.number_input("Buy Price", min_value=0.0, step=0.05)
            quantity = c3.number_input("Quantity", min_value=1, step=1)
            
            c4, c5, c6 = st.columns(3)
            sl = c4.number_input("SL", min_value=0.0, step=0.05)
            t1 = c5.number_input("T1", min_value=0.0, step=0.05)
            t2 = c6.number_input("T2", min_value=0.0, step=0.05)
            
            if st.form_submit_button("➕ Add", use_container_width=True) and symbol and buy_price > 0:
                # Add .NS if needed
                if not symbol.endswith(('.NS', '.BO')):
                    symbol = f"{symbol}.NS"
                
                new_row = pd.DataFrame([{
                    'Symbol': symbol, 'Buy_Price': buy_price, 'Quantity': quantity,
                    'Date': datetime.now().strftime('%Y-%m-%d'), 'SL': sl, 'T1': t1, 'T2': t2
                }])
                df_portfolio = pd.concat([df_portfolio, new_row], ignore_index=True)
                if data_mgr.save_portfolio(df_portfolio):
                    st.success(f"✅ {symbol} added!")
                    st.rerun()
    else:
        # 🔥 Single batch call for all portfolio stocks
        symbols = df_portfolio['Symbol'].tolist()
        
        with st.spinner("Loading prices..."):
            current_data = fetch_stock_batch(symbols, period="1d", interval="1m")
        
        portfolio_data = []
        total_invested = total_current = 0
        
        for _, row in df_portfolio.iterrows():
            symbol = row['Symbol']
            try:
                if current_data is not None and isinstance(current_data.columns, pd.MultiIndex) and symbol in current_data.columns:
                    current_price = current_data[symbol]['Close'].iloc[-1]
                elif current_data is not None:
                    current_price = current_data['Close'].iloc[-1]
                else:
                    current_price = float(row['Buy_Price'])
            except:
                current_price = float(row['Buy_Price'])
            
            qty = float(row['Quantity'])
            buy_price = float(row['Buy_Price'])
            invested = qty * buy_price
            current_value = qty * current_price
            pnl = current_value - invested
            pnl_pct = (pnl / invested) * 100 if invested > 0 else 0
            
            total_invested += invested
            total_current += current_value
            
            portfolio_data.append({
                'Symbol': symbol.replace('.NS', ''),
                'Qty': int(qty),
                'Buy': buy_price,
                'Current': round(current_price, 2),
                'Invested': invested,
                'Value': round(current_value, 2),
                'P&L': round(pnl, 2),
                'P&L%': round(pnl_pct, 2)
            })
        
        # Summary
        total_pnl = total_current - total_invested
        total_pnl_pct = (total_pnl / total_invested) * 100 if total_invested > 0 else 0
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Invested", f"₹{total_invested:,.0f}")
        c2.metric("Current", f"₹{total_current:,.0f}")
        c3.metric("P&L", f"₹{total_pnl:,.0f}", f"{total_pnl_pct:+.1f}%")
        c4.metric("Stocks", len(portfolio_data))
        
        # Table
        df_display = pd.DataFrame(portfolio_data)
        st.dataframe(
            df_display.style.applymap(
                lambda x: 'color: #3fb950; font-weight: bold' if isinstance(x, (int, float)) and x >= 0 else 'color: #f85149; font-weight: bold',
                subset=['P&L', 'P&L%']
            ),
            use_container_width=True,
            height=350
        )

# --- 12. FAST TRADEBOOK ---
def render_tradebook(data_mgr):
    st.header("📒 Trade Book")
    df_trades = data_mgr.load_closed_trades()
    
    if df_trades.empty:
        st.info("📭 No closed trades.")
    else:
        st.dataframe(df_trades, use_container_width=True, height=400)
        
        total_pnl = df_trades['PnL_Rs'].sum() if 'PnL_Rs' in df_trades.columns else 0
        wins = len(df_trades[df_trades['PnL_Rs'] > 0]) if 'PnL_Rs' in df_trades.columns else 0
        total = len(df_trades)
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Trades", total)
        c2.metric("Win Rate", f"{(wins/total*100):.1f}%" if total > 0 else "0%")
        c3.metric("Net P&L", f"₹{total_pnl:,.0f}")

# --- 13. FAST MUTUAL FUNDS (Parallel Processing) ---
def render_mutual_funds_fast(mf_api):
    st.header("🏦 Mutual Funds")
    
    categories = list(MUTUAL_FUNDS.keys())
    selected_category = st.selectbox("Category", categories)
    funds = MUTUAL_FUNDS[selected_category]
    
    # 🔥 Check in-memory cache first
    cache_key = f"mf_{selected_category}"
    if cache_key in st.session_state.mf_cache:
        st.info("📦 Loading from cache...")
        fund_results = st.session_state.mf_cache[cache_key]
    else:
        progress_bar = st.progress(0)
        status = st.empty()
        
        fund_results = []
        
        # 🔥 Parallel processing with ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_fund = {
                executor.submit(mf_api.fetch_fund_parallel, fund, selected_category): fund 
                for fund in funds
            }
            
            completed = 0
            for future in as_completed(future_to_fund):
                completed += 1
                progress = completed / len(funds)
                progress_bar.progress(min(progress, 0.99))
                status.text(f"Loading... {completed}/{len(funds)}")
                
                result = future.result()
                if result:
                    fund_results.append(result)
        
        progress_bar.empty()
        status.empty()
        
        # Store in cache
        st.session_state.mf_cache[cache_key] = fund_results
    
    if fund_results:
        df_results = pd.DataFrame(fund_results)
        
        if '1Y_return' in df_results.columns:
            df_results = df_results.sort_values('1Y_return', ascending=False)
        
        # Display
        display_cols = ['fund_name', 'latest_nav', '1M_return', '1Y_return', 'cagr']
        available_cols = [c for c in display_cols if c in df_results.columns]
        
        st.dataframe(df_results[available_cols], use_container_width=True, height=400)
        
        # Chart
        if '1Y_return' in df_results.columns:
            fig = go.Figure(data=[go.Bar(
                x=df_results['fund_name'].str.replace(' Direct Growth', '').str.replace(' Direct Plan Growth', ''),
                y=df_results['1Y_return'],
                marker_color=['#1e5f29' if x and x >= 0 else '#b52524' for x in df_results['1Y_return']]
            )])
            fig.update_layout(
                plot_bgcolor='#0e1117', paper_bgcolor='#0e1117', font_color='#ffffff',
                xaxis_tickangle=-45, height=450, margin=dict(b=150)
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.error("❌ No data loaded")

# --- 14. FAST SECTORS ---
def render_sectors_fast():
    st.header("🌡️ Sector Heatmap")
    
    selected_sector = st.selectbox("Sector", list(TOP_SECTOR_STOCKS.keys()))
    stocks = TOP_SECTOR_STOCKS[selected_sector]
    
    # 🔥 Single batch call
    with st.spinner("Loading..."):
        sector_data = fetch_stock_batch(stocks, period="5d", interval="1d")
    
    if sector_data is not None:
        cards_html = '<div class="heatmap-grid">'
        
        for stock in stocks:
            try:
                if isinstance(sector_data.columns, pd.MultiIndex) and stock in sector_data.columns:
                    current = sector_data[stock]['Close'].iloc[-1]
                    prev = sector_data[stock]['Close'].iloc[-2]
                else:
                    continue
                
                change = ((current - prev) / prev) * 100
                card_class = "bull-card" if change > 2 else ("bear-card" if change < -2 else "neut-card")
                
                cards_html += f"""
                    <div class="stock-card {card_class}">
                        <div class="t-name">{stock.replace('.NS', '')}</div>
                        <div class="t-price">₹{current:,.1f}</div>
                        <div class="t-pct">{'+' if change >= 0 else ''}{change:.2f}%</div>
                    </div>
                """
            except:
                cards_html += f"""
                    <div class="stock-card neut-card">
                        <div class="t-name">{stock.replace('.NS', '')}</div>
                        <div class="t-price">--</div>
                        <div class="t-pct">N/A</div>
                    </div>
                """
        
        cards_html += '</div>'
        st.markdown(cards_html, unsafe_allow_html=True)

# --- 15. SETTINGS ---
def render_settings():
    st.header("⚙️ Settings")
    
    if st.button("🗑️ Clear All Cache", use_container_width=True):
        st.cache_data.clear()
        st.session_state.mf_cache = {}
        st.success("✅ Cache cleared!")
        st.rerun()
    
    st.markdown("---")
    st.subheader("Cache Status")
    st.write(f"MF Cache: {len(st.session_state.mf_cache)} categories")
    st.write(f"Last Refresh: {st.session_state.last_refresh.strftime('%H:%M:%S')}")

# --- 16. RUN ---
if __name__ == "__main__":
    main()
