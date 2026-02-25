import streamlit as st

# Page configuration
st.set_page_config(layout="wide", page_title="Market Watchlist")

st.title("📊 Market Watchlist")

# Custom CSS for 10 columns on Desktop and 3 columns on Mobile
st.markdown("""
    <style>
    /* Remove default link styling */
    a:link, a:visited, a:hover, a:active {
        text-decoration: none;
        color: inherit;
    }
    
    /* Default CSS Grid Container (For Desktop - 10 items) */
    .grid-container {
        display: grid;
        grid-template-columns: repeat(10, 1fr); 
        gap: 8px;
        margin-bottom: 20px;
    }
    
    /* Box styling */
    .stock-card {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 10px 2px;
        border-radius: 4px;
        color: white;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        transition: transform 0.2s ease-in-out;
        cursor: pointer;
        height: 100%;
        text-align: center;
    }
    
    .stock-card:hover {
        transform: scale(1.05);
        box-shadow: 0 6px 12px rgba(0,0,0,0.5);
    }
    
    .ticker { font-size: 11px; font-weight: 600; letter-spacing: 0.5px; opacity: 0.9; text-transform: uppercase; }
    .price { font-size: 14px; font-weight: 800; margin: 4px 0; }
    .change { font-size: 10px; font-weight: 500; }
    
    /* Tablet Responsive styling */
    @media (max-width: 1024px) {
        .grid-container {
            grid-template-columns: repeat(5, 1fr);
        }
    }
    
    /* Mobile Responsive styling (For Mobile - 3 items per row) */
    @media (max-width: 600px) {
        .grid-container {
            grid-template-columns: repeat(3, 1fr);
            gap: 6px; 
        }
        .stock-card {
            padding: 8px 2px;
        }
        .ticker { font-size: 10px; }
        .price { font-size: 14px; margin: 2px 0; }
        .change { font-size: 9px; }
    }
    </style>
""", unsafe_allow_html=True)

# 1. Top Indices Data
indices_data = [
    {"ticker": "NIFTY 50", "tv_symbol": "NSE:NIFTY", "price": 25482.50, "change": 57.85, "pct": 0.23},
    {"ticker": "NIFTY BANK", "tv_symbol": "NSE:BANKNIFTY", "price": 61043.35, "change": -3.95, "pct": -0.01},
    {"ticker": "INDIA VIX", "tv_symbol": "NSE:INDIAVIX", "price": 13.45, "change": -0.25, "pct": -1.82},
]

