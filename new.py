import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import concurrent.futures
from datetime import datetime

# --- 1. PAGE CONFIGURATION & STATE ---
st.set_page_config(page_title="Legendary Swing Scanner", page_icon="📈", layout="wide")

if 'pinned_stocks' not in st.session_state:
    st.session_state.pinned_stocks = []
if 'custom_alerts' not in st.session_state:
    st.session_state.custom_alerts = {}

# 🔥 CSS ఫర్ పర్ఫెక్ట్ చార్ట్ గ్రిడ్ 
st.markdown("""
    <style>
    .stApp { background-color: #0e1117; color: #ffffff; }
    .block-container { padding-top: 2rem !important; padding-bottom: 1rem !important; }
    .stRadio label { color: #ffffff !important; font-weight: normal !important; }
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { display: grid !important; gap: 12px !important; align-items: start !important; }
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div:nth-child(1) { display: none !important; }
    @media screen and (min-width: 1700px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(6, 1fr) !important; } }
    @media screen and (min-width: 1400px) and (max-width: 1699px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(5, 1fr) !important; } }
    @media screen and (min-width: 1100px) and (max-width: 1399px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(4, 1fr) !important; } }
    @media screen and (min-width: 850px) and (max-width: 1099px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(3, 1fr) !important; } }
    @media screen and (max-width: 849px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(2, 1fr) !important; } }
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div[data-testid="stVerticalBlock"] { background-color: #161b22 !important; border: 1px solid #30363d !important; border-radius: 8px !important; padding: 5px !important; position: relative !important; width: 100% !important; }
    .custom-hr { border: 0; height: 1px; background: #30363d; margin: 15px 0; }
    </style>
""", unsafe_allow_html=True)

st.title("📈 Legendary Swing Trading Scanner")
st.markdown("మార్క్ మినర్విని, నికోలస్ డార్వాస్, డాన్ జ్యాంగర్ మరియు స్టాన్ వైన్‌స్టీన్ స్ట్రాటజీల కోసం ప్రత్యేకమైన ఫుల్-మార్కెట్ స్కానర్.")

# --- 2. FULL STOCK UNIVERSE ---
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

ALL_STOCKS = list(set(NIFTY_50 + FNO_STOCKS + MIDCAP_150 + SMALLCAP_250))
TICKERS = [f"{sym}.NS" for sym in ALL_STOCKS]

