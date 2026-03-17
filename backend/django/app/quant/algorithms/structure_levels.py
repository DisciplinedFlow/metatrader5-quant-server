"""Structure-Based SL/TP Calculator.

Places stops and targets at meaningful market structure levels instead of
fixed ATR multiples. Uses swing points, FVGs, and order blocks.

Fallback: if no clear structure, use ATR-based levels (existing behavior).

The philosophy: SL should be where your trade idea is WRONG (below last HL
for a long), not at an arbitrary distance. TP should be where opposing
pressure exists (next supply zone for a long).

Integration points:
- ``market_structure.py`` (``find_swing_points``, ``label_structure``) — built
  by another agent; graceful fallback if absent.
- ``zone_mapper.py`` (``find_fvgs``, ``find_order_blocks``) — built by another
  agent; graceful fallback if absent.
- ``smc_detector.py`` — always available; used as secondary source for swing
  points, FVGs, and OBs when the dedicated modules are missing.
"""

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger('structure_levels')

# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------
SL_MIN_ATR_DISTANCE = 0.5   # SL must be at least 0.5 ATR from entry
SL_MAX_ATR_DISTANCE = 3.0   # SL must not exceed 3.0 ATR from entry
SL_BUFFER_ATR_FRAC = 0.2    # Buffer beyond structural level (stop-hunt protection)

# ---------------------------------------------------------------------------
# Lazy imports — graceful degradation when companion modules are absent
# ---------------------------------------------------------------------------
_MARKET_STRUCTURE_AVAILABLE = False
_ZONE_MAPPER_AVAILABLE = False

try:
    from app.quant.algorithms.market_structure import find_swing_points, label_structure
    _MARKET_STRUCTURE_AVAILABLE = True
except ImportError:
    find_swing_points = None  # type: ignore[assignment, misc]
    label_structure = None    # type: ignore[assignment, misc]
    logger.debug(
        "market_structure module not available — will use smc_detector "
        "swing points as fallback"
    )

try:
    from app.quant.algorithms.zone_mapper import find_fvgs, find_order_blocks
    _ZONE_MAPPER_AVAILABLE = True
except ImportError:
    find_fvgs = None          # type: ignore[assignment, misc]
    find_order_blocks = None  # type: ignore[assignment, misc]
    logger.debug(
        "zone_mapper module not available — will use smc_detector "
        "FVGs/OBs as fallback"
    )


# ---------------------------------------------------------------------------
# Internal helpers — swing point extraction
# ---------------------------------------------------------------------------

def _get_swing_points_from_smc(df: pd.DataFrame) -> List[Dict]:
    """Extract swing highs and lows via smc_detector as fallback.

    Returns a list of dicts with keys:
        ``type``  — ``'high'`` or ``'low'``
        ``price`` — the swing price level
        ``bar_idx`` — integer index into *df*
    """
    try:
        from app.quant.indicators.smc_detector import detect_swing_points

        sp_df = detect_swing_points(df, swing_lookback=5)
        points: List[Dict] = []

        for i in range(len(sp_df)):
            hl = sp_df['HighLow'].iloc[i]
            level = sp_df['Level'].iloc[i]

            if pd.isna(hl) or hl == 0 or pd.isna(level):
                continue

            points.append({
                'type': 'high' if hl == 1 else 'low',
                'price': float(level),
                'bar_idx': i,
            })

        return points

    except Exception as e:
        logger.debug(f"smc_detector swing points failed: {e}")
        return []


