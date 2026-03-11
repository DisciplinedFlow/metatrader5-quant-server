# Autonomous "Human-Like" Trading Bot: Implementation Plan

**Date:** March 11, 2026
**Status:** Planning
**Vision:** Transform from fixed-strategy execution to an autonomous market reader that dynamically analyzes price action, detects regimes, scores confluence, and manages positions like an elite trader.

---

## Current Architecture Summary

```
Celery Beat (every 60s)
  └─► tasks.run_quant_entry_algorithm()
        ├─ Global daily halt check ($300 loss limit)
        ├─ Iterate active StrategyConfig objects (sorted by priority)
        │   ├─ Position limit check (global max=10, per-strategy max_positions)
        │   ├─ Regime filter check (MarketRegime model)
        │   ├─ Live performance gate (5 consec losses OR -$50 last 10 → disable)
        │   └─ Route to entry algorithm:
        │       ├─ CustomStrategy (CVD) → cvd_entry_algorithm()
        │       │   └─ 7 entry layers: Event Guard → Circuit Breaker → Symbol Filter
        │       │      → Market Context Gate → Group Tendency → ML Meta-Filter
        │       │      → Dynamic Position Sizing
        │       ├─ SCALPING → scalp_entry_algorithm()
        │       └─ MEAN_REVERSION → mr_entry_algorithm()
        └─ Re-count positions after each strategy

Celery Beat (every 15s)
  └─► tasks.run_quant_trailing_stop_algorithm()
        └─ position_manager.manage_positions()
            └─ Per position: Hard loss ceiling → Scale-in → MFE Acceleration
               → Profit Protection → Breakeven → Partial Close → Swing Trail
               → Time Exit

Celery Beat (every 5 min)
  └─► tasks.run_regime_scan()
        ├─ Rule-based regime (ADX + BB + ATR) → MarketRegime model
        └─ HMM regime (GaussianHMM on returns + vol) → Redis cache

Celery Beat (every 5 min, via strategy_orchestrator)
  └─► tasks.run_strategy_orchestrator()
        └─ Enable/disable strategies based on regime alignment + rolling WR

Celery Beat (every 30 min)
  └─► tasks.run_ml_retrain()
        └─ LightGBM on TradeFeature data (11 selected features)
```

**Existing Indicators:** `smc.py` (BOS, CHoCH, FVG, OB, liquidity sweep, confluence), `support_resistance.py` (multi-TF S/R), `momentum.py` (EMA ribbon pullback), `mean_reversion.py`, `cvd.py`, `scalping.py`

**Existing ML Pipeline:** `features.py` (30 features extracted, 11 selected), `trainer.py` (LightGBM + SHAP), `scorer.py` (threshold progression), `regime_hmm.py` (3-state HMM)

**Existing Models (Django):** Trade, StrategyConfig, CustomStrategy, BacktestResult, MarketRegime, TradeFeature, MLModel, PairLock

---

## Phase 0: Quick Wins (This Week)

**Goal:** Add displacement detection, kill zone weighting, and the `smartmoneyconcepts` package to the existing entry pipeline. Zero architectural changes — just augment what we have.

### 0.1 Install smartmoneyconcepts Package

**Complexity:** S

**Files to modify:**
- `/backend/django/requirements.txt` — add `smartmoneyconcepts`

```
# Add to requirements.txt
smartmoneyconcepts
```

**Dependencies:** None
**Testing:** `docker compose exec django pip install smartmoneyconcepts && python -c "from smartmoneyconcepts.smc import smc; print('OK')"`

### 0.2 Create SMC Integration Module

**Complexity:** M

**File to create:** `/backend/django/app/quant/indicators/smc_detector.py`

This wraps the `smartmoneyconcepts` package and our existing `smc.py` into a unified detection interface that returns structured results (not just signal strings).

```python
"""
SMC Detector — unified Smart Money Concepts detection.

Wraps the smartmoneyconcepts package (pip) alongside our custom smc.py
indicators. Returns structured detection results for use by the
confluence scorer and MTF analyzer.

The package API takes OHLCV DataFrames with lowercase column names and
returns DataFrames with detection results.
"""

import pandas as pd
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger('app.quant.indicators.smc_detector')


@dataclass
class FVGZone:
    """A detected Fair Value Gap zone."""
    direction: str          # 'bullish' or 'bearish'
    top: float              # Upper edge of the gap
    bottom: float           # Lower edge of the gap
    midpoint: float         # (top + bottom) / 2 — optimal entry
    bar_index: int          # Bar where FVG formed
    mitigated: bool = False # Whether price has filled the gap


@dataclass
class OrderBlockZone:
    """A detected Order Block zone."""
    direction: str          # 'bullish' or 'bearish'
    top: float              # OB zone upper edge
    bottom: float           # OB zone lower edge
    bar_index: int
    retested: bool = False


@dataclass
class LiquiditySweep:
    """A detected liquidity sweep event."""
    direction: str          # 'bullish' (swept lows) or 'bearish' (swept highs)
    sweep_price: float      # The extreme price of the sweep wick
    level_price: float      # The swing level that was swept
    bar_index: int


@dataclass
class StructureBreak:
    """A BOS or CHoCH detection."""
    break_type: str         # 'bos' or 'choch'
    direction: str          # 'bullish' or 'bearish'
    break_price: float      # Price level of the break
    bar_index: int


@dataclass
class SMCDetectionResult:
    """Complete SMC analysis result for a timeframe."""
    fvgs: List[FVGZone] = field(default_factory=list)
    order_blocks: List[OrderBlockZone] = field(default_factory=list)
    sweeps: List[LiquiditySweep] = field(default_factory=list)
    structure_breaks: List[StructureBreak] = field(default_factory=list)
    market_structure_bias: str = 'neutral'  # 'bullish', 'bearish', 'neutral'
    current_bar_signals: dict = field(default_factory=dict)


def detect_all(df: pd.DataFrame, swing_lookback: int = 5) -> SMCDetectionResult:
    """Run all SMC detections on an OHLCV DataFrame.

    Uses the smartmoneyconcepts package when available, falls back
    to our custom smc.py indicators.

    Args:
        df: OHLCV DataFrame with columns: open, high, low, close, volume (optional)
        swing_lookback: Bars on each side for swing detection

    Returns:
        SMCDetectionResult with all detected patterns
    """
    result = SMCDetectionResult()

    try:
        result = _detect_with_package(df, swing_lookback)
    except ImportError:
        logger.debug("smartmoneyconcepts not installed, using custom smc.py")
        result = _detect_with_custom(df, swing_lookback)
    except Exception as e:
        logger.warning(f"Package detection failed, falling back to custom: {e}")
        result = _detect_with_custom(df, swing_lookback)

    return result


def _detect_with_package(df: pd.DataFrame, swing_lookback: int) -> SMCDetectionResult:
    """Detection using the smartmoneyconcepts pip package."""
    from smartmoneyconcepts.smc import smc

    result = SMCDetectionResult()
    ohlcv = df[['open', 'high', 'low', 'close']].copy()
    if 'volume' in df.columns:
        ohlcv['volume'] = df['volume']
    else:
        ohlcv['volume'] = 0

    # Swing detection
    swing_hl = smc.swing_highs_lows(ohlcv, swing_length=swing_lookback)

    # FVG detection
    fvg_data = smc.fvg(ohlcv)
    if fvg_data is not None and not fvg_data.empty:
        for idx, row in fvg_data.iterrows():
            if pd.notna(row.get('FVG', None)) and row['FVG'] != 0:
                direction = 'bullish' if row['FVG'] == 1 else 'bearish'
                top = row.get('Top', 0)
                bottom = row.get('Bottom', 0)
                result.fvgs.append(FVGZone(
                    direction=direction,
                    top=float(top),
                    bottom=float(bottom),
                    midpoint=float((top + bottom) / 2),
                    bar_index=int(idx) if isinstance(idx, (int, float)) else 0,
                    mitigated=bool(row.get('MitigatedIndex', 0)),
                ))

    # BOS / CHoCH
    bos_choch = smc.bos_choch(ohlcv, swing_hl)
    if bos_choch is not None and not bos_choch.empty:
        for idx, row in bos_choch.iterrows():
            val = row.get('BOS', 0)
            choch_val = row.get('CHOCH', 0)
            if pd.notna(val) and val != 0:
                result.structure_breaks.append(StructureBreak(
                    break_type='bos',
                    direction='bullish' if val == 1 else 'bearish',
                    break_price=float(row.get('Level', 0)),
                    bar_index=int(idx) if isinstance(idx, (int, float)) else 0,
                ))
            if pd.notna(choch_val) and choch_val != 0:
                result.structure_breaks.append(StructureBreak(
                    break_type='choch',
                    direction='bullish' if choch_val == 1 else 'bearish',
                    break_price=float(row.get('Level', 0)),
                    bar_index=int(idx) if isinstance(idx, (int, float)) else 0,
                ))

    # Order blocks
    ob_data = smc.ob(ohlcv, swing_hl)
    if ob_data is not None and not ob_data.empty:
        for idx, row in ob_data.iterrows():
            val = row.get('OB', 0)
            if pd.notna(val) and val != 0:
                result.order_blocks.append(OrderBlockZone(
                    direction='bullish' if val == 1 else 'bearish',
                    top=float(row.get('Top', 0)),
                    bottom=float(row.get('Bottom', 0)),
                    bar_index=int(idx) if isinstance(idx, (int, float)) else 0,
                ))

    # Liquidity detection
    liq_data = smc.liquidity(ohlcv, swing_hl)
    if liq_data is not None and not liq_data.empty:
        for idx, row in liq_data.iterrows():
            val = row.get('Liquidity', 0)
            if pd.notna(val) and val != 0:
                swept = row.get('Swept', 0)
                if swept:
                    result.sweeps.append(LiquiditySweep(
                        direction='bullish' if val == -1 else 'bearish',
                        sweep_price=float(row.get('Level', 0)),
                        level_price=float(row.get('Level', 0)),
                        bar_index=int(idx) if isinstance(idx, (int, float)) else 0,
                    ))

    # Determine overall market structure bias from recent structure breaks
    recent_breaks = result.structure_breaks[-5:] if result.structure_breaks else []
    bull_count = sum(1 for b in recent_breaks if b.direction == 'bullish')
    bear_count = sum(1 for b in recent_breaks if b.direction == 'bearish')
    if bull_count > bear_count:
        result.market_structure_bias = 'bullish'
    elif bear_count > bull_count:
        result.market_structure_bias = 'bearish'

    return result


def _detect_with_custom(df: pd.DataFrame, swing_lookback: int) -> SMCDetectionResult:
    """Fallback detection using our custom smc.py indicators."""
    from app.quant.indicators.smc import (
        market_structure, fair_value_gap, order_block, liquidity_sweep,
    )

    result = SMCDetectionResult()

    ms_signals = market_structure(df, {'swing_lookback': swing_lookback})
    fvg_signals = fair_value_gap(df)
    ob_signals = order_block(df)
    liq_signals = liquidity_sweep(df, {'swing_lookback': swing_lookback})

    # Convert signal strings to structured results (last bar only for current state)
    last_idx = len(df) - 1
    last_ms = ms_signals.iloc[last_idx] if last_idx >= 0 else 0
    last_fvg = fvg_signals.iloc[last_idx] if last_idx >= 0 else 0
    last_ob = ob_signals.iloc[last_idx] if last_idx >= 0 else 0
    last_liq = liq_signals.iloc[last_idx] if last_idx >= 0 else 0

    result.current_bar_signals = {
        'market_structure': last_ms,
        'fvg': last_fvg,
        'order_block': last_ob,
        'liquidity_sweep': last_liq,
    }

    # Determine bias
    if isinstance(last_ms, str):
        if 'bullish' in last_ms:
            result.market_structure_bias = 'bullish'
        elif 'bearish' in last_ms:
            result.market_structure_bias = 'bearish'

    return result
```

