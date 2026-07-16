"""
Backtesting engine — fetch MT5 data, simulate strategies, report results.

Usage:
    from engine import fetch_bars, backtest, report
    df = fetch_bars('XAUUSD', 'H1', 5000)
    trades = backtest(df, strategy_fn, sl_atr=1.8, tp_atr=3.6)
    report(trades, 'My Strategy — XAUUSD H1')

Strategy function signature:
    def my_strategy(df, i) -> 'BUY' | 'SELL' | None
        df: full DataFrame (but only look at rows <= i)
        i:  current bar index
        Return 'BUY', 'SELL', or None (no signal)
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime

MT5_URL = 'http://localhost:5001'

# MT5 timeframe constants
TF_MAP = {
    'M1': 1, 'M5': 5, 'M15': 15, 'M30': 30,
    'H1': 16385, 'H4': 16388, 'D1': 16408, 'W1': 32769,
}

# Typical spreads in price units (approximate for Vantage demo)
SPREADS = {
    'XAUUSD': 0.30, 'XAGUSD': 0.030, 'XAUEUR': 0.40, 'XAUAUD': 0.50, 'XAUJPY': 5.0,
    'EURUSD': 0.00012, 'GBPUSD': 0.00015, 'USDJPY': 0.015, 'AUDUSD': 0.00012,
    'NZDUSD': 0.00015, 'USDCAD': 0.00015, 'USDCHF': 0.00015, 'EURGBP': 0.00015,
    'USDSEK': 0.005, 'USDCNH': 0.0005,
    'USOUSD': 0.03, 'UKOUSDft': 0.03, 'NG-C': 0.005,
}


def fetch_bars(symbol: str, timeframe: str = 'H1', count: int = 5000,
               start: str = None, end: str = '2026-03-19T23:59:59') -> pd.DataFrame:
    """Fetch OHLCV bars from MT5 API. Uses date range for longer history."""
    tf_int = TF_MAP.get(timeframe, 16385)
    if start:
        resp = requests.get(f'{MT5_URL}/fetch_data_range', params={
            'symbol': symbol, 'timeframe': tf_int,
            'start': start, 'end': end,
        }, timeout=60)
    else:
        resp = requests.get(f'{MT5_URL}/fetch_data_pos', params={
            'symbol': symbol, 'timeframe': tf_int, 'count': count,
        }, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and 'error' in data:
        raise ValueError(data['error'])
    df = pd.DataFrame(data)
    df['time'] = pd.to_datetime(df['time'])
    df = df.sort_values('time').reset_index(drop=True)
    # Compute ATR
    df['tr'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(abs(df['high'] - df['close'].shift(1)),
                   abs(df['low'] - df['close'].shift(1)))
    )
    df['atr'] = df['tr'].rolling(14).mean()
    return df


def backtest(df: pd.DataFrame, strategy_fn, sl_atr: float = 1.8, tp_atr: float = 3.6,
             spread: float = None, symbol: str = '', cooldown: int = 0,
             session_hours: list = None, max_open: int = 1) -> list:
    """
    Run a strategy over historical bars. Returns list of trade dicts.

    Args:
        df:             OHLCV DataFrame with 'atr' column
        strategy_fn:    fn(df, i) -> 'BUY' | 'SELL' | None
        sl_atr:         SL distance as ATR multiple
        tp_atr:         TP distance as ATR multiple
        spread:         Spread in price units (auto-detected from symbol if None)
        symbol:         Symbol name (for spread lookup)
        cooldown:       Bars to wait between entries
        session_hours:  List of (start_hour, end_hour) tuples for session filter, or None
        max_open:       Max simultaneous open trades
    """
    if spread is None:
        spread = SPREADS.get(symbol, 0.0002)

    trades = []
    open_trades = []
    last_entry_bar = -cooldown - 1

    warmup = 50  # bars needed for indicators

    for i in range(warmup, len(df)):
        bar = df.iloc[i]

        # --- Check open trades against this bar ---
        still_open = []
        for t in open_trades:
            if t['direction'] == 'BUY':
                # SL hit? (low touches SL)
                if bar['low'] <= t['sl']:
                    t['exit_price'] = t['sl']
                    t['exit_bar'] = i
                    t['exit_time'] = bar['time']
                    t['pnl'] = t['exit_price'] - t['entry_price'] - spread
                    t['result'] = 'SL'
                    trades.append(t)
                    continue
                # TP hit? (high touches TP)
                if bar['high'] >= t['tp']:
                    t['exit_price'] = t['tp']
                    t['exit_bar'] = i
                    t['exit_time'] = bar['time']
                    t['pnl'] = t['exit_price'] - t['entry_price'] - spread
                    t['result'] = 'TP'
                    trades.append(t)
                    continue
            else:  # SELL
                # SL hit? (high touches SL)
                if bar['high'] >= t['sl']:
                    t['exit_price'] = t['sl']
                    t['exit_bar'] = i
                    t['exit_time'] = bar['time']
                    t['pnl'] = t['entry_price'] - t['exit_price'] - spread
                    t['result'] = 'SL'
                    trades.append(t)
                    continue
                # TP hit? (low touches TP)
                if bar['low'] <= t['tp']:
                    t['exit_price'] = t['tp']
                    t['exit_bar'] = i
                    t['exit_time'] = bar['time']
                    t['pnl'] = t['entry_price'] - t['exit_price'] - spread
                    t['result'] = 'TP'
                    trades.append(t)
                    continue
            still_open.append(t)
        open_trades = still_open

        # --- Check for new entry ---
        if len(open_trades) >= max_open:
            continue
        if i - last_entry_bar < cooldown:
            continue

        # Session filter
        if session_hours:
            hour = bar['time'].hour
            in_session = any(s <= hour < e for s, e in session_hours)
            if not in_session:
                continue

        atr_val = df['atr'].iloc[i]
        if pd.isna(atr_val) or atr_val <= 0:
            continue

        signal = strategy_fn(df, i)
        if signal is None:
            continue

        entry_price = bar['close']
        sl_dist = sl_atr * atr_val
        tp_dist = tp_atr * atr_val

        if signal == 'BUY':
            entry_price += spread / 2  # buy at ask
            sl = entry_price - sl_dist
            tp = entry_price + tp_dist
        else:
            entry_price -= spread / 2  # sell at bid
            sl = entry_price + sl_dist
            tp = entry_price - tp_dist

        trade = {
            'direction': signal,
            'entry_price': entry_price,
            'sl': sl,
            'tp': tp,
            'sl_dist': sl_dist,
            'tp_dist': tp_dist,
            'entry_bar': i,
            'entry_time': bar['time'],
            'atr': atr_val,
            'exit_price': None,
            'exit_bar': None,
            'exit_time': None,
            'pnl': None,
            'result': None,
        }
        open_trades.append(trade)
        last_entry_bar = i

    # Close any remaining open trades at last bar
    last_bar = df.iloc[-1]
    for t in open_trades:
        t['exit_price'] = last_bar['close']
        t['exit_bar'] = len(df) - 1
        t['exit_time'] = last_bar['time']
        if t['direction'] == 'BUY':
            t['pnl'] = t['exit_price'] - t['entry_price'] - spread
        else:
            t['pnl'] = t['entry_price'] - t['exit_price'] - spread
        t['result'] = 'OPEN'
        trades.append(t)

    return trades


def report(trades: list, title: str = 'Backtest') -> dict:
    """Print and return performance summary."""
    if not trades:
        print(f'\n{title}: No trades generated.')
        return {}

    closed = [t for t in trades if t['result'] in ('SL', 'TP')]
    if not closed:
        print(f'\n{title}: No closed trades (all still open).')
        return {}

    wins = [t for t in closed if t['pnl'] > 0]
    losses = [t for t in closed if t['pnl'] <= 0]
    tp_hits = [t for t in closed if t['result'] == 'TP']
    sl_hits = [t for t in closed if t['result'] == 'SL']

    total_pnl_r = sum(t['pnl'] / t['sl_dist'] for t in closed if t['sl_dist'] > 0)
    avg_win_r = np.mean([t['pnl'] / t['sl_dist'] for t in wins]) if wins else 0
    avg_loss_r = np.mean([t['pnl'] / t['sl_dist'] for t in losses]) if losses else 0

    gross_wins = sum(t['pnl'] for t in wins)
    gross_losses = abs(sum(t['pnl'] for t in losses))
    pf = gross_wins / gross_losses if gross_losses > 0 else float('inf')

    wr = len(wins) / len(closed) * 100
    expectancy_r = total_pnl_r / len(closed)

    # Equity curve in R-multiples
    equity = [0.0]
    for t in closed:
        r = t['pnl'] / t['sl_dist'] if t['sl_dist'] > 0 else 0
        equity.append(equity[-1] + r)
    peak = 0.0
    max_dd = 0.0
    for e in equity:
        peak = max(peak, e)
        dd = peak - e
        max_dd = max(max_dd, dd)

    # Streaks
    max_win_streak = max_lose_streak = cur_win = cur_lose = 0
    for t in closed:
        if t['pnl'] > 0:
            cur_win += 1
            cur_lose = 0
        else:
            cur_lose += 1
            cur_win = 0
        max_win_streak = max(max_win_streak, cur_win)
        max_lose_streak = max(max_lose_streak, cur_lose)

    # Duration in bars
    durations = [t['exit_bar'] - t['entry_bar'] for t in closed]
    win_dur = [t['exit_bar'] - t['entry_bar'] for t in wins]
    loss_dur = [t['exit_bar'] - t['entry_bar'] for t in losses]

    # Time of day distribution
    hours = {}
    for t in closed:
        h = t['entry_time'].hour
        hours.setdefault(h, {'w': 0, 'l': 0})
        if t['pnl'] > 0:
            hours[h]['w'] += 1
        else:
            hours[h]['l'] += 1

    stats = {
        'trades': len(closed),
        'wins': len(wins),
        'losses': len(losses),
        'wr': wr,
        'tp_hits': len(tp_hits),
        'sl_hits': len(sl_hits),
        'total_r': total_pnl_r,
        'avg_win_r': avg_win_r,
        'avg_loss_r': avg_loss_r,
        'expectancy_r': expectancy_r,
        'profit_factor': pf,
        'max_drawdown_r': max_dd,
        'max_win_streak': max_win_streak,
        'max_lose_streak': max_lose_streak,
        'avg_duration': np.mean(durations),
        'avg_win_duration': np.mean(win_dur) if win_dur else 0,
        'avg_loss_duration': np.mean(loss_dur) if loss_dur else 0,
    }

    # Print
    sep = '─' * 55
    print(f'\n{sep}')
    print(f'  {title}')
    print(sep)
    print(f'  Trades:      {len(closed)} ({len(wins)}W / {len(losses)}L)')
    print(f'  Win Rate:    {wr:.1f}%')
    print(f'  TP hits:     {len(tp_hits)} | SL hits: {len(sl_hits)}')
    print(f'  Profit Factor: {pf:.2f}')
    print(f'  Expectancy:  {expectancy_r:+.3f} R per trade')
    print(f'  Total P&L:   {total_pnl_r:+.1f} R')
    print(f'  Avg Win:     {avg_win_r:+.2f} R | Avg Loss: {avg_loss_r:+.2f} R')
    print(f'  Max DD:      {max_dd:.1f} R')
    print(f'  Streaks:     {max_win_streak}W / {max_lose_streak}L')
    print(f'  Avg Duration: {np.mean(durations):.1f} bars (win: {np.mean(win_dur) if win_dur else 0:.1f}, loss: {np.mean(loss_dur) if loss_dur else 0:.1f})')

    # Best/worst hours
    if hours:
        print(f'\n  Hour  Trades  WR%')
        for h in sorted(hours.keys()):
            w, l = hours[h]['w'], hours[h]['l']
            total = w + l
            print(f'  {h:02d}:00  {total:>4d}    {w/total*100:>5.1f}%')

    print(sep)

    # Pass/fail verdict
    if wr >= 60 and expectancy_r > 0.1 and pf > 1.3:
        print(f'  PASS — viable strategy')
    elif wr >= 55 and expectancy_r > 0:
        print(f'  MAYBE — needs refinement')
    else:
        print(f'  FAIL — not viable at current parameters')
    print()

    return stats
