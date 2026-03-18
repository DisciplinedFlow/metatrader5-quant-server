"""
Adaptive Position Manager — MFE-optimized for maximum profit capture.

Phases per position (applied in order):
S. SCALE-IN: Livermore "feeling-out bet" — add remaining 40% after +1x ATR confirmation (within 10min)
0. MFE ACCELERATION: Lock in 60% of profit when $5+ within 15min; kill flat trades at 20min
1. BREAKEVEN: Move SL to entry price after 1x ATR profit
2. PARTIAL CLOSE: Close 33% at 2x ATR profit, lock in gains
3. SWING TRAIL: Trail SL using multi-TF S/R levels
4. TIME EXIT: Close stale positions after 45 min with < $3 profit
5. PROFIT PROTECTION: Close if giving back 50%+ from peak

MFE/MAE data shows: winners move in 5-15 min (avg 26 min), losers linger 70 min.
92% of wins hit $5+ profit. Optimized to capture fast moves and cut lingering losers.
"""

import traceback
import logging
import numpy as np
import pandas as pd
from datetime import datetime

from app.utils.api.positions import get_positions
from app.utils.api.data import fetch_data_pos
from app.utils.api.order import modify_sl_tp, close_partial, close_full, send_market_order
from app.utils.db.get import get_trade_with_mutations
from app.utils.constants import MT5Timeframe
from app.quant.indicators.scalping import atr

logger = logging.getLogger('position_manager')

# -- Position type constants (MT5) --
BUY = 0
SELL = 1

# -- MFE Acceleration (Phase 0) — data-driven from MFE/MAE analysis --
MFE_PROFIT_THRESHOLD = 5.0     # Lock profit once trade hits $5+ (92% of wins reach this)
MFE_LOCK_MINUTES = 15          # Within first 15 min = fast mover, lock it
MFE_LOCK_FRACTION = 0.40       # Lock in 40% (was 60%) — give winners room to breathe
FLAT_TRADE_MINUTES = 15        # Kill flat trades at 15min (was 20) — losers linger, cut faster
FLAT_TRADE_MIN_PROFIT = 1.5    # "Going nowhere" = less than $1.50 profit (was $2)

# -- Phase thresholds (in ATR multiples) --
BREAKEVEN_ATR_THRESHOLD = 1.0
PARTIAL_CLOSE_ATR_THRESHOLD = 2.0  # Legacy — kept for backward compat
PARTIAL_CLOSE_FRACTION = 0.33     # Legacy

# 3-tier partial close: lock profits incrementally, let remainder ride
PARTIAL_CLOSE_TIERS = [
    {'atr_mult': 1.5, 'close_pct': 0.30, 'flag': 'partial_1'},  # 30% at 1.5R — lock early
    {'atr_mult': 3.0, 'close_pct': 0.30, 'flag': 'partial_2'},  # 30% at 3R — lock mid
    # Remaining 40% trails on H1/H4 structure until invalidation
]
SWING_TRAIL_LOOKBACK = 3       # bars on each side for swing detection
SWING_TRAIL_ATR_BUFFER = 0.2   # ATR fraction for buffer beyond swing point
TIME_EXIT_MINUTES = 20         # Marcus: "best trades work immediately" — cut dead trades at 20min
TIME_EXIT_MIN_PROFIT = 2.0     # Need $2+ to justify holding past 20min
ATR_PERIOD = 14

# -- Profit protection thresholds --
PROFIT_PROTECT_MIN_USD = 30.0   # Only protect after clearly past 2R territory (~€25 at €250 risk)
PROFIT_PROTECT_GIVEBACK = 0.35  # Allow 35% giveback from peak before closing (was 25%)

# -- ATR Floor Trail (always-on, aggressive) --
# Guarantees SL trails behind best price even when no S/R or swing levels exist.
# At 2s tick interval, this creates a ratcheting floor that locks profits.
ATR_FLOOR_TRAIL_MULT = 1.0     # Trail 1.0x current ATR behind best price (tightened from 1.5)
ATR_FLOOR_MIN_PROFIT_R = 2.0   # Only activate after 2R profit — let fixed TP fire first

# -- Adaptive ATR-% Trail (from entry, M5 candle-adaptive) --
# Trails from the moment the trade opens — no profit gate required.
# Uses entry_atr (H1-based) so trail distance matches signal timeframe.
# Ratchets: SL only moves in trader's favour, never loosened once set.
ADAPTIVE_TRAIL_BASE_MULT     = 2.0   # Default: 2x entry ATR behind best price
ADAPTIVE_TRAIL_MOMENTUM_MULT = 2.5   # Strong M5 momentum → give room to run
ADAPTIVE_TRAIL_REVERSAL_MULT = 1.5   # M5 reversal candle → lock in profits faster
ADAPTIVE_TRAIL_CUTOFF_MULT   = 2.0   # Force close if adverse > 2x entry ATR (gap backstop)

# -- TP Removal: disabled — fixed TP handles primary exit, trail captures beyond-TP runners --
# Previous: XAUUSD TP removed based on early data. Restored to achieve designed 1:2 R:R.
NO_TP_SYMBOLS = set()

# -- Hard dollar loss ceiling (O'Neil: "Cut all losses at 7-8%") --
MAX_LOSS_PER_TRADE_USD = 250.0  # Matches entry.py MAX_LOSS_PER_TRADE — €250 risk stress test

