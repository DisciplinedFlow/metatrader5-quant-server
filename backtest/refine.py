#!/usr/bin/env python3
"""
Refine top strategies with parameter sweeps and filters.
Pre-computes swings and indicators once per symbol for speed.
"""
import sys, time
sys.path.insert(0, '.')
import numpy as np
import pandas as pd
from engine import fetch_bars, backtest, report, SPREADS

# ---------------------------------------------------------------------------
# Fast pre-computation (done ONCE per DataFrame, not per bar)
# ---------------------------------------------------------------------------

def precompute(df, swing_lb=3):
    """Add all indicators and swing labels to df in-place. O(n) per indicator."""
    c = df['close']
    h = df['high']
    l = df['low']

    # EMAs
    df['ema50'] = c.ewm(span=50, adjust=False).mean()
    df['ema200'] = c.ewm(span=200, adjust=False).mean()

    # RSI (Wilder)
    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    df['rsi'] = 100 - 100 / (1 + gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean() /
                                  loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean().replace(0, np.nan))

    # Swing highs/lows (vectorized with rolling)
    df['swing_high'] = False
    df['swing_low'] = False
    df['swing_high_price'] = np.nan
    df['swing_low_price'] = np.nan

    for i in range(swing_lb, len(df) - swing_lb):
        win_h = h.iloc[i-swing_lb:i+swing_lb+1]
        win_l = l.iloc[i-swing_lb:i+swing_lb+1]
        if h.iloc[i] == win_h.max() and h.iloc[i] > h.iloc[i-1]:
            df.iloc[i, df.columns.get_loc('swing_high')] = True
            df.iloc[i, df.columns.get_loc('swing_high_price')] = h.iloc[i]
        if l.iloc[i] == win_l.min() and l.iloc[i] < l.iloc[i-1]:
            df.iloc[i, df.columns.get_loc('swing_low')] = True
            df.iloc[i, df.columns.get_loc('swing_low_price')] = l.iloc[i]

    # Forward-fill last swing prices for quick lookup
    df['last_sh'] = df['swing_high_price'].ffill()
    df['last_sl'] = df['swing_low_price'].ffill()

    # Session info
    df['hour'] = df['time'].dt.hour
    df['date'] = df['time'].dt.date

    # Body size
    df['body'] = abs(df['close'] - df['open'])
    df['avg_body'] = df['body'].rolling(20).mean()

    # Trend: bullish if ema50 > ema200
    df['trend_bull'] = df['ema50'] > df['ema200']

    return df


def get_asia_range(df, i, asia_start=0, asia_end=5):
    """Get Asia session high/low for the same day as bar i."""
    today = df['date'].iloc[i]
    mask = (df['date'] == today) & (df['hour'] >= asia_start) & (df['hour'] < asia_end)
    asia = df.loc[mask]
    if len(asia) < 2:
        return None, None
    return asia['high'].max(), asia['low'].min()


def recent_swings(df, i, lookback=50, count=3):
    """Get recent confirmed swing highs and lows (index, price) up to bar i-3."""
    end = i - 3  # confirmed swings only (need lookback buffer)
    start = max(0, end - lookback)
    chunk = df.iloc[start:end+1]
    highs = [(idx, row['high']) for idx, row in chunk.iterrows() if row['swing_high']]
    lows = [(idx, row['low']) for idx, row in chunk.iterrows() if row['swing_low']]
    return highs[-count:], lows[-count:]


# ---------------------------------------------------------------------------
# REFINED TJR ASIA SWEEP
# ---------------------------------------------------------------------------

