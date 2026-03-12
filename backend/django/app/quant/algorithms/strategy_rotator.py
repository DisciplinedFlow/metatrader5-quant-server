"""Strategy Auto-Rotator — backtests all strategies and activates top performers.

Runs 5x daily at forex session boundaries. Scores each strategy based on
profit factor, win rate, R:R, trade count, and HMM regime fit, then
activates the best and deactivates the worst.

Livermore: "There is a time to go long, a time to go short, and a time to go fishing."
This module decides which.
"""

import json
import logging
import time
from datetime import datetime, timezone

from django.core.cache import cache

logger = logging.getLogger('strategy_rotator')

# ---------------------------------------------------------------------------
# Session definitions (UTC hours)
# ---------------------------------------------------------------------------

ROTATION_SESSIONS = {
    'ASIA_OPEN':    {'hour': 6,  'label': 'Asia Open',     'window': (0, 8)},
    'LONDON_OPEN':  {'hour': 9,  'label': 'London Open',   'window': (7, 14)},
    'NY_OPEN':      {'hour': 13, 'label': 'NY Open',       'window': (12, 18)},
    'NY_AFTERNOON': {'hour': 17, 'label': 'NY Afternoon',  'window': (15, 22)},
    'ASIA_CLOSE':   {'hour': 22, 'label': 'Asia Close',    'window': (20, 3)},
}

# ---------------------------------------------------------------------------
# Scoring weights (sum to 1.0)
# ---------------------------------------------------------------------------

W_PROFIT_FACTOR = 0.30
W_WIN_RATE      = 0.20
W_RR_RATIO      = 0.15
W_TRADE_COUNT   = 0.10
W_REGIME_FIT    = 0.25

# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

MIN_TRADES_FOR_SCORING  = 5
MIN_ACTIVE_STRATEGIES   = 2
MAX_ACTIVE_STRATEGIES   = 7
ROTATION_LOCK_TTL       = 14400   # 4 hours
MIN_SCORE_TO_ACTIVATE   = 0.35
BACKTEST_PERIOD_DAYS    = 60
ROTATION_LOCK_KEY       = 'rotation_in_progress'


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _regime_fit_score(strategy_name, dominant_regime):
    """Score how well a strategy fits the current regime (0.0 - 1.0)."""
    from app.quant.algorithms.strategy_router import STRATEGY_POOL

    pool_entry = STRATEGY_POOL.get(strategy_name)
    if not pool_entry or not dominant_regime or dominant_regime == 'UNKNOWN':
        return 0.3  # neutral when unknown

    preferred = pool_entry.get('preferred_regimes', [])
    acceptable = pool_entry.get('acceptable_regimes', [])

    if dominant_regime in preferred:
        return 1.0
    if dominant_regime in acceptable:
        return 0.6
    return 0.1  # hostile regime


def score_strategy(backtest_result, strategy_name, dominant_regime):
    """Score a strategy based on backtest results and regime context.

    Returns dict with composite_score (0-1) and component breakdown.
    """
    total_trades = backtest_result.get('total_trades', 0)

    if total_trades < MIN_TRADES_FOR_SCORING:
        return {
            'composite_score': 0.0,
            'components': {},
            'trade_count': total_trades,
            'reason': f'insufficient trades ({total_trades} < {MIN_TRADES_FOR_SCORING})',
        }

    # Profit Factor score (PF of 2.0+ = great, 1.0 = breakeven)
    pf = backtest_result.get('profit_factor') or 0
    pf_score = min(pf / 2.5, 1.0)

    # Win Rate score
    wr = backtest_result.get('win_rate', 0)
    wr_score = min(wr / 0.60, 1.0)

    # Risk-Reward ratio score
    avg_win = backtest_result.get('avg_win', 0) or 0
    avg_loss = abs(backtest_result.get('avg_loss', 0) or -1)
    rr = avg_win / avg_loss if avg_loss > 0 else 0
    rr_score = min(rr / 3.0, 1.0)

    # Trade count score (penalize sparse strategies)
    tc_score = min(total_trades / 50, 1.0)

    # Regime fit score
    rf_score = _regime_fit_score(strategy_name, dominant_regime)

    composite = (
        W_PROFIT_FACTOR * pf_score +
        W_WIN_RATE      * wr_score +
        W_RR_RATIO      * rr_score +
        W_TRADE_COUNT   * tc_score +
        W_REGIME_FIT    * rf_score
    )

    return {
        'composite_score': round(composite, 4),
        'components': {
            'profit_factor': round(pf_score, 3),
            'win_rate': round(wr_score, 3),
            'rr_ratio': round(rr_score, 3),
            'trade_count': round(tc_score, 3),
            'regime_fit': round(rf_score, 3),
        },
        'raw': {
            'profit_factor': round(pf, 3),
            'win_rate': round(wr, 3),
            'rr_ratio': round(rr, 3),
            'total_trades': total_trades,
        },
        'trade_count': total_trades,
        'reason': 'scored',
    }


