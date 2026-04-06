#!/usr/bin/env python3
"""
Backtest CVD V2 strategies (research-refined).

Usage:
    python backtest/run_cvd_v2.py
    python backtest/run_cvd_v2.py --symbol XAUUSD
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from engine import fetch_bars, backtest, report
from cvd_strategies_v2 import (
    compute_cvd_v2,
    cvd_lop_v2,
    cvd_absorption_v2,
    cvd_lop_full_confluence,
    cvd_absorption_full,
    cvd_lop_sweep_v2,
    cvd_exhaustion_v2,
    cvd_any_divergence,
)

SYMBOLS = ['XAUUSD', 'XAGUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'UKOUSDft', 'USOUSD']
TIMEFRAMES = ['M15', 'H1']

# V2 Strategy configs: (name, function, sl_atr, tp_atr, session_hours)
CONFIGS = [
    # Core V2 strategies (no extra session filter — some have built-in)
    ('V2 LoP Pivot',             cvd_lop_v2,                 1.8, 3.6, None),
    ('V2 LoP Pivot 1:3',        cvd_lop_v2,                 1.5, 4.5, None),
    ('V2 LoP Pivot 1:4',        cvd_lop_v2,                 1.2, 4.8, None),
    ('V2 Absorption',            cvd_absorption_v2,           1.8, 3.6, None),
    ('V2 Absorption 1:3',       cvd_absorption_v2,           1.5, 4.5, None),

    # Full confluence (trend + session + confirmation built-in)
    ('V2 LoP Full',              cvd_lop_full_confluence,     1.8, 3.6, None),
    ('V2 LoP Full 1:3',         cvd_lop_full_confluence,     1.5, 4.5, None),
    ('V2 LoP Full 1:4',         cvd_lop_full_confluence,     1.2, 4.8, None),
    ('V2 Absorb Full',           cvd_absorption_full,         1.8, 3.6, None),
    ('V2 Absorb Full 1:3',      cvd_absorption_full,         1.5, 4.5, None),

    # Session sweep combo
    ('V2 LoP Sweep',             cvd_lop_sweep_v2,            1.8, 3.6, None),
    ('V2 LoP Sweep 1:3',        cvd_lop_sweep_v2,            1.5, 4.5, None),

    # Exhaustion (session-anchored)
    ('V2 Exhaustion',            cvd_exhaustion_v2,            1.5, 3.0, None),
    ('V2 Exhaustion 1:3',       cvd_exhaustion_v2,            1.2, 3.6, None),

    # Combined divergence
    ('V2 Any Divergence',        cvd_any_divergence,           1.8, 3.6, None),
    ('V2 Any Divergence 1:3',   cvd_any_divergence,           1.5, 4.5, None),

    # Session-filtered raw strategies
    ('V2 LoP London',           cvd_lop_v2,                  1.8, 3.6, [(7, 12)]),
    ('V2 LoP NY',               cvd_lop_v2,                  1.8, 3.6, [(13, 17)]),
    ('V2 LoP London+NY',        cvd_lop_v2,                  1.8, 3.6, [(7, 17)]),
    ('V2 Absorb London',        cvd_absorption_v2,            1.8, 3.6, [(7, 12)]),
]


def fetch_and_prepare(symbol, timeframe):
    df = fetch_bars(symbol, timeframe, 10000, start='2025-09-01T00:00:00')
    if len(df) < 100:
        return None
    return compute_cvd_v2(df)


def main(symbols=None, timeframes=None):
    symbols = symbols or SYMBOLS
    timeframes = timeframes or TIMEFRAMES
    results = []
    data_cache = {}

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
            if df is None:
                continue

            for name, fn, sl, tp, session in CONFIGS:
                kwargs = {'sl_atr': sl, 'tp_atr': tp, 'symbol': symbol, 'cooldown': 3, 'session_hours': session}
                trades = backtest(df, fn, **kwargs)
                title = f'{name} — {symbol} {tf}'
                stats = report(trades, title)
                if stats and stats.get('trades', 0) >= 10:
                    stats.update({'symbol': symbol, 'timeframe': tf, 'strategy': name, 'sl_atr': sl, 'tp_atr': tp})
                    results.append(stats)

    if not results:
        print('\nNo results.')
        return

    results.sort(key=lambda x: x.get('wr', 0), reverse=True)

    print('\n' + '=' * 115)
    print('  CVD V2 LEADERBOARD — sorted by WIN RATE (min 10 trades)')
    print('=' * 115)
    print(f'  {"Strategy":<28s} {"Symbol":<10s} {"TF":<5s} {"SL/TP":>7s} {"Trades":>6s} {"WR%":>6s} {"PF":>6s} {"Exp(R)":>8s} {"MaxDD":>7s} {"Verdict":<8s}')
    print('-' * 115)

    for r in results[:60]:
        wr = r.get('wr', 0)
        exp = r.get('expectancy_r', 0)
        pf = r.get('profit_factor', 0)
        sl_tp = f'{r["sl_atr"]}/{r["tp_atr"]}'
        verdict = 'PASS' if wr >= 60 and exp > 0.1 and pf > 1.3 else 'MAYBE' if wr >= 55 and exp > 0 else 'FAIL'
        print(f'  {r["strategy"]:<28s} {r["symbol"]:<10s} {r["timeframe"]:<5s} {sl_tp:>7s} {r["trades"]:>6d} {wr:>5.1f}% {pf:>6.2f} {exp:>+7.3f} {r.get("max_drawdown_r",0):>6.1f}R {verdict:<8s}')

    print('=' * 115)

    passing = [r for r in results if r.get('wr', 0) >= 60 and r.get('expectancy_r', 0) > 0.1 and r.get('profit_factor', 0) > 1.3]
    maybe = [r for r in results if r.get('wr', 0) >= 55 and r.get('expectancy_r', 0) > 0 and r not in passing]

    print(f'\n  {len(passing)} PASS | {len(maybe)} MAYBE | {len(results) - len(passing) - len(maybe)} FAIL')
    if passing:
        best = passing[0]
        print(f'  BEST: {best["strategy"]} on {best["symbol"]} {best["timeframe"]} — {best["wr"]:.1f}% WR, {best["expectancy_r"]:+.3f}R, PF {best["profit_factor"]:.2f}')

    # Group winners by symbol
    print('\n  === 60%+ WR BY SYMBOL ===')
    by_sym = {}
    for r in passing:
        by_sym.setdefault(r['symbol'], []).append(r)
    for sym, sresults in sorted(by_sym.items()):
        print(f'  {sym}: {len(sresults)} strategies PASS')
        for r in sresults[:3]:
            print(f'    {r["strategy"]} {r["timeframe"]} — {r["wr"]:.1f}% WR, {r["expectancy_r"]:+.3f}R')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol', '-s')
    parser.add_argument('--timeframe', '-t')
    args = parser.parse_args()
    symbols = [args.symbol] if args.symbol else None
    timeframes = [args.timeframe] if args.timeframe else None
    main(symbols, timeframes)
