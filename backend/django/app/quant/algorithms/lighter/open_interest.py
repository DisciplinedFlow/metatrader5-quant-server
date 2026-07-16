"""
Open Interest tracking via Coinalyze API (free, 40 req/min).

OI signals:
- Rising price + rising OI = strong trend confirmation
- Rising price + falling OI = distribution (potential reversal)
- Falling price + rising OI = fresh shorts being built
- Falling price + falling OI = capitulation (potential bottom)

Returns a signal that confirms or warns against the current trade direction.
"""
import logging

import requests
from django.core.cache import cache

logger = logging.getLogger('app.lighter')

# ── Coinalyze API ────────────────────────────────────────
COINALYZE_BASE_URL = 'https://api.coinalyze.net/v1'
COINALYZE_TIMEOUT = 10  # seconds

# ── Cache settings ───────────────────────────────────────
OI_CACHE_TTL = 300  # 5 minutes
OI_CACHE_PREFIX = 'lighter:oi:'

# ── Lighter symbol -> Coinalyze symbol mapping ───────────
# Coinalyze uses '.6' suffix for aggregate OI across all exchanges.
# Only crypto perpetuals are available.
SYMBOL_TO_COINALYZE = {
    'BTC': 'BTCUSD.6',
    'ETH': 'ETHUSD.6',
    'SOL': 'SOLUSD.6',
    'DOGE': 'DOGEUSD.6',
    'XRP': 'XRPUSD.6',
    'LINK': 'LINKUSD.6',
    'AVAX': 'AVAXUSD.6',
    'NEAR': 'NEARUSD.6',
    'DOT': 'DOTUSD.6',
    'TON': 'TONUSD.6',
    'SUI': 'SUIUSD.6',
    'BNB': 'BNBUSD.6',
    'AAVE': 'AAVEUSD.6',
    'ADA': 'ADAUSD.6',
    'ARB': 'ARBUSD.6',
    'OP': 'OPUSD.6',
}

# Symbols that should skip OI analysis entirely (not available on Coinalyze)
SKIP_SYMBOLS = {
    'XAU', 'XAG', 'PAXG', 'WTI',
    'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'USDCAD', 'AUDUSD', 'NZDUSD',
    'TSLA', 'NVDA', 'AAPL', 'AMZN', 'MSFT', 'GOOGL', 'META',
    'SPY', 'QQQ',
    'HYPE',  # Too new, may not be on Coinalyze yet
}

# OI change thresholds for signal generation
OI_CHANGE_SIGNIFICANT = 3.0   # 3% OI change in 4h is significant
OI_CHANGE_STRONG = 7.0        # 7% OI change in 4h is very strong
PRICE_CHANGE_THRESHOLD = 0.5  # 0.5% price change to determine direction


def get_oi_signal(symbol: str, direction: str) -> dict:
    """Get open interest signal for a Lighter trading symbol.

    Args:
        symbol: Trading pair (e.g. 'BTC', 'ETH', 'SOL')
        direction: 'BUY' or 'SELL' -- the intended trade direction

    Returns dict with:
        signal: 'CONFIRM', 'WARN', or 'NEUTRAL'
        oi_change_pct: % change in OI over last 4 hours
        price_direction: 'UP' or 'DOWN'
        interpretation: human-readable explanation string
        confluence_score: +1 (confirm), -1 (warn), or 0 (neutral)
    """
    # Check cache first
    cache_key = f'{OI_CACHE_PREFIX}{symbol}'
    cached = cache.get(cache_key)
    if cached is not None:
        # Re-evaluate signal direction since cached data may be from different direction
        return _evaluate_signal(
            cached['oi_change_pct'],
            cached['price_direction'],
            direction,
        )

    # Skip non-crypto symbols
    if symbol in SKIP_SYMBOLS:
        return _neutral_result('non_crypto_symbol')

    coinalyze_sym = SYMBOL_TO_COINALYZE.get(symbol)
    if not coinalyze_sym:
        return _neutral_result('unknown_symbol')

    # Fetch OI data from Coinalyze
    oi_data = _fetch_oi_history(coinalyze_sym)
    if oi_data is None:
        return _neutral_result('api_unavailable')

    oi_change_pct = oi_data['oi_change_pct']
    price_direction = oi_data['price_direction']

    # Cache the raw OI data (direction-independent)
    cache.set(cache_key, {
        'oi_change_pct': oi_change_pct,
        'price_direction': price_direction,
    }, timeout=OI_CACHE_TTL)

    result = _evaluate_signal(oi_change_pct, price_direction, direction)

    logger.debug(
        "OI signal %s %s: %s (OI %+.1f%%, price %s) -- %s",
        symbol, direction, result['signal'], oi_change_pct,
        price_direction, result['interpretation'],
    )
    return result


def _neutral_result(reason: str = 'default') -> dict:
    """Neutral result when OI data is unavailable."""
    return {
        'signal': 'NEUTRAL',
        'oi_change_pct': 0.0,
        'price_direction': 'FLAT',
        'interpretation': f'OI data unavailable ({reason})',
        'confluence_score': 0,
    }


