import logging
import pandas as pd
import numpy as np

from .config import (
    CRYPTO_PAIRS, CRYPTO_CAPITAL_USD, CRYPTO_FAST_MA, CRYPTO_SLOW_MA,
    CRYPTO_LOOKBACK, CRYPTO_MAX_POSITION_PCT, CRYPTO_STOP_LOSS_PCT,
    CRYPTO_TAKE_PROFIT_PCT,
)
from .client import get_candles
from .strategy import MomentumStrategy

logger = logging.getLogger('app.crypto')


def backtest_symbol(symbol: str, capital: float = None) -> dict:
    """Run backtest for a single symbol using historical candle data."""
    if capital is None:
        capital = CRYPTO_CAPITAL_USD

    strategy = MomentumStrategy(
        signal_type='ma_crossover',
        fast_ma=CRYPTO_FAST_MA,
        slow_ma=CRYPTO_SLOW_MA,
        lookback=CRYPTO_LOOKBACK,
        max_position_pct=CRYPTO_MAX_POSITION_PCT,
    )

    candles = get_candles(symbol, interval='1h', limit=500)
    if not candles or len(candles) < CRYPTO_SLOW_MA + 10:
        return {'symbol': symbol, 'trades': [], 'total_pnl': 0, 'error': 'insufficient data'}

    closes = pd.Series([float(c['c']) for c in candles])
    timestamps = [c.get('t', i) for i, c in enumerate(candles)]

    trades = []
    equity_curve = []
    equity = capital
    position = None  # {'side': 'LONG'/'SHORT', 'entry_price': float, 'size': float, 'entry_idx': int}

    for i in range(CRYPTO_SLOW_MA, len(closes)):
        price_slice = closes.iloc[:i + 1]
        signal = strategy.generate_signal(price_slice)
        current_price = closes.iloc[i]

        # Check exits first
        if position is not None:
            should_exit = False
            reason = ''

            # Stop loss
            if position['side'] == 'LONG' and current_price <= position['entry_price'] * (1 - CRYPTO_STOP_LOSS_PCT):
                should_exit = True
                reason = 'stop_loss'
            elif position['side'] == 'SHORT' and current_price >= position['entry_price'] * (1 + CRYPTO_STOP_LOSS_PCT):
                should_exit = True
                reason = 'stop_loss'

            # Take profit
            if not should_exit:
                if position['side'] == 'LONG' and current_price >= position['entry_price'] * (1 + CRYPTO_TAKE_PROFIT_PCT):
                    should_exit = True
                    reason = 'take_profit'
                elif position['side'] == 'SHORT' and current_price <= position['entry_price'] * (1 - CRYPTO_TAKE_PROFIT_PCT):
                    should_exit = True
                    reason = 'take_profit'

            # Signal reversal
            if not should_exit:
                if position['side'] == 'LONG' and signal <= 0:
                    should_exit = True
                    reason = 'signal_reversal'
                elif position['side'] == 'SHORT' and signal >= 0:
                    should_exit = True
                    reason = 'signal_reversal'

            if should_exit:
                if position['side'] == 'LONG':
                    pnl = (current_price - position['entry_price']) * position['size']
                else:
                    pnl = (position['entry_price'] - current_price) * position['size']

                equity += pnl
                trades.append({
                    'symbol': symbol,
                    'side': position['side'],
                    'entry_price': position['entry_price'],
                    'exit_price': current_price,
                    'size': position['size'],
                    'pnl': round(pnl, 2),
                    'reason': reason,
                    'cumulative_pnl': round(equity - capital, 2),
                })
                position = None

        # Check entries
        if position is None and signal != 0:
            size = abs(strategy.calculate_position_size(signal, equity, current_price))
            if size > 0:
                position = {
                    'side': 'LONG' if signal > 0 else 'SHORT',
                    'entry_price': current_price,
                    'size': size,
                    'entry_idx': i,
                }

        equity_curve.append({'idx': i, 'equity': round(equity, 2)})

    # Close any remaining position at last price
    if position is not None:
        current_price = closes.iloc[-1]
        if position['side'] == 'LONG':
            pnl = (current_price - position['entry_price']) * position['size']
        else:
            pnl = (position['entry_price'] - current_price) * position['size']
        equity += pnl
        trades.append({
            'symbol': symbol,
            'side': position['side'],
            'entry_price': position['entry_price'],
            'exit_price': current_price,
            'size': position['size'],
            'pnl': round(pnl, 2),
            'reason': 'end_of_data',
            'cumulative_pnl': round(equity - capital, 2),
        })

    winning = [t for t in trades if t['pnl'] > 0]
    losing = [t for t in trades if t['pnl'] <= 0]
    total_pnl = sum(t['pnl'] for t in trades)
    total_wins = sum(t['pnl'] for t in winning)
    total_losses = abs(sum(t['pnl'] for t in losing))

    # Max drawdown
    peak = capital
    max_dd = 0
    for point in equity_curve:
        if point['equity'] > peak:
            peak = point['equity']
        dd = (peak - point['equity']) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

    return {
        'symbol': symbol,
        'total_trades': len(trades),
        'winning_trades': len(winning),
        'losing_trades': len(losing),
        'win_rate': len(winning) / len(trades) if trades else 0,
        'total_pnl': round(total_pnl, 2),
        'profit_factor': round(total_wins / total_losses, 2) if total_losses > 0 else None,
        'avg_win': round(total_wins / len(winning), 2) if winning else None,
        'avg_loss': round(total_losses / len(losing), 2) if losing else None,
        'max_drawdown': round(max_dd, 4),
        'trades': trades,
        'equity_curve': equity_curve,
    }


def run_and_store_backtest(symbol: str = None):
    """Run backtest and store result in DB."""
    from app.crypto.models import CryptoBacktestResult

    target = symbol or (CRYPTO_PAIRS[0] if CRYPTO_PAIRS else 'BTC')
    result = backtest_symbol(target)

    if 'error' in result:
        logger.warning(f"Backtest skipped for {target}: {result['error']}")
        return None

    total_pnl = result['total_pnl']
    passed = total_pnl > 0 and result.get('win_rate', 0) > 0.4

    record = CryptoBacktestResult.objects.create(
        symbol=target,
        strategy_name='momentum',
        total_trades=result['total_trades'],
        winning_trades=result['winning_trades'],
        losing_trades=result['losing_trades'],
        win_rate=result['win_rate'],
        total_pnl=total_pnl,
        profit_factor=result.get('profit_factor'),
        avg_win=result.get('avg_win'),
        avg_loss=result.get('avg_loss'),
        max_drawdown=result.get('max_drawdown'),
        passed=passed,
        capital_usd=CRYPTO_CAPITAL_USD,
        trades=result['trades'],
        equity_curve=result['equity_curve'],
    )

    logger.info(f"Backtest stored: {target} pnl=${total_pnl:.2f} passed={passed}")
    return record
