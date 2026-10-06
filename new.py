import uvicorn
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import requests
import httpx  
import time   
from datetime import datetime, time as dt_time, timedelta
import webbrowser
import threading
import os
import platform
import io
import asyncio
import json

# Try importing Dhan libraries
try:
    from dhanhq import dhanhq, DhanContext, marketfeed
    DHAN_AVAILABLE = True
except ImportError:
    DHAN_AVAILABLE = False
    print("\n⚠️ 'dhanhq' library is not installed. Please run 'pip install dhanhq'. Falling back to yfinance.\n")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# ==========================================
# DHAN API SETUP
# ==========================================
DHAN_CLIENT_ID = "1110981080"
DHAN_ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJ1c2VyUmVnaW9uIjoiUjEiLCJpc3MiOiJkaGFuIiwicGFydG5lcklkIjoiIiwiZXhwIjoxNzkwOTI1NzMyLCJpYXQiOjE3OTA4MzkzMzIsInRva2VuQ29uc3VtZXJUeXBlIjoiU0VMRiIsIndlYmhvb2tVcmwiOiIiLCJkaGFuQ2xpZW50SWQiOiIxMTEwOTgxMDgwIn0.8DGvuWcgv5aqMjCKl72jGDuUu_f4YIgOaSMerTpzr1Dr9dCB_xu5qM8gbvggUhi6rboucGisSlabD8bVO71sWQ"

dhan = None
if DHAN_AVAILABLE:
    try:
        dhan_context = DhanContext(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)
        dhan = dhanhq(dhan_context)
        print("✅ Dhan REST API successfully initialized.")
    except Exception as e:
        print(f"⚠️ Failed to initialize Dhan API: {e}")

dhan_scrip_master = None
screener_cache = {}
chart_cache = {}
CACHE_TIME_SECONDS = 300  
CHART_CACHE_TIME = 5      

# ==========================================
# FASTAPI WEBSOCKETS (LIVE DATA STREAM TO BROWSER)
# ==========================================
active_connections = []
main_event_loop = None

@app.on_event("startup")
async def startup_event():
    global main_event_loop
    main_event_loop = asyncio.get_running_loop()
    if DHAN_AVAILABLE and dhan is not None:
        threading.Thread(target=start_dhan_websocket, daemon=True).start()

@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.remove(websocket)

async def broadcast_live_tick(symbol: str, ltp: float, vol: int, timestamp: int):
    message = json.dumps({
        "type": "tick",
        "symbol": symbol,
        "price": ltp,
        "volume": vol,
        "time": timestamp
    })
    for connection in active_connections:
        try:
            await connection.send_text(message)
        except Exception:
            pass

# ==========================================
# DHAN MARKETFEED (TICK-BY-TICK FROM DHAN)
# ==========================================
def on_message(ws, message):
    try:
        if 'LTP' in message or 'last_price' in message:
            ltp = float(message.get('LTP', message.get('last_price', 0)))
            sec_id = str(message.get('security_id', ''))
            vol = int(message.get('volume', 0))
            ts = int(time.time())
            
            if ltp > 0 and main_event_loop and main_event_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    broadcast_live_tick(sec_id, ltp, vol, ts), 
                    main_event_loop
                )
    except Exception as e:
        pass

def start_dhan_websocket():
    try:
        print("⏳ Starting Dhan Live Market Feed (WebSockets)...")
        
        # 1 = Ticker data code mapping as dictionary
        instruments_dict = {
            1: [
                (0, "13"),      # Index: Nifty 50
                (0, "26009")    # Index: Bank Nifty
            ]
        }
        
        ws_context = DhanContext(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)
        
        feed = marketfeed.MarketFeed(
            ws_context,         
            instruments_dict,   
            "v2",               
            on_message=on_message
        )
        feed.run_forever()
    except Exception as e:
        print(f"❌ Failed to start Dhan WebSockets: {e}")

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def load_dhan_scrip_master():
    global dhan_scrip_master
    if dhan_scrip_master is None:
        try:
            res = requests.get("https://images.dhan.co/api-data/api-scrip-master.csv")
            dhan_scrip_master = pd.read_csv(io.StringIO(res.text), low_memory=False)
        except Exception:
            dhan_scrip_master = pd.DataFrame()