**Integration:** Registered in `INDICATOR_REGISTRY` (backtester_generic.py) and called by confluence_scorer (Phase 1).

**Dependencies:** Phase 0.1 (smartmoneyconcepts installed)
**Testing:** Unit test with sample OHLCV DataFrame, verify each dataclass is populated correctly.
**Success criteria:** `detect_all()` returns populated `SMCDetectionResult` for any OHLCV DataFrame.

### 0.3 Create Displacement Detection Module

**Complexity:** S

**File to create:** `/backend/django/app/quant/indicators/displacement.py`

```python
"""
Displacement Detection — identify institutional momentum moves.

A displacement is NOT just a big candle. It is 3+ consecutive candles with:
- Same direction (all bullish or all bearish)
- Body-to-total-range ratio > 70% (strong conviction, minimal wicks)
- Creates a Fair Value Gap between candle 1 and candle 3
- Breaks a structural level (swing high/low, session high/low)
- Higher reliability during kill zones

Reference: elite_trader_research.md Section 2 "Displacement Detection"
"""

import numpy as np
import pandas as pd
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger('app.quant.indicators.displacement')


@dataclass
class Displacement:
    """A detected displacement event."""
    direction: str           # 'bullish' or 'bearish'
    start_index: int         # First candle of the displacement
    end_index: int           # Last candle of the displacement
    consecutive_candles: int # Number of consecutive strong candles
    avg_body_ratio: float    # Average body/range ratio across candles
    fvg_top: Optional[float] = None    # FVG zone created by displacement
    fvg_bottom: Optional[float] = None
    broke_structure: bool = False       # Did it break a swing high/low?
    in_kill_zone: bool = False          # Did it occur during London/NY open?


def detect_displacement(
    df: pd.DataFrame,
    min_consecutive: int = 3,
    min_body_ratio: float = 0.70,
    lookback: int = 20,
) -> Optional[Displacement]:
    """Detect the most recent displacement in the OHLCV data.

    Args:
        df: OHLCV DataFrame
        min_consecutive: Minimum consecutive strong candles (default 3)
        min_body_ratio: Minimum body/range ratio per candle (default 0.70)
        lookback: How many bars back to search (default 20)

    Returns:
        Displacement object if found, None otherwise
    """
    if df is None or len(df) < min_consecutive + 2:
        return None

    n = len(df)
    search_start = max(0, n - lookback)

    best_displacement = None

    for i in range(n - 1, search_start - 1, -1):
        # Count consecutive strong candles ending at bar i
        bull_count = 0
        bear_count = 0
        body_ratios = []

        for j in range(i, max(i - min_consecutive - 2, search_start - 1), -1):
            open_p = df['open'].iloc[j]
            close_p = df['close'].iloc[j]
            high_p = df['high'].iloc[j]
            low_p = df['low'].iloc[j]
            total_range = high_p - low_p

            if total_range <= 0:
                break

            body = abs(close_p - open_p)
            body_ratio = body / total_range

            if body_ratio < min_body_ratio:
                break

            body_ratios.append(body_ratio)

            if close_p > open_p:
                if bear_count > 0:
                    break  # Direction changed
                bull_count += 1
            elif close_p < open_p:
                if bull_count > 0:
                    break  # Direction changed
                bear_count += 1
            else:
                break  # Doji — not a displacement candle

        count = max(bull_count, bear_count)
        if count < min_consecutive:
            continue

        direction = 'bullish' if bull_count >= min_consecutive else 'bearish'
        start_idx = i - count + 1
        end_idx = i
        avg_ratio = sum(body_ratios) / len(body_ratios)

        # Check for FVG between first and third candle
        fvg_top, fvg_bottom = None, None
        if count >= 3:
            fvg_top, fvg_bottom = _check_fvg(df, start_idx, direction)

        # Check if displacement broke a swing level
        broke_structure = _check_structure_break(df, start_idx, end_idx, direction)

        displacement = Displacement(
            direction=direction,
            start_index=start_idx,
            end_index=end_idx,
            consecutive_candles=count,
            avg_body_ratio=avg_ratio,
            fvg_top=fvg_top,
            fvg_bottom=fvg_bottom,
            broke_structure=broke_structure,
        )

        # Return the most recent displacement found
        if best_displacement is None or displacement.consecutive_candles > best_displacement.consecutive_candles:
            best_displacement = displacement

        break  # Take the first (most recent) displacement

    return best_displacement


def _check_fvg(df: pd.DataFrame, start_idx: int, direction: str) -> Tuple[Optional[float], Optional[float]]:
    """Check if the displacement created an FVG between candle 1 and candle 3."""
    if start_idx + 2 >= len(df):
        return None, None

    if direction == 'bullish':
        c1_high = df['high'].iloc[start_idx]
        c3_low = df['low'].iloc[start_idx + 2]
        if c3_low > c1_high:
            return float(c3_low), float(c1_high)
    else:
        c1_low = df['low'].iloc[start_idx]
        c3_high = df['high'].iloc[start_idx + 2]
        if c3_high < c1_low:
            return float(c1_low), float(c3_high)

    return None, None


def _check_structure_break(df: pd.DataFrame, start_idx: int, end_idx: int, direction: str) -> bool:
    """Check if the displacement broke a recent swing high/low."""
    lookback = 20
    pre_start = max(0, start_idx - lookback)
    pre_data = df.iloc[pre_start:start_idx]

    if len(pre_data) < 5:
        return False

    if direction == 'bullish':
        recent_swing_high = pre_data['high'].max()
        displacement_high = df['high'].iloc[start_idx:end_idx + 1].max()
        return displacement_high > recent_swing_high
    else:
        recent_swing_low = pre_data['low'].min()
        displacement_low = df['low'].iloc[start_idx:end_idx + 1].min()
        return displacement_low < recent_swing_low


def displacement_signal(data: pd.DataFrame, params: dict = None) -> pd.Series:
    """INDICATOR_REGISTRY-compatible wrapper.

    Returns a Series of signal strings compatible with CONDITION_OPS.
    """
    params = params or {}
    min_consecutive = params.get('min_consecutive', 3)
    min_body_ratio = params.get('min_body_ratio', 0.70)

    result = pd.Series(0, index=data.index, dtype=object)

    if len(data) < min_consecutive + 2:
        return result

    for i in range(min_consecutive + 2, len(data)):
        window = data.iloc[max(0, i - 10):i + 1]
        d = detect_displacement(window, min_consecutive, min_body_ratio, lookback=10)
        if d and d.end_index == len(window) - 1:
            result.iloc[i] = f'{d.direction}_displacement'

    return result
```

**Integration:** Add to `INDICATOR_REGISTRY` in `backtester_generic.py`:
```python
'DISPLACEMENT': lambda df, params: displacement_signal(df, params),
```

**Dependencies:** None
**Testing:** Construct synthetic OHLCV with 3 consecutive bullish candles (body ratio > 0.7), verify detection.
**Success criteria:** Correctly detects bullish/bearish displacements on historical data.

### 0.4 Add Kill Zone Weighting

**Complexity:** S

**File to create:** `/backend/django/app/quant/indicators/kill_zones.py`

```python
"""
Kill Zone Detection — session-aware confidence weighting.

Research shows London-NY overlap produces 30-50% larger pip ranges than
single sessions. Kill zones are optimal windows for institutional moves.

Kill Zones (UTC):
- London Open:  07:00-10:00 UTC (weight 1.5)
- NY Open:      12:00-15:00 UTC (weight 2.0, highest probability)
- London Close: 15:00-17:00 UTC (weight 1.0, retracement setups)
- Asian:        22:00-02:00 UTC (weight 0.5, range only)
- Dead Zone:    everything else (weight 0.3)
"""

from datetime import datetime, timezone
from dataclasses import dataclass


@dataclass
class KillZoneInfo:
    """Current kill zone analysis."""
    name: str               # 'london_open', 'ny_open', 'london_close', 'asian', 'dead'
    weight: float           # Confluence multiplier (0.3 - 2.0)
    minutes_remaining: int  # Minutes until kill zone ends
    is_active: bool         # Whether we're in any kill zone


KILL_ZONES = {
    'london_open':  {'start': 7,  'end': 10, 'weight': 1.5},
    'ny_open':      {'start': 12, 'end': 15, 'weight': 2.0},
    'london_close': {'start': 15, 'end': 17, 'weight': 1.0},
    'asian':        {'start': 22, 'end': 2,  'weight': 0.5},  # Wraps midnight
}


def get_current_kill_zone(utc_hour: int = None, utc_minute: int = None) -> KillZoneInfo:
    """Determine the current kill zone and its weight.

    Args:
        utc_hour: Override for testing (default: current UTC hour)
        utc_minute: Override for testing (default: current UTC minute)

    Returns:
        KillZoneInfo with the current zone details
    """
    if utc_hour is None:
        now = datetime.now(timezone.utc)
        utc_hour = now.hour
        utc_minute = now.minute
    elif utc_minute is None:
        utc_minute = 0

    for name, zone in KILL_ZONES.items():
        start = zone['start']
        end = zone['end']

        if start < end:
            # Normal range (e.g., 7-10)
            if start <= utc_hour < end:
                remaining = (end - utc_hour) * 60 - utc_minute
                return KillZoneInfo(
                    name=name,
                    weight=zone['weight'],
                    minutes_remaining=remaining,
                    is_active=True,
                )
        else:
            # Wraps midnight (e.g., 22-02)
            if utc_hour >= start or utc_hour < end:
                if utc_hour >= start:
                    remaining = (24 - utc_hour + end) * 60 - utc_minute
                else:
                    remaining = (end - utc_hour) * 60 - utc_minute
                return KillZoneInfo(
                    name=name,
                    weight=zone['weight'],
                    minutes_remaining=remaining,
                    is_active=True,
                )

    # Dead zone
    return KillZoneInfo(
        name='dead',
        weight=0.3,
        minutes_remaining=0,
        is_active=False,
    )


def get_kill_zone_confluence_points() -> int:
    """Return confluence points for the current kill zone.

    NY Open = 1 point, London Open = 1 point, others = 0.
    Used by the confluence scorer (Phase 1).
    """
    kz = get_current_kill_zone()
    if kz.name in ('ny_open', 'london_open'):
        return 1
    return 0
```

