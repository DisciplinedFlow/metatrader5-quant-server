"""
Redis tick consumer for real-time CVD signal detection.

Subscribes to MT5 tick channels via Redis pub/sub, processes ticks through
the RealtimeCVD engine, and caches detected signals in Django's Redis cache
for the entry algorithm to pick up.

Can be run as:
  1. Django management command: python manage.py tick_consumer
  2. Standalone: python -m app.quant.tick_consumer
"""

import json
import logging
import os
import signal
import sys
import time

import redis

logger = logging.getLogger(__name__)

# Same 14 symbols as the MT5 tick streamer
DEFAULT_SYMBOLS = [
    # Forex majors
    'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'NZDUSD',
    'USDCAD', 'USDCHF', 'EURGBP', 'USDCNH', 'USDSEK',
    # Metals
    'XAUUSD', 'XAUEUR', 'XAUAUD', 'XAUJPY', 'XAGUSD',
    # Energy
    'USOUSD', 'UKOUSDft', 'NG-C',
    # US stocks
    'AMD', 'MSFT',
]

# Stats logging interval (seconds)
STATS_LOG_INTERVAL = 10

# Reconnect backoff parameters
RECONNECT_BASE_DELAY = 1.0   # seconds
RECONNECT_MAX_DELAY = 30.0   # seconds


