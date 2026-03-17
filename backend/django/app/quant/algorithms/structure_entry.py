"""Autonomous Structure-Based Entry Generator.

Scans multiple timeframes for trade setups WITHOUT waiting for CVD signals.
Generates entries like a human trader would:

1. Read HTF trend (H1/H4) -- what direction should we trade?
2. Wait for LTF correction (M15) -- price pulling back against trend
3. Find entry zone (M15/M5) -- FVG, OB, or structure level where price is likely to react
4. Confirm entry (M5) -- CHoCH or BOS confirming the pullback is over
5. Set structural SL/TP -- SL behind the correction, TP at next structure target

This replaces the CVD-dependent entry pipeline for the autonomous brain.
Runs ALONGSIDE CVD entry -- both can generate entries independently.

Data flow:
  build_mtf_context(symbol)
  -> classify_setup_type()
  -> find_entry_zone()
  -> confirm_ltf_entry()
  -> calculate structure SL/TP via get_structure_levels()
  -> check VWAP, orderbook, news, graph advisor
  -> return signal dict

Design principles:
- **Fail-open** -- returns empty list on any error (never crashes the scanner).
- **Stateless** -- no side-effects (caller decides whether to execute).
- **Anti-churn** -- won't signal same symbol within 60s of a recent trade.
- **Rate-limited** -- max 3 signals per scan cycle.
- **INFO logging** for signals, DEBUG for skips.
"""

import logging
import time as _time_mod
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger('structure_entry')

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_SYMBOLS = [
    'XAGUSD', 'XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY',
    'AUDUSD', 'NZDUSD', 'USDCAD', 'USOUSD', 'UKOUSDft',
]

# Minimum MTF confidence to consider a symbol (0.0-1.0).
# Below this, the market picture is too unclear for an autonomous entry.
MIN_MTF_CONFIDENCE = 0.3

# Minimum alignment score (0-10) from MTF context builder.
MIN_ALIGNMENT_SCORE = 4

# Minimum R:R for all setups -- non-negotiable.
MIN_RR_RATIO = 2.0

# Maximum number of signals per scan cycle to avoid overloading.
MAX_SIGNALS_PER_CYCLE = 3

# Anti-churn: seconds since last trade on the same symbol.
ANTI_CHURN_SECONDS = 60

# Reversal setup requires higher confluence.
REVERSAL_MIN_ALIGNMENT = 7

# ATR-based proximity: how close price must be to an entry zone (in ATR multiples).
ZONE_PROXIMITY_ATR = 1.0

# Global position limit.
GLOBAL_MAX_POSITIONS = 20

# Risk per trade (EUR, matches CVD config).
DEFAULT_TARGET_RISK = 50.0

# Zone age: ignore FVGs/OBs older than this many bars on M15.
MAX_ZONE_AGE_BARS = 40

# Setup types with their base confidence adjustments.
SETUP_CONFIDENCE = {
    'TREND_CONTINUATION': 0.10,   # Best probability -- bonus
    'BREAKOUT': 0.00,             # Neutral
    'REVERSAL': -0.10,            # Harder to trade -- penalty
    'RANGE_FADE': -0.05,          # Moderate difficulty
}


# ---------------------------------------------------------------------------
# Setup type classification
# ---------------------------------------------------------------------------

def classify_setup_type(
    htf_trend: str,
    ltf_trend: str,
    alignment: str,
    htf_phase: str,
    ltf_phase: str,
    structure_breaks: List[Dict],
) -> Optional[str]:
    """Classify the current market state into one of four setup types.

    Parameters
    ----------
    htf_trend : str
        Higher-timeframe trend: UPTREND, DOWNTREND, RANGE, REVERSAL.
    ltf_trend : str
        Lower-timeframe trend.
    alignment : str
        ALIGNED, DIVERGING, NEUTRAL.
    htf_phase : str
        IMPULSE, CORRECTION, RANGE, REVERSAL.
    ltf_phase : str
        IMPULSE, CORRECTION, RANGE, REVERSAL.
    structure_breaks : list[dict]
        Recent BOS/CHoCH across all timeframes.

    Returns
    -------
    str or None
        'TREND_CONTINUATION', 'BREAKOUT', 'REVERSAL', 'RANGE_FADE', or
        None if no classifiable setup is detected.
    """
    try:
        # 1. TREND_CONTINUATION: HTF trending, LTF correcting or re-aligning
        if htf_trend in ('UPTREND', 'DOWNTREND'):
            # LTF was correcting and is now re-aligning (best case)
            if alignment == 'DIVERGING' or ltf_phase == 'CORRECTION':
                return 'TREND_CONTINUATION'
            # LTF is aligned with HTF (already in impulse -- still good)
            if alignment == 'ALIGNED':
                return 'TREND_CONTINUATION'

        # 2. BREAKOUT: HTF was RANGE, now showing a BOS
        if htf_trend == 'RANGE':
            # Check for recent BOS on H1/H4 timeframes
            htf_bos = [
                b for b in structure_breaks
                if b.get('break_type') == 'BOS'
                and b.get('timeframe') in ('H1', 'H4')
            ]
            if htf_bos:
                return 'BREAKOUT'

        # 3. REVERSAL: HTF showing CHoCH after extended trend
        if htf_trend == 'REVERSAL' or htf_phase == 'REVERSAL':
            # Need LTF confirmation of the new direction
            ltf_choch = [
                b for b in structure_breaks
                if b.get('break_type') == 'CHoCH'
                and b.get('timeframe') in ('M15', 'M5')
            ]
            if ltf_choch:
                return 'REVERSAL'

        # 4. RANGE_FADE: HTF ranging, price at range extremes
        # (Zone proximity is checked separately -- here we just classify)
        if htf_trend == 'RANGE' and ltf_trend in ('UPTREND', 'DOWNTREND'):
            # LTF is pushing to a range boundary
            return 'RANGE_FADE'

        return None

    except Exception:
        logger.exception("classify_setup_type failed")
        return None