def _get_swing_points_from_market_structure(df: pd.DataFrame) -> List[Dict]:
    """Extract swing points from the dedicated market_structure module.

    Returns same format as ``_get_swing_points_from_smc``.
    """
    if not _MARKET_STRUCTURE_AVAILABLE or find_swing_points is None:
        return []

    try:
        raw = find_swing_points(df)

        # Normalise whatever format market_structure returns into our
        # standard list-of-dicts.  We accept both list[dict] and DataFrame.
        if isinstance(raw, pd.DataFrame):
            points: List[Dict] = []
            for i in range(len(raw)):
                row = raw.iloc[i]
                pt_type = row.get('type', row.get('HighLow', None))
                price = row.get('price', row.get('Level', None))
                if pt_type is None or price is None:
                    continue
                if isinstance(pt_type, (int, float)):
                    pt_type = 'high' if pt_type == 1 else 'low'
                points.append({
                    'type': str(pt_type),
                    'price': float(price),
                    'bar_idx': int(row.get('bar_idx', i)),
                })
            return points

        if isinstance(raw, list):
            return [
                {
                    'type': str(p.get('type', '')),
                    'price': float(p.get('price', 0)),
                    'bar_idx': int(p.get('bar_idx', 0)),
                }
                for p in raw
                if 'price' in p
            ]

        return []

    except Exception as e:
        logger.debug(f"market_structure swing points failed: {e}")
        return []


def _get_swing_points(df: pd.DataFrame) -> List[Dict]:
    """Get swing points from the best available source.

    Prefers ``market_structure`` module; falls back to ``smc_detector``.
    """
    points = _get_swing_points_from_market_structure(df)
    if points:
        return points
    return _get_swing_points_from_smc(df)


# ---------------------------------------------------------------------------
# Internal helpers — zone extraction (FVGs + OBs)
# ---------------------------------------------------------------------------

def _get_zones_from_smc(df: pd.DataFrame) -> List[Dict]:
    """Extract active FVG and OB zones from smc_detector.

    Returns list of dicts:
        ``zone_type`` — ``'FVG'`` or ``'OB'``
        ``direction`` — ``'bullish'`` or ``'bearish'``
        ``top``       — upper price boundary
        ``bottom``    — lower price boundary
        ``bar_idx``   — where the zone was detected
    """
    zones: List[Dict] = []

    try:
        from app.quant.indicators.smc_detector import (
            detect_fair_value_gaps,
            detect_order_blocks,
        )

        fvg_df = detect_fair_value_gaps(df, swing_lookback=5)
        for i in range(len(fvg_df)):
            fvg_val = fvg_df['FVG'].iloc[i]
            mitigated = fvg_df['MitigatedIndex'].iloc[i]
            if pd.isna(fvg_val) or fvg_val == 0:
                continue
            if not pd.isna(mitigated):
                continue  # already filled
            top = fvg_df['Top'].iloc[i]
            bottom = fvg_df['Bottom'].iloc[i]
            if pd.isna(top) or pd.isna(bottom):
                continue
            zones.append({
                'zone_type': 'FVG',
                'direction': 'bullish' if fvg_val == 1 else 'bearish',
                'top': float(top),
                'bottom': float(bottom),
                'bar_idx': i,
            })

        ob_df = detect_order_blocks(df, swing_lookback=5)
        for i in range(len(ob_df)):
            ob_val = ob_df['OB'].iloc[i]
            mitigated = ob_df['MitigatedIndex'].iloc[i]
            if pd.isna(ob_val) or ob_val == 0:
                continue
            if not pd.isna(mitigated):
                continue
            top = ob_df['Top'].iloc[i]
            bottom = ob_df['Bottom'].iloc[i]
            if pd.isna(top) or pd.isna(bottom):
                continue
            zones.append({
                'zone_type': 'OB',
                'direction': 'bullish' if ob_val == 1 else 'bearish',
                'top': float(top),
                'bottom': float(bottom),
                'bar_idx': i,
            })

    except Exception as e:
        logger.debug(f"smc_detector zone extraction failed: {e}")

    return zones


