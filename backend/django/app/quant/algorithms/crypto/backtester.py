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
from .strategies import get_all_strategies, get_strategy, STRATEGY_REGISTRY

logger = logging.getLogger('app.crypto')


def _fetch_ohlcv(symbol: str, interval: str = '1h', limit: int = 500) -> dict:
    """Fetch candle data and return as dict of pd.Series."""
    candles = get_candles(symbol, interval=interval, limit=limit)
    if not candles:
        return None

    data = {
        'close': pd.Series([float(c['c']) for c in candles]),
        'high': pd.Series([float(c['h']) for c in candles]),
        'low': pd.Series([float(c['l']) for c in candles]),
        'open': pd.Series([float(c['o']) for c in candles]),
        'volume': pd.Series([float(c.get('v', 0)) for c in candles]),
        'timestamps': [c.get('t', i) for i, c in enumerate(candles)],
    }
    return data


def _compute_stats(trades: list, equity_curve: list, capital: float) -> dict:
    """Compute detailed performance statistics from trade list."""
    if not trades:
        return {
            'total_trades': 0, 'winning_trades': 0, 'losing_trades': 0,
            'win_rate': 0, 'total_pnl': 0, 'profit_factor': None,
            'avg_win': None, 'avg_loss': None, 'max_drawdown': 0,
            'sharpe_ratio': None, 'avg_trade_pnl': None,
            'max_consecutive_wins': 0, 'max_consecutive_losses': 0,
            'expectancy': 0,
        }

    winning = [t for t in trades if t['pnl'] > 0]
    losing = [t for t in trades if t['pnl'] <= 0]
    total_pnl = sum(t['pnl'] for t in trades)
    total_wins = sum(t['pnl'] for t in winning)
    total_losses = abs(sum(t['pnl'] for t in losing))

    # Max drawdown
    peak = capital
    max_dd = 0
    for point in equity_curve:
        eq = point['equity']
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

    # Sharpe ratio (annualized, using hourly bars → sqrt(8760))
    if len(equity_curve) > 1:
        returns = []
        for i in range(1, len(equity_curve)):
            prev_eq = equity_curve[i - 1]['equity']
            curr_eq = equity_curve[i]['equity']
            if prev_eq > 0:
                returns.append((curr_eq - prev_eq) / prev_eq)
        if returns:
            mean_ret = np.mean(returns)
            std_ret = np.std(returns)
            sharpe = (mean_ret / std_ret * np.sqrt(8760)) if std_ret > 0 else None
        else:
            sharpe = None
    else:
        sharpe = None

    # Consecutive wins/losses
    max_consec_w = max_consec_l = consec_w = consec_l = 0
    for t in trades:
        if t['pnl'] > 0:
            consec_w += 1
            consec_l = 0
        else:
            consec_l += 1
            consec_w = 0
        max_consec_w = max(max_consec_w, consec_w)
        max_consec_l = max(max_consec_l, consec_l)

    win_rate = len(winning) / len(trades)
    avg_w = total_wins / len(winning) if winning else 0
    avg_l = total_losses / len(losing) if losing else 0
    expectancy = (win_rate * avg_w) - ((1 - win_rate) * avg_l)

    return {
        'total_trades': len(trades),
        'winning_trades': len(winning),
        'losing_trades': len(losing),
        'win_rate': round(win_rate, 4),
        'total_pnl': round(total_pnl, 2),
        'profit_factor': round(total_wins / total_losses, 2) if total_losses > 0 else None,
        'avg_win': round(avg_w, 2) if winning else None,
        'avg_loss': round(avg_l, 2) if losing else None,
        'max_drawdown': round(max_dd, 4),
        'sharpe_ratio': round(sharpe, 2) if sharpe is not None else None,
        'avg_trade_pnl': round(total_pnl / len(trades), 2),
        'max_consecutive_wins': max_consec_w,
        'max_consecutive_losses': max_consec_l,
        'expectancy': round(expectancy, 2),
    }


