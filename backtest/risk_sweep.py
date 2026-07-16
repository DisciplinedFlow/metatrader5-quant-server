"""
Risk management parameter sweep — SL/TP ratios, time-based exits, trailing stops.
Uses EMA 8/21 crossover as baseline signal across SOL, XAU, AVAX, DOGE.
"""

import os
import sys
import itertools
import numpy as np
import pandas as pd
from typing import Callable, Optional, List, Dict

# ── Data loading ──────────────────────────────────────────

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

SLIPPAGE_PCT = 0.0005
FEE_PCT = 0.00028
LOOKBACK = 50


def load_candles(symbol: str, timeframe: str) -> pd.DataFrame:
    csv_path = os.path.join(DATA_DIR, f'{symbol}_{timeframe}.csv')
    pq_path = os.path.join(DATA_DIR, f'{symbol}_{timeframe}.parquet')
    if os.path.exists(pq_path):
        df = pd.read_parquet(pq_path)
    elif os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
    else:
        raise FileNotFoundError(f"No data for {symbol}_{timeframe}")
    for col in ('open', 'high', 'low', 'close', 'volume'):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df.sort_values('timestamp').reset_index(drop=True)


# ── Signal function ───────────────────────────────────────

def ema_crossover(df: pd.DataFrame) -> int:
    if len(df) < 22:
        return 0
    close = df['close']
    ema_fast = close.ewm(span=8, adjust=False).mean()
    ema_slow = close.ewm(span=21, adjust=False).mean()
    if ema_fast.iloc[-2] <= ema_slow.iloc[-2] and ema_fast.iloc[-1] > ema_slow.iloc[-1]:
        return 1
    if ema_fast.iloc[-2] >= ema_slow.iloc[-2] and ema_fast.iloc[-1] < ema_slow.iloc[-1]:
        return -1
    return 0


# ── Core simulation (supports SL/TP, time exits, trailing stops) ──

