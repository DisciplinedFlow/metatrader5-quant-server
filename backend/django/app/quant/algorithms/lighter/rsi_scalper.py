"""
Lighter.xyz RSI(2) Ultra-Fast Scalper — highest documented win rate strategy.

Based on Larry Connors' RSI(2) mean reversion (91% WR on stocks).
Adapted for 5-minute crypto scalping on zero-fee venue.

Rules:
- RSI(2) < 15 → BUY (deeply oversold on ultra-fast RSI)
- RSI(2) > 85 → SELL (deeply overbought)
- EMA(50) trend filter: only longs above EMA, only shorts below
- TP: 0.3-0.5% (mean reversion target)
- SL: 0.5-1.0% (tight, cut losses fast)
- Cooldown: 30 seconds per symbol (zero fees = trade often)
- Max 3 positions at a time

Asset-class aware SL/TP:
- Crypto: SL 1.0%, TP 0.5%
- Metals: SL 0.8%, TP 0.4%
- Forex: SL 0.3%, TP 0.15%

Targets 20-50 trades/day. Each trade captures 0.2-0.5%.
"""
import logging
import pandas as pd
from django.core.cache import cache

from .config import LIGHTER_MARKETS, LIGHTER_LEVERAGE
from .client import get_candles, get_best_bid_ask, place_market_order_usd, update_leverage, place_oco_sltp
from .session_sizing import get_combined_sizing

logger = logging.getLogger('app.lighter')



PLATFORM_PREFIX = 'lighter:'

# ── Asset-class classification ────────────────────────────

