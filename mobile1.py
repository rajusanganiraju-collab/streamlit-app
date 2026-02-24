# --- 4a. SEARCH FUNCTIONALITY ---
st.markdown("<div style='margin-top: 5px;'></div>", unsafe_allow_html=True)
search_query = st.text_input("🔍 Search Stock (e.g. RELIANCE, INFIBEAM):", "").upper().strip()

if search_query:
    search_ticker = format_ticker(search_query)
    # సెర్చ్ కోసం ఫ్రెష్ డేటా అవసరం కాబట్టి ఇక్కడ డౌన్లోడ్ చేస్తున్నాం
    s_data = yf.download(search_ticker, period="5d", progress=False, group_by='ticker')
    
    if not s_data.empty:
        # Bullish and Bearish రెండింటినీ చెక్ చేసి బెస్ట్ రిజల్ట్ ఇస్తుంది
        search_res = analyze(search_ticker, s_data, force=True)
        
        if search_res:
            col1, col2, col3, col4, col5 = st.columns([1,1,1,1,2])
            col1.metric("PRICE", search_res['PRICE'])
            col2.metric("DAY %", f"{search_res['DAY%']}%")
            col3.metric("VOL", search_res['VOL'])
            col4.metric("SCORE", search_res['SCORE'])
            
            # Status display with color
            status_color = "#008000" if float(search_res['DAY%']) >= 0 else "#FF0000"
            col5.markdown(f"""
                <div style='background-color: {status_color}; color: white; padding: 10px; 
                border-radius: 5px; text-align: center; font-weight: 800; font-size: 18px;'>
                    {search_res['STATUS']}
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("ఈ స్టాక్‌లో ప్రస్తుతానికి ప్రత్యేకమైన సిగ్నల్స్ (Status) ఏమీ లేవు.")
    else:
        st.error("స్టాక్ డేటా దొరకలేదు. పేరు సరిగ్గా ఉందో లేదో చూడండి.")
