import logging
import traceback

import pandas as pd
import numpy as np

from app.utils.api.data import fetch_data_pos
from app.utils.api.yahoo import fetch_yahoo_data
from app.quant.indicators.scalping import ema_crossover, rsi, atr
from app.quant.indicators.mean_reversion import mean_reversion
from app.quant.indicators.cvd import cvd_divergence, cvd_raw, cvd_leading, cvd_extremes, cvd_mtf, cvd_cross_market
from app.quant.indicators.momentum import ema_ribbon_pullback
from app.quant.indicators.smc import (
    market_structure, fair_value_gap, order_block,
    liquidity_sweep, smc_confluence,
)
from app.quant.indicators.smc_detector import (
    _registry_fvg, _registry_ob, _registry_structure,
    _registry_liquidity, _registry_confluence,
)
# Pair-specific indicators
from app.quant.indicators.session_range import (
    asian_range, sweep_fade_signal, session_filter, london_killzone_active,
)
from app.quant.indicators.donchian import (
    donchian_channel, donchian_trend_filter, donchian_width,
)
from app.quant.indicators.gold_silver_ratio import (
    gold_silver_ratio, momentum_trend,
)
from app.quant.indicators.session_hybrid import (
    asian_mean_reversion, london_breakout, session_strategy_router,
    commodity_correlation_filter,
)
from app.quant.indicators.energy import (
    energy_trend_follow, energy_range_detect, energy_range_trade,
    energy_breakout, keltner_channel, brent_wti_spread,
)

logger = logging.getLogger(__name__)

YAHOO_PERIOD = '60d'