def simulate(
    df: pd.DataFrame,
    signal_fn: Callable,
    sl_pct: float,
    tp_pct: Optional[float] = None,
    max_hold: Optional[int] = None,
    trail_activation: Optional[float] = None,
    trail_distance: Optional[float] = None,
) -> List[Dict]:
    """Run backtest returning list of trade dicts."""
    trades = []
    n = len(df)
    if n <= LOOKBACK:
        return trades

    in_position = False
    side = 0
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    entry_time = None
    entry_idx = 0
    peak_price = 0.0       # for trailing stop
    trail_active = False
    trail_sl = 0.0
    pending = 0

    for i in range(LOOKBACK, n):
        bar = df.iloc[i]

        # ── Enter on this bar's open if pending ──
        if pending != 0 and not in_position:
            raw_open = bar['open']
            if pending == 1:
                entry_price = raw_open * (1 + SLIPPAGE_PCT)
                sl_price = entry_price * (1 - sl_pct)
                tp_price = entry_price * (1 + tp_pct) if tp_pct is not None else None
            else:
                entry_price = raw_open * (1 - SLIPPAGE_PCT)
                sl_price = entry_price * (1 + sl_pct)
                tp_price = entry_price * (1 - tp_pct) if tp_pct is not None else None

            in_position = True
            side = pending
            entry_time = bar['timestamp']
            entry_idx = i
            peak_price = entry_price
            trail_active = False
            trail_sl = 0.0
            pending = 0

        # ── Check exits ──
        if in_position:
            close_reason = None
            exit_price = None

            # Update peak for trailing
            if side == 1:
                if bar['high'] > peak_price:
                    peak_price = bar['high']
            else:
                if bar['low'] < peak_price:
                    peak_price = bar['low']

            # Trailing stop activation and level
            if trail_activation is not None and trail_distance is not None:
                if side == 1:
                    unrealized = (peak_price - entry_price) / entry_price
                    if unrealized >= trail_activation:
                        trail_active = True
                        new_trail_sl = peak_price * (1 - trail_distance)
                        trail_sl = max(trail_sl, new_trail_sl) if trail_sl > 0 else new_trail_sl
                else:
                    unrealized = (entry_price - peak_price) / entry_price
                    if unrealized >= trail_activation:
                        trail_active = True
                        new_trail_sl = peak_price * (1 + trail_distance)
                        trail_sl = min(trail_sl, new_trail_sl) if trail_sl > 0 else new_trail_sl

            # Check SL
            hit_sl = False
            if side == 1:
                if bar['low'] <= sl_price:
                    hit_sl = True
                    exit_price = sl_price
                # Check trailing SL (only if above fixed SL)
                if trail_active and bar['low'] <= trail_sl and trail_sl > sl_price:
                    hit_sl = True
                    exit_price = trail_sl
                    close_reason = 'TRAILING_STOP'
            else:
                if bar['high'] >= sl_price:
                    hit_sl = True
                    exit_price = sl_price
                if trail_active and bar['high'] >= trail_sl and trail_sl < sl_price:
                    hit_sl = True
                    exit_price = trail_sl
                    close_reason = 'TRAILING_STOP'

            if hit_sl and close_reason is None:
                close_reason = 'STOP_LOSS'

            # Check TP (only if no SL hit — conservative)
            if not hit_sl and tp_price is not None:
                if side == 1 and bar['high'] >= tp_price:
                    exit_price = tp_price
                    close_reason = 'TAKE_PROFIT'
                elif side == -1 and bar['low'] <= tp_price:
                    exit_price = tp_price
                    close_reason = 'TAKE_PROFIT'

            # Time-based exit (only if no SL/TP hit)
            if close_reason is None and max_hold is not None:
                candles_held = i - entry_idx
                if candles_held >= max_hold:
                    exit_price = bar['close']
                    close_reason = 'TIME_EXIT'

            if exit_price is not None:
                # Apply slippage to exit
                if side == 1:
                    exit_adj = exit_price * (1 - SLIPPAGE_PCT)
                    pnl_gross = (exit_adj - entry_price) / entry_price
                else:
                    exit_adj = exit_price * (1 + SLIPPAGE_PCT)
                    pnl_gross = (entry_price - exit_adj) / entry_price

                pnl_net = pnl_gross - 2 * FEE_PCT

                trades.append({
                    'entry_time': entry_time,
                    'exit_time': bar['timestamp'],
                    'side': 'LONG' if side == 1 else 'SHORT',
                    'entry_price': entry_price,
                    'exit_price': exit_adj,
                    'pnl_net': pnl_net,
                    'close_reason': close_reason,
                    'candles_held': i - entry_idx,
                })
                in_position = False
                side = 0
                continue

        # ── Generate signal ──
        if not in_position:
            window = df.iloc[i - LOOKBACK + 1:i + 1]
            sig = signal_fn(window)
            pending = sig if sig in (1, -1) else 0

    # Close open position at end
    if in_position:
        last = df.iloc[-1]
        if side == 1:
            exit_adj = last['close'] * (1 - SLIPPAGE_PCT)
            pnl_gross = (exit_adj - entry_price) / entry_price
        else:
            exit_adj = last['close'] * (1 + SLIPPAGE_PCT)
            pnl_gross = (entry_price - exit_adj) / entry_price
        pnl_net = pnl_gross - 2 * FEE_PCT
        trades.append({
            'entry_time': entry_time,
            'exit_time': last['timestamp'],
            'side': 'LONG' if side == 1 else 'SHORT',
            'entry_price': entry_price,
            'exit_price': exit_adj,
            'pnl_net': pnl_net,
            'close_reason': 'END_OF_DATA',
            'candles_held': len(df) - 1 - entry_idx,
        })

    return trades


