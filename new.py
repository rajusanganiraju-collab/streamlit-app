import streamlit as st
import yfinance as yf
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import json
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os
from datetime import datetime, time as dt_time, timedelta
from streamlit_autorefresh import st_autorefresh
from concurrent.futures import ThreadPoolExecutor, as_completed
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 🤖 AI/ML IMPORTS
# ============================================================
try:
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False

# --- 1. PAGE CONFIGURATION ---
st.set_page_config(page_title="Market Heatmap Pro", page_icon="📊", layout="wide")

# --- 2. GOOGLE SHEETS CONNECTION ---
@st.cache_resource
def init_connection():
    creds_json = st.secrets["gcp_service_account"]
    creds_dict = json.loads(creds_json)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

client = init_connection()

try:
    db_sheet = client.open("Trading_DB")
    port_ws = db_sheet.worksheet("Portfolio")
    trade_ws = db_sheet.worksheet("TradeBook")
except Exception as e:
    st.error(f"గూగుల్ షీట్ కనెక్ట్ అవ్వలేదు బాస్! Error: {e}")
    st.stop()

# --- 3. DATA LOAD & SAVE FUNCTIONS ---
def load_portfolio():
    try:
        records = port_ws.get_all_records()
        df = pd.DataFrame(records) if records else pd.DataFrame(columns=['Symbol', 'Buy_Price', 'Quantity', 'Date', 'SL', 'T1', 'T2'])
        if not df.empty and 'Stock Name' in df.columns:
            df.rename(columns={'Stock Name': 'Symbol', 'Buy Price': 'Buy_Price', 'Buy Date': 'Date'}, inplace=True)
            for col in ['SL', 'T1', 'T2']:
                if col not in df.columns: df[col] = 0.0
            save_portfolio(df)
        return df
    except:
        return pd.DataFrame(columns=['Symbol', 'Buy_Price', 'Quantity', 'Date', 'SL', 'T1', 'T2'])

def load_closed_trades():
    try:
        records = trade_ws.get_all_records()
        df = pd.DataFrame(records) if records else pd.DataFrame(columns=['Sell_Date', 'Symbol', 'Quantity', 'Buy_Price', 'Sell_Price', 'PnL_Rs', 'PnL_Pct'])
        if not df.empty and 'Stock Name' in df.columns:
            df.rename(columns={'Stock Name': 'Symbol', 'Buy Price': 'Buy_Price', 'Sell Price': 'Sell_Price', 'Sell Date': 'Sell_Date', 'Profit/Loss': 'PnL_Rs'}, inplace=True)
            if 'PnL_Pct' not in df.columns: df['PnL_Pct'] = 0.0
            save_closed_trades(df)
        return df
    except:
        return pd.DataFrame(columns=['Sell_Date', 'Symbol', 'Quantity', 'Buy_Price', 'Sell_Price', 'PnL_Rs', 'PnL_Pct'])

def save_portfolio(df):
    port_ws.clear()
    df = df.fillna("")
    port_ws.update([df.columns.values.tolist()] + df.values.tolist())

def save_closed_trades(df):
    trade_ws.clear()
    df = df.fillna("")
    trade_ws.update([df.columns.values.tolist()] + df.values.tolist())

# --- 4. AUTO RUN & STATE MANAGEMENT ---
st_autorefresh(interval=60000, key="datarefresh")

if 'pinned_stocks' not in st.session_state:
    st.session_state.pinned_stocks = []
if 'custom_alerts' not in st.session_state:
    st.session_state.custom_alerts = {}
if 'ml_models' not in st.session_state:
    st.session_state.ml_models = {}
if 'backtest_results' not in st.session_state:
    st.session_state.backtest_results = {}

def toggle_pin(symbol):
    if symbol in st.session_state.pinned_stocks:
        st.session_state.pinned_stocks.remove(symbol)
    else:
        st.session_state.pinned_stocks.append(symbol)

# ============================================================
# ⚡ PERFORMANCE OPTIMIZATION: Parallel Fetcher
# ============================================================
def fetch_single_ticker(ticker, period="2y"):
    """Fetch single ticker data with error handling"""
    try:
        data = yf.download(ticker, period=period, progress=False, auto_adjust=True)
        return ticker, data
    except:
        return ticker, pd.DataFrame()

@st.cache_data(ttl=150)
def fetch_batch_parallel(tickers, period="2y", max_workers=30):
    """
    ⚡ PERFORMANCE BOOST: Parallel download using ThreadPoolExecutor
    Original: Sequential → New: Parallel (3-5x faster)
    """
    results = {}
    # yfinance batch download is faster than individual calls
    try:
        if len(tickers) == 1:
            data = yf.download(tickers[0], period=period, progress=False, auto_adjust=True)
            results[tickers[0]] = data
        else:
            data = yf.download(
                tickers, period=period, progress=False,
                group_by='ticker', threads=True, auto_adjust=True
            )
            for t in tickers:
                try:
                    if isinstance(data.columns, pd.MultiIndex):
                        results[t] = data[t].dropna(how='all')
                    else:
                        results[t] = data
                except:
                    results[t] = pd.DataFrame()
    except Exception as e:
        # Fallback: parallel individual fetches
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_single_ticker, t, period): t for t in tickers}
            for future in as_completed(futures):
                ticker, df = future.result()
                results[ticker] = df
    return results

# ============================================================
# 🤖 AI/ML ENGINE
# ============================================================
def build_ml_features(df):
    """
    Build feature matrix for ML model from OHLCV data
    Features: RSI, MACD, BB, ATR, Volume ratio, Price position
    """
    df = df.copy()
    close = df['Close']
    high = df['High']
    low = df['Low']
    volume = df['Volume'] if 'Volume' in df.columns else pd.Series(1, index=df.index)

    # EMAs
    df['EMA_9']  = close.ewm(span=9,  adjust=False).mean()
    df['EMA_21'] = close.ewm(span=21, adjust=False).mean()
    df['EMA_50'] = close.ewm(span=50, adjust=False).mean()

    # RSI
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    df['RSI'] = 100 - (100 / (1 + gain / loss.replace(0, np.nan))).fillna(100)

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df['MACD']        = ema12 - ema26
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist']   = df['MACD'] - df['MACD_Signal']

    # Bollinger Bands
    bb_mid       = close.rolling(20).mean()
    bb_std       = close.rolling(20).std()
    df['BB_Pct'] = (close - (bb_mid - 2*bb_std)) / (4*bb_std + 1e-9)

    # ATR (normalized)
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    df['ATR_Pct'] = tr.ewm(span=14, adjust=False).mean() / close

    # Volume ratio
    df['Vol_Ratio'] = volume / (volume.rolling(20).mean() + 1e-9)

    # Price position in day range
    df['Price_Pos']  = (close - low) / (high - low + 1e-9)

    # Candle body direction
    df['Body_Dir']   = np.sign(close - df['Open']) if 'Open' in df.columns else 0

    # Momentum
    df['Mom_5']  = close.pct_change(5)
    df['Mom_10'] = close.pct_change(10)

    # Gap from VWAP proxy
    vwap_proxy   = (high + low + close) / 3
    df['VWAP_Gap'] = (close - vwap_proxy) / vwap_proxy

    feature_cols = [
        'EMA_9', 'EMA_21', 'EMA_50', 'RSI',
        'MACD', 'MACD_Signal', 'MACD_Hist',
        'BB_Pct', 'ATR_Pct', 'Vol_Ratio',
        'Price_Pos', 'Body_Dir', 'Mom_5', 'Mom_10', 'VWAP_Gap'
    ]

    # Normalize price-based features
    for col in ['EMA_9', 'EMA_21', 'EMA_50']:
        df[col] = df[col] / close

    return df[feature_cols].dropna()


@st.cache_data(ttl=3600, show_spinner=False)
def train_ml_model(symbol, _df_raw):
    """
    🤖 Train RandomForest + GradientBoosting ensemble
    Target: Will next candle close HIGHER than open? (1=Yes, 0=No)
    Returns model, scaler, accuracy
    """
    if not ML_AVAILABLE or _df_raw is None or len(_df_raw) < 200:
        return None, None, 0.0

    try:
        features = build_ml_features(_df_raw)
        if len(features) < 150:
            return None, None, 0.0

        # Target: next candle direction
        next_close = _df_raw['Close'].shift(-1)
        next_open  = _df_raw['Open'].shift(-1) if 'Open' in _df_raw.columns else _df_raw['Close']
        target = (next_close > next_open).astype(int)
        target = target.reindex(features.index).dropna()

        X = features.loc[target.index]
        y = target

        if len(X) < 100:
            return None, None, 0.0

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, shuffle=False
        )

        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_test_s  = scaler.transform(X_test)

        # Ensemble: RF + GBM
        rf  = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42, n_jobs=-1)
        gbm = GradientBoostingClassifier(n_estimators=100, max_depth=4, learning_rate=0.05, random_state=42)

        rf.fit(X_train_s, y_train)
        gbm.fit(X_train_s, y_train)

        # Average probabilities
        rf_prob  = rf.predict_proba(X_test_s)[:, 1]
        gbm_prob = gbm.predict_proba(X_test_s)[:, 1]
        avg_prob = (rf_prob + gbm_prob) / 2
        y_pred   = (avg_prob >= 0.5).astype(int)

        acc = accuracy_score(y_test, y_pred)

        # Store both models for prediction
        return {'rf': rf, 'gbm': gbm}, scaler, round(acc * 100, 1)

    except Exception as e:
        return None, None, 0.0


def predict_next_candle(symbol, df_raw, models_dict, scaler):
    """
    🤖 Predict next candle: Bullish / Bearish + confidence %
    """
    if models_dict is None or scaler is None or df_raw is None or len(df_raw) < 50:
        return "⚪ No Signal", 50.0

    try:
        features = build_ml_features(df_raw)
        if features.empty:
            return "⚪ No Signal", 50.0

        last_features = features.iloc[[-1]]
        last_scaled   = scaler.transform(last_features)

        rf_prob  = models_dict['rf'].predict_proba(last_scaled)[0][1]
        gbm_prob = models_dict['gbm'].predict_proba(last_scaled)[0][1]
        avg_prob = (rf_prob + gbm_prob) / 2
        conf     = round(avg_prob * 100, 1)

        if avg_prob >= 0.65:
            return f"🟢 Bullish", conf
        elif avg_prob <= 0.35:
            return f"🔴 Bearish", round((1 - avg_prob) * 100, 1)
        else:
            return f"🟡 Neutral", 50.0

    except:
        return "⚪ No Signal", 50.0