def tjr_v2(df, i, asia_start=0, asia_end=5, trade_start=7, trade_end=16,
           require_trend=False, require_fvg=False):
    """Refined TJR: Asia sweep + MSS + optional trend/FVG filters."""
    if i < 50:
        return None
    hour = df['hour'].iloc[i]
    if hour < trade_start or hour >= trade_end:
        return None

    asia_high, asia_low = get_asia_range(df, i, asia_start, asia_end)
    if asia_high is None:
        return None

    close = df['close'].iloc[i]
    prev_close = df['close'].iloc[i-1]
    atr = df['atr'].iloc[i]
    if pd.isna(atr) or atr <= 0:
        return None

    # Trend filter
    if require_trend:
        trend_bull = df['trend_bull'].iloc[i]

    today = df['date'].iloc[i]
    session_mask = (df['date'] == today) & (df['hour'] >= trade_start) & (df.index <= i)
    session_bars = df.loc[session_mask]
    if len(session_bars) < 2:
        return None

    # --- BULLISH: sweep Asia low, reverse up ---
    if session_bars['low'].min() < asia_low:
        if require_trend and not df['trend_bull'].iloc[i]:
            pass  # skip if counter-trend
        else:
            # MSS: closing above recent swing high
            sh_list, _ = recent_swings(df, i)
            if sh_list:
                last_sh_price = sh_list[-1][1]
                if prev_close <= last_sh_price and close > last_sh_price:
                    if close > asia_low:  # recovered
                        # FVG filter
                        if require_fvg:
                            has_fvg = _check_bullish_fvg(df, i)
                            if not has_fvg:
                                return None
                        return 'BUY'

    # --- BEARISH: sweep Asia high, reverse down ---
    if session_bars['high'].max() > asia_high:
        if require_trend and df['trend_bull'].iloc[i]:
            pass
        else:
            _, sl_list = recent_swings(df, i)
            if sl_list:
                last_sl_price = sl_list[-1][1]
                if prev_close >= last_sl_price and close < last_sl_price:
                    if close < asia_high:
                        if require_fvg:
                            has_fvg = _check_bearish_fvg(df, i)
                            if not has_fvg:
                                return None
                        return 'SELL'
    return None


def _check_bullish_fvg(df, i):
    for j in range(max(0, i-5), i+1):
        if j < 2:
            continue
        if df['high'].iloc[j-2] < df['low'].iloc[j]:
            return True
        # Relaxed: displacement candle + partial gap
        if (df['close'].iloc[j-1] > df['open'].iloc[j-1] and
            df['body'].iloc[j-1] > df['avg_body'].iloc[j-1] * 1.5):
            gap = df['low'].iloc[j] - df['high'].iloc[j-2]
            if gap > -df['atr'].iloc[j] * 0.2:
                return True
    return False


def _check_bearish_fvg(df, i):
    for j in range(max(0, i-5), i+1):
        if j < 2:
            continue
        if df['low'].iloc[j-2] > df['high'].iloc[j]:
            return True
        if (df['close'].iloc[j-1] < df['open'].iloc[j-1] and
            df['body'].iloc[j-1] > df['avg_body'].iloc[j-1] * 1.5):
            gap = df['low'].iloc[j-2] - df['high'].iloc[j]
            if gap > -df['atr'].iloc[j] * 0.2:
                return True
    return False


# ---------------------------------------------------------------------------
# REFINED ICC
# ---------------------------------------------------------------------------

def icc_v2(df, i, require_session=False, session_hours=None, require_trend=False):
    """Refined ICC: Indication-Correction-Continuation with optional filters."""
    if i < 50:
        return None

    if require_session and session_hours:
        hour = df['hour'].iloc[i]
        if not any(s <= hour < e for s, e in session_hours):
            return None

    close = df['close'].iloc[i]
    sh_list, sl_list = recent_swings(df, i, lookback=80, count=4)
    if len(sh_list) < 2 or len(sl_list) < 2:
        return None

    # --- BULLISH ICC ---
    last_sh_idx, last_sh_price = sh_list[-1]
    prev_sh_idx, prev_sh_price = sh_list[-2]
    last_sl_idx, last_sl_price = sl_list[-1]

    if last_sh_price > prev_sh_price:  # HH = bullish indication
        if last_sl_idx > prev_sh_idx:  # correction happened after prev structure
            retrace = last_sh_price - last_sl_price
            if retrace > 0:
                fib_38 = last_sh_price - retrace * 0.618
                fib_62 = last_sh_price - retrace * 0.382
                # Price was in correction zone, now breaking out
                if (df['low'].iloc[i-1] <= fib_62 and
                    close > df['high'].iloc[i-1] and
                    close > fib_62):
                    if require_trend and not df['trend_bull'].iloc[i]:
                        return None
                    return 'BUY'

    # --- BEARISH ICC ---
    last_sl_idx2, last_sl_price2 = sl_list[-1]
    prev_sl_idx2, prev_sl_price2 = sl_list[-2]
    last_sh_idx2, last_sh_price2 = sh_list[-1]

    if last_sl_price2 < prev_sl_price2:  # LL = bearish indication
        if last_sh_idx2 > prev_sl_idx2:
            retrace = last_sh_price2 - last_sl_price2
            if retrace > 0:
                fib_38 = last_sl_price2 + retrace * 0.618
                fib_62 = last_sl_price2 + retrace * 0.382
                if (df['high'].iloc[i-1] >= fib_62 and
                    close < df['low'].iloc[i-1] and
                    close < fib_62):
                    if require_trend and df['trend_bull'].iloc[i]:
                        return None
                    return 'SELL'
    return None


