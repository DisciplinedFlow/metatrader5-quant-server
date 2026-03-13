# backend/django/app/quant/tasks.py

import os
from celery import shared_task
import logging
from datetime import date
from celery.exceptions import SoftTimeLimitExceeded

from app.quant.algorithms.mean_reversion.entry import entry_algorithm as mr_entry_algorithm
from app.quant.algorithms.mean_reversion.trailing import trailing_stop_algorithm as mr_trailing_algorithm
from app.quant.algorithms.scalping.entry import entry_algorithm as scalp_entry_algorithm
from app.quant.algorithms.scalping.trailing import trailing_stop_algorithm as scalp_trailing_algorithm
from app.quant.algorithms.cvd.entry import entry_algorithm as cvd_entry_algorithm_legacy
from app.quant.algorithms.cvd.entry import cvd_entry_algorithm
from app.quant.algorithms.cvd.trailing import trailing_stop_algorithm as cvd_trailing_algorithm
from app.quant.algorithms.close.close import close_algorithm
from app.utils.bot_control import is_bot_paused

logger = logging.getLogger(__name__)

# --- TRAINING MODE: imported from entry config ---
# When True, bypasses daily halt and raises position limits for max data collection.
from app.quant.algorithms.cvd.entry import TRAINING_MODE

GLOBAL_MAX = 20 if TRAINING_MODE else 10
DAILY_MAX_LOSS_USD = 9999.0 if TRAINING_MODE else 300.0
DRAWDOWN_REDUCTION_THRESHOLD = 2000.0   # Total cumulative loss to trigger size reduction
DRAWDOWN_REDUCED_CAPITAL = 100  # Fall back to conservative sizing


def _check_global_daily_halt():
    """Account-level daily hard stop. Returns True if trading should be halted.

    Checks all closed trades in the last 24 hours across ALL strategies.
    If cumulative loss exceeds DAILY_MAX_LOSS_USD, halts all trading for 24h.
    Also checks total cumulative loss — if it exceeds $10k, reduces capital per
    trade back to $100 (conservative mode).
    """
    from django.core.cache import cache

    # Fast path: check Redis cache first
    cached = cache.get('global_daily_halt')
    if cached is not None:
        logger.debug(f"Daily halt active (PnL: ${cached}).")
        return True

    try:
        from datetime import timedelta
        from django.utils import timezone
        from django.db.models import Sum
        from app.nexus.models import Trade

        # --- Cumulative drawdown check: reduce size at -$10k total ---
        total_cumulative = Trade.objects.filter(
            pnl__isnull=False,
        ).aggregate(total=Sum('pnl'))['total'] or 0.0
        if total_cumulative < -DRAWDOWN_REDUCTION_THRESHOLD:
            from app.quant.algorithms.cvd import config as cvd_config
            if cvd_config.CAPITAL_PER_TRADE != DRAWDOWN_REDUCED_CAPITAL:
                cvd_config.CAPITAL_PER_TRADE = DRAWDOWN_REDUCED_CAPITAL
                cache.set('drawdown_reduction_active', round(total_cumulative, 2), timeout=86400)
                logger.critical(
                    f"DRAWDOWN REDUCTION: Cumulative PnL ${total_cumulative:.2f} exceeds "
                    f"-${DRAWDOWN_REDUCTION_THRESHOLD}. CAPITAL_PER_TRADE reduced to "
                    f"${DRAWDOWN_REDUCED_CAPITAL}."
                )

        # --- Daily halt check ---
        # Only count trades after the parameter reset to avoid old $5k-era
        # losses re-triggering the halt with the new $300 limit.
        reset_ts = cache.get('daily_halt_reset_time')
        if reset_ts:
            cutoff = max(reset_ts, timezone.now() - timedelta(hours=24))
        else:
            cutoff = timezone.now() - timedelta(hours=24)
        total_pnl = Trade.objects.filter(
            close_time__gte=cutoff,
            pnl__isnull=False,
        ).aggregate(total=Sum('pnl'))['total'] or 0.0

        if total_pnl < -DAILY_MAX_LOSS_USD:
            cache.set('global_daily_halt', round(total_pnl, 2), timeout=86400)
            logger.critical(
                f"GLOBAL DAILY HALT: Total 24h loss ${total_pnl:.2f} exceeds "
                f"-${DAILY_MAX_LOSS_USD} limit. All trading suspended."
            )
            return True

        return False
    except Exception as e:
        logger.error(f"Global daily halt check error: {e}")
        return False  # Fail open — don't block trading on check errors


def get_active_strategy():
    """Return the name of the currently active strategy, or None.
    Kept for backward compatibility."""
    try:
        from app.nexus.models import StrategyConfig
        active = StrategyConfig.objects.filter(is_active=True).first()
        if active:
            return active.name
        return None
    except Exception as e:
        logger.error(f"Error fetching active strategy: {e}")
        return None


def _is_custom_strategy(strategy_config):
    """Check if a StrategyConfig is linked to a CustomStrategy (CVD, etc.).

    Accepts a StrategyConfig object directly (Phase 1C).
    Also accepts a string name for backward compatibility.
    """
    try:
        from app.nexus.models import StrategyConfig, CustomStrategy
        if isinstance(strategy_config, str):
            # Backward compat: lookup by name
            config = StrategyConfig.objects.filter(name=strategy_config, is_active=True).first()
            if config is None:
                return False
            return CustomStrategy.objects.filter(strategy_config=config).exists()
        # StrategyConfig object passed directly
        return CustomStrategy.objects.filter(strategy_config=strategy_config).exists()
    except Exception:
        return False