def _get_zones_from_zone_mapper(df: pd.DataFrame) -> List[Dict]:
    """Extract zones from the dedicated zone_mapper module."""
    if not _ZONE_MAPPER_AVAILABLE or find_fvgs is None or find_order_blocks is None:
        return []

    zones: List[Dict] = []
    try:
        raw_fvgs = find_fvgs(df)
        if isinstance(raw_fvgs, list):
            for z in raw_fvgs:
                zones.append({
                    'zone_type': 'FVG',
                    'direction': str(z.get('direction', '')),
                    'top': float(z.get('top', 0)),
                    'bottom': float(z.get('bottom', 0)),
                    'bar_idx': int(z.get('bar_idx', 0)),
                })
    except Exception as e:
        logger.debug(f"zone_mapper find_fvgs failed: {e}")

    try:
        raw_obs = find_order_blocks(df)
        if isinstance(raw_obs, list):
            for z in raw_obs:
                zones.append({
                    'zone_type': 'OB',
                    'direction': str(z.get('direction', '')),
                    'top': float(z.get('top', 0)),
                    'bottom': float(z.get('bottom', 0)),
                    'bar_idx': int(z.get('bar_idx', 0)),
                })
    except Exception as e:
        logger.debug(f"zone_mapper find_order_blocks failed: {e}")

    return zones


def _get_zones(df: pd.DataFrame) -> List[Dict]:
    """Get FVG/OB zones from the best available source."""
    zones = _get_zones_from_zone_mapper(df)
    if zones:
        return zones
    return _get_zones_from_smc(df)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate_structure_sl(
    symbol: str,
    direction: str,
    entry_price: float,
    df: pd.DataFrame,
    atr_value: float,
    atr_sl_mult: float = 1.8,
) -> Tuple[float, str]:
    """Calculate SL based on market structure.

    For BUY: SL below last swing low (HL in uptrend, LL in downtrend).
    For SELL: SL above last swing high (LH in downtrend, HH in uptrend).

    Adds a buffer of 0.2 * ATR beyond the structural level to avoid
    stop hunts (brokers push price just past structure to grab stops).

    Parameters
    ----------
    symbol : str
        Trading pair name (for logging).
    direction : str
        ``'BUY'`` or ``'SELL'``.
    entry_price : float
        Intended entry price.
    df : pd.DataFrame
        M15 OHLCV data with columns ``high``, ``low``, ``close`` (or
        uppercase equivalents).
    atr_value : float
        Current 14-period ATR value, used for fallback and buffer sizing.
    atr_sl_mult : float
        ATR multiplier for the fallback SL (default 1.8).

    Returns
    -------
    tuple[float, str]
        ``(sl_price, source)`` where *source* is ``'STRUCTURE'`` or
        ``'ATR_FALLBACK'``.
    """
    buffer = atr_value * SL_BUFFER_ATR_FRAC
    min_dist = atr_value * SL_MIN_ATR_DISTANCE
    max_dist = atr_value * SL_MAX_ATR_DISTANCE

    swing_points = _get_swing_points(df)

    # --- Attempt structure-based SL ---
    if swing_points:
        if direction == 'BUY':
            # Find swing lows below entry — SL goes below the nearest one
            candidates = [
                p for p in swing_points
                if p['type'] == 'low' and p['price'] < entry_price
            ]
            # Sort by price descending (closest to entry first)
            candidates.sort(key=lambda p: p['price'], reverse=True)

            for cand in candidates:
                sl_candidate = cand['price'] - buffer
                dist = entry_price - sl_candidate

                if dist < min_dist:
                    # Too tight — try next swing low further away
                    continue
                if dist > max_dist:
                    # Too wide — stop searching (sorted desc, rest will be wider)
                    break

                logger.info(
                    f"STRUCT SL {symbol} BUY: swing low {cand['price']:.5f} "
                    f"(bar {cand['bar_idx']}) - buffer {buffer:.5f} = "
                    f"SL {sl_candidate:.5f} (dist {dist:.5f}, "
                    f"{dist / atr_value:.1f}x ATR)"
                )
                return sl_candidate, 'STRUCTURE'

        else:  # SELL
            # Find swing highs above entry — SL goes above the nearest one
            candidates = [
                p for p in swing_points
                if p['type'] == 'high' and p['price'] > entry_price
            ]
            # Sort by price ascending (closest to entry first)
            candidates.sort(key=lambda p: p['price'])

            for cand in candidates:
                sl_candidate = cand['price'] + buffer
                dist = sl_candidate - entry_price

                if dist < min_dist:
                    continue
                if dist > max_dist:
                    break

                logger.info(
                    f"STRUCT SL {symbol} SELL: swing high {cand['price']:.5f} "
                    f"(bar {cand['bar_idx']}) + buffer {buffer:.5f} = "
                    f"SL {sl_candidate:.5f} (dist {dist:.5f}, "
                    f"{dist / atr_value:.1f}x ATR)"
                )
                return sl_candidate, 'STRUCTURE'

        logger.debug(
            f"STRUCT SL {symbol} {direction}: no swing point in "
            f"[{min_dist:.5f}, {max_dist:.5f}] range — falling back to ATR"
        )

    else:
        logger.debug(
            f"STRUCT SL {symbol} {direction}: no swing points detected "
            f"— falling back to ATR"
        )

    # --- ATR fallback ---
    sl_distance = atr_value * atr_sl_mult
    if direction == 'BUY':
        sl_price = entry_price - sl_distance
    else:
        sl_price = entry_price + sl_distance

    logger.info(
        f"STRUCT SL {symbol} {direction}: ATR fallback SL={sl_price:.5f} "
        f"({atr_sl_mult}x ATR)"
    )
    return sl_price, 'ATR_FALLBACK'


