"""
Adaptive Position Manager
Replaces static trailing stop with dynamic, price-aware position management.

Phases per position (applied in order):
1. BREAKEVEN: Move SL to entry price after 1x ATR profit
2. PARTIAL CLOSE: Close 50% at 2x ATR profit, lock in gains
3. SWING TRAIL: Trail SL using swing lows (longs) or swing highs (shorts)
4. TIME EXIT: Close stale positions after 20+ bars with < 0.5 ATR profit
"""

import traceback
import logging
import numpy as np
import pandas as pd
from datetime import datetime

from app.utils.api.positions import get_positions
from app.utils.api.data import fetch_data_pos
from app.utils.api.order import modify_sl_tp, close_partial, close_full
from app.utils.db.get import get_trade_with_mutations
from app.utils.constants import MT5Timeframe
from app.quant.indicators.scalping import atr

logger = logging.getLogger('position_manager')

# -- Position type constants (MT5) --
BUY = 0
SELL = 1

# -- Phase thresholds (in ATR multiples) --
BREAKEVEN_ATR_THRESHOLD = 1.0
PARTIAL_CLOSE_ATR_THRESHOLD = 2.0
PARTIAL_CLOSE_FRACTION = 0.5
SWING_TRAIL_LOOKBACK = 3       # bars on each side for swing detection
SWING_TRAIL_ATR_BUFFER = 0.2   # ATR fraction for buffer beyond swing point
TIME_EXIT_BAR_THRESHOLD = 20
TIME_EXIT_ATR_THRESHOLD = 0.5
ATR_PERIOD = 14

# -- Timeframe mapping from Trade.entry_timeframe to MT5Timeframe --
TIMEFRAME_MAP = {
    'M1': MT5Timeframe.M1,
    'M5': MT5Timeframe.M5,
    'M15': MT5Timeframe.M15,
    'M30': MT5Timeframe.M30,
    'H1': MT5Timeframe.H1,
    'H4': MT5Timeframe.H4,
    'D1': MT5Timeframe.D1,
    'W1': MT5Timeframe.W1,
    'MN1': MT5Timeframe.MN1,
    # Django Trade.timeframe choices
    '1M': MT5Timeframe.M1,
    '5M': MT5Timeframe.M5,
    '15M': MT5Timeframe.M15,
    '1H': MT5Timeframe.H1,
    '4H': MT5Timeframe.H4,
    '1D': MT5Timeframe.D1,
}


def manage_positions():
    """
    Main entry point. Called every 15 seconds by Celery beat.
    Iterates all open MT5 positions and applies adaptive management.
    """
    try:
        positions = get_positions()

        if positions is None or positions.empty:
            logger.info("Position manager: No open positions")
            return

        for _, position in positions.iterrows():
            try:
                _manage_single_position(position)
            except Exception as e:
                logger.error(
                    f"Position manager: Error managing ticket {position.ticket}: "
                    f"{e}\n{traceback.format_exc()}"
                )

    except Exception as e:
        logger.error(f"Position manager exception: {e}\n{traceback.format_exc()}")