# -- Livermore Scale-In ("feeling-out bet") --
SCALE_IN_ATR_THRESHOLD = 1.0   # Add remaining size after +1x ATR confirmation
SCALE_IN_MAX_MINUTES = 10      # Must confirm within 10 minutes

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
            logger.debug("Position manager: No open positions")
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
    # 0. Orphan protection — close positions with no Trade record if losing
    trade_data = get_trade_with_mutations(position.ticket)
    if trade_data is None:
        if position.profit < -MAX_LOSS_PER_TRADE_USD:
            result = close_full(position.ticket, position.symbol, position.type, position.volume)
            if result is not None:
                logger.warning(
                    f"ORPHAN CLOSED: {position.symbol} ticket={position.ticket} "
                    f"no trade record, loss=${position.profit:.2f} exceeded ${MAX_LOSS_PER_TRADE_USD} ceiling"
                )
        return

    trade = trade_data.get("trade")
    if trade is None:
        return

    # 2. Determine position type (numeric from MT5 DataFrame)
    position_type = position.type  # 0=BUY, 1=SELL

    # 2b. Remove TP for symbols where trailing SL replaces fixed TP
    if position.symbol in NO_TP_SYMBOLS and position.tp and position.tp != 0:
        result = modify_sl_tp(position, position.sl, tp=0.0)
        if result is not None and result != 'MARKET_CLOSED':
            logger.info(
                f"TP REMOVED: {position.symbol} ticket={position.ticket} "
                f"old_tp={position.tp:.5f} — trailing SL handles exit"
            )

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

    # 6. Track max profit / max drawdown on every tick
    current_pnl = position.profit
    _update_profit_tracking(trade, current_pnl)

    # 7. Compute minutes in trade (used by multiple phases)
    minutes_in_trade = _get_minutes_in_trade(trade)

    # Hard dollar loss ceiling (O'Neil: "Cut all losses at 7-8%")
    if _check_hard_loss_ceiling(position, trade, current_pnl):
        return

    # Fetch M5 bars once — shared by adaptive trail and M5 TP mgmt to avoid double API call
    df_m5 = _fetch_m5_bars(position.symbol)

    # Adaptive ATR-% trail — active from entry, M5 candle-adaptive, H1 ATR-based
    if _check_adaptive_trail(position, trade, df_m5):
        return

    # Scale-in check (Livermore "feeling-out bet") — add remaining 40% on confirmation
    _check_scale_in(position, trade, profit_distance, minutes_in_trade)

    # Phase 0: MFE Acceleration — lock fast profits, kill flat trades
    if _check_mfe_acceleration(position, trade, current_pnl, minutes_in_trade, current_atr):
        return  # Trade was closed or SL locked, skip remaining phases

    # Profit protection — close if giving back too much from peak
    if _check_profit_protection(position, trade, current_pnl):
        return

    # Apply management phases in order
    _check_breakeven(position, trade, profit_distance, current_atr)

    # Phase 1.5: M5 dynamic TP/SL — extend TP on momentum, tighten on reversal (reuse fetched bars)
    _check_m5_tp_management(position, profit_distance, current_atr, df_m5)

    _check_partial_close(position, trade, profit_distance)

    # Dynamic trail tightening: if momentum is fading, use tighter ATR multiplier
    trail_atr = current_atr
    if df is not None and trade.entry_atr and trade.entry_atr > 0:
        vol_ratio = current_atr / trade.entry_atr if trade.entry_atr > 0 else 1.0
        if vol_ratio < 0.6:
            # Volatility contracted significantly — momentum fading, tighten trail
            trail_atr = current_atr * 0.7
            logger.debug(
                f"MOMENTUM FADE: {position.symbol} vol_ratio={vol_ratio:.2f} "
                f"— tightening trail ATR from {current_atr:.6f} to {trail_atr:.6f}"
            )

    _check_swing_trail(position, trade, df, trail_atr)
    _check_atr_floor_trail(position, trade, profit_distance, current_atr)
    _check_time_exit(position, trade, current_pnl, minutes_in_trade)


# ---------------------------------------------------------------------------
# Profit Tracking & Protection
# ---------------------------------------------------------------------------

def _update_profit_tracking(trade, current_pnl):
    """Update max_profit and max_drawdown on every tick."""
    updates = []

    if trade.max_profit is None or current_pnl > trade.max_profit:
        trade.max_profit = current_pnl
        updates.append('max_profit')

    if trade.max_drawdown is None or current_pnl < trade.max_drawdown:
        trade.max_drawdown = current_pnl
        updates.append('max_drawdown')

    if updates:
        trade.save(update_fields=updates)


def _check_hard_loss_ceiling(position, trade, current_pnl):
    """O'Neil's rule: cut ALL losses at a hard dollar ceiling, no exceptions.

    This is the absolute safety net — catches gaps, slippage, and any scenario
    where the ATR-based SL hasn't triggered. Returns True if trade was closed.
    """
    if current_pnl >= -MAX_LOSS_PER_TRADE_USD:
        return False

    result = close_full(position.ticket, position.symbol, position.type, position.volume)
    if result is not None:
        logger.warning(
            f"HARD CEILING: {position.symbol} ticket={position.ticket} "
            f"${current_pnl:.2f} hit -${MAX_LOSS_PER_TRADE_USD} ceiling — CLOSED"
        )
        try:
            from app.quant.tasks import record_to_graph
            minutes_in_trade = _get_minutes_in_trade(trade)
            record_to_graph.delay({
                'type': 'exit_event',
                'trade_id': str(position.ticket),
                'symbol': position.symbol,
                'phase': 'MAX_LOSS',
                'trigger_value': float(current_pnl),
                'action': f'Hard loss ceiling ${current_pnl:.2f} hit -${MAX_LOSS_PER_TRADE_USD} max',
                'pnl_at_event': float(current_pnl),
                'minutes_in_trade': int(minutes_in_trade),
            })
        except Exception:
            pass
        return True
    return False


def _check_profit_protection(position, trade, current_pnl):
    """Close trade if profit drops too far from peak.

    Example: peak was $40, current is $15 → gave back 62.5% → close.
    Only activates after peak exceeds PROFIT_PROTECT_MIN_USD.

    Returns True if trade was closed.
    """
    if trade.max_profit is None or trade.max_profit < PROFIT_PROTECT_MIN_USD:
        return False

    # Still profitable but gave back too much
    threshold = trade.max_profit * PROFIT_PROTECT_GIVEBACK
    if current_pnl > threshold:
        return False

    # Close the trade — protecting remaining profit
    result = close_full(position.ticket, position.symbol, position.type, position.volume)
    if result is not None:
        logger.info(
            f"PROFIT PROTECTION: {position.symbol} ticket={position.ticket} "
            f"peak=${trade.max_profit:.2f} → current=${current_pnl:.2f} "
            f"(gave back {((trade.max_profit - current_pnl) / trade.max_profit * 100):.0f}%) — CLOSED"
        )
        try:
            from app.quant.tasks import record_to_graph
            minutes_in_trade = _get_minutes_in_trade(trade)
            giveback_pct = (trade.max_profit - current_pnl) / trade.max_profit * 100
            record_to_graph.delay({
                'type': 'exit_event',
                'trade_id': str(position.ticket),
                'symbol': position.symbol,
                'phase': 'PROFIT_PROTECT',
                'trigger_value': float(giveback_pct),
                'action': f'Closed after {giveback_pct:.0f}% giveback from peak ${trade.max_profit:.2f}',
                'pnl_at_event': float(current_pnl),
                'minutes_in_trade': int(minutes_in_trade),
            })
        except Exception:
            pass
        return True
    else:
        logger.warning(f"PROFIT PROTECTION: Failed to close {position.symbol} ticket={position.ticket}")
        return False


