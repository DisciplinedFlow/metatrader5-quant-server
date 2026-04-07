"""
entry_cvd_tick.py — Tick-Based CVD Entry Algorithm (24/7)

Reads real-time CVD signals from tick_consumer (cached in Redis) and
confirms with M5/M15 candle structure before entering.

Signal source: tick_consumer → RealtimeCVD → Redis `realtime_cvd:{symbol}`
Signal types used: absorption only (lack_of_participants disabled — 8.3% WR)

Confirmation:
  M5:  EMA 8/21 alignment in signal direction (momentum)
  M15: Price not against structure (not buying at resistance / selling at support)
       + ATR for SL/TP sizing

Entry: market order at current price
SL: 2.5× M15 ATR from entry (wide for extreme vol)
TP: 5.0× M15 ATR from entry (safety TP — trail should close before this)

Vol-regime gate: only trades absorption in extreme vol if signal is very strong.
Donchian breakout (entry_forex.py) is the primary strategy — CVD absorption is secondary.
Directional bias: XAUUSD long-only, USDJPY/USDCHF short-only (safe haven flows).

24/7 operation with loose session sizing:
  - London/NY: full size
  - Asian/off-hours: 60% size (less liquidity, wider spreads)

Generates ML training data on every trade for the XGBoost pipeline.
"""

import logging
import time
from datetime import datetime, timezone

from django.core.cache import cache

from app.utils.api.data import fetch_data_pos, symbol_info_tick
from app.utils.api.order import send_market_order
from app.utils.api.positions import get_positions
from app.utils.arithmetics import calculate_risk_based_lots
from app.utils.constants import MT5Timeframe

logger = logging.getLogger('quant')

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Symbol-specific configs — derived from 4,000+ backtest configurations
# across 7 months of data (2025-09 to 2026-04)
# ---------------------------------------------------------------------------

# Per-symbol config: (sl_atr, tp_atr, session_start, session_end, signals, filter)
# filter: 'ema50' = EMA50 trend required, 'structure' = structure check, None = raw
SYMBOL_CONFIGS = {
    # XAUUSD H1: LoP+EMA50, 53.3% WR, +€1,116 over 30 trades
    'XAUUSD': {
        'sl_atr': 2.5, 'tp_atr': 5.0,
        'session': (7, 17),     # London + NY
        'signals': {'bullish_lack_of_participants', 'bearish_lack_of_participants',
                    'bullish_absorption', 'bearish_absorption'},
        'filter': 'ema50',
        'bias': 'BUY',          # Long-only (safe haven in war)
    },
    # USDJPY H1: LoP Raw, 56.2% WR, +€10.5 over 32 trades
    'USDJPY': {
        'sl_atr': 2.0, 'tp_atr': 4.0,
        'session': (7, 12),     # London only
        'signals': {'bullish_lack_of_participants', 'bearish_lack_of_participants',
                    'bullish_absorption', 'bearish_absorption'},
        'filter': None,         # Raw LoP — no extra filter needed
        'bias': 'SELL',         # Short-only (JPY safe haven)
    },
    # USDCHF M30: LoP+Structure, 71.4% WR over 14 trades
    'USDCHF': {
        'sl_atr': 1.5, 'tp_atr': 3.0,
        'session': (7, 12),     # London only
        'signals': {'bullish_lack_of_participants', 'bearish_lack_of_participants',
                    'bullish_absorption', 'bearish_absorption'},
        'filter': None,
        'bias': 'SELL',         # Short-only (CHF safe haven)
    },
    # USDCAD H1: LoP+EMA50, 57.9% WR over 19 trades
    'USDCAD': {
        'sl_atr': 1.8, 'tp_atr': 3.6,
        'session': (13, 17),    # NY overlap only
        'signals': {'bullish_lack_of_participants', 'bearish_lack_of_participants',
                    'bullish_absorption', 'bearish_absorption'},
        'filter': 'ema50',
        'bias': None,           # Both directions
    },
    # XAGUSD M15: LoP+EMA50, 55% WR over 40 trades (marginal but included)
    'XAGUSD': {
        'sl_atr': 2.5, 'tp_atr': 5.0,
        'session': (7, 12),     # London only
        'signals': {'bullish_absorption', 'bearish_absorption'},  # Absorption only for silver
        'filter': 'ema50',
        'bias': None,
    },
}

