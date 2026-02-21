# --- పాత కోడ్ లోని లాజిక్ అలాగే ఉంచుతూ, కింద ఉన్న DISPLAY సెక్షన్ మాత్రం ఇలా మార్చు ---

if data is not None and not data.empty:
    # 1. DASHBOARD
    st.markdown("#### 📉 DASHBOARD")
    # Columns వాడకుండా డైరెక్ట్ గా మెట్రిక్స్ ఇస్తున్నాను, అప్పుడు మొబైల్ లో ఒకదాని కింద ఒకటి వస్తాయి
    for ticker, name in INDICES.items():
        try:
            if ticker in data.columns.levels[0]:
                df = data[ticker].dropna()
                ltp = float(df['Close'].iloc[-1])
                pct = ((ltp - float(df['Close'].iloc[-2])) / float(df['Close'].iloc[-2])) * 100
                st.metric(f"{name}", f"{ltp:.0f}", f"{pct:.1f}%")
        except: continue

    st.divider()

    # 2. SECTOR RANKS
    st.markdown("#### 📋 SECTOR RANKS")
    sec_rows = []
    # ... (పాత సెక్టార్ ర్యాంక్ లాజిక్ ఇక్కడ ఉండాలి) ...
    if sec_rows:
        df_sec = pd.DataFrame(sec_rows).sort_values("DAY%", ascending=False)
        st.dataframe(df_sec.set_index("SECTOR").style.format("{:.2f}"), use_container_width=True)
        top_sec, bot_sec = df_sec.index[0], df_sec.index[-1]

    st.divider()

    # 3. BUY & SELL TABLES (ఒకదాని కింద ఒకటి)
    st.markdown(f"<div class='bull-head'>🚀 BUY: {top_sec}</div>", unsafe_allow_html=True)
    res_bull = [analyze(s, data, True) for s in SECTOR_MAP[top_sec]['stocks']]
    res_bull = [x for x in res_bull if x]
    if res_bull:
        st.dataframe(pd.DataFrame(res_bull).sort_values(by=["SCORE"], ascending=False), use_container_width=True, hide_index=True)
    
    st.markdown(f"<div class='bear-head'>🩸 SELL: {bot_sec}</div>", unsafe_allow_html=True)
    res_bear = [analyze(s, data, False) for s in SECTOR_MAP[bot_sec]['stocks']]
    res_bear = [x for x in res_bear if x]
    if res_bear:
        st.dataframe(pd.DataFrame(res_bear).sort_values(by=["SCORE"], ascending=False), use_container_width=True, hide_index=True)

    st.divider()

    # 4. INDEPENDENT & BROADER (ఒకదాని కింద ఒకటి)
    st.markdown("#### 🌟 INDEPENDENT (Top 8)")
    # ... (పాత ఇండిపెండెంట్ లాజిక్) ...
    st.dataframe(df_ind_movers, use_container_width=True, hide_index=True)

    st.markdown("#### 🌌 BROADER MARKET (Top 8)")
    # ... (పాత బ్రాడర్ మార్కెట్ లాజిక్) ...
    st.dataframe(df_broader, use_container_width=True, hide_index=True)
