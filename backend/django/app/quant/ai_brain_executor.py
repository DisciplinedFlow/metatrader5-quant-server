"""
AI Brain Executor — Monitoring + protective actions only.

The AI Brain analyzes portfolio state every 5 minutes and caches recommendations
in Redis. This executor reads those recommendations and:

1. Position management: auto-TIGHTEN SL (protective only), log EXIT/SCALE_OUT as advisory
2. Strategy health: log AI opinions only (no auto-disable — avoids two-AI-layers problem)
3. Performance-based auto-pause: consecutive losses, 24h drawdown, low win rate (data-driven)

Design rationale: ML scorer is the single meta-filter for new entries. AI Brain
handles open-position protection (SL tightening) and data-driven safety stops.
Subjective AI opinions (health scores) are advisory-only to prevent conflicting
AI layers from making contradictory decisions.

Runs every 5 minutes via Celery Beat, offset from AI Brain analysis.
"""

import json
import logging
from datetime import timedelta
from collections import defaultdict

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger('app.quant.ai_brain_executor')

# Thresholds for strategy auto-pause
HEALTH_SCORE_DISABLE = 4       # Below this → disable strategy
HEALTH_SCORE_REDUCE = 6        # Below this → reduce capital allocation by 50%
MAX_24H_LOSS_USD = 30.0        # Lose more than this in 24h → pause
MAX_CONSECUTIVE_LOSSES = 5     # Consecutive losses → pause
MIN_WIN_RATE_LAST_20 = 0.30    # Win rate threshold on last 20 trades


def execute_ai_brain_recommendations():
    """Main entry point. Read AI Brain Redis cache and act on recommendations."""
    actions_taken = {
        'positions_tightened': 0,
        'strategies_paused': 0,  # Only from data-driven Phase 3
    }

    # Phase 1: Execute position-level recommendations
    _execute_position_recommendations(actions_taken)

    # Phase 2: Execute strategy health actions
    _execute_strategy_health_actions(actions_taken)

    # Phase 3: Performance-based auto-pause (independent of AI Brain)
    _execute_performance_autopause(actions_taken)

    total_actions = sum(actions_taken.values())
    if total_actions > 0:
        logger.info(f"AI Brain Executor: {actions_taken}")
    else:
        logger.debug("AI Brain Executor: no actions needed")

    return actions_taken


# ---------------------------------------------------------------------------
# Phase 1: Position Recommendations
# ---------------------------------------------------------------------------

def _execute_position_recommendations(actions_taken):
    """Read per-position recommendations. Auto-execute TIGHTEN only; log others.

    TIGHTEN is the only auto-executed action because it's purely protective
    (can only move SL in your favor). EXIT and SCALE_OUT are logged as
    advisory recommendations — the position manager and SL/TP handle exits.
    """
    try:
        from app.nexus.models import Trade
        from app.utils.api.positions import get_positions
        from app.utils.api.order import modify_sl_tp

        positions = get_positions()
        if positions is None or positions.empty:
            return

        for _, pos in positions.iterrows():
            ticket = str(pos.ticket)

            # Check for AI Brain recommendation in Redis
            rec = cache.get(f'ai_brain:position:{ticket}')
            if rec is None:
                trade = Trade.objects.filter(
                    transaction_broker_id=ticket,
                    close_time__isnull=True,
                ).first()
                if trade:
                    rec = cache.get(f'ai_brain:position:{trade.transaction_broker_id}')
                if rec is None:
                    continue

            action = rec.get('action', 'HOLD')
            reason = rec.get('reason', '')

            if action == 'EXIT':
                # Advisory only — log but don't auto-close
                logger.warning(
                    f"AI BRAIN ADVISORY EXIT: {pos.symbol} ticket={pos.ticket} "
                    f"PnL=${pos.profit:.2f} — {reason}"
                )
                cache.delete(f'ai_brain:position:{ticket}')

            elif action == 'TIGHTEN':
                # Auto-execute: only tightens SL (protective, can't make things worse)
                suggested_sl = rec.get('suggested_sl')
                if suggested_sl is not None:
                    current_sl = pos.sl
                    if pos.type == 0:  # BUY
                        if suggested_sl > (current_sl or 0):
                            result = modify_sl_tp(pos, suggested_sl, pos.tp or None)
                            if result is not None:
                                actions_taken['positions_tightened'] += 1
                                logger.info(
                                    f"AI BRAIN TIGHTEN: {pos.symbol} ticket={pos.ticket} "
                                    f"SL {current_sl} → {suggested_sl} — {reason}"
                                )
                    else:  # SELL
                        if current_sl is None or current_sl == 0 or suggested_sl < current_sl:
                            result = modify_sl_tp(pos, suggested_sl, pos.tp or None)
                            if result is not None:
                                actions_taken['positions_tightened'] += 1
                                logger.info(
                                    f"AI BRAIN TIGHTEN: {pos.symbol} ticket={pos.ticket} "
                                    f"SL {current_sl} → {suggested_sl} — {reason}"
                                )
                    cache.delete(f'ai_brain:position:{ticket}')

            elif action == 'SCALE_OUT':
                # Advisory only — log but don't auto-partial-close
                logger.warning(
                    f"AI BRAIN ADVISORY SCALE_OUT: {pos.symbol} ticket={pos.ticket} "
                    f"vol={pos.volume} PnL=${pos.profit:.2f} — {reason}"
                )
                cache.delete(f'ai_brain:position:{ticket}')

    except Exception as e:
        logger.error(f"Position recommendation execution failed: {e}")


