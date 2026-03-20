# backend/django/app/quant/tasks.py

import os
from celery import shared_task
import logging
from datetime import date
from celery.exceptions import SoftTimeLimitExceeded

from app.quant.algorithms.close.close import close_algorithm
from app.utils.bot_control import is_bot_paused

logger = logging.getLogger(__name__)


@shared_task(name='quant.tasks.run_quant_trailing_stop_algorithm', max_retries=3, soft_time_limit=15, time_limit=25)
def run_quant_trailing_stop_algorithm():
    """Adaptive position management — replaces static trailing stop."""
    if is_bot_paused():
        logger.info("Bot is paused, skipping trailing stop algorithm.")
        return
    try:
        from app.quant.algorithms.position_manager import manage_positions
        manage_positions()
    except Exception as e:
        logger.error(f"Position manager error: {e}")


@shared_task(name='quant.tasks.run_quant_close_algorithm', max_retries=3, soft_time_limit=15, time_limit=25)
def run_quant_close_algorithm():
    try:
        logger.info("Starting quant close algorithm...")
        close_algorithm()
    except SoftTimeLimitExceeded:
        logger.error("Task timed out.")
    except Exception as e:
        logger.error(f"Error in quant close algorithm: {e}")


@shared_task(name='quant.tasks.run_position_reconciliation', soft_time_limit=20, time_limit=30)
def run_position_reconciliation():
    """Reconcile MT5 positions with Django DB every 30s."""
    try:
        from app.quant.algorithms.close.close import reconcile_positions
        reconcile_positions()
    except SoftTimeLimitExceeded:
        logger.error("Reconciliation task timed out.")
    except Exception as e:
        logger.error(f"Reconciliation error: {e}")


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

    # macro_analyst module removed — event guards (NFP/FOMC/CPI) not available


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


# ========================================================================
# Knowledge Graph Tasks
# ========================================================================

@shared_task(name='quant.tasks.record_to_graph', max_retries=3,
             soft_time_limit=10, time_limit=20)
def record_to_graph(payload):
    """Async fire-and-forget write to Neo4j knowledge graph."""
    if not payload:
        return

    try:
        from app.quant.knowledge.connection import get_graph
        graph = get_graph()
        if graph is None:
            return

        record_type = payload.get('type')

        if record_type == 'trade':
            from app.nexus.models import Trade
            trade = Trade.objects.get(id=payload['trade_id'])
            features = payload.get('features', {})

            # Entry context cached at trade open time (regime, MTF, confluence, etc.)
            brain_meta = payload.get('brain_meta', {})

            trade_data = {
                'trade_id': f"trade_{trade.id}",
                'django_id': trade.id,
                'symbol': trade.symbol,
                'direction': trade.type,
                'entry_time': trade.entry_time,
                'close_time': trade.close_time,
                'entry_price': trade.entry_price,
                'close_price': trade.close_price,
                'pnl': trade.pnl,
                'entry_atr': trade.entry_atr,
                'strategy': trade.strategy or (trade.strategy_config.name if trade.strategy_config else 'unknown'),
                'closing_reason': trade.closing_reason or '',
                'confluence_score': brain_meta.get('confluence_score') or features.get('confluence_score', 0),
                'regime_at_entry': brain_meta.get('regime_at_entry', 'UNKNOWN'),
                'regime_confidence': brain_meta.get('regime_confidence', 0),
                'hour_utc': trade.entry_time.hour if trade.entry_time else 0,
                'day_of_week': trade.entry_time.weekday() if trade.entry_time else 0,
            }
            # Only include brain-era fields if we have real data (not defaults)
            if brain_meta:
                trade_data.update({
                    'mtf_bias': brain_meta.get('mtf_bias', 'UNKNOWN'),
                    'mtf_confidence': brain_meta.get('mtf_confidence', 0),
                    'mtf_alignment': brain_meta.get('mtf_alignment', 'UNKNOWN'),
                    'graph_confidence': brain_meta.get('graph_confidence', 0.5),
                    'graph_recommendation': brain_meta.get('graph_recommendation', 'NORMAL'),
                    'sl_source': brain_meta.get('sl_source', 'ATR'),
                    'tp_source': brain_meta.get('tp_source', 'ATR'),
                })
            graph.record_trade(trade_data)

        elif record_type == 'lighter_trade':
            # Lighter/crypto trades — payload already has all fields, pass through
            graph.record_trade(payload)

        elif record_type == 'lighter_trade_open':
            # Record a Lighter position open (no close data yet)
            graph.record_trade_open(payload)

        elif record_type == 'lighter_trade_close':
            # Update an existing open Lighter trade with close data
            graph.update_trade_close(payload)

        elif record_type == 'trade_open':
            # Record an MT5 trade open (no close data yet)
            graph.record_trade_open(payload)

        elif record_type == 'market_condition':
            graph.record_market_condition(
                payload['symbol'], payload['condition']
            )

        elif record_type == 'regime_transition':
            graph.record_regime_transition(
                payload['symbol'],
                payload['from_regime'],
                payload['to_regime'],
                payload.get('meta', {}),
            )

        elif record_type == 'news':
            graph.record_news(payload.get('articles', []))

        elif record_type == 'rejection':
            graph.record_rejected_signal(payload)

        elif record_type == 'exit_event':
            graph.record_exit_event(payload)

        elif record_type == 'confluence':
            graph.record_confluence_breakdown(payload)

        elif record_type == 'ict_partial':
            graph.record_ict_partial(payload)

        elif record_type == 'htf_bias':
            graph.record_htf_bias(payload)

        elif record_type == 'causal_chains':
            graph.record_causal_chain(payload)

        elif record_type == 'performance_snapshot':
            graph.record_performance_snapshot(payload)

        elif record_type == 'trade_reasoning':
            graph.record_trade_reasoning(payload.get('reasoning', payload))

        elif record_type == 'era_transition':
            graph.record_era_transition(payload)

        elif record_type == 'era_backfill':
            updated = graph.backfill_trading_era()
            logger.info("Backfilled %d trades as RULE_BASED", updated)

    except Exception as e:
        logger.error(f"Graph recording error: {e}")


