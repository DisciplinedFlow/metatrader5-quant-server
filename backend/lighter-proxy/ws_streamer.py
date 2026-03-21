#!/usr/bin/env python3
"""
Lighter.xyz WebSocket Streamer — real-time market data to Redis.

Runs as a SEPARATE process alongside proxy.py on macOS (not in Docker — same
reason as the proxy: native Go library dependency in the lighter-sdk).

Subscribes to:
1. order_book/{market} — order book updates, calculates imbalance from top 20 levels
2. REST recent_trades poll (10s) — the SDK WsClient strips trade data from OB updates,
   so we poll the REST API as a reliable fallback for trade flow / CVD
3. market_stats/{market} — funding rate, OI, mark/index price  (TODO: when channel available)

Publishes to Redis (same pattern as MT5 tick_streamer → Redis pub/sub DB2):
- lighter:ob:{symbol}           — order book snapshot (JSON, top 20 bids/asks)
- lighter:trades:{symbol}       — recent trade flow (JSON: buy_vol, sell_vol, cvd, trades)
- lighter:stats:{symbol}        — funding, OI, mark price (JSON)
- lighter:ob_imbalance:{symbol} — bid/ask ratio (float as string)

Usage:
    cd backend/lighter-proxy
    python ws_streamer.py

Reads config from ../../.env (project root).
"""
import asyncio
import json
import logging
import os
import signal
import sys
import time
from collections import deque
from pathlib import Path

# Load .env from project root
from dotenv import load_dotenv
env_path = Path(__file__).resolve().parent.parent.parent / '.env'
load_dotenv(env_path)

import redis

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger('lighter-ws')

# ── Config ────────────────────────────────────────────────

WS_URL = os.getenv(
    'LIGHTER_WS_URL',
    'wss://mainnet.zklighter.elliot.ai/stream',
)
REDIS_URL = os.getenv('LIGHTER_WS_REDIS_URL', 'redis://localhost:6379/2')
REDIS_KEY_TTL = 60  # seconds — downstream treats data stale after this

# Markets to subscribe (symbol → market_id)
SUBSCRIBE_MARKETS = {
    'XAU': 92,
    'XAG': 93,
    'WTI': 145,
}

# Reverse map: market_id (str) → symbol
ID_TO_SYMBOL = {str(v): k for k, v in SUBSCRIBE_MARKETS.items()}

# Order book imbalance settings
OB_LEVELS = 20  # Top N bid/ask levels to evaluate
TRADE_WINDOW = 300  # seconds of trade history to keep for CVD

# Reconnection settings
RECONNECT_BASE_DELAY = 1.0
RECONNECT_MAX_DELAY = 30.0
RECONNECT_MULTIPLIER = 2.0

# Trade polling (REST fallback — WS doesn't deliver trades via SDK callback)
TRADE_POLL_INTERVAL = 10  # seconds
TRADE_POLL_LIMIT = 100    # max trades per REST call (SDK max)
LARGE_TRADE_USD = 5000.0  # $5K threshold for large trade detection

# Stats logging interval
STATS_LOG_INTERVAL = 60  # seconds


# ── Trade Accumulator ─────────────────────────────────────