# ---------------------------------------------------------------------------
# Direction determination
# ---------------------------------------------------------------------------

def determine_direction(
    setup_type: str,
    htf_trend: str,
    bias: str,
    structure_breaks: List[Dict],
    ltf_trend: str = 'RANGE',
) -> Optional[str]:
    """Determine trade direction (BUY or SELL) from the setup.

    Parameters
    ----------
    setup_type : str
        One of the four classified setup types.
    htf_trend : str
        UPTREND, DOWNTREND, RANGE, REVERSAL.
    bias : str
        LONG, SHORT, NEUTRAL from MTF context.
    structure_breaks : list[dict]
        Recent breaks to detect breakout/reversal direction.
    ltf_trend : str
        Lower-timeframe trend for RANGE_FADE direction.

    Returns
    -------
    str or None
        'BUY', 'SELL', or None if direction cannot be determined.
    """
    try:
        if setup_type == 'TREND_CONTINUATION':
            if htf_trend == 'UPTREND':
                return 'BUY'
            elif htf_trend == 'DOWNTREND':
                return 'SELL'

        elif setup_type == 'BREAKOUT':
            # Direction from the most recent HTF BOS
            htf_bos = [
                b for b in structure_breaks
                if b.get('break_type') == 'BOS'
                and b.get('timeframe') in ('H1', 'H4')
            ]
            if htf_bos:
                last_bos = htf_bos[-1]
                if last_bos.get('direction') == 'bullish':
                    return 'BUY'
                elif last_bos.get('direction') == 'bearish':
                    return 'SELL'

        elif setup_type == 'REVERSAL':
            # Direction from the most recent CHoCH (opposing previous trend)
            ltf_choch = [
                b for b in structure_breaks
                if b.get('break_type') == 'CHoCH'
                and b.get('timeframe') in ('M15', 'M5')
            ]
            if ltf_choch:
                last_choch = ltf_choch[-1]
                if last_choch.get('direction') == 'bullish':
                    return 'BUY'
                elif last_choch.get('direction') == 'bearish':
                    return 'SELL'

        elif setup_type == 'RANGE_FADE':
            # Fade the LTF push -- if LTF is pushing up at range top, sell.
            # if LTF is pushing down at range bottom, buy.
            # The MTF bias helps here.
            if bias == 'LONG':
                return 'BUY'
            elif bias == 'SHORT':
                return 'SELL'
            else:
                # Use LTF trend as a fade: trending up at resistance = sell
                if ltf_trend == 'UPTREND':
                    return 'SELL'
                elif ltf_trend == 'DOWNTREND':
                    return 'BUY'

        return None

    except Exception:
        logger.exception("determine_direction failed")
        return None


# ---------------------------------------------------------------------------
# Entry zone validation
# ---------------------------------------------------------------------------

def find_best_entry_zone(
    entry_zones: List[Dict],
    direction: str,
    current_price: float,
    max_age_bars: int = MAX_ZONE_AGE_BARS,
    total_bars: int = 100,
) -> Optional[Dict]:
    """Find the best entry zone aligned with the trade direction.

    Picks the closest, freshest zone that aligns with the direction.

    Parameters
    ----------
    entry_zones : list[dict]
        From ``build_mtf_context``'s ``entry_zones`` field. Each has
        ``{'zone': {...}, 'distance': float, 'distance_atr': float, 'price_in_zone': bool}``.
    direction : str
        'BUY' or 'SELL'.
    current_price : float
        Current market price.
    max_age_bars : int
        Maximum bar_index age for the zone to be considered fresh.
    total_bars : int
        Total bars in the dataset (for age calculation).

    Returns
    -------
    dict or None
        The best matching zone entry from the list, or None.
    """
    try:
        if not entry_zones:
            return None

        # Determine which zone directions we want.
        # For BUY: we want bullish zones (demand) -- price pulling back into demand.
        # For SELL: we want bearish zones (supply) -- price rallying into supply.
        wanted_direction = 'bullish' if direction == 'BUY' else 'bearish'

        candidates = []
        for ez in entry_zones:
            zone = ez.get('zone', {})
            zone_dir = zone.get('direction', '')

            if zone_dir != wanted_direction:
                continue

            # Check zone age (bar_index relative to total bars)
            bar_idx = zone.get('bar_index', 0)
            age = total_bars - bar_idx
            if age > max_age_bars:
                continue

            # Prefer zones where price is actually inside or very close
            candidates.append({
                **ez,
                'age': age,
            })

        if not candidates:
            return None

        # Sort: price_in_zone first, then by distance (closest)
        candidates.sort(key=lambda c: (
            not c.get('price_in_zone', False),
            c.get('distance', float('inf')),
        ))

        return candidates[0]

    except Exception:
        logger.exception("find_best_entry_zone failed")
        return None


# ---------------------------------------------------------------------------
# LTF confirmation check
# ---------------------------------------------------------------------------

