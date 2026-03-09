#!/usr/bin/env python3
"""
Lighter.xyz strategy parameter optimizer.

Fetches historical 1h candles for ETH, BTC, SOL from the Lighter API
and backtests EMA crossover + RSI confirmation across parameter combinations.
Simulates trades with 3% SL / 6% TP (2:1 RR) matching the live entry algorithm.
"""
import sys
sys.path.insert(0, '/Users/rosaria/Desktop/metatrader5-quant-server-python/backend/django')
import os
os.environ.setdefault('LIGHTER_API_URL', 'https://mainnet.zklighter.elliot.ai')
os.environ.setdefault('LIGHTER_ACCOUNT_INDEX', '718566')

import itertools
import time
import pandas as pd
import numpy as np
from app.quant.algorithms.lighter.client import get_candles

# ── Parameters to test ──────────────────────────────────
EMA_FAST_OPTIONS = [8, 12, 20]
EMA_SLOW_OPTIONS = [21, 26, 50]
RSI_PERIOD_OPTIONS = [10, 14]
RSI_OVERSOLD_OPTIONS = [30, 35, 40]
RSI_OVERBOUGHT_OPTIONS = [60, 65, 70]

SL_PCT = 0.03   # 3% stop loss
TP_PCT = 0.06   # 6% take profit

SYMBOLS = ['ETH', 'BTC', 'SOL']
CANDLE_COUNT = 1000
RESOLUTION = '1h'


def calculate_ema(prices: pd.Series, span: int) -> pd.Series:
    return prices.ewm(span=span, adjust=False).mean()


def calculate_rsi(prices: pd.Series, period: int) -> pd.Series:
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def generate_signals(closes: pd.Series, ema_fast: int, ema_slow: int,
                     rsi_period: int, rsi_oversold: float, rsi_overbought: float) -> pd.Series:
    """Generate signal series: 1=buy, -1=sell, 0=neutral for every bar."""
    ema_f = calculate_ema(closes, ema_fast)
    ema_s = calculate_ema(closes, ema_slow)
    rsi = calculate_rsi(closes, rsi_period)

    signals = pd.Series(0, index=closes.index)

    for i in range(max(ema_slow, rsi_period) + 2, len(closes)):
        if pd.isna(ema_f.iloc[i]) or pd.isna(ema_s.iloc[i]) or pd.isna(rsi.iloc[i]):
            continue

        current_rsi = rsi.iloc[i]
        ema_cross_up = ema_f.iloc[i] > ema_s.iloc[i] and ema_f.iloc[i-1] <= ema_s.iloc[i-1]
        ema_cross_down = ema_f.iloc[i] < ema_s.iloc[i] and ema_f.iloc[i-1] >= ema_s.iloc[i-1]
        ema_trending_up = ema_f.iloc[i] > ema_s.iloc[i]
        ema_trending_down = ema_f.iloc[i] < ema_s.iloc[i]

        if ema_cross_up and current_rsi < rsi_overbought:
            signals.iloc[i] = 1
        elif ema_trending_up and current_rsi < rsi_oversold:
            signals.iloc[i] = 1
        elif ema_cross_down and current_rsi > rsi_oversold:
            signals.iloc[i] = -1
        elif ema_trending_down and current_rsi > rsi_overbought:
            signals.iloc[i] = -1

    return signals


