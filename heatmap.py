import streamlit as st

# Page configuration
st.set_page_config(layout="wide", page_title="Nifty 50 Heatmap")

st.title("📊 Market Watchlist")

# Custom CSS
st.markdown("""
    <style>
    a:link, a:visited, a:hover, a:active {
        text-decoration: none;
        color: inherit;
    }
    .stock-card {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 15px 5px;
        border-radius: 4px;
        margin-bottom: 15px;
        color: white;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        transition: transform 0.2s ease-in-out;
        cursor: pointer;
    }
    .stock-card:hover {
        transform: scale(1.03);
        box-shadow: 0 6px 12px rgba(0,0,0,0.5);
    }
    .ticker { font-size: 13px; font-weight: 600; letter-spacing: 0.5px; opacity: 0.9; }
    .price { font-size: 18px; font-weight: 800; margin: 4px 0; }
    .change { font-size: 12px; font-weight: 500; }
    </style>
""", unsafe_allow_html=True)

# 1. Top Indices Data
indices_data = [
    {"ticker": "NIFTY 50", "tv_symbol": "NSE:NIFTY", "price": 25482.50, "change": 57.85, "pct": 0.23},
    {"ticker": "NIFTY BANK", "tv_symbol": "NSE:BANKNIFTY", "price": 61043.35, "change": -3.95, "pct": -0.01},
    {"ticker": "INDIA VIX", "tv_symbol": "NSE:INDIAVIX", "price": 13.45, "change": -0.25, "pct": -1.82},
]