# ---------------------------------------------------------------------------
# Phase 2: Strategy Health
# ---------------------------------------------------------------------------

def _execute_strategy_health_actions(actions_taken):
    """Log strategy health scores as advisory — no auto-disable or capital changes.

    The AI Brain's health_score is Claude's subjective opinion. Auto-disabling
    strategies based on AI opinion conflicts with the data-driven performance
    auto-pause in Phase 3. Keep one source of truth: hard numbers.
    """
    try:
        health_raw = cache.get('ai_brain:strategy_health')
        if health_raw is None:
            return

        health_data = json.loads(health_raw) if isinstance(health_raw, str) else health_raw

        for strategy_name, health in health_data.items():
            score = health.get('health_score', 5)
            is_active = health.get('is_active', False)

            if not is_active:
                continue

            if score < HEALTH_SCORE_DISABLE:
                logger.warning(
                    f"AI BRAIN ADVISORY: Strategy '{strategy_name}' health_score={score} "
                    f"(below {HEALTH_SCORE_DISABLE}) — concerns={health.get('concerns', [])}. "
                    f"No action taken (advisory only)."
                )
            elif score < HEALTH_SCORE_REDUCE:
                logger.info(
                    f"AI BRAIN ADVISORY: Strategy '{strategy_name}' health_score={score} "
                    f"(below {HEALTH_SCORE_REDUCE}) — consider reducing capital. "
                    f"No action taken (advisory only)."
                )

    except Exception as e:
        logger.error(f"Strategy health execution failed: {e}")


# ---------------------------------------------------------------------------
# Phase 3: Performance Auto-Pause (independent of AI Brain)
# ---------------------------------------------------------------------------

def _execute_performance_autopause(actions_taken):
    """Auto-pause strategies based on hard performance thresholds.

    These fire even if the AI Brain is disabled or hasn't run yet.
    """
    try:
        from app.nexus.models import StrategyConfig, Trade, CustomStrategy

        active_configs = StrategyConfig.objects.filter(is_active=True)

        for config in active_configs:
            pause_reason = _should_pause_strategy(config)
            if pause_reason:
                config.is_active = False
                config.save(update_fields=['is_active'])
                actions_taken['strategies_paused'] += 1
                logger.warning(
                    f"PERFORMANCE PAUSE: Strategy '{config.name}' disabled — {pause_reason}"
                )
                # Cache the reason for dashboard display
                cache.set(
                    f'strategy_pause_reason:{config.name}',
                    pause_reason,
                    timeout=86400,  # 24h
                )

    except Exception as e:
        logger.error(f"Performance autopause failed: {e}")


def _should_pause_strategy(strategy_config):
    """Check if a strategy should be auto-paused. Returns reason string or None."""
    from app.nexus.models import Trade, CustomStrategy

    # Build queryset for this strategy's trades
    trades_qs = Trade.objects.filter(
        strategy_config=strategy_config,
        close_time__isnull=False,
        pnl__isnull=False,
    ).order_by('-close_time')

    # Fallback to name matching if no FK-linked trades
    if trades_qs.count() < 3:
        custom = CustomStrategy.objects.filter(strategy_config=strategy_config).first()
        if custom:
            trades_qs = Trade.objects.filter(
                strategy__icontains=custom.name,
                close_time__isnull=False,
                pnl__isnull=False,
            ).order_by('-close_time')

    # Check 1: 24h loss exceeds threshold
    since_24h = timezone.now() - timedelta(hours=24)
    recent_24h = trades_qs.filter(close_time__gte=since_24h)
    if recent_24h.exists():
        total_24h_pnl = sum(t.pnl for t in recent_24h if t.pnl is not None)
        if total_24h_pnl < -MAX_24H_LOSS_USD:
            return f"Lost ${abs(total_24h_pnl):.2f} in last 24h (threshold: ${MAX_24H_LOSS_USD})"

    # Check 2: Consecutive losses
    recent_pnls = list(trades_qs.values_list('pnl', flat=True)[:20])
    if len(recent_pnls) >= MAX_CONSECUTIVE_LOSSES:
        consecutive = 0
        for pnl in recent_pnls:
            if pnl is not None and pnl <= 0:
                consecutive += 1
            else:
                break
        if consecutive >= MAX_CONSECUTIVE_LOSSES:
            return f"{consecutive} consecutive losses"

    # Check 3: Win rate on last 20 trades
    if len(recent_pnls) >= 10:
        wins = sum(1 for p in recent_pnls if p is not None and p > 0)
        wr = wins / len(recent_pnls)
        if wr < MIN_WIN_RATE_LAST_20:
            return f"Win rate {wr:.0%} on last {len(recent_pnls)} trades (min: {MIN_WIN_RATE_LAST_20:.0%})"

    return None
