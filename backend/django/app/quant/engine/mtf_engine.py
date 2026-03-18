"""
mtf_engine.py — Multi-timeframe signal engine (per symbol).

Logic (relaxed mode):
  H1  — required: ADX > 20, MACD direction, RSI not extreme
  THEN either:
    M15 — structure confirms (bullish/bearish market structure)
    M5  — trigger fires (FVG bounce or liquidity sweep)

CVD realtime signal used as a soft filter: if it actively disagrees, skip.

One MTFEngine instance per symbol. Call on_tick() on every incoming tick.
Returns a signal dict when conditions align, None otherwise.
"""
from __future__ import annotations

import logging
import time

from .bar_builder import BarBuilder
from . import indicators as ind

logger = logging.getLogger('quant')

ADX_MIN      = 20     # minimum trend strength on H1
RSI_BULL_MAX = 65     # RSI ceiling for buy entries (not overbought)
RSI_BEAR_MIN = 35     # RSI floor for sell entries (not oversold)
SIGNAL_TTL   = 60     # seconds before the same signal can fire again


class MTFEngine:
    """
    Per-symbol multi-timeframe engine.

    on_tick(tick) → signal dict | None

    Signal dict:
        {
            'direction': 'buy' | 'sell',
            'level':     float,    # FVG or sweep level (entry reference)
            'atr':       float,
            'setup':     'fvg' | 'sweep',
            'reason':    'h1+m15' | 'h1+m5',
        }
    """

    def __init__(self, symbol: str):
        self.symbol  = symbol
        self.builder = BarBuilder()
        self._last_signal_ts: float = 0.0
        self._seeded = False

    def seed_from_mt5(self):
        """
        Pre-load historical bars from MT5 so indicators work immediately.
        Fetches H1, M15, M5 history. Called once on first use.
        """
        try:
            from app.utils.api.data import fetch_data_pos_batch
            from app.utils.constants import MT5Timeframe
            from app.quant.engine.bar_builder import Bar

            tf_map = {
                'H1':  MT5Timeframe.H1,
                'M15': MT5Timeframe.M15,
                'M5':  MT5Timeframe.M5,
            }

            for tf_name, tf_enum in tf_map.items():
                result = fetch_data_pos_batch([self.symbol], tf_enum, 100)
                df = result.get(self.symbol)
                if df is None or df.empty:
                    continue
                import pandas as pd
                records = df.to_dict('records')
                bars = []
                for row in records:
                    t = row.get('time', 0)
                    try:
                        ts = int(pd.Timestamp(t).timestamp()) if not isinstance(t, (int, float)) else int(t)
                    except Exception:
                        ts = 0
                    bars.append(Bar(
                        ts=ts,
                        o=float(row['open']),  h=float(row['high']),
                        l=float(row['low']),   c=float(row['close']),
                        v=float(row.get('tick_volume', 0)),
                    ))
                self.builder.seed(tf_name, bars)
                logger.debug('[mtf_engine] %s seeded %d %s bars', self.symbol, len(bars), tf_name)

            self._seeded = True
            logger.info('[mtf_engine] %s ready — H1/M15/M5 seeded from MT5', self.symbol)
        except Exception as e:
            logger.warning('[mtf_engine] Seed failed for %s: %s', self.symbol, e)
            self._seeded = True  # don't retry forever

    def on_tick(self, tick: dict) -> dict | None:
        """Process one tick. Returns a signal dict if all conditions align."""
        if not self._seeded:
            self.seed_from_mt5()

        closed = self.builder.update(tick)
        if not closed:
            return None

        # Evaluate on every bar close (M5, M15, H1)
        for tf, _ in closed:
            signal = self._evaluate(tf)
            if signal:
                return signal
        return None

    # ------------------------------------------------------------------
    # Internal evaluation
    # ------------------------------------------------------------------

    def _evaluate(self, closed_tf: str) -> dict | None:
        # Cooldown: don't fire the same symbol twice within SIGNAL_TTL
        if time.time() - self._last_signal_ts < SIGNAL_TTL:
            return None

        h1_bars  = self.builder.bars('H1')
        m15_bars = self.builder.bars('M15')
        m5_bars  = self.builder.bars('M5')

        # ── H1 bias (required) ────────────────────────────────────────
        h1_adx  = ind.adx(h1_bars)
        h1_macd = ind.macd(h1_bars)
        h1_rsi  = ind.rsi(h1_bars)

        if not h1_adx or h1_adx < ADX_MIN:
            return None
        if not h1_macd or h1_rsi is None:
            return None

        macd_line, sig_line = h1_macd

        h1_bull = macd_line > sig_line and h1_rsi < RSI_BULL_MAX
        h1_bear = macd_line < sig_line and h1_rsi > RSI_BEAR_MIN

        if not h1_bull and not h1_bear:
            return None

        direction = 'buy' if h1_bull else 'sell'

        # ── ATR for sizing and FVG proximity ─────────────────────────
        # Must use H1 ATR — signal is H1-timeframe, sizing must match.
        # M15 ATR is 3-5x smaller → produces absurdly large lot sizes.
        atr_val = ind.atr(h1_bars) or ind.atr(m15_bars)
        if not atr_val:
            return None

        # ── Relaxed: M15 structure OR M5 trigger OR H1 CVD divergence ───
        m15_ok           = self._m15_confirms(m15_bars, direction)
        trigger, level   = self._m5_trigger(m5_bars, direction, atr_val)
        cvd_ok           = ind.cvd_divergence(h1_bars, direction)

        if not m15_ok and not trigger and not cvd_ok:
            return None

        if m15_ok:
            reason = 'h1+m15'
        elif trigger:
            reason = 'h1+m5'
        else:
            reason = 'h1+cvd'
        if cvd_ok and reason != 'h1+cvd':
            reason += '+cvd'   # annotate when CVD also agrees

        setup = trigger if trigger else 'structure'

        self._last_signal_ts = time.time()

        logger.info(
            '[mtf_engine] %s %s | adx=%.1f rsi=%.1f macd=%+.5f '
            'm15=%s m5=%s reason=%s atr=%.5f',
            self.symbol, direction.upper(),
            h1_adx, h1_rsi, macd_line - sig_line,
            '✓' if m15_ok else '✗',
            f'✓({trigger})' if trigger else '✗',
            reason, atr_val,
        )

        return {
            'direction': direction,
            'level':     level,
            'atr':       atr_val,
            'setup':     setup,
            'reason':    reason,
        }

    def _m15_confirms(self, bars: list, direction: str) -> bool:
        if len(bars) < 10:
            return False
        structure = ind.market_structure(bars)
        return (direction == 'buy'  and structure == 'bullish') or \
               (direction == 'sell' and structure == 'bearish')

    def _m5_trigger(self, bars: list, direction: str, atr_val: float) -> tuple[str | None, float | None]:
        """Returns (setup_name, level) or (None, None)."""
        # FVG first — more precise level
        level = ind.fvg_trigger(bars, atr_val, direction)
        if level:
            return 'fvg', level

        # Sweep fallback
        sweep = ind.sweep_trigger(bars)
        if sweep and sweep[0] == direction:
            return 'sweep', sweep[1]

        return None, None