class TickConsumer:
    """
    Subscribes to Redis tick channels and processes ticks through the
    real-time CVD engine. Caches detected signals in Django's Redis cache
    (db/1) for downstream consumption by the entry algorithm.
    """

    def __init__(self, redis_url='redis://redis:6379/2', symbols=None):
        """
        Args:
            redis_url: Redis URL for tick pub/sub stream (db/2).
            symbols: List of symbols to subscribe to. Defaults to 14 MT5 pairs.
        """
        self.symbols = symbols or list(DEFAULT_SYMBOLS)
        self.redis_url = redis_url
        self._running = False

        # Lazy imports — avoid importing Django/Celery at module level
        # so the module can be parsed without Django configured
        self._cvd_engine  = None
        self._mtf_engines = {}   # symbol -> MTFEngine
        self._redis_sub   = None  # pub/sub connection (db/2)

        # Stats
        self._total_ticks = 0
        self._total_signals = 0
        self._last_stats_time = 0

    def _ensure_engine(self):
        """Lazy-init the CVD engine and MTF engines."""
        if self._cvd_engine is None:
            from app.quant.indicators.cvd_realtime import RealtimeCVD
            self._cvd_engine = RealtimeCVD(window_size=300)

    def _get_mtf_engine(self, symbol: str):
        """Return (or create) the MTFEngine for a symbol."""
        if symbol not in self._mtf_engines:
            from app.quant.engine.mtf_engine import MTFEngine
            self._mtf_engines[symbol] = MTFEngine(symbol)
        return self._mtf_engines[symbol]

    def _connect_redis(self):
        """Create or reconnect the Redis pub/sub connection."""
        if self._redis_sub is not None:
            try:
                self._redis_sub.close()
            except Exception:
                pass

        r = redis.Redis.from_url(self.redis_url, decode_responses=True)
        r.ping()  # verify connectivity
        self._redis_sub = r
        logger.info("Connected to Redis tick stream at %s", self.redis_url)
        return r

    def start(self):
        """
        Blocking method that runs the consumer loop.

        Subscribes to ticks:* channels, processes each tick through the CVD
        engine, and caches signals in Django's cache (db/1).
        """
        self._ensure_engine()
        self._running = True
        self._last_stats_time = time.time()

        reconnect_delay = RECONNECT_BASE_DELAY

        while self._running:
            try:
                r = self._connect_redis()
                pubsub = r.pubsub()

                # Subscribe to all tick channels via pattern
                pubsub.psubscribe('ticks:*')
                logger.info(
                    "Subscribed to ticks:* — listening for %d symbols",
                    len(self.symbols),
                )

                # Reset backoff on successful connection
                reconnect_delay = RECONNECT_BASE_DELAY

                for message in pubsub.listen():
                    if not self._running:
                        break

                    if message['type'] != 'pmessage':
                        continue

                    try:
                        self._handle_message(message)
                    except Exception:
                        logger.exception("Error processing tick message")

                    # Periodic stats logging
                    now = time.time()
                    if now - self._last_stats_time >= STATS_LOG_INTERVAL:
                        self._log_stats()
                        self._last_stats_time = now

            except redis.ConnectionError as e:
                logger.warning(
                    "Redis connection lost: %s — reconnecting in %.1fs",
                    e, reconnect_delay,
                )
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, RECONNECT_MAX_DELAY)

            except Exception:
                if self._running:
                    logger.exception(
                        "Unexpected error in tick consumer — reconnecting in %.1fs",
                        reconnect_delay,
                    )
                    time.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, RECONNECT_MAX_DELAY)

        logger.info("Tick consumer stopped.")

    def _handle_message(self, message):
        """Process a single pub/sub message."""
        channel = message.get('channel', '')
        data = message.get('data', '')

        # Extract symbol from channel: "ticks:EURUSD" -> "EURUSD"
        if ':' not in channel:
            return
        symbol = channel.split(':', 1)[1]

        # Parse tick JSON
        try:
            tick = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return

        self._total_ticks += 1

        # Process through CVD engine (caches realtime_cvd:{symbol} for MTF use)
        signal_str = self._cvd_engine.process_tick(symbol, tick)
        if signal_str is not None:
            self._total_signals += 1
            self._emit_signal(symbol, signal_str, tick)

        # Process through MTF engine (bar builder + indicators + alignment check)
        mtf_signal = self._get_mtf_engine(symbol).on_tick(tick)
        if mtf_signal is not None:
            self._emit_mtf_signal(symbol, mtf_signal)

    def _emit_signal(self, symbol, signal_str, tick):
        """Cache a detected signal and dispatch Celery task for fast entry."""
        from app.quant.indicators.cvd_realtime import _signal_direction

        direction = _signal_direction(signal_str)
        state = self._cvd_engine._state.get(symbol, {})

        signal_data = {
            'signal': signal_str,
            'direction': direction,
            'cvd_value': state.get('cvd', 0.0),
            'timestamp': tick.get('t', 0),
            'tick_count': self._cvd_engine._tick_counts.get(symbol, 0),
        }

        # Cache in Django Redis (db/1) with 30s TTL
        try:
            from django.core.cache import cache
            cache_key = f'realtime_cvd:{symbol}'
            cache.set(cache_key, signal_data, timeout=30)
        except Exception:
            logger.exception("Failed to cache signal for %s", symbol)

        logger.info(
            "REALTIME CVD: %s %s direction=%s cvd=%.1f ticks=%d",
            symbol, signal_str, direction,
            signal_data['cvd_value'], signal_data['tick_count'],
        )

        # Dispatch Celery task for immediate entry evaluation (rate-limited)
        try:
            from django.core.cache import cache
            dedup_key = 'rt_entry_dispatch_lock'
            if cache.add(dedup_key, 1, timeout=10):  # Only dispatch once per 10 seconds
                from app.quant.tasks import run_forex_entry
                run_forex_entry.delay()
                logger.info("Dispatched forex entry from RT CVD signal")
            else:
                logger.debug("Entry algorithm dispatch skipped (rate limited)")
        except Exception:
            logger.exception("Failed to dispatch entry algorithm task")

    def _emit_mtf_signal(self, symbol: str, signal: dict):
        """Cache an MTF alignment signal and dispatch the forex entry task."""
        try:
            from django.core.cache import cache
            cache.set(f'mtf_signal:{symbol}', signal, timeout=60)
        except Exception:
            logger.exception('Failed to cache MTF signal for %s', symbol)

        logger.info(
            'MTF SIGNAL: %s %s setup=%s reason=%s atr=%.5f',
            symbol, signal['direction'].upper(),
            signal['setup'], signal['reason'], signal['atr'],
        )

        try:
            from django.core.cache import cache
            dedup_key = f'mtf_dispatch:{symbol}'
            if cache.add(dedup_key, 1, timeout=30):
                from app.quant.tasks import run_forex_entry
                run_forex_entry.delay()
        except Exception:
            logger.exception('Failed to dispatch MTF entry for %s', symbol)

    def _log_stats(self):
        """Log periodic stats summary."""
        stats = self._cvd_engine.get_stats()
        symbol_summary = ', '.join(
            f"{s}={d['tick_count']}"
            for s, d in sorted(stats.items())
        )
        logger.info(
            "TICK CONSUMER STATS: total_ticks=%d signals=%d | %s",
            self._total_ticks, self._total_signals, symbol_summary,
        )

    def stop(self):
        """Signal the consumer to stop and clean up connections."""
        self._running = False
        if self._redis_sub is not None:
            try:
                self._redis_sub.close()
            except Exception:
                pass
            self._redis_sub = None
        logger.info("Tick consumer stop requested.")


def start_tick_consumer(redis_url='redis://redis:6379/2'):
    """
    Convenience function to create and start a TickConsumer.

    Sets up Django if not already configured and installs signal handlers
    for graceful shutdown on SIGINT/SIGTERM.
    """
    # Ensure Django is configured
    if not os.environ.get('DJANGO_SETTINGS_MODULE'):
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app.settings')

    try:
        import django
        django.setup()
    except Exception:
        pass  # Already configured

    consumer = TickConsumer(redis_url=redis_url)

    def _shutdown(signum, frame):
        logger.info("Received signal %d — shutting down tick consumer", signum)
        consumer.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("Starting real-time tick consumer (redis=%s)...", redis_url)
    consumer.start()


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s %(levelname)s %(message)s',
    )
    start_tick_consumer()