INDICATOR_REGISTRY = {
    'EMA_CROSSOVER': lambda df, params: ema_crossover(df, fast=params.get('fast', 9), slow=params.get('slow', 21)),
    'RSI': lambda df, params: rsi(df, period=params.get('period', 14)),
    'ATR': lambda df, params: atr(df, period=params.get('period', 14)),
    'BOLLINGER_BANDS': lambda df, params: mean_reversion(df, window=params.get('window', 20), num_std_dev=params.get('num_std_dev', 2)),
    'CVD': lambda df, params: cvd_divergence(df, lookback=params.get('lookback', 20), swing_lookback=params.get('swing_lookback', 5)),
    'CVD_RAW': lambda df, params: cvd_raw(df, lookback=params.get('lookback', 20)),
    'CVD_LEADING': lambda df, params: cvd_leading(df, lookback=params.get('lookback', 10), swing_lookback=params.get('swing_lookback', 5)),
    'CVD_EXTREMES': lambda df, params: cvd_extremes(df, lookback=params.get('lookback', 50), swing_lookback=params.get('swing_lookback', 5), strength=params.get('strength', 3)),
    'CVD_MTF': lambda df, params: cvd_mtf(df, lookback=params.get('lookback', 20), swing_lookback=params.get('swing_lookback', 5)),
    'CVD_CROSS_MARKET': lambda df, params: cvd_cross_market(df, lookback=params.get('lookback', 20), swing_lookback=params.get('swing_lookback', 5)),
    'EMA_RIBBON_PULLBACK': lambda df, params: ema_ribbon_pullback(df, params),
    # SWING_DETECTOR is used by Extremes Scanner — CVD_EXTREMES handles swing detection internally
    'SWING_DETECTOR': lambda df, params: pd.Series(0, index=df.index),
    # Smart Money Concepts (ICT / TJR-style price action)
    'MARKET_STRUCTURE': lambda df, params: market_structure(df, params),
    'FAIR_VALUE_GAP': lambda df, params: fair_value_gap(df, params),
    'ORDER_BLOCK': lambda df, params: order_block(df, params),
    'LIQUIDITY_SWEEP': lambda df, params: liquidity_sweep(df, params),
    'SMC_CONFLUENCE': lambda df, params: smc_confluence(df, params),
    # Library-backed SMC detectors (smartmoneyconcepts package)
    'SMC_FVG_LIB': lambda df, params: _registry_fvg(df, params),
    'SMC_OB_LIB': lambda df, params: _registry_ob(df, params),
    'SMC_STRUCTURE_LIB': lambda df, params: _registry_structure(df, params),
    'SMC_LIQUIDITY_LIB': lambda df, params: _registry_liquidity(df, params),
    'SMC_CONFLUENCE_LIB': lambda df, params: _registry_confluence(df, params),
    # ── GBPUSD: Session range & sweep fade ──
    'ASIAN_RANGE': lambda df, params: asian_range(df, params),
    'SWEEP_FADE_SIGNAL': lambda df, params: sweep_fade_signal(df, params),
    'SESSION_FILTER': lambda df, params: session_filter(df, params),
    'LONDON_KILLZONE_ACTIVE': lambda df, params: london_killzone_active(df, params),
    # ── XAGUSD: Donchian trend following + Gold-Silver ratio ──
    'DONCHIAN_CHANNEL': lambda df, params: donchian_channel(df, params),
    'DONCHIAN_TREND_FILTER': lambda df, params: donchian_trend_filter(df, params),
    'DONCHIAN_WIDTH': lambda df, params: donchian_width(df, params),
    'GOLD_SILVER_RATIO': lambda df, params: gold_silver_ratio(df, params),
    'MOMENTUM_TREND': lambda df, params: momentum_trend(df, params),
    # ── AUDUSD: Session hybrid (Asian mean reversion + London breakout) ──
    'ASIAN_MEAN_REVERSION': lambda df, params: asian_mean_reversion(df, params),
    'LONDON_BREAKOUT': lambda df, params: london_breakout(df, params),
    'SESSION_STRATEGY_ROUTER': lambda df, params: session_strategy_router(df, params),
    'COMMODITY_CORRELATION_FILTER': lambda df, params: commodity_correlation_filter(df, params),
    # ── Energy: Trend / Range / Breakout ──
    'ENERGY_TREND_FOLLOW': lambda df, params: energy_trend_follow(df, params),
    'ENERGY_RANGE_DETECT': lambda df, params: energy_range_detect(df, params),
    'ENERGY_RANGE_TRADE': lambda df, params: energy_range_trade(df, params),
    'ENERGY_BREAKOUT': lambda df, params: energy_breakout(df, params),
    'KELTNER_CHANNEL': lambda df, params: keltner_channel(df, params),
    'BRENT_WTI_SPREAD': lambda df, params: brent_wti_spread(df, params),
}

CONDITION_OPS = {
    'eq': lambda a, b: a == b,
    'gte': lambda a, b: float(a) >= float(b),
    'lte': lambda a, b: float(a) <= float(b),
    'gt': lambda a, b: float(a) > float(b),
    'lt': lambda a, b: float(a) < float(b),
    # CVD divergence conditions: signal value contains the pattern name
    'divergence': lambda a, b: isinstance(a, str) and b in a,
    'leading_divergence': lambda a, b: isinstance(a, str) and b in a,
    'extreme_divergence': lambda a, b: isinstance(a, str) and b in a,
    'mtf_divergence': lambda a, b: isinstance(a, str) and b in a,
    'cross_market_divergence': lambda a, b: isinstance(a, str) and b in a,
    'cross_side_divergence': lambda a, b: isinstance(a, str) and b in a,
    'leading_volume': lambda a, b: isinstance(a, str) and b in a,
    'pullback': lambda a, b: isinstance(a, str) and b in a,
    # Smart Money Concepts conditions
    'structure_break': lambda a, b: isinstance(a, str) and b in a,
    'fvg_fill': lambda a, b: isinstance(a, str) and b in a,
    'ob_retest': lambda a, b: isinstance(a, str) and b in a,
    'sweep': lambda a, b: isinstance(a, str) and b in a,
    'confluence': lambda a, b: isinstance(a, str) and b in a,
    # Library-backed SMC conditions (smartmoneyconcepts package)
    'fvg_lib': lambda a, b: isinstance(a, str) and b in a,
    'ob_lib': lambda a, b: isinstance(a, str) and b in a,
    'structure_lib': lambda a, b: isinstance(a, str) and b in a,
    'liquidity_lib': lambda a, b: isinstance(a, str) and b in a,
    'smc_confluence_lib': lambda a, b: isinstance(a, str) and b in a,
}