**Dependencies:** None
**Testing:** Call `get_current_kill_zone()` at various UTC hours, verify correct zone detection.
**Success criteria:** Correctly identifies kill zone at any time, weight values match research.

### 0.5 Wire Quick Wins into Entry Pipeline

**Complexity:** M

**Files to modify:**
- `/backend/django/app/quant/algorithms/cvd/entry.py` — import and call kill zone check, displacement check
- `/backend/django/app/quant/backtester_generic.py` — register new indicators
- `/backend/django/app/quant/ml/features.py` — add kill zone and displacement features to FEATURE_NAMES

**Changes to `cvd/entry.py`:**

In `_is_trading_session()`, add kill zone weighting by returning both `allowed` and `weight`:

```python
def _is_trading_session():
    """Check trading session and return kill zone weight."""
    from app.quant.indicators.kill_zones import get_current_kill_zone
    from datetime import datetime, timezone as tz

    now = datetime.now(tz.utc)
    if now.weekday() == 6:
        return False, 0.0
    if now.weekday() == 0 and now.hour < 1:
        return False, 0.0
    if now.hour < 7 or now.hour >= 17:
        return False, 0.0
    if now.hour == 9:
        return False, 0.0

    kz = get_current_kill_zone()
    return True, kz.weight
```

In the main entry flow (the part that computes `dynamic_capital`), multiply by the kill zone weight:

```python
# After all sizing adjustments
kz_weight = kill_zone_weight  # from _is_trading_session()
if kz_weight < 1.0:
    dynamic_capital *= kz_weight
    logger.info(f"Kill zone sizing: {kz.name} → {kz_weight:.1f}x")
```

**Changes to `backtester_generic.py`:**

```python
from app.quant.indicators.displacement import displacement_signal

# Add to INDICATOR_REGISTRY:
'DISPLACEMENT': lambda df, params: displacement_signal(df, params),
```

**Changes to `ml/features.py`:**

Add to `FEATURE_NAMES`:
```python
'kill_zone_weight',       # Kill zone confidence multiplier
'displacement_detected',  # 1 if displacement on current bar, 0 otherwise
```

In `extract_features()`:
```python
# Kill zone
from app.quant.indicators.kill_zones import get_current_kill_zone
kz = get_current_kill_zone()
features['kill_zone_weight'] = kz.weight

# Displacement
from app.quant.indicators.displacement import detect_displacement
displacement = detect_displacement(df, min_consecutive=3)
features['displacement_detected'] = 1 if displacement else 0
```

**Dependencies:** Phases 0.3 and 0.4 complete
**Testing:** Run entry algorithm in paper mode, verify kill zone weight appears in logs. Verify displacement detection runs without errors.
**Success criteria:** Entry logs show kill zone name and weight; displacement feature appears in TradeFeature.features_json.

---

## Phase 1: Confluence Scorer (Week 2)

**Goal:** Build a quantitative confluence scoring system (0-11 points) that gates entries based on setup quality and scales position size accordingly.

### 1.1 Build Confluence Scorer

**Complexity:** L

**File to create:** `/backend/django/app/quant/algorithms/confluence_scorer.py`

```python
"""
Confluence Scorer — quantitative setup quality assessment.

Scores each potential trade entry from 0-11 based on how many
confirming factors align. Inspired by how elite ICT/SMC traders
stack confluence before entering.

Scoring breakdown:
  Kill zone active (London/NY Open)       +1
  HTF bias aligned                        +2
  Liquidity sweep detected                +2
  FVG present at entry zone               +1
  Order block at entry zone               +1
  Market regime favorable (HMM)           +1
  CVD divergence confirms                 +2
  Displacement detected                   +1
  ─────────────────────────────────────
  Maximum possible                        11

Position sizing tiers:
  0-3:  SKIP (do not trade)
  4-6:  50% size (marginal setup)
  7-8:  100% size (solid setup)
  9-11: 150% size (A+ setup)

References: elite_trader_research.md Section 7 "Priority 5"
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

logger = logging.getLogger('app.quant.algorithms.confluence')


@dataclass
class ConfluenceResult:
    """Output of the confluence scoring process."""
    total_score: int = 0
    max_score: int = 11
    size_multiplier: float = 0.0     # 0.0 = skip, 0.5, 1.0, or 1.5
    tier: str = 'SKIP'               # SKIP, MARGINAL, SOLID, A_PLUS
    factors: dict = field(default_factory=dict)  # factor_name -> (points, detail)
    should_trade: bool = False


def score_confluence(
    symbol: str,
    order_type: str,         # 'BUY' or 'SELL'
    df_htf: pd.DataFrame,   # H4/Daily data
    df_mtf: pd.DataFrame,   # H1/M15 data (entry timeframe)
    df_ltf: Optional[pd.DataFrame] = None,  # M5/M1 data (optional)
    regime_state: int = -1,  # HMM regime: 0=calm, 1=normal, 2=volatile, -1=unknown
    cvd_divergence: bool = False,
    strategy_config=None,
) -> ConfluenceResult:
    """Score the confluence of a potential trade entry.

    Called after a signal is detected but before the order is placed.
    Each factor adds points to the score.

    Args:
        symbol: Trading pair
        order_type: 'BUY' or 'SELL'
        df_htf: Higher timeframe DataFrame (H4/Daily) for bias
        df_mtf: Medium timeframe DataFrame (entry TF) for SMC
        df_ltf: Lower timeframe DataFrame (M5) for timing (optional)
        regime_state: Current HMM regime
        cvd_divergence: Whether CVD divergence confirmed this signal
        strategy_config: StrategyConfig for context

    Returns:
        ConfluenceResult with score, tier, and size multiplier
    """
    result = ConfluenceResult()
    direction = 'bullish' if order_type == 'BUY' else 'bearish'

    # --- Factor 1: Kill Zone (0 or 1 point) ---
    kz_points = _score_kill_zone()
    result.factors['kill_zone'] = kz_points

    # --- Factor 2: HTF Bias Alignment (0 or 2 points) ---
    htf_points = _score_htf_bias(df_htf, direction)
    result.factors['htf_bias'] = htf_points

    # --- Factor 3: Liquidity Sweep (0 or 2 points) ---
    sweep_points = _score_liquidity_sweep(df_mtf, direction)
    result.factors['liquidity_sweep'] = sweep_points

    # --- Factor 4: FVG at Entry (0 or 1 point) ---
    fvg_points = _score_fvg(df_mtf, direction)
    result.factors['fvg'] = fvg_points

    # --- Factor 5: Order Block at Entry (0 or 1 point) ---
    ob_points = _score_order_block(df_mtf, direction)
    result.factors['order_block'] = ob_points

    # --- Factor 6: Regime Favorable (0 or 1 point) ---
    regime_points = _score_regime(regime_state)
    result.factors['regime'] = regime_points

    # --- Factor 7: CVD Divergence (0 or 2 points) ---
    cvd_points = 2 if cvd_divergence else 0
    result.factors['cvd_divergence'] = cvd_points

    # --- Factor 8: Displacement Detected (0 or 1 point) ---
    disp_points = _score_displacement(df_mtf, direction)
    result.factors['displacement'] = disp_points

    # --- Compute total and tier ---
    result.total_score = sum(result.factors.values())

    if result.total_score < 4:
        result.tier = 'SKIP'
        result.size_multiplier = 0.0
        result.should_trade = False
    elif result.total_score < 7:
        result.tier = 'MARGINAL'
        result.size_multiplier = 0.5
        result.should_trade = True
    elif result.total_score < 9:
        result.tier = 'SOLID'
        result.size_multiplier = 1.0
        result.should_trade = True
    else:
        result.tier = 'A_PLUS'
        result.size_multiplier = 1.5
        result.should_trade = True

    logger.info(
        f"CONFLUENCE: {symbol} {order_type} score={result.total_score}/{result.max_score} "
        f"tier={result.tier} size={result.size_multiplier:.1f}x "
        f"factors={result.factors}"
    )

    return result


def _score_kill_zone() -> int:
    """Score: 1 point if in London Open or NY Open kill zone."""
    from app.quant.indicators.kill_zones import get_current_kill_zone
    kz = get_current_kill_zone()
    return 1 if kz.name in ('london_open', 'ny_open') else 0


def _score_htf_bias(df_htf: pd.DataFrame, direction: str) -> int:
    """Score: 2 points if HTF market structure aligns with trade direction.

    Uses EMA alignment + swing structure to determine HTF bias.
    """
    if df_htf is None or len(df_htf) < 50:
        return 0

    try:
        close = df_htf['close']
        ema_fast = close.ewm(span=8, adjust=False).mean().iloc[-1]
        ema_slow = close.ewm(span=34, adjust=False).mean().iloc[-1]

        # Also check market structure via our SMC detector
        from app.quant.indicators.smc import market_structure
        ms = market_structure(df_htf, {'swing_lookback': 5})
        last_ms = ms.iloc[-1] if len(ms) > 0 else 0

        htf_bias = 'neutral'
        if ema_fast > ema_slow:
            htf_bias = 'bullish'
        elif ema_fast < ema_slow:
            htf_bias = 'bearish'

        # Structure confirmation
        if isinstance(last_ms, str):
            if 'bullish' in last_ms:
                htf_bias = 'bullish'
            elif 'bearish' in last_ms:
                htf_bias = 'bearish'

        return 2 if htf_bias == direction else 0

    except Exception as e:
        logger.debug(f"HTF bias scoring failed: {e}")
        return 0


def _score_liquidity_sweep(df_mtf: pd.DataFrame, direction: str) -> int:
    """Score: 2 points if a liquidity sweep was detected in the trade direction."""
    if df_mtf is None or len(df_mtf) < 20:
        return 0

    try:
        from app.quant.indicators.smc import liquidity_sweep
        signals = liquidity_sweep(df_mtf, {'swing_lookback': 5})

        # Check last 5 bars for a sweep
        for i in range(max(0, len(signals) - 5), len(signals)):
            val = signals.iloc[i]
            if isinstance(val, str) and direction in val:
                return 2

        return 0
    except Exception as e:
        logger.debug(f"Liquidity sweep scoring failed: {e}")
        return 0


def _score_fvg(df_mtf: pd.DataFrame, direction: str) -> int:
    """Score: 1 point if an active FVG exists in the trade direction."""
    if df_mtf is None or len(df_mtf) < 10:
        return 0

    try:
        from app.quant.indicators.smc import fair_value_gap
        signals = fair_value_gap(df_mtf)

        # Check last 3 bars for FVG fill entry
        for i in range(max(0, len(signals) - 3), len(signals)):
            val = signals.iloc[i]
            if isinstance(val, str) and direction in val:
                return 1

        return 0
    except Exception as e:
        logger.debug(f"FVG scoring failed: {e}")
        return 0


def _score_order_block(df_mtf: pd.DataFrame, direction: str) -> int:
    """Score: 1 point if an order block retest detected in trade direction."""
    if df_mtf is None or len(df_mtf) < 20:
        return 0

    try:
        from app.quant.indicators.smc import order_block
        signals = order_block(df_mtf)

        for i in range(max(0, len(signals) - 3), len(signals)):
            val = signals.iloc[i]
            if isinstance(val, str) and direction in val:
                return 1

        return 0
    except Exception as e:
        logger.debug(f"Order block scoring failed: {e}")
        return 0


def _score_regime(regime_state: int) -> int:
    """Score: 1 point if HMM regime is low-volatility (calm) or normal.

    High volatility (state 2) = not favorable, 0 points.
    """
    if regime_state in (0, 1):  # Calm or normal
        return 1
    return 0


def _score_displacement(df_mtf: pd.DataFrame, direction: str) -> int:
    """Score: 1 point if displacement detected in trade direction."""
    if df_mtf is None or len(df_mtf) < 10:
        return 0

    try:
        from app.quant.indicators.displacement import detect_displacement
        d = detect_displacement(df_mtf)
        if d and d.direction == direction:
            return 1
        return 0
    except Exception as e:
        logger.debug(f"Displacement scoring failed: {e}")
        return 0
```

