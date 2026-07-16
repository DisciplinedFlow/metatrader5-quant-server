"""
entry_forex.py — Donchian Breakout System for Extreme Volatility

Replaces the sweep-fade strategies with a trend-following Donchian breakout
approach, activated ONLY when ATR(14) > 1.5x its 20-period SMA (extreme vol).

Vol-regime gate:
    H1 ATR(14) must exceed 1.5x its 20-bar SMA on the symbol being traded.
    When vol is normal, this algorithm does nothing (normal-vol strategies TBD).

Donchian breakout:
    entry_period=15 (reduced 25% from standard 20 for high vol)
    EMA filter=50
    XAUUSD on H1, all other symbols on M15
    Only 'long_confirmed' or 'short_confirmed' signals from donchian_trend_filter

Directional bias:
    XAUUSD  — LONG ONLY  (safe haven in war)
    USDJPY  — SHORT ONLY (JPY safe haven)
    USDCHF  — SHORT ONLY (CHF safe haven)
    EURUSD  — sell bias but both allowed
    GBPUSD, AUDUSD, XAGUSD, USDCAD — both directions

Risk:
    €7.50 per trade (half size for extreme vol)
    SL = 2.5x ATR (wider for vol)
    TP = 5.0x ATR (safety net only — Donchian exit trail manages real exit)
    No fixed TP philosophy: trail should close before safety TP hits

Session: 07:00–17:00 UTC (London + NY overlap)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
from django.core.cache import cache

from app.utils.api.data import fetch_data_pos
from app.utils.api.order import send_market_order
from app.utils.api.positions import get_positions
from app.utils.api.data import symbol_info_tick
from app.utils.arithmetics import calculate_risk_based_lots
from app.utils.constants import MT5Timeframe
from app.quant.indicators.donchian import donchian_trend_filter

logger = logging.getLogger('quant')

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
RISK_EUR = 7.50               # Half size for extreme vol
MAX_LOT = 0.10
SL_ATR_MULT = 2.5             # Wider stops for extreme vol
TP_ATR_MULT = 5.0             # Safety-net TP only (Donchian exit trail manages)
COOLDOWN_TTL = 1800            # 30min cooldown
MAX_DAILY_LOSS = -50.0
DAILY_LOSS_KEY = 'fx:daily_loss'

CB_KEY = 'fx:circuit_breaker'
LOSS_KEY = 'fx:consecutive_losses'
CB_LOSSES = 3
CB_TTL = 7200

DONCHIAN_ENTRY_PERIOD = 15     # Reduced 25% from 20 for high vol
DONCHIAN_EMA_PERIOD = 50
VOL_THRESHOLD = 1.5            # ATR must exceed 1.5x its SMA to qualify

# ---------------------------------------------------------------------------
# Symbol groups
# ---------------------------------------------------------------------------
SYMBOLS_H1 = ['XAUUSD']
SYMBOLS_M15 = ['EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'XAGUSD', 'AUDUSD', 'USDCAD']

# Directional bias: None = both directions allowed
DIRECTION_BIAS = {
    'XAUUSD': 'BUY',       # LONG ONLY — safe haven in war
    'USDJPY': 'SELL',       # SHORT ONLY — JPY safe haven
    'USDCHF': 'SELL',       # SHORT ONLY — CHF safe haven
    'EURUSD': None,         # Sell bias but both allowed
    'GBPUSD': None,
    'AUDUSD': None,
    'XAGUSD': None,
    'USDCAD': None,
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def entry_forex_algorithm():
    """Run Donchian breakout scan for all symbols. Called every 60s by Celery beat."""
    if cache.get(CB_KEY):
        return
    if (cache.get(DAILY_LOSS_KEY) or 0) <= MAX_DAILY_LOSS:
        return

    # Session filter: 07:00–17:00 UTC only
    hour = datetime.now(timezone.utc).hour
    if hour < 7 or hour >= 17:
        return

    open_syms = _open_symbols()

    # H1 symbols (XAUUSD)
    for symbol in SYMBOLS_H1:
        if symbol in open_syms or cache.get(f'fx_cd:{symbol}'):
            continue
        _run_donchian(symbol, MT5Timeframe.H1, 'H1')

    # M15 symbols (forex pairs + silver)
    for symbol in SYMBOLS_M15:
        if symbol in open_syms or cache.get(f'fx_cd:{symbol}'):
            continue
        _run_donchian(symbol, MT5Timeframe.M15, 'M15')


# ---------------------------------------------------------------------------
# Donchian breakout scanner
# ---------------------------------------------------------------------------

def _run_donchian(symbol, timeframe, tf_label):
    """Check vol regime, then scan for Donchian breakout on a single symbol."""

    # --- Vol-regime gate (always check on H1) ---
    atr_df = _fetch_bars(symbol, MT5Timeframe.H1, 50)
    if atr_df is None or len(atr_df) < 35:
        return
    atr_df = _add_atr(atr_df, period=14)

    atr_14 = atr_df['atr'].iloc[-1]
    atr_ma_20 = atr_df['atr'].rolling(20).mean().iloc[-1]

    if pd.isna(atr_14) or pd.isna(atr_ma_20) or atr_ma_20 <= 0:
        return

    is_extreme_vol = atr_14 > VOL_THRESHOLD * atr_ma_20
    if not is_extreme_vol:
        return  # Normal vol — skip (normal-vol strategies added later)

    # --- Fetch data for the trading timeframe ---
    bar_count = 250 if timeframe == MT5Timeframe.H1 else 900
    df = _fetch_bars(symbol, timeframe, bar_count)
    if df is None or len(df) < 60:
        return

    # --- Donchian trend filter ---
    signals = donchian_trend_filter(df, params={
        'entry_period': DONCHIAN_ENTRY_PERIOD,
        'ema_period': DONCHIAN_EMA_PERIOD,
    })

    latest_signal = signals.iloc[-1]

    if latest_signal not in ('long_confirmed', 'short_confirmed'):
        return

    direction = 'BUY' if latest_signal == 'long_confirmed' else 'SELL'

    # --- Directional bias filter ---
    bias = DIRECTION_BIAS.get(symbol)
    if bias is not None and direction != bias:
        logger.info(
            '[donchian] %s %s blocked by directional bias (%s only)',
            symbol, direction, bias,
        )
        return

    # --- Compute ATR on the trading timeframe for SL/TP ---
    df = _add_atr(df, period=14 if timeframe == MT5Timeframe.H1 else 56)
    atr_val = df['atr'].iloc[-1]
    if pd.isna(atr_val) or atr_val <= 0:
        return

    logger.info(
        '[donchian] SIGNAL %s %s on %s | atr=%.5f atr14_h1=%.5f atr_ma20=%.5f (%.1fx)',
        symbol, direction, tf_label, atr_val, atr_14, atr_ma_20,
        atr_14 / atr_ma_20,
    )

    _execute(symbol, direction, df, SL_ATR_MULT, TP_ATR_MULT, 'DONCHIAN_BREAKOUT', tf_label)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _execute(symbol, direction, df, sl_mult, tp_mult, strategy_name, timeframe):
    atr_val = df['atr'].iloc[-1]
    sl_dist = sl_mult * atr_val
    tp_dist = tp_mult * atr_val

    tick = symbol_info_tick(symbol)
    if tick is None or tick.empty:
        logger.warning('[fx] No tick data for %s', symbol)
        return

    fill_ref = float(tick['ask'].iloc[0]) if direction == 'BUY' else float(tick['bid'].iloc[0])
    sl = fill_ref - sl_dist if direction == 'BUY' else fill_ref + sl_dist
    tp = fill_ref + tp_dist if direction == 'BUY' else fill_ref - tp_dist

    try:
        from app.quant.algorithms.position_manager import get_dynamic_risk
        dynamic_risk = get_dynamic_risk()
        volume = calculate_risk_based_lots(
            symbol=symbol, sl_distance=sl_dist,
            target_risk=dynamic_risk, order_type=direction,
        )
    except Exception as e:
        logger.error('[fx] Sizing failed %s: %s', symbol, e)
        return

    if not volume or volume <= 0:
        logger.warning('[fx] Could not size %s', symbol)
        return
    if volume > MAX_LOT:
        volume = MAX_LOT

    decimals = 2 if 'XAU' in symbol else 3 if 'XAG' in symbol else 5
    sl_r, tp_r = round(sl, decimals), round(tp, decimals)

    result = send_market_order(
        symbol=symbol, volume=volume, order_type=direction,
        sl=sl_r, tp=tp_r, comment=strategy_name, min_rr=2.0,
    )

    ticket = result.get('order') or result.get('ticket') if result else None
    if not ticket:
        logger.warning('[fx] Rejected %s: %s', symbol, result)
        return

    cache.set(f'fx_cd:{symbol}', True, timeout=COOLDOWN_TTL)
    logger.info(
        '[fx] OPENED %s %s ticket=%s vol=%.2f sl=%s tp=%s atr=%.4f strat=%s',
        symbol, direction, ticket, volume, sl_r, tp_r, atr_val, strategy_name,
    )

    try:
        from app.utils.db.create import create_trade
        trade_obj, _ = create_trade(
            order=result, symbol=symbol, capital=dynamic_risk,
            position_size_usd=0, leverage=500, commission=0,
            type=direction, broker='VantageInternational-Demo',
            market='FOREX', strategy=strategy_name,
            timeframe=timeframe, order_volume=volume,
            sl=sl_r, tp=tp_r,
        )
        if trade_obj:
            trade_obj.entry_atr = atr_val
            trade_obj.entry_timeframe = timeframe
            trade_obj.save(update_fields=['entry_atr', 'entry_timeframe'])

            # Create ML training record
            try:
                from app.nexus.models import TradeFeature
                now = datetime.now(timezone.utc)
                features_dict = {
                    'symbol': symbol,
                    'direction': direction,
                    'strategy': strategy_name,
                    'hour_utc': now.hour,
                    'day_of_week': now.weekday(),
                    'atr': float(atr_val),
                    'sl_distance': float(sl_dist),
                    'tp_distance': float(tp_dist),
                    'entry_price': float(fill_ref),
                    'volume': float(volume),
                    'timeframe': timeframe,
                }
                TradeFeature.objects.create(
                    trade=trade_obj,
                    features_json=features_dict,
                    ml_score=0.0,
                    ml_accepted=True,
                )
                logger.info('[fx] TradeFeature created for %s %s', symbol, direction)
            except Exception as e:
                logger.debug('[fx] TradeFeature creation failed: %s', e)
    except Exception as e:
        logger.error('[fx] Trade record failed %s: %s', symbol, e)


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------

def _add_atr(df, period=14):
    """Add ATR column to dataframe if not already present."""
    if 'atr' in df.columns and df['atr'].notna().sum() > 0:
        return df
    c = df['close']
    tr = np.maximum(df['high'] - df['low'],
                    np.maximum(abs(df['high'] - c.shift(1)), abs(df['low'] - c.shift(1))))
    df['atr'] = tr.rolling(period).mean()
    return df


def _indicators_h1(df):
    c = df['close']
    tr = np.maximum(df['high'] - df['low'],
                    np.maximum(abs(df['high'] - c.shift(1)), abs(df['low'] - c.shift(1))))
    df['atr'] = tr.rolling(14).mean()
    df['ema50'] = c.ewm(span=50, adjust=False).mean()
    df['ema200'] = c.ewm(span=200, adjust=False).mean()
    df['hour'] = df['time'].dt.hour
    df['date'] = df['time'].dt.date
    return df


def _indicators_m15(df):
    c = df['close']
    tr = np.maximum(df['high'] - df['low'],
                    np.maximum(abs(df['high'] - c.shift(1)), abs(df['low'] - c.shift(1))))
    df['atr'] = tr.rolling(56).mean()
    df['ema50'] = c.ewm(span=200, adjust=False).mean()
    df['ema200'] = c.ewm(span=800, adjust=False).mean()
    df['hour'] = df['time'].dt.hour
    df['date'] = df['time'].dt.date
    return df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_bars(symbol, timeframe, count):
    try:
        df = fetch_data_pos(symbol, timeframe, count)
        if df is None or df.empty:
            return None
        df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
        df = df.sort_values('time').reset_index(drop=True)
        return df
    except Exception as e:
        logger.error('[fx] Fetch failed %s: %s', symbol, e)
        return None


def _open_symbols():
    try:
        positions = get_positions()
        if positions is None:
            return set()
        if hasattr(positions, 'empty'):
            return set() if positions.empty else set(positions['symbol'].values)
        return set()
    except Exception:
        return set()


def on_trade_closed(won: bool, pnl: float = 0):
    if won:
        cache.set(LOSS_KEY, 0, timeout=86400)
    else:
        losses = (cache.get(LOSS_KEY) or 0) + 1
        cache.set(LOSS_KEY, losses, timeout=86400)
        if losses >= CB_LOSSES:
            cache.set(CB_KEY, True, timeout=CB_TTL)
            logger.warning('[fx] Circuit breaker: %d losses', losses)
    daily = cache.get(DAILY_LOSS_KEY) or 0
    daily += pnl
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    cache.set(DAILY_LOSS_KEY, daily, timeout=int((midnight - now).total_seconds()))
