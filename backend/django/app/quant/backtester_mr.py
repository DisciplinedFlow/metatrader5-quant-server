import logging
import traceback

import pandas as pd
import numpy as np

from app.utils.api.data import fetch_data_pos
from app.utils.api.yahoo import fetch_yahoo_data
from app.quant.indicators.mean_reversion import mean_reversion
from app.quant.algorithms.mean_reversion.config import (
    PAIRS,
    MAIN_TIMEFRAME,
    TP_PNL_MULTIPLIER,
    SL_PNL_MULTIPLIER,
)

logger = logging.getLogger(__name__)


def _bar_to_unix(df, idx):
    """Convert DataFrame bar index to Unix timestamp."""
    ts = df.index[idx] if hasattr(df.index[idx], 'timestamp') else pd.Timestamp(df.iloc[idx].get('time', 0))
    return int(ts.timestamp()) if hasattr(ts, 'timestamp') else 0


YAHOO_PERIOD = '60d'
YAHOO_INTERVAL = '15m'
BB_WINDOW = 20
MIN_WIN_RATE = 0.55


def _simulate_trades_mr(df):
    """
    Walk forward through candle data and simulate trades based on Bollinger Band
    mean-reversion signals.  'top' -> SELL, 'bottom' -> BUY.
    Returns a list of trade result dicts.
    """
    df = df.copy()
    df['mr_signal'] = mean_reversion(df, window=BB_WINDOW)

    trades = []
    in_trade = False
    entry_price = 0
    sl_price = 0
    tp_price = 0
    trade_type = None
    entry_bar_idx = 0

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        # If in a trade, check for SL/TP hit
        if in_trade:
            trade_base = {'type': trade_type, 'entry': entry_price, 'sl': sl_price, 'tp': tp_price, 'signal': entry_signal, 'entry_time': _bar_to_unix(df, entry_bar_idx)}
            if trade_type == 'BUY':
                if row['low'] <= sl_price:
                    pnl = sl_price - entry_price
                    trades.append({**trade_base, 'exit': sl_price, 'pnl_pct': pnl / entry_price, 'result': 'SL', 'exit_time': _bar_to_unix(df, i)})
                    in_trade = False
                    continue
                if row['high'] >= tp_price:
                    pnl = tp_price - entry_price
                    trades.append({**trade_base, 'exit': tp_price, 'pnl_pct': pnl / entry_price, 'result': 'TP', 'exit_time': _bar_to_unix(df, i)})
                    in_trade = False
                    continue
            elif trade_type == 'SELL':
                if row['high'] >= sl_price:
                    pnl = entry_price - sl_price
                    trades.append({**trade_base, 'exit': sl_price, 'pnl_pct': pnl / entry_price, 'result': 'SL', 'exit_time': _bar_to_unix(df, i)})
                    in_trade = False
                    continue
                if row['low'] <= tp_price:
                    pnl = entry_price - tp_price
                    trades.append({**trade_base, 'exit': tp_price, 'pnl_pct': pnl / entry_price, 'result': 'TP', 'exit_time': _bar_to_unix(df, i)})
                    in_trade = False
                    continue
            continue

        # Check for entry signal on previous bar
        signal = prev['mr_signal']

        if signal == 'top':
            # Price crossed above upper band -> expect reversion down -> SELL
            trade_type = 'SELL'
            entry_price = row['open']
            entry_bar_idx = i
            sl_price = entry_price * (1 - SL_PNL_MULTIPLIER / 100)   # SL_PNL_MULTIPLIER is negative
            tp_price = entry_price * (1 - TP_PNL_MULTIPLIER / 100)
            entry_signal = 'BB upper band touch'
            in_trade = True
        elif signal == 'bottom':
            # Price crossed below lower band -> expect reversion up -> BUY
            trade_type = 'BUY'
            entry_price = row['open']
            entry_bar_idx = i
            sl_price = entry_price * (1 + SL_PNL_MULTIPLIER / 100)   # SL_PNL_MULTIPLIER is negative
            tp_price = entry_price * (1 + TP_PNL_MULTIPLIER / 100)
            entry_signal = 'BB lower band touch'
            in_trade = True

    return trades