**Dependencies:** Phase 0 complete (displacement, kill zones, smc_detector)
**Integration point:** Called from `cvd/entry.py` AFTER signal detection, BEFORE order placement.

### 1.2 Integrate Confluence Scorer into CVD Entry Pipeline

**Complexity:** M

**File to modify:** `/backend/django/app/quant/algorithms/cvd/entry.py`

**Where it hooks in:** Inside the loop that iterates over symbols after a CVD signal fires, between the signal detection and order placement sections. Currently the flow is:

```
signal detected → entry layers (circuit breaker, etc.) → size calculation → order
```

New flow becomes:

```
signal detected → entry layers → CONFLUENCE SCORE → size calculation × confluence multiplier → order
```

**Changes:**

```python
# In the per-symbol signal processing section, after signal detection:
from app.quant.algorithms.confluence_scorer import score_confluence
from app.utils.api.data import fetch_data_pos
from app.utils.constants import MT5Timeframe

# Fetch HTF data for confluence scoring
df_htf = fetch_data_pos(symbol, MT5Timeframe.H4, 100)

# Get HMM regime from cache
from django.core.cache import cache
hmm_regime = cache.get(f'hmm_regime:{symbol}', -1)

# Score confluence
confluence = score_confluence(
    symbol=symbol,
    order_type=order_type,
    df_htf=df_htf,
    df_mtf=df,  # The entry timeframe data already loaded
    regime_state=int(hmm_regime),
    cvd_divergence=True,  # CVD signal already confirmed
    strategy_config=strategy_config,
)

if not confluence.should_trade:
    logger.info(f"CONFLUENCE SKIP: {symbol} score={confluence.total_score}/11")
    continue

# Apply confluence size multiplier to dynamic_capital
dynamic_capital *= confluence.size_multiplier
```

**Dependencies:** Phase 1.1
**Testing:** Paper trade with logging, verify confluence scores appear and sizing adjusts correctly.
**Success criteria:** Confluence score logged for every entry attempt. Low-score setups skipped. High-score setups get larger position sizes.

### 1.3 Store Confluence Score in TradeFeature

**Complexity:** S

**Files to modify:**
- `/backend/django/app/nexus/models.py` — add `confluence_score` field to Trade or TradeFeature
- `/backend/django/app/quant/ml/features.py` — add confluence score to feature extraction

**New field on Trade model:**
```python
confluence_score = models.IntegerField(null=True, blank=True)  # 0-11 confluence score at entry
confluence_factors = models.JSONField(default=dict, blank=True)  # Factor breakdown
```

**Migration required:** `python manage.py makemigrations nexus && python manage.py migrate`

**Dependencies:** Phase 1.1
**Testing:** Verify confluence_score is populated on new Trade records.
**Success criteria:** Every new trade has a confluence_score and confluence_factors JSON saved.

---

## Phase 2: HMM Regime Detector Enhancement (Weeks 2-3)

**Goal:** Upgrade the existing `regime_hmm.py` from a basic 3-state detector into a production regime engine with per-pair detection, cross-pair analysis, rolling retraining, and explicit regime labels (TRENDING/RANGING/VOLATILE).

### 2.1 Enhance HMM Regime Detector

**Complexity:** L

**File to modify:** `/backend/django/app/quant/ml/regime_hmm.py`

The existing `fit_and_predict()` function already works but has limitations:
- Only uses returns + 5-bar rolling vol (2 features)
- Only 50 EM iterations (research recommends 1000)
- No caching of the trained model (refits every scan)
- States are ordered by volatility but not explicitly labeled

**Enhanced version — key additions:**

```python
"""
HMM Regime Detection — data-driven market state classification.

Enhanced from v1:
- 4 observation features: returns, rolling vol, Bollinger width, ADX normalized
- 1000 EM iterations for stable convergence
- Model caching: refit only when >1h old or when regime shift detected
- Explicit state labeling based on mean return + variance analysis
- Cross-pair regime consensus
- Rolling 60-day training window (configurable)

Reference: Hamilton (1989), QuantStart HMM Study (57% drawdown reduction)
"""

N_STATES = 3
MIN_BARS = 200            # Need more bars for stable 4-feature fitting
REFIT_INTERVAL_SECONDS = 3600  # Refit model every hour
EM_ITERATIONS = 1000       # Full convergence (research recommendation)
TRAINING_WINDOW_BARS = 60 * 24  # ~60 trading days of H1 data


def fit_and_predict_enhanced(df, n_states=N_STATES, symbol=None):
    """Enhanced HMM fitting with multi-feature observations and model caching.

    Args:
        df: OHLCV DataFrame with at least MIN_BARS rows
        n_states: Number of hidden states (default 3)
        symbol: Optional symbol for model caching

    Returns:
        dict with:
            - state: int (0=trending, 1=ranging, 2=volatile)
            - label: str ('TRENDING', 'RANGING', 'VOLATILE')
            - confidence: float (posterior probability of current state)
            - state_durations: dict of average bars per state
    """
    # ... (implementation details)


def get_cross_pair_regime_consensus(pairs, fetch_fn, timeframe):
    """Analyze regime consistency across multiple pairs.

    If 5/7 pairs are in state 0 (trending), the market is broadly trending.
    Useful for strategy routing: a "trending" consensus means trend-following
    strategies should be preferred globally.

    Returns:
        dict with 'dominant_regime', 'consensus_pct', 'per_pair' details
    """
    # ... (implementation details)
```

**Key function signatures:**

```python
def fit_and_predict_enhanced(
    df: pd.DataFrame,
    n_states: int = 3,
    symbol: str = None,
) -> dict:
    """
    Returns:
        {
            'state': 0,                    # Raw state number
            'label': 'TRENDING',           # Human-readable label
            'confidence': 0.87,            # Posterior probability
            'state_durations': {0: 45, 1: 20, 2: 8},  # Avg bars per state
            'transition_matrix': [[...], ...],          # State transition probs
        }
    """


def get_cross_pair_regime_consensus(
    pairs: list,
    fetch_fn: callable,
    timeframe,
) -> dict:
    """
    Returns:
        {
            'dominant_regime': 'TRENDING',
            'consensus_pct': 0.71,          # 71% of pairs agree
            'per_pair': {'EURUSD': 'TRENDING', 'GBPUSD': 'RANGING', ...},
        }
    """
```

**Dependencies:** `hmmlearn` already in requirements.txt
**Integration:** Called by `algorithms/regime.py` `scan_all_pairs()` function (replace existing HMM call)
**Testing:** Fit on 200 bars of EURUSD H1 data, verify 3 states labeled correctly, confidence > 0.5.
**Success criteria:** State labels match intuitive assessment (volatile during news, ranging during Asian session, trending during London).

### 2.2 Replace Simple MarketRegime with HMM Output

**Complexity:** M

**File to modify:** `/backend/django/app/quant/algorithms/regime.py`

**Changes:**
- In `scan_all_pairs()`, use `fit_and_predict_enhanced()` as primary (currently secondary)
- Store both rule-based AND HMM results in MarketRegime model
- When they disagree, log a warning (useful for debugging)
- Add `hmm_label` and `hmm_confidence` fields to MarketRegime model

**New fields on MarketRegime:**
```python
hmm_state = models.IntegerField(default=-1)        # Raw HMM state
hmm_label = models.CharField(max_length=20, default='UNKNOWN')  # TRENDING/RANGING/VOLATILE
hmm_confidence = models.FloatField(default=0)       # Posterior probability
```

**Decision logic for which regime to use:**
```python
def get_effective_regime(symbol):
    """Return the most reliable regime classification.

    Priority: HMM (when confidence > 0.7) > Rule-based (always available)
    When both available and agree: highest confidence
    When they disagree: use HMM if confident, else rule-based
    """
```

**Dependencies:** Phase 2.1
**Migration required:** Yes (new MarketRegime fields)
**Testing:** Compare HMM vs rule-based classifications over 1 week of data, measure agreement rate.
**Success criteria:** HMM and rule-based agree > 70% of the time; HMM detects regime shifts 1-3 bars earlier.

### 2.3 Add Cross-Pair Regime Detection

**Complexity:** M

**File to modify:** `/backend/django/app/quant/ml/regime_hmm.py` (add `get_cross_pair_regime_consensus`)

**Integration:** Called at the end of `scan_all_pairs()` after individual pair regimes are computed. Result cached in Redis as `cross_pair_regime_consensus` with 10-minute TTL.

**Used by:** Strategy router (Phase 3) and strategy orchestrator.

**Dependencies:** Phase 2.1
**Testing:** Verify consensus matches when > 70% of pairs agree.
**Success criteria:** Cross-pair consensus available in Redis cache, used by strategy router.

---

## Phase 3: Strategy Router (Weeks 3-4)