def get_dhan_security_info(ticker):
    global dhan_scrip_master
    if dhan_scrip_master is None or dhan_scrip_master.empty:
        load_dhan_scrip_master()
    if dhan_scrip_master.empty:
        return None, None, None
    search_sym = ticker.replace(".NS", "").replace(".BO", "").strip().upper()
    if search_sym in ["^NSEI", "NIFTY", "NIFTY 50", "NIFTY50"]: search_sym = "Nifty 50"
    elif search_sym in ["^NSEBANK", "BANKNIFTY", "BANK NIFTY"]: search_sym = "Nifty Bank"

    try:
        if search_sym in ["Nifty 50", "Nifty Bank"]:
            row = dhan_scrip_master[(dhan_scrip_master['SEM_CUSTOM_SYMBOL'] == search_sym) & (dhan_scrip_master['SEM_EXM_EXCH_ID'] == 'IDX_I')]
            if not row.empty: return str(row.iloc[0]['SEM_SMST_SECURITY_ID']), "IDX_I", "INDEX"
        else:
            row = dhan_scrip_master[(dhan_scrip_master['SEM_TRADING_SYMBOL'] == search_sym) & (dhan_scrip_master['SEM_EXM_EXCH_ID'] == 'NSE')]
            if not row.empty: return str(row.iloc[0]['SEM_SMST_SECURITY_ID']), "NSE", "EQUITY"
    except Exception:
        pass
    return None, None, None

def calculate_fvg(df, offset):
    fvgs = []
    for i in range(2, len(df)):
        if df['Low'].iloc[i] > df['High'].iloc[i-2]:
            fvgs.append({'time': int(df.index[i].timestamp()) + offset, 'type': 'bullish', 'price': float(df['Low'].iloc[i])})
        elif df['High'].iloc[i] < df['Low'].iloc[i-2]:
            fvgs.append({'time': int(df.index[i].timestamp()) + offset, 'type': 'bearish', 'price': float(df['High'].iloc[i])})
    return fvgs

def calc_kalman(src, length, R=0.01, Q=0.1):
    if len(src) == 0: return pd.Series(dtype=float)
    est = np.zeros(len(src))
    err = np.ones(len(src))
    meas = R * length
    est[0] = src.iloc[0]
    for i in range(1, len(src)):
        pred = est[i-1]
        gain = err[i-1] / (err[i-1] + meas)
        est[i] = pred + gain * (src.iloc[i] - pred)
        err[i] = (1 - gain) * err[i-1] + Q / length
    return pd.Series(est, index=src.index)

def get_market_minutes():
    now = datetime.now()
    if now.weekday() >= 5 or now.time() >= dt_time(15, 30): return 375
    if now.time() < dt_time(9, 15): return 375
    open_time = now.replace(hour=9, minute=15, second=0, microsecond=0)
    return max(15, min(375, int((now - open_time).total_seconds() / 60)))

# ==========================================
# REST ENDPOINTS
# ==========================================
@app.get("/api/search")
async def search_ticker(query: str, market: str = "NSE"):
    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}&quotesCount=10&newsCount=0"
        headers = {'User-Agent': 'Mozilla/5.0'}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            data = response.json()
        results = []
        if 'quotes' in data:
            for q in data['quotes']:
                symbol = q.get('symbol', '')
                exch = q.get('exchDisp', '')
                shortname = q.get('shortname', '')
                if market == "NSE":
                    if symbol.endswith('.NS') or symbol.endswith('.BO') or 'India' in exch or exch in ['NSE', 'BSE'] or symbol in ['^NSEI', '^NSEBANK']:
                        results.append({"symbol": symbol, "name": shortname, "exch": exch})
                else:
                    results.append({"symbol": symbol, "name": shortname, "exch": exch})
        return {"results": results[:8]}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/api/screener")
