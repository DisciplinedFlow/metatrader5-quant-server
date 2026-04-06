import traceback
import logging
from datetime import datetime, timedelta
from time import sleep

import pandas as pd

from app.utils.api.positions import get_positions
from app.utils.api.ticket import get_order_from_ticket, get_deal_from_ticket, history_deals_bulk
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

            try:
                # Retrieve the closed order and deal details
                closed_order = get_order_from_ticket(ticket)

                # Retry up to 3 times — MT5 can take 1-2s to finalise deal history
                closed_deal = None
                for _attempt in range(3):
                    now = datetime.now(TIMEZONE)
                    closed_deal = get_deal_from_ticket(ticket, now - timedelta(hours=24), now)
                    if closed_deal is not None:
                        break
                    sleep(0.5)

                if closed_deal is not None:
                    close_time = closed_deal.get('close_time', current_time)
                    close_price = closed_deal.get('close_price', position.price_current)
                    pnl = closed_deal.get('profit', position.profit)
                    pnl_excluding_commission = pnl - closed_deal.get('commission', 0)
                    closing_reason = closed_deal.get('reason', 'SL/TP')
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
                    _on_trade_closed(closed_trade, ticket, close_price, pnl, closing_reason)
                else:
                    logger.error({"error": f"Failed to close trade {ticket}.", "ticket": ticket})

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

                if deal is not None and deal.get('still_open'):
                    # Deal exists but no exit yet — skip, will retry next cycle
                    logger.debug(f"Orphan {ticket_str}: deal found but still_open, skipping")
                    continue

                if deal is not None and not deal.get('still_open'):
                    trade.close_time = deal.get('close_time', current_time)
                    trade.close_price = deal.get('close_price', trade.entry_price)
                    trade.pnl = deal.get('profit', 0)
                    trade.pnl_excluding_commission = trade.pnl - deal.get('commission', 0)
                    trade.closing_reason = 'ORPHAN_SYNCED'
                elif deal is None:
                    # No deals at all — likely a phantom order (accepted but never filled)
                    # Delete phantom trades instead of recording fake pnl=0
                    logger.warning(
                        f"PHANTOM DELETED: {trade.symbol} ticket={ticket_str} "
                        f"— no deals found, order never filled"
                    )
                    trade.delete()
                    continue

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


def _on_trade_closed(closed_trade, ticket, close_price, pnl, closing_reason):
    """Run all post-close side effects (WebSocket, ML, graph, brain pattern)."""
    # Broadcast via WebSocket
    try:
        from app.ws.publisher import publish_trade_closed
        publish_trade_closed({
            'trade_id': closed_trade.id,
            'symbol': closed_trade.symbol,
            'type': closed_trade.type,
            'pnl': float(closed_trade.pnl) if closed_trade.pnl else 0,
            'close_price': float(close_price) if close_price else 0,
            'closing_reason': closing_reason,
            'strategy': getattr(closed_trade, 'strategy', ''),
        })
    except Exception:
        pass

    # Update ML features with actual outcome
    try:
        _update_ml_features(closed_trade)
    except Exception as e:
        logger.debug(f"ML feature update skipped: {e}")

    # Update circuit breaker + daily loss tracking
    try:
        from app.quant.algorithms.entry_forex import on_trade_closed as fx_on_trade_closed
        won = pnl > 0 if pnl else False
        fx_on_trade_closed(won=won, pnl=float(pnl) if pnl else 0)
    except Exception as e:
        logger.debug(f"Circuit breaker update skipped: {e}")


def _update_ml_features(closed_trade):
    """Update TradeFeature with actual outcome and generate LLM training data."""
    from app.nexus.models import TradeFeature

    try:
        tf = TradeFeature.objects.filter(trade=closed_trade).first()
        if tf is None:
            return

        won = closed_trade.pnl > 0 if closed_trade.pnl else False
        tf.actual_win = won
        tf.save(update_fields=['actual_win', 'updated_at'])

        from app.quant.ml.data_collector import generate_training_example, save_training_example
        example = generate_training_example(closed_trade, tf)
        save_training_example(example)

        from app.quant.ml.trainer import should_retrain
        if should_retrain():
            logger.info("ML: Retraining triggered after new trade outcome")
            from app.quant.ml.trainer import train_model
            train_model()

    except Exception as e:
        logger.debug(f"ML feature update error: {e}")