def compute_stats(trades: List[Dict]) -> Dict:
    """Compute stats from trade list, excluding END_OF_DATA trades."""
    closed = [t for t in trades if t['close_reason'] != 'END_OF_DATA']
    if not closed:
        return {'total_trades': 0, 'win_rate': 0, 'total_pnl': 0, 'profit_factor': 0,
                'avg_win': 0, 'avg_loss': 0, 'max_dd': 0, 'sharpe': 0}

    wins = [t for t in closed if t['pnl_net'] > 0]
    losses = [t for t in closed if t['pnl_net'] <= 0]
    gross_w = sum(t['pnl_net'] for t in wins)
    gross_l = sum(t['pnl_net'] for t in losses)
    pf = gross_w / abs(gross_l) if gross_l != 0 else float('inf')

    cum = np.cumsum([t['pnl_net'] for t in closed])
    peak = np.maximum.accumulate(cum)
    max_dd = float(np.max(peak - cum)) if len(cum) > 0 else 0.0

    rets = np.array([t['pnl_net'] for t in closed])
    sharpe = float(np.mean(rets) / np.std(rets) * np.sqrt(252)) if len(rets) > 1 and np.std(rets) > 0 else 0.0

    return {
        'total_trades': len(closed),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': len(wins) / len(closed),
        'total_pnl': sum(t['pnl_net'] for t in closed),
        'avg_win': gross_w / len(wins) if wins else 0,
        'avg_loss': gross_l / len(losses) if losses else 0,
        'profit_factor': pf,
        'max_dd': max_dd,
        'sharpe': sharpe,
    }


# ── SWEEP 1: R:R Ratio ───────────────────────────────────

def sweep_rr():
    symbols = ['SOL', 'XAU', 'AVAX', 'DOGE']
    sl_pcts = [0.01, 0.015, 0.02, 0.03]
    rr_ratios = [1.0, 1.5, 2.0, 2.5, 3.0]
    timeframe = '1h'
    rows = []

    total = len(symbols) * len(sl_pcts) * len(rr_ratios)
    done = 0

    for sym in symbols:
        try:
            df = load_candles(sym, timeframe)
        except FileNotFoundError:
            print(f"  [SKIP] {sym}_{timeframe} — no data")
            done += len(sl_pcts) * len(rr_ratios)
            continue

        for sl, rr in itertools.product(sl_pcts, rr_ratios):
            tp = sl * rr
            trades = simulate(df, ema_crossover, sl_pct=sl, tp_pct=tp)
            stats = compute_stats(trades)
            done += 1

            rows.append({
                'sweep': 'RR',
                'symbol': sym,
                'timeframe': timeframe,
                'sl_pct': sl,
                'rr': rr,
                'tp_pct': tp,
                'max_hold': None,
                'trail_act': None,
                'trail_dist': None,
                **stats,
            })

            if done % 20 == 0:
                print(f"  R:R sweep: {done}/{total}")

    print(f"  R:R sweep complete: {len(rows)} combos")
    return rows


# ── SWEEP 2: Time-based exits ────────────────────────────

def sweep_time():
    symbols = ['SOL', 'XAU', 'AVAX', 'DOGE']
    timeframes = ['1h', '15m']
    max_holds = [5, 10, 20, 50, 100]
    sl_pct = 0.02
    tp_pct = 0.04
    rows = []

    total_combos = len(symbols) * len(timeframes) * len(max_holds)
    done = 0

    for sym in symbols:
        for tf in timeframes:
            try:
                df = load_candles(sym, tf)
            except FileNotFoundError:
                print(f"  [SKIP] {sym}_{tf} — no data")
                done += len(max_holds)
                continue

            for mh in max_holds:
                trades = simulate(df, ema_crossover, sl_pct=sl_pct, tp_pct=tp_pct, max_hold=mh)
                stats = compute_stats(trades)
                done += 1

                rows.append({
                    'sweep': 'TIME',
                    'symbol': sym,
                    'timeframe': tf,
                    'sl_pct': sl_pct,
                    'rr': tp_pct / sl_pct,
                    'tp_pct': tp_pct,
                    'max_hold': mh,
                    'trail_act': None,
                    'trail_dist': None,
                    **stats,
                })

    print(f"  Time sweep complete: {len(rows)} combos")
    return rows