def run_screener(strategy: str = "kalman"):
    global screener_cache
    current_time = time.time()
    if strategy in screener_cache:
        cached_data, saved_time = screener_cache[strategy]
        if (current_time - saved_time) < CACHE_TIME_SECONDS:
            return {"data": cached_data, "cached": True}
    try:
        index_results = []
        try:
            idx_df = yf.download(["^NSEI", "^NSEBANK"], period="5d", interval="5m", progress=False, group_by='ticker', threads=True)
            for idx_sym, idx_label in [("^NSEI", "NIFTY 50"), ("^NSEBANK", "BANK NIFTY")]:
                try:
                    idf = idx_df[idx_sym].dropna(subset=['Close']) if isinstance(idx_df.columns, pd.MultiIndex) else idx_df
                    if not idf.empty and len(idf) >= 2:
                        iltp = float(idf['Close'].iloc[-1])
                        iprev = float(idf['Close'].iloc[-2])
                        ichg = round(((iltp - iprev) / iprev) * 100, 2)
                        vol = float(idf['Volume'].iloc[-1]) if 'Volume' in idf.columns else 0
                        tag_txt = "🟢 Bullish" if ichg >= 0 else "🔴 Bearish"
                        color_code = "#00E676" if ichg >= 0 else "#FF1744"
                        index_results.append({"symbol": idx_sym, "name": idx_label, "price": round(iltp, 2), "chg": ichg, "vol": vol, "tag": f"📌 {tag_txt}", "color": color_code, "is_index": True})
                except Exception: pass
        except Exception: pass
        fno_stocks = ["AARTIIND", "ABB", "ABBOTINDIA", "ABCAPITAL", "ABFRL", "ACC", "ADANIENSOL", "ADANIENT", "ADANIPORTS", "ALKEM", "AMBUJACEM", "ANGELONE", "APOLLOHOSP", "APOLLOTYRE", "ASHOKLEY", "ASIANPAINT", "ASTRAL", "ATUL", "AUBANK", "AUROPHARMA", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE", "BALKRISIND", "BALRAMCHIN", "BANDHANBNK", "BANKBARODA", "BATAINDIA", "BEL", "BERGEPAINT", "BHARATFORG", "BHARTIARTL", "BHEL", "BIOCON", "BOSCHLTD", "BPCL", "BRITANNIA", "BSE", "CANBK", "CANFINHOME", "CDSL", "CHAMBLFERT", "CHOLAFIN", "CIPLA", "COALINDIA", "COFORGE", "COLPAL", "CONCOR", "COROMANDEL", "CROMPTON", "CUB", "CUMMINSIND", "DABUR", "DALBHARAT", "DEEPAKNTR", "DIVISLAB", "DIXON", "DLF", "DRREDDY", "EICHERMOT", "ESCORTS", "EXIDEIND", "FEDERALBNK", "GAIL", "GLENMARK", "GMRINFRA", "GNFC", "GODREJCP", "GODREJPROP", "GRANULES", "GRASIM", "GUJGASLTD", "HAL", "HAVELLS", "HCLTECH", "HDFCAMC", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDCOPPER", "HINDPETRO", "HINDUNILVR", "HUDCO", "ICICIBANK", "ICICIGI", "ICICIPRULI", "IDEA", "IDFCFIRSTB", "IEX", "IGL", "INDHOTEL", "INDIACEM", "INDIAMART", "INDIGO", "INDUSINDBK", "INDUSTOWER", "INFY", "IOC", "IPCALAB", "IRCTC", "IRFC", "ITC", "JINDALSTEL", "JSWSTEEL", "JUBLFOOD", "KOTAKBANK", "LALPATHLAB", "LAURUSLABS", "LICHSGFIN", "LT", "LTIM", "LTTS", "LUPIN", "M&M", "M&MFIN", "MANAPPURAM", "MARICO", "MARUTI", "MCX", "METROPOLIS", "MFSL", "MGL", "MOTHERSON", "MPHASIS", "MRF", "MUTHOOTFIN", "NATIONALUM", "NAUKRI", "NAVINFLUOR", "NCC", "NESTLEIND", "NMDC", "NTPC", "OBEROIRLTY", "OFSS", "ONGC", "PAGEIND", "PEL", "PERSISTENT", "PETRONET", "PFC", "PIDILITIND", "PIIND", "PNB", "POLYCAB", "POWERGRID", "PRESTIGE", "PVRINOX", "RAMCOCEM", "RBLBANK", "RECLTD", "RELIANCE", "SAIL", "SBICARD", "SBILIFE", "SBIN", "SHREECEM", "SHRIRAMFIN", "SIEMENS", "SRF", "SUNPHARMA", "SUNTV", "SYNGENE", "TATACHEM", "TATACOMM", "TATACONSUM", "TATAMOTORS", "TATAPOWER", "TATASTEEL", "TCS", "TECHM", "TITAN", "TORNTPHARM", "TRENT", "TVSMOTOR", "UBL", "ULTRACEMCO", "UNIONBANK", "UPL", "VEDL", "VOLTAS", "WIPRO", "ZEEL", "ZOMATO", "ZYDUSLIFE", "PHOENIXLTD"]
        watch_list = [f"{sym}.NS" for sym in fno_stocks]
        stock_results = []
        if strategy == "kalman":
            df_batch = yf.download(watch_list, period="5d", interval="5m", progress=False, group_by='ticker', threads=True)
            for tkr in watch_list:
                try: df = df_batch[tkr].dropna() if isinstance(df_batch.columns, pd.MultiIndex) else df_batch
                except: continue
                if df.empty or len(df) < 20: continue
                df['VWAP'] = ta.vwap(high=df['High'], low=df['Low'], close=df['Close'], volume=df['Volume']) if (df['Volume'] > 0).any() else (df['High'] + df['Low'] + df['Close']) / 3
                df['SK'], df['LK'] = calc_kalman(df['Close'], 10), calc_kalman(df['Close'], 20)
                sk_current, lk_current, sk_prev, lk_prev = float(df['SK'].iloc[-1]), float(df['LK'].iloc[-1]), float(df['SK'].iloc[-2]), float(df['LK'].iloc[-2])
                ltp, vwap_val, vol = float(df['Close'].iloc[-1]), float(df['VWAP'].iloc[-1]), float(df['Volume'].iloc[-1]) if 'Volume' in df.columns else 0
                base_long, base_short = (sk_current > lk_current) and not (sk_prev > lk_prev), (sk_prev > lk_prev) and not (sk_current > lk_current)
                chg = ((ltp - df['Close'].iloc[-2]) / df['Close'].iloc[-2]) * 100
                if base_long and ltp > (vwap_val * 1.002): stock_results.append({"symbol": tkr, "name": tkr.replace('.NS',''), "price": round(ltp,2), "chg": round(chg,2), "vol": vol, "tag": "🟢 Kalman BUY", "color": "#13bd6e"})
                elif base_short: stock_results.append({"symbol": tkr, "name": tkr.replace('.NS',''), "price": round(ltp,2), "chg": round(chg,2), "vol": vol, "tag": "🔴 Kalman EXIT", "color": "#af0d4b"})
        elif strategy in ["minervini", "weinstein", "darvas", "zanger", "king"]:
            minutes_passed = get_market_minutes()
            df_batch = yf.download(watch_list, period="2y", interval="1d", progress=False, group_by='ticker', threads=True)
            for tkr in watch_list:
                try: df = df_batch[tkr].dropna() if isinstance(df_batch.columns, pd.MultiIndex) else df_batch
                except: continue
                if df.empty or len(df) < 150: continue
                df['SMA50'], df['SMA150'], df['SMA200'] = df['Close'].rolling(50).mean(), df['Close'].rolling(150).mean(), df['Close'].rolling(200).mean()
                df['SMA200_20D'], df['SMA150_20D'] = df['SMA200'].shift(20), df['SMA150'].shift(20)
                df['High52W'], df['Low52W'] = df['High'].rolling(252).max(), df['Low'].rolling(252).min()
                df['Box_Top20'], df['Box_Bot20'] = df['High'].shift(1).rolling(20).max(), df['Low'].shift(1).rolling(20).min()
                df['Vol_SMA50'] = df['Volume'].rolling(50).mean()
                ltp, prev_c, o, h, l, vol = float(df['Close'].iloc[-1]), float(df['Close'].iloc[-2]), float(df['Open'].iloc[-1]), float(df['High'].iloc[-1]), float(df['Low'].iloc[-1]), float(df['Volume'].iloc[-1])
                sma50, sma150 = float(df['SMA50'].iloc[-1]), float(df['SMA150'].iloc[-1])
                sma200 = float(df['SMA200'].iloc[-1]) if not pd.isna(df['SMA200'].iloc[-1]) else 0
                sma200_20d = float(df['SMA200_20D'].iloc[-1]) if not pd.isna(df['SMA200_20D'].iloc[-1]) else 0
                sma150_20d = float(df['SMA150_20D'].iloc[-1]) if not pd.isna(df['SMA150_20D'].iloc[-1]) else 0
                h52, l52 = float(df['High52W'].iloc[-1]), float(df['Low52W'].iloc[-1])
                box_top, box_bot = float(df['Box_Top20'].iloc[-1]), float(df['Box_Bot20'].iloc[-1])
                vol_sma = float(df['Vol_SMA50'].iloc[-1])
                expected_vol = (vol_sma / 375.0) * minutes_passed if vol_sma > 0 else 1
                vol_x, chg = round(vol / expected_vol, 2) if expected_vol > 0 else 1.0, ((ltp - prev_c) / prev_c) * 100
                is_match, tag, color = False, "", ""
                if strategy == "minervini":
                    if ltp > sma150 and (ltp > sma200 or sma200 == 0) and ((sma150 > sma200) or sma200 == 0) and ((sma200 > sma200_20d) or sma200 == 0) and sma50 > sma150 and ltp > sma50 and ltp >= l52 * 1.25 and ltp >= h52 * 0.75: is_match, tag, color = True, "📈 M-VCP", "#2ea043"
                elif strategy == "weinstein":
                    if ltp > sma150 and (sma150 > sma150_20d if sma150_20d > 0 else True) and sma50 > sma150 and ltp >= h52 * 0.75 and ltp >= l52 * 1.25: is_match, tag, color = True, "📈 Stage 2", "#00BFFF"
                elif strategy == "darvas":
                    if ltp > sma50 and sma50 > sma150 and ltp >= (box_top * 0.99) and (((box_top - box_bot) / box_bot) <= 0.20 if box_bot > 0 else False) and ltp >= h52 * 0.85 and vol_x >= 1.0: is_match, tag, color = True, "📦 Darvas", "#FFD700"
                elif strategy == "zanger":
                    if vol_x >= 1.1 and ltp > sma50 and sma50 > sma150 and ((ltp - l) / (h - l + 0.001)) >= 0.55 and ltp >= (box_top * 0.97): is_match, tag, color = True, "💥 Zanger", "#FF4500"
                elif strategy == "king":
                    if ((sma150 > sma200) or sma200 == 0) and sma50 > sma150 and ((l <= sma50 * 1.03 and ltp >= sma50 * 0.98) or (l <= sma150 * 1.03 and ltp >= sma150 * 0.98) or (sma200 > 0 and l <= sma200 * 1.03 and ltp >= sma200 * 0.98)) and ((ltp > o) or (chg >= 0.5)) and vol_x >= 0.9: is_match, tag, color = True, "👑 King Bounce", "#9c27b0"
                if is_match: stock_results.append({"symbol": tkr, "name": tkr.replace('.NS',''), "price": round(ltp,2), "chg": round(chg,2), "vol": vol, "tag": tag, "color": color})
        elif strategy == "theta_gainers":
            df_batch_5m = yf.download(watch_list, period="5d", interval="5m", progress=False, group_by='ticker', threads=True)
            df_batch_1d = yf.download(watch_list, period="5d", interval="1d", progress=False, group_by='ticker', threads=True)
            for tkr in watch_list:
                try: 
                    df_5m, df_1d = df_batch_5m[tkr].dropna() if isinstance(df_batch_5m.columns, pd.MultiIndex) else df_batch_5m, df_batch_1d[tkr].dropna() if isinstance(df_batch_1d.columns, pd.MultiIndex) else df_batch_1d
                except: continue
                if df_5m.empty or len(df_5m) < 50 or df_1d.empty or len(df_1d) < 2: continue
                st = ta.supertrend(df_5m['High'], df_5m['Low'], df_5m['Close'], length=7, multiplier=3.0)
                if st is None or st.empty: continue
                df_5m['ST'], df_5m['ST_DIR'] = st.iloc[:, 0], st.iloc[:, 1]
                prev_day = df_1d.iloc[-2] 
                pp = (prev_day['High'] + prev_day['Low'] + prev_day['Close']) / 3
                r1, s1 = (2 * pp) - prev_day['Low'], (2 * pp) - prev_day['High']
                ltp, prev_c, vol = float(df_5m['Close'].iloc[-1]), float(df_5m['Close'].iloc[-2]), float(df_5m['Volume'].iloc[-1]) if 'Volume' in df_5m.columns else 0
                chg, current_st, current_st_dir = ((ltp - prev_c) / prev_c) * 100, float(df_5m['ST'].iloc[-1]), int(df_5m['ST_DIR'].iloc[-1])
                if (ltp > current_st) and (ltp > r1) and (current_st_dir == 1): stock_results.append({"symbol": tkr, "name": tkr.replace('.NS',''), "price": round(ltp,2), "chg": round(chg,2), "vol": vol, "tag": "🟢 ST+Pivot BUY", "color": "#13bd6e"})
                elif (ltp < current_st) and (ltp < s1) and (current_st_dir == -1): stock_results.append({"symbol": tkr, "name": tkr.replace('.NS',''), "price": round(ltp,2), "chg": round(chg,2), "vol": vol, "tag": "🔴 ST+Pivot SELL", "color": "#af0d4b"})
        final_list = index_results + sorted(stock_results, key=lambda x: x['chg'], reverse=True)
        screener_cache[strategy] = (final_list, current_time)
        return {"data": final_list, "cached": False}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/api/data")
