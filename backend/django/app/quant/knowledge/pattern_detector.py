"""
Pattern Detector — OHLCV-based ICT/SMC pattern recognition for backtest seeding.

Consumes raw H4 OHLCV bars (list of dicts) and returns labelled pattern events.
No ML, no external APIs — pure price action geometry.

Used by backtest_seeder.py to scan 6 months of historical data and generate
reference trade nodes for the Neo4j brain. These nodes carry weight=0.3 vs
live trades (weight=1.0) — live data progressively dominates as it accumulates.

Pattern hierarchy:
  1. HTF Bias       — EMA(8/34) trend direction on H4
  2. FVG            — 3-bar imbalance gap (bullish / bearish)
  3. Order Block    — last candle before impulse move
  4. Fib GP         — 0.618–0.650 retracement of last major swing
  5. CVD Proxy      — OHLCV-derived volume flow divergence
  6. Session        — ASIA / LONDON / NY_OVERLAP / NY / EVENING

A "setup" fires when FVG + CVD_proxy align with HTF bias. OB and Fib zones
add confluence weight (multiplied into sim trade sizing downstream).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FVG:
    """Fair Value Gap — 3-bar imbalance zone."""
    direction: str          # 'bullish' | 'bearish'
    high: float
    low: float
    bar_index: int
    bar_time: datetime
    mitigated: bool = False
    mitigation_index: Optional[int] = None


@dataclass
class OrderBlock:
    """Last opposing candle before impulsive expansion move."""
    direction: str          # 'bullish' (demand OB) | 'bearish' (supply OB)
    ob_high: float
    ob_low: float
    ob_body_high: float
    ob_body_low: float
    bar_index: int
    bar_time: datetime
    impulse_size: float     # ATR multiples of the impulse that followed
    valid: bool = True


@dataclass
class FibLevel:
    """Golden pocket retracement zone (0.618–0.650) of a swing."""
    direction: str          # 'bullish' | 'bearish'  (direction of original swing)
    gp_high: float          # 0.618 level (upper bound of golden pocket)
    gp_low: float           # 0.650 level (lower bound — deeper retracement)
    swing_high: float
    swing_low: float
    swing_start_index: int
    swing_end_index: int


@dataclass
class CVDBar:
    """Per-bar CVD proxy value (cumulative from scan start)."""
    bar_index: int
    bar_time: datetime
    close: float
    money_flow: float       # single-bar delta
    cumulative: float       # running sum from bar 0


@dataclass
class Setup:
    """A complete pattern match ready for simulation."""
    symbol: str
    direction: str                          # 'bullish' | 'bearish'
    trigger_bar_index: int
    trigger_bar_time: datetime
    entry_price: float                      # FVG midpoint or OB body mid
    atr: float                              # ATR at trigger bar
    htf_bias: str                           # 'bullish' | 'bearish' | 'neutral'
    session: str                            # ASIA / LONDON / NY_OVERLAP / NY / EVENING
    fvg: Optional[FVG] = None
    order_block: Optional[OrderBlock] = None
    fib: Optional[FibLevel] = None
    cvd_divergence: bool = False
    confluence_score: float = 0.0
    nearby_geo_events: list = field(default_factory=list)
    era_sentiment: str = 'neutral'


# ---------------------------------------------------------------------------
# Session classification
# ---------------------------------------------------------------------------

SESSION_WINDOWS = {
    'ASIA':       (0, 7),
    'LONDON':     (7, 13),
    'NY_OVERLAP': (13, 17),
    'NY':         (17, 21),
    'EVENING':    (21, 24),
}


def _parse_bar_time(t) -> datetime:
    """Normalise bar time to a UTC datetime regardless of source format."""
    if isinstance(t, datetime):
        return t
    if isinstance(t, (int, float)):
        return datetime.fromtimestamp(t, tz=timezone.utc)
    # MT5 Flask returns strings like "Fri, 19 Sep 2025 04:00:00 GMT"
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(str(t))
    except Exception:
        pass
    # ISO fallback
    try:
        return datetime.fromisoformat(str(t).replace('Z', '+00:00'))
    except Exception:
        return datetime.now(tz=timezone.utc)


def _classify_session(dt: datetime) -> str:
    """Return session name for a UTC datetime."""
    if not isinstance(dt, datetime):
        dt = _parse_bar_time(dt)
    hour = dt.hour
    for name, (start, end) in SESSION_WINDOWS.items():
        if start <= hour < end:
            return name
    return 'EVENING'


# ---------------------------------------------------------------------------
# ATR calculation
# ---------------------------------------------------------------------------

def _compute_atr(bars: list[dict], period: int = 14) -> list[float]:
    """
    Compute ATR for each bar. bars[0] = oldest.
    Returns list same length as bars (first `period-1` entries are None).
    """
    trs = [None]
    for i in range(1, len(bars)):
        high = bars[i]['high']
        low = bars[i]['low']
        prev_close = bars[i - 1]['close']
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)

    atrs = [None] * len(bars)
    # First ATR = simple average of first `period` TRs
    if len(trs) >= period + 1:
        first_valid = sum(trs[1:period + 1]) / period
        atrs[period] = first_valid
        for i in range(period + 1, len(bars)):
            atrs[i] = (atrs[i - 1] * (period - 1) + trs[i]) / period

    return atrs


# ---------------------------------------------------------------------------
# HTF Bias — EMA(8/34) trend
# ---------------------------------------------------------------------------

def _compute_ema(bars: list[dict], period: int) -> list[Optional[float]]:
    """Wilder-style EMA over 'close'. Returns list aligned with bars."""
    closes = [b['close'] for b in bars]
    emas: list[Optional[float]] = [None] * len(closes)
    if len(closes) < period:
        return emas
    emas[period - 1] = sum(closes[:period]) / period
    k = 2.0 / (period + 1)
    for i in range(period, len(closes)):
        emas[i] = closes[i] * k + emas[i - 1] * (1 - k)
    return emas


def compute_htf_bias(bars: list[dict]) -> list[Optional[str]]:
    """
    EMA(8) vs EMA(34) bias for each bar.
    Returns 'bullish' | 'bearish' | 'neutral' per bar (None if insufficient data).
    """
    ema8 = _compute_ema(bars, 8)
    ema34 = _compute_ema(bars, 34)
    biases: list[Optional[str]] = []
    for e8, e34 in zip(ema8, ema34):
        if e8 is None or e34 is None:
            biases.append(None)
        elif e8 > e34:
            biases.append('bullish')
        elif e8 < e34:
            biases.append('bearish')
        else:
            biases.append('neutral')
    return biases


# ---------------------------------------------------------------------------
# FVG detection
# ---------------------------------------------------------------------------

def detect_fvgs(bars: list[dict], min_gap_atr: float = 0.3) -> list[FVG]:
    """
    Scan bars for Fair Value Gaps.

    Bullish FVG: bars[i-2].high < bars[i].low  (gap between candle i-2 top and candle i bottom)
    Bearish FVG: bars[i-2].low  > bars[i].high (gap between candle i-2 bottom and candle i top)

    min_gap_atr: minimum gap size expressed as fraction of the bar's ATR. Filters micro-gaps.
    """
    atrs = _compute_atr(bars)
    fvgs: list[FVG] = []

    for i in range(2, len(bars)):
        atr = atrs[i]
        if atr is None or atr == 0:
            continue

        bar_time = _parse_bar_time(bars[i]['time'])

        # Bullish FVG
        gap_high = bars[i]['low']
        gap_low = bars[i - 2]['high']
        if gap_high > gap_low and (gap_high - gap_low) >= min_gap_atr * atr:
            fvgs.append(FVG(
                direction='bullish',
                high=gap_high,
                low=gap_low,
                bar_index=i,
                bar_time=bar_time,
            ))

        # Bearish FVG
        gap_high2 = bars[i - 2]['low']
        gap_low2 = bars[i]['high']
        if gap_high2 > gap_low2 and (gap_high2 - gap_low2) >= min_gap_atr * atr:
            fvgs.append(FVG(
                direction='bearish',
                high=gap_high2,
                low=gap_low2,
                bar_index=i,
                bar_time=bar_time,
            ))

    return fvgs


def mark_fvg_mitigations(bars: list[dict], fvgs: list[FVG]) -> None:
    """
    In-place: mark each FVG as mitigated when price re-enters its zone.
    A bullish FVG is mitigated when a subsequent close dips below its high.
    A bearish FVG is mitigated when a subsequent close rises above its low.
    """
    for fvg in fvgs:
        for i in range(fvg.bar_index + 1, len(bars)):
            close = bars[i]['close']
            if fvg.direction == 'bullish' and close < fvg.high:
                fvg.mitigated = True
                fvg.mitigation_index = i
                break
            elif fvg.direction == 'bearish' and close > fvg.low:
                fvg.mitigated = True
                fvg.mitigation_index = i
                break


# ---------------------------------------------------------------------------
# Order Block detection
# ---------------------------------------------------------------------------

def detect_order_blocks(bars: list[dict], impulse_atr_threshold: float = 1.5) -> list[OrderBlock]:
    """
    Detect Order Blocks: the last opposing candle before an impulsive expansion.

    An OB is valid when:
    - A candle (i) is followed by an impulse move of >= impulse_atr_threshold × ATR
    - The impulse closes at least 2 bars later in the same direction
    - The OB candle is OPPOSITE to the impulse direction (supply/demand zone origin)
    """
    atrs = _compute_atr(bars)
    obs: list[OrderBlock] = []
    avg_body = _avg_body_size(bars)

    for i in range(1, len(bars) - 2):
        atr = atrs[i]
        if atr is None or atr == 0:
            continue

        # Look at the move from bar i to bar i+1
        move = bars[i + 1]['close'] - bars[i]['open']
        move_size = abs(move)

        if move_size < impulse_atr_threshold * atr:
            continue

        direction = 'bullish' if move > 0 else 'bearish'
        # OB is the candle opposing the impulse
        ob_direction = 'bullish' if direction == 'bullish' else 'bearish'

        bar = bars[i]
        bar_time = _parse_bar_time(bar['time'])

        body_high = max(bar['open'], bar['close'])
        body_low = min(bar['open'], bar['close'])

        # Skip doji (body < 20% of average — essentially no OB)
        if avg_body > 0 and (body_high - body_low) < 0.20 * avg_body:
            continue

        obs.append(OrderBlock(
            direction=ob_direction,
            ob_high=bar['high'],
            ob_low=bar['low'],
            ob_body_high=body_high,
            ob_body_low=body_low,
            bar_index=i,
            bar_time=bar_time,
            impulse_size=move_size / atr,
        ))

    return obs


def _avg_body_size(bars: list[dict]) -> float:
    bodies = [abs(b['close'] - b['open']) for b in bars]
    return sum(bodies) / max(len(bodies), 1)


# ---------------------------------------------------------------------------
# Fibonacci Golden Pocket
# ---------------------------------------------------------------------------

def detect_fib_golden_pocket(bars: list[dict], swing_lookback: int = 50) -> list[FibLevel]:
    """
    Find the most recent significant swing high/low in the last `swing_lookback` bars
    and compute the golden pocket (0.618–0.650 retracement).

    Returns one FibLevel per detected swing.
    A swing high is a local maximum flanked by lower bars on both sides (5-bar window).
    A swing low is a local minimum flanked by higher bars on both sides (5-bar window).
    """
    fibs: list[FibLevel] = []
    window = 5  # bars each side for pivot detection
    scan_start = max(window, len(bars) - swing_lookback)

    swings_high: list[tuple[int, float]] = []
    swings_low: list[tuple[int, float]] = []

    for i in range(scan_start + window, len(bars) - window):
        is_swing_high = all(
            bars[i]['high'] >= bars[j]['high']
            for j in range(i - window, i + window + 1) if j != i
        )
        is_swing_low = all(
            bars[i]['low'] <= bars[j]['low']
            for j in range(i - window, i + window + 1) if j != i
        )
        if is_swing_high:
            swings_high.append((i, bars[i]['high']))
        if is_swing_low:
            swings_low.append((i, bars[i]['low']))

    if not swings_high or not swings_low:
        return fibs

    # Bullish retracement: swing low → swing high, price pulls back into GP
    if swings_low and swings_high:
        sl_idx, sl_price = swings_low[-1]
        sh_idx, sh_price = swings_high[-1]

        if sl_idx < sh_idx and sh_price > sl_price:
            rng = sh_price - sl_price
            fibs.append(FibLevel(
                direction='bullish',
                gp_high=sh_price - 0.618 * rng,   # 0.618 = upper bound (shallower)
                gp_low=sh_price - 0.650 * rng,    # 0.650 = lower bound (deeper)
                swing_high=sh_price,
                swing_low=sl_price,
                swing_start_index=sl_idx,
                swing_end_index=sh_idx,
            ))

        # Bearish retracement: swing high → swing low, price pulls back into GP
        if sh_idx < sl_idx and sh_price > sl_price:
            rng = sh_price - sl_price
            fibs.append(FibLevel(
                direction='bearish',
                gp_high=sl_price + 0.650 * rng,   # 0.650 deeper (higher retracement up)
                gp_low=sl_price + 0.618 * rng,    # 0.618 shallower
                swing_high=sh_price,
                swing_low=sl_price,
                swing_start_index=sh_idx,
                swing_end_index=sl_idx,
            ))

    return fibs


# ---------------------------------------------------------------------------
# CVD Proxy — OHLCV money-flow divergence
# ---------------------------------------------------------------------------

def compute_cvd_proxy(bars: list[dict]) -> list[CVDBar]:
    """
    Approximate CVD from OHLCV using Money Flow Volume:

        money_flow_delta = ((2*close - high - low) / (high - low)) * tick_volume

    A close near the top of the bar = strong buying pressure (positive delta).
    A close near the bottom = strong selling pressure (negative delta).
    Cumulative sum = synthetic CVD.

    Division by zero protection: when high == low (doji), delta = 0.
    """
    cumulative = 0.0
    result: list[CVDBar] = []

    for i, bar in enumerate(bars):
        h, l, c = bar['high'], bar['low'], bar['close']
        vol = bar.get('tick_volume', bar.get('volume', 0))

        bar_time = _parse_bar_time(bar['time'])

        if h == l:
            mf = 0.0
        else:
            mf = ((2 * c - h - l) / (h - l)) * vol

        cumulative += mf
        result.append(CVDBar(
            bar_index=i,
            bar_time=bar_time,
            close=c,
            money_flow=mf,
            cumulative=cumulative,
        ))

    return result


def detect_cvd_divergence(
    bars: list[dict],
    cvd_bars: list[CVDBar],
    lookback: int = 10,
    min_price_move_pct: float = 0.003,
) -> list[tuple[int, str]]:
    """
    Detect CVD divergence vs price over a rolling `lookback` window.

    Bullish divergence: price makes lower low, CVD makes higher low → buyers absorbing.
    Bearish divergence: price makes higher high, CVD makes lower high → sellers distributing.

    Returns list of (bar_index, 'bullish'|'bearish') tuples.
    """
    divergences: list[tuple[int, str]] = []

    for i in range(lookback, len(bars)):
        window_bars = bars[i - lookback: i + 1]
        window_cvd = cvd_bars[i - lookback: i + 1]

        price_low_idx = min(range(len(window_bars)), key=lambda x: window_bars[x]['low'])
        price_high_idx = max(range(len(window_bars)), key=lambda x: window_bars[x]['high'])

        # Price range filter — ignore micro moves
        price_range = window_bars[-1]['high'] - window_bars[-1]['low']
        if price_range / max(window_bars[-1]['close'], 1) < min_price_move_pct:
            continue

        # Bullish divergence: price LL, CVD HL
        if price_low_idx == len(window_bars) - 1:
            first_cvd_low = window_cvd[0].cumulative
            last_cvd_low = window_cvd[-1].cumulative
            price_first_low = window_bars[0]['low']
            price_last_low = window_bars[-1]['low']
            if price_last_low < price_first_low and last_cvd_low > first_cvd_low:
                divergences.append((i, 'bullish'))

        # Bearish divergence: price HH, CVD LH
        if price_high_idx == len(window_bars) - 1:
            first_cvd_high = window_cvd[0].cumulative
            last_cvd_high = window_cvd[-1].cumulative
            price_first_high = window_bars[0]['high']
            price_last_high = window_bars[-1]['high']
            if price_last_high > price_first_high and last_cvd_high < first_cvd_high:
                divergences.append((i, 'bearish'))

    return divergences


# ---------------------------------------------------------------------------
# Confluence scoring (lightweight version for pattern_detector)
# ---------------------------------------------------------------------------

def score_confluence(
    direction: str,
    htf_bias: Optional[str],
    fvg: Optional[FVG],
    ob: Optional[OrderBlock],
    fib: Optional[FibLevel],
    cvd_divergence: bool,
    session: str,
) -> float:
    """
    Score 0.0–1.0 representing how well all signals align.

    Weights:
      HTF bias alignment   0.30
      FVG (unmitigated)    0.25
      CVD divergence       0.25
      OB alignment         0.10
      Fib golden pocket    0.10
    Session bonus: LONDON/NY_OVERLAP add 0.05 (metals/forex)
    """
    score = 0.0

    if htf_bias == direction:
        score += 0.30

    if fvg and not fvg.mitigated and fvg.direction == direction:
        score += 0.25

    if cvd_divergence:
        score += 0.25

    if ob and ob.direction == direction and ob.valid:
        score += 0.10

    if fib and fib.direction == direction:
        score += 0.10

    if session in ('LONDON', 'NY_OVERLAP'):
        score = min(1.0, score + 0.05)

    return round(score, 3)


# ---------------------------------------------------------------------------
# Price-at-FVG entry detector (the actual setup trigger)
# ---------------------------------------------------------------------------

def find_setups(
    symbol: str,
    bars: list[dict],
    min_confluence: float = 0.55,
) -> list[Setup]:
    """
    Scan bars for complete setups: price returning to an unmitigated FVG
    while CVD divergence + HTF bias confirm direction.

    Returns setups sorted by trigger time (oldest first).
    """
    try:
        from app.quant.knowledge.geo_events import get_nearby_events, get_era_sentiment
    except ImportError:
        from quant.knowledge.geo_events import get_nearby_events, get_era_sentiment

    atrs = _compute_atr(bars)
    biases = compute_htf_bias(bars)
    fvgs = detect_fvgs(bars)
    mark_fvg_mitigations(bars, fvgs)
    obs = detect_order_blocks(bars)
    fibs = detect_fib_golden_pocket(bars)
    cvd_bars = compute_cvd_proxy(bars)
    divergences_list = detect_cvd_divergence(bars, cvd_bars)
    divergence_set = {(idx, d) for idx, d in divergences_list}

    setups: list[Setup] = []

    for i in range(34, len(bars)):  # start after EMA(34) warmup
        bar = bars[i]
        bar_time = _parse_bar_time(bar['time'])

        atr = atrs[i]
        if not atr:
            continue

        htf_bias = biases[i]
        session = _classify_session(bar_time)

        # Check each unmitigated FVG older than this bar
        for fvg in fvgs:
            if fvg.bar_index >= i:
                continue
            if fvg.mitigated and fvg.mitigation_index is not None and fvg.mitigation_index <= i:
                continue

            direction = fvg.direction
            # Price must have returned to the FVG zone
            price_in_fvg = (bar['low'] <= fvg.high) and (bar['high'] >= fvg.low)
            if not price_in_fvg:
                continue

            cvd_div = (i, direction) in divergence_set

            # Find nearest OB on same side
            nearest_ob = _find_nearest_ob(obs, i, direction, atr)
            # Find nearest Fib
            nearest_fib = _find_nearest_fib(fibs, direction, bar['close'], atr)

            conf = score_confluence(direction, htf_bias, fvg, nearest_ob, nearest_fib, cvd_div, session)
            if conf < min_confluence:
                continue

            entry = (fvg.high + fvg.low) / 2  # FVG midpoint

            # Geo event enrichment
            nearby_events = get_nearby_events(bar_time, window_hours=24)
            era_sentiment = get_era_sentiment(bar_time)

            setups.append(Setup(
                symbol=symbol,
                direction=direction,
                trigger_bar_index=i,
                trigger_bar_time=bar_time,
                entry_price=entry,
                atr=atr,
                htf_bias=htf_bias or 'neutral',
                session=session,
                fvg=fvg,
                order_block=nearest_ob,
                fib=nearest_fib,
                cvd_divergence=cvd_div,
                confluence_score=conf,
                nearby_geo_events=nearby_events,
                era_sentiment=era_sentiment,
            ))

    # Deduplicate: if multiple FVGs trigger on same bar, keep highest confluence
    seen: dict[int, Setup] = {}
    for s in setups:
        key = (s.trigger_bar_index, s.direction)
        if key not in seen or s.confluence_score > seen[key].confluence_score:
            seen[key] = s  # type: ignore[assignment]

    return sorted(seen.values(), key=lambda x: x.trigger_bar_index)


def _find_nearest_ob(
    obs: list[OrderBlock],
    bar_index: int,
    direction: str,
    atr: float,
) -> Optional[OrderBlock]:
    """Return the most recent valid OB older than bar_index matching direction."""
    candidates = [
        ob for ob in obs
        if ob.direction == direction and ob.bar_index < bar_index and ob.valid
    ]
    return candidates[-1] if candidates else None


def _find_nearest_fib(
    fibs: list[FibLevel],
    direction: str,
    current_price: float,
    atr: float,
) -> Optional[FibLevel]:
    """Return Fib GP if current price is within the golden pocket zone (±0.5 ATR)."""
    for fib in reversed(fibs):
        if fib.direction != direction:
            continue
        gp_low = min(fib.gp_low, fib.gp_high)
        gp_high = max(fib.gp_low, fib.gp_high)
        # Price is within GP zone or within 0.5 ATR of it
        if (gp_low - 0.5 * atr) <= current_price <= (gp_high + 0.5 * atr):
            return fib
    return None