def reconcile_positions():
    """Reconcile MT5 broker positions with Django Trade records.

    Fixes both directions of desync:
    1. MT5 position exists but no DB record → create Trade record
    2. DB record is open but MT5 position gone → close Trade with deal history

    Should run every 30-60s alongside close_algorithm.
    """
    try:
        from app.nexus.models import Trade
        from django.utils import timezone

        positions = get_positions()
        if positions is None or positions.empty:
            return

        mt5_tickets = {}
        for _, p in positions.iterrows():
            mt5_tickets[int(p.ticket)] = p

        db_open = Trade.objects.filter(close_time__isnull=True)
        db_tickets = {int(t.transaction_broker_id): t for t in db_open}

        # --- Direction 1: MT5 position without DB record → create Trade ---
        for ticket, pos in mt5_tickets.items():
            if ticket in db_tickets:
                continue

            # This MT5 position has no DB record — create one
            symbol = pos.symbol
            order_type = 'BUY' if int(pos.type) == 0 else 'SELL'
            entry_price = float(pos.price_open)
            volume = float(pos.volume)
            entry_time = pos.time if hasattr(pos, 'time') and pos.time else timezone.now()

            # Infer strategy from magic number or default
            strategy = 'RECONCILED'
            if hasattr(pos, 'magic') and pos.magic:
                magic = int(pos.magic)
                if magic == 234000:
                    strategy = 'CVD_RECONCILED'
                elif magic == 0:
                    strategy = 'SCALPING_RECONCILED'

            try:
                trade = Trade.objects.create(
                    transaction_broker_id=str(ticket),
                    symbol=symbol,
                    entry_time=entry_time,
                    entry_price=entry_price,
                    type=order_type,
                    order_volume=volume,
                    position_size_usd=0,
                    capital=0,
                    leverage=0,
                    liquidity_price=entry_price,
                    break_even_price=entry_price,
                    order_commission=0,
                    strategy=strategy,
                    broker='VantageInternational-Demo',
                    market_type='FOREX',
                    timeframe='M15',
                )
                logger.warning(
                    f"RECONCILE: Created DB record for MT5 position "
                    f"{symbol} {order_type} ticket={ticket} vol={volume} "
                    f"entry={entry_price}"
                )
            except Exception as e:
                logger.error(f"RECONCILE: Failed to create Trade for ticket {ticket}: {e}")

        # --- Direction 2: DB record open but gone from MT5 → close Trade ---
        # Collect orphaned tickets (open in DB, gone from MT5)
        orphan_tickets = {}
        for ticket, trade in db_tickets.items():
            if ticket in mt5_tickets:
                continue
            if trade.closing_reason:
                continue  # Already being processed
            orphan_tickets[ticket] = trade

        if orphan_tickets:
            # Bulk-fetch ALL deals in last 48h in a single API call
            now = datetime.now(TIMEZONE)
            all_deals = history_deals_bulk(now - timedelta(hours=48), now)

            # Index deals by position_id for fast lookup
            deals_by_position = {}
            for d in all_deals:
                pos_id = d.get('position_id')
                if pos_id:
                    deals_by_position.setdefault(pos_id, []).append(d)

            for ticket, trade in orphan_tickets.items():
                try:
                    pos_deals = deals_by_position.get(ticket, [])
                    entry_deals = [d for d in pos_deals if d.get('entry') == 0]
                    exit_deals = [d for d in pos_deals if d.get('entry') == 1]

                    if exit_deals:
                        exit_deal = exit_deals[-1]
                        total_profit = sum(d.get('profit', 0) for d in pos_deals)
                        total_commission = sum(d.get('commission', 0) for d in pos_deals)

                        trade.close_time = datetime.fromtimestamp(exit_deal['time'], tz=TIMEZONE) if 'time' in exit_deal else now
                        trade.close_price = exit_deal.get('price', trade.entry_price)
                        trade.pnl = total_profit
                        trade.pnl_excluding_commission = total_profit - total_commission
                        trade.closing_reason = 'RECONCILE_SYNCED'
                    else:
                        trade.close_time = now
                        trade.close_price = trade.entry_price
                        trade.pnl = 0
                        trade.pnl_excluding_commission = 0
                        trade.closing_reason = 'RECONCILE_NO_DEAL'

                    trade.save(update_fields=[
                        'close_time', 'close_price', 'pnl',
                        'pnl_excluding_commission', 'closing_reason',
                    ])
                    logger.warning(
                        f"RECONCILE: Closed orphan {trade.symbol} ticket={ticket} "
                        f"PnL=${trade.pnl:.2f} reason={trade.closing_reason}"
                    )
                except Exception as e:
                    logger.error(f"RECONCILE: Error closing orphan ticket {ticket}: {e}")

    except Exception as e:
        logger.error(f"Reconciliation error: {e}\n{traceback.format_exc()}")
