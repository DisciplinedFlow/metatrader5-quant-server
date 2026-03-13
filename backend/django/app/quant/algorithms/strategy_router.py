"""
Strategy Router — dynamic strategy selection based on market regime.

Per-symbol routing: EURUSD can be trending while USDCHF is ranging.
Each gets the approach that fits its current regime.

Trending regime  -> ICT displacement, EMA ribbon pullback, CVD Lack of Participants
Ranging regime   -> Mean reversion (Bollinger), FVG fill, CVD Absorption
Volatile regime  -> Only A+ setups (confluence 9+), 50% position size, wider stops
Unknown regime   -> CVD Lack of Participants with reduced size (safest default)

Livermore Ch X: "In a narrow market, don't anticipate direction -- wait for the breakout"
= Ranging regime -> don't use trend strategies, use mean reversion

Market Wizards (Dennis): "Skip periods of whipsaw"
= Volatile regime -> reduce exposure or sit out entirely

Replaces: static StrategyConfig.regime_filter matching
Keeps: strategy_orchestrator.py as a performance watchdog (still monitors WR)
"""

import json
import logging
from dataclasses import dataclass
from typing import Dict, List

from django.core.cache import cache

logger = logging.getLogger('strategy_router')


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RoutingDecision:
    """The router's decision for a specific symbol."""
    symbol: str
    regime: str                          # TRENDING, RANGING, VOLATILE, UNKNOWN
    regime_confidence: float             # 0.0-1.0
    regime_direction: str                # UP, DOWN, NEUTRAL
    selected_strategies: List[str]       # Strategy names to try (ordered by preference)
    size_multiplier: float               # Regime-based sizing (1.0 normal, 0.5 volatile)
    min_confluence: int                  # Minimum confluence score needed
    sl_multiplier_adj: float             # ATR SL adjustment (1.0 normal, 1.5 volatile = wider)
    tp_approach: str                     # 'trailing' or 'fixed_target'
    reason: str                          # Human-readable explanation

    def to_dict(self) -> dict:
        """Dict representation for logging, API responses, or ML training data."""
        return {
            'symbol': self.symbol,
            'regime': self.regime,
            'regime_confidence': self.regime_confidence,
            'regime_direction': self.regime_direction,
            'selected_strategies': self.selected_strategies,
            'size_multiplier': self.size_multiplier,
            'min_confluence': self.min_confluence,
            'sl_multiplier_adj': self.sl_multiplier_adj,
            'tp_approach': self.tp_approach,
            'reason': self.reason,
        }


# ---------------------------------------------------------------------------
# Strategy pool with regime preferences
#
# Keys match StrategyConfig.name values in the database so the router's
# decisions can be mapped back to real strategy objects when needed.
# ---------------------------------------------------------------------------

STRATEGY_POOL = {
    'CVD Lack of Participants': {
        'preferred_regimes': ['TRENDING'],
        'acceptable_regimes': ['RANGING', 'UNKNOWN'],
        'type': 'divergence',
        'min_confluence': 4,
    },
    'CVD Absorption': {
        'preferred_regimes': ['RANGING'],
        'acceptable_regimes': ['TRENDING'],
        'type': 'absorption',
        'min_confluence': 4,
    },
    'Bollinger Band Mean Reversion + RSI M5 Minors': {
        'preferred_regimes': ['RANGING'],
        'acceptable_regimes': [],
        'type': 'mean_reversion',
        'min_confluence': 5,
    },
    'EMA Ribbon Pullback Trend Rider M30': {
        'preferred_regimes': ['TRENDING'],
        'acceptable_regimes': [],
        'type': 'trend',
        'min_confluence': 4,
    },
    'EMA Momentum + RSI Filter M15': {
        'preferred_regimes': ['TRENDING'],
        'acceptable_regimes': ['VOLATILE'],
        'type': 'momentum',
        'min_confluence': 4,
    },
    'ICT Fair Value Gap + Order Block H1': {
        'preferred_regimes': ['TRENDING'],
        'acceptable_regimes': ['RANGING'],
        'type': 'structure',
        'min_confluence': 4,
    },
    'Bollinger Squeeze Breakout M15': {
        'preferred_regimes': ['RANGING'],
        'acceptable_regimes': ['TRENDING'],
        'type': 'breakout',
        'min_confluence': 4,
    },
    'CVD Extremes Scanner': {
        'preferred_regimes': ['VOLATILE'],
        'acceptable_regimes': ['TRENDING', 'RANGING'],
        'type': 'extremes',
        'min_confluence': 4,
    },
    'ICT BOS Continuation + FVG': {
        'preferred_regimes': ['TRENDING'],
        'acceptable_regimes': ['RANGING'],
        'type': 'structure',
        'min_confluence': 4,
    },
    'ICT Market Structure + FVG': {
        'preferred_regimes': ['TRENDING'],
        'acceptable_regimes': ['VOLATILE'],
        'type': 'structure',
        'min_confluence': 4,
    },
    'SMC Confluence Liquidity Sweep H4 Majors': {
        'preferred_regimes': ['TRENDING'],
        'acceptable_regimes': ['RANGING'],
        'type': 'structure',
        'min_confluence': 4,
    },
}