def _manage_single_position(position):
    """Apply all management phases to a single position."""
    # 1. Look up the Trade record in Django
    trade_data = get_trade_with_mutations(position.ticket)
    if trade_data is None:
        logger.debug(f"Position manager: No trade record for ticket {position.ticket}, skipping")
        return

    trade = trade_data.get("trade")
    if trade is None:
        return

    # 2. Determine position type (numeric from MT5 DataFrame)
    position_type = position.type  # 0=BUY, 1=SELL

    # 3. Calculate profit distance in price units
    entry_price = position.price_open
    current_price = position.price_current

    if position_type == BUY:
        profit_distance = current_price - entry_price
    else:
        profit_distance = entry_price - current_price

    # 4. Fetch price data for swing detection, time analysis, and ATR fallback
    timeframe = _resolve_timeframe(trade)
    df = fetch_data_pos(position.symbol, timeframe, 50)
    if df is None or df.empty or len(df) < 20:
        logger.debug(f"Position manager: Insufficient data for {position.symbol}, skipping swing/time phases")
        df = None

    # 5. Ensure entry_atr is available — fallback to live ATR if missing
    if trade.entry_atr is None:
        if df is not None and len(df) >= ATR_PERIOD + 1:
            atr_series = atr(df, period=ATR_PERIOD)
            fallback_atr = atr_series.iloc[-1]
            if not pd.isna(fallback_atr) and fallback_atr > 0:
                trade.entry_atr = fallback_atr
                trade.save(update_fields=['entry_atr'])
                logger.info(f"Position manager: Backfilled entry_atr={fallback_atr:.6f} for ticket {position.ticket}")
            else:
                logger.debug(f"Position manager: No valid ATR for ticket {position.ticket}, skipping")
                return
        else:
            logger.debug(f"Position manager: No entry_atr and no data for ticket {position.ticket}, skipping")
            return

    # 6. Compute current ATR from recent data
    current_atr = trade.entry_atr  # fallback
    if df is not None and len(df) >= ATR_PERIOD + 1:
        atr_series = atr(df, period=ATR_PERIOD)
        latest_atr = atr_series.iloc[-1]
        if not pd.isna(latest_atr) and latest_atr > 0:
            current_atr = latest_atr

    # 6. Apply management phases in order
    _check_breakeven(position, trade, profit_distance, current_atr)
    _check_partial_close(position, trade, profit_distance)
    _check_swing_trail(position, trade, df, current_atr)
    _check_time_exit(position, trade, df, current_atr, profit_distance)


# ---------------------------------------------------------------------------
# Phase 1: Breakeven
# ---------------------------------------------------------------------------

def _check_breakeven(position, trade, profit_distance, current_atr):
    """Move SL to entry price after position reaches 1x ATR profit."""
    if trade.breakeven_moved:
        return

    if trade.entry_atr is None:
        return

    if profit_distance < trade.entry_atr * BREAKEVEN_ATR_THRESHOLD:
        return

    entry_price = position.price_open
    position_type = position.type
    current_sl = position.sl
    current_tp = position.tp

    # New SL at entry price, with small buffer for spread on buys
    spread_buffer = _get_spread_buffer(position.symbol)
    if position_type == BUY:
        new_sl = entry_price + spread_buffer
    else:
        new_sl = entry_price - spread_buffer

    # Only move SL if it improves the position
    if not _is_better_sl(position_type, new_sl, current_sl):
        return

    result = modify_sl_tp(position, new_sl, current_tp if current_tp and current_tp != 0 else None)
    if result is not None:
        trade.breakeven_moved = True
        trade.save(update_fields=['breakeven_moved'])
        logger.info(
            f"BREAKEVEN: {position.symbol} ticket={position.ticket} "
            f"moved SL to {new_sl:.5f} (entry={entry_price:.5f})"
        )
    else:
        logger.warning(f"BREAKEVEN: Failed to modify SL for {position.symbol} ticket={position.ticket}")


# ---------------------------------------------------------------------------
# Phase 2: Partial Close
# ---------------------------------------------------------------------------