def calculate_structure_tp(
    symbol: str,
    direction: str,
    entry_price: float,
    sl_price: float,
    df: pd.DataFrame,
    zones: Optional[List[Dict]] = None,
    atr_value: float = 0.0,
    min_rr: float = 2.0,
) -> Tuple[float, float, str]:
    """Calculate TP based on opposing structural zones.

    For BUY: TP at next supply zone (bearish FVG or bearish OB above entry).
    For SELL: TP at next demand zone (bullish FVG or bullish OB below entry).

    Ensures minimum R:R of *min_rr*.  If no structural zone provides
    adequate R:R, falls back to ATR-based TP.

    Parameters
    ----------
    symbol : str
        Trading pair name (for logging).
    direction : str
        ``'BUY'`` or ``'SELL'``.
    entry_price : float
        Intended entry price.
    sl_price : float
        Stop loss price (needed for R:R calculation).
    df : pd.DataFrame
        M15 OHLCV data.
    zones : list[dict] or None
        Pre-computed FVG/OB zones.  If ``None``, they will be detected
        from *df*.
    atr_value : float
        Current ATR (for fallback TP).
    min_rr : float
        Minimum reward-to-risk ratio required (default 2.0).

    Returns
    -------
    tuple[float, float, str]
        ``(tp_price, rr_ratio, source)`` where *source* is
        ``'STRUCTURE'`` or ``'ATR_FALLBACK'``.
    """
    risk_distance = abs(entry_price - sl_price)
    if risk_distance <= 0:
        logger.warning(
            f"STRUCT TP {symbol}: invalid risk distance "
            f"(entry={entry_price}, sl={sl_price})"
        )
        # Hard fallback — use atr_value as risk proxy
        risk_distance = atr_value if atr_value > 0 else 1e-5

    # Load zones if not provided
    if zones is None:
        zones = _get_zones(df)

    # --- Find opposing zones ---
    if direction == 'BUY':
        # Supply zones (bearish FVG/OB) ABOVE entry
        opposing = [
            z for z in zones
            if z['direction'] == 'bearish' and z['bottom'] > entry_price
        ]
        # Sort by bottom price ascending — closest supply zone first
        opposing.sort(key=lambda z: z['bottom'])

        for zone in opposing:
            # TP at the bottom of the opposing supply zone (price will
            # likely stall or reverse there)
            tp_candidate = zone['bottom']
            reward = tp_candidate - entry_price
            rr = reward / risk_distance

            if rr >= min_rr:
                logger.info(
                    f"STRUCT TP {symbol} BUY: {zone['zone_type']} "
                    f"({zone['bottom']:.5f}-{zone['top']:.5f}) "
                    f"TP={tp_candidate:.5f} R:R={rr:.2f}"
                )
                return tp_candidate, round(rr, 2), 'STRUCTURE'

    else:  # SELL
        # Demand zones (bullish FVG/OB) BELOW entry
        opposing = [
            z for z in zones
            if z['direction'] == 'bullish' and z['top'] < entry_price
        ]
        # Sort by top price descending — closest demand zone first
        opposing.sort(key=lambda z: z['top'], reverse=True)

        for zone in opposing:
            # TP at the top of the opposing demand zone
            tp_candidate = zone['top']
            reward = entry_price - tp_candidate
            rr = reward / risk_distance

            if rr >= min_rr:
                logger.info(
                    f"STRUCT TP {symbol} SELL: {zone['zone_type']} "
                    f"({zone['bottom']:.5f}-{zone['top']:.5f}) "
                    f"TP={tp_candidate:.5f} R:R={rr:.2f}"
                )
                return tp_candidate, round(rr, 2), 'STRUCTURE'

    # No opposing zone found (or none met min_rr) — also try swing points as
    # TP targets (next swing high for sell, next swing low for buy).
    swing_points = _get_swing_points(df)
    if swing_points:
        if direction == 'BUY':
            # Target the next swing high above entry
            highs = [
                p for p in swing_points
                if p['type'] == 'high' and p['price'] > entry_price
            ]
            highs.sort(key=lambda p: p['price'])
            for h in highs:
                reward = h['price'] - entry_price
                rr = reward / risk_distance
                if rr >= min_rr:
                    logger.info(
                        f"STRUCT TP {symbol} BUY: swing high "
                        f"{h['price']:.5f} (bar {h['bar_idx']}) "
                        f"R:R={rr:.2f}"
                    )
                    return h['price'], round(rr, 2), 'STRUCTURE'
        else:
            lows = [
                p for p in swing_points
                if p['type'] == 'low' and p['price'] < entry_price
            ]
            lows.sort(key=lambda p: p['price'], reverse=True)
            for l_pt in lows:
                reward = entry_price - l_pt['price']
                rr = reward / risk_distance
                if rr >= min_rr:
                    logger.info(
                        f"STRUCT TP {symbol} SELL: swing low "
                        f"{l_pt['price']:.5f} (bar {l_pt['bar_idx']}) "
                        f"R:R={rr:.2f}"
                    )
                    return l_pt['price'], round(rr, 2), 'STRUCTURE'

    # --- ATR fallback ---
    tp_distance = risk_distance * min_rr
    if direction == 'BUY':
        tp_price = entry_price + tp_distance
    else:
        tp_price = entry_price - tp_distance

    rr_fallback = round(tp_distance / risk_distance, 2) if risk_distance > 0 else min_rr

    logger.info(
        f"STRUCT TP {symbol} {direction}: ATR fallback TP={tp_price:.5f} "
        f"R:R={rr_fallback} (no opposing zone met {min_rr} R:R)"
    )
    return tp_price, rr_fallback, 'ATR_FALLBACK'


