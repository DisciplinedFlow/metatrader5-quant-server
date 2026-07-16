"""Market Structure Analysis — HH, HL, LH, LL, BOS, CHoCH detection.

Reads price action like a human trader:
- Identifies swing highs and swing lows using pivot detection
- Labels them as HH (Higher High), HL (Higher Low), LH (Lower High), LL (Lower Low)
- Detects BOS (Break of Structure) — trend continuation
- Detects CHoCH (Change of Character) — potential trend reversal
- Determines trend phase: IMPULSE, CORRECTION, RANGE, REVERSAL

Approach mirrors the TradingView "Market Structure" indicator logic:
a swing high is a bar whose high is higher than the ``lookback`` bars on
both sides; a swing low is a bar whose low is lower than the ``lookback``
bars on both sides.

Design principles:
- **Fail-open** — errors return empty / neutral results.
- **Stateless** — no side-effects on the input DataFrame.
- **DEBUG logging** — these run every cycle; avoid INFO spam.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger('market_structure')


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SwingPoint:
    """A single swing high or swing low."""
    index: int          # Bar index within the DataFrame
    price: float        # High value (swing high) or Low value (swing low)
    swing_type: str     # 'high' or 'low'
    timestamp: Optional[datetime] = None
    label: str = ''     # HH, HL, LH, LL — filled by label_structure()


@dataclass
class StructureBreak:
    """A Break of Structure (BOS) or Change of Character (CHoCH)."""
    index: int              # Bar index where the break occurred
    break_type: str         # 'BOS' or 'CHoCH'
    direction: str          # 'bullish' or 'bearish'
    level: float            # The swing level that was broken
    timestamp: Optional[datetime] = None


# ---------------------------------------------------------------------------
# 1. Swing point detection
# ---------------------------------------------------------------------------

def find_swing_points(df: pd.DataFrame, lookback: int = 5) -> List[SwingPoint]:
    """Find swing highs and swing lows using pivot detection.

    A swing high at index *i* requires ``high[i]`` to be strictly the
    maximum of ``high[i-lookback : i+lookback+1]`` (the bar must be
    unique — no ties within the window).  Swing lows are analogous.

    Parameters
    ----------
    df : DataFrame
        OHLCV data with at least ``high``, ``low`` columns (lowercase).
    lookback : int
        Number of bars on each side to confirm a swing (default 5).

    Returns
    -------
    list[SwingPoint]
        Chronologically ordered list of swing highs and lows.
    """
    try:
        if df is None or len(df) < lookback * 2 + 1:
            logger.debug("find_swing_points: insufficient data (%d bars, need %d)",
                         len(df) if df is not None else 0, lookback * 2 + 1)
            return []

        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)
        n = len(df)

        has_time = 'time' in df.columns

        swings: List[SwingPoint] = []

        for i in range(lookback, n - lookback):
            # --- Swing High ---
            window_h = high[i - lookback: i + lookback + 1]
            if high[i] == window_h.max() and np.sum(window_h == high[i]) == 1:
                ts = df['time'].iloc[i] if has_time else None
                swings.append(SwingPoint(
                    index=i,
                    price=float(high[i]),
                    swing_type='high',
                    timestamp=ts,
                ))

            # --- Swing Low ---
            window_l = low[i - lookback: i + lookback + 1]
            if low[i] == window_l.min() and np.sum(window_l == low[i]) == 1:
                ts = df['time'].iloc[i] if has_time else None
                swings.append(SwingPoint(
                    index=i,
                    price=float(low[i]),
                    swing_type='low',
                    timestamp=ts,
                ))

        # Sort by bar index (stable for same-bar high+low)
        swings.sort(key=lambda s: s.index)

        logger.debug("find_swing_points: found %d swings in %d bars (lookback=%d)",
                      len(swings), n, lookback)
        return swings

    except Exception:
        logger.exception("find_swing_points failed")
        return []


# ---------------------------------------------------------------------------
# 2. Label structure — HH, HL, LH, LL
# ---------------------------------------------------------------------------

def label_structure(swings: List[SwingPoint]) -> List[SwingPoint]:
    """Label each swing point as HH, HL, LH, or LL relative to its predecessor.

    Comparison rules:
    - A swing high is compared to the previous swing high:
      HH if price > previous swing high, else LH.
    - A swing low is compared to the previous swing low:
      HL if price > previous swing low, else LL.

    The first swing of each type is labelled with a bare 'H' or 'L'
    (no predecessor to compare against).

    Parameters
    ----------
    swings : list[SwingPoint]
        Chronologically ordered swing points (from ``find_swing_points``).

    Returns
    -------
    list[SwingPoint]
        The same list with ``.label`` populated on each point.
    """
    try:
        if not swings:
            return swings

        last_swing_high: Optional[SwingPoint] = None
        last_swing_low: Optional[SwingPoint] = None

        for sp in swings:
            if sp.swing_type == 'high':
                if last_swing_high is None:
                    sp.label = 'H'
                elif sp.price > last_swing_high.price:
                    sp.label = 'HH'
                else:
                    sp.label = 'LH'
                last_swing_high = sp

            elif sp.swing_type == 'low':
                if last_swing_low is None:
                    sp.label = 'L'
                elif sp.price > last_swing_low.price:
                    sp.label = 'HL'
                else:
                    sp.label = 'LL'
                last_swing_low = sp

        return swings

    except Exception:
        logger.exception("label_structure failed")
        return swings


# ---------------------------------------------------------------------------
# 3. BOS and CHoCH detection
# ---------------------------------------------------------------------------

def detect_bos_choch(
    labeled_swings: List[SwingPoint],
    df: Optional[pd.DataFrame] = None,
) -> List[StructureBreak]:
    """Detect Break of Structure (BOS) and Change of Character (CHoCH).

    Logic (mirroring TradingView Market Structure indicator):

    **Uptrend context** (established when we have HH + HL):
    - BOS (bullish): price breaks above the last swing high → continuation.
    - CHoCH (bearish): price breaks below the last swing low → potential reversal.

    **Downtrend context** (established when we have LH + LL):
    - BOS (bearish): price breaks below the last swing low → continuation.
    - CHoCH (bullish): price breaks above the last swing high → potential reversal.

    When *df* is provided, the break is confirmed by checking whether any
    bar's close actually crossed the level.  Without *df*, we rely solely
    on the swing labels (HH/HL/LH/LL) to infer breaks.

    Parameters
    ----------
    labeled_swings : list[SwingPoint]
        Swing points with ``.label`` populated (from ``label_structure``).
    df : DataFrame, optional
        The original OHLCV data, used for close-based break confirmation.

    Returns
    -------
    list[StructureBreak]
        Chronologically ordered structure breaks.
    """
    try:
        if not labeled_swings or len(labeled_swings) < 3:
            return []

        breaks: List[StructureBreak] = []

        # Track the current market context from swing labels
        # We need at least a pair of (high, low) labels to establish context
        context = 'unknown'  # 'uptrend', 'downtrend', 'unknown'

        # Track last key swing levels
        last_sh: Optional[SwingPoint] = None  # last swing high
        last_sl: Optional[SwingPoint] = None  # last swing low

        close = df['close'].values.astype(float) if df is not None else None
        high_arr = df['high'].values.astype(float) if df is not None else None
        low_arr = df['low'].values.astype(float) if df is not None else None
        has_time = df is not None and 'time' in df.columns

        for sp in labeled_swings:
            # Update context based on consecutive labels
            if sp.swing_type == 'high':
                if sp.label in ('HH', 'H'):
                    # Bullish swing high — if we had HL before, uptrend
                    if last_sl is not None and last_sl.label in ('HL', 'L'):
                        context = 'uptrend'
                elif sp.label == 'LH':
                    # Lower high — if preceded by LL, downtrend
                    if last_sl is not None and last_sl.label == 'LL':
                        context = 'downtrend'

            elif sp.swing_type == 'low':
                if sp.label in ('HL', 'L'):
                    if last_sh is not None and last_sh.label in ('HH', 'H'):
                        context = 'uptrend'
                elif sp.label == 'LL':
                    if last_sh is not None and last_sh.label in ('LH',):
                        context = 'downtrend'

            # Now check for breaks using the swing itself
            if sp.swing_type == 'high' and last_sh is not None:
                if context == 'uptrend' and sp.label == 'HH':
                    # BOS (bullish) — broke above last swing high in uptrend
                    _add_break(breaks, sp, last_sh, 'BOS', 'bullish',
                               close, high_arr, has_time, df)

                elif context == 'downtrend' and sp.label == 'HH':
                    # CHoCH (bullish) — broke above last swing high in downtrend
                    _add_break(breaks, sp, last_sh, 'CHoCH', 'bullish',
                               close, high_arr, has_time, df)

            elif sp.swing_type == 'low' and last_sl is not None:
                if context == 'downtrend' and sp.label == 'LL':
                    # BOS (bearish) — broke below last swing low in downtrend
                    _add_break(breaks, sp, last_sl, 'BOS', 'bearish',
                               close, low_arr, has_time, df)

                elif context == 'uptrend' and sp.label == 'LL':
                    # CHoCH (bearish) — broke below last swing low in uptrend
                    _add_break(breaks, sp, last_sl, 'CHoCH', 'bearish',
                               close, low_arr, has_time, df)

            # Update last swing references
            if sp.swing_type == 'high':
                last_sh = sp
            else:
                last_sl = sp

        logger.debug("detect_bos_choch: found %d structure breaks", len(breaks))
        return breaks

    except Exception:
        logger.exception("detect_bos_choch failed")
        return []


def _add_break(
    breaks: List[StructureBreak],
    current_swing: SwingPoint,
    reference_swing: SwingPoint,
    break_type: str,
    direction: str,
    close: Optional[np.ndarray],
    price_arr: Optional[np.ndarray],
    has_time: bool,
    df: Optional[pd.DataFrame],
) -> None:
    """Helper to add a structure break, optionally confirming via close."""
    # Determine the level that was broken
    level = reference_swing.price

    # Find the bar where the break actually occurred
    break_index = current_swing.index

    if close is not None:
        # Look for the first bar after the reference swing that closed past the level
        start = reference_swing.index + 1
        end = min(current_swing.index + 1, len(close))
        for i in range(start, end):
            if direction == 'bullish' and close[i] > level:
                break_index = i
                break
            elif direction == 'bearish' and close[i] < level:
                break_index = i
                break

    ts = None
    if has_time and df is not None and break_index < len(df):
        ts = df['time'].iloc[break_index]

    breaks.append(StructureBreak(
        index=break_index,
        break_type=break_type,
        direction=direction,
        level=level,
        timestamp=ts,
    ))


# ---------------------------------------------------------------------------
# 4. Trend phase detection
# ---------------------------------------------------------------------------

def get_trend_phase(df: pd.DataFrame, lookback: int = 5) -> str:
    """Determine the current market phase from price structure.

    Phases:
    - ``UPTREND``: Most recent swings show HH + HL pattern.
    - ``DOWNTREND``: Most recent swings show LH + LL pattern.
    - ``RANGE``: Mixed structure — no clear directional bias.
    - ``REVERSAL``: Recent CHoCH detected (trend changing).

    Parameters
    ----------
    df : DataFrame
        OHLCV data with ``high``, ``low`` columns.
    lookback : int
        Swing detection lookback (default 5).

    Returns
    -------
    str
        One of ``'UPTREND'``, ``'DOWNTREND'``, ``'RANGE'``, ``'REVERSAL'``.
    """
    try:
        if df is None or len(df) < lookback * 2 + 3:
            return 'RANGE'

        swings = find_swing_points(df, lookback=lookback)
        if len(swings) < 3:
            return 'RANGE'

        swings = label_structure(swings)
        breaks = detect_bos_choch(swings, df)

        # Check for recent CHoCH — if there's one in the last quarter of
        # the data, we're in a reversal phase
        n = len(df)
        recent_cutoff = int(n * 0.75)

        recent_choch = [b for b in breaks
                        if b.break_type == 'CHoCH' and b.index >= recent_cutoff]
        if recent_choch:
            return 'REVERSAL'

        # Determine trend from the last few swing labels
        recent_swings = swings[-6:]  # Last 6 swings for context

        high_labels = [s.label for s in recent_swings if s.swing_type == 'high']
        low_labels = [s.label for s in recent_swings if s.swing_type == 'low']

        # Count HH/LH and HL/LL
        hh_count = sum(1 for l in high_labels if l == 'HH')
        lh_count = sum(1 for l in high_labels if l == 'LH')
        hl_count = sum(1 for l in low_labels if l == 'HL')
        ll_count = sum(1 for l in low_labels if l == 'LL')

        bullish_score = hh_count + hl_count
        bearish_score = lh_count + ll_count

        if bullish_score >= 2 and bullish_score > bearish_score:
            return 'UPTREND'
        elif bearish_score >= 2 and bearish_score > bullish_score:
            return 'DOWNTREND'
        else:
            return 'RANGE'

    except Exception:
        logger.exception("get_trend_phase failed")
        return 'RANGE'


# ---------------------------------------------------------------------------
# 5. Complete structure summary
# ---------------------------------------------------------------------------

def get_structure_summary(df: pd.DataFrame, lookback: int = 5) -> Dict:
    """Return a comprehensive market structure summary.

    This is the high-level function that other modules call to get a
    complete picture of market structure on a single timeframe.

    Parameters
    ----------
    df : DataFrame
        OHLCV data with ``high``, ``low``, ``close`` columns.
    lookback : int
        Swing detection lookback (default 5).

    Returns
    -------
    dict
        {
            'trend_phase': str,          # UPTREND, DOWNTREND, RANGE, REVERSAL
            'swing_points': list[dict],  # Recent swings with labels
            'structure_breaks': list[dict],  # BOS/CHoCH events
            'last_swing_high': dict|None,
            'last_swing_low': dict|None,
            'swing_count': int,
        }
    """
    empty = {
        'trend_phase': 'RANGE',
        'swing_points': [],
        'structure_breaks': [],
        'last_swing_high': None,
        'last_swing_low': None,
        'swing_count': 0,
    }

    try:
        if df is None or len(df) < lookback * 2 + 3:
            return empty

        swings = find_swing_points(df, lookback=lookback)
        if not swings:
            return empty

        swings = label_structure(swings)
        breaks = detect_bos_choch(swings, df)
        phase = get_trend_phase(df, lookback=lookback)

        # Serialise swing points
        swing_dicts = [
            {
                'index': s.index,
                'price': s.price,
                'type': s.swing_type,
                'label': s.label,
                'timestamp': str(s.timestamp) if s.timestamp else None,
            }
            for s in swings
        ]

        # Serialise structure breaks
        break_dicts = [
            {
                'index': b.index,
                'break_type': b.break_type,
                'direction': b.direction,
                'level': b.level,
                'timestamp': str(b.timestamp) if b.timestamp else None,
            }
            for b in breaks
        ]

        # Find last swing high / low
        last_sh = None
        last_sl = None
        for s in reversed(swings):
            if s.swing_type == 'high' and last_sh is None:
                last_sh = {
                    'index': s.index, 'price': s.price, 'label': s.label,
                    'timestamp': str(s.timestamp) if s.timestamp else None,
                }
            elif s.swing_type == 'low' and last_sl is None:
                last_sl = {
                    'index': s.index, 'price': s.price, 'label': s.label,
                    'timestamp': str(s.timestamp) if s.timestamp else None,
                }
            if last_sh and last_sl:
                break

        logger.debug(
            "structure_summary: phase=%s, swings=%d, breaks=%d",
            phase, len(swings), len(breaks),
        )

        return {
            'trend_phase': phase,
            'swing_points': swing_dicts,
            'structure_breaks': break_dicts,
            'last_swing_high': last_sh,
            'last_swing_low': last_sl,
            'swing_count': len(swings),
        }

    except Exception:
        logger.exception("get_structure_summary failed")
        return empty