def _check_live_performance(strategy_config):
    """Auto-disable strategies with sustained poor live performance.

    Kill switches:
    - 5 consecutive losing trades → disable
    - Last 10 trades cumulative P&L < -$50 → disable

    Only evaluates trades since the strategy was last activated (respects
    rotator decisions — old losses before re-activation don't count).

    Returns True if strategy is allowed to trade.
    """
    try:
        from app.nexus.models import Trade, CustomStrategy

        # Only evaluate trades since last activation (cooperate with rotator)
        since = strategy_config.last_activated

        # Try strategy_config FK first, fall back to strategy name pattern
        trades_qs = Trade.objects.filter(
            strategy_config=strategy_config,
            close_time__isnull=False,
        )
        if since:
            trades_qs = trades_qs.filter(close_time__gte=since)
        trades_qs = trades_qs.order_by('-close_time')

        if trades_qs.count() < 3:
            # Fallback: match by strategy name pattern
            custom = CustomStrategy.objects.filter(strategy_config=strategy_config).first()
            if custom:
                trades_qs = Trade.objects.filter(
                    strategy__icontains=custom.name,
                    close_time__isnull=False,
                )
                if since:
                    trades_qs = trades_qs.filter(close_time__gte=since)
                trades_qs = trades_qs.order_by('-close_time')

        recent_pnls = list(trades_qs.values_list('pnl', flat=True)[:10])

        if len(recent_pnls) < 5:
            return True  # Not enough data

        # Kill switch 1: consecutive losses
        consecutive_losses = 0
        for pnl in recent_pnls:
            if pnl is not None and pnl < 0:
                consecutive_losses += 1
            else:
                break

        if consecutive_losses >= 5:
            strategy_config.is_active = False
            strategy_config.save(update_fields=['is_active'])
            logger.warning(
                f"PERFORMANCE GATE: Disabled '{strategy_config.name}' — "
                f"{consecutive_losses} consecutive losses"
            )
            return False

        # Kill switch 2: cumulative drawdown
        total_pnl = sum(p for p in recent_pnls if p is not None)
        if total_pnl < -50:
            strategy_config.is_active = False
            strategy_config.save(update_fields=['is_active'])
            logger.warning(
                f"PERFORMANCE GATE: Disabled '{strategy_config.name}' — "
                f"cumulative P&L ${total_pnl:.2f} over last {len(recent_pnls)} trades"
            )
            return False

        return True
    except Exception as e:
        logger.error(f"Performance gate error: {e}")
        return True  # Fail open


def _count_open_positions():
    """Count currently open positions via MT5 Flask API."""
    try:
        from app.utils.api.positions import get_positions
        positions = get_positions()
        if positions is None or positions.empty:
            return 0
        return len(positions)
    except Exception as e:
        logger.error(f"Error counting open positions: {e}")
        # Fallback: count PairLocks
        try:
            from app.nexus.models import PairLock
            return PairLock.objects.count()
        except Exception:
            return 0


@shared_task(name='quant.tasks.run_quant_entry_algorithm', max_retries=3, soft_time_limit=60, time_limit=90)
def run_quant_entry_algorithm():
    """Multi-strategy entry dispatcher. Runs all active strategies in priority order."""
    if is_bot_paused():
        logger.info("Bot is paused, skipping entry algorithm.")
        return
    if not TRAINING_MODE and _check_global_daily_halt():
        logger.debug("Daily halt — skipping entry algorithms.")
        return
    try:
        from app.nexus.models import StrategyConfig, PairLock

        active_strategies = StrategyConfig.objects.filter(is_active=True).order_by('priority')
        if not active_strategies.exists():
            logger.warning("No active strategies found.")
            return

        total_open = _count_open_positions()

        for config in active_strategies:
            if total_open >= GLOBAL_MAX:
                logger.info(f"Global position limit reached ({GLOBAL_MAX})")
                break

            # Check per-strategy position limit
            strategy_open = PairLock.objects.filter(strategy=config).count()
            if strategy_open >= config.max_positions:
                logger.info(f"Strategy {config.name}: position limit reached ({config.max_positions})")
                continue

            # Check regime filter (if set) — bypassed in training mode
            if not TRAINING_MODE and config.regime_filter:
                try:
                    from app.quant.algorithms.regime import get_dominant_regime
                    current_regime = get_dominant_regime()
                    if current_regime != config.regime_filter and current_regime != 'UNKNOWN':
                        logger.info(f"Skipping {config.name}: regime={current_regime}, wants={config.regime_filter}")
                        continue
                except Exception as e:
                    logger.warning(f"Regime check failed for {config.name}, proceeding anyway: {e}")

            # Live performance gate — bypassed in training mode
            if not TRAINING_MODE and not _check_live_performance(config):
                continue

            # Route to appropriate entry algorithm
            remaining_slots = min(config.max_positions - strategy_open, GLOBAL_MAX - total_open)

            if _is_custom_strategy(config):
                cvd_entry_algorithm(config, remaining_slots)
            elif config.name == 'SCALPING':
                scalp_entry_algorithm()
            elif config.name == 'MEAN_REVERSION':
                mr_entry_algorithm()
            else:
                logger.info(f"Unknown strategy type: {config.name}")

            # Re-count after each strategy runs
            total_open = _count_open_positions()

    except SoftTimeLimitExceeded:
        logger.error("Task timed out.")
    except Exception as e:
        logger.error(f"Error in quant entry algorithm: {e}")