def _run_backtest_engine(strategy, data: dict, capital: float,
                          sl_pct: float = None, tp_pct: float = None,
                          max_position_pct: float = 0.10) -> dict:
    """Generic backtest engine that works with any BaseStrategy subclass."""
    close = data['close']

    exit_params = strategy.get_exit_params()
    if sl_pct is None:
        sl_pct = exit_params['stop_loss_pct']
    if tp_pct is None:
        tp_pct = exit_params['take_profit_pct']

    start_idx = max(strategy.min_bars, 2)
    if len(close) < start_idx + 10:
        return None

    trades = []
    equity_curve = []
    equity = capital
    position = None

    for i in range(start_idx, len(close)):
        # Build data slice up to current bar
        data_slice = {
            'close': close.iloc[:i + 1],
            'high': data['high'].iloc[:i + 1],
            'low': data['low'].iloc[:i + 1],
            'volume': data['volume'].iloc[:i + 1],
        }
        signal = strategy.generate_signal(data_slice)
        current_price = close.iloc[i]

        # Check exits
        if position is not None:
            should_exit = False
            reason = ''

            if position['side'] == 'LONG':
                if current_price <= position['entry_price'] * (1 - sl_pct):
                    should_exit, reason = True, 'stop_loss'
                elif current_price >= position['entry_price'] * (1 + tp_pct):
                    should_exit, reason = True, 'take_profit'
                elif signal <= 0:
                    should_exit, reason = True, 'signal_reversal'
            else:
                if current_price >= position['entry_price'] * (1 + sl_pct):
                    should_exit, reason = True, 'stop_loss'
                elif current_price <= position['entry_price'] * (1 - tp_pct):
                    should_exit, reason = True, 'take_profit'
                elif signal >= 0:
                    should_exit, reason = True, 'signal_reversal'

            if should_exit:
                if position['side'] == 'LONG':
                    pnl = (current_price - position['entry_price']) * position['size']
                else:
                    pnl = (position['entry_price'] - current_price) * position['size']
                equity += pnl
                trades.append({
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
            size = abs(capital * max_position_pct / current_price)
            if size > 0:
                position = {
                    'side': 'LONG' if signal > 0 else 'SHORT',
                    'entry_price': current_price,
                    'size': size,
                    'entry_idx': i,
                }

        equity_curve.append({'idx': i, 'equity': round(equity, 2)})

    # Close remaining position
    if position is not None:
        current_price = close.iloc[-1]
        if position['side'] == 'LONG':
            pnl = (current_price - position['entry_price']) * position['size']
        else:
            pnl = (position['entry_price'] - current_price) * position['size']
        equity += pnl
        trades.append({
            'side': position['side'],
            'entry_price': position['entry_price'],
            'exit_price': current_price,
            'size': position['size'],
            'pnl': round(pnl, 2),
            'reason': 'end_of_data',
            'cumulative_pnl': round(equity - capital, 2),
        })

    return {'trades': trades, 'equity_curve': equity_curve}


# ─────────────────────────────────────────────────────────────
# Legacy backtest function (original MomentumStrategy)
# ─────────────────────────────────────────────────────────────
def backtest_symbol(symbol: str, capital: float = None) -> dict:
    """Run backtest for a single symbol using the legacy MomentumStrategy."""
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

    trades = []
    equity_curve = []
    equity = capital
    position = None

    for i in range(CRYPTO_SLOW_MA, len(closes)):
        price_slice = closes.iloc[:i + 1]
        signal = strategy.generate_signal(price_slice)
        current_price = closes.iloc[i]

        if position is not None:
            should_exit = False
            reason = ''

            if position['side'] == 'LONG' and current_price <= position['entry_price'] * (1 - CRYPTO_STOP_LOSS_PCT):
                should_exit, reason = True, 'stop_loss'
            elif position['side'] == 'SHORT' and current_price >= position['entry_price'] * (1 + CRYPTO_STOP_LOSS_PCT):
                should_exit, reason = True, 'stop_loss'

            if not should_exit:
                if position['side'] == 'LONG' and current_price >= position['entry_price'] * (1 + CRYPTO_TAKE_PROFIT_PCT):
                    should_exit, reason = True, 'take_profit'
                elif position['side'] == 'SHORT' and current_price <= position['entry_price'] * (1 - CRYPTO_TAKE_PROFIT_PCT):
                    should_exit, reason = True, 'take_profit'

            if not should_exit:
                if position['side'] == 'LONG' and signal <= 0:
                    should_exit, reason = True, 'signal_reversal'
                elif position['side'] == 'SHORT' and signal >= 0:
                    should_exit, reason = True, 'signal_reversal'

            if should_exit:
                if position['side'] == 'LONG':
                    pnl = (current_price - position['entry_price']) * position['size']
                else:
                    pnl = (position['entry_price'] - current_price) * position['size']
                equity += pnl
                trades.append({
                    'symbol': symbol, 'side': position['side'],
                    'entry_price': position['entry_price'],
                    'exit_price': current_price,
                    'size': position['size'],
                    'pnl': round(pnl, 2), 'reason': reason,
                    'cumulative_pnl': round(equity - capital, 2),
                })
                position = None

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

    if position is not None:
        current_price = closes.iloc[-1]
        if position['side'] == 'LONG':
            pnl = (current_price - position['entry_price']) * position['size']
        else:
            pnl = (position['entry_price'] - current_price) * position['size']
        equity += pnl
        trades.append({
            'symbol': symbol, 'side': position['side'],
            'entry_price': position['entry_price'],
            'exit_price': current_price,
            'size': position['size'],
            'pnl': round(pnl, 2), 'reason': 'end_of_data',
            'cumulative_pnl': round(equity - capital, 2),
        })

    winning = [t for t in trades if t['pnl'] > 0]
    losing = [t for t in trades if t['pnl'] <= 0]
    total_pnl = sum(t['pnl'] for t in trades)
    total_wins = sum(t['pnl'] for t in winning)
    total_losses = abs(sum(t['pnl'] for t in losing))

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


# ─────────────────────────────────────────────────────────────
# Multi-strategy backtester
# ─────────────────────────────────────────────────────────────
def backtest_strategy(strategy_name: str, symbol: str, capital: float = None,
                       interval: str = '1h', limit: int = 500) -> dict:
    """Backtest a single strategy on a single symbol."""
    if capital is None:
        capital = CRYPTO_CAPITAL_USD

    strategy = get_strategy(strategy_name)
    data = _fetch_ohlcv(symbol, interval=interval, limit=limit)
    if data is None or len(data['close']) < strategy.min_bars + 10:
        return {
            'symbol': symbol,
            'strategy': strategy_name,
            'error': 'insufficient data',
            'total_pnl': 0,
            'trades': [],
        }

    result = _run_backtest_engine(strategy, data, capital)
    if result is None:
        return {
            'symbol': symbol,
            'strategy': strategy_name,
            'error': 'insufficient data for strategy',
            'total_pnl': 0,
            'trades': [],
        }

    stats = _compute_stats(result['trades'], result['equity_curve'], capital)

    return {
        'symbol': symbol,
        'strategy': strategy_name,
        'strategy_description': strategy.description,
        **stats,
        'trades': result['trades'],
        'equity_curve': result['equity_curve'],
    }


def backtest_all_strategies(symbols: list = None, capital: float = None,
                             interval: str = '1h', limit: int = 500) -> list:
    """Run all strategies across all symbols. Returns list of result dicts."""
    if symbols is None:
        symbols = CRYPTO_PAIRS
    if capital is None:
        capital = CRYPTO_CAPITAL_USD

    all_results = []
    strategy_names = list(STRATEGY_REGISTRY.keys())

    for symbol in symbols:
        data = _fetch_ohlcv(symbol, interval=interval, limit=limit)
        if data is None:
            logger.warning(f"No data for {symbol}, skipping")
            continue

        for name in strategy_names:
            strategy = get_strategy(name)
            if len(data['close']) < strategy.min_bars + 10:
                all_results.append({
                    'symbol': symbol,
                    'strategy': name,
                    'error': 'insufficient data',
                    'total_pnl': 0,
                })
                continue

            result = _run_backtest_engine(strategy, data, capital)
            if result is None:
                continue

            stats = _compute_stats(result['trades'], result['equity_curve'], capital)
            all_results.append({
                'symbol': symbol,
                'strategy': name,
                'strategy_description': strategy.description,
                **stats,
                'trades': result['trades'],
                'equity_curve': result['equity_curve'],
            })

            logger.info(
                f"Backtest {name}/{symbol}: {stats['total_trades']} trades, "
                f"PnL=${stats['total_pnl']:.2f}, WR={stats['win_rate']:.1%}, "
                f"Sharpe={stats.get('sharpe_ratio', 'N/A')}"
            )

    return all_results


def run_and_store_all_backtests(symbols: list = None) -> list:
    """Run all strategies, store results in DB, return records."""
    from app.crypto.models import CryptoBacktestResult

    results = backtest_all_strategies(symbols)
    records = []

    for r in results:
        if 'error' in r:
            continue

        total_pnl = r['total_pnl']
        passed = total_pnl > 0 and r.get('win_rate', 0) > 0.4

        record = CryptoBacktestResult.objects.create(
            symbol=r['symbol'],
            strategy_name=r['strategy'],
            total_trades=r['total_trades'],
            winning_trades=r['winning_trades'],
            losing_trades=r['losing_trades'],
            win_rate=r['win_rate'],
            total_pnl=total_pnl,
            profit_factor=r.get('profit_factor'),
            avg_win=r.get('avg_win'),
            avg_loss=r.get('avg_loss'),
            max_drawdown=r.get('max_drawdown'),
            passed=passed,
            capital_usd=CRYPTO_CAPITAL_USD,
            trades=r.get('trades', []),
            equity_curve=r.get('equity_curve', []),
        )
        records.append(record)
        logger.info(
            f"Stored: {r['strategy']}/{r['symbol']} PnL=${total_pnl:.2f} "
            f"passed={passed}"
        )

    return records


def run_and_store_backtest(symbol: str = None):
    """Run legacy momentum backtest and store result in DB."""
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
