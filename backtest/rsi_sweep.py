"""
RSI mean-reversion parameter sweep — optimized with pre-computed indicators.
Pre-computes RSI for all periods and EMA(50) once per dataset, then runs
vectorized signal generation + engine simulation for each param combo.
"""

from __future__ import annotations

import os
import sys
import time
import itertools
import pandas as pd
import numpy as np

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

SYMBOLS = ['SOL', 'XAU', 'AVAX', 'DOGE']
TIMEFRAMES = ['5m', '15m', '1h']
RSI_PERIODS = [2, 3, 5, 7, 14]
OVERSOLD = [10, 15, 20, 25, 30]
OVERBOUGHT = [70, 75, 80, 85, 90]
EMA_FILTER_OPTIONS = [False, True]
SL_TP = [(0.01, 0.02), (0.015, 0.03), (0.02, 0.04), (0.03, 0.06)]

SLIPPAGE_PCT = 0.0005
FEE_PCT = 0.00028
LOOKBACK = 50


def compute_rsi(close: np.ndarray, period: int) -> np.ndarray:
    """Compute RSI using SMA method (matching engine_v2's rolling mean approach)."""
    delta = np.diff(close, prepend=close[0])
    gain = np.maximum(delta, 0.0)
    loss = np.maximum(-delta, 0.0)

    n = len(close)
    rsi = np.full(n, np.nan)

    for i in range(period, n):
        avg_gain = np.mean(gain[i - period + 1:i + 1])
        avg_loss = np.mean(loss[i - period + 1:i + 1])
        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))

    return rsi


def compute_ema(close: np.ndarray, span: int) -> np.ndarray:
    """Compute EMA matching pandas ewm(span=N, adjust=False)."""
    alpha = 2.0 / (span + 1.0)
    ema = np.empty_like(close)
    ema[0] = close[0]
    for i in range(1, len(close)):
        ema[i] = alpha * close[i] + (1 - alpha) * ema[i - 1]
    return ema


def simulate_trades(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    timestamps: np.ndarray,
    signals: np.ndarray,  # +1/-1/0 per bar, signal generated AT bar, entry on NEXT bar's open
    sl_pct: float,
    tp_pct: float,
) -> dict:
    """Fast trade simulation matching engine_v2 logic."""
    n = len(opens)
    trades = []
    in_position = False
    pending_signal = 0
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    entry_time = None
    position_side = 0

    for i in range(LOOKBACK, n):
        # Handle pending entry at this bar's open
        if pending_signal != 0 and not in_position:
            raw_open = opens[i]
            if pending_signal == 1:
                entry_price = raw_open * (1 + SLIPPAGE_PCT)
                sl_price = entry_price * (1 - sl_pct)
                tp_price = entry_price * (1 + tp_pct)
            else:
                entry_price = raw_open * (1 - SLIPPAGE_PCT)
                sl_price = entry_price * (1 + sl_pct)
                tp_price = entry_price * (1 - tp_pct)
            in_position = True
            position_side = pending_signal
            entry_time = timestamps[i]
            pending_signal = 0

        # Check SL/TP
        if in_position:
            hit_sl = False
            hit_tp = False

            if position_side == 1:
                if lows[i] <= sl_price:
                    hit_sl = True
                if highs[i] >= tp_price:
                    hit_tp = True
            else:
                if highs[i] >= sl_price:
                    hit_sl = True
                if lows[i] <= tp_price:
                    hit_tp = True

            if hit_sl:
                exit_price = sl_price
                close_reason = 'STOP_LOSS'
            elif hit_tp:
                exit_price = tp_price
                close_reason = 'TAKE_PROFIT'
            else:
                exit_price = None
                close_reason = None

            if exit_price is not None:
                if position_side == 1:
                    exit_adj = exit_price * (1 - SLIPPAGE_PCT)
                    pnl_gross = (exit_adj - entry_price) / entry_price
                else:
                    exit_adj = exit_price * (1 + SLIPPAGE_PCT)
                    pnl_gross = (entry_price - exit_adj) / entry_price

                pnl_net = pnl_gross - 2 * FEE_PCT

                trades.append((pnl_net, close_reason))
                in_position = False
                position_side = 0
                continue

        # Generate signal for next bar
        if not in_position:
            sig = signals[i]
            if sig == 1 or sig == -1:
                pending_signal = sig
            else:
                pending_signal = 0

    # Compute stats (only SL/TP trades)
    closed = [(pnl, reason) for pnl, reason in trades if reason in ('STOP_LOSS', 'TAKE_PROFIT')]
    total = len(closed)

    if total == 0:
        return {'trades': 0, 'wins': 0, 'losses': 0, 'win_rate': 0.0,
                'total_pnl': 0.0, 'profit_factor': 0.0}

    wins = [pnl for pnl, _ in closed if pnl > 0]
    losses = [pnl for pnl, _ in closed if pnl <= 0]

    gross_wins = sum(wins)
    gross_losses = sum(losses)
    total_pnl = gross_wins + gross_losses
    pf = gross_wins / abs(gross_losses) if gross_losses != 0 else float('inf')

    return {
        'trades': total,
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': len(wins) / total * 100,
        'total_pnl': total_pnl * 100,  # as pct
        'profit_factor': pf,
    }