# ---------------------------------------------------------------------------
# Regime helpers
# ---------------------------------------------------------------------------

def _get_regime_snapshot():
    """Read HMM regime data from Redis for all pairs.

    Returns (per_pair_dict, dominant_regime_str).
    """
    per_pair = {}
    pairs = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'NZDUSD', 'USDCAD',
             'USDCHF', 'XAUUSD', 'XAGUSD']

    for symbol in pairs:
        raw = cache.get(f'hmm_regime_detail:{symbol}')
        if raw:
            try:
                detail = json.loads(raw) if isinstance(raw, str) else raw
                per_pair[symbol] = detail.get('label', 'UNKNOWN')
            except (json.JSONDecodeError, TypeError):
                per_pair[symbol] = 'UNKNOWN'
        else:
            per_pair[symbol] = 'UNKNOWN'

    # Consensus
    consensus_raw = cache.get('hmm_regime_consensus')
    dominant = 'UNKNOWN'
    if consensus_raw:
        try:
            consensus = json.loads(consensus_raw) if isinstance(consensus_raw, str) else consensus_raw
            dominant = consensus.get('dominant_regime', 'UNKNOWN')
        except (json.JSONDecodeError, TypeError):
            pass

    return per_pair, dominant


def _detect_session():
    """Auto-detect the nearest rotation session based on current UTC hour."""
    now_hour = datetime.now(timezone.utc).hour
    best = None
    best_dist = 999
    for name, info in ROTATION_SESSIONS.items():
        dist = abs(now_hour - info['hour'])
        if dist > 12:
            dist = 24 - dist
        if dist < best_dist:
            best_dist = dist
            best = name
    return best


# ---------------------------------------------------------------------------
# Core rotation
# ---------------------------------------------------------------------------