def _fetch_oi_history(coinalyze_symbol: str) -> dict | None:
    """Fetch OI history from Coinalyze API.

    Returns dict with oi_change_pct and price_direction, or None on failure.

    Uses 4h interval with 2 data points to calculate change.
    """
    try:
        # ── Open Interest history ──
        oi_url = f'{COINALYZE_BASE_URL}/open-interest-history'
        oi_params = {
            'symbols': coinalyze_symbol,
            'interval': '4hour',
            'limit': 2,
        }
        oi_resp = requests.get(oi_url, params=oi_params, timeout=COINALYZE_TIMEOUT)
        oi_resp.raise_for_status()
        oi_json = oi_resp.json()

        if not oi_json or not isinstance(oi_json, list) or len(oi_json) == 0:
            logger.debug("OI: empty response for %s", coinalyze_symbol)
            return None

        # Coinalyze returns [{symbol, history: [{t, o, h, l, c}, ...]}]
        oi_entry = oi_json[0]
        history = oi_entry.get('history', [])
        if len(history) < 2:
            logger.debug("OI: insufficient history for %s (%d points)", coinalyze_symbol, len(history))
            return None

        # OI change: compare latest close to previous close
        prev_oi = float(history[-2].get('c', 0))
        curr_oi = float(history[-1].get('c', 0))

        if prev_oi <= 0:
            return None

        oi_change_pct = ((curr_oi - prev_oi) / prev_oi) * 100.0

        # ── Price direction from the same candles ──
        # Coinalyze OI candles don't have price -- we need to infer from our own data
        # or use a separate endpoint. For now, use the OI open/close to determine
        # if this was a bullish or bearish OI period, and complement with price data.
        price_direction = _get_price_direction(coinalyze_symbol)

        return {
            'oi_change_pct': round(oi_change_pct, 2),
            'price_direction': price_direction,
        }

    except requests.exceptions.Timeout:
        logger.debug("OI: Coinalyze timeout for %s", coinalyze_symbol)
        return None
    except requests.exceptions.HTTPError as e:
        logger.debug("OI: Coinalyze HTTP error for %s: %s", coinalyze_symbol, e)
        return None
    except requests.exceptions.ConnectionError:
        logger.debug("OI: Coinalyze connection error for %s", coinalyze_symbol)
        return None
    except Exception as e:
        logger.debug("OI: unexpected error fetching %s: %s", coinalyze_symbol, e)
        return None