TIMEFRAME_YAHOO_INTERVAL = {
    'M1': '1m', 'M5': '5m', 'M15': '15m',
    'H1': '1h', 'H4': '4h', 'D1': '1d',
    # Crypto-format timeframes (used by Hyperliquid/Binance strategies)
    '1m': '1m', '5m': '5m', '15m': '15m',
    '1h': '1h', '4h': '4h', '1d': '1d',
}

# Default spread (in pips / price units) per symbol for spread simulation.
# Majors are tight, minors wider, metals in price-unit terms (cents).
DEFAULT_SPREADS = {
    'EURUSD': 1.5, 'GBPUSD': 1.5, 'USDJPY': 1.5,
    'AUDUSD': 2.0, 'NZDUSD': 2.0, 'USDCAD': 2.0, 'USDCHF': 2.0,
    'XAUUSD': 30.0,   # 30 cents
    'XAGUSD': 3.0,    # 3 cents
    'UKOUSDft': 5.0,  # 5 cents Brent crude
    'USOUSD': 5.0,    # 5 cents WTI crude
    'NG-C': 3.0,      # 3 cents natural gas
    'EURGBP': 2.0,
}

# Pip value multiplier: how many price units = 1 pip for a given symbol.
# Forex pairs: 1 pip = 0.0001 (or 0.01 for JPY pairs).
# Metals: spread is already in price units so multiplier is 1.
_PIP_MULTIPLIERS = {
    'USDJPY': 0.01,
    'XAUUSD': 1.0,
    'XAGUSD': 1.0,
    'UKOUSDft': 1.0,
    'USOUSD': 1.0,
    'NG-C': 1.0,
}
_DEFAULT_PIP_MULTIPLIER = 0.0001


def _spread_in_price(symbol, spread_pips):
    """Convert spread from pips to price units for a given symbol."""
    mult = _PIP_MULTIPLIERS.get(symbol, _DEFAULT_PIP_MULTIPLIER)
    return spread_pips * mult


def _bar_to_unix(df, idx):
    ts = df.index[idx] if hasattr(df.index[idx], 'timestamp') else pd.Timestamp(df.iloc[idx].get('time', 0))
    return int(ts.timestamp()) if hasattr(ts, 'timestamp') else 0


def _clean_trade(trade):
    """Convert numpy types to native Python for JSON serialization."""
    cleaned = {}
    for k, v in trade.items():
        if isinstance(v, (np.integer,)):
            cleaned[k] = int(v)
        elif isinstance(v, (np.floating,)):
            cleaned[k] = float(v)
        elif isinstance(v, np.ndarray):
            cleaned[k] = v.tolist()
        else:
            cleaned[k] = v
    return cleaned