**Goal:** Replace the current static `StrategyConfig.regime_filter` matching with a dynamic strategy router that selects the optimal approach per-symbol based on the current regime, available confluences, and recent performance.

### 3.1 Build Strategy Router

**Complexity:** L

**File to create:** `/backend/django/app/quant/algorithms/strategy_router.py`

```python
"""
Strategy Router — dynamic strategy selection based on market regime.

Replaces the static StrategyConfig.regime_filter with intelligent routing:
- TRENDING regime → ICT displacement + trend continuation + EMA pullback
- RANGING regime  → Mean reversion + FVG fill + OB bounce
- VOLATILE regime → Only A+ setups (confluence 9+), 50% size

The router runs per-symbol, not globally. EURUSD can be trending while
USDCHF is ranging — each gets a different strategy.

Replaces: strategy_orchestrator.py (which only enables/disables + adjusts size)
Keeps: strategy_orchestrator.py as a performance watchdog (it still monitors WR)

References:
- elite_trader_research.md Section 3 "Dynamic Strategy Selection"
- Market Wizards: "Strategic adaptability — adjusting based on conditions"
"""

import logging
from typing import List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger('app.quant.algorithms.strategy_router')


@dataclass
class RoutingDecision:
    """The router's decision for a specific symbol."""
    symbol: str
    regime: str                          # TRENDING, RANGING, VOLATILE, UNKNOWN
    selected_strategies: List[str]       # Ordered list of strategy names to try
    size_multiplier: float = 1.0         # Regime-based sizing adjustment
    min_confluence: int = 4              # Minimum confluence score to enter
    reason: str = ''


# Strategy pool: all available strategies and their regime preferences
STRATEGY_POOL = {
    'ict_displacement': {
        'preferred_regimes': ['TRENDING'],
        'description': 'ICT displacement + FVG entry (trend continuation)',
        'min_confluence': 7,
    },
    'ema_ribbon_pullback': {
        'preferred_regimes': ['TRENDING'],
        'description': 'EMA ribbon pullback in established trends',
        'min_confluence': 5,
    },
    'cvd_divergence': {
        'preferred_regimes': ['TRENDING', 'RANGING'],
        'description': 'CVD divergence — works in both regimes',
        'min_confluence': 4,
    },
    'mean_reversion_bb': {
        'preferred_regimes': ['RANGING'],
        'description': 'Bollinger Band mean reversion in ranges',
        'min_confluence': 4,
    },
    'fvg_fill': {
        'preferred_regimes': ['RANGING'],
        'description': 'FVG fill entries in ranging markets',
        'min_confluence': 5,
    },
    'ob_bounce': {
        'preferred_regimes': ['RANGING'],
        'description': 'Order block retest bounce',
        'min_confluence': 6,
    },
    'smc_confluence': {
        'preferred_regimes': ['TRENDING', 'RANGING'],
        'description': 'Multi-concept SMC confluence (2+ aligned)',
        'min_confluence': 6,
    },
}


def route_strategy(
    symbol: str,
    regime: str = None,
    hmm_confidence: float = 0.0,
) -> RoutingDecision:
    """Determine which strategies to use for a given symbol based on its regime.

    Args:
        symbol: Trading pair
        regime: Override regime (if None, fetched from cache/DB)
        hmm_confidence: Confidence of the HMM classification

    Returns:
        RoutingDecision with ordered strategy list and parameters
    """
    if regime is None:
        regime = _get_effective_regime(symbol)

    decision = RoutingDecision(symbol=symbol, regime=regime)

    if regime in ('TRENDING', 'TRENDING_UP', 'TRENDING_DOWN'):
        decision.selected_strategies = [
            'ict_displacement',
            'ema_ribbon_pullback',
            'cvd_divergence',
        ]
        decision.size_multiplier = 1.0
        decision.min_confluence = 5
        decision.reason = f"Trending regime → trend-following strategies"

    elif regime == 'RANGING':
        decision.selected_strategies = [
            'mean_reversion_bb',
            'fvg_fill',
            'ob_bounce',
            'cvd_divergence',
        ]
        decision.size_multiplier = 0.8  # Slightly reduce — ranges can break
        decision.min_confluence = 4
        decision.reason = f"Ranging regime → mean reversion strategies"

    elif regime == 'VOLATILE':
        decision.selected_strategies = [
            'smc_confluence',  # Only high-confluence setups
        ]
        decision.size_multiplier = 0.5   # Half size in volatile
        decision.min_confluence = 9       # Only A+ setups
        decision.reason = f"Volatile regime → A+ setups only, 50% size"

    else:  # UNKNOWN
        decision.selected_strategies = ['cvd_divergence']
        decision.size_multiplier = 0.5
        decision.min_confluence = 6
        decision.reason = f"Unknown regime → conservative CVD only"

    logger.info(
        f"ROUTER: {symbol} regime={regime} → "
        f"{decision.selected_strategies} (size={decision.size_multiplier:.1f}x, "
        f"min_confluence={decision.min_confluence})"
    )

    return decision


def _get_effective_regime(symbol: str) -> str:
    """Get the best available regime for a symbol."""
    try:
        from django.core.cache import cache

        # Try HMM first
        hmm_state = cache.get(f'hmm_regime:{symbol}')
        if hmm_state is not None:
            labels = {0: 'TRENDING', 1: 'RANGING', 2: 'VOLATILE'}
            return labels.get(int(hmm_state), 'UNKNOWN')

        # Fall back to rule-based
        from app.quant.algorithms.regime import get_regime_for_pair
        return get_regime_for_pair(symbol)
    except Exception:
        return 'UNKNOWN'
```

**Dependencies:** Phase 2 (HMM regime)
**Integration point:** Replaces the `config.regime_filter` check in `tasks.py` `run_quant_entry_algorithm()`. Instead of filtering strategies by regime, the router selects strategies per-symbol.

### 3.2 Integrate Router into Entry Dispatcher

**Complexity:** M

**File to modify:** `/backend/django/app/quant/tasks.py`

**Current flow:** Iterate StrategyConfig objects, check regime_filter, route to entry algorithm.

**New flow:**
```python
@shared_task(name='quant.tasks.run_quant_entry_algorithm')
def run_quant_entry_algorithm():
    """Dynamic multi-strategy entry dispatcher with regime-based routing."""
    # ... existing guards (pause check, daily halt) ...

    from app.quant.algorithms.strategy_router import route_strategy
    from app.quant.algorithms.regime import FOREX_PAIRS

    for symbol in FOREX_PAIRS:
        if total_open >= GLOBAL_MAX:
            break
        if have_open_positions_in_symbol(symbol):
            continue

        # Route to optimal strategies for this symbol's regime
        routing = route_strategy(symbol)

        for strategy_name in routing.selected_strategies:
            # Try each strategy in order until one produces a trade
            success = _try_strategy_entry(
                symbol, strategy_name,
                routing.size_multiplier,
                routing.min_confluence,
            )
            if success:
                total_open += 1
                break
```

**Dependencies:** Phase 3.1
**Testing:** Paper trade for 1 week. Verify different symbols get different strategies based on their regime.
**Success criteria:** Logs show per-symbol routing decisions. Trending pairs get trend strategies, ranging pairs get mean reversion.

---

## Phase 4: Multi-Timeframe Analysis Engine (Weeks 4-6)

**Goal:** Build a structured MTF analysis engine that establishes HTF bias, identifies key structural levels on MTF, and times entries on LTF. This is the "chart reading" component.

### 4.1 Build MTF Analyzer

**Complexity:** L

**File to create:** `/backend/django/app/quant/algorithms/mtf_analyzer.py`