def simulate_trades(candles_df: pd.DataFrame, signals: pd.Series) -> list:
    """Simulate trades with SL/TP exits. Returns list of trade dicts."""
    trades = []
    in_position = False
    entry_price = 0
    entry_bar = 0
    side = 0  # 1=long, -1=short

    highs = candles_df['h'].values
    lows = candles_df['l'].values
    closes = candles_df['c'].values

    for i in range(len(candles_df)):
        if in_position:
            # Check SL/TP on this bar using high/low
            if side == 1:  # Long
                sl_price = entry_price * (1 - SL_PCT)
                tp_price = entry_price * (1 + TP_PCT)
                if lows[i] <= sl_price:
                    trades.append({
                        'entry_bar': entry_bar, 'exit_bar': i,
                        'entry_price': entry_price, 'exit_price': sl_price,
                        'side': 'LONG', 'pnl_pct': -SL_PCT,
                        'duration': i - entry_bar, 'result': 'SL',
                    })
                    in_position = False
                elif highs[i] >= tp_price:
                    trades.append({
                        'entry_bar': entry_bar, 'exit_bar': i,
                        'entry_price': entry_price, 'exit_price': tp_price,
                        'side': 'LONG', 'pnl_pct': TP_PCT,
                        'duration': i - entry_bar, 'result': 'TP',
                    })
                    in_position = False
            else:  # Short
                sl_price = entry_price * (1 + SL_PCT)
                tp_price = entry_price * (1 - TP_PCT)
                if highs[i] >= sl_price:
                    trades.append({
                        'entry_bar': entry_bar, 'exit_bar': i,
                        'entry_price': entry_price, 'exit_price': sl_price,
                        'side': 'SHORT', 'pnl_pct': -SL_PCT,
                        'duration': i - entry_bar, 'result': 'SL',
                    })
                    in_position = False
                elif lows[i] <= tp_price:
                    trades.append({
                        'entry_bar': entry_bar, 'exit_bar': i,
                        'entry_price': entry_price, 'exit_price': tp_price,
                        'side': 'SHORT', 'pnl_pct': TP_PCT,
                        'duration': i - entry_bar, 'result': 'TP',
                    })
                    in_position = False

        if not in_position and signals.iloc[i] != 0:
            in_position = True
            entry_price = closes[i]
            entry_bar = i
            side = signals.iloc[i]

    # Close any open position at last bar price
    if in_position:
        exit_price = closes[-1]
        if side == 1:
            pnl = (exit_price - entry_price) / entry_price
        else:
            pnl = (entry_price - exit_price) / entry_price
        trades.append({
            'entry_bar': entry_bar, 'exit_bar': len(candles_df) - 1,
            'entry_price': entry_price, 'exit_price': exit_price,
            'side': 'LONG' if side == 1 else 'SHORT', 'pnl_pct': pnl,
            'duration': len(candles_df) - 1 - entry_bar, 'result': 'OPEN',
        })

    return trades


def evaluate_params(all_candles: dict, ema_fast: int, ema_slow: int,
                    rsi_period: int, rsi_oversold: float, rsi_overbought: float) -> dict:
    """Run backtest across all symbols for one parameter set."""
    if ema_fast >= ema_slow:
        return None

    all_trades = []
    per_symbol = {}

    for sym, df in all_candles.items():
        closes = df['c']
        signals = generate_signals(closes, ema_fast, ema_slow, rsi_period, rsi_oversold, rsi_overbought)
        trades = simulate_trades(df, signals)
        all_trades.extend(trades)
        per_symbol[sym] = trades

    if not all_trades:
        return None

    wins = [t for t in all_trades if t['pnl_pct'] > 0]
    losses = [t for t in all_trades if t['pnl_pct'] <= 0]
    total_pnl = sum(t['pnl_pct'] for t in all_trades)
    win_rate = len(wins) / len(all_trades) * 100 if all_trades else 0
    avg_duration = np.mean([t['duration'] for t in all_trades]) if all_trades else 0
    avg_pnl = total_pnl / len(all_trades) if all_trades else 0

    # Profit factor
    gross_profit = sum(t['pnl_pct'] for t in wins) if wins else 0
    gross_loss = abs(sum(t['pnl_pct'] for t in losses)) if losses else 0.001
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    return {
        'ema_fast': ema_fast, 'ema_slow': ema_slow,
        'rsi_period': rsi_period, 'rsi_oversold': rsi_oversold, 'rsi_overbought': rsi_overbought,
        'total_trades': len(all_trades), 'wins': len(wins), 'losses': len(losses),
        'win_rate': win_rate, 'total_pnl_pct': total_pnl * 100,
        'avg_pnl_pct': avg_pnl * 100, 'profit_factor': profit_factor,
        'avg_duration_bars': avg_duration,
        'per_symbol': {s: len(t) for s, t in per_symbol.items()},
    }


