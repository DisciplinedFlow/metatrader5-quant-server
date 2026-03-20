"""
Lighter.xyz Position Reconciliation — keeps DB in sync with exchange.

Runs every 60s. Compares DB open positions with actual Lighter exchange positions.
Fixes two types of drift:
1. Exchange has position, DB doesn't → create DB record (orphaned position)
2. DB shows open, exchange doesn't → mark DB as closed (stale record)

Also:
3. sync_neo4j() — backfills closed Lighter trades into the Neo4j knowledge graph
4. cleanup_oco_orphans() — cancels the surviving SL or TP when its counterpart fills

This ensures trailing stops, SL/TP, and exit phases always have accurate data.
"""
import logging
from django.utils import timezone

from .config import LIGHTER_MARKETS, LIGHTER_LEVERAGE
from .client import get_account_info, get_best_bid_ask

logger = logging.getLogger('app.lighter')

PLATFORM_PREFIX = 'lighter:'

# Reverse lookup: market_id -> symbol
ID_TO_SYMBOL = {v['id']: k for k, v in LIGHTER_MARKETS.items()}

# Redis key for tracking the last Neo4j sync timestamp
_NEO4J_SYNC_KEY = 'lighter:neo4j_last_sync_id'


def reconcile_positions():
    """Sync DB positions with actual Lighter exchange state."""
    from app.crypto.models import CryptoPosition

    try:
        acct = get_account_info()
        a = acct.accounts[0] if hasattr(acct, 'accounts') and acct.accounts else None
        if not a:
            return
    except Exception as e:
        logger.debug("Reconcile: failed to fetch account: %s", e)
        return

    # Cache collateral so entry algorithms can guard without extra API calls
    try:
        from django.core.cache import cache
        cache.set('lighter:collateral', float(a.collateral), timeout=90)
    except Exception:
        pass

    # Build exchange position map: symbol -> {side, size, entry_price}
    # pos.position is always the absolute size — use pos.sign for direction:
    # sign=1 → LONG, sign=-1 → SHORT (pos.position > 0 is always True, useless for direction)
    exchange_positions = {}
    for pos in (a.positions or []):
        size = float(pos.position)
        if size != 0:
            market_id = int(pos.market_id)
            symbol = ID_TO_SYMBOL.get(market_id)
            if symbol:
                sign = int(pos.sign) if hasattr(pos, 'sign') and pos.sign is not None else 1
                exchange_positions[symbol] = {
                    'side': 'LONG' if sign > 0 else 'SHORT',
                    'size': size,
                    'entry_price': float(pos.avg_entry_price),
                }

    # Get all DB open positions for Lighter
    db_open = CryptoPosition.objects.filter(
        status='OPEN',
        entry_signal__startswith=PLATFORM_PREFIX,
    )
    db_symbols = {p.symbol: p for p in db_open}

    # Also check by venue
    db_open_venue = CryptoPosition.objects.filter(
        status='OPEN',
        venue='LIGHTER',
    )
    for p in db_open_venue:
        if p.symbol not in db_symbols:
            db_symbols[p.symbol] = p

    # ── Fix 1: Exchange has position, DB doesn't → create DB record ──
    for symbol, exch in exchange_positions.items():
        if symbol not in db_symbols:
            # Orphaned position on exchange — create DB record so exit algo can manage it
            try:
                prices = get_best_bid_ask(symbol)
                current_price = prices.get('mid', exch['entry_price'])
            except Exception:
                current_price = exch['entry_price']

            # Calculate SL/TP based on asset class
            if symbol in ('EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'USDCAD', 'AUDUSD', 'NZDUSD'):
                sl_pct, tp_pct = 0.005, 0.01
            elif symbol in ('XAU', 'XAG', 'PAXG', 'WTI'):
                sl_pct, tp_pct = 0.015, 0.03
            else:
                sl_pct, tp_pct = 0.03, 0.06

            entry = exch['entry_price']
            is_long = exch['side'] == 'LONG'
            stop_loss = entry * (1 - sl_pct) if is_long else entry * (1 + sl_pct)
            take_profit = entry * (1 + tp_pct) if is_long else entry * (1 - tp_pct)

            position = CryptoPosition.objects.create(
                symbol=symbol,
                side=exch['side'],
                entry_price=entry,
                size=exch['size'],
                leverage=LIGHTER_LEVERAGE,
                entry_signal=f'{PLATFORM_PREFIX}reconciled',
                stop_loss=stop_loss,
                take_profit=take_profit,
                status='OPEN',
                venue='LIGHTER',
            )
            logger.info(
                "RECONCILE: Created DB record for orphaned %s %s position "
                "(entry=%.4f, size=%.6f, SL=%.4f, TP=%.4f, id=%d)",
                symbol, exch['side'], entry, exch['size'],
                stop_loss, take_profit, position.id,
            )

            # Record trade open to knowledge graph
            try:
                from app.quant.tasks import record_to_graph
                record_to_graph.delay({
                    'type': 'lighter_trade_open',
                    'trade_id': f'lighter_{position.id}',
                    'django_id': position.id,
                    'symbol': symbol,
                    'direction': 'BUY' if exch['side'] == 'LONG' else 'SELL',
                    'entry_time': position.opened_at,
                    'entry_price': float(entry),
                    'strategy': position.entry_signal or 'reconciled',
                    'venue': 'LIGHTER',
                    'hour_utc': position.opened_at.hour if position.opened_at else 0,
                    'day_of_week': position.opened_at.weekday() if position.opened_at else 0,
                    'trading_era': 'BRAIN_V1',
                })
            except Exception:
                pass

        else:
            # Position exists in both — update size/entry/side if they drifted
            db_pos = db_symbols[symbol]
            update_fields = []

            # Side flip (e.g., SHORT → LONG after position reversal)
            if db_pos.side != exch['side']:
                logger.info(
                    "RECONCILE: %s side flipped %s -> %s",
                    symbol, db_pos.side, exch['side'],
                )
                db_pos.side = exch['side']
                db_pos.entry_price = exch['entry_price']
                db_pos.size = exch['size']
                update_fields = ['side', 'entry_price', 'size']

            # Size/entry drift (>1%)
            elif abs(db_pos.size - exch['size']) / max(exch['size'], 0.0001) > 0.01:
                old_size = db_pos.size
                db_pos.size = exch['size']
                db_pos.entry_price = exch['entry_price']
                update_fields = ['size', 'entry_price']
                logger.info(
                    "RECONCILE: Updated %s size %.6f -> %.6f, entry -> %.4f",
                    symbol, old_size, exch['size'], exch['entry_price'],
                )

            if update_fields:
                db_pos.save(update_fields=update_fields)

    # ── Fix 2: DB shows open, exchange doesn't → delete stale DB record ──
    # Do NOT create fake CLOSED trades — they pollute ML training data.
    # The exit algorithm is the only source of truth for closed trades.
    for symbol, db_pos in db_symbols.items():
        if symbol not in exchange_positions:
            # Grace period: don't touch positions opened < 90s ago (fill settlement race)
            if db_pos.opened_at and (timezone.now() - db_pos.opened_at).total_seconds() < 90:
                logger.debug("RECONCILE: Skipping %s — opened %ds ago (grace period)",
                             symbol, (timezone.now() - db_pos.opened_at).total_seconds())
                continue

            logger.info(
                "RECONCILE: Deleting stale DB record %s %s (id=%d) — not on exchange",
                symbol, db_pos.side, db_pos.id,
            )
            db_pos.delete()

    # ── Additional reconcile duties ──
    try:
        sync_neo4j()
    except Exception as e:
        logger.debug("Neo4j sync during reconcile failed: %s", e)

    try:
        cleanup_oco_orphans(exchange_positions)
    except Exception as e:
        logger.debug("OCO cleanup during reconcile failed: %s", e)


def sync_neo4j():
    """Backfill closed Lighter trades into the Neo4j knowledge graph.

    Uses a Redis-stored last-synced position ID to avoid re-processing trades
    every cycle. Only processes trades closed since the last sync.
    Catches duplicate constraint violations and skips them.
    """
    from django.core.cache import cache
    from app.crypto.models import CryptoPosition

    try:
        from app.quant.knowledge.connection import get_graph
        graph = get_graph()
        if graph is None:
            return  # Neo4j not available
    except Exception:
        return

    # Get the last synced position ID (0 = never synced, backfill all)
    last_synced_id = cache.get(_NEO4J_SYNC_KEY, 0)

    # Get all closed Lighter trades with PnL, newer than last sync
    closed_trades = CryptoPosition.objects.filter(
        status='CLOSED',
        venue='LIGHTER',
        pnl_usd__isnull=False,
        id__gt=last_synced_id,
    ).order_by('id')

    if not closed_trades.exists():
        return

    synced = 0
    skipped = 0
    max_id = last_synced_id

    for pos in closed_trades:
        try:
            trade_data = {
                'trade_id': f'lighter_{pos.id}',
                'django_id': pos.id,
                'symbol': pos.symbol,
                'direction': 'BUY' if pos.side == 'LONG' else 'SELL',
                'entry_time': pos.opened_at,
                'close_time': pos.closed_at,
                'entry_price': float(pos.entry_price or 0),
                'close_price': float(pos.close_price or 0),
                'pnl': float(pos.pnl_usd or 0),
                'strategy': pos.entry_signal or 'unknown',
                'closing_reason': pos.close_reason or '',
                'venue': 'LIGHTER',
                'hour_utc': pos.opened_at.hour if pos.opened_at else 0,
                'day_of_week': pos.opened_at.weekday() if pos.opened_at else 0,
            }
            result = graph.record_trade(trade_data)
            if result:
                synced += 1
            else:
                skipped += 1
        except Exception as e:
            err_str = str(e)
            if 'already exists' in err_str or 'ConstraintValidation' in err_str:
                skipped += 1
            else:
                logger.debug("Neo4j sync error for position %d: %s", pos.id, e)
                skipped += 1

        if pos.id > max_id:
            max_id = pos.id

    # Update the watermark so we don't re-process these trades
    if max_id > last_synced_id:
        cache.set(_NEO4J_SYNC_KEY, max_id, timeout=None)  # persist indefinitely

    if synced > 0:
        logger.info("NEO4J SYNC: backfilled %d Lighter trades (%d skipped/dupes), watermark=%d",
                     synced, skipped, max_id)


def cleanup_oco_orphans(exchange_positions=None):
    """Cancel orphaned SL or TP orders when a position closes.

    For each tracked OCO pair, if the symbol no longer has an exchange position,
    both orders should be dead. If the symbol still has a position but one order
    filled (position size changed), we can't know which — let the exit algo handle it.

    In practice, the main case is: position closed entirely → cancel all orders for
    that symbol to avoid ghost triggers on future positions.
    """
    from .client import get_oco_pairs, remove_oco_pair, cancel_all_orders

    oco_pairs = get_oco_pairs()
    if not oco_pairs:
        return

    for pair in oco_pairs:
        symbol = pair.get('symbol')
        if not symbol:
            continue

        # If position is gone from exchange, cancel all orders for this symbol
        # to prevent ghost SL/TP triggering on future positions
        if exchange_positions is not None and symbol not in exchange_positions:
            try:
                cancel_all_orders(symbol)
                remove_oco_pair(symbol)
                logger.info("OCO CLEANUP: %s position gone, cancelled orphaned orders", symbol)
            except Exception as e:
                logger.debug("OCO cleanup failed for %s: %s", symbol, e)
