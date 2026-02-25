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
    
    /* Default CSS Grid Container (For Desktop & Laptop - 10 items per row) */
    .grid-container {
        display: grid;
        grid-template-columns: repeat(10, 1fr); /* 10 columns for desktop */
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
    
    /* Hover effect */
    .stock-card:hover {
        transform: scale(1.05);
        box-shadow: 0 6px 12px rgba(0,0,0,0.5);
    }
    
    /* Default Text styling (Desktop - kept slightly smaller to fit 10 items) */
    .ticker { font-size: 11px; font-weight: 600; letter-spacing: 0.5px; opacity: 0.9; }
    .price { font-size: 14px; font-weight: 800; margin: 4px 0; }
    .change { font-size: 10px; font-weight: 500; }
    
    /* Tablet Responsive styling (Optional - 5 items per row for medium screens) */
    @media (max-width: 1024px) {
        .grid-container {
            grid-template-columns: repeat(5, 1fr);
        }
        .ticker { font-size: 12px; }
        .price { font-size: 16px; }
        .change { font-size: 11px; }
    }
    
    /* Mobile Responsive styling (For Mobile - 3 items per row) */
    @media (max-width: 600px) {
        .grid-container {
            grid-template-columns: repeat(3, 1fr); /* 3 columns for mobile */
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

# 2. Main Stocks Data (Added more samples to clearly see 10 items in a row on desktop)
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
    {"ticker": "INFY", "price": 1625.30, "change": 12.40, "pct": 0.77},
    {"ticker": "ICICIBANK", "price": 1085.10, "change": 8.50, "pct": 0.79},
    {"ticker": "ITC", "price": 415.75, "change": -3.75, "pct": -1.16},
    {"ticker": "LT", "price": 3540.00, "change": 65.20, "pct": 1.88},
    {"ticker": "TITAN", "price": 3625.00, "change": 30.50, "pct": 0.71},
]

def render_cards_html(data_list, is_index=False):
    # Desktop lo indices ki matram 3 e chupinchali ante, kinda id class create cheyochu.
    # Kani present anni grid-container style ne follow avtay.
    
    html_content = '<div class="grid-container">'
    
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
        
        # Determine TradingView URL
        if is_index:
            tv_symbol = row['tv_symbol']
        else:
            tv_symbol = f"NSE:{ticker}"
            
        tv_url = f"https://in.tradingview.com/chart/?symbol={tv_symbol}"
        
        # Add individual card HTML
        html_content += f"""
        <a href="{tv_url}" target="_blank">
            <div class="stock-card" style="background-color: {bg_color};">
                <div class="ticker">{ticker}</div>
                <div class="price">{price}</div>
                <div class="change">{change_text}</div>
            </div>
        </a>
        """
    
    html_content += '</div>'
    
    st.markdown(html_content, unsafe_allow_html=True)

# Render Top Indices
st.subheader("Indices")
render_cards_html(indices_data, is_index=True)

# Render Main Stocks Grid
st.subheader("Nifty 50 Stocks")
render_cards_html(nifty_data, is_index=False)
