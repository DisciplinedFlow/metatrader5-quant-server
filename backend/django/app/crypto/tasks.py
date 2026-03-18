from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
import logging

from .bot_control import is_crypto_bot_paused

logger = logging.getLogger('app.crypto')


def _check_global_daily_halt():
    """Return True if the global daily loss halt is active."""
    try:
        from django.core.cache import cache
        return bool(cache.get('global_daily_halt'))
    except Exception:
        return False


@shared_task(name='crypto.tasks.sync_crypto_prices', max_retries=3, soft_time_limit=120)
def sync_crypto_prices():
    if is_crypto_bot_paused():
        logger.info("Crypto bot is paused, skipping price sync.")
        return
    try:
        from app.quant.algorithms.crypto.entry import sync_prices
        sync_prices()
        try:
            from app.ws.publish import publish_prices
            publish_prices({'source': 'sync', 'timestamp': __import__('time').time()})
        except Exception:
            pass
    except SoftTimeLimitExceeded:
        logger.error("sync_crypto_prices timed out.")
    except Exception as e:
        logger.error(f"sync_crypto_prices error: {e}")


@shared_task(name='crypto.tasks.run_crypto_entry', max_retries=3, soft_time_limit=60)
def run_crypto_entry():
    if is_crypto_bot_paused():
        logger.info("Crypto bot is paused, skipping entry algorithm.")
        return
    if _check_global_daily_halt():
        logger.debug("Daily halt — skipping crypto entry.")
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
        if result:
            logger.info(f"Crypto backtest complete: passed={result.passed}, win_rate={result.win_rate:.2%}")
    except SoftTimeLimitExceeded:
        logger.error("run_crypto_backtest timed out.")
    except Exception as e:
        logger.error(f"run_crypto_backtest error: {e}")


@shared_task(name='crypto.tasks.run_crypto_backtest_all', max_retries=1, soft_time_limit=600)
def run_crypto_backtest_all(symbols=None):
    """Run all strategies across all symbols and store results."""
    try:
        from app.quant.algorithms.crypto.backtester import run_and_store_all_backtests
        records = run_and_store_all_backtests(symbols)
        passed = sum(1 for r in records if r.passed)
        logger.info(f"Multi-strategy backtest complete: {len(records)} results, {passed} passed")
        return {'total': len(records), 'passed': passed}
    except SoftTimeLimitExceeded:
        logger.error("run_crypto_backtest_all timed out (600s limit).")
    except Exception as e:
        logger.error(f"run_crypto_backtest_all error: {e}")


# ── Lighter.xyz DEX tasks ────────────────────────────────

@shared_task(name='crypto.tasks.run_lighter_entry', max_retries=3, soft_time_limit=60)
def run_lighter_entry():
    if is_crypto_bot_paused():
        return
    if _check_global_daily_halt():
        logger.debug("Daily halt — skipping lighter entry.")
        return
    try:
        from app.quant.algorithms.lighter.entry import entry_algorithm
        entry_algorithm()
    except SoftTimeLimitExceeded:
        logger.error("run_lighter_entry timed out.")
    except Exception as e:
        logger.error(f"run_lighter_entry error: {e}")


@shared_task(name='crypto.tasks.run_lighter_mean_reversion', max_retries=2, soft_time_limit=60)
def run_lighter_mean_reversion():
    if is_crypto_bot_paused():
        return
    try:
        from app.quant.algorithms.lighter.mean_reversion import mean_reversion_algorithm
        mean_reversion_algorithm()
    except SoftTimeLimitExceeded:
        logger.error("run_lighter_mean_reversion timed out.")
    except Exception as e:
        logger.error(f"run_lighter_mean_reversion error: {e}")


@shared_task(name='crypto.tasks.run_lighter_grid', max_retries=2, soft_time_limit=45)
def run_lighter_grid():
    if is_crypto_bot_paused():
        return
    try:
        from app.quant.algorithms.lighter.grid import grid_algorithm
        grid_algorithm()
    except SoftTimeLimitExceeded:
        logger.error("run_lighter_grid timed out.")
    except Exception as e:
        logger.error(f"run_lighter_grid error: {e}")


@shared_task(name='crypto.tasks.run_lighter_rsi_scalper', max_retries=2, soft_time_limit=45)
def run_lighter_rsi_scalper():
    if is_crypto_bot_paused():
        return
    try:
        from app.quant.algorithms.lighter.rsi_scalper import rsi_scalper_algorithm
        rsi_scalper_algorithm()
    except SoftTimeLimitExceeded:
        logger.error("run_lighter_rsi_scalper timed out.")
    except Exception as e:
        logger.error(f"run_lighter_rsi_scalper error: {e}")


@shared_task(name='crypto.tasks.run_lighter_reconcile', max_retries=1, soft_time_limit=45)
def run_lighter_reconcile():
    """Sync DB positions with actual Lighter exchange state."""
    if is_crypto_bot_paused():
        return
    try:
        from app.quant.algorithms.lighter.reconcile import reconcile_positions
        reconcile_positions()
    except SoftTimeLimitExceeded:
        logger.error("run_lighter_reconcile timed out.")
    except Exception as e:
        logger.error(f"run_lighter_reconcile error: {e}")


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


# ── Funding Rate Arbitrage Monitor ────────────────────────

@shared_task(name='crypto.tasks.train_crypto_ml', max_retries=1, soft_time_limit=120)
def train_crypto_ml():
    """Train crypto ML model from Lighter trade data. Runs every 6 hours."""
    try:
        from app.quant.ml.crypto_trainer import train_crypto_model
        result = train_crypto_model()
        if result:
            logger.info(f"Crypto ML trained: accuracy={result.get('accuracy', 0):.1%}, trades={result.get('train_size', 0)}")
        else:
            logger.info("Crypto ML: insufficient data for training")
    except Exception as e:
        logger.error(f"Crypto ML training error: {e}")


@shared_task(name='crypto.tasks.run_funding_arb_scan', max_retries=2, soft_time_limit=120)
def run_funding_arb_scan():
    """Scan funding rates across Hyperliquid and Lighter.xyz for arb opportunities."""
    try:
        from app.quant.algorithms.crypto.funding_arb import scan_funding_arb
        result = scan_funding_arb()
        if result.get('opportunity_count', 0) > 0:
            logger.info(
                "Funding arb scan: %d opportunities found across %s",
                result['opportunity_count'],
                [o['symbol'] for o in result['opportunities']],
            )
        else:
            logger.debug("Funding arb scan: no opportunities (threshold=%.6f)", result.get('threshold', 0))
    except SoftTimeLimitExceeded:
        logger.error("run_funding_arb_scan timed out.")
    except Exception as e:
        logger.error(f"run_funding_arb_scan error: {e}")