def _compute_enhanced_metrics(all_trades, equity_curve):
    """Compute advanced performance metrics from a list of trades.

    Returns a dict with: sharpe_ratio, max_drawdown_pct,
    avg_trade_duration_bars, consecutive_losses_max, expectancy.
    """
    metrics = {
        'sharpe_ratio': None,
        'max_drawdown_pct': 0.0,
        'avg_trade_duration_bars': 0.0,
        'consecutive_losses_max': 0,
        'expectancy': 0.0,
    }

    if not all_trades:
        return metrics

    # --- Sharpe Ratio (annualized, 252 trading days) ---
    pnls = [t['pnl_pct'] for t in all_trades]
    pnl_arr = np.array(pnls, dtype=float)
    if len(pnl_arr) >= 2 and np.std(pnl_arr) > 0:
        metrics['sharpe_ratio'] = round(
            float(np.mean(pnl_arr) / np.std(pnl_arr) * np.sqrt(252)), 4
        )

    # --- Max Drawdown % (peak-to-trough on equity curve) ---
    if equity_curve:
        eq_values = [pt['value'] for pt in equity_curve]
        peak = eq_values[0]
        max_dd = 0.0
        for v in eq_values:
            if v > peak:
                peak = v
            dd = peak - v
            if dd > max_dd:
                max_dd = dd
        # Express as percentage of peak (guard against zero peak)
        if peak > 0:
            metrics['max_drawdown_pct'] = round(max_dd / peak * 100, 4)
        elif max_dd > 0:
            # Peak was zero or negative; report absolute drawdown
            metrics['max_drawdown_pct'] = round(max_dd * 100, 4)

    # --- Avg Trade Duration (in bars) ---
    durations = []
    for t in all_trades:
        entry_t = t.get('entry_time', 0)
        exit_t = t.get('exit_time', 0)
        if entry_t and exit_t and exit_t > entry_t:
            durations.append(exit_t - entry_t)
    if durations:
        # We don't know bar size in seconds here, so approximate:
        # duration is in seconds; normalize by median duration to get "bars"
        # A simpler approach: use entry_bar_idx and exit bar index stored in trades.
        # Since we only have timestamps, report average duration in seconds
        # and the caller can convert. But the spec says "bars" -- store
        # entry_bar_idx in the trade for accuracy (see _simulate_trades changes).
        # For trades that have 'duration_bars', use that directly.
        bar_durations = [t['duration_bars'] for t in all_trades if 'duration_bars' in t]
        if bar_durations:
            metrics['avg_trade_duration_bars'] = round(float(np.mean(bar_durations)), 2)
        else:
            # Fallback: average seconds (not ideal, but non-breaking)
            metrics['avg_trade_duration_bars'] = round(float(np.mean(durations)), 2)

    # --- Consecutive Losses Max ---
    streak = 0
    max_streak = 0
    for t in all_trades:
        if t['result'] == 'SL':
            streak += 1
            if streak > max_streak:
                max_streak = streak
        else:
            streak = 0
    metrics['consecutive_losses_max'] = max_streak

    # --- Expectancy ---
    wins = [t['pnl_pct'] for t in all_trades if t['result'] == 'TP']
    losses = [t['pnl_pct'] for t in all_trades if t['result'] == 'SL']
    total = len(all_trades)
    if total > 0:
        win_rate = len(wins) / total
        loss_rate = len(losses) / total
        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = abs(float(np.mean(losses))) if losses else 0.0
        metrics['expectancy'] = round(
            (win_rate * avg_win) - (loss_rate * avg_loss), 6
        )

    return metrics