# ---------------------------------------------------------------------------
# Regime-specific parameter tables
#
# Livermore: "feeling-out bets" -- in uncertain conditions, reduce size.
# Market Wizards (Seykota): "Risk small in volatile markets."
# ---------------------------------------------------------------------------

REGIME_PARAMS = {
    'TRENDING': {
        'size_multiplier': 1.0,
        'min_confluence': 4,
        'sl_multiplier_adj': 1.0,
        'tp_approach': 'trailing',
    },
    'RANGING': {
        'size_multiplier': 0.8,
        'min_confluence': 4,
        'sl_multiplier_adj': 1.0,
        'tp_approach': 'fixed_target',
    },
    'VOLATILE': {
        'size_multiplier': 0.5,
        'min_confluence': 4,
        'sl_multiplier_adj': 1.5,
        'tp_approach': 'trailing',
    },
    'UNKNOWN': {
        'size_multiplier': 0.7,
        'min_confluence': 4,
        'sl_multiplier_adj': 1.2,
        'tp_approach': 'trailing',
    },
}

# Confidence threshold below which we blend toward UNKNOWN (more conservative)
LOW_CONFIDENCE_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_hmm_regime(symbol: str) -> dict:
    """Read the enhanced HMM regime detail from Redis for a symbol.

    Returns a dict with keys: label, confidence, direction.
    Falls back to UNKNOWN with 0 confidence if nothing cached.
    """
    raw = cache.get(f'hmm_regime_detail:{symbol}')
    if raw is None:
        return {'label': 'UNKNOWN', 'confidence': 0.0, 'direction': 'NEUTRAL'}

    try:
        detail = json.loads(raw) if isinstance(raw, str) else raw
        return {
            'label': detail.get('label', 'UNKNOWN'),
            'confidence': float(detail.get('confidence', 0.0)),
            'direction': detail.get('direction', 'NEUTRAL'),
        }
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning(f"ROUTER: Failed to parse HMM detail for {symbol}: {e}")
        return {'label': 'UNKNOWN', 'confidence': 0.0, 'direction': 'NEUTRAL'}


def _normalize_regime(label: str) -> str:
    """Normalize regime labels to the four canonical forms.

    The HMM module uses TRENDING/RANGING/VOLATILE/UNKNOWN.
    The MarketRegime model uses TRENDING_UP/TRENDING_DOWN/RANGING/VOLATILE.
    This function maps both to the router's canonical set.
    """
    label_upper = label.upper() if label else 'UNKNOWN'

    if label_upper in ('TRENDING', 'TRENDING_UP', 'TRENDING_DOWN'):
        return 'TRENDING'
    if label_upper == 'RANGING':
        return 'RANGING'
    if label_upper in ('VOLATILE', 'HIGH_VOLATILITY'):
        return 'VOLATILE'
    return 'UNKNOWN'


