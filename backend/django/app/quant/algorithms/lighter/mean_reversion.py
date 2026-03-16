"""
Lighter.xyz Mean Reversion Strategy — BB(20,2.5) + RSI(14) + ADX(14) filter
+ Liquidation Cascade Detector.

Academic evidence: ADX filter turned $7K loss into $57K profit in backtests.
Only trades when market is ranging (ADX < 25). Enters at Bollinger Band
extremes confirmed by RSI, exits at the mean (middle BB).

Liquidation cascade integration:
- If BB/RSI + liquidation cascade align: boost position by 50% (confluence)
- If liquidation cascade fires alone (without BB/RSI): enter with half position size
- Signal types: mr_liq_buy / mr_liq_sell (liquidation-only), mr_buy/mr_sell (BB/RSI+liq boost)

Optimized for zero-fee venues — targets 0.3-0.8% captures per trade.

Asset-class aware:
- Crypto: BB(20, 2.5), RSI <20/>80
- Metals: BB(20, 2.0), RSI <25/>75
- Forex: BB(20, 2.0), RSI <25/>75 (tighter bands for lower vol)
"""
import logging
import math
import pandas as pd
from django.core.cache import cache

from .config import LIGHTER_MARKETS, LIGHTER_LEVERAGE
from .client import get_candles, get_best_bid_ask, place_market_order_usd, update_leverage, place_oco_sltp
from .confluence import score_entry
from .liquidation_detector import check_liquidation_signal

logger = logging.getLogger('app.lighter')

PLATFORM_PREFIX = 'lighter:'

# ── Asset-class configs ─────────────────────────────────

FOREX_SYMBOLS = {'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'USDCAD', 'AUDUSD', 'NZDUSD'}
METALS_SYMBOLS = {'XAU', 'XAG', 'PAXG', 'WTI'}

MR_CONFIG = {
    'crypto': {
        'bb_period': 20, 'bb_std': 2.5,
        'rsi_period': 14, 'rsi_oversold': 25, 'rsi_overbought': 75,
        'adx_max': 40,   # Relaxed — BB+RSI already filter, don't miss volatile moves
        'sl_pct': 0.02, 'tp_pct': 0.01,
        'size_usd': 8,
    },
    'metals': {
        'bb_period': 20, 'bb_std': 2.0,
        'rsi_period': 14, 'rsi_oversold': 28, 'rsi_overbought': 72,
        'adx_max': 35,   # Relaxed — XAU moves fast, catch the pumps
        'sl_pct': 0.015, 'tp_pct': 0.008,
        'size_usd': 8,
    },
    'forex': {
        'bb_period': 20, 'bb_std': 2.0,
        'rsi_period': 14, 'rsi_oversold': 28, 'rsi_overbought': 72,
        'adx_max': 30,   # Slightly relaxed
        'sl_pct': 0.005, 'tp_pct': 0.003,
        'size_usd': 8,
    },
}

# Symbols to scan
MR_SYMBOLS = ['ETH', 'BTC', 'SOL', 'XAU', 'EURUSD', 'GBPUSD']

# Cooldown between trades on same symbol (seconds)
MR_COOLDOWN_SECONDS = 60  # 1 minute — aggressive, zero fees make rapid trades viable


def _get_config(symbol):
    if symbol in FOREX_SYMBOLS:
        return MR_CONFIG['forex']
    elif symbol in METALS_SYMBOLS:
        return MR_CONFIG['metals']
    return MR_CONFIG['crypto']


def _calculate_bb(closes, period=20, std_mult=2.0):
    """Calculate Bollinger Bands."""
    sma = closes.rolling(period).mean()
    std = closes.rolling(period).std()
    upper = sma + std_mult * std
    lower = sma - std_mult * std
    return upper, sma, lower


def _calculate_rsi(closes, period=14):
    """Calculate RSI."""
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _calculate_adx(df, period=14):
    """Calculate ADX from OHLC data."""
    high = df['h'].astype(float)
    low = df['l'].astype(float)
    close = df['c'].astype(float)

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)

    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
    adx = dx.rolling(period).mean()
    return adx


def _check_cooldown(symbol):
    """Check if symbol is in post-trade cooldown."""
    key = f'lighter:mr_cooldown:{symbol}'
    return not cache.get(key)


def _set_cooldown(symbol):
    """Set post-trade cooldown for symbol."""
    key = f'lighter:mr_cooldown:{symbol}'
    cache.set(key, True, timeout=MR_COOLDOWN_SECONDS)