@shared_task(name='quant.tasks.run_quant_trailing_stop_algorithm', max_retries=3, soft_time_limit=15, time_limit=25)
def run_quant_trailing_stop_algorithm():
    """Adaptive position management — replaces static trailing stop."""
    if is_bot_paused():
        logger.info("Bot is paused, skipping trailing stop algorithm.")
        return
    try:
        from app.quant.algorithms.position_manager import manage_positions
        manage_positions()
    except ImportError:
        # Position manager not yet available — fall back to old trailing stop
        logger.info("Position manager not available, falling back to legacy trailing stop.")
        _run_legacy_trailing_stop()
    except Exception as e:
        logger.error(f"Position manager error: {e}")
        # Fallback to old trailing stop if position manager fails
        _run_legacy_trailing_stop()


def _run_legacy_trailing_stop():
    """Run the old per-strategy trailing stop as a fallback."""
    try:
        strategy = get_active_strategy()
        logger.info(f"Running legacy trailing stop (strategy={strategy})...")

        if strategy == 'SCALPING':
            scalp_trailing_algorithm()
        elif strategy == 'MEAN_REVERSION':
            mr_trailing_algorithm()
        elif strategy and _is_custom_strategy(strategy):
            cvd_trailing_algorithm()
        else:
            logger.warning(f"No active strategy found or unknown strategy: {strategy}")
    except SoftTimeLimitExceeded:
        logger.error("Task timed out during trailing stop algorithm.")
    except Exception as e:
        logger.error(f"Error in legacy trailing stop algorithm: {e}")


@shared_task(name='quant.tasks.run_quant_close_algorithm', max_retries=3, soft_time_limit=15, time_limit=25)
def run_quant_close_algorithm():
    try:
        logger.info("Starting quant close algorithm...")
        close_algorithm()
    except SoftTimeLimitExceeded:
        logger.error("Task timed out.")
    except Exception as e:
        logger.error(f"Error in quant close algorithm: {e}")


@shared_task(name='quant.tasks.run_regime_scan', soft_time_limit=60, time_limit=90)
def run_regime_scan():
    """Classify market regime for all pairs. Runs every 5 minutes."""
    try:
        from app.quant.algorithms.regime import scan_all_pairs
        scan_all_pairs()
    except ImportError:
        logger.info("Regime scanner not yet available, skipping.")
    except Exception as e:
        logger.error(f"Regime scan error: {e}")


@shared_task(name='quant.tasks.run_backtest', max_retries=1, soft_time_limit=120, time_limit=180)
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


@shared_task(name='quant.tasks.run_custom_backtest', max_retries=1, soft_time_limit=120, time_limit=180)
def run_custom_backtest(custom_strategy_id):
    try:
        from app.nexus.models import CustomStrategy, StrategyConfig, BacktestResult
        from app.quant.backtester_generic import GenericBacktester

        custom = CustomStrategy.objects.get(id=custom_strategy_id)
        logger.info(f"Starting custom backtest for '{custom.name}'...")

        backtester = GenericBacktester(custom.definition)
        result = backtester.run()

        # Reuse existing StrategyConfig or create one
        config_name = f'{custom.name[:40]} ({custom.domain})'[:50]
        if custom.strategy_config:
            strategy_config = custom.strategy_config
            # Keep name in sync
            if strategy_config.name != config_name:
                strategy_config.name = config_name
            strategy_config.description = custom.description
            strategy_config.save(update_fields=['name', 'description'])
        else:
            strategy_config, _ = StrategyConfig.objects.get_or_create(
                name=config_name,
                defaults={'description': custom.description, 'is_active': False}
            )
            custom.strategy_config = strategy_config
            custom.save(update_fields=['strategy_config'])

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


@shared_task(name='quant.tasks.run_strategy_evolution', max_retries=0, soft_time_limit=300, time_limit=450)
def run_strategy_evolution():
    """Strategy Evolution Engine — research, generate, backtest, promote/retire strategies."""
    if is_bot_paused():
        return
    try:
        from app.quant.strategy_evolver import evolve_strategies
        logger.info("Starting strategy evolution cycle...")
        result = evolve_strategies()
        if result:
            logger.info(
                f"Strategy evolution complete: "
                f"promoted={result.get('promoted', 0)}, "
                f"retired={result.get('retired', 0)}, "
                f"candidates={result.get('candidates_tested', 0)}"
            )
    except Exception as e:
        logger.error(f"Strategy evolution error: {e}")


@shared_task(name='quant.tasks.run_macro_analysis', max_retries=1, soft_time_limit=60, time_limit=90)
def run_macro_analysis():
    """Periodic macro analysis — Claude analyzes news/geopolitics for trading intelligence."""
    try:
        from app.quant.macro_analyst import run_macro_analysis as analyze
        logger.info("Starting macro analysis...")
        result = analyze()
        if result:
            logger.info(
                f"Macro analysis: risk={result.get('risk_level')}, "
                f"narrative={result.get('market_narrative', '')[:80]}"
            )
        else:
            logger.info("Macro analysis: no data or skipped")
    except Exception as e:
        logger.error(f"Macro analysis error: {e}")