```python
"""
Multi-Timeframe Analysis Engine — structured chart reading.

Implements the 3-tier analysis process used by elite ICT/SMC traders:

  HTF (H4/Daily): Directional bias + key liquidity levels + premium/discount zones
  MTF (H1/M15):   Market structure (BOS/CHoCH) + FVG + OB + sweep detection
  LTF (M5/M1):    Entry timing + LTF confirmation of MTF setup

Critical rule: NEVER take LTF entries that contradict HTF bias.

Timeframe mapping (day trading):
  HTF = H4    (bias determination)
  MTF = M15   (structure & setup detection)
  LTF = M5    (entry timing)

References:
- elite_trader_research.md Section 2 "Multi-Timeframe Confluence Structure"
- ICT model: HTF Bias → Sweep → MSS → FVG → LTF Entry
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict

import pandas as pd

logger = logging.getLogger('app.quant.algorithms.mtf_analyzer')


@dataclass
class HTFAnalysis:
    """Higher timeframe bias and key levels."""
    bias: str                       # 'bullish', 'bearish', 'neutral'
    bias_confidence: float          # 0.0 - 1.0
    key_resistance_levels: List[float] = field(default_factory=list)
    key_support_levels: List[float] = field(default_factory=list)
    premium_zone_start: float = 0.0  # Fibonacci 50% level (sell zone)
    discount_zone_start: float = 0.0 # Fibonacci 50% level (buy zone)
    previous_day_high: float = 0.0
    previous_day_low: float = 0.0
    recent_structure: str = ''       # 'HH_HL', 'LH_LL', 'mixed'


@dataclass
class MTFAnalysis:
    """Medium timeframe structure and setup detection."""
    active_fvgs: list = field(default_factory=list)
    active_order_blocks: list = field(default_factory=list)
    recent_sweeps: list = field(default_factory=list)
    recent_structure_breaks: list = field(default_factory=list)
    market_structure: str = 'neutral'     # 'bullish', 'bearish', 'neutral'
    last_choch_direction: Optional[str] = None
    last_bos_direction: Optional[str] = None


@dataclass
class LTFAnalysis:
    """Lower timeframe entry timing signals."""
    entry_confirmed: bool = False
    entry_type: str = ''             # 'fvg_fill', 'ob_retest', 'choch_entry'
    entry_price: float = 0.0
    suggested_sl: float = 0.0
    suggested_tp: float = 0.0
    rr_ratio: float = 0.0


@dataclass
class MTFResult:
    """Complete multi-timeframe analysis result."""
    htf: HTFAnalysis = field(default_factory=HTFAnalysis)
    mtf: MTFAnalysis = field(default_factory=MTFAnalysis)
    ltf: LTFAnalysis = field(default_factory=LTFAnalysis)
    htf_mtf_aligned: bool = False    # Does MTF structure agree with HTF bias?
    overall_bias: str = 'neutral'    # Final directional conclusion
    trade_permitted: bool = False    # All conditions met for entry?


def analyze_multi_timeframe(
    symbol: str,
    fetch_fn: callable,
) -> MTFResult:
    """Run complete multi-timeframe analysis for a symbol.

    Args:
        symbol: Trading pair
        fetch_fn: Function(symbol, timeframe, bars) -> DataFrame

    Returns:
        MTFResult with HTF/MTF/LTF analysis and overall conclusion
    """
    from app.utils.constants import MT5Timeframe

    result = MTFResult()

    # --- HTF Analysis (H4) ---
    df_h4 = fetch_fn(symbol, MT5Timeframe.H4, 200)
    if df_h4 is not None and len(df_h4) >= 50:
        result.htf = _analyze_htf(df_h4)

    # --- MTF Analysis (M15) ---
    df_m15 = fetch_fn(symbol, MT5Timeframe.M15, 200)
    if df_m15 is not None and len(df_m15) >= 50:
        result.mtf = _analyze_mtf(df_m15)

    # --- LTF Analysis (M5) ---
    df_m5 = fetch_fn(symbol, MT5Timeframe.M5, 100)
    if df_m5 is not None and len(df_m5) >= 20:
        result.ltf = _analyze_ltf(df_m5, result.htf, result.mtf)

    # --- Cross-TF alignment check ---
    result.htf_mtf_aligned = _check_alignment(result.htf, result.mtf)

    if result.htf.bias != 'neutral' and result.htf_mtf_aligned:
        result.overall_bias = result.htf.bias
        result.trade_permitted = True
    elif result.htf.bias != 'neutral':
        result.overall_bias = result.htf.bias
        result.trade_permitted = False  # MTF doesn't confirm yet
    else:
        result.trade_permitted = False

    return result


def _analyze_htf(df: pd.DataFrame) -> HTFAnalysis:
    """Analyze H4/Daily for directional bias and key levels.

    Determines:
    1. Swing structure (HH/HL = bullish, LH/LL = bearish)
    2. EMA alignment (8 vs 34)
    3. Key liquidity levels (previous day high/low, swing extremes)
    4. Premium/discount zones (Fibonacci 50% of recent swing range)
    """
    analysis = HTFAnalysis()

    close = df['close'].values
    high = df['high'].values
    low = df['low'].values

    # EMA bias
    ema_fast = pd.Series(close).ewm(span=8, adjust=False).mean().iloc[-1]
    ema_slow = pd.Series(close).ewm(span=34, adjust=False).mean().iloc[-1]

    if ema_fast > ema_slow * 1.001:
        analysis.bias = 'bullish'
        analysis.bias_confidence = min((ema_fast / ema_slow - 1) * 100, 1.0)
    elif ema_fast < ema_slow * 0.999:
        analysis.bias = 'bearish'
        analysis.bias_confidence = min((1 - ema_fast / ema_slow) * 100, 1.0)
    else:
        analysis.bias = 'neutral'
        analysis.bias_confidence = 0.3

    # Swing structure analysis
    from app.quant.indicators.smc import _find_swing_points
    sh, sl = _find_swing_points(df, lookback=5)

    sh_prices = [high[i] for i in range(len(sh)) if sh.iloc[i]]
    sl_prices = [low[i] for i in range(len(sl)) if sl.iloc[i]]

    if len(sh_prices) >= 2 and len(sl_prices) >= 2:
        hh = sh_prices[-1] > sh_prices[-2]
        hl = sl_prices[-1] > sl_prices[-2]
        if hh and hl:
            analysis.recent_structure = 'HH_HL'
            if analysis.bias == 'neutral':
                analysis.bias = 'bullish'
        elif not hh and not hl:
            analysis.recent_structure = 'LH_LL'
            if analysis.bias == 'neutral':
                analysis.bias = 'bearish'
        else:
            analysis.recent_structure = 'mixed'

    # Key levels
    if len(df) >= 24:
        recent_24 = df.iloc[-24:]
        analysis.previous_day_high = float(recent_24['high'].max())
        analysis.previous_day_low = float(recent_24['low'].min())

    # Premium/discount zones
    recent_high = float(high[-50:].max())
    recent_low = float(low[-50:].min())
    midpoint = (recent_high + recent_low) / 2
    analysis.premium_zone_start = midpoint  # Above = premium (sell zone)
    analysis.discount_zone_start = midpoint # Below = discount (buy zone)

    # S/R levels
    from app.quant.indicators.support_resistance import find_sr_levels
    from app.quant.indicators.scalping import atr as compute_atr
    atr_val = compute_atr(df, period=14).iloc[-1]
    if not pd.isna(atr_val):
        sr = find_sr_levels(df, float(atr_val), lookback=5, max_levels=5)
        analysis.key_resistance_levels = [r['price'] for r in sr['resistance']]
        analysis.key_support_levels = [s['price'] for s in sr['support']]

    return analysis


def _analyze_mtf(df: pd.DataFrame) -> MTFAnalysis:
    """Analyze M15/H1 for structure, FVGs, OBs, and sweeps."""
    analysis = MTFAnalysis()

    try:
        from app.quant.indicators.smc_detector import detect_all
        smc_result = detect_all(df, swing_lookback=5)

        analysis.active_fvgs = smc_result.fvgs
        analysis.active_order_blocks = smc_result.order_blocks
        analysis.recent_sweeps = smc_result.sweeps
        analysis.recent_structure_breaks = smc_result.structure_breaks
        analysis.market_structure = smc_result.market_structure_bias

        # Extract most recent CHoCH and BOS
        for sb in reversed(smc_result.structure_breaks):
            if sb.break_type == 'choch' and analysis.last_choch_direction is None:
                analysis.last_choch_direction = sb.direction
            elif sb.break_type == 'bos' and analysis.last_bos_direction is None:
                analysis.last_bos_direction = sb.direction

    except Exception as e:
        logger.debug(f"MTF analysis with smc_detector failed: {e}")
        # Fallback to basic smc.py
        from app.quant.indicators.smc import market_structure
        ms = market_structure(df, {'swing_lookback': 5})
        last_ms = ms.iloc[-1]
        if isinstance(last_ms, str):
            if 'bullish' in last_ms:
                analysis.market_structure = 'bullish'
            elif 'bearish' in last_ms:
                analysis.market_structure = 'bearish'

    return analysis


def _analyze_ltf(df: pd.DataFrame, htf: HTFAnalysis, mtf: MTFAnalysis) -> LTFAnalysis:
    """Analyze M5 for entry timing within the HTF/MTF setup.

    Looks for:
    1. Price retracing into an active FVG zone from MTF analysis
    2. LTF CHoCH/BOS confirming the HTF bias direction
    3. Entry at FVG midpoint with SL beyond the sweep/swing
    """
    analysis = LTFAnalysis()

    if htf.bias == 'neutral':
        return analysis

    current_price = df['close'].iloc[-1]
    direction = htf.bias

    # Check if price is in any active MTF FVG zone
    for fvg in mtf.active_fvgs:
        if fvg.direction != direction:
            continue
        if fvg.mitigated:
            continue
        if fvg.bottom <= current_price <= fvg.top:
            # Price is IN the FVG zone — check for LTF confirmation
            from app.quant.indicators.smc import market_structure
            ms = market_structure(df, {'swing_lookback': 3})
            last_ms = ms.iloc[-1]

            if isinstance(last_ms, str) and direction in last_ms:
                analysis.entry_confirmed = True
                analysis.entry_type = 'fvg_fill'
                analysis.entry_price = fvg.midpoint
                break

    return analysis


def _check_alignment(htf: HTFAnalysis, mtf: MTFAnalysis) -> bool:
    """Check if MTF structure aligns with HTF bias."""
    if htf.bias == 'neutral':
        return False
    return htf.bias == mtf.market_structure
```

**Dependencies:** Phases 0.2, 0.3, 0.4 (SMC detector, displacement, kill zones)
**Integration:** Called by the strategy router before confluence scoring. Provides the structural analysis that feeds into confluence scoring.
**Testing:** Run on 1 week of EURUSD data across all 3 timeframes, verify HTF bias matches visual assessment.
**Success criteria:** HTF/MTF alignment correctly identifies when structure agrees across timeframes. False positive rate < 30%.

### 4.2 Wire MTF Analyzer into Entry Pipeline

**Complexity:** M

**File to modify:** `/backend/django/app/quant/algorithms/cvd/entry.py`

**Integration:** Replace the simple regime check with full MTF analysis. The MTF result feeds into:
1. Confluence scorer (HTF bias, sweeps, FVGs, OBs all come from MTF analyzer)
2. SL/TP calculation (key levels from HTF analysis)
3. Order type validation (never trade against HTF bias)

**Dependencies:** Phase 4.1
**Testing:** Paper trade for 1 week, verify MTF analysis runs within the 60-second Celery task timeout.
**Success criteria:** No trades taken against HTF bias. MTF analysis completes in < 10 seconds per symbol.

---

## Phase 5: Full ICT Entry Model (Weeks 6-8)

**Goal:** Implement the complete 5-step ICT institutional entry model as the primary entry method for trending regimes.

### 5.1 Build ICT Entry Model

**Complexity:** L

**File to create:** `/backend/django/app/quant/algorithms/ict_entry.py`

The ICT 5-step confluence chain:
```
Step 1: HTF Bias (from mtf_analyzer.HTFAnalysis)
Step 2: Liquidity Sweep Detection (from smc_detector/smc.py)
Step 3: Market Structure Shift — CHoCH or BOS (from smc_detector/smc.py)
Step 4: Fair Value Gap Identification (from smc_detector/smc.py)
Step 5: LTF Entry at FVG with Confirmation (from mtf_analyzer.LTFAnalysis)
```

