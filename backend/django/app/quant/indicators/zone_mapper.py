"""Zone Mapper — FVG and Order Block detection across timeframes.

Fair Value Gap (FVG): Three-candle sequence where candle 1 high < candle 3 low (bullish)
or candle 1 low > candle 3 high (bearish). The gap is where price hasn't traded.

Order Block (OB): The last opposing candle before a strong move. Bullish OB = last
bearish candle before a strong up move. Often retested as support.

This module is a standalone, dependency-free implementation — it does NOT
require the ``smartmoneyconcepts`` third-party package (unlike
``smc_detector.py``).  This makes it suitable for the MTF context builder
where we need fast, lightweight zone detection on multiple timeframes
simultaneously.

Design principles:
- **Fail-open** — errors return empty lists.
- **Stateless** — no side-effects on the input DataFrame.
- **DEBUG logging** — these run every cycle; avoid INFO spam.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger('zone_mapper')


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FVGZone:
    """A Fair Value Gap zone."""
    start_price: float      # Lower edge of the gap
    end_price: float        # Upper edge of the gap
    direction: str          # 'bullish' or 'bearish'
    bar_index: int          # Bar index of the middle candle (candle 2)
    filled: bool = False    # Whether price has since traded through the gap
    timestamp: Optional[datetime] = None
    size: float = 0.0       # Gap size in price units


@dataclass
class OrderBlockZone:
    """An Order Block zone."""
    top: float              # Top of the OB (candle high)
    bottom: float           # Bottom of the OB (candle low)
    direction: str          # 'bullish' or 'bearish'
    bar_index: int          # Bar index of the OB candle
    mitigated: bool = False # Whether price has returned and broken through
    timestamp: Optional[datetime] = None
    strength: float = 0.0   # Move strength in ATR multiples


# ---------------------------------------------------------------------------
# ATR helper
# ---------------------------------------------------------------------------

def _calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Calculate the Average True Range for position sizing reference.

    Returns the last ATR value, or 0.0 on failure.
    """
    try:
        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)
        close = df['close'].values.astype(float)
        n = len(df)

        if n < period + 1:
            # Not enough data — use simple range
            return float(np.mean(high - low)) if n > 0 else 0.0

        tr = np.zeros(n)
        tr[0] = high[0] - low[0]
        for i in range(1, n):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )

        # Simple moving average of TR
        if n >= period:
            return float(np.mean(tr[-period:]))
        return float(np.mean(tr))

    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# 1. Fair Value Gap detection
# ---------------------------------------------------------------------------

def find_fvgs(df: pd.DataFrame) -> List[FVGZone]:
    """Detect Fair Value Gaps in OHLCV data.

    A **bullish FVG** occurs when candle_1.high < candle_3.low — there is
    a gap between candle 1's upper wick and candle 3's lower wick that
    price has not traded through.

    A **bearish FVG** occurs when candle_1.low > candle_3.high.

    After detection, each FVG is checked against subsequent price action
    to determine if it has been filled (price traded through the gap).

    Parameters
    ----------
    df : DataFrame
        OHLCV data with ``high``, ``low``, ``close`` columns (lowercase).

    Returns
    -------
    list[FVGZone]
        All detected FVGs, both filled and unfilled.
    """
    try:
        if df is None or len(df) < 3:
            return []

        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)
        n = len(df)
        has_time = 'time' in df.columns

        fvgs: List[FVGZone] = []

        for i in range(2, n):
            c1_high = high[i - 2]
            c1_low = low[i - 2]
            c3_high = high[i]
            c3_low = low[i]

            # Bullish FVG: gap between candle 1 high and candle 3 low
            if c3_low > c1_high:
                gap_bottom = c1_high
                gap_top = c3_low
                ts = df['time'].iloc[i - 1] if has_time else None

                fvg = FVGZone(
                    start_price=gap_bottom,
                    end_price=gap_top,
                    direction='bullish',
                    bar_index=i - 1,  # Middle candle
                    timestamp=ts,
                    size=gap_top - gap_bottom,
                )

                # Check if filled by subsequent price action
                for j in range(i + 1, n):
                    if low[j] <= gap_bottom:
                        fvg.filled = True
                        break

                fvgs.append(fvg)

            # Bearish FVG: gap between candle 1 low and candle 3 high
            elif c1_low > c3_high:
                gap_top = c1_low
                gap_bottom = c3_high
                ts = df['time'].iloc[i - 1] if has_time else None

                fvg = FVGZone(
                    start_price=gap_bottom,
                    end_price=gap_top,
                    direction='bearish',
                    bar_index=i - 1,
                    timestamp=ts,
                    size=gap_top - gap_bottom,
                )

                # Check if filled by subsequent price action
                for j in range(i + 1, n):
                    if high[j] >= gap_top:
                        fvg.filled = True
                        break

                fvgs.append(fvg)

        logger.debug("find_fvgs: detected %d FVGs (%d unfilled) in %d bars",
                      len(fvgs), sum(1 for f in fvgs if not f.filled), n)
        return fvgs

    except Exception:
        logger.exception("find_fvgs failed")
        return []


