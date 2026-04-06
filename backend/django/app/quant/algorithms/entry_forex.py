"""
entry_forex.py — Four-Strategy Sweep System (07:00–22:00 UTC)

Strategy 1: TJR Asia Sweep — XAUUSD H1 (07:00–16:00)
  Asia range (00–05) → London/NY sweep → MSS → EMA trend
  Backtest: 50-53% WR, PF 2.28, +0.48R/trade, 3.0R max DD

Strategy 2: London Sweep — XAGUSD M15 (07:00–12:00)
  Pre-London range (04–07) → London sweep → MSS → EMA trend
  Backtest: 60-67% WR, PF 1.52, +0.88R/trade, 2.5R max DD

Strategy 3: NY Sweep — EURUSD M15 (13:00–16:00)
  London range (07–13) → NY open sweep → MSS
  Backtest: 62.5% WR, PF 2.94, +0.76R/trade, 3.3R max DD

Strategy 4: NY PM Sweep — XAGUSD M15 (16:00–22:00)
  London+NY AM range (07–16) → NY PM sweep → MSS → EMA trend
  Backtest: 67-75% WR, PF 4.52, +1.16R/trade, 1.2R max DD

All strategies: broker SL/TP only, no trailing, no phases.
Risk: €50 per trade. Max 1 trade per symbol at a time.
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

logger = logging.getLogger('quant')

# ---------------------------------------------------------------------------
# Shared config
# ---------------------------------------------------------------------------
RISK_EUR = 15.0
MAX_LOT = 0.20
COOLDOWN_TTL = 900
MAX_DAILY_LOSS = -75.0
DAILY_LOSS_KEY = 'fx:daily_loss'

CB_KEY = 'fx:circuit_breaker'
LOSS_KEY = 'fx:consecutive_losses'
CB_LOSSES = 3
CB_TTL = 7200

# ---------------------------------------------------------------------------
# Strategy 1: TJR Asia Sweep — XAUUSD H1
# ---------------------------------------------------------------------------
XAU = 'XAUUSD'
XAU_SL = 1.2
XAU_TP = 2.4
XAU_BARS = 250

# ---------------------------------------------------------------------------
# Strategy 2 & 4: Silver Sweep — XAGUSD M15
# ---------------------------------------------------------------------------
XAG = 'XAGUSD'
XAG_SL = 1.5               # Silver — tighter for faster resolution
XAG_TP = 3.0
XAG_BARS = 900

# ---------------------------------------------------------------------------
# Strategy 3: NY Sweep — EURUSD M15
# ---------------------------------------------------------------------------
EUR = 'EURUSD'
EUR_SL = 1.2
EUR_TP = 2.4
EUR_BARS = 900

# Swing lookback
SLB_H1 = 3
SLB_M15 = 5


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def entry_forex_algorithm():
    """Run all three strategies. Called every 60s by Celery beat."""
    if cache.get(CB_KEY):
        return
    if (cache.get(DAILY_LOSS_KEY) or 0) <= MAX_DAILY_LOSS:
        return

    open_syms = _open_symbols()
    hour = datetime.now(timezone.utc).hour

    # Strategy 1: XAUUSD TJR (07:00–16:00)
    if XAU not in open_syms and not cache.get(f'fx_cd:{XAU}'):
        if 7 <= hour < 16:
            _run_xau_tjr()

    # Strategy 2: XAGUSD London Sweep (07:00–12:00)
    if XAG not in open_syms and not cache.get(f'fx_cd:{XAG}'):
        if 7 <= hour < 12:
            _run_xag_london()

    # Strategy 3: EURUSD NY Sweep (13:00–16:00)
    if EUR not in open_syms and not cache.get(f'fx_cd:{EUR}'):
        if 13 <= hour < 16:
            _run_eur_ny()

    # Strategy 4: XAGUSD NY PM Sweep (16:00–22:00)
    if XAG not in open_syms and not cache.get(f'fx_cd:{XAG}'):
        if 16 <= hour < 22:
            _run_xag_ny_pm()


# ---------------------------------------------------------------------------
# Strategy 1: XAUUSD TJR Asia Sweep
# Asia range (00–05) → sweep during London/NY (07–16) → MSS → trend
# ---------------------------------------------------------------------------

def _run_xau_tjr():
    df = _fetch_bars(XAU, MT5Timeframe.H1, XAU_BARS)
    if df is None or len(df) < 210:
        return
    df = _indicators_h1(df)

    i = len(df) - 1
    atr = df['atr'].iloc[i]
    if pd.isna(atr) or atr <= 0:
        return
    if pd.isna(df['ema200'].iloc[i]):
        return

    today = df['date'].iloc[i]
    c, pc = df['close'].iloc[i], df['close'].iloc[i - 1]
    trend_bull = df['ema50'].iloc[i] > df['ema200'].iloc[i]

    # Asia range (try today, fallback to yesterday)
    asia_h, asia_l = _session_range(df, i, today, 0, 5)
    if asia_h is None:
        yesterday = (df['time'].iloc[i] - timedelta(days=1)).date()
        asia_h, asia_l = _session_range(df, i, yesterday, 0, 5)
        if asia_h is None:
            return

    sess = df[(df['date'] == today) & (df['hour'] >= 7) & (df.index <= i)]
    if len(sess) < 2:
        return

    # BULLISH: sweep Asia low + MSS + uptrend
    if sess['low'].min() < asia_l and trend_bull:
        shs = _swing_highs(df, i - SLB_H1, SLB_H1)
        if shs and pc <= shs[-1][1] and c > shs[-1][1] and c > asia_l:
            logger.info('[tjr] BUY: swept asia_low=%.2f MSS>%.2f c=%.2f', asia_l, shs[-1][1], c)
            _execute(XAU, 'BUY', df, XAU_SL, XAU_TP, 'TJR_ASIA_XAU', 'H1')
            return

    # BEARISH: sweep Asia high + MSS + downtrend
    if sess['high'].max() > asia_h and not trend_bull:
        sls = _swing_lows(df, i - SLB_H1, SLB_H1)
        if sls and pc >= sls[-1][1] and c < sls[-1][1] and c < asia_h:
            logger.info('[tjr] SELL: swept asia_high=%.2f MSS<%.2f c=%.2f', asia_h, sls[-1][1], c)
            _execute(XAU, 'SELL', df, XAU_SL, XAU_TP, 'TJR_ASIA_XAU', 'H1')


# ---------------------------------------------------------------------------
# Strategy 2: XAGUSD London Sweep
# Pre-London range (04–07) → sweep during London (07–12) → MSS → trend
# ---------------------------------------------------------------------------

def _run_xag_london():
    df = _fetch_bars(XAG, MT5Timeframe.M15, XAG_BARS)
    if df is None or len(df) < 820:
        return
    df = _indicators_m15(df)

    i = len(df) - 1
    atr = df['atr'].iloc[i]
    if pd.isna(atr) or atr <= 0:
        return
    if pd.isna(df['ema200'].iloc[i]):
        return

    today = df['date'].iloc[i]
    c, pc = df['close'].iloc[i], df['close'].iloc[i - 1]
    trend_bull = df['ema50'].iloc[i] > df['ema200'].iloc[i]

    pre_h, pre_l = _session_range(df, i, today, 4, 7)
    if pre_h is None:
        return

    sess = df[(df['date'] == today) & (df['hour'] >= 7) & (df['hour'] < 12) & (df.index <= i)]
    if len(sess) < 2:
        return

    # BULLISH
    if sess['low'].min() < pre_l and trend_bull:
        shs = _swing_highs(df, i - SLB_M15, SLB_M15)
        if shs and pc <= shs[-1][1] and c > shs[-1][1] and c > pre_l:
            logger.info('[ldn] BUY: swept pre_low=%.4f MSS>%.4f c=%.4f', pre_l, shs[-1][1], c)
            _execute(XAG, 'BUY', df, XAG_SL, XAG_TP, 'LDN_SWEEP_XAG', 'M15')
            return

    # BEARISH
    if sess['high'].max() > pre_h and not trend_bull:
        sls = _swing_lows(df, i - SLB_M15, SLB_M15)
        if sls and pc >= sls[-1][1] and c < sls[-1][1] and c < pre_h:
            logger.info('[ldn] SELL: swept pre_high=%.4f MSS<%.4f c=%.4f', pre_h, sls[-1][1], c)
            _execute(XAG, 'SELL', df, XAG_SL, XAG_TP, 'LDN_SWEEP_XAG', 'M15')


# ---------------------------------------------------------------------------
# Strategy 3: EURUSD NY Sweep
# London range (07–13) → sweep during NY open (13–16) → MSS
# ---------------------------------------------------------------------------

def _run_eur_ny():
    df = _fetch_bars(EUR, MT5Timeframe.M15, EUR_BARS)
    if df is None or len(df) < 820:
        return
    df = _indicators_m15(df)

    i = len(df) - 1
    atr = df['atr'].iloc[i]
    if pd.isna(atr) or atr <= 0:
        return

    today = df['date'].iloc[i]
    c, pc = df['close'].iloc[i], df['close'].iloc[i - 1]

    # London range to sweep (07:00–13:00)
    ldn_h, ldn_l = _session_range(df, i, today, 7, 13)
    if ldn_h is None:
        return

    sess = df[(df['date'] == today) & (df['hour'] >= 13) & (df['hour'] < 16) & (df.index <= i)]
    if len(sess) < 2:
        return

    # BULLISH: sweep London low + MSS
    if sess['low'].min() < ldn_l:
        shs = _swing_highs(df, i - SLB_M15, SLB_M15)
        if shs and pc <= shs[-1][1] and c > shs[-1][1]:
            logger.info('[ny_eur] BUY: swept ldn_low=%.5f MSS>%.5f c=%.5f', ldn_l, shs[-1][1], c)
            _execute(EUR, 'BUY', df, EUR_SL, EUR_TP, 'NY_SWEEP_EUR', 'M15')
            return

    # BEARISH: sweep London high + MSS
    if sess['high'].max() > ldn_h:
        sls = _swing_lows(df, i - SLB_M15, SLB_M15)
        if sls and pc >= sls[-1][1] and c < sls[-1][1]:
            logger.info('[ny_eur] SELL: swept ldn_high=%.5f MSS<%.5f c=%.5f', ldn_h, sls[-1][1], c)
            _execute(EUR, 'SELL', df, EUR_SL, EUR_TP, 'NY_SWEEP_EUR', 'M15')


# ---------------------------------------------------------------------------
# Strategy 4: XAGUSD NY PM Sweep
# London+NY AM range (07–16) → sweep during NY PM (16–22) → MSS → trend
# ---------------------------------------------------------------------------

def _run_xag_ny_pm():
    df = _fetch_bars(XAG, MT5Timeframe.M15, XAG_BARS)
    if df is None or len(df) < 820:
        return
    df = _indicators_m15(df)

    i = len(df) - 1
    atr = df['atr'].iloc[i]
    if pd.isna(atr) or atr <= 0:
        return
    if pd.isna(df['ema200'].iloc[i]):
        return

    today = df['date'].iloc[i]
    c, pc = df['close'].iloc[i], df['close'].iloc[i - 1]
    trend_bull = df['ema50'].iloc[i] > df['ema200'].iloc[i]

    # Range to sweep: London + NY AM (07:00–16:00)
    day_h, day_l = _session_range(df, i, today, 7, 16)
    if day_h is None:
        return

    sess = df[(df['date'] == today) & (df['hour'] >= 16) & (df.index <= i)]
    if len(sess) < 2:
        return

    # BULLISH: sweep day low + MSS + uptrend
    if sess['low'].min() < day_l and trend_bull:
        shs = _swing_highs(df, i - SLB_M15, SLB_M15)
        if shs and pc <= shs[-1][1] and c > shs[-1][1] and c > day_l:
            logger.info('[nypm] BUY: swept day_low=%.4f MSS>%.4f c=%.4f', day_l, shs[-1][1], c)
            _execute(XAG, 'BUY', df, XAG_SL, XAG_TP, 'NY_PM_SWEEP_XAG', 'M15')
            return

    # BEARISH: sweep day high + MSS + downtrend
    if sess['high'].max() > day_h and not trend_bull:
        sls = _swing_lows(df, i - SLB_M15, SLB_M15)
        if sls and pc >= sls[-1][1] and c < sls[-1][1] and c < day_h:
            logger.info('[nypm] SELL: swept day_high=%.4f MSS<%.4f c=%.4f', day_h, sls[-1][1], c)
            _execute(XAG, 'SELL', df, XAG_SL, XAG_TP, 'NY_PM_SWEEP_XAG', 'M15')


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
        volume = calculate_risk_based_lots(
            symbol=symbol, sl_distance=sl_dist,
            target_risk=RISK_EUR, order_type=direction,
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
            order=result, symbol=symbol, capital=RISK_EUR,
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
# Structure
# ---------------------------------------------------------------------------

def _session_range(df, i, date, start_h, end_h):
    mask = (df['date'] == date) & (df['hour'] >= start_h) & (df['hour'] < end_h)
    bars = df.loc[mask]
    if len(bars) < 2:
        return None, None
    return bars['high'].max(), bars['low'].min()


def _swing_highs(df, end_idx, lookback=3, count=3):
    start = max(lookback, end_idx - 80)
    swings = []
    highs = df['high']
    for j in range(start, min(end_idx + 1, len(df) - lookback)):
        window = highs.iloc[j - lookback:j + lookback + 1]
        if highs.iloc[j] == window.max() and highs.iloc[j] > highs.iloc[j - 1]:
            swings.append((j, highs.iloc[j]))
    return swings[-count:]


def _swing_lows(df, end_idx, lookback=3, count=3):
    start = max(lookback, end_idx - 80)
    swings = []
    lows = df['low']
    for j in range(start, min(end_idx + 1, len(df) - lookback)):
        window = lows.iloc[j - lookback:j + lookback + 1]
        if lows.iloc[j] == window.min() and lows.iloc[j] < lows.iloc[j - 1]:
            swings.append((j, lows.iloc[j]))
    return swings[-count:]


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