def _check_partial_close(position, trade, profit_distance):
    """Close 50% of position at 2x ATR profit."""
    if trade.partial_closed:
        return

    # Only after breakeven has been achieved
    if not trade.breakeven_moved:
        return

    if trade.entry_atr is None:
        return

    if profit_distance < trade.entry_atr * PARTIAL_CLOSE_ATR_THRESHOLD:
        return

    position_type = position.type
    position_volume = position.volume
    current_price = position.price_current

    partial_vol = round(position_volume * PARTIAL_CLOSE_FRACTION, 2)
    if partial_vol < 0.01:
        logger.info(
            f"PARTIAL CLOSE: {position.symbol} ticket={position.ticket} "
            f"volume too small ({partial_vol}), skipping"
        )
        return

    result = close_partial(position.ticket, position.symbol, position_type, partial_vol)
    if result is not None:
        trade.partial_closed = True
        trade.partial_close_volume = partial_vol
        trade.partial_close_price = current_price
        trade.save(update_fields=['partial_closed', 'partial_close_volume', 'partial_close_price'])
        logger.info(
            f"PARTIAL CLOSE: {position.symbol} ticket={position.ticket} "
            f"closed {partial_vol} lots at {current_price:.5f}"
        )
    else:
        logger.warning(f"PARTIAL CLOSE: Failed for {position.symbol} ticket={position.ticket}")


# ---------------------------------------------------------------------------
# Phase 3: Swing Trail
# ---------------------------------------------------------------------------

def _check_swing_trail(position, trade, df, current_atr):
    """Trail SL using swing lows (longs) or swing highs (shorts)."""
    if not trade.breakeven_moved:
        return

    if df is None or len(df) < (2 * SWING_TRAIL_LOOKBACK + 1):
        return

    position_type = position.type
    current_sl = position.sl
    current_tp = position.tp

    if position_type == BUY:
        # Find recent swing lows for trailing a long position
        swing_values = _find_swing_low_values(df['low'].values, SWING_TRAIL_LOOKBACK)
        if len(swing_values) < 1:
            return

        # Use the most recent swing low minus a small ATR buffer
        candidate_sl = swing_values[-1] - (current_atr * SWING_TRAIL_ATR_BUFFER)

        # Only move SL up, never down
        if _is_better_sl(position_type, candidate_sl, current_sl):
            result = modify_sl_tp(
                position, candidate_sl,
                current_tp if current_tp and current_tp != 0 else None
            )
            if result is not None:
                logger.info(
                    f"SWING TRAIL: {position.symbol} ticket={position.ticket} "
                    f"BUY SL -> {candidate_sl:.5f}"
                )
            else:
                logger.warning(
                    f"SWING TRAIL: Failed to modify SL for {position.symbol} ticket={position.ticket}"
                )

    else:  # SELL
        swing_values = _find_swing_high_values(df['high'].values, SWING_TRAIL_LOOKBACK)
        if len(swing_values) < 1:
            return

        candidate_sl = swing_values[-1] + (current_atr * SWING_TRAIL_ATR_BUFFER)

        if _is_better_sl(position_type, candidate_sl, current_sl):
            result = modify_sl_tp(
                position, candidate_sl,
                current_tp if current_tp and current_tp != 0 else None
            )
            if result is not None:
                logger.info(
                    f"SWING TRAIL: {position.symbol} ticket={position.ticket} "
                    f"SELL SL -> {candidate_sl:.5f}"
                )
            else:
                logger.warning(
                    f"SWING TRAIL: Failed to modify SL for {position.symbol} ticket={position.ticket}"
                )


# ---------------------------------------------------------------------------
# Phase 4: Time Exit
# ---------------------------------------------------------------------------

def _check_time_exit(position, trade, df, current_atr, profit_distance):
    """Close positions that haven't moved significantly after 20+ bars."""
    if df is None or df.empty:
        return

    if trade.entry_atr is None:
        return

    bars_since_entry = _estimate_bars_since_entry(trade, df)

    if bars_since_entry <= TIME_EXIT_BAR_THRESHOLD:
        return

    if profit_distance >= trade.entry_atr * TIME_EXIT_ATR_THRESHOLD:
        return

    # This trade is going nowhere -- free up capital
    position_type = position.type
    position_volume = position.volume

    result = close_full(position.ticket, position.symbol, position_type, position_volume)
    if result is not None:
        logger.info(
            f"TIME EXIT: {position.symbol} ticket={position.ticket} "
            f"after {bars_since_entry} bars, profit_dist={profit_distance:.5f}, "
            f"threshold={trade.entry_atr * TIME_EXIT_ATR_THRESHOLD:.5f}"
        )
    else:
        logger.warning(f"TIME EXIT: Failed to close {position.symbol} ticket={position.ticket}")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _is_better_sl(position_type, new_sl, current_sl):
    """
    Check if a new SL is better (tighter) than the current one.

    For BUY positions, a higher SL is better (locks in more profit).
    For SELL positions, a lower SL is better.

    Also returns True if current_sl is 0 (no SL set).
    """
    if current_sl is None or current_sl == 0:
        return True

    if position_type == BUY:
        return new_sl > current_sl
    else:
        return new_sl < current_sl


