"""
Bollinger Band Mean Reversion Parameter Sweep
=============================================
Tests ALL combinations of BB params, RSI confirmation, ADX filter,
TP type (mid-BB dynamic vs fixed %), and SL across SOL/XAU/AVAX/DOGE.

Custom simulation loop handles dynamic BB middle-band TP target.
"""

from __future__ import annotations

import os
import itertools
import time
from multiprocessing import Pool, cpu_count
from typing import Optional, Tuple, Dict

import numpy as np
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

# ── Parameter grid ──────────────────────────────────────────
SYMBOLS = ['SOL', 'XAU', 'AVAX', 'DOGE']
TIMEFRAMES = ['5m', '15m', '1h']
BB_PERIODS = [14, 20, 30]
BB_STDS = [1.5, 2.0, 2.5, 3.0]
RSI_CONFIRMS = [
    None,           # No RSI filter
    (14, 30, 70),   # RSI(14) < 30 / > 70
    (14, 25, 75),   # RSI(14) < 25 / > 75
]
ADX_FILTERS = [
    None,   # No ADX filter
    25,     # ADX < 25 (ranging only)
    35,     # ADX < 35
]
TP_TYPES = ['mid_bb', 'fixed_1', 'fixed_2', 'fixed_3']  # mid_bb or fixed 1%/2%/3%
SL_PCTS = [0.015, 0.02, 0.03]

SLIPPAGE_PCT = 0.0005
FEE_PCT = 0.00028
LOOKBACK = 50  # min bars before first signal


# ── Indicator helpers ───────────────────────────────────────

def compute_bb(close: np.ndarray, period: int, std_mult: float):
    """Return (middle, upper, lower) BB arrays. NaN for first period-1 bars."""
    mid = np.full_like(close, np.nan)
    upper = np.full_like(close, np.nan)
    lower = np.full_like(close, np.nan)
    for i in range(period - 1, len(close)):
        window = close[i - period + 1:i + 1]
        m = np.mean(window)
        s = np.std(window, ddof=0)
        mid[i] = m
        upper[i] = m + std_mult * s
        lower[i] = m - std_mult * s
    return mid, upper, lower


def compute_rsi(close: np.ndarray, period: int):
    """Return RSI array. NaN for first period bars."""
    rsi = np.full_like(close, np.nan)
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    # Simple moving average for initial, then EMA-style
    if len(close) < period + 1:
        return rsi
    avg_gain = np.mean(gain[1:period + 1])
    avg_loss = np.mean(loss[1:period + 1])
    for i in range(period, len(close)):
        if i == period:
            ag, al = avg_gain, avg_loss
        else:
            ag = (avg_gain * (period - 1) + gain[i]) / period
            al = (avg_loss * (period - 1) + loss[i]) / period
        avg_gain, avg_loss = ag, al
        if al == 0:
            rsi[i] = 100.0
        else:
            rs = ag / al
            rsi[i] = 100.0 - 100.0 / (1.0 + rs)
    return rsi