# ---------------------------------------------------------------------------
# REFINED LONDON SWEEP
# ---------------------------------------------------------------------------

def london_v2(df, i, pre_start=4, pre_end=7, trade_start=7, trade_end=12,
              require_trend=False, min_range_atr=0.5):
    """London sweep reversal with range quality filter."""
    if i < 30:
        return None
    hour = df['hour'].iloc[i]
    if hour < trade_start or hour >= trade_end:
        return None

    today = df['date'].iloc[i]
    pre_mask = (df['date'] == today) & (df['hour'] >= pre_start) & (df['hour'] < pre_end)
    pre_bars = df.loc[pre_mask]
    if len(pre_bars) < 2:
        return None

    range_high = pre_bars['high'].max()
    range_low = pre_bars['low'].min()
    range_size = range_high - range_low
    atr = df['atr'].iloc[i]

    # Range quality: must be at least min_range_atr * ATR (not too tight)
    if pd.isna(atr) or range_size < min_range_atr * atr:
        return None

    close = df['close'].iloc[i]
    prev_close = df['close'].iloc[i-1]

    london_mask = (df['date'] == today) & (df['hour'] >= trade_start) & (df.index <= i)
    london_bars = df.loc[london_mask]
    if len(london_bars) < 2:
        return None

    swept_low = london_bars['low'].min() < range_low
    swept_high = london_bars['high'].max() > range_high

    # BULLISH: swept low, reversing
    if swept_low and not swept_high:
        if require_trend and not df['trend_bull'].iloc[i]:
            return None
        if prev_close < range_low and close > range_low:
            return 'BUY'
        if df['low'].iloc[i] < range_low and close > range_low and close > df['open'].iloc[i]:
            return 'BUY'

    # BEARISH: swept high, reversing
    if swept_high and not swept_low:
        if require_trend and df['trend_bull'].iloc[i]:
            return None
        if prev_close > range_high and close < range_high:
            return 'SELL'
        if df['high'].iloc[i] > range_high and close < range_high and close < df['open'].iloc[i]:
            return 'SELL'

    return None


# ---------------------------------------------------------------------------
# Run parameter sweep
# ---------------------------------------------------------------------------

