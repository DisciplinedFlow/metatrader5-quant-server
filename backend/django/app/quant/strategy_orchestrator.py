"""
Strategy Orchestrator — Dynamic strategy management based on market regime and rolling performance.

Runs every 5 minutes as a Celery periodic task. Responsibilities:
1. Read current market regime for all traded pairs (from MarketRegime model)
2. Determine dominant regime via majority vote
3. Check rolling performance (last 10 trades in 4 hours) per active strategy
4. Enable/disable strategies and adjust position sizing based on regime fit
5. Track orchestrator-managed vs user-managed strategies (never override user intent)

Design principles:
- Conservative: prefer reduced sizing over hard disable
- Zero API cost: purely data-driven from DB + Redis
- Fail-open: missing data → skip, don't block
- Transparent: every decision is logged with reasoning
"""

import logging
from collections import Counter
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger('orchestrator')

# ---------------------------------------------------------------------------
# Strategy → Regime mapping
# ---------------------------------------------------------------------------

STRATEGY_REGIME_MAP = {
    'CVD Lack of Participants': {
        'preferred_regimes': ['TRENDING_UP', 'TRENDING_DOWN'],
        'acceptable_regimes': ['RANGING'],
        'hostile_regimes': ['VOLATILE'],
        'type': 'divergence',
    },
    'EMA Ribbon Pullback Trend Rider M30': {
        'preferred_regimes': ['TRENDING_UP', 'TRENDING_DOWN'],
        'acceptable_regimes': [],
        'hostile_regimes': ['RANGING', 'VOLATILE'],
        'type': 'trend',
    },
    'EMA Momentum + RSI Filter M15': {
        'preferred_regimes': ['TRENDING_UP', 'TRENDING_DOWN'],
        'acceptable_regimes': ['VOLATILE'],
        'hostile_regimes': ['RANGING'],
        'type': 'momentum',
    },
    'ICT Fair Value Gap + Order Block H1': {
        'preferred_regimes': ['TRENDING_UP', 'TRENDING_DOWN'],
        'acceptable_regimes': ['RANGING'],
        'hostile_regimes': ['VOLATILE'],
        'type': 'structure',
    },
    'SMC Confluence Liquidity Sweep H4 Majors': {
        'preferred_regimes': ['TRENDING_UP', 'TRENDING_DOWN'],
        'acceptable_regimes': ['RANGING'],
        'hostile_regimes': ['VOLATILE'],
        'type': 'structure',
    },
    'CVD Absorption': {
        'preferred_regimes': ['RANGING'],
        'acceptable_regimes': ['TRENDING_UP', 'TRENDING_DOWN'],
        'hostile_regimes': ['VOLATILE'],
        'type': 'absorption',
    },
    'Bollinger Band Mean Reversion + RSI M5 Minors': {
        'preferred_regimes': ['RANGING'],
        'acceptable_regimes': [],
        'hostile_regimes': ['TRENDING_UP', 'TRENDING_DOWN', 'VOLATILE'],
        'type': 'mean_reversion',
    },
}

# Size multipliers by regime alignment
SIZE_MULT_PREFERRED = 1.0
SIZE_MULT_ACCEPTABLE = 0.7
SIZE_MULT_HOSTILE_MIXED = 0.4  # hostile regime but mixed signals across pairs

# Performance thresholds
PERF_MIN_WIN_RATE = 0.25       # 25% WR floor over recent trades
PERF_LOOKBACK_TRADES = 10      # Number of trades to evaluate
PERF_LOOKBACK_HOURS = 4        # Time window for performance check
PERF_PAUSE_SECONDS = 3600      # 1 hour cooldown for underperforming strategies

# Redis key prefixes
REDIS_PREFIX_PAUSE = 'orch_pause_'
REDIS_PREFIX_MANAGED = 'orch_managed_'
REDIS_PREFIX_SIZE_MULT = 'orch_size_'
REDIS_BASELINE_KEY = 'orch_user_baseline'


def _safe_key(name):
    """Sanitize strategy name for Redis cache keys (no spaces/special chars)."""
    return name.replace(' ', '_').replace('+', '').replace('/', '_')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_current_regimes():
    """Fetch recent MarketRegime records (within 10 minutes).

    Returns dict: {symbol: regime_string}
    """
    from app.nexus.models import MarketRegime

    cutoff = timezone.now() - timedelta(minutes=10)
    regimes = MarketRegime.objects.filter(computed_at__gt=cutoff)
    return {r.symbol: r.regime for r in regimes}


