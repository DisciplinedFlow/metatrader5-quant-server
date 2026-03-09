"""
Generic CVD strategy live entry algorithm.

Reads the active CustomStrategy definition from the database and executes
live trades via MT5 when CVD divergence signals fire. Uses the same indicator
registry and condition operators as GenericBacktester for signal parity.
"""

import pandas as pd
import logging
import traceback
from datetime import timedelta

from app.utils.arithmetics import (
    calculate_order_size_usd,
    calculate_commission,
    get_price_at_pnl,
    get_pnl_at_price,
    convert_usd_to_lots,
)
from app.utils.constants import MT5Timeframe
from app.utils.api.data import fetch_data_pos, symbol_info_tick
from app.utils.api.order import send_market_order
from app.utils.account import have_open_positions_in_symbol
from app.utils.market import is_market_open
from app.utils.api.positions import get_positions
from app.utils.db.create import create_trade
from app.quant.indicators.scalping import atr
from app.quant.backtester_generic import INDICATOR_REGISTRY, CONDITION_OPS
from app.quant.algorithms.cvd.config import (
    LEVERAGE,
    CAPITAL_PER_TRADE,
    DEVIATION,
    MAX_OPEN_TRADES,
    ATR_PERIOD,
    SL_ATR_MULTIPLIER,
    TP_ATR_MULTIPLIER,
)

logger = logging.getLogger(__name__)


def _is_trading_session():
    """Check if current UTC hour is within allowed trading sessions.

    Only trade during London through NY close: 07:00-21:00 UTC.
    Blocks Sunday night, Asian quiet hours, and post-NY dead zone.
    """
    from datetime import datetime, timezone as tz
    now = datetime.now(tz.utc)
    # Block all Sunday trading (weekday 6 = Sunday)
    if now.weekday() == 6:
        return False
    # Block Monday before 00:00 UTC (markets barely open)
    if now.weekday() == 0 and now.hour < 1:
        return False
    # Only trade 07:00-21:00 UTC (London open → NY close)
    if now.hour < 7 or now.hour >= 21:
        return False
    return True


def _load_active_custom_strategy():
    """Load the CustomStrategy linked to the currently active StrategyConfig."""
    from app.nexus.models import StrategyConfig, CustomStrategy
    active = StrategyConfig.objects.filter(is_active=True).first()
    if active is None:
        return None, None
    custom = CustomStrategy.objects.filter(strategy_config=active).first()
    return active, custom


def _load_custom_strategy_for_config(strategy_config):
    """Load the CustomStrategy linked to a specific StrategyConfig."""
    from app.nexus.models import CustomStrategy
    custom = CustomStrategy.objects.filter(strategy_config=strategy_config).first()
    return custom


def _count_open_trades():
    positions = get_positions()
    if positions is None or positions.empty:
        return 0
    return len(positions)


def _check_backtest_gate(strategy_config):
    """Verify a recent, profitable backtest exists for this strategy."""
    try:
        from app.nexus.models import BacktestResult
        from django.utils import timezone

        latest = BacktestResult.objects.filter(
            strategy=strategy_config
        ).order_by('-run_time').first()

        if latest is None:
            logger.warning(f"No backtest for {strategy_config.name}, allowing trading (new strategy).")
            return True

        age = timezone.now() - latest.run_time
        if age > timedelta(hours=24):
            logger.warning(f"Backtest for {strategy_config.name} is {age} old (>24h), blocking.")
            return False

        if latest.total_trades == 0:
            logger.warning(f"Latest backtest for {strategy_config.name} has 0 trades, blocking.")
            return False

        if latest.total_pnl < -0.5:
            logger.warning(f"Backtest PnL {latest.total_pnl:.4f} heavily negative, blocking.")
            return False

        logger.info(f"Backtest gate passed: PnL={latest.total_pnl:.4f}, WR={latest.win_rate:.2%}, age={age}")
        return True
    except Exception as e:
        logger.error(f"Backtest gate error: {e}")
        return True


