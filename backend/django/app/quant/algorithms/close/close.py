import traceback
import logging
from datetime import datetime, timedelta
from time import sleep

import pandas as pd

from app.utils.api.positions import get_positions
from app.utils.api.ticket import get_order_from_ticket, get_deal_from_ticket
from app.utils.constants import TIMEZONE
from app.utils.db.close import close_trade

logger = logging.getLogger(__name__)

# Dictionary to cache open positions between runs
cached_positions = {}

def close_algorithm():
    """
    Continuously monitors open trades, detects closed trades, and updates their
    corresponding Trade records in the database with closing details.
    """
    global cached_positions

    try:
        current_time = datetime.now(TIMEZONE).replace(microsecond=0)

        # Fetch current open positions
        positions = get_positions()
        if positions.empty:
            positions = pd.DataFrame(columns=[
                'ticket', 'time', 'time_msc', 'time_update', 'time_update_msc', 'type',
                'magic', 'identifier', 'reason', 'volume', 'price_open', 'sl', 'tp',
                'price_current', 'swap', 'profit', 'symbol', 'comment', 'external_id'
            ])

        # Convert time fields to datetime
        positions['time'] = pd.to_datetime(positions['time'], unit='s', utc=True)
        positions['time_update'] = pd.to_datetime(positions['time_update'], unit='s', utc=True)

        # Detect closed trades by comparing cached_positions with current positions
        current_tickets = set(positions['ticket'].values)
        cached_tickets = set(cached_positions.keys())

        # Identify closed tickets
        closed_tickets = cached_tickets - current_tickets

        for ticket in closed_tickets:
            position = cached_positions.pop(ticket)
            sleep(0.5)  # Brief delay to ensure the trade is fully processed

            try:
                # Retrieve the closed order and deal details
                closed_order = get_order_from_ticket(ticket)
                now = datetime.now(TIMEZONE)
                closed_deal = get_deal_from_ticket(ticket, now - timedelta(hours=24), now)

                if closed_deal is not None:
                    close_time = closed_deal.get('time', current_time)
                    close_price = closed_deal.get('price', position.price_current)
                    pnl = closed_deal.get('profit', position.profit)
                    pnl_excluding_commission = pnl - closed_deal.get('commission', 0)
                    closing_reason = closed_deal.get('reason', 'CLOSED')
                else:
                    # Fallback: use cached position data when deal history is unavailable
                    logger.debug(f"No deal history for ticket {ticket}, using cached position data.")
                    close_time = current_time
                    close_price = position.price_current
                    pnl = position.profit
                    pnl_excluding_commission = pnl
                    closing_reason = 'SL/TP'
                    closed_deal = {}

                # Update the Trade record in the database
                closed_trade = close_trade(position.ticket, close_time, close_price, pnl, pnl_excluding_commission, closing_reason, closed_deal)

                # Release PairLock for this ticket
                try:
                    from app.nexus.models import PairLock
                    deleted_count, _ = PairLock.objects.filter(ticket=ticket).delete()
                    if deleted_count:
                        logger.info(f"PairLock released for ticket {ticket}")
                except Exception as e:
                    logger.warning(f"Error releasing PairLock for ticket {ticket}: {e}")

                if closed_trade is not None:
                    logger.info({
                        "event": "trade_closed",
                        "trade_id": closed_trade.id,
                        "symbol": closed_trade.symbol,
                    })

                    # Update ML features with actual outcome
                    try:
                        _update_ml_features(closed_trade)
                    except Exception as e:
                        logger.debug(f"ML feature update skipped: {e}")
                else:
                    error_msg = f"Failed to close trade {ticket}."
                    logger.error({"error": error_msg, "ticket": ticket})

            except Exception as e:
                error_msg = f"Error processing closed ticket {ticket}: {e}\n{traceback.format_exc()}"
                logger.error({"error": error_msg, "ticket": ticket})

        # Clean up stale PairLocks
        _cleanup_stale_locks(positions)

        # Detect orphaned Django trades (open in DB but gone from MT5)
        _close_orphaned_trades(current_tickets, current_time)

        # Update cached_positions with current open positions
        for index, position in positions.iterrows():
            cached_positions[position.ticket] = position

    except Exception as e:
        error_msg = f"Exception in close_algorithm: {e}\n{traceback.format_exc()}"
        logger.error({"error": error_msg})


