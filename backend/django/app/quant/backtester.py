import logging
import traceback

import pandas as pd
import numpy as np

from app.utils.api.data import fetch_data_pos
from app.utils.api.yahoo import fetch_yahoo_data
from app.quant.indicators.scalping import ema_crossover, rsi, atr
from app.quant.algorithms.scalping.config import (
    PAIRS,
    MAIN_TIMEFRAME,
    EMA_FAST,
    EMA_SLOW,
    RSI_PERIOD,
    ATR_PERIOD,
    SL_ATR_MULTIPLIER,
    TP_ATR_MULTIPLIER,
    MIN_WIN_RATE,
)

logger = logging.getLogger(__name__)

YAHOO_PERIOD = '60d'
YAHOO_INTERVAL = '5m'


def _simulate_trades(df):
    """
    Walk forward through candle data and simulate trades based on EMA crossover + RSI.
    Returns a list of trade result dicts.
    """
    df = df.copy()
    df['ema_signal'] = ema_crossover(df, fast=EMA_FAST, slow=EMA_SLOW)
    df['rsi'] = rsi(df, period=RSI_PERIOD)
    df['atr'] = atr(df, period=ATR_PERIOD)

    trades = []
    in_trade = False
    entry_price = 0
    sl_price = 0
    tp_price = 0
    trade_type = None

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        # If in a trade, check for SL/TP hit
        if in_trade:
            if trade_type == 'BUY':
                # Check SL hit (low touches SL)
                if row['low'] <= sl_price:
                    pnl = sl_price - entry_price
                    trades.append({'type': trade_type, 'entry': entry_price, 'exit': sl_price, 'pnl_pct': pnl / entry_price, 'result': 'SL'})
                    in_trade = False
                    continue
                # Check TP hit (high touches TP)
                if row['high'] >= tp_price:
                    pnl = tp_price - entry_price
                    trades.append({'type': trade_type, 'entry': entry_price, 'exit': tp_price, 'pnl_pct': pnl / entry_price, 'result': 'TP'})
                    in_trade = False
                    continue
            elif trade_type == 'SELL':
                # Check SL hit (high touches SL)
                if row['high'] >= sl_price:
                    pnl = entry_price - sl_price
                    trades.append({'type': trade_type, 'entry': entry_price, 'exit': sl_price, 'pnl_pct': pnl / entry_price, 'result': 'SL'})
                    in_trade = False
                    continue
                # Check TP hit (low touches TP)
                if row['low'] <= tp_price:
                    pnl = entry_price - tp_price
                    trades.append({'type': trade_type, 'entry': entry_price, 'exit': tp_price, 'pnl_pct': pnl / entry_price, 'result': 'TP'})
                    in_trade = False
                    continue
            continue

        # Check for entry signal on previous bar
        signal = prev['ema_signal']
        rsi_val = prev['rsi']
        atr_val = prev['atr']

        if pd.isna(rsi_val) or pd.isna(atr_val) or atr_val <= 0:
            continue

        if signal == 'bull_cross' and 30 <= rsi_val <= 65:
            trade_type = 'BUY'
            entry_price = row['open']
            sl_price = entry_price - (atr_val * SL_ATR_MULTIPLIER)
            tp_price = entry_price + (atr_val * TP_ATR_MULTIPLIER)
            in_trade = True
        elif signal == 'bear_cross' and 35 <= rsi_val <= 70:
            trade_type = 'SELL'
            entry_price = row['open']
            sl_price = entry_price + (atr_val * SL_ATR_MULTIPLIER)
            tp_price = entry_price - (atr_val * TP_ATR_MULTIPLIER)
            in_trade = True

    return trades


def run_backtest():
    """
    Run backtest across all pairs using historical M5 data.
    Primary: Yahoo Finance (up to 60 days of 5m data).
    Fallback: MT5 API (500 bars).
    Returns a dict with aggregated results.
    """
    all_trades = []
    data_source = 'YAHOO'
    period_days = 60

    for pair in PAIRS:
        try:
            # Primary: Yahoo Finance
            df = fetch_yahoo_data(pair, period=YAHOO_PERIOD, interval=YAHOO_INTERVAL)
            source = 'yahoo'

            # Fallback: MT5
            if df is None or df.empty or len(df) < EMA_SLOW + 10:
                logger.info(f"Backtest {pair}: Yahoo data insufficient, falling back to MT5")
                df = fetch_data_pos(pair, MAIN_TIMEFRAME, 500)
                source = 'mt5'
                if source == 'mt5' and data_source == 'YAHOO':
                    data_source = 'MIXED'

            if df is None or df.empty or len(df) < EMA_SLOW + 10:
                logger.info(f"Backtest: insufficient data for {pair} (both sources)")
                continue

            trades = _simulate_trades(df)
            for t in trades:
                t['symbol'] = pair
            all_trades.extend(trades)
            logger.info(f"Backtest {pair}: {len(trades)} trades simulated ({source}, {len(df)} bars)")

        except Exception as e:
            logger.error(f"Backtest error for {pair}: {e}\n{traceback.format_exc()}")

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
        }

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
    }

    logger.info(f"Backtest complete: {result}")
    return result


def run_and_store_backtest():
    """
    Run backtest and store the result in the database.
    Returns the BacktestResult instance.
    """
    from app.nexus.models import StrategyConfig, BacktestResult

    strategy = StrategyConfig.objects.filter(name='SCALPING').first()
    if strategy is None:
        logger.error("SCALPING strategy not found, cannot store backtest result.")
        return None

    result = run_backtest()

    backtest = BacktestResult.objects.create(
        strategy=strategy,
        total_trades=result['total_trades'],
        winning_trades=result['winning_trades'],
        losing_trades=result['losing_trades'],
        win_rate=result['win_rate'],
        total_pnl=result['total_pnl'],
        profit_factor=result['profit_factor'],
        avg_win=result['avg_win'],
        avg_loss=result['avg_loss'],
        passed=result['passed'],
        data_source=result.get('data_source', 'MT5'),
        period_days=result.get('period_days', 7),
    )

    logger.info(f"Backtest result stored: id={backtest.id}, passed={backtest.passed}")
    return backtest
