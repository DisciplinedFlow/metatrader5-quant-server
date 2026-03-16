import pandas as pd
import logging
import traceback
from datetime import datetime, timedelta

from app.utils.arithmetics import (
    calculate_order_size_usd,
    calculate_commission,
    get_price_at_pnl,
    get_pnl_at_price,
    convert_usd_to_lots,
    get_symbol_contract_info,
)
from app.utils.api.data import fetch_data_pos, symbol_info_tick
from app.utils.api.positions import get_positions
from app.utils.api.order import send_market_order
from app.utils.account import have_open_positions_in_symbol
from app.utils.market import is_market_open
from app.quant.indicators.scalping import ema_crossover, rsi, atr
from app.quant.algorithms.scalping.config import (
    PAIRS,
    MAIN_TIMEFRAME,
    LEVERAGE,
    DEVIATION,
    CAPITAL_PER_TRADE,
    MAX_OPEN_TRADES,
    EMA_FAST,
    EMA_SLOW,
    RSI_PERIOD,
    ATR_PERIOD,
    SL_ATR_MULTIPLIER,
    TP_ATR_MULTIPLIER,
    MIN_WIN_RATE,
)
from app.utils.db.create import create_trade

logger = logging.getLogger(__name__)


def _count_open_trades():
    """Return count of currently open positions."""
    positions = get_positions()
    if positions is None or positions.empty:
        return 0
    return len(positions)


def _check_backtest_gate():
    """
    Check the latest backtest result for the SCALPING strategy.
    Returns True if trading is allowed, False otherwise.
    """
    try:
        from app.nexus.models import StrategyConfig, BacktestResult
        from django.utils import timezone

        strategy = StrategyConfig.objects.filter(name='SCALPING').first()
        if strategy is None:
            logger.warning("SCALPING strategy not found in DB, blocking trading.")
            return False

        latest = BacktestResult.objects.filter(strategy=strategy).order_by('-run_time').first()
        if latest is None:
            logger.warning("No backtest results found for SCALPING, blocking trading.")
            return False

        age = timezone.now() - latest.run_time
        if age > timedelta(hours=12):
            logger.warning(f"Latest backtest is {age} old (>12h), blocking trading.")
            return False

        if latest.win_rate < MIN_WIN_RATE:
            logger.warning(
                f"Backtest win rate {latest.win_rate:.2%} < {MIN_WIN_RATE:.2%}, blocking trading."
            )
            return False

        logger.info(
            f"Backtest gate passed: win_rate={latest.win_rate:.2%}, age={age}"
        )
        return True

    except Exception as e:
        logger.error(f"Error checking backtest gate: {e}\n{traceback.format_exc()}")
        return False


