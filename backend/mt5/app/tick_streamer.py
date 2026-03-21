"""
Real-time tick streamer via Redis pub/sub.

Polls the MT5 Flask API /fetch_ticks endpoint (running on Wine Python)
from system Python, and publishes ticks to Redis for downstream consumers.

Runs as a standalone process inside the MT5 container:
    python3 /app/tick_streamer.py
"""

import json
import logging
import signal
import sys
import time
from datetime import datetime

import redis
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
)
logger = logging.getLogger('tick_streamer')

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

FLASK_API_URL = 'http://localhost:5001'
POLL_INTERVAL = 1.0  # seconds between full cycles


class TickStreamer:
    """Polls MT5 Flask API for ticks and publishes them to Redis pub/sub."""

    def __init__(self, redis_url='redis://redis:6379/2', symbols=None,
                 flask_url=FLASK_API_URL):
        self.symbols = symbols or list(DEFAULT_SYMBOLS)
        self.redis_url = redis_url
        self.flask_url = flask_url
        self._running = False

        # Per-symbol tracking: last seen time_msc
        self._last_time_msc = {}

        # Stats
        self.ticks_published = 0
        self.errors = 0
        self.last_cycle_duration = 0.0

        # Connections
        self._redis = None
        self._session = requests.Session()

    def start(self):
        """Blocking loop — polls ticks and publishes to Redis."""
        self._connect_redis()
        self._running = True
        stats_timer = time.monotonic()

        logger.info(
            "Tick streamer started — %d symbols, redis=%s, flask=%s",
            len(self.symbols), self.redis_url, self.flask_url,
        )

        while self._running:
            cycle_start = time.monotonic()

            try:
                self._poll_all_symbols()
            except Exception as e:
                logger.error("Batch tick poll error: %s", e)
                self.errors += 1

            self.last_cycle_duration = time.monotonic() - cycle_start

            # Periodic stats (every 60s)
            if time.monotonic() - stats_timer >= 60:
                logger.info(
                    "Tick streamer stats — published=%d  errors=%d  "
                    "cycle=%.3fs  symbols=%d",
                    self.ticks_published, self.errors,
                    self.last_cycle_duration, len(self.symbols),
                )
                stats_timer = time.monotonic()

            # Sleep until next cycle
            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0, POLL_INTERVAL - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

        logger.info("Tick streamer loop exiting")

    def stop(self):
        """Signal the loop to stop."""
        self._running = False
        logger.info("Tick streamer stop requested")

    def _connect_redis(self):
        """Create or re-create the Redis connection."""
        try:
            self._redis = redis.Redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            self._redis.ping()
            logger.info("Connected to Redis at %s", self.redis_url)
        except Exception as e:
            logger.error("Redis connection failed: %s", e)
            self._redis = None
            self.errors += 1

    def _poll_all_symbols(self):
        """Fetch ticks for all symbols in one batch POST and publish to Redis."""
        try:
            resp = self._session.post(
                f'{self.flask_url}/fetch_ticks_batch',
                json={'symbols': self.symbols, 'count': 500, 'seconds_back': 3},
                timeout=10.0,
            )
            resp.raise_for_status()
            batch = resp.json()
        except requests.RequestException:
            # Flask not ready yet or network issue — silently skip
            return
        except Exception as e:
            logger.debug("Batch fetch ticks error: %s", e)
            return

        for symbol, ticks in batch.items():
            self._process_symbol_ticks(symbol, ticks)

    def _process_symbol_ticks(self, symbol, ticks):
        """Filter and publish ticks for a symbol to Redis."""
        if not ticks:
            return

        # Filter out already-seen ticks
        last_msc = self._last_time_msc.get(symbol, 0)
        new_ticks = [t for t in ticks if t.get('time_msc', 0) > last_msc]

        if not new_ticks:
            return

        # Update high-water mark
        max_msc = max(t.get('time_msc', 0) for t in new_ticks)
        self._last_time_msc[symbol] = max_msc

        # Publish each tick
        channel = f"ticks:{symbol}"
        spread_sum = 0.0

        for t in new_ticks:
            msg = {
                "t": t.get('time_msc', 0),
                "b": t.get('bid', 0.0),
                "a": t.get('ask', 0.0),
                "l": t.get('last', 0.0),
                "v": t.get('volume', 0),
                "f": t.get('flags', 0),
            }
            spread_sum += msg['a'] - msg['b']
            self._publish(channel, msg)
            self.ticks_published += 1

        # Publish summary
        count = len(new_ticks)
        last_t = new_ticks[-1]
        summary = {
            "t": max_msc,
            "b": last_t.get('bid', 0.0),
            "a": last_t.get('ask', 0.0),
            "count": count,
            "avg_spread": round(spread_sum / count, 6) if count > 0 else 0.0,
        }
        self._publish(f"tick_summary:{symbol}", summary)

    def _publish(self, channel, data):
        """Publish JSON message to Redis pub/sub."""
        if self._redis is None:
            self._connect_redis()
        if self._redis is None:
            return

        try:
            self._redis.publish(channel, json.dumps(data))
        except redis.ConnectionError:
            self.errors += 1
            self._connect_redis()
        except Exception as e:
            logger.error("Redis publish error: %s", e)
            self.errors += 1


def main():
    import os
    redis_url = os.environ.get('REDIS_URL', 'redis://redis:6379/2')
    flask_url = os.environ.get('FLASK_API_URL', FLASK_API_URL)

    streamer = TickStreamer(redis_url=redis_url, flask_url=flask_url)

    def _shutdown(signum, frame):
        logger.info("Received signal %d — shutting down", signum)
        streamer.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Wait for Flask API to be ready
    logger.info("Waiting for Flask API at %s ...", flask_url)
    for _ in range(60):
        try:
            r = requests.get(f'{flask_url}/health', timeout=2)
            if r.status_code == 200:
                logger.info("Flask API is ready")
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        logger.warning("Flask API not responding after 120s, starting anyway")

    streamer.start()


if __name__ == '__main__':
    main()