@shared_task(name='quant.tasks.run_graph_enrichment', max_retries=0,
             soft_time_limit=30, time_limit=45)
def run_graph_enrichment():
    """Pre-compute graph-derived features into Redis for ML consumption."""
    try:
        from django.core.cache import cache
        from app.quant.knowledge.enricher import compute_and_cache_features

        scanned_symbols = [
            'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'NZDUSD',
            'USDCAD', 'USDCHF', 'EURGBP', 'XAUUSD', 'XAGUSD',
            'USOUSD', 'UKOUSDft',
        ]

        for symbol in scanned_symbols:
            regime_detail = cache.get(f':1:hmm_regime_detail:{symbol}') or {}
            if regime_detail:
                compute_and_cache_features(symbol, regime_detail)

    except Exception as e:
        logger.error(f"Graph enrichment error: {e}")


@shared_task(name='quant.tasks.check_graph_health', max_retries=0)
def check_graph_health():
    """Health check for Neo4j knowledge graph."""
    try:
        from django.core.cache import cache
        from app.quant.knowledge.connection import get_graph

        graph = get_graph()
        if graph is None:
            cache.set('graph:status', {'connected': False}, timeout=600)
            return

        health = graph.health_check()
        summary = graph.get_graph_summary()
        cache.set('graph:status', {**health, **summary}, timeout=600)
        logger.info(
            f"Graph health: {health.get('status')} | "
            f"trades={summary.get('trades', 0)} | "
            f"conditions={summary.get('conditions', 0)}"
        )

    except Exception as e:
        logger.error(f"Graph health check error: {e}")


@shared_task(name='quant.tasks.record_daily_performance', max_retries=1,
             soft_time_limit=30, time_limit=45)
def record_daily_performance():
    """Record daily performance snapshot to knowledge graph."""
    try:
        from app.nexus.models import Trade
        from datetime import date, timedelta
        from django.db.models import Sum, Count, Q, Max, Min

        today = date.today()
        trades_today = Trade.objects.filter(
            close_time__date=today,
            close_time__isnull=False
        )

        total = trades_today.count()
        if total == 0:
            return

        wins = trades_today.filter(pnl__gt=0).count()
        losses = trades_today.filter(pnl__lte=0).count()
        agg = trades_today.aggregate(
            total_pnl=Sum('pnl'),
            best=Max('pnl'),
            worst=Min('pnl'),
        )

        record_to_graph.delay({
            'type': 'performance_snapshot',
            'id': today.isoformat(),
            'date': today.isoformat(),
            'total_trades': total,
            'wins': wins,
            'losses': losses,
            'win_rate': round(wins / total, 4) if total > 0 else 0,
            'total_pnl': float(agg['total_pnl'] or 0),
            'best_trade_pnl': float(agg['best'] or 0),
            'worst_trade_pnl': float(agg['worst'] or 0),
            'sharpe': 0,  # computed in Phase 2
            'max_drawdown': 0,  # computed in Phase 2
        })

    except Exception as e:
        logger.error(f"Daily performance snapshot error: {e}")


@shared_task(name='quant.tasks.check_news_sentiment', soft_time_limit=30, time_limit=45)
def check_news_sentiment():
    """Disabled — news sentiment gating removed. Brain handles context via geo nodes."""
    pass


# ---------------------------------------------------------------------------
# Brain entry — replaces cvd_entry_algorithm pipeline
# ---------------------------------------------------------------------------

