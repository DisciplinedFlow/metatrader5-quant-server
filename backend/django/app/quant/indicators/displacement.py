"""Displacement Detection — identifies institutional momentum moves.

A displacement is 3+ consecutive candles with:
- Same direction (all bullish or all bearish)
- Large bodies (body-to-range ratio > 70%)
- Creates a Fair Value Gap between candle 1 and candle 3
- Often breaks a structural level

Used as a high-conviction confirmation signal in the confluence scorer.
Livermore Ch X: "When the price line of least resistance is established, I follow it"
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger('displacement')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_strong_candle(row, body_ratio_threshold=0.70):
    """Check if a single candle shows strong conviction.

    Args:
        row: dict-like with 'open', 'high', 'low', 'close' keys (lowercase)
        body_ratio_threshold: minimum body/range ratio (default 0.70)

    Returns:
        (is_strong: bool, direction: 'bullish'/'bearish'/None, body_ratio: float)
    """
    open_p = row['open']
    high = row['high']
    low = row['low']
    close = row['close']

    candle_range = high - low
    if candle_range <= 0 or np.isnan(candle_range):
        # Zero-range candle (doji) or NaN — never strong
        return False, None, 0.0

    body = abs(close - open_p)
    body_ratio = body / candle_range

    if body_ratio < body_ratio_threshold:
        return False, None, body_ratio

    if close > open_p:
        return True, 'bullish', body_ratio
    elif close < open_p:
        return True, 'bearish', body_ratio
    else:
        # Body == 0 (open == close) — doji, not strong
        return False, None, body_ratio


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------

def detect_displacement(df, min_consecutive=3, body_ratio_threshold=0.70):
    """Detect institutional displacement moves in OHLCV data.

    A displacement is ``min_consecutive`` or more consecutive candles that are
    all strong (body/range >= threshold) and point in the same direction.
    When detected, the last candle in the sequence is marked.

    Args:
        df: DataFrame with open, high, low, close columns (lowercase)
        min_consecutive: Minimum consecutive strong candles (default 3)
        body_ratio_threshold: Minimum body/range ratio (default 0.70)

    Returns:
        DataFrame with columns:
        - displacement: 1 for bullish, -1 for bearish, 0 for none
        - displacement_strength: float (avg body ratio of the consecutive run)
        - fvg_top: top of the Fair Value Gap zone (NaN if none)
        - fvg_bottom: bottom of the Fair Value Gap zone (NaN if none)
    """
    n = len(df)
    displacement = np.zeros(n, dtype=int)
    strength = np.zeros(n, dtype=float)
    fvg_top = np.full(n, np.nan)
    fvg_bottom = np.full(n, np.nan)

    if n < min_consecutive:
        return pd.DataFrame({
            'displacement': displacement,
            'displacement_strength': strength,
            'fvg_top': fvg_top,
            'fvg_bottom': fvg_bottom,
        }, index=df.index)

    # Pre-compute per-candle strength/direction
    directions = np.zeros(n, dtype=int)   # 1=bullish, -1=bearish, 0=weak
    ratios = np.zeros(n, dtype=float)

    for i in range(n):
        row = df.iloc[i]
        is_s, direction, ratio = is_strong_candle(row, body_ratio_threshold)
        if is_s:
            directions[i] = 1 if direction == 'bullish' else -1
        ratios[i] = ratio

    # Scan for consecutive runs
    run_start = 0
    for i in range(1, n + 1):
        # Check if the run continues
        if i < n and directions[i] != 0 and directions[i] == directions[i - 1]:
            continue

        # Run ended at i-1 (or we hit the end of data)
        run_end = i - 1
        run_len = run_end - run_start + 1

        if run_len >= min_consecutive and directions[run_start] != 0:
            direction = directions[run_start]
            avg_ratio = float(np.mean(ratios[run_start:run_end + 1]))

            # Mark the last candle in the run
            displacement[run_end] = direction
            strength[run_end] = avg_ratio

            # Check for FVG within the displacement run
            # Bullish FVG: candle[j-2].high < candle[j].low (gap between C1 and C3)
            # Bearish FVG: candle[j-2].low > candle[j].high
            for j in range(run_start + 2, run_end + 1):
                c1_high = df['high'].iloc[j - 2]
                c1_low = df['low'].iloc[j - 2]
                c3_low = df['low'].iloc[j]
                c3_high = df['high'].iloc[j]

                if direction == 1 and c3_low > c1_high:
                    # Bullish FVG found — store the widest one
                    if np.isnan(fvg_top[run_end]) or (c3_low - c1_high) > (fvg_top[run_end] - fvg_bottom[run_end]):
                        fvg_top[run_end] = c3_low
                        fvg_bottom[run_end] = c1_high

                elif direction == -1 and c3_high < c1_low:
                    # Bearish FVG found
                    if np.isnan(fvg_top[run_end]) or (c1_low - c3_high) > (fvg_top[run_end] - fvg_bottom[run_end]):
                        fvg_top[run_end] = c1_low
                        fvg_bottom[run_end] = c3_high

        # Start new run
        if i < n:
            run_start = i

    return pd.DataFrame({
        'displacement': displacement,
        'displacement_strength': strength,
        'fvg_top': fvg_top,
        'fvg_bottom': fvg_bottom,
    }, index=df.index)


def detect_displacement_with_fvg(df, min_consecutive=3, body_ratio_threshold=0.70):
    """Detect displacement moves that also create a Fair Value Gap.

    A displacement with FVG is the highest-probability setup in ICT methodology.
    The FVG zone is where price is likely to retrace before continuing.

    Args:
        df: DataFrame with open, high, low, close columns (lowercase)
        min_consecutive: Minimum consecutive strong candles (default 3)
        body_ratio_threshold: Minimum body/range ratio (default 0.70)

    Returns:
        List of dicts with:
        - direction: 'bullish' or 'bearish'
        - start_idx: index of first candle in displacement
        - end_idx: index of last candle
        - strength: avg body ratio
        - fvg_zone: (top, bottom) tuple of the FVG, or None
        - structural_break: bool (did it break a recent swing high/low?)
    """
    n = len(df)
    results = []

    if n < min_consecutive:
        return results

    # Pre-compute swing points for structural break detection
    swing_highs, swing_lows = _find_displacement_swings(df, lookback=5)

    # Pre-compute per-candle strength/direction
    directions = np.zeros(n, dtype=int)
    ratios = np.zeros(n, dtype=float)

    for i in range(n):
        row = df.iloc[i]
        is_s, direction, ratio = is_strong_candle(row, body_ratio_threshold)
        if is_s:
            directions[i] = 1 if direction == 'bullish' else -1
        ratios[i] = ratio

    # Scan for consecutive runs
    run_start = 0
    for i in range(1, n + 1):
        if i < n and directions[i] != 0 and directions[i] == directions[i - 1]:
            continue

        run_end = i - 1
        run_len = run_end - run_start + 1

        if run_len >= min_consecutive and directions[run_start] != 0:
            direction = directions[run_start]
            avg_ratio = float(np.mean(ratios[run_start:run_end + 1]))

            # Find FVG within the run
            fvg_zone = None
            for j in range(run_start + 2, run_end + 1):
                c1_high = df['high'].iloc[j - 2]
                c1_low = df['low'].iloc[j - 2]
                c3_low = df['low'].iloc[j]
                c3_high = df['high'].iloc[j]

                if direction == 1 and c3_low > c1_high:
                    candidate = (c3_low, c1_high)
                    if fvg_zone is None or (candidate[0] - candidate[1]) > (fvg_zone[0] - fvg_zone[1]):
                        fvg_zone = candidate

                elif direction == -1 and c3_high < c1_low:
                    candidate = (c1_low, c3_high)
                    if fvg_zone is None or (candidate[0] - candidate[1]) > (fvg_zone[0] - fvg_zone[1]):
                        fvg_zone = candidate

            # Check structural break: did the displacement break a swing level?
            structural_break = False
            if direction == 1:
                # Bullish: check if any candle in the run closed above a prior swing high
                for j in range(run_start, run_end + 1):
                    close = df['close'].iloc[j]
                    for sh_idx in range(max(0, run_start - 20), run_start):
                        if swing_highs[sh_idx] and close > df['high'].iloc[sh_idx]:
                            structural_break = True
                            break
                    if structural_break:
                        break
            else:
                # Bearish: check if any candle closed below a prior swing low
                for j in range(run_start, run_end + 1):
                    close = df['close'].iloc[j]
                    for sl_idx in range(max(0, run_start - 20), run_start):
                        if swing_lows[sl_idx] and close < df['low'].iloc[sl_idx]:
                            structural_break = True
                            break
                    if structural_break:
                        break

            results.append({
                'direction': 'bullish' if direction == 1 else 'bearish',
                'start_idx': df.index[run_start],
                'end_idx': df.index[run_end],
                'strength': avg_ratio,
                'fvg_zone': fvg_zone,
                'structural_break': structural_break,
            })

        if i < n:
            run_start = i

    return results


def _find_displacement_swings(df, lookback=5):
    """Identify swing highs and lows for structural break detection.

    Returns two boolean arrays (swing_highs, swing_lows).
    """
    high = df['high'].values
    low = df['low'].values
    n = len(df)

    sh = np.zeros(n, dtype=bool)
    sl = np.zeros(n, dtype=bool)

    for i in range(lookback, n - lookback):
        window_h = high[i - lookback:i + lookback + 1]
        if high[i] == window_h.max() and np.sum(window_h == high[i]) == 1:
            sh[i] = True

        window_l = low[i - lookback:i + lookback + 1]
        if low[i] == window_l.min() and np.sum(window_l == low[i]) == 1:
            sl[i] = True

    return sh, sl


# ---------------------------------------------------------------------------
# INDICATOR_REGISTRY-compatible wrapper
# ---------------------------------------------------------------------------

def displacement_signal(data, params=None):
    """Return a signal Series compatible with INDICATOR_REGISTRY / CONDITION_OPS.

    Signal values: 'bullish_displacement', 'bearish_displacement', or 0.

    Params:
        min_consecutive (int):      minimum consecutive strong candles (default 3)
        body_ratio_threshold (float): minimum body/range ratio (default 0.70)
        require_fvg (bool):         only fire if displacement has an FVG (default False)
    """
    params = params or {}
    min_consecutive = params.get('min_consecutive', 3)
    body_ratio_threshold = params.get('body_ratio_threshold', 0.70)
    require_fvg = params.get('require_fvg', False)

    df = data.copy()
    result = pd.Series(0, index=df.index, dtype=object)

    disp = detect_displacement(df, min_consecutive, body_ratio_threshold)

    for i in range(len(df)):
        d = disp['displacement'].iloc[i]
        if d == 0:
            continue

        if require_fvg and np.isnan(disp['fvg_top'].iloc[i]):
            continue

        if d == 1:
            result.iloc[i] = 'bullish_displacement'
        elif d == -1:
            result.iloc[i] = 'bearish_displacement'

    return result
