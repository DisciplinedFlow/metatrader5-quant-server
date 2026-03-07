# backend/django/app/quant/tasks.py

from celery import shared_task
import logging
from celery.exceptions import SoftTimeLimitExceeded

from app.quant.algorithms.mean_reversion.entry import entry_algorithm as mr_entry_algorithm
from app.quant.algorithms.mean_reversion.trailing import trailing_stop_algorithm as mr_trailing_algorithm
from app.quant.algorithms.scalping.entry import entry_algorithm as scalp_entry_algorithm
from app.quant.algorithms.scalping.trailing import trailing_stop_algorithm as scalp_trailing_algorithm
from app.quant.algorithms.close.close import close_algorithm

logger = logging.getLogger(__name__)


def get_active_strategy():
    """Return the name of the currently active strategy, or None."""
    try:
        from app.nexus.models import StrategyConfig
        active = StrategyConfig.objects.filter(is_active=True).first()
        if active:
            return active.name
        return None
    except Exception as e:
        logger.error(f"Error fetching active strategy: {e}")
        return None


@shared_task(name='quant.tasks.run_quant_entry_algorithm', max_retries=3, soft_time_limit=30)
def run_quant_entry_algorithm():
    try:
        strategy = get_active_strategy()
        logger.info(f"Starting quant entry algorithm (strategy={strategy})...")

        if strategy == 'SCALPING':
            scalp_entry_algorithm()
        elif strategy == 'MEAN_REVERSION':
            mr_entry_algorithm()
        else:
            logger.warning(f"No active strategy found or unknown strategy: {strategy}")
    except SoftTimeLimitExceeded:
        logger.error("Task timed out.")
    except Exception as e:
        logger.error(f"Error in quant entry algorithm: {e}")

@shared_task(name='quant.tasks.run_quant_trailing_stop_algorithm', max_retries=3, soft_time_limit=30)
def run_quant_trailing_stop_algorithm():
    try:
        strategy = get_active_strategy()
        logger.info(f"Starting quant trailing stop algorithm (strategy={strategy})...")

        if strategy == 'SCALPING':
            scalp_trailing_algorithm()
        elif strategy == 'MEAN_REVERSION':
            mr_trailing_algorithm()
        else:
            logger.warning(f"No active strategy found or unknown strategy: {strategy}")
    except SoftTimeLimitExceeded:
        logger.error("Task timed out during trailing stop algorithm.")
    except Exception as e:
        logger.error(f"Error in quant trailing stop algorithm: {e}")

@shared_task(name='quant.tasks.run_quant_close_algorithm', max_retries=3, soft_time_limit=30)
def run_quant_close_algorithm():
    try:
        logger.info("Starting quant close algorithm...")
        close_algorithm()
    except SoftTimeLimitExceeded:
        logger.error("Task timed out.")
    except Exception as e:
        logger.error(f"Error in quant close algorithm: {e}")


@shared_task(name='quant.tasks.run_backtest', max_retries=1, soft_time_limit=120)
def run_backtest():
    try:
        logger.info("Starting backtest...")
        from app.quant.backtester import run_and_store_backtest
        result = run_and_store_backtest()
        if result:
            logger.info(f"Backtest completed: passed={result.passed}, win_rate={result.win_rate:.2%}")
        else:
            logger.error("Backtest returned no result.")
    except SoftTimeLimitExceeded:
        logger.error("Backtest task timed out.")
    except Exception as e:
        logger.error(f"Error in backtest task: {e}")
