"""Smart Money Concepts (SMC) indicators.

Implements ICT/TJR-style price action analysis:
- Market Structure: Break of Structure (BOS) and Change of Character (CHoCH)
- Fair Value Gaps (FVG): 3-candle imbalances where price hasn't traded
- Order Blocks: Last opposing candle before an impulsive institutional move
- Liquidity Sweeps: Stop hunts beyond swing points with immediate reversal
- SMC Confluence: Combined signal requiring 2+ aligned concepts

All functions return a pandas Series of signal strings or 0, compatible
with the INDICATOR_REGISTRY / CONDITION_OPS system.
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _find_swing_points(df, lookback=5):
    """Identify swing highs and swing lows using a rolling window.

    A swing high is confirmed when its high is the strict maximum in a window
    of ``lookback`` bars on each side.  Same logic (minimum) for swing lows.

    Returns (swing_highs, swing_lows) — two boolean Series.
    """
    high = df['high'].values
    low = df['low'].values
    n = len(df)

    sh = np.zeros(n, dtype=bool)
    sl = np.zeros(n, dtype=bool)

    for i in range(lookback, n - lookback):
        # Swing high: highest in window, unique maximum
        window_h = high[i - lookback:i + lookback + 1]
        if high[i] == window_h.max() and np.sum(window_h == high[i]) == 1:
            sh[i] = True

        # Swing low: lowest in window, unique minimum
        window_l = low[i - lookback:i + lookback + 1]
        if low[i] == window_l.min() and np.sum(window_l == low[i]) == 1:
            sl[i] = True

    return pd.Series(sh, index=df.index), pd.Series(sl, index=df.index)


# ---------------------------------------------------------------------------
# 1. Market Structure — BOS / CHoCH
# ---------------------------------------------------------------------------

def market_structure(data, params=None):
    """Detect Break of Structure (BOS) and Change of Character (CHoCH).

    Trend is inferred from the last two swing highs and swing lows:
    - Uptrend: higher highs + higher lows (HH / HL)
    - Downtrend: lower highs + lower lows (LH / LL)

    Signals:
    - bullish_bos  — uptrend continuation (close breaks above last swing high)
    - bearish_bos  — downtrend continuation (close breaks below last swing low)
    - bullish_choch — reversal: downtrend broken (close above last lower high)
    - bearish_choch — reversal: uptrend broken (close below last higher low)

    Params:
        swing_lookback (int): bars on each side for swing detection (default 5)
    """
    params = params or {}
    swing_lookback = params.get('swing_lookback', 5)

    df = data.copy()
    result = pd.Series(0, index=df.index, dtype=object)

    swing_highs, swing_lows = _find_swing_points(df, swing_lookback)

    # Collect confirmed swing prices in chronological order
    sh_list = []  # (bar_position, price)
    sl_list = []

    for i in range(len(df)):
        if swing_highs.iloc[i]:
            sh_list.append((i, df['high'].iloc[i]))
        if swing_lows.iloc[i]:
            sl_list.append((i, df['low'].iloc[i]))

        # Need at least 2 of each to determine trend
        if len(sh_list) < 2 or len(sl_list) < 2:
            continue

        close = df['close'].iloc[i]
        last_sh = sh_list[-1][1]
        prev_sh = sh_list[-2][1]
        last_sl = sl_list[-1][1]
        prev_sl = sl_list[-2][1]

        # Determine trend from swing sequence
        hh = last_sh > prev_sh  # Higher high
        hl = last_sl > prev_sl  # Higher low
        lh = last_sh < prev_sh  # Lower high
        ll = last_sl < prev_sl  # Lower low

        if hh and hl:
            trend = 1   # Uptrend
        elif lh and ll:
            trend = -1  # Downtrend
        else:
            continue    # Mixed / transitioning — no signal

        if trend == 1:
            if close > last_sh:
                result.iloc[i] = 'bullish_bos'
            elif close < last_sl:
                result.iloc[i] = 'bearish_choch'

        elif trend == -1:
            if close < last_sl:
                result.iloc[i] = 'bearish_bos'
            elif close > last_sh:
                result.iloc[i] = 'bullish_choch'

    return result


# ---------------------------------------------------------------------------
# 2. Fair Value Gaps (FVG)
# ---------------------------------------------------------------------------

def fair_value_gap(data, params=None):
    """Detect Fair Value Gaps and signal when price fills them.

    A bullish FVG forms when candle[i].low > candle[i-2].high (gap up).
    The signal fires when a later candle's low dips into the FVG zone —
    this is the "discount entry" as price revisits the imbalance.

    Params:
        min_gap_pct (float): minimum gap size as fraction of price (default 0.0005)
        max_fvg_age (int):   max bars to wait for fill (default 20)
    """
    params = params or {}
    min_gap_pct = params.get('min_gap_pct', 0.0005)
    max_fvg_age = params.get('max_fvg_age', 20)

    df = data.copy()
    result = pd.Series(0, index=df.index, dtype=object)

    if len(df) < 5:
        return result

    active_fvgs = []  # {type, top, bottom, bar_idx}

    for i in range(2, len(df)):
        close = df['close'].iloc[i]
        high_i = df['high'].iloc[i]
        low_i = df['low'].iloc[i]

        # Expire old FVGs
        active_fvgs = [f for f in active_fvgs if i - f['bar_idx'] <= max_fvg_age]

        # --- Detect new FVGs on the 3-candle window ending at bar i ---
        c1_high = df['high'].iloc[i - 2]
        c1_low = df['low'].iloc[i - 2]
        c3_low = low_i
        c3_high = high_i

        # Bullish FVG: C3 low > C1 high  (gap between candle 1 and 3)
        if c3_low > c1_high:
            gap = (c3_low - c1_high) / close
            if gap >= min_gap_pct:
                active_fvgs.append({
                    'type': 'bullish',
                    'top': c3_low,       # upper edge of FVG zone
                    'bottom': c1_high,   # lower edge
                    'bar_idx': i,
                })

        # Bearish FVG: C3 high < C1 low
        if c3_high < c1_low:
            gap = (c1_low - c3_high) / close
            if gap >= min_gap_pct:
                active_fvgs.append({
                    'type': 'bearish',
                    'top': c1_low,
                    'bottom': c3_high,
                    'bar_idx': i,
                })

        # --- Check if current candle fills any active FVG ---
        filled = []
        for j, fvg in enumerate(active_fvgs):
            if fvg['bar_idx'] == i:
                continue  # Don't trigger on formation bar

            if fvg['type'] == 'bullish':
                # Wick dips into the gap AND candle closes above the bottom
                if low_i <= fvg['top'] and close > fvg['bottom']:
                    if result.iloc[i] == 0:
                        result.iloc[i] = 'bullish_fvg'
                    filled.append(j)

            elif fvg['type'] == 'bearish':
                if high_i >= fvg['bottom'] and close < fvg['top']:
                    if result.iloc[i] == 0:
                        result.iloc[i] = 'bearish_fvg'
                    filled.append(j)

        for j in sorted(filled, reverse=True):
            active_fvgs.pop(j)

    return result


# ---------------------------------------------------------------------------
# 3. Order Blocks
# ---------------------------------------------------------------------------

def order_block(data, params=None):
    """Detect Order Blocks and signal on retest.

    A bullish OB is the last bearish candle before a strong bullish impulse.
    When price later returns to that candle's zone (open→low) and closes
    above it, that's an institutional re-entry — bullish signal.

    Params:
        impulse_mult (float):     impulse candle must be >= N × avg range (default 2.0)
        ob_lookback (int):        bars to search back for the OB candle (default 3)
        max_ob_age (int):         max bars to wait for retest (default 30)
        avg_range_period (int):   period for average true range (default 14)
    """
    params = params or {}
    impulse_mult = params.get('impulse_mult', 2.0)
    ob_lookback = params.get('ob_lookback', 3)
    max_ob_age = params.get('max_ob_age', 30)
    avg_range_period = params.get('avg_range_period', 14)

    df = data.copy()
    result = pd.Series(0, index=df.index, dtype=object)
    min_bars = avg_range_period + ob_lookback + 5

    if len(df) < min_bars:
        return result

    ranges = (df['high'] - df['low']).values
    avg_range = pd.Series(ranges, index=df.index).rolling(avg_range_period).mean().values

    active_obs = []  # {type, top, bottom, bar_idx}

    for i in range(min_bars, len(df)):
        close = df['close'].iloc[i]
        open_p = df['open'].iloc[i]
        high_i = df['high'].iloc[i]
        low_i = df['low'].iloc[i]
        candle_range = high_i - low_i
        avg_r = avg_range[i]

        if np.isnan(avg_r) or avg_r <= 0:
            continue

        # Expire old OBs
        active_obs = [ob for ob in active_obs if i - ob['bar_idx'] <= max_ob_age]

        # --- Detect impulsive move ---
        if candle_range >= avg_r * impulse_mult:
            if close > open_p:
                # Bullish impulse → find last bearish candle before it
                for back in range(1, ob_lookback + 1):
                    pi = i - back
                    if pi < 0:
                        break
                    if df['close'].iloc[pi] < df['open'].iloc[pi]:
                        active_obs.append({
                            'type': 'bullish',
                            'top': df['open'].iloc[pi],
                            'bottom': df['low'].iloc[pi],
                            'bar_idx': i,
                        })
                        break

            elif close < open_p:
                # Bearish impulse → find last bullish candle before it
                for back in range(1, ob_lookback + 1):
                    pi = i - back
                    if pi < 0:
                        break
                    if df['close'].iloc[pi] > df['open'].iloc[pi]:
                        active_obs.append({
                            'type': 'bearish',
                            'top': df['high'].iloc[pi],
                            'bottom': df['open'].iloc[pi],
                            'bar_idx': i,
                        })
                        break

        # --- Check retests of active OBs ---
        filled = []
        for j, ob in enumerate(active_obs):
            if ob['bar_idx'] == i:
                continue

            if ob['type'] == 'bullish':
                # Wick into bullish OB zone, close above (rejection = entry)
                if low_i <= ob['top'] and close > ob['top']:
                    if result.iloc[i] == 0:
                        result.iloc[i] = 'bullish_ob'
                    filled.append(j)

            elif ob['type'] == 'bearish':
                if high_i >= ob['bottom'] and close < ob['bottom']:
                    if result.iloc[i] == 0:
                        result.iloc[i] = 'bearish_ob'
                    filled.append(j)

        for j in sorted(filled, reverse=True):
            active_obs.pop(j)

    return result


# ---------------------------------------------------------------------------
# 4. Liquidity Sweeps
# ---------------------------------------------------------------------------

def liquidity_sweep(data, params=None):
    """Detect Liquidity Sweeps — stop hunts beyond swing points.

    Bullish sweep: price wicks below a swing low (sweeping sell-stops)
    then closes ABOVE the swing low in the same candle → reversal signal.

    Bearish sweep: price wicks above a swing high (sweeping buy-stops)
    then closes BELOW the swing high.

    Params:
        swing_lookback (int):      bars on each side for swing detection (default 5)
        sweep_buffer_pct (float):  min distance beyond swing to qualify (default 0.0002)
        max_sweep_levels (int):    how many recent swing levels to track (default 10)
    """
    params = params or {}
    swing_lookback = params.get('swing_lookback', 5)
    sweep_buffer_pct = params.get('sweep_buffer_pct', 0.0002)
    max_levels = params.get('max_sweep_levels', 10)

    df = data.copy()
    result = pd.Series(0, index=df.index, dtype=object)

    swing_highs, swing_lows = _find_swing_points(df, swing_lookback)

    recent_sh = []  # (price, bar_index)
    recent_sl = []

    for i in range(len(df)):
        close = df['close'].iloc[i]
        high_i = df['high'].iloc[i]
        low_i = df['low'].iloc[i]

        # Register new swing points as liquidity pools
        if swing_highs.iloc[i]:
            recent_sh.append((df['high'].iloc[i], i))
            recent_sh = recent_sh[-max_levels:]
        if swing_lows.iloc[i]:
            recent_sl.append((df['low'].iloc[i], i))
            recent_sl = recent_sl[-max_levels:]

        # Bullish sweep: wick below swing low, close above
        for sl_price, sl_idx in recent_sl:
            if sl_idx >= i - 1:
                continue  # Skip very recent swings
            buffer = sl_price * sweep_buffer_pct
            if low_i < sl_price - buffer and close > sl_price:
                if result.iloc[i] == 0:
                    result.iloc[i] = 'bullish_sweep'
                break

        # Bearish sweep: wick above swing high, close below
        for sh_price, sh_idx in recent_sh:
            if sh_idx >= i - 1:
                continue
            buffer = sh_price * sweep_buffer_pct
            if high_i > sh_price + buffer and close < sh_price:
                if result.iloc[i] == 0:
                    result.iloc[i] = 'bearish_sweep'
                break

    return result


# ---------------------------------------------------------------------------
# 5. SMC Confluence — High-probability combined signal
# ---------------------------------------------------------------------------

def smc_confluence(data, params=None):
    """Combined SMC signal requiring 2+ aligned concepts on the same bar.

    This is the high-probability setup that TJR/Trades By Sci look for:
    confluence of market structure, FVGs, order blocks, and liquidity sweeps.

    CHoCH signals count double (worth 2 points) because a change of character
    is the strongest structural signal — it marks a genuine trend reversal.

    Params:
        min_confluence (int): minimum aligned signals to trigger (default 2)
        choch_weight (int):   extra weight for CHoCH signals (default 2)
        Sub-params forwarded to each individual indicator via nested dicts.
    """
    params = params or {}
    min_confluence = params.get('min_confluence', 2)
    choch_weight = params.get('choch_weight', 2)

    df = data.copy()
    result = pd.Series(0, index=df.index, dtype=object)

    ms = market_structure(df, params.get('market_structure', {}))
    fvg = fair_value_gap(df, params.get('fair_value_gap', {}))
    ob = order_block(df, params.get('order_block', {}))
    liq = liquidity_sweep(df, params.get('liquidity_sweep', {}))

    for i in range(len(df)):
        bull = 0
        bear = 0

        def _score(val):
            nonlocal bull, bear
            if not isinstance(val, str):
                return
            if 'bullish' in val:
                bull += choch_weight if 'choch' in val else 1
            elif 'bearish' in val:
                bear += choch_weight if 'choch' in val else 1

        _score(ms.iloc[i])
        _score(fvg.iloc[i])
        _score(ob.iloc[i])
        _score(liq.iloc[i])

        if bull >= min_confluence:
            result.iloc[i] = 'bullish_confluence'
        elif bear >= min_confluence:
            result.iloc[i] = 'bearish_confluence'

    return result
