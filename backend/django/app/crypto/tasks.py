from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
import logging

from .bot_control import is_crypto_bot_paused

logger = logging.getLogger('app.crypto')


@shared_task(name='crypto.tasks.sync_crypto_prices', max_retries=3, soft_time_limit=120)
def sync_crypto_prices():
    if is_crypto_bot_paused():
        logger.info("Crypto bot is paused, skipping price sync.")
        return
    try:
        from app.quant.algorithms.crypto.entry import sync_prices
        sync_prices()
    except SoftTimeLimitExceeded:
        logger.error("sync_crypto_prices timed out.")
    except Exception as e:
        logger.error(f"sync_crypto_prices error: {e}")


@shared_task(name='crypto.tasks.run_crypto_entry', max_retries=3, soft_time_limit=60)
def run_crypto_entry():
    if is_crypto_bot_paused():
        logger.info("Crypto bot is paused, skipping entry algorithm.")
        return
    try:
        from app.quant.algorithms.crypto.entry import entry_algorithm
        entry_algorithm()
    except SoftTimeLimitExceeded:
        logger.error("run_crypto_entry timed out.")
    except Exception as e:
        logger.error(f"run_crypto_entry error: {e}")


@shared_task(name='crypto.tasks.run_crypto_exit', max_retries=3, soft_time_limit=60)
def run_crypto_exit():
    if is_crypto_bot_paused():
        logger.info("Crypto bot is paused, skipping exit algorithm.")
        return
    try:
        from app.quant.algorithms.crypto.exit import exit_algorithm
        exit_algorithm()
    except SoftTimeLimitExceeded:
        logger.error("run_crypto_exit timed out.")
    except Exception as e:
        logger.error(f"run_crypto_exit error: {e}")


@shared_task(name='crypto.tasks.run_crypto_backtest', max_retries=1, soft_time_limit=120)
def run_crypto_backtest():
    try:
        from app.quant.algorithms.crypto.backtester import run_and_store_backtest
        result = run_and_store_backtest()
        logger.info(f"Crypto backtest complete: passed={result.passed}, win_rate={result.win_rate:.2%}")
    except SoftTimeLimitExceeded:
        logger.error("run_crypto_backtest timed out.")
    except Exception as e:
        logger.error(f"run_crypto_backtest error: {e}")


# ── Lighter.xyz DEX tasks ────────────────────────────────

@shared_task(name='crypto.tasks.run_lighter_entry', max_retries=3, soft_time_limit=60)
def run_lighter_entry():
    if is_crypto_bot_paused():
        return
    try:
        from app.quant.algorithms.lighter.entry import entry_algorithm
        entry_algorithm()
    except SoftTimeLimitExceeded:
        logger.error("run_lighter_entry timed out.")
    except Exception as e:
        logger.error(f"run_lighter_entry error: {e}")


@shared_task(name='crypto.tasks.run_lighter_exit', max_retries=3, soft_time_limit=60)
def run_lighter_exit():
    if is_crypto_bot_paused():
        return
    try:
        from app.quant.algorithms.lighter.exit import exit_algorithm
        exit_algorithm()
    except SoftTimeLimitExceeded:
        logger.error("run_lighter_exit timed out.")
    except Exception as e:
        logger.error(f"run_lighter_exit error: {e}")
