"""
Trailing stop algorithm for CVD strategies.

Monitors open positions and adjusts stop-loss levels as profit grows,
using the same trailing step logic as the mean reversion trailing stop.
"""

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
from app.utils.constants import TIMEZONE
from app.utils.api.positions import get_positions
from app.utils.api.order import modify_sl_tp
from app.utils.db.mutation import mutate_trade
from app.utils.db.get import get_trade_with_mutations
from app.quant.algorithms.cvd.config import TRAILING_STOP_STEPS

logger = logging.getLogger(__name__)

EPSILON = 1e-4


def trailing_stop_algorithm():
    try:
        current_time = datetime.now(TIMEZONE).replace(microsecond=0)
        positions = get_positions()

        if positions is None or positions.empty:
            logger.info('CVD trailing: No positions found')
            return

        for index, position in positions.iterrows():
            position_start_time = perf_counter()

            trade_with_mutations = get_trade_with_mutations(position.ticket)
            if trade_with_mutations is None:
                logger.error(f"CVD trailing: No trade found with ticket {position.ticket}")
                continue

            trade = trade_with_mutations.get("trade")
            mutations = trade_with_mutations.get("mutations", [])

            current_sl_pnl, _ = get_pnl_at_price(
                position.sl, position.price_open, trade.position_size_usd,
                trade.leverage, trade.type, trade.order_commission
            )

            for trailing_step in TRAILING_STOP_STEPS:
                trigger_pnl = trade.capital * trailing_step['trigger_pnl_multiplier']
                new_sl_pnl = trade.capital * trailing_step['new_sl_pnl_multiplier']

                trigger_price, _ = get_price_at_pnl(
                    desired_pnl=trigger_pnl,
                    entry_price=position.price_open,
                    commission=trade.order_commission,
                    order_size_usd=trade.position_size_usd,
                    leverage=trade.leverage,
                    type=trade.type
                )

                new_sl_price, _ = get_price_at_pnl(
                    desired_pnl=new_sl_pnl,
                    commission=trade.order_commission,
                    order_size_usd=trade.position_size_usd,
                    leverage=trade.leverage,
                    entry_price=position.price_open,
                    type=trade.type
                )

                trigger_pnl, _ = get_pnl_at_price(
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
                    position.profit is not None and trigger_pnl is not None
                    and position.sl is not None and new_sl_price is not None
                )

                if nothing_is_none and position.profit >= trigger_pnl:
                    if (trade.type == 'BUY' and new_sl_price > position.sl + EPSILON) or \
                       (trade.type == 'SELL' and new_sl_price < position.sl - EPSILON):
                        modify_request = modify_sl_tp(position, new_sl_price)
                        if modify_request is not None:
                            logger.info(f"CVD trailing: Modified SL for {position.symbol} "
                                        f"ticket={position.ticket} new_sl={new_sl_price:.5f}")
                            mutation = mutate_trade(position, current_time, new_sl_price, pnl_at_new_sl)
                            if mutation is not None:
                                logger.info(f"CVD trailing: Mutation created for ticket {position.ticket}")
                        else:
                            logger.warning(f"CVD trailing: Failed to modify SL for {position.symbol}")
                        break

            position_duration = perf_counter() - position_start_time
            logger.info(f"CVD trailing: Processed ticket {position.ticket} in {position_duration:.4f}s")

    except Exception as e:
        logger.error(f"CVD trailing exception: {e}\n{traceback.format_exc()}")
