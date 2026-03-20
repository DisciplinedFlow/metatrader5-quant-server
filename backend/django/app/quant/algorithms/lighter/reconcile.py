"""
Lighter.xyz Position Reconciliation — keeps DB in sync with exchange.

Runs every 60s. Compares DB open positions with actual Lighter exchange positions.
Fixes two types of drift:
1. Exchange has position, DB doesn't → create DB record (orphaned position)
2. DB shows open, exchange doesn't → mark CLOSED with estimated PnL + set cooldown

Also:
3. cleanup_oco_orphans() — cancels the surviving SL or TP when its counterpart fills

This ensures trailing stops, SL/TP, and exit phases always have accurate data.
"""
import logging
from django.utils import timezone
from django.core.cache import cache

from .config import LIGHTER_MARKETS, LIGHTER_LEVERAGE
from .client import get_account_info, get_best_bid_ask

logger = logging.getLogger('app.lighter')

PLATFORM_PREFIX = 'lighter:'

# Reverse lookup: market_id -> symbol
ID_TO_SYMBOL = {v['id']: k for k, v in LIGHTER_MARKETS.items()}

# Cooldown after a position vanishes from exchange — prevents re-entry loop
VANISH_COOLDOWN_SECONDS = 600  # 10 minutes


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
        cache.set('lighter:collateral', float(a.collateral), timeout=90)
    except Exception:
        pass

    # Build exchange position map: symbol -> {side, size, entry_price}
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

    # ── Fix 2: DB shows open, exchange doesn't → record as CLOSED + cooldown ──
    for symbol, db_pos in db_symbols.items():
        if symbol not in exchange_positions:
            # Grace period: don't touch positions opened < 90s ago (fill settlement race)
            if db_pos.opened_at and (timezone.now() - db_pos.opened_at).total_seconds() < 90:
                logger.debug("RECONCILE: Skipping %s — opened %ds ago (grace period)",
                             symbol, (timezone.now() - db_pos.opened_at).total_seconds())
                continue

            # Estimate PnL from last known price
            estimated_pnl = 0.0
            try:
                prices = get_best_bid_ask(symbol)
                close_price = prices.get('mid')
                if close_price and close_price > 0:
                    if db_pos.side == 'LONG':
                        estimated_pnl = (close_price - db_pos.entry_price) * db_pos.size
                    else:
                        estimated_pnl = (db_pos.entry_price - close_price) * db_pos.size
                    db_pos.close_price = close_price
            except Exception:
                pass

            # Mark as CLOSED — not delete — so PnL is tracked
            db_pos.status = 'CLOSED'
            db_pos.close_reason = 'SYNC'
            db_pos.closed_at = timezone.now()
            db_pos.pnl_usd = estimated_pnl
            db_pos.save()

            # Set cooldown to prevent immediate re-entry loop
            cache.set(f'lighter:vanish_cooldown:{symbol}', True, timeout=VANISH_COOLDOWN_SECONDS)

            logger.warning(
                "RECONCILE: %s %s vanished from exchange — marked CLOSED "
                "(id=%d, est_pnl=$%.4f, cooldown=%ds)",
                symbol, db_pos.side, db_pos.id, estimated_pnl, VANISH_COOLDOWN_SECONDS,
            )

    # ── Additional reconcile duties ──
    try:
        cleanup_oco_orphans(exchange_positions)
    except Exception as e:
        logger.debug("OCO cleanup during reconcile failed: %s", e)


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