FOREX_SYMBOLS = {'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'USDCAD', 'AUDUSD', 'NZDUSD'}
METALS_SYMBOLS = {'XAU', 'XAG', 'PAXG', 'WTI'}

# ── RSI(2) scalper configs per asset class ────────────────

RSI2_CONFIG = {
    'crypto': {
        'rsi_period': 2,
        'rsi_oversold': 15,
        'rsi_overbought': 85,
        'ema_period': 50,
        'sl_pct': 0.010,   # 1.0% SL
        'tp_pct': 0.020,   # 2.0% TP — 1:2 R:R, break-even at 33.3% WR (was 0.75%)
        'size_usd': 12,
    },
    'metals': {
        'rsi_period': 2,
        'rsi_oversold': 15,
        'rsi_overbought': 85,
        'ema_period': 50,
        'sl_pct': 0.008,   # 0.8% SL
        'tp_pct': 0.016,   # 1.6% TP — 1:2 R:R (was 0.6%)
        'size_usd': 12,
    },
    'forex': {
        'rsi_period': 2,
        'rsi_oversold': 15,
        'rsi_overbought': 85,
        'ema_period': 50,
        'sl_pct': 0.003,   # 0.3% SL
        'tp_pct': 0.006,   # 0.6% TP — 1:2 R:R (was 0.15%)
        'size_usd': 12,
    },
}

# Symbols to scan every 10 seconds
# BTC removed: 50% WR, -$4.08 net PnL | ETH removed: 60% WR, -$8.32 net PnL
RSI2_SYMBOLS = ['SOL', 'XAU']

# Cooldown between trades on same symbol (seconds)
# 600s = 10 min: prevents re-entering same downtrend on 15m bars (knife-catching)
RSI2_COOLDOWN_SECONDS = 600

# Max simultaneous RSI2 positions (2 leaves 1+ slot for trend/mean-reversion strategies)
RSI2_MAX_POSITIONS = 2


def _get_config(symbol):
    """Get asset-class config for a symbol."""
    if symbol in FOREX_SYMBOLS:
        return RSI2_CONFIG['forex']
    elif symbol in METALS_SYMBOLS:
        return RSI2_CONFIG['metals']
    return RSI2_CONFIG['crypto']


def _calculate_rsi(closes, period=2):
    """Calculate RSI with configurable period. Uses SMA smoothing for RSI(2)."""
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _calculate_ema(closes, period=50):
    """Calculate EMA for trend filter."""
    return closes.ewm(span=period, adjust=False).mean()


def _check_cooldown(symbol):
    """Check if symbol is in post-trade cooldown."""
    key = f'lighter:rsi2_cooldown:{symbol}'
    return not cache.get(key)


def _set_cooldown(symbol):
    """Set post-trade cooldown for symbol."""
    key = f'lighter:rsi2_cooldown:{symbol}'
    cache.set(key, True, timeout=RSI2_COOLDOWN_SECONDS)


def rsi_scalper_algorithm(symbols=None):
    """RSI(2) ultra-fast scalper entry algorithm. Called every 10s by Celery.

    For each symbol:
    1. Fetch 5m candles (60 bars for EMA(50) calculation)
    2. Calculate RSI(2) — ultra-fast 2-period RSI
    3. Calculate EMA(50) — trend filter
    4. BUY: RSI(2) < 15 AND price > EMA(50) — oversold in uptrend
    5. SELL: RSI(2) > 85 AND price < EMA(50) — overbought in downtrend
    """
    if cache.get('lighter:disabled'):
        return

    # Losing streak cooldown disabled — brain collects data through all conditions
    # if cache.get('lighter:streak_cooldown'):
    #     logger.debug("RSI2: losing streak cooldown, skipping")
    #     return

    if symbols is None:
        symbols = RSI2_SYMBOLS

    from app.crypto.models import CryptoPosition

    # Count open RSI2 positions
    rsi2_open = CryptoPosition.objects.filter(
        status='OPEN',
        entry_signal__startswith=f'{PLATFORM_PREFIX}rsi2_',
    ).count()

    if rsi2_open >= RSI2_MAX_POSITIONS:
        logger.debug("RSI2: max positions reached (%d/%d)", rsi2_open, RSI2_MAX_POSITIONS)
        return

    # Global cap — enforces exchange OCO slot limit (2 positions × SL+TP = 4 orders max)
    from .config import is_global_position_limit_reached
    if is_global_position_limit_reached():
        logger.debug("RSI2: global position limit reached, skipping")
        return

    for symbol in symbols:
        try:
            # Re-check position count inside loop — may have opened one this iteration
            if rsi2_open >= RSI2_MAX_POSITIONS:
                break
            opened = _scan_symbol(symbol)
            if opened:
                rsi2_open += 1
        except Exception as e:
            logger.error("RSI2 error for %s: %s", symbol, e)


def _scan_symbol(symbol):
    """Scan a single symbol for RSI(2) scalp entry. Returns True if position opened."""
    from app.crypto.models import CryptoPosition, CryptoTrade

    meta = LIGHTER_MARKETS.get(symbol)
    if meta is None:
        return False

    # Check if already in position on this symbol (any lighter strategy)
    if CryptoPosition.objects.filter(symbol=symbol, status='OPEN',
                                      entry_signal__startswith=PLATFORM_PREFIX).exists():
        return False

    # Check cooldown
    if not _check_cooldown(symbol):
        return False

    config = _get_config(symbol)

    # Fetch 15m candles — better mean reversion properties than 5m on crypto
    # 60 bars × 15min = 15 hours of history (sufficient for EMA(50) + buffer)
    candles = get_candles(symbol, resolution='15m', count_back=60)
    if not candles or len(candles) < config['ema_period'] + 5:
        return False

    df = pd.DataFrame(candles)
    for col in ['o', 'h', 'l', 'c']:
        df[col] = df[col].astype(float)

    closes = df['c']

    # Calculate indicators
    rsi = _calculate_rsi(closes, config['rsi_period'])
    ema = _calculate_ema(closes, config['ema_period'])

    # Get latest values
    current_price = closes.iloc[-1]
    current_rsi = rsi.iloc[-1]
    current_ema = ema.iloc[-1]

    if pd.isna(current_rsi) or pd.isna(current_ema):
        return False

    # ── Entry logic ──
    # BUY: RSI(2) deeply oversold AND price above EMA(50) — dip in uptrend
    # SELL: RSI(2) deeply overbought AND price below EMA(50) — pop in downtrend
    signal = 0
    trend = 'up' if current_price > current_ema else 'down'

    if current_rsi < config['rsi_oversold'] and current_price > current_ema:
        signal = 1  # BUY
    elif current_rsi > config['rsi_overbought'] and current_price < current_ema:
        signal = -1  # SELL
    else:
        return False

    signal_type = f"rsi2_{'buy' if signal > 0 else 'sell'}_rsi{current_rsi:.0f}_ema{trend}"

    # ML filter disabled — collecting training data, brain learns from trades
    # Re-enable once model has 200+ crypto trades to train on

    # ── Funding rate contrarian signal (NEVER blocks — adjusts size) ──
    funding_mult = 1.0
    funding_info = ''
    try:
        from .funding_signal import get_funding_rate_signal
        funding = get_funding_rate_signal(symbol)
        funding_signal = funding.get('signal', 0)
        if funding_signal != 0:
            if funding_signal == signal:
                funding_mult = 1.2  # Boost 20% — contrarian agrees
                funding_info = f"funding_boost(z={funding.get('z_score', 0):.1f})"
            else:
                funding_mult = 0.7  # Reduce 30% — contrarian disagrees
                funding_info = f"funding_reduce(z={funding.get('z_score', 0):.1f})"
        else:
            funding_info = "funding_neutral"
    except Exception as e:
        logger.debug("RSI2 %s: funding signal check failed: %s", symbol, e)
        funding_info = "funding_error"

    # ── Trade flow analysis (NEVER blocks — adjusts size + warns) ──
    flow_mult = 1.0
    flow_info = ''
    try:
        from .trade_flow import analyze_trade_flow
        flow = analyze_trade_flow(symbol)
        flow_signal = flow.get('signal', 0)
        whale = flow.get('whale_detected', False)
        whale_dir = flow.get('whale_direction')

        if whale:
            if (whale_dir == 'BUY' and signal > 0) or (whale_dir == 'SELL' and signal < 0):
                flow_mult = 1.2  # Whale in our direction — boost 20%
                flow_info = f"whale_{whale_dir}_boost(cvd=${flow.get('cvd', 0):.0f})"
            elif (whale_dir == 'SELL' and signal > 0) or (whale_dir == 'BUY' and signal < 0):
                flow_mult = 0.7  # Whale against us — reduce 30%
                flow_info = f"whale_{whale_dir}_warn(cvd=${flow.get('cvd', 0):.0f})"
                logger.warning("RSI2 %s: WHALE AGAINST trade direction! whale=%s our=%s cvd=$%.0f",
                               symbol, whale_dir, 'BUY' if signal > 0 else 'SELL', flow.get('cvd', 0))
            else:
                flow_info = f"whale_mixed(cvd=${flow.get('cvd', 0):.0f})"
        elif flow_signal != 0:
            if flow_signal == signal:
                flow_mult = 1.1  # Flow agrees — slight boost
                flow_info = f"flow_agree(ratio={flow.get('aggressor_ratio', 0.5):.2f})"
            else:
                flow_mult = 0.9  # Flow disagrees — slight reduction
                flow_info = f"flow_disagree(ratio={flow.get('aggressor_ratio', 0.5):.2f})"
        else:
            flow_info = "flow_balanced"
    except Exception as e:
        logger.debug("RSI2 %s: trade flow check failed: %s", symbol, e)
        flow_info = "flow_error"

    # ── Execute entry ──
    is_buy = signal > 0
    side = 'LONG' if is_buy else 'SHORT'
    position_usd = config['size_usd'] * LIGHTER_LEVERAGE * get_combined_sizing(symbol)

    # Apply funding + trade flow multipliers (the only ones that actually help)
    position_usd = position_usd * funding_mult * flow_mult

    # Get live price
    prices = get_best_bid_ask(symbol)
    live_price = prices.get('mid')
    if not live_price or live_price <= 0:
        return False

    logger.info("RSI2 ENTRY: %s %s $%.2f (price=%.4f, RSI(2)=%.1f, EMA50=%.4f, trend=%s, %s, %s)",
                symbol, side, position_usd, live_price, current_rsi, current_ema, trend,
                funding_info, flow_info)

    # Set leverage
    try:
        update_leverage(symbol, LIGHTER_LEVERAGE)
    except Exception:
        pass

    # Place order
    result = place_market_order_usd(symbol, is_buy, position_usd)
    if result.get('error'):
        logger.error("RSI2 %s: order failed: %s", symbol, result['error'])
        return False

    # Calculate SL/TP
    if is_buy:
        take_profit = live_price * (1 + config['tp_pct'])
        stop_loss = live_price * (1 - config['sl_pct'])
    else:
        take_profit = live_price * (1 - config['tp_pct'])
        stop_loss = live_price * (1 + config['sl_pct'])

    # Record position
    base_size = position_usd / live_price
    position = CryptoPosition.objects.create(
        symbol=symbol,
        side=side,
        entry_price=live_price,
        size=base_size,
        leverage=LIGHTER_LEVERAGE,
        entry_signal=f"{PLATFORM_PREFIX}{signal_type}",
        stop_loss=stop_loss,
        take_profit=take_profit,
        status='OPEN',
        venue='LIGHTER',
    )

    # Estimate taker fee (0.028% of notional = size × price)
    entry_fee = base_size * live_price * 0.00028

    CryptoTrade.objects.create(
        position=position,
        order_id=result.get('tx_hash', ''),
        side='BUY' if is_buy else 'SELL',
        price=live_price,
        size=base_size,
        fee=entry_fee,
        status='FILLED',
    )

    # Record ML features at entry (cached in Redis, saved to JSONL on close)
    try:
        from django.core.cache import cache as _cache
        from datetime import datetime, timezone as _tz
        now = datetime.now(_tz.utc)
        _cache.set(f'lighter:ml_features:{position.id}', {
            'symbol': symbol,
            'side': side,
            'strategy': 'rsi2',
            'entry_price': float(live_price),
            'position_usd': float(position_usd),
            'rsi2': float(current_rsi),
            'ema50': float(current_ema),
            'trend': trend,
            'signal_type': signal_type,
            'funding_mult': float(funding_mult),
            'flow_mult': float(flow_mult),
            'session_hour': now.hour,
            'day_of_week': now.weekday(),
            'leverage': LIGHTER_LEVERAGE,
        }, timeout=86400)  # 24h TTL
    except Exception:
        pass

    # Place native on-chain SL/TP as OCO group (one-cancels-other)
    try:
        oco_result = place_oco_sltp(symbol, is_buy, base_size, stop_loss, take_profit)
        if oco_result.get('error'):
            logger.warning("RSI2 OCO SL/TP failed for %s: %s", symbol, oco_result['error'])
        else:
            logger.info("RSI2 OCO SL/TP placed: %s SL=%.4f TP=%.4f tx=%s",
                        symbol, stop_loss, take_profit, oco_result.get('tx_hash', '?'))
    except Exception as e:
        logger.warning("RSI2 OCO SL/TP exception for %s: %s", symbol, e)

    _set_cooldown(symbol)

    logger.info("RSI2 position opened: %s %s size=%.6f TP=%.4f SL=%.4f signal=%s",
                symbol, side, base_size, take_profit, stop_loss, signal_type)
    return True
