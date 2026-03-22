"""
ADX trend-following backtest — EURUSD + SOL on Lighter.xyz

Tests ADX-based entries on Yahoo Finance data (6 months) + Lighter recent data.

Strategy:
  BUY:  +DI crosses above -DI AND ADX > threshold (trending)
  SELL: -DI crosses above +DI AND ADX > threshold (trending)
  SL/TP: configurable per asset class, 1:2 R:R

Sweeps ADX thresholds (20-35) and DI periods (10-20) to find best params.
"""
import pandas as pd
import numpy as np
import json
import logging

logger = logging.getLogger(__name__)


def calculate_adx(df, period=14):
    """Calculate ADX, +DI, -DI from OHLC DataFrame."""
    high = df['h'].astype(float)
    low = df['l'].astype(float)
    close = df['c'].astype(float)

    # True Range
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Directional Movement
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # Smoothed averages (Wilder's smoothing)
    atr = pd.Series(tr).ewm(alpha=1/period, min_periods=period).mean()
    plus_di_smooth = pd.Series(plus_dm).ewm(alpha=1/period, min_periods=period).mean()
    minus_di_smooth = pd.Series(minus_dm).ewm(alpha=1/period, min_periods=period).mean()

    plus_di = 100 * plus_di_smooth / atr
    minus_di = 100 * minus_di_smooth / atr

    # ADX
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.ewm(alpha=1/period, min_periods=period).mean()

    return adx, plus_di, minus_di


def fetch_yahoo_data(symbol, period='6mo', interval='15m'):
    """Fetch OHLC from Yahoo Finance."""
    import yfinance as yf

    ticker_map = {
        'EURUSD': 'EURUSD=X',
        'GBPUSD': 'GBPUSD=X',
        'USDJPY': 'USDJPY=X',
        'SOL': 'SOL-USD',
        'BTC': 'BTC-USD',
        'ETH': 'ETH-USD',
        'XAU': 'GC=F',
    }

    ticker = ticker_map.get(symbol, symbol)

    # Yahoo limits: 15m data = max 60 days, 1h = max 730 days
    if interval in ('15m', '5m'):
        period = '60d'
    elif interval == '1h':
        period = '6mo'

    data = yf.download(ticker, period=period, interval=interval, progress=False)
    if data.empty:
        return None

    # Flatten MultiIndex columns if present
    if hasattr(data.columns, 'levels'):
        data.columns = data.columns.get_level_values(0)

    df = pd.DataFrame({
        'o': data['Open'].values,
        'h': data['High'].values,
        'l': data['Low'].values,
        'c': data['Close'].values,
        'v': data['Volume'].values if 'Volume' in data.columns else 0,
    })
    df = df.dropna()
    return df


def fetch_lighter_data(symbol, resolution='15m', count=500):
    """Fetch OHLC from Lighter API."""
    try:
        from app.quant.algorithms.lighter.client import get_candles
        candles = get_candles(symbol, resolution=resolution, count_back=count)
        if not candles:
            return None
        df = pd.DataFrame(candles)
        for c in ['o', 'h', 'l', 'c']:
            df[c] = df[c].astype(float)
        return df
    except Exception as e:
        logger.warning("Lighter data fetch failed for %s: %s", symbol, e)
        return None


def backtest_adx(df, sl_pct, tp_pct, adx_threshold=25, di_period=14, cooldown_bars=4):
    """Backtest ADX trend-following strategy.

    Entry: +DI crosses above -DI with ADX > threshold → BUY
           -DI crosses above +DI with ADX > threshold → SELL
    Exit:  SL or TP hit (checked on high/low of each bar)

    Returns dict with results.
    """
    adx, plus_di, minus_di = calculate_adx(df, period=di_period)

    trades = []
    in_trade = False
    entry_side = None
    sl = tp = entry_price = 0
    bars_since_trade = cooldown_bars + 1
    entry_bar = 0

    warmup = di_period * 3  # need enough bars for ADX to stabilize

    for i in range(warmup, len(df)):
        bars_since_trade += 1

        if in_trade:
            # Check SL/TP
            if entry_side == 'LONG':
                if df['l'].iloc[i] <= sl:
                    trades.append({'side': 'LONG', 'pnl_pct': -sl_pct, 'bars': i - entry_bar})
                    in_trade = False
                    bars_since_trade = 0
                elif df['h'].iloc[i] >= tp:
                    trades.append({'side': 'LONG', 'pnl_pct': tp_pct, 'bars': i - entry_bar})
                    in_trade = False
                    bars_since_trade = 0
            else:
                if df['h'].iloc[i] >= sl:
                    trades.append({'side': 'SHORT', 'pnl_pct': -sl_pct, 'bars': i - entry_bar})
                    in_trade = False
                    bars_since_trade = 0
                elif df['l'].iloc[i] <= tp:
                    trades.append({'side': 'SHORT', 'pnl_pct': tp_pct, 'bars': i - entry_bar})
                    in_trade = False
                    bars_since_trade = 0
        else:
            if bars_since_trade < cooldown_bars:
                continue

            curr_adx = adx.iloc[i]
            curr_plus = plus_di.iloc[i]
            curr_minus = minus_di.iloc[i]
            prev_plus = plus_di.iloc[i-1]
            prev_minus = minus_di.iloc[i-1]

            if pd.isna(curr_adx) or pd.isna(curr_plus):
                continue

            if curr_adx < adx_threshold:
                continue

            price = df['c'].iloc[i]

            # +DI crosses above -DI → BUY
            if prev_plus <= prev_minus and curr_plus > curr_minus:
                entry_side = 'LONG'
                entry_price = price
                sl = price * (1 - sl_pct)
                tp = price * (1 + tp_pct)
                in_trade = True
                entry_bar = i

            # -DI crosses above +DI → SELL
            elif prev_minus <= prev_plus and curr_minus > curr_plus:
                entry_side = 'SHORT'
                entry_price = price
                sl = price * (1 + sl_pct)
                tp = price * (1 - tp_pct)
                in_trade = True
                entry_bar = i

    return trades