def check_ltf_confirmation(
    structure_breaks: List[Dict],
    direction: str,
    setup_type: str,
) -> Tuple[bool, str]:
    """Check if LTF (M5/M15) confirms the entry with a structure break.

    For TREND_CONTINUATION: need BOS in trade direction on M5/M15.
    For BREAKOUT: need BOS in trade direction on M15.
    For REVERSAL: need CHoCH in trade direction on M15/M5.
    For RANGE_FADE: need any rejection pattern (CHoCH against LTF push).

    Parameters
    ----------
    structure_breaks : list[dict]
        All recent structure breaks across timeframes.
    direction : str
        'BUY' or 'SELL'.
    setup_type : str
        One of the four setup types.

    Returns
    -------
    tuple[bool, str]
        (confirmed, reason)
    """
    try:
        break_dir = 'bullish' if direction == 'BUY' else 'bearish'
        fade_dir = 'bearish' if direction == 'BUY' else 'bullish'

        ltf_breaks = [
            b for b in structure_breaks
            if b.get('timeframe') in ('M5', 'M15')
        ]

        if setup_type == 'TREND_CONTINUATION':
            # Need BOS confirming the pullback is over
            aligned_bos = [
                b for b in ltf_breaks
                if b.get('break_type') == 'BOS'
                and b.get('direction') == break_dir
            ]
            if aligned_bos:
                return True, f"M5/M15 BOS {break_dir} confirms correction is over"

            # Also accept CHoCH back in trend direction (pullback reversal)
            aligned_choch = [
                b for b in ltf_breaks
                if b.get('break_type') == 'CHoCH'
                and b.get('direction') == break_dir
            ]
            if aligned_choch:
                return True, f"M5/M15 CHoCH {break_dir} confirms pullback reversal"

        elif setup_type == 'BREAKOUT':
            # Need BOS on LTF confirming the break
            aligned_bos = [
                b for b in ltf_breaks
                if b.get('break_type') == 'BOS'
                and b.get('direction') == break_dir
            ]
            if aligned_bos:
                return True, f"M15 BOS {break_dir} confirms breakout"

        elif setup_type == 'REVERSAL':
            # Need CHoCH on LTF in the new direction
            aligned_choch = [
                b for b in ltf_breaks
                if b.get('break_type') == 'CHoCH'
                and b.get('direction') == break_dir
            ]
            if aligned_choch:
                return True, f"M5/M15 CHoCH {break_dir} confirms reversal"

        elif setup_type == 'RANGE_FADE':
            # Need rejection -- CHoCH against the push or BOS in fade direction
            rejection = [
                b for b in ltf_breaks
                if b.get('direction') == break_dir
            ]
            if rejection:
                return True, f"M5/M15 rejection pattern confirms range fade"

        return False, "No LTF confirmation found"

    except Exception:
        logger.exception("check_ltf_confirmation failed")
        return False, "LTF confirmation check error"


# ---------------------------------------------------------------------------
# VWAP alignment check
# ---------------------------------------------------------------------------

def check_vwap_alignment(symbol: str, direction: str) -> Dict:
    """Check VWAP alignment for the proposed direction.

    Returns dict with 'aligned' bool and 'bias' string.
    """
    try:
        from app.utils.api.data import fetch_data_pos_cached
        from app.utils.constants import MT5Timeframe
        from app.quant.indicators.vwap import get_vwap_bias

        df = fetch_data_pos_cached(symbol, MT5Timeframe.M15, 100)
        if df is None or len(df) < 10:
            return {'aligned': True, 'bias': 'NEUTRAL', 'distance_pct': 0}

        vwap_info = get_vwap_bias(df)
        vwap_bias = vwap_info.get('bias', 'NEUTRAL')

        aligned = True
        if direction == 'BUY' and vwap_bias == 'BEARISH':
            aligned = False
        elif direction == 'SELL' and vwap_bias == 'BULLISH':
            aligned = False

        return {
            'aligned': aligned,
            'bias': vwap_bias,
            'distance_pct': vwap_info.get('distance_pct', 0),
        }

    except Exception as e:
        logger.debug("VWAP check failed for %s: %s", symbol, e)
        return {'aligned': True, 'bias': 'NEUTRAL', 'distance_pct': 0}


# ---------------------------------------------------------------------------
# Orderbook alignment check
# ---------------------------------------------------------------------------

def check_orderbook_alignment(symbol: str, direction: str) -> Dict:
    """Check orderbook bias alignment for the proposed direction.

    Returns dict with 'aligned' bool, 'bias' string, 'imbalance' float.
    """
    try:
        from app.utils.api.orderbook import get_orderbook_bias

        ob_info = get_orderbook_bias(symbol)
        ob_bias = ob_info.get('bias', 'NEUTRAL')

        aligned = True
        if direction == 'BUY' and ob_bias == 'BEARISH':
            aligned = False
        elif direction == 'SELL' and ob_bias == 'BULLISH':
            aligned = False

        return {
            'aligned': aligned,
            'bias': ob_bias,
            'imbalance': ob_info.get('imbalance', 0),
        }

    except Exception as e:
        logger.debug("Orderbook check failed for %s: %s", symbol, e)
        return {'aligned': True, 'bias': 'NEUTRAL', 'imbalance': 0}


# ---------------------------------------------------------------------------
# Graph advisor consultation
# ---------------------------------------------------------------------------

def consult_graph_advisor(
    symbol: str,
    direction: str,
    setup_type: str,
    regime: str = 'UNKNOWN',
    confluence_score: int = 0,
) -> Dict:
    """Consult Neo4j knowledge graph for historical confidence.

    Returns advice dict with confidence, size_modifier, recommendation.
    """
    try:
        from app.quant.knowledge.advisor import get_trade_advice

        advice = get_trade_advice(
            symbol=symbol,
            direction=direction,
            strategy=f'STRUCTURE_{setup_type}',
            regime=regime,
            confluence_score=confluence_score,
        )
        return advice

    except Exception as e:
        logger.debug("Graph advisor failed for %s: %s", symbol, e)
        return {
            'confidence': 0.5,
            'size_modifier': 1.0,
            'recommendation': 'NORMAL',
            'reasoning': 'Graph advisor unavailable',
        }