class GenericBacktester:
    def __init__(self, definition, data_source='auto'):
        self.definition = definition
        self.timeframe = definition.get('timeframe', 'M5')
        self.pairs = definition.get('pairs', [])
        self.indicators = definition.get('indicators', [])
        self.entry_rules = definition.get('entry_rules', {})
        self.exit_rules = definition.get('exit_rules', {})
        self.min_win_rate = definition.get('min_win_rate', 0.55)
        self.data_source = data_source

    # Map entry rule conditions to the CVD variant that produces those signals
    CVD_CONDITION_TO_VARIANT = {
        'leading_divergence': 'CVD_LEADING',
        'extreme_divergence': 'CVD_EXTREMES',
        'mtf_divergence': 'CVD_MTF',
        'cross_market_divergence': 'CVD_CROSS_MARKET',
        'cross_side_divergence': 'CVD_CROSS_MARKET',
    }

    def _resolve_cvd_variant(self):
        """Determine which CVD variant to use based on entry rule conditions."""
        for side in ['long', 'short', 'buy_yes', 'buy_no']:
            for rule in self.entry_rules.get(side, []):
                condition = rule.get('condition', '')
                if condition in self.CVD_CONDITION_TO_VARIANT:
                    return self.CVD_CONDITION_TO_VARIANT[condition]
        return None

    def _compute_indicators(self, df):
        """Compute all declared indicators and store as columns."""
        cvd_variant = self._resolve_cvd_variant()
        results = {}
        for ind in self.indicators:
            ind_type = ind['type']
            params = ind.get('params', {})

            if ind_type == 'CVD' and cvd_variant and cvd_variant in INDICATOR_REGISTRY:
                # Use the specialized CVD variant that matches the entry rule conditions
                results[ind_type] = INDICATOR_REGISTRY[cvd_variant](df, params)
            elif ind_type in INDICATOR_REGISTRY:
                results[ind_type] = INDICATOR_REGISTRY[ind_type](df, params)
            else:
                continue

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

    def _simulate_trades(self, df, spread_price=0.0):
        """Walk-forward simulation with generic entry/exit rules.

        Parameters
        ----------
        df : DataFrame
            OHLCV data with DatetimeIndex.
        spread_price : float
            Half-spread in price units to apply against entry direction.
        """
        df = self._compute_indicators(df)

        exit_type = self.exit_rules.get('type', 'ATR_BASED')
        exit_params = self.exit_rules.get('params', {})

        if exit_type == 'ATR_BASED':
            atr_period = exit_params.get('atr_period', 14)
            sl_mult = exit_params.get('sl_multiplier', 1.5)
            tp_mult = exit_params.get('tp_multiplier', 2.0)
            df['_atr'] = atr(df, period=atr_period)
        else:
            sl_pct = exit_params.get('stop_loss_pct', exit_params.get('sl_pct', 0.5))
            tp_pct = exit_params.get('take_profit_pct', exit_params.get('tp_pct', 0.5))
            # Normalize: if values look like raw percentages (> 1), divide by 100
            if sl_pct > 1:
                sl_pct = sl_pct / 100
            if tp_pct > 1:
                tp_pct = tp_pct / 100

        long_rules = self.entry_rules.get('long', self.entry_rules.get('buy_yes', []))
        short_rules = self.entry_rules.get('short', self.entry_rules.get('buy_no', []))

        half_spread = spread_price / 2.0

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
                                       'exit_time': _bar_to_unix(df, i),
                                       'duration_bars': i - entry_bar_idx})
                        in_trade = False
                        continue
                    if row['high'] >= tp_price:
                        pnl = tp_price - entry_price
                        trades.append({**trade_base, 'exit': tp_price,
                                       'pnl_pct': pnl / entry_price, 'result': 'TP',
                                       'exit_time': _bar_to_unix(df, i),
                                       'duration_bars': i - entry_bar_idx})
                        in_trade = False
                        continue
                elif trade_type == 'SELL':
                    if row['high'] >= sl_price:
                        pnl = entry_price - sl_price
                        trades.append({**trade_base, 'exit': sl_price,
                                       'pnl_pct': pnl / entry_price, 'result': 'SL',
                                       'exit_time': _bar_to_unix(df, i),
                                       'duration_bars': i - entry_bar_idx})
                        in_trade = False
                        continue
                    if row['low'] <= tp_price:
                        pnl = entry_price - tp_price
                        trades.append({**trade_base, 'exit': tp_price,
                                       'pnl_pct': pnl / entry_price, 'result': 'TP',
                                       'exit_time': _bar_to_unix(df, i),
                                       'duration_bars': i - entry_bar_idx})
                        in_trade = False
                        continue
                continue

            prev_idx = i - 1
            enter_long = long_rules and self._check_rules(df, prev_idx, long_rules)
            enter_short = short_rules and self._check_rules(df, prev_idx, short_rules)

            if enter_long:
                trade_type = 'BUY'
                # Spread simulation: BUY enters at ask = open + half_spread
                entry_price = row['open'] + half_spread
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
                # Spread simulation: SELL enters at bid = open - half_spread
                entry_price = row['open'] - half_spread
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

    def _fetch_data(self, pair, period_days, data_source):
        """Fetch OHLCV data for a single pair using the configured source.

        Tries the unified data_fetcher first (if available and source != 'yahoo'/'mt5'),
        then falls back to Yahoo Finance, then MT5.

        Returns (DataFrame, source_label) or (None, None).
        """
        yahoo_interval = TIMEFRAME_YAHOO_INTERVAL.get(self.timeframe, '5m')
        yahoo_period = f'{period_days}d'
        df = None
        source = None

        # ---- Unified fetcher (lazy import, may not exist yet) ----
        if data_source not in ('yahoo', 'mt5'):
            try:
                from app.quant.data_fetcher import fetch_ohlcv
                df = fetch_ohlcv(
                    pair, self.timeframe, days=period_days, source=data_source,
                )
                if df is not None and not df.empty and len(df) >= 30:
                    source = data_source if data_source != 'auto' else 'unified'
                    return df, source
                # Unified fetcher returned insufficient data — fall through
                df = None
            except ImportError:
                logger.debug("data_fetcher module not available, using Yahoo/MT5 fallback")
            except Exception as exc:
                logger.warning(f"data_fetcher failed for {pair}: {exc}")

        # ---- Yahoo Finance fallback ----
        if data_source in ('auto', 'yahoo'):
            try:
                df = fetch_yahoo_data(pair, period=yahoo_period, interval=yahoo_interval)
                if df is not None and not df.empty and len(df) >= 30:
                    return df, 'yahoo'
            except Exception as exc:
                logger.warning(f"Yahoo fetch failed for {pair}: {exc}")
            df = None

        # ---- MT5 fallback ----
        if data_source in ('auto', 'mt5', 'yahoo'):
            try:
                from app.utils.constants import MT5Timeframe as TF
                mt5_tf = TF[self.timeframe.upper()] if isinstance(self.timeframe, str) else self.timeframe
                df = fetch_data_pos(pair, mt5_tf, 500)
                if df is not None and not df.empty and len(df) >= 30:
                    return df, 'mt5'
            except Exception as exc:
                logger.warning(f"MT5 fetch failed for {pair}: {exc}")

        return None, None

    @staticmethod
    def _aggregate_results(all_trades, data_source_label, period_days, min_win_rate):
        """Build the results dict from a list of cleaned trades.

        Factored out so both the main run and walk-forward splits can reuse it.
        """
        if not all_trades:
            return {
                'total_trades': 0, 'winning_trades': 0, 'losing_trades': 0,
                'win_rate': 0.0, 'total_pnl': 0.0, 'profit_factor': None,
                'avg_win': None, 'avg_loss': None, 'passed': False,
                'data_source': data_source_label, 'period_days': period_days,
                'trades': [], 'equity_curve': [], 'symbol_breakdown': {},
                'sharpe_ratio': None, 'max_drawdown_pct': 0.0,
                'avg_trade_duration_bars': 0.0, 'consecutive_losses_max': 0,
                'expectancy': 0.0,
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
        passed = win_rate >= min_win_rate

        # Enhanced metrics
        enhanced = _compute_enhanced_metrics(all_trades, equity_curve)

        result = {
            'total_trades': total_trades, 'winning_trades': winning_trades,
            'losing_trades': losing_trades, 'win_rate': win_rate,
            'total_pnl': total_pnl, 'profit_factor': profit_factor,
            'avg_win': avg_win, 'avg_loss': avg_loss, 'passed': passed,
            'data_source': data_source_label, 'period_days': period_days,
            'trades': all_trades, 'equity_curve': equity_curve,
            'symbol_breakdown': symbol_breakdown,
        }
        result.update(enhanced)
        return result

    def run(self, data_source=None, period_days=60, spread_pips=None,
            walk_forward=False):
        """Run backtest across all pairs. Returns result dict.

        Parameters
        ----------
        data_source : str or None
            Data source override.  'auto' (default from __init__), 'yahoo',
            'mt5', or any source supported by the unified data_fetcher.
            If None, uses self.data_source set at __init__ time.
        period_days : int
            Number of calendar days of historical data to test on (max 365).
        spread_pips : float or None
            Simulated spread in pips applied against entry direction.
            If None, uses DEFAULT_SPREADS per symbol (falls back to 1.5).
        walk_forward : bool
            When True, split data 70/30 and report in_sample_results and
            out_of_sample_results separately. Main results = out-of-sample.
        """
        if data_source is None:
            data_source = self.data_source
        period_days = min(max(int(period_days), 1), 365)

        all_trades = []
        data_source_label = data_source.upper() if data_source != 'auto' else 'YAHOO'
        yahoo_interval = TIMEFRAME_YAHOO_INTERVAL.get(self.timeframe, '5m')

        # Collect per-pair DataFrames (needed for walk-forward split)
        pair_dataframes = {}

        for pair in self.pairs:
            try:
                df, source = self._fetch_data(pair, period_days, data_source)

                if df is None:
                    logger.info(f"Generic Backtest: insufficient data for {pair}")
                    continue

                # Track actual data source label
                if source == 'mt5' and data_source_label == 'YAHOO':
                    data_source_label = 'MIXED'
                elif source and source not in ('yahoo', 'mt5') and data_source_label in ('YAHOO', 'MT5'):
                    data_source_label = source.upper()

                pair_dataframes[pair] = df

                if not walk_forward:
                    # Determine spread for this symbol
                    if spread_pips is not None:
                        sp = _spread_in_price(pair, spread_pips)
                    else:
                        default_pips = DEFAULT_SPREADS.get(pair, 1.5)
                        sp = _spread_in_price(pair, default_pips)

                    trades = self._simulate_trades(df.copy(), spread_price=sp)
                    for t in trades:
                        t['symbol'] = pair
                    all_trades.extend(_clean_trade(t) for t in trades)
                    logger.info(f"Generic Backtest {pair}: {len(trades)} trades ({source}, {len(df)} bars)")

            except Exception as e:
                logger.error(f"Generic Backtest error for {pair}: {e}\n{traceback.format_exc()}")

        # ---- Walk-forward mode ----
        if walk_forward:
            is_trades = []
            oos_trades = []

            for pair, df in pair_dataframes.items():
                split_idx = int(len(df) * 0.7)
                if split_idx < 30 or (len(df) - split_idx) < 10:
                    # Not enough data for a meaningful split; run on full set
                    logger.info(f"Walk-forward {pair}: insufficient data for split, using full set")
                    split_idx = len(df)

                df_is = df.iloc[:split_idx].copy()
                df_oos = df.iloc[split_idx:].copy() if split_idx < len(df) else pd.DataFrame()

                if spread_pips is not None:
                    sp = _spread_in_price(pair, spread_pips)
                else:
                    default_pips = DEFAULT_SPREADS.get(pair, 1.5)
                    sp = _spread_in_price(pair, default_pips)

                # In-sample
                if len(df_is) >= 30:
                    trades_is = self._simulate_trades(df_is, spread_price=sp)
                    for t in trades_is:
                        t['symbol'] = pair
                    is_trades.extend(_clean_trade(t) for t in trades_is)

                # Out-of-sample
                if len(df_oos) >= 10:
                    trades_oos = self._simulate_trades(df_oos, spread_price=sp)
                    for t in trades_oos:
                        t['symbol'] = pair
                    oos_trades.extend(_clean_trade(t) for t in trades_oos)

                logger.info(
                    f"Walk-forward {pair}: IS={len(is_trades)} trades, "
                    f"OOS={len(oos_trades)} trades"
                )

            is_results = self._aggregate_results(
                is_trades, data_source_label, period_days, self.min_win_rate,
            )
            oos_results = self._aggregate_results(
                oos_trades, data_source_label, period_days, self.min_win_rate,
            )

            # Main results = out-of-sample (the real test)
            result = dict(oos_results)
            result['in_sample_results'] = is_results
            result['out_of_sample_results'] = oos_results
            return result

        # ---- Standard (non-walk-forward) mode ----
        return self._aggregate_results(
            all_trades, data_source_label, period_days, self.min_win_rate,
        )