def get_structure_levels(
    symbol: str,
    direction: str,
    entry_price: float,
    df: pd.DataFrame,
    atr_value: float,
    atr_sl_mult: float = 1.8,
    atr_tp_mult: float = 3.6,
    min_rr: float = 2.0,
) -> Dict:
    """Get complete structure-based SL/TP with R:R calculation.

    This is the main entry point.  It orchestrates ``calculate_structure_sl``
    and ``calculate_structure_tp``, pre-loads zones once (avoiding duplicate
    detection), and assembles a full result dict.

    Parameters
    ----------
    symbol : str
        Trading pair name.
    direction : str
        ``'BUY'`` or ``'SELL'``.
    entry_price : float
        Intended entry price.
    df : pd.DataFrame
        M15 OHLCV data.
    atr_value : float
        Current 14-period ATR.
    atr_sl_mult : float
        Fallback SL multiplier (default 1.8).
    atr_tp_mult : float
        Fallback TP multiplier (default 3.6) — used only when *both* SL and
        TP fall back to ATR.
    min_rr : float
        Minimum reward-to-risk ratio (default 2.0).

    Returns
    -------
    dict
        ``sl_price``           — float
        ``tp_price``           — float
        ``sl_source``          — ``'STRUCTURE'`` | ``'ATR_FALLBACK'``
        ``tp_source``          — ``'STRUCTURE'`` | ``'ATR_FALLBACK'``
        ``rr_ratio``           — float
        ``risk_distance``      — ``|entry - SL|``
        ``reward_distance``    — ``|TP - entry|``
        ``structural_context`` — human-readable description of reasoning
    """
    if atr_value <= 0:
        logger.warning(
            f"STRUCT {symbol}: ATR is zero or negative ({atr_value}), "
            f"using pure ATR fallback"
        )
        return _atr_fallback_result(
            symbol, direction, entry_price, atr_value,
            atr_sl_mult, atr_tp_mult, min_rr,
        )

    if df is None or len(df) < 20:
        logger.debug(
            f"STRUCT {symbol}: insufficient data ({len(df) if df is not None else 0} bars) "
            f"— using ATR fallback"
        )
        return _atr_fallback_result(
            symbol, direction, entry_price, atr_value,
            atr_sl_mult, atr_tp_mult, min_rr,
        )

    # Pre-load zones once for both SL and TP calculations
    zones = _get_zones(df)

    # --- SL ---
    sl_price, sl_source = calculate_structure_sl(
        symbol, direction, entry_price, df, atr_value, atr_sl_mult,
    )

    # --- Validate SL side ---
    if direction == 'BUY' and sl_price >= entry_price:
        logger.warning(
            f"STRUCT {symbol} BUY: SL {sl_price:.5f} >= entry "
            f"{entry_price:.5f} — correcting to ATR fallback"
        )
        sl_price = entry_price - atr_value * atr_sl_mult
        sl_source = 'ATR_FALLBACK'

    if direction == 'SELL' and sl_price <= entry_price:
        logger.warning(
            f"STRUCT {symbol} SELL: SL {sl_price:.5f} <= entry "
            f"{entry_price:.5f} — correcting to ATR fallback"
        )
        sl_price = entry_price + atr_value * atr_sl_mult
        sl_source = 'ATR_FALLBACK'

    # --- TP ---
    tp_price, rr_ratio, tp_source = calculate_structure_tp(
        symbol, direction, entry_price, sl_price,
        df, zones=zones, atr_value=atr_value, min_rr=min_rr,
    )

    # --- Validate TP side ---
    if direction == 'BUY' and tp_price <= entry_price:
        logger.warning(
            f"STRUCT {symbol} BUY: TP {tp_price:.5f} <= entry "
            f"{entry_price:.5f} — correcting to ATR fallback"
        )
        risk_dist = entry_price - sl_price
        tp_price = entry_price + risk_dist * min_rr
        tp_source = 'ATR_FALLBACK'

    if direction == 'SELL' and tp_price >= entry_price:
        logger.warning(
            f"STRUCT {symbol} SELL: TP {tp_price:.5f} >= entry "
            f"{entry_price:.5f} — correcting to ATR fallback"
        )
        risk_dist = sl_price - entry_price
        tp_price = entry_price - risk_dist * min_rr
        tp_source = 'ATR_FALLBACK'

    # --- Final metrics ---
    risk_distance = abs(entry_price - sl_price)
    reward_distance = abs(tp_price - entry_price)
    rr_ratio = round(reward_distance / risk_distance, 2) if risk_distance > 0 else 0.0

    # --- Enforce minimum R:R ---
    if rr_ratio < min_rr:
        logger.info(
            f"STRUCT {symbol} {direction}: R:R {rr_ratio} < {min_rr} — "
            f"extending TP to meet minimum"
        )
        reward_needed = risk_distance * min_rr
        if direction == 'BUY':
            tp_price = entry_price + reward_needed
        else:
            tp_price = entry_price - reward_needed
        tp_source = 'ATR_FALLBACK'
        reward_distance = reward_needed
        rr_ratio = min_rr

    # --- Build context string ---
    context_parts = []
    if sl_source == 'STRUCTURE':
        context_parts.append(
            f"SL behind swing {'low' if direction == 'BUY' else 'high'} "
            f"+ {SL_BUFFER_ATR_FRAC}x ATR buffer"
        )
    else:
        context_parts.append(f"SL at {atr_sl_mult}x ATR (no valid structure)")

    if tp_source == 'STRUCTURE':
        context_parts.append(
            f"TP at opposing {'supply' if direction == 'BUY' else 'demand'} zone"
        )
    else:
        context_parts.append(f"TP at {rr_ratio}x risk distance (no opposing zone)")

    structural_context = "; ".join(context_parts)

    result = {
        'sl_price': sl_price,
        'tp_price': tp_price,
        'sl_source': sl_source,
        'tp_source': tp_source,
        'rr_ratio': rr_ratio,
        'risk_distance': round(risk_distance, 6),
        'reward_distance': round(reward_distance, 6),
        'structural_context': structural_context,
    }

    logger.info(
        f"STRUCT LEVELS {symbol} {direction}: "
        f"entry={entry_price:.5f} SL={sl_price:.5f}({sl_source}) "
        f"TP={tp_price:.5f}({tp_source}) R:R={rr_ratio} | "
        f"{structural_context}"
    )

    return result


