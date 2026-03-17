"""
Lighter.xyz Confluence Scorer — rates trade quality from -1 to 9.

Simplified version of the forex 0-11 confluence scorer, tuned for crypto
perpetuals on Lighter.xyz. Each factor is binary (0 or 1 point), except
OI which can be -1, 0, or +1, and OB imbalance which is 0-2.

Factors:
1. Volume confirmation (0-1): Is current volume > 1.5x 20-period average?
2. Multi-timeframe alignment (0-1): Does 1H trend agree with signal direction?
3. Funding rate awareness (0-1): Is funding favorable for our direction?
4. Spread check (0-1): Is bid-ask spread tight enough?
5. RSI/momentum confirmation (0-1): Multiple indicators agree?
6. Open Interest confirmation (-1 to +1): Does OI+price confirm direction?
7. Order book imbalance (0-2): Does real-time OB pressure align with direction?
8. VWAP alignment (0-1): Is trade direction aligned with VWAP bias?

MAX_SCORE = 9  (sum of all max factor values: 1+1+1+1+1+1+2+1)
Minimum score to trade: 1/9

Scoring bands:
  <=0: skip — don't trade, insufficient confirmation
  1:   half_size — weak edge, trade with 50% position
  2-5: full_size — solid edge, trade normal
  6-9: boost — everything aligned, trade with 120% position
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

import pandas as pd
from django.core.cache import cache

from .client import get_best_bid_ask, get_candles
from .config import LIGHTER_MARKETS

logger = logging.getLogger('app.lighter')

# ── Constants ─────────────────────────────────────────────

MIN_SCORE = 1  # Aggressive — BB+RSI+ADX already filter, confluence is bonus
VOLUME_THRESHOLD = 1.5       # Current volume must be > 1.5x average
VOLUME_LOOKBACK = 20         # 20-period volume average
EMA_FAST = 8                 # 1H fast EMA for MTF alignment
EMA_SLOW = 21                # 1H slow EMA for MTF alignment
FUNDING_CACHE_TTL = 300      # Cache funding rate for 5 min
SPREAD_THRESHOLD_CRYPTO = 0.0005   # 0.05% for crypto
SPREAD_THRESHOLD_FOREX = 0.0002    # 0.02% for forex

FOREX_SYMBOLS = {'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'USDCAD', 'AUDUSD', 'NZDUSD'}


# ── Result dataclass ──────────────────────────────────────

@dataclass
class ConfluenceResult:
    """Complete confluence assessment for a potential Lighter.xyz trade."""
    total_score: int
    factors: Dict[str, int] = field(default_factory=dict)
    details: Dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.total_score >= MIN_SCORE

    @property
    def band(self) -> str:
        if self.total_score <= 0:
            return 'skip'
        elif self.total_score == 1:
            return 'half_size'
        elif self.total_score <= 5:
            return 'full_size'
        else:  # 6-9
            return 'boost'

    @property
    def size_multiplier(self) -> float:
        """Position size multiplier based on band."""
        return {
            'skip': 0.0,
            'half_size': 0.5,
            'full_size': 1.0,
            'boost': 1.2,
        }[self.band]


# ── Main entry point ──────────────────────────────────────

def score_entry(
    symbol: str,
    direction: str,
    candles_15m: list,
    candles_1h: Optional[list] = None,
) -> ConfluenceResult:
    """Score a potential entry from -1 to 9 based on confluence factors.

    Args:
        symbol: Trading pair (e.g. 'ETH', 'BTC', 'EURUSD')
        direction: 'BUY' or 'SELL'
        candles_15m: List of 15m candle dicts with keys: o, h, l, c, v
        candles_1h: Optional list of 1H candle dicts for MTF alignment.
                    If None, will be fetched automatically.

    Returns:
        ConfluenceResult with total_score, factors, passed, and band.
    """
    factors = {}
    details = {}

    # Factor 1: Volume confirmation
    score, detail = _score_volume(candles_15m)
    factors['volume'] = score
    details['volume'] = detail

    # Factor 2: Multi-timeframe alignment
    score, detail = _score_mtf_alignment(symbol, direction, candles_1h)
    factors['mtf_alignment'] = score
    details['mtf_alignment'] = detail

    # Factor 3: Funding rate awareness
    score, detail = _score_funding(symbol, direction)
    factors['funding'] = score
    details['funding'] = detail

    # Factor 4: Spread check
    score, detail = _score_spread(symbol)
    factors['spread'] = score
    details['spread'] = detail

    # Factor 5: RSI/momentum confirmation
    score, detail = _score_momentum(candles_15m, direction)
    factors['momentum'] = score
    details['momentum'] = detail

    # Factor 6: Open Interest confirmation (can be -1, 0, or +1)
    score, detail = _score_open_interest(symbol, direction)
    factors['open_interest'] = score
    details['open_interest'] = detail

    # Factor 7: Order book imbalance (0-2 points, from WebSocket stream)
    score, detail = _score_ob_imbalance(symbol, direction)
    factors['ob_imbalance'] = score
    details['ob_imbalance'] = detail

    # Factor 8: VWAP alignment (0-1 point)
    score, detail = _score_vwap(symbol, direction)
    factors['vwap'] = score
    details['vwap'] = detail

    total = sum(factors.values())
    result = ConfluenceResult(total_score=total, factors=factors, details=details)

    logger.info(
        "Confluence %s %s: %d/9 [%s] band=%s | %s",
        symbol, direction, total,
        ' '.join(f'{k}={v}' for k, v in factors.items()),
        result.band,
        ' | '.join(f'{k}: {v}' for k, v in details.items()),
    )

    return result


# ── Factor implementations ────────────────────────────────

def _score_volume(candles_15m: list) -> tuple:
    """Factor 1: Volume confirmation.

    Compare last candle volume to 20-period average.
    Score 1 if current volume > 1.5x average (institutional participation).
    """
    try:
        if not candles_15m or len(candles_15m) < VOLUME_LOOKBACK + 1:
            return 0, "insufficient data"

        volumes = [float(c.get('v', 0)) for c in candles_15m]
        if not any(v > 0 for v in volumes):
            return 0, "no volume data"

        current_vol = volumes[-1]
        avg_vol = sum(volumes[-VOLUME_LOOKBACK - 1:-1]) / VOLUME_LOOKBACK

        if avg_vol <= 0:
            return 0, "zero avg volume"

        ratio = current_vol / avg_vol
        if ratio >= VOLUME_THRESHOLD:
            return 1, f"vol {ratio:.1f}x avg (>{VOLUME_THRESHOLD}x)"
        else:
            return 0, f"vol {ratio:.1f}x avg (<{VOLUME_THRESHOLD}x)"
    except Exception as e:
        logger.debug("Volume scoring failed: %s", e)
        return 0, f"error: {e}"


def _score_mtf_alignment(
    symbol: str,
    direction: str,
    candles_1h: Optional[list] = None,
) -> tuple:
    """Factor 2: Multi-timeframe alignment.

    Check if 1H EMA(8) > EMA(21) for BUY signals, or EMA(8) < EMA(21) for SELL.
    This ensures we're trading with the higher-timeframe trend.
    """
    try:
        # Fetch 1H candles if not provided
        if candles_1h is None:
            candles_1h = get_candles(symbol, resolution='1h', count_back=30)

        if not candles_1h or len(candles_1h) < EMA_SLOW + 5:
            return 0, "insufficient 1H data"

        closes = pd.Series([float(c['c']) for c in candles_1h])
        ema_fast = closes.ewm(span=EMA_FAST, adjust=False).mean()
        ema_slow = closes.ewm(span=EMA_SLOW, adjust=False).mean()

        fast_val = ema_fast.iloc[-1]
        slow_val = ema_slow.iloc[-1]

        is_buy = direction.upper() == 'BUY'

        if is_buy and fast_val > slow_val:
            return 1, f"1H EMA8({fast_val:.4f}) > EMA21({slow_val:.4f}), bullish aligned"
        elif not is_buy and fast_val < slow_val:
            return 1, f"1H EMA8({fast_val:.4f}) < EMA21({slow_val:.4f}), bearish aligned"
        else:
            trend = "bullish" if fast_val > slow_val else "bearish"
            return 0, f"1H trend {trend}, misaligned with {direction}"
    except Exception as e:
        logger.debug("MTF alignment scoring failed: %s", e)
        return 0, f"error: {e}"


def _score_funding(symbol: str, direction: str) -> tuple:
    """Factor 3: Funding rate awareness.

    Score 1 if funding is favorable for our direction:
    - Going SHORT when funding is positive = favorable (longs pay shorts)
    - Going LONG when funding is negative = favorable (shorts pay longs)
    - Neutral funding (near zero) also scores 1 (no headwind)

    Uses Redis cache with 5-min TTL to avoid excessive API calls.
    """
    try:
        # Check if this is a non-crypto symbol (no funding for forex/metals)
        if symbol in FOREX_SYMBOLS:
            return 1, "forex: no funding rate (neutral)"

        cache_key = f'lighter:funding:{symbol}'
        funding_rate = cache.get(cache_key)

        if funding_rate is None:
            # Try to get funding from exchange stats
            try:
                from .client import get_exchange_stats
                stats = get_exchange_stats()
                # Exchange stats may contain funding info per market
                if hasattr(stats, 'markets') and stats.markets:
                    market_id = LIGHTER_MARKETS.get(symbol, {}).get('id')
                    for m in stats.markets:
                        if hasattr(m, 'market_id') and m.market_id == market_id:
                            funding_rate = float(getattr(m, 'funding_rate', 0))
                            break
            except Exception:
                pass

            if funding_rate is None:
                funding_rate = 0.0  # Default to neutral if unavailable

            cache.set(cache_key, funding_rate, timeout=FUNDING_CACHE_TTL)

        is_buy = direction.upper() == 'BUY'
        # Near-zero funding (< 0.005%) is neutral — no headwind
        NEUTRAL_THRESHOLD = 0.00005

        if abs(funding_rate) < NEUTRAL_THRESHOLD:
            return 1, f"funding {funding_rate:+.6f} (neutral)"
        elif is_buy and funding_rate < 0:
            return 1, f"funding {funding_rate:+.6f} (favorable for long)"
        elif not is_buy and funding_rate > 0:
            return 1, f"funding {funding_rate:+.6f} (favorable for short)"
        else:
            return 0, f"funding {funding_rate:+.6f} (unfavorable for {direction})"
    except Exception as e:
        logger.debug("Funding scoring failed: %s", e)
        return 0, f"error: {e}"


def _score_spread(symbol: str) -> tuple:
    """Factor 4: Spread check.

    Score 1 if bid-ask spread is tight enough:
    - Crypto: spread < 0.05% of mid price
    - Forex: spread < 0.02% of mid price

    Wide spreads eat into edge — skip if liquidity is thin.
    """
    try:
        prices = get_best_bid_ask(symbol)
        bid = prices.get('bid')
        ask = prices.get('ask')
        mid = prices.get('mid')

        if not bid or not ask or not mid or mid <= 0:
            return 0, "no bid/ask data"

        spread_pct = (ask - bid) / mid
        threshold = SPREAD_THRESHOLD_FOREX if symbol in FOREX_SYMBOLS else SPREAD_THRESHOLD_CRYPTO

        if spread_pct <= threshold:
            return 1, f"spread {spread_pct:.4%} <= {threshold:.4%}"
        else:
            return 0, f"spread {spread_pct:.4%} > {threshold:.4%} (wide)"
    except Exception as e:
        logger.debug("Spread scoring failed: %s", e)
        return 0, f"error: {e}"


def _score_momentum(candles_15m: list, direction: str) -> tuple:
    """Factor 5: RSI + MACD + price action momentum confirmation.

    Score 1 if at least 2 of 3 indicators agree with direction:
    - RSI: < 50 for SELL, > 50 for BUY (momentum direction)
    - MACD: histogram positive for BUY, negative for SELL
    - Price action: last 3 candles net direction matches signal

    Note: For mean reversion, RSI will often be at extremes (which is
    the entry signal). This factor checks if secondary momentum indicators
    confirm the expected reversal.
    """
    try:
        if not candles_15m or len(candles_15m) < 30:
            return 0, "insufficient data for momentum"

        closes = pd.Series([float(c['c']) for c in candles_15m])
        is_buy = direction.upper() == 'BUY'
        agreements = 0
        signals = []

        # 1. RSI direction check
        rsi = _calculate_rsi(closes, period=14)
        current_rsi = rsi.iloc[-1]
        if not pd.isna(current_rsi):
            # For mean reversion: RSI at extreme IS the signal.
            # Here we check if RSI is moving back toward 50 (reversal starting).
            prev_rsi = rsi.iloc[-2] if len(rsi) > 1 else current_rsi
            if is_buy and current_rsi > prev_rsi:
                agreements += 1
                signals.append(f"RSI turning up ({prev_rsi:.0f}->{current_rsi:.0f})")
            elif not is_buy and current_rsi < prev_rsi:
                agreements += 1
                signals.append(f"RSI turning down ({prev_rsi:.0f}->{current_rsi:.0f})")
            else:
                signals.append(f"RSI not confirming ({prev_rsi:.0f}->{current_rsi:.0f})")

        # 2. MACD histogram direction
        ema12 = closes.ewm(span=12, adjust=False).mean()
        ema26 = closes.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line

        current_hist = histogram.iloc[-1]
        prev_hist = histogram.iloc[-2] if len(histogram) > 1 else current_hist

        if not pd.isna(current_hist):
            # Check if histogram is improving in our direction
            if is_buy and current_hist > prev_hist:
                agreements += 1
                signals.append(f"MACD hist improving ({current_hist:.6f})")
            elif not is_buy and current_hist < prev_hist:
                agreements += 1
                signals.append(f"MACD hist declining ({current_hist:.6f})")
            else:
                signals.append(f"MACD hist not confirming ({current_hist:.6f})")

        # 3. Price action — last 3 candles net direction
        if len(closes) >= 3:
            net_change = closes.iloc[-1] - closes.iloc[-3]
            if is_buy and net_change > 0:
                agreements += 1
                signals.append(f"PA bullish (net +{net_change:.4f})")
            elif not is_buy and net_change < 0:
                agreements += 1
                signals.append(f"PA bearish (net {net_change:.4f})")
            else:
                signals.append(f"PA not confirming (net {net_change:+.4f})")

        detail = f"{agreements}/3 agree: {', '.join(signals)}"
        if agreements >= 2:
            return 1, detail
        else:
            return 0, detail
    except Exception as e:
        logger.debug("Momentum scoring failed: %s", e)
        return 0, f"error: {e}"


def _score_ob_imbalance(symbol: str, direction: str) -> tuple:
    """Factor 7: Order book imbalance (0-2 points).

    Uses real-time order book data streamed via WebSocket to Redis.
    Scores based on alignment between OB pressure and trade direction:

      - OB imbalance > 0.65 AND direction is BUY  -> +2 (strong bid pressure aligns)
      - OB imbalance < 0.35 AND direction is SELL  -> +2 (strong ask pressure aligns)
      - OB imbalance 0.45-0.55 (balanced book)     -> +1 (no headwind)
      - Otherwise                                   -> 0  (misaligned or no data)

    Falls back gracefully to 0 if WebSocket data is stale or unavailable.
    """
    try:
        from .orderbook_signal import get_ob_confluence_score, get_ob_imbalance
        score = get_ob_confluence_score(symbol, direction)
        imbalance = get_ob_imbalance(symbol)
        if score == 2:
            return score, f"OB imbalance {imbalance:.3f} strongly aligned with {direction}"
        elif score == 1:
            return score, f"OB imbalance {imbalance:.3f} balanced (neutral)"
        else:
            return score, f"OB imbalance {imbalance:.3f} not aligned with {direction}"
    except Exception as e:
        logger.debug("OB imbalance scoring failed: %s", e)
        return 0, f"error: {e}"


def _score_open_interest(symbol: str, direction: str) -> tuple:
    """Factor 6: Open Interest confirmation.

    Uses Coinalyze OI data to confirm or warn against the trade direction.
    Unlike other factors, this can return -1 (warning), which reduces the total
    confluence score. This is intentional: OI divergence is a strong counter-signal.

    Score +1 if OI confirms direction (e.g., rising price + rising OI for longs).
    Score -1 if OI warns against direction (e.g., rising price + falling OI for longs).
    Score 0 if data unavailable or neutral.
    """
    try:
        from .open_interest import get_oi_signal
        oi = get_oi_signal(symbol, direction)
        score = oi.get('confluence_score', 0)
        detail = oi.get('interpretation', 'no data')
        return score, detail
    except Exception as e:
        logger.debug("OI scoring failed: %s", e)
        return 0, f"error: {e}"


def _score_vwap(symbol: str, direction: str) -> tuple:
    """Factor 8: VWAP alignment.

    Score 1 if trade direction aligns with price position relative to VWAP:
    - BUY signal + price ABOVE VWAP -> +1 (buying with intraday bullish bias)
    - SELL signal + price BELOW VWAP -> +1 (selling with intraday bearish bias)
    - Otherwise -> 0 (trading against intraday VWAP bias)

    VWAP resets at 00:00 UTC each day (crypto is 24h).
    """
    try:
        from .vwap import get_vwap_bias
        vwap_data = get_vwap_bias(symbol)
        vwap = vwap_data.get('vwap', 0)
        price = vwap_data.get('price', 0)
        bias = vwap_data.get('bias', 'AT')
        distance_pct = vwap_data.get('distance_pct', 0)

        if vwap <= 0 or price <= 0:
            return 0, "no VWAP data"

        is_buy = direction.upper() == 'BUY'

        if is_buy and bias == 'ABOVE':
            return 1, f"price ABOVE VWAP ({distance_pct:+.3%}), aligned with BUY"
        elif not is_buy and bias == 'BELOW':
            return 1, f"price BELOW VWAP ({distance_pct:+.3%}), aligned with SELL"
        elif bias == 'AT':
            return 0, f"price AT VWAP ({distance_pct:+.3%}), neutral"
        else:
            return 0, f"price {bias} VWAP ({distance_pct:+.3%}), misaligned with {direction}"
    except Exception as e:
        logger.debug("VWAP scoring failed: %s", e)
        return 0, f"error: {e}"


# ── Helper indicators (self-contained) ────────────────────

def _calculate_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI from a pandas Series of close prices."""
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))
