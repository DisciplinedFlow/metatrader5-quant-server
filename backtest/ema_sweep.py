"""
EMA crossover parameter sweep across symbols, timeframes, and SL/TP ratios.
Uses engine_v2.py BacktestEngine.
"""

import sys
import os
import itertools
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtest.engine_v2 import run_backtest


# ── Signal factory ──────────────────────────────────────────

def make_ema_signal(fast_period: int, slow_period: int):
    """Return a signal function: EMA fast > slow AND fast rising → LONG, vice versa → SHORT."""
    def signal_fn(df: pd.DataFrame) -> int:
        if len(df) < slow_period + 2:
            return 0
        close = df['close']
        ema_fast = close.ewm(span=fast_period, adjust=False).mean()
        ema_slow = close.ewm(span=slow_period, adjust=False).mean()

        curr_fast = ema_fast.iloc[-1]
        prev_fast = ema_fast.iloc[-2]
        curr_slow = ema_slow.iloc[-1]

        fast_rising = curr_fast > prev_fast
        fast_falling = curr_fast < prev_fast

        if curr_fast > curr_slow and fast_rising:
            return 1   # LONG
        if curr_fast < curr_slow and fast_falling:
            return -1  # SHORT
        return 0
    return signal_fn


# ── Parameter grid ──────────────────────────────────────────

SYMBOLS = ['XAU']
TIMEFRAMES = ['5m', '15m', '1h']
FAST_PERIODS = [5, 8, 13, 21]
SLOW_PERIODS = [21, 34, 50, 100]

# SL/TP as (sl_pct, tp_pct)
XAU_SLTP = [(0.01, 0.02), (0.015, 0.03), (0.02, 0.04)]

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')


# ── Run sweep ───────────────────────────────────────────────

def main():
    all_results = []
    total = 0
    skipped = 0

    for symbol in SYMBOLS:
        sltp_list = XAU_SLTP

        for tf in TIMEFRAMES:
            # Check if data file exists
            pq = os.path.join(DATA_DIR, f'{symbol}_{tf}.parquet')
            csv = os.path.join(DATA_DIR, f'{symbol}_{tf}.csv')
            if not os.path.exists(pq) and not os.path.exists(csv):
                print(f"  SKIP {symbol} {tf} — no data file")
                skipped += 1
                continue

            for fast, slow in itertools.product(FAST_PERIODS, SLOW_PERIODS):
                if slow <= fast:
                    continue  # slow must be > fast

                for sl_pct, tp_pct in sltp_list:
                    total += 1
                    sig_fn = make_ema_signal(fast, slow)
                    lookback = max(slow + 10, 50)

                    try:
                        res = run_backtest(
                            symbol, tf, sig_fn,
                            sl_pct=sl_pct, tp_pct=tp_pct,
                            data_dir=DATA_DIR,
                            lookback=lookback,
                        )
                    except Exception as e:
                        print(f"  ERROR {symbol} {tf} EMA({fast}/{slow}) SL{sl_pct}/TP{tp_pct}: {e}")
                        continue

                    row = {
                        'symbol': symbol,
                        'timeframe': tf,
                        'ema_fast': fast,
                        'ema_slow': slow,
                        'sl_pct': sl_pct,
                        'tp_pct': tp_pct,
                        'trades': res['total_trades'],
                        'wins': res['wins'],
                        'losses': res['losses'],
                        'win_rate': round(res['win_rate'], 4),
                        'total_pnl': round(res['total_pnl'], 6),
                        'profit_factor': round(res['profit_factor'], 4),
                        'max_drawdown': round(res['max_drawdown'], 6),
                        'sharpe': round(res['sharpe'], 4),
                        'avg_win': round(res['avg_win'], 6),
                        'avg_loss': round(res['avg_loss'], 6),
                    }
                    all_results.append(row)

    print(f"\nCompleted {total} combinations ({skipped} skipped for missing data)")
    print(f"Total result rows: {len(all_results)}")

    # Save full results
    df_all = pd.DataFrame(all_results)
    df_all = df_all.sort_values('profit_factor', ascending=False).reset_index(drop=True)
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results_ema_sweep.csv')
    df_all.to_csv(out_path, index=False)
    print(f"\nFull results saved to {out_path}")

    # Filter TOP 20
    top = df_all[
        (df_all['trades'] >= 20) &
        (df_all['win_rate'] > 0.45) &
        (df_all['profit_factor'] > 1.2)
    ].head(20)

    print(f"\n{'='*100}")
    print(f"TOP {len(top)} COMBINATIONS (trades>=20, WR>45%, PF>1.2)")
    print(f"{'='*100}")

    if top.empty:
        print("No combinations met the filter criteria.")
        # Show best regardless
        print("\nBest 20 by profit factor (no filter):")
        best = df_all[df_all['trades'] >= 5].head(20)
        print(best.to_string(index=False))
    else:
        print(top.to_string(index=False))

    # Summary stats
    print(f"\n{'='*100}")
    print("SUMMARY BY SYMBOL")
    print(f"{'='*100}")
    for sym in SYMBOLS:
        sym_df = df_all[df_all['symbol'] == sym]
        if sym_df.empty:
            continue
        best_row = sym_df.iloc[0]
        avg_wr = sym_df['win_rate'].mean()
        avg_pf = sym_df[sym_df['profit_factor'] < float('inf')]['profit_factor'].mean()
        print(f"  {sym}: {len(sym_df)} combos, avg WR={avg_wr:.1%}, avg PF={avg_pf:.2f}, "
              f"best PF={best_row['profit_factor']:.2f} "
              f"(EMA {int(best_row['ema_fast'])}/{int(best_row['ema_slow'])} {best_row['timeframe']} "
              f"SL{best_row['sl_pct']}/TP{best_row['tp_pct']})")


if __name__ == '__main__':
    main()
