"""
Real-time tick-based CVD (Cumulative Volume Delta) engine.

Processes individual ticks from MT5 to compute CVD with ~1 second latency,
compared to ~15 minutes for bar-based CVD. Uses tick direction classification:
- Bid uptick (bid > prev_bid) -> buying pressure (positive delta)
- Bid downtick (bid < prev_bid) -> selling pressure (negative delta)
- TICK_FLAG_BUY/SELL flags used when available

Maintains rolling CVD windows for divergence detection against price swings.
"""

import time
import logging
from collections import deque

logger = logging.getLogger(__name__)

# MT5 tick flags
TICK_FLAG_BID = 2
TICK_FLAG_ASK = 4
TICK_FLAG_LAST = 8
TICK_FLAG_BUY = 32
TICK_FLAG_SELL = 64

# Divergence check interval (every N ticks)
DIVERGENCE_CHECK_INTERVAL = 30

# Minimum data points for divergence detection
MIN_HISTORY_POINTS = 100

# Signal cooldown: same signal suppressed for N seconds
SIGNAL_COOLDOWN_MS = 60_000  # 60 seconds in milliseconds

# Exhaustion momentum window
EXHAUSTION_WINDOW = 50


class RealtimeCVD:
    """
    Real-time CVD computation engine.

    Processes individual ticks and maintains running CVD state per symbol.
    Detects divergence between price swings and CVD swings in real time.
    """

    def __init__(self, window_size=300):
        """
        Args:
            window_size: max ticks to keep in rolling buffer per symbol.
        """
        self.window_size = window_size
        # Per-symbol state: symbol -> dict of state vars
        self._state = {}
        # Global tick counter for periodic divergence checks
        self._tick_counts = {}

    def _init_symbol(self, symbol):
        """Initialize state for a new symbol."""
        self._state[symbol] = {
            'ticks': deque(maxlen=self.window_size),
            'prev_bid': None,
            'prev_ask': None,
            'cvd': 0.0,
            'cvd_history': deque(maxlen=self.window_size),
            'price_history': deque(maxlen=self.window_size),
            'last_signal': None,
            'last_signal_time': 0,
        }
        self._tick_counts[symbol] = 0

    def process_tick(self, symbol, tick):
        """
        Process a single tick and return a divergence signal if detected.

        Args:
            symbol: e.g. 'EURUSD'
            tick: dict with keys: t (time_msc), b (bid), a (ask), l (last),
                  v (volume), f (flags)

        Returns:
            Signal string if divergence detected, None otherwise.
        """
        if symbol not in self._state:
            self._init_symbol(symbol)

        state = self._state[symbol]
        self._tick_counts[symbol] += 1

        bid = tick.get('b', 0.0)
        ask = tick.get('a', 0.0)
        volume = tick.get('v', 0)
        flags = tick.get('f', 0)
        time_msc = tick.get('t', 0)

        # --- Classify tick direction ---
        delta = 0.0

        if flags & TICK_FLAG_BUY:
            delta = 1.0
        elif flags & TICK_FLAG_SELL:
            delta = -1.0
        elif state['prev_bid'] is not None:
            if bid > state['prev_bid']:
                delta = 1.0  # uptick rule
            elif bid < state['prev_bid']:
                delta = -1.0  # downtick rule
            # else: no change, delta stays 0

        # Weight delta by volume if available
        if volume and volume > 0:
            delta *= max(1, volume)

        # Update running CVD
        state['cvd'] += delta

        # Update previous prices
        state['prev_bid'] = bid
        state['prev_ask'] = ask

        # Append to history buffers
        mid_price = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else bid or ask
        state['ticks'].append(tick)
        state['cvd_history'].append((time_msc, state['cvd']))
        state['price_history'].append((time_msc, mid_price))

        # Check for divergence periodically (not every tick, to save CPU)
        signal = None
        if self._tick_counts[symbol] % DIVERGENCE_CHECK_INTERVAL == 0:
            signal = self._check_divergence(symbol)

        if signal is not None:
            # Only return NEW signals (different type or cooldown expired)
            if (signal != state['last_signal']
                    or (time_msc - state['last_signal_time']) > SIGNAL_COOLDOWN_MS):
                state['last_signal'] = signal
                state['last_signal_time'] = time_msc
                return signal

        return None

    def _check_divergence(self, symbol):
        """
        Check for price-CVD divergence using segment-based swing detection.

        Returns:
            Signal string or None.
        """
        state = self._state[symbol]
        cvd_hist = state['cvd_history']
        price_hist = state['price_history']

        if len(cvd_hist) < MIN_HISTORY_POINTS or len(price_hist) < MIN_HISTORY_POINTS:
            return None

        # Convert to lists for segment analysis
        cvd_values = [v for _, v in cvd_hist]
        price_values = [v for _, v in price_hist]
        n = len(cvd_values)

        # --- Segment-based swing detection ---
        # Split the window into 4 segments, find max/min in each
        seg_size = n // 4
        if seg_size < 5:
            return None

        segments = []
        for i in range(4):
            start = i * seg_size
            end = start + seg_size if i < 3 else n
            seg_cvd = cvd_values[start:end]
            seg_price = price_values[start:end]
            segments.append({
                'cvd_max': max(seg_cvd),
                'cvd_min': min(seg_cvd),
                'price_max': max(seg_price),
                'price_min': min(seg_price),
            })

        # Compare the last two segments for swing highs/lows
        seg_prev = segments[2]  # third segment
        seg_last = segments[3]  # fourth (most recent) segment

        # --- Standard divergence patterns ---

        # bullish_lack_of_participants: price lower low, CVD higher low
        if (seg_last['price_min'] < seg_prev['price_min']
                and seg_last['cvd_min'] > seg_prev['cvd_min']):
            return 'bullish_lack_of_participants'

        # bearish_lack_of_participants: price higher high, CVD lower high
        if (seg_last['price_max'] > seg_prev['price_max']
                and seg_last['cvd_max'] < seg_prev['cvd_max']):
            return 'bearish_lack_of_participants'

        # bullish_absorption: CVD lower low, price higher low
        if (seg_last['cvd_min'] < seg_prev['cvd_min']
                and seg_last['price_min'] >= seg_prev['price_min']):
            return 'bullish_absorption'

        # bearish_absorption: CVD higher high, price lower high
        if (seg_last['cvd_max'] > seg_prev['cvd_max']
                and seg_last['price_max'] <= seg_prev['price_max']):
            return 'bearish_absorption'

        # --- Early exhaustion patterns ---
        # CVD momentum (rate of change over last EXHAUSTION_WINDOW ticks)
        # diverging from price direction
        if n >= EXHAUSTION_WINDOW:
            recent_cvd = cvd_values[-EXHAUSTION_WINDOW:]
            recent_price = price_values[-EXHAUSTION_WINDOW:]

            cvd_roc = recent_cvd[-1] - recent_cvd[0]
            price_roc = recent_price[-1] - recent_price[0]

            # Normalize price_roc relative to price level to avoid scale issues
            avg_price = sum(recent_price) / len(recent_price)
            if avg_price > 0:
                price_roc_pct = price_roc / avg_price
            else:
                price_roc_pct = 0.0

            # bullish_exhaustion_early: price falling but CVD turning up
            if price_roc_pct < -0.0005 and cvd_roc > 0:
                return 'bullish_exhaustion_early'

            # bearish_exhaustion_early: price rising but CVD turning down
            if price_roc_pct > 0.0005 and cvd_roc < 0:
                return 'bearish_exhaustion_early'

        return None

    def get_latest_signal(self, symbol):
        """
        Get the most recent signal for a symbol if it's still fresh.

        Returns:
            dict with signal, direction, cvd_value, timestamp — or None if
            no recent signal (>30 seconds old).
        """
        if symbol not in self._state:
            return None

        state = self._state[symbol]
        if state['last_signal'] is None:
            return None

        # Check staleness: 30 seconds = 30_000 ms
        now_msc = int(time.time() * 1000)
        if (now_msc - state['last_signal_time']) > 30_000:
            return None

        signal = state['last_signal']
        direction = _signal_direction(signal)

        return {
            'signal': signal,
            'direction': direction,
            'cvd_value': state['cvd'],
            'timestamp': state['last_signal_time'],
        }

    def get_stats(self):
        """
        Return per-symbol statistics.

        Returns:
            dict: symbol -> {tick_count, cvd_value, last_signal}
        """
        stats = {}
        for symbol in self._state:
            state = self._state[symbol]
            stats[symbol] = {
                'tick_count': self._tick_counts.get(symbol, 0),
                'cvd_value': state['cvd'],
                'last_signal': state['last_signal'],
            }
        return stats


def _signal_direction(signal):
    """Map signal string to BUY/SELL direction."""
    if signal is None:
        return None
    if 'bullish' in signal:
        return 'BUY'
    if 'bearish' in signal:
        return 'SELL'
    return None