def run_rotation(session_name=None):
    """Main entry point — backtest all strategies, score, and rotate.

    Args:
        session_name: One of ROTATION_SESSIONS keys, or None to auto-detect.

    Returns dict with rotation results or None if skipped.
    """
    from app.nexus.models import (
        CustomStrategy, StrategyConfig, BacktestResult, PairLock, RotationLog,
    )
    from app.quant.backtester_generic import GenericBacktester

    start_time = time.time()

    # Weekend check
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        logger.info('Strategy rotation skipped: weekend')
        return {'status': 'skipped', 'reason': 'weekend'}

    # Prevent concurrent runs
    if cache.get(ROTATION_LOCK_KEY):
        logger.info('Strategy rotation skipped: already in progress')
        return {'status': 'skipped', 'reason': 'already_running'}
    cache.set(ROTATION_LOCK_KEY, '1', timeout=600)

    try:
        session = session_name or _detect_session()
        logger.info(f'ROTATION: Starting {session} rotation cycle')

        # 1. Get regime snapshot
        regime_state, dominant_regime = _get_regime_snapshot()
        logger.info(f'ROTATION: Dominant regime = {dominant_regime}')

        # 2. Get all FOREX strategies
        forex_strategies = CustomStrategy.objects.filter(
            domain='FOREX',
            strategy_config__isnull=False,
        ).select_related('strategy_config')

        if not forex_strategies.exists():
            logger.warning('ROTATION: No FOREX strategies found')
            return {'status': 'skipped', 'reason': 'no_strategies'}

        # 3. Backtest and score each strategy
        scored = []
        for cs in forex_strategies:
            strategy_name = cs.name
            config = cs.strategy_config

            try:
                backtester = GenericBacktester(cs.definition)
                result = backtester.run()
            except Exception as e:
                logger.warning(f'ROTATION: Backtest failed for {strategy_name}: {e}')
                continue

            # Store backtest result
            try:
                BacktestResult.objects.create(
                    strategy=config,
                    total_trades=result.get('total_trades', 0),
                    winning_trades=result.get('winning_trades', 0),
                    losing_trades=result.get('losing_trades', 0),
                    win_rate=result.get('win_rate', 0),
                    total_pnl=result.get('total_pnl', 0),
                    profit_factor=result.get('profit_factor', 0),
                    avg_win=result.get('avg_win', 0),
                    avg_loss=result.get('avg_loss', 0),
                    passed=result.get('passed', False),
                    data_source=result.get('data_source', 'YAHOO'),
                    period_days=result.get('period_days', BACKTEST_PERIOD_DAYS),
                    symbol_breakdown=result.get('symbol_breakdown', {}),
                )
            except Exception as e:
                logger.debug(f'ROTATION: Failed to store backtest for {strategy_name}: {e}')

            # Score
            score_data = score_strategy(result, strategy_name, dominant_regime)
            score_data['strategy_name'] = strategy_name
            score_data['config_id'] = config.id
            score_data['was_active'] = config.is_active
            scored.append(score_data)

            logger.info(
                f'ROTATION: {strategy_name}: score={score_data["composite_score"]:.3f} '
                f'(PF={score_data.get("raw", {}).get("profit_factor", 0):.2f}, '
                f'WR={score_data.get("raw", {}).get("win_rate", 0):.1%}, '
                f'trades={score_data["trade_count"]})'
            )

        if not scored:
            logger.error('ROTATION: All backtests failed, keeping current state')
            return {'status': 'skipped', 'reason': 'all_backtests_failed'}

        # 4. Sort by score and apply activation decisions
        scored.sort(key=lambda x: x['composite_score'], reverse=True)
        activated, deactivated = _apply_decisions(scored, PairLock, StrategyConfig)

        duration = time.time() - start_time

        # 5. Build summary
        reason_parts = [
            f'{session} rotation: regime={dominant_regime},',
            f'scored {len(scored)} strategies,',
            f'activated {len(activated)}, deactivated {len(deactivated)}.',
        ]
        if activated:
            reason_parts.append(f'Top: {scored[0]["strategy_name"]} ({scored[0]["composite_score"]:.3f})')

        reason = ' '.join(reason_parts)

        # 6. Log rotation
        scores_dict = {s['strategy_name']: {
            'score': s['composite_score'],
            'components': s.get('components', {}),
            'raw': s.get('raw', {}),
        } for s in scored}

        RotationLog.objects.create(
            session_name=session,
            regime_state=regime_state,
            dominant_regime=dominant_regime,
            strategies_scored=len(scored),
            strategies_activated=activated,
            strategies_deactivated=deactivated,
            scores=scores_dict,
            reason=reason,
            duration_seconds=round(duration, 1),
        )

        logger.info(
            f'ROTATION COMPLETE: {session} in {duration:.1f}s — '
            f'activated={activated}, deactivated={deactivated}'
        )

        return {
            'status': 'completed',
            'session': session,
            'dominant_regime': dominant_regime,
            'scored': len(scored),
            'activated': activated,
            'deactivated': deactivated,
            'duration': round(duration, 1),
        }

    finally:
        cache.delete(ROTATION_LOCK_KEY)