# ---------------------------------------------------------------------------
# Scale-In: Livermore "feeling-out bet"
# ---------------------------------------------------------------------------

def _check_scale_in(position, trade, profit_distance, minutes_in_trade):
    """Add remaining 40% position size when trade confirms direction.

    Livermore's principle: enter with a small "feeling-out" bet (60%), then
    add to winners once the market confirms your thesis (+1x ATR within 10min).

    Scale-in data is stored in Redis by the entry algorithm:
    - scale_in_remaining:{ticket}  = remaining lots to add
    - scale_in_atr:{ticket}        = ATR at entry time
    - scale_in_done:{ticket}       = True if already scaled in
    """
    if minutes_in_trade < 0:
        return

    try:
        from django.core.cache import cache

        ticket = position.ticket
        remaining_key = f'scale_in_remaining:{ticket}'
        done_key = f'scale_in_done:{ticket}'
        atr_key = f'scale_in_atr:{ticket}'

        # Skip if no scale-in pending for this trade
        remaining_volume = cache.get(remaining_key)
        if remaining_volume is None:
            return

        # Skip if already scaled in
        if cache.get(done_key):
            return

        entry_atr = cache.get(atr_key)
        if entry_atr is None:
            # Fallback to trade.entry_atr
            entry_atr = trade.entry_atr
        if entry_atr is None or entry_atr <= 0:
            return

        symbol = position.symbol
        position_type = position.type  # 0=BUY, 1=SELL

        # Check timeout: trade did not confirm within SCALE_IN_MAX_MINUTES
        if minutes_in_trade > SCALE_IN_MAX_MINUTES:
            cache.delete(remaining_key)
            cache.delete(atr_key)
            logger.info(
                f"SCALE-IN EXPIRED: {symbol} ticket={ticket} did not confirm "
                f"within {SCALE_IN_MAX_MINUTES}min, staying at 60%"
            )
            return

        # Check confirmation: profit distance >= 1x ATR
        if profit_distance < entry_atr * SCALE_IN_ATR_THRESHOLD:
            return

        # Trade confirmed! Send additional order for remaining volume
        order_type = 'BUY' if position_type == BUY else 'SELL'

        logger.info(
            f"SCALE-IN CONFIRMED: {symbol} ticket={ticket} {order_type} "
            f"+{profit_distance:.5f} >= {entry_atr * SCALE_IN_ATR_THRESHOLD:.5f} ATR threshold, "
            f"adding {remaining_volume} lots"
        )

        try:
            # Use same SL/TP as original position
            sl = position.sl
            tp = position.tp

            order = send_market_order(
                symbol=symbol,
                volume=float(remaining_volume),
                order_type=order_type,
                sl=float(sl) if sl and sl != 0 else 0.0,
                tp=float(tp) if tp and tp != 0 else None,
                deviation=20,
                type_filling="ORDER_FILLING_IOC",
                comment=f'Scale-in for ticket {ticket}',
            )

            if order is not None:
                cache.set(done_key, True, timeout=3600)
                cache.delete(remaining_key)
                cache.delete(atr_key)

                # Create Trade record so close/trailing algorithms can manage it
                try:
                    from app.utils.db.create import create_trade
                    from app.nexus.models import TradeFeature

                    scale_vol = float(remaining_volume)
                    parent_vol = trade.order_volume or 1
                    scale_trade, _ = create_trade(
                        order=order,
                        symbol=symbol,
                        capital=trade.capital,
                        position_size_usd=trade.position_size_usd * (scale_vol / parent_vol),
                        leverage=trade.leverage,
                        commission=trade.order_commission or 0,
                        type=order_type,
                        broker=trade.broker,
                        market=trade.market_type,
                        strategy=trade.strategy,
                        timeframe=trade.timeframe,
                        order_volume=scale_vol,
                        sl=float(sl) if sl and sl != 0 else 0.0,
                        tp=float(tp) if tp and tp != 0 else None,
                    )
                    if scale_trade:
                        scale_trade.entry_atr = trade.entry_atr
                        scale_trade.entry_timeframe = trade.entry_timeframe
                        scale_trade.strategy_config = trade.strategy_config
                        scale_trade.save(update_fields=['entry_atr', 'entry_timeframe', 'strategy_config'])

                        # Inherit ML features from parent trade
                        parent_tf = TradeFeature.objects.filter(trade=trade).first()
                        if parent_tf and parent_tf.features_json:
                            feat = parent_tf.features_json.copy() if isinstance(parent_tf.features_json, dict) else {}
                            feat['is_scale_in'] = True
                            feat['parent_trade_id'] = trade.id
                            TradeFeature.objects.create(
                                trade=scale_trade,
                                features_json=feat,
                                ml_score=parent_tf.ml_score,
                                ml_accepted=True,
                            )

                        logger.info(f"SCALE-IN TRADE RECORD: #{scale_trade.id} created for order {order.get('order')}")
                except Exception as e:
                    logger.error(f"SCALE-IN: order placed but Trade record failed: {e}")

                logger.info(
                    f"SCALE-IN SUCCESS: {symbol} ticket={ticket} "
                    f"added {remaining_volume} lots, new order={order.get('order', 'unknown')}"
                )
                try:
                    from app.quant.tasks import record_to_graph
                    record_to_graph.delay({
                        'type': 'exit_event',
                        'trade_id': str(ticket),
                        'symbol': symbol,
                        'phase': 'SCALE_IN',
                        'trigger_value': float(profit_distance),
                        'action': f'Added {remaining_volume} lots after +1x ATR confirmation',
                        'pnl_at_event': float(position.profit),
                        'minutes_in_trade': int(minutes_in_trade),
                    })
                except Exception:
                    pass
            else:
                logger.warning(
                    f"SCALE-IN FAILED: {symbol} ticket={ticket} "
                    f"order returned None, will retry next cycle"
                )

        except Exception as e:
            logger.error(
                f"SCALE-IN ERROR: {symbol} ticket={ticket} "
                f"failed to send order: {e}\n{traceback.format_exc()}"
            )

    except Exception as e:
        logger.error(f"Scale-in check error for ticket {position.ticket}: {e}")


