"""
Fibonacci retracement and extension calculator for dynamic TP targets.

Uses ZigZag algorithm to detect swing highs/lows, then calculates:
- Retracement levels: 0.236, 0.382, 0.5, 0.618, 0.786
- Extension levels: 1.272, 1.618, 2.618

Usage: Calculate TP targets at Fib extension levels instead of fixed percentages.
The exit algorithm can then use these as dynamic TP zones.
"""
import logging

logger = logging.getLogger('app.lighter')

# Standard Fibonacci ratios
RETRACEMENT_LEVELS = (0.236, 0.382, 0.5, 0.618, 0.786)
EXTENSION_LEVELS = (1.272, 1.618, 2.618)


def detect_swing_points(candles, min_deviation_pct=0.5, depth=10):
    """ZigZag algorithm — detect significant swing highs and lows.

    Args:
        candles: list of dicts with keys 'h' (high) and 'l' (low).
        min_deviation_pct: minimum price change (%) to qualify as a new swing.
            0.5% is suitable for 5m crypto; tighter assets may need smaller values.
        depth: minimum number of bars between consecutive swing points.

    Returns:
        list of (index, price, type) tuples where type is 'high' or 'low',
        ordered chronologically (oldest first).
    """
    if not candles or len(candles) < depth * 2:
        return []

    highs = [float(c['h']) for c in candles]
    lows = [float(c['l']) for c in candles]
    n = len(candles)
    min_dev = min_deviation_pct / 100.0

    swings = []

    # Seed: find the first significant extreme in the opening window
    first_high_idx = max(range(depth), key=lambda i: highs[i])
    first_low_idx = min(range(depth), key=lambda i: lows[i])

    if first_high_idx <= first_low_idx:
        # Start with the high, then look for alternating swings
        swings.append((first_high_idx, highs[first_high_idx], 'high'))
    else:
        swings.append((first_low_idx, lows[first_low_idx], 'low'))

    i = swings[0][0] + 1

    while i < n:
        last_idx, last_price, last_type = swings[-1]

        if last_type == 'high':
            # Looking for the next swing low
            # Scan for the lowest low in the next window
            window_end = min(i + depth, n)
            if window_end <= i:
                break
            local_low_offset = min(range(window_end - i), key=lambda j: lows[i + j])
            local_low_idx = i + local_low_offset
            local_low = lows[local_low_idx]

            deviation = (last_price - local_low) / last_price
            if deviation >= min_dev and (local_low_idx - last_idx) >= depth:
                swings.append((local_low_idx, local_low, 'low'))
                i = local_low_idx + 1
            else:
                # Check if current bar makes a higher high — extend the last swing
                if highs[i] > last_price:
                    swings[-1] = (i, highs[i], 'high')
                i += 1
        else:
            # Looking for the next swing high
            window_end = min(i + depth, n)
            if window_end <= i:
                break
            local_high_offset = max(range(window_end - i), key=lambda j: highs[i + j])
            local_high_idx = i + local_high_offset
            local_high = highs[local_high_idx]

            deviation = (local_high - last_price) / last_price if last_price else 0
            if deviation >= min_dev and (local_high_idx - last_idx) >= depth:
                swings.append((local_high_idx, local_high, 'high'))
                i = local_high_idx + 1
            else:
                # Check if current bar makes a lower low — extend the last swing
                if lows[i] < last_price:
                    swings[-1] = (i, lows[i], 'low')
                i += 1

    return swings


def calculate_fib_levels(swing_high, swing_low, direction='up'):
    """Calculate Fibonacci retracement levels between two swing points.

    Args:
        swing_high: the higher price point.
        swing_low: the lower price point.
        direction: 'up' = uptrend (retracement measured from high back toward low),
                   'down' = downtrend (retracement measured from low back toward high).

    Returns:
        dict mapping level label (str) to price (float).
        For 'up': levels are below swing_high (potential support).
        For 'down': levels are above swing_low (potential resistance).
    """
    diff = swing_high - swing_low
    if diff <= 0:
        return {}

    levels = {}
    for ratio in RETRACEMENT_LEVELS:
        label = str(ratio)
        if direction == 'up':
            # Retracement from high toward low (support zones)
            levels[label] = swing_high - diff * ratio
        else:
            # Retracement from low toward high (resistance zones)
            levels[label] = swing_low + diff * ratio
    return levels


def calculate_fib_extensions(swing_high, swing_low, direction='up'):
    """Calculate Fibonacci extension levels beyond the swing range.

    These are proven take-profit targets (1.272, 1.618, 2.618 extensions).

    Args:
        swing_high: the higher price point.
        swing_low: the lower price point.
        direction: 'up' = extensions above swing_high (long TP targets),
                   'down' = extensions below swing_low (short TP targets).

    Returns:
        dict mapping level label (str) to price (float).
    """
    diff = swing_high - swing_low
    if diff <= 0:
        return {}

    levels = {}
    for ratio in EXTENSION_LEVELS:
        label = str(ratio)
        if direction == 'up':
            # Project above swing_low by ratio * range
            levels[label] = swing_low + diff * ratio
        else:
            # Project below swing_high by ratio * range
            levels[label] = swing_high - diff * ratio
    return levels


def get_fib_tp_targets(candles, direction, min_deviation_pct=0.5, depth=10):
    """Main function for the exit algorithm — compute Fib extension TP targets.

    Detects the most recent swing high/low pair from candle data, then
    calculates extension levels in the trade direction.

    Args:
        candles: list of candle dicts (keys: 'h', 'l', at minimum).
        direction: 'up' for long positions, 'down' for short positions.
        min_deviation_pct: ZigZag sensitivity (default 0.5% for 5m crypto).
        depth: minimum bars between swing points.

    Returns:
        list of (price, label) tuples sorted by distance from current price
        (nearest first). Empty list if insufficient swing data.
    """
    swings = detect_swing_points(candles, min_deviation_pct=min_deviation_pct, depth=depth)

    if len(swings) < 2:
        return []

    # Find the most recent swing high and swing low
    recent_high = None
    recent_low = None
    for idx, price, swing_type in reversed(swings):
        if swing_type == 'high' and recent_high is None:
            recent_high = price
        elif swing_type == 'low' and recent_low is None:
            recent_low = price
        if recent_high is not None and recent_low is not None:
            break

    if recent_high is None or recent_low is None:
        return []

    if recent_high <= recent_low:
        return []

    extensions = calculate_fib_extensions(recent_high, recent_low, direction=direction)
    if not extensions:
        return []

    # Sort by distance from current price (use last candle close as reference)
    current_price = float(candles[-1]['c']) if candles else 0
    targets = [(price, f'fib_{label}') for label, price in extensions.items()]

    if direction == 'up':
        # For longs, only include targets above current price
        targets = [(p, lbl) for p, lbl in targets if p > current_price]
        targets.sort(key=lambda t: t[0])  # nearest first
    else:
        # For shorts, only include targets below current price
        targets = [(p, lbl) for p, lbl in targets if p < current_price]
        targets.sort(key=lambda t: t[0], reverse=True)  # nearest first (highest below)

    return targets