def _select_strategies(regime: str) -> List[str]:
    """Select and order strategies for a given regime.

    Strategy selection priority:
    1. Strategies whose preferred_regimes include the current regime
       (ordered by min_confluence ascending -- more permissive first)
    2. Strategies whose acceptable_regimes include the current regime
       (same ordering)
    3. If nothing matched, fall back to CVD Lack of Participants (safest default)

    Returns an ordered list of strategy names.
    """
    preferred = []
    acceptable = []

    for name, meta in STRATEGY_POOL.items():
        if regime in meta['preferred_regimes']:
            preferred.append((name, meta['min_confluence']))
        elif regime in meta['acceptable_regimes']:
            acceptable.append((name, meta['min_confluence']))

    # Sort each tier by min_confluence ascending (more permissive = tried first)
    preferred.sort(key=lambda x: x[1])
    acceptable.sort(key=lambda x: x[1])

    selected = [name for name, _ in preferred] + [name for name, _ in acceptable]

    # Guarantee at least one strategy (CVD Lack of Participants is the safest)
    if not selected:
        selected = ['CVD Lack of Participants']

    return selected


def _blend_toward_unknown(params: dict, confidence: float) -> dict:
    """When regime confidence is low, blend parameters toward UNKNOWN (conservative).

    At confidence=0.0, fully use UNKNOWN params.
    At confidence=LOW_CONFIDENCE_THRESHOLD, fully use regime params.
    Linear interpolation in between.

    Livermore: "When you are in doubt, get out." Low confidence = doubt.
    We don't get out entirely, but we become more conservative.
    """
    if confidence >= LOW_CONFIDENCE_THRESHOLD:
        return params

    unknown_params = REGIME_PARAMS['UNKNOWN']
    # blend_factor: 0.0 at confidence=0, 1.0 at confidence=threshold
    blend_factor = confidence / LOW_CONFIDENCE_THRESHOLD if LOW_CONFIDENCE_THRESHOLD > 0 else 0.0

    blended = {
        'size_multiplier': _lerp(unknown_params['size_multiplier'], params['size_multiplier'], blend_factor),
        'min_confluence': round(_lerp(unknown_params['min_confluence'], params['min_confluence'], blend_factor)),
        'sl_multiplier_adj': _lerp(unknown_params['sl_multiplier_adj'], params['sl_multiplier_adj'], blend_factor),
        'tp_approach': params['tp_approach'] if blend_factor >= 0.5 else unknown_params['tp_approach'],
    }

    return blended