# ---------------------------------------------------------------------------
# Phase 1.5: M5 Dynamic TP/SL Management
# ---------------------------------------------------------------------------

# Activate when price is this far (fraction) toward TP
_M5_ACTIVATE_PROGRESS  = 0.70   # 70% of the way to TP
# TP extension: push TP out by this many ATRs when M5 momentum is strong
_M5_TP_EXTEND_ATR      = 0.5
_M5_TP_MAX_EXTENSIONS  = 2      # hard cap — don't extend infinitely
# SL tighten: pull SL this close to current price on reversal candle
_M5_SL_TIGHTEN_ATR     = 0.25
# TP compress: bring TP this close to current price on reversal (quick fill)
_M5_TP_COMPRESS_ATR    = 0.35


def _check_m5_tp_management(position, profit_distance: float, current_atr: float, df_m5=None):
    """
    When price is ≥70% of the way to TP, check the last 3 M5 bars:
      • Strong momentum (3 bars moving in direction) → extend TP by 0.5 ATR
      • Reversal candle (engulfing against direction) → tighten SL + compress TP
        to lock the open profit and force a quick fill.

    TP extensions are capped at 2 per trade. SL tightening fires once.
    Accepts pre-fetched df_m5 to avoid duplicate API calls when called from
    _manage_single_position() which already fetches for adaptive trail.
    """
    try:
        tp = float(position.tp or 0)
        if tp == 0:
            return

        entry_price = float(position.price_open)
        current_price = float(position.price_current)
        sl = float(position.sl or 0)
        is_buy = int(position.type) == BUY

        tp_dist = abs(tp - entry_price)
        if tp_dist == 0:
            return

        progress = profit_distance / tp_dist
        if progress < _M5_ACTIVATE_PROGRESS:
            return  # Not in the TP zone yet

        # Use pre-fetched bars if available, otherwise fetch now
        if df_m5 is None:
            df_m5 = _fetch_m5_bars(position.symbol)
        if df_m5 is None or len(df_m5) < 4:
            return

        momentum, reversal = _m5_signals(df_m5, is_buy)

        from django.core.cache import cache
        ticket = position.ticket
        ext_key = f'tp_ext:{ticket}'
        lock_key = f'sl_lock:{ticket}'

        if momentum and not cache.get(lock_key):
            ext_count = cache.get(ext_key, 0)
            if ext_count < _M5_TP_MAX_EXTENSIONS:
                new_tp = tp + (_M5_TP_EXTEND_ATR * current_atr if is_buy
                               else -_M5_TP_EXTEND_ATR * current_atr)
                result = modify_sl_tp(position, sl,
                                      round(new_tp, 5) if new_tp else None)
                if result is not None and result != 'MARKET_CLOSED':
                    cache.set(ext_key, ext_count + 1, timeout=86400)
                    logger.info(
                        f"M5 TP EXTENDED #{ext_count + 1}: {position.symbol} "
                        f"ticket={ticket} progress={progress:.0%} "
                        f"tp {tp:.5f} → {new_tp:.5f} (+{_M5_TP_EXTEND_ATR}×ATR)"
                    )

        elif reversal and not cache.get(lock_key):
            # Tighten SL and compress TP to capture what's already on the table
            if is_buy:
                new_sl = max(sl, current_price - _M5_SL_TIGHTEN_ATR * current_atr)
                new_tp = min(tp, current_price + _M5_TP_COMPRESS_ATR * current_atr)
            else:
                new_sl = min(sl, current_price + _M5_SL_TIGHTEN_ATR * current_atr)
                new_tp = max(tp, current_price - _M5_TP_COMPRESS_ATR * current_atr)

            sl_improved  = (is_buy and new_sl > sl) or (not is_buy and new_sl < sl)
            tp_compressed = (is_buy and new_tp < tp) or (not is_buy and new_tp > tp)

            if sl_improved or tp_compressed:
                result = modify_sl_tp(position,
                                      round(new_sl, 5) if sl_improved else sl,
                                      round(new_tp, 5) if tp_compressed else None)
                if result is not None and result != 'MARKET_CLOSED':
                    cache.set(lock_key, True, timeout=86400)
                    logger.info(
                        f"M5 LOCK-IN: {position.symbol} ticket={ticket} "
                        f"progress={progress:.0%} reversal candle — "
                        f"sl {sl:.5f}→{new_sl:.5f} | tp {tp:.5f}→{new_tp:.5f}"
                    )

    except Exception as e:
        logger.debug(f"M5 TP management error {position.ticket}: {e}")


def _fetch_m5_bars(symbol: str):
    """Fetch last 8 M5 bars from MT5. Returns DataFrame or None."""
    try:
        return fetch_data_pos(symbol, MT5Timeframe.M5, 8)
    except Exception:
        return None


def _m5_signals(df_m5, is_buy: bool) -> tuple[bool, bool]:
    """
    Analyse last 3 completed M5 bars.

    Returns (momentum: bool, reversal: bool).
      momentum = all 3 bars closing in trade direction
      reversal = last bar is an engulfing candle against trade direction
    """
    try:
        bars = df_m5.iloc[-4:-1]   # last 3 completed bars (exclude still-forming)
        if len(bars) < 3:
            return False, False

        opens  = bars['open'].tolist()
        closes = bars['close'].tolist()

        # Momentum: all 3 bars green (buy) or red (sell)
        if is_buy:
            momentum = all(closes[i] > opens[i] for i in range(3))
            # Reversal: last bar is strongly bearish and body > prior bar's body
            prev_body = abs(closes[-2] - opens[-2])
            last_body = abs(closes[-1] - opens[-1])
            reversal  = closes[-1] < opens[-1] and last_body > prev_body * 0.8
        else:
            momentum = all(closes[i] < opens[i] for i in range(3))
            prev_body = abs(closes[-2] - opens[-2])
            last_body = abs(closes[-1] - opens[-1])
            reversal  = closes[-1] > opens[-1] and last_body > prev_body * 0.8

        return momentum, reversal

    except Exception:
        return False, False