# ---------------------------------------------------------------------------
# Anti-churn check
# ---------------------------------------------------------------------------

def check_anti_churn(symbol: str) -> bool:
    """Check if enough time has passed since the last trade on this symbol.

    Returns True if the symbol is clear to trade (no recent trade).
    """
    try:
        from app.nexus.models import Trade

        cutoff = datetime.now() - timedelta(seconds=ANTI_CHURN_SECONDS)
        recent = Trade.objects.filter(
            symbol=symbol,
            entry_time__gte=cutoff,
        ).exists()

        if recent:
            logger.debug("Anti-churn: %s traded within %ds, skipping", symbol, ANTI_CHURN_SECONDS)
            return False

        return True

    except Exception as e:
        logger.debug("Anti-churn check failed for %s: %s", symbol, e)
        return True  # Fail-open


# ---------------------------------------------------------------------------
# Build reasoning string
# ---------------------------------------------------------------------------

def build_reasoning(
    setup_type: str,
    htf_trend: str,
    ltf_phase: str,
    entry_zone_type: str,
    ltf_confirmation: str,
    vwap_bias: str,
    ob_bias: str,
) -> str:
    """Build a human-readable reasoning string for the signal."""
    parts = []

    htf_desc = htf_trend.lower().replace('_', ' ')
    parts.append(f"H1 {htf_desc}")

    if ltf_phase:
        parts.append(f"M15 {ltf_phase.lower()}")

    if entry_zone_type:
        parts.append(f"entry at {entry_zone_type}")

    if ltf_confirmation:
        parts.append(ltf_confirmation)

    extras = []
    if vwap_bias != 'NEUTRAL':
        extras.append(f"VWAP {vwap_bias.lower()}")
    if ob_bias != 'NEUTRAL':
        extras.append(f"DOM {ob_bias.lower()}")

    if extras:
        parts.append(f"[{', '.join(extras)}]")

    return ', '.join(parts)


# ---------------------------------------------------------------------------
# Main scanner
# ---------------------------------------------------------------------------

def scan_for_entries(symbols: List[str] = None) -> List[Dict]:
    """Scan all symbols for autonomous structure-based entry setups.

    This is the main public function. For each symbol:
    1. Build MTF context (H4, H1, M15, M5).
    2. Classify the setup type.
    3. Determine trade direction.
    4. Find and validate entry zones.
    5. Confirm with LTF structure breaks.
    6. Calculate structure-based SL/TP.
    7. Check VWAP, orderbook, news, graph advisor.
    8. Return the entry signal if all conditions are met.

    Parameters
    ----------
    symbols : list[str] or None
        Symbols to scan. Defaults to DEFAULT_SYMBOLS.

    Returns
    -------
    list[dict]
        Entry signals. Each signal contains:
        {
            'symbol': str,
            'direction': str,          # 'BUY' or 'SELL'
            'entry_price': float,
            'sl_price': float,
            'tp_price': float,
            'rr_ratio': float,
            'confidence': float,       # 0.0-1.0
            'setup_type': str,         # TREND_CONTINUATION, BREAKOUT, REVERSAL, RANGE_FADE
            'reasoning': str,
            'htf_trend': str,
            'ltf_phase': str,
            'entry_zone': str,         # 'FVG', 'OB', or 'STRUCTURE'
            'mtf_alignment_score': int,
            'news_size_mult': float,   # Sizing multiplier from news risk
            'graph_confidence': float,
            'graph_size_mult': float,
            'vwap_aligned': bool,
            'ob_aligned': bool,
            'sl_source': str,          # 'STRUCTURE' or 'ATR_FALLBACK'
            'tp_source': str,
        }
    """
    if symbols is None:
        symbols = list(DEFAULT_SYMBOLS)

    signals: List[Dict] = []
    scan_start = _time_mod.monotonic()

    for symbol in symbols:
        if len(signals) >= MAX_SIGNALS_PER_CYCLE:
            logger.info(
                "Structure scanner: max signals (%d) reached, stopping scan",
                MAX_SIGNALS_PER_CYCLE,
            )
            break

        try:
            signal = _scan_symbol(symbol)
            if signal is not None:
                signals.append(signal)
        except Exception:
            logger.exception("Structure scanner: unhandled error scanning %s", symbol)
            continue

    elapsed = _time_mod.monotonic() - scan_start
    logger.info(
        "Structure scanner: scanned %d symbols in %.1fs, found %d signals",
        len(symbols), elapsed, len(signals),
    )

    return signals


