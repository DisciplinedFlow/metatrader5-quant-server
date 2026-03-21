"""Forex-only settings — filters beat schedule to forex/monitoring tasks only."""
from app.settings import *  # noqa: F401,F403

CELERY_BEAT_SCHEDULE = {
    k: v for k, v in CELERY_BEAT_SCHEDULE.items()
    if not any(x in k for x in ('crypto', 'lighter', 'funding'))
}