def _find_swing_low_values(values, lookback):
    """
    Find swing low VALUES from a numpy array of price lows.

    A swing low is a point that is the lowest within `lookback` bars on each side.
    Returns a list of the actual price values at swing low points.
    """
    results = []
    for i in range(lookback, len(values) - lookback):
        window = values[i - lookback:i + lookback + 1]
        if not np.isnan(values[i]) and values[i] == np.nanmin(window):
            results.append(values[i])
    return results


def _find_swing_high_values(values, lookback):
    """
    Find swing high VALUES from a numpy array of price highs.

    A swing high is a point that is the highest within `lookback` bars on each side.
    Returns a list of the actual price values at swing high points.
    """
    results = []
    for i in range(lookback, len(values) - lookback):
        window = values[i - lookback:i + lookback + 1]
        if not np.isnan(values[i]) and values[i] == np.nanmax(window):
            results.append(values[i])
    return results


def _estimate_bars_since_entry(trade, df):
    """
    Estimate how many bars have passed since the trade was opened.

    Compares the trade's entry_time with the timestamps in the price DataFrame.
    Falls back to counting from the first bar if entry_time is missing or
    doesn't fall within the DataFrame's time range.
    """
    if trade.entry_time is None:
        return 0

    entry_time = trade.entry_time

    # The df may have a 'time' column as epoch seconds or datetime
    if 'time' not in df.columns:
        return 0

    try:
        df_times = pd.to_datetime(df['time'], unit='s', utc=True, errors='coerce')
    except Exception:
        try:
            df_times = pd.to_datetime(df['time'], utc=True, errors='coerce')
        except Exception:
            return 0

    # Make entry_time timezone-aware if needed
    if entry_time.tzinfo is None:
        import pytz
        entry_time = pytz.utc.localize(entry_time)

    # Count bars after entry
    bars_after = (df_times >= entry_time).sum()

    # bars_after is the number of bars from entry to end of data
    return int(bars_after)


def _get_spread_buffer(symbol):
    """
    Return a small spread buffer for breakeven calculations.

    For major forex pairs, the spread is typically 1-3 pips.
    We use a conservative 2 pip buffer to avoid premature stop-outs.
    """
    # JPY pairs have 2 decimal places for pips (0.01 = 1 pip)
    if 'JPY' in symbol:
        return 0.02  # 2 pips for JPY pairs

    # Standard pairs have 4 decimal places for pips (0.0001 = 1 pip)
    return 0.0002  # 2 pips for standard pairs


def _resolve_timeframe(trade):
    """
    Resolve the trading timeframe from the Trade record.

    Checks entry_timeframe first, falls back to timeframe field,
    then defaults to M15.
    """
    # Try entry_timeframe first (new field)
    tf_str = getattr(trade, 'entry_timeframe', None)
    if tf_str and tf_str in TIMEFRAME_MAP:
        return TIMEFRAME_MAP[tf_str]

    # Fall back to the standard timeframe field
    tf_str = getattr(trade, 'timeframe', None)
    if tf_str and tf_str in TIMEFRAME_MAP:
        return TIMEFRAME_MAP[tf_str]

    # Default
    return MT5Timeframe.M15