def entry_algorithm():
    try:
        # Backtest gate disabled during data collection phase (Mar 15-31)
        # if not _check_backtest_gate():
        #     logger.info("SCALPING entry blocked by backtest gate.")
        #     return

        open_count = _count_open_trades()
        if open_count >= MAX_OPEN_TRADES:
            logger.info(
                f"Max open trades reached ({open_count}/{MAX_OPEN_TRADES}), skipping entry."
            )
            return

        for pair in PAIRS:
            # Re-check open trade limit per iteration (in case one was opened this loop)
            if _count_open_trades() >= MAX_OPEN_TRADES:
                logger.info("Max open trades reached during iteration, stopping.")
                break

            if have_open_positions_in_symbol(pair):
                logger.info(f"Skipping {pair}: already has open position.")
                continue

            if not is_market_open(pair):
                logger.info(f"Skipping {pair}: market closed.")
                continue

            # Fetch 50 bars of M5 data
            df = fetch_data_pos(pair, MAIN_TIMEFRAME, 50)
            if df is None or df.empty or len(df) < EMA_SLOW + 2:
                logger.info(f"Skipping {pair}: insufficient data.")
                continue

            # Calculate indicators
            df['ema_signal'] = ema_crossover(df, fast=EMA_FAST, slow=EMA_SLOW)
            df['rsi'] = rsi(df, period=RSI_PERIOD)
            df['atr'] = atr(df, period=ATR_PERIOD)

            # Check signal on completed bar (second to last)
            last_row = df.iloc[-2]

            signal = last_row['ema_signal']
            rsi_val = last_row['rsi']
            atr_val = last_row['atr']

            if pd.isna(rsi_val) or pd.isna(atr_val) or atr_val <= 0:
                logger.info(f"Skipping {pair}: indicators not ready (RSI={rsi_val}, ATR={atr_val}).")
                continue

            # Determine order type based on crossover + RSI confirmation
            order_type = None
            if signal == 'bull_cross' and 30 <= rsi_val <= 65:
                order_type = 'BUY'
            elif signal == 'bear_cross' and 35 <= rsi_val <= 70:
                order_type = 'SELL'

            if order_type is None:
                logger.info(f"No scalping signal for {pair} (signal={signal}, RSI={rsi_val:.1f}).")
                continue

            # Get current tick price
            tick_info = symbol_info_tick(pair)
            if tick_info is None or tick_info.empty:
                logger.info(f"Skipping {pair}: no tick info.")
                continue

            last_tick_price = (
                tick_info['ask'].iloc[0] if order_type == 'BUY' else tick_info['bid'].iloc[0]
            )
            price_decimals = len(str(last_tick_price).split('.')[-1])

            # Calculate SL and TP based on ATR
            if order_type == 'BUY':
                sl_price = last_tick_price - (atr_val * SL_ATR_MULTIPLIER)
                tp_price = last_tick_price + (atr_val * TP_ATR_MULTIPLIER)
            else:
                sl_price = last_tick_price + (atr_val * SL_ATR_MULTIPLIER)
                tp_price = last_tick_price - (atr_val * TP_ATR_MULTIPLIER)

            # Clamp SL so max loss does not exceed CAPITAL_PER_TRADE
            order_capital = CAPITAL_PER_TRADE
            order_size_usd = calculate_order_size_usd(order_capital, LEVERAGE)
            commission = calculate_commission(order_size_usd, pair)

            # Calculate PnL at the proposed SL
            pnl_at_sl, _ = get_pnl_at_price(
                sl_price, last_tick_price, order_size_usd, LEVERAGE, order_type, commission
            )

            # If loss at SL exceeds capital, tighten the SL
            if pnl_at_sl < -order_capital:
                sl_price, _ = get_price_at_pnl(
                    desired_pnl=-order_capital,
                    entry_price=last_tick_price,
                    order_size_usd=order_size_usd,
                    leverage=LEVERAGE,
                    type=order_type,
                    commission=commission,
                )
                logger.info(f"Clamped SL for {pair} to limit loss to ${order_capital:.2f}")

            # Convert to lots — uses trade_contract_size from MT5
            order_volume_lots = convert_usd_to_lots(pair, order_size_usd, order_type)

            if isinstance(order_volume_lots, (pd.Series, pd.DataFrame)):
                order_volume_lots = order_volume_lots.iloc[0] if not order_volume_lots.empty else 0.0

            # Validate against broker's volume_min (varies per symbol)
            contract_info = get_symbol_contract_info(pair)
            broker_volume_min = contract_info['volume_min'] if contract_info else 0.01

            if order_volume_lots < broker_volume_min:
                logger.error(f"Order volume too low for {pair}: {order_volume_lots:.4f} < broker min {broker_volume_min}")
                continue

            # Validate SL direction
            if order_type == 'BUY' and sl_price >= tick_info['bid'].iloc[0]:
                logger.error(f"SL too high for BUY on {pair}.")
                continue
            if order_type == 'SELL' and sl_price <= tick_info['ask'].iloc[0]:
                logger.error(f"SL too low for SELL on {pair}.")
                continue

            # Send order
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
                logger.info({
                    'event': 'scalping_trade_opened',
                    'symbol': pair,
                    'type': order_type,
                    'entry_condition': f"EMA({EMA_FAST}/{EMA_SLOW}) {signal}, RSI={rsi_val:.1f}",
                    'capital': f"${order_capital:.2f}",
                    'sl': f"{sl_price:.{price_decimals}f}",
                    'tp': f"{tp_price:.{price_decimals}f}",
                    'atr': f"{atr_val:.{price_decimals}f}",
                })

                try:
                    create_trade(
                        order, pair, order_capital, order_size_usd,
                        LEVERAGE, commission, order_type, 'Alpari',
                        'FOREX', 'SCALPING', MAIN_TIMEFRAME, order_volume_lots,
                        sl_price, tp_price,
                    )
                except Exception as e:
                    logger.error(f"Error creating trade record: {e}\n{traceback.format_exc()}")
            else:
                logger.error({
                    'event': 'scalping_trade_failed',
                    'symbol': pair,
                    'type': order_type,
                    'volume': order_volume_lots,
                })

    except Exception as e:
        logger.error(f"Exception in scalping entry_algorithm: {e}\n{traceback.format_exc()}")