# ── SWEEP 3: Trailing stops ──────────────────────────────

def sweep_trailing():
    symbols = ['SOL', 'XAU', 'AVAX', 'DOGE']
    timeframe = '1h'
    sl_pct = 0.02
    trail_activations = [0.01, 0.02, 0.03]
    trail_distances = [0.005, 0.01, 0.015, 0.02]
    rows = []

    total = len(symbols) * len(trail_activations) * len(trail_distances)
    done = 0

    for sym in symbols:
        try:
            df = load_candles(sym, timeframe)
        except FileNotFoundError:
            print(f"  [SKIP] {sym}_{timeframe} — no data")
            done += len(trail_activations) * len(trail_distances)
            continue

        for ta, td in itertools.product(trail_activations, trail_distances):
            trades = simulate(df, ema_crossover, sl_pct=sl_pct, tp_pct=None,
                              trail_activation=ta, trail_distance=td)
            stats = compute_stats(trades)
            done += 1

            rows.append({
                'sweep': 'TRAIL',
                'symbol': sym,
                'timeframe': timeframe,
                'sl_pct': sl_pct,
                'rr': None,
                'tp_pct': None,
                'max_hold': None,
                'trail_act': ta,
                'trail_dist': td,
                **stats,
            })

    print(f"  Trailing sweep complete: {len(rows)} combos")
    return rows


# ── Print top results ─────────────────────────────────────

def print_top(df_results: pd.DataFrame, sweep_name: str, n: int = 20):
    sub = df_results[df_results['sweep'] == sweep_name].copy()
    # Filter: trades >= 15, WR > 40%, PF > 1.1
    sub = sub[(sub['total_trades'] >= 15) & (sub['win_rate'] > 0.40) & (sub['profit_factor'] > 1.1)]
    sub = sub.sort_values('total_pnl', ascending=False).head(n)

    if sub.empty:
        print(f"\n{'='*80}")
        print(f"TOP {n} — {sweep_name} (no results met filter: trades>=15, WR>40%, PF>1.1)")
        print(f"{'='*80}")
        # Show best available
        fallback = df_results[df_results['sweep'] == sweep_name].copy()
        fallback = fallback[fallback['total_trades'] >= 5].sort_values('total_pnl', ascending=False).head(10)
        if not fallback.empty:
            print(f"  (Showing top 10 with relaxed filters: trades>=5)")
            _print_table(fallback, sweep_name)
        return

    print(f"\n{'='*80}")
    print(f"TOP {n} — {sweep_name} (trades>=15, WR>40%, PF>1.1)")
    print(f"{'='*80}")
    _print_table(sub, sweep_name)


