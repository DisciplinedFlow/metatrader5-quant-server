"""
bar_builder.py — Real-time OHLCV bar aggregation from ticks.

Converts raw ticks (bid/ask/last/volume) into M5, M15, H1 bars stored
in a rolling in-memory deque. One BarBuilder instance per symbol.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

TIMEFRAMES = {
    'M5':  5  * 60,
    'M15': 15 * 60,
    'H1':  60 * 60,
}

MAX_BARS = 100  # closed bars kept per timeframe


@dataclass
class Bar:
    ts: int       # bar open timestamp (unix seconds, floored to TF boundary)
    o:  float
    h:  float
    l:  float
    c:  float
    v:  float = 0.0


class BarBuilder:
    """
    Aggregates ticks into OHLCV bars for M5, M15 and H1.

    Usage:
        builder = BarBuilder()
        closed = builder.update(tick)   # list of (tf, Bar) that just closed
        h1_bars = builder.bars('H1')    # list of completed H1 bars
    """

    def __init__(self):
        self._current: dict[str, Bar | None] = {tf: None for tf in TIMEFRAMES}
        self._closed:  dict[str, deque]      = {tf: deque(maxlen=MAX_BARS) for tf in TIMEFRAMES}

    def update(self, tick: dict) -> list[tuple[str, Bar]]:
        """
        Process one tick. Returns a list of (timeframe, bar) for every bar
        that completed with this tick (can be 0, 1 or more).
        """
        price = tick.get('l') or 0.0
        if not price:
            b, a = tick.get('b', 0.0), tick.get('a', 0.0)
            price = (b + a) / 2 if b and a else 0.0
        if not price:
            return []

        volume  = float(tick.get('v', 0))
        ts_ms   = tick.get('t', int(time.time() * 1000))
        ts_sec  = ts_ms // 1000

        newly_closed = []

        for tf, period in TIMEFRAMES.items():
            bar_ts  = (ts_sec // period) * period
            current = self._current[tf]

            if current is None:
                # First tick ever for this timeframe
                self._current[tf] = Bar(ts=bar_ts, o=price, h=price, l=price, c=price, v=volume)

            elif bar_ts > current.ts:
                # New bar period — the current bar is now closed
                self._closed[tf].append(current)
                newly_closed.append((tf, current))
                self._current[tf] = Bar(ts=bar_ts, o=price, h=price, l=price, c=price, v=volume)

            else:
                # Same bar period — update OHLCV
                current.h  = max(current.h, price)
                current.l  = min(current.l, price)
                current.c  = price
                current.v += volume

        return newly_closed

    def seed(self, tf: str, historical_bars: list[Bar]):
        """
        Pre-load historical bars so indicators are ready immediately.
        Call once at startup before ticks start flowing.
        """
        self._closed[tf].clear()
        for bar in historical_bars[-MAX_BARS:]:
            self._closed[tf].append(bar)

    def bars(self, tf: str) -> list[Bar]:
        """Closed bars for timeframe, oldest first."""
        return list(self._closed[tf])

    def current(self, tf: str) -> Bar | None:
        """The bar currently forming (not yet closed)."""
        return self._current.get(tf)