SYMBOLS = list(SYMBOL_CONFIGS.keys())

# Risk (shared across all symbols)
RISK_EUR = 7.50
MAX_LOT = 0.10

# Position limits
MAX_OPEN = 5
MAX_PER_SYMBOL = 2

# Cooldowns
COOLDOWN_SEC = 600
GLOBAL_COOLDOWN = 30

# Circuit breaker
CB_LOSSES = 3
CB_TTL = 3600

# Session sizing (24/7 but adjust for liquidity)
def _session_size_mult():
    """Return sizing multiplier based on current session."""
    hour = datetime.now(timezone.utc).hour
    if 7 <= hour < 17:   # London + NY
        return 1.0
    elif 22 <= hour or hour < 2:  # Dead zone
        return 0.4
    else:  # Asian, early European
        return 0.6


# ---------------------------------------------------------------------------
# Confirmation: M5 momentum + M15 structure
# ---------------------------------------------------------------------------

def _check_m5_momentum(symbol, direction):
    """Check M5 EMA 8/21 alignment confirms direction.

    Returns True if M5 momentum supports the trade direction.
    """
    try:
        bars = fetch_data_pos(symbol, MT5Timeframe.M5, 30)
        if bars is None or len(bars) < 25:
            return False

        close = bars['close']
        ema8 = close.ewm(span=8, adjust=False).mean()
        ema21 = close.ewm(span=21, adjust=False).mean()

        last_ema8 = ema8.iloc[-1]
        last_ema21 = ema21.iloc[-1]
        last_close = close.iloc[-1]

        if direction == 'BUY':
            # Bullish: EMA8 > EMA21 (trend confirmed)
            # Price can be in pullback zone (between EMA21 and above) — not below EMA21
            return last_ema8 > last_ema21 and last_close > last_ema21
        else:
            # Bearish: EMA8 < EMA21 (trend confirmed)
            # Price can be in pullback zone (between EMA21 and below) — not above EMA21
            return last_ema8 < last_ema21 and last_close < last_ema21

    except Exception as e:
        logger.debug("M5 momentum check failed for %s: %s", symbol, e)
        return False


def _get_m15_atr(symbol):
    """Get M15 ATR(14) for SL/TP sizing.

    Returns (atr_value, last_close) or (None, None).
    """
    try:
        bars = fetch_data_pos(symbol, MT5Timeframe.M15, 20)
        if bars is None or len(bars) < 16:
            return None, None

        import numpy as np
        high = bars['high']
        low = bars['low']
        close = bars['close']

        tr = np.maximum(
            high - low,
            np.maximum(abs(high - close.shift(1)),
                       abs(low - close.shift(1)))
        )
        atr = tr.rolling(14).mean().iloc[-1]
        last_close = close.iloc[-1]

        if atr <= 0 or np.isnan(atr):
            return None, None

        return atr, last_close

    except Exception as e:
        logger.debug("M15 ATR fetch failed for %s: %s", symbol, e)
        return None, None


def _check_ema50_trend(symbol, direction):
    """Check H1 EMA50 trend alignment for LoP signals.

    Backtest showed LoP only works with EMA50 filter (WR 31% → 53%).
    Returns True if trade direction aligns with EMA50 trend.
    """
    try:
        bars = fetch_data_pos(symbol, MT5Timeframe.H1, 55)
        if bars is None or len(bars) < 52:
            return False
        ema50 = bars['close'].ewm(span=50, adjust=False).mean()
        close = bars['close'].iloc[-1]
        if direction == 'BUY':
            return close > ema50.iloc[-1]
        else:
            return close < ema50.iloc[-1]
    except Exception:
        return False


