"""
ICC Detector — Imbalance, Confluence, Confirmation framework.

Implements Trades by Sci's ICC method with ICT structural foundations:

  I = Imbalance  — Fair Value Gap on H4/H1 (the POI anchor)
  C = Confluence — OB at same level, premium/discount zone, HTF BOS/CHoCH
  C = Confirmation — CVD divergence at the POI (handled by entry.py / tick consumer)

The core problem it solves:
  The existing FVG/OB detection runs on M15 bars — there's almost always *some*
  FVG somewhere on M15, so fvg_present=True ~80% of the time and carries no
  predictive signal. This module detects ONLY H4 and H1 structural POIs and checks
  whether current price is actually inside or approaching them.

Key concepts:
- Stacked POI: FVG + OB overlap at the same H4/H1 price level — two independent
  institutional decisions produced the same zone, highest conviction entry.
- Premium/Discount: buys from discount zones (below 50% fib of last swing),
  sells from premium — aligned with mean-reversion bias of institutional flow.
- Bar age cap: only consider POIs formed within the last 30 H4 bars (~5 trading
  days) or 48 H1 bars (~2 days) — older zones lose their magnetic pull.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger('icc_detector')

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

# How close price must be to the POI edge to count as "at" the zone
POI_TOLERANCE_ATR = 0.30      # 30% of ATR

# Max age for an active (unmitigated) POI to still be considered
H4_MAX_AGE_BARS = 30          # ~5 trading days on H4
H1_MAX_AGE_BARS = 48          # ~2 trading days on H1

# Overlap required for two zones to be "stacked" (fraction of the smaller zone width)
STACK_OVERLAP_MIN_FRACTION = 0.20


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class POIZone:
    """A single higher-timeframe Point of Interest zone."""
    direction: str        # 'bullish' or 'bearish'
    top: float
    bottom: float
    zone_type: str        # 'fvg', 'ob', 'stacked_fvg_ob'
    timeframe: str        # 'H4' or 'H1'
    bar_age: int          # Bars since formation (lower = fresher)

    @property
    def midpoint(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def width(self) -> float:
        return self.top - self.bottom


@dataclass
class ICCContext:
    """Full ICC analysis result for a symbol + direction."""
    symbol: str
    direction: str                          # 'long' or 'short'

    # Core ICC outputs — fed directly into confluence_scorer
    price_at_htf_fvg: bool = False          # Price inside/at H4 or H1 FVG
    price_at_htf_ob: bool = False           # Price inside/at H4 or H1 OB
    htf_poi_stacked: bool = False           # FVG + OB overlap at same HTF level
    htf_poi_timeframe: str = 'none'         # 'H4', 'H1', or 'none'

    # Market structure from H4 BOS / CHoCH
    structure_bias: str = 'neutral'         # 'bullish', 'bearish', 'neutral'
    last_structure_type: str = 'none'       # 'BOS', 'CHOCH', 'none'

    # Premium / discount context
    premium_discount: str = 'equilibrium'  # 'premium', 'discount', 'equilibrium'
    poi_in_correct_zone: bool = False       # Buy from discount, sell from premium

    # Fibonacci golden pocket (0.618 retracement of last H4 swing)
    fib_alignment: bool = False             # POI/price at the 0.618 golden pocket
    fib_level: float = 0.0                  # Actual fib level hit (0.382, 0.5, 0.618, 0.786)
    fib_golden_pocket_low: float = 0.0      # Golden pocket zone bottom (0.618 retracement)
    fib_golden_pocket_high: float = 0.0     # Golden pocket zone top (0.65 retracement)

    # Volume Profile — Point of Control
    at_poc: bool = False                    # Price/POI near H4 Volume Profile POC
    poc_level: float = 0.0                  # POC price (highest-volume H4 price level)

    # Best POI found (None if none found / none near price)
    nearest_poi: Optional[POIZone] = None

    # Human-readable quality label
    icc_score: int = 0                      # 0–7, used as bonus in confluence
    icc_label: str = 'no HTF POI'


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_htf_poi(
    symbol: str,
    direction: str,
    current_price: float,
    atr_val: float,
) -> ICCContext:
    """Detect higher-timeframe POIs and check proximity to current price.

    Fetches H4 first (primary) and H1 as fallback if no H4 POI is found.
    All SMC detection is fail-open — any exception returns a conservative
    context with no POI found so the pipeline never breaks.

    Args:
        symbol:        Trading pair e.g. 'EURUSD'
        direction:     'BUY' or 'SELL' (or 'long'/'short')
        current_price: Current mid price (bid for sell, ask for buy)
        atr_val:       ATR value at the signal bar, used for proximity tolerance

    Returns:
        ICCContext — all fields default to False/neutral on errors.
    """
    dir_norm = 'long' if direction in ('BUY', 'buy', 'long') else 'short'
    ctx = ICCContext(symbol=symbol, direction=dir_norm)

    if atr_val is None or atr_val <= 0 or current_price is None or current_price <= 0:
        return ctx

    try:
        from app.utils.api.data import fetch_data_pos_cached
        from app.utils.constants import MT5Timeframe
        from app.quant.indicators.smc_detector import (
            detect_fair_value_gaps,
            detect_order_blocks,
            detect_market_structure,
        )

        # ----------------------------------------------------------------
        # H4 analysis (primary)
        # ----------------------------------------------------------------
        h4_df = fetch_data_pos_cached(symbol, MT5Timeframe.H4, 80)
        if h4_df is None or len(h4_df) < 20:
            logger.debug(f"ICC {symbol}: insufficient H4 data ({len(h4_df) if h4_df is not None else 0} bars)")
            return ctx

        # Market structure bias (BOS/CHoCH)
        ms_df = detect_market_structure(h4_df)
        ctx.structure_bias, ctx.last_structure_type = _get_structure_bias(ms_df)

        # Premium/discount zone
        ctx.premium_discount = _get_premium_discount(h4_df, current_price)

        # H4 FVGs and OBs aligned with trade direction
        h4_fvg_df = detect_fair_value_gaps(h4_df)
        h4_ob_df = detect_order_blocks(h4_df)

        h4_fvgs = _extract_active_pois(h4_fvg_df, 'fvg', 'H4', dir_norm, H4_MAX_AGE_BARS)
        h4_obs = _extract_active_pois(h4_ob_df, 'ob', 'H4', dir_norm, H4_MAX_AGE_BARS)
        h4_stacked = _find_stacked_zones(h4_fvgs, h4_obs)

        # ----------------------------------------------------------------
        # H1 analysis (fallback — only if no H4 POI found near price)
        # ----------------------------------------------------------------
        h1_fvgs, h1_obs, h1_stacked = [], [], []
        if not (h4_stacked or h4_fvgs or h4_obs):
            try:
                h1_df = fetch_data_pos_cached(symbol, MT5Timeframe.H1, 60)
                if h1_df is not None and len(h1_df) >= 20:
                    h1_fvg_df = detect_fair_value_gaps(h1_df)
                    h1_ob_df = detect_order_blocks(h1_df)
                    h1_fvgs = _extract_active_pois(h1_fvg_df, 'fvg', 'H1', dir_norm, H1_MAX_AGE_BARS)
                    h1_obs = _extract_active_pois(h1_ob_df, 'ob', 'H1', dir_norm, H1_MAX_AGE_BARS)
                    h1_stacked = _find_stacked_zones(h1_fvgs, h1_obs)
            except Exception as e:
                logger.debug(f"ICC {symbol}: H1 fallback failed: {e}")

        # ----------------------------------------------------------------
        # Find nearest POI to current price
        # Priority: H4 stacked > H4 FVG > H4 OB > H1 stacked > H1 FVG > H1 OB
        # ----------------------------------------------------------------
        candidate_groups = [h4_stacked, h4_fvgs, h4_obs, h1_stacked, h1_fvgs, h1_obs]
        for group in candidate_groups:
            for poi in group:
                if _price_at_poi(current_price, poi, atr_val):
                    ctx.nearest_poi = poi
                    ctx.htf_poi_timeframe = poi.timeframe
                    if poi.zone_type in ('fvg', 'stacked_fvg_ob'):
                        ctx.price_at_htf_fvg = True
                    if poi.zone_type in ('ob', 'stacked_fvg_ob'):
                        ctx.price_at_htf_ob = True
                    if poi.zone_type == 'stacked_fvg_ob':
                        ctx.htf_poi_stacked = True
                    break
            if ctx.nearest_poi is not None:
                break

        # Premium/discount alignment
        ctx.poi_in_correct_zone = _poi_zone_aligned(dir_norm, ctx.premium_discount)

        # --- Fibonacci Golden Pocket (0.618 retracement of last H4 swing) ---
        try:
            fib_hit, fib_lvl, gp_low, gp_high = _get_golden_pocket(h4_df, dir_norm, current_price)
            ctx.fib_alignment = fib_hit
            ctx.fib_level = fib_lvl
            ctx.fib_golden_pocket_low = gp_low
            ctx.fib_golden_pocket_high = gp_high
        except Exception as e:
            logger.debug(f"ICC {symbol}: Fibonacci failed: {e}")

        # --- Volume Profile POC (H4 tick_volume distribution) ---
        try:
            poc = _compute_volume_poc(h4_df)
            if poc > 0:
                ctx.poc_level = poc
                # POC is relevant if within 1.0 ATR of current price or nearest POI
                ctx.at_poc = abs(current_price - poc) <= (atr_val * 1.0)
        except Exception as e:
            logger.debug(f"ICC {symbol}: Volume POC failed: {e}")

        # ICC quality score and label
        ctx.icc_score, ctx.icc_label = _compute_icc_score(ctx)

        logger.debug(
            f"ICC {symbol} {dir_norm}: score={ctx.icc_score} tf={ctx.htf_poi_timeframe} "
            f"poi={ctx.nearest_poi.zone_type if ctx.nearest_poi else 'none'} "
            f"stacked={ctx.htf_poi_stacked} struct={ctx.structure_bias}/{ctx.last_structure_type} "
            f"zone={ctx.premium_discount} correct_zone={ctx.poi_in_correct_zone} "
            f"label={ctx.icc_label}"
        )

    except Exception as e:
        logger.debug(f"ICC detection failed for {symbol}: {e}")

    return ctx


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_active_pois(
    df: pd.DataFrame,
    zone_type: str,
    timeframe: str,
    direction: str,
    max_age_bars: int,
) -> List[POIZone]:
    """Extract unmitigated, direction-aligned POIs from a detector DataFrame.

    Returns a list sorted by bar_age (freshest first) so the caller can
    iterate priority order naturally.
    """
    pois: List[POIZone] = []

    if df is None or len(df) == 0:
        return pois

    val_col = 'FVG' if zone_type == 'fvg' else 'OB'
    if val_col not in df.columns:
        return pois

    total = len(df)
    trade_dir_poi = 'bullish' if direction == 'long' else 'bearish'

    for i in range(total):
        val = df[val_col].iloc[i]
        if pd.isna(val) or val == 0:
            continue

        # Skip mitigated zones
        mitigated = df['MitigatedIndex'].iloc[i] if 'MitigatedIndex' in df.columns else float('nan')
        if not pd.isna(mitigated):
            continue

        # Direction must match trade direction
        poi_dir = 'bullish' if val == 1 else 'bearish'
        if poi_dir != trade_dir_poi:
            continue

        # Age check (only recent POIs)
        bar_age = total - 1 - i
        if bar_age > max_age_bars:
            continue

        top_val = df['Top'].iloc[i] if 'Top' in df.columns else float('nan')
        bot_val = df['Bottom'].iloc[i] if 'Bottom' in df.columns else float('nan')
        if pd.isna(top_val) or pd.isna(bot_val):
            continue

        pois.append(POIZone(
            direction=poi_dir,
            top=float(top_val),
            bottom=float(bot_val),
            zone_type=zone_type,
            timeframe=timeframe,
            bar_age=bar_age,
        ))

    pois.sort(key=lambda p: p.bar_age)
    return pois


def _find_stacked_zones(
    fvgs: List[POIZone],
    obs: List[POIZone],
) -> List[POIZone]:
    """Return zones where an FVG and OB overlap — the stacked POI.

    Overlap is only counted if it covers at least STACK_OVERLAP_MIN_FRACTION
    of the smaller zone's width, preventing trivial single-pip overlaps.
    """
    stacked: List[POIZone] = []

    for fvg in fvgs:
        for ob in obs:
            overlap_top = min(fvg.top, ob.top)
            overlap_bottom = max(fvg.bottom, ob.bottom)
            if overlap_top <= overlap_bottom:
                continue  # No overlap

            overlap_width = overlap_top - overlap_bottom
            min_zone_width = min(fvg.width, ob.width)
            if min_zone_width <= 0:
                continue
            if (overlap_width / min_zone_width) < STACK_OVERLAP_MIN_FRACTION:
                continue  # Overlap too thin

            stacked.append(POIZone(
                direction=fvg.direction,
                top=overlap_top,
                bottom=overlap_bottom,
                zone_type='stacked_fvg_ob',
                timeframe=fvg.timeframe,
                bar_age=min(fvg.bar_age, ob.bar_age),
            ))

    stacked.sort(key=lambda p: p.bar_age)
    return stacked


def _price_at_poi(price: float, poi: POIZone, atr_val: float) -> bool:
    """True if price is inside the zone or within tolerance ATR of the edge.

    Bullish FVG: price should be pulling back into it from above (price >= bottom).
    Bearish FVG: price should be rallying back into it from below (price <= top).
    Tolerance allows entries when price is approaching but not yet inside.
    """
    # Inside the zone
    if poi.bottom <= price <= poi.top:
        return True

    tolerance = atr_val * POI_TOLERANCE_ATR

    if poi.direction == 'bullish':
        # Approaching from above — price slightly above the FVG top
        return (poi.top < price <= poi.top + tolerance)
    else:
        # Approaching from below — price slightly below the FVG bottom
        return (poi.bottom - tolerance <= price < poi.bottom)


def _get_structure_bias(ms_df: pd.DataFrame) -> Tuple[str, str]:
    """Extract the bias from the most recent BOS/CHoCH event on the HTF.

    CHoCH takes precedence over BOS if they appear at the same bar (reversal
    signal is stronger). Scans from the end of the DataFrame backwards.
    """
    if ms_df is None or len(ms_df) == 0:
        return 'neutral', 'none'

    for i in range(len(ms_df) - 1, -1, -1):
        choch = ms_df['CHOCH'].iloc[i] if 'CHOCH' in ms_df.columns else float('nan')
        bos = ms_df['BOS'].iloc[i] if 'BOS' in ms_df.columns else float('nan')

        if not pd.isna(choch) and choch != 0:
            return ('bullish' if choch == 1 else 'bearish'), 'CHOCH'
        if not pd.isna(bos) and bos != 0:
            return ('bullish' if bos == 1 else 'bearish'), 'BOS'

    return 'neutral', 'none'


def _get_premium_discount(df: pd.DataFrame, current_price: float) -> str:
    """Classify price as premium, discount, or equilibrium.

    Uses the 50% Fibonacci level of the last 50 H4 bars (the 'institutional
    equilibrium' per ICT). Buys from discount, sells from premium.
    """
    high_col = 'high' if 'high' in df.columns else 'High'
    low_col = 'low' if 'low' in df.columns else 'Low'

    lookback = min(50, len(df))
    recent_high = float(df[high_col].iloc[-lookback:].max())
    recent_low = float(df[low_col].iloc[-lookback:].min())
    midpoint = (recent_high + recent_low) / 2

    # Small buffer (0.1%) prevents oscillating on flat markets
    if current_price > midpoint * 1.001:
        return 'premium'
    if current_price < midpoint * 0.999:
        return 'discount'
    return 'equilibrium'


def _get_golden_pocket(
    df: pd.DataFrame,
    direction: str,
    current_price: float,
) -> Tuple[bool, float, float, float]:
    """Compute the 0.618 Fibonacci golden pocket from the last significant H4 swing.

    The golden pocket is the 0.618-0.650 retracement zone — the most
    statistically respected Fibonacci level across all markets (derived from
    the inverse of the Golden Ratio φ=1.618).

    For LONG: last swing low → swing high. Golden pocket = high - 0.618*(high-low)
              to high - 0.650*(high-low). Price pulling back into this zone = long entry.
    For SHORT: last swing high → swing low. Golden pocket = low + 0.618*(high-low)
               to low + 0.650*(high-low). Price bouncing into this zone = short entry.

    Returns:
        (is_aligned, fib_level_hit, pocket_low, pocket_high)
        fib_level_hit is the nearest fib level: 0.382, 0.5, 0.618, or 0.786.
    """
    high_col = 'high' if 'high' in df.columns else 'High'
    low_col = 'low' if 'low' in df.columns else 'Low'

    h = df[high_col].values.astype(float)
    l = df[low_col].values.astype(float)

    # Find swing highs and lows using the existing helper (lookback=5 on H4)
    sh_idx, sl_idx = _find_swings_simple(h, l, lookback=5)

    if not sh_idx or not sl_idx:
        return False, 0.0, 0.0, 0.0

    if direction == 'long':
        # Find the most recent swing high, then the swing low that preceded it
        sh = sh_idx[-1]  # Most recent swing high
        # Last swing low before the swing high
        sl_before = [i for i in sl_idx if i < sh]
        if not sl_before:
            return False, 0.0, 0.0, 0.0
        sl = sl_before[-1]
        swing_high = h[sh]
        swing_low = l[sl]
        if swing_high <= swing_low:
            return False, 0.0, 0.0, 0.0

        rng = swing_high - swing_low
        # Fib levels (retracement from high back toward low)
        levels = {
            0.382: swing_high - 0.382 * rng,
            0.500: swing_high - 0.500 * rng,
            0.618: swing_high - 0.618 * rng,
            0.650: swing_high - 0.650 * rng,
            0.786: swing_high - 0.786 * rng,
        }
        pocket_high = levels[0.618]
        pocket_low = levels[0.650]

    else:  # short
        # Find most recent swing low, then the swing high that preceded it
        sl = sl_idx[-1]
        sh_before = [i for i in sh_idx if i < sl]
        if not sh_before:
            return False, 0.0, 0.0, 0.0
        sh = sh_before[-1]
        swing_high = h[sh]
        swing_low = l[sl]
        if swing_high <= swing_low:
            return False, 0.0, 0.0, 0.0

        rng = swing_high - swing_low
        # Fib levels (retracement from low back toward high)
        levels = {
            0.382: swing_low + 0.382 * rng,
            0.500: swing_low + 0.500 * rng,
            0.618: swing_low + 0.618 * rng,
            0.650: swing_low + 0.650 * rng,
            0.786: swing_low + 0.786 * rng,
        }
        pocket_low = levels[0.618]
        pocket_high = levels[0.650]

    # Is current price inside or within a small buffer of the golden pocket?
    # Buffer: 15% of pocket width to catch near-misses
    width = abs(pocket_high - pocket_low)
    buf = width * 0.15 + 1e-8  # Prevent zero-width issues

    in_pocket = (pocket_low - buf) <= current_price <= (pocket_high + buf)

    if not in_pocket:
        # Find the nearest fib level to current price for logging
        nearest_fib = min(
            (k for k in levels if k != 0.650),
            key=lambda k: abs(levels[k] - current_price)
        )
        return False, nearest_fib, pocket_low, pocket_high

    return True, 0.618, pocket_low, pocket_high


def _find_swings_simple(
    high: np.ndarray,
    low: np.ndarray,
    lookback: int = 5,
) -> Tuple[List[int], List[int]]:
    """Lightweight swing high/low finder (same logic as mtf_analyzer)."""
    n = len(high)
    sh_idx: List[int] = []
    sl_idx: List[int] = []

    for i in range(lookback, n - lookback):
        window_h = high[i - lookback:i + lookback + 1]
        if high[i] == window_h.max() and np.sum(window_h == high[i]) == 1:
            sh_idx.append(i)

        window_l = low[i - lookback:i + lookback + 1]
        if low[i] == window_l.min() and np.sum(window_l == low[i]) == 1:
            sl_idx.append(i)

    return sh_idx, sl_idx


def _compute_volume_poc(df: pd.DataFrame, num_buckets: int = 40) -> float:
    """Identify the Volume Profile Point of Control (POC) from OHLCV bars.

    POC = the price level with the highest cumulative tick_volume, i.e., where
    the most institutional trading activity occurred. This is a statistically
    meaningful support/resistance level — price gravitates back to POC because
    unfilled orders cluster there.

    Uses tick_volume (MT5 proxy for real volume) from the H4 bars.
    Returns the POC mid-price. Returns 0.0 if volume data unavailable.
    """
    high_col = 'high' if 'high' in df.columns else 'High'
    low_col = 'low' if 'low' in df.columns else 'Low'
    vol_col = None
    for c in ('tick_volume', 'volume', 'Volume', 'real_volume'):
        if c in df.columns:
            vol_col = c
            break

    if vol_col is None:
        return 0.0

    h = df[high_col].values.astype(float)
    l = df[low_col].values.astype(float)
    vol = df[vol_col].values.astype(float)

    price_max = h.max()
    price_min = l.min()
    if price_max <= price_min:
        return 0.0

    # Build price buckets
    bucket_size = (price_max - price_min) / num_buckets
    if bucket_size <= 0:
        return 0.0

    volume_by_bucket = np.zeros(num_buckets)

    for i in range(len(df)):
        # Distribute bar volume across all buckets the bar's range touches
        bar_low_bucket = int((l[i] - price_min) / bucket_size)
        bar_high_bucket = int((h[i] - price_min) / bucket_size)
        bar_low_bucket = max(0, min(bar_low_bucket, num_buckets - 1))
        bar_high_bucket = max(0, min(bar_high_bucket, num_buckets - 1))

        n_buckets_touched = bar_high_bucket - bar_low_bucket + 1
        vol_per_bucket = vol[i] / max(n_buckets_touched, 1)

        for b in range(bar_low_bucket, bar_high_bucket + 1):
            volume_by_bucket[b] += vol_per_bucket

    poc_bucket = int(np.argmax(volume_by_bucket))
    poc_price = price_min + (poc_bucket + 0.5) * bucket_size

    return float(poc_price)


def _poi_zone_aligned(direction: str, premium_discount: str) -> bool:
    """Confirm POI is in the institutionally correct zone.

    ICT rule: buy setups should originate from discount, sell setups from premium.
    Equilibrium is neutral (not penalized, not rewarded).
    """
    if direction == 'long' and premium_discount == 'discount':
        return True
    if direction == 'short' and premium_discount == 'premium':
        return True
    return False


def _compute_icc_score(ctx: ICCContext) -> Tuple[int, str]:
    """Score the ICC setup quality from 0 to 7.

    Breakdown:
      +2  H4 POI (FVG, OB, or stacked)    / +1 if H1 only
      +1  Stacked POI (FVG + OB overlap at same H4/H1 level)
      +1  Structure aligned (BOS/CHoCH direction matches trade)
      +1  Price in correct premium/discount zone
      +1  Fibonacci golden pocket (0.618 retracement of last H4 swing)
      +1  Volume Profile POC within 1 ATR (statistically magnetic price level)

    Even without a POI, Fibonacci + POC can score partial points — they are
    mathematically grounded signals that can contribute independent of ICC POI.
    """
    score = 0
    parts: List[str] = []

    # HTF POI (requires nearest_poi)
    if ctx.nearest_poi is not None:
        if ctx.htf_poi_timeframe == 'H4':
            score += 2
            parts.append(f'H4-{ctx.nearest_poi.zone_type}')
        elif ctx.htf_poi_timeframe == 'H1':
            score += 1
            parts.append(f'H1-{ctx.nearest_poi.zone_type}')

        if ctx.htf_poi_stacked:
            score += 1
            parts.append('stacked')

        if ctx.poi_in_correct_zone:
            score += 1
            parts.append(ctx.premium_discount)

    # Structure alignment (independent of POI)
    if ctx.structure_bias != 'neutral':
        struct_aligned = (
            (ctx.direction == 'long' and ctx.structure_bias == 'bullish') or
            (ctx.direction == 'short' and ctx.structure_bias == 'bearish')
        )
        if struct_aligned:
            score += 1
            parts.append(ctx.last_structure_type)

    # Fibonacci golden pocket — pure math, independent of SMC zones
    if ctx.fib_alignment:
        score += 1
        parts.append('fib0.618')

    # Volume Profile POC — statistically magnetic level
    if ctx.at_poc:
        score += 1
        parts.append('POC')

    label = ' '.join(parts) if parts else ('no HTF POI' if ctx.nearest_poi is None else 'weak ICC')
    return min(score, 7), label