# --- 3. 🚀 20X SPEED FETCH & PROCESS DATA ---
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_and_calculate_metrics(tickers):
    chunk_size = 25 # ఒక్కో బ్యాచ్‌కి 25 స్టాక్స్
    chunks = [tickers[i : i + chunk_size] for i in range(0, len(tickers), chunk_size)]
    data_frames = []

    def download_chunk(chunk):
        try:
            temp = yf.download(chunk, period="18mo", interval="1d", progress=False, group_by='ticker', threads=False)
            if not temp.empty:
                if len(chunk) == 1:
                    temp.columns = pd.MultiIndex.from_product([chunk, temp.columns])
                return temp
        except Exception:
            return pd.DataFrame()
        return pd.DataFrame()

    # 🔥 20 Threads in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(download_chunk, c) for c in chunks]
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if not res.empty:
                data_frames.append(res)
            
    if not data_frames: return pd.DataFrame()
    data = pd.concat(data_frames, axis=1)
    results = []
    
    for sym in data.columns.levels[0]:
        try:
            df = data[sym].dropna(subset=['Close']).copy()
            if len(df) < 200: continue
            
            ltp = float(df['Close'].iloc[-1])
            prev_c = float(df['Close'].iloc[-2])
            day_chg = ((ltp - prev_c) / prev_c) * 100
            
            high = float(df['High'].iloc[-1])
            low = float(df['Low'].iloc[-1])
            
            df['SMA50'] = df['Close'].rolling(window=50).mean()
            df['SMA150'] = df['Close'].rolling(window=150).mean()
            df['SMA200'] = df['Close'].rolling(window=200).mean()
            
            sma50 = float(df['SMA50'].iloc[-1])
            sma150 = float(df['SMA150'].iloc[-1])
            sma200 = float(df['SMA200'].iloc[-1])
            sma150_20d = float(df['SMA150'].iloc[-21])
            sma200_20d = float(df['SMA200'].iloc[-21])
            
            high52w = float(df['High'].rolling(window=252).max().iloc[-1])
            low52w = float(df['Low'].rolling(window=252).min().iloc[-1])
            
            df['Vol_SMA50'] = df['Volume'].rolling(window=50).mean()
            curr_vol = float(df['Volume'].iloc[-1])
            avg_vol_50 = float(df['Vol_SMA50'].iloc[-1])
            vol_x = round(curr_vol / avg_vol_50, 1) if avg_vol_50 > 0 else 0.0
            
            box_top_20 = float(df['High'].iloc[-21:-1].max())
            box_bot_20 = float(df['Low'].iloc[-21:-1].min())
            
            vcp_contract = False
            vcp_vol_dry = False
            max_60 = float(df['High'].iloc[-60:].max())
            min_60 = float(df['Low'].iloc[-60:].min())
            range_60 = (max_60 - min_60) / min_60 if min_60 > 0 else 0
            
            max_10 = float(df['High'].iloc[-10:].max())
            min_10 = float(df['Low'].iloc[-10:].min())
            range_10 = (max_10 - min_10) / min_10 if min_10 > 0 else 0
            
            if (range_60 > 0) and (range_10 <= (range_60 * 0.75)) and (range_10 <= 0.15):
                vcp_contract = True
                
            vol_avg_5 = float(df['Volume'].iloc[-5:].mean())
            if vol_avg_5 <= (avg_vol_50 * 1.05):
                vcp_vol_dry = True
                
            results.append({
                "Stock": sym.replace(".NS", ""),
                "LTP": round(ltp, 2),
                "Day_Change_%": round(day_chg, 2),
                "Volume_x": vol_x,
                "SMA50": sma50, "SMA150": sma150, "SMA200": sma200,
                "SMA150_20D": sma150_20d, "SMA200_20D": sma200_20d,
                "High52W": high52w, "Low52W": low52w,
                "Box_Top20": box_top_20, "Box_Bot20": box_bot_20,
                "VCP_Contract": vcp_contract, "VCP_Vol_Dry": vcp_vol_dry,
                "Close_Range": (ltp - low) / (high - low + 0.001)
            })
        except Exception as e:
            continue
    return pd.DataFrame(results)

# --- 4. CHARTS HISTORICAL DATA FETCH ---
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_historical_charts_data(tkrs, timeframe):
    p, i = ("2y", "1wk") if timeframe == "Weekly Chart" else ("1y", "1d")
    res = yf.download(tkrs, period=p, interval=i, progress=False, group_by='ticker', threads=False)
    if res.empty: return pd.DataFrame()
    return res

