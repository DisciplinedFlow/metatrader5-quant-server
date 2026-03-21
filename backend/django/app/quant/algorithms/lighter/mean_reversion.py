"""
Lighter.xyz Mean Reversion Strategy — BB + RSI + ADX filter
+ Liquidation Cascade Detector.

Per-symbol backtest-validated configs:
- XAU 15m: BB(14,3σ)+RSI(14)<30/>70+ADX<35, TP=mid_bb, SL=2% → 89.7% WR, PF 5.15
- SOL 1h:  BB(20,2.5σ)+RSI(14)<30/>70+ADX<35, TP=1% fixed, SL=2% → 85.2% WR, PF 2.44

Liquidation cascade integration:
- If BB/RSI + liquidation cascade align: boost position by 50% (confluence)
- If liquidation cascade fires alone (without BB/RSI): enter with half position size
"""
import logging
import math
import pandas as pd
from django.core.cache import cache

from .config import LIGHTER_MARKETS, LIGHTER_LEVERAGE
from .client import get_candles, get_best_bid_ask, place_market_order_usd, update_leverage, place_oco_sltp
from .confluence import score_entry
from .liquidation_detector import check_liquidation_signal
from .sizing import calculate_position_usd

logger = logging.getLogger('app.lighter')


PLATFORM_PREFIX = 'lighter:'

# ── Per-symbol configs (backtest-validated) ──

MR_CONFIGS = {
    'XAU': {
        'bb_period': 14, 'bb_std': 3.0,
        'rsi_period': 14, 'rsi_oversold': 30, 'rsi_overbought': 70,
        'adx_max': 35,
        'sl_pct': 0.02,
        'tp_mode': 'mid_bb',       # dynamic: TP = middle Bollinger Band
        'tp_fixed_pct': None,
        'timeframe': '15m',
    },
    # SOL removed: 50% WR, net negative PnL. Re-enable after recalibration
    # 'SOL': {
    #     'bb_period': 20, 'bb_std': 2.5,
    #     'rsi_period': 14, 'rsi_oversold': 30, 'rsi_overbought': 70,
    #     'adx_max': 35,
    #     'sl_pct': 0.02,
    #     'tp_mode': 'fixed',
    #     'tp_fixed_pct': 0.01,
    #     'timeframe': '1h',
    # },
}

MR_SYMBOLS = list(MR_CONFIGS.keys())

MR_COOLDOWN_SECONDS = 60


def _get_config(symbol):
    return MR_CONFIGS.get(symbol, MR_CONFIGS['XAU'])


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

    # Losing streak cooldown disabled — brain collects data through all conditions
    # if cache.get('lighter:streak_cooldown'):
    #     logger.debug("MR: losing streak cooldown, skipping")
    #     return

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

    # Global cap — enforces exchange OCO slot limit (2 positions × SL+TP = 4 conditional orders max)
    from .config import is_global_position_limit_reached
    if is_global_position_limit_reached():
        logger.debug("MR: global position limit reached, skipping")
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

    # Vanish cooldown — position recently disappeared from exchange
    if cache.get(f'lighter:vanish_cooldown:{symbol}'):
        return

    # Check cooldown
    if not _check_cooldown(symbol):
        return

    config = _get_config(symbol)

    # Fetch candles at per-symbol validated timeframe
    tf = config.get('timeframe', '15m')
    candles = get_candles(symbol, resolution=tf, count_back=60)
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

    # ML filter disabled — collecting training data, brain learns from trades
    # Re-enable once model has 200+ crypto trades to train on

    # Neo4j feedback removed — graph is offline, was always returning 1.0

    # ── Confluence scoring (NEVER blocks — only adjusts size) ──
    confluence = None
    try:
        direction = 'BUY' if signal > 0 else 'SELL'
        confluence = score_entry(symbol, direction, candles)
    except Exception:
        pass

    # ── Funding rate contrarian signal (NEVER blocks — adjusts size) ──
    funding_mult = 1.0
    funding_info = ''
    try:
        from .funding_signal import get_funding_rate_signal
        funding = get_funding_rate_signal(symbol)
        funding_signal = funding.get('signal', 0)
        if funding_signal != 0:
            # Funding contrarian agrees with our trade direction?
            if funding_signal == signal:
                funding_mult = 1.2  # Boost 20% — crowd is wrong, we agree with contrarian
                funding_info = f"funding_boost(z={funding.get('z_score', 0):.1f})"
            else:
                funding_mult = 0.7  # Reduce 30% — contrarian signal disagrees
                funding_info = f"funding_reduce(z={funding.get('z_score', 0):.1f})"
        else:
            funding_info = "funding_neutral"
    except Exception as e:
        logger.debug("MR %s: funding signal check failed: %s", symbol, e)
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
                logger.warning("MR %s: WHALE AGAINST trade direction! whale=%s our=%s cvd=$%.0f",
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
        logger.debug("MR %s: trade flow check failed: %s", symbol, e)
        flow_info = "flow_error"

    # ── Execute entry ──
    is_buy = signal > 0
    side = 'LONG' if is_buy else 'SHORT'
    base_position_usd = calculate_position_usd(symbol, config['sl_pct'])

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

    # Apply funding + trade flow multipliers
    position_usd = position_usd * funding_mult * flow_mult

    # Get live price
    prices = get_best_bid_ask(symbol)
    live_price = prices.get('mid')
    if not live_price or live_price <= 0:
        return

    confluence_str = f"confluence={confluence.total_score}/5 {confluence.band} {confluence.size_multiplier * 100:.0f}%" if confluence else "liq_only"
    logger.info("MR ENTRY: %s %s $%.2f mode=%s (price=%.4f, RSI=%.1f, ADX=%.1f, BB=[%.4f, %.4f, %.4f], %s, liq=%.1fx, %s, %s)",
                symbol, side, position_usd, size_mode, live_price, current_rsi, current_adx,
                current_bb_lower, current_bb_mid, current_bb_upper,
                confluence_str, liq_ratio, funding_info, flow_info)

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

    # Calculate SL/TP — per-symbol: mid_bb (XAU) or fixed % (SOL)
    if is_buy:
        stop_loss = live_price * (1 - config['sl_pct'])
        if config.get('tp_mode') == 'fixed':
            take_profit = live_price * (1 + config['tp_fixed_pct'])
        else:
            take_profit = current_bb_mid
    else:
        stop_loss = live_price * (1 + config['sl_pct'])
        if config.get('tp_mode') == 'fixed':
            take_profit = live_price * (1 - config['tp_fixed_pct'])
        else:
            take_profit = current_bb_mid

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