def _print_table(sub: pd.DataFrame, sweep_name: str):
    if sweep_name == 'RR':
        cols = ['symbol', 'sl_pct', 'rr', 'tp_pct', 'total_trades', 'win_rate', 'total_pnl', 'profit_factor', 'max_dd', 'sharpe']
        header = f"{'Sym':<6} {'SL%':>5} {'R:R':>5} {'TP%':>6} {'#Trades':>7} {'WR':>6} {'PnL%':>8} {'PF':>6} {'MaxDD%':>7} {'Sharpe':>7}"
    elif sweep_name == 'TIME':
        cols = ['symbol', 'timeframe', 'max_hold', 'total_trades', 'win_rate', 'total_pnl', 'profit_factor', 'max_dd', 'sharpe']
        header = f"{'Sym':<6} {'TF':>4} {'Hold':>5} {'#Trades':>7} {'WR':>6} {'PnL%':>8} {'PF':>6} {'MaxDD%':>7} {'Sharpe':>7}"
    else:  # TRAIL
        cols = ['symbol', 'sl_pct', 'trail_act', 'trail_dist', 'total_trades', 'win_rate', 'total_pnl', 'profit_factor', 'max_dd', 'sharpe']
        header = f"{'Sym':<6} {'SL%':>5} {'TrAct%':>6} {'TrDst%':>6} {'#Trades':>7} {'WR':>6} {'PnL%':>8} {'PF':>6} {'MaxDD%':>7} {'Sharpe':>7}"

    print(header)
    print('-' * len(header))

    for _, row in sub.iterrows():
        if sweep_name == 'RR':
            print(f"{row['symbol']:<6} {row['sl_pct']*100:>5.1f} {row['rr']:>5.1f} {row['tp_pct']*100:>6.1f} "
                  f"{int(row['total_trades']):>7} {row['win_rate']*100:>5.1f}% {row['total_pnl']*100:>7.2f}% "
                  f"{row['profit_factor']:>6.2f} {row['max_dd']*100:>6.2f}% {row['sharpe']:>7.2f}")
        elif sweep_name == 'TIME':
            print(f"{row['symbol']:<6} {row['timeframe']:>4} {int(row['max_hold']):>5} "
                  f"{int(row['total_trades']):>7} {row['win_rate']*100:>5.1f}% {row['total_pnl']*100:>7.2f}% "
                  f"{row['profit_factor']:>6.2f} {row['max_dd']*100:>6.2f}% {row['sharpe']:>7.2f}")
        else:
            print(f"{row['symbol']:<6} {row['sl_pct']*100:>5.1f} {row['trail_act']*100:>6.1f} {row['trail_dist']*100:>6.1f} "
                  f"{int(row['total_trades']):>7} {row['win_rate']*100:>5.1f}% {row['total_pnl']*100:>7.2f}% "
                  f"{row['profit_factor']:>6.2f} {row['max_dd']*100:>6.2f}% {row['sharpe']:>7.2f}")


# ── Main ──────────────────────────────────────────────────

def main():
    print("=" * 80)
    print("RISK MANAGEMENT PARAMETER SWEEP")
    print("EMA 8/21 crossover | SOL, XAU, AVAX, DOGE")
    print("Slippage: 0.05% | Fees: 0.028% per leg")
    print("=" * 80)

    print("\n[1/3] R:R Ratio sweep (4 symbols × 4 SL × 5 R:R = 80 combos per symbol)...")
    rr_rows = sweep_rr()

    print("\n[2/3] Time-based exit sweep (4 symbols × 2 TFs × 5 holds = 40 combos)...")
    time_rows = sweep_time()

    print("\n[3/3] Trailing stop sweep (4 symbols × 3 activations × 4 distances = 48 combos)...")
    trail_rows = sweep_trailing()

    # Combine all results
    all_rows = rr_rows + time_rows + trail_rows
    df_all = pd.DataFrame(all_rows)

    # Print summaries
    print_top(df_all, 'RR', 20)
    print_top(df_all, 'TIME', 20)
    print_top(df_all, 'TRAIL', 20)

    # Summary statistics
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Total combos tested: {len(all_rows)}")
    for sweep in ['RR', 'TIME', 'TRAIL']:
        sub = df_all[df_all['sweep'] == sweep]
        profitable = sub[sub['total_pnl'] > 0]
        print(f"  {sweep}: {len(sub)} combos, {len(profitable)} profitable ({len(profitable)/len(sub)*100:.0f}%)" if len(sub) > 0 else f"  {sweep}: 0 combos")

    # Save to CSV
    out_path = os.path.join(os.path.dirname(__file__), 'results_risk_sweep.csv')
    df_all.to_csv(out_path, index=False)
    print(f"\nResults saved to {out_path}")
    print(f"Total rows: {len(df_all)}")


if __name__ == '__main__':
    main()
