import logging
from django.utils import timezone

logger = logging.getLogger('app.polymarket')


def sync_markets():
    """Sync markets from Polymarket CLOB API into database."""
    from app.polymarket.models import PolyMarket
    from .client import get_markets

    raw_markets = get_markets()
    created, updated = 0, 0

    for m in raw_markets:
        condition_id = m.get('condition_id', '')
        if not condition_id:
            continue

        defaults = {
            'question': m.get('question', ''),
            'description': m.get('description', ''),
            'category': m.get('category', ''),
            'end_date': m.get('end_date_iso') or m.get('end_date'),
            'is_active': m.get('active', True),
            'outcomes': m.get('outcomes', ['Yes', 'No']),
            'token_ids': [t.get('token_id', '') for t in m.get('tokens', [])],
        }

        # Get current market price from tokens
        tokens = m.get('tokens', [])
        if tokens:
            # First token is typically YES
            yes_price = float(tokens[0].get('price', 0.5))
            defaults['market_price'] = yes_price

        obj, was_created = PolyMarket.objects.update_or_create(
            condition_id=condition_id,
            defaults=defaults,
        )
        if was_created:
            created += 1
        else:
            updated += 1

    logger.info(f"Market sync complete: {created} created, {updated} updated")
    return {'created': created, 'updated': updated}


def entry_algorithm():
    """Main entry algorithm: sync markets, estimate probabilities, open positions on +EV."""
    from app.polymarket.models import PolyMarket, PolyPosition, PolyTrade
    from .config import EV_THRESHOLD, MAX_POSITIONS, CAPITAL_USD
    from .estimator import estimate_probability
    from .sizing import calculate_position_size
    from .pricing import compute_ev, compute_ev_no
    from .client import place_market_order

    # 1. Sync markets
    sync_markets()

    # 2. Check current open positions count
    open_count = PolyPosition.objects.filter(status='OPEN').count()
    if open_count >= MAX_POSITIONS:
        logger.info(f"Max positions reached ({open_count}/{MAX_POSITIONS}), skipping entry.")
        return

    # 3. Get active markets and estimate probabilities
    markets = PolyMarket.objects.filter(is_active=True).order_by('-last_synced')

    for market in markets:
        if PolyPosition.objects.filter(status='OPEN').count() >= MAX_POSITIONS:
            logger.info("Max positions reached during iteration, stopping.")
            break

        # Skip markets we already have positions in
        if market.positions.filter(status='OPEN').exists():
            logger.debug(f"Skipping '{market.question[:50]}': already have position")
            continue

        # Skip if no token IDs
        if not market.token_ids:
            continue

        # Estimate probability via LLM
        estimate = estimate_probability(market)
        if not estimate:
            continue

        model_prob = estimate['probability']
        market_price = market.market_price

        # Calculate EV for both sides
        ev_yes = compute_ev(model_prob, market_price)
        ev_no = compute_ev_no(model_prob, market_price)

        # Determine best side
        if ev_yes >= EV_THRESHOLD:
            side = 'YES'
            ev = ev_yes
            token_id = market.token_ids[0] if market.token_ids else None
            entry_price = market_price
        elif ev_no >= EV_THRESHOLD:
            side = 'NO'
            ev = ev_no
            token_id = market.token_ids[1] if len(market.token_ids) > 1 else None
            entry_price = 1.0 - market_price
        else:
            logger.debug(f"No EV edge for '{market.question[:50]}': ev_yes={ev_yes:.3f}, ev_no={ev_no:.3f}")
            continue

        if not token_id:
            logger.warning(f"No token_id for {side} side of '{market.question[:50]}'")
            continue

        # Calculate position size
        sizing = calculate_position_size(model_prob, market_price, side)
        if sizing['size_usd'] < 1.0:
            logger.debug(f"Position too small for '{market.question[:50]}': ${sizing['size_usd']}")
            continue

        # Place order
        logger.info(f"Opening {side} position: '{market.question[:50]}' | EV={ev:.3f} | size=${sizing['size_usd']}")
        order_response = place_market_order(token_id, 'BUY', sizing['size_usd'])

        if order_response:
            # Create position record
            position = PolyPosition.objects.create(
                market=market,
                side=side,
                entry_price=entry_price,
                shares=sizing['shares'],
                cost_basis_usd=sizing['size_usd'],
                entry_ev=ev,
                entry_model_prob=model_prob,
                kelly_fraction=sizing['kelly_fraction'],
            )

            # Create trade record
            order_id = order_response.get('orderID', order_response.get('id', 'unknown'))
            PolyTrade.objects.create(
                position=position,
                order_id=str(order_id),
                token_id=token_id,
                side='BUY',
                price=entry_price,
                size=sizing['size_usd'],
                status='FILLED',
            )

            logger.info(f"Position opened: {side} '{market.question[:50]}' | ${sizing['size_usd']}")
        else:
            logger.error(f"Failed to open position for '{market.question[:50]}'")
