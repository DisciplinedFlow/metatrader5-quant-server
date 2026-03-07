from django.conf import settings
import redis

BOT_PAUSED_KEY = 'bot:paused'


def _get_redis():
    return redis.Redis.from_url(settings.CELERY_BROKER_URL)


def is_bot_paused():
    return _get_redis().get(BOT_PAUSED_KEY) == b'1'


def set_bot_paused(paused: bool):
    _get_redis().set(BOT_PAUSED_KEY, '1' if paused else '0')


def get_bot_status():
    return {'paused': is_bot_paused()}