def get_chart_data(ticker: str, timeframe: str = "5m", market: str = "US"):
    global chart_cache
    cache_key = f"{ticker}_{timeframe}_{market}"
    current_time = time.time()

    if cache_key in chart_cache:
        cached_res, saved_time = chart_cache[cache_key]
        if (current_time - saved_time) < CHART_CACHE_TIME:
            return cached_res

    try:
        ticker_clean = ticker.strip().upper()
        if ticker_clean in ["NIFTY", "^NSEI", "NIFTY 50", "NIFTY50"]: ticker = "^NSEI"
        elif ticker_clean in ["BANKNIFTY", "^NSEBANK", "BANK NIFTY"]: ticker = "^NSEBANK"
        elif market == "NSE" and not ticker.endswith(".NS") and not ticker.startswith("^"): ticker = f"{ticker}.NS"
        elif market == "CRYPTO" and not ticker.endswith("-USD"): ticker = f"{ticker}-USD"

        tf_map = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "4h": "1h", "1d": "1d", "1W": "1wk"}
        period_map = {"1m": "5d", "5m": "60d", "15m": "30d", "30m": "30d", "1h": "300d", "4h": "300d", "1d": "max", "1W": "max"}
        
        yf_tf = tf_map.get(timeframe, "5m")
        period = period_map.get(timeframe, "15d")

        df = pd.DataFrame()
        
        # --- DHAN API DATA FETCH LOGIC (INTRADAY) ---
        if DHAN_AVAILABLE and dhan is not None and market == "NSE":
            sec_id, exch_seg, inst_type = get_dhan_security_info(ticker)
            if sec_id:
                try:
                    res = dhan.intraday_minute_charts(
                        security_id=sec_id,
                        exchange_segment=exch_seg,
                        instrument_type=inst_type
                    )
                    
                    if res.get('status') == 'success' and 'data' in res:
                        raw_data = res['data']
                        if raw_data.get('start_Time'):
                            df = pd.DataFrame({
                                'Date': pd.to_datetime(raw_data['start_Time']),
                                'Open': raw_data['open'],
                                'High': raw_data['high'],
                                'Low': raw_data['low'],
                                'Close': raw_data['close'],
                                'Volume': raw_data['volume']
                            })
                            df.set_index('Date', inplace=True)
                            if timeframe == "5m":
                                df = df.resample('5min', closed='left', label='left').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()
                            elif timeframe == "15m":
                                df = df.resample('15min', closed='left', label='left').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()
                except Exception as e:
                    print(f"Dhan API Fetch Error for {ticker}: {e}")
                    df = pd.DataFrame() 
        
        # --- FALLBACK TO YFINANCE ---
        if df.empty:
            df = yf.download(ticker, period=period, interval=yf_tf, progress=False)
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

        if df.empty or len(df) == 0: 
            return JSONResponse(content={"error": f"No data found for {ticker}"}, status_code=404)
        
        df = df.dropna(subset=['Close'])

        # Daily Data for Pivots
        df_daily_raw = yf.download(ticker, period="30d", interval="1d", progress=False)
        if isinstance(df_daily_raw.columns, pd.MultiIndex): df_daily_raw.columns = df_daily_raw.columns.get_level_values(0)
        df_daily_raw = df_daily_raw.dropna(subset=['Close'])
        
        if not df_daily_raw.empty:
            df_daily_raw['PP'] = (df_daily_raw['High'].shift(1) + df_daily_raw['Low'].shift(1) + df_daily_raw['Close'].shift(1)) / 3
            df_daily_raw['R1'] = (2 * df_daily_raw['PP']) - df_daily_raw['Low'].shift(1)
            df_daily_raw['S1'] = (2 * df_daily_raw['PP']) - df_daily_raw['High'].shift(1)
            try: df_daily_raw['Date_Str'] = pd.to_datetime(df_daily_raw.index).tz_localize(None).strftime('%Y-%m-%d')
            except: df_daily_raw['Date_Str'] = pd.to_datetime(df_daily_raw.index).strftime('%Y-%m-%d')
            pivot_map_r1 = df_daily_raw.set_index('Date_Str')['R1'].to_dict()
            pivot_map_s1 = df_daily_raw.set_index('Date_Str')['S1'].to_dict()
        else:
            pivot_map_r1, pivot_map_s1 = {}, {}

        if timeframe == "4h":
            if df.index.tz is not None: df.index = df.index.tz_localize(None) 
            df = df.resample('4h', closed='left', label='left').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'})
            df = df.dropna()

        has_vol = 'Volume' in df.columns and (df['Volume'] > 0).any()
        if not has_vol: df['Volume'] = 0

        df['EMA10'] = ta.ema(df['Close'], length=10)
        df['EMA21'] = ta.ema(df['Close'], length=21)
        df['EMA50'] = ta.ema(df['Close'], length=50)
        df['EMA200'] = ta.ema(df['Close'], length=200)
        df['RSI14'] = ta.rsi(df['Close'], length=14)
        
        typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
        if has_vol:
            volume = df["Volume"].fillna(0)
            pv = typical_price * volume
            session_key = pd.to_datetime(df.index).date
            cum_pv = pv.groupby(session_key).cumsum()
            cum_vol = volume.groupby(session_key).cumsum()
            df["VWAP"] = cum_pv / cum_vol.replace(0, np.nan)
            df["Vol_SMA375"] = ta.sma(df["Volume"], length=min(375, len(df)))
        else:
            session_key = pd.to_datetime(df.index).date
            session_count = pd.Series(1.0, index=df.index).groupby(session_key).cumsum()
            session_price_sum = typical_price.groupby(session_key).cumsum()
            df["VWAP"] = session_price_sum / session_count
            df["Vol_SMA375"] = 0

        bb = ta.bbands(df["Close"], length=20, std=2)
        if bb is not None and not bb.empty: df["BBL"], df["BBM"], df["BBU"] = bb.iloc[:, 0], bb.iloc[:, 1], bb.iloc[:, 2]
        else: df["BBL"], df["BBM"], df["BBU"] = np.nan, np.nan, np.nan
        
        st7 = ta.supertrend(df['High'], df['Low'], df['Close'], length=7, multiplier=3.0)
        if st7 is not None and not st7.empty: df['ST7'] = st7.iloc[:, 0]
        else: df['ST7'] = np.nan

        len_fast, len_slow, len_150 = 10, (20 if timeframe in ["1m", "5m"] else 50), 150
        df['SK'], df['LK'], df['EK'] = calc_kalman(df['Close'], len_fast), calc_kalman(df['Close'], len_slow), calc_kalman(df['Close'], len_150)

        is_intraday = timeframe in ["1m", "5m", "15m", "30m", "1h", "4h"]
        if is_intraday:
            try: df_dates_str = pd.to_datetime(df.index).tz_localize(None).strftime('%Y-%m-%d')
            except: df_dates_str = pd.to_datetime(df.index).strftime('%Y-%m-%d')
            df['R1'] = [pivot_map_r1.get(d, np.nan) for d in df_dates_str]
            df['S1'] = [pivot_map_s1.get(d, np.nan) for d in df_dates_str]
        else:
            df['R1'], df['S1'] = np.nan, np.nan

        df['PivotHigh'] = df['High'][(df['High'] > df['High'].shift(1)) & (df['High'] > df['High'].shift(-1)) & (df['High'] > df['High'].shift(2)) & (df['High'] > df['High'].shift(-2))]
        df['PivotLow'] = df['Low'][(df['Low'] < df['Low'].shift(1)) & (df['Low'] < df['Low'].shift(-1)) & (df['Low'] < df['Low'].shift(2)) & (df['Low'] < df['Low'].shift(-2))]
        df['Support'], df['Resistance'] = df['PivotLow'].ffill(), df['PivotHigh'].ffill()

        offset = 19800 if is_intraday else 0
        fvgs = calculate_fvg(df, offset)
        df = df.replace({np.nan: None}) 
        
        candles, indicators = [], {"RSI": [], "VWAP": [], "BBU": [], "BBM": [], "BBL": [], "EMA21": [], "EMA50": [], "EMA200": [], "ST": [], "SK": [], "LK": [], "EK": [], "R1": [], "S1": []}
        snr_reversals = []

        for i in range(len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i-1] if i > 0 else None
            timestamp = df.index[i]
            try: time_val = int(timestamp.timestamp()) + offset
            except: time_val = int(pd.Timestamp(timestamp).timestamp()) + offset

            o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
            vol = float(row["Volume"]) if row.get("Volume") is not None else 0.0
            vol_sma_val = float(row["Vol_SMA375"]) if row.get("Vol_SMA375") is not None else 0
            vwap_val = float(row["VWAP"]) if row.get("VWAP") is not None else c
            ema10_val = float(row["EMA10"]) if row.get("EMA10") is not None else c
            
            is_bull = c >= o
            is_high_vol = vol > (vol_sma_val * 1.5) if vol_sma_val > 0 else False
            is_strong_up, is_strong_down = (c > vwap_val) and (c > ema10_val), (c < vwap_val) and (c < ema10_val)
            
            if is_high_vol:
                if is_strong_up and is_bull: c_color = '#006400' 
                elif is_strong_down and not is_bull: c_color = '#8B0000' 
                else: c_color = '#FFD700' if is_bull else '#FF8C00'
            else:
                c_color = 'rgba(46, 160, 67, 0.4)' if is_bull else 'rgba(218, 54, 51, 0.4)'
            
            candles.append({"time": time_val, "open": o, "high": h, "low": l, "close": c, "value": vol, "color": c_color, "borderColor": c_color, "wickColor": c_color})
            
            body, upper_wick, lower_wick = max(abs(c - o), 0.01), h - max(c, o), min(c, o) - l
            is_hammer, is_shooting_star = (lower_wick >= body * 1.5) and (upper_wick <= body * 1.0), (upper_wick >= body * 1.5) and (lower_wick <= body * 1.0)
            
            is_bull_engulf, is_bear_engulf = False, False
            if prev_row is not None:
                po, ph, pl, pc = float(prev_row['Open']), float(prev_row['High']), float(prev_row['Low']), float(prev_row['Close'])
                is_bull_engulf = (pc < po) and (c > o) and (c > po) and (o < pc)
                is_bear_engulf = (pc > po) and (c < o) and (c < po) and (o > pc)
                
            is_bullish_rev, is_bearish_rev = is_hammer or is_bull_engulf, is_shooting_star or is_bear_engulf

            levels = []
            for k in ['EMA200', 'VWAP', 'Support', 'Resistance']:
                if row.get(k) is not None: levels.append(float(row[k]))
            
            threshold = c * 0.003
            touched_bull = any((abs(l - lvl) <= threshold or (l <= lvl and c >= lvl)) for lvl in levels)
            touched_bear = any((abs(h - lvl) <= threshold or (h >= lvl and c <= lvl)) for lvl in levels)
            
            if is_bullish_rev and touched_bull: snr_reversals.append({'time': time_val, 'type': 'bullish', 'price': l, 'text': 'S&R Buy'})
            elif is_bearish_rev and touched_bear: snr_reversals.append({'time': time_val, 'type': 'bearish', 'price': h, 'text': 'S&R Sell'})

            for ind in ["RSI14", "EMA21", "EMA50", "EMA200", "VWAP", "SK", "LK", "EK", "BBL", "BBM", "BBU", "ST7", "R1", "S1"]:
                val = row.get(ind)
                if val is not None and not pd.isna(val):
                    key = ind.replace("14", "").replace("7", "")
                    indicators[key].append({"time": time_val, "value": float(val)})

        result = {"ticker": ticker, "candles": candles, "indicators": indicators, "fvg": fvgs, "snr_reversals": snr_reversals}
        chart_cache[cache_key] = (result, current_time) 
        return result

    except Exception as e: return JSONResponse(content={"error": str(e)}, status_code=500)