def run_sweep():
    symbols = ['XAUUSD', 'GBPUSD', 'USDJPY', 'EURUSD', 'USDCAD', 'XAGUSD', 'AUDUSD']
    results = []

    for sym in symbols:
        t0 = time.time()
        print(f'Fetching {sym}...', flush=True)
        df = fetch_bars(sym, 'H1', start='2025-06-01T00:00:00')
        df = precompute(df)
        days = (df['time'].iloc[-1] - df['time'].iloc[0]).days
        print(f'  {len(df)} bars, {days}d, precomputed in {time.time()-t0:.1f}s', flush=True)

        configs = [
            # TJR variants
            ('TJR base',       lambda d,i: tjr_v2(d,i), 1.8, 3.6),
            ('TJR+trend',      lambda d,i: tjr_v2(d,i, require_trend=True), 1.8, 3.6),
            ('TJR+FVG',        lambda d,i: tjr_v2(d,i, require_fvg=True), 1.8, 3.6),
            ('TJR+trend+FVG',  lambda d,i: tjr_v2(d,i, require_trend=True, require_fvg=True), 1.8, 3.6),
            ('TJR wide asia',  lambda d,i: tjr_v2(d,i, asia_end=7), 1.8, 3.6),
            ('TJR NY only',    lambda d,i: tjr_v2(d,i, trade_start=13, trade_end=17), 1.8, 3.6),
            # ICC variants
            ('ICC base',       lambda d,i: icc_v2(d,i), 1.8, 3.6),
            ('ICC London',     lambda d,i: icc_v2(d,i, require_session=True, session_hours=[(7,17)]), 1.8, 3.6),
            ('ICC+trend',      lambda d,i: icc_v2(d,i, require_trend=True), 1.8, 3.6),
            ('ICC Lon+trend',  lambda d,i: icc_v2(d,i, require_session=True, session_hours=[(7,17)], require_trend=True), 1.8, 3.6),
            # London sweep variants
            ('LDN base',       lambda d,i: london_v2(d,i), 1.5, 3.0),
            ('LDN+trend',      lambda d,i: london_v2(d,i, require_trend=True), 1.5, 3.0),
            ('LDN tight rng',  lambda d,i: london_v2(d,i, min_range_atr=0.8), 1.5, 3.0),
            ('LDN wide win',   lambda d,i: london_v2(d,i, trade_end=15), 1.5, 3.0),
            # SL/TP variants on best strategies
            ('TJR SL1.5 TP3',  lambda d,i: tjr_v2(d,i), 1.5, 3.0),
            ('TJR SL2.0 TP4',  lambda d,i: tjr_v2(d,i), 2.0, 4.0),
            ('ICC SL1.5 TP3',  lambda d,i: icc_v2(d,i, require_session=True, session_hours=[(7,17)]), 1.5, 3.0),
        ]

        for name, fn, sl, tp in configs:
            t1 = time.time()
            trades = backtest(df, fn, sl_atr=sl, tp_atr=tp, symbol=sym, cooldown=3)
            closed = [t for t in trades if t['result'] in ('SL','TP')]
            elapsed = time.time() - t1
            if len(closed) < 8:
                continue
            wins = [t for t in closed if t['pnl'] > 0]
            losses = [t for t in closed if t['pnl'] <= 0]
            wr = len(wins) / len(closed) * 100
            gw = sum(t['pnl'] for t in wins)
            gl = abs(sum(t['pnl'] for t in losses))
            pf = gw / gl if gl > 0 else 99
            exp = sum(t['pnl']/t['sl_dist'] for t in closed if t['sl_dist']>0) / len(closed)
            total_r = sum(t['pnl']/t['sl_dist'] for t in closed if t['sl_dist']>0)
            # Max DD in R
            eq = [0.0]
            for t in closed:
                eq.append(eq[-1] + (t['pnl']/t['sl_dist'] if t['sl_dist']>0 else 0))
            peak = dd = 0
            for e in eq:
                peak = max(peak, e)
                dd = max(dd, peak - e)

            results.append({
                'name': name, 'sym': sym, 'n': len(closed), 'wr': wr,
                'pf': pf, 'exp': exp, 'tot': total_r, 'dd': dd, 'days': days,
            })

        print(f'  Done {sym} ({time.time()-t0:.0f}s)', flush=True)

    # Sort by WR then expectancy
    results.sort(key=lambda x: (-x['wr'], -x['exp']))

    print()
    print('=' * 105)
    print(f'  {"Strategy":<18s} {"Symbol":<8s} {"Days":>4s} {"Trades":>6s} {"WR%":>6s} {"PF":>6s} {"Exp(R)":>8s} {"Total":>7s} {"MaxDD":>6s} Verdict')
    print('-' * 105)
    for r in results[:40]:
        v = 'PASS' if r['wr']>=60 and r['exp']>0.1 else 'SOLID' if r['wr']>=50 and r['exp']>0.1 else 'MAYBE' if r['wr']>=40 and r['exp']>0 else 'FAIL'
        print(f'  {r["name"]:<18s} {r["sym"]:<8s} {r["days"]:>4d} {r["n"]:>6d} {r["wr"]:>5.1f}% {r["pf"]:>6.2f} {r["exp"]:>+7.3f} {r["tot"]:>+6.1f}R {r["dd"]:>5.1f}R {v}')
    print('=' * 105)

    # Winners
    solid = [r for r in results if r['wr'] >= 50 and r['exp'] > 0.1]
    maybe = [r for r in results if 40 <= r['wr'] < 50 and r['exp'] > 0 and r not in solid]
    passing = [r for r in results if r['wr'] >= 60 and r['exp'] > 0.1]
    print(f'\n  {len(passing)} PASS | {len(solid)} SOLID | {len(maybe)} MAYBE | {len(results)-len(passing)-len(solid)-len(maybe)} FAIL')
    for p in solid:
        print(f'    {p["name"]} — {p["sym"]} — {p["wr"]:.1f}% WR, PF={p["pf"]:.2f}, {p["exp"]:+.3f}R/trade, {p["n"]}t/{p["days"]}d')


if __name__ == '__main__':
    run_sweep()
