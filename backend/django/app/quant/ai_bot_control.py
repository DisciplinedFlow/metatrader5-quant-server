from django.conf import settings
import redis
import json

BOT_PAUSED_KEY = 'bot:ai_brain:paused'
LAST_ANALYSIS_KEY = 'ai_brain:last_analysis'


def _get_redis():
    return redis.Redis.from_url(settings.CELERY_BROKER_URL)


def is_ai_brain_paused():
    return _get_redis().get(BOT_PAUSED_KEY) != b'1'  # Default OFF (paused) — must explicitly enable


def set_ai_brain_enabled(enabled: bool):
    _get_redis().set(BOT_PAUSED_KEY, '1' if enabled else '0')


def get_ai_brain_status():
    r = _get_redis()
    enabled = r.get(BOT_PAUSED_KEY) == b'1'
    last_raw = r.get(LAST_ANALYSIS_KEY)
    last_analysis = json.loads(last_raw) if last_raw else None
    return {
        'enabled': enabled,
        'last_analysis': last_analysis,
    }


def store_analysis(analysis: dict):
    _get_redis().set(LAST_ANALYSIS_KEY, json.dumps(analysis), ex=60 * 60)  # TTL 1 hour
