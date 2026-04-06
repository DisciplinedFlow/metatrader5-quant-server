#!/usr/bin/env python3
"""
Backtest all CVD strategies across forex symbols.
Find CVD setups that hit 60%+ WR with positive expectancy.

Usage:
    python backtest/run_cvd.py
    python backtest/run_cvd.py --symbol XAUUSD
    python backtest/run_cvd.py --symbol XAUUSD --timeframe M15
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from engine import fetch_bars, backtest, report
from cvd_strategies import (
    compute_cvd,
    cvd_lack_of_participation,
    cvd_absorption,
    cvd_lop_trend,
    cvd_absorption_trend,
    cvd_lop_session_sweep,
    cvd_momentum,
    cvd_exhaustion,
    cvd_lop_structure,
)

# Symbols to test
SYMBOLS = ['XAUUSD', 'XAGUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'UKOUSDft', 'USOUSD']

# Timeframes to test
TIMEFRAMES = ['M15', 'H1']

# Strategy configs: (name, function, sl_atr, tp_atr, session_hours)
# We test each strategy with different R:R and session filters
STRATEGY_CONFIGS = [
    # Raw CVD strategies (no session filter)
    ('CVD LoP Raw',             cvd_lack_of_participation,  1.8, 3.6, None),
    ('CVD LoP 1:3',             cvd_lack_of_participation,  1.5, 4.5, None),
    ('CVD Absorption Raw',      cvd_absorption,             1.8, 3.6, None),
    ('CVD Absorption 1:3',      cvd_absorption,             1.5, 4.5, None),

    # Trend-filtered
    ('CVD LoP + EMA50',         cvd_lop_trend,              1.8, 3.6, None),
    ('CVD LoP + EMA50 1:3',     cvd_lop_trend,              1.5, 4.5, None),
    ('CVD Absorb + EMA50',      cvd_absorption_trend,       1.8, 3.6, None),
    ('CVD Absorb + EMA50 1:3',  cvd_absorption_trend,       1.5, 4.5, None),

    # Session-filtered (London + NY only)
    ('CVD LoP London',          cvd_lack_of_participation,  1.8, 3.6, [(7, 12)]),
    ('CVD LoP NY',              cvd_lack_of_participation,  1.8, 3.6, [(13, 17)]),
    ('CVD LoP London+NY',       cvd_lack_of_participation,  1.8, 3.6, [(7, 17)]),
    ('CVD Absorb London',       cvd_absorption,             1.8, 3.6, [(7, 12)]),
    ('CVD Absorb London+NY',    cvd_absorption,             1.8, 3.6, [(7, 17)]),

    # Session sweep combos
    ('CVD LoP + Sweep',         cvd_lop_session_sweep,      1.8, 3.6, None),
    ('CVD LoP + Sweep 1:3',     cvd_lop_session_sweep,      1.5, 4.5, None),

    # Momentum and exhaustion
    ('CVD Momentum',            cvd_momentum,               1.8, 3.6, None),
    ('CVD Momentum London+NY',  cvd_momentum,               1.8, 3.6, [(7, 17)]),
    ('CVD Exhaustion',          cvd_exhaustion,              1.5, 3.0, None),
    ('CVD Exhaustion London',   cvd_exhaustion,              1.5, 3.0, [(7, 12)]),

    # Structure-based
    ('CVD LoP + Structure',     cvd_lop_structure,           1.8, 3.6, None),
    ('CVD LoP + Struct London',  cvd_lop_structure,          1.8, 3.6, [(7, 17)]),
    ('CVD LoP + Struct 1:3',    cvd_lop_structure,           1.5, 4.5, None),

    # Trend + Session combos (the "best of both filters")
    ('CVD LoP+EMA London',      cvd_lop_trend,              1.8, 3.6, [(7, 12)]),
    ('CVD LoP+EMA London+NY',   cvd_lop_trend,              1.8, 3.6, [(7, 17)]),
    ('CVD Absorb+EMA London',   cvd_absorption_trend,       1.8, 3.6, [(7, 12)]),
]


def fetch_and_prepare(symbol, timeframe, months=6):
    """Fetch candle data and compute CVD."""
    # Use 6 months of data for backtesting
    if months >= 6:
        start = '2025-09-01T00:00:00'
    else:
        start = '2026-01-01T00:00:00'

    df = fetch_bars(symbol, timeframe, 10000, start=start)
    if len(df) < 100:
        return None

    # Compute CVD columns
    df = compute_cvd(df)
    return df


def run_single(df, symbol, timeframe, strategy_name, strategy_fn, sl_atr, tp_atr, session_hours):
    """Run one CVD strategy. Returns stats dict or None."""
    if df is None or len(df) < 100:
        return None

    kwargs = {
        'sl_atr': sl_atr,
        'tp_atr': tp_atr,
        'symbol': symbol,
        'cooldown': 3,
        'session_hours': session_hours,
    }

    trades = backtest(df, strategy_fn, **kwargs)
    title = f'{strategy_name} — {symbol} {timeframe}'
    stats = report(trades, title)

    if stats:
        stats['symbol'] = symbol
        stats['timeframe'] = timeframe
        stats['strategy'] = strategy_name
        stats['sl_atr'] = sl_atr
        stats['tp_atr'] = tp_atr
    return stats


def run_all(symbols=None, timeframes=None):
    """Run all CVD strategies. Print leaderboard."""
    symbols = symbols or SYMBOLS
    timeframes = timeframes or TIMEFRAMES

    results = []
    # Cache fetched data per (symbol, timeframe) to avoid re-fetching
    data_cache = {}

    total = len(STRATEGY_CONFIGS) * len(symbols) * len(timeframes)
    done = 0

    for symbol in symbols:
        for tf in timeframes:
            key = (symbol, tf)
            if key not in data_cache:
                print(f'\nFetching {symbol} {tf}...')
                try:
                    data_cache[key] = fetch_and_prepare(symbol, tf)
                except Exception as e:
                    print(f'  SKIP {symbol} {tf}: {e}')
                    data_cache[key] = None

            df = data_cache[key]

            for name, fn, sl, tp, session in STRATEGY_CONFIGS:
                done += 1
                if df is None:
                    continue

                stats = run_single(df, symbol, tf, name, fn, sl, tp, session)
                if stats and stats.get('trades', 0) >= 10:
                    results.append(stats)

    if not results:
        print('\nNo results with enough trades.')
        return

    # Sort by expectancy
    results.sort(key=lambda x: x.get('expectancy_r', -999), reverse=True)

    # Print leaderboard
    print('\n' + '=' * 110)
    print('  CVD STRATEGY LEADERBOARD — sorted by expectancy (min 10 trades)')
    print('=' * 110)
    print(f'  {"Strategy":<28s} {"Symbol":<10s} {"TF":<5s} {"SL/TP":>7s} {"Trades":>6s} {"WR%":>6s} {"PF":>6s} {"Exp(R)":>8s} {"MaxDD":>7s} {"Verdict":<8s}')
    print('-' * 110)

    for r in results[:50]:
        wr = r.get('wr', 0)
        exp = r.get('expectancy_r', 0)
        pf = r.get('profit_factor', 0)
        sl_tp = f'{r["sl_atr"]}/{r["tp_atr"]}'
        verdict = 'PASS' if wr >= 60 and exp > 0.1 and pf > 1.3 else 'MAYBE' if wr >= 55 and exp > 0 else 'FAIL'
        print(f'  {r["strategy"]:<28s} {r["symbol"]:<10s} {r["timeframe"]:<5s} {sl_tp:>7s} {r["trades"]:>6d} {wr:>5.1f}% {pf:>6.2f} {exp:>+7.3f} {r.get("max_drawdown_r",0):>6.1f}R {verdict:<8s}')

    print('=' * 110)

    # Summary
    passing = [r for r in results if r.get('wr', 0) >= 60 and r.get('expectancy_r', 0) > 0.1 and r.get('profit_factor', 0) > 1.3]
    maybe = [r for r in results if r.get('wr', 0) >= 55 and r.get('expectancy_r', 0) > 0 and r not in passing]

    print(f'\n  {len(passing)} PASS | {len(maybe)} MAYBE | {len(results) - len(passing) - len(maybe)} FAIL')
    if passing:
        best = passing[0]
        print(f'  BEST: {best["strategy"]} on {best["symbol"]} {best["timeframe"]} — {best["wr"]:.1f}% WR, {best["expectancy_r"]:+.3f}R/trade, PF {best["profit_factor"]:.2f}')

    # Group by strategy type to find which CVD pattern works best
    print('\n  === BY STRATEGY TYPE ===')
    by_strat = {}
    for r in results:
        base = r['strategy'].split(' ')[1] if len(r['strategy'].split(' ')) > 1 else r['strategy']
        by_strat.setdefault(base, []).append(r)

    for stype, sresults in sorted(by_strat.items()):
        avg_wr = np.mean([r['wr'] for r in sresults])
        avg_exp = np.mean([r['expectancy_r'] for r in sresults])
        n_pass = len([r for r in sresults if r.get('wr', 0) >= 60 and r.get('expectancy_r', 0) > 0.1])
        print(f'  {stype:<20s}: avg WR={avg_wr:.1f}%, avg Exp={avg_exp:+.3f}R, PASS={n_pass}/{len(sresults)}')


import numpy as np

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Backtest CVD strategies')
    parser.add_argument('--symbol', '-s', help='Single symbol to test')
    parser.add_argument('--timeframe', '-t', help='Single timeframe (M15, H1)')
    args = parser.parse_args()

    symbols = [args.symbol] if args.symbol else None
    timeframes = [args.timeframe] if args.timeframe else None

    run_all(symbols, timeframes)