def _check_m15_structure(symbol, direction, atr):
    """Check M15 structure doesn't invalidate the trade.

    For BUY: price shouldn't be at M15 resistance (recent high within 0.5 ATR)
    For SELL: price shouldn't be at M15 support (recent low within 0.5 ATR)

    Returns True if structure is acceptable.
    """
    try:
        bars = fetch_data_pos(symbol, MT5Timeframe.M15, 30)
        if bars is None or len(bars) < 20:
            return True  # no data = don't block

        last_close = bars['close'].iloc[-1]
        recent_high = bars['high'].iloc[-20:-1].max()
        recent_low = bars['low'].iloc[-20:-1].min()

        if direction == 'BUY':
            # Don't buy right at resistance
            if last_close > recent_high - atr * 0.3:
                return False
        else:
            # Don't sell right at support
            if last_close < recent_low + atr * 0.3:
                return False

        return True

    except Exception:
        return True  # don't block on error


# ---------------------------------------------------------------------------
# Position & risk checks
# ---------------------------------------------------------------------------

def _get_open_symbols():
    """Get set of symbols with open positions."""
    try:
        positions = get_positions()
        if positions is not None and not positions.empty:
            return set(positions['symbol'].tolist()), len(positions)
        return set(), 0
    except Exception:
        return set(), 0


def _check_circuit_breaker():
    """Check if circuit breaker is active."""
    return cache.get('cvd_tick:circuit_breaker') is not None


def _record_loss():
    """Record a loss for circuit breaker tracking."""
    losses = cache.get('cvd_tick:consecutive_losses', 0)
    losses += 1
    cache.set('cvd_tick:consecutive_losses', losses, timeout=CB_TTL)
    if losses >= CB_LOSSES:
        cache.set('cvd_tick:circuit_breaker', True, timeout=CB_TTL)
        logger.warning("CVD TICK: Circuit breaker activated after %d losses", losses)


def _record_win():
    """Reset consecutive loss counter on a win."""
    cache.delete('cvd_tick:consecutive_losses')


# ---------------------------------------------------------------------------
# Main entry algorithm
# ---------------------------------------------------------------------------

