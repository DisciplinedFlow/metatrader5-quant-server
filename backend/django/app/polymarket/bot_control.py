from django.conf import settings
import redis

BOT_PAUSED_KEY = 'bot:polymarket:paused'


def _get_redis():
    return redis.Redis.from_url(settings.CELERY_BROKER_URL)


def is_polymarket_bot_paused():
    return _get_redis().get(BOT_PAUSED_KEY) == b'1'


def set_polymarket_bot_paused(paused: bool):
    _get_redis().set(BOT_PAUSED_KEY, '1' if paused else '0')


def get_polymarket_bot_status():
    return {'paused': is_polymarket_bot_paused()}