@shared_task(name='quant.tasks.run_ai_brain', max_retries=1, soft_time_limit=120, time_limit=180)
def run_ai_brain():
    """Periodic AI Brain analysis — gathers data from all domains and sends to Claude."""
    from app.quant.ai_bot_control import is_ai_brain_paused
    if is_ai_brain_paused():
        return
    try:
        from app.quant.ai_brain import run_analysis
        logger.info("Starting AI Brain analysis...")
        result = run_analysis()
        if result:
            logger.info(f"AI Brain complete: regime={result.get('market_regime')}, risk={result.get('risk_score')}")
        else:
            logger.warning("AI Brain returned no result")
    except SoftTimeLimitExceeded:
        logger.error("AI Brain task timed out.")
    except Exception as e:
        logger.error(f"AI Brain error: {e}")


@shared_task(name='quant.tasks.fetch_market_pulse', max_retries=1, soft_time_limit=30, time_limit=45)
def fetch_market_pulse():
    """Fetch forex news from Finnhub + RSS feeds, economic calendar from Finnhub."""
    import requests
    import time
    from xml.etree import ElementTree as ET
    from email.utils import parsedate_to_datetime
    from django.conf import settings
    from django.core.cache import cache

    FOREX_KEYWORDS = {'forex', 'currency', 'dollar', 'eur', 'gbp', 'jpy', 'aud', 'nzd',
                      'cad', 'chf', 'gold', 'xau', 'oil', 'fed', 'ecb', 'boj', 'rba',
                      'fomc', 'nfp', 'cpi', 'gdp', 'inflation', 'rate', 'yield', 'bond',
                      'treasury', 'dxy', 'fx', 'central bank', 'tariff', 'trade war'}

    all_news = []

    # --- Source 1: Finnhub (forex + general filtered) ---
    api_key = getattr(settings, 'FINNHUB_API_KEY', os.environ.get('FINNHUB_API_KEY', ''))
    if api_key:
        for category in ('forex', 'general'):
            try:
                resp = requests.get(
                    'https://finnhub.io/api/v1/news',
                    params={'category': category, 'token': api_key},
                    timeout=10,
                )
                resp.raise_for_status()
                articles = resp.json()
                if category == 'general':
                    # Filter general news for forex/macro relevance
                    articles = [a for a in articles if any(
                        kw in (a.get('headline', '') + ' ' + a.get('summary', '')).lower()
                        for kw in FOREX_KEYWORDS
                    )][:10]
                for a in articles:
                    all_news.append({
                        'id': a.get('id', 0),
                        'headline': a.get('headline', ''),
                        'url': a.get('url', ''),
                        'source': a.get('source', 'Finnhub'),
                        'datetime': a.get('datetime', 0),
                        'category': a.get('category', category),
                    })
            except Exception as e:
                logger.error(f'Market pulse Finnhub {category} fetch failed: {e}')

    # --- Source 2: ForexLive RSS (free, no key) ---
    try:
        resp = requests.get('https://www.forexlive.com/feed', timeout=8,
                            headers={'User-Agent': 'Mozilla/5.0'})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        for item in root.findall('.//item')[:12]:
            title = item.find('title')
            link = item.find('link')
            pub_date = item.find('pubDate')
            ts = 0
            if pub_date is not None and pub_date.text:
                try:
                    ts = int(parsedate_to_datetime(pub_date.text).timestamp())
                except Exception:
                    ts = int(time.time())
            all_news.append({
                'id': hash(title.text if title is not None else '') & 0x7FFFFFFF,
                'headline': title.text if title is not None else '',
                'url': link.text if link is not None else '',
                'source': 'ForexLive',
                'datetime': ts,
                'category': 'forex',
            })
    except Exception as e:
        logger.error(f'Market pulse ForexLive RSS failed: {e}')

    # --- Source 3: Investing.com forex RSS (free, no key) ---
    try:
        resp = requests.get('https://www.investing.com/rss/news_14.rss', timeout=8,
                            headers={'User-Agent': 'Mozilla/5.0'})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        for item in root.findall('.//item')[:8]:
            title = item.find('title')
            link = item.find('link')
            pub_date = item.find('pubDate')
            ts = 0
            if pub_date is not None and pub_date.text:
                try:
                    ts = int(parsedate_to_datetime(pub_date.text).timestamp())
                except Exception:
                    ts = int(time.time())
            all_news.append({
                'id': hash(title.text if title is not None else '') & 0x7FFFFFFF,
                'headline': title.text if title is not None else '',
                'url': link.text if link is not None else '',
                'source': 'Investing.com',
                'datetime': ts,
                'category': 'forex',
            })
    except Exception as e:
        logger.error(f'Market pulse Investing.com RSS failed: {e}')

    # Deduplicate by headline similarity and sort by recency
    seen = set()
    unique_news = []
    for article in all_news:
        key = article['headline'].lower().strip()[:60]
        if key and key not in seen:
            seen.add(key)
            unique_news.append(article)
    unique_news.sort(key=lambda a: a.get('datetime', 0), reverse=True)

    cache.set('market_pulse:news', unique_news[:20], timeout=300)
    logger.info(f'Market pulse: {len(unique_news)} unique articles from {len(all_news)} total')

    # Fetch economic calendar (skip if previously got 403 — requires paid Finnhub plan)
    if not cache.get('market_pulse:calendar_disabled') and api_key:
        try:
            today = date.today().isoformat()
            resp = requests.get(
                'https://finnhub.io/api/v1/calendar/economic',
                params={'from': today, 'to': today, 'token': api_key},
                timeout=10,
            )
            resp.raise_for_status()
            calendar = resp.json().get('economicCalendar', [])[:10]
            cache.set('market_pulse:calendar', calendar, timeout=300)
            logger.info(f'Market pulse: fetched {len(calendar)} calendar events')
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 403:
                cache.set('market_pulse:calendar_disabled', True, timeout=3600)
                logger.warning('Market pulse: calendar endpoint returned 403 (paid plan required), disabled for 1 hour')
            else:
                logger.error(f'Market pulse calendar fetch failed: {e}')
        except Exception as e:
            logger.error(f'Market pulse calendar fetch failed: {e}')

    # Update high-impact event guards (scans calendar for imminent NFP, FOMC, CPI, etc.)
    try:
        from app.quant.macro_analyst import update_event_guards
        update_event_guards()
    except Exception as e:
        logger.error(f'Event guard update failed: {e}')