def _resolve_cvd_variant(entry_rules):
    """Determine which CVD indicator variant to use based on entry rule conditions."""
    mapping = {
        'leading_divergence': 'CVD_LEADING',
        'extreme_divergence': 'CVD_EXTREMES',
        'mtf_divergence': 'CVD_MTF',
        'cross_market_divergence': 'CVD_CROSS_MARKET',
        'cross_side_divergence': 'CVD_CROSS_MARKET',
    }
    for side in ['long', 'short']:
        for rule in entry_rules.get(side, []):
            condition = rule.get('condition', '')
            if condition in mapping:
                return mapping[condition]
    return None


def _compute_indicators(df, indicators, entry_rules):
    """Compute all declared indicators on the dataframe."""
    cvd_variant = _resolve_cvd_variant(entry_rules)
    for ind in indicators:
        ind_type = ind['type']
        params = ind.get('params', {})

        if ind_type == 'CVD' and cvd_variant and cvd_variant in INDICATOR_REGISTRY:
            df[ind_type] = INDICATOR_REGISTRY[cvd_variant](df, params)
        elif ind_type in INDICATOR_REGISTRY:
            df[ind_type] = INDICATOR_REGISTRY[ind_type](df, params)
    return df


def _check_rules(df, idx, rules):
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


def cvd_entry_algorithm(strategy_config, remaining_slots):
    """Multi-strategy CVD entry algorithm.

    Args:
        strategy_config: StrategyConfig instance to run.
        remaining_slots: Maximum number of new positions this invocation may open.
    """
    from app.nexus.models import PairLock
    from django.db import IntegrityError

    try:
        custom = _load_custom_strategy_for_config(strategy_config)
        if custom is None:
            logger.warning(f"No CustomStrategy linked to StrategyConfig '{strategy_config.name}'.")
            return

        definition = custom.definition
        if not definition:
            logger.warning(f"CustomStrategy '{custom.name}' has empty definition.")
            return

        if not _check_backtest_gate(strategy_config):
            logger.info(f"CVD entry blocked by backtest gate for '{custom.name}'.")
            return

        if not _is_trading_session():
            logger.info(f"CVD: Outside trading session (07:00-21:00 UTC), skipping.")
            return

        positions_opened = 0

        pairs = definition.get('pairs', [])
        indicators = definition.get('indicators', [])
        entry_rules = definition.get('entry_rules', {})
        exit_rules = definition.get('exit_rules', {})
        timeframe_str = definition.get('timeframe', 'M15')

        try:
            timeframe = MT5Timeframe(timeframe_str)
        except ValueError:
            timeframe = MT5Timeframe.M15

        # ATR params from strategy definition or defaults
        exit_params = exit_rules.get('params', {})
        atr_period = exit_params.get('atr_period', ATR_PERIOD)
        sl_mult = exit_params.get('sl_multiplier', SL_ATR_MULTIPLIER)
        tp_mult = exit_params.get('tp_multiplier', TP_ATR_MULTIPLIER)

        long_rules = entry_rules.get('long', [])
        short_rules = entry_rules.get('short', [])

        for pair in pairs:
            if positions_opened >= remaining_slots:
                logger.info(f"CVD ({custom.name}): Remaining slots exhausted ({remaining_slots}), stopping.")
                break

            # Fast DB check first — prevents cross-strategy conflicts without API call
            if PairLock.objects.filter(symbol=pair).exists():
                logger.info(f"CVD: Skipping {pair} — locked by another strategy.")
                continue

            if have_open_positions_in_symbol(pair):
                logger.info(f"CVD: Skipping {pair} — already has open position.")
                continue

            if not is_market_open(pair):
                logger.info(f"CVD: Skipping {pair} — market closed.")
                continue

            # Fetch enough bars for indicator computation
            df = fetch_data_pos(pair, timeframe, 100)
            if df is None or df.empty or len(df) < 30:
                logger.info(f"CVD: Skipping {pair} — insufficient data ({0 if df is None else len(df)} bars).")
                continue

            # Compute CVD indicators
            df = _compute_indicators(df, indicators, entry_rules)

            # Compute ATR for exit levels
            df['_atr'] = atr(df, period=atr_period)

            # Check signal on last N completed bars (most recent first)
            SIGNAL_LOOKBACK = 4
            order_type = None
            signal_desc = None
            check_idx = None
            atr_val = None

            for offset in range(2, 2 + SIGNAL_LOOKBACK):
                idx = len(df) - offset
                if idx < 0:
                    break
                _atr_val = df['_atr'].iloc[idx]
                if pd.isna(_atr_val) or _atr_val <= 0:
                    continue
                if long_rules and _check_rules(df, idx, long_rules):
                    order_type = 'BUY'
                    check_idx = idx
                    atr_val = _atr_val
                    signal_desc = str(df.get('CVD', pd.Series()).iloc[idx] if 'CVD' in df.columns else 'long_signal')
                    logger.info(f"CVD: Signal found at bar offset {offset} for {pair}")
                    break
                if short_rules and _check_rules(df, idx, short_rules):
                    order_type = 'SELL'
                    check_idx = idx
                    atr_val = _atr_val
                    signal_desc = str(df.get('CVD', pd.Series()).iloc[idx] if 'CVD' in df.columns else 'short_signal')
                    logger.info(f"CVD: Signal found at bar offset {offset} for {pair}")
                    break

            if order_type is None:
                logger.debug(f"CVD ({custom.name}): No signal for {pair} on last {SIGNAL_LOOKBACK} bars.")
                continue

            if atr_val is None:
                logger.info(f"CVD ({custom.name}): Signal found for {pair} but ATR not valid.")
                continue

            # Macro context — advisory only, does NOT block trades
            try:
                from app.quant.macro_analyst import check_macro_for_trade
                macro_ok, macro_reason = check_macro_for_trade(pair, order_type)
                if not macro_ok:
                    logger.info(f"CVD: MACRO WARNING {pair} {order_type} — {macro_reason} (proceeding anyway)")
                else:
                    logger.info(f"CVD: {pair} {order_type} — {macro_reason}")
            except Exception as e:
                logger.debug(f"Macro check unavailable: {e}")

            logger.info(f"CVD SIGNAL: {pair} {order_type} — {signal_desc}")

            # Acquire PairLock before placing order
            try:
                PairLock.objects.create(symbol=pair, strategy=strategy_config, ticket=0)
            except IntegrityError:
                logger.info(f"CVD: Skipping {pair} — already locked by another strategy")
                continue

            try:
                # Get current tick price
                tick_info = symbol_info_tick(pair)
                if tick_info is None or tick_info.empty:
                    logger.info(f"CVD: Skipping {pair} — no tick info.")
                    PairLock.objects.filter(symbol=pair).delete()
                    continue

                last_tick_price = (
                    tick_info['ask'].iloc[0] if order_type == 'BUY' else tick_info['bid'].iloc[0]
                )
                price_decimals = len(str(last_tick_price).split('.')[-1])

                # ATR-based SL and TP
                if order_type == 'BUY':
                    sl_price = last_tick_price - (atr_val * sl_mult)
                    tp_price = last_tick_price + (atr_val * tp_mult)
                else:
                    sl_price = last_tick_price + (atr_val * sl_mult)
                    tp_price = last_tick_price - (atr_val * tp_mult)

                # Order sizing
                order_capital = CAPITAL_PER_TRADE
                order_size_usd = calculate_order_size_usd(order_capital, LEVERAGE)
                commission = calculate_commission(order_size_usd, pair)

                # Clamp SL so max loss does not exceed capital
                pnl_at_sl, _ = get_pnl_at_price(
                    sl_price, last_tick_price, order_size_usd, LEVERAGE, order_type, commission
                )
                if pnl_at_sl < -order_capital:
                    sl_price, _ = get_price_at_pnl(
                        desired_pnl=-order_capital,
                        entry_price=last_tick_price,
                        order_size_usd=order_size_usd,
                        leverage=LEVERAGE,
                        type=order_type,
                        commission=commission,
                    )
                    logger.info(f"CVD: Clamped SL for {pair} to limit loss to ${order_capital:.2f}")

                # Convert to lots
                order_volume_lots = convert_usd_to_lots(pair, order_size_usd, order_type)
                if isinstance(order_volume_lots, (pd.Series, pd.DataFrame)):
                    order_volume_lots = order_volume_lots.iloc[0] if not order_volume_lots.empty else 0.0

                if order_volume_lots < 0.01:
                    logger.error(f"CVD: Order volume too low for {pair}: {order_volume_lots}")
                    PairLock.objects.filter(symbol=pair).delete()
                    continue

                # Validate SL direction
                if order_type == 'BUY' and sl_price >= tick_info['bid'].iloc[0]:
                    logger.error(f"CVD: SL too high for BUY on {pair}.")
                    PairLock.objects.filter(symbol=pair).delete()
                    continue
                if order_type == 'SELL' and sl_price <= tick_info['ask'].iloc[0]:
                    logger.error(f"CVD: SL too low for SELL on {pair}.")
                    PairLock.objects.filter(symbol=pair).delete()
                    continue

                # Send market order
                order = send_market_order(
                    symbol=pair,
                    volume=order_volume_lots,
                    order_type=order_type,
                    sl=round(sl_price, price_decimals),
                    tp=round(tp_price, price_decimals),
                    deviation=DEVIATION,
                    type_filling="ORDER_FILLING_IOC",
                    position_size_usd=order_size_usd,
                    commission=commission,
                    capital=order_capital,
                    leverage=LEVERAGE,
                )

                if order is not None:
                    # Update PairLock with actual ticket
                    order_ticket = order.get('order', 0)
                    PairLock.objects.filter(symbol=pair).update(ticket=order_ticket)
                    positions_opened += 1

                    logger.info({
                        'event': 'cvd_trade_opened',
                        'symbol': pair,
                        'type': order_type,
                        'strategy': custom.name,
                        'signal': signal_desc,
                        'capital': f"${order_capital:.2f}",
                        'sl': f"{sl_price:.{price_decimals}f}",
                        'tp': f"{tp_price:.{price_decimals}f}",
                        'atr': f"{atr_val:.{price_decimals}f}",
                    })

                    try:
                        trade_result = create_trade(
                            order, pair, order_capital, order_size_usd,
                            LEVERAGE, commission, order_type, 'Alpari',
                            'FOREX', f'CVD_{custom.name}', timeframe, order_volume_lots,
                            sl_price, tp_price,
                        )

                        # Save Phase 1C fields on the Trade record
                        if trade_result:
                            trade_obj = trade_result[0] if isinstance(trade_result, tuple) else trade_result
                            try:
                                update_fields = []
                                if hasattr(trade_obj, 'entry_atr'):
                                    trade_obj.entry_atr = atr_val
                                    update_fields.append('entry_atr')
                                if hasattr(trade_obj, 'entry_timeframe'):
                                    trade_obj.entry_timeframe = timeframe.value
                                    update_fields.append('entry_timeframe')
                                if hasattr(trade_obj, 'strategy_config'):
                                    trade_obj.strategy_config = strategy_config
                                    update_fields.append('strategy_config')
                                if update_fields:
                                    trade_obj.save(update_fields=update_fields)
                            except Exception as e:
                                logger.warning(f"CVD: Could not save Phase 1C trade fields: {e}")

                    except Exception as e:
                        logger.error(f"CVD: Error creating trade record: {e}\n{traceback.format_exc()}")
                else:
                    # Order failed — release PairLock
                    PairLock.objects.filter(symbol=pair).delete()
                    logger.error({
                        'event': 'cvd_trade_failed',
                        'symbol': pair,
                        'type': order_type,
                        'strategy': custom.name,
                        'volume': order_volume_lots,
                    })

            except Exception as e:
                PairLock.objects.filter(symbol=pair).delete()
                logger.error(f"Order failed for {pair}: {e}\n{traceback.format_exc()}")

    except Exception as e:
        logger.error(f"Exception in cvd_entry_algorithm: {e}\n{traceback.format_exc()}")


def entry_algorithm():
    """Legacy entry point — backward compatible wrapper.

    Called by older code paths that don't pass strategy_config.
    Loads the first active custom strategy and delegates to cvd_entry_algorithm.
    """
    try:
        strategy_config, custom = _load_active_custom_strategy()
        if custom is None:
            logger.warning("No CustomStrategy linked to active StrategyConfig.")
            return
        cvd_entry_algorithm(strategy_config, MAX_OPEN_TRADES)
    except Exception as e:
        logger.error(f"Exception in legacy entry_algorithm: {e}\n{traceback.format_exc()}")
