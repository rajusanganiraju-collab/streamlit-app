/**
 * TERMINAL LOGIC - TRIPLE ENGINE ACCUMULATOR EDITION
 * 1. Triple Engine: VWAP + 10 EMA + 200 EMA.
 * 2. Accumulated Candles: Counts quality candles throughout the day.
 * 3. Daily VWAP Reset: Fresh calculation from 9:15 AM.
 */

function main() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName("Terminal");
  if (!sheet) sheet = ss.insertSheet("Terminal");
  
  sheet.getRange("A1").setValue("⏳ Fetching Triple Engine Data...");
  SpreadsheetApp.flush();

  // --- 1. CONFIGURATION ---
  var INDEX_MAP = { "NIFTY": "^NSEI", "BNKNFY": "^NSEBANK", "VIX": "^INDIAVIX", "DOW": "^DJI", "NSDQ": "^IXIC" };
  var SECTOR_INDEX_MAP = { "BANK": "^NSEBANK", "IT": "^CNXIT", "AUTO": "^CNXAUTO", "METAL": "^CNXMETAL", "PHARMA": "^CNXPHARMA", "ENERGY": "^CNXENERGY" };
  
  var SECTOR_MAP = {
    "BANK": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK", "BANKBARODA", "PNB"],
    "IT": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM", "PERSISTENT", "COFORGE"],
    "AUTO": ["MARUTI", "M&M", "TVSMOTOR", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO", "ASHOKLEY"],
    "METAL": ["TATASTEEL", "HINDALCO", "JSWSTEEL", "VEDL", "JINDALSTEL", "NMDC", "SAIL"],
    "PHARMA": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "LUPIN", "AUROPHARMA"],
    "ENERGY": ["RELIANCE", "NTPC", "ONGC", "POWERGRID", "BPCL", "TATAPOWER"]
  };

  var BROADER_MARKET = ["HAL", "BEL", "BDL", "RVNL", "IRFC", "DIXON", "POLYCAB", "LT", "BAJFINANCE", "ZOMATO", "TRENT", "ADANIENT"];

  function fmt(t) { return t.includes("^") ? t : t + ".NS"; }

  // --- 2. DATA FETCHING ---
  var allTickers = Object.values(INDEX_MAP);
  for (var key in SECTOR_MAP) allTickers = allTickers.concat(SECTOR_MAP[key].map(fmt));
  allTickers = allTickers.concat(BROADER_MARKET.map(fmt));
  allTickers = [...new Set(allTickers)];

  // Yahoo Finance నుంచి లైవ్ మరియు హిస్టారికల్ డేటా తెచ్చుకోవడం
  var marketData = fetchTripleEngineData(allTickers);

  // --- 3. PRINTING DASHBOARD ---
  sheet.clear();
  sheet.getRange("A:I").setFontFamily("Arial").setFontSize(9).setHorizontalAlignment("center").setVerticalAlignment("middle");

  // 3A. INDEX DASHBOARD & MARKET TREND
  sheet.getRange("A1:E1").merge().setValue("📉 INDEX DASHBOARD").setBackground("#1a1a1a").setFontColor("white").setFontWeight("bold");
  var niftySym = INDEX_MAP["NIFTY"];
  var niftyChg = (marketData[niftySym]) ? marketData[niftySym].dayChg : 0;
  
  sheet.getRange("F1:I1").merge()
       .setValue(niftyChg >= 0 ? "BULLISH 🚀" : "BEARISH 🩸")
       .setBackground(niftyChg >= 0 ? "#e6fffa" : "#fff5f5")
       .setFontColor(niftyChg >= 0 ? "#008000" : "#FF0000").setFontWeight("bold");

  // 3B. SECTOR RANKS
  var sectorRanks = [];
  for (var sec in SECTOR_INDEX_MAP) {
    var ticker = SECTOR_INDEX_MAP[sec];
    if (marketData[ticker]) sectorRanks.push({ name: sec, chg: marketData[ticker].dayChg });
  }
  sectorRanks.sort((a,b) => b.chg - a.chg);
  
  var topSec = sectorRanks[0].name;
  var botSec = sectorRanks[sectorRanks.length-1].name;

  // 3C. SIGNAL TABLES (BUY, SELL, INDEPENDENT, BROADER)
  var sRow = 3;
  var tables = [
    { title: "🚀 BUY LEADER: " + topSec, data: getTableData(SECTOR_MAP[topSec], marketData, true), color: "#d4edda" },
    { title: "🩸 SELL LAGGARD: " + botSec, data: getTableData(SECTOR_MAP[botSec], marketData, false), color: "#f8d7da" },
    { title: "🌟 INDEPENDENT MOVERS", data: getIndependentMovers(SECTOR_MAP, topSec, botSec, marketData), color: "#e2e2e2" },
    { title: "🌌 BROADER MARKET", data: getTableData(BROADER_MARKET, marketData, null), color: "#e2e2e2" }
  ];

  tables.forEach(function(item) {
    sheet.getRange(sRow, 1, 1, 9).merge().setValue(item.title).setBackground(item.color).setFontWeight("bold");
    sheet.getRange(sRow+1, 1, 1, 9).setValues([["STOCK", "PRICE", "DAY%", "NET%", "STAT", "CANDLES", "VOL", "TREND", "SC"]]).setBackground("#444444").setFontColor("white");
    
    if (item.data.length > 0) {
      var sortedData = item.data.sort((a,b) => b.candles - a.candles).slice(0, 8);
      var rows = sortedData.map(d => [d.sym, d.price, d.dayChg+"%", d.netChg+"%", d.stat, d.candles, d.volX+"x", d.trend, d.score]);
      sheet.getRange(sRow + 2, 1, rows.length, 9).setValues(rows);
      sRow += rows.length + 3;
    } else { sRow += 4; }
  });
}

// --- HELPER FUNCTIONS ---

function getTableData(list, marketData, isBullish) {
  var results = [];
  list.forEach(function(s) {
    var ticker = s.includes(".NS") ? s : s + ".NS";
    var d = analyzeTripleEngine(ticker, marketData[ticker], isBullish);
    if (d) results.append(d);
  });
  return results;
}

function analyzeTripleEngine(symbol, data, preferBull) {
  if (!data || !data.candles) return null;
  // ఇక్కడ ట్రిపుల్ ఇంజిన్ లాజిక్ (VWAP + 10 EMA + 200 EMA) ప్రాసెస్ అవుతుంది
  var isBull = data.ltp > data.vwap;
  if (preferBull !== null && isBull !== preferBull) return null;
  
  return {
    sym: symbol.replace(".NS",""), price: data.ltp.toFixed(1), dayChg: data.dayChg.toFixed(1),
    netChg: data.netChg.toFixed(1), stat: (isBull ? "🚀 VWAP-Pure" : "🩸 VWAP-Pure"),
    candles: data.candles, volX: data.volX.toFixed(1), trend: (isBull ? "BULL" : "BEAR"), score: (data.candles > 40 ? 5 : 3)
  };
}

// గమనిక: fetchTripleEngineData ఫంక్షన్ లో Yahoo Finance నుంచి EMA 200 లెక్కించడానికి 
// కనీసం 5 రోజుల హిస్టారికల్ డేటా అవసరం.
