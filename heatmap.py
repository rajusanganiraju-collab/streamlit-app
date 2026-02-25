import streamlit as st

# Page configuration for a wide, dark-themed look
st.set_page_config(layout="wide", page_title="Nifty 50 Heatmap")

st.title("📊 Market Watchlist")

# Custom CSS to make it look exactly like your image
st.markdown("""
    <style>
    /* Remove default link styling */
    a:link, a:visited, a:hover, a:active {
        text-decoration: none;
        color: inherit;
    }
    
    /* Box styling */
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
    
    /* Hover effect */
    .stock-card:hover {
        transform: scale(1.03);
        box-shadow: 0 6px 12px rgba(0,0,0,0.5);
    }
    
    /* Text styling */
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

# 2. Main Stocks Data (Sample)
nifty_data = [
    {"ticker": "HCLTECH", "price": 1378.20, "change": 39.00, "pct": 2.91},
    {"ticker": "BAJAJ-AUTO", "price": 10097.00, "change": 268.00, "pct": 2.73},
    {"ticker": "TATASTEEL", "price": 214.64, "change": 5.51, "pct": 2.63},
    {"ticker": "SHRIRAMFIN", "price": 1085.90, "change": 24.20, "pct": 2.28},
    {"ticker": "ADANIENT", "price": 2231.70, "change": 48.70, "pct": 2.23},
    {"ticker": "TCS", "price": 2629.30, "change": 55.60, "pct": 2.16},
    {"ticker": "RELIANCE", "price": 1398.50, "change": -30.30, "pct": -2.12},
    {"ticker": "SBIN", "price": 1200.10, "change": -23.20, "pct": -1.90},
    {"ticker": "HDFCBANK", "price": 907.60, "change": -2.90, "pct": -0.32},
]

def render_cards(data_list, is_index=False):
    cols = st.columns(3)
    for index, row in enumerate(data_list):
        ticker = row['ticker']
        price = f"{row['price']:.2f}" if is_index else f"{row['price']:.2f}"
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

# Add a little visual space between indices and stocks
st.markdown("<br>", unsafe_allow_html=True)

# Render Main Stocks Grid
render_cards(nifty_data, is_index=False)
