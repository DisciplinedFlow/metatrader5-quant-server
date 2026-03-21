import time

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
            publish_prices({'source': 'sync', 'timestamp': time.time()})
        except Exception:
            pass
    except SoftTimeLimitExceeded:
        logger.error("sync_crypto_prices timed out.")
    except Exception as e:
        logger.error("sync_crypto_prices error: %s", e)


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
        logger.error("run_crypto_entry error: %s", e)


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
        logger.error("run_crypto_exit error: %s", e)


@shared_task(name='crypto.tasks.run_crypto_backtest', max_retries=1, soft_time_limit=120)
def run_crypto_backtest():
    try:
        from app.quant.algorithms.crypto.backtester import run_and_store_backtest
        result = run_and_store_backtest()
        if result:
            logger.info("Crypto backtest complete: passed=%s, win_rate=%.2f%%",
                        result.passed, result.win_rate * 100)
    except SoftTimeLimitExceeded:
        logger.error("run_crypto_backtest timed out.")
    except Exception as e:
        logger.error("run_crypto_backtest error: %s", e)


@shared_task(name='crypto.tasks.run_crypto_backtest_all', max_retries=1, soft_time_limit=600)
def run_crypto_backtest_all(symbols=None):
    """Run all strategies across all symbols and store results."""
    try:
        from app.quant.algorithms.crypto.backtester import run_and_store_all_backtests
        records = run_and_store_all_backtests(symbols)
        passed = sum(1 for r in records if r.passed)
        logger.info("Multi-strategy backtest complete: %d results, %d passed", len(records), passed)
        return {'total': len(records), 'passed': passed}
    except SoftTimeLimitExceeded:
        logger.error("run_crypto_backtest_all timed out (600s limit).")
    except Exception as e:
        logger.error("run_crypto_backtest_all error: %s", e)


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
        logger.error("run_lighter_entry error: %s", e)


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
        logger.error("run_lighter_mean_reversion error: %s", e)


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
        logger.error("run_lighter_rsi_scalper error: %s", e)


@shared_task(name='crypto.tasks.run_lighter_reconcile', max_retries=1, soft_time_limit=20)
def run_lighter_reconcile():
    """Sync DB positions with actual Lighter exchange state. Runs even when paused."""
    try:
        from app.quant.algorithms.lighter.reconcile import reconcile_positions
        reconcile_positions()
    except SoftTimeLimitExceeded:
        logger.error("run_lighter_reconcile timed out.")
    except Exception as e:
        logger.error("run_lighter_reconcile error: %s", e)


@shared_task(name='crypto.tasks.run_lighter_exit', max_retries=3, soft_time_limit=30)
def run_lighter_exit():
    """Manage SL/TP and trailing stops for open positions. Runs even when paused."""
    try:
        from app.quant.algorithms.lighter.exit import exit_algorithm
        exit_algorithm()
    except SoftTimeLimitExceeded:
        logger.error("run_lighter_exit timed out.")
    except Exception as e:
        logger.error("run_lighter_exit error: %s", e)


@shared_task(name='crypto.tasks.run_lighter_momentum', max_retries=2, soft_time_limit=55)
def run_lighter_momentum():
    """EMA momentum entries for Lighter.xyz. Complements CVD divergence."""
    if is_crypto_bot_paused():
        return
    if _check_global_daily_halt():
        logger.debug("Daily halt — skipping lighter momentum entry.")
        return
    try:
        from app.quant.algorithms.lighter.momentum_entry import momentum_entry_algorithm
        momentum_entry_algorithm()
    except SoftTimeLimitExceeded:
        logger.error("run_lighter_momentum timed out.")
    except Exception as e:
        logger.error("run_lighter_momentum error: %s", e)


@shared_task(name='crypto.tasks.run_lighter_cvd', max_retries=2, soft_time_limit=55)
def run_lighter_cvd():
    """CVD divergence entry for Lighter.xyz. Reads active CVD strategies from DB."""
    if is_crypto_bot_paused():
        return
    if _check_global_daily_halt():
        logger.debug("Daily halt — skipping lighter CVD entry.")
        return
    try:
        from app.quant.algorithms.lighter.cvd_entry import cvd_entry_algorithm
        cvd_entry_algorithm()
    except SoftTimeLimitExceeded:
        logger.error("run_lighter_cvd timed out.")
    except Exception as e:
        logger.error("run_lighter_cvd error: %s", e)


# ── Funding Rate Arbitrage Monitor ────────────────────────

@shared_task(name='crypto.tasks.train_crypto_ml', max_retries=1, soft_time_limit=120)
def train_crypto_ml():
    """Train crypto ML model from Lighter trade data. Runs every 6 hours."""
    try:
        from app.quant.ml.crypto_trainer import train_crypto_model
        result = train_crypto_model()
        if result:
            logger.info("Crypto ML trained: accuracy=%.1f%%, trades=%d",
                        result.get('accuracy', 0) * 100, result.get('train_size', 0))
        else:
            logger.info("Crypto ML: insufficient data for training")
    except Exception as e:
        logger.error("Crypto ML training error: %s", e)


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
        logger.error("run_funding_arb_scan error: %s", e)
