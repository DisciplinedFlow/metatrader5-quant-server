import logging
import pandas as pd
from django.utils import timezone

from .config import (
    CRYPTO_PAIRS, CRYPTO_CAPITAL_USD, CRYPTO_MAX_POSITIONS,
    CRYPTO_LEVERAGE, CRYPTO_FAST_MA, CRYPTO_SLOW_MA,
    CRYPTO_LOOKBACK, CRYPTO_MAX_POSITION_PCT, CRYPTO_STRATEGY,
    CRYPTO_STOP_LOSS_PCT, CRYPTO_TAKE_PROFIT_PCT,
)
from .client import get_all_mids, get_candles, place_market_order
from .strategy import MomentumStrategy
from .sizing import check_position_limits

logger = logging.getLogger('app.crypto')


def sync_prices():
    """Fetch latest prices for tracked pairs. Logs current mid prices."""
    try:
        mids = get_all_mids()
        tracked = {pair: mids.get(pair) for pair in CRYPTO_PAIRS if pair in mids}
        logger.info(f"Price sync: {tracked}")
    except Exception as e:
        logger.error(f"Price sync error: {e}")


def _get_strategy() -> MomentumStrategy:
    """Build strategy from config (or Redis overrides)."""
    import redis as _redis
    from django.conf import settings
    import json

    r = _redis.Redis.from_url(settings.CELERY_BROKER_URL)
    override = r.get('crypto:strategy:config')
    if override:
        cfg = json.loads(override)
        return MomentumStrategy(
            signal_type='ma_crossover',
            fast_ma=cfg.get('fast_ma', CRYPTO_FAST_MA),
            slow_ma=cfg.get('slow_ma', CRYPTO_SLOW_MA),
            lookback=cfg.get('lookback', CRYPTO_LOOKBACK),
            max_position_pct=cfg.get('max_position_pct', CRYPTO_MAX_POSITION_PCT),
        )
    return MomentumStrategy(
        signal_type='ma_crossover',
        fast_ma=CRYPTO_FAST_MA,
        slow_ma=CRYPTO_SLOW_MA,
        lookback=CRYPTO_LOOKBACK,
        max_position_pct=CRYPTO_MAX_POSITION_PCT,
    )


def entry_algorithm():
    """Check signals and enter positions."""
    from app.crypto.models import CryptoPosition, CryptoTrade

    open_count = CryptoPosition.objects.filter(status='OPEN').count()
    if not check_position_limits(open_count, CRYPTO_MAX_POSITIONS):
        logger.info(f"Max positions reached ({open_count}/{CRYPTO_MAX_POSITIONS}), skipping entry.")
        return

    strategy = _get_strategy()
    mids = get_all_mids()

    for pair in CRYPTO_PAIRS:
        if CryptoPosition.objects.filter(symbol=pair, status='OPEN').exists():
            continue

        if open_count >= CRYPTO_MAX_POSITIONS:
            break

        try:
            candles = get_candles(pair, interval='1h', limit=max(CRYPTO_SLOW_MA + 50, 300))
            if not candles:
                continue

            closes = pd.Series([float(c['c']) for c in candles])
            signal = strategy.generate_signal(closes)

            if signal == 0:
                continue

            current_price = float(mids.get(pair, 0))
            if current_price <= 0:
                continue

            size = abs(strategy.calculate_position_size(signal, CRYPTO_CAPITAL_USD, current_price))
            if size <= 0:
                continue

            is_buy = signal > 0
            side = 'LONG' if is_buy else 'SHORT'

            logger.info(f"Entry signal: {pair} {side} size={size:.6f} price={current_price}")

            result = place_market_order(pair, is_buy, size, CRYPTO_LEVERAGE)

            if result and result.get('status') == 'ok':
                stop_loss = current_price * (1 - CRYPTO_STOP_LOSS_PCT) if is_buy else current_price * (1 + CRYPTO_STOP_LOSS_PCT)
                take_profit = current_price * (1 + CRYPTO_TAKE_PROFIT_PCT) if is_buy else current_price * (1 - CRYPTO_TAKE_PROFIT_PCT)

                position = CryptoPosition.objects.create(
                    symbol=pair,
                    side=side,
                    entry_price=current_price,
                    size=size,
                    leverage=CRYPTO_LEVERAGE,
                    entry_signal=f"momentum_{strategy.signal_type}",
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                )

                statuses = result.get('response', {}).get('data', {}).get('statuses', [])
                order_id = ''
                if statuses:
                    filled = statuses[0].get('filled', {})
                    order_id = str(filled.get('oid', ''))

                CryptoTrade.objects.create(
                    position=position,
                    order_id=order_id,
                    side='BUY' if is_buy else 'SELL',
                    price=current_price,
                    size=size,
                    status='FILLED',
                )

                open_count += 1
                logger.info(f"Position opened: {pair} {side} size={size:.6f}")

        except Exception as e:
            logger.error(f"Entry error for {pair}: {e}")