# ---------------------------------------------------------------------------
# Phase 0: MFE Acceleration
# ---------------------------------------------------------------------------

def _check_mfe_acceleration(position, trade, current_pnl, minutes_in_trade, current_atr):
    """MFE-optimized exit management based on time + profit analysis.

    Data shows: 92% of wins hit $5+ profit, winners average 26 min,
    losers average 70 min. This phase aggressively locks fast profits
    and kills trades going nowhere.

    Returns True if trade was closed (caller should return early).
    """
    if minutes_in_trade < 0:
        return False

    position_type = position.type
    entry_price = position.price_open
    current_price = position.price_current
    current_sl = position.sl
    current_tp = position.tp

    # --- Rule 1: Lock in 60% of profit on fast movers ---
    # If trade hit $5+ profit within 15 min, it's a fast mover — lock it in
    if current_pnl >= MFE_PROFIT_THRESHOLD and minutes_in_trade <= MFE_LOCK_MINUTES:
        # Calculate price level that locks in 60% of current unrealized profit
        if position_type == BUY:
            profit_distance = current_price - entry_price
            lock_distance = profit_distance * MFE_LOCK_FRACTION
            new_sl = entry_price + lock_distance
        else:
            profit_distance = entry_price - current_price
            lock_distance = profit_distance * MFE_LOCK_FRACTION
            new_sl = entry_price - lock_distance

        if _is_better_sl(position_type, new_sl, current_sl):
            result = modify_sl_tp(
                position, new_sl,
                current_tp if current_tp and current_tp != 0 else None,
            )
            if result is not None:
                logger.info(
                    f"MFE LOCK: {position.symbol} ticket={position.ticket} "
                    f"${current_pnl:.2f} profit in {minutes_in_trade}min — "
                    f"SL locked at {new_sl:.5f} (60% of ${profit_distance*10000:.0f}pips)"
                )
                try:
                    from app.quant.tasks import record_to_graph
                    record_to_graph.delay({
                        'type': 'exit_event',
                        'trade_id': str(position.ticket),
                        'symbol': position.symbol,
                        'phase': 'MFE_LOCK',
                        'trigger_value': float(current_pnl),
                        'action': f'SL locked at {new_sl:.5f} after ${current_pnl:.2f} profit in {minutes_in_trade}min',
                        'pnl_at_event': float(current_pnl),
                        'minutes_in_trade': int(minutes_in_trade),
                    })
                except Exception:
                    pass
        return False  # Don't close, just lock — let it run with protection

    # --- Rule 2: Kill flat trades after 20 min ---
    # Data shows trades going nowhere after 20 min have negative expected value
    if minutes_in_trade >= FLAT_TRADE_MINUTES and current_pnl < FLAT_TRADE_MIN_PROFIT:
        result = close_full(position.ticket, position.symbol, position.type, position.volume)
        if result is not None:
            logger.info(
                f"MFE FLAT EXIT: {position.symbol} ticket={position.ticket} "
                f"${current_pnl:.2f} after {minutes_in_trade}min — no momentum, closing"
            )
            try:
                from app.quant.tasks import record_to_graph
                record_to_graph.delay({
                    'type': 'exit_event',
                    'trade_id': str(position.ticket),
                    'symbol': position.symbol,
                    'phase': 'MFE_FLAT_EXIT',
                    'trigger_value': float(current_pnl),
                    'action': f'Killed flat trade after {minutes_in_trade}min with ${current_pnl:.2f} profit',
                    'pnl_at_event': float(current_pnl),
                    'minutes_in_trade': int(minutes_in_trade),
                })
            except Exception:
                pass
            return True
        else:
            logger.warning(
                f"MFE FLAT EXIT: Failed to close {position.symbol} ticket={position.ticket}"
            )

    return False


def _get_minutes_in_trade(trade):
    """Calculate how many minutes the trade has been open."""
    if trade.entry_time is None:
        return -1

    from datetime import datetime, timezone as tz
    now = datetime.now(tz.utc)
    entry = trade.entry_time

    if entry.tzinfo is None:
        import pytz
        entry = pytz.utc.localize(entry)

    delta = now - entry
    return int(delta.total_seconds() / 60)


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
        # SL is already better than entry — mark breakeven as achieved
        trade.breakeven_moved = True
        trade.save(update_fields=['breakeven_moved'])
        logger.info(
            f"BREAKEVEN: {position.symbol} ticket={position.ticket} "
            f"SL={current_sl:.5f} already past entry={entry_price:.5f} — marking achieved"
        )
        return

    result = modify_sl_tp(position, new_sl, current_tp if current_tp and current_tp != 0 else None)
    if result == 'MARKET_CLOSED':
        return  # Market closed — will retry on next cycle when market reopens
    elif result is not None:
        trade.breakeven_moved = True
        trade.save(update_fields=['breakeven_moved'])
        logger.info(
            f"BREAKEVEN: {position.symbol} ticket={position.ticket} "
            f"moved SL to {new_sl:.5f} (entry={entry_price:.5f})"
        )
        try:
            from app.quant.tasks import record_to_graph
            minutes_in_trade = _get_minutes_in_trade(trade)
            record_to_graph.delay({
                'type': 'exit_event',
                'trade_id': str(position.ticket),
                'symbol': position.symbol,
                'phase': 'BREAKEVEN',
                'trigger_value': float(profit_distance),
                'action': f'SL moved to entry {new_sl:.5f} after {profit_distance / trade.entry_atr:.1f}R profit',
                'pnl_at_event': float(position.profit),
                'minutes_in_trade': int(minutes_in_trade),
            })
        except Exception:
            pass
    else:
        logger.warning(f"BREAKEVEN: Failed to modify SL for {position.symbol} ticket={position.ticket}")


# ---------------------------------------------------------------------------
# Phase 2: Partial Close
# ---------------------------------------------------------------------------