def summarize(trades, symbol, params_str):
    """Summarize backtest results."""
    if not trades:
        return None

    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] < 0]
    total = len(trades)
    win_count = len(wins)
    wr = win_count / total * 100
    gross_win = sum(t['pnl_pct'] for t in wins)
    gross_loss = abs(sum(t['pnl_pct'] for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else float('inf')
    net_pct = sum(t['pnl_pct'] for t in trades) * 100
    avg_bars = sum(t['bars'] for t in trades) / total

    return {
        'symbol': symbol,
        'params': params_str,
        'trades': total,
        'wins': win_count,
        'wr': round(wr, 1),
        'pf': round(pf, 2),
        'net_pct': round(net_pct, 2),
        'avg_bars': round(avg_bars, 1),
    }


def run_sweep():
    """Run parameter sweep across symbols and ADX configs."""
    configs = {
        'EURUSD': {'sl': 0.003, 'tp': 0.006},   # forex: tight SL/TP
        'SOL':    {'sl': 0.015, 'tp': 0.030},     # crypto: wider SL/TP
        'XAU':    {'sl': 0.008, 'tp': 0.016},     # metals: reference
    }

    results = []

    for symbol, risk in configs.items():
        print(f"\n{'='*60}")
        print(f"  {symbol} — ADX Trend-Following Backtest")
        print(f"  SL={risk['sl']*100:.1f}%  TP={risk['tp']*100:.1f}%  (1:2 R:R)")
        print(f"{'='*60}")

        # Try Yahoo first (more data), then Lighter
        for tf_label, interval, lighter_res in [('15m', '15m', '15m'), ('1h', '1h', '1h')]:
            print(f"\n  --- Timeframe: {tf_label} ---")

            # Yahoo data
            ydf = fetch_yahoo_data(symbol, interval=interval)
            yahoo_bars = len(ydf) if ydf is not None else 0

            # Lighter data
            ldf = fetch_lighter_data(symbol, resolution=lighter_res, count=500)
            lighter_bars = len(ldf) if ldf is not None else 0

            print(f"  Yahoo: {yahoo_bars} bars | Lighter: {lighter_bars} bars")

            # Use whichever has more data
            df = ydf if yahoo_bars > lighter_bars else ldf
            source = 'Yahoo' if yahoo_bars > lighter_bars else 'Lighter'
            if df is None or len(df) < 100:
                print(f"  SKIP — not enough data")
                continue

            print(f"  Using: {source} ({len(df)} bars)")

            # Sweep ADX thresholds and DI periods
            best = None
            for adx_thresh in [20, 22, 25, 28, 30]:
                for di_period in [10, 14, 18]:
                    trades = backtest_adx(
                        df, risk['sl'], risk['tp'],
                        adx_threshold=adx_thresh,
                        di_period=di_period,
                        cooldown_bars=4,
                    )
                    params = f"ADX>{adx_thresh} DI({di_period})"
                    s = summarize(trades, symbol, params)
                    if s and s['trades'] >= 5:
                        results.append({**s, 'tf': tf_label, 'source': source})
                        if best is None or s['pf'] > best['pf']:
                            best = s

            if best:
                print(f"  BEST: {best['params']} — {best['trades']}T {best['wins']}W "
                      f"{best['wr']}%WR PF={best['pf']} net={best['net_pct']:+.2f}%")
            else:
                print(f"  No viable configs found (need >=5 trades)")

    # Print full leaderboard
    results.sort(key=lambda x: x['pf'], reverse=True)
    print(f"\n{'='*60}")
    print("  LEADERBOARD — All viable configs (PF sorted)")
    print(f"{'='*60}")
    print(f"  {'Symbol':<8} {'TF':<4} {'Params':<16} {'T':>3} {'W':>3} {'WR':>6} {'PF':>6} {'Net':>8} {'Src':<7}")
    print(f"  {'-'*66}")
    for r in results[:20]:
        print(f"  {r['symbol']:<8} {r['tf']:<4} {r['params']:<16} {r['trades']:>3} {r['wins']:>3} "
              f"{r['wr']:>5.1f}% {r['pf']:>5.2f} {r['net_pct']:>+7.2f}% {r['source']:<7}")


if __name__ == '__main__':
    run_sweep()
