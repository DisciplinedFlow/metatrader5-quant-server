"""
Confluence Scorer — quantifies trade quality from 0 to 11.

Inspired by Mark Weinstein (Market Wizards): "Use multiple confirmations —
don't trade on one indicator alone." And Bruce Kovner: "The best trades
have multiple reasons — fundamental + technical + market position alignment."

The scorer stacks independent confirmations. Each factor adds points based on
its predictive value (validated by research and our own trade data):

Factor                    Points   Source/Validation
-----------------------------------------------------
HTF bias aligned            2     ICT: Never trade against HTF structure
Liquidity sweep detected    2     ICT: Sweep = institutional entry
CVD divergence              2     Our own data: CVD Lack of Participants = best WR
Kill zone active            1     Research: 30-50% larger pip range in kill zones
Fair Value Gap present      1     ICT: FVG = institutional imbalance
Order Block at entry        1     ICT: OB = institutional origin point
Regime favorable            1     HMM regime aligns with strategy type
Displacement detected       1     Research: 3+ strong candles = institutional move
-----------------------------------------------------
Maximum:                   11

Scoring bands:
  0-2: NO TRADE -- need at least volume + one confirmation
  3:   REDUCED SIZE (50%) -- edge present but thin
  4-7: FULL SIZE (100%) -- CVD + trend = the core edge, trade it
  8-11: ENHANCED SIZE (150%) -- everything aligned, size up

Paul Tudor Jones: "Risk/reward: don't take a trade unless potential reward
is at least 3x the risk." High confluence = higher expected R:R.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, List

logger = logging.getLogger('confluence_scorer')


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ConfluenceFactor:
    """A single confluence factor contributing to the trade score."""
    name: str
    points: int          # Points awarded (0 if not present)
    max_points: int      # Maximum possible points
    present: bool        # Whether this factor is confirmed
    detail: str = ""     # Human-readable detail for logging/analysis


@dataclass
class ConfluenceScore:
    """Complete confluence assessment for a potential trade."""
    symbol: str
    direction: str            # 'long' or 'short'
    total_score: int          # Sum of all factor points (0-11)
    max_possible: int         # Maximum possible score (11)
    factors: List[ConfluenceFactor] = field(default_factory=list)
    size_multiplier: float = 0.0   # Computed from score bands
    should_trade: bool = False      # True if score >= 4
    band: str = ""                  # 'skip', 'reduced', 'full', 'enhanced'

    def to_log_string(self):
        """One-line summary for logging."""
        factors_str = ", ".join(
            f"{f.name}={'Y' if f.present else 'N'}({f.points}/{f.max_points})"
            for f in self.factors
        )
        return (
            f"CONFLUENCE [{self.symbol} {self.direction.upper()}]: "
            f"{self.total_score}/{self.max_possible} ({self.band}) "
            f"-> {self.size_multiplier:.0%} size | {factors_str}"
        )

    def to_dict(self):
        """Dict representation for ML training data collection."""
        result = {
            'symbol': self.symbol,
            'direction': self.direction,
            'total_score': self.total_score,
            'max_possible': self.max_possible,
            'size_multiplier': self.size_multiplier,
            'should_trade': self.should_trade,
            'band': self.band,
        }
        for f in self.factors:
            result[f'factor_{f.name}'] = f.present
            result[f'factor_{f.name}_points'] = f.points
        return result


# ---------------------------------------------------------------------------
# Score bands (Livermore: "feeling-out bets" -- start small, scale up with
# confirmation)
# ---------------------------------------------------------------------------

SCORE_BANDS = {
    'skip':     {'min': 0, 'max': 2, 'size_mult': 0.0},
    'reduced':  {'min': 3, 'max': 3, 'size_mult': 0.5},
    'full':     {'min': 4, 'max': 7, 'size_mult': 1.0},
    'enhanced': {'min': 8, 'max': 11, 'size_mult': 1.5},
}

MAX_POSSIBLE_SCORE = 11


# ---------------------------------------------------------------------------
# Individual factor evaluators
# ---------------------------------------------------------------------------

def _evaluate_htf_bias(direction: str, htf_bias: Optional[str]) -> ConfluenceFactor:
    """HTF bias alignment (2 points).

    ICT principle: never trade against higher-timeframe structure.
    Long trades need bullish HTF bias, short trades need bearish.

    If htf_bias is None (data not available), factor scores 0 but does not
    penalize -- fail-open design.
    """
    max_pts = 2

    if htf_bias is None:
        return ConfluenceFactor(
            name='htf_bias', points=0, max_points=max_pts,
            present=False, detail='HTF bias data not available',
        )

    htf_bias_lower = htf_bias.lower()
    aligned = (
        (direction == 'long' and htf_bias_lower == 'bullish') or
        (direction == 'short' and htf_bias_lower == 'bearish')
    )

    if aligned:
        return ConfluenceFactor(
            name='htf_bias', points=max_pts, max_points=max_pts,
            present=True, detail=f'HTF bias {htf_bias} aligns with {direction}',
        )

    # Neutral counts as not-present but not opposing
    return ConfluenceFactor(
        name='htf_bias', points=0, max_points=max_pts,
        present=False,
        detail=f'HTF bias {htf_bias} does not align with {direction}',
    )


def _evaluate_liquidity_sweep(liquidity_sweep: Optional[bool]) -> ConfluenceFactor:
    """Liquidity sweep detection (2 points).

    ICT: A sweep of liquidity (stop hunt) before entry is one of the
    highest-probability institutional setups. Price sweeps stops below/above
    a swing point, then reverses -- that is the "smart money" entering.

    Placeholder: returns False until smc_detector is wired in.
    """
    max_pts = 2

    if liquidity_sweep is None:
        return ConfluenceFactor(
            name='liquidity_sweep', points=0, max_points=max_pts,
            present=False, detail='Liquidity sweep data not available',
        )

    if liquidity_sweep:
        return ConfluenceFactor(
            name='liquidity_sweep', points=max_pts, max_points=max_pts,
            present=True, detail='Liquidity sweep detected before entry',
        )

    return ConfluenceFactor(
        name='liquidity_sweep', points=0, max_points=max_pts,
        present=False, detail='No liquidity sweep detected',
    )


def _evaluate_cvd_divergence(cvd_divergence: Optional[bool]) -> ConfluenceFactor:
    """CVD divergence confirmation (2 points).

    Our own data validates this: CVD Lack of Participants is our best
    Forex strategy by win rate (46.3% WR, +0.273 PnL over 626 trades).
    When CVD divergence aligns with the entry, it is a strong confirmation
    that institutional order flow supports the trade direction.
    """
    max_pts = 2

    if cvd_divergence is None:
        return ConfluenceFactor(
            name='cvd_divergence', points=0, max_points=max_pts,
            present=False, detail='CVD divergence data not available',
        )

    if cvd_divergence:
        return ConfluenceFactor(
            name='cvd_divergence', points=max_pts, max_points=max_pts,
            present=True, detail='CVD divergence confirms direction',
        )

    return ConfluenceFactor(
        name='cvd_divergence', points=0, max_points=max_pts,
        present=False, detail='No CVD divergence confirmation',
    )


def _evaluate_kill_zone(kill_zone_active: Optional[bool]) -> ConfluenceFactor:
    """Kill zone timing (1 point).

    Research shows 30-50% larger pip range during kill zones (London open,
    NY open, London close). Trading within kill zones means more volume,
    tighter spreads, and faster price delivery to targets.

    Attempts to import from kill_zones module. If the module does not exist
    yet, gracefully returns False (fail-open).
    """
    max_pts = 1

    # If caller already evaluated, use their result
    if kill_zone_active is not None:
        if kill_zone_active:
            return ConfluenceFactor(
                name='kill_zone', points=max_pts, max_points=max_pts,
                present=True, detail='Currently in a kill zone session',
            )
        return ConfluenceFactor(
            name='kill_zone', points=0, max_points=max_pts,
            present=False, detail='Outside kill zone sessions',
        )

    # Try to auto-detect from kill_zones module
    try:
        from app.quant.indicators.kill_zones import is_in_kill_zone
        active = is_in_kill_zone()
        if active:
            return ConfluenceFactor(
                name='kill_zone', points=max_pts, max_points=max_pts,
                present=True, detail='Kill zone auto-detected as active',
            )
        return ConfluenceFactor(
            name='kill_zone', points=0, max_points=max_pts,
            present=False, detail='Kill zone auto-detected as inactive',
        )
    except (ImportError, Exception):
        # Module not built yet -- fail-open
        return ConfluenceFactor(
            name='kill_zone', points=0, max_points=max_pts,
            present=False, detail='Kill zone module not available',
        )


def _evaluate_fvg(fvg_present: Optional[bool]) -> ConfluenceFactor:
    """Fair Value Gap at entry level (1 point).

    ICT: An FVG represents an institutional imbalance -- a zone where
    price moved too fast for efficient price discovery. When price returns
    to fill the gap, it is a high-probability entry because institutions
    need to fill those orders.

    Placeholder: will be wired from smc_detector.
    """
    max_pts = 1

    if fvg_present is None:
        return ConfluenceFactor(
            name='fvg', points=0, max_points=max_pts,
            present=False, detail='FVG data not available',
        )

    if fvg_present:
        return ConfluenceFactor(
            name='fvg', points=max_pts, max_points=max_pts,
            present=True, detail='Fair Value Gap present at entry level',
        )

    return ConfluenceFactor(
        name='fvg', points=0, max_points=max_pts,
        present=False, detail='No Fair Value Gap at entry level',
    )


def _evaluate_order_block(order_block_at_entry: Optional[bool]) -> ConfluenceFactor:
    """Order Block at entry level (1 point).

    ICT: An Order Block is the origin point of an institutional move --
    the last opposing candle before a strong impulse. When price retests
    this zone, institutions are likely to defend it again.

    Placeholder: will be wired from smc_detector.
    """
    max_pts = 1

    if order_block_at_entry is None:
        return ConfluenceFactor(
            name='order_block', points=0, max_points=max_pts,
            present=False, detail='Order block data not available',
        )

    if order_block_at_entry:
        return ConfluenceFactor(
            name='order_block', points=max_pts, max_points=max_pts,
            present=True, detail='Order Block confirmed at entry level',
        )

    return ConfluenceFactor(
        name='order_block', points=0, max_points=max_pts,
        present=False, detail='No Order Block at entry level',
    )


def _evaluate_regime(
    regime_favorable: Optional[bool],
    strategy_name: Optional[str] = None,
) -> ConfluenceFactor:
    """Regime alignment (1 point).

    Uses the strategy orchestrator's size multiplier as a proxy for regime
    favorability. If the orchestrator sets multiplier >= 0.7, the regime
    is considered favorable (preferred or acceptable alignment).

    If caller passes regime_favorable directly, that takes precedence.
    Otherwise, auto-detect from orchestrator if strategy_name is provided.
    """
    max_pts = 1

    # Caller already evaluated
    if regime_favorable is not None:
        if regime_favorable:
            return ConfluenceFactor(
                name='regime', points=max_pts, max_points=max_pts,
                present=True, detail='Market regime supports strategy type',
            )
        return ConfluenceFactor(
            name='regime', points=0, max_points=max_pts,
            present=False, detail='Market regime does not favor strategy type',
        )

    # Auto-detect from strategy router (uses HMM regime)
    if strategy_name:
        try:
            from app.quant.algorithms.strategy_router import route_symbol
            # We need a symbol for routing — try to get it from context
            # If no symbol available, fall back to orchestrator
            pass  # Symbol not available here; rely on caller passing regime_favorable
        except Exception:
            pass

        try:
            from app.quant.strategy_orchestrator import get_orchestrator_size_multiplier
            orch_mult = get_orchestrator_size_multiplier(strategy_name)
            favorable = orch_mult >= 0.7
            return ConfluenceFactor(
                name='regime', points=max_pts if favorable else 0,
                max_points=max_pts, present=favorable,
                detail=f'Orchestrator size mult={orch_mult:.2f} '
                       f'({"favorable" if favorable else "unfavorable"})',
            )
        except (ImportError, Exception) as e:
            logger.debug(f"Regime auto-detect failed: {e}")

    return ConfluenceFactor(
        name='regime', points=0, max_points=max_pts,
        present=False, detail='Regime data not available',
    )


def _evaluate_displacement(displacement: Optional[bool]) -> ConfluenceFactor:
    """Displacement move detection (1 point).

    Research: 3+ consecutive strong candles in one direction (each closing
    near its extreme) indicates institutional commitment. Trading in the
    direction of displacement aligns with the "line of least resistance"
    (Livermore).

    Attempts to import from displacement module. If the module does not exist
    yet, gracefully returns False (fail-open).
    """
    max_pts = 1

    # Caller already evaluated
    if displacement is not None:
        if displacement:
            return ConfluenceFactor(
                name='displacement', points=max_pts, max_points=max_pts,
                present=True, detail='Displacement move detected',
            )
        return ConfluenceFactor(
            name='displacement', points=0, max_points=max_pts,
            present=False, detail='No displacement move detected',
        )

    # Try auto-detect
    try:
        from app.quant.indicators.displacement import is_displacement_active
        active = is_displacement_active()
        if active:
            return ConfluenceFactor(
                name='displacement', points=max_pts, max_points=max_pts,
                present=True, detail='Displacement auto-detected',
            )
        return ConfluenceFactor(
            name='displacement', points=0, max_points=max_pts,
            present=False, detail='Displacement auto-detected as absent',
        )
    except (ImportError, Exception):
        return ConfluenceFactor(
            name='displacement', points=0, max_points=max_pts,
            present=False, detail='Displacement module not available',
        )


# ---------------------------------------------------------------------------
# Score classification
# ---------------------------------------------------------------------------

def _classify_score(total_score: int) -> tuple:
    """Classify a total score into a band and size multiplier.

    Returns (band_name, size_multiplier, should_trade).
    """
    for band_name, band_def in SCORE_BANDS.items():
        if band_def['min'] <= total_score <= band_def['max']:
            should_trade = band_name != 'skip'
            return band_name, band_def['size_mult'], should_trade

    # Fallback (should never reach here with valid scores 0-11)
    return 'skip', 0.0, False


# ---------------------------------------------------------------------------
# Main scorer
# ---------------------------------------------------------------------------

def score_confluence(
    symbol: str,
    direction: str,
    # Individual factor inputs (each is Optional -- scorer handles missing data gracefully)
    htf_bias: Optional[str] = None,            # 'bullish', 'bearish', 'neutral'
    liquidity_sweep: Optional[bool] = None,     # True if sweep detected
    cvd_divergence: Optional[bool] = None,      # True if CVD confirms direction
    kill_zone_active: Optional[bool] = None,    # True if in a kill zone
    fvg_present: Optional[bool] = None,         # True if FVG at entry level
    order_block_at_entry: Optional[bool] = None,  # True if OB at entry level
    regime_favorable: Optional[bool] = None,    # True if HMM regime supports strategy
    displacement: Optional[bool] = None,        # True if displacement move detected
    # Optional context for auto-detection
    strategy_name: Optional[str] = None,        # For regime auto-detect from orchestrator
) -> ConfluenceScore:
    """Score a potential trade's confluence from 0 to 11.

    Missing factors (None) are scored as 0 points but don't count against.
    This allows progressive integration -- start with available factors,
    add more as modules are built.

    Bruce Kovner: "The best trades have multiple reasons."
    Mark Weinstein: "Use multiple confirmations."
    This function quantifies that wisdom into a single actionable number.

    Args:
        symbol: Trading pair (e.g., 'EURUSD')
        direction: 'long' or 'short'
        htf_bias: Higher-timeframe market structure direction
        liquidity_sweep: Whether a liquidity sweep was detected
        cvd_divergence: Whether CVD divergence confirms the direction
        kill_zone_active: Whether we are in a high-volume kill zone
        fvg_present: Whether a Fair Value Gap exists at entry level
        order_block_at_entry: Whether an Order Block exists at entry level
        regime_favorable: Whether the HMM regime supports the strategy type
        displacement: Whether a displacement move was detected
        strategy_name: Strategy name for auto-detecting regime from orchestrator

    Returns:
        ConfluenceScore with total score, band, size multiplier, and factor breakdown
    """
    # Normalize direction
    direction = direction.lower()
    if direction in ('buy', 'long'):
        direction = 'long'
    elif direction in ('sell', 'short'):
        direction = 'short'

    # Evaluate each factor independently
    factors = [
        _evaluate_htf_bias(direction, htf_bias),
        _evaluate_liquidity_sweep(liquidity_sweep),
        _evaluate_cvd_divergence(cvd_divergence),
        _evaluate_kill_zone(kill_zone_active),
        _evaluate_fvg(fvg_present),
        _evaluate_order_block(order_block_at_entry),
        _evaluate_regime(regime_favorable, strategy_name),
        _evaluate_displacement(displacement),
    ]

    # Sum the points
    total_score = sum(f.points for f in factors)

    # Classify into band
    band, size_multiplier, should_trade = _classify_score(total_score)

    return ConfluenceScore(
        symbol=symbol,
        direction=direction,
        total_score=total_score,
        max_possible=MAX_POSSIBLE_SCORE,
        factors=factors,
        size_multiplier=size_multiplier,
        should_trade=should_trade,
        band=band,
    )


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def get_size_multiplier_from_score(score: int) -> float:
    """Convert confluence score to position size multiplier.

    Returns: 0.0 (skip), 0.5 (reduced), 1.0 (full), or 1.5 (enhanced)
    """
    _, size_mult, _ = _classify_score(score)
    return size_mult


def log_confluence_decision(confluence: ConfluenceScore):
    """Log the confluence decision with full factor breakdown.

    Uses INFO for trades taken, DEBUG for skips (to avoid log spam
    from the many signals that don't pass the confluence threshold).
    """
    log_line = confluence.to_log_string()

    if confluence.should_trade:
        logger.info(log_line)

        # Log individual factor details at DEBUG for post-trade analysis
        for f in confluence.factors:
            logger.debug(
                f"  {f.name}: {'PRESENT' if f.present else 'absent'} "
                f"({f.points}/{f.max_points}) -- {f.detail}"
            )
    else:
        logger.debug(log_line)
