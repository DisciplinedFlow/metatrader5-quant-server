# backend/django/app/quant/tasks.py

from celery import shared_task
import logging
from celery.exceptions import SoftTimeLimitExceeded

from app.quant.algorithms.mean_reversion.entry import entry_algorithm as mr_entry_algorithm
from app.quant.algorithms.mean_reversion.trailing import trailing_stop_algorithm as mr_trailing_algorithm
from app.quant.algorithms.scalping.entry import entry_algorithm as scalp_entry_algorithm
from app.quant.algorithms.scalping.trailing import trailing_stop_algorithm as scalp_trailing_algorithm
from app.quant.algorithms.close.close import close_algorithm
from app.utils.bot_control import is_bot_paused

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
    if is_bot_paused():
        logger.info("Bot is paused, skipping entry algorithm.")
        return
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
    if is_bot_paused():
        logger.info("Bot is paused, skipping trailing stop algorithm.")
        return
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
def run_backtest(strategy_name='SCALPING'):
    if is_bot_paused():
        logger.info("Bot is paused, skipping backtest.")
        return
    try:
        logger.info(f"Starting backtest for {strategy_name}...")
        from app.quant.backtester import run_and_store_backtest
        result = run_and_store_backtest(strategy_name=strategy_name)
        if result:
            logger.info(f"Backtest completed: passed={result.passed}, win_rate={result.win_rate:.2%}")
        else:
            logger.error("Backtest returned no result.")
    except SoftTimeLimitExceeded:
        logger.error("Backtest task timed out.")
    except Exception as e:
        logger.error(f"Error in backtest task: {e}")


@shared_task(name='quant.tasks.run_custom_backtest', max_retries=1, soft_time_limit=120)
def run_custom_backtest(custom_strategy_id):
    try:
        from app.nexus.models import CustomStrategy, StrategyConfig, BacktestResult
        from app.quant.backtester_generic import GenericBacktester

        custom = CustomStrategy.objects.get(id=custom_strategy_id)
        logger.info(f"Starting custom backtest for '{custom.name}'...")

        backtester = GenericBacktester(custom.definition)
        result = backtester.run()

        # Create or get a StrategyConfig to link the result
        # Use the actual strategy name so it appears correctly in the UI
        # Include domain to avoid name collisions across domains
        config_name = f'{custom.name[:40]} ({custom.domain})'[:50]
        strategy_config, created = StrategyConfig.objects.get_or_create(
            name=config_name,
            defaults={'description': custom.description, 'is_active': False}
        )
        if not created:
            strategy_config.description = custom.description
            strategy_config.save(update_fields=['description'])
        if not custom.strategy_config:
            custom.strategy_config = strategy_config
            custom.save()

        BacktestResult.objects.create(
            strategy=strategy_config,
            total_trades=result['total_trades'],
            winning_trades=result['winning_trades'],
            losing_trades=result['losing_trades'],
            win_rate=result['win_rate'],
            total_pnl=result['total_pnl'],
            profit_factor=result['profit_factor'],
            avg_win=result['avg_win'],
            avg_loss=result['avg_loss'],
            passed=result['passed'],
            data_source=result.get('data_source', 'YAHOO'),
            period_days=result.get('period_days', 60),
            trades=result.get('trades', []),
            equity_curve=result.get('equity_curve', []),
            symbol_breakdown=result.get('symbol_breakdown', {}),
        )

        logger.info(f"Custom backtest completed for '{custom.name}': passed={result['passed']}")
    except SoftTimeLimitExceeded:
        logger.error("Custom backtest task timed out.")
    except Exception as e:
        logger.error(f"Error in custom backtest task: {e}")
