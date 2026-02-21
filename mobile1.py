import streamlit as st

# 1. Page Configuration (Wide layout for better table view)
st.set_page_config(page_title="Trading Dashboard", layout="wide", initial_sidebar_state="collapsed")

# 2. Complete HTML & CSS Structure
custom_dashboard_html = """
<style>
    /* Basic Reset */
    * {
        box-sizing: border-box;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    body {
        margin: 0;
        padding: 0;
    }
    
    /* Section Headings */
    .section-header {
        font-size: 14px;
        font-weight: 800;
        display: flex;
        align-items: center;
        margin-top: 20px;
        margin-bottom: 8px;
        text-transform: uppercase;
        padding: 5px;
        border-radius: 4px;
    }
    .bg-buy { background-color: #e6f4ea; color: #000; }
    .bg-sell { background-color: #fce8e6; color: #000; }

    /* 📈 Dashboard Single Line */
    .dashboard-container {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 5px;
        border-bottom: 1px solid #ddd;
        border-top: 1px solid #ddd;
        background-color: #fafafa;
    }
    .dash-item {
        text-align: center;
        font-size: 13px;
        font-weight: bold;
    }
    .dash-val {
        color: #888;
        margin: 4px 0;
        font-size: 12px;
    }
    .badge-green { background-color: #e6f4ea; color: #1e8e3e; padding: 2px 6px; border-radius: 4px; font-size: 11px; }

    /* 📊 Table General Styles */
    .table-container {
        width: 100%;
        overflow-x: auto; /* Adds horizontal scroll on small screens */
        margin-bottom: 20px;
    }
    table {
        width: 100%;
        border-collapse: collapse;
        min-width: 600px; /* Prevents columns from squishing too much */
    }
    
    /* ✅ White Headers, Black Bold Text */
    th {
        background-color: #ffffff !important;
        color: #000000 !important;
        font-weight: 900 !important;
        font-size: 12px;
        padding: 10px 4px;
        border-bottom: 2px solid #000; /* Distinct line below headers */
        text-align: center;
        text-transform: uppercase;
        white-space: nowrap;
    }

    /* ✅ Bold Table Data, Width Maintained */
    td {
        padding: 8px 4px;
        font-size: 13px; /* Slightly increased text size */
        font-weight: 700; /* Bold text for clarity */
        text-align: center;
        white-space: nowrap; /* Keeps text in a single line */
        border-bottom: 1px solid #f0f0f0;
    }

    /* Aligning the first column (Stock names) to the left */
    td:first-child, th:first-child {
        text-align: left;
        padding-left: 8px;
    }

    /* Specific Colors */
    .text-green { color: #1e8e3e; }
    .text-red { color: #d93025; }
    .bg-green-light { background-color: #e6f4ea; }
    .bg-red-light { background-color: #fce8e6; }
    .row-header { background-color: #1a1a2e; color: #ffffff; font-weight: bold; }
</style>

<div class="section-header" style="background: none;">📈 DASHBOARD</div>
<div class="dashboard-container">
    <div class="dash-item">NIFTY 50<div class="dash-val">22415.5</div><span class="badge-green">↑ 0.5%</span></div>
    <div class="dash-item">BANK NIFTY<div class="dash-val">47172.0</div><span class="badge-green">↑ 0.7%</span></div>
    <div class="dash-item">FIN NIFTY<div class="dash-val">20912.0</div><span class="badge-green">↑ 0.6%</span></div>
    <div class="dash-item">SENSEX<div class="dash-val">73800.0</div><span class="badge-green">↑ 0.5%</span></div>
</div>

<div class="section-header" style="background: none;">📋 SECTOR RANKS</div>
<div class="table-container">
    <table>
        <thead>
            <tr>
                <th></th>
                <th>ENERGY</th>
                <th>METAL</th>
                <th>BANK</th>
                <th>REALTY</th>
                <th>FMCG</th>
                <th>AUTO</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td class="row-header">DAY%</td>
                <td class="bg-green-light text-green">1.30</td>
                <td class="bg-green-light text-green">1.13</td>
                <td class="bg-green-light text-green">0.80</td>
                <td class="bg-green-light text-green">0.80</td>
                <td class="bg-green-light text-green">0.64</td>
                <td class="bg-green-light text-green">0.43</td>
            </tr>
            <tr>
                <td class="row-header">NET%</td>
                <td class="bg-green-light text-green">1.37</td>
                <td class="bg-green-light text-green">1.25</td>
                <td class="bg-green-light text-green">0.71</td>
                <td class="bg-green-light text-green">0.36</td>
                <td class="bg-green-light text-green">0.50</td>
                <td class="bg-green-light text-green">0.41</td>
            </tr>
        </tbody>
    </table>
</div>

<div class="section-header bg-buy">🚀 BUY: ENERGY</div>
<div class="table-container">
    <table>
        <thead>
            <tr>
                <th>STOCK</th>
                <th>PRICE</th>
                <th>DAY%</th>
                <th>NET%</th>
                <th>MOVE</th>
                <th>SL</th>
                <th>TGT</th>
                <th>VOL</th>
                <th>SCORE</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>NTPC</td>
                <td class="text-green">372.95</td>
                <td class="text-green">2.80</td>
                <td class="text-green">2.68</td>
                <td class="bg-red-light text-red">-0.11</td>
                <td class="text-green">362.70</td>
                <td class="text-green">380.41</td>
                <td>3.2x</td>
                <td>11</td>
            </tr>
            <tr>
                <td>TATAPOWER</td>
                <td>378.00</td>
                <td>2.55</td>
                <td>2.55</td>
                <td class="bg-green-light text-green">0.00</td>
                <td>369.25</td>
                <td>385.56</td>
                <td>0.9x</td>
                <td>7</td>
            </tr>
        </tbody>
    </table>
</div>

<div class="section-header bg-sell">🩸 SELL: IT</div>
<div class="table-container">
    <table>
        <thead>
            <tr>
                <th>STOCK</th>
                <th>PRICE</th>
                <th>DAY%</th>
                <th>NET%</th>
                <th>MOVE</th>
                <th>SL</th>
                <th>TGT</th>
                <th>VOL</th>
                <th>SCORE</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>PERSISTENT</td>
                <td>3352.00</td>
                <td>-2.73</td>
                <td>-3.30</td>
                <td class="bg-red-light text-red">-0.57</td>
                <td>3274.00</td>
                <td>3200.15</td>
                <td>2.2x</td>
                <td>7</td>
            </tr>
        </tbody>
    </table>
</div>
"""

# 3. Render HTML in Streamlit
st.markdown(custom_dashboard_html, unsafe_allow_html=True)