def compute_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14):
    """Return ADX array. NaN for first ~2*period bars."""
    n = len(close)
    adx = np.full(n, np.nan)
    if n < period * 2 + 1:
        return adx

    tr = np.zeros(n)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)

    for i in range(1, n):
        h_l = high[i] - low[i]
        h_pc = abs(high[i] - close[i - 1])
        l_pc = abs(low[i] - close[i - 1])
        tr[i] = max(h_l, h_pc, l_pc)

        up = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        plus_dm[i] = up if up > down and up > 0 else 0.0
        minus_dm[i] = down if down > up and down > 0 else 0.0

    # Smoothed TR, +DM, -DM using Wilder's smoothing
    atr = np.zeros(n)
    s_plus = np.zeros(n)
    s_minus = np.zeros(n)

    atr[period] = np.sum(tr[1:period + 1])
    s_plus[period] = np.sum(plus_dm[1:period + 1])
    s_minus[period] = np.sum(minus_dm[1:period + 1])

    for i in range(period + 1, n):
        atr[i] = atr[i - 1] - atr[i - 1] / period + tr[i]
        s_plus[i] = s_plus[i - 1] - s_plus[i - 1] / period + plus_dm[i]
        s_minus[i] = s_minus[i - 1] - s_minus[i - 1] / period + minus_dm[i]

    # +DI, -DI, DX
    dx = np.zeros(n)
    for i in range(period, n):
        if atr[i] == 0:
            continue
        pdi = 100 * s_plus[i] / atr[i]
        mdi = 100 * s_minus[i] / atr[i]
        denom = pdi + mdi
        if denom > 0:
            dx[i] = 100 * abs(pdi - mdi) / denom

    # ADX = smoothed DX
    start = period * 2
    if start < n:
        adx[start] = np.mean(dx[period:start + 1])
        for i in range(start + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period

    return adx


# ── Precompute all indicators for a dataset ─────────────────

def precompute_indicators(df: pd.DataFrame) -> dict:
    """Precompute BB/RSI/ADX for all param combos on one dataset."""
    close = df['close'].values.astype(np.float64)
    high = df['high'].values.astype(np.float64)
    low = df['low'].values.astype(np.float64)

    cache = {}
    # BB for all period/std combos
    for period in BB_PERIODS:
        for std in BB_STDS:
            mid, upper, lower = compute_bb(close, period, std)
            cache[('bb', period, std)] = (mid, upper, lower)

    # RSI
    for rsi_conf in RSI_CONFIRMS:
        if rsi_conf is not None:
            rsi_period = rsi_conf[0]
            if ('rsi', rsi_period) not in cache:
                cache[('rsi', rsi_period)] = compute_rsi(close, rsi_period)

    # ADX(14)
    cache[('adx', 14)] = compute_adx(high, low, close, 14)

    return cache


# ── Core simulation loop ────────────────────────────────────

def simulate(
    df: pd.DataFrame,
    cache: dict,
    bb_period: int,
    bb_std: float,
    rsi_confirm: tuple | None,
    adx_filter: int | None,
    tp_type: str,
    sl_pct: float,
) -> dict:
    """Run BB mean reversion backtest. Returns stats dict."""
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    opn = df['open'].values
    n = len(close)

    mid_bb, upper_bb, lower_bb = cache[('bb', bb_period, bb_std)]
    rsi = cache.get(('rsi', rsi_confirm[0])) if rsi_confirm else None
    adx = cache[('adx', 14)]

    # Fixed TP percentages
    tp_pct_map = {'fixed_1': 0.01, 'fixed_2': 0.02, 'fixed_3': 0.03}

    trades = []
    in_position = False
    position_side = 0
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    pending_signal = 0
    pending_tp_pct = 0.0

    min_start = max(LOOKBACK, bb_period, 30)  # ensure enough data for all indicators

    for i in range(min_start, n):
        # ── Handle pending entry at this bar's open ──
        if pending_signal != 0 and not in_position:
            raw_open = opn[i]
            if pending_signal == 1:
                entry_price = raw_open * (1 + SLIPPAGE_PCT)
                sl_price = entry_price * (1 - sl_pct)
                if tp_type == 'mid_bb':
                    # TP = distance to middle BB at signal bar
                    tp_price = entry_price + pending_tp_pct  # pending_tp_pct holds absolute distance
                else:
                    tp_price = entry_price * (1 + tp_pct_map[tp_type])
            else:
                entry_price = raw_open * (1 - SLIPPAGE_PCT)
                sl_price = entry_price * (1 + sl_pct)
                if tp_type == 'mid_bb':
                    tp_price = entry_price - pending_tp_pct
                else:
                    tp_price = entry_price * (1 - tp_pct_map[tp_type])

            in_position = True
            position_side = pending_signal
            pending_signal = 0

        # ── Check SL/TP ──
        if in_position:
            hit_sl = False
            hit_tp = False

            if position_side == 1:
                if low[i] <= sl_price:
                    hit_sl = True
                if high[i] >= tp_price:
                    hit_tp = True
            else:
                if high[i] >= sl_price:
                    hit_sl = True
                if low[i] <= tp_price:
                    hit_tp = True

            if hit_sl:
                if position_side == 1:
                    exit_price = sl_price * (1 - SLIPPAGE_PCT)
                    pnl = (exit_price - entry_price) / entry_price
                else:
                    exit_price = sl_price * (1 + SLIPPAGE_PCT)
                    pnl = (entry_price - exit_price) / entry_price
                trades.append(pnl - 2 * FEE_PCT)
                in_position = False
                position_side = 0
                continue
            elif hit_tp:
                if position_side == 1:
                    exit_price = tp_price * (1 - SLIPPAGE_PCT)
                    pnl = (exit_price - entry_price) / entry_price
                else:
                    exit_price = tp_price * (1 + SLIPPAGE_PCT)
                    pnl = (entry_price - exit_price) / entry_price
                trades.append(pnl - 2 * FEE_PCT)
                in_position = False
                position_side = 0
                continue

        # ── Generate signal ──
        if not in_position:
            # Need valid BB values
            if np.isnan(mid_bb[i]) or np.isnan(upper_bb[i]) or np.isnan(lower_bb[i]):
                continue

            # ADX filter
            if adx_filter is not None:
                if np.isnan(adx[i]) or adx[i] >= adx_filter:
                    continue

            sig = 0
            # Price touches/crosses lower BB → BUY
            if close[i] <= lower_bb[i]:
                sig = 1
            # Price touches/crosses upper BB → SELL
            elif close[i] >= upper_bb[i]:
                sig = -1

            if sig == 0:
                continue

            # RSI confirmation
            if rsi_confirm is not None:
                rsi_period, oversold, overbought = rsi_confirm
                if rsi is None or np.isnan(rsi[i]):
                    continue
                if sig == 1 and rsi[i] >= oversold:
                    continue  # RSI not oversold enough
                if sig == -1 and rsi[i] <= overbought:
                    continue  # RSI not overbought enough

            # Calculate dynamic TP distance for mid_bb
            if tp_type == 'mid_bb':
                if sig == 1:
                    dist = mid_bb[i] - close[i]
                else:
                    dist = close[i] - mid_bb[i]
                if dist <= 0:
                    continue  # no room for TP
                pending_tp_pct = dist  # absolute price distance
            else:
                pending_tp_pct = 0.0

            pending_signal = sig

    # ── Compute stats ──
    if not trades:
        return None

    trades_arr = np.array(trades)
    wins = trades_arr[trades_arr > 0]
    losses = trades_arr[trades_arr <= 0]
    total = len(trades_arr)
    n_wins = len(wins)
    n_losses = len(losses)
    wr = n_wins / total if total > 0 else 0
    total_pnl = float(np.sum(trades_arr))
    gross_wins = float(np.sum(wins)) if len(wins) > 0 else 0
    gross_losses = float(np.sum(losses)) if len(losses) > 0 else 0
    pf = gross_wins / abs(gross_losses) if gross_losses != 0 else (float('inf') if gross_wins > 0 else 0)

    return {
        'trades': total,
        'wins': n_wins,
        'losses': n_losses,
        'win_rate': wr,
        'total_pnl': total_pnl,
        'profit_factor': pf,
    }


# ── Worker function for multiprocessing ─────────────────────

def _load_and_cache(sym_tf: str) -> tuple:
    """Load data and precompute indicators for a symbol/timeframe combo."""
    sym, tf = sym_tf.split('_', 1)
    csv_path = os.path.join(DATA_DIR, f'{sym}_{tf}.csv')
    pq_path = os.path.join(DATA_DIR, f'{sym}_{tf}.parquet')
    if os.path.exists(pq_path):
        df = pd.read_parquet(pq_path)
    elif os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
    else:
        return sym_tf, None, None
    for col in ('open', 'high', 'low', 'close', 'volume'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.sort_values('timestamp').reset_index(drop=True)
    cache = precompute_indicators(df)
    return sym_tf, df, cache


def run_combo(args):
    """Run a single parameter combo. Returns result row dict or None."""
    sym, tf, bb_period, bb_std, rsi_confirm, adx_filter, tp_type, sl_pct, df, cache = args

    result = simulate(df, cache, bb_period, bb_std, rsi_confirm, adx_filter, tp_type, sl_pct)
    if result is None:
        return None

    rsi_label = 'None'
    if rsi_confirm is not None:
        rsi_label = f'RSI({rsi_confirm[0]})<{rsi_confirm[1]}/>{rsi_confirm[2]}'

    adx_label = 'None' if adx_filter is None else f'ADX<{adx_filter}'

    tp_label = tp_type if tp_type == 'mid_bb' else f'{tp_type.split("_")[1]}%'

    return {
        'symbol': sym,
        'timeframe': tf,
        'bb_period': bb_period,
        'bb_std': bb_std,
        'rsi_confirm': rsi_label,
        'adx_filter': adx_label,
        'tp_type': tp_label,
        'sl_pct': f'{sl_pct * 100:.1f}%',
        'trades': result['trades'],
        'win_rate': result['win_rate'],
        'total_pnl': result['total_pnl'],
        'profit_factor': result['profit_factor'],
    }


# ── Main sweep ──────────────────────────────────────────────

def main():
    t0 = time.time()

    # Step 1: Find all valid symbol/timeframe combos and precompute indicators
    print("Loading data and precomputing indicators...")
    datasets = {}
    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            key = f'{sym}_{tf}'
            csv_path = os.path.join(DATA_DIR, f'{sym}_{tf}.csv')
            pq_path = os.path.join(DATA_DIR, f'{sym}_{tf}.parquet')
            if os.path.exists(pq_path) or os.path.exists(csv_path):
                _, df, cache = _load_and_cache(key)
                if df is not None:
                    datasets[key] = (df, cache)
                    print(f"  {key}: {len(df)} bars")
            else:
                print(f"  {key}: SKIPPED (no data)")

    # Step 2: Build all parameter combos
    print("\nBuilding parameter grid...")
    combos = []
    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            key = f'{sym}_{tf}'
            if key not in datasets:
                continue
            df, cache = datasets[key]
            for bb_period, bb_std, rsi_confirm, adx_filter, tp_type, sl_pct in itertools.product(
                BB_PERIODS, BB_STDS, RSI_CONFIRMS, ADX_FILTERS, TP_TYPES, SL_PCTS
            ):
                combos.append((
                    sym, tf, bb_period, bb_std, rsi_confirm, adx_filter,
                    tp_type, sl_pct, df, cache
                ))

    total_combos = len(combos)
    print(f"Total combos: {total_combos:,}")

    # Step 3: Run all combos (use multiprocessing for speed)
    print("Running sweep...")
    n_workers = max(1, cpu_count() - 1)
    results = []

    # Use multiprocessing pool
    with Pool(n_workers) as pool:
        for i, res in enumerate(pool.imap_unordered(run_combo, combos, chunksize=64)):
            if res is not None:
                results.append(res)
            if (i + 1) % 2000 == 0:
                print(f"  {i + 1:,}/{total_combos:,} done ({len(results):,} with trades)")

    elapsed = time.time() - t0
    print(f"\nCompleted {total_combos:,} combos in {elapsed:.1f}s")
    print(f"Combos with trades: {len(results):,}")

    if not results:
        print("No results with trades found!")
        return

    # Step 4: Save full results
    df_results = pd.DataFrame(results)
    out_path = os.path.join(os.path.dirname(__file__), 'results_bb_sweep.csv')
    df_results.to_csv(out_path, index=False)
    print(f"\nFull results saved to: {out_path}")

    # Step 5: Filter and display top 20
    filtered = df_results[
        (df_results['trades'] >= 15) &
        (df_results['win_rate'] > 0.45) &
        (df_results['profit_factor'] > 1.2)
    ].copy()
    filtered = filtered.sort_values('profit_factor', ascending=False).head(20)

    if filtered.empty:
        print("\nNo combos met filter criteria (trades>=15, WR>45%, PF>1.2)")
        print("\nRelaxed top 20 by PF (trades >= 5):")
        relaxed = df_results[df_results['trades'] >= 5].copy()
        relaxed = relaxed.sort_values('profit_factor', ascending=False).head(20)
        print_results_table(relaxed)
    else:
        print(f"\n{'='*120}")
        print(f"TOP {len(filtered)} BB MEAN REVERSION STRATEGIES (trades>=15, WR>45%, PF>1.2)")
        print(f"{'='*120}")
        print_results_table(filtered)


def print_results_table(df: pd.DataFrame):
    """Pretty-print results dataframe."""
    if df.empty:
        print("  (no results)")
        return

    fmt = "{:<6} {:<4} {:<4} {:<5} {:<18} {:<8} {:<7} {:<5} {:>6} {:>7} {:>10} {:>7}"
    header = fmt.format(
        'SYM', 'TF', 'BBP', 'BBSD', 'RSI', 'ADX', 'TP', 'SL',
        'TRADES', 'WR', 'PnL%', 'PF'
    )
    print(header)
    print('-' * len(header))

    for _, row in df.iterrows():
        pf_str = f"{row['profit_factor']:.2f}" if row['profit_factor'] != float('inf') else 'INF'
        print(fmt.format(
            row['symbol'],
            row['timeframe'],
            str(row['bb_period']),
            f"{row['bb_std']:.1f}",
            row['rsi_confirm'],
            row['adx_filter'],
            row['tp_type'],
            row['sl_pct'],
            str(row['trades']),
            f"{row['win_rate']:.1%}",
            f"{row['total_pnl']:.4f}",
            pf_str,
        ))


if __name__ == '__main__':
    main()
