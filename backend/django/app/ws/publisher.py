"""Publish events to Redis pub/sub for WebSocket broadcast.

All publish functions are fire-and-forget: they catch and log exceptions
so they never interfere with the trading pipeline.

Usage:
    from app.ws.publisher import publish_trade_opened
    publish_trade_opened({'symbol': 'EURUSD', 'type': 'BUY', ...})
"""
import json
import logging
import os

import redis

logger = logging.getLogger('ws')

_redis_client = None

REDIS_URL = os.environ.get('WS_REDIS_URL', 'redis://redis:6379/1')


def _get_redis():
    """Lazy-initialise and return the Redis client (DB 1)."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


def _safe_publish(channel: str, payload: dict):
    """Publish JSON payload to a Redis pub/sub channel. Never raises."""
    try:
        _get_redis().publish(channel, json.dumps(payload))
    except Exception as e:
        logger.debug(f"WS publish failed ({channel}): {e}")


# ---------------------------------------------------------------------------
# Trade events
# ---------------------------------------------------------------------------

def publish_trade_opened(trade_data: dict):
    """Broadcast when a new trade is opened."""
    _safe_publish('ws:trades', {
        'event': 'trade_opened',
        'data': trade_data,
    })


def publish_trade_closed(trade_data: dict):
    """Broadcast when a trade is closed."""
    _safe_publish('ws:trades', {
        'event': 'trade_closed',
        'data': trade_data,
    })


# ---------------------------------------------------------------------------
# Position events
# ---------------------------------------------------------------------------

def publish_position_update(positions: list):
    """Broadcast current open positions snapshot."""
    _safe_publish('ws:positions', {
        'event': 'position_update',
        'data': positions,
    })


# ---------------------------------------------------------------------------
# Bot / system events
# ---------------------------------------------------------------------------

def publish_bot_status(status: dict):
    """Broadcast bot status changes (running/paused/error)."""
    _safe_publish('ws:bot_status', {
        'event': 'bot_status',
        'data': status,
    })


# ---------------------------------------------------------------------------
# News events
# ---------------------------------------------------------------------------

def publish_news_alert(news: dict):
    """Broadcast news/sentiment alerts."""
    _safe_publish('ws:news', {
        'event': 'news_alert',
        'data': news,
    })