def _get_dominant_regime(regime_map):
    """Majority vote across all symbol regimes.

    Returns (dominant_regime, counts_dict).
    """
    if not regime_map:
        return 'UNKNOWN', {}
    counter = Counter(regime_map.values())
    dominant = counter.most_common(1)[0][0]
    return dominant, dict(counter)


def _get_rolling_performance(strategy_config):
    """Check last N trades within the lookback window for a strategy.

    Returns dict with: total, wins, losses, win_rate, or None if insufficient data.
    """
    from app.nexus.models import Trade, CustomStrategy

    cutoff = timezone.now() - timedelta(hours=PERF_LOOKBACK_HOURS)

    # Try FK first, then name-based fallback
    trades_qs = Trade.objects.filter(
        strategy_config=strategy_config,
        close_time__isnull=False,
        close_time__gte=cutoff,
    ).order_by('-close_time')

    if trades_qs.count() < 3:
        # Fallback: match by strategy name
        custom = CustomStrategy.objects.filter(strategy_config=strategy_config).first()
        if custom:
            trades_qs = Trade.objects.filter(
                strategy__icontains=custom.name,
                close_time__isnull=False,
                close_time__gte=cutoff,
            ).order_by('-close_time')

    pnls = list(trades_qs.values_list('pnl', flat=True)[:PERF_LOOKBACK_TRADES])
    if len(pnls) < 3:
        return None  # Not enough data to judge

    wins = sum(1 for p in pnls if p is not None and p > 0)
    losses = sum(1 for p in pnls if p is not None and p <= 0)
    total = wins + losses
    win_rate = wins / total if total > 0 else 0.0

    return {
        'total': total,
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'pnls': pnls,
    }


def _snapshot_user_baseline(active_configs):
    """On first run, save which strategies are currently active as the user baseline.

    This lets us distinguish "user disabled this" from "orchestrator disabled this".
    Only runs once — subsequent calls are no-ops (baseline persists in Redis for 24h).
    """
    existing = cache.get(REDIS_BASELINE_KEY)
    if existing is not None:
        return existing

    baseline = {cfg.name: cfg.is_active for cfg in active_configs}
    cache.set(REDIS_BASELINE_KEY, baseline, timeout=86400)
    logger.info(
        f"ORCHESTRATOR: Baseline snapshot — "
        f"{sum(1 for v in baseline.values() if v)} active, "
        f"{sum(1 for v in baseline.values() if not v)} inactive"
    )
    return baseline


def _is_user_disabled(strategy_name):
    """Check if a strategy was disabled by the user (not by the orchestrator).

    A strategy is user-disabled if it was inactive in the baseline AND the
    orchestrator never marked it as managed.
    """
    baseline = cache.get(REDIS_BASELINE_KEY) or {}

    # If it was inactive in baseline and orchestrator didn't manage it → user disabled
    safe = _safe_key(strategy_name)
    if strategy_name in baseline and not baseline[strategy_name]:
        if not cache.get(f'{REDIS_PREFIX_MANAGED}{safe}'):
            return True
    return False


def _is_orchestrator_paused(strategy_name):
    """Check if the orchestrator has a cooldown pause on a strategy."""
    return cache.get(f'{REDIS_PREFIX_PAUSE}{_safe_key(strategy_name)}') is not None


def _pause_strategy(strategy_config, reason):
    """Pause a strategy: set is_active=False, set Redis cooldown, mark as managed."""
    strategy_config.is_active = False
    strategy_config.save(update_fields=['is_active'])
    safe = _safe_key(strategy_config.name)
    cache.set(f'{REDIS_PREFIX_PAUSE}{safe}', True, timeout=PERF_PAUSE_SECONDS)
    cache.set(f'{REDIS_PREFIX_MANAGED}{safe}', True, timeout=86400)
    logger.warning(f"ORCHESTRATOR: Pausing '{strategy_config.name}' — {reason}")


