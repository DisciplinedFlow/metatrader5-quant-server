"""Publish events to the WebSocket relay server via Redis pub/sub."""
import json
import logging
import redis
from django.conf import settings

logger = logging.getLogger('ws')

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(
            getattr(settings, 'WS_REDIS_URL', 'redis://redis:6379/1'),
            decode_responses=True,
        )
    return _redis_client


def publish(channel: str, event: str, data: dict):
    """Publish an event to a WebSocket channel.

    Args:
        channel: Redis channel name (e.g., 'ws:trades', 'ws:positions', 'ws:bot_status', 'ws:news')
        event: Event type (e.g., 'trade_opened', 'trade_closed', 'position_update')
        data: Event payload dict
    """
    try:
        msg = json.dumps({'event': event, 'data': data})
        _get_redis().publish(channel, msg)
    except Exception as e:
        logger.debug("WS publish error on %s: %s", channel, e)


def publish_trade(event: str, trade_data: dict):
    publish('ws:trades', event, trade_data)


def publish_position(position_data: dict):
    publish('ws:positions', 'position_update', position_data)


def publish_bot_status(status_data: dict):
    publish('ws:bot_status', 'bot_status', status_data)


def publish_news(news_data: dict):
    publish('ws:news', 'news_alert', news_data)


def publish_prices(prices_data: dict):
    """Publish live price updates."""
    publish('ws:positions', 'price_update', prices_data)
