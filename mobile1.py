import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Legendary Swing Scanner", page_icon="📈", layout="wide")
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

# --- 3. FETCH & PROCESS DATA ---
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_and_calculate_metrics(tickers):
    chunk_size = 200
    data_frames = []
    
    # 1. Download Data in Chunks to prevent yfinance crashes
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i : i + chunk_size]
        temp_data = yf.download(chunk, period="18mo", interval="1d", progress=False, group_by='ticker', threads=False)
        if not temp_data.empty:
            if len(chunk) == 1:
                temp_data.columns = pd.MultiIndex.from_product([chunk, temp_data.columns])
            data_frames.append(temp_data)
            
    if not data_frames:
        return pd.DataFrame()
        
    data = pd.concat(data_frames, axis=1)
    results = []
    
    # 2. Calculate Legendary Metrics
    for sym in data.columns.levels[0]:
        try:
            df = data[sym].dropna(subset=['Close']).copy()
            if len(df) < 200: continue # లాంగ్ టర్మ్ మూవింగ్ యావరేజెస్ కోసం కనీసం 200 రోజులు కావాలి
            
            ltp = float(df['Close'].iloc[-1])
            prev_c = float(df['Close'].iloc[-2])
            day_chg = ((ltp - prev_c) / prev_c) * 100
            
            high = float(df['High'].iloc[-1])
            low = float(df['Low'].iloc[-1])
            
            # Simple Moving Averages
            df['SMA50'] = df['Close'].rolling(window=50).mean()
            df['SMA150'] = df['Close'].rolling(window=150).mean()
            df['SMA200'] = df['Close'].rolling(window=200).mean()
            
            sma50 = float(df['SMA50'].iloc[-1])
            sma150 = float(df['SMA150'].iloc[-1])
            sma200 = float(df['SMA200'].iloc[-1])
            
            # Slope Metrics (20 Days Ago)
            sma150_20d = float(df['SMA150'].iloc[-21])
            sma200_20d = float(df['SMA200'].iloc[-21])
            
            # 52 Week High / Low
            high52w = float(df['High'].rolling(window=252).max().iloc[-1])
            low52w = float(df['Low'].rolling(window=252).min().iloc[-1])
            
            # Volume Metrics
            df['Vol_SMA50'] = df['Volume'].rolling(window=50).mean()
            curr_vol = float(df['Volume'].iloc[-1])
            avg_vol_50 = float(df['Vol_SMA50'].iloc[-1])
            vol_x = round(curr_vol / avg_vol_50, 1) if avg_vol_50 > 0 else 0.0
            
            # Darvas Box (Last 20 Days excluding today)
            box_top_20 = float(df['High'].iloc[-21:-1].max())
            box_bot_20 = float(df['Low'].iloc[-21:-1].min())
            
            # VCP Contraction Logic
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

# --- 4. UI FILTERS & LOGIC ---
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
    
    # 1. Minervini VCP
    if strategy == "📈 Minervini Trend Template (VCP)":
        cond1 = (df_filtered['LTP'] > df_filtered['SMA150']) & (df_filtered['LTP'] > df_filtered['SMA200'])
        cond2 = df_filtered['SMA150'] > df_filtered['SMA200']
        cond3 = df_filtered['SMA200'] > df_filtered['SMA200_20D']
        cond4 = (df_filtered['SMA50'] > df_filtered['SMA150']) & (df_filtered['SMA50'] > df_filtered['SMA200'])
        cond5 = df_filtered['LTP'] > df_filtered['SMA50']
        cond6 = df_filtered['LTP'] >= (df_filtered['Low52W'] * 1.30)
        cond7 = df_filtered['LTP'] >= (df_filtered['High52W'] * 0.75)
        df_final = df_filtered[cond1 & cond2 & cond3 & cond4 & cond5 & cond6 & cond7]
        st.info("💡 **Minervini Rules Applied:** P > 50,150,200 SMA | 150 > 200 | 200 Trending Up | Price within 25% of 52W High.")

    # 2. Strict VCP
    elif strategy == "📉 Strict VCP (Price & Vol Contraction)":
        cond_minervini = (df_filtered['LTP'] > df_filtered['SMA150']) & (df_filtered['SMA150'] > df_filtered['SMA200']) & (df_filtered['SMA200'] > df_filtered['SMA200_20D']) & (df_filtered['LTP'] > df_filtered['SMA50'])
        vcp_cond = (df_filtered['VCP_Contract'] == True) & (df_filtered['VCP_Vol_Dry'] == True)
        df_final = df_filtered[cond_minervini & vcp_cond]
        st.info("💡 **Strict VCP Rules:** Minervini Trend + Price Range Contraction (Last 10 days tight) + Volume Dry Up.")

    # 3. Darvas Box
    elif strategy == "📦 Nicolas Darvas (Box Breakout)":
        box_width = (df_filtered['Box_Top20'] - df_filtered['Box_Bot20']) / (df_filtered['Box_Bot20'] + 0.001)
        darvas_cond = (df_filtered['LTP'] > df_filtered['Box_Top20']) & (box_width <= 0.15) & (df_filtered['LTP'] >= df_filtered['High52W'] * 0.90) & (df_filtered['Volume_x'] >= 1.5)
        df_final = df_filtered[darvas_cond]
        st.info("💡 **Darvas Rules:** Box width < 15% in last 20 days | Price breaking Box Top | Volume > 1.5x | Near 52W High.")

    # 4. Stan Weinstein
    elif strategy == "📈 Stan Weinstein (Stage 2 Uptrend)":
        weinstein_cond = (df_filtered['LTP'] > df_filtered['SMA150']) & (df_filtered['SMA150'] > df_filtered['SMA150_20D']) & (df_filtered['SMA50'] > df_filtered['SMA150']) & (df_filtered['LTP'] > df_filtered['SMA200']) & (df_filtered['Day_Change_%'] >= 1.5)
        df_final = df_filtered[weinstein_cond]
        st.info("💡 **Weinstein Rules:** Price > 150 SMA | 150 SMA is sloping upwards (Current > 20D ago) | 50 SMA > 150 SMA.")

    # 5. Dan Zanger
    elif strategy == "💥 Dan Zanger (Volume Explosion)":
        zanger_cond = (df_filtered['Volume_x'] >= 2.5) & (df_filtered['Day_Change_%'] >= 4.0) & (df_filtered['Close_Range'] >= 0.75) & (df_filtered['SMA50'] > df_filtered['SMA150'])
        df_final = df_filtered[zanger_cond]
        st.info("💡 **Zanger Rules:** Volume > 2.5x Avg | Price moved +4% today | Closed near the High of the day.")

    # --- 5. RENDER RESULTS ---
    if not df_final.empty:
        df_final = df_final.sort_values(by="Day_Change_%", ascending=False).reset_index(drop=True)
        st.success(f"🎉 Found {len(df_final)} stocks matching {strategy}!")
        
        # Select columns to show
        display_cols = ["Stock", "LTP", "Day_Change_%", "Volume_x", "High52W", "Box_Top20"]
        st.dataframe(df_final[display_cols], use_container_width=True)
    else:
        st.warning("⚠️ No stocks matched this strategy today. Market condition might be weak or choppy.")
else:
    st.error("Failed to fetch data.")