def _scan_symbol(symbol: str) -> Optional[Dict]:
    """Scan a single symbol for a structure-based entry.

    Returns a signal dict or None if no valid setup is found.
    """
    # --- 0. Anti-churn ---
    if not check_anti_churn(symbol):
        return None

    # --- 1. Build MTF context ---
    try:
        from app.quant.indicators.mtf_context import build_mtf_context
    except ImportError:
        logger.error("Structure scanner: mtf_context module not available")
        return None

    mtf = build_mtf_context(symbol)

    # --- 2. Confidence gate ---
    confidence = mtf.get('confidence', 0.0)
    alignment_score = mtf.get('alignment_score', 0)

    if confidence < MIN_MTF_CONFIDENCE:
        logger.debug(
            "STRUCT SKIP %s: MTF confidence %.2f < %.2f",
            symbol, confidence, MIN_MTF_CONFIDENCE,
        )
        return None

    if alignment_score < MIN_ALIGNMENT_SCORE:
        logger.debug(
            "STRUCT SKIP %s: alignment score %d < %d",
            symbol, alignment_score, MIN_ALIGNMENT_SCORE,
        )
        return None

    # --- 3. Extract MTF fields ---
    htf_trend = mtf.get('htf_trend', 'RANGE')
    ltf_trend = mtf.get('ltf_trend', 'RANGE')
    alignment = mtf.get('alignment', 'NEUTRAL')
    htf_phase = mtf.get('htf_phase', 'RANGE')
    ltf_phase = mtf.get('ltf_phase', 'RANGE')
    bias = mtf.get('bias', 'NEUTRAL')
    entry_zones = mtf.get('entry_zones', [])
    structure_breaks = mtf.get('structure_breaks', [])

    # --- 4. Classify setup type ---
    setup_type = classify_setup_type(
        htf_trend=htf_trend,
        ltf_trend=ltf_trend,
        alignment=alignment,
        htf_phase=htf_phase,
        ltf_phase=ltf_phase,
        structure_breaks=structure_breaks,
    )

    if setup_type is None:
        logger.debug("STRUCT SKIP %s: no classifiable setup (htf=%s ltf=%s)", symbol, htf_trend, ltf_trend)
        return None

    # Reversal requires higher alignment
    if setup_type == 'REVERSAL' and alignment_score < REVERSAL_MIN_ALIGNMENT:
        logger.debug(
            "STRUCT SKIP %s: REVERSAL needs alignment >= %d, got %d",
            symbol, REVERSAL_MIN_ALIGNMENT, alignment_score,
        )
        return None

    # --- 5. Determine direction ---
    direction = determine_direction(
        setup_type=setup_type,
        htf_trend=htf_trend,
        bias=bias,
        structure_breaks=structure_breaks,
        ltf_trend=ltf_trend,
    )

    if direction is None:
        logger.debug("STRUCT SKIP %s: cannot determine direction for %s", symbol, setup_type)
        return None

    # --- 6. Find entry zone ---
    best_zone = find_best_entry_zone(
        entry_zones=entry_zones,
        direction=direction,
        current_price=0.0,  # Will be fetched below
        max_age_bars=MAX_ZONE_AGE_BARS,
    )

    # Entry zone is preferred but not strictly required for TREND_CONTINUATION
    # when alignment is high (the trend itself is the reason to enter).
    zone_required = setup_type not in ('TREND_CONTINUATION',)
    if best_zone is None and zone_required:
        logger.debug(
            "STRUCT SKIP %s: no valid %s entry zone for %s",
            symbol, direction, setup_type,
        )
        return None

    entry_zone_type = 'NONE'
    if best_zone is not None:
        entry_zone_type = best_zone.get('zone', {}).get('type', 'ZONE')

    # --- 7. LTF confirmation ---
    confirmed, confirm_reason = check_ltf_confirmation(
        structure_breaks=structure_breaks,
        direction=direction,
        setup_type=setup_type,
    )

    if not confirmed:
        logger.debug(
            "STRUCT SKIP %s: no LTF confirmation for %s %s -- %s",
            symbol, direction, setup_type, confirm_reason,
        )
        return None

    # --- 8. Get current price and M15 data for SL/TP ---
    try:
        from app.utils.api.data import symbol_info_tick, fetch_data_pos_cached
        from app.utils.constants import MT5Timeframe

        tick = symbol_info_tick(symbol)
        if tick is None or tick.empty:
            logger.debug("STRUCT SKIP %s: no tick data", symbol)
            return None

        if direction == 'BUY':
            current_price = float(tick['ask'].iloc[0])
        else:
            current_price = float(tick['bid'].iloc[0])

        m15_df = fetch_data_pos_cached(symbol, MT5Timeframe.M15, 100)
        if m15_df is None or len(m15_df) < 20:
            logger.debug("STRUCT SKIP %s: insufficient M15 data", symbol)
            return None

    except Exception as e:
        logger.debug("STRUCT SKIP %s: data fetch error: %s", symbol, e)
        return None

    # --- 9. Calculate structure-based SL/TP ---
    try:
        from app.quant.algorithms.structure_levels import get_structure_levels
        from app.quant.indicators.zone_mapper import _calc_atr

        atr_value = _calc_atr(m15_df)
        if atr_value <= 0:
            logger.debug("STRUCT SKIP %s: ATR is zero", symbol)
            return None

        levels = get_structure_levels(
            symbol=symbol,
            direction=direction,
            entry_price=current_price,
            df=m15_df,
            atr_value=atr_value,
            min_rr=MIN_RR_RATIO,
        )

        sl_price = levels['sl_price']
        tp_price = levels['tp_price']
        rr_ratio = levels['rr_ratio']
        sl_source = levels['sl_source']
        tp_source = levels['tp_source']

        # Enforce minimum R:R
        if rr_ratio < MIN_RR_RATIO:
            logger.debug(
                "STRUCT SKIP %s: R:R %.2f < %.2f minimum",
                symbol, rr_ratio, MIN_RR_RATIO,
            )
            return None

    except Exception as e:
        logger.debug("STRUCT SKIP %s: SL/TP calculation failed: %s", symbol, e)
        return None

    # --- 10. VWAP alignment ---
    vwap_info = check_vwap_alignment(symbol, direction)
    vwap_aligned = vwap_info['aligned']

    # --- 11. Orderbook alignment ---
    ob_info = check_orderbook_alignment(symbol, direction)
    ob_aligned = ob_info['aligned']

    # --- 12. News risk ---
    news_size_mult = 1.0
    try:
        from app.quant.indicators.news_sentiment import get_market_risk_level

        news = get_market_risk_level()
        news_size_mult = news.get('size_multiplier', 1.0)
    except Exception as e:
        logger.debug("STRUCT: news check failed for %s: %s", symbol, e)

    # --- 13. Graph advisor ---
    graph_advice = consult_graph_advisor(
        symbol=symbol,
        direction=direction,
        setup_type=setup_type,
        regime=htf_trend,
        confluence_score=alignment_score,
    )
    graph_confidence = graph_advice.get('confidence', 0.5)
    graph_size_mult = graph_advice.get('size_modifier', 1.0)

    # --- 14. Compute final confidence ---
    # Base confidence from MTF context
    final_confidence = confidence

    # Setup type adjustment
    final_confidence += SETUP_CONFIDENCE.get(setup_type, 0.0)

    # VWAP alignment bonus/penalty
    if vwap_aligned:
        final_confidence += 0.05
    else:
        final_confidence -= 0.10

    # Orderbook alignment bonus/penalty
    if ob_aligned:
        final_confidence += 0.05
    else:
        final_confidence -= 0.05

    # Graph advisor blending (20% weight)
    final_confidence = final_confidence * 0.80 + graph_confidence * 0.20

    # Clamp
    final_confidence = max(0.0, min(1.0, round(final_confidence, 3)))

    # Final confidence gate
    if final_confidence < MIN_MTF_CONFIDENCE:
        logger.debug(
            "STRUCT SKIP %s: final confidence %.3f < %.2f after adjustments",
            symbol, final_confidence, MIN_MTF_CONFIDENCE,
        )
        return None

    # --- 15. Build reasoning ---
    reasoning = build_reasoning(
        setup_type=setup_type,
        htf_trend=htf_trend,
        ltf_phase=ltf_phase,
        entry_zone_type=entry_zone_type if entry_zone_type != 'NONE' else '',
        ltf_confirmation=confirm_reason,
        vwap_bias=vwap_info.get('bias', 'NEUTRAL'),
        ob_bias=ob_info.get('bias', 'NEUTRAL'),
    )

    # --- 16. Build signal ---
    signal = {
        'symbol': symbol,
        'direction': direction,
        'entry_price': current_price,
        'sl_price': sl_price,
        'tp_price': tp_price,
        'rr_ratio': rr_ratio,
        'confidence': final_confidence,
        'setup_type': setup_type,
        'reasoning': reasoning,
        'htf_trend': htf_trend,
        'ltf_phase': ltf_phase,
        'entry_zone': entry_zone_type,
        'mtf_alignment_score': alignment_score,
        'news_size_mult': news_size_mult,
        'graph_confidence': graph_confidence,
        'graph_size_mult': graph_size_mult,
        'vwap_aligned': vwap_aligned,
        'ob_aligned': ob_aligned,
        'sl_source': sl_source,
        'tp_source': tp_source,
        'structural_context': levels.get('structural_context', ''),
        'atr': atr_value,
    }

    logger.info(
        "STRUCT SIGNAL %s %s %s: entry=%.5f SL=%.5f TP=%.5f "
        "R:R=%.2f conf=%.3f score=%d zone=%s | %s",
        symbol, direction, setup_type,
        current_price, sl_price, tp_price,
        rr_ratio, final_confidence, alignment_score,
        entry_zone_type, reasoning,
    )

    return signal