def _get_price_direction(coinalyze_symbol: str) -> str:
    """Determine price direction over the last 4 hours.

    First tries Coinalyze OHLCV endpoint, then falls back to Lighter candle data.
    """
    # Try Coinalyze OHLCV first
    try:
        ohlcv_url = f'{COINALYZE_BASE_URL}/ohlcv-history'
        ohlcv_params = {
            'symbols': coinalyze_symbol,
            'interval': '4hour',
            'limit': 2,
        }
        resp = requests.get(ohlcv_url, params=ohlcv_params, timeout=COINALYZE_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        if data and isinstance(data, list) and len(data) > 0:
            history = data[0].get('history', [])
            if len(history) >= 2:
                prev_close = float(history[-2].get('c', 0))
                curr_close = float(history[-1].get('c', 0))
                if prev_close > 0:
                    pct_change = ((curr_close - prev_close) / prev_close) * 100.0
                    if pct_change > PRICE_CHANGE_THRESHOLD:
                        return 'UP'
                    elif pct_change < -PRICE_CHANGE_THRESHOLD:
                        return 'DOWN'
                    return 'FLAT'
    except Exception:
        pass

    # Fall back to Lighter candle data
    try:
        # Reverse-map Coinalyze symbol to Lighter symbol
        lighter_sym = None
        for sym, csym in SYMBOL_TO_COINALYZE.items():
            if csym == coinalyze_symbol:
                lighter_sym = sym
                break

        if lighter_sym:
            from .client import get_candles
            candles = get_candles(lighter_sym, resolution='1h', count_back=5)
            if candles and len(candles) >= 4:
                old_close = float(candles[-4]['c'])
                new_close = float(candles[-1]['c'])
                if old_close > 0:
                    pct = ((new_close - old_close) / old_close) * 100.0
                    if pct > PRICE_CHANGE_THRESHOLD:
                        return 'UP'
                    elif pct < -PRICE_CHANGE_THRESHOLD:
                        return 'DOWN'
    except Exception:
        pass

    return 'FLAT'


def _evaluate_signal(oi_change_pct: float, price_direction: str, direction: str) -> dict:
    """Evaluate OI + price data against intended trade direction.

    OI interpretation matrix:
    ┌────────────┬──────────────┬──────────────────────────────────────┐
    │ Price      │ OI           │ Meaning                              │
    ├────────────┼──────────────┼──────────────────────────────────────┤
    │ UP         │ RISING       │ Strong trend, new longs entering     │
    │ UP         │ FALLING      │ Distribution, shorts closing (weak)  │
    │ DOWN       │ RISING       │ Fresh shorts, bearish pressure       │
    │ DOWN       │ FALLING      │ Capitulation, longs giving up        │
    │ FLAT       │ any          │ Neutral, no clear signal             │
    └────────────┴──────────────┴──────────────────────────────────────┘
    """
    is_buy = direction.upper() == 'BUY'
    oi_rising = oi_change_pct > OI_CHANGE_SIGNIFICANT
    oi_falling = oi_change_pct < -OI_CHANGE_SIGNIFICANT
    oi_strong = abs(oi_change_pct) > OI_CHANGE_STRONG

    # Flat price or insignificant OI change -> neutral
    if price_direction == 'FLAT' or (not oi_rising and not oi_falling):
        return {
            'signal': 'NEUTRAL',
            'oi_change_pct': oi_change_pct,
            'price_direction': price_direction,
            'interpretation': f'OI change {oi_change_pct:+.1f}% with {price_direction} price -- no clear signal',
            'confluence_score': 0,
        }

    # ── Rising price + rising OI = strong uptrend ──
    if price_direction == 'UP' and oi_rising:
        if is_buy:
            strength = 'strongly ' if oi_strong else ''
            return {
                'signal': 'CONFIRM',
                'oi_change_pct': oi_change_pct,
                'price_direction': price_direction,
                'interpretation': f'Price UP + OI rising {oi_change_pct:+.1f}% -- {strength}confirms long entry (new longs entering)',
                'confluence_score': 1,
            }
        else:
            return {
                'signal': 'WARN',
                'oi_change_pct': oi_change_pct,
                'price_direction': price_direction,
                'interpretation': f'Price UP + OI rising {oi_change_pct:+.1f}% -- warns against short (uptrend strengthening)',
                'confluence_score': -1,
            }

    # ── Rising price + falling OI = distribution (potential reversal) ──
    if price_direction == 'UP' and oi_falling:
        if is_buy:
            return {
                'signal': 'WARN',
                'oi_change_pct': oi_change_pct,
                'price_direction': price_direction,
                'interpretation': f'Price UP + OI falling {oi_change_pct:+.1f}% -- distribution, shorts closing not new longs',
                'confluence_score': -1,
            }
        else:
            return {
                'signal': 'NEUTRAL',
                'oi_change_pct': oi_change_pct,
                'price_direction': price_direction,
                'interpretation': f'Price UP + OI falling {oi_change_pct:+.1f}% -- potential reversal, short may be early',
                'confluence_score': 0,
            }

    # ── Falling price + rising OI = fresh shorts being built ──
    if price_direction == 'DOWN' and oi_rising:
        if not is_buy:
            strength = 'strongly ' if oi_strong else ''
            return {
                'signal': 'CONFIRM',
                'oi_change_pct': oi_change_pct,
                'price_direction': price_direction,
                'interpretation': f'Price DOWN + OI rising {oi_change_pct:+.1f}% -- {strength}confirms short (fresh shorts building)',
                'confluence_score': 1,
            }
        else:
            return {
                'signal': 'WARN',
                'oi_change_pct': oi_change_pct,
                'price_direction': price_direction,
                'interpretation': f'Price DOWN + OI rising {oi_change_pct:+.1f}% -- warns against long (bearish pressure)',
                'confluence_score': -1,
            }

    # ── Falling price + falling OI = capitulation (potential bottom) ──
    if price_direction == 'DOWN' and oi_falling:
        if is_buy:
            return {
                'signal': 'NEUTRAL',
                'oi_change_pct': oi_change_pct,
                'price_direction': price_direction,
                'interpretation': f'Price DOWN + OI falling {oi_change_pct:+.1f}% -- capitulation, long may be early',
                'confluence_score': 0,
            }
        else:
            return {
                'signal': 'WARN',
                'oi_change_pct': oi_change_pct,
                'price_direction': price_direction,
                'interpretation': f'Price DOWN + OI falling {oi_change_pct:+.1f}% -- capitulation (longs giving up), short may be late',
                'confluence_score': -1,
            }

    # Fallback (shouldn't reach here)
    return _neutral_result('unhandled_case')


def get_funding_rate(symbol: str) -> dict | None:
    """Get current funding rate from Coinalyze.

    Bonus utility -- can be used by confluence scorer or other modules.
    Returns dict with funding_rate and predicted_rate, or None.
    """
    coinalyze_sym = SYMBOL_TO_COINALYZE.get(symbol)
    if not coinalyze_sym:
        return None

    cache_key = f'{OI_CACHE_PREFIX}funding:{symbol}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        url = f'{COINALYZE_BASE_URL}/current-funding-rate'
        params = {'symbols': coinalyze_sym}
        resp = requests.get(url, params=params, timeout=COINALYZE_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        if data and isinstance(data, list) and len(data) > 0:
            entry = data[0]
            result = {
                'funding_rate': float(entry.get('value', 0)),
                'predicted_rate': float(entry.get('predicted', 0)),
            }
            cache.set(cache_key, result, timeout=OI_CACHE_TTL)
            return result

    except Exception as e:
        logger.debug("OI: funding rate error for %s: %s", symbol, e)

    return None
