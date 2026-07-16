"""Multi-Timeframe Context Builder.

Combines structure analysis from H4, H1, M15, M5 into a unified
market context object. This is what a human trader does when they
"zoom out" to see the big picture, then "zoom in" for entry.

The context object answers:
- What's the higher timeframe trend? (H4/H1)
- Is the lower timeframe confirming or diverging? (M15/M5)
- Are there entry zones nearby? (FVGs, OBs on entry timeframe)
- What's the probability assessment? (alignment score 0-10)

Data flow:
  fetch_data_pos(symbol, TF, 100 bars) per timeframe
  -> market_structure.get_structure_summary() per timeframe
  -> zone_mapper.get_zone_summary() on entry timeframe (M15)
  -> combine into unified context dict

Design principles:
- **Fail-open** — returns neutral context on any error.
- **Stateless** — no side-effects, no caching (caller can cache).
- **DEBUG logging** — runs frequently in the entry pipeline.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from app.quant.indicators.market_structure import (
    get_structure_summary,
    get_trend_phase,
)
from app.quant.indicators.zone_mapper import (
    check_zone_proximity,
    find_fvgs,
    find_order_blocks,
    get_zone_summary,
    FVGZone,
    OrderBlockZone,
    _calc_atr,
)

logger = logging.getLogger('mtf_context')


# ---------------------------------------------------------------------------
# Timeframe config
# ---------------------------------------------------------------------------

# Timeframe hierarchy: HTF (bias) -> LTF (entry)
TIMEFRAMES = {
    'H4': {'role': 'htf', 'lookback': 5},
    'H1': {'role': 'htf', 'lookback': 5},
    'M15': {'role': 'ltf', 'lookback': 5},
    'M5': {'role': 'ltf', 'lookback': 3},   # Smaller lookback for faster TF
}

BARS_PER_TF = 100  # Well within MT5's 10K limit


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_tf_data(symbol: str, timeframe_str: str, fetch_fn=None) -> Optional[pd.DataFrame]:
    """Fetch OHLCV data for a single timeframe.

    Parameters
    ----------
    symbol : str
        Trading pair (e.g. 'XAGUSD').
    timeframe_str : str
        One of 'H4', 'H1', 'M15', 'M5'.
    fetch_fn : callable, optional
        Override for testing.  Signature: ``fn(symbol, tf_enum, bars) -> DataFrame``.

    Returns
    -------
    DataFrame or None on failure.
    """
    try:
        from app.utils.constants import MT5Timeframe

        tf_map = {
            'H4': MT5Timeframe.H4,
            'H1': MT5Timeframe.H1,
            'M15': MT5Timeframe.M15,
            'M5': MT5Timeframe.M5,
        }

        tf_enum = tf_map.get(timeframe_str)
        if tf_enum is None:
            logger.debug("Unknown timeframe: %s", timeframe_str)
            return None

        if fetch_fn is None:
            from app.utils.api.data import fetch_data_pos_cached
            fetch_fn = fetch_data_pos_cached

        df = fetch_fn(symbol, tf_enum, BARS_PER_TF)
        if df is None or len(df) == 0:
            logger.debug("No data for %s %s", symbol, timeframe_str)
            return None

        return df

    except Exception:
        logger.exception("Failed to fetch %s %s", symbol, timeframe_str)
        return None


def _consensus_trend(trend_a: str, trend_b: str) -> str:
    """Determine consensus trend from two timeframes.

    If both agree, return the trend. If they disagree, return the
    higher-timeframe (first argument) trend since it carries more weight.
    If one is RANGE, defer to the other.
    """
    if trend_a == trend_b:
        return trend_a

    # REVERSAL dominates — it's the most urgent signal
    if trend_a == 'REVERSAL' or trend_b == 'REVERSAL':
        return 'REVERSAL'

    # If one is RANGE, defer to the other
    if trend_a == 'RANGE':
        return trend_b
    if trend_b == 'RANGE':
        return trend_a

    # Conflicting trends — HTF wins
    return trend_a


def _determine_alignment(htf_trend: str, ltf_trend: str) -> str:
    """Determine how HTF and LTF trends align.

    Returns
    -------
    str
        'ALIGNED'   — both point same direction
        'DIVERGING' — LTF is moving against HTF (correction)
        'NEUTRAL'   — at least one is RANGE or unknown
    """
    uptrends = {'UPTREND'}
    downtrends = {'DOWNTREND'}

    if htf_trend in uptrends and ltf_trend in uptrends:
        return 'ALIGNED'
    if htf_trend in downtrends and ltf_trend in downtrends:
        return 'ALIGNED'

    if htf_trend in uptrends and ltf_trend in downtrends:
        return 'DIVERGING'
    if htf_trend in downtrends and ltf_trend in uptrends:
        return 'DIVERGING'

    return 'NEUTRAL'


def _compute_alignment_score(
    htf_trend: str,
    ltf_trend: str,
    alignment: str,
    htf_phase: str,
    ltf_phase: str,
    entry_zones_count: int,
    recent_breaks: List[Dict],
) -> int:
    """Compute 0-10 alignment score.

    Scoring breakdown:
    - HTF clear trend (not RANGE):      +3
    - HTF + LTF aligned:                +3
    - LTF in corrective phase (ideal):  +1
    - Entry zones available:             +1
    - Recent BOS in trend direction:     +1
    - No recent CHoCH against trend:     +1
    """
    score = 0

    # HTF has a clear trend
    if htf_trend in ('UPTREND', 'DOWNTREND'):
        score += 3

    # Alignment bonus
    if alignment == 'ALIGNED':
        score += 3
    elif alignment == 'NEUTRAL':
        score += 1

    # LTF correcting against HTF = ideal entry timing
    # (pullback in the direction of the trend)
    if alignment == 'DIVERGING' and ltf_phase in ('CORRECTION', 'REVERSAL'):
        score += 1

    # Entry zones present
    if entry_zones_count > 0:
        score += 1

    # Recent structure breaks
    if recent_breaks:
        htf_dir = 'bullish' if htf_trend == 'UPTREND' else 'bearish'
        aligned_bos = any(
            b.get('break_type') == 'BOS' and b.get('direction') == htf_dir
            for b in recent_breaks
        )
        against_choch = any(
            b.get('break_type') == 'CHoCH' and b.get('direction') != htf_dir
            for b in recent_breaks
        )

        if aligned_bos:
            score += 1
        if not against_choch:
            score += 1

    return min(score, 10)


def _trend_to_bias(trend: str) -> str:
    """Convert a trend phase string to a trade bias."""
    if trend == 'UPTREND':
        return 'LONG'
    elif trend == 'DOWNTREND':
        return 'SHORT'
    else:
        return 'NEUTRAL'


def _compute_confidence(alignment_score: int, alignment: str) -> float:
    """Derive a 0.0-1.0 confidence value from the alignment score."""
    base = alignment_score / 10.0

    # Alignment modifiers
    if alignment == 'ALIGNED':
        base = min(base + 0.1, 1.0)
    elif alignment == 'DIVERGING':
        base = max(base - 0.1, 0.0)

    return round(base, 2)


def _determine_phase(trend: str, alignment: str) -> str:
    """Determine the structural phase label.

    Maps our trend + alignment into ICT-style phase names:
    - IMPULSE:    trend is clear and LTF confirms
    - CORRECTION: LTF is moving against HTF temporarily
    - RANGE:      no clear structure
    - REVERSAL:   structure is breaking / CHoCH detected
    """
    if trend == 'REVERSAL':
        return 'REVERSAL'
    if trend == 'RANGE':
        return 'RANGE'
    if alignment == 'DIVERGING':
        return 'CORRECTION'
    return 'IMPULSE'


def _build_summary(context: Dict) -> str:
    """Build a human-readable one-liner summary of the MTF context."""
    parts = []

    # HTF trend
    htf = context.get('htf_trend', 'RANGE')
    htf_phase = context.get('htf_phase', '')
    parts.append(f"HTF {htf.lower()}")
    if htf_phase and htf_phase != htf:
        parts.append(f"({htf_phase.lower()})")

    # LTF
    ltf = context.get('ltf_trend', 'RANGE')
    alignment = context.get('alignment', 'NEUTRAL')
    if alignment == 'DIVERGING':
        parts.append(f", LTF correcting ({ltf.lower()})")
    elif alignment == 'ALIGNED':
        parts.append(f", LTF confirming ({ltf.lower()})")
    else:
        parts.append(f", LTF {ltf.lower()}")

    # Entry zones
    zones = context.get('entry_zones', [])
    if zones:
        fvg_count = sum(1 for z in zones if z.get('zone', {}).get('type') == 'FVG')
        ob_count = sum(1 for z in zones if z.get('zone', {}).get('type') == 'OB')
        zone_parts = []
        if fvg_count:
            zone_parts.append(f"{fvg_count} FVG")
        if ob_count:
            zone_parts.append(f"{ob_count} OB")
        if zone_parts:
            parts.append(f". {'+'.join(zone_parts)} nearby")

    # Bias
    bias = context.get('bias', 'NEUTRAL')
    score = context.get('alignment_score', 0)
    conf = context.get('confidence', 0)
    parts.append(f". Bias: {bias} (score {score}/10, conf {conf:.0%})")

    return ''.join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_mtf_context(symbol: str, fetch_fn=None) -> Dict:
    """Build complete multi-timeframe context for a symbol.

    Fetches H4, H1, M15, M5 data from MT5 and analyzes structure on each.
    This is the main entry point for the MTF structure reader.

    Parameters
    ----------
    symbol : str
        Trading pair (e.g. 'XAGUSD', 'EURUSD').
    fetch_fn : callable, optional
        Override for the data fetch function (for testing).
        Signature: ``fn(symbol, tf_enum, bars) -> DataFrame``.

    Returns
    -------
    dict
        {
            'symbol': str,
            'timestamp': datetime,
            'htf_trend': str,       # UPTREND, DOWNTREND, RANGE, REVERSAL
            'htf_phase': str,       # IMPULSE, CORRECTION, RANGE, REVERSAL
            'ltf_trend': str,
            'ltf_phase': str,
            'alignment': str,       # ALIGNED, DIVERGING, NEUTRAL
            'alignment_score': int, # 0-10
            'entry_zones': list,    # FVGs and OBs near current price on M15
            'structure_breaks': list,  # Recent BOS/CHoCH per timeframe
            'bias': str,            # LONG, SHORT, NEUTRAL
            'confidence': float,    # 0.0-1.0
            'summary': str,         # Human-readable one-liner
            'timeframe_detail': dict,  # Per-TF structure summaries
        }
    """
    empty_context = {
        'symbol': symbol,
        'timestamp': datetime.utcnow(),
        'htf_trend': 'RANGE',
        'htf_phase': 'RANGE',
        'ltf_trend': 'RANGE',
        'ltf_phase': 'RANGE',
        'alignment': 'NEUTRAL',
        'alignment_score': 0,
        'entry_zones': [],
        'structure_breaks': [],
        'bias': 'NEUTRAL',
        'confidence': 0.0,
        'summary': f'{symbol}: insufficient data for MTF analysis',
        'timeframe_detail': {},
    }

    try:
        # --- Fetch data for all timeframes ---
        tf_data: Dict[str, Optional[pd.DataFrame]] = {}
        for tf_name in TIMEFRAMES:
            tf_data[tf_name] = _fetch_tf_data(symbol, tf_name, fetch_fn=fetch_fn)

        # Need at least one HTF and one LTF for meaningful analysis
        has_htf = tf_data.get('H4') is not None or tf_data.get('H1') is not None
        has_ltf = tf_data.get('M15') is not None or tf_data.get('M5') is not None

        if not has_htf and not has_ltf:
            logger.debug("build_mtf_context(%s): no data available", symbol)
            return empty_context

        # --- Analyze structure on each timeframe ---
        tf_structures: Dict[str, Dict] = {}
        tf_trends: Dict[str, str] = {}

        for tf_name, config in TIMEFRAMES.items():
            df = tf_data.get(tf_name)
            if df is None or len(df) < 15:
                tf_structures[tf_name] = {}
                tf_trends[tf_name] = 'RANGE'
                continue

            lookback = config['lookback']
            structure = get_structure_summary(df, lookback=lookback)
            tf_structures[tf_name] = structure
            tf_trends[tf_name] = structure.get('trend_phase', 'RANGE')

        # --- Determine HTF consensus (H4 primary, H1 secondary) ---
        h4_trend = tf_trends.get('H4', 'RANGE')
        h1_trend = tf_trends.get('H1', 'RANGE')
        htf_trend = _consensus_trend(h4_trend, h1_trend)

        # --- Determine LTF trend (M15 primary, M5 secondary) ---
        m15_trend = tf_trends.get('M15', 'RANGE')
        m5_trend = tf_trends.get('M5', 'RANGE')
        ltf_trend = _consensus_trend(m15_trend, m5_trend)

        # --- Alignment analysis ---
        alignment = _determine_alignment(htf_trend, ltf_trend)
        htf_phase = _determine_phase(htf_trend, alignment)
        ltf_phase = _determine_phase(ltf_trend, alignment)

        # --- Entry zones: FVGs and OBs on M15 near current price ---
        entry_zones: List[Dict] = []
        m15_df = tf_data.get('M15')
        if m15_df is not None and len(m15_df) >= 5:
            current_price = float(m15_df['close'].iloc[-1])
            atr = _calc_atr(m15_df)

            # Get raw FVG and OB objects for proximity check
            fvgs = find_fvgs(m15_df)
            obs = find_order_blocks(m15_df)

            # Filter to active zones only
            active_fvgs = [f for f in fvgs if not f.filled]
            active_obs = [o for o in obs if not o.mitigated]

            # Further filter: only zones aligned with HTF bias
            htf_dir = 'bullish' if htf_trend == 'UPTREND' else (
                'bearish' if htf_trend == 'DOWNTREND' else None
            )
            if htf_dir:
                aligned_fvgs = [f for f in active_fvgs if f.direction == htf_dir]
                aligned_obs = [o for o in active_obs if o.direction == htf_dir]
            else:
                aligned_fvgs = active_fvgs
                aligned_obs = active_obs

            # Check proximity (within 1.0 ATR)
            all_zones = list(aligned_fvgs) + list(aligned_obs)
            if all_zones and atr > 0:
                entry_zones = check_zone_proximity(
                    current_price, all_zones, atr, threshold_atr=1.0
                )

        # --- Collect all recent structure breaks across timeframes ---
        all_breaks: List[Dict] = []
        for tf_name, structure in tf_structures.items():
            for brk in structure.get('structure_breaks', []):
                brk_copy = dict(brk)
                brk_copy['timeframe'] = tf_name
                all_breaks.append(brk_copy)

        # --- Compute alignment score ---
        alignment_score = _compute_alignment_score(
            htf_trend=htf_trend,
            ltf_trend=ltf_trend,
            alignment=alignment,
            htf_phase=htf_phase,
            ltf_phase=ltf_phase,
            entry_zones_count=len(entry_zones),
            recent_breaks=all_breaks,
        )

        # --- Derive bias and confidence ---
        bias = _trend_to_bias(htf_trend)
        confidence = _compute_confidence(alignment_score, alignment)

        # --- Build context ---
        context = {
            'symbol': symbol,
            'timestamp': datetime.utcnow(),
            'htf_trend': htf_trend,
            'htf_phase': htf_phase,
            'ltf_trend': ltf_trend,
            'ltf_phase': ltf_phase,
            'alignment': alignment,
            'alignment_score': alignment_score,
            'entry_zones': entry_zones,
            'structure_breaks': all_breaks,
            'bias': bias,
            'confidence': confidence,
            'summary': '',  # Filled below
            'timeframe_detail': {
                tf_name: {
                    'trend': tf_trends.get(tf_name, 'RANGE'),
                    'swing_count': structure.get('swing_count', 0),
                    'last_swing_high': structure.get('last_swing_high'),
                    'last_swing_low': structure.get('last_swing_low'),
                    'break_count': len(structure.get('structure_breaks', [])),
                }
                for tf_name, structure in tf_structures.items()
            },
        }

        context['summary'] = _build_summary(context)

        logger.debug(
            "build_mtf_context(%s): %s — score %d/10, conf %.0f%%, zones=%d",
            symbol, context['summary'][:80], alignment_score,
            confidence * 100, len(entry_zones),
        )

        return context

    except Exception:
        logger.exception("build_mtf_context failed for %s", symbol)
        return empty_context