# ---------------------------------------------------------------------------
# Celery-callable execution function
# ---------------------------------------------------------------------------

def run_structure_scanner():
    """Celery-callable function that scans and executes autonomous entries.

    Scans all default symbols for structure-based setups, then executes
    any valid signals by placing market orders via MT5.

    This function handles:
    - Position limit checks
    - PairLock acquisition
    - Risk-based lot sizing
    - Order execution
    - Trade record creation

    Returns
    -------
    dict
        Summary of the scan: signals_found, trades_opened, skipped, errors.
    """
    from django.db import IntegrityError

    summary = {
        'signals_found': 0,
        'trades_opened': 0,
        'skipped': 0,
        'errors': 0,
        'details': [],
    }

    try:
        signals = scan_for_entries()
        summary['signals_found'] = len(signals)
    except Exception:
        logger.exception("Structure scanner: scan_for_entries failed")
        summary['errors'] += 1
        return summary

    if not signals:
        logger.debug("Structure scanner: no signals found")
        return summary

    # Lazy imports for execution path
    try:
        from app.nexus.models import StrategyConfig, PairLock, Trade
        from app.utils.api.order import send_market_order
        from app.utils.arithmetics import calculate_risk_based_lots
        from app.utils.db.create import create_trade
        from app.utils.arithmetics import (
            calculate_order_size_usd,
            calculate_commission,
            get_symbol_contract_info,
        )
    except ImportError as e:
        logger.error("Structure scanner: missing import: %s", e)
        summary['errors'] += 1
        return summary

    # Get or create a StrategyConfig for structure entries
    try:
        strategy_config, _ = StrategyConfig.objects.get_or_create(
            name='STRUCTURE_AUTONOMOUS',
            defaults={
                'is_active': True,
                'description': 'Autonomous structure-based entry generator',
                'max_positions': 5,
            },
        )
    except Exception as e:
        logger.error("Structure scanner: cannot get/create StrategyConfig: %s", e)
        summary['errors'] += 1
        return summary

    for signal in signals:
        symbol = signal['symbol']
        direction = signal['direction']

        try:
            # --- Position limit check ---
            open_count = Trade.objects.filter(close_time__isnull=True).count()
            if open_count >= GLOBAL_MAX_POSITIONS:
                logger.info(
                    "Structure scanner: global position limit (%d/%d) reached",
                    open_count, GLOBAL_MAX_POSITIONS,
                )
                summary['skipped'] += 1
                summary['details'].append(f"{symbol}: global limit reached")
                break

            # --- PairLock check ---
            if PairLock.objects.filter(symbol=symbol).exists():
                logger.debug("Structure scanner: %s already locked", symbol)
                summary['skipped'] += 1
                summary['details'].append(f"{symbol}: pair locked")
                continue

            # --- Check existing position ---
            try:
                from app.utils.account import have_open_positions_in_symbol
                if have_open_positions_in_symbol(symbol):
                    logger.debug("Structure scanner: %s already has position", symbol)
                    summary['skipped'] += 1
                    summary['details'].append(f"{symbol}: existing position")
                    continue
            except Exception:
                pass

            # --- Risk-based lot sizing ---
            sl_distance = abs(signal['entry_price'] - signal['sl_price'])
            target_risk = DEFAULT_TARGET_RISK * signal.get('news_size_mult', 1.0)

            # Apply graph advisor size modifier
            target_risk *= signal.get('graph_size_mult', 1.0)

            # Clamp target risk
            target_risk = min(target_risk, DEFAULT_TARGET_RISK * 1.5)
            target_risk = max(target_risk, 10.0)

            try:
                lots = calculate_risk_based_lots(
                    symbol, sl_distance, target_risk, direction,
                )
            except Exception as e:
                logger.warning("Structure scanner: lot calc failed for %s: %s", symbol, e)
                summary['errors'] += 1
                summary['details'].append(f"{symbol}: lot calc error: {e}")
                continue

            if lots <= 0:
                logger.warning("Structure scanner: zero lots for %s", symbol)
                summary['skipped'] += 1
                continue

            # --- Acquire PairLock ---
            try:
                PairLock.objects.create(
                    symbol=symbol,
                    strategy=strategy_config,
                    ticket=0,  # Updated after order fills
                )
            except IntegrityError:
                logger.info("Structure scanner: %s locked during scan", symbol)
                summary['skipped'] += 1
                summary['details'].append(f"{symbol}: lock race")
                continue

            # --- Execute order ---
            try:
                comment = f"STRUCT_{signal['setup_type'][:4]}"
                order = send_market_order(
                    symbol=symbol,
                    volume=lots,
                    order_type=direction,
                    sl=signal['sl_price'],
                    tp=signal['tp_price'],
                    comment=comment,
                    min_rr=MIN_RR_RATIO,
                )

                if order is None:
                    logger.warning("Structure scanner: order rejected for %s %s", symbol, direction)
                    # Release PairLock on failure
                    PairLock.objects.filter(symbol=symbol, strategy=strategy_config).delete()
                    summary['skipped'] += 1
                    summary['details'].append(f"{symbol}: order rejected")
                    continue

                # --- Update PairLock with ticket ---
                order_ticket = order.get('order', 0)
                try:
                    PairLock.objects.filter(
                        symbol=symbol, strategy=strategy_config,
                    ).update(ticket=order_ticket)
                except Exception:
                    pass

                # --- Create Trade record ---
                try:
                    contract_info = get_symbol_contract_info(symbol)
                    contract_size = contract_info.get('trade_contract_size', 100000) if contract_info else 100000
                    entry_price = order.get('price', signal['entry_price'])

                    # Notional calculation
                    if symbol.startswith('USD') and symbol != 'USDX':
                        order_size_usd = lots * contract_size
                    else:
                        order_size_usd = lots * contract_size * entry_price

                    leverage = 500
                    commission = calculate_commission(order_size_usd, symbol)
                    capital = order_size_usd / leverage

                    # Determine market type
                    from app.utils.constants import METALS, OILS
                    if symbol in METALS:
                        market_type = 'FOREX'  # Metals are under forex broker
                    elif symbol in OILS:
                        market_type = 'FOREX'
                    else:
                        market_type = 'FOREX'

                    trade_result = create_trade(
                        order, symbol, capital, order_size_usd,
                        leverage, commission, direction, 'Alpari',
                        market_type, f'STRUCT_{signal["setup_type"]}',
                        'M15', lots,
                        signal['sl_price'], signal['tp_price'],
                    )

                    if trade_result:
                        trade_obj = trade_result[0] if isinstance(trade_result, tuple) else trade_result
                        try:
                            update_fields = []
                            if hasattr(trade_obj, 'entry_atr'):
                                trade_obj.entry_atr = signal.get('atr', 0)
                                update_fields.append('entry_atr')
                            if hasattr(trade_obj, 'entry_timeframe'):
                                trade_obj.entry_timeframe = 'M15'
                                update_fields.append('entry_timeframe')
                            if hasattr(trade_obj, 'strategy_config'):
                                trade_obj.strategy_config = strategy_config
                                update_fields.append('strategy_config')
                            if update_fields:
                                trade_obj.save(update_fields=update_fields)
                        except Exception as e:
                            logger.warning("Structure scanner: could not update trade fields: %s", e)

                        # Store ML features
                        try:
                            from app.nexus.models import TradeFeature
                            TradeFeature.objects.create(
                                trade=trade_obj,
                                features_json={
                                    'setup_type': signal['setup_type'],
                                    'htf_trend': signal['htf_trend'],
                                    'ltf_phase': signal['ltf_phase'],
                                    'alignment_score': signal['mtf_alignment_score'],
                                    'confidence': signal['confidence'],
                                    'entry_zone': signal['entry_zone'],
                                    'rr_ratio': signal['rr_ratio'],
                                    'vwap_aligned': signal['vwap_aligned'],
                                    'ob_aligned': signal['ob_aligned'],
                                    'news_size_mult': signal['news_size_mult'],
                                    'graph_confidence': signal['graph_confidence'],
                                    'sl_source': signal['sl_source'],
                                    'tp_source': signal['tp_source'],
                                    'reasoning': signal['reasoning'],
                                },
                            )
                        except Exception as e:
                            logger.warning("Structure scanner: could not save TradeFeature: %s", e)

                        # Record WHY this trade was taken (agent memory)
                        try:
                            from app.quant.tasks import record_to_graph as _rtg
                            _reasoning_text = (
                                f"{signal['setup_type']} on {symbol} {direction}. "
                                f"{signal.get('reasoning', '')} "
                                f"SL: {signal['sl_source']} at {signal['sl_price']:.5f}, "
                                f"TP: {signal['tp_source']} at {signal['tp_price']:.5f}, "
                                f"R:R={signal['rr_ratio']:.2f}. "
                                f"Graph conf={signal.get('graph_confidence', 0.5):.2f}. "
                                f"News size mult={signal.get('news_size_mult', 1.0):.2f}."
                            )
                            _rtg.delay({
                                'type': 'trade_reasoning',
                                'reasoning': {
                                    'trade_id': trade_obj.id,
                                    'symbol': symbol,
                                    'direction': direction,
                                    'htf_trend': signal.get('htf_trend', 'UNKNOWN'),
                                    'htf_phase': 'UNKNOWN',
                                    'ltf_trend': 'UNKNOWN',
                                    'ltf_phase': signal.get('ltf_phase', 'UNKNOWN'),
                                    'mtf_alignment': 'ALIGNED' if signal.get('mtf_alignment_score', 0) >= 7 else 'DIVERGING',
                                    'mtf_alignment_score': signal.get('mtf_alignment_score', 0),
                                    'mtf_bias': signal.get('htf_trend', 'UNKNOWN'),
                                    'mtf_confidence': signal.get('confidence', 0),
                                    'setup_type': signal.get('setup_type', 'UNKNOWN'),
                                    'entry_zone': signal.get('entry_zone', 'UNKNOWN'),
                                    'entry_zone_price': signal.get('entry_price', 0),
                                    'entry_source': 'STRUCTURE',
                                    'vwap_bias': 'BULLISH' if signal.get('vwap_aligned') else 'NEUTRAL',
                                    'orderbook_bias': 'BULLISH' if signal.get('ob_aligned') else 'NEUTRAL',
                                    'news_risk': 'ELEVATED' if signal.get('news_size_mult', 1.0) < 1.0 else 'NORMAL',
                                    'news_size_mult': signal.get('news_size_mult', 1.0),
                                    'llm_decision': '',
                                    'llm_confidence': 0,
                                    'graph_confidence': signal.get('graph_confidence', 0.5),
                                    'graph_recommendation': 'NORMAL',
                                    'similar_setups_wr': 0,
                                    'similar_setups_count': 0,
                                    'sl_source': signal.get('sl_source', 'ATR'),
                                    'tp_source': signal.get('tp_source', 'ATR'),
                                    'sl_reasoning': f"SL at {signal['sl_price']:.5f} via {signal.get('sl_source', 'ATR')}",
                                    'tp_reasoning': f"TP at {signal['tp_price']:.5f} via {signal.get('tp_source', 'ATR')}",
                                    'rr_ratio': signal.get('rr_ratio', 0),
                                    'confluence_score': signal.get('mtf_alignment_score', 0),
                                    'confluence_band': '',
                                    'regime_at_entry': signal.get('htf_trend', 'UNKNOWN'),
                                    'regime_confidence': signal.get('confidence', 0),
                                    'size_multiplier': signal.get('news_size_mult', 1.0) * signal.get('graph_size_mult', 1.0),
                                    'strategy': f"STRUCT_{signal.get('setup_type', 'UNKNOWN')}",
                                    'reasoning_text': _reasoning_text,
                                },
                            })
                        except Exception:
                            pass  # Reasoning recording is fire-and-forget

                except Exception as e:
                    logger.error("Structure scanner: trade record creation failed for %s: %s", symbol, e)
                    summary['errors'] += 1

                summary['trades_opened'] += 1
                summary['details'].append(
                    f"{symbol} {direction} {signal['setup_type']}: "
                    f"entry={signal['entry_price']:.5f} SL={signal['sl_price']:.5f} "
                    f"TP={signal['tp_price']:.5f} R:R={signal['rr_ratio']:.2f} "
                    f"lots={lots}"
                )

                logger.info(
                    "STRUCT EXECUTED %s %s %s: entry=%.5f lots=%.2f "
                    "SL=%.5f TP=%.5f R:R=%.2f conf=%.3f",
                    symbol, direction, signal['setup_type'],
                    signal['entry_price'], lots,
                    signal['sl_price'], signal['tp_price'],
                    signal['rr_ratio'], signal['confidence'],
                )

            except Exception as e:
                # Release PairLock on execution failure
                try:
                    PairLock.objects.filter(symbol=symbol, strategy=strategy_config).delete()
                except Exception:
                    pass
                logger.error("Structure scanner: execution failed for %s: %s", symbol, e)
                summary['errors'] += 1
                summary['details'].append(f"{symbol}: execution error: {e}")

        except Exception:
            logger.exception("Structure scanner: unhandled error processing signal for %s", symbol)
            summary['errors'] += 1
            continue

    logger.info(
        "Structure scanner complete: %d signals, %d opened, %d skipped, %d errors",
        summary['signals_found'], summary['trades_opened'],
        summary['skipped'], summary['errors'],
    )

    return summary
