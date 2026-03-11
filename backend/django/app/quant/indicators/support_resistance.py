"""
Support & Resistance Detection — price structure awareness for dynamic TP/SL.

Identifies key price levels where supply/demand imbalances exist, using:
1. Swing point detection (local highs/lows with configurable lookback)
2. Level clustering (group nearby swings within ATR distance)
3. Multi-timeframe confirmation (H1/H4 levels are stronger than M15)
4. Touch-count scoring (more bounces = stronger level)

Used by:
- Entry algorithm: place TP at next resistance, SL below nearest support
- Position manager: trail SL along structural levels instead of fixed ATR
"""

import numpy as np
import pandas as pd
import logging

logger = logging.getLogger('app.quant.indicators.sr')


def find_sr_levels(df, atr_val, lookback=5, max_levels=10):
    """Find support and resistance levels from OHLC data.

    Args:
        df: DataFrame with 'high', 'low', 'close', 'time' columns
        atr_val: Current ATR value (used for clustering distance)
        lookback: Bars on each side for swing detection (higher = fewer, stronger levels)
        max_levels: Maximum number of levels to return per side

    Returns:
        dict with 'support' and 'resistance' lists, each containing
        dicts with 'price', 'strength', 'touches', 'recency' keys,
        sorted by strength (strongest first).
    """
    if df is None or len(df) < (2 * lookback + 1):
        return {'support': [], 'resistance': []}

    highs = df['high'].values
    lows = df['low'].values
    n = len(df)

    # Clustering distance: levels within 0.5 ATR of each other merge
    cluster_dist = atr_val * 0.5 if atr_val > 0 else 0

    # --- Find swing highs (resistance candidates) ---
    swing_highs = []
    for i in range(lookback, n - lookback):
        window = highs[i - lookback:i + lookback + 1]
        if not np.isnan(highs[i]) and highs[i] == np.nanmax(window):
            swing_highs.append({'price': float(highs[i]), 'bar_idx': i})

    # --- Find swing lows (support candidates) ---
    swing_lows = []
    for i in range(lookback, n - lookback):
        window = lows[i - lookback:i + lookback + 1]
        if not np.isnan(lows[i]) and lows[i] == np.nanmin(window):
            swing_lows.append({'price': float(lows[i]), 'bar_idx': i})

    # --- Cluster and score ---
    resistance = _cluster_levels(swing_highs, cluster_dist, n)
    support = _cluster_levels(swing_lows, cluster_dist, n)

    # Sort by strength and limit
    resistance.sort(key=lambda x: x['strength'], reverse=True)
    support.sort(key=lambda x: x['strength'], reverse=True)

    return {
        'support': support[:max_levels],
        'resistance': resistance[:max_levels],
    }


def get_dynamic_sl_tp(entry_price, order_type, sr_levels, atr_val,
                      min_rr=1.5, sl_buffer_atr=0.3):
    """Calculate dynamic SL and TP based on support/resistance levels.

    Args:
        entry_price: The entry price
        order_type: 'BUY' or 'SELL'
        sr_levels: Output from find_sr_levels()
        atr_val: Current ATR value
        min_rr: Minimum reward:risk ratio required (default 1.5)
        sl_buffer_atr: ATR fraction buffer beyond the S/R level for SL

    Returns:
        dict with 'sl', 'tp', 'rr_ratio', 'sl_source', 'tp_source',
        or None if no valid S/R levels found (caller should fall back to ATR-based).
    """
    supports = sr_levels.get('support', [])
    resistances = sr_levels.get('resistance', [])
    buffer = atr_val * sl_buffer_atr

    if order_type == 'BUY':
        # SL: nearest support BELOW entry
        sl_candidates = [s for s in supports if s['price'] < entry_price - buffer * 0.5]
        # TP: nearest resistance ABOVE entry
        tp_candidates = [r for r in resistances if r['price'] > entry_price + atr_val * 0.5]

        if not sl_candidates or not tp_candidates:
            return None

        # Best SL: closest support below (least risk)
        sl_candidates.sort(key=lambda x: x['price'], reverse=True)  # highest first = closest to entry
        best_sl = sl_candidates[0]
        sl_price = best_sl['price'] - buffer

        # Best TP: pick the first resistance that gives us min_rr
        tp_candidates.sort(key=lambda x: x['price'])  # lowest first = closest above
        sl_distance = entry_price - sl_price
        best_tp = None
        for tp_cand in tp_candidates:
            tp_distance = tp_cand['price'] - entry_price
            rr = tp_distance / sl_distance if sl_distance > 0 else 0
            if rr >= min_rr:
                best_tp = tp_cand
                break

        # If no single level gives min_rr, try the strongest (furthest) resistance
        if best_tp is None and tp_candidates:
            best_tp = max(tp_candidates, key=lambda x: x['strength'])
            tp_distance = best_tp['price'] - entry_price
            rr = tp_distance / sl_distance if sl_distance > 0 else 0
            if rr < min_rr:
                return None  # Can't achieve min R:R

        if best_tp is None:
            return None

        tp_price = best_tp['price']
        rr_ratio = (tp_price - entry_price) / sl_distance if sl_distance > 0 else 0

    else:  # SELL
        # SL: nearest resistance ABOVE entry
        sl_candidates = [r for r in resistances if r['price'] > entry_price + buffer * 0.5]
        # TP: nearest support BELOW entry
        tp_candidates = [s for s in supports if s['price'] < entry_price - atr_val * 0.5]

        if not sl_candidates or not tp_candidates:
            return None

        # Best SL: closest resistance above (least risk)
        sl_candidates.sort(key=lambda x: x['price'])  # lowest first = closest to entry
        best_sl = sl_candidates[0]
        sl_price = best_sl['price'] + buffer

        # Best TP: pick the first support that gives us min_rr
        tp_candidates.sort(key=lambda x: x['price'], reverse=True)  # highest first = closest below
        sl_distance = sl_price - entry_price
        best_tp = None
        for tp_cand in tp_candidates:
            tp_distance = entry_price - tp_cand['price']
            rr = tp_distance / sl_distance if sl_distance > 0 else 0
            if rr >= min_rr:
                best_tp = tp_cand
                break

        if best_tp is None and tp_candidates:
            best_tp = max(tp_candidates, key=lambda x: x['strength'])
            tp_distance = entry_price - best_tp['price']
            rr = tp_distance / sl_distance if sl_distance > 0 else 0
            if rr < min_rr:
                return None

        if best_tp is None:
            return None

        tp_price = best_tp['price']
        rr_ratio = (entry_price - tp_price) / sl_distance if sl_distance > 0 else 0

    return {
        'sl': sl_price,
        'tp': tp_price,
        'rr_ratio': round(rr_ratio, 2),
        'sl_source': f"S/R {best_sl['price']:.5f} ({best_sl['touches']}T, str={best_sl['strength']:.1f})",
        'tp_source': f"S/R {best_tp['price']:.5f} ({best_tp['touches']}T, str={best_tp['strength']:.1f})",
    }