@shared_task(name='quant.tasks.run_ai_brain_executor', max_retries=1, soft_time_limit=60, time_limit=90)
def run_ai_brain_executor():
    """Execute AI Brain recommendations — the critical feedback loop.

    Reads cached analysis from Redis and acts on it:
    - Close/tighten/scale positions per AI recommendation
    - Auto-pause strategies with poor health scores
    - Auto-pause strategies exceeding loss thresholds
    """
    if is_bot_paused():
        return
    try:
        from app.quant.ai_brain_executor import execute_ai_brain_recommendations
        result = execute_ai_brain_recommendations()
        total = sum(result.values())
        if total > 0:
            logger.info(f"AI Brain Executor: {result}")
    except SoftTimeLimitExceeded:
        logger.error("AI Brain Executor task timed out.")
    except Exception as e:
        logger.error(f"AI Brain Executor error: {e}")


@shared_task(name='quant.tasks.run_strategy_orchestrator', max_retries=1, soft_time_limit=60, time_limit=90)
def run_strategy_orchestrator():
    """Strategy Orchestrator — dynamically enable/disable strategies based on regime + performance."""
    try:
        from app.quant.strategy_orchestrator import run_orchestrator
        run_orchestrator()
    except Exception as e:
        logger.error(f"Strategy orchestrator error: {e}")


@shared_task(name='quant.tasks.run_ict_scanner', max_retries=1, soft_time_limit=60, time_limit=90)
def run_ict_scanner():
    """ICT 5-step institutional entry scanner.

    Scans all forex pairs for full ICT chain setups (HTF bias -> sweep ->
    MSS -> FVG -> price at FVG). When a valid setup is found, places an order.
    Results are cached in Redis for the dashboard ICT Setup Log.
    """
    if is_bot_paused():
        return
    if not TRAINING_MODE and _check_global_daily_halt():
        return
    try:
        total_open = _count_open_positions()
        if total_open >= GLOBAL_MAX:
            logger.debug("ICT scanner: global position limit reached")
            return

        from app.quant.algorithms.ict_entry import scan_ict_setups

        symbols = [
            # Forex majors
            'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'NZDUSD', 'USDCAD', 'USDCHF',
            # Forex minors
            'EURGBP', 'USDCNH', 'USDSEK',
            # Metals
            'XAUUSD', 'XAGUSD',
            # Energy
            'USOUSD', 'UKOUSDft',
        ]
        setups = scan_ict_setups(symbols)

        # Cache scan results for dashboard (even partial/failed results)
        _cache_ict_scan_results(symbols, setups)

        if not setups:
            return

        for setup in setups:
            if total_open >= GLOBAL_MAX:
                break

            try:
                _execute_ict_setup(setup)
                total_open += 1
            except Exception as e:
                logger.error(f"ICT: failed to execute {setup.symbol} {setup.direction}: {e}")

    except SoftTimeLimitExceeded:
        logger.error("ICT scanner task timed out.")
    except Exception as e:
        logger.error(f"ICT scanner error: {e}")


@shared_task(name='quant.tasks.handle_realtime_cvd_signal', max_retries=1, soft_time_limit=30, time_limit=45)
def handle_realtime_cvd_signal(symbol, signal_type, direction):
    """Fast-path entry triggered by real-time tick-based CVD signal.

    Called by the tick consumer when a new CVD divergence is detected.
    Runs the entry algorithm immediately instead of waiting for the 60s cycle.
    """
    if is_bot_paused():
        return
    try:
        logger.info(f"REALTIME CVD TRIGGER: {symbol} {signal_type} {direction}")
        # Trigger full entry algorithm — it will pick up the cached signal
        run_quant_entry_algorithm()
    except Exception as e:
        logger.error(f"Realtime CVD signal handler error: {e}")


@shared_task(name='quant.tasks.check_tick_consumer_health', max_retries=0, soft_time_limit=10, time_limit=15)
def check_tick_consumer_health():
    """Periodic health check for the tick consumer process."""
    from django.core.cache import cache

    # Check if tick consumer is alive by looking for recent tick data
    alive = False
    for symbol in ['EURUSD', 'XAUUSD']:
        data = cache.get(f'realtime_cvd:{symbol}')
        if data:
            alive = True
            break

    status = cache.get('tick_consumer:status', {})
    cache.set('tick_consumer:alive', alive, timeout=120)

    if not alive:
        logger.debug("TICK CONSUMER: No recent real-time CVD data detected. Consumer may be down.")


