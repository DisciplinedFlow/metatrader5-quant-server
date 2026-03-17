"""Lightweight WebSocket relay server.

Subscribes to Redis pub/sub and broadcasts to connected WebSocket clients.
Runs as a separate process alongside Django — no ASGI migration needed.

Usage: python -m app.ws.server
"""
import asyncio
import json
import logging
import os
import signal
import redis.asyncio as aioredis
import websockets

logger = logging.getLogger('ws')

REDIS_URL = os.environ.get('WS_REDIS_URL', 'redis://redis:6379/1')
WS_PORT = int(os.environ.get('WS_PORT', '8001'))
WS_HOST = os.environ.get('WS_HOST', '0.0.0.0')

# Redis pub/sub channels to relay
CHANNELS = [
    'ws:trades',
    'ws:positions',
    'ws:bot_status',
    'ws:news',
]

connected_clients: set = set()
_shutdown = False


async def handler(websocket):
    """Handle a new WebSocket client connection."""
    connected_clients.add(websocket)
    remote = websocket.remote_address
    logger.info(f"Client connected from {remote} ({len(connected_clients)} total)")
    try:
        async for _message in websocket:
            # Broadcast-only server — client messages are ignored.
            # Keeping the read loop alive so we detect disconnects.
            pass
    finally:
        connected_clients.discard(websocket)
        logger.info(f"Client disconnected from {remote} ({len(connected_clients)} total)")


async def broadcast(message: str):
    """Send a message to every connected client."""
    if not connected_clients:
        return
    # Build list of send coroutines; failures are returned not raised
    results = await asyncio.gather(
        *[client.send(message) for client in connected_clients],
        return_exceptions=True,
    )
    # Clean up any clients that errored out
    for client, result in zip(list(connected_clients), results):
        if isinstance(result, Exception):
            connected_clients.discard(client)
            logger.debug(f"Removed broken client: {result}")


async def redis_listener():
    """Subscribe to Redis pub/sub channels and relay messages to WebSocket clients."""
    while not _shutdown:
        try:
            r = aioredis.from_url(REDIS_URL, decode_responses=True)
            pubsub = r.pubsub()
            await pubsub.subscribe(*CHANNELS)
            logger.info(f"Subscribed to Redis channels: {CHANNELS}")

            async for message in pubsub.listen():
                if _shutdown:
                    break
                if message['type'] == 'message':
                    data = message['data']
                    # Validate it's JSON before broadcasting
                    try:
                        json.loads(data)
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(f"Non-JSON message on {message['channel']}, skipping")
                        continue
                    await broadcast(data)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Redis listener error: {e}, reconnecting in 3s...")
            await asyncio.sleep(3)


async def main():
    """Start the WebSocket server and Redis listener."""
    global _shutdown

    loop = asyncio.get_event_loop()

    def _signal_handler():
        global _shutdown
        _shutdown = True
        logger.info("Shutdown signal received")

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    async with websockets.serve(
        handler,
        WS_HOST,
        WS_PORT,
        ping_interval=30,
        ping_timeout=10,
    ):
        logger.info(f"WebSocket relay server running on ws://{WS_HOST}:{WS_PORT}")
        logger.info(f"Redis: {REDIS_URL} | Channels: {CHANNELS}")
        await redis_listener()

    logger.info("WebSocket server shut down cleanly")


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(name)s] %(levelname)s %(message)s',
    )
    asyncio.run(main())