def find_multi_tf_sr(symbol, fetch_fn, atr_val, timeframes=None):
    """Find S/R levels across multiple timeframes and merge.

    Higher timeframe levels get a strength bonus since they represent
    more significant supply/demand zones.

    Args:
        symbol: Trading pair
        fetch_fn: Function(symbol, timeframe, bars) -> DataFrame
        atr_val: ATR from the entry timeframe
        timeframes: List of (MT5Timeframe, weight, lookback, bars) tuples

    Returns:
        Same format as find_sr_levels() but with multi-TF merged levels.
    """
    from app.utils.constants import MT5Timeframe

    if timeframes is None:
        timeframes = [
            (MT5Timeframe.M15, 1.0, 3, 100),   # Entry TF: many levels, lower weight
            (MT5Timeframe.H1,  2.0, 5, 100),    # Higher TF: fewer, stronger levels
            (MT5Timeframe.H4,  3.0, 5, 100),    # Highest TF: major levels only
        ]

    all_supports = []
    all_resistances = []

    for tf, weight, lookback, bars in timeframes:
        df = fetch_fn(symbol, tf, bars)
        if df is None or len(df) < 20:
            continue

        levels = find_sr_levels(df, atr_val, lookback=lookback)

        for s in levels['support']:
            s['strength'] *= weight
            s['timeframe'] = tf.value if hasattr(tf, 'value') else str(tf)
            all_supports.append(s)

        for r in levels['resistance']:
            r['strength'] *= weight
            r['timeframe'] = tf.value if hasattr(tf, 'value') else str(tf)
            all_resistances.append(r)

    # Merge levels across timeframes (cluster nearby levels)
    cluster_dist = atr_val * 0.5
    merged_support = _cluster_levels(
        [{'price': s['price'], 'bar_idx': 0, 'strength': s['strength']} for s in all_supports],
        cluster_dist, 1, pre_scored=True,
    )
    merged_resistance = _cluster_levels(
        [{'price': r['price'], 'bar_idx': 0, 'strength': r['strength']} for r in all_resistances],
        cluster_dist, 1, pre_scored=True,
    )

    merged_support.sort(key=lambda x: x['strength'], reverse=True)
    merged_resistance.sort(key=lambda x: x['strength'], reverse=True)

    return {
        'support': merged_support[:10],
        'resistance': merged_resistance[:10],
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cluster_levels(swing_points, cluster_dist, total_bars, pre_scored=False):
    """Cluster nearby swing points into S/R levels.

    Points within cluster_dist of each other are merged. Each cluster
    is scored by:
    - touches: how many swing points formed at this level
    - recency: more recent touches score higher
    - strength: combined score for ranking
    """
    if not swing_points:
        return []

    # Sort by price
    sorted_points = sorted(swing_points, key=lambda x: x['price'])

    clusters = []
    current_cluster = [sorted_points[0]]

    for point in sorted_points[1:]:
        if cluster_dist > 0 and abs(point['price'] - current_cluster[-1]['price']) <= cluster_dist:
            current_cluster.append(point)
        else:
            clusters.append(current_cluster)
            current_cluster = [point]
    clusters.append(current_cluster)

    # Score each cluster
    levels = []
    for cluster in clusters:
        avg_price = sum(p['price'] for p in cluster) / len(cluster)
        touches = len(cluster)

        if pre_scored:
            # Already has strength from multi-TF weighting
            strength = sum(p.get('strength', 1) for p in cluster)
        else:
            # Recency: most recent bar index gets highest weight
            max_idx = max(p['bar_idx'] for p in cluster)
            recency = max_idx / total_bars if total_bars > 0 else 0.5

            # Strength = touches × recency_bonus
            # A level with 3 touches near the end of data is very strong
            strength = touches * (0.5 + recency)

        levels.append({
            'price': round(avg_price, 6),
            'touches': touches,
            'strength': round(strength, 2),
            'recency': round(max(p.get('bar_idx', 0) for p in cluster) / total_bars, 2) if total_bars > 0 and not pre_scored else 0.5,
        })

    return levels