def mean_reversion_algorithm(symbols=None):
    """Mean reversion entry algorithm. Called every 30-60s by Celery.

    For each symbol:
    1. Check ADX — only trade in ranging markets (ADX < threshold)
    2. Check Bollinger Bands — price at upper/lower extreme
    3. Check RSI — confirms oversold/overbought
    4. Enter position targeting the mean (middle BB)
    """
    if cache.get('lighter:disabled'):
        return

    # Circuit breaker check
    if cache.get('lighter:circuit_breaker'):
        logger.debug("MR: circuit breaker active, skipping")
        return

    if symbols is None:
        symbols = MR_SYMBOLS

    from app.crypto.models import CryptoPosition

    # Count open MR positions
    mr_open = CryptoPosition.objects.filter(
        status='OPEN',
        entry_signal__startswith=f'{PLATFORM_PREFIX}mr_',
    ).count()

    if mr_open >= 4:  # Aggressive — up to 4 MR positions
        logger.debug("MR: max positions reached (%d/4)", mr_open)
        return

    for symbol in symbols:
        try:
            _scan_symbol(symbol)
        except Exception as e:
            logger.error("MR error for %s: %s", symbol, e)


def _scan_symbol(symbol):
    """Scan a single symbol for mean reversion entry."""
    from app.crypto.models import CryptoPosition, CryptoTrade

    meta = LIGHTER_MARKETS.get(symbol)
    if meta is None:
        return

    # Check if already in position
    if CryptoPosition.objects.filter(symbol=symbol, status='OPEN',
                                      entry_signal__startswith=PLATFORM_PREFIX).exists():
        return

    # Check cooldown
    if not _check_cooldown(symbol):
        return

    config = _get_config(symbol)

    # Fetch 15m candles (best timeframe for crypto MR per research)
    candles = get_candles(symbol, resolution='15m', count_back=60)
    if not candles or len(candles) < config['bb_period'] + 10:
        return

    df = pd.DataFrame(candles)
    for col in ['o', 'h', 'l', 'c']:
        df[col] = df[col].astype(float)

    closes = df['c']

    # Calculate indicators
    bb_upper, bb_mid, bb_lower = _calculate_bb(closes, config['bb_period'], config['bb_std'])
    rsi = _calculate_rsi(closes, config['rsi_period'])
    adx = _calculate_adx(df, period=14)

    # Get latest values
    current_price = closes.iloc[-1]
    current_rsi = rsi.iloc[-1]
    current_adx = adx.iloc[-1]
    current_bb_upper = bb_upper.iloc[-1]
    current_bb_lower = bb_lower.iloc[-1]
    current_bb_mid = bb_mid.iloc[-1]

    if pd.isna(current_adx) or pd.isna(current_rsi) or pd.isna(current_bb_upper):
        return

    # ── Liquidation cascade check (runs regardless of ADX/BB/RSI) ──
    liq_signal, liq_ratio = 0, 0.0
    try:
        liq_signal, liq_ratio = check_liquidation_signal(symbol)
    except Exception as e:
        logger.debug("MR %s: liquidation check failed: %s", symbol, e)

    # ── Gate 1: ADX filter — only trade in ranging markets ──
    adx_ok = current_adx <= config['adx_max']
    if not adx_ok and liq_signal == 0:
        logger.debug("MR %s: ADX=%.1f > %d, market trending, no liq signal, skip",
                     symbol, current_adx, config['adx_max'])
        return

    # ── Gate 2: Bollinger Band + RSI signal ──
    bb_rsi_signal = 0
    signal_type = ''

    # BUY: price near/below lower BB AND RSI oversold
    # "Near" = within 20% of the band width — catches bounces before touching
    band_width = current_bb_upper - current_bb_lower
    near_threshold = band_width * 0.2

    if current_price <= (current_bb_lower + near_threshold) and current_rsi < config['rsi_oversold']:
        bb_rsi_signal = 1
        signal_type = f"mr_buy_bb{config['bb_std']}_rsi{current_rsi:.0f}_adx{current_adx:.0f}"

    # SELL: price near/above upper BB AND RSI overbought
    elif current_price >= (current_bb_upper - near_threshold) and current_rsi > config['rsi_overbought']:
        bb_rsi_signal = -1
        signal_type = f"mr_sell_bb{config['bb_std']}_rsi{current_rsi:.0f}_adx{current_adx:.0f}"

    # ── Determine final signal and sizing mode ──
    # Three cases:
    #   1. BB/RSI + liquidation cascade (same direction) = boosted entry (150% size)
    #   2. BB/RSI only (no liquidation) = normal entry (confluence-sized)
    #   3. Liquidation only (no BB/RSI) = half-size entry (50% size)
    signal = 0
    size_mode = 'normal'  # 'normal', 'boosted', 'liq_only'

    if bb_rsi_signal != 0 and liq_signal != 0 and bb_rsi_signal == liq_signal:
        # Case 1: Both signals agree — maximum confidence
        signal = bb_rsi_signal
        size_mode = 'boosted'
        signal_type = f"{signal_type}_liq{liq_ratio:.1f}x"
        logger.info("MR %s: BB/RSI + LIQUIDATION CASCADE agree (%s, %.1fx volume) — boosted entry",
                     symbol, 'BUY' if signal > 0 else 'SELL', liq_ratio)
    elif bb_rsi_signal != 0 and adx_ok:
        # Case 2: BB/RSI signal only, normal path
        signal = bb_rsi_signal
        size_mode = 'normal'
    elif liq_signal != 0:
        # Case 3: Liquidation cascade only — enter with half size
        # ADX gate relaxed: liquidation cascades override ranging-market requirement
        signal = liq_signal
        size_mode = 'liq_only'
        direction_label = 'buy' if liq_signal > 0 else 'sell'
        signal_type = f"mr_liq_{direction_label}_vol{liq_ratio:.1f}x_adx{current_adx:.0f}"
        logger.info("MR %s: LIQUIDATION CASCADE only (%.1fx volume, %s) — half-size entry",
                     symbol, liq_ratio, direction_label.upper())
    else:
        return

    # ── Confluence scoring (NEVER blocks — only adjusts size) ──
    confluence = None
    try:
        direction = 'BUY' if signal > 0 else 'SELL'
        confluence = score_entry(symbol, direction, candles)
    except Exception:
        pass

    # ── Execute entry ──
    is_buy = signal > 0
    side = 'LONG' if is_buy else 'SHORT'
    base_position_usd = config['size_usd'] * LIGHTER_LEVERAGE

    # Size adjustment: confluence boosts size, never blocks
    conf_mult = confluence.size_multiplier if confluence else 1.0
    if conf_mult < 0.5:
        conf_mult = 0.5  # Floor at 50% — always trade, just smaller

    if size_mode == 'boosted':
        position_usd = base_position_usd * conf_mult * 1.5
    elif size_mode == 'liq_only':
        position_usd = base_position_usd * 0.5
    else:
        position_usd = base_position_usd * conf_mult

    # Get live price
    prices = get_best_bid_ask(symbol)
    live_price = prices.get('mid')
    if not live_price or live_price <= 0:
        return

    confluence_str = f"confluence={confluence.total_score}/5 {confluence.band} {confluence.size_multiplier * 100:.0f}%" if confluence else "liq_only"
    logger.info("MR ENTRY: %s %s $%.2f mode=%s (price=%.4f, RSI=%.1f, ADX=%.1f, BB=[%.4f, %.4f, %.4f], %s, liq=%.1fx)",
                symbol, side, position_usd, size_mode, live_price, current_rsi, current_adx,
                current_bb_lower, current_bb_mid, current_bb_upper,
                confluence_str, liq_ratio)

    # Set leverage
    try:
        update_leverage(symbol, LIGHTER_LEVERAGE)
    except Exception:
        pass

    # Place order
    result = place_market_order_usd(symbol, is_buy, position_usd)
    if result.get('error'):
        logger.error("MR %s: order failed: %s", symbol, result['error'])
        return

    # Calculate SL/TP — TP targets the mean (middle BB), SL is wider
    if is_buy:
        take_profit = current_bb_mid  # Target the mean
        stop_loss = live_price * (1 - config['sl_pct'])
    else:
        take_profit = current_bb_mid  # Target the mean
        stop_loss = live_price * (1 + config['sl_pct'])

    # Record position
    base_size = position_usd / live_price
    confluence_tag = f"_c{confluence.total_score}" if confluence else ""
    position = CryptoPosition.objects.create(
        symbol=symbol,
        side=side,
        entry_price=live_price,
        size=base_size,
        leverage=LIGHTER_LEVERAGE,
        entry_signal=f"{PLATFORM_PREFIX}{signal_type}{confluence_tag}",
        stop_loss=stop_loss,
        take_profit=take_profit,
        status='OPEN',
        venue='LIGHTER',
    )

    CryptoTrade.objects.create(
        position=position,
        order_id=result.get('tx_hash', ''),
        side='BUY' if is_buy else 'SELL',
        price=live_price,
        size=base_size,
        fee=0.0,
        status='FILLED',
    )

    # Place native on-chain SL/TP as OCO group (one-cancels-other)
    try:
        oco_result = place_oco_sltp(symbol, is_buy, base_size, stop_loss, take_profit)
        if oco_result.get('error'):
            logger.warning("MR OCO SL/TP failed for %s: %s", symbol, oco_result['error'])
        else:
            logger.info("MR OCO SL/TP placed: %s SL=%.4f TP=%.4f tx=%s",
                        symbol, stop_loss, take_profit, oco_result.get('tx_hash', '?'))
    except Exception as e:
        logger.warning("MR OCO SL/TP exception for %s: %s", symbol, e)

    _set_cooldown(symbol)

    confluence_log = f"confluence={confluence.total_score}/5({confluence.band})" if confluence else "liq_cascade"
    logger.info("MR position opened: %s %s size=%.6f TP=%.4f (mean) SL=%.4f signal=%s %s mode=%s",
                symbol, side, base_size, take_profit, stop_loss, signal_type,
                confluence_log, size_mode)