def _check_partial_close(position, trade, profit_distance):
    """Tiered partial close: 30% at 1.5R, 30% at 3R, trail remaining 40%.

    Locks profits incrementally — early lock secures gains, middle lock
    captures momentum, final 40% rides on structural trailing for home runs.
    """
    if not trade.breakeven_moved:
        return

    if trade.entry_atr is None or trade.entry_atr <= 0:
        return

    position_type = position.type
    position_volume = position.volume
    current_price = position.price_current

    for tier in PARTIAL_CLOSE_TIERS:
        flag = tier['flag']

        # Check if this tier was already triggered
        if getattr(trade, 'partial_closed', False) and flag == 'partial_1':
            # partial_closed=True means tier 1 done (backward compat)
            continue

        # Use Redis cache for tier tracking (avoids DB schema changes)
        try:
            from django.core.cache import cache
            tier_key = f"partial_{flag}:{position.ticket}"
            if cache.get(tier_key):
                continue
        except Exception:
            continue

        # Check if profit reached this tier's threshold
        if profit_distance < trade.entry_atr * tier['atr_mult']:
            break  # Tiers are ordered — if this one isn't hit, later ones won't be either

        # Calculate volume to close
        partial_vol = round(position_volume * tier['close_pct'], 2)
        if partial_vol < 0.01:
            logger.debug(
                f"PARTIAL CLOSE T{tier['atr_mult']}: {position.symbol} "
                f"volume too small ({partial_vol}), skipping"
            )
            continue

        result = close_partial(position.ticket, position.symbol, position_type, partial_vol)
        if result is not None:
            # Mark tier as done
            try:
                from django.core.cache import cache
                cache.set(f"partial_{flag}:{position.ticket}", True, timeout=86400)
            except Exception:
                pass

            # Update trade record (backward compat with partial_closed field)
            if flag == 'partial_1':
                trade.partial_closed = True
                trade.partial_close_volume = partial_vol
                trade.partial_close_price = current_price
                trade.save(update_fields=['partial_closed', 'partial_close_volume', 'partial_close_price'])

            profit_r = profit_distance / trade.entry_atr
            logger.info(
                f"PARTIAL CLOSE ({tier['atr_mult']}R): {position.symbol} "
                f"ticket={position.ticket} closed {partial_vol} lots "
                f"({tier['close_pct']:.0%}) at {current_price:.5f} "
                f"(profit={profit_r:.1f}R)"
            )
            try:
                from app.quant.tasks import record_to_graph
                minutes_in_trade = _get_minutes_in_trade(trade)
                record_to_graph.delay({
                    'type': 'exit_event',
                    'trade_id': str(position.ticket),
                    'symbol': position.symbol,
                    'phase': 'PARTIAL_CLOSE',
                    'trigger_value': float(profit_r),
                    'action': f"Closed {partial_vol} lots ({tier['close_pct']:.0%}) at {tier['atr_mult']}R",
                    'pnl_at_event': float(position.profit),
                    'minutes_in_trade': int(minutes_in_trade),
                })
            except Exception:
                pass
        else:
            logger.warning(
                f"PARTIAL CLOSE ({tier['atr_mult']}R): Failed for "
                f"{position.symbol} ticket={position.ticket}"
            )


# ---------------------------------------------------------------------------
# Phase 3: Swing Trail
# ---------------------------------------------------------------------------

def _check_swing_trail(position, trade, df, current_atr):
    """Trail SL using multi-TF structure, escalating timeframe with profit.

    Phase 3a: <2R profit → trail on entry timeframe (tight, responsive)
    Phase 3b: 2-4R profit → trail on H1 structure (wider, for bigger moves)
    Phase 3c: 4R+ profit → trail on H4 structure (let it ride — Livermore "sit tight")

    Also checks for structure invalidation (BOS/CHoCH against position).
    """
    if not trade.breakeven_moved:
        return

    if df is None or len(df) < (2 * SWING_TRAIL_LOOKBACK + 1):
        return

    position_type = position.type
    current_sl = position.sl
    current_tp = position.tp
    entry_price = position.price_open
    current_price = position.price_current

    # Calculate profit in ATR multiples for timeframe escalation
    profit_distance = (current_price - entry_price) if position_type == BUY else (entry_price - current_price)
    profit_r = profit_distance / trade.entry_atr if trade.entry_atr and trade.entry_atr > 0 else 0

    # Structure invalidation check — exit if structure breaks against us
    if _check_structure_invalidation(position, trade, df, profit_distance):
        return

    # Determine trailing timeframe based on profit level
    trailing_tf = _resolve_timeframe(trade)
    trail_label = "SWING"

    if profit_r >= 4.0:
        trailing_tf = MT5Timeframe.H4
        trail_label = "H4-STRUCT"
    elif profit_r >= 2.0:
        trailing_tf = MT5Timeframe.H1
        trail_label = "H1-STRUCT"

    # Try S/R-based trailing on the selected timeframe
    candidate_sl = _get_sr_trail_level(
        position.symbol, position_type, entry_price, current_price,
        current_sl, current_atr,
    )

    # For elevated timeframes, also fetch that TF's swings
    if candidate_sl is None and trailing_tf != _resolve_timeframe(trade):
        try:
            htf_df = fetch_data_pos(position.symbol, trailing_tf, 50)
            if htf_df is not None and len(htf_df) >= (2 * 5 + 1):
                if position_type == BUY:
                    swing_values = _find_swing_low_values(htf_df['low'].values, 5)
                    if swing_values:
                        candidate_sl = swing_values[-1] - (current_atr * SWING_TRAIL_ATR_BUFFER)
                else:
                    swing_values = _find_swing_high_values(htf_df['high'].values, 5)
                    if swing_values:
                        candidate_sl = swing_values[-1] + (current_atr * SWING_TRAIL_ATR_BUFFER)
        except Exception as e:
            logger.debug(f"HTF swing trail fetch failed for {position.symbol}: {e}")

    # Fallback to entry-timeframe swing detection
    if candidate_sl is None:
        if position_type == BUY:
            swing_values = _find_swing_low_values(df['low'].values, SWING_TRAIL_LOOKBACK)
            if swing_values:
                candidate_sl = swing_values[-1] - (current_atr * SWING_TRAIL_ATR_BUFFER)
        else:
            swing_values = _find_swing_high_values(df['high'].values, SWING_TRAIL_LOOKBACK)
            if swing_values:
                candidate_sl = swing_values[-1] + (current_atr * SWING_TRAIL_ATR_BUFFER)
        trail_label = "SWING"

    if candidate_sl is None:
        return

    if _is_better_sl(position_type, candidate_sl, current_sl):
        result = modify_sl_tp(
            position, candidate_sl,
            current_tp if current_tp and current_tp != 0 else None
        )
        if result == 'MARKET_CLOSED':
            return  # Market closed — will retry when market reopens
        if result is not None:
            logger.info(
                f"{trail_label} TRAIL: {position.symbol} ticket={position.ticket} "
                f"{'BUY' if position_type == BUY else 'SELL'} SL -> {candidate_sl:.5f} "
                f"(profit={profit_r:.1f}R)"
            )
            try:
                from app.quant.tasks import record_to_graph
                minutes_in_trade = _get_minutes_in_trade(trade)
                record_to_graph.delay({
                    'type': 'exit_event',
                    'trade_id': str(position.ticket),
                    'symbol': position.symbol,
                    'phase': 'TRAIL',
                    'trigger_value': float(candidate_sl),
                    'action': f'{trail_label} SL -> {candidate_sl:.5f} at {profit_r:.1f}R',
                    'pnl_at_event': float(position.profit),
                    'minutes_in_trade': int(minutes_in_trade),
                })
            except Exception:
                pass


