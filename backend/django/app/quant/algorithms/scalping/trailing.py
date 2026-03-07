import traceback
import logging
from datetime import datetime
from time import perf_counter

from app.utils.arithmetics import (
    calculate_trade_volume,
    convert_usd_to_lots,
    get_price_at_pnl,
    get_pnl_at_price,
)
from app.utils.api.positions import get_positions
from app.utils.api.order import modify_sl_tp
from app.utils.db.mutation import mutate_trade
from app.utils.db.get import get_trade_with_mutations
from app.utils.constants import TIMEZONE
from app.quant.algorithms.scalping.config import TRAILING_STOP_STEPS

logger = logging.getLogger(__name__)

EPSILON = 1e-4


def trailing_stop_algorithm():
    """
    Trailing stop algorithm for the SCALPING strategy.
    Same logic as mean_reversion trailing but uses tighter scalping steps.
    Only processes trades that belong to the SCALPING strategy.
    """
    try:
        current_time = datetime.now(TIMEZONE).replace(microsecond=0)
        positions = get_positions()

        if positions.empty:
            logger.info('No positions found for scalping trailing stop')
            return

        for index, position in positions.iterrows():
            position_start_time = perf_counter()

            trade_with_mutations = get_trade_with_mutations(position.ticket)
            if trade_with_mutations is None:
                logger.error(f"No trade found with ticket {position.ticket}")
                continue

            trade = trade_with_mutations.get("trade")

            # Only process SCALPING trades
            if trade.strategy != 'SCALPING':
                continue

            current_sl_pnl, current_sl_pnl_excluding_commission = get_pnl_at_price(
                position.sl, position.price_open, trade.position_size_usd,
                trade.leverage, trade.type, trade.order_commission
            )

            for trailing_step in TRAILING_STOP_STEPS:
                trigger_pnl = trade.capital * trailing_step['trigger_pnl_multiplier']
                new_sl_pnl = trade.capital * trailing_step['new_sl_pnl_multiplier']

                trigger_price, trigger_price_excl = get_price_at_pnl(
                    desired_pnl=trigger_pnl,
                    entry_price=position.price_open,
                    commission=trade.order_commission,
                    order_size_usd=trade.position_size_usd,
                    leverage=trade.leverage,
                    type=trade.type
                )

                new_sl_price, new_sl_price_excl = get_price_at_pnl(
                    desired_pnl=new_sl_pnl,
                    commission=trade.order_commission,
                    order_size_usd=trade.position_size_usd,
                    leverage=trade.leverage,
                    entry_price=position.price_open,
                    type=trade.type
                )

                trigger_pnl_calc, _ = get_pnl_at_price(
                    current_price=trigger_price,
                    entry_price=position.price_open,
                    order_size_usd=trade.position_size_usd,
                    leverage=trade.leverage,
                    type=trade.type,
                    commission=trade.order_commission
                )

                pnl_at_new_sl, _ = get_pnl_at_price(
                    current_price=new_sl_price,
                    entry_price=position.price_open,
                    order_size_usd=trade.position_size_usd,
                    leverage=trade.leverage,
                    type=trade.type,
                    commission=trade.order_commission
                )

                nothing_is_none = (
                    position.profit is not None
                    and trigger_pnl_calc is not None
                    and position.sl is not None
                    and new_sl_price is not None
                )

                if nothing_is_none and position.profit >= trigger_pnl_calc:
                    is_better_sl = (
                        (trade.type == 'BUY' and new_sl_price > position.sl + EPSILON)
                        or (trade.type == 'SELL' and new_sl_price < position.sl - EPSILON)
                    )

                    if is_better_sl:
                        logger.info({
                            'event': 'scalping_trailing_stop_triggered',
                            'symbol': position.symbol,
                            'type': trade.type,
                            'current_pnl': f"${position.profit:.5f}",
                            'old_sl': f"${position.sl:.5f}",
                            'new_sl': f"${new_sl_price:.5f}",
                            'pnl_at_new_sl': f"${pnl_at_new_sl:.5f}",
                        })

                        modify_request = modify_sl_tp(position, new_sl_price)
                        if modify_request is not None:
                            logger.info(f"Scalping trailing SL modified for {position.symbol}")
                            mutate_trade(position, current_time, new_sl_price, pnl_at_new_sl)
                        else:
                            logger.error(f"Failed to modify scalping trailing SL for {position.symbol}")

                        break

            position_duration = perf_counter() - position_start_time
            logger.info(f"Processed scalping trailing for {position.ticket} in {position_duration:.4f}s")

    except Exception as e:
        logger.error(f"Exception in scalping trailing_stop_algorithm: {e}\n{traceback.format_exc()}")
