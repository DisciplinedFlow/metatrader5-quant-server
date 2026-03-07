import json
import logging
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger('app.polymarket')


def estimate_probability(market):
    """Use Claude API to estimate true probability for a market.

    Args:
        market: PolyMarket model instance

    Returns:
        dict with 'probability' (float) and 'reasoning' (str), or None on failure
    """
    from .config import LLM_MODEL, ESTIMATION_CACHE_MINUTES
    import os

    # Check cache - skip if recently estimated
    if market.last_estimated and market.last_estimated > timezone.now() - timedelta(minutes=ESTIMATION_CACHE_MINUTES):
        logger.debug(f"Skipping estimation for '{market.question}' - cached")
        return {'probability': market.model_probability, 'reasoning': 'cached'}

    api_key = os.getenv('ANTHROPIC_API_KEY', '')
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set, skipping LLM estimation")
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        prompt = f"""You are a calibrated probability estimator for prediction markets.
Given the following market, estimate the TRUE probability of the YES outcome.

Market: "{market.question}"
Description: "{market.description}"
Category: {market.category}
Resolution date: {market.end_date}
Current market price: {market.market_price} (what the market thinks)

Output ONLY a JSON object: {{"probability": 0.XX, "reasoning": "..."}}

Be well-calibrated: when you say 70%, it should happen ~70% of the time.
Consider base rates, current events, and any relevant domain knowledge."""

        response = client.messages.create(
            model=LLM_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        # Parse JSON from response (handle potential markdown wrapping)
        if text.startswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()

        result = json.loads(text)
        probability = float(result['probability'])
        reasoning = result.get('reasoning', '')

        # Clamp to valid range
        probability = max(0.01, min(0.99, probability))

        # Update market model
        market.model_probability = probability
        market.last_estimated = timezone.now()
        market.save(update_fields=['model_probability', 'last_estimated'])

        # Log the estimation
        from app.polymarket.models import PolyProbabilityLog
        from .pricing import compute_ev

        ev = compute_ev(probability, market.market_price)
        PolyProbabilityLog.objects.create(
            market=market,
            market_price=market.market_price,
            model_probability=probability,
            alpha=market.prior_alpha,
            beta=market.prior_beta,
            ev=ev,
            reasoning=reasoning,
        )

        logger.info(f"Estimated probability for '{market.question[:50]}': {probability:.3f} (market: {market.market_price:.3f}, EV: {ev:.3f})")
        return {'probability': probability, 'reasoning': reasoning}

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response: {e}")
        return None
    except Exception as e:
        logger.error(f"LLM estimation error: {e}")
        return None


def estimate_batch(markets):
    """Estimate probabilities for a batch of markets.

    Args:
        markets: queryset or list of PolyMarket instances

    Returns:
        list of results
    """
    from .config import LLM_MAX_MARKETS

    results = []
    for i, market in enumerate(markets[:LLM_MAX_MARKETS]):
        result = estimate_probability(market)
        if result:
            results.append({'market_id': market.id, **result})

    logger.info(f"Batch estimation complete: {len(results)}/{len(markets)} markets estimated")
    return results