```python
"""
ICT Entry Model — 5-step institutional confluence chain.

The dominant methodology among consistently profitable retail forex traders.
Each step MUST confirm before entry. This is the highest-probability setup
available, combining liquidity engineering with structural price action.

Steps:
1. HTF Directional Bias (H4/Daily market structure)
2. Liquidity Sweep (stop hunt beyond swing high/low)
3. Market Structure Shift (CHoCH or BOS after sweep)
4. Fair Value Gap (3-candle imbalance zone)
5. LTF Entry at FVG with confirmation (M5 CHoCH/BOS)

Entry: FVG midpoint (OTE = 61.8-78.6% Fibonacci)
Stop: Beyond the sweep wick extreme
TP: Nearest opposing liquidity pool

References:
- elite_trader_research.md Section 2 "Core Entry Process"
- xaubot-ai architecture (654 trades, 63.9% WR, Sharpe 4.83)
"""

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

logger = logging.getLogger('app.quant.algorithms.ict_entry')


@dataclass
class ICTSetup:
    """A validated ICT entry setup."""
    direction: str          # 'BUY' or 'SELL'
    entry_price: float      # FVG midpoint
    stop_loss: float        # Beyond sweep wick
    take_profit: float      # Nearest opposing liquidity
    rr_ratio: float         # Risk:Reward
    steps_confirmed: int    # How many of the 5 steps confirmed (5 = all)
    step_details: dict      # Per-step confirmation details
    confluence_score: int   # Synced with confluence scorer


def evaluate_ict_entry(
    symbol: str,
    mtf_result,           # MTFResult from mtf_analyzer
    df_htf: pd.DataFrame,
    df_mtf: pd.DataFrame,
    df_ltf: pd.DataFrame,
) -> Optional[ICTSetup]:
    """Evaluate whether a full ICT entry setup exists.

    This is the "gold standard" entry — all 5 steps must pass.
    Called by the strategy router when regime = TRENDING.

    Args:
        symbol: Trading pair
        mtf_result: Output from analyze_multi_timeframe()
        df_htf: H4 data
        df_mtf: M15 data
        df_ltf: M5 data

    Returns:
        ICTSetup if all 5 steps confirmed, None otherwise
    """
    steps = {}
    direction = None

    # Step 1: HTF Bias
    if mtf_result.htf.bias == 'neutral':
        return None
    direction = 'BUY' if mtf_result.htf.bias == 'bullish' else 'SELL'
    steps['htf_bias'] = {
        'confirmed': True,
        'detail': f"{mtf_result.htf.bias} ({mtf_result.htf.recent_structure})",
    }

    # Step 2: Liquidity Sweep
    sweep = _find_recent_sweep(mtf_result.mtf, direction)
    if sweep is None:
        return None
    steps['liquidity_sweep'] = {
        'confirmed': True,
        'detail': f"Swept {sweep.level_price:.5f}, wick to {sweep.sweep_price:.5f}",
    }

    # Step 3: Market Structure Shift (CHoCH or BOS after sweep)
    mss = _find_structure_shift_after_sweep(mtf_result.mtf, sweep, direction)
    if mss is None:
        return None
    steps['market_structure_shift'] = {
        'confirmed': True,
        'detail': f"{mss.break_type.upper()} {mss.direction} at {mss.break_price:.5f}",
    }

    # Step 4: FVG after MSS
    fvg = _find_fvg_after_mss(mtf_result.mtf, mss, direction)
    if fvg is None:
        return None
    steps['fvg'] = {
        'confirmed': True,
        'detail': f"FVG zone {fvg.bottom:.5f} - {fvg.top:.5f}",
    }

    # Step 5: LTF confirmation at FVG
    ltf_confirmed = _check_ltf_confirmation(df_ltf, fvg, direction)
    if not ltf_confirmed:
        return None
    steps['ltf_confirmation'] = {
        'confirmed': True,
        'detail': 'LTF structure confirms at FVG zone',
    }

    # Calculate entry, SL, TP
    entry_price = fvg.midpoint
    stop_loss = sweep.sweep_price  # Beyond the sweep wick
    if direction == 'BUY':
        # TP at nearest HTF resistance (liquidity pool)
        tp_levels = mtf_result.htf.key_resistance_levels
        take_profit = tp_levels[0] if tp_levels else entry_price + abs(entry_price - stop_loss) * 3
        sl_distance = entry_price - stop_loss
    else:
        tp_levels = mtf_result.htf.key_support_levels
        take_profit = tp_levels[0] if tp_levels else entry_price - abs(stop_loss - entry_price) * 3
        sl_distance = stop_loss - entry_price

    tp_distance = abs(take_profit - entry_price)
    rr_ratio = tp_distance / sl_distance if sl_distance > 0 else 0

    if rr_ratio < 1.5:
        logger.info(f"ICT: {symbol} R:R too low ({rr_ratio:.1f}), skipping")
        return None

    setup = ICTSetup(
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        rr_ratio=round(rr_ratio, 2),
        steps_confirmed=5,
        step_details=steps,
        confluence_score=9,  # 5-step ICT = automatic 9+ confluence
    )

    logger.info(
        f"ICT SETUP: {symbol} {direction} entry={entry_price:.5f} "
        f"SL={stop_loss:.5f} TP={take_profit:.5f} R:R={rr_ratio:.1f}"
    )

    return setup


def _find_recent_sweep(mtf: 'MTFAnalysis', direction: str):
    """Find a liquidity sweep in the last N bars matching direction."""
    target_dir = 'bullish' if direction == 'BUY' else 'bearish'
    for sweep in reversed(mtf.recent_sweeps):
        if sweep.direction == target_dir:
            return sweep
    return None


def _find_structure_shift_after_sweep(mtf: 'MTFAnalysis', sweep, direction: str):
    """Find a CHoCH or BOS that occurred after the sweep."""
    target_dir = 'bullish' if direction == 'BUY' else 'bearish'
    for sb in reversed(mtf.recent_structure_breaks):
        if sb.direction == target_dir and sb.bar_index > sweep.bar_index:
            return sb
    return None


def _find_fvg_after_mss(mtf: 'MTFAnalysis', mss, direction: str):
    """Find an active FVG that formed after the market structure shift."""
    target_dir = 'bullish' if direction == 'BUY' else 'bearish'
    for fvg in mtf.active_fvgs:
        if fvg.direction == target_dir and fvg.bar_index >= mss.bar_index and not fvg.mitigated:
            return fvg
    return None


def _check_ltf_confirmation(df_ltf: pd.DataFrame, fvg, direction: str) -> bool:
    """Check if LTF (M5) shows a CHoCH/BOS confirming entry at the FVG zone."""
    if df_ltf is None or len(df_ltf) < 10:
        return False

    current_price = df_ltf['close'].iloc[-1]

    # Price must be within or near the FVG zone
    buffer = (fvg.top - fvg.bottom) * 0.5
    if not (fvg.bottom - buffer <= current_price <= fvg.top + buffer):
        return False

    # Check for LTF structure confirmation
    from app.quant.indicators.smc import market_structure
    ms = market_structure(df_ltf, {'swing_lookback': 3})

    target = 'bullish' if direction == 'BUY' else 'bearish'
    # Check last 3 bars for confirmation
    for i in range(max(0, len(ms) - 3), len(ms)):
        val = ms.iloc[i]
        if isinstance(val, str) and target in val:
            return True

    return False
```

**Dependencies:** Phase 4 (MTF analyzer), Phase 1 (confluence scorer)
**Integration:** Registered as a strategy in the strategy router. Selected when regime = TRENDING and at least 1 symbol has an active liquidity sweep.
**Testing:** Backtest on 3 months of EURUSD/GBPUSD M15 data. Target: > 55% WR, R:R > 1.5.
**Success criteria:** Successfully identifies and enters at least 2-3 ICT setups per week per pair on paper. Win rate > 55%.

### 5.2 Integrate ICT Entry with Confluence Scorer

**Complexity:** S

**File to modify:** `/backend/django/app/quant/algorithms/confluence_scorer.py`

**Changes:** When an ICT 5-step setup is fully confirmed, it automatically scores 9+ on confluence (the steps themselves ARE the confluence factors). Add a helper:

```python
def score_ict_setup(ict_setup: 'ICTSetup') -> ConfluenceResult:
    """Convert a validated ICT setup into a confluence score.

    A 5-step ICT setup automatically gets:
    - HTF bias: +2
    - Liquidity sweep: +2
    - FVG: +1
    - Displacement (implied): +1
    - Kill zone (checked separately): +0 or +1
    - Regime: +1
    - Structure break (CHoCH/BOS): +1 (via OB points)
    = 8-9 base, plus any additional confluence
    """
```

**Dependencies:** Phases 1.1 and 5.1
**Testing:** Verify ICT setups always score >= 8.
**Success criteria:** No ICT setup gets rejected by confluence scorer.

---

## Phase 6: XGBoost Meta-Model (Weeks 8-10)

**Goal:** Upgrade the ML pipeline from the current 11-feature LightGBM to a comprehensive XGBoost meta-model with SMC features, regime context, and adaptive retraining on regime shifts.

### 6.1 Add SMC Features to Feature Extraction

**Complexity:** M

**File to modify:** `/backend/django/app/quant/ml/features.py`

**New features to add to FEATURE_NAMES and extraction logic:**

```python
# SMC features (new)
'fvg_count',              # Number of active FVGs on entry TF
'ob_count',               # Number of active order blocks
'recent_sweep',           # 1 if sweep in last 5 bars, 0 otherwise
'displacement',           # 1 if displacement detected, 0 otherwise
'structure_break_type',   # 0=none, 1=BOS, 2=CHoCH
'structure_direction',    # -1=bearish, 0=none, 1=bullish
'fvg_distance_atr',       # Distance to nearest FVG / ATR (proximity signal)
'ob_distance_atr',        # Distance to nearest OB / ATR
'confluence_score',       # 0-11 confluence score
'kill_zone_weight',       # Kill zone multiplier (0.3-2.0)
'htf_bias_aligned',       # 1 if HTF agrees with trade direction, 0 otherwise
```

**In `extract_features()`:**
```python
# SMC features
from app.quant.indicators.smc_detector import detect_all
smc = detect_all(df)
features['fvg_count'] = len([f for f in smc.fvgs if not f.mitigated])
features['ob_count'] = len(smc.order_blocks)
features['recent_sweep'] = 1 if any(
    s.bar_index >= len(df) - 5 for s in smc.sweeps
) else 0
# ... etc.
```

**Update SELECTED_FEATURES to include the most predictive new features once data accumulates.**

**Dependencies:** Phase 0.2 (smc_detector), Phase 1 (confluence scorer)
**Testing:** Verify feature extraction produces valid values for all new features.
**Success criteria:** 41 total features extracted (30 existing + 11 new), all populated in TradeFeature.features_json.

### 6.2 Switch to XGBoost with Expanded Feature Set

**Complexity:** M

**File to modify:** `/backend/django/app/quant/ml/trainer.py`

**Changes:**
- Add XGBoost as primary model (keep LightGBM as fallback)
- Expand SELECTED_FEATURES to include SMC features once enough data exists
- Add regime-shift-triggered retraining
- Add walk-forward validation (train on older data, validate on recent)

```python
# Add to requirements.txt:
# xgboost

def train_model():
    """Train XGBoost meta-model with expanded feature set."""
    try:
        import xgboost as xgb
    except ImportError:
        # Fall back to LightGBM
        return _train_lightgbm()

    # ... same data gathering as before ...

    # Adaptive feature selection based on dataset size
    if len(X) < 100:
        use_features = SELECTED_FEATURES  # Original 11
    elif len(X) < 300:
        use_features = SELECTED_FEATURES + ['fvg_count', 'recent_sweep', 'confluence_score']
    else:
        use_features = SELECTED_FEATURES + SMC_FEATURES  # Full 22

    # XGBoost params (regularized for small datasets)
    params = {
        'n_estimators': 200,
        'max_depth': 5,
        'learning_rate': 0.05,
        'subsample': 0.8,
        'colsample_bytree': 0.7,
        'reg_alpha': 0.1,    # L1
        'reg_lambda': 1.0,   # L2
        'scale_pos_weight': len(y[y==0]) / max(len(y[y==1]), 1),  # Class imbalance
        'random_state': 42,
        'eval_metric': 'logloss',
        'use_label_encoder': False,
    }

    model = xgb.XGBClassifier(**params)
    # ... rest of training, CV, SHAP analysis ...
```