def _lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation: a when t=0, b when t=1."""
    return a + (b - a) * t


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_routing_parameters(regime: str, confidence: float) -> dict:
    """Get position sizing and risk parameters for a regime.

    If confidence is below LOW_CONFIDENCE_THRESHOLD, parameters are blended
    toward the UNKNOWN (conservative) defaults.

    Returns: {
        'size_multiplier': float,     # 1.0 for trending, 0.5 for volatile
        'min_confluence': int,        # 4 for trending, 9 for volatile
        'sl_multiplier_adj': float,   # 1.0 normal, 1.5 wider for volatile
        'tp_approach': str,           # 'trailing' or 'fixed_target'
    }
    """
    base_params = REGIME_PARAMS.get(regime, REGIME_PARAMS['UNKNOWN']).copy()
    return _blend_toward_unknown(base_params, confidence)


def route_symbol(symbol: str) -> RoutingDecision:
    """Determine the best strategy approach for a specific symbol.

    Reads the HMM regime from Redis and selects strategies that fit.
    If HMM data is unavailable, falls back to UNKNOWN with conservative params.

    Returns RoutingDecision with ordered strategy list and parameters.
    """
    # Step 1: Read regime from Redis
    hmm = _read_hmm_regime(symbol)
    raw_label = hmm['label']
    confidence = hmm['confidence']
    direction = hmm['direction']

    # Step 2: Normalize the regime label
    regime = _normalize_regime(raw_label)

    # Step 3: Select strategies that fit this regime
    selected = _select_strategies(regime)

    # Step 4: Get risk/sizing parameters, blended for confidence
    params = get_routing_parameters(regime, confidence)

    # Step 5: Build the reason string
    strat_names = ", ".join(selected[:3])
    if len(selected) > 3:
        strat_names += f" (+{len(selected) - 3} more)"
    blended_note = ""
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        blended_note = f" [low-conf blend: {confidence:.2f}<{LOW_CONFIDENCE_THRESHOLD}]"

    reason = (
        f"{regime} regime (conf={confidence:.2f}, {direction}) -> "
        f"[{strat_names}] size={params['size_multiplier']:.1f}x, "
        f"min_conf={params['min_confluence']}, "
        f"SL={params['sl_multiplier_adj']:.1f}x, "
        f"TP={params['tp_approach']}{blended_note}"
    )

    decision = RoutingDecision(
        symbol=symbol,
        regime=regime,
        regime_confidence=confidence,
        regime_direction=direction,
        selected_strategies=selected,
        size_multiplier=params['size_multiplier'],
        min_confluence=params['min_confluence'],
        sl_multiplier_adj=params['sl_multiplier_adj'],
        tp_approach=params['tp_approach'],
        reason=reason,
    )

    logger.info(
        f"ROUTER: {symbol} -> {regime} (conf={confidence:.2f}, {direction}) -> "
        f"{selected} size={params['size_multiplier']:.1f}x, "
        f"min_conf={params['min_confluence']}"
    )

    return decision


def route_all_symbols(symbols: List[str]) -> Dict[str, RoutingDecision]:
    """Route all symbols and return a map of decisions.

    Also logs a summary of routing decisions grouped by regime.
    """
    decisions = {}
    regime_groups: Dict[str, List[str]] = {}

    for symbol in symbols:
        try:
            decision = route_symbol(symbol)
            decisions[symbol] = decision

            # Group by regime for summary
            regime_groups.setdefault(decision.regime, []).append(symbol)
        except Exception as e:
            logger.error(f"ROUTER: Failed to route {symbol}: {e}", exc_info=True)
            # Fail-open: produce a safe default decision
            decisions[symbol] = RoutingDecision(
                symbol=symbol,
                regime='UNKNOWN',
                regime_confidence=0.0,
                regime_direction='NEUTRAL',
                selected_strategies=['CVD Lack of Participants'],
                size_multiplier=0.7,
                min_confluence=3,
                sl_multiplier_adj=1.2,
                tp_approach='trailing',
                reason='Error fallback -> conservative defaults',
            )

    # Summary log
    summary_parts = []
    for regime, syms in sorted(regime_groups.items()):
        summary_parts.append(f"{regime}: {', '.join(syms)}")
    summary = " | ".join(summary_parts) if summary_parts else "no symbols routed"

    logger.info(f"ROUTER SUMMARY: {len(decisions)} symbols routed -- {summary}")

    return decisions


# ---------------------------------------------------------------------------
# Convenience helpers for external callers
# ---------------------------------------------------------------------------

def get_strategies_for_symbol(symbol: str) -> List[str]:
    """Quick access: get the ordered strategy list for a symbol.

    Convenience wrapper around route_symbol() for callers that only need
    the strategy names without the full RoutingDecision.
    """
    decision = route_symbol(symbol)
    return decision.selected_strategies


def is_strategy_valid_for_symbol(strategy_name: str, symbol: str) -> bool:
    """Check if a specific strategy is valid for a symbol's current regime.

    Returns True if the strategy appears in the routing decision's selected
    strategies for the given symbol. Used by the entry pipeline to validate
    that a strategy should actually fire for a particular pair.

    Handles domain suffix mismatch: StrategyConfig.name may include a domain
    like '(FOREX)' while STRATEGY_POOL keys are bare names. Uses prefix
    matching so 'CVD Lack of Participants (FOREX)' matches 'CVD Lack of Participants'.
    """
    decision = route_symbol(symbol)
    # Exact match first, then prefix match for domain-suffixed names
    for router_name in decision.selected_strategies:
        if strategy_name == router_name or strategy_name.startswith(router_name):
            return True
    return False


def get_regime_summary() -> Dict[str, str]:
    """Get a quick regime label for all scanned symbols (forex + commodities).

    Returns: {'EURUSD': 'TRENDING', 'GBPUSD': 'RANGING', 'XAUUSD': 'TRENDING', ...}
    Useful for dashboard display and logging.
    """
    from app.quant.algorithms.regime import SCANNED_SYMBOLS

    summary = {}
    for symbol in SCANNED_SYMBOLS:
        hmm = _read_hmm_regime(symbol)
        summary[symbol] = _normalize_regime(hmm['label'])
    return summary