# ---------------------------------------------------------------------------
# 2. Order Block detection
# ---------------------------------------------------------------------------

def find_order_blocks(
    df: pd.DataFrame,
    min_move_atr: float = 1.5,
) -> List[OrderBlockZone]:
    """Detect Order Blocks in OHLCV data.

    A **bullish OB** is the last bearish (red) candle before a strong
    upward move. The OB zone is the candle's high-to-low range. The
    idea is that institutional buying absorbed the selling within that
    candle, and price will revisit the zone as support.

    A **bearish OB** is the last bullish (green) candle before a strong
    downward move.

    "Strong move" is defined as a price displacement of at least
    ``min_move_atr`` times the ATR within the next few candles.

    After detection, each OB is checked for mitigation (price returning
    through the zone and closing beyond it).

    Parameters
    ----------
    df : DataFrame
        OHLCV data with ``open``, ``high``, ``low``, ``close`` columns.
    min_move_atr : float
        Minimum displacement in ATR multiples to qualify as "strong move"
        (default 1.5).

    Returns
    -------
    list[OrderBlockZone]
        All detected OBs, both mitigated and unmitigated.
    """
    try:
        if df is None or len(df) < 5:
            return []

        open_p = df['open'].values.astype(float)
        high = df['high'].values.astype(float)
        low = df['low'].values.astype(float)
        close = df['close'].values.astype(float)
        n = len(df)
        has_time = 'time' in df.columns

        atr = _calc_atr(df)
        if atr <= 0:
            logger.debug("find_order_blocks: ATR is zero, skipping")
            return []

        min_move = atr * min_move_atr
        obs: List[OrderBlockZone] = []

        # Look-ahead window: check the next few candles for displacement
        look_ahead = 3

        for i in range(1, n - look_ahead):
            is_bearish_candle = close[i] < open_p[i]
            is_bullish_candle = close[i] > open_p[i]

            # --- Bullish OB: bearish candle followed by strong up move ---
            if is_bearish_candle:
                # Measure the upward displacement in the next few candles
                max_close_ahead = max(close[i + 1: i + 1 + look_ahead])
                move_up = max_close_ahead - close[i]

                if move_up >= min_move:
                    ts = df['time'].iloc[i] if has_time else None
                    ob = OrderBlockZone(
                        top=float(high[i]),
                        bottom=float(low[i]),
                        direction='bullish',
                        bar_index=i,
                        timestamp=ts,
                        strength=move_up / atr,
                    )

                    # Check mitigation: price returns and closes below the OB bottom
                    for j in range(i + 1 + look_ahead, n):
                        if close[j] < ob.bottom:
                            ob.mitigated = True
                            break

                    obs.append(ob)

            # --- Bearish OB: bullish candle followed by strong down move ---
            if is_bullish_candle:
                min_close_ahead = min(close[i + 1: i + 1 + look_ahead])
                move_down = close[i] - min_close_ahead

                if move_down >= min_move:
                    ts = df['time'].iloc[i] if has_time else None
                    ob = OrderBlockZone(
                        top=float(high[i]),
                        bottom=float(low[i]),
                        direction='bearish',
                        bar_index=i,
                        timestamp=ts,
                        strength=move_down / atr,
                    )

                    # Check mitigation: price returns and closes above the OB top
                    for j in range(i + 1 + look_ahead, n):
                        if close[j] > ob.top:
                            ob.mitigated = True
                            break

                    obs.append(ob)

        logger.debug("find_order_blocks: detected %d OBs (%d unmitigated) in %d bars",
                      len(obs), sum(1 for o in obs if not o.mitigated), n)
        return obs

    except Exception:
        logger.exception("find_order_blocks failed")
        return []


# ---------------------------------------------------------------------------
# 3. Zone proximity check
# ---------------------------------------------------------------------------

