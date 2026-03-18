"""
indicators.py — Pure-Python indicators operating on Bar lists.

No pandas, no numpy. All functions take list[Bar] and return a scalar
or None (if not enough data). Designed to run on every tick cheaply.
"""
from __future__ import annotations

from .bar_builder import Bar


# ---------------------------------------------------------------------------
# Trend indicators
# ---------------------------------------------------------------------------

def _ema(values: list[float], period: int) -> list[float]:
    k = 2.0 / (period + 1)
    out = []
    for v in values:
        out.append(v if not out else v * k + out[-1] * (1 - k))
    return out


def adx(bars: list[Bar], period: int = 14) -> float | None:
    """Average Directional Index. Returns ADX value or None if not enough bars."""
    if len(bars) < period * 2 + 1:
        return None

    trs, p_dm, m_dm = [], [], []
    for i in range(1, len(bars)):
        h,  l,  _  = bars[i].h,     bars[i].l,     bars[i].c
        ph, pl, pc = bars[i-1].h,   bars[i-1].l,   bars[i-1].c
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        up, dn = h - ph, pl - l
        p_dm.append(up if up > dn and up > 0 else 0.0)
        m_dm.append(dn if dn > up and dn > 0 else 0.0)

    def _wilder(vals: list[float], p: int) -> list[float]:
        s = [sum(vals[:p])]
        for v in vals[p:]:
            s.append(s[-1] - s[-1] / p + v)
        return s

    atr_s = _wilder(trs,  period)
    pdi_s = _wilder(p_dm, period)
    mdi_s = _wilder(m_dm, period)

    dx_vals = []
    for a, p, m in zip(atr_s, pdi_s, mdi_s):
        if a == 0:
            continue
        pdi = 100 * p / a
        mdi = 100 * m / a
        dx_vals.append(100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) else 0.0)

    if len(dx_vals) < period:
        return None
    return sum(dx_vals[-period:]) / period


def macd(bars: list[Bar], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[float, float] | None:
    """
    Returns (macd_line, signal_line) or None.
    macd_line > signal_line  → bullish momentum
    macd_line < signal_line  → bearish momentum
    """
    if len(bars) < slow + signal:
        return None
    closes    = [b.c for b in bars]
    fast_ema  = _ema(closes, fast)
    slow_ema  = _ema(closes, slow)
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
    sig_line  = _ema(macd_line, signal)
    return macd_line[-1], sig_line[-1]


def rsi(bars: list[Bar], period: int = 14) -> float | None:
    """RSI. < 35 oversold (look for buys), > 65 overbought (look for sells)."""
    if len(bars) < period + 1:
        return None
    closes = [b.c for b in bars[-(period + 1):]]
    gains  = [max(closes[i] - closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1] - closes[i], 0) for i in range(1, len(closes))]
    ag, al = sum(gains) / period, sum(losses) / period
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


def atr(bars: list[Bar], period: int = 14) -> float | None:
    """Average True Range."""
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i].h, bars[i].l, bars[i-1].c
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    recent = trs[-period:]
    return sum(recent) / len(recent) if recent else None


# ---------------------------------------------------------------------------
# Market structure
# ---------------------------------------------------------------------------

def market_structure(bars: list[Bar], lookback: int = 10) -> str:
    """
    Splits last `lookback` bars into two halves, compares swing extremes.
    Returns 'bullish', 'bearish', or 'ranging'.
    """
    if len(bars) < lookback:
        return 'ranging'
    recent = bars[-lookback:]
    mid    = lookback // 2
    first, second = recent[:mid], recent[mid:]

    hh = max(b.h for b in second) > max(b.h for b in first)
    hl = min(b.l for b in second) > min(b.l for b in first)
    lh = max(b.h for b in second) < max(b.h for b in first)
    ll = min(b.l for b in second) < min(b.l for b in first)

    if hh and hl:
        return 'bullish'
    if lh and ll:
        return 'bearish'
    return 'ranging'


# ---------------------------------------------------------------------------
# Entry triggers
# ---------------------------------------------------------------------------