# ---------------------------------------------------------------------------
# Internal — pure ATR fallback (no structure at all)
# ---------------------------------------------------------------------------

def _atr_fallback_result(
    symbol: str,
    direction: str,
    entry_price: float,
    atr_value: float,
    atr_sl_mult: float,
    atr_tp_mult: float,
    min_rr: float,
) -> Dict:
    """Build a complete result dict using only ATR multiples.

    Used when no structural data is available at all (missing DataFrame,
    zero ATR, etc.).
    """
    # Guard against zero ATR — use a tiny default to avoid division by zero
    if atr_value <= 0:
        atr_value = entry_price * 0.001  # 0.1% of price as last-resort proxy
        logger.warning(
            f"STRUCT {symbol}: using 0.1% price proxy as ATR ({atr_value:.6f})"
        )

    sl_distance = atr_value * atr_sl_mult
    tp_distance = atr_value * atr_tp_mult

    # Ensure minimum R:R even in fallback
    if sl_distance > 0 and (tp_distance / sl_distance) < min_rr:
        tp_distance = sl_distance * min_rr

    if direction == 'BUY':
        sl_price = entry_price - sl_distance
        tp_price = entry_price + tp_distance
    else:
        sl_price = entry_price + sl_distance
        tp_price = entry_price - tp_distance

    rr_ratio = round(tp_distance / sl_distance, 2) if sl_distance > 0 else min_rr

    context = (
        f"Full ATR fallback: SL={atr_sl_mult}x ATR, "
        f"TP={atr_tp_mult}x ATR (R:R={rr_ratio})"
    )

    logger.info(
        f"STRUCT LEVELS {symbol} {direction}: ATR FALLBACK "
        f"entry={entry_price:.5f} SL={sl_price:.5f} TP={tp_price:.5f} "
        f"R:R={rr_ratio}"
    )

    return {
        'sl_price': sl_price,
        'tp_price': tp_price,
        'sl_source': 'ATR_FALLBACK',
        'tp_source': 'ATR_FALLBACK',
        'rr_ratio': rr_ratio,
        'risk_distance': round(sl_distance, 6),
        'reward_distance': round(tp_distance, 6),
        'structural_context': context,
    }