def _check_structure_invalidation(position, trade, df, profit_distance):
    """Exit immediately if market structure breaks against the position.

    A CHoCH against our direction means the thesis is invalid — get out.
    Only applies after breakeven is set (we have a risk-free position).
    Returns True if trade was closed.
    """
    if not trade.breakeven_moved:
        return False

    # Don't invalidate if we're significantly in profit (>2R) — structure
    # breaks can be temporary in strong trends
    if trade.entry_atr and profit_distance > trade.entry_atr * 2:
        return False

    try:
        from app.quant.indicators.smc_detector import detect_market_structure
        ms_df = detect_market_structure(df, swing_lookback=5)

        if ms_df is None or len(ms_df) < 3:
            return False

        position_type = position.type

        # Check last 3 bars for a CHoCH against our direction
        for i in range(max(0, len(ms_df) - 3), len(ms_df)):
            choch_val = ms_df['CHOCH'].iloc[i]
            if pd.isna(choch_val):
                continue

            # Bearish CHoCH against a BUY, or bullish CHoCH against a SELL
            if (position_type == BUY and choch_val == -1) or \
               (position_type == SELL and choch_val == 1):
                result = close_full(position.ticket, position.symbol, position.type, position.volume)
                if result is not None:
                    current_pnl = position.profit
                    logger.info(
                        f"STRUCTURE INVALIDATION: {position.symbol} ticket={position.ticket} "
                        f"CHoCH against {'BUY' if position_type == BUY else 'SELL'} "
                        f"at bar {i} — CLOSED (PnL=${current_pnl:.2f})"
                    )
                    return True
    except Exception as e:
        logger.debug(f"Structure invalidation check failed: {e}")

    return False


def _get_sr_trail_level(symbol, position_type, entry_price, current_price,
                        current_sl, current_atr):
    """Find the best S/R level for trailing stop placement.

    For BUY: find the highest support level that is below current price
    but above the current SL (i.e., tightens the stop along structure).
    For SELL: find the lowest resistance level above current price but
    below the current SL.
    """
    try:
        from app.quant.indicators.support_resistance import find_multi_tf_sr
        from app.utils.api.data import fetch_data_pos

        sr_levels = find_multi_tf_sr(symbol, fetch_data_pos, current_atr)
        buffer = current_atr * SWING_TRAIL_ATR_BUFFER

        if position_type == BUY:
            # Find support levels between current_sl and current_price
            candidates = [
                s for s in sr_levels.get('support', [])
                if s['price'] < current_price - buffer
                and (current_sl is None or current_sl == 0 or s['price'] - buffer > current_sl)
                and s['price'] > entry_price  # Only trail above entry (already at breakeven)
            ]
            if candidates:
                # Use the highest (closest to price) for tightest trail
                best = max(candidates, key=lambda x: x['price'])
                return best['price'] - buffer

        else:  # SELL
            candidates = [
                r for r in sr_levels.get('resistance', [])
                if r['price'] > current_price + buffer
                and (current_sl is None or current_sl == 0 or r['price'] + buffer < current_sl)
                and r['price'] < entry_price  # Only trail below entry
            ]
            if candidates:
                best = min(candidates, key=lambda x: x['price'])
                return best['price'] + buffer

    except Exception as e:
        logger.debug(f"S/R trail lookup failed for {symbol}: {e}")

    return None


# ---------------------------------------------------------------------------
# Adaptive ATR-% Trail (from entry, M5 candle-adaptive)
# ---------------------------------------------------------------------------

