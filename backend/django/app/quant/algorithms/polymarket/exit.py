import logging
from django.utils import timezone

logger = logging.getLogger('app.polymarket')


def exit_algorithm():
    """Monitor open positions and exit on EV collapse, stop-loss, or resolution."""
    from app.polymarket.models import PolyPosition, PolyTrade
    from .config import EV_THRESHOLD, STOP_LOSS_THRESHOLD
    from .pricing import compute_ev, compute_ev_no
    from .client import place_market_order, get_market
    from .estimator import estimate_probability

    open_positions = PolyPosition.objects.filter(status='OPEN').select_related('market')

    for position in open_positions:
        market = position.market

        # Refresh market data
        market_data = get_market(market.condition_id)
        if market_data:
            tokens = market_data.get('tokens', [])
            if tokens:
                market.market_price = float(tokens[0].get('price', market.market_price))
                market.save(update_fields=['market_price'])

        # Check if market resolved
        if market_data and not market_data.get('active', True):
            _close_position(position, market.market_price, 'RESOLVED')
            continue

        # Re-estimate probability
        estimate = estimate_probability(market)
        if estimate:
            model_prob = estimate['probability']
        else:
            model_prob = market.model_probability or 0.5

        # Calculate current EV
        if position.side == 'YES':
            current_ev = compute_ev(model_prob, market.market_price)
            current_price = market.market_price
        else:
            current_ev = compute_ev_no(model_prob, market.market_price)
            current_price = 1.0 - market.market_price

        # Calculate P&L
        pnl_pct = (current_price - position.entry_price) / position.entry_price if position.entry_price > 0 else 0

        # Exit conditions
        close_reason = None

        # 1. EV collapsed below negative threshold
        if current_ev < -EV_THRESHOLD:
            close_reason = 'EV_COLLAPSE'
            logger.info(f"EV collapse for '{market.question[:50]}': EV={current_ev:.3f}")

        # 2. Stop loss hit
        elif pnl_pct < STOP_LOSS_THRESHOLD:
            close_reason = 'STOP_LOSS'
            logger.info(f"Stop loss for '{market.question[:50]}': PnL={pnl_pct:.1%}")

        if close_reason:
            _close_position(position, current_price, close_reason)


def _close_position(position, close_price, reason):
    """Close a position and record the trade."""
    from app.polymarket.models import PolyTrade
    from .client import place_market_order

    market = position.market
    token_idx = 0 if position.side == 'YES' else 1
    token_id = market.token_ids[token_idx] if len(market.token_ids) > token_idx else None

    if token_id:
        order_response = place_market_order(token_id, 'SELL', position.cost_basis_usd)

        if order_response:
            order_id = order_response.get('orderID', order_response.get('id', 'unknown'))
            PolyTrade.objects.create(
                position=position,
                order_id=str(order_id),
                token_id=token_id,
                side='SELL',
                price=close_price,
                size=position.cost_basis_usd,
                status='FILLED',
            )

    # Calculate PnL
    pnl = (close_price - position.entry_price) * position.shares

    position.status = 'CLOSED'
    position.close_price = close_price
    position.pnl_usd = round(pnl, 2)
    position.close_reason = reason
    position.closed_at = timezone.now()
    position.save()

    logger.info(f"Position closed: {position.side} '{market.question[:50]}' | reason={reason} | PnL=${pnl:.2f}")
