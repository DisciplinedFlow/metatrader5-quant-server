import logging
import traceback

import pandas as pd
import numpy as np

from app.utils.api.data import fetch_data_pos
from app.utils.api.yahoo import fetch_yahoo_data
from app.quant.indicators.scalping import ema_crossover, rsi, atr
from app.quant.indicators.mean_reversion import mean_reversion

logger = logging.getLogger(__name__)

YAHOO_PERIOD = '60d'

INDICATOR_REGISTRY = {
    'EMA_CROSSOVER': lambda df, params: ema_crossover(df, fast=params.get('fast', 9), slow=params.get('slow', 21)),
    'RSI': lambda df, params: rsi(df, period=params.get('period', 14)),
    'ATR': lambda df, params: atr(df, period=params.get('period', 14)),
    'BOLLINGER_BANDS': lambda df, params: mean_reversion(df, window=params.get('window', 20), num_std_dev=params.get('num_std_dev', 2)),
}

CONDITION_OPS = {
    'eq': lambda a, b: a == b,
    'gte': lambda a, b: float(a) >= float(b),
    'lte': lambda a, b: float(a) <= float(b),
    'gt': lambda a, b: float(a) > float(b),
    'lt': lambda a, b: float(a) < float(b),
}

TIMEFRAME_YAHOO_INTERVAL = {
    'M1': '1m', 'M5': '5m', 'M15': '15m',
    'H1': '1h', 'H4': '4h', 'D1': '1d',
}


def _bar_to_unix(df, idx):
    ts = df.index[idx] if hasattr(df.index[idx], 'timestamp') else pd.Timestamp(df.iloc[idx].get('time', 0))
    return int(ts.timestamp()) if hasattr(ts, 'timestamp') else 0