def _cache_ict_scan_results(symbols, setups):
    """Cache ICT scan results in Redis for the dashboard.

    Maintains a rolling list of the last 50 scan results, each with per-symbol
    step chain details so the dashboard can show checkmark/cross for each step.
    """
    import json
    from django.core.cache import cache
    from django.utils import timezone

    try:
        now = timezone.now().isoformat()

        # Build result entries for symbols that produced setups
        scan_entries = []
        setup_symbols = set()

        for setup in (setups or []):
            setup_symbols.add(setup.symbol)
            # Determine grade from R:R and confluence
            grade = _compute_ict_grade(setup.rr_ratio, setup.confluence_score)

            # Build step chain: all 5 steps passed for valid setups
            steps = [True, True, True, True, True]

            scan_entries.append({
                'symbol': setup.symbol,
                'direction': setup.direction,
                'grade': grade,
                'steps': steps,
                'rr_ratio': round(setup.rr_ratio, 2),
                'entry_price': round(setup.entry_price, 5),
                'stop_loss': round(setup.stop_loss, 5),
                'take_profit': round(setup.take_profit, 5),
                'confluence': setup.confluence_score,
                'timestamp': now,
            })

        # Also log symbols that were scanned but had no setup (grade F)
        for sym in symbols:
            if sym not in setup_symbols:
                scan_entries.append({
                    'symbol': sym,
                    'direction': '-',
                    'grade': 'F',
                    'steps': [False, False, False, False, False],
                    'rr_ratio': 0,
                    'entry_price': 0,
                    'stop_loss': 0,
                    'take_profit': 0,
                    'confluence': 0,
                    'timestamp': now,
                })

        # Merge with existing cache (keep last 50 entries)
        existing = cache.get('ict_scan_results', [])
        updated = scan_entries + existing
        updated = updated[:50]  # Keep last 50

        cache.set('ict_scan_results', updated, timeout=3600)  # 1 hour TTL

    except Exception as e:
        logger.error(f"Failed to cache ICT scan results: {e}")


def _compute_ict_grade(rr_ratio, confluence_score):
    """Compute ICT setup quality grade.

    A+: R:R >= 3.0 and confluence >= 8
    A:  R:R >= 2.0 and confluence >= 6
    B:  R:R >= 1.5 (minimum valid setup)
    F:  Below minimum (should not happen for valid setups)
    """
    if rr_ratio >= 3.0 and confluence_score >= 8:
        return 'A+'
    elif rr_ratio >= 2.0 and confluence_score >= 6:
        return 'A'
    elif rr_ratio >= 1.5:
        return 'B'
    return 'F'


def _execute_ict_setup(setup):
    """Place an order for a confirmed ICT setup."""
    from app.nexus.models import PairLock, Trade
    from app.utils.api.order import send_order

    # Check pair lock
    if PairLock.objects.filter(pair=setup.symbol).exists():
        logger.info(f"ICT: {setup.symbol} already has open position, skipping")
        return

    # Dynamic sizing based on ICT grade
    from app.quant.algorithms.cvd.config import CAPITAL_PER_TRADE
    capital = CAPITAL_PER_TRADE * setup.step_details.get('sl_tp', {}).get('atr', 0.001)

    # Use a sensible lot size (0.01 for micro, scaled by grade)
    lot_size = round(0.01 * (CAPITAL_PER_TRADE / 500) * (setup.rr_ratio / 2.0), 2)
    lot_size = max(0.01, min(lot_size, 0.10))  # Clamp to safe range

    order_type_mt5 = 'BUY' if setup.direction == 'BUY' else 'SELL'

    result = send_order(
        symbol=setup.symbol,
        order_type=order_type_mt5,
        lot=lot_size,
        sl=round(setup.stop_loss, 5),
        tp=round(setup.take_profit, 5),
        comment=f"ICT {setup.step_details.get('step3_mss', {}).get('type', '5step') if isinstance(setup.step_details.get('step3_mss'), dict) else '5step'}",
    )

    if result and result.get('success'):
        # Create pair lock
        PairLock.objects.create(pair=setup.symbol)

        # Log trade
        Trade.objects.create(
            symbol=setup.symbol,
            strategy=f"ICT_{setup.direction}",
            entry_price=setup.entry_price,
            sl=setup.stop_loss,
            tp=setup.take_profit,
            lot=lot_size,
            direction=setup.direction,
            entry_signal=f"ICT 5-step: {setup.step_details.get('step1_htf_bias', '')}",
        )

        logger.info(
            f"ICT ORDER PLACED: {setup.symbol} {setup.direction} "
            f"lot={lot_size} SL={setup.stop_loss:.5f} TP={setup.take_profit:.5f} "
            f"R:R={setup.rr_ratio}"
        )
    else:
        logger.warning(f"ICT: order failed for {setup.symbol}: {result}")