def _check_adaptive_trail(position, trade, df_m5=None) -> bool:
    """Trail SL from entry using entry_atr (H1-based), adapting distance with M5 candle shape.

    Multiplier logic (applied to entry_atr, SL ratchets — never loosened):
      • Default: 2.0x ATR behind best price
      • Strong M5 momentum (3 consecutive bars in direction): 2.5x — give room to run
      • M5 reversal engulfing candle: 1.5x — lock in profits faster

    Hard cutoff: if adverse price move > 2.0x entry_atr from entry, force-close immediately.
    This backstop catches gaps and slippage past the broker SL.

    Returns True if the position was force-closed (caller should return early).
    """
    if trade.entry_atr is None or trade.entry_atr <= 0:
        return False

    from django.core.cache import cache

    position_type = position.type
    entry_price   = float(position.price_open)
    current_price = float(position.price_current)
    current_sl    = float(position.sl or 0)
    current_tp    = position.tp
    ticket        = position.ticket

    # ── Hard cutoff: adverse move beyond 2x entry ATR (gap / slippage backstop) ──
    adverse = (entry_price - current_price) if position_type == BUY else (current_price - entry_price)
    if adverse > ADAPTIVE_TRAIL_CUTOFF_MULT * trade.entry_atr:
        result = close_full(position.ticket, position.symbol, position.type, position.volume)
        if result is not None:
            logger.warning(
                f"ADAPTIVE CUTOFF: {position.symbol} ticket={ticket} "
                f"adverse={adverse:.5f} > {ADAPTIVE_TRAIL_CUTOFF_MULT}x entry_atr "
                f"({ADAPTIVE_TRAIL_CUTOFF_MULT * trade.entry_atr:.5f}) — FORCE CLOSED"
            )
        return True

    # ── Determine multiplier from M5 candle shape ──
    mult_key    = f'adaptive_mult:{ticket}'
    current_mult = cache.get(mult_key) or ADAPTIVE_TRAIL_BASE_MULT

    if df_m5 is not None and len(df_m5) >= 4:
        is_buy   = position_type == BUY
        momentum, reversal = _m5_signals(df_m5, is_buy)
        new_mult = (ADAPTIVE_TRAIL_REVERSAL_MULT if reversal
                    else ADAPTIVE_TRAIL_MOMENTUM_MULT if momentum
                    else ADAPTIVE_TRAIL_BASE_MULT)
        if new_mult != current_mult:
            cache.set(mult_key, new_mult, timeout=86400)
            current_mult = new_mult

    # ── Compute trailing SL: best_price − (multiplier × entry_atr) ──
    trail_dist = current_mult * trade.entry_atr
    trail_sl   = (current_price - trail_dist) if position_type == BUY else (current_price + trail_dist)

    # Ratchet: only tighten — never pull SL back
    if not _is_better_sl(position_type, trail_sl, current_sl):
        return False

    result = modify_sl_tp(
        position, round(trail_sl, 5),
        current_tp if current_tp and current_tp != 0 else None,
    )
    if result == 'MARKET_CLOSED':
        return False
    if result is not None:
        logger.debug(
            f"ADAPTIVE TRAIL: {position.symbol} ticket={ticket} "
            f"{'BUY' if position_type == BUY else 'SELL'} SL -> {trail_sl:.5f} "
            f"({current_mult}x ATR={trade.entry_atr:.5f})"
        )
    return False


# ---------------------------------------------------------------------------
# Phase 3b: ATR Floor Trail (always-on ratchet)
# ---------------------------------------------------------------------------

def _check_atr_floor_trail(position, trade, profit_distance, current_atr):
    """Always-on trailing stop that ratchets 1.5x ATR behind the best price.

    Unlike swing/S/R trailing which depends on finding structural levels,
    this trail ALWAYS tightens as the trade moves in profit. It acts as a
    floor — the swing trail can set a tighter SL, but this ensures SL
    never lags more than 1.5x ATR behind the peak favorable price.

    With 2-second tick interval, this creates aggressive profit locking
    on fast-moving instruments like XAGUSD and XAUUSD.
    """
    if trade.entry_atr is None or trade.entry_atr <= 0:
        return

    # Only activate after minimum profit threshold (1R)
    if profit_distance < trade.entry_atr * ATR_FLOOR_MIN_PROFIT_R:
        return

    position_type = position.type
    entry_price = position.price_open
    current_price = position.price_current
    current_sl = position.sl
    current_tp = position.tp

    # Calculate the floor SL: best price - 1.5x ATR
    trail_distance = current_atr * ATR_FLOOR_TRAIL_MULT

    if position_type == BUY:
        # Best price for BUY is the highest price reached
        # We approximate from current price (max_profit tracks $, not price)
        floor_sl = current_price - trail_distance
    else:
        # Best price for SELL is the lowest price reached
        floor_sl = current_price + trail_distance

    # Only move SL if it improves (tightens) the position
    if not _is_better_sl(position_type, floor_sl, current_sl):
        return

    # Ensure floor SL is past breakeven (don't go backwards)
    if position_type == BUY and floor_sl <= entry_price:
        return
    if position_type == SELL and floor_sl >= entry_price:
        return

    result = modify_sl_tp(
        position, floor_sl,
        current_tp if current_tp and current_tp != 0 else None
    )
    if result == 'MARKET_CLOSED':
        return
    if result is not None:
        profit_r = profit_distance / trade.entry_atr if trade.entry_atr else 0
        logger.info(
            f"ATR FLOOR TRAIL: {position.symbol} ticket={position.ticket} "
            f"SL -> {floor_sl:.5f} ({ATR_FLOOR_TRAIL_MULT}x ATR behind price) "
            f"profit={profit_r:.1f}R, locking ${position.profit:.2f}"
        )
    else:
        logger.warning(
            f"ATR FLOOR TRAIL: {position.symbol} ticket={position.ticket} "
            f"modify FAILED — wanted SL={floor_sl:.5f} (current={current_sl:.5f})"
        )


# ---------------------------------------------------------------------------
# Phase 4: Time Exit
# ---------------------------------------------------------------------------

def _check_time_exit(position, trade, current_pnl, minutes_in_trade):
    """Close positions that haven't moved significantly after 30 minutes.

    MFE/MAE data shows: avg winner takes 26 min, avg loser takes 70 min.
    Trades lingering past 30 min with <$2 profit have negative expected value.
    """
    if minutes_in_trade < 0:
        return

    if minutes_in_trade <= TIME_EXIT_MINUTES:
        return

    if current_pnl >= TIME_EXIT_MIN_PROFIT:
        return

    result = close_full(position.ticket, position.symbol, position.type, position.volume)
    if result is not None:
        logger.info(
            f"TIME EXIT: {position.symbol} ticket={position.ticket} "
            f"${current_pnl:.2f} after {minutes_in_trade}min (threshold: "
            f"{TIME_EXIT_MINUTES}min with <${TIME_EXIT_MIN_PROFIT})"
        )
        try:
            from app.quant.tasks import record_to_graph
            record_to_graph.delay({
                'type': 'exit_event',
                'trade_id': str(position.ticket),
                'symbol': position.symbol,
                'phase': 'TIME_EXIT',
                'trigger_value': float(minutes_in_trade),
                'action': f'Closed stale trade after {minutes_in_trade}min with ${current_pnl:.2f} profit',
                'pnl_at_event': float(current_pnl),
                'minutes_in_trade': int(minutes_in_trade),
            })
        except Exception:
            pass
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