def check_zone_proximity(
    current_price: float,
    zones: List,
    atr: float,
    threshold_atr: float = 0.5,
) -> List[Dict]:
    """Check if current price is near any of the provided zones.

    A zone is "nearby" if the current price is within ``threshold_atr``
    ATR units of the zone's boundary.

    Parameters
    ----------
    current_price : float
        The current market price.
    zones : list
        List of ``FVGZone`` or ``OrderBlockZone`` objects.
    atr : float
        Current ATR value for distance measurement.
    threshold_atr : float
        How close price must be to a zone edge in ATR multiples (default 0.5).

    Returns
    -------
    list[dict]
        Nearby zones with distance information:
        ``{'zone': zone_dict, 'distance': float, 'distance_atr': float}``
    """
    try:
        if not zones or atr <= 0 or current_price <= 0:
            return []

        threshold = atr * threshold_atr
        nearby: List[Dict] = []

        for zone in zones:
            # Get zone boundaries
            if isinstance(zone, FVGZone):
                zone_top = zone.end_price
                zone_bottom = zone.start_price
                zone_dict = {
                    'type': 'FVG',
                    'direction': zone.direction,
                    'top': zone_top,
                    'bottom': zone_bottom,
                    'bar_index': zone.bar_index,
                    'filled': zone.filled,
                }
            elif isinstance(zone, OrderBlockZone):
                zone_top = zone.top
                zone_bottom = zone.bottom
                zone_dict = {
                    'type': 'OB',
                    'direction': zone.direction,
                    'top': zone_top,
                    'bottom': zone_bottom,
                    'bar_index': zone.bar_index,
                    'mitigated': zone.mitigated,
                    'strength': zone.strength,
                }
            else:
                continue

            # Calculate distance to zone
            if current_price > zone_top:
                distance = current_price - zone_top
            elif current_price < zone_bottom:
                distance = zone_bottom - current_price
            else:
                # Price is inside the zone
                distance = 0.0

            if distance <= threshold:
                nearby.append({
                    'zone': zone_dict,
                    'distance': distance,
                    'distance_atr': distance / atr if atr > 0 else 0.0,
                    'price_in_zone': zone_bottom <= current_price <= zone_top,
                })

        # Sort by distance (closest first)
        nearby.sort(key=lambda x: x['distance'])

        logger.debug("check_zone_proximity: %d/%d zones within %.1f ATR of %.5f",
                      len(nearby), len(zones), threshold_atr, current_price)
        return nearby

    except Exception:
        logger.exception("check_zone_proximity failed")
        return []


# ---------------------------------------------------------------------------
# 4. Zone summary
# ---------------------------------------------------------------------------

def get_zone_summary(df: pd.DataFrame, min_move_atr: float = 1.5) -> Dict:
    """Return all active (unfilled/unmitigated) FVGs and Order Blocks.

    This is the high-level function for the MTF context builder — returns
    only the zones that are still "live" and could act as entry zones.

    Parameters
    ----------
    df : DataFrame
        OHLCV data with standard lowercase columns.
    min_move_atr : float
        ATR threshold for OB detection (default 1.5).

    Returns
    -------
    dict
        {
            'active_fvgs': list[dict],    # Unfilled FVGs
            'active_obs': list[dict],     # Unmitigated OBs
            'all_fvg_count': int,
            'all_ob_count': int,
            'atr': float,
        }
    """
    empty = {
        'active_fvgs': [],
        'active_obs': [],
        'all_fvg_count': 0,
        'all_ob_count': 0,
        'atr': 0.0,
    }

    try:
        if df is None or len(df) < 5:
            return empty

        atr = _calc_atr(df)
        fvgs = find_fvgs(df)
        obs = find_order_blocks(df, min_move_atr=min_move_atr)

        # Filter to active (unfilled / unmitigated) zones
        active_fvgs = [
            {
                'start_price': f.start_price,
                'end_price': f.end_price,
                'direction': f.direction,
                'bar_index': f.bar_index,
                'size': f.size,
                'size_atr': f.size / atr if atr > 0 else 0.0,
                'timestamp': str(f.timestamp) if f.timestamp else None,
            }
            for f in fvgs if not f.filled
        ]

        active_obs = [
            {
                'top': o.top,
                'bottom': o.bottom,
                'direction': o.direction,
                'bar_index': o.bar_index,
                'strength': o.strength,
                'timestamp': str(o.timestamp) if o.timestamp else None,
            }
            for o in obs if not o.mitigated
        ]

        logger.debug("zone_summary: %d active FVGs, %d active OBs (atr=%.5f)",
                      len(active_fvgs), len(active_obs), atr)

        return {
            'active_fvgs': active_fvgs,
            'active_obs': active_obs,
            'all_fvg_count': len(fvgs),
            'all_ob_count': len(obs),
            'atr': atr,
        }

    except Exception:
        logger.exception("get_zone_summary failed")
        return empty
