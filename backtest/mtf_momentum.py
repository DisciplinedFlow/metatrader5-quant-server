#!/usr/bin/env python3
"""
Multi-Timeframe Momentum Scalper — backtest & strategy.

Philosophy: Quality comes from CONFLUENCE across timeframes, not from
waiting days for a single signal.

M30: TREND — which direction are we trading?
  - EMA 8/21 alignment + ADX > 20 = confirmed trend
  - Only trade WITH the M30 trend, never against it

M15: STRUCTURE — where do we enter?
  - Pullback to EMA 21 zone (within 1 ATR)
  - Higher low in uptrend / lower high in downtrend
  - NOT chasing — waiting for price to come to us

M5: TIMING — when exactly do we pull the trigger?
  - Momentum shift: MACD histogram turns positive (bullish) / negative (bearish)
  - RSI crosses above 50 (bullish) / below 50 (bearish)
  - OR: strong body candle in trend direction (>60% body ratio)

Live addition (not backtestable): tick CVD confirms volume is backing the move.

Entry: M5 bar close after all 3 timeframes align
SL: Below M15 swing low (long) / above M15 swing high (short)
TP: 2x SL distance (1:2 R:R)

Expected: trades every 15-60 min during active sessions.
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pandas as pd
from engine import fetch_bars, report, SPREADS

MT5_URL = 'http://localhost:5001'
TF_MAP = {'M5': 5, 'M15': 15, 'M30': 30, 'H1': 16385, 'H4': 16388}


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def adx(df, period=14):
    high, low, close = df['high'], df['low'], df['close']
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    plus_dm[plus_dm < minus_dm] = 0
    minus_dm[minus_dm < plus_dm] = 0
    tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
    atr = tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/period, min_periods=period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1/period, min_periods=period, adjust=False).mean() / atr
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1/period, min_periods=period, adjust=False).mean(), plus_di, minus_di


def macd(series, fast=12, slow=26, signal=9):
    f = ema(series, fast)
    s = ema(series, slow)
    macd_line = f - s
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df, period=14):
    tr = np.maximum(
        df['high'] - df['low'],
        np.maximum(abs(df['high'] - df['close'].shift(1)),
                   abs(df['low'] - df['close'].shift(1)))
    )
    return tr.rolling(period).mean()


# ---------------------------------------------------------------------------
# Prepare multi-timeframe data
# ---------------------------------------------------------------------------

def prepare_mtf(symbol, start='2025-09-01T00:00:00'):
    """Fetch M5, M15, M30 data and align them."""
    print(f'  Fetching {symbol} M5/M15/M30...')

    m5 = fetch_bars(symbol, 'M5', 10000, start=start)
    m15 = fetch_bars(symbol, 'M15', 10000, start=start)
    m30 = fetch_bars(symbol, 'M30', 10000, start=start)

    # Add indicators to each timeframe
    for df in [m5, m15, m30]:
        df['ema8'] = ema(df['close'], 8)
        df['ema21'] = ema(df['close'], 21)
        df['ema50'] = ema(df['close'], 50)
        df['atr14'] = atr(df)
        df['rsi14'] = rsi(df['close'])
        adx_val, plus_di, minus_di = adx(df)
        df['adx'] = adx_val
        df['plus_di'] = plus_di
        df['minus_di'] = minus_di
        m_line, s_line, hist = macd(df['close'])
        df['macd'] = m_line
        df['macd_signal'] = s_line
        df['macd_hist'] = hist

    return m5, m15, m30


def get_htf_bar(htf_df, timestamp):
    """Find the most recent HTF bar at or before the given timestamp."""
    mask = htf_df['time'] <= timestamp
    if not mask.any():
        return None
    return htf_df[mask].iloc[-1]


# ---------------------------------------------------------------------------
# M30 Trend Analysis
# ---------------------------------------------------------------------------

def m30_trend(bar):
    """Determine M30 trend direction.

    Returns: 'BULL', 'BEAR', or None (no clear trend)
    """
    if bar is None:
        return None

    ema8 = bar['ema8']
    ema21 = bar['ema21']
    adx_val = bar['adx']

    if pd.isna(ema8) or pd.isna(ema21) or pd.isna(adx_val):
        return None

    # Need ADX > 18 for trend confirmation (slightly relaxed from 20)
    if adx_val < 18:
        return None

    if ema8 > ema21:
        return 'BULL'
    elif ema8 < ema21:
        return 'BEAR'

    return None


# ---------------------------------------------------------------------------
# M15 Structure Analysis
# ---------------------------------------------------------------------------

def m15_structure(m15_df, idx, trend, lookback=12):
    """Check M15 structure for entry zone.

    For BULL: price pulled back near EMA21, making higher lows
    For BEAR: price pulled back near EMA21, making lower highs

    Returns: (valid, sl_price) or (False, None)
    """
    if idx < lookback + 5:
        return False, None

    bar = m15_df.iloc[idx]
    ema21 = bar['ema21']
    atr_val = bar['atr14']

    if pd.isna(ema21) or pd.isna(atr_val) or atr_val <= 0:
        return False, None

    price = bar['close']

    if trend == 'BULL':
        # Price should be near EMA21 (within 1.5 ATR above it)
        # Not too far above (that's chasing), not below (trend broken)
        dist_from_ema = (price - ema21) / atr_val
        if dist_from_ema < -0.5 or dist_from_ema > 1.5:
            return False, None

        # Check for higher low structure
        recent_low = m15_df['low'].iloc[max(0, idx-lookback):idx+1].min()
        prior_low = m15_df['low'].iloc[max(0, idx-lookback*2):max(0, idx-lookback)].min()

        # Higher low or equal low (some tolerance)
        if recent_low < prior_low - atr_val * 0.3:
            return False, None  # Lower low = structure broken

        # SL below recent swing low
        sl = recent_low - atr_val * 0.3
        return True, sl

    elif trend == 'BEAR':
        dist_from_ema = (ema21 - price) / atr_val
        if dist_from_ema < -0.5 or dist_from_ema > 1.5:
            return False, None

        recent_high = m15_df['high'].iloc[max(0, idx-lookback):idx+1].max()
        prior_high = m15_df['high'].iloc[max(0, idx-lookback*2):max(0, idx-lookback)].max()

        if recent_high > prior_high + atr_val * 0.3:
            return False, None

        sl = recent_high + atr_val * 0.3
        return True, sl

    return False, None


# ---------------------------------------------------------------------------
# M5 Momentum Trigger
# ---------------------------------------------------------------------------

def m5_trigger(m5_df, idx, trend):
    """Check M5 for momentum trigger in trend direction.

    Returns True if M5 momentum confirms the entry.
    """
    if idx < 3:
        return False

    bar = m5_df.iloc[idx]
    prev = m5_df.iloc[idx-1]

    macd_hist = bar['macd_hist']
    macd_hist_prev = prev['macd_hist']
    rsi_val = bar['rsi14']
    rsi_prev = prev['rsi14']

    if pd.isna(macd_hist) or pd.isna(rsi_val):
        return False

    if trend == 'BULL':
        # MACD histogram turning positive (momentum shifting up)
        macd_turn = macd_hist > 0 and macd_hist_prev <= 0

        # RSI crossing above 50 (bullish momentum)
        rsi_cross = rsi_val > 50 and rsi_prev <= 50

        # Strong bullish candle (>60% body, close near high)
        h, l, o, c = bar['high'], bar['low'], bar['open'], bar['close']
        bar_range = h - l
        strong_candle = False
        if bar_range > 0:
            body_pct = (c - o) / bar_range
            close_pos = (c - l) / bar_range
            strong_candle = body_pct > 0.5 and close_pos > 0.65

        # Need at least one trigger
        return macd_turn or rsi_cross or strong_candle

    elif trend == 'BEAR':
        macd_turn = macd_hist < 0 and macd_hist_prev >= 0
        rsi_cross = rsi_val < 50 and rsi_prev >= 50

        h, l, o, c = bar['high'], bar['low'], bar['open'], bar['close']
        bar_range = h - l
        strong_candle = False
        if bar_range > 0:
            body_pct = (o - c) / bar_range
            close_pos = (h - c) / bar_range
            strong_candle = body_pct > 0.5 and close_pos > 0.65

        return macd_turn or rsi_cross or strong_candle

    return False


# ---------------------------------------------------------------------------
# Session filter
# ---------------------------------------------------------------------------

def in_trading_session(timestamp):
    """Only trade during London (07-12) and NY (13-17) UTC."""
    hour = timestamp.hour
    return 7 <= hour < 17


# ---------------------------------------------------------------------------
# Main backtest loop
# ---------------------------------------------------------------------------

def backtest_mtf(symbol, m5, m15, m30, sl_mult=1.0, tp_mult=2.0,
                 cooldown_bars=3, max_open=2):
    """Multi-timeframe backtest on M5 execution bars.

    Entry: M30 trend + M15 structure + M5 trigger
    SL: M15 swing-based
    TP: sl_dist * tp_mult
    """
    spread = SPREADS.get(symbol, 0.0002)
    trades = []
    open_trades = []
    last_entry_bar = -cooldown_bars - 1

    warmup = 100  # bars for indicators

    for i in range(warmup, len(m5)):
        m5_bar = m5.iloc[i]
        ts = m5_bar['time']

        # --- Check open trades ---
        still_open = []
        for t in open_trades:
            if t['direction'] == 'BUY':
                if m5_bar['low'] <= t['sl']:
                    t.update({'exit_price': t['sl'], 'exit_bar': i, 'exit_time': ts,
                              'pnl': t['sl'] - t['entry_price'] - spread, 'result': 'SL'})
                    trades.append(t)
                    continue
                if m5_bar['high'] >= t['tp']:
                    t.update({'exit_price': t['tp'], 'exit_bar': i, 'exit_time': ts,
                              'pnl': t['tp'] - t['entry_price'] - spread, 'result': 'TP'})
                    trades.append(t)
                    continue
            else:
                if m5_bar['high'] >= t['sl']:
                    t.update({'exit_price': t['sl'], 'exit_bar': i, 'exit_time': ts,
                              'pnl': t['entry_price'] - t['sl'] - spread, 'result': 'SL'})
                    trades.append(t)
                    continue
                if m5_bar['low'] <= t['tp']:
                    t.update({'exit_price': t['tp'], 'exit_bar': i, 'exit_time': ts,
                              'pnl': t['entry_price'] - t['tp'] - spread, 'result': 'TP'})
                    trades.append(t)
                    continue
            still_open.append(t)
        open_trades = still_open

        # --- New entry check ---
        if len(open_trades) >= max_open:
            continue
        if i - last_entry_bar < cooldown_bars:
            continue
        if not in_trading_session(ts):
            continue

        # Step 1: M30 trend
        m30_bar = get_htf_bar(m30, ts)
        trend = m30_trend(m30_bar)
        if trend is None:
            continue

        # Step 2: M15 structure + SL placement
        m15_idx_mask = m15['time'] <= ts
        if not m15_idx_mask.any():
            continue
        m15_idx = m15[m15_idx_mask].index[-1]
        valid, sl_price = m15_structure(m15, m15_idx, trend)
        if not valid:
            continue

        # Step 3: M5 momentum trigger
        if not m5_trigger(m5, i, trend):
            continue

        # --- Execute entry ---
        entry_price = m5_bar['close']
        sl_dist = abs(entry_price - sl_price)

        # Sanity: SL must be at least 0.2 ATR and at most 3 ATR
        m5_atr = m5_bar['atr']
        if pd.isna(m5_atr) or m5_atr <= 0:
            continue
        if sl_dist < m5_atr * 0.2 or sl_dist > m5_atr * 3.0:
            continue

        tp_dist = sl_dist * tp_mult

        if trend == 'BULL':
            entry_price += spread / 2
            tp_price = entry_price + tp_dist
        else:
            entry_price -= spread / 2
            sl_price = entry_price + sl_dist  # recalc for short
            tp_price = entry_price - tp_dist

        trade = {
            'direction': 'BUY' if trend == 'BULL' else 'SELL',
            'entry_price': entry_price,
            'sl': sl_price if trend == 'BULL' else entry_price + sl_dist,
            'tp': tp_price,
            'sl_dist': sl_dist,
            'tp_dist': tp_dist,
            'entry_bar': i,
            'entry_time': ts,
            'atr': m5_atr,
            'exit_price': None, 'exit_bar': None, 'exit_time': None,
            'pnl': None, 'result': None,
        }
        open_trades.append(trade)
        last_entry_bar = i

    # Close remaining
    if open_trades:
        last = m5.iloc[-1]
        for t in open_trades:
            pnl = (last['close'] - t['entry_price'] - spread) if t['direction'] == 'BUY' else (t['entry_price'] - last['close'] - spread)
            t.update({'exit_price': last['close'], 'exit_bar': len(m5)-1,
                      'exit_time': last['time'], 'pnl': pnl, 'result': 'OPEN'})
            trades.append(t)

    return trades


# ---------------------------------------------------------------------------
# Strategy variations
# ---------------------------------------------------------------------------

STRATEGIES = [
    # (name, tp_mult, cooldown_bars, max_open)
    ('MTF Momentum 1:2',       2.0, 3, 2),
    ('MTF Momentum 1:1.5',     1.5, 3, 2),
    ('MTF Momentum 1:2.5',     2.5, 3, 2),
    ('MTF Momentum 1:3',       3.0, 3, 2),
    ('MTF Tight CD 1:2',       2.0, 1, 2),   # tighter cooldown
    ('MTF Wide CD 1:2',        2.0, 6, 2),   # wider cooldown (quality)
    ('MTF Single 1:2',         2.0, 3, 1),   # max 1 open trade
    ('MTF Single 1:1.5',       1.5, 3, 1),
]


def run_symbol(symbol):
    """Run all MTF strategies on one symbol."""
    try:
        m5, m15, m30 = prepare_mtf(symbol)
    except Exception as e:
        print(f'  SKIP {symbol}: {e}')
        return []

    results = []
    for name, tp_mult, cd, max_open in STRATEGIES:
        trades = backtest_mtf(symbol, m5, m15, m30,
                              tp_mult=tp_mult, cooldown_bars=cd, max_open=max_open)
        title = f'{name} — {symbol}'
        stats = report(trades, title)
        if stats and stats.get('trades', 0) >= 15:
            stats.update({'symbol': symbol, 'strategy': name,
                          'tp_mult': tp_mult, 'cooldown': cd})
            results.append(stats)

    return results


def main(symbols=None):
    symbols = symbols or ['XAUUSD', 'XAGUSD', 'EURUSD', 'GBPUSD', 'USDJPY',
                          'AUDUSD', 'USDCAD', 'UKOUSDft', 'USOUSD']
    all_results = []

    for sym in symbols:
        all_results.extend(run_symbol(sym))

    if not all_results:
        print('\nNo results.')
        return

    all_results.sort(key=lambda x: x.get('wr', 0), reverse=True)

    print('\n' + '=' * 100)
    print('  MTF MOMENTUM LEADERBOARD — sorted by WIN RATE')
    print('=' * 100)
    print(f'  {"Strategy":<25s} {"Symbol":<10s} {"TP":>4s} {"CD":>3s} {"Trades":>6s} {"WR%":>6s} {"PF":>6s} {"Exp(R)":>8s} {"MaxDD":>7s} {"Verdict":<8s}')
    print('-' * 100)

    for r in all_results[:40]:
        wr = r.get('wr', 0)
        exp = r.get('expectancy_r', 0)
        pf = r.get('profit_factor', 0)
        verdict = 'PASS' if wr >= 60 and exp > 0.1 and pf > 1.3 else 'MAYBE' if wr >= 55 and exp > 0 else 'FAIL'
        print(f'  {r["strategy"]:<25s} {r["symbol"]:<10s} {r["tp_mult"]:>4.1f} {r["cooldown"]:>3d} {r["trades"]:>6d} {wr:>5.1f}% {pf:>6.2f} {exp:>+7.3f} {r.get("max_drawdown_r",0):>6.1f}R {verdict:<8s}')

    print('=' * 100)

    passing = [r for r in all_results if r.get('wr', 0) >= 60 and r.get('expectancy_r', 0) > 0.1]
    maybe = [r for r in all_results if r.get('wr', 0) >= 55 and r.get('expectancy_r', 0) > 0 and r not in passing]
    print(f'\n  {len(passing)} PASS | {len(maybe)} MAYBE | {len(all_results) - len(passing) - len(maybe)} FAIL')

    if passing:
        best = passing[0]
        print(f'  BEST: {best["strategy"]} on {best["symbol"]} — {best["wr"]:.1f}% WR, {best["expectancy_r"]:+.3f}R, PF {best["profit_factor"]:.2f}, {best["trades"]} trades')

    # Frequency analysis
    print('\n  === TRADE FREQUENCY ===')
    for r in all_results[:10]:
        if r.get('trades', 0) > 0:
            # Estimate trades per day from 6 months of data
            first_t = None
            last_t = None
            # Approximate: 130 trading days in 6 months
            tpd = r['trades'] / 130
            print(f'  {r["strategy"]:<25s} {r["symbol"]:<10s}: ~{tpd:.1f} trades/day ({r["trades"]} total)')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol', '-s')
    args = parser.parse_args()
    symbols = [args.symbol] if args.symbol else None
    main(symbols)