@shared_task(name='quant.tasks.run_forex_entry', max_retries=2, soft_time_limit=55, time_limit=75)
def run_forex_entry():
    """
    Forex entry — runs BOTH the sweep system AND CVD tick entry.
    Dispatched by tick_consumer on CVD signals + Celery beat every 60s.
    """
    if is_bot_paused():
        return
    # CVD tick-based entry (24/7, uses real-time tick CVD signals)
    try:
        from app.quant.algorithms.entry_cvd_tick import entry_cvd_tick_algorithm
        entry_cvd_tick_algorithm()
    except SoftTimeLimitExceeded:
        logger.warning("[entry_cvd_tick] Task timed out")
    except Exception as e:
        logger.error(f"[entry_cvd_tick] Task error: {e}")
    # Sweep-based entry (session-specific, candle-based)
    try:
        from app.quant.algorithms.entry_forex import entry_forex_algorithm
        entry_forex_algorithm()
    except SoftTimeLimitExceeded:
        logger.warning("[entry_forex] Task timed out")
    except Exception as e:
        logger.error(f"[entry_forex] Task error: {e}")


@shared_task(name='quant.tasks.run_crypto_entry', max_retries=2, soft_time_limit=55, time_limit=75)
def run_crypto_entry():
    """
    KISS crypto entry — CVD LoP + CVD Absorption on Lighter.xyz.
    Runs every 5 minutes from Celery beat.
    """
    try:
        from app.quant.algorithms.entry_crypto import entry_crypto_algorithm
        entry_crypto_algorithm()
    except SoftTimeLimitExceeded:
        logger.warning("[entry_crypto] Task timed out")
    except Exception as e:
        logger.error(f"[entry_crypto] Task error: {e}")


@shared_task(name='quant.tasks.update_brain_pattern', max_retries=2)
def update_brain_pattern(fingerprint: str, won: bool, pnl_r: float,
                         symbol: str = '', closing_reason: str = ''):
    """
    Update StrategyPattern WR after a live trade closes.
    Then async: call Haiku to label/describe the pattern.
    Fire-and-forget — trading continues regardless of outcome.
    """
    if not fingerprint:
        return

    try:
        from app.quant.knowledge.connection import get_graph
        graph = get_graph()
        if graph:
            graph.update_pattern_outcome(fingerprint, won, pnl_r)

        # Async Haiku label — only if we have a real API key
        from app.quant.intelligence.claude_analyst import label_trade_pattern
        conditions = [c for c in fingerprint.split('_', 2)[-1].split('+') if c]
        session = next((c.replace('session_', '') for c in conditions if c.startswith('session_')), '')
        htf = 'bullish' if 'htf_aligned' in conditions and '_bullish_' in fingerprint else 'bearish'
        direction = fingerprint.split('_')[1] if '_' in fingerprint else ''
        outcome = 'WIN' if won else 'LOSS'

        label = label_trade_pattern(
            symbol=symbol or fingerprint.split('_')[0],
            direction=direction,
            outcome=outcome,
            pnl_r=pnl_r,
            conditions=conditions,
            session=session,
            htf_bias=htf,
            fingerprint=fingerprint,
        )
        if label and graph:
            graph.set_pattern_label(fingerprint, label)

    except Exception as e:
        logger.debug(f"[brain] update_brain_pattern failed: {e}")


@shared_task(name='quant.tasks.run_weekly_edge_review')
def run_weekly_edge_review():
    """
    Weekly Haiku review of all active StrategyPattern nodes.
    Deactivates dead patterns. Logs emerging edges.
    Scheduled: every Monday 06:00 UTC in CELERY_BEAT_SCHEDULE.
    """
    try:
        from app.quant.knowledge.connection import get_graph
        graph = get_graph()
        if not graph:
            return

        with graph.driver.session(database=graph.database) as sess:
            patterns = sess.run(
                """
                MATCH (p:StrategyPattern {active: true})
                RETURN p {
                    .fingerprint, .symbol, .direction,
                    .win_rate, .total, .avg_r, .source, .label
                } AS p
                """
            ).data()

        patterns = [row['p'] for row in patterns]
        if not patterns:
            logger.info("[brain] Weekly review: no active patterns")
            return

        from app.quant.intelligence.claude_analyst import weekly_edge_review
        review = weekly_edge_review(patterns)

        # Deactivate patterns Haiku flagged
        for fp in review.get('deactivate', []):
            with graph.driver.session(database=graph.database) as sess:
                sess.run(
                    "MATCH (p:StrategyPattern {fingerprint: $fp}) SET p.active = false",
                    fp=fp,
                )
            logger.info(f"[brain] Deactivated pattern: {fp}")

        # Also run automatic WR-based deactivation
        dead = graph.deactivate_dead_patterns(min_samples=8, max_wr=0.35)

        logger.info(
            f"[brain] Weekly review: {len(review.get('deactivate', []))} Haiku-deactivated, "
            f"{dead} auto-deactivated, {len(review.get('promote', []))} promoted | "
            f"Observations: {review.get('observations', '')}"
        )

    except Exception as e:
        logger.error(f"[brain] Weekly review failed: {e}")