def entry_cvd_tick_algorithm():
    """Scan all symbols for fresh CVD signals and enter trades.

    Called by Celery task every time tick_consumer dispatches a signal,
    or on the regular 60s beat schedule.
    """

    # Circuit breaker check
    if _check_circuit_breaker():
        return

    # Vol-regime gate: only trade absorption in extreme vol if signal is very strong
    # This allows the Donchian breakout (entry_forex.py) to be the primary strategy
    # CVD absorption is secondary — only fires if direction matches the trend
    vol_regime = cache.get('market:vol_regime')
    if vol_regime == 'extreme':
        logger.info("CVD TICK: Extreme vol regime detected — tightening filters")

    # Global cooldown
    if cache.get('cvd_tick:global_cooldown'):
        return

    # Position limits
    open_syms, open_count = _get_open_symbols()
    if open_count >= MAX_OPEN:
        return

    for symbol in SYMBOLS:
        if symbol in open_syms:
            continue

        # Per-symbol cooldown
        if cache.get(f'cvd_tick:cooldown:{symbol}'):
            continue

        # Read cached CVD signal (30s TTL from tick_consumer)
        signal_data = cache.get(f'realtime_cvd:{symbol}')
        if signal_data is None:
            continue

        signal_type = signal_data.get('signal', '')
        direction = signal_data.get('direction', '')

        # Get symbol-specific config
        sym_cfg = SYMBOL_CONFIGS.get(symbol)
        if sym_cfg is None:
            continue

        # Signal must be allowed for this symbol
        if signal_type not in sym_cfg['signals']:
            continue

        if direction not in ('BUY', 'SELL'):
            continue

        # Session filter (symbol-specific hours from backtest)
        hour = datetime.now(timezone.utc).hour
        sess_start, sess_end = sym_cfg['session']
        if not (sess_start <= hour < sess_end):
            continue

        # Directional bias (safe-haven flows)
        bias = sym_cfg.get('bias')
        if bias and direction != bias:
            logger.info("CVD TICK SKIP: %s %s blocked by %s-only bias",
                       symbol, direction, bias)
            continue

        # EMA50 trend filter (required for XAUUSD, USDCAD, XAGUSD)
        if sym_cfg.get('filter') == 'ema50':
            if not _check_ema50_trend(symbol, direction):
                logger.info("CVD TICK SKIP: %s %s blocked — against EMA50 trend",
                           symbol, direction)
                continue

        # --- CONFIRMATION LAYER 1: M5 momentum ---
        if not _check_m5_momentum(symbol, direction):
            logger.info("CVD TICK SKIP: %s %s %s — M5 momentum rejected",
                       symbol, signal_type, direction)
            continue

        # --- CONFIRMATION LAYER 2: M15 ATR for sizing ---
        atr, last_price = _get_m15_atr(symbol)
        if atr is None:
            continue

        # --- CONFIRMATION LAYER 3: M15 structure ---
        if not _check_m15_structure(symbol, direction, atr):
            logger.info("CVD TICK SKIP: %s %s %s — M15 structure rejected",
                       symbol, signal_type, direction)
            continue

        # --- EXECUTE ENTRY (symbol-specific SL/TP from backtest) ---
        sl_dist = sym_cfg['sl_atr'] * atr
        tp_dist = sym_cfg['tp_atr'] * atr

        # Get live tick price for precise entry
        tick_df = symbol_info_tick(symbol)
        if tick_df is None or tick_df.empty:
            continue

        ask_price = float(tick_df['ask'].iloc[0])
        bid_price = float(tick_df['bid'].iloc[0])

        if direction == 'BUY':
            entry_price = ask_price
            sl = entry_price - sl_dist
            tp = entry_price + tp_dist
        else:
            entry_price = bid_price
            sl = entry_price + sl_dist
            tp = entry_price - tp_dist

        # Session-adjusted sizing
        size_mult = _session_size_mult()
        risk = RISK_EUR * size_mult

        # Calculate lot size
        lots = calculate_risk_based_lots(symbol, sl_dist, risk, direction)
        if lots is None or lots <= 0:
            continue
        lots = min(lots, MAX_LOT)

        logger.info(
            "CVD TICK ENTRY: %s %s | signal=%s | entry=%.5f sl=%.5f tp=%.5f | "
            "lots=%.2f risk=€%.0f | atr=%.5f session_mult=%.1f",
            symbol, direction, signal_type,
            entry_price, sl, tp, lots, risk, atr, size_mult,
        )

        # Place the order
        try:
            result = send_market_order(
                symbol=symbol,
                volume=lots,
                order_type=direction,
                sl=sl,
                tp=tp,
                comment=f'CVD_TICK:{signal_type[:20]}',
            )

            if result and result.get('deal'):
                ticket = result.get('order', result.get('deal', '?'))
                fill_price = result.get('price', entry_price)
                logger.info("CVD TICK FILLED: %s %s | ticket=%s price=%.5f lots=%.2f | signal=%s",
                           symbol, direction, ticket, fill_price, lots, signal_type)

                # CREATE TRADE RECORD IN DB (so close algo + dashboard track it properly)
                trade_obj = None
                try:
                    from app.nexus.models import Trade
                    from django.utils import timezone as tz
                    trade_obj = Trade.objects.create(
                        transaction_broker_id=str(ticket),
                        symbol=symbol,
                        entry_time=tz.now(),
                        entry_price=fill_price,
                        type=direction,
                        order_volume=lots,
                        position_size_usd=float(lots * fill_price),
                        capital=risk,
                        leverage=500,
                        liquidity_price=fill_price,
                        break_even_price=fill_price,
                        order_commission=0,
                        entry_atr=atr,
                        strategy=f'CVD_TICK:{signal_type}',
                        broker='VantageInternational-Demo',
                        market_type='FOREX',
                        timeframe='M5',
                    )
                    logger.info("CVD TICK DB: Created Trade record for %s %s ticket=%s",
                               symbol, direction, ticket)
                except Exception as db_err:
                    logger.error("CVD TICK DB: Failed to create Trade: %s", db_err)

                # Create ML training record (TradeFeature)
                if trade_obj:
                    try:
                        from app.nexus.models import TradeFeature
                        now = datetime.now(timezone.utc)
                        features_dict = {
                            'symbol': symbol,
                            'direction': direction,
                            'signal_type': signal_type,
                            'strategy': f'CVD_TICK:{signal_type}',
                            'hour_utc': now.hour,
                            'day_of_week': now.weekday(),
                            'atr': float(atr),
                            'sl_distance': float(sl_dist),
                            'tp_distance': float(tp_dist),
                            'entry_price': float(fill_price),
                            'volume': float(lots),
                            'session_mult': float(size_mult),
                            'timeframe': 'M5',
                        }
                        # Add CVD signal data if available
                        cvd_data = cache.get(f'realtime_cvd:{symbol}')
                        if cvd_data and isinstance(cvd_data, dict):
                            features_dict['cvd_signal'] = cvd_data
                        TradeFeature.objects.create(
                            trade=trade_obj,
                            features_json=features_dict,
                            ml_score=0.0,
                            ml_accepted=True,
                        )
                        logger.info("CVD TICK: TradeFeature created for %s %s", symbol, direction)
                    except Exception as tf_err:
                        logger.debug("CVD TICK: TradeFeature creation failed: %s", tf_err)

                # Set cooldowns
                cache.set(f'cvd_tick:cooldown:{symbol}', True, timeout=COOLDOWN_SEC)
                cache.set('cvd_tick:global_cooldown', True, timeout=GLOBAL_COOLDOWN)

                # Record ML training features (legacy Redis cache)
                _record_ml_features(symbol, signal_type, direction, entry_price,
                                   sl, tp, atr, size_mult, result)

                # Only one entry per cycle
                return

            else:
                logger.warning("CVD TICK REJECTED: %s %s order not filled: %s",
                              symbol, direction, result)

        except Exception as e:
            logger.error("CVD TICK: %s %s order error: %s", symbol, direction, e)

        # Small delay between symbol checks to avoid hammering MT5
        time.sleep(0.2)


# ---------------------------------------------------------------------------
# ML training data recording
# ---------------------------------------------------------------------------

def _record_ml_features(symbol, signal_type, direction, entry_price,
                        sl, tp, atr, session_mult, order_result):
    """Cache entry features for ML training. Close algorithm will add outcome."""
    try:
        ticket = order_result.get('ticket', 0)
        features = {
            'symbol': symbol,
            'signal_type': signal_type,
            'direction': direction,
            'entry_price': float(entry_price),
            'sl': float(sl),
            'tp': float(tp),
            'atr': float(atr),
            'session_mult': float(session_mult),
            'hour_utc': datetime.now(timezone.utc).hour,
            'day_of_week': datetime.now(timezone.utc).weekday(),
            'cvd_signal': cache.get(f'realtime_cvd:{symbol}', {}),
        }
        cache.set(f'cvd_tick:ml_features:{ticket}', features, timeout=7 * 86400)
        logger.info("CVD TICK ML: recorded entry features for ticket %s", ticket)
    except Exception as e:
        logger.debug("CVD TICK ML: failed to record features: %s", e)