# 2. Main Nifty 50 Stocks Data (Complete 50 Stocks)
nifty_data = [
    {"ticker": "HCLTECH", "price": 1378.20, "change": 39.00, "pct": 2.91},
    {"ticker": "BAJAJ-AUTO", "price": 10097.00, "change": 268.00, "pct": 2.73},
    {"ticker": "TATASTEEL", "price": 214.64, "change": 5.51, "pct": 2.63},
    {"ticker": "SHRIRAMFIN", "price": 1085.90, "change": 24.20, "pct": 2.28},
    {"ticker": "ADANIENT", "price": 2231.70, "change": 48.70, "pct": 2.23},
    {"ticker": "TCS", "price": 2629.30, "change": 55.60, "pct": 2.16},
    {"ticker": "INDIGO", "price": 4947.40, "change": 97.10, "pct": 2.00},
    {"ticker": "SUNPHARMA", "price": 1764.20, "change": 32.40, "pct": 1.87},
    {"ticker": "COALINDIA", "price": 438.60, "change": 7.65, "pct": 1.78},
    {"ticker": "M&M", "price": 3491.30, "change": 58.10, "pct": 1.69},
    {"ticker": "JSWSTEEL", "price": 1275.00, "change": 20.50, "pct": 1.63},
    {"ticker": "HINDALCO", "price": 937.40, "change": 14.55, "pct": 1.58},
    {"ticker": "CIPLA", "price": 1346.10, "change": 19.40, "pct": 1.46},
    {"ticker": "TECHM", "price": 1361.80, "change": 16.40, "pct": 1.22},
    {"ticker": "INFY", "price": 1290.10, "change": 14.60, "pct": 1.14},
    {"ticker": "TATAMOTORS", "price": 981.85, "change": 11.30, "pct": 1.14},
    {"ticker": "ICICIBANK", "price": 1400.50, "change": 15.70, "pct": 1.13},
    {"ticker": "AXISBANK", "price": 1403.00, "change": 15.40, "pct": 1.11},
    {"ticker": "EICHERMOT", "price": 8008.00, "change": 79.00, "pct": 1.00},
    {"ticker": "BEL", "price": 439.30, "change": 4.25, "pct": 0.98},
    {"ticker": "MARUTI", "price": 15070.00, "change": 144.00, "pct": 0.96},
    {"ticker": "LT", "price": 4298.50, "change": 39.30, "pct": 0.92},
    {"ticker": "WIPRO", "price": 501.92, "change": 4.78, "pct": 0.89},
    {"ticker": "APOLLOHOSP", "price": 7783.00, "change": 62.50, "pct": 0.81},
    {"ticker": "POWERGRID", "price": 307.25, "change": 2.45, "pct": 0.80},
    {"ticker": "TITAN", "price": 4325.00, "change": 30.50, "pct": 0.71},
    {"ticker": "HINDUNILVR", "price": 2374.90, "change": 16.30, "pct": 0.69},
    {"ticker": "JIOFIN", "price": 356.95, "change": 2.70, "pct": 0.67},
    {"ticker": "ULTRACEMCO", "price": 10041.00, "change": 81.00, "pct": 0.63},
    {"ticker": "NTPC", "price": 384.90, "change": 2.15, "pct": 0.56},
    {"ticker": "DRREDDY", "price": 6306.50, "change": 36.30, "pct": 0.48},
    {"ticker": "ONGC", "price": 277.45, "change": 0.95, "pct": 0.34},
    {"ticker": "BAJAJFINSV", "price": 1649.30, "change": 6.00, "pct": 0.29},
    {"ticker": "NESTLEIND", "price": 2523.40, "change": 3.40, "pct": 0.26},
    {"ticker": "MAXHEALTH", "price": 888.10, "change": 1.70, "pct": 0.16},
    {"ticker": "ASIANPAINT", "price": 2816.40, "change": 3.30, "pct": 0.14},
    {"ticker": "HDFCLIFE", "price": 635.25, "change": 0.50, "pct": 0.07},
    {"ticker": "GRASIM", "price": 2278.40, "change": -0.90, "pct": -0.03},
    {"ticker": "TRENT", "price": 3922.00, "change": -9.30, "pct": -0.24},
    {"ticker": "BAJFINANCE", "price": 7021.05, "change": -16.50, "pct": -0.24},
    {"ticker": "HDFCBANK", "price": 1450.60, "change": -4.90, "pct": -0.32},
    {"ticker": "SBILIFE", "price": 1473.60, "change": -9.30, "pct": -0.45},
    {"ticker": "TATACONSUM", "price": 1172.30, "change": -5.70, "pct": -0.48},
    {"ticker": "KOTAKBANK", "price": 1724.95, "change": -11.75, "pct": -0.64},
    {"ticker": "ITC", "price": 415.75, "change": -3.75, "pct": -1.16},
    {"ticker": "BHARTIARTL", "price": 1213.40, "change": -17.60, "pct": -1.42},
    {"ticker": "BPCL", "price": 550.20, "change": -8.80, "pct": -1.50},
    {"ticker": "ADANIPORTS", "price": 1328.70, "change": -26.70, "pct": -1.72},
    {"ticker": "SBIN", "price": 760.10, "change": -14.20, "pct": -1.90},
    {"ticker": "RELIANCE", "price": 2898.50, "change": -60.30, "pct": -2.12},
]

# SORTING LOGIC: Sort stocks by percentage change in descending order (Green first, Red last)
nifty_data_sorted = sorted(nifty_data, key=lambda x: x['pct'], reverse=True)

def render_cards_html(data_list, is_index=False):
    html_content = '<div class="grid-container">\n'
    
    for row in data_list:
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
        
        # TradingView URL
        if is_index:
            tv_symbol = row['tv_symbol']
        else:
            tv_symbol = f"NSE:{ticker}"
            
        tv_url = f"https://in.tradingview.com/chart/?symbol={tv_symbol}"
        
        # Single line HTML to avoid Markdown issues
        html_content += f'<a href="{tv_url}" target="_blank"><div class="stock-card" style="background-color: {bg_color};"><div class="ticker">{ticker}</div><div class="price">{price}</div><div class="change">{change_text}</div></div></a>\n'
    
    html_content += '</div>'
    st.markdown(html_content, unsafe_allow_html=True)

# Render Indices
st.subheader("Indices")
render_cards_html(indices_data, is_index=True)

# Render Sorted Nifty 50 Stocks
st.subheader("Nifty 50 Stocks")
render_cards_html(nifty_data_sorted, is_index=False)