def main():
    print("=" * 80)
    print("LIGHTER.XYZ STRATEGY PARAMETER OPTIMIZER")
    print("=" * 80)
    print(f"SL: {SL_PCT*100}%  |  TP: {TP_PCT*100}%  |  Resolution: {RESOLUTION}  |  Candles: {CANDLE_COUNT}")
    print()

    # ── Fetch candle data ──────────────────────────────
    all_candles = {}
    for sym in SYMBOLS:
        print(f"Fetching {CANDLE_COUNT} x {RESOLUTION} candles for {sym}...", end=' ', flush=True)
        try:
            raw = get_candles(sym, resolution=RESOLUTION, count_back=CANDLE_COUNT)
            if not raw:
                print(f"EMPTY - skipping")
                continue
            df = pd.DataFrame(raw)
            for col in ['o', 'h', 'l', 'c']:
                df[col] = df[col].astype(float)
            df['v'] = pd.to_numeric(df['v'], errors='coerce').fillna(0)
            all_candles[sym] = df
            print(f"OK ({len(df)} bars)")
        except Exception as e:
            print(f"ERROR: {e}")

    if not all_candles:
        print("No candle data fetched. Exiting.")
        sys.exit(1)

    # ── Generate parameter combinations ────────────────
    combos = list(itertools.product(
        EMA_FAST_OPTIONS, EMA_SLOW_OPTIONS,
        RSI_PERIOD_OPTIONS, RSI_OVERSOLD_OPTIONS, RSI_OVERBOUGHT_OPTIONS,
    ))
    # Filter out invalid combos (fast >= slow)
    combos = [(f, s, rp, ro, rb) for f, s, rp, ro, rb in combos if f < s]
    print(f"\nTesting {len(combos)} parameter combinations across {list(all_candles.keys())}...")
    print()

    # ── Run backtests ──────────────────────────────────
    results = []
    t0 = time.time()
    for idx, (ef, es, rp, ro, rb) in enumerate(combos):
        r = evaluate_params(all_candles, ef, es, rp, ro, rb)
        if r and r['total_trades'] >= 5:  # Minimum 5 trades for statistical relevance
            results.append(r)
        if (idx + 1) % 20 == 0:
            print(f"  ... tested {idx+1}/{len(combos)} combos ({time.time()-t0:.1f}s)")

    elapsed = time.time() - t0
    print(f"\nCompleted {len(combos)} combos in {elapsed:.1f}s. {len(results)} had >= 5 trades.\n")

    if not results:
        print("No valid results. Try adjusting parameters or fetching more data.")
        sys.exit(1)

    # ── Sort by composite score: profit_factor * sqrt(trades) * total_pnl ──
    # This balances profitability, consistency, and trade count
    for r in results:
        # Composite: profit_factor weighted by trade count and total pnl direction
        r['score'] = r['profit_factor'] * np.sqrt(r['total_trades']) * (1 if r['total_pnl_pct'] > 0 else 0.1)

    results.sort(key=lambda x: x['score'], reverse=True)

    # ── Display top 15 results ─────────────────────────
    print("=" * 120)
    print(f"{'Rank':>4} {'EMA':>7} {'RSI':>12} {'Trades':>7} {'WinR%':>7} {'PnL%':>8} {'AvgPnL%':>8} {'PF':>6} {'AvgDur':>7} {'Score':>8}")
    print("-" * 120)
    for i, r in enumerate(results[:15]):
        ema_str = f"{r['ema_fast']}/{r['ema_slow']}"
        rsi_str = f"{r['rsi_period']}/{r['rsi_oversold']}/{r['rsi_overbought']}"
        print(f"{i+1:>4} {ema_str:>7} {rsi_str:>12} {r['total_trades']:>7} {r['win_rate']:>6.1f}% "
              f"{r['total_pnl_pct']:>+7.2f}% {r['avg_pnl_pct']:>+7.3f}% {r['profit_factor']:>6.2f} "
              f"{r['avg_duration_bars']:>6.1f}h {r['score']:>8.2f}")
    print("=" * 120)

    # ── Show best result details ───────────────────────
    best = results[0]
    print(f"\n{'BEST PARAMETERS':=^80}")
    print(f"  EMA Fast:       {best['ema_fast']}")
    print(f"  EMA Slow:       {best['ema_slow']}")
    print(f"  RSI Period:     {best['rsi_period']}")
    print(f"  RSI Oversold:   {best['rsi_oversold']}")
    print(f"  RSI Overbought: {best['rsi_overbought']}")
    print(f"  ─────────────────────────────")
    print(f"  Total Trades:   {best['total_trades']}")
    print(f"  Win Rate:       {best['win_rate']:.1f}%")
    print(f"  Total PnL:      {best['total_pnl_pct']:+.2f}%")
    print(f"  Avg PnL/Trade:  {best['avg_pnl_pct']:+.3f}%")
    print(f"  Profit Factor:  {best['profit_factor']:.2f}")
    print(f"  Avg Duration:   {best['avg_duration_bars']:.1f} hours")
    print(f"  Per-symbol:     {best['per_symbol']}")
    print(f"{'':=^80}")

    # ── Also show current params for comparison ────────
    current = evaluate_params(all_candles, 12, 26, 14, 35, 65)
    if current:
        print(f"\n{'CURRENT PARAMETERS (12/26, 14/35/65)':=^80}")
        print(f"  Total Trades:   {current['total_trades']}")
        print(f"  Win Rate:       {current['win_rate']:.1f}%")
        print(f"  Total PnL:      {current['total_pnl_pct']:+.2f}%")
        print(f"  Profit Factor:  {current['profit_factor']:.2f}")
        print(f"{'':=^80}")

    # Return best params for programmatic use
    return best


if __name__ == '__main__':
    best = main()