def open_in_chrome(url):
    try:
        sys_name = platform.system()
        if sys_name == "Windows":
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%USERPROFILE%\AppData\Local\Google\Chrome\Application\chrome.exe")
            ]
            for path in chrome_paths:
                if os.path.exists(path):
                    webbrowser.register('chrome', None, webbrowser.BackgroundBrowser(path))
                    webbrowser.get('chrome').open(url)
                    return
            webbrowser.open(url)
        elif sys_name == "Darwin":
            webbrowser.get("open -a /Applications/Google\\ Chrome.app %s").open(url)
        else:
            webbrowser.get("google-chrome").open(url)
    except Exception as e:
        webbrowser.open(url)

if __name__ == "__main__":
    HOST = "127.0.0.1"
    PORT = 5000
    DASHBOARD_URL = f"http://{HOST}:{PORT}/static/index.html"

    print("\n" + "=" * 70)
    print("🚀 TRADING DASHBOARD STARTING...")
    print("=" * 70)
    print(f"📊 Dashboard : {DASHBOARD_URL}")
    print(f"🔌 API       : http://{HOST}:{PORT}")
    print("=" * 70 + "\n")

    threading.Timer(2.0, lambda: open_in_chrome(DASHBOARD_URL)).start()
    uvicorn.run("app:app", host=HOST, port=PORT, reload=True)
