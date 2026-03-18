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


# ── Intelligence layers (all fail-open, never block trading) ─────────

def _get_news_risk():
    """Get news risk level — cached 5min, fail-open."""
    try:
        from app.quant.indicators.news_sentiment import get_market_risk_level
        return get_market_risk_level()
    except Exception:
        return {'risk_level': 'NORMAL', 'size_multiplier': 1.0}


def _get_graph_advice(symbol, direction, hour_utc):
    """Get Neo4j graph advisor — cached 5min, fail-open."""
    try:
        from app.quant.knowledge.advisor import get_trade_advice
        return get_trade_advice(
            symbol=symbol,
            direction='BUY' if direction > 0 else 'SELL',
            strategy='LIGHTER_RSI2',
            hour_utc=hour_utc,
            setup_type='RSI_SCALP',
        )
    except Exception:
        return {'confidence': 0.5, 'size_modifier': 1.0, 'recommendation': 'NORMAL'}


def _record_reasoning(trade_id, symbol, direction, rsi_val, ema_trend,
                      signal_type, graph_advice, news_risk, position_usd):
    """Record trade reasoning to Neo4j — fire-and-forget."""
    try:
        from app.quant.tasks import record_to_graph
        record_to_graph.delay({
            'type': 'trade_reasoning',
            'reasoning': {
                'trade_id': trade_id,
                'symbol': symbol,
                'direction': 'BUY' if direction > 0 else 'SELL',
                'setup_type': 'RSI_SCALP',
                'entry_source': 'LIGHTER_RSI2',
                'entry_zone': f'RSI2_{rsi_val:.0f}',
                'htf_trend': ema_trend.upper(),
                'news_risk': news_risk.get('risk_level', 'NORMAL'),
                'news_size_mult': news_risk.get('size_multiplier', 1.0),
                'graph_confidence': graph_advice.get('confidence', 0.5),
                'graph_recommendation': graph_advice.get('recommendation', 'NORMAL'),
                'confluence_score': 0,
                'reasoning_text': (
                    f'RSI2={rsi_val:.0f} in {ema_trend} trend, '
                    f'signal={signal_type}, size=${position_usd:.2f}'
                ),
            }
        })
    except Exception:
        pass


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
        'tp_pct': 0.010,   # 1.0% TP — 1:1 R:R requires only >50% WR (was 0.75%, 57% WR needed)
        'size_usd': 12,
    },
    'metals': {
        'rsi_period': 2,
        'rsi_oversold': 15,
        'rsi_overbought': 85,
        'ema_period': 50,
        'sl_pct': 0.008,   # 0.8% SL
        'tp_pct': 0.008,   # 0.8% TP — 1:1 R:R (was 0.6%)
        'size_usd': 12,
    },
    'forex': {
        'rsi_period': 2,
        'rsi_oversold': 15,
        'rsi_overbought': 85,
        'ema_period': 50,
        'sl_pct': 0.003,   # 0.3% SL
        'tp_pct': 0.003,   # 0.3% TP — 1:1 R:R (was 0.15%)
        'size_usd': 12,
    },
}

# Symbols to scan every 10 seconds
RSI2_SYMBOLS = ['ETH', 'BTC', 'SOL', 'XAU']

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

    # ── Neo4j feedback loop (NEVER blocks — adjusts size or skips) ──
    neo4j_mult = 1.0
    neo4j_info = 'neo4j_neutral'
    try:
        from .neo4j_feedback import get_neo4j_sizing
        direction = 'LONG' if signal > 0 else 'SHORT'
        hour = __import__('datetime').datetime.utcnow().hour
        neo4j_mult = get_neo4j_sizing(symbol, direction, 'rsi2', hour)
        if neo4j_mult == 0.0:
            logger.info("RSI2 %s: Neo4j feedback SKIP — historical WR too low", symbol)
            return False
        elif neo4j_mult != 1.0:
            neo4j_info = f"neo4j_{neo4j_mult:.2f}x"
        else:
            neo4j_info = "neo4j_neutral"
    except Exception as e:
        logger.debug("RSI2 %s: Neo4j feedback failed: %s", symbol, e)
        neo4j_info = "neo4j_error"

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

    # ── News sentiment sizing (cached 5min, fail-open) ──
    news_risk = _get_news_risk()
    news_mult = news_risk.get('size_multiplier', 1.0)
    news_info = f"news_{news_risk.get('risk_level', 'NORMAL')}({news_mult:.2f}x)"

    # ── Graph advisor (richer than neo4j_sizing — cached 5min, fail-open) ──
    current_hour_utc = __import__('datetime').datetime.utcnow().hour
    graph_advice = _get_graph_advice(symbol, signal, current_hour_utc)
    graph_mult = graph_advice.get('size_modifier', 1.0)
    graph_info = f"graph_{graph_advice.get('recommendation', 'NORMAL')}({graph_mult:.2f}x)"
    if graph_advice.get('recommendation') == 'AVOID':
        logger.info("RSI2 %s: Graph advisor AVOID — skipping", symbol)
        return False

    if news_mult != 1.0 or graph_mult != 1.0:
        logger.info("RSI2 %s: intelligence sizing: %s %s", symbol, news_info, graph_info)

    # ── Execute entry ──
    is_buy = signal > 0
    side = 'LONG' if is_buy else 'SHORT'
    position_usd = config['size_usd'] * LIGHTER_LEVERAGE * get_combined_sizing(symbol)

    # Apply neo4j feedback + funding + trade flow + news + graph multipliers
    position_usd = position_usd * neo4j_mult * funding_mult * flow_mult * news_mult * graph_mult

    # Get live price
    prices = get_best_bid_ask(symbol)
    live_price = prices.get('mid')
    if not live_price or live_price <= 0:
        return False

    logger.info("RSI2 ENTRY: %s %s $%.2f (price=%.4f, RSI(2)=%.1f, EMA50=%.4f, trend=%s, %s, %s, %s, %s, %s)",
                symbol, side, position_usd, live_price, current_rsi, current_ema, trend,
                neo4j_info, funding_info, flow_info, news_info, graph_info)

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

    # Record trade open to knowledge graph
    try:
        from app.quant.tasks import record_to_graph
        record_to_graph.delay({
            'type': 'lighter_trade_open',
            'trade_id': f'lighter_{position.id}',
            'django_id': position.id,
            'symbol': symbol,
            'direction': 'BUY' if is_buy else 'SELL',
            'entry_time': position.opened_at,
            'entry_price': float(live_price),
            'strategy': position.entry_signal or 'unknown',
            'venue': 'LIGHTER',
            'hour_utc': position.opened_at.hour if position.opened_at else 0,
            'day_of_week': position.opened_at.weekday() if position.opened_at else 0,
            'trading_era': 'BRAIN_V1',
        })
    except Exception:
        pass

    # Record trade reasoning to Neo4j (fire-and-forget)
    _record_reasoning(
        position.id, symbol, signal, current_rsi, trend,
        signal_type, graph_advice, news_risk, position_usd,
    )

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