def main():
    t0 = time.time()

    # Load and precompute all data
    datasets = {}
    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            for ext in ('parquet', 'csv'):
                path = os.path.join(DATA_DIR, f'{sym}_{tf}.{ext}')
                if os.path.exists(path):
                    if ext == 'parquet':
                        df = pd.read_parquet(path)
                    else:
                        df = pd.read_csv(path)
                    df = df.sort_values('timestamp').reset_index(drop=True)
                    for col in ('open', 'high', 'low', 'close', 'volume'):
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                    close = df['close'].values.astype(np.float64)

                    # Pre-compute RSI for all periods
                    rsi_data = {}
                    for period in RSI_PERIODS:
                        rsi_data[period] = compute_rsi(close, period)

                    # Pre-compute EMA(50)
                    ema50 = compute_ema(close, 50)

                    datasets[(sym, tf)] = {
                        'opens': df['open'].values.astype(np.float64),
                        'highs': df['high'].values.astype(np.float64),
                        'lows': df['low'].values.astype(np.float64),
                        'closes': close,
                        'timestamps': df['timestamp'].values,
                        'rsi': rsi_data,
                        'ema50': ema50,
                        'n': len(df),
                    }
                    print(f"  Loaded {sym}_{tf}: {len(df)} candles")
                    break

    print(f"Data loaded in {time.time() - t0:.1f}s")

    # Build combos
    combos = []
    for sym, tf, rsi_p, os_thresh, ob_thresh, ema, (sl, tp) in itertools.product(
        SYMBOLS, TIMEFRAMES, RSI_PERIODS, OVERSOLD, OVERBOUGHT, EMA_FILTER_OPTIONS, SL_TP
    ):
        if os_thresh >= ob_thresh:
            continue
        if (sym, tf) not in datasets:
            continue
        combos.append((sym, tf, rsi_p, os_thresh, ob_thresh, ema, sl, tp))

    total = len(combos)
    print(f"\nRunning {total} parameter combinations...")

    results = []
    last_report = 0

    for idx, (sym, tf, rsi_p, os_thresh, ob_thresh, ema, sl, tp) in enumerate(combos):
        ds = datasets[(sym, tf)]
        rsi_arr = ds['rsi'][rsi_p]
        ema50 = ds['ema50']
        closes = ds['closes']
        n = ds['n']

        # Build signal array
        signals = np.zeros(n, dtype=np.int8)
        for i in range(LOOKBACK, n):
            rsi_val = rsi_arr[i]
            if np.isnan(rsi_val):
                continue
            if rsi_val <= os_thresh:
                raw = 1
            elif rsi_val >= ob_thresh:
                raw = -1
            else:
                continue

            if ema:
                if raw == 1 and closes[i] <= ema50[i]:
                    continue
                if raw == -1 and closes[i] >= ema50[i]:
                    continue

            signals[i] = raw

        # Run simulation
        res = simulate_trades(
            ds['opens'], ds['highs'], ds['lows'], ds['closes'], ds['timestamps'],
            signals, sl, tp,
        )

        results.append({
            'symbol': sym,
            'timeframe': tf,
            'rsi_period': rsi_p,
            'oversold': os_thresh,
            'overbought': ob_thresh,
            'ema_filter': ema,
            'sl_pct': sl,
            'tp_pct': tp,
            'trades': res['trades'],
            'wins': res['wins'],
            'losses': res['losses'],
            'win_rate': round(res['win_rate'], 2),
            'total_pnl': round(res['total_pnl'], 4),
            'profit_factor': round(res['profit_factor'], 4),
        })

        if (idx + 1) - last_report >= 2000 or idx + 1 == total:
            elapsed = time.time() - t0
            rate = (idx + 1) / elapsed
            eta = (total - idx - 1) / rate if rate > 0 else 0
            print(f"  [{idx+1}/{total}] {elapsed:.0f}s elapsed, {rate:.0f}/s, ETA {eta:.0f}s")
            last_report = idx + 1

    # Save full results
    df_results = pd.DataFrame(results)
    df_results = df_results.sort_values('profit_factor', ascending=False)
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results_rsi_sweep.csv')
    df_results.to_csv(output_path, index=False)
    print(f"\nFull results saved to {output_path} ({len(df_results)} rows)")

    # Filter and display top 20
    filtered = df_results[
        (df_results['trades'] >= 20) &
        (df_results['win_rate'] > 45) &
        (df_results['profit_factor'] > 1.2)
    ].head(20)

    if filtered.empty:
        print("\nNo combinations met the filter criteria (trades>=20, WR>45%, PF>1.2)")
        fallback = df_results[df_results['trades'] >= 10].head(20)
        if not fallback.empty:
            print("\nTop 20 by profit_factor (trades >= 10, relaxed filter):")
            print(fallback.to_string(index=False))
        else:
            fallback2 = df_results[df_results['trades'] >= 5].head(20)
            if not fallback2.empty:
                print("\nTop 20 by profit_factor (trades >= 5, very relaxed filter):")
                print(fallback2.to_string(index=False))
    else:
        print(f"\n{'='*130}")
        print(f"TOP {len(filtered)} COMBINATIONS (trades>=20, WR>45%, PF>1.2) sorted by profit_factor:")
        print(f"{'='*130}")
        print(filtered.to_string(index=False))

    # Summary stats
    has_trades = df_results[df_results['trades'] > 0]
    print(f"\n{'='*80}")
    print("SWEEP SUMMARY:")
    print(f"  Total combos tested: {total}")
    print(f"  Combos with > 0 trades: {len(has_trades)}")
    print(f"  Combos with >= 20 trades: {len(df_results[df_results['trades'] >= 20])}")
    print(f"  Combos with WR > 45%: {len(df_results[df_results['win_rate'] > 45])}")
    print(f"  Combos with PF > 1.2: {len(df_results[df_results['profit_factor'] > 1.2])}")
    all_criteria = df_results[
        (df_results['trades'] >= 20) &
        (df_results['win_rate'] > 45) &
        (df_results['profit_factor'] > 1.2)
    ]
    print(f"  Combos meeting ALL criteria: {len(all_criteria)}")
    elapsed = time.time() - t0
    print(f"  Total runtime: {elapsed:.1f}s")


if __name__ == '__main__':
    main()
