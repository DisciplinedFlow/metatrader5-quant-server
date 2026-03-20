"""
V2 Strategies — based on real trader methods (ICC, TJR, ICT concepts).
All at 1:2 R:R. SL at structure, not arbitrary ATR distances.

Each strategy: fn(df, i) -> 'BUY' | 'SELL' | None
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Structure detection helpers
# ---------------------------------------------------------------------------

def find_swing_highs(highs, lookback=3):
    """Return boolean series: True where bar is a swing high."""
    result = pd.Series(False, index=highs.index)
    for i in range(lookback, len(highs) - lookback):
        window = highs.iloc[i-lookback:i+lookback+1]
        if highs.iloc[i] == window.max() and (highs.iloc[i] > highs.iloc[i-1]):
            result.iloc[i] = True
    return result


def find_swing_lows(lows, lookback=3):
    """Return boolean series: True where bar is a swing low."""
    result = pd.Series(False, index=lows.index)
    for i in range(lookback, len(lows) - lookback):
        window = lows.iloc[i-lookback:i+lookback+1]
        if lows.iloc[i] == window.min() and (lows.iloc[i] < lows.iloc[i-1]):
            result.iloc[i] = True
    return result


def get_recent_swing_highs(df, i, lookback=3, count=5):
    """Return list of (index, price) for recent swing highs up to bar i."""
    highs = df['high'].iloc[:i+1]
    swings = []
    for j in range(lookback, len(highs) - lookback):
        window = highs.iloc[j-lookback:j+lookback+1]
        if highs.iloc[j] == window.max() and highs.iloc[j] > highs.iloc[j-1]:
            swings.append((j, highs.iloc[j]))
    return swings[-count:] if swings else []


def get_recent_swing_lows(df, i, lookback=3, count=5):
    """Return list of (index, price) for recent swing lows up to bar i."""
    lows = df['low'].iloc[:i+1]
    swings = []
    for j in range(lookback, len(lows) - lookback):
        window = lows.iloc[j-lookback:j+lookback+1]
        if lows.iloc[j] == window.min() and lows.iloc[j] < lows.iloc[j-1]:
            swings.append((j, lows.iloc[j]))
    return swings[-count:] if swings else []


def detect_fvg(df, i):
    """Detect Fair Value Gap at bar i.
    Bullish FVG: bar[i-2].high < bar[i].low (gap up)
    Bearish FVG: bar[i-2].low > bar[i].high (gap down)
    Returns ('bullish', mid_price) or ('bearish', mid_price) or None.
    """
    if i < 2:
        return None
    bar0 = df.iloc[i-2]  # first candle
    bar2 = df.iloc[i]    # third candle
    # Bullish FVG: gap between candle 1 high and candle 3 low
    if bar0['high'] < bar2['low']:
        mid = (bar0['high'] + bar2['low']) / 2
        return ('bullish', mid, bar0['high'], bar2['low'])
    # Bearish FVG: gap between candle 1 low and candle 3 high
    if bar0['low'] > bar2['high']:
        mid = (bar0['low'] + bar2['high']) / 2
        return ('bearish', mid, bar2['high'], bar0['low'])
    return None


def detect_fvg_relaxed(df, i):
    """Relaxed FVG: displacement candle (body > 1.5x avg body) with imbalance.
    More signals than strict FVG. Checks if middle candle's body is large
    and there's insufficient overlap between candles 1 and 3.
    """
    if i < 2:
        return None
    bar0 = df.iloc[i-2]
    bar1 = df.iloc[i-1]  # middle (displacement) candle
    bar2 = df.iloc[i]

    # Middle candle must have significant body
    body1 = abs(bar1['close'] - bar1['open'])
    avg_body = abs(df['close'].iloc[max(0,i-20):i] - df['open'].iloc[max(0,i-20):i]).mean()
    if body1 < avg_body * 1.5:
        return None

    # Bullish: middle candle is bullish, gap between candle 1 high and candle 3 low
    if bar1['close'] > bar1['open']:
        gap = bar2['low'] - bar0['high']
        if gap > 0:
            return ('bullish', (bar0['high'] + bar2['low']) / 2, bar0['high'], bar2['low'])
        # Partial gap (at least 50% imbalance)
        overlap = min(bar2['low'], bar0['high']) - max(bar2['low'], bar0['high'])
        range_size = bar2['low'] - bar0['high']
        if range_size != 0 and bar0['high'] < bar2['low'] + body1 * 0.3:
            return ('bullish', (bar0['high'] + bar2['low']) / 2, bar0['high'], bar2['low'])

    # Bearish: middle candle is bearish
    if bar1['close'] < bar1['open']:
        gap = bar0['low'] - bar2['high']
        if gap > 0:
            return ('bearish', (bar2['high'] + bar0['low']) / 2, bar2['high'], bar0['low'])
        if bar0['low'] > bar2['high'] - body1 * 0.3:
            return ('bearish', (bar2['high'] + bar0['low']) / 2, bar2['high'], bar0['low'])

    return None


# ---------------------------------------------------------------------------
# ICC METHOD (TradesBySci)
# Indication → Correction → Continuation
# ---------------------------------------------------------------------------

def icc_method(df, i, swing_lookback=5):
    """
    ICC: Indication-Correction-Continuation.

    1. INDICATION: Detect a new Higher High or Lower Low (break of structure)
    2. CORRECTION: Wait for price to retrace into the zone (38-62% Fib)
    3. CONTINUATION: Enter when price breaks back in the indication direction

    SL: Below correction low (buy) or above correction high (sell)
    This function is called with the backtest engine's SL/TP — but we override
    by returning the signal. The engine places ATR-based SL/TP, but the real
    edge is in the TIMING of entry (after correction completes).
    """
    if i < 40:
        return None

    # Get recent swings (confirmed, with lookback buffer)
    swing_highs = get_recent_swing_highs(df, i - swing_lookback, swing_lookback, 5)
    swing_lows = get_recent_swing_lows(df, i - swing_lookback, swing_lookback, 5)

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return None

    close = df['close'].iloc[i]
    high = df['high'].iloc[i]
    low = df['low'].iloc[i]
    prev_close = df['close'].iloc[i-1]

    # --- BULLISH ICC ---
    # Indication: most recent swing high is higher than the one before (HH)
    last_sh = swing_highs[-1]
    prev_sh = swing_highs[-2]
    last_sl = swing_lows[-1]

    if last_sh[1] > prev_sh[1]:  # Higher High formed = bullish indication
        # The correction should happen AFTER the indication
        if last_sl[0] > prev_sh[0]:  # Swing low formed after the previous high
            # Correction zone: between the swing low and the indication high
            correction_low = last_sl[1]
            indication_high = last_sh[1]
            retrace_range = indication_high - correction_low

            if retrace_range > 0:
                # Is price in the correction zone? (38-62% retracement)
                fib_382 = indication_high - retrace_range * 0.618
                fib_618 = indication_high - retrace_range * 0.382

                # CONTINUATION: price was in correction zone and now breaks above
                # the previous candle's high (momentum returning)
                if (df['low'].iloc[i-1] <= fib_618 and  # prev bar touched zone
                    close > df['high'].iloc[i-1] and       # current bar breaks up
                    close > fib_618):                       # above the zone
                    return 'BUY'

    # --- BEARISH ICC ---
    last_sl_bear = swing_lows[-1]
    prev_sl_bear = swing_lows[-2]
    last_sh_bear = swing_highs[-1]

    if last_sl_bear[1] < prev_sl_bear[1]:  # Lower Low formed = bearish indication
        if last_sh_bear[0] > prev_sl_bear[0]:
            correction_high = last_sh_bear[1]
            indication_low = last_sl_bear[1]
            retrace_range = correction_high - indication_low

            if retrace_range > 0:
                fib_382 = indication_low + retrace_range * 0.618
                fib_618 = indication_low + retrace_range * 0.382

                if (df['high'].iloc[i-1] >= fib_618 and
                    close < df['low'].iloc[i-1] and
                    close < fib_618):
                    return 'SELL'

    return None


# ---------------------------------------------------------------------------
# TJR ASIA SWEEP METHOD
# Asia range → London/NY sweeps → MSS → FVG entry
# ---------------------------------------------------------------------------

def tjr_asia_sweep(df, i, asia_start=0, asia_end=5, trade_start=7, trade_end=16):
    """
    TJR: Asia Session Sweep + Market Structure Shift + FVG entry.

    1. Define Asia session range (00:00-05:00 UTC)
    2. Wait for London/NY (07:00-16:00 UTC) to sweep Asia high or low
    3. Look for MSS (break of recent swing in opposite direction of sweep)
    4. Enter at FVG or MSS level

    SL: Behind the sweep level (the Asia high/low that was swept)
    """
    if i < 30:
        return None

    bar = df.iloc[i]
    hour = bar['time'].hour

    # Only trade during London/NY session
    if hour < trade_start or hour >= trade_end:
        return None

    today = bar['time'].date()

    # Get Asia range for today
    asia_bars = df.iloc[:i+1]
    asia_bars = asia_bars[
        (asia_bars['time'].dt.date == today) &
        (asia_bars['time'].dt.hour >= asia_start) &
        (asia_bars['time'].dt.hour < asia_end)
    ]

    if len(asia_bars) < 3:
        return None

    asia_high = asia_bars['high'].max()
    asia_low = asia_bars['low'].min()
    asia_range = asia_high - asia_low

    if asia_range <= 0:
        return None

    # Look at recent session bars (since trade_start)
    session_bars = df.iloc[:i+1]
    session_bars = session_bars[
        (session_bars['time'].dt.date == today) &
        (session_bars['time'].dt.hour >= trade_start)
    ]

    if len(session_bars) < 3:
        return None

    close = df['close'].iloc[i]
    prev_close = df['close'].iloc[i-1]
    atr = df['atr'].iloc[i]
    if pd.isna(atr) or atr <= 0:
        return None

    # --- BULLISH: Sweep Asia LOW then reverse up ---
    # Check if any session bar swept below Asia low
    swept_low = session_bars['low'].min() < asia_low
    if swept_low:
        # MSS: price is now closing above the most recent swing high
        # (structure shift from bearish sweep to bullish)
        recent_highs = get_recent_swing_highs(df, i-1, 2, 3)
        if recent_highs:
            last_swing_high = recent_highs[-1][1]
            # Close breaks above recent swing high = MSS confirmed
            if prev_close <= last_swing_high and close > last_swing_high:
                # Check for FVG in recent bars (bonus confirmation)
                has_fvg = False
                for j in range(max(0, i-5), i+1):
                    fvg = detect_fvg_relaxed(df, j)
                    if fvg and fvg[0] == 'bullish':
                        has_fvg = True
                        break
                # Enter even without FVG if MSS is clear (FVG is bonus)
                if close > asia_low:  # sanity: price recovered above Asia range
                    return 'BUY'

    # --- BEARISH: Sweep Asia HIGH then reverse down ---
    swept_high = session_bars['high'].max() > asia_high
    if swept_high:
        recent_lows = get_recent_swing_lows(df, i-1, 2, 3)
        if recent_lows:
            last_swing_low = recent_lows[-1][1]
            if prev_close >= last_swing_low and close < last_swing_low:
                if close < asia_high:
                    return 'SELL'

    return None


# ---------------------------------------------------------------------------
# ICT LIQUIDITY SWEEP + FVG (simplified ICT 2022 model)
# ---------------------------------------------------------------------------

def ict_sweep_fvg(df, i, lookback=20):
    """
    Simplified ICT model:
    1. Identify liquidity pool (equal highs/lows or swing high/low)
    2. Wait for sweep (price takes out the level then reverses)
    3. Enter at FVG formed after the sweep

    This is the core concept behind both ICC and TJR — stripped to essentials.
    """
    if i < lookback + 5:
        return None

    close = df['close'].iloc[i]
    atr = df['atr'].iloc[i]
    if pd.isna(atr) or atr <= 0:
        return None

    # Find recent swing highs and lows
    swing_highs = get_recent_swing_highs(df, i-1, 3, 3)
    swing_lows = get_recent_swing_lows(df, i-1, 3, 3)

    if not swing_highs or not swing_lows:
        return None

    # --- BULLISH: sweep of swing low + FVG ---
    last_sl_idx, last_sl_price = swing_lows[-1]
    bars_since_sl = i - last_sl_idx

    if 2 <= bars_since_sl <= 10:
        # Was the swing low swept? (some bar went below it)
        swept = False
        for j in range(last_sl_idx + 1, i):
            if df['low'].iloc[j] < last_sl_price:
                swept = True
                break

        if swept and close > last_sl_price:
            # Look for bullish FVG in the recovery
            for j in range(max(last_sl_idx, i-5), i+1):
                fvg = detect_fvg_relaxed(df, j)
                if fvg and fvg[0] == 'bullish':
                    return 'BUY'

    # --- BEARISH: sweep of swing high + FVG ---
    last_sh_idx, last_sh_price = swing_highs[-1]
    bars_since_sh = i - last_sh_idx

    if 2 <= bars_since_sh <= 10:
        swept = False
        for j in range(last_sh_idx + 1, i):
            if df['high'].iloc[j] > last_sh_price:
                swept = True
                break

        if swept and close < last_sh_price:
            for j in range(max(last_sh_idx, i-5), i+1):
                fvg = detect_fvg_relaxed(df, j)
                if fvg and fvg[0] == 'bearish':
                    return 'SELL'

    return None


# ---------------------------------------------------------------------------
# BREAK OF STRUCTURE + ORDER BLOCK
# ---------------------------------------------------------------------------

def bos_order_block(df, i, lookback=3):
    """
    Break of Structure with Order Block entry:
    1. Detect break of structure (HH for bullish, LL for bearish)
    2. Identify the order block (last bearish candle before bullish BOS, or vice versa)
    3. Enter when price retests the order block zone

    SL: Below order block (buy) or above order block (sell)
    """
    if i < 30:
        return None

    close = df['close'].iloc[i]
    swing_highs = get_recent_swing_highs(df, i-lookback, lookback, 4)
    swing_lows = get_recent_swing_lows(df, i-lookback, lookback, 4)

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return None

    # --- BULLISH BOS ---
    # Recent swing high broken = bullish break of structure
    prev_sh_idx, prev_sh_price = swing_highs[-2]

    # Check if any recent bar broke above the previous swing high
    bos_bullish = False
    bos_bar = None
    for j in range(prev_sh_idx + 1, i):
        if df['close'].iloc[j] > prev_sh_price:
            bos_bullish = True
            bos_bar = j
            break

    if bos_bullish and bos_bar:
        # Find the order block: last bearish candle before the BOS
        ob_high = None
        ob_low = None
        for j in range(bos_bar - 1, max(prev_sh_idx - 5, 0), -1):
            if df['close'].iloc[j] < df['open'].iloc[j]:  # bearish candle
                ob_high = df['high'].iloc[j]
                ob_low = df['low'].iloc[j]
                break

        if ob_high and ob_low:
            # Entry: price retests the order block zone
            if df['low'].iloc[i] <= ob_high and close > ob_low and close > df['open'].iloc[i]:
                # Confirm we're still above BOS level
                if close > prev_sh_price * 0.998:  # within 0.2% of BOS level
                    return 'BUY'

    # --- BEARISH BOS ---
    prev_sl_idx, prev_sl_price = swing_lows[-2]

    bos_bearish = False
    bos_bar = None
    for j in range(prev_sl_idx + 1, i):
        if df['close'].iloc[j] < prev_sl_price:
            bos_bearish = True
            bos_bar = j
            break

    if bos_bearish and bos_bar:
        ob_high = None
        ob_low = None
        for j in range(bos_bar - 1, max(prev_sl_idx - 5, 0), -1):
            if df['close'].iloc[j] > df['open'].iloc[j]:  # bullish candle
                ob_high = df['high'].iloc[j]
                ob_low = df['low'].iloc[j]
                break

        if ob_high and ob_low:
            if df['high'].iloc[i] >= ob_low and close < ob_high and close < df['open'].iloc[i]:
                if close < prev_sl_price * 1.002:
                    return 'SELL'

    return None


# ---------------------------------------------------------------------------
# SESSION RANGE SWEEP + MSS (simplified TJR for any session)
# ---------------------------------------------------------------------------

def london_sweep_reversal(df, i):
    """
    London open sweep reversal:
    1. Compute pre-London range (04:00-07:00 UTC consolidation)
    2. London open (07:00-08:30) sweeps one side
    3. MSS confirms reversal
    4. Enter on continuation

    Classic "turtle soup" / liquidity grab pattern.
    """
    if i < 20:
        return None

    bar = df.iloc[i]
    hour = bar['time'].hour

    # Only look for entries during London session
    if hour < 7 or hour >= 12:
        return None

    today = bar['time'].date()

    # Pre-London range: 04:00-07:00 UTC
    pre_london = df.iloc[:i+1]
    pre_london = pre_london[
        (pre_london['time'].dt.date == today) &
        (pre_london['time'].dt.hour >= 4) &
        (pre_london['time'].dt.hour < 7)
    ]

    if len(pre_london) < 3:
        return None

    range_high = pre_london['high'].max()
    range_low = pre_london['low'].min()

    close = df['close'].iloc[i]
    prev_close = df['close'].iloc[i-1]

    # --- BULLISH: swept below range low, now reversing up ---
    # Check if any bar since 07:00 went below range_low
    london_bars = df.iloc[:i+1]
    london_bars = london_bars[
        (london_bars['time'].dt.date == today) &
        (london_bars['time'].dt.hour >= 7)
    ]

    if len(london_bars) < 2:
        return None

    swept_low = london_bars['low'].min() < range_low
    swept_high = london_bars['high'].max() > range_high

    if swept_low and not swept_high:
        # Price swept below, now closing back inside range or above = reversal
        if prev_close < range_low and close > range_low:
            return 'BUY'
        # Or: price dipped below and formed a strong bullish candle
        if (close > df['open'].iloc[i] and
            df['low'].iloc[i] < range_low and
            close > range_low):
            return 'BUY'

    if swept_high and not swept_low:
        if prev_close > range_high and close < range_high:
            return 'SELL'
        if (close < df['open'].iloc[i] and
            df['high'].iloc[i] > range_high and
            close < range_high):
            return 'SELL'

    return None