class TradeAccumulator:
    """Accumulates trades per symbol for CVD and flow analysis."""

    def __init__(self, window_seconds: int = TRADE_WINDOW):
        self.window = window_seconds
        # {symbol: deque of (timestamp, price, size, is_buy, trade_id)}
        self._trades: dict[str, deque] = {}
        self._buy_volume: dict[str, float] = {}
        self._sell_volume: dict[str, float] = {}
        self._cvd: dict[str, float] = {}
        self._large_trades: dict[str, int] = {}
        # Dedup: track recently seen trade_ids to avoid double-counting
        self._seen_trade_ids: dict[str, set] = {}  # symbol -> set of trade_id

    def add_trade(self, symbol: str, price: float, size: float, is_buy: bool,
                  timestamp: float = None, trade_id: int = None):
        """Record a trade and update running totals. Deduplicates by trade_id."""
        ts = timestamp or time.time()

        if symbol not in self._trades:
            self._trades[symbol] = deque()
            self._buy_volume[symbol] = 0.0
            self._sell_volume[symbol] = 0.0
            self._cvd[symbol] = 0.0
            self._large_trades[symbol] = 0
            self._seen_trade_ids[symbol] = set()

        # Deduplicate by trade_id if provided
        if trade_id is not None:
            if trade_id in self._seen_trade_ids[symbol]:
                return
            self._seen_trade_ids[symbol].add(trade_id)

        self._trades[symbol].append((ts, price, size, is_buy, trade_id))
        usd_amount = price * size

        if is_buy:
            self._buy_volume[symbol] += usd_amount
            self._cvd[symbol] += usd_amount
        else:
            self._sell_volume[symbol] += usd_amount
            self._cvd[symbol] -= usd_amount

        # Track large trades (> $5K)
        if usd_amount >= LARGE_TRADE_USD:
            self._large_trades[symbol] += 1

        self._prune(symbol)

    def _prune(self, symbol: str):
        """Remove trades older than window, recalculating volumes."""
        cutoff = time.time() - self.window
        trades = self._trades[symbol]
        seen = self._seen_trade_ids.get(symbol, set())
        while trades and trades[0][0] < cutoff:
            ts, price, size, is_buy, tid = trades.popleft()
            usd_amount = price * size
            if is_buy:
                self._buy_volume[symbol] -= usd_amount
                self._cvd[symbol] -= usd_amount
            else:
                self._sell_volume[symbol] -= usd_amount
                self._cvd[symbol] += usd_amount
            if usd_amount >= LARGE_TRADE_USD:
                self._large_trades[symbol] = max(0, self._large_trades[symbol] - 1)
            # Remove from dedup set
            if tid is not None:
                seen.discard(tid)

    def get_flow(self, symbol: str) -> dict:
        """Get current trade flow snapshot."""
        if symbol not in self._trades:
            return {
                'buy_volume': 0.0,
                'sell_volume': 0.0,
                'cvd': 0.0,
                'large_trades': 0,
                'trade_count': 0,
                'timestamp': time.time(),
            }
        self._prune(symbol)
        return {
            'buy_volume': round(self._buy_volume.get(symbol, 0.0), 2),
            'sell_volume': round(self._sell_volume.get(symbol, 0.0), 2),
            'cvd': round(self._cvd.get(symbol, 0.0), 2),
            'large_trades': self._large_trades.get(symbol, 0),
            'trade_count': len(self._trades.get(symbol, [])),
            'timestamp': time.time(),
        }


# ── Order Book Imbalance Calculator ──────────────────────

def calculate_ob_imbalance(order_book: dict, levels: int = OB_LEVELS) -> dict:
    """Calculate bid/ask imbalance from the top N levels.

    Returns:
        {
            'imbalance': float 0.0-1.0 (>0.5 = bid heavy, <0.5 = ask heavy),
            'bid_depth': float (total bid size in top N levels),
            'ask_depth': float (total ask size in top N levels),
            'best_bid': float,
            'best_ask': float,
            'spread_pct': float,
            'timestamp': float,
        }
    """
    bids = order_book.get('bids', [])
    asks = order_book.get('asks', [])

    # Sort: bids descending by price, asks ascending by price
    try:
        sorted_bids = sorted(bids, key=lambda x: float(x.get('price', 0)), reverse=True)[:levels]
        sorted_asks = sorted(asks, key=lambda x: float(x.get('price', 0)))[:levels]
    except (TypeError, ValueError):
        return _neutral_ob_snapshot()

    bid_depth = sum(float(b.get('size', 0)) for b in sorted_bids)
    ask_depth = sum(float(a.get('size', 0)) for a in sorted_asks)

    total_depth = bid_depth + ask_depth
    if total_depth <= 0:
        return _neutral_ob_snapshot()

    imbalance = bid_depth / total_depth  # >0.5 = more bids = buy pressure

    best_bid = float(sorted_bids[0]['price']) if sorted_bids else 0.0
    best_ask = float(sorted_asks[0]['price']) if sorted_asks else 0.0
    mid = (best_bid + best_ask) / 2.0 if best_bid > 0 and best_ask > 0 else 0.0
    spread_pct = ((best_ask - best_bid) / mid) if mid > 0 else 0.0

    return {
        'imbalance': round(imbalance, 4),
        'bid_depth': round(bid_depth, 6),
        'ask_depth': round(ask_depth, 6),
        'best_bid': best_bid,
        'best_ask': best_ask,
        'spread_pct': round(spread_pct, 6),
        'timestamp': time.time(),
    }


