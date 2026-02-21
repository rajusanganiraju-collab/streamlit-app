<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Dashboard</title>
    <style>
        * {
            box-sizing: border-box;
            font-family: Arial, sans-serif;
        }
        body {
            margin: 0;
            padding: 5px;
            background-color: #ffffff;
        }
        
        /* Section Titles */
        .section-header {
            font-size: 14px;
            font-weight: bold;
            display: flex;
            align-items: center;
            margin-top: 15px;
            margin-bottom: 5px;
            text-transform: uppercase;
        }

        /* 1. Dashboard Single Line (Flexbox) */
        .dashboard-container {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid #eee;
        }
        .dash-item {
            text-align: center;
            font-size: 13px; /* Slightly increased */
            font-weight: bold; /* Bold text */
        }
        .dash-val {
            color: #ccc; /* As per your faded look, change if needed */
            margin: 3px 0;
        }
        .badge-green {
            background-color: #e6f4ea;
            color: #1e8e3e;
            padding: 2px 5px;
            border-radius: 4px;
            font-size: 11px;
        }

        /* 2. Table Styles */
        .table-container {
            width: 100%;
            overflow-x: auto; /* Adds scroll if screen is too small, prevents breaking */
        }
        table {
            width: 100%;
            border-collapse: collapse;
            /* table-layout: fixed; prevents table from expanding beyond screen */
        }
        
        /* 3. White Headers with Black Bold Text */
        th {
            background-color: #ffffff; /* White background */
            color: #000000; /* Black text */
            font-weight: 900; /* Extra bold for headings */
            font-size: 11px;
            padding: 8px 2px;
            border-bottom: 2px solid #000; /* Black bottom border to separate header */
            text-align: center;
            text-transform: uppercase;
        }

        /* 4. Table Data - Bold & Size increased without expanding width */
        td {
            padding: 6px 2px; /* Reduced padding to fit more text */
            font-size: 13px; /* Increased font size */
            font-weight: bold; /* Made text bold */
            text-align: center;
            white-space: nowrap; /* Prevents text from breaking into two lines */
            border-bottom: 1px solid #f0f0f0;
        }

        /* Specific text alignment for Stock Names */
        td:first-child, th:first-child {
            text-align: left;
            padding-left: 5px;
        }

        /* Colors for specific cells */
        .text-green { color: #1e8e3e; }
        .text-red { color: #d93025; }
        .bg-green-light { background-color: #e6f4ea; }
        .bg-red-light { background-color: #fce8e6; }
        
        /* Section Backgrounds */
        .bg-buy { background-color: #e6f4ea; padding: 5px; border-radius: 4px; }
        .bg-sell { background-color: #fce8e6; padding: 5px; border-radius: 4px; }
    </style>
</head>
<body>

    <div class="section-header">📈 DASHBOARD</div>
    <div class="dashboard-container">
        <div class="dash-item">NIFTY 50 <div class="dash-val">22415.5</div> <span class="badge-green">↑ 0.5%</span></div>
        <div class="dash-item">BANK NIFTY <div class="dash-val">47172.0</div> <span class="badge-green">↑ 0.7%</span></div>
        <div class="dash-item">FIN NIFTY <div class="dash-val">20912.0</div> <span class="badge-green">↑ 0.6%</span></div>
        <div class="dash-item">SENSEX <div class="dash-val">73800.0</div> <span class="badge-green">↑ 0.5%</span></div>
    </div>

    <div class="section-header">📋 SECTOR RANKS</div>
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
                    <td style="background-color: #1a1a2e; color: white;">DAY%</td>
                    <td class="bg-green-light text-green">1.30</td>
                    <td class="bg-green-light text-green">1.13</td>
                    <td class="bg-green-light text-green">0.80</td>
                    <td class="bg-green-light text-green">0.80</td>
                    <td class="bg-green-light text-green">0.64</td>
                    <td class="bg-green-light text-green">0.43</td>
                </tr>
                <tr>
                    <td style="background-color: #1a1a2e; color: white;">NET%</td>
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
                </tr>
                <tr>
                    <td>BPCL</td>
                    <td>566.30</td>
                    <td>0.40</td>
                    <td>0.37</td>
                    <td class="bg-red-light text-red">-0.78</td>
                    <td>560.50</td>
                    <td>573.53</td>
                    <td>2.2x</td>
                </tr>
            </tbody>
        </table>
    </div>

</body>
</html>
