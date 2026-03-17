"""
Order book imbalance signal — reads WebSocket data from Redis.

The ws_streamer.py process (running natively on macOS) pushes real-time
order book and trade flow data to Redis DB2. This module reads those keys
from within Django/Celery (running in Docker) to provide microstructure
signals for the confluence scorer and entry algorithms.

Redis keys consumed (set by ws_streamer.py with 60s TTL):
  lighter:ob:{symbol}           — order book imbalance snapshot (JSON)
  lighter:trades:{symbol}       — trade flow: buy_vol, sell_vol, cvd (JSON)
  lighter:ob_imbalance:{symbol} — bid/ask ratio (float string)
  lighter:stats:{symbol}        — funding, OI, mark price (JSON)

Provides:
  1. get_ob_imbalance(symbol) -> float
  2. get_trade_flow(symbol) -> dict
  3. get_funding_signal(symbol, direction) -> tuple[int, float]
  4. get_ob_confluence_score(symbol, direction) -> int
"""
import json
import logging
import time
from typing import Optional

import redis

logger = logging.getLogger('app.lighter')

# ── Redis Connection ─────────────────────────────────────

# Redis DB2 is the tick/stream database, accessible from Docker via redis:6379
# and from host via localhost:6379 — same DB the ws_streamer writes to.
_redis_client: Optional[redis.Redis] = None

STALE_THRESHOLD = 60  # seconds — data older than this is considered stale


def _get_redis() -> Optional[redis.Redis]:
    """Lazy-init Redis connection to DB2 (tick/stream database)."""
    global _redis_client
    if _redis_client is not None:
        try:
            _redis_client.ping()
            return _redis_client
        except Exception:
            _redis_client = None

    try:
        import os
        redis_url = os.getenv('LIGHTER_WS_REDIS_URL', 'redis://redis:6379/2')
        _redis_client = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        _redis_client.ping()
        return _redis_client
    except Exception as e:
        logger.debug("Redis DB2 connection failed for OB signal: %s", e)
        _redis_client = None
        return None


def _get_key(key: str) -> Optional[str]:
    """Get a Redis key, returning None on any failure."""
    r = _get_redis()
    if r is None:
        return None
    try:
        return r.get(key)
    except Exception as e:
        logger.debug("Redis GET %s failed: %s", key, e)
        return None


def _get_json(key: str) -> Optional[dict]:
    """Get and parse a JSON Redis key, returning None on failure or stale data."""
    raw = _get_key(key)
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        # Check freshness
        ts = data.get('timestamp', 0)
        if ts > 0 and (time.time() - ts) > STALE_THRESHOLD:
            logger.debug("Stale data for %s: age=%.0fs", key, time.time() - ts)
            return None
        return data
    except (json.JSONDecodeError, TypeError) as e:
        logger.debug("JSON parse failed for %s: %s", key, e)
        return None


# ── Public API ───────────────────────────────────────────

def get_ob_imbalance(symbol: str) -> float:
    """Get order book imbalance for a symbol.

    Returns:
        Float 0.0 to 1.0:
          > 0.65 = strong buy pressure (bids dominate)
          < 0.35 = strong sell pressure (asks dominate)
          ~0.50  = balanced book
          0.50   = neutral (returned on failure/stale data)
    """
    # Try the fast scalar key first
    raw = _get_key(f'lighter:ob_imbalance:{symbol}')
    if raw is not None:
        try:
            val = float(raw)
            if 0.0 <= val <= 1.0:
                return val
        except (TypeError, ValueError):
            pass

    # Fall back to full OB snapshot
    data = _get_json(f'lighter:ob:{symbol}')
    if data is not None:
        imb = data.get('imbalance', 0.5)
        try:
            return float(imb)
        except (TypeError, ValueError):
            pass

    logger.debug("OB imbalance unavailable for %s — returning neutral", symbol)
    return 0.5