def run_backtest_mr():
    """
    Run mean-reversion backtest across all pairs using historical M15 data.
    Primary: Yahoo Finance.  Fallback: MT5 API.
    Returns a dict with aggregated results.
    """
    all_trades = []
    data_source = 'YAHOO'
    period_days = 60

    for pair in PAIRS:
        try:
            df = fetch_yahoo_data(pair, period=YAHOO_PERIOD, interval=YAHOO_INTERVAL)
            source = 'yahoo'

            if df is None or df.empty or len(df) < BB_WINDOW + 10:
                logger.info(f"MR Backtest {pair}: Yahoo data insufficient, falling back to MT5")
                df = fetch_data_pos(pair, MAIN_TIMEFRAME, 500)
                source = 'mt5'
                if source == 'mt5' and data_source == 'YAHOO':
                    data_source = 'MIXED'

            if df is None or df.empty or len(df) < BB_WINDOW + 10:
                logger.info(f"MR Backtest: insufficient data for {pair} (both sources)")
                continue

            trades = _simulate_trades_mr(df)
            for t in trades:
                t['symbol'] = pair
            all_trades.extend(trades)
            logger.info(f"MR Backtest {pair}: {len(trades)} trades simulated ({source}, {len(df)} bars)")

        except Exception as e:
            logger.error(f"MR Backtest error for {pair}: {e}\n{traceback.format_exc()}")

    if not all_trades:
        return {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0.0,
            'total_pnl': 0.0,
            'profit_factor': None,
            'avg_win': None,
            'avg_loss': None,
            'passed': False,
            'data_source': data_source,
            'period_days': period_days,
            'trades': [],
            'equity_curve': [],
            'symbol_breakdown': {},
        }

    # Compute equity curve
    sorted_trades = sorted(all_trades, key=lambda t: t.get('exit_time', 0))
    cumulative = 0
    equity_curve = []
    for t in sorted_trades:
        cumulative += t['pnl_pct']
        equity_curve.append({'time': t.get('exit_time', 0), 'value': round(cumulative, 6)})

    # Compute symbol breakdown
    symbol_breakdown = {}
    for t in all_trades:
        sym = t.get('symbol', 'UNKNOWN')
        if sym not in symbol_breakdown:
            symbol_breakdown[sym] = {'total': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0}
        symbol_breakdown[sym]['total'] += 1
        if t['result'] == 'TP':
            symbol_breakdown[sym]['wins'] += 1
        else:
            symbol_breakdown[sym]['losses'] += 1
        symbol_breakdown[sym]['pnl'] += t['pnl_pct']
    for sym in symbol_breakdown:
        s = symbol_breakdown[sym]
        s['win_rate'] = s['wins'] / s['total'] if s['total'] > 0 else 0
        s['pnl'] = round(s['pnl'], 6)

    wins = [t for t in all_trades if t['result'] == 'TP']
    losses = [t for t in all_trades if t['result'] == 'SL']

    total_trades = len(all_trades)
    winning_trades = len(wins)
    losing_trades = len(losses)
    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

    total_pnl = sum(t['pnl_pct'] for t in all_trades)
    avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else None
    avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else None

    gross_profit = sum(t['pnl_pct'] for t in wins) if wins else 0.0
    gross_loss = abs(sum(t['pnl_pct'] for t in losses)) if losses else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

    passed = win_rate >= MIN_WIN_RATE

    result = {
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'losing_trades': losing_trades,
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'profit_factor': profit_factor,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'passed': passed,
        'data_source': data_source,
        'period_days': period_days,
        'trades': all_trades,
        'equity_curve': equity_curve,
        'symbol_breakdown': symbol_breakdown,
    }

    logger.info(f"MR Backtest complete: {result}")
    return result
