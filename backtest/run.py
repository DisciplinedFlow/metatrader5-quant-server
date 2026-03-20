#!/usr/bin/env python3
"""
Run all strategies across multiple symbols and timeframes.
Find combinations that hit 60%+ WR with positive expectancy.

Usage:
    python backtest/run.py
    python backtest/run.py --symbol XAUUSD --timeframe H1
    python backtest/run.py --strategy ema_crossover
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from engine import fetch_bars, backtest, report
import strategies as strat

# Symbols to test (the ones with enough liquidity on Vantage)
SYMBOLS = [
    'XAUUSD', 'XAGUSD', 'EURUSD', 'GBPUSD', 'USDJPY',
    'AUDUSD', 'USDCAD', 'UKOUSDft', 'USOUSD',
]

# Timeframes to test
TIMEFRAMES = ['M15', 'H1', 'H4']

# Strategy configs: (name, function, sl_atr, tp_atr, kwargs)
STRATEGY_CONFIGS = [
    ('EMA 8/21 Cross', lambda df, i: strat.ema_crossover(df, i, 8, 21), 1.8, 3.6, {}),
    ('EMA 13/34 Cross', lambda df, i: strat.ema_crossover(df, i, 13, 34), 1.8, 3.6, {}),
    ('RSI Reversal 30/70', lambda df, i: strat.rsi_reversal(df, i, 14, 30, 70), 1.5, 3.0, {}),
    ('RSI Reversal 25/75', lambda df, i: strat.rsi_reversal(df, i, 14, 25, 75), 1.5, 3.0, {}),
    ('MACD + ADX>20', lambda df, i: strat.macd_momentum(df, i), 1.8, 3.6, {}),
    ('Bollinger Bounce', lambda df, i: strat.bollinger_bounce(df, i), 1.5, 3.0, {}),
    ('Session Breakout', lambda df, i: strat.session_breakout(df, i), 1.5, 3.0, {'session_hours': [(7, 17)]}),
    ('Keltner Breakout', lambda df, i: strat.keltner_breakout(df, i), 2.0, 4.0, {}),
    ('Stoch + RSI Combo', lambda df, i: strat.stoch_rsi_combo(df, i), 1.5, 3.0, {}),
    ('Engulfing Pattern', lambda df, i: strat.engulfing_pattern(df, i), 1.5, 3.0, {}),
    ('Triple EMA Pullback', lambda df, i: strat.triple_ema_pullback(df, i), 1.5, 3.0, {}),
]


def run_single(symbol, timeframe, strategy_name, strategy_fn, sl_atr, tp_atr, extra_kwargs=None):
    """Run one strategy on one symbol/timeframe. Returns stats dict or None."""
    try:
        df = fetch_bars(symbol, timeframe, 8000)
    except Exception as e:
        print(f'  SKIP {symbol} {timeframe}: {e}')
        return None

    if len(df) < 100:
        return None

    kwargs = {'sl_atr': sl_atr, 'tp_atr': tp_atr, 'symbol': symbol, 'cooldown': 3}
    if extra_kwargs:
        kwargs.update(extra_kwargs)

    trades = backtest(df, strategy_fn, **kwargs)
    title = f'{strategy_name} — {symbol} {timeframe}'
    stats = report(trades, title)
    if stats:
        stats['symbol'] = symbol
        stats['timeframe'] = timeframe
        stats['strategy'] = strategy_name
    return stats


def run_all():
    """Run all strategies across all symbols and timeframes. Print leaderboard."""
    results = []

    for name, fn, sl, tp, kwargs in STRATEGY_CONFIGS:
        for symbol in SYMBOLS:
            for tf in TIMEFRAMES:
                stats = run_single(symbol, tf, name, fn, sl, tp, kwargs)
                if stats and stats.get('trades', 0) >= 20:  # minimum sample size
                    results.append(stats)

    if not results:
        print('\nNo results with enough trades.')
        return

    # Sort by expectancy
    results.sort(key=lambda x: x.get('expectancy_r', -999), reverse=True)

    # Print leaderboard
    print('\n' + '=' * 90)
    print('  LEADERBOARD — Top strategies by expectancy (min 20 trades)')
    print('=' * 90)
    print(f'  {"Strategy":<25s} {"Symbol":<10s} {"TF":<5s} {"Trades":>6s} {"WR%":>6s} {"PF":>6s} {"Exp(R)":>8s} {"MaxDD":>7s} {"Verdict":<8s}')
    print('-' * 90)

    for r in results[:30]:
        wr = r.get('wr', 0)
        exp = r.get('expectancy_r', 0)
        pf = r.get('profit_factor', 0)
        verdict = 'PASS' if wr >= 60 and exp > 0.1 and pf > 1.3 else 'MAYBE' if wr >= 55 and exp > 0 else 'FAIL'
        print(f'  {r["strategy"]:<25s} {r["symbol"]:<10s} {r["timeframe"]:<5s} {r["trades"]:>6d} {wr:>5.1f}% {pf:>6.2f} {exp:>+7.3f} {r.get("max_drawdown_r",0):>6.1f}R {verdict:<8s}')

    print('=' * 90)

    # Summary
    passing = [r for r in results if r.get('wr', 0) >= 60 and r.get('expectancy_r', 0) > 0.1]
    print(f'\n  {len(passing)} strategies PASS (60%+ WR, positive expectancy)')
    if passing:
        print(f'  Best: {passing[0]["strategy"]} on {passing[0]["symbol"]} {passing[0]["timeframe"]} — {passing[0]["wr"]:.1f}% WR, {passing[0]["expectancy_r"]:+.3f}R')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol', '-s', help='Single symbol to test')
    parser.add_argument('--timeframe', '-t', help='Single timeframe to test')
    parser.add_argument('--strategy', help='Single strategy name to test')
    args = parser.parse_args()

    if args.symbol or args.strategy:
        symbols = [args.symbol] if args.symbol else SYMBOLS
        timeframes = [args.timeframe] if args.timeframe else TIMEFRAMES
        strats = STRATEGY_CONFIGS
        if args.strategy:
            strats = [s for s in STRATEGY_CONFIGS if args.strategy.lower() in s[0].lower()]
            if not strats:
                print(f'Strategy "{args.strategy}" not found. Available:')
                for s in STRATEGY_CONFIGS:
                    print(f'  {s[0]}')
                sys.exit(1)

        results = []
        for name, fn, sl, tp, kwargs in strats:
            for sym in symbols:
                for tf in timeframes:
                    stats = run_single(sym, tf, name, fn, sl, tp, kwargs)
                    if stats and stats.get('trades', 0) >= 20:
                        results.append(stats)
        if results:
            results.sort(key=lambda x: x.get('expectancy_r', -999), reverse=True)
            best = results[0]
            print(f'\nBest: {best["strategy"]} on {best["symbol"]} {best["timeframe"]} — {best["wr"]:.1f}% WR, {best["expectancy_r"]:+.3f}R')
    else:
        run_all()