def get_trade_flow(symbol: str) -> dict:
    """Get recent trade flow data for a symbol.

    Returns:
        {
            'buy_volume': float,   # USD buy volume in window
            'sell_volume': float,  # USD sell volume in window
            'cvd': float,          # Cumulative volume delta (+ = buy dominant)
            'large_trades': int,   # Count of large trades (> 2x average)
            'trade_count': int,    # Total trades in window
            'timestamp': float,    # Unix timestamp
        }
        Returns neutral dict on failure.
    """
    data = _get_json(f'lighter:trades:{symbol}')
    if data is not None:
        return {
            'buy_volume': float(data.get('buy_volume', 0)),
            'sell_volume': float(data.get('sell_volume', 0)),
            'cvd': float(data.get('cvd', 0)),
            'large_trades': int(data.get('large_trades', 0)),
            'trade_count': int(data.get('trade_count', 0)),
            'timestamp': float(data.get('timestamp', 0)),
        }

    logger.debug("Trade flow unavailable for %s — returning neutral", symbol)
    return {
        'buy_volume': 0.0,
        'sell_volume': 0.0,
        'cvd': 0.0,
        'large_trades': 0,
        'trade_count': 0,
        'timestamp': 0.0,
    }


def get_funding_signal(symbol: str, direction: str) -> tuple:
    """Get funding rate signal for a symbol.

    Args:
        symbol: Trading pair (e.g. 'ETH', 'BTC')
        direction: 'BUY' or 'SELL'

    Returns:
        (signal: int, z_score: float)
        signal: 1 = favorable, 0 = neutral, -1 = headwind
        z_score: standardized funding rate magnitude

        On failure: (0, 0.0) — neutral, never blocks trading.
    """
    data = _get_json(f'lighter:stats:{symbol}')
    if data is None:
        logger.debug("Funding data unavailable for %s — returning neutral", symbol)
        return (0, 0.0)

    try:
        funding_rate = float(data.get('funding_rate', 0))
    except (TypeError, ValueError):
        return (0, 0.0)

    # Typical funding rates range from -0.01% to +0.01% per interval
    # Normalize to a z-score-like value (1 unit = ~0.001%)
    z_score = funding_rate / 0.0001 if funding_rate != 0 else 0.0

    is_buy = direction.upper() == 'BUY'
    NEUTRAL_THRESHOLD = 0.00005  # 0.005%

    if abs(funding_rate) < NEUTRAL_THRESHOLD:
        return (0, round(z_score, 2))
    elif is_buy and funding_rate < 0:
        # Shorts pay longs — favorable for long
        return (1, round(z_score, 2))
    elif not is_buy and funding_rate > 0:
        # Longs pay shorts — favorable for short
        return (1, round(z_score, 2))
    else:
        # Funding works against our direction
        return (-1, round(z_score, 2))


def get_ob_confluence_score(symbol: str, direction: str) -> int:
    """Get order book imbalance confluence score (0-2 points).

    Scoring:
      - OB imbalance > 0.65 AND direction is BUY  -> +2 (strong buy pressure aligns)
      - OB imbalance < 0.35 AND direction is SELL  -> +2 (strong sell pressure aligns)
      - OB imbalance 0.45-0.55 (balanced book)     -> +1 (no headwind from OB)
      - Otherwise                                   -> 0  (OB pressure opposes direction)

    Args:
        symbol: Trading pair
        direction: 'BUY' or 'SELL'

    Returns:
        0, 1, or 2 points
    """
    imbalance = get_ob_imbalance(symbol)
    is_buy = direction.upper() == 'BUY'

    # Strong alignment: OB pressure matches trade direction
    if is_buy and imbalance > 0.65:
        logger.debug(
            "OB confluence %s %s: +2 (imbalance=%.3f, strong bid pressure)",
            symbol, direction, imbalance,
        )
        return 2

    if not is_buy and imbalance < 0.35:
        logger.debug(
            "OB confluence %s %s: +2 (imbalance=%.3f, strong ask pressure)",
            symbol, direction, imbalance,
        )
        return 2

    # Balanced book: no headwind, mild positive
    if 0.45 <= imbalance <= 0.55:
        logger.debug(
            "OB confluence %s %s: +1 (imbalance=%.3f, balanced book)",
            symbol, direction, imbalance,
        )
        return 1

    # Misaligned or weakly aligned: OB pressure opposes direction
    logger.debug(
        "OB confluence %s %s: 0 (imbalance=%.3f, not aligned)",
        symbol, direction, imbalance,
    )
    return 0