**Add to `requirements.txt`:**
```
xgboost
```

**Dependencies:** Phase 6.1
**Testing:** Compare XGBoost vs LightGBM accuracy on same dataset using cross-validation.
**Success criteria:** XGBoost achieves >= LightGBM accuracy. Feature importance shows SMC features contributing meaningfully.

### 6.3 Add Regime-Shift Triggered Retraining

**Complexity:** S

**File to modify:** `/backend/django/app/quant/ml/trainer.py`

**New function:**
```python
def should_retrain():
    """Check if retraining is needed.

    Triggers:
    1. N new trades since last training (existing logic)
    2. Regime shift detected (new): dominant regime changed since last training
    3. Model accuracy decay: rolling WR deviates significantly from model predictions
    """
```

**Integration:** Already called by `tasks.run_ml_retrain` every 30 minutes. Just add regime-shift logic.

**Dependencies:** Phase 2 (enhanced HMM regime)
**Testing:** Simulate regime shift, verify retraining triggers within 30 minutes.
**Success criteria:** Model retrains automatically when regime shifts, maintaining prediction accuracy.

---

## Phase 7: Position Manager Enhancement (Ongoing)

**Goal:** Upgrade the existing MFE-optimized position manager with structure-based trailing, dynamic phase transitions, and partial close refinement.

### 7.1 Structure-Based Trailing (Replace Fixed ATR Trail)

**Complexity:** M

**File to modify:** `/backend/django/app/quant/algorithms/position_manager.py`

The existing `_check_swing_trail()` already uses S/R levels from `support_resistance.py`. Enhance it with:

1. **MTF-aware swing detection:** Use H1 swing highs/lows for trailing (more significant than M15)
2. **Never trail backwards:** Enforce that trailing stop only moves in the profit direction
3. **Structure invalidation exit:** If the swing structure that validated the entry breaks, exit immediately

**Changes to `_check_swing_trail()`:**

```python
def _check_swing_trail(position, trade, df, current_atr):
    """Enhanced: Trail using multi-TF structure, not just entry-TF swings.

    Phase 3a: Trail below M15 swing lows (tight, responsive)
    Phase 3b: After 2R profit, switch to H1 swing lows (wider, for bigger moves)
    Phase 3c: After 4R profit, switch to H4 swing lows (let it ride)
    """
    if not trade.breakeven_moved:
        return

    profit_distance = _get_profit_distance(position)

    # Determine which timeframe to use for trailing based on profit
    if trade.entry_atr and profit_distance > trade.entry_atr * 4:
        # 4R+ profit: use H4 structure (major levels only)
        trailing_tf = MT5Timeframe.H4
        swing_lookback = 5
    elif trade.entry_atr and profit_distance > trade.entry_atr * 2:
        # 2R+ profit: use H1 structure
        trailing_tf = MT5Timeframe.H1
        swing_lookback = 5
    else:
        # Default: use entry timeframe
        trailing_tf = _resolve_timeframe(trade)
        swing_lookback = SWING_TRAIL_LOOKBACK

    # ... rest of trailing logic using trailing_tf ...
```

**Dependencies:** Existing position_manager.py, support_resistance.py
**Testing:** Backtest trailing performance on 100 historical trades, compare avg profit captured vs current.
**Success criteria:** Average profit capture increases by >= 10% (from current 55% MFE capture).

### 7.2 Partial Close System Refinement

**Complexity:** S

**File to modify:** `/backend/django/app/quant/algorithms/position_manager.py`

**Current:** Close 33% at 2R, then trail remainder.

**New 3-tier partial close:**
```python
# Phase 2a: Close 30% at 1.5R (lock some profit early)
# Phase 2b: Close 30% at 3R (let middle portion ride)
# Phase 2c: Trail remaining 40% on H1 structure until invalidation
```

**Changes:**
```python
PARTIAL_CLOSE_TIERS = [
    {'atr_mult': 1.5, 'close_pct': 0.30, 'flag': 'partial_1'},
    {'atr_mult': 3.0, 'close_pct': 0.30, 'flag': 'partial_2'},
]
# Remaining 40% trails on structure until exit
```

**Dependencies:** None (existing position manager)
**Testing:** Compare average closed profit on winning trades before/after change.
**Success criteria:** Average win size increases while maintaining win rate.

### 7.3 Dynamic Phase Transitions Based on Price Action

**Complexity:** M

**File to modify:** `/backend/django/app/quant/algorithms/position_manager.py`

**Current phases are time-based:** Phase 0 at 0-15min, Phase 1 at 15-30min, etc.

**New dynamic transitions based on what price is doing:**
```python
def _determine_phase(position, trade, current_pnl, profit_distance, df):
    """Determine management phase from price action, not just time.

    Phase transitions:
    - Hit MFE threshold → lock (regardless of time)
    - Break structure → tighten trail (regardless of profit)
    - Approaching S/R level → prepare partial close
    - Momentum fading (vol contraction) → tighten trail
    """
```

**Dependencies:** Phase 4 (MTF analyzer for structure awareness)
**Testing:** Paper trade for 2 weeks, compare phase transition timing vs time-based.
**Success criteria:** Dynamic phases capture at least as much profit as time-based phases.

---

## Dependency Graph

```
Phase 0 (Quick Wins)                    ← START HERE
  ├── 0.1 Install smartmoneyconcepts
  ├── 0.2 SMC Detector module
  ├── 0.3 Displacement module
  ├── 0.4 Kill Zone module
  └── 0.5 Wire into entry pipeline
         │
Phase 1 (Confluence Scorer)             ← Depends on Phase 0
  ├── 1.1 Build scorer
  ├── 1.2 Integrate into entry
  └── 1.3 Store in TradeFeature
         │
Phase 2 (HMM Enhancement)              ← Independent of Phase 1
  ├── 2.1 Enhanced HMM
  ├── 2.2 Replace MarketRegime
  └── 2.3 Cross-pair consensus
         │
Phase 3 (Strategy Router)              ← Depends on Phase 2
  ├── 3.1 Build router
  └── 3.2 Integrate into dispatcher
         │
Phase 4 (MTF Analyzer)                 ← Depends on Phases 0, 2
  ├── 4.1 Build MTF engine
  └── 4.2 Wire into entry pipeline
         │
Phase 5 (ICT Entry Model)              ← Depends on Phase 4
  ├── 5.1 Build ICT entry
  └── 5.2 Integrate with confluence
         │
Phase 6 (XGBoost Meta-Model)           ← Depends on Phases 0, 1
  ├── 6.1 Add SMC features
  ├── 6.2 Switch to XGBoost
  └── 6.3 Regime-shift retraining
         │
Phase 7 (Position Manager)             ← Can start anytime (ongoing)
  ├── 7.1 Structure-based trailing
  ├── 7.2 Partial close refinement
  └── 7.3 Dynamic phase transitions
```

**Parallel tracks:**
- Phase 2 can run in parallel with Phase 1
- Phase 7 can start anytime (independent improvements)
- Phase 6 can start after Phases 0-1 (needs SMC features collecting)

---

## File Summary

### New files to create:
| File | Phase | Purpose |
|------|-------|---------|
| `indicators/smc_detector.py` | 0.2 | Unified SMC detection with structured dataclasses |
| `indicators/displacement.py` | 0.3 | Displacement (institutional momentum) detection |
| `indicators/kill_zones.py` | 0.4 | Session-aware kill zone weighting |
| `algorithms/confluence_scorer.py` | 1.1 | 0-11 point confluence scoring system |
| `algorithms/strategy_router.py` | 3.1 | Dynamic per-symbol strategy selection |
| `algorithms/mtf_analyzer.py` | 4.1 | Multi-timeframe analysis engine |
| `algorithms/ict_entry.py` | 5.1 | Full ICT 5-step entry model |

### Existing files to modify:
| File | Phase | Changes |
|------|-------|---------|
| `requirements.txt` | 0.1 | Add `smartmoneyconcepts`, `xgboost` |
| `backtester_generic.py` | 0.5 | Register DISPLACEMENT indicator |
| `algorithms/cvd/entry.py` | 0.5, 1.2, 4.2 | Kill zone weight, confluence gate, MTF integration |
| `ml/features.py` | 0.5, 6.1 | Kill zone + displacement + SMC features |
| `ml/regime_hmm.py` | 2.1, 2.3 | Enhanced HMM with model caching + cross-pair |
| `algorithms/regime.py` | 2.2 | Use enhanced HMM as primary regime source |
| `tasks.py` | 3.2 | Strategy router integration |
| `ml/trainer.py` | 6.2, 6.3 | XGBoost model + regime-shift retraining |
| `algorithms/position_manager.py` | 7.1, 7.2, 7.3 | Structure trail + partial close + dynamic phases |
| `nexus/models.py` | 1.3, 2.2 | confluence_score field, hmm_* fields |

### Django migrations needed:
- Phase 1.3: Add `confluence_score`, `confluence_factors` to Trade
- Phase 2.2: Add `hmm_state`, `hmm_label`, `hmm_confidence` to MarketRegime

---

## Risk Mitigation

1. **Every phase is independently deployable.** Phase 0 adds value without Phase 1. Phase 7 improves position management regardless of other phases.

2. **All new modules have fallback paths.** If smartmoneyconcepts fails to import, smc_detector falls back to custom smc.py. If XGBoost unavailable, LightGBM is used. If HMM fails, rule-based regime is used.

3. **Paper trading first.** Each phase should run in paper mode for at least 1 week before going live with real capital.

4. **Feature flags.** New systems (confluence gating, strategy routing, ICT entry) should be behind Redis-based feature flags that can be toggled without deployment.

5. **Performance monitoring.** Every phase adds logging. The dashboard already shows ML metrics. Extend it to show confluence score distribution, regime classification accuracy, and routing decisions.

---

## Success Metrics (End State)

| Metric | Current | Target |
|--------|---------|--------|
| Win Rate | 46% | > 55% |
| Profit Factor | ~1.0 | > 1.5 |
| Avg Winner / Avg Loser | ~1.0 | > 1.5 |
| Max Drawdown | ~20% | < 10% |
| Sharpe Ratio | < 0.5 | > 1.0 |
| MFE Capture | 55% | > 70% |
| Trades per week | ~90 | ~40-60 (fewer, higher quality) |
| Confluence score avg | N/A | > 6/11 |

The goal is NOT more trades — it is higher quality trades with better risk management. Fewer trades at higher confluence should yield better risk-adjusted returns.