@shared_task(name='quant.tasks.run_llm_retrain', max_retries=1, soft_time_limit=120, time_limit=180)
def run_llm_retrain():
    """Daily LLM retraining monitor — checks data growth and triggers host-side fine-tuning.

    The actual fine-tuning (MLX LoRA) CANNOT run inside Docker (no Metal GPU access).
    This task's responsibilities:
    1. Check if Ollama is reachable on the host
    2. Count new training examples since last retrain
    3. If enough new examples (50+), export JSONL to host-accessible path
    4. Create a trigger file that a host-side cron/launchd can pick up
    5. Report status to Redis for dashboard visibility
    """
    from django.core.cache import cache
    import requests

    OLLAMA_HOST = 'http://host.docker.internal:11434'
    TRIGGER_DIR = '/app/ml_models/llm_training_data'
    TRIGGER_FILE = os.path.join(TRIGGER_DIR, 'retrain_trigger.json')
    JSONL_PATH = os.path.join(TRIGGER_DIR, 'trade_analyses.jsonl')

    status = {
        'ollama_reachable': False,
        'total_examples': 0,
        'new_since_last': 0,
        'retrain_needed': False,
        'trigger_created': False,
        'error': None,
    }

    try:
        # --- Step 1: Check if Ollama is reachable ---
        try:
            resp = requests.get(f'{OLLAMA_HOST}/api/tags', timeout=5)
            status['ollama_reachable'] = resp.status_code == 200
            if status['ollama_reachable']:
                models = [m.get('name', '') for m in resp.json().get('models', [])]
                status['ollama_models'] = models
                logger.info(f"LLM retrain: Ollama reachable, models: {models}")
            else:
                logger.warning(f"LLM retrain: Ollama returned status {resp.status_code}")
        except requests.exceptions.ConnectionError:
            logger.info("LLM retrain: Ollama not reachable at host.docker.internal:11434")
        except Exception as e:
            logger.warning(f"LLM retrain: Ollama check failed: {e}")

        # --- Step 2: Count training examples ---
        from app.quant.ml.data_collector import get_training_data_stats
        stats = get_training_data_stats()
        status['total_examples'] = stats['total_examples']
        status['wins'] = stats.get('wins', 0)
        status['losses'] = stats.get('losses', 0)
        status['file_size_kb'] = stats.get('file_size_kb', 0)

        # Compare against last retrain count
        from app.quant.ml.llm_config import RETRAIN_MIN_NEW_TRADES
        last_retrain_count = cache.get('llm_retrain:last_count', 0)
        status['new_since_last'] = stats['total_examples'] - last_retrain_count

        logger.info(
            f"LLM retrain: {stats['total_examples']} total examples "
            f"({status['new_since_last']} new since last retrain), "
            f"wins={stats.get('wins', 0)}, losses={stats.get('losses', 0)}"
        )

        # --- Step 3: Check if retrain threshold met ---
        if status['new_since_last'] < RETRAIN_MIN_NEW_TRADES:
            logger.info(
                f"LLM retrain: only {status['new_since_last']} new examples, "
                f"need {RETRAIN_MIN_NEW_TRADES}. Skipping."
            )
            cache.set('llm_retrain:status', status, timeout=86400)
            return status

        status['retrain_needed'] = True
        logger.info(
            f"LLM retrain: {status['new_since_last']} new examples >= "
            f"{RETRAIN_MIN_NEW_TRADES} threshold. Preparing retrain trigger."
        )

        # --- Step 4: Export JSONL and create trigger file ---
        # The JSONL is already written incrementally by data_collector.py to TRIGGER_DIR.
        # Verify it exists and is non-empty.
        if not os.path.exists(JSONL_PATH):
            status['error'] = 'JSONL file not found at expected path'
            logger.error(f"LLM retrain: {status['error']}: {JSONL_PATH}")
            cache.set('llm_retrain:status', status, timeout=86400)
            return status

        # Create trigger file for host-side cron/launchd to pick up
        import json
        from datetime import datetime as dt
        trigger_data = {
            'trigger_time': dt.now().isoformat(),
            'total_examples': stats['total_examples'],
            'new_examples': status['new_since_last'],
            'wins': stats.get('wins', 0),
            'losses': stats.get('losses', 0),
            'file_size_kb': stats.get('file_size_kb', 0),
            'jsonl_path': JSONL_PATH,
            'status': 'PENDING',
        }

        os.makedirs(TRIGGER_DIR, exist_ok=True)
        with open(TRIGGER_FILE, 'w') as f:
            json.dump(trigger_data, f, indent=2)

        status['trigger_created'] = True
        logger.info(
            f"LLM retrain: trigger file created at {TRIGGER_FILE}. "
            f"Host-side script should pick this up and run MLX LoRA fine-tuning."
        )

        # Update the last retrain count so we don't re-trigger next cycle
        cache.set('llm_retrain:last_count', stats['total_examples'], timeout=None)

    except Exception as e:
        status['error'] = str(e)
        logger.error(f"LLM retrain error: {e}")

    # Cache status for dashboard visibility
    cache.set('llm_retrain:status', status, timeout=86400)
    return status


@shared_task(name='quant.tasks.run_ml_retrain', max_retries=1, soft_time_limit=120, time_limit=180)
def run_ml_retrain():
    """Periodic ML model retraining check.

    Checks if enough new labeled trades have accumulated since the last
    training run, and retrains the signal scorer if so.
    """
    try:
        from app.quant.ml.trainer import should_retrain, train_model
        if should_retrain():
            result = train_model()
            if result:
                logger.info(
                    f"ML retrained: v{result['version']} {result['model_type']} "
                    f"accuracy={result['accuracy']:.1%} trades={result['trade_count']}"
                )
            else:
                logger.info("ML retrain: not enough data yet")
        else:
            logger.debug("ML retrain: not enough new trades since last training")
    except Exception as e:
        logger.error(f"ML retrain error: {e}")