# ============================================================
# 📈 BACKTESTING ENGINE
# ============================================================
def run_backtest(df_raw, strategy="VWAP_Momentum", initial_capital=100000):
    """
    📈 Backtest engine supporting multiple intraday strategies.
    Returns detailed metrics: Win Rate, Sharpe, Max DD, Total Return
    """
    if df_raw is None or len(df_raw) < 100:
        return None

    df = df_raw.copy()
    df['EMA_9']  = df['Close'].ewm(span=9,  adjust=False).mean()
    df['EMA_21'] = df['Close'].ewm(span=21, adjust=False).mean()
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['VWAP']   = (df['High'] + df['Low'] + df['Close']) / 3

    delta = df['Close'].diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    df['RSI'] = (100 - (100 / (1 + gain / loss.replace(0, np.nan)))).fillna(50)

    tr = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - df['Close'].shift(1)).abs(),
        (df['Low']  - df['Close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    df['ATR'] = tr.ewm(span=14, adjust=False).mean()

    trades     = []
    capital    = initial_capital
    equity     = [capital]
    position   = None

    for i in range(50, len(df) - 1):
        row      = df.iloc[i]
        next_row = df.iloc[i + 1]
        price    = float(row['Close'])
        atr      = float(row['ATR']) if row['ATR'] > 0 else price * 0.01

        # --- Entry Logic per Strategy ---
        signal = None

        if strategy == "VWAP_Momentum":
            if (price > row['VWAP'] and
                price > row['EMA_9'] and
                row['RSI'] > 55 and
                row['RSI'] < 75 and
                position is None):
                signal = "BUY"
            elif (price < row['VWAP'] and
                  price < row['EMA_9'] and
                  row['RSI'] < 45 and
                  position is None):
                signal = "SELL"

        elif strategy == "EMA_Crossover":
            prev = df.iloc[i - 1]
            if (prev['EMA_9'] <= prev['EMA_21'] and
                row['EMA_9'] > row['EMA_21'] and
                position is None):
                signal = "BUY"
            elif (prev['EMA_9'] >= prev['EMA_21'] and
                  row['EMA_9'] < row['EMA_21'] and
                  position is None):
                signal = "SELL"

        elif strategy == "RSI_Reversal":
            if row['RSI'] < 30 and price > row['EMA_50'] and position is None:
                signal = "BUY"
            elif row['RSI'] > 70 and price < row['EMA_50'] and position is None:
                signal = "SELL"

        elif strategy == "Momentum_Breakout":
            high_20 = df['High'].iloc[i-20:i].max()
            low_20  = df['Low'].iloc[i-20:i].min()
            if price > high_20 * 0.995 and row['RSI'] > 55 and position is None:
                signal = "BUY"
            elif price < low_20 * 1.005 and row['RSI'] < 45 and position is None:
                signal = "SELL"

        # --- Execute Entry ---
        if signal == "BUY" and position is None:
            qty      = int(capital * 0.95 / price)
            sl       = price - 1.5 * atr
            target   = price + 3.0 * atr
            position = {'type': 'LONG', 'entry': price, 'qty': qty, 'sl': sl, 'target': target, 'entry_idx': i}

        elif signal == "SELL" and position is None:
            qty      = int(capital * 0.95 / price)
            sl       = price + 1.5 * atr
            target   = price - 3.0 * atr
            position = {'type': 'SHORT', 'entry': price, 'qty': qty, 'sl': sl, 'target': target, 'entry_idx': i}

        # --- Exit Logic ---
        if position is not None:
            exit_price = None
            exit_reason = ""
            np_price = float(next_row['Close'])

            if position['type'] == 'LONG':
                if np_price <= position['sl']:
                    exit_price = position['sl']
                    exit_reason = "SL Hit"
                elif np_price >= position['target']:
                    exit_price = position['target']
                    exit_reason = "Target Hit"
                elif (i - position['entry_idx']) >= 5:
                    exit_price = np_price
                    exit_reason = "Time Exit"

            elif position['type'] == 'SHORT':
                if np_price >= position['sl']:
                    exit_price = position['sl']
                    exit_reason = "SL Hit"
                elif np_price <= position['target']:
                    exit_price = position['target']
                    exit_reason = "Target Hit"
                elif (i - position['entry_idx']) >= 5:
                    exit_price = np_price
                    exit_reason = "Time Exit"

            if exit_price is not None:
                if position['type'] == 'LONG':
                    pnl = (exit_price - position['entry']) * position['qty']
                else:
                    pnl = (position['entry'] - exit_price) * position['qty']

                capital += pnl
                equity.append(capital)

                trades.append({
                    'Entry': position['entry'],
                    'Exit': exit_price,
                    'Type': position['type'],
                    'PnL': round(pnl, 2),
                    'Result': '✅ Win' if pnl > 0 else '❌ Loss',
                    'Reason': exit_reason,
                    'Idx': i
                })
                position = None

    if not trades:
        return None

    df_trades  = pd.DataFrame(trades)
    total_trades = len(df_trades)
    wins         = (df_trades['PnL'] > 0).sum()
    win_rate     = round(wins / total_trades * 100, 1)
    total_pnl    = df_trades['PnL'].sum()
    total_return = round((total_pnl / initial_capital) * 100, 2)

    # Sharpe Ratio
    returns   = pd.Series(equity).pct_change().dropna()
    sharpe    = round((returns.mean() / (returns.std() + 1e-9)) * np.sqrt(252), 2)

    # Max Drawdown
    eq_series = pd.Series(equity)
    rolling_max = eq_series.cummax()
    drawdown    = (eq_series - rolling_max) / rolling_max
    max_dd      = round(drawdown.min() * 100, 2)

    # Avg Win / Loss
    avg_win  = round(df_trades[df_trades['PnL'] > 0]['PnL'].mean(), 2) if wins > 0 else 0
    avg_loss = round(df_trades[df_trades['PnL'] <= 0]['PnL'].mean(), 2) if (total_trades - wins) > 0 else 0
    profit_factor = round(abs(df_trades[df_trades['PnL'] > 0]['PnL'].sum() /
                              (df_trades[df_trades['PnL'] <= 0]['PnL'].sum() + 1e-9)), 2)

    return {
        'trades':         df_trades,
        'equity':         equity,
        'total_trades':   total_trades,
        'win_rate':       win_rate,
        'total_return':   total_return,
        'sharpe':         sharpe,
        'max_dd':         max_dd,
        'avg_win':        avg_win,
        'avg_loss':       avg_loss,
        'profit_factor':  profit_factor,
        'final_capital':  round(capital, 2)
    }


def render_backtest_results(result, strategy_name, symbol):
    """Render backtest results as a styled terminal table"""
    if result is None:
        return "<div style='padding:15px; color:#888; text-align:center;'>Not enough data for backtest.</div>"

    wr_color   = "#3fb950" if result['win_rate'] >= 50 else "#f85149"
    ret_color  = "#3fb950" if result['total_return'] >= 0 else "#f85149"
    dd_color   = "#f85149"
    sh_color   = "#3fb950" if result['sharpe'] >= 1 else "#ffd700"
    pf_color   = "#3fb950" if result['profit_factor'] >= 1.5 else "#ffd700"

    html = f"""
    <table class="term-table" style="margin-bottom:10px;">
      <thead>
        <tr><th colspan="6" style="background-color:#005a9e; color:white; text-align:left; padding-left:10px; font-size:14px;">
          📈 BACKTEST: {symbol} | Strategy: {strategy_name}
        </th></tr>
        <tr style="background-color:#21262d;">
          <th>TOTAL TRADES</th><th>WIN RATE</th><th>TOTAL RETURN</th>
          <th>SHARPE RATIO</th><th>MAX DRAWDOWN</th><th>PROFIT FACTOR</th>
        </tr>
      </thead>
      <tbody>
        <tr class="row-dark">
          <td><b>{result['total_trades']}</b></td>
          <td style="color:{wr_color}; font-weight:bold;">{result['win_rate']}%</td>
          <td style="color:{ret_color}; font-weight:bold;">{"+" if result['total_return']>0 else ""}{result['total_return']}%</td>
          <td style="color:{sh_color}; font-weight:bold;">{result['sharpe']}</td>
          <td style="color:{dd_color}; font-weight:bold;">{result['max_dd']}%</td>
          <td style="color:{pf_color}; font-weight:bold;">{result['profit_factor']}x</td>
        </tr>
        <tr class="row-light">
          <td colspan="2">💰 Avg Win: <span style="color:#3fb950;">+₹{result['avg_win']:,.0f}</span></td>
          <td colspan="2">💸 Avg Loss: <span style="color:#f85149;">₹{result['avg_loss']:,.0f}</span></td>
          <td colspan="2">🏦 Final Capital: <span style="color:#58a6ff;">₹{result['final_capital']:,.0f}</span></td>
        </tr>
      </tbody>
    </table>
    """
    return html


def render_equity_curve(equity_data, symbol, strategy):
    """Render interactive equity curve chart"""
    if not equity_data:
        return

    fig = go.Figure()
    initial = equity_data[0]

    colors = ['#2ea043' if v >= initial else '#da3633' for v in equity_data]

    fig.add_trace(go.Scatter(
        x=list(range(len(equity_data))),
        y=equity_data,
        mode='lines',
        fill='tozeroy',
        fillcolor='rgba(46, 160, 67, 0.1)',
        line=dict(color='#2ea043', width=2),
        name='Equity',
        hovertemplate="Trade %{x}: ₹%{y:,.0f}<extra></extra>"
    ))

    fig.add_hline(y=initial, line_dash="dash", line_color="#888", line_width=1)

    fig.update_layout(
        title=dict(text=f"📈 Equity Curve — {symbol} ({strategy})", font=dict(color='#e6edf3', size=13)),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        height=250,
        margin=dict(l=0, r=0, t=35, b=0),
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(showgrid=True, gridcolor='#21262d', tickfont=dict(color='#888'), zeroline=False, side='right'),
        hovermode='x unified',
        hoverlabel=dict(bgcolor="#161b22", font_color="#ffffff")
    )

    st.plotly_chart(fig, use_container_width=True)


# ============================================================
# CSS FOR STYLING (same as original + additions)
# ============================================================
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {display: none !important;}
    .stApp { background-color: #0e1117; color: #ffffff; }
    .block-container { padding-top: 1rem !important; padding-bottom: 0rem !important; margin-top: -10px; }

    .stRadio label, .stRadio p, div[role="radiogroup"] p { color: #ffffff !important; font-weight: normal !important; }
    div.stButton > button p, div.stButton > button span { color: #ffffff !important; font-weight: normal !important; font-size: 14px !important; }

    .t-name { font-size: 13px; font-weight: normal !important; margin-bottom: 2px; }
    .t-price { font-size: 17px; font-weight: normal !important; margin-bottom: 2px; }
    .t-pct { font-size: 12px; font-weight: normal !important; }
    .t-score { position: absolute; top: 3px; left: 3px; font-size: 10px; background: rgba(0,0,0,0.4); padding: 1px 4px; border-radius: 3px; color: #ffd700; font-weight: normal !important; }
    .t-ml { position: absolute; bottom: 3px; right: 3px; font-size: 9px; background: rgba(0,0,0,0.5); padding: 1px 3px; border-radius: 3px; }

    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) {
        display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important;
        justify-content: space-between !important; align-items: center !important; gap: 6px !important; width: 100% !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) > div[data-testid="stElementContainer"]:has(.filter-marker) { display: none !important; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) > div[data-testid="stElementContainer"] {
        flex: 1 1 0px !important; min-width: 0 !important; width: 100% !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) div.stButton > button { width: 100% !important; height: 38px !important; padding: 0px !important; }
    div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .filter-marker) div.stButton > button p { font-size: clamp(9px, 2.5vw, 13px) !important; white-space: nowrap !important; margin: 0 !important; }

    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { display: grid !important; gap: 12px !important; align-items: start !important; }
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div:nth-child(1) { display: none !important; }
    @media screen and (min-width: 1700px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(8, 1fr) !important; } }
    @media screen and (min-width: 1400px) and (max-width: 1699px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(6, 1fr) !important; } }
    @media screen and (min-width: 1100px) and (max-width: 1399px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(5, 1fr) !important; } }
    @media screen and (min-width: 850px) and (max-width: 1099px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(4, 1fr) !important; } }
    @media screen and (min-width: 651px) and (max-width: 849px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(3, 1fr) !important; } }
    @media screen and (max-width: 650px) { div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) { grid-template-columns: repeat(2, 1fr) !important; gap: 6px !important; } }

    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div[data-testid="stVerticalBlock"] {
        background-color: #161b22 !important; border: 1px solid #30363d !important; border-radius: 8px !important;
        padding: 5px !important; position: relative !important; width: 100% !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div:nth-child(1) .fluid-board) > div[data-testid="stVerticalBlock"] div[data-testid="stCheckbox"] {
        position: absolute !important; top: 10px !important; left: 10px !important; z-index: 100 !important;
    }
    div[data-testid="stCheckbox"] label { padding: 0 !important; min-height: 0 !important; }
    div.stButton > button { border-radius: 8px !important; border: 1px solid #30363d !important; background-color: #161b22 !important; height: 45px !important; }

    .heatmap-grid { display: grid; grid-template-columns: repeat(10, 1fr); gap: 8px; padding: 5px 0; }
    .stock-card { border-radius: 4px; padding: 8px 4px; text-align: center; text-decoration: none !important; color: white !important; display: flex; flex-direction: column; justify-content: center; height: 90px; position: relative; box-shadow: 0 1px 3px rgba(0,0,0,0.3); transition: transform 0.2s; }
    .stock-card:hover { transform: scale(1.05); z-index: 10; box-shadow: 0 4px 8px rgba(0,0,0,0.5); }
    .bull-card { background-color: #1e5f29 !important; } .bear-card { background-color: #b52524 !important; } .neut-card { background-color: #30363d !important; }
    .idx-card { background-color: #0d47a1 !important; border: 1px solid #1976d2; }
    @media screen and (max-width: 1400px) { .heatmap-grid { grid-template-columns: repeat(8, 1fr); } }
    @media screen and (max-width: 1100px) { .heatmap-grid { grid-template-columns: repeat(6, 1fr); } }
    @media screen and (max-width: 800px) { .heatmap-grid { grid-template-columns: repeat(4, 1fr); } }
    @media screen and (max-width: 600px) { .heatmap-grid { grid-template-columns: repeat(3, 1fr); gap: 6px; } .stock-card { height: 95px; } .t-name { font-size: 12px; } .t-price { font-size: 16px; } .t-pct { font-size: 11px; } }
    .custom-hr { border: 0; height: 1px; background: #30363d; margin: 15px 0; }

    .term-table { width: 100%; border-collapse: collapse; margin-bottom: 15px; font-family: monospace; font-size: 11.5px; color: #e6edf3; background-color: #0e1117; table-layout: fixed; }
    .term-table th { padding: 6px 4px; text-align: center; border: 1px solid #30363d; font-weight: bold; overflow: hidden; }
    .term-table td { padding: 6px 4px; text-align: center; border: 1px solid #30363d; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .term-table a { color: inherit; text-decoration: none; border-bottom: 1px dashed rgba(255,255,255,0.4); }
    .term-table a:hover { color: #58a6ff !important; text-decoration: none; border-bottom: 1px solid #58a6ff; }

    .term-head-buy { background-color: #1e5f29; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
    .term-head-sell { background-color: #b52524; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
    .term-head-ind { background-color: #9e6a03; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
    .term-head-brd { background-color: #0d47a1; color: white; text-align: left !important; padding-left: 10px !important; font-size:13px; }
    .term-head-port { background-color: #4a148c; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
    .term-head-swing { background-color: #005a9e; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
    .term-head-high { background-color: #b71c1c; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
    .term-head-levels { background-color: #004d40; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
    .term-head-ml { background-color: #1a237e; color: white; text-align: left !important; padding-left: 10px !important; font-size:14px; }
    .row-dark { background-color: #161b22; } .row-light { background-color: #0e1117; }
    .text-green { color: #3fb950; font-weight: bold; } .text-red { color: #f85149; font-weight: bold; }
    .t-symbol { text-align: left !important; font-weight: bold; }
    .port-total { background-color: #21262d; font-weight: bold; font-size: 13px; }

    .ml-badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold; margin-left: 4px; }
    .ml-bull { background-color: rgba(46,160,67,0.3); color: #3fb950; border: 1px solid #2ea043; }
    .ml-bear { background-color: rgba(218,54,51,0.3); color: #f85149; border: 1px solid #da3633; }
    .ml-neut { background-color: rgba(48,54,61,0.5); color: #8b949e; border: 1px solid #30363d; }

    .metric-box { background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 12px; text-align: center; }
    .metric-value { font-size: 22px; font-weight: bold; }
    .metric-label { font-size: 11px; color: #8b949e; margin-top: 3px; }
    </style>
""", unsafe_allow_html=True)

# --- 5. DATA SETUP & SECTOR MAPPING ---
INDICES_MAP = {"^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY", "^INDIAVIX": "INDIA VIX", "^DJI": "DOW", "^IXIC": "NSDQ"}
TV_INDICES_URL = {"^NSEI": "NSE:NIFTY", "^NSEBANK": "NSE:BANKNIFTY", "^INDIAVIX": "NSE:INDIAVIX", "^DJI": "CAPITALCOM:DOWJONES", "^IXIC": "NASDAQ:IXIC"}

SECTOR_INDICES_MAP = {
    "^CNXIT": "NIFTY IT", "^CNXAUTO": "NIFTY AUTO", "^CNXMETAL": "NIFTY METAL",
    "^CNXPHARMA": "NIFTY PHARMA", "^CNXFMCG": "NIFTY FMCG", "^CNXENERGY": "NIFTY ENERGY", "^CNXREALTY": "NIFTY REALTY"
}
TV_SECTOR_URL = {
    "^CNXIT": "NSE:CNXIT", "^CNXAUTO": "NSE:CNXAUTO", "^CNXMETAL": "NSE:CNXMETAL",
    "^CNXPHARMA": "NSE:CNXPHARMA", "^CNXFMCG": "NSE:CNXFMCG", "^CNXENERGY": "NSE:CNXENERGY", "^CNXREALTY": "NSE:CNXREALTY"
}
COMMODITY_MAP = {"GC=F": "GOLD", "SI=F": "SILVER", "CL=F": "CRUDE OIL", "NG=F": "NATURAL GAS", "HG=F": "COPPER"}

NIFTY_50_SECTORS = {
    "PHARMA": ["SUNPHARMA", "CIPLA", "DRREDDY", "APOLLOHOSP"],
    "IT": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM"],
    "BANK": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK"],
    "FINANCE": ["BAJFINANCE", "BAJAJFINSV", "HDFCLIFE", "SBILIFE", "SHRIRAMFIN"],
    "ENERGY": ["RELIANCE", "ONGC", "NTPC", "POWERGRID", "COALINDIA", "BPCL"],
    "AUTO": ["TATAMOTORS", "M&M", "MARUTI", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO"],
    "METAL": ["TATASTEEL", "JSWSTEEL", "HINDALCO"],
    "FMCG": ["ITC", "HINDUNILVR", "NESTLEIND", "BRITANNIA", "TATACONSUM"],
    "INFRA_CEMENT": ["LT", "ULTRACEMCO", "GRASIM"],
    "OTHERS": ["BHARTIARTL", "ASIANPAINT", "TITAN", "ADANIENT", "ADANIPORTS", "TRENT", "BEL"]
}
NIFTY_50 = [stock for sector in NIFTY_50_SECTORS.values() for stock in sector]

FNO_STOCKS = [
    "AARTIIND", "ABB", "ABBOTINDIA", "ABCAPITAL", "ABFRL", "ACC", "ADANIENSOL", "ADANIENT", "ADANIPORTS",
    "ALKEM", "AMBUJACEM", "ANGELONE", "APOLLOHOSP", "APOLLOTYRE", "ASHOKLEY", "ASIANPAINT", "ASTRAL", "ATUL",
    "AUBANK", "AUROPHARMA", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE", "BALKRISIND", "BALRAMCHIN",
    "BANDHANBNK", "BANKBARODA", "BATAINDIA", "BEL", "BERGEPAINT", "BHARATFORG", "BHARTIARTL", "BHEL", "BIOCON",
    "BOSCHLTD", "BPCL", "BRITANNIA", "BSE", "CANBK", "CANFINHOME", "CDSL", "CHAMBLFERT", "CHOLAFIN", "CIPLA",
    "COALINDIA", "COFORGE", "COLPAL", "CONCOR", "COROMANDEL", "CROMPTON", "CUB", "CUMMINSIND", "DABUR", "DALBHARAT",
    "DEEPAKNTR", "DIVISLAB", "DIXON", "DLF", "DRREDDY", "EICHERMOT", "ESCORTS", "EXIDEIND", "FEDERALBNK", "GAIL",
    "GLENMARK", "GMRINFRA", "GNFC", "GODREJCP", "GODREJPROP", "GRANULES", "GRASIM", "GUJGASLTD", "HAL", "HAVELLS",
    "HCLTECH", "HDFCAMC", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDCOPPER", "HINDPETRO", "HINDUNILVR",
    "HUDCO", "ICICIBANK", "ICICIGI", "ICICIPRULI", "IDEA", "IDFCFIRSTB", "IEX", "IGL", "INDHOTEL", "INDIACEM",
    "INDIAMART", "INDIGO", "INDUSINDBK", "INDUSTOWER", "INFY", "IOC", "IPCALAB", "IRCTC", "IRFC", "ITC", "JINDALSTEL",
    "JSWSTEEL", "JUBLFOOD", "KOTAKBANK", "LALPATHLAB", "LAURUSLABS", "LICHSGFIN", "LT", "LTIM", "LTTS", "LUPIN",
    "M&M", "M&MFIN", "MANAPPURAM", "MARICO", "MARUTI", "MCX", "METROPOLIS", "MFSL", "MGL", "MOTHERSON", "MPHASIS",
    "MRF", "MUTHOOTFIN", "NATIONALUM", "NAUKRI", "NAVINFLUOR", "NCC", "NESTLEIND", "NMDC", "NTPC", "OBEROIRLTY",
    "OFSS", "ONGC", "PAGEIND", "PEL", "PERSISTENT", "PETRONET", "PFC", "PIDILITIND", "PIIND", "PNB", "POLYCAB",
    "POWERGRID", "PRESTIGE", "PVRINOX", "RAMCOCEM", "RBLBANK", "RECLTD", "RELIANCE", "SAIL", "SBICARD", "SBILIFE",
    "SBIN", "SHREECEM", "SHRIRAMFIN", "SIEMENS", "SRF", "SUNPHARMA", "SUNTV", "SYNGENE", "TATACHEM", "TATACOMM",
    "TATACONSUM", "TATAMOTORS", "TATAPOWER", "TATASTEEL", "TCS", "TECHM", "TITAN", "TORNTPHARM", "TRENT", "TVSMOTOR",
    "UBL", "ULTRACEMCO", "UPL", "VEDL", "VOLTAS", "WIPRO", "ZEEL", "ZOMATO", "ZYDUSLIFE"
]

def get_minutes_passed():
    now = datetime.now()
    if now.weekday() >= 5 or now.time() > dt_time(15, 30): return 375
    open_time = now.replace(hour=9, minute=15, second=0)
    return min(375, max(1, int((now - open_time).total_seconds() / 60)))

# ============================================================
# ⚡ OPTIMIZED MAIN DATA FETCH
# ============================================================
@st.cache_data(ttl=150)
def fetch_all_data():
    port_df   = load_portfolio()
    port_stocks = [str(sym).upper().strip() for sym in port_df['Symbol'].tolist() if str(sym).strip() != ""]
    all_stocks  = set(NIFTY_50 + FNO_STOCKS + port_stocks)

    # ⚡ Single batch call (faster than multiple calls)
    tkrs = (list(INDICES_MAP.keys()) + list(SECTOR_INDICES_MAP.keys()) +
            list(COMMODITY_MAP.keys()) + [f"{t}.NS" for t in all_stocks if t])

    # ⚡ Use threads=True for parallel internal fetching
    data = yf.download(tkrs, period="2y", progress=False, group_by='ticker', threads=True, auto_adjust=True)

    results  = []
    minutes  = get_minutes_passed()
    nifty_dist = 0.1

    if "^NSEI" in data.columns.levels[0]:
        try:
            n_df  = data["^NSEI"].dropna(subset=['Close'])
            if not n_df.empty:
                n_ltp  = float(n_df['Close'].iloc[-1])
                n_vwap = (float(n_df['High'].iloc[-1]) + float(n_df['Low'].iloc[-1]) + n_ltp) / 3
                if n_vwap > 0:
                    nifty_dist = abs(n_ltp - n_vwap) / n_vwap * 100
        except:
            pass

    for symbol in data.columns.levels[0]:
        try:
            df = data[symbol].dropna(subset=['Close'])
            if len(df) < 2: continue

            ltp    = float(df['Close'].iloc[-1])
            open_p = float(df['Open'].iloc[-1])
            prev_c = float(df['Close'].iloc[-2])
            prev_h = float(df['High'].iloc[-2])
            prev_l = float(df['Low'].iloc[-2])
            low    = float(df['Low'].iloc[-1])
            high   = float(df['High'].iloc[-1])

            day_chg = ((ltp - open_p) / open_p) * 100
            net_chg = ((ltp - prev_c) / prev_c) * 100

            p_pivot    = (prev_h + prev_l + prev_c) / 3
            p_bc       = (prev_h + prev_l) / 2
            p_tc       = (p_pivot - p_bc) + p_pivot
            cpr_width  = abs(p_tc - p_bc) / p_pivot * 100
            is_narrow  = bool(cpr_width <= 0.30)

            high_low        = df['High'] - df['Low']
            high_prev_close = (df['High'] - df['Close'].shift(1)).abs()
            low_prev_close  = (df['Low']  - df['Close'].shift(1)).abs()
            tr  = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
            atr = tr.ewm(span=14, adjust=False).mean().iloc[-1]

            if 'Volume' in df.columns and not df['Volume'].isna().all() and len(df) >= 6:
                avg_vol_5d = df['Volume'].iloc[-6:-1].mean()
                curr_vol   = float(df['Volume'].iloc[-1])
                vol_x = round(curr_vol / ((avg_vol_5d / 375) * minutes), 1) if avg_vol_5d > 0 else 0.0
            else:
                vol_x    = 0.0
                curr_vol = 0.0

            vwap    = (high + low + ltp) / 3
            ema50_d = float(df['Close'].ewm(span=50, adjust=False).mean().iloc[-1]) if len(df) >= 50 else 0.0

            is_swing      = False
            is_w_pullback = False
            latest_w_ema10 = 0
            latest_w_ema50 = 0

            df_w = df.resample('W').agg({'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()

            weekly_net_chg = net_chg
            if len(df_w) >= 2:
                prev_w_c = float(df_w['Close'].iloc[-2])
                if prev_w_c > 0:
                    weekly_net_chg = ((ltp - prev_w_c) / prev_w_c) * 100

            if len(df_w) >= 75:
                df_w['EMA_10'] = df_w['Close'].ewm(span=10, adjust=False).mean()
                df_w['EMA_50'] = df_w['Close'].ewm(span=50, adjust=False).mean()
                latest_w_ema10 = float(df_w['EMA_10'].iloc[-1])
                latest_w_ema50 = float(df_w['EMA_50'].iloc[-1])
                df_w['Trend_Up'] = np.where(df_w['EMA_10'] > df_w['EMA_50'], 1, 0)
                continuous_4w = df_w['Trend_Up'].rolling(window=4).min().iloc[-1] == 1

                w_tr     = pd.concat([df_w['High'] - df_w['Low'], (df_w['High'] - df_w['Close'].shift(1)).abs(), (df_w['Low'] - df_w['Close'].shift(1)).abs()], axis=1).max(axis=1)
                w_atr14  = w_tr.ewm(alpha=1/14, adjust=False).mean()
                w_plus_dm  = df_w['High'].diff()
                w_minus_dm = df_w['Low'].shift(1) - df_w['Low']
                w_plus_dm  = w_plus_dm.where((w_plus_dm > w_minus_dm) & (w_plus_dm > 0), 0.0)
                w_minus_dm = w_minus_dm.where((w_minus_dm > w_plus_dm) & (w_minus_dm > 0), 0.0)
                w_plus_di  = 100 * (w_plus_dm.ewm(alpha=1/14, adjust=False).mean() / w_atr14)
                w_minus_di = 100 * (w_minus_dm.ewm(alpha=1/14, adjust=False).mean() / w_atr14)
                w_dx       = (w_plus_di - w_minus_di).abs() / (w_plus_di + w_minus_di) * 100
                w_adx      = w_dx.ewm(alpha=1/14, adjust=False).mean().iloc[-1]

                recent_w_low = df_w['Low'].iloc[-2:].min()
                touch_ema = recent_w_low <= (latest_w_ema10 * 1.002)
                bounce    = ltp > latest_w_ema10
                catch_early = ltp <= (latest_w_ema10 * 1.02)
                if continuous_4w and touch_ema and bounce and catch_early and (w_adx >= 15):
                    is_w_pullback = True

            if len(df) >= 100:
                ema20_w = latest_w_ema10 if latest_w_ema10 > 0 else 0
                delta   = df['Close'].diff()
                gain    = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
                loss    = -delta.clip(upper=0).ewm(alpha=1/14, adjust=False).mean()
                loss    = loss.replace(0, np.nan)
                rs      = gain / loss
                rsi     = 100 - (100 / (1 + rs))
                current_rsi = rsi.fillna(100).iloc[-1]
                if (ltp > ema50_d) and (ltp > ema20_w) and (current_rsi >= 55) and (net_chg > 0):
                    is_swing = True

            score = 0
            stock_dist        = abs(ltp - vwap) / vwap * 100 if vwap > 0 else 0
            effective_nifty   = max(nifty_dist, 0.25)
            if stock_dist > (effective_nifty * 3): score += 5
            elif stock_dist > (effective_nifty * 2): score += 3
            if abs(open_p - low) <= (ltp * 0.003) or abs(open_p - high) <= (ltp * 0.003): score += 3
            if vol_x > 1.0: score += 3
            if (ltp >= high * 0.998 and day_chg > 0.5) or (ltp <= low * 1.002 and day_chg < -0.5): score += 1
            if (ltp > (low * 1.01) and ltp > vwap) or (ltp < (high * 0.99) and ltp < vwap): score += 1

            is_index    = symbol in INDICES_MAP
            is_sector   = symbol in SECTOR_INDICES_MAP
            is_commodity = symbol in COMMODITY_MAP
            disp_name   = INDICES_MAP.get(symbol, SECTOR_INDICES_MAP.get(symbol, COMMODITY_MAP.get(symbol, symbol.replace(".NS", ""))))

            stock_sector = "OTHER"
            if not is_index and not is_sector and not is_commodity:
                for sec, stocks in NIFTY_50_SECTORS.items():
                    if disp_name in stocks:
                        stock_sector = sec
                        break

            results.append({
                "Fetch_T": symbol, "T": disp_name, "P": ltp, "O": open_p, "H": high, "L": low, "Prev_C": prev_c,
                "Prev_H": prev_h, "Prev_L": prev_l, "W_EMA10": latest_w_ema10, "W_EMA50": latest_w_ema50, "D_EMA50": ema50_d,
                "Day_C": day_chg, "C": net_chg, "W_C": float(weekly_net_chg), "S": score, "VolX": vol_x,
                "Is_Swing": is_swing, "Is_W_Pullback": is_w_pullback, "VWAP": vwap, "ATR": atr,
                "Narrow_CPR": is_narrow, "Is_Index": is_index, "Is_Sector": is_sector,
                "Sector": stock_sector, "Is_Commodity": is_commodity,
                "RSI": float(rsi.fillna(50).iloc[-1]) if len(df) >= 100 else 50.0,
                "Raw_DF_Key": symbol  # for referencing raw data in ML
            })
        except:
            continue

    return pd.DataFrame(results)


def process_5m_data(df_raw):
    try:
        df_s = df_raw.dropna(subset=['Open', 'High', 'Low', 'Close']).copy()
        if df_s.empty: return pd.DataFrame()
        df_s['EMA_10'] = df_s['Close'].ewm(span=10, adjust=False).mean()
        df_s['EMA_20'] = df_s['Close'].ewm(span=20, adjust=False).mean()
        df_s['EMA_50'] = df_s['Close'].ewm(span=50, adjust=False).mean()
        df_s.index     = pd.to_datetime(df_s.index)
        unique_dates   = sorted(list(set(df_s.index.date)))
        target_date    = unique_dates[-1]
        df_day         = df_s[df_s.index.date == target_date].copy()
        if not df_day.empty:
            df_day['Typical_Price'] = (df_day['High'] + df_day['Low'] + df_day['Close']) / 3
            if 'Volume' in df_day.columns and df_day['Volume'].sum() > 0:
                vol_cumsum  = df_day['Volume'].cumsum()
                df_day['VWAP'] = (df_day['Typical_Price'] * df_day['Volume']).cumsum() / vol_cumsum.replace(0, np.nan)
                df_day['VWAP'] = df_day['VWAP'].fillna(df_day['Typical_Price'].expanding().mean())
            else:
                df_day['VWAP'] = df_day['Typical_Price'].expanding().mean()
            df_day = df_day.bfill().ffill()
            return df_day
        return pd.DataFrame()
    except:
        return pd.DataFrame()


def generate_status(row):
    status = ""
    p = row['P']
    if 'AlphaTag' in row and row['AlphaTag']: status += f"{row['AlphaTag']} "
    if abs(row['O'] - row['L']) < (p * 0.002): status += "O=L🔥 "
    if abs(row['O'] - row['H']) < (p * 0.002): status += "O=H🩸 "
    if row['C'] > 0 and row['Day_C'] > 0 and row['VolX'] > 1.5: status += "Rec⇈ "
    if row['VolX'] > 1.5: status += "VOL🟢 "
    return status.strip()


# ============================================================
# 🤖 ML PREDICTION TABLE
# ============================================================
def render_ml_predictions_table(df_subset, raw_data_dict, top_n=15):
    """Render ML predictions for top stocks"""
    if not ML_AVAILABLE:
        return "<div style='padding:15px; color:#ffd700; text-align:center;'>⚠️ scikit-learn not installed. Run: pip install scikit-learn</div>"

    if df_subset.empty:
        return "<div style='padding:15px; color:#888; text-align:center;'>No stocks to predict.</div>"

    html = """
    <table class="term-table">
      <thead>
        <tr><th colspan="8" class="term-head-ml">🤖 AI/ML NEXT-CANDLE PREDICTION ENGINE (RandomForest + GBM Ensemble)</th></tr>
        <tr style="background-color:#21262d;">
          <th style="text-align:left; width:15%;">STOCK</th>
          <th style="width:10%;">LTP</th>
          <th style="width:10%;">RSI</th>
          <th style="width:12%;">DAY%</th>
          <th style="width:20%;">🤖 ML SIGNAL</th>
          <th style="width:12%;">CONFIDENCE</th>
          <th style="width:11%;">MODEL ACC</th>
          <th style="width:10%;">SCORE</th>
        </tr>
      </thead>
      <tbody>
    """

    count = 0
    for _, row in df_subset.head(top_n).iterrows():
        fetch_t = row['Fetch_T']
        sym     = row['T']
        raw_df  = raw_data_dict.get(fetch_t)

        if raw_df is None or len(raw_df) < 200:
            continue

        # Train / retrieve cached model
        models, scaler, acc = train_ml_model(sym, raw_df)
        signal, conf = predict_next_candle(sym, raw_df, models, scaler)

        if "Bullish" in signal:
            sig_class = "ml-bull"
        elif "Bearish" in signal:
            sig_class = "ml-bear"
        else:
            sig_class = "ml-neut"

        conf_bar_width = int(conf)
        conf_bar_color = "#2ea043" if "Bullish" in signal else ("#da3633" if "Bearish" in signal else "#555")
        acc_color  = "#3fb950" if acc >= 55 else "#ffd700" if acc >= 50 else "#f85149"
        day_color  = "text-green" if row['Day_C'] >= 0 else "text-red"
        bg_class   = "row-dark" if count % 2 == 0 else "row-light"
        rsi_val    = row.get('RSI', 50)
        rsi_color  = "#3fb950" if rsi_val >= 60 else ("#f85149" if rsi_val <= 40 else "#ffd700")

        html += f"""
        <tr class="{bg_class}">
          <td class="t-symbol"><a href="https://in.tradingview.com/chart/?symbol=NSE:{sym}" target="_blank">{sym}</a></td>
          <td>₹{row['P']:.2f}</td>
          <td style="color:{rsi_color};">{rsi_val:.0f}</td>
          <td class="{day_color}">{row['Day_C']:+.2f}%</td>
          <td><span class="ml-badge {sig_class}">{signal}</span></td>
          <td>
            <div style="background:#21262d; border-radius:3px; height:8px; width:100%; margin-bottom:2px;">
              <div style="background:{conf_bar_color}; width:{conf_bar_width}%; height:8px; border-radius:3px;"></div>
            </div>
            <span style="font-size:10px;">{conf:.1f}%</span>
          </td>
          <td style="color:{acc_color};">{acc:.1f}%</td>
          <td style="color:#ffd700;">{int(row['S'])}</td>
        </tr>
        """
        count += 1

    html += "</tbody></table>"
    return html


# ============================================================
# ALL ORIGINAL RENDER FUNCTIONS (unchanged)
# ============================================================
def render_html_table(df_subset, title, color_class):
    if df_subset.empty: return ""
    html = f'<table class="term-table"><thead><tr><th colspan="7" class="{color_class}">{title}</th></tr><tr style="background-color: #21262d;"><th style="text-align:left; width:20%;">STOCK</th><th style="width:12%;">PRICE</th><th style="width:12%;">DAY%</th><th style="width:12%;">NET%</th><th style="width:10%;">VOL</th><th style="width:26%;">STATUS</th><th style="width:8%;">SCORE</th></tr></thead><tbody>'
    for i, (_, row) in enumerate(df_subset.iterrows()):
        bg_class  = "row-dark" if i % 2 == 0 else "row-light"
        day_color = "text-green" if row['Day_C'] >= 0 else "text-red"
        net_color = "text-green" if row['C'] >= 0 else "text-red"
        status    = generate_status(row)
        html += f'<tr class="{bg_class}"><td class="t-symbol {net_color}"><a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank">{row["T"]}</a></td><td>{row["P"]:.2f}</td><td class="{day_color}">{row["Day_C"]:.2f}%</td><td class="{net_color}">{row["C"]:.2f}%</td><td>{row["VolX"]:.1f}x</td><td style="font-size:10px;">{status}</td><td style="color:#ffd700;">{int(row["S"])}</td></tr>'
    html += "</tbody></table>"
    return html


def render_portfolio_table(df_port, df_stocks, weekly_trends, port_sort="Default"):
    if df_port.empty: return "<div style='padding:20px; text-align:center; color:#8b949e;'>Portfolio empty.</div>"
    rows_data = []
    total_invested, total_current, total_day_pnl = 0, 0, 0

    for i, (_, row) in enumerate(df_port.iterrows()):
        sym    = str(row['Symbol']).upper().strip()
        try:   qty   = float(row['Quantity'])
        except: qty  = 0
        try:   buy_p = float(row['Buy_Price'])
        except: buy_p = 0

        date_val = str(row.get('Date', '-'))
        if date_val in ['nan', 'NaN', '']: date_val = '-'

        live_row   = df_stocks[df_stocks['T'] == sym]
        trend_html = "➖"

        if not live_row.empty:
            ltp    = float(live_row['P'].iloc[0])
            prev_c = float(live_row['Prev_C'].iloc[0])
            fetch_t = live_row['Fetch_T'].iloc[0]
            trend_state = weekly_trends.get(fetch_t, "Neutral")
            if trend_state == 'Bullish': trend_html = "🟢 Bullish"
            elif trend_state == 'Bearish': trend_html = "🔴 Bearish"
            else: trend_html = "⚪ Neutral"
        else:
            ltp, prev_c = buy_p, buy_p

        invested     = buy_p * qty
        current      = ltp * qty
        overall_pnl  = current - invested
        pnl_pct      = (overall_pnl / invested * 100) if invested > 0 else 0
        day_pnl      = (ltp - prev_c) * qty
        total_invested  += invested
        total_current   += current
        total_day_pnl   += day_pnl
        rows_data.append({'sym': sym, 'date': date_val, 'qty': qty, 'buy_p': buy_p,
            'ltp': ltp, 'trend_html': trend_html, 'invested': invested,
            'overall_pnl': overall_pnl, 'pnl_pct': pnl_pct, 'day_pnl': day_pnl})

    if port_sort == "Day P&L ⬆️": rows_data.sort(key=lambda x: x['day_pnl'], reverse=True)
    elif port_sort == "Day P&L ⬇️": rows_data.sort(key=lambda x: x['day_pnl'])
    elif port_sort == "Total P&L ⬆️": rows_data.sort(key=lambda x: x['overall_pnl'], reverse=True)
    elif port_sort == "Total P&L ⬇️": rows_data.sort(key=lambda x: x['overall_pnl'])
    elif port_sort == "P&L % ⬆️": rows_data.sort(key=lambda x: x['pnl_pct'], reverse=True)
    elif port_sort == "P&L % ⬇️": rows_data.sort(key=lambda x: x['pnl_pct'])

    html = f'<table class="term-table"><thead><tr><th colspan="10" class="term-head-port">💼 LIVE PORTFOLIO TERMINAL</th></tr><tr style="background-color: #21262d;"><th style="text-align:left; width:12%;">STOCK</th><th style="width:10%;">DATE</th><th style="width:6%;">QTY</th><th style="width:9%;">AVG</th><th style="width:9%;">LTP</th><th style="width:11%;">WK TREND</th><th style="width:13%;">INVESTED (₹)</th><th style="width:10%;">DAY P&L</th><th style="width:10%;">TOT P&L</th><th style="width:10%;">P&L %</th></tr></thead><tbody>'
    for i, rd in enumerate(rows_data):
        bg_class   = "row-dark" if i % 2 == 0 else "row-light"
        tpnl_color = "text-green" if rd['overall_pnl'] >= 0 else "text-red"
        dpnl_color = "text-green" if rd['day_pnl'] >= 0 else "text-red"
        t_sign     = "+" if rd['overall_pnl'] > 0 else ""
        d_sign     = "+" if rd['day_pnl'] > 0 else ""
        html += f'<tr class="{bg_class}"><td class="t-symbol {tpnl_color}"><a href="https://in.tradingview.com/chart/?symbol=NSE:{rd["sym"]}" target="_blank">{rd["sym"]}</a></td><td>{rd["date"]}</td><td>{int(rd["qty"])}</td><td>{rd["buy_p"]:.2f}</td><td>{rd["ltp"]:.2f}</td><td style="font-size:10px;">{rd["trend_html"]}</td><td>{rd["invested"]:,.0f}</td><td class="{dpnl_color}">{d_sign}{rd["day_pnl"]:,.0f}</td><td class="{tpnl_color}">{t_sign}{rd["overall_pnl"]:,.0f}</td><td class="{tpnl_color}">{t_sign}{rd["pnl_pct"]:.2f}%</td></tr>'

    overall_total_pnl = total_current - total_invested
    overall_total_pct = (overall_total_pnl / total_invested * 100) if total_invested > 0 else 0
    o_color = "text-green" if overall_total_pnl >= 0 else "text-red"
    o_sign  = "+" if overall_total_pnl > 0 else ""
    d_color = "text-green" if total_day_pnl >= 0 else "text-red"
    d_sign  = "+" if total_day_pnl > 0 else ""
    html += f'<tr class="port-total"><td colspan="7" style="text-align:right; padding-right:15px; font-size:12px;">TOTAL INVESTED: ₹{total_invested:,.0f} &nbsp;|&nbsp; CURRENT: ₹{total_current:,.0f} &nbsp;|&nbsp; OVERALL P&L:</td><td class="{d_color}">{d_sign}₹{total_day_pnl:,.0f}</td><td class="{o_color}">{o_sign}₹{overall_total_pnl:,.0f}</td><td class="{o_color}">{o_sign}{overall_total_pct:.2f}%</td></tr>'
    html += "</tbody></table>"
    return html


def render_swing_terminal_table(df_subset):
    if df_subset.empty: return "<div style='padding:20px; text-align:center; color:#8b949e;'>No Swing setups found.</div>"
    df_sorted = df_subset.reset_index(drop=True)
    html = f'<table class="term-table"><thead><tr><th colspan="10" class="term-head-swing">🌊 SWING TRADING RADAR</th></tr><tr style="background-color: #21262d;"><th style="width:4%;">RANK</th><th style="text-align:left; width:13%;">STOCK</th><th style="width:9%;">LTP</th><th style="width:9%;">DAY%</th><th style="width:8%;">VOL</th><th style="width:17%;">STATUS</th><th style="width:11%; color:#f85149;">🛑 SL</th><th style="width:11%; color:#3fb950;">🎯 T1</th><th style="width:11%; color:#3fb950;">🎯 T2</th><th style="width:7%;">SCORE</th></tr></thead><tbody>'
    for i, row in df_sorted.iterrows():
        bg_class  = "row-dark" if i % 2 == 0 else "row-light"
        day_color = "text-green" if row['Day_C'] >= 0 else "text-red"
        status    = generate_status(row)
        atr_val   = row.get("ATR", row["P"] * 0.02)
        sl_val    = row["P"] - 1.5 * atr_val
        t1_val    = row["P"] + 1.5 * atr_val
        t2_val    = row["P"] + 3.0 * atr_val
        rank_badge = f"🏆 1" if i == 0 else f"{i+1}"
        html += f'<tr class="{bg_class}"><td><b>{rank_badge}</b></td><td class="t-symbol"><a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank">{row["T"]}</a></td><td>{row["P"]:.2f}</td><td class="{day_color}">{row["Day_C"]:.2f}%</td><td>{row["VolX"]:.1f}x</td><td style="font-size:10px;">{status}</td><td style="color:#f85149; font-weight:bold;">{sl_val:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t1_val:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t2_val:.2f}</td><td style="color:#ffd700;">{int(row["S"])}</td></tr>'
    html += "</tbody></table>"
    return html


def render_highscore_terminal_table(df_subset):
    if df_subset.empty: return "<div style='padding:20px; text-align:center; color:#8b949e;'>No High Score stocks.</div>"
    df_sorted = df_subset.reset_index(drop=True)
    html = f'<table class="term-table"><thead><tr><th colspan="10" class="term-head-high">🔥 HIGH SCORE RADAR</th></tr><tr style="background-color: #21262d;"><th style="width:4%;">RANK</th><th style="text-align:left; width:13%;">STOCK</th><th style="width:9%;">LTP</th><th style="width:9%;">DAY%</th><th style="width:8%;">VOL</th><th style="width:17%;">STATUS</th><th style="width:11%; color:#f85149;">🛑 SL</th><th style="width:11%; color:#3fb950;">🎯 T1</th><th style="width:11%; color:#3fb950;">🎯 T2</th><th style="width:7%;">SCORE</th></tr></thead><tbody>'
    for i, row in df_sorted.iterrows():
        bg_class  = "row-dark" if i % 2 == 0 else "row-light"
        day_color = "text-green" if row['Day_C'] >= 0 else "text-red"
        custom_status = str(row.get('Strategy_Icon', '')) or generate_status(row)
        is_down   = row['C'] < 0
        atr_val   = row.get("ATR", row["P"] * 0.02)
        sl_val    = row["P"] + 1.5 * atr_val if is_down else row["P"] - 1.5 * atr_val
        t1_val    = row["P"] - 1.5 * atr_val if is_down else row["P"] + 1.5 * atr_val
        t2_val    = row["P"] - 3.0 * atr_val if is_down else row["P"] + 3.0 * atr_val
        rank_badge = f"🏆 1" if i == 0 else f"{i+1}"
        html += f'<tr class="{bg_class}"><td><b>{rank_badge}</b></td><td class="t-symbol"><a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank">{row["T"]}</a></td><td>{row["P"]:.2f}</td><td class="{day_color}">{row["Day_C"]:.2f}%</td><td>{row["VolX"]:.1f}x</td><td style="font-size:10px;">{custom_status}</td><td style="color:#f85149; font-weight:bold;">{sl_val:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t1_val:.2f}</td><td style="color:#3fb950; font-weight:bold;">{t2_val:.2f}</td><td style="color:#ffd700;">{int(row["S"])}</td></tr>'
    html += "</tbody></table>"
    return html


def render_chart(row, df_chart, show_pin=True, key_suffix="", timeframe="Day", show_crosshair=False, show_vol=False, ml_signal=None):
    display_sym = row['T']
    fetch_sym   = row['Fetch_T']
    pct_val     = float(row.get('W_C', row['C'])) if timeframe == "Weekly Chart" else float(row['C'])
    color_hex   = "#da3633" if pct_val < 0 else "#2ea043"
    sign        = "+" if pct_val > 0 else ""
    tv_link     = f"https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(fetch_sym, 'NSE:' + display_sym)}"

    ml_html = ""
    if ml_signal:
        sig, conf = ml_signal
        if "Bullish" in sig: ml_html = f"<span class='ml-badge ml-bull'>{sig} {conf:.0f}%</span>"
        elif "Bearish" in sig: ml_html = f"<span class='ml-badge ml-bear'>{sig} {conf:.0f}%</span>"
        else: ml_html = f"<span class='ml-badge ml-neut'>{sig}</span>"

    if show_pin and display_sym not in ["NIFTY", "BANKNIFTY", "INDIA VIX", "DOW", "NSDQ"] and not row.get('Is_Commodity'):
        cb_key = f"cb_{fetch_sym}_{key_suffix}" if key_suffix else f"cb_{fetch_sym}"
        st.checkbox("pin", value=(fetch_sym in st.session_state.pinned_stocks), key=cb_key, on_change=toggle_pin, args=(fetch_sym,), label_visibility="collapsed")

    st.markdown(f"""
        <div style='text-align:left; font-size:14px; font-weight:bold; margin-top:3px; margin-bottom:5px; padding-left:30px;'>
            <a href='{tv_link}' target='_blank' style='color:#ffffff; text-decoration:none;'>
                {display_sym} &nbsp;&nbsp; <span style='color:#ffffff;'>₹{row['P']:.2f}</span> &nbsp;&nbsp; <span style='color:{color_hex}; font-size:12px;'>({sign}{pct_val:.2f}%)</span>
            </a> {ml_html}
        </div>
    """, unsafe_allow_html=True)

    try:
        if not df_chart.empty:
            min_val   = df_chart['Low'].min()
            max_val   = df_chart['High'].max()
            y_padding = (max_val - min_val) * 0.1 if (max_val - min_val) != 0 else min_val * 0.005

            if show_vol:
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.02, row_heights=[0.75, 0.25])
                fig.add_trace(go.Candlestick(x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'], increasing_line_color='#2ea043', decreasing_line_color='#da3633', showlegend=False, hoverinfo='skip', name=""), row=1, col=1)
                hover_data = "H: ₹" + df_chart['High'].round(2).astype(str) + "<br>L: ₹" + df_chart['Low'].round(2).astype(str)
                fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['High'], mode='lines', line=dict(color='rgba(0,0,0,0)'), showlegend=False, hoverinfo='text' if show_crosshair else 'skip', text=hover_data, hovertemplate="%{text}<extra></extra>" if show_crosshair else None, name=""), row=1, col=1)
                if timeframe == "Weekly Chart":
                    if 'EMA_10' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA_10'], mode='lines', line=dict(color='#FFD700', width=1.5), showlegend=False, hoverinfo='skip'), row=1, col=1)
                    if 'EMA_50' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA_50'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), showlegend=False, hoverinfo='skip'), row=1, col=1)
                else:
                    if 'VWAP' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['VWAP'], mode='lines', line=dict(color='#FFD700', width=1.5, dash='dot'), showlegend=False, hoverinfo='skip'), row=1, col=1)
                    if 'EMA_10' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA_10'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), showlegend=False, hoverinfo='skip'), row=1, col=1)
                colors = ['#2ea043' if c >= o else '#da3633' for c, o in zip(df_chart['Close'], df_chart['Open'])]
                fig.add_trace(go.Bar(x=df_chart.index, y=df_chart['Volume'], marker_color=colors, showlegend=False, hoverinfo='skip'), row=2, col=1)
                fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=230, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', xaxis_rangeslider_visible=False)
                fig.update_yaxes(showgrid=False, zeroline=False, showticklabels=True, side='right', tickfont=dict(color="#ffffff", size=10), showline=False, fixedrange=True, range=[min_val - y_padding, max_val + y_padding], row=1, col=1)
                fig.update_xaxes(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True, row=1, col=1)
                fig.update_yaxes(visible=False, fixedrange=True, row=2, col=1)
                fig.update_xaxes(visible=False, fixedrange=True, row=2, col=1)
            else:
                fig = go.Figure()
                fig.add_trace(go.Candlestick(x=df_chart.index, open=df_chart['Open'], high=df_chart['High'], low=df_chart['Low'], close=df_chart['Close'], increasing_line_color='#2ea043', decreasing_line_color='#da3633', showlegend=False, hoverinfo='skip', name=""))
                if timeframe == "Weekly Chart":
                    if 'EMA_10' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA_10'], mode='lines', line=dict(color='#FFD700', width=1.5), hoverinfo='skip'))
                    if 'EMA_50' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA_50'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), hoverinfo='skip'))
                else:
                    if 'VWAP' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['VWAP'], mode='lines', line=dict(color='#FFD700', width=1.5, dash='dot'), hoverinfo='skip'))
                    if 'EMA_10' in df_chart.columns: fig.add_trace(go.Scatter(x=df_chart.index, y=df_chart['EMA_10'], mode='lines', line=dict(color='#00BFFF', width=1.5, dash='dash'), hoverinfo='skip'))
                fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=190, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', showlegend=False, xaxis_rangeslider_visible=False)
                if show_crosshair:
                    fig.update_layout(hovermode='x', dragmode=False, hoverlabel=dict(bgcolor="#161b22", font_size=12, font_color="#ffffff"))
                    fig.update_yaxes(showspikes=True, spikesnap='cursor', spikemode='across', spikethickness=0.2, spikecolor="rgba(255,255,255,0.4)", showgrid=False, zeroline=False, showticklabels=True, side='right', tickfont=dict(color="#ffffff", size=10), showline=False, fixedrange=True, range=[min_val - y_padding, max_val + y_padding])
                    fig.update_xaxes(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True)
                else:
                    fig.update_layout(hovermode=False, dragmode=False)
                    fig.update_yaxes(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True, range=[min_val - y_padding, max_val + y_padding])
                    fig.update_xaxes(showgrid=False, zeroline=False, showticklabels=False, showline=False, fixedrange=True)

            st.plotly_chart(fig, use_container_width=True, key=f"plot_{fetch_sym}_{key_suffix}_{timeframe}_{show_vol}_{show_crosshair}")
        else:
            st.markdown("<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888;'>Data N/A</div>", unsafe_allow_html=True)
    except:
        st.markdown("<div style='height:150px; display:flex; align-items:center; justify-content:center; color:#888;'>Chart error</div>", unsafe_allow_html=True)


def render_chart_grid(df_grid, show_pin_option, key_prefix, timeframe="Day", chart_dict=None, show_crosshair=False, show_vol=False, ml_signals=None):
    if df_grid.empty: return
    if chart_dict  is None: chart_dict  = {}
    if ml_signals  is None: ml_signals  = {}
    with st.container():
        st.markdown("<div class='fluid-board'></div>", unsafe_allow_html=True)
        for j, (_, row) in enumerate(df_grid.iterrows()):
            with st.container():
                ml_sig = ml_signals.get(row['Fetch_T'])
                render_chart(row, chart_dict.get(row['Fetch_T'], pd.DataFrame()), show_pin=show_pin_option,
                             key_suffix=f"{key_prefix}_{j}", timeframe=timeframe, show_crosshair=show_crosshair,
                             show_vol=show_vol, ml_signal=ml_sig)


def render_closed_trades_table(df_closed):
    if df_closed.empty: return "<div style='padding:20px; text-align:center; color:#8b949e;'>No closed trades yet.</div>"
    html = f'<table class="term-table"><thead><tr><th colspan="7" style="background-color:#4a148c; color:white; text-align:left; padding-left:10px;">📜 CLOSED TRADES</th></tr><tr style="background-color: #21262d;"><th style="width:15%; text-align:left;">DATE</th><th style="width:15%; text-align:left;">STOCK</th><th style="width:10%;">QTY</th><th style="width:15%;">BUY</th><th style="width:15%;">SELL</th><th style="width:15%;">P&L (₹)</th><th style="width:15%;">P&L %</th></tr></thead><tbody>'
    total_pnl = 0
    for i, (_, row) in enumerate(df_closed.iterrows()):
        bg_class = "row-dark" if i % 2 == 0 else "row-light"
        pnl_rs   = float(row['PnL_Rs'])
        pnl_pct  = float(row['PnL_Pct'])
        total_pnl += pnl_rs
        p_color  = "text-green" if pnl_rs >= 0 else "text-red"
        p_sign   = "+" if pnl_rs > 0 else ""
        html += f'<tr class="{bg_class}"><td style="text-align:left;">{row["Sell_Date"]}</td><td class="t-symbol {p_color}" style="text-align:left;">{row["Symbol"]}</td><td>{int(row["Quantity"])}</td><td>{float(row["Buy_Price"]):.2f}</td><td>{float(row["Sell_Price"]):.2f}</td><td class="{p_color}">{p_sign}{pnl_rs:,.2f}</td><td class="{p_color}">{p_sign}{pnl_pct:.2f}%</td></tr>'
    tot_color = "text-green" if total_pnl >= 0 else "text-red"
    tot_sign  = "+" if total_pnl > 0 else ""
    html += f'<tr class="port-total"><td colspan="5" style="text-align:right; padding-right:15px;">NET REALIZED P&L:</td><td colspan="2" class="{tot_color}" style="font-size:14px; text-align:center;">{tot_sign}₹{total_pnl:,.2f}</td></tr>'
    html += "</tbody></table>"
    return html


# ============================================================
# --- 6. TOP NAVIGATION ---
# ============================================================
c1, c2, c3 = st.columns([0.4, 0.3, 0.3])
with c1:
    watchlist_mode = st.selectbox("Watchlist", [
        "High Score Stocks 🔥", "Swing Trading 📈", "Nifty 50 Heatmap",
        "Day Trading Stocks 🚀", "Terminal Tables 🗃️", "My Portfolio 💼",
        "Commodity 🛢️", "Fundamentals 🏢",
        "🤖 AI Predictions",     # NEW
        "📈 Backtesting Lab"      # NEW
    ], index=3, label_visibility="collapsed")
with c2:
    sort_mode = st.selectbox("Sort By", ["Custom Sort", "Heatmap Marks Up ⭐", "Heatmap Marks Down ⬇️", "% Change Up 🟢", "% Change Down 🔴"], label_visibility="collapsed")
with c3:
    view_mode = st.radio("Display", ["Heat Map", "Chart 📈"], horizontal=True, label_visibility="collapsed")

chart_timeframe = "Day Chart"
show_crosshair  = False
show_vol        = False

if view_mode == "Chart 📈" or watchlist_mode in ["Swing Trading 📈", "My Portfolio 💼", "Commodity 🛢️"]:
    c_opt1, c_opt2, c_opt3 = st.columns(3)
    with c_opt1:
        if watchlist_mode in ["Swing Trading 📈", "My Portfolio 💼", "Commodity 🛢️"]:
            chart_timeframe = st.radio("⏳ Timeframe:", ["Day Chart", "Weekly Chart"], horizontal=True, label_visibility="collapsed")
    with c_opt2:
        if view_mode == "Chart 📈" or watchlist_mode == "Commodity 🛢️": show_crosshair = st.toggle("⌖ Show Crosshair Price")
    with c_opt3:
        if view_mode == "Chart 📈" or watchlist_mode == "Commodity 🛢️": show_vol = st.toggle("📊 Show Volume Bars")

# ============================================================
# --- 7. MAIN DATA LOAD ---
# ============================================================
df = fetch_all_data()

if not df.empty:
    all_names   = sorted(df[(~df['Is_Sector']) & (~df['Is_Index']) & (~df['Is_Commodity'])]['T'].unique().tolist())
    df_indices  = df[df['Is_Index']].copy()
    df_indices['Order'] = df_indices['T'].map({"NIFTY": 1, "BANKNIFTY": 2, "INDIA VIX": 3, "DOW": 4, "NSDQ": 5})
    df_indices  = df_indices.sort_values('Order')
    df_sectors  = df[df['Is_Sector']].copy().sort_values(by="Day_C", ascending=False)
    df_stocks   = df[(~df['Is_Index']) & (~df['Is_Sector']) & (~df['Is_Commodity'])].copy()
    df_commodities = df[df['Is_Commodity']].copy()

    c_search, c_type, _ = st.columns([0.4, 0.3, 0.3])
    with c_search:
        search_stock = st.selectbox("🔍 Search & View Chart", ["-- None --"] + all_names)

    move_type_filter = "All Moves"
    with c_type:
        if watchlist_mode == "Day Trading Stocks 🚀":
            move_type_filter = st.selectbox("🎯 Strategy Filter", [
                "All Moves", "⚡ Intraday Pro Breakout (Top 5)", "🌊 One Sided Only",
                "🔄 VWAP Reversal", "🎯 Reversals Only", "🏹 Rubber Band Stretch",
                "🏄‍♂️ Momentum Ignition", "💥 Narrow CPR Breakout"
            ], index=0)
        elif watchlist_mode == "Swing Trading 📈":
            move_type_filter = st.selectbox("📈 Strategy Filter", ["All Swing Stocks", "🚀 Pro Breakout Strategy", "🌟 Weekly 10EMA Pro"], index=0)

    df_nifty       = df_stocks[df_stocks['T'].isin(NIFTY_50)].copy()
    sector_perf    = df_nifty.groupby('Sector')['C'].mean().sort_values(ascending=False)
    valid_sectors  = [s for s in sector_perf.index if s != "OTHER"]
    top_buy_sector  = valid_sectors[0]  if valid_sectors else "PHARMA"
    top_sell_sector = valid_sectors[-1] if valid_sectors else "IT"

    df_buy_sector  = df_nifty[df_nifty['Sector'] == top_buy_sector].sort_values(by=['S', 'C'], ascending=[False, False])
    df_sell_sector = df_nifty[df_nifty['Sector'] == top_sell_sector].sort_values(by=['S', 'C'], ascending=[False, True])
    df_independent = df_nifty[(~df_nifty['Sector'].isin([top_buy_sector, top_sell_sector])) & (df_nifty['S'] >= 5)].sort_values(by='S', ascending=False).head(8)
    df_broader     = df_stocks[(df_stocks['T'].isin(FNO_STOCKS)) & (~df_stocks['T'].isin(NIFTY_50)) & (df_stocks['S'] >= 5)].sort_values(by='S', ascending=False).head(8)

    df_port_saved  = load_portfolio()

    # Filter logic
    if watchlist_mode == "Terminal Tables 🗃️":
        terminal_tickers = pd.concat([df_buy_sector, df_sell_sector, df_independent, df_broader])['Fetch_T'].unique().tolist()
        df_filtered = df_stocks[df_stocks['Fetch_T'].isin(terminal_tickers)]
    elif watchlist_mode == "My Portfolio 💼":
        port_tickers = [f"{str(sym).upper().strip()}.NS" for sym in df_port_saved['Symbol'].tolist() if str(sym).strip() != ""]
        df_filtered  = df_stocks[df_stocks['Fetch_T'].isin(port_tickers)]
    elif watchlist_mode == "Commodity 🛢️":
        df_filtered  = df_commodities.copy()
    elif watchlist_mode in ["Fundamentals 🏢", "🤖 AI Predictions"]:
        df_filtered  = df_stocks[df_stocks['T'].isin(NIFTY_50)].copy()
    elif watchlist_mode == "📈 Backtesting Lab":
        df_filtered  = df_stocks.copy()
    elif watchlist_mode == "Nifty 50 Heatmap":
        df_filtered  = df_stocks[df_stocks['T'].isin(NIFTY_50)]
    elif watchlist_mode == "Day Trading Stocks 🚀":
        df_filtered  = df_stocks[df_stocks['C'].abs() >= 1.0].copy()
    elif watchlist_mode == "Swing Trading 📈":
        df_filtered  = df_stocks[(df_stocks['Is_Swing'] == True) | (df_stocks['Is_W_Pullback'] == True)]
    else:
        df_filtered  = df_stocks[(df_stocks['S'] >= 11) & (df_stocks['VolX'] >= 1.5)]

    all_display_tickers = list(set(df_indices['Fetch_T'].tolist() + df_filtered['Fetch_T'].tolist() + st.session_state.pinned_stocks))
    if search_stock != "-- None --":
        search_fetch_t = df[df['T'] == search_stock]['Fetch_T'].iloc[0]
        if search_fetch_t not in all_display_tickers: all_display_tickers.append(search_fetch_t)

    with st.spinner("⚡ Fetching Live Market Data..."):
        five_min_data = yf.download(all_display_tickers, period="5d", interval="5m", progress=False, group_by='ticker', threads=True, auto_adjust=True)

    processed_charts = {}
    weekly_trends    = {}
    alpha_tags       = {}
    trend_scores     = {}
    ml_signals_dict  = {}
    raw_daily_data   = {}  # ⚡ store raw daily for ML

    nifty_dist_5m = 0.1
    if "^NSEI" in five_min_data.columns.levels[0]:
        n_raw = five_min_data["^NSEI"] if isinstance(five_min_data.columns, pd.MultiIndex) else five_min_data
        n_day = process_5m_data(n_raw)
        if not n_day.empty:
            n_ltp  = n_day['Close'].iloc[-1]
            n_vwap = n_day['VWAP'].iloc[-1]
            if n_vwap > 0: nifty_dist_5m = abs(n_ltp - n_vwap) / n_vwap * 100

    for sym in all_display_tickers:
        try:
            df_raw = five_min_data[sym] if isinstance(five_min_data.columns, pd.MultiIndex) else five_min_data
        except KeyError:
            df_raw = pd.DataFrame()

        df_day = process_5m_data(df_raw)
        processed_charts[sym] = df_day

        try:
            sym_row    = df[df['Fetch_T'] == sym].iloc[0]
            w_ema10    = float(sym_row['W_EMA10'])
            w_ema50    = float(sym_row['W_EMA50'])
            last_p     = float(sym_row['P'])
            if last_p > w_ema10 and w_ema10 >= w_ema50: weekly_trends[sym] = 'Bullish'
            elif last_p < w_ema10 and w_ema10 <= w_ema50: weekly_trends[sym] = 'Bearish'
            else: weekly_trends[sym] = 'Neutral'
        except:
            weekly_trends[sym] = 'Neutral'

        if sym in df_filtered['Fetch_T'].tolist() and not df_day.empty:
            last_price  = df_day['Close'].iloc[-1]
            last_vwap   = df_day['VWAP'].iloc[-1]
            net_chg     = df[df['Fetch_T'] == sym]['C'].iloc[0]
            alpha_tag   = ""
            if len(df_day) >= 50:
                stock_dist_5m    = abs(last_price - last_vwap) / last_vwap * 100 if last_vwap > 0 else 0
                effective_nifty_5m = max(nifty_dist_5m, 0.25)
                if stock_dist_5m > (effective_nifty_5m * 3): alpha_tag = "🚀Alpha-Mover"
                elif stock_dist_5m > (effective_nifty_5m * 2): alpha_tag = "💪Nifty-Beater"

            one_sided_tag = ""
            trend_bonus   = 0
            if len(df_day) >= 12 and last_vwap > 0:
                trend_candles = (df_day['Low'] >= df_day['VWAP']).sum() if net_chg > 0 else (df_day['High'] <= df_day['VWAP']).sum()
                total_candles = len(df_day)
                if (trend_candles / total_candles) >= 0.85:
                    current_gap_pct = abs(last_price - last_vwap) / last_vwap * 100
                    if current_gap_pct >= 1.50: one_sided_tag = "🌊Mega-1.5%"; trend_bonus = 7
                    elif current_gap_pct >= 1.00: one_sided_tag = "🌊Super-1.0%"; trend_bonus = 5
                    elif current_gap_pct >= 0.50: one_sided_tag = "🌊Trend-0.5%"; trend_bonus = 3
                    else: one_sided_tag = "🌊Trend"; trend_bonus = 1

            trap_tag  = ""
            trap_bonus = 0
            if len(df_day) >= 6 and last_vwap > 0:
                curr_open  = float(df_day['Open'].iloc[-1])
                day_open   = df[df['Fetch_T'] == sym]['O'].iloc[0]
                day_high   = df[df['Fetch_T'] == sym]['H'].iloc[0]
                day_low    = df[df['Fetch_T'] == sym]['L'].iloc[0]
                morning_spike = (day_high - day_open) / day_open * 100 if day_open > 0 else 0
                morning_drop  = (day_open - day_low)  / day_open * 100 if day_open > 0 else 0
                if morning_spike >= 1.0 and last_price < last_vwap and last_price < curr_open:
                    trap_tag = "🎯 Reversal Sell 🩸"; trap_bonus = 6
                elif morning_drop >= 1.0 and last_price > last_vwap and last_price > curr_open:
                    trap_tag = "🎯 Reversal Buy 🚀"; trap_bonus = 6

            alpha_tags[sym]  = f"{alpha_tag} {one_sided_tag} {trap_tag}".strip()
            trend_scores[sym] = trend_bonus + trap_bonus

    if not df_filtered.empty:
        df_filtered = df_filtered.copy()
        df_filtered['AlphaTag']    = df_filtered['Fetch_T'].map(alpha_tags).fillna("")
        df_filtered['Trend_Score'] = df_filtered['Fetch_T'].map(trend_scores).fillna(0)
        df_filtered['S']           = df_filtered['S'] + df_filtered['Trend_Score']

        # Day Trading strategy filters (same as original)
        if watchlist_mode == "Day Trading Stocks 🚀":
            base_buy  = (df_filtered['P'] > df_filtered['W_EMA10']) & (df_filtered['P'] > df_filtered['W_EMA50']) & (df_filtered['P'] > df_filtered['VWAP'])
            base_sell = (df_filtered['P'] < df_filtered['W_EMA10']) & (df_filtered['P'] < df_filtered['W_EMA50']) & (df_filtered['P'] < df_filtered['VWAP'])
            nifty_dist = 0.25
            nifty_row  = df_indices[df_indices['T'] == 'NIFTY']
            if not nifty_row.empty:
                n_h, n_l, n_p = float(nifty_row['H'].iloc[0]), float(nifty_row['L'].iloc[0]), float(nifty_row['P'].iloc[0])
                n_vwap     = (n_h + n_l + n_p) / 3
                nifty_dist = min(max(abs(n_p - n_vwap) / n_vwap * 100, 0.25), 0.75)
            s_vwap         = (df_filtered['H'] + df_filtered['L'] + df_filtered['P']) / 3
            stock_vwap_dist = (df_filtered['P'] - s_vwap).abs() / s_vwap * 100
            open_drive_bull = (df_filtered['O'] - df_filtered['L'] <= df_filtered['P'] * 0.003)
            open_drive_bear = (df_filtered['H'] - df_filtered['O'] <= df_filtered['P'] * 0.003)

            strategies_list = ["⚡ Intraday Pro Breakout (Top 5)", "🌊 One Sided Only", "🔄 VWAP Reversal",
                               "🎯 Reversals Only", "🏹 Rubber Band Stretch", "🏄‍♂️ Momentum Ignition", "💥 Narrow CPR Breakout"]
            strats_to_run = strategies_list if move_type_filter == "All Moves" else [move_type_filter]
            all_dfs = []
            for strat in strats_to_run:
                c_buy = pd.Series(False, index=df_filtered.index)
                c_sell = pd.Series(False, index=df_filtered.index)
                icon_str = ""
                if strat == "⚡ Intraday Pro Breakout (Top 5)":
                    c_buy  = base_buy & (df_filtered['P'] > df_filtered['O']) & ((df_filtered['H'] - df_filtered['P']) <= (df_filtered['H'] - df_filtered['L']) * 0.30)
                    c_sell = base_sell & (df_filtered['P'] < df_filtered['O']) & ((df_filtered['P'] - df_filtered['L']) <= (df_filtered['H'] - df_filtered['L']) * 0.30)
                    icon_str = "⚡"
                elif strat == "🌊 One Sided Only":
                    c_buy  = base_buy & (~df_filtered['AlphaTag'].str.contains("Reversal", na=False)) & (df_filtered['Day_C'] >= 1.5) & (stock_vwap_dist >= (nifty_dist * 1.5)) & (df_filtered['Trend_Score'] >= 3) & open_drive_bull
                    c_sell = base_sell & (~df_filtered['AlphaTag'].str.contains("Reversal", na=False)) & (df_filtered['Day_C'] <= -1.5) & (stock_vwap_dist >= (nifty_dist * 1.5)) & (df_filtered['Trend_Score'] >= 3) & open_drive_bear
                    icon_str = "🌊"
                elif strat == "🔄 VWAP Reversal":
                    c_buy  = base_buy & (df_filtered['AlphaTag'].str.contains("Reversal Buy", na=False)) & (df_filtered['Day_C'] >= 1.5) & (stock_vwap_dist >= (nifty_dist * 1.5))
                    c_sell = base_sell & (df_filtered['AlphaTag'].str.contains("Reversal Sell", na=False)) & (df_filtered['Day_C'] <= -1.5) & (stock_vwap_dist >= (nifty_dist * 1.5))
                    icon_str = "🔄"
                elif strat == "🎯 Reversals Only":
                    c_buy  = base_buy & (df_filtered['AlphaTag'].str.contains("Reversal Buy", na=False)) & (df_filtered['Day_C'] >= 1.0)
                    c_sell = base_sell & (df_filtered['AlphaTag'].str.contains("Reversal Sell", na=False)) & (df_filtered['Day_C'] <= -1.0)
                    icon_str = "🎯"
                elif strat == "🏹 Rubber Band Stretch":
                    c_buy  = base_buy & (~df_filtered['AlphaTag'].str.contains("Reversal", na=False)) & (df_filtered['Day_C'] >= 2.5)
                    c_sell = base_sell & (~df_filtered['AlphaTag'].str.contains("Reversal", na=False)) & (df_filtered['Day_C'] <= -2.5)
                    icon_str = "🏹"
                elif strat == "🏄‍♂️ Momentum Ignition":
                    c_buy  = base_buy & (~df_filtered['AlphaTag'].str.contains("Reversal", na=False)) & (df_filtered['P'] > df_filtered['O']) & (df_filtered['Day_C'] >= 2.0) & ((df_filtered['H'] - df_filtered['P']) <= (df_filtered['H'] - df_filtered['L']) * 0.15)
                    c_sell = base_sell & (~df_filtered['AlphaTag'].str.contains("Reversal", na=False)) & (df_filtered['P'] < df_filtered['O']) & (df_filtered['Day_C'] <= -2.0) & ((df_filtered['P'] - df_filtered['L']) <= (df_filtered['H'] - df_filtered['L']) * 0.15)
                    icon_str = "🏄‍♂️"
                elif strat == "💥 Narrow CPR Breakout":
                    c_buy  = base_buy & (df_filtered['Narrow_CPR'] == True) & (~df_filtered['AlphaTag'].str.contains("Reversal", na=False)) & (df_filtered['Day_C'] >= 1.0)
                    c_sell = base_sell & (df_filtered['Narrow_CPR'] == True) & (~df_filtered['AlphaTag'].str.contains("Reversal", na=False)) & (df_filtered['Day_C'] <= -1.0)
                    icon_str = "💥"
                top_buy_d  = df_filtered[c_buy].sort_values(by=['VolX', 'Day_C'], ascending=[False, False]).head(5).copy()
                top_sell_d = df_filtered[c_sell].sort_values(by=['VolX', 'Day_C'], ascending=[False, True]).head(5).copy()
                if not top_buy_d.empty:  top_buy_d['Strategy_Icon']  = f"{icon_str} BUY"
                if not top_sell_d.empty: top_sell_d['Strategy_Icon'] = f"{icon_str} SELL"
                all_dfs += [top_buy_d, top_sell_d]
            df_filtered = pd.concat(all_dfs).drop_duplicates(subset=['Fetch_T']) if all_dfs else pd.DataFrame(columns=df_filtered.columns)
            if not df_filtered.empty:
                df_filtered['T1'] = np.where(df_filtered['Strategy_Icon'].str.contains('BUY', na=False), round(df_filtered['P'] * 1.008, 2), round(df_filtered['P'] * 0.992, 2))
                df_filtered['T2'] = np.where(df_filtered['Strategy_Icon'].str.contains('BUY', na=False), round(df_filtered['P'] * 1.015, 2), round(df_filtered['P'] * 0.985, 2))
                df_filtered['SL'] = np.where(df_filtered['Strategy_Icon'].str.contains('BUY', na=False), round(df_filtered['P'] * 0.992, 2), round(df_filtered['P'] * 1.008, 2))

        elif watchlist_mode == "Swing Trading 📈":
            if move_type_filter == "🚀 Pro Breakout Strategy":
                top_body  = df_filtered['H'] - df_filtered['P']
                total_rng = df_filtered['H'] - df_filtered['L']
                df_filtered = df_filtered[(df_filtered['P'] > df_filtered['O']) & (top_body <= (total_rng * 0.25)) & (df_filtered['VolX'] >= 1.5) & (df_filtered['Day_C'] >= 2.0) & (df_filtered['Is_Swing'] == True)]
            elif move_type_filter == "🌟 Weekly 10EMA Pro":
                df_filtered = df_filtered[df_filtered['Is_W_Pullback'] == True]

    # Sort
    sort_key = "W_C" if chart_timeframe == "Weekly Chart" else "C"
    if sort_mode == "% Change Up 🟢":      df_stocks_display = df_filtered.sort_values(by=sort_key, ascending=False)
    elif sort_mode == "% Change Down 🔴":  df_stocks_display = df_filtered.sort_values(by=sort_key, ascending=True)
    elif sort_mode == "Heatmap Marks Up ⭐":
        df_stocks_display = pd.concat([
            df_filtered[df_filtered[sort_key] >= 0].sort_values(by=['S', 'VolX', sort_key], ascending=[False, False, False]),
            df_filtered[df_filtered[sort_key] < 0].sort_values(by=['S', 'VolX', sort_key], ascending=[False, False, True])
        ])
    elif sort_mode == "Heatmap Marks Down ⬇️":
        df_stocks_display = pd.concat([
            df_filtered[df_filtered[sort_key] < 0].sort_values(by=['S', 'VolX', sort_key], ascending=[False, False, True]),
            df_filtered[df_filtered[sort_key] >= 0].sort_values(by=['S', 'VolX', sort_key], ascending=[False, False, False])
        ])
    else:
        df_stocks_display = df_filtered.sort_values(by=['S', 'VolX', sort_key], ascending=[False, False, False])

    # ============================================================
    # 🤖 AI PREDICTIONS TAB
    # ============================================================
    if watchlist_mode == "🤖 AI Predictions":
        st.markdown("<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#58a6ff;'>🤖 AI/ML Next-Candle Prediction Engine</div>", unsafe_allow_html=True)

        if not ML_AVAILABLE:
            st.error("scikit-learn not installed! Run: `pip install scikit-learn` and restart.")
        else:
            ml_col1, ml_col2, ml_col3 = st.columns(3)
            with ml_col1: top_n_ml = st.slider("Top N Stocks", 5, 30, 15)
            with ml_col2: min_acc  = st.slider("Min Model Accuracy (%)", 50, 70, 52)
            with ml_col3: st.markdown("<div style='padding-top:28px; color:#888; font-size:12px;'>⚠️ Past accuracy ≠ future performance</div>", unsafe_allow_html=True)

            st.markdown("---")

            # ⚡ Fetch raw daily data for ML in parallel
            ml_symbols = df_stocks_display.head(top_n_ml)['Fetch_T'].tolist()
            with st.spinner(f"🤖 Training ML models for {len(ml_symbols)} stocks..."):
                raw_data_batch = fetch_batch_parallel(ml_symbols, period="2y")

            # Build ML signals
            ml_predictions = {}
            for sym in ml_symbols:
                raw_df = raw_data_batch.get(sym)
                if raw_df is not None and len(raw_df) >= 200:
                    models, scaler, acc = train_ml_model(sym.replace('.NS', ''), raw_df)
                    if acc >= min_acc:
                        signal, conf = predict_next_candle(sym, raw_df, models, scaler)
                        ml_predictions[sym] = {'signal': signal, 'conf': conf, 'acc': acc}

            # Summary metrics
            bullish_count = sum(1 for v in ml_predictions.values() if "Bullish" in v['signal'])
            bearish_count = sum(1 for v in ml_predictions.values() if "Bearish" in v['signal'])
            total_pred    = len(ml_predictions)

            m1, m2, m3, m4 = st.columns(4)
            m1.markdown(f"<div class='metric-box'><div class='metric-value' style='color:#3fb950;'>{bullish_count}</div><div class='metric-label'>🟢 Bullish Signals</div></div>", unsafe_allow_html=True)
            m2.markdown(f"<div class='metric-box'><div class='metric-value' style='color:#f85149;'>{bearish_count}</div><div class='metric-label'>🔴 Bearish Signals</div></div>", unsafe_allow_html=True)
            m3.markdown(f"<div class='metric-box'><div class='metric-value' style='color:#ffd700;'>{total_pred - bullish_count - bearish_count}</div><div class='metric-label'>🟡 Neutral Signals</div></div>", unsafe_allow_html=True)
            m4.markdown(f"<div class='metric-box'><div class='metric-value' style='color:#58a6ff;'>{total_pred}</div><div class='metric-label'>📊 Models Trained</div></div>", unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown(render_ml_predictions_table(df_stocks_display.head(top_n_ml), raw_data_batch, top_n_ml), unsafe_allow_html=True)

            # Add ML signals to chart display
            for sym, pred in ml_predictions.items():
                ml_signals_dict[sym] = (pred['signal'], pred['conf'])

    # ============================================================
    # 📈 BACKTESTING LAB TAB
    # ============================================================
    elif watchlist_mode == "📈 Backtesting Lab":
        st.markdown("<div style='font-size:18px; font-weight:bold; margin-bottom:10px; color:#3fb950;'>📈 Backtesting Laboratory</div>", unsafe_allow_html=True)

        bt_col1, bt_col2, bt_col3, bt_col4 = st.columns(4)
        with bt_col1:
            bt_symbol = st.selectbox("📊 Select Stock", ["NIFTY"] + all_names, key="bt_sym")
        with bt_col2:
            bt_strategy = st.selectbox("🎯 Strategy", [
                "VWAP_Momentum", "EMA_Crossover", "RSI_Reversal", "Momentum_Breakout"
            ], key="bt_strat")
        with bt_col3:
            bt_capital = st.number_input("💰 Initial Capital (₹)", min_value=10000, max_value=10000000, value=100000, step=10000)
        with bt_col4:
            st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
            run_bt = st.button("🚀 Run Backtest", use_container_width=True)

        if run_bt:
            fetch_t_bt = df[df['T'] == bt_symbol]['Fetch_T'].iloc[0] if bt_symbol in df['T'].values else f"{bt_symbol}.NS"
            with st.spinner(f"📈 Running {bt_strategy} backtest on {bt_symbol}..."):
                raw_bt_data = yf.download(fetch_t_bt, period="2y", progress=False, auto_adjust=True)
                bt_result   = run_backtest(raw_bt_data, bt_strategy, bt_capital)
                st.session_state.backtest_results[f"{bt_symbol}_{bt_strategy}"] = {
                    'result': bt_result, 'symbol': bt_symbol, 'strategy': bt_strategy
                }

        # Show all cached backtest results
        if st.session_state.backtest_results:
            for key, bt_data in list(st.session_state.backtest_results.items()):
                result   = bt_data['result']
                symbol   = bt_data['symbol']
                strategy = bt_data['strategy']

                st.markdown(render_backtest_results(result, strategy, symbol), unsafe_allow_html=True)

                if result and result.get('equity'):
                    render_equity_curve(result['equity'], symbol, strategy)

                if result and not result['trades'].empty:
                    with st.expander(f"📋 View All Trades — {symbol} ({strategy})", expanded=False):
                        df_trades_display = result['trades'][['Entry', 'Exit', 'Type', 'PnL', 'Result', 'Reason']].copy()
                        df_trades_display['Entry'] = df_trades_display['Entry'].round(2)
                        df_trades_display['Exit']  = df_trades_display['Exit'].round(2)
                        st.dataframe(df_trades_display, use_container_width=True, hide_index=True)

                st.markdown("<hr style='border-color:#30363d; margin:10px 0;'>", unsafe_allow_html=True)

        else:
            st.info("👆 Select a stock & strategy, then click **Run Backtest** to see results.")

            # Show comparison table for quick overview
            st.markdown("### 📊 Quick Strategy Comparison (NIFTY50 Top Stocks)")
            if st.button("⚡ Auto-Compare Top 5 Stocks × All Strategies"):
                top5 = df_nifty.sort_values('S', ascending=False).head(5)['T'].tolist()
                strategies = ["VWAP_Momentum", "EMA_Crossover", "RSI_Reversal", "Momentum_Breakout"]
                comparison_rows = []
                with st.spinner("Running comparison backtests..."):
                    for sym in top5:
                        fetch_t = df[df['T'] == sym]['Fetch_T'].iloc[0]
                        raw_d   = yf.download(fetch_t, period="2y", progress=False, auto_adjust=True)
                        for strat in strategies:
                            r = run_backtest(raw_d, strat, 100000)
                            if r:
                                comparison_rows.append({'Stock': sym, 'Strategy': strat,
                                    'Win Rate': f"{r['win_rate']}%", 'Return': f"{r['total_return']:+.1f}%",
                                    'Sharpe': r['sharpe'], 'Max DD': f"{r['max_dd']}%", 'Trades': r['total_trades']})
                if comparison_rows:
                    df_comp = pd.DataFrame(comparison_rows)
                    st.dataframe(df_comp, use_container_width=True, hide_index=True)

    # ============================================================
    # All Original Views (unchanged logic)
    # ============================================================
    elif view_mode == "Heat Map" and watchlist_mode not in ["Fundamentals 🏢", "Terminal Tables 🗃️", "My Portfolio 💼"]:
        if not df_indices.empty and watchlist_mode != "Commodity 🛢️":
            html_idx = '<div class="heatmap-grid">'
            for _, row in df_indices.iterrows():
                pct_val = float(row.get('W_C', row['C'])) if chart_timeframe == "Weekly Chart" else float(row['C'])
                bg = "bear-card" if (row['T'] == "INDIA VIX" and pct_val > 0) else ("bull-card" if pct_val > 0 else ("bear-card" if pct_val < 0 else "neut-card"))
                html_idx += f'<a href="https://in.tradingview.com/chart/?symbol={TV_INDICES_URL.get(row["Fetch_T"])}" target="_blank" class="stock-card {bg}"><div class="t-score">IDX</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{"+" if pct_val>0 else ""}{pct_val:.2f}%</div></a>'
            st.markdown(html_idx + '</div><hr class="custom-hr">', unsafe_allow_html=True)

        if not df_sectors.empty and watchlist_mode != "Commodity 🛢️":
            html_sec = '<div class="heatmap-grid">'
            for _, row in df_sectors.iterrows():
                pct_val = float(row.get('W_C', row['C'])) if chart_timeframe == "Weekly Chart" else float(row['C'])
                bg = "bull-card" if pct_val > 0 else ("bear-card" if pct_val < 0 else "neut-card")
                html_sec += f'<a href="https://in.tradingview.com/chart/?symbol={TV_SECTOR_URL.get(row["Fetch_T"], "")}" target="_blank" class="stock-card {bg}"><div class="t-score" style="color:#00BFFF;">SEC</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{"+" if pct_val>0 else ""}{pct_val:.2f}%</div></a>'
            st.markdown(html_sec + '</div><hr class="custom-hr">', unsafe_allow_html=True)

        if not df_stocks_display.empty:
            df_buy  = df_stocks_display[df_stocks_display['Strategy_Icon'].str.contains('BUY', na=False)] if 'Strategy_Icon' in df_stocks_display.columns else df_stocks_display[df_stocks_display[sort_key] >= 0]
            df_sell = df_stocks_display[df_stocks_display['Strategy_Icon'].str.contains('SELL', na=False)] if 'Strategy_Icon' in df_stocks_display.columns else df_stocks_display[df_stocks_display[sort_key] < 0]

            def render_heatmap_section(df_sec, title, title_color):
                st.markdown(f"<div style='font-size:16px; font-weight:bold; margin:15px 0 5px 0; color:{title_color};'>{title}</div>", unsafe_allow_html=True)
                html_stk = '<div class="heatmap-grid">'
                for _, row in df_sec.iterrows():
                    pct_val = float(row.get('W_C', row['C'])) if chart_timeframe == "Weekly Chart" else float(row['C'])
                    bg      = "bull-card" if pct_val > 0 else ("bear-card" if pct_val < 0 else "neut-card")
                    special_icon = f"⭐{int(row['S'])}"
                    if watchlist_mode == "Swing Trading 📈": special_icon = "🌟" if row.get('Is_W_Pullback', False) else "🚀"
                    elif watchlist_mode == "Day Trading Stocks 🚀":
                        si = str(row.get('Strategy_Icon', ''))
                        special_icon = "🟢 BUY" if 'BUY' in si else ("🔴 SELL" if 'SELL' in si else "🚀")
                    html_stk += f'<a href="https://in.tradingview.com/chart/?symbol=NSE:{row["T"]}" target="_blank" class="stock-card {bg}"><div class="t-score">{special_icon}</div><div class="t-name">{row["T"]}</div><div class="t-price">{row["P"]:.2f}</div><div class="t-pct">{"+" if pct_val>0 else ""}{pct_val:.2f}%</div></a>'
                st.markdown(html_stk + '</div>', unsafe_allow_html=True)

            if not df_buy.empty:  render_heatmap_section(df_buy,  f"🟢 POSITIVE / BUY ({watchlist_mode})",  "#3fb950")
            if not df_sell.empty: render_heatmap_section(df_sell, f"🔴 NEGATIVE / SELL ({watchlist_mode})", "#f85149")
            st.markdown('<br>', unsafe_allow_html=True)

            if watchlist_mode == "Swing Trading 📈":
                with st.expander("🌊 Swing Trading Radar", expanded=True): st.markdown(render_swing_terminal_table(df_stocks_display), unsafe_allow_html=True)
            elif watchlist_mode in ["High Score Stocks 🔥", "Day Trading Stocks 🚀"]:
                with st.expander("🔥 Day Trading Radar", expanded=True): st.markdown(render_highscore_terminal_table(df_stocks_display), unsafe_allow_html=True)
        else:
            st.info("No items found.")

    elif watchlist_mode == "Terminal Tables 🗃️" and view_mode == "Heat Map":
        for df_temp in [df_buy_sector, df_sell_sector, df_independent, df_broader]:
            if not df_temp.empty:
                df_temp['AlphaTag'] = df_temp['Fetch_T'].map(alpha_tags).fillna("")
                df_temp['S'] = df_temp['S'] + df_temp['Fetch_T'].map(trend_scores).fillna(0)
        st.markdown(render_html_table(df_buy_sector.sort_values(['S', 'C'], ascending=[False, False]), f"🚀 BUY LEADER: {top_buy_sector}", "term-head-buy"), unsafe_allow_html=True)
        st.markdown(render_html_table(df_sell_sector.sort_values(['S', 'C'], ascending=[False, True]), f"🩸 SELL LAGGARD: {top_sell_sector}", "term-head-sell"), unsafe_allow_html=True)
        st.markdown(render_html_table(df_independent, "🌟 INDEPENDENT MOVERS", "term-head-ind"), unsafe_allow_html=True)
        st.markdown(render_html_table(df_broader, "🌌 BROADER MARKET", "term-head-brd"), unsafe_allow_html=True)

    elif watchlist_mode == "My Portfolio 💼" and view_mode == "Heat Map":
        sc1, sc2 = st.columns([0.7, 0.3])
        with sc2:
            port_sort = st.selectbox("↕️ Sort:", ["Default", "Day P&L ⬆️", "Day P&L ⬇️", "Total P&L ⬆️", "Total P&L ⬇️", "P&L % ⬆️", "P&L % ⬇️"], label_visibility="collapsed")
        st.markdown(render_portfolio_table(df_port_saved, df_stocks, weekly_trends, port_sort), unsafe_allow_html=True)

        with st.expander("➕ Add Stock to Portfolio", expanded=False):
            with st.form("portfolio_add_form", clear_on_submit=True):
                c1, c2, c3, c4 = st.columns(4)
                with c1: new_sym   = st.text_input("NSE Symbol", placeholder="e.g. ITC").upper().strip()
                with c2: new_qty   = st.number_input("Quantity", min_value=1, value=10)
                with c3: new_price = st.number_input("Buy Price (₹)", min_value=0.0, value=100.0)
                with c4: new_date  = st.date_input("Purchase Date")
                c5, c6, c7, c8 = st.columns(4)
                with c5: new_sl = st.number_input("Fixed SL", min_value=0.0, value=0.0)
                with c6: new_t1 = st.number_input("Target 1", min_value=0.0, value=0.0)
                with c7: new_t2 = st.number_input("Target 2", min_value=0.0, value=0.0)
                with c8:
                    st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
                    submit_btn = st.form_submit_button("➕ Verify & Add", use_container_width=True)
            if submit_btn and new_sym:
                with st.spinner(f"Checking {new_sym}..."):
                    chk = yf.download(f"{new_sym}.NS", period="1d", progress=False)
                    if chk.empty: st.error(f"'{new_sym}' not found!")
                    else:
                        new_date_str = new_date.strftime("%d-%b-%Y")
                        if new_sym in df_port_saved['Symbol'].values:
                            old = df_port_saved[df_port_saved['Symbol'] == new_sym].iloc[0]
                            old_qty, old_price = float(old['Quantity']), float(old['Buy_Price'])
                            total_qty = old_qty + new_qty
                            avg_price = ((old_qty * old_price) + (new_qty * new_price)) / total_qty
                            df_port_saved.loc[df_port_saved['Symbol'] == new_sym, ['Buy_Price', 'Quantity', 'Date', 'SL', 'T1', 'T2']] = [round(avg_price, 2), total_qty, new_date_str, new_sl, new_t1, new_t2]
                            st.success(f"✅ {new_sym} averaged! (Avg: ₹{round(avg_price,2)}, Qty: {int(total_qty)})")
                        else:
                            new_row = pd.DataFrame({"Symbol": [new_sym], "Buy_Price": [new_price], "Quantity": [new_qty], "Date": [new_date_str], "SL": [new_sl], "T1": [new_t1], "T2": [new_t2]})
                            df_port_saved = pd.concat([df_port_saved, new_row], ignore_index=True)
                            st.success(f"✅ {new_sym} added!")
                        import time
                        save_portfolio(df_port_saved)
                        fetch_all_data.clear()
                        time.sleep(1.5)
                        st.rerun()

        if not df_port_saved.empty:
            with st.expander("💸 Sell Stock & Book P&L", expanded=False):
                with st.form("portfolio_sell_form"):
                    rc1, rc2, rc3, rc4 = st.columns([2, 1, 2, 2])
                    with rc1: sell_sym   = st.selectbox("Select Stock", ["-- Select --"] + df_port_saved['Symbol'].tolist())
                    with rc2: sell_qty   = st.number_input("Qty", min_value=1, value=1)
                    with rc3: sell_price = st.number_input("Exit Price (₹)", min_value=0.0, value=0.0)
                    with rc4:
                        st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
                        sell_btn = st.form_submit_button("💸 Confirm Sell", use_container_width=True)
                    if sell_btn and sell_sym != "-- Select --" and sell_price > 0:
                        port_row    = df_port_saved[df_port_saved['Symbol'] == sell_sym].iloc[0]
                        buy_price   = float(port_row['Buy_Price'])
                        current_qty = int(port_row['Quantity'])
                        sell_qty    = min(sell_qty, current_qty)
                        pnl_rs  = (sell_price - buy_price) * sell_qty
                        pnl_pct = ((sell_price - buy_price) / buy_price) * 100
                        df_closed = load_closed_trades()
                        new_closed = pd.DataFrame({"Sell_Date": [datetime.now().strftime("%d-%b-%Y")], "Symbol": [sell_sym], "Quantity": [sell_qty], "Buy_Price": [buy_price], "Sell_Price": [sell_price], "PnL_Rs": [pnl_rs], "PnL_Pct": [pnl_pct]})
                        df_closed = pd.concat([df_closed, new_closed], ignore_index=True)
                        save_closed_trades(df_closed)
                        if sell_qty == current_qty: df_port_saved = df_port_saved[df_port_saved['Symbol'] != sell_sym]
                        else: df_port_saved.loc[df_port_saved['Symbol'] == sell_sym, 'Quantity'] = current_qty - sell_qty
                        save_portfolio(df_port_saved)
                        fetch_all_data.clear()
                        st.rerun()

            with st.expander("📜 Trade Book", expanded=False):
                st.markdown(render_closed_trades_table(load_closed_trades()), unsafe_allow_html=True)

    else:  # CHART VIEW
        st.markdown("<br>", unsafe_allow_html=True)
        weekly_charts = {}
        if chart_timeframe == "Weekly Chart":
            with st.spinner("Fetching Weekly Data..."):
                display_tkrs = list(set(
                    ([] if search_stock == "-- None --" else [df[df['T'] == search_stock]['Fetch_T'].iloc[0]]) +
                    df_indices['Fetch_T'].tolist() +
                    st.session_state.pinned_stocks +
                    df_stocks_display['Fetch_T'].tolist()
                ))
                if display_tkrs:
                    wk_data = yf.download(display_tkrs, period="2y", interval="1wk", progress=False, group_by='ticker', threads=True, auto_adjust=True)
                    for sym in display_tkrs:
                        try:
                            df_w = wk_data[sym] if isinstance(wk_data.columns, pd.MultiIndex) else wk_data
                            df_w = df_w.dropna(subset=['Close']).copy()
                            if not df_w.empty:
                                df_w['EMA_10'] = df_w['Close'].ewm(span=10, adjust=False).mean()
                                df_w['EMA_50'] = df_w['Close'].ewm(span=50, adjust=False).mean()
                                weekly_charts[sym] = df_w
                        except: pass

        chart_dict_to_use = weekly_charts if chart_timeframe == "Weekly Chart" else processed_charts

        if search_stock != "-- None --":
            render_chart_grid(pd.DataFrame([df[df['T'] == search_stock].iloc[0]]), show_pin_option=True, key_prefix="search", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol, ml_signals=ml_signals_dict)
            st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)

        if watchlist_mode not in ["Terminal Tables 🗃️", "My Portfolio 💼", "Fundamentals 🏢", "Commodity 🛢️"]:
            render_chart_grid(df_indices, show_pin_option=False, key_prefix="idx", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol)
            st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)

        pinned_df  = df[df['Fetch_T'].isin(st.session_state.pinned_stocks)].copy()
        unpinned_df = df_stocks_display[~df_stocks_display['Fetch_T'].isin(pinned_df['Fetch_T'].tolist())]

        if not pinned_df.empty:
            st.markdown("<div style='font-size:16px; font-weight:bold; margin-bottom:5px; color:#ffd700;'>📌 Pinned Charts</div>", unsafe_allow_html=True)
            render_chart_grid(pinned_df, show_pin_option=True, key_prefix="pin", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol, ml_signals=ml_signals_dict)
            st.markdown("<hr class='custom-hr'>", unsafe_allow_html=True)

        if not unpinned_df.empty:
            df_buy_chart  = unpinned_df[unpinned_df['Strategy_Icon'].str.contains('BUY', na=False)] if 'Strategy_Icon' in unpinned_df.columns else unpinned_df[unpinned_df[sort_key] >= 0]
            df_sell_chart = unpinned_df[unpinned_df['Strategy_Icon'].str.contains('SELL', na=False)] if 'Strategy_Icon' in unpinned_df.columns else unpinned_df[unpinned_df[sort_key] < 0]

            if not df_buy_chart.empty:
                st.markdown(f"<div style='font-size:16px; font-weight:bold; margin-top:10px; margin-bottom:5px; color:#3fb950;'>🟢 POSITIVE / BUY ({watchlist_mode})</div>", unsafe_allow_html=True)
                render_chart_grid(df_buy_chart, show_pin_option=True, key_prefix="main_buy", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol, ml_signals=ml_signals_dict)

            if not df_sell_chart.empty:
                st.markdown(f"<div style='font-size:16px; font-weight:bold; margin-top:20px; margin-bottom:5px; color:#f85149;'>🔴 NEGATIVE / SELL ({watchlist_mode})</div>", unsafe_allow_html=True)
                render_chart_grid(df_sell_chart, show_pin_option=True, key_prefix="main_sell", timeframe=chart_timeframe, chart_dict=chart_dict_to_use, show_crosshair=show_crosshair, show_vol=show_vol, ml_signals=ml_signals_dict)

else:
    st.info("⏳ Loading Market Data...")
