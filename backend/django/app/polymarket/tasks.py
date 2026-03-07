from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
import logging

from .bot_control import is_polymarket_bot_paused

logger = logging.getLogger('app.polymarket')


@shared_task(name='polymarket.tasks.sync_polymarket_markets', max_retries=3, soft_time_limit=120)
def sync_polymarket_markets():
    if is_polymarket_bot_paused():
        logger.info("Polymarket bot is paused, skipping market sync.")
        return
    try:
        from app.quant.algorithms.polymarket.entry import sync_markets
        sync_markets()
    except SoftTimeLimitExceeded:
        logger.error("sync_polymarket_markets timed out.")
    except Exception as e:
        logger.error(f"sync_polymarket_markets error: {e}")


@shared_task(name='polymarket.tasks.run_polymarket_entry', max_retries=3, soft_time_limit=60)
def run_polymarket_entry():
    if is_polymarket_bot_paused():
        logger.info("Polymarket bot is paused, skipping entry algorithm.")
        return
    try:
        from app.quant.algorithms.polymarket.entry import entry_algorithm
        entry_algorithm()
    except SoftTimeLimitExceeded:
        logger.error("run_polymarket_entry timed out.")
    except Exception as e:
        logger.error(f"run_polymarket_entry error: {e}")


@shared_task(name='polymarket.tasks.run_polymarket_backtest', max_retries=1, soft_time_limit=120)
def run_polymarket_backtest():
    try:
        from app.quant.algorithms.polymarket.backtester import run_and_store_backtest
        result = run_and_store_backtest()
        logger.info(f"Polymarket backtest complete: passed={result.passed}, win_rate={result.win_rate:.2%}")
    except SoftTimeLimitExceeded:
        logger.error("run_polymarket_backtest timed out.")
    except Exception as e:
        logger.error(f"run_polymarket_backtest error: {e}")


@shared_task(name='polymarket.tasks.run_polymarket_exit', max_retries=3, soft_time_limit=60)
def run_polymarket_exit():
    if is_polymarket_bot_paused():
        logger.info("Polymarket bot is paused, skipping exit algorithm.")
        return
    try:
        from app.quant.algorithms.polymarket.exit import exit_algorithm
        exit_algorithm()
    except SoftTimeLimitExceeded:
        logger.error("run_polymarket_exit timed out.")
    except Exception as e:
        logger.error(f"run_polymarket_exit error: {e}")