def _neutral_ob_snapshot() -> dict:
    return {
        'imbalance': 0.5,
        'bid_depth': 0.0,
        'ask_depth': 0.0,
        'best_bid': 0.0,
        'best_ask': 0.0,
        'spread_pct': 0.0,
        'timestamp': time.time(),
    }


# ── WebSocket Streamer ───────────────────────────────────

class LighterWsStreamer:
    """WebSocket client that streams Lighter order book and trade data to Redis."""

    def __init__(self, ws_url: str = WS_URL, redis_url: str = REDIS_URL):
        self.ws_url = ws_url
        self.redis_url = redis_url
        self._running = False
        self._redis: redis.Redis | None = None
        self._trade_accum = TradeAccumulator()
        self._ws = None

        # Maintained order book state (mirrors SDK WsClient logic)
        self._order_books: dict[str, dict] = {}  # market_id_str -> {bids:[], asks:[]}

        # Stats
        self._ob_updates = 0
        self._trade_updates = 0
        self._errors = 0
        self._connected_since: float | None = None
        self._last_stats = 0.0

    def _connect_redis(self):
        """Create Redis connection."""
        try:
            self._redis = redis.Redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            self._redis.ping()
            logger.info("Redis connected: %s", self.redis_url)
        except Exception as e:
            logger.error("Redis connection failed: %s", e)
            self._redis = None
            self._errors += 1

    def _redis_set(self, key: str, value: str, ttl: int = REDIS_KEY_TTL):
        """Set a Redis key with TTL, reconnecting if needed."""
        if self._redis is None:
            self._connect_redis()
        if self._redis is None:
            return
        try:
            self._redis.setex(key, ttl, value)
        except redis.ConnectionError:
            self._errors += 1
            self._connect_redis()
        except Exception as e:
            logger.error("Redis SET error: %s", e)
            self._errors += 1

    def _redis_publish(self, channel: str, data: dict):
        """Publish JSON to a Redis pub/sub channel + SET for polling readers."""
        json_str = json.dumps(data)
        if self._redis is None:
            self._connect_redis()
        if self._redis is None:
            return
        try:
            self._redis.publish(channel, json_str)
        except redis.ConnectionError:
            self._errors += 1
            self._connect_redis()
        except Exception as e:
            logger.error("Redis PUBLISH error: %s", e)
            self._errors += 1

    # ── WebSocket Message Handling ────────────────────────

    def _on_connected(self, ws):
        """Subscribe to all configured market channels on connect."""
        for symbol, market_id in SUBSCRIBE_MARKETS.items():
            # Subscribe to order book channel
            sub_msg = json.dumps({
                "type": "subscribe",
                "channel": f"order_book/{market_id}",
            })
            ws.send(sub_msg)
            logger.info("Subscribed: order_book/%d (%s)", market_id, symbol)

        self._connected_since = time.time()
        logger.info("WebSocket connected — subscribed to %d markets", len(SUBSCRIBE_MARKETS))

    async def _on_connected_async(self, ws):
        """Subscribe to all configured market channels on connect (async)."""
        for symbol, market_id in SUBSCRIBE_MARKETS.items():
            sub_msg = json.dumps({
                "type": "subscribe",
                "channel": f"order_book/{market_id}",
            })
            await ws.send(sub_msg)
            logger.info("Subscribed: order_book/%d (%s)", market_id, symbol)

        self._connected_since = time.time()
        logger.info("WebSocket connected — subscribed to %d markets", len(SUBSCRIBE_MARKETS))

    def _handle_order_book_snapshot(self, message: dict):
        """Initial order book snapshot from subscription."""
        channel = message.get('channel', '')
        market_id = channel.split(':')[-1] if ':' in channel else channel.split('/')[-1]
        ob_data = message.get('order_book', {})
        symbol = ID_TO_SYMBOL.get(market_id)

        if not symbol:
            logger.debug("Unknown market_id in OB snapshot: %s", market_id)
            return

        # Store full order book state
        self._order_books[market_id] = {
            'bids': ob_data.get('bids', []),
            'asks': ob_data.get('asks', []),
        }

        self._process_order_book(symbol, market_id)

    def _handle_order_book_update(self, message: dict):
        """Incremental order book update (delta)."""
        channel = message.get('channel', '')
        market_id = channel.split(':')[-1] if ':' in channel else channel.split('/')[-1]
        ob_delta = message.get('order_book', {})
        symbol = ID_TO_SYMBOL.get(market_id)

        if not symbol:
            return

        if market_id not in self._order_books:
            # Got update before snapshot — store as initial
            self._order_books[market_id] = {
                'bids': ob_delta.get('bids', []),
                'asks': ob_delta.get('asks', []),
            }
        else:
            # Apply delta (same logic as SDK WsClient.update_orders)
            self._apply_ob_delta(
                ob_delta.get('bids', []),
                self._order_books[market_id]['bids'],
            )
            self._apply_ob_delta(
                ob_delta.get('asks', []),
                self._order_books[market_id]['asks'],
            )

        self._process_order_book(symbol, market_id)
        self._ob_updates += 1

    def _apply_ob_delta(self, new_orders: list, existing_orders: list):
        """Apply incremental order book updates (mirrors SDK logic)."""
        for new_order in new_orders:
            is_new = True
            existing_copy = existing_orders[:]
            for existing in existing_copy:
                if new_order.get('price') == existing.get('price'):
                    is_new = False
                    existing['size'] = new_order['size']
                    if float(new_order.get('size', 0)) == 0:
                        try:
                            existing_orders.remove(existing)
                        except ValueError:
                            pass
            if is_new and float(new_order.get('size', 0)) > 0:
                existing_orders.append(new_order)

        # Final cleanup
        existing_orders[:] = [
            o for o in existing_orders if float(o.get('size', 0)) > 0
        ]

    def _process_order_book(self, symbol: str, market_id: str):
        """Calculate imbalance and publish to Redis."""
        ob = self._order_books.get(market_id, {})
        snapshot = calculate_ob_imbalance(ob)

        # Store order book snapshot (top 20 levels) with TTL
        self._redis_set(
            f'lighter:ob:{symbol}',
            json.dumps(snapshot),
        )

        # Store imbalance as a simple float key for fast reads
        self._redis_set(
            f'lighter:ob_imbalance:{symbol}',
            str(snapshot['imbalance']),
        )

        # Also publish for real-time consumers
        self._redis_publish(f'lighter:ob_update:{symbol}', snapshot)

    def _handle_trade(self, message: dict):
        """Process trade message — extract trades from raw WS order book updates.

        NOTE: This is a best-effort path for the raw WS fallback. The SDK path
        strips trades before the callback. The primary trade source is the REST
        polling loop (_poll_recent_trades) which runs concurrently.

        If raw WS messages contain a 'trades' field, those trades will be
        ingested here (without trade_id dedup, since the wire format may differ).
        """
        channel = message.get('channel', '')
        market_id = channel.split(':')[-1] if ':' in channel else channel.split('/')[-1]
        symbol = ID_TO_SYMBOL.get(market_id)
        if not symbol:
            return

        trades = message.get('order_book', {}).get('trades', [])
        if not trades:
            return

        for trade in trades:
            try:
                price = float(trade.get('price', 0))
                size = float(trade.get('size', 0))
                # is_maker_ask=True means taker bought (aggressive buy)
                is_buy = bool(trade.get('is_maker_ask', False))

                if price > 0 and size > 0:
                    self._trade_accum.add_trade(symbol, price, size, is_buy)
                    self._trade_updates += 1
            except (TypeError, ValueError) as e:
                logger.debug("Trade parse error: %s — %s", e, trade)

        # Publish updated trade flow to Redis
        flow = self._trade_accum.get_flow(symbol)
        self._redis_set(f'lighter:trades:{symbol}', json.dumps(flow))
        self._redis_publish(f'lighter:trade_flow:{symbol}', flow)

    def _log_stats(self):
        """Log periodic stats."""
        now = time.time()
        if now - self._last_stats < STATS_LOG_INTERVAL:
            return
        self._last_stats = now

        uptime = (now - self._connected_since) if self._connected_since else 0
        # Per-symbol trade window summary
        sym_counts = {
            sym: len(self._trade_accum._trades.get(sym, []))
            for sym in SUBSCRIBE_MARKETS
        }
        sym_str = ', '.join(f'{s}={c}' for s, c in sym_counts.items())
        logger.info(
            "Stats — OB updates: %d | Trades polled: %d | Errors: %d | "
            "Uptime: %.0fs | Markets: %d | Window[5m]: %s",
            self._ob_updates,
            self._trade_updates,
            self._errors,
            uptime,
            len(self._order_books),
            sym_str,
        )

    # ── Main Loop ────────────────────────────────────────

    async def _run_ws_loop(self):
        """Single WebSocket connection session using the lighter SDK WsClient.

        We use the SDK's async run to get proper subscription handling and
        order book state management. Falls back to raw websockets if SDK fails.
        """
        try:
            await self._run_with_sdk()
        except Exception as e:
            logger.warning("SDK WebSocket failed (%s), falling back to raw websockets", e)
            await self._run_with_raw_ws()

    async def _run_with_sdk(self):
        """Connect using lighter.WsClient (async mode)."""
        import lighter

        market_ids = list(SUBSCRIBE_MARKETS.values())

        def on_order_book_update(market_id_str, order_book):
            """Called by WsClient on every order book snapshot/update.

            NOTE: The SDK's WsClient.update_order_book_state only keeps bids/asks
            in the maintained state — any 'trades' field from the raw wire message
            is stripped before this callback fires. Trade data is obtained via the
            REST polling loop (_poll_recent_trades) instead.
            """
            symbol = ID_TO_SYMBOL.get(str(market_id_str))
            if not symbol:
                return

            # The SDK maintains full order book state for us
            self._order_books[str(market_id_str)] = order_book

            # Calculate and publish imbalance
            snapshot = calculate_ob_imbalance(order_book)
            self._redis_set(f'lighter:ob:{symbol}', json.dumps(snapshot))
            self._redis_set(f'lighter:ob_imbalance:{symbol}', str(snapshot['imbalance']))
            self._redis_publish(f'lighter:ob_update:{symbol}', snapshot)
            self._ob_updates += 1

            self._log_stats()

        # Parse the host from WS URL (SDK expects host without wss://)
        host = self.ws_url.replace('wss://', '').replace('ws://', '')
        # Strip /stream path if present (SDK adds it)
        if host.endswith('/stream'):
            host = host[:-7]

        ws_client = lighter.WsClient(
            host=host,
            path='/stream',
            order_book_ids=market_ids,
            on_order_book_update=on_order_book_update,
        )

        self._connected_since = time.time()
        logger.info("Starting SDK WebSocket: wss://%s/stream", host)

        # run_async blocks until disconnected
        await ws_client.run_async()

    async def _run_with_raw_ws(self):
        """Fallback: connect using raw websockets library."""
        from websockets.client import connect as connect_async

        logger.info("Connecting raw WebSocket: %s", self.ws_url)

        async with connect_async(self.ws_url, ping_interval=20, ping_timeout=30) as ws:
            self._ws = ws

            async for raw_message in ws:
                if not self._running:
                    break

                try:
                    message = json.loads(raw_message) if isinstance(raw_message, str) else json.loads(raw_message.decode())
                except json.JSONDecodeError:
                    logger.debug("Invalid JSON: %s", raw_message[:200])
                    continue

                msg_type = message.get('type', '')

                if msg_type == 'connected':
                    await self._on_connected_async(ws)

                elif msg_type == 'ping':
                    await ws.send(json.dumps({"type": "pong"}))

                elif msg_type == 'subscribed/order_book':
                    self._handle_order_book_snapshot(message)
                    # Also check for trades in the initial snapshot
                    self._handle_trade(message)

                elif msg_type == 'update/order_book':
                    self._handle_order_book_update(message)
                    # Trades come embedded in OB updates
                    self._handle_trade(message)

                elif msg_type in ('subscribed/account_all', 'update/account_all'):
                    pass  # Ignore account updates

                else:
                    logger.debug("Unhandled message type: %s", msg_type)

                self._log_stats()

    # ── REST Trade Polling (fallback) ────────────────────

    async def _poll_recent_trades(self):
        """Poll REST recent_trades endpoint every TRADE_POLL_INTERVAL seconds.

        The SDK WsClient strips trade data from OB update callbacks (it only
        maintains bids/asks state). This polling loop is the reliable path for
        trade flow, CVD, and large-trade detection.
        """
        import lighter

        api_url = self.ws_url.replace('wss://', 'https://').replace('ws://', 'http://')
        # Strip /stream path — REST API is at the root
        if api_url.endswith('/stream'):
            api_url = api_url[:-7]

        logger.info("Trade poller starting — REST endpoint: %s, interval: %ds",
                     api_url, TRADE_POLL_INTERVAL)

        api_client = None
        order_api = None

        while self._running:
            try:
                if api_client is None:
                    api_client = lighter.ApiClient(
                        configuration=lighter.Configuration(host=api_url),
                    )
                    order_api = lighter.OrderApi(api_client)

                for symbol, market_id in SUBSCRIBE_MARKETS.items():
                    try:
                        resp = await order_api.recent_trades_without_preload_content(
                            market_id=market_id,
                            limit=TRADE_POLL_LIMIT,
                        )
                        raw = await resp.json()
                        trades_list = raw.get('trades', [])

                        new_count = 0
                        for t in trades_list:
                            try:
                                trade_id = int(t.get('trade_id', 0))
                                price = float(t.get('price', 0))
                                size = float(t.get('size', 0))
                                is_buy = bool(t.get('is_maker_ask', False))
                                ts = float(t.get('timestamp', 0))
                                # SDK timestamps are in seconds (Unix epoch)
                                if ts > 1e12:
                                    ts = ts / 1000.0  # ms -> s if needed

                                if price > 0 and size > 0:
                                    self._trade_accum.add_trade(
                                        symbol, price, size, is_buy,
                                        timestamp=ts, trade_id=trade_id,
                                    )
                                    new_count += 1
                            except (TypeError, ValueError, KeyError):
                                pass

                        if new_count > 0:
                            self._trade_updates += new_count

                        # Publish updated flow to Redis regardless (keeps TTL fresh)
                        flow = self._trade_accum.get_flow(symbol)
                        self._redis_set(f'lighter:trades:{symbol}', json.dumps(flow))
                        self._redis_publish(f'lighter:trade_flow:{symbol}', flow)

                    except Exception as e:
                        logger.debug("Trade poll error for %s: %s", symbol, e)
                        self._errors += 1

            except Exception as e:
                logger.warning("Trade poller error: %s", e)
                self._errors += 1
                # Reset API client on failure
                if api_client:
                    try:
                        await api_client.close()
                    except Exception:
                        pass
                api_client = None
                order_api = None

            await asyncio.sleep(TRADE_POLL_INTERVAL)

        # Cleanup
        if api_client:
            try:
                await api_client.close()
            except Exception:
                pass
        logger.info("Trade poller stopped")

    async def run(self):
        """Main entry: run WS (order book) + REST polling (trades) concurrently."""
        self._running = True
        self._connect_redis()
        delay = RECONNECT_BASE_DELAY

        logger.info(
            "Lighter WS Streamer starting — %d markets, Redis=%s",
            len(SUBSCRIBE_MARKETS), self.redis_url,
        )

        # Start trade poller as a background task
        trade_poller = asyncio.create_task(self._poll_recent_trades())

        while self._running:
            try:
                await self._run_ws_loop()
            except asyncio.CancelledError:
                logger.info("WebSocket loop cancelled")
                break
            except Exception as e:
                self._errors += 1
                logger.error("WebSocket error: %s — reconnecting in %.1fs", e, delay)

            if not self._running:
                break

            # Exponential backoff with cap
            await asyncio.sleep(delay)
            delay = min(delay * RECONNECT_MULTIPLIER, RECONNECT_MAX_DELAY)

            # Reset delay on successful connection (connected for > 60s)
            if self._connected_since and (time.time() - self._connected_since) > 60:
                delay = RECONNECT_BASE_DELAY

            self._connected_since = None
            logger.info("Reconnecting WebSocket...")

        # Cancel trade poller
        trade_poller.cancel()
        try:
            await trade_poller
        except asyncio.CancelledError:
            pass

        logger.info("Lighter WS Streamer stopped")

    def stop(self):
        """Signal the run loop to exit."""
        self._running = False
        if self._ws:
            try:
                # Close will cause the async for loop to exit
                asyncio.get_event_loop().call_soon_threadsafe(self._ws.close)
            except Exception:
                pass
        logger.info("Stop requested")


# ── CLI Entry Point ──────────────────────────────────────

def main():
    streamer = LighterWsStreamer()

    def _shutdown(signum, frame):
        logger.info("Received signal %d — shutting down", signum)
        streamer.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        asyncio.run(streamer.run())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt — exiting")


if __name__ == '__main__':
    main()