@shared_task(name='quant.tasks.run_remote_training', soft_time_limit=7200, time_limit=7500)
def run_remote_training(run_id):
    """Execute remote ML training pipeline (SSH+rsync to training machine)."""
    try:
        from app.quant.ml.remote_trainer import execute_training
        execute_training(run_id)
    except Exception as e:
        logger.error(f"Remote training error: {e}")
        from app.nexus.models import TrainingRun
        from django.utils import timezone
        try:
            run = TrainingRun.objects.get(pk=run_id)
            run.status = 'failed'
            run.error = str(e)
            run.completed_at = timezone.now()
            run.save(update_fields=['status', 'error', 'completed_at'])
            run.append_log(f"FATAL: {e}")
        except TrainingRun.DoesNotExist:
            pass


@shared_task(name='quant.tasks.run_multi_source_backtest', soft_time_limit=300, time_limit=360)
def run_multi_source_backtest(strategy_config_id, period_days=90, data_source='auto', walk_forward=True):
    """Run comprehensive backtest using multi-source data.

    Supports data_source: 'auto' (try Yahoo then MT5 then Finnhub),
    'mt5', 'yahoo', 'finnhub'. Walk-forward splits data 70/30 for
    in-sample/out-of-sample validation when enabled.
    """
    try:
        from app.nexus.models import StrategyConfig, CustomStrategy, BacktestResult
        from app.quant.backtester_generic import GenericBacktester

        strategy_config = StrategyConfig.objects.get(id=strategy_config_id)
        logger.info(
            f"Multi-source backtest starting: strategy='{strategy_config.name}', "
            f"period={period_days}d, source={data_source}, walk_forward={walk_forward}"
        )

        # Resolve the definition — either from a linked CustomStrategy or a minimal default
        custom = CustomStrategy.objects.filter(strategy_config=strategy_config).first()
        if custom:
            definition = dict(custom.definition)
        else:
            # Built-in strategy: build a minimal definition from StrategyConfig
            definition = {
                'pairs': ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'XAUUSD'],
                'timeframe': 'M15',
                'indicators': [
                    {'type': 'EMA_CROSSOVER', 'params': {'fast': 9, 'slow': 21}},
                    {'type': 'RSI', 'params': {'period': 14}},
                    {'type': 'ATR', 'params': {'period': 14}},
                ],
                'entry_rules': {
                    'long': [{'indicator': 'EMA_CROSSOVER', 'condition': 'eq', 'value': 1}],
                    'short': [{'indicator': 'EMA_CROSSOVER', 'condition': 'eq', 'value': -1}],
                },
                'exit_rules': {'type': 'ATR_BASED', 'params': {'atr_period': 14, 'sl_multiplier': 1.5, 'tp_multiplier': 2.0}},
            }

        backtester = GenericBacktester(definition, data_source=data_source)

        result = backtester.run(
            data_source=data_source,
            period_days=period_days,
            walk_forward=walk_forward,
        )
        result['walk_forward'] = walk_forward

        # Save to BacktestResult
        BacktestResult.objects.create(
            strategy=strategy_config,
            total_trades=result['total_trades'],
            winning_trades=result['winning_trades'],
            losing_trades=result['losing_trades'],
            win_rate=result['win_rate'],
            total_pnl=result['total_pnl'],
            profit_factor=result.get('profit_factor'),
            avg_win=result.get('avg_win'),
            avg_loss=result.get('avg_loss'),
            passed=result['passed'],
            data_source=result.get('data_source', 'AUTO'),
            period_days=result.get('period_days', period_days),
            trades=result.get('trades', []),
            equity_curve=result.get('equity_curve', []),
            symbol_breakdown=result.get('symbol_breakdown', {}),
        )

        logger.info(
            f"Multi-source backtest completed for '{strategy_config.name}': "
            f"passed={result['passed']}, trades={result['total_trades']}, "
            f"WR={result['win_rate']:.1%}, sharpe={result.get('sharpe_ratio')}, "
            f"max_dd={result.get('max_drawdown_pct')}%, source={result.get('data_source')}"
        )

        return result

    except SoftTimeLimitExceeded:
        logger.error("Multi-source backtest task timed out.")
        return {'error': 'Task timed out'}
    except Exception as e:
        from app.nexus.models import StrategyConfig as SC
        if isinstance(e, SC.DoesNotExist):
            logger.error(f"Multi-source backtest: StrategyConfig id={strategy_config_id} not found")
            return {'error': f'StrategyConfig {strategy_config_id} not found'}
        logger.error(f"Multi-source backtest error: {e}")
        return {'error': str(e)}


@shared_task(name='quant.tasks.run_strategy_rotation', max_retries=1, soft_time_limit=300, time_limit=450)
def run_strategy_rotation(session_name=None):
    """Strategy Auto-Rotator — backtest all strategies and activate top performers.

    Runs 5x daily at forex session boundaries. Can also be triggered manually.
    """
    if is_bot_paused():
        logger.info("Bot is paused, skipping strategy rotation.")
        return
    try:
        from app.quant.algorithms.strategy_rotator import run_rotation
        result = run_rotation(session_name=session_name)
        if result:
            logger.info(
                f"Strategy rotation complete ({result.get('session')}): "
                f"activated={result.get('activated', [])}, "
                f"deactivated={result.get('deactivated', [])}, "
                f"duration={result.get('duration', 0):.1f}s"
            )
    except SoftTimeLimitExceeded:
        logger.error("Strategy rotation task timed out.")
    except Exception as e:
        logger.error(f"Strategy rotation error: {e}")