class GenericBacktester:
    def __init__(self, definition):
        self.definition = definition
        self.timeframe = definition.get('timeframe', 'M5')
        self.pairs = definition.get('pairs', [])
        self.indicators = definition.get('indicators', [])
        self.entry_rules = definition.get('entry_rules', {})
        self.exit_rules = definition.get('exit_rules', {})
        self.min_win_rate = definition.get('min_win_rate', 0.55)

    def _compute_indicators(self, df):
        """Compute all declared indicators and store as columns."""
        results = {}
        for ind in self.indicators:
            ind_type = ind['type']
            params = ind.get('params', {})
            if ind_type in INDICATOR_REGISTRY:
                results[ind_type] = INDICATOR_REGISTRY[ind_type](df, params)
                df[ind_type] = results[ind_type]
        return df

    def _check_rules(self, df, idx, rules):
        """Check if all conditions in a rule set are met at bar idx."""
        for rule in rules:
            indicator = rule['indicator']
            condition = rule['condition']
            value = rule['value']
            if indicator not in df.columns:
                return False
            actual = df[indicator].iloc[idx]
            if pd.isna(actual):
                return False
            op = CONDITION_OPS.get(condition)
            if op is None:
                return False
            try:
                if not op(actual, value):
                    return False
            except (ValueError, TypeError):
                return False
        return True

    def _simulate_trades(self, df):
        """Walk-forward simulation with generic entry/exit rules."""
        df = self._compute_indicators(df)

        exit_type = self.exit_rules.get('type', 'ATR_BASED')
        exit_params = self.exit_rules.get('params', {})

        if exit_type == 'ATR_BASED':
            atr_period = exit_params.get('atr_period', 14)
            sl_mult = exit_params.get('sl_multiplier', 1.5)
            tp_mult = exit_params.get('tp_multiplier', 2.0)
            df['_atr'] = atr(df, period=atr_period)
        else:
            sl_pct = exit_params.get('sl_pct', 0.5) / 100
            tp_pct = exit_params.get('tp_pct', 0.5) / 100

        long_rules = self.entry_rules.get('long', [])
        short_rules = self.entry_rules.get('short', [])

        trades = []
        in_trade = False
        entry_price = 0
        sl_price = 0
        tp_price = 0
        trade_type = None
        entry_bar_idx = 0

        for i in range(1, len(df)):
            row = df.iloc[i]

            if in_trade:
                trade_base = {'type': trade_type, 'entry': entry_price, 'sl': sl_price, 'tp': tp_price, 'signal': entry_signal, 'entry_time': _bar_to_unix(df, entry_bar_idx)}
                if trade_type == 'BUY':
                    if row['low'] <= sl_price:
                        pnl = sl_price - entry_price
                        trades.append({**trade_base, 'exit': sl_price,
                                       'pnl_pct': pnl / entry_price, 'result': 'SL',
                                       'exit_time': _bar_to_unix(df, i)})
                        in_trade = False
                        continue
                    if row['high'] >= tp_price:
                        pnl = tp_price - entry_price
                        trades.append({**trade_base, 'exit': tp_price,
                                       'pnl_pct': pnl / entry_price, 'result': 'TP',
                                       'exit_time': _bar_to_unix(df, i)})
                        in_trade = False
                        continue
                elif trade_type == 'SELL':
                    if row['high'] >= sl_price:
                        pnl = entry_price - sl_price
                        trades.append({**trade_base, 'exit': sl_price,
                                       'pnl_pct': pnl / entry_price, 'result': 'SL',
                                       'exit_time': _bar_to_unix(df, i)})
                        in_trade = False
                        continue
                    if row['low'] <= tp_price:
                        pnl = entry_price - tp_price
                        trades.append({**trade_base, 'exit': tp_price,
                                       'pnl_pct': pnl / entry_price, 'result': 'TP',
                                       'exit_time': _bar_to_unix(df, i)})
                        in_trade = False
                        continue
                continue

            prev_idx = i - 1
            enter_long = long_rules and self._check_rules(df, prev_idx, long_rules)
            enter_short = short_rules and self._check_rules(df, prev_idx, short_rules)

            if enter_long:
                trade_type = 'BUY'
                entry_price = row['open']
                entry_bar_idx = i
                entry_signal = 'Long rules met'
                if exit_type == 'ATR_BASED':
                    atr_val = df['_atr'].iloc[prev_idx]
                    if pd.isna(atr_val) or atr_val <= 0:
                        continue
                    sl_price = entry_price - (atr_val * sl_mult)
                    tp_price = entry_price + (atr_val * tp_mult)
                else:
                    sl_price = entry_price * (1 - sl_pct)
                    tp_price = entry_price * (1 + tp_pct)
                in_trade = True
            elif enter_short:
                trade_type = 'SELL'
                entry_price = row['open']
                entry_bar_idx = i
                entry_signal = 'Short rules met'
                if exit_type == 'ATR_BASED':
                    atr_val = df['_atr'].iloc[prev_idx]
                    if pd.isna(atr_val) or atr_val <= 0:
                        continue
                    sl_price = entry_price + (atr_val * sl_mult)
                    tp_price = entry_price - (atr_val * tp_mult)
                else:
                    sl_price = entry_price * (1 + sl_pct)
                    tp_price = entry_price * (1 - tp_pct)
                in_trade = True

        return trades

    def run(self):
        """Run backtest across all pairs. Returns result dict."""
        all_trades = []
        data_source = 'YAHOO'
        period_days = 60
        yahoo_interval = TIMEFRAME_YAHOO_INTERVAL.get(self.timeframe, '5m')

        for pair in self.pairs:
            try:
                df = fetch_yahoo_data(pair, period=YAHOO_PERIOD, interval=yahoo_interval)
                source = 'yahoo'

                if df is None or df.empty or len(df) < 30:
                    logger.info(f"Generic Backtest {pair}: Yahoo insufficient, falling back to MT5")
                    df = fetch_data_pos(pair, self.timeframe, 500)
                    source = 'mt5'
                    if source == 'mt5' and data_source == 'YAHOO':
                        data_source = 'MIXED'

                if df is None or df.empty or len(df) < 30:
                    logger.info(f"Generic Backtest: insufficient data for {pair}")
                    continue

                trades = self._simulate_trades(df)
                for t in trades:
                    t['symbol'] = pair
                all_trades.extend(trades)
                logger.info(f"Generic Backtest {pair}: {len(trades)} trades ({source}, {len(df)} bars)")

            except Exception as e:
                logger.error(f"Generic Backtest error for {pair}: {e}\n{traceback.format_exc()}")

        if not all_trades:
            return {
                'total_trades': 0, 'winning_trades': 0, 'losing_trades': 0,
                'win_rate': 0.0, 'total_pnl': 0.0, 'profit_factor': None,
                'avg_win': None, 'avg_loss': None, 'passed': False,
                'data_source': data_source, 'period_days': period_days,
                'trades': [], 'equity_curve': [], 'symbol_breakdown': {},
            }

        # Equity curve
        sorted_trades = sorted(all_trades, key=lambda t: t.get('exit_time', 0))
        cumulative = 0
        equity_curve = []
        for t in sorted_trades:
            cumulative += t['pnl_pct']
            equity_curve.append({'time': t.get('exit_time', 0), 'value': round(cumulative, 6)})

        # Symbol breakdown
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
        avg_win = float(np.mean([t['pnl_pct'] for t in wins])) if wins else None
        avg_loss = float(np.mean([t['pnl_pct'] for t in losses])) if losses else None
        gross_profit = sum(t['pnl_pct'] for t in wins) if wins else 0.0
        gross_loss = abs(sum(t['pnl_pct'] for t in losses)) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
        passed = win_rate >= self.min_win_rate

        return {
            'total_trades': total_trades, 'winning_trades': winning_trades,
            'losing_trades': losing_trades, 'win_rate': win_rate,
            'total_pnl': total_pnl, 'profit_factor': profit_factor,
            'avg_win': avg_win, 'avg_loss': avg_loss, 'passed': passed,
            'data_source': data_source, 'period_days': period_days,
            'trades': all_trades, 'equity_curve': equity_curve,
            'symbol_breakdown': symbol_breakdown,
        }
