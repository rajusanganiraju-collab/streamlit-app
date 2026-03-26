import streamlit as st
import yfinance as yf
import plotly.graph_objects as go

# 1. వర్చువల్ పోర్ట్‌ఫోలియో సెటప్ (లక్ష రూపాయలతో మొదలు)
if 'cash' not in st.session_state:
    st.session_state.cash = 100000.0  # ₹1,00,000 వర్చువల్ మనీ
if 'holdings' not in st.session_state:
    st.session_state.holdings = 0     # మన దగ్గర ఉన్న షేర్లు
if 'history' not in st.session_state:
    st.session_state.history = []     # ట్రేడ్ హిస్టరీ (ఆర్డర్ బుక్)

st.title("📈 Mock Trading Terminal")

# 2. రియల్-టైమ్ స్టాక్ డేటా తెచ్చుకోవడం (ఉదాహరణకు: టాటా మోటార్స్)
ticker = "TATAMOTORS.NS" 
df = yf.download(ticker, period="1mo", interval="15m") # గత 1 నెల 15 నిమిషాల డేటా

if not df.empty:
    current_price = float(df['Close'].iloc[-1])
    st.subheader(f"Stock: {ticker} | Current Price: ₹{current_price:.2f}")

    # 3. క్యాండిల్‌స్టిక్ చార్ట్ డిజైన్
    fig = go.Figure(data=[go.Candlestick(x=df.index,
                    open=df['Open'], high=df['High'],
                    low=df['Low'], close=df['Close'])])
    fig.update_layout(xaxis_rangeslider_visible=False, height=450, margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig, use_container_width=True)

    st.write("---")

    # 4. Buy & Sell కంట్రోల్స్ (చార్ట్ కింద)
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        qty = st.number_input("Enter Quantity:", min_value=1, value=10, step=1)
        
    with col2:
        st.write("") # బటన్ అలైన్‌మెంట్ కోసం
        st.write("")
        if st.button("🟢 BUY", use_container_width=True):
            cost = qty * current_price
            if st.session_state.cash >= cost:
                st.session_state.cash -= cost
                st.session_state.holdings += qty
                st.session_state.history.insert(0, f"✅ BOUGHT {qty} shares @ ₹{current_price:.2f}")
                st.success("Buy Order Executed!")
            else:
                st.error("Not enough virtual cash!")

    with col3:
        st.write("") # బటన్ అలైన్‌మెంట్ కోసం
        st.write("")
        if st.button("🔴 SELL", use_container_width=True):
            if st.session_state.holdings >= qty:
                revenue = qty * current_price
                st.session_state.cash += revenue
                st.session_state.holdings -= qty
                st.session_state.history.insert(0, f"🔻 SOLD {qty} shares @ ₹{current_price:.2f}")
                st.success("Sell Order Executed!")
            else:
                st.error("You don't have enough shares to sell!")

    st.write("---")

    # 5. పోర్ట్‌ఫోలియో వివరాలు (డే ఎండ్ రిపోర్ట్ కోసం)
    colA, colB, colC = st.columns(3)
    with colA:
        st.info(f"💰 Available Cash:\n### ₹{st.session_state.cash:.2f}")
    with colB:
        st.warning(f"📦 Current Holdings:\n### {st.session_state.holdings} Shares")
    with colC:
        invested_value = st.session_state.holdings * current_price
        st.success(f"📊 Holdings Value:\n### ₹{invested_value:.2f}")

    # 6. ట్రేడ్ బుక్ (ఆర్డర్ హిస్టరీ)
    with st.expander("📝 View Order History (Trade Book)"):
        if len(st.session_state.history) > 0:
            for trade in st.session_state.history:
                st.text(trade)
        else:
            st.write("No trades taken yet.")