def fvg_trigger(bars: list[Bar], atr_val: float, direction: str) -> float | None:
    """
    Fair Value Gap: 3-bar imbalance where price is currently returning.
    Returns the FVG level (entry reference) or None.
    """
    if len(bars) < 5 or not atr_val:
        return None

    last     = bars[-1]
    lookback = bars[-32:-1]   # recent history, exclude last bar

    for i in range(2, len(lookback)):
        prev2, curr = lookback[i - 2], lookback[i]

        if direction == 'buy' and prev2.h < curr.l:
            fvg_l, fvg_h = prev2.h, curr.l
            mid = (fvg_l + fvg_h) / 2
            if abs(last.c - mid) > 2 * atr_val:
                continue
            if any(b.c < mid for b in lookback[i:]):
                continue   # mitigated
            if last.l <= fvg_h and last.c >= fvg_l:
                return fvg_l

        elif direction == 'sell' and prev2.l > curr.h:
            fvg_h, fvg_l = prev2.l, curr.h
            mid = (fvg_l + fvg_h) / 2
            if abs(last.c - mid) > 2 * atr_val:
                continue
            if any(b.c > mid for b in lookback[i:]):
                continue   # mitigated
            if last.h >= fvg_l and last.c <= fvg_h:
                return fvg_h

    return None


def sweep_trigger(bars: list[Bar], lookback: int = 20) -> tuple[str, float] | None:
    """
    Liquidity sweep: last bar wicked beyond swing high/low but closed inside.
    Returns ('buy'/'sell', level) or None.
    """
    if len(bars) < lookback + 1:
        return None
    last  = bars[-1]
    prior = bars[-lookback - 1:-1]
    sh    = max(b.h for b in prior)
    sl    = min(b.l for b in prior)

    if last.h > sh and last.c < sh:
        return ('sell', sh)
    if last.l < sl and last.c > sl:
        return ('buy', sl)
    return None


# ---------------------------------------------------------------------------
# CVD (Cumulative Volume Delta)
# ---------------------------------------------------------------------------

def cvd_from_bars(bars: list[Bar]) -> list[float]:
    """Running CVD from OHLCV bars. delta = vol * (2c - h - l) / (h - l)."""
    running = 0.0
    result  = []
    for b in bars:
        rng   = b.h - b.l
        delta = b.v * (2 * b.c - b.h - b.l) / rng if rng > 0 else 0.0
        running += delta
        result.append(running)
    return result


def cvd_divergence(bars: list[Bar], direction: str, lookback: int = 20) -> bool:
    """
    True if bars show CVD Lack-of-Participants or Absorption confirming direction.

    Buy signals:
      - LoP: price making lower lows, CVD making higher lows (hidden buying)
      - Absorption: CVD making lower lows, price holds (sellers absorbing bids)

    Sell signals:
      - LoP: price making higher highs, CVD making lower highs (hidden selling)
      - Absorption: CVD making higher highs, price fails to follow
    """
    if len(bars) < lookback:
        return False

    recent = bars[-lookback:]
    cvd    = cvd_from_bars(recent)

    def _two_highs(vals: list[float]) -> tuple:
        highs = [i for i in range(1, len(vals) - 1)
                 if vals[i] > vals[i-1] and vals[i] > vals[i+1]]
        return (highs[-2], highs[-1]) if len(highs) >= 2 else (None, None)

    def _two_lows(vals: list[float]) -> tuple:
        lows = [i for i in range(1, len(vals) - 1)
                if vals[i] < vals[i-1] and vals[i] < vals[i+1]]
        return (lows[-2], lows[-1]) if len(lows) >= 2 else (None, None)

    p_lows  = [b.l for b in recent]
    p_highs = [b.h for b in recent]

    if direction == 'buy':
        # LoP: price LL + CVD HL
        pl1, pl2 = _two_lows(p_lows)
        cl1, cl2 = _two_lows(cvd)
        if all(x is not None for x in [pl1, pl2, cl1, cl2]):
            if recent[pl2].l < recent[pl1].l and cvd[cl2] > cvd[cl1]:
                return True
        # Absorption: CVD LL + price holds
        cl1, cl2 = _two_lows(cvd)
        pl1, pl2 = _two_lows(p_lows)
        if all(x is not None for x in [cl1, cl2, pl1, pl2]):
            if cvd[cl2] < cvd[cl1] and recent[pl2].l >= recent[pl1].l:
                return True
    else:
        # LoP: price HH + CVD LH
        ph1, ph2 = _two_highs(p_highs)
        ch1, ch2 = _two_highs(cvd)
        if all(x is not None for x in [ph1, ph2, ch1, ch2]):
            if recent[ph2].h > recent[ph1].h and cvd[ch2] < cvd[ch1]:
                return True
        # Absorption: CVD HH + price fails
        ch1, ch2 = _two_highs(cvd)
        ph1, ph2 = _two_highs(p_highs)
        if all(x is not None for x in [ch1, ch2, ph1, ph2]):
            if cvd[ch2] > cvd[ch1] and recent[ph2].h <= recent[ph1].h:
                return True

    return False