def _close_orphaned_trades(current_mt5_tickets, current_time):
    """Close Django Trade records that have no corresponding MT5 position.

    This catches trades that were closed on MT5's side (via SL/TP/manual)
    but missed by the close algorithm due to worker restarts wiping the
    in-memory cached_positions dict.
    """
    try:
        from app.nexus.models import Trade

        open_trades = Trade.objects.filter(close_time__isnull=True)
        if not open_trades.exists():
            return

        mt5_tickets_str = {str(t) for t in current_mt5_tickets}

        for trade in open_trades:
            ticket_str = str(trade.transaction_broker_id)
            ticket_int = int(trade.transaction_broker_id)

            if ticket_str in mt5_tickets_str:
                continue  # Still open on MT5, not an orphan

            # This trade is open in Django but gone from MT5 — it's an orphan
            # Try to get deal history for accurate close data
            try:
                now = datetime.now(TIMEZONE)
                deal = get_deal_from_ticket(ticket_int, now - timedelta(hours=48), now)

                if deal is not None:
                    trade.close_time = deal.get('time', current_time)
                    trade.close_price = deal.get('price', trade.entry_price)
                    trade.pnl = deal.get('profit', 0)
                    trade.pnl_excluding_commission = trade.pnl - deal.get('commission', 0)
                    trade.closing_reason = 'ORPHAN_SYNCED'
                else:
                    trade.close_time = current_time
                    trade.close_price = trade.entry_price
                    trade.pnl = 0
                    trade.pnl_excluding_commission = 0
                    trade.closing_reason = 'ORPHAN_NO_DEAL'

                trade.save(update_fields=[
                    'close_time', 'close_price', 'pnl',
                    'pnl_excluding_commission', 'closing_reason',
                ])
                logger.warning(
                    f"ORPHAN CLOSED: {trade.symbol} ticket={ticket_str} "
                    f"PnL=${trade.pnl:.2f} reason={trade.closing_reason}"
                )

                # Update ML features for orphaned trade
                try:
                    _update_ml_features(trade)
                except Exception as e:
                    logger.debug(f"ML feature update skipped for orphan: {e}")

            except Exception as e:
                logger.error(f"Error closing orphan ticket {ticket_str}: {e}")

    except Exception as e:
        logger.error(f"Orphan detection error: {e}")


def _cleanup_stale_locks(positions):
    """Remove PairLocks for positions that no longer exist on MT5.

    Handles edge cases like crashes or missed close events where a PairLock
    lingers without a corresponding MT5 position.
    """
    try:
        from app.nexus.models import PairLock

        current_tickets = set()
        if positions is not None and not positions.empty:
            current_tickets = set(positions['ticket'].values)

        # Find PairLocks with non-zero tickets that aren't in current positions
        stale = PairLock.objects.exclude(ticket__in=current_tickets).exclude(ticket=0)
        if stale.exists():
            count = stale.count()
            logger.info(f"Cleaning {count} stale PairLocks")
            stale.delete()
    except Exception as e:
        logger.warning(f"Error cleaning stale PairLocks: {e}")


def _update_ml_features(closed_trade):
    """Update TradeFeature with actual outcome and generate LLM training data."""
    from app.nexus.models import TradeFeature

    try:
        tf = TradeFeature.objects.filter(trade=closed_trade).first()
        if tf is None:
            return  # Trade was placed before ML system was active

        won = closed_trade.pnl > 0 if closed_trade.pnl else False
        tf.actual_win = won
        tf.save(update_fields=['actual_win', 'updated_at'])

        # Generate LLM training data
        from app.quant.ml.data_collector import generate_training_example, save_training_example
        example = generate_training_example(closed_trade, tf)
        save_training_example(example)

        # Check if model should retrain
        from app.quant.ml.trainer import should_retrain
        if should_retrain():
            logger.info("ML: Retraining triggered after new trade outcome")
            from app.quant.ml.trainer import train_model
            train_model()

    except Exception as e:
        logger.debug(f"ML feature update error: {e}")