# 2. Complete Nifty 50 Stocks Data (Static Dummy Data for all 50)
nifty_data = [
    {"ticker": "RELIANCE", "price": 2985.50, "change": -30.30, "pct": -2.12},
    {"ticker": "TCS", "price": 4120.00, "change": 55.60, "pct": 2.16},
    {"ticker": "HDFCBANK", "price": 1450.60, "change": -2.90, "pct": -0.32},
    {"ticker": "ICICIBANK", "price": 1085.10, "change": 15.70, "pct": 1.13},
    {"ticker": "BHARTIARTL", "price": 1215.40, "change": -27.60, "pct": -1.42},
    {"ticker": "SBIN", "price": 760.10, "change": -23.20, "pct": -1.90},
    {"ticker": "INFY", "price": 1625.30, "change": 14.60, "pct": 1.14},
    {"ticker": "ITC", "price": 415.75, "change": -3.75, "pct": -1.16},
    {"ticker": "HINDUNILVR", "price": 2374.90, "change": 16.30, "pct": 0.69},
    {"ticker": "LT", "price": 3540.00, "change": 39.30, "pct": 0.92},
    {"ticker": "BAJFINANCE", "price": 7021.05, "change": -2.50, "pct": -0.24},
    {"ticker": "HCLTECH", "price": 1378.20, "change": 39.00, "pct": 2.91},
    {"ticker": "MARUTI", "price": 15070.00, "change": 144.00, "pct": 0.96},
    {"ticker": "SUNPHARMA", "price": 1764.20, "change": 32.40, "pct": 1.87},
    {"ticker": "TATAMOTORS", "price": 985.40, "change": 12.30, "pct": 1.25},
    {"ticker": "M&M", "price": 3491.30, "change": 58.10, "pct": 1.69},
    {"ticker": "TATASTEEL", "price": 214.64, "change": 5.51, "pct": 2.63},
    {"ticker": "POWERGRID", "price": 307.25, "change": 2.45, "pct": 0.80},
    {"ticker": "NTPC", "price": 384.90, "change": 2.15, "pct": 0.56},
    {"ticker": "AXISBANK", "price": 1403.00, "change": 15.40, "pct": 1.11},
    {"ticker": "KOTAKBANK", "price": 1724.95, "change": -2.75, "pct": -0.64},
    {"ticker": "ULTRACEMCO", "price": 10041.00, "change": 81.00, "pct": 0.63},
    {"ticker": "TITAN", "price": 3625.00, "change": 30.50, "pct": 0.71},
    {"ticker": "ONGC", "price": 277.45, "change": 0.95, "pct": 0.34},
    {"ticker": "COALINDIA", "price": 438.60, "change": 7.65, "pct": 1.78},
    {"ticker": "BAJAJFINSV", "price": 1649.30, "change": 6.00, "pct": 0.29},
    {"ticker": "ASIANPAINT", "price": 2816.40, "change": 3.30, "pct": 0.14},
    {"ticker": "ADANIENT", "price": 3231.70, "change": 48.70, "pct": 2.23},
    {"ticker": "ADANIPORTS", "price": 1328.70, "change": -26.70, "pct": -1.72},
    {"ticker": "TRENT", "price": 3922.00, "change": -9.30, "pct": -0.24},
    {"ticker": "SHRIRAMFIN", "price": 2485.90, "change": 24.20, "pct": 2.28},
    {"ticker": "BAJAJ-AUTO", "price": 10097.00, "change": 268.00, "pct": 2.73},
    {"ticker": "GRASIM", "price": 2278.40, "change": -0.90, "pct": -0.03},
    {"ticker": "WIPRO", "price": 501.92, "change": 1.78, "pct": 0.89},
    {"ticker": "TECHM", "price": 1361.80, "change": 16.40, "pct": 1.22},
    {"ticker": "HINDALCO", "price": 637.40, "change": 14.55, "pct": 1.58},
    {"ticker": "JSWSTEEL", "price": 875.00, "change": 20.50, "pct": 1.63},
    {"ticker": "EICHERMOT", "price": 4008.00, "change": 79.00, "pct": 1.00},
    {"ticker": "NESTLEIND", "price": 2523.40, "change": 3.40, "pct": 0.26},
    {"ticker": "DIVISLAB", "price": 3845.60, "change": -12.40, "pct": -0.32},
    {"ticker": "CIPLA", "price": 1446.10, "change": 19.40, "pct": 1.46},
    {"ticker": "DRREDDY", "price": 6106.50, "change": 6.30, "pct": 0.48},
    {"ticker": "HEROMOTOCO", "price": 4725.30, "change": 45.20, "pct": 0.95},
    {"ticker": "HDFCLIFE", "price": 635.25, "change": 0.50, "pct": 0.07},
    {"ticker": "SBILIFE", "price": 1473.60, "change": -9.30, "pct": -0.45},
    {"ticker": "BRITANNIA", "price": 4920.10, "change": 25.40, "pct": 0.52},
    {"ticker": "APOLLOHOSP", "price": 6283.00, "change": 62.50, "pct": 0.81},
    {"ticker": "TATACONSUM", "price": 1172.30, "change": -5.70, "pct": -0.48},
    {"ticker": "BEL", "price": 239.30, "change": 4.25, "pct": 0.98},
    {"ticker": "INDIGO", "price": 4247.40, "change": 97.10, "pct": 2.00},
]

def render_cards(data_list, is_index=False):
    cols = st.columns(3)
    for index, row in enumerate(data_list):
        ticker = row['ticker']
        price = f"{row['price']:.2f}"
        change = row['change']
        pct = row['pct']
        
        # Colors (Green for profit, Red for loss)
        if change >= 0:
            bg_color = "#2E5A27" # Green
            sign = "+"
        else:
            bg_color = "#8B1A1A" # Red
            sign = "" 
            
        change_text = f"{sign}{change:.2f} ({sign}{pct:.2f}%)"
        
        # Determine TradingView URL
        if is_index:
            tv_symbol = row['tv_symbol']
        else:
            tv_symbol = f"NSE:{ticker}"
            
        tv_url = f"https://in.tradingview.com/chart/?symbol={tv_symbol}"
        
        # HTML Block
        html_content = f"""
        <a href="{tv_url}" target="_blank">
            <div class="stock-card" style="background-color: {bg_color};">
                <div class="ticker">{ticker}</div>
                <div class="price">{price}</div>
                <div class="change">{change_text}</div>
            </div>
        </a>
        """
        
        with cols[index % 3]:
            st.markdown(html_content, unsafe_allow_html=True)

# Render Top Indices
render_cards(indices_data, is_index=True)

# Visual gap
st.markdown("<br>", unsafe_allow_html=True)

# Render Main Stocks Grid
render_cards(nifty_data, is_index=False)