def _apply_decisions(scored, PairLock, StrategyConfig):
    """Decide which strategies to activate/deactivate based on scores.

    Rules:
    - Activate top MAX_ACTIVE_STRATEGIES with score >= MIN_SCORE_TO_ACTIVATE
    - Never go below MIN_ACTIVE_STRATEGIES
    - Don't deactivate strategies with open positions (PairLock)
    - Ensure at least 1 RANGING and 1 TRENDING strategy when possible
    - Set rotation locks in Redis
    """
    from app.quant.algorithms.strategy_router import STRATEGY_POOL

    activated = []
    deactivated = []

    # Identify strategies with open positions (can't deactivate)
    locked_config_ids = set(
        PairLock.objects.values_list('strategy_id', flat=True).distinct()
    )

    # Split into eligible and must-keep
    eligible = []
    for s in scored:
        s['has_open_positions'] = s['config_id'] in locked_config_ids
        eligible.append(s)

    # Select top performers
    to_activate = []
    to_deactivate = []

    for i, s in enumerate(eligible):
        meets_threshold = s['composite_score'] >= MIN_SCORE_TO_ACTIVATE
        in_top_n = i < MAX_ACTIVE_STRATEGIES

        if meets_threshold and in_top_n:
            to_activate.append(s)
        else:
            to_deactivate.append(s)

    # Ensure minimum active count
    while len(to_activate) < MIN_ACTIVE_STRATEGIES and to_deactivate:
        promoted = to_deactivate.pop(0)  # best of the deactivated
        to_activate.append(promoted)

    # Ensure regime diversity: at least 1 RANGING and 1 TRENDING if available
    active_regimes = set()
    for s in to_activate:
        pool = STRATEGY_POOL.get(s['strategy_name'], {})
        for r in pool.get('preferred_regimes', []):
            active_regimes.add(r)

    for needed_regime in ('RANGING', 'TRENDING'):
        if needed_regime not in active_regimes:
            # Find best strategy for this regime from deactivated list
            for i, s in enumerate(to_deactivate):
                pool = STRATEGY_POOL.get(s['strategy_name'], {})
                if needed_regime in pool.get('preferred_regimes', []):
                    promoted = to_deactivate.pop(i)
                    to_activate.append(promoted)
                    active_regimes.add(needed_regime)
                    break

    # Apply changes inside a transaction to ensure DB writes commit
    from django.db import transaction
    now = datetime.now(timezone.utc)

    with transaction.atomic():
        for s in to_activate:
            config_id = s['config_id']
            name = s['strategy_name']
            try:
                config = StrategyConfig.objects.select_for_update().get(id=config_id)
                if not config.is_active:
                    config.is_active = True
                    config.last_activated = now
                    config.save(update_fields=['is_active', 'last_activated'])
                    activated.append(name)
                    logger.info(f'ROTATION: ACTIVATED {name} (score={s["composite_score"]:.3f})')
                cache.set(f'rotation_lock:{config_id}', 'active', timeout=ROTATION_LOCK_TTL)
            except StrategyConfig.DoesNotExist:
                pass

        for s in to_deactivate:
            config_id = s['config_id']
            name = s['strategy_name']
            if s['has_open_positions']:
                logger.info(f'ROTATION: Keeping {name} active — has open positions')
                continue
            try:
                config = StrategyConfig.objects.select_for_update().get(id=config_id)
                if config.is_active:
                    config.is_active = False
                    config.save(update_fields=['is_active'])
                    deactivated.append(name)
                    logger.info(f'ROTATION: DEACTIVATED {name} (score={s["composite_score"]:.3f})')
                cache.set(f'rotation_lock:{config_id}', 'inactive', timeout=ROTATION_LOCK_TTL)
            except StrategyConfig.DoesNotExist:
                pass

    return activated, deactivated