# --- 5. RENDER CHART FUNCTION ---
def render_chart(row, df_chart, show_pin=True, key_suffix="", timeframe="Daily Chart", show_crosshair=False, show_vol=False):
    display_sym = row['T']
    fetch_sym = row['Fetch_T']
    pct_val = float(row.get('W_C', row['Day_C'])) if timeframe == "Weekly Chart" else float(row['Day_C'])
    color_hex = "#da3633" if pct_val < 0 else "#2ea043"
    sign = "+" if pct_val > 0 else ""
    tv_link = f"https://in.tradingview.com/chart/?symbol=NSE:{display_sym}"
    
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

                # 1. Normal Candles
                fig_obj.add_trace(go.Candlestick(
                    x=df_chart.index, open=am('Open', mask_norm), high=am('High', mask_norm), low=am('Low', mask_norm), close=am('Close', mask_norm), 
                    increasing_line_color='#2ea043', increasing_fillcolor='#2ea043', increasing_line_width=1,
                    decreasing_line_color='#da3633', decreasing_fillcolor='#da3633', decreasing_line_width=1,
                    showlegend=False, hoverinfo='skip'
                ), **rc)
                
                # 2. High Volume Bullish Candles
                if mask_hv_bull.any():
                    fig_obj.add_trace(go.Candlestick(
                        x=df_chart.index, open=am('Open', mask_hv_bull), high=am('High', mask_hv_bull), low=am('Low', mask_hv_bull), close=am('Close', mask_hv_bull), 
                        increasing_line_color='#00FF00', increasing_fillcolor='#00FF00', increasing_line_width=2,
                        decreasing_line_color='#00FF00', decreasing_fillcolor='#00FF00', decreasing_line_width=2,
                        showlegend=False, hoverinfo='skip'
                    ), **rc)
                    
                # 3. High Volume Bearish Candles
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
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['High'], mode='lines', line=dict(color='rgba(0,0,0,0)'), showlegend=False, hoverinfo='text' if show_crosshair else 'skip', text=hover_data, hovertemplate="%{text}<extra></extra>" if show_crosshair else None, name=""), row=1, col=1)
                
                if timeframe == "Daily Chart":
                    if 'SMA_50' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_50'], mode='lines', line=dict(color='#FFD700', width=1.5), name='50 SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
                    if 'SMA_150' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_150'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), name='150 SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
                    if 'SMA_200' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_200'], mode='lines', line=dict(color='#FF4500', width=2), name='200 SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
                elif timeframe == "Weekly Chart":
                    if 'SMA_10' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_10'], mode='lines', line=dict(color='#FFD700', width=1.5), name='10 Wk SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
                    if 'SMA_40' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_40'], mode='lines', line=dict(color='#FF4500', width=2), name='40 Wk SMA', showlegend=False, hoverinfo='skip'), row=1, col=1)
                
                vol_colors = []
                if 'Volume' in df_chart.columns:
                    vol_sma = df_chart.get('Vol_SMA_89', df_chart['Volume'].rolling(window=20, min_periods=1).mean())
                    for i in range(len(df_chart)):
                        close_p = df_chart['Close'].iloc[i]
                        open_p = df_chart['Open'].iloc[i]
                        bull = close_p >= open_p
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
                    vol_colors = ['rgba(46, 160, 67, 0.4)' if close >= open_p else 'rgba(218, 54, 51, 0.4)' for close, open_p in zip(df_chart['Close'], df_chart['Open'])]
                
                fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Volume'], marker_color=vol_colors, showlegend=False, hoverinfo='skip'), row=2, col=1)
                
                fig.update_layout(margin=dict(l=0, r=45 if show_crosshair else 5, t=0, b=0), height=275, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_rangeslider_visible=False)
                fig.add_annotation(text=title_html, xref="paper", yref="paper", x=0, xanchor="left", xshift=35, y=0.98, yanchor="top", showarrow=False, font=dict(size=13, color="#ffffff"), bgcolor="rgba(0,0,0,0)", borderwidth=0)

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
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['High'], mode='lines', line=dict(color='rgba(0,0,0,0)'), showlegend=False, hoverinfo='text' if show_crosshair else 'skip', text=hover_data, hovertemplate="%{text}<extra></extra>" if show_crosshair else None, name=""))
                
                if timeframe == "Daily Chart":
                    if 'SMA_50' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_50'], mode='lines', line=dict(color='#FFD700', width=1.5), name='50 SMA', showlegend=False, hoverinfo='skip'))
                    if 'SMA_150' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_150'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), name='150 SMA', showlegend=False, hoverinfo='skip'))
                    if 'SMA_200' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_200'], mode='lines', line=dict(color='#FF4500', width=2), name='200 SMA', showlegend=False, hoverinfo='skip'))
                elif timeframe == "Weekly Chart":
                    if 'SMA_10' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_10'], mode='lines', line=dict(color='#FFD700', width=1.5), name='10 Wk SMA', showlegend=False, hoverinfo='skip'))
                    if 'SMA_40' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['SMA_40'], mode='lines', line=dict(color='#FF4500', width=2), name='40 Wk SMA', showlegend=False, hoverinfo='skip'))
            
                fig.update_layout(margin=dict(l=0, r=45 if show_crosshair else 5, t=0, b=0), height=235, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', showlegend=False, xaxis_rangeslider_visible=False)
                fig.add_annotation(text=title_html, xref="paper", yref="paper", x=0, xanchor="left", xshift=35, y=0.98, yanchor="top", showarrow=False, font=dict(size=13, color="#ffffff"), bgcolor="rgba(0,0,0,0)", borderwidth=0)

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

def render_chart_grid(df_grid, show_pin_option, key_prefix, timeframe="Daily Chart", chart_dict=None, show_crosshair=False, show_vol=False):
    if df_grid.empty: return
    if chart_dict is None: chart_dict = {}
    with st.container():
        st.markdown("<div class='fluid-board'></div>", unsafe_allow_html=True)
        for _, row in df_grid.iterrows():
            with st.container():
                render_chart(row, chart_dict.get(row['Fetch_T'], pd.DataFrame()), show_pin=show_pin_option, key_suffix=key_prefix, timeframe=timeframe, show_crosshair=show_crosshair, show_vol=show_vol)


# --- 6. UI FILTERS & LOGIC ---
st.sidebar.header("⚙️ Strategy Filters")
strategy = st.sidebar.radio("Select Legendary Strategy", [
    "📈 Minervini Trend Template (VCP)",
    "📉 Strict VCP (Price & Vol Contraction)",
    "📦 Nicolas Darvas (Box Breakout)",
    "📈 Stan Weinstein (Stage 2 Uptrend)",
    "💥 Dan Zanger (Volume Explosion)"
])

with st.spinner(f"📥 Fetching Data & Calculating Metrics for {len(TICKERS)} Stocks..."):
    df_metrics = fetch_and_calculate_metrics(TICKERS)

if not df_metrics.empty:
    df_filtered = df_metrics.copy()
    
    # Apply selected strategy filters
    if strategy == "📈 Minervini Trend Template (VCP)":
        cond1 = (df_filtered['LTP'] > df_filtered['SMA150']) & (df_filtered['LTP'] > df_filtered['SMA200'])
        cond2 = df_filtered['SMA150'] > df_filtered['SMA200']
        cond3 = df_filtered['SMA200'] > df_filtered['SMA200_20D']
        cond4 = (df_filtered['SMA50'] > df_filtered['SMA150']) & (df_filtered['SMA50'] > df_filtered['SMA200'])
        cond5 = df_filtered['LTP'] > df_filtered['SMA50']
        cond6 = df_filtered['LTP'] >= (df_filtered['Low52W'] * 1.30)
        cond7 = df_filtered['LTP'] >= (df_filtered['High52W'] * 0.75)
        df_final = df_filtered[cond1 & cond2 & cond3 & cond4 & cond5 & cond6 & cond7]
        st.sidebar.info("💡 P > 50,150,200 SMA | 150 > 200 | 200 Trending Up | Price within 25% of 52W High.")

    elif strategy == "📉 Strict VCP (Price & Vol Contraction)":
        cond_minervini = (df_filtered['LTP'] > df_filtered['SMA150']) & (df_filtered['SMA150'] > df_filtered['SMA200']) & (df_filtered['SMA200'] > df_filtered['SMA200_20D']) & (df_filtered['LTP'] > df_filtered['SMA50'])
        vcp_cond = (df_filtered['VCP_Contract'] == True) & (df_filtered['VCP_Vol_Dry'] == True)
        df_final = df_filtered[cond_minervini & vcp_cond]
        st.sidebar.info("💡 Minervini Trend + Price Range Contraction + Volume Dry Up.")

    elif strategy == "📦 Nicolas Darvas (Box Breakout)":
        box_width = (df_filtered['Box_Top20'] - df_filtered['Box_Bot20']) / (df_filtered['Box_Bot20'] + 0.001)
        darvas_cond = (df_filtered['LTP'] > df_filtered['Box_Top20']) & (box_width <= 0.15) & (df_filtered['LTP'] >= df_filtered['High52W'] * 0.90) & (df_filtered['Volume_x'] >= 1.5)
        df_final = df_filtered[darvas_cond]
        st.sidebar.info("💡 Box width < 15% | Price breaking Box Top | Volume > 1.5x | Near 52W High.")

    elif strategy == "📈 Stan Weinstein (Stage 2 Uptrend)":
        weinstein_cond = (df_filtered['LTP'] > df_filtered['SMA150']) & (df_filtered['SMA150'] > df_filtered['SMA150_20D']) & (df_filtered['SMA50'] > df_filtered['SMA150']) & (df_filtered['LTP'] > df_filtered['SMA200']) & (df_filtered['Day_Change_%'] >= 1.5)
        df_final = df_filtered[weinstein_cond]
        st.sidebar.info("💡 Price > 150 SMA | 150 SMA sloping upwards | 50 SMA > 150 SMA.")

    elif strategy == "💥 Dan Zanger (Volume Explosion)":
        zanger_cond = (df_filtered['Volume_x'] >= 2.5) & (df_filtered['Day_Change_%'] >= 4.0) & (df_filtered['Close_Range'] >= 0.75) & (df_filtered['SMA50'] > df_filtered['SMA150'])
        df_final = df_filtered[zanger_cond]
        st.sidebar.info("💡 Volume > 2.5x Avg | Price moved +4% today | Closed near High.")

    # --- 7. DISPLAY SETTINGS ---
    st.markdown("<hr style='margin:10px 0; border-color:#30363d;'>", unsafe_allow_html=True)
    cc1, cc2, cc3, cc4 = st.columns(4)
    with cc1:
        view_mode = st.radio("Display Mode", ["Data Table 📊", "Charts 📈"], index=0, horizontal=True)
    
    if view_mode == "Charts 📈":
        with cc2: chart_timeframe = st.radio("Timeframe", ["Daily Chart", "Weekly Chart"], index=0, horizontal=True)
        with cc3: show_crosshair = st.toggle("⌖ Show Crosshair", value=False)
        with cc4: show_vol = st.toggle("📊 Show Vol Bars", value=True)

    # --- 8. RENDER RESULTS ---
    if not df_final.empty:
        df_final = df_final.sort_values(by="Day_Change_%", ascending=False).reset_index(drop=True)
        
        if view_mode == "Data Table 📊":
            st.success(f"🎉 Found {len(df_final)} stocks matching {strategy}!")
            display_cols = ["Stock", "LTP", "Day_Change_%", "Volume_x", "High52W", "Box_Top20"]
            st.dataframe(df_final[display_cols], use_container_width=True)
            
        elif view_mode == "Charts 📈":
            display_tkrs = [f"{sym}.NS" for sym in df_final['Stock']]
            chart_data = fetch_historical_charts_data(display_tkrs, chart_timeframe)
            
            # Map df_final to the format expected by render_chart
            df_final_mapped = df_final.copy()
            df_final_mapped['T'] = df_final_mapped['Stock']
            df_final_mapped['Fetch_T'] = df_final_mapped['Stock'] + ".NS"
            df_final_mapped['P'] = df_final_mapped['LTP']
            df_final_mapped['Day_C'] = df_final_mapped['Day_Change_%']
            df_final_mapped['W_C'] = 0.0 # Default value for Weekly fallback
            
            # Calculate extra indicators for the charts
            processed_charts = {}
            for sym in display_tkrs:
                try:
                    df_h = chart_data[sym] if isinstance(chart_data.columns, pd.MultiIndex) else chart_data
                    df_h = df_h.dropna(subset=['Close']).copy()
                    if not df_h.empty:
                        if chart_timeframe == "Daily Chart":
                            df_h['SMA_50'] = df_h['Close'].rolling(window=50).mean()
                            df_h['SMA_150'] = df_h['Close'].rolling(window=150).mean()
                            df_h['SMA_200'] = df_h['Close'].rolling(window=200).mean()
                        elif chart_timeframe == "Weekly Chart":
                            df_h['SMA_10'] = df_h['Close'].rolling(window=10).mean()
                            df_h['SMA_40'] = df_h['Close'].rolling(window=40).mean()
                        processed_charts[sym] = df_h
                except: pass

            st.markdown(f"<div style='font-size:16px; font-weight:bold; margin-top:10px; margin-bottom:5px; color:#3fb950;'>🟢 POSITIVE MOVERS ({len(df_final)} Stocks)</div>", unsafe_allow_html=True)
            render_chart_grid(df_final_mapped, show_pin_option=False, key_prefix="swing", timeframe=chart_timeframe, chart_dict=processed_charts, show_crosshair=show_crosshair, show_vol=show_vol)
            
    else:
        st.warning("⚠️ No stocks matched this strategy today. Market condition might be weak or choppy.")
else:
    st.error("Failed to fetch data.")