def _enable_strategy(strategy_config, reason):
    """Re-enable a strategy that was previously paused by the orchestrator."""
    strategy_config.is_active = True
    strategy_config.save(update_fields=['is_active'])
    cache.delete(f'{REDIS_PREFIX_PAUSE}{_safe_key(strategy_config.name)}')
    logger.info(f"ORCHESTRATOR: Re-enabling '{strategy_config.name}' — {reason}")


def _set_size_multiplier(strategy_name, multiplier, reason):
    """Store the orchestrator's size multiplier in Redis (24h TTL)."""
    cache.set(f'{REDIS_PREFIX_SIZE_MULT}{_safe_key(strategy_name)}', multiplier, timeout=86400)
    if multiplier < 1.0:
        logger.info(
            f"ORCHESTRATOR: Size adjustment for '{strategy_name}': "
            f"{multiplier:.2f}x — {reason}"
        )


def _classify_regime_alignment(strategy_name, dominant_regime, regime_map):
    """Determine how well a strategy aligns with the current market regime.

    Returns: 'preferred', 'acceptable', 'hostile', or 'neutral' (unknown/no mapping).
    Also returns per-pair hostile count for mixed-signal detection.
    """
    mapping = STRATEGY_REGIME_MAP.get(strategy_name)
    if not mapping:
        return 'neutral', 0, len(regime_map)

    hostile_count = sum(
        1 for regime in regime_map.values()
        if regime in mapping['hostile_regimes']
    )
    total_pairs = len(regime_map) if regime_map else 1

    if dominant_regime in mapping['preferred_regimes']:
        return 'preferred', hostile_count, total_pairs
    elif dominant_regime in mapping['acceptable_regimes']:
        return 'acceptable', hostile_count, total_pairs
    elif dominant_regime in mapping['hostile_regimes']:
        return 'hostile', hostile_count, total_pairs
    else:
        return 'neutral', hostile_count, total_pairs


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_orchestrator():
    """Main orchestrator loop — called every 5 minutes by Celery.

    Decision flow for each strategy:
    1. Skip user-disabled strategies (never touch them)
    2. Check if orchestrator pause cooldown is active → skip if so (unless regime improved)
    3. Check regime alignment → set size multiplier
    4. Check rolling performance → pause if WR < 25%
    5. If hostile across ALL pairs → pause
    6. If previously paused by orchestrator and cooldown expired + regime favorable → re-enable
    """
    from app.nexus.models import StrategyConfig

    logger.info("ORCHESTRATOR: Starting strategy evaluation cycle...")

    # Step A: Read current regimes
    regime_map = _get_current_regimes()
    if not regime_map:
        logger.warning("ORCHESTRATOR: No recent regime data available — skipping cycle.")
        return

    dominant_regime, regime_counts = _get_dominant_regime(regime_map)
    logger.info(
        f"ORCHESTRATOR: Dominant regime = {dominant_regime} "
        f"(distribution: {regime_counts})"
    )

    # Step B: Snapshot user baseline (first run only)
    all_configs = list(StrategyConfig.objects.all())
    baseline = _snapshot_user_baseline(all_configs)

    # Step C: Evaluate each strategy
    decisions = []

    for config in all_configs:
        strategy_name = config.name
        mapping = STRATEGY_REGIME_MAP.get(strategy_name)

        # Skip strategies we don't have a regime mapping for
        if not mapping:
            continue

        # Never touch user-disabled strategies
        if _is_user_disabled(strategy_name):
            logger.debug(
                f"ORCHESTRATOR: Skipping '{strategy_name}' — user-disabled"
            )
            continue

        alignment, hostile_count, total_pairs = _classify_regime_alignment(
            strategy_name, dominant_regime, regime_map,
        )
        hostile_pct = hostile_count / total_pairs if total_pairs > 0 else 0

        safe_name = _safe_key(strategy_name)

        # --- Case 1: Strategy is currently paused by orchestrator ---
        if not config.is_active and cache.get(f'{REDIS_PREFIX_MANAGED}{safe_name}'):
            # Check if cooldown expired AND regime improved
            cooldown_expired = not _is_orchestrator_paused(strategy_name)

            if cooldown_expired and alignment in ('preferred', 'acceptable'):
                _enable_strategy(
                    config,
                    f"cooldown expired + regime now {alignment} "
                    f"(dominant={dominant_regime})",
                )
                _set_size_multiplier(
                    strategy_name,
                    SIZE_MULT_PREFERRED if alignment == 'preferred' else SIZE_MULT_ACCEPTABLE,
                    f"re-enabled in {alignment} regime",
                )
                decisions.append(f"RE-ENABLED '{strategy_name}' ({alignment})")
            elif cooldown_expired and alignment == 'neutral':
                # Unknown regime — cautiously re-enable with reduced size
                _enable_strategy(config, "cooldown expired, regime neutral")
                _set_size_multiplier(strategy_name, SIZE_MULT_ACCEPTABLE, "neutral regime after cooldown")
                decisions.append(f"RE-ENABLED '{strategy_name}' (neutral, reduced size)")
            else:
                reason = "cooldown active" if not cooldown_expired else f"regime still {alignment}"
                logger.debug(f"ORCHESTRATOR: '{strategy_name}' remains paused — {reason}")
                decisions.append(f"PAUSED '{strategy_name}' (still {reason})")
            continue

        # --- Case 2: Strategy is active — evaluate it ---
        if not config.is_active:
            # Inactive but not orchestrator-managed → user disabled, skip
            continue

        # 2a. Check rolling performance
        perf = _get_rolling_performance(config)
        if perf is not None and perf['win_rate'] < PERF_MIN_WIN_RATE:
            _pause_strategy(
                config,
                f"WR {perf['win_rate']:.0%} < {PERF_MIN_WIN_RATE:.0%} "
                f"over last {perf['total']} trades in {PERF_LOOKBACK_HOURS}h "
                f"(W:{perf['wins']} L:{perf['losses']})"
            )
            _set_size_multiplier(strategy_name, 0.0, "performance pause")
            decisions.append(
                f"PAUSED '{strategy_name}' (WR={perf['win_rate']:.0%})"
            )
            continue

        # 2b. Check regime alignment
        if alignment == 'hostile' and hostile_pct >= 1.0:
            # ALL pairs are hostile — pause the strategy
            _pause_strategy(
                config,
                f"{hostile_count}/{total_pairs} pairs in hostile regime "
                f"({dominant_regime}) for {mapping['type']}"
            )
            _set_size_multiplier(strategy_name, 0.0, "all pairs hostile")
            decisions.append(
                f"PAUSED '{strategy_name}' (all {total_pairs} pairs hostile)"
            )
            continue

        # 2c. Set size multiplier based on alignment
        if alignment == 'preferred':
            _set_size_multiplier(strategy_name, SIZE_MULT_PREFERRED, f"preferred regime ({dominant_regime})")
            decisions.append(f"OK '{strategy_name}' — preferred (1.0x)")

        elif alignment == 'acceptable':
            _set_size_multiplier(strategy_name, SIZE_MULT_ACCEPTABLE, f"acceptable regime ({dominant_regime})")
            decisions.append(f"OK '{strategy_name}' — acceptable (0.7x)")

        elif alignment == 'hostile' and hostile_pct < 1.0:
            # Mixed signals — some pairs hostile, some not. Reduce size, don't disable
            _set_size_multiplier(
                strategy_name, SIZE_MULT_HOSTILE_MIXED,
                f"mixed hostile: {hostile_count}/{total_pairs} pairs hostile ({dominant_regime})"
            )
            decisions.append(
                f"REDUCED '{strategy_name}' — mixed hostile "
                f"({hostile_count}/{total_pairs} pairs, 0.4x)"
            )

        else:
            # Neutral / unknown regime — leave at acceptable sizing
            _set_size_multiplier(strategy_name, SIZE_MULT_ACCEPTABLE, f"neutral regime ({dominant_regime})")
            decisions.append(f"OK '{strategy_name}' — neutral (0.7x)")

    # Summary log
    logger.info(
        f"ORCHESTRATOR: Cycle complete — {len(decisions)} decisions: "
        + "; ".join(decisions) if decisions else "no mapped strategies found"
    )


def get_orchestrator_size_multiplier(strategy_name):
    """Read the orchestrator size multiplier for a strategy.

    Called from entry algorithms to adjust position sizing.
    Returns 1.0 if no orchestrator data is available (fail-open).
    """
    mult = cache.get(f'{REDIS_PREFIX_SIZE_MULT}{_safe_key(strategy_name)}')
    if mult is not None:
        return float(mult)
    return 1.0
