"""
ICT 5-Step Institutional Entry Model.

The Inner Circle Trader methodology distilled into a sequential confirmation
chain.  Each step MUST confirm in temporal order on M15 data before an entry
is valid:

    1. HTF Bias        -- H4 directional bias (bullish / bearish)
    2. Liquidity Sweep -- price takes out swing stops, then reverses
    3. Market Structure Shift -- CHoCH or BOS after the sweep
    4. Fair Value Gap  -- 3-candle imbalance zone forms after the MSS
    5. Price at FVG    -- current price enters the FVG zone

Entry:     FVG midpoint
Stop Loss: Beyond the sweep wick extreme
Take Profit: Nearest opposing HTF S/R level
Minimum R:R: 1.5

Livermore: "The big money is not in the buying or selling,
but in the waiting."  This model waits for ALL five steps.

Design:
- Fail-open: any detector failure -> None (no setup), never crash
- Temporal ordering enforced via bar indices
- Recency window: last 20 M15 bars (5 hours) -- stale setups are invalid
- Direction logic:
    Bullish: sell-side sweep (Liq=-1) -> bullish MSS -> bullish FVG (FVG=1) -> BUY
    Bearish: buy-side sweep (Liq=1)  -> bearish MSS -> bearish FVG (FVG=-1) -> SELL
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger('ict_entry')

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Only consider signals from the last N bars on M15 (20 bars = 5 hours)
RECENCY_WINDOW = 20

# Minimum reward-to-risk ratio to accept a setup
MIN_RR_RATIO = 1.5

# How close price must be to the FVG zone to trigger step 5.
# Expressed as a fraction of the FVG height added as a buffer on each side.
FVG_PROXIMITY_BUFFER = 0.5

# Swing lookback for the SMC detectors (bars on each side)
SMC_SWING_LOOKBACK = 5

# SL buffer beyond the sweep wick (in ATR fraction)
SL_BUFFER_ATR_FRACTION = 0.3

# Minimum HTF bias confidence to proceed
MIN_HTF_CONFIDENCE = 0.3


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ICTSetup:
    """A fully confirmed ICT 5-step institutional entry setup."""
    symbol: str
    direction: str              # 'BUY' or 'SELL'
    entry_price: float          # FVG midpoint
    stop_loss: float            # Beyond the sweep wick extreme
    take_profit: float          # Nearest opposing liquidity / S/R level
    rr_ratio: float             # Reward-to-risk ratio
    steps_confirmed: int        # Always 5 for a valid setup
    step_details: Dict          # Per-step info for logging and analysis
    confluence_score: int       # Auto 9+ for full 5-step chain
    fvg_zone: Tuple[float, float]  # (top, bottom) of the FVG
    sweep_level: float          # Price level that was swept
    mss_bar_idx: int            # Bar index of the market structure shift
    fvg_bar_idx: int            # Bar index where the FVG was detected

    def to_log_string(self) -> str:
        """One-line summary for logging."""
        return (
            f"ICT SETUP [{self.symbol} {self.direction}]: "
            f"entry={self.entry_price:.5f} SL={self.stop_loss:.5f} "
            f"TP={self.take_profit:.5f} R:R={self.rr_ratio:.2f} "
            f"confluence={self.confluence_score} "
            f"FVG=({self.fvg_zone[0]:.5f}-{self.fvg_zone[1]:.5f}) "
            f"sweep={self.sweep_level:.5f}"
        )

    def to_dict(self) -> dict:
        """Dict representation for API responses and ML training data."""
        return {
            'symbol': self.symbol,
            'direction': self.direction,
            'entry_price': self.entry_price,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'rr_ratio': self.rr_ratio,
            'steps_confirmed': self.steps_confirmed,
            'step_details': self.step_details,
            'confluence_score': self.confluence_score,
            'fvg_zone': list(self.fvg_zone),
            'sweep_level': self.sweep_level,
        }


# ---------------------------------------------------------------------------
# Step 1: HTF Bias
# ---------------------------------------------------------------------------

def _check_step1_htf_bias(symbol: str) -> Optional[dict]:
    """Check for a clear H4 directional bias.

    Returns dict with 'direction' ('bullish'/'bearish') and 'bias' object,
    or None if bias is neutral or confidence is too low.
    """
    try:
        from app.quant.algorithms.mtf_analyzer import get_htf_bias

        bias = get_htf_bias(symbol)

        if bias.bias == 'neutral':
            logger.debug(f"ICT {symbol} step1: HTF bias is neutral -- no setup")
            return None

        if bias.confidence < MIN_HTF_CONFIDENCE:
            logger.debug(
                f"ICT {symbol} step1: HTF bias {bias.bias} but confidence "
                f"{bias.confidence:.2f} < {MIN_HTF_CONFIDENCE} -- skipping"
            )
            return None

        logger.debug(
            f"ICT {symbol} step1 PASS: HTF bias={bias.bias} "
            f"confidence={bias.confidence:.2f} "
            f"EMA={bias.ema_direction} swing={bias.swing_structure} "
            f"zone={bias.premium_discount}"
        )

        return {
            'direction': bias.bias,
            'bias': bias,
            'detail': (
                f"HTF {bias.bias} (conf={bias.confidence:.2f}, "
                f"EMA={bias.ema_direction}, swing={bias.swing_structure}, "
                f"zone={bias.premium_discount})"
            ),
        }

    except Exception as e:
        logger.warning(f"ICT {symbol} step1: HTF bias check failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Step 2: Liquidity Sweep
# ---------------------------------------------------------------------------

def _check_step2_liquidity_sweep(
    df: pd.DataFrame,
    direction: str,
    symbol: str,
) -> Optional[dict]:
    """Find a recent liquidity sweep aligned with the bias direction.

    For a bullish setup: look for a sell-side sweep (Liquidity == -1)
        => price swept below swing lows (stop hunt), taking out sell stops
    For a bearish setup: look for a buy-side sweep (Liquidity == 1)
        => price swept above swing highs (stop hunt), taking out buy stops

    Returns dict with 'bar_idx', 'level', 'detail' or None.
    """
    try:
        from app.quant.indicators.smc_detector import detect_liquidity_sweeps

        liq_df = detect_liquidity_sweeps(df, swing_lookback=SMC_SWING_LOOKBACK)

        if liq_df is None or len(liq_df) == 0:
            logger.debug(f"ICT {symbol} step2: liquidity detector returned empty")
            return None

        # Determine which sweep type we need
        # Bullish setup -> sell-side sweep (Liq == -1): institutions swept sell stops
        # Bearish setup -> buy-side sweep (Liq == 1): institutions swept buy stops
        target_liq = -1 if direction == 'bullish' else 1
        sweep_label = 'sell-side' if direction == 'bullish' else 'buy-side'

        n = len(df)
        recency_start = max(0, n - RECENCY_WINDOW)

        # Search for the most recent matching sweep within the recency window
        best_sweep = None
        for i in range(n - 1, recency_start - 1, -1):
            liq_val = liq_df['Liquidity'].iloc[i]
            swept_val = liq_df['Swept'].iloc[i]

            if pd.isna(liq_val) or liq_val != target_liq:
                continue

            # Accept both swept and non-swept liquidity pools.
            # A swept pool (Swept == 1) means price already took the stops.
            # An un-swept pool that price is currently probing is also valid
            # (the sweep is happening NOW).  But prefer swept pools.
            level = liq_df['Level'].iloc[i]
            if pd.isna(level):
                continue

            best_sweep = {
                'bar_idx': i,
                'level': float(level),
                'swept': not pd.isna(swept_val) and swept_val == 1,
            }
            break  # Most recent match is best

        if best_sweep is None:
            logger.debug(
                f"ICT {symbol} step2: no {sweep_label} sweep in last "
                f"{RECENCY_WINDOW} bars"
            )
            return None

        # For a valid ICT setup the sweep wick gives us the SL level.
        # For sell-side sweeps, the extreme is the low of the sweep bar.
        # For buy-side sweeps, the extreme is the high of the sweep bar.
        sweep_bar_idx = best_sweep['bar_idx']
        if direction == 'bullish':
            sweep_extreme = float(df['low'].iloc[sweep_bar_idx])
        else:
            sweep_extreme = float(df['high'].iloc[sweep_bar_idx])

        detail = (
            f"{sweep_label} sweep at bar {sweep_bar_idx} "
            f"level={best_sweep['level']:.5f} "
            f"extreme={sweep_extreme:.5f} "
            f"swept={'yes' if best_sweep['swept'] else 'in-progress'}"
        )
        logger.debug(f"ICT {symbol} step2 PASS: {detail}")

        return {
            'bar_idx': sweep_bar_idx,
            'level': best_sweep['level'],
            'extreme': sweep_extreme,
            'detail': detail,
        }

    except Exception as e:
        logger.warning(f"ICT {symbol} step2: liquidity sweep check failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Step 3: Market Structure Shift (CHoCH / BOS)
# ---------------------------------------------------------------------------

def _check_step3_market_structure_shift(
    df: pd.DataFrame,
    sweep_bar_idx: int,
    direction: str,
    symbol: str,
) -> Optional[dict]:
    """Find a CHoCH or BOS AFTER the sweep bar, confirming a reversal.

    For a bullish setup: need a bullish CHoCH (CHOCH == 1) or bullish BOS (BOS == 1)
    For a bearish setup: need a bearish CHoCH (CHOCH == -1) or bearish BOS (BOS == -1)

    CHoCH is preferred over BOS (it is a reversal signal, not just continuation).
    The MSS must occur AFTER the sweep (temporal ordering).

    Returns dict with 'bar_idx', 'type' (CHoCH/BOS), 'level', 'detail' or None.
    """
    try:
        from app.quant.indicators.smc_detector import detect_market_structure

        ms_df = detect_market_structure(
            df, swing_lookback=SMC_SWING_LOOKBACK, close_break=True,
        )

        if ms_df is None or len(ms_df) == 0:
            logger.debug(f"ICT {symbol} step3: market structure detector returned empty")
            return None

        # Target direction values
        target_val = 1 if direction == 'bullish' else -1
        n = len(df)
        recency_start = max(0, n - RECENCY_WINDOW)

        # Search for MSS after the sweep bar, within recency window
        best_mss = None
        for i in range(sweep_bar_idx + 1, n):
            if i < recency_start:
                continue

            choch_val = ms_df['CHOCH'].iloc[i]
            bos_val = ms_df['BOS'].iloc[i]
            level = ms_df['Level'].iloc[i]

            # Prefer CHoCH (reversal) over BOS (continuation)
            if not pd.isna(choch_val) and choch_val == target_val:
                best_mss = {
                    'bar_idx': i,
                    'type': 'CHoCH',
                    'level': float(level) if not pd.isna(level) else None,
                }
                break  # CHoCH found -- stop searching

            if not pd.isna(bos_val) and bos_val == target_val:
                # Record BOS but keep searching for a CHoCH
                if best_mss is None:
                    best_mss = {
                        'bar_idx': i,
                        'type': 'BOS',
                        'level': float(level) if not pd.isna(level) else None,
                    }
                # Don't break -- a later CHoCH would be better

        if best_mss is None:
            dir_label = 'bullish' if direction == 'bullish' else 'bearish'
            logger.debug(
                f"ICT {symbol} step3: no {dir_label} MSS after sweep bar "
                f"{sweep_bar_idx} within recency window"
            )
            return None

        detail = (
            f"{best_mss['type']} at bar {best_mss['bar_idx']} "
            f"({'bullish' if target_val == 1 else 'bearish'}) "
            f"level={best_mss['level']}"
        )
        logger.debug(f"ICT {symbol} step3 PASS: {detail}")

        return {
            'bar_idx': best_mss['bar_idx'],
            'type': best_mss['type'],
            'level': best_mss['level'],
            'detail': detail,
        }

    except Exception as e:
        logger.warning(f"ICT {symbol} step3: market structure shift check failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Step 4: Fair Value Gap
# ---------------------------------------------------------------------------

def _check_step4_fvg(
    df: pd.DataFrame,
    mss_bar_idx: int,
    direction: str,
    symbol: str,
) -> Optional[dict]:
    """Find an unmitigated FVG that formed AFTER the MSS.

    For a bullish setup: need a bullish FVG (FVG == 1)
    For a bearish setup: need a bearish FVG (FVG == -1)

    Returns dict with 'bar_idx', 'top', 'bottom', 'midpoint', 'detail' or None.
    """
    try:
        from app.quant.indicators.smc_detector import detect_fair_value_gaps

        fvg_df = detect_fair_value_gaps(df, swing_lookback=SMC_SWING_LOOKBACK)

        if fvg_df is None or len(fvg_df) == 0:
            logger.debug(f"ICT {symbol} step4: FVG detector returned empty")
            return None

        target_val = 1 if direction == 'bullish' else -1
        n = len(df)

        # Search for FVG after the MSS bar
        best_fvg = None
        for i in range(mss_bar_idx + 1, n):
            fvg_val = fvg_df['FVG'].iloc[i]
            mitigated = fvg_df['MitigatedIndex'].iloc[i]

            if pd.isna(fvg_val) or fvg_val != target_val:
                continue

            # Must be unmitigated (MitigatedIndex is NaN)
            if not pd.isna(mitigated):
                continue

            top = fvg_df['Top'].iloc[i]
            bottom = fvg_df['Bottom'].iloc[i]

            if pd.isna(top) or pd.isna(bottom):
                continue

            top_f = float(top)
            bottom_f = float(bottom)
            midpoint = (top_f + bottom_f) / 2.0

            best_fvg = {
                'bar_idx': i,
                'top': top_f,
                'bottom': bottom_f,
                'midpoint': midpoint,
            }
            # Take the first valid FVG after MSS (closest to the structure shift)
            break

        # If no FVG found strictly after MSS, also check if an FVG formed
        # ON the MSS bar itself (some aggressive setups have FVG + MSS on the
        # same displacement candle).
        if best_fvg is None:
            fvg_val = fvg_df['FVG'].iloc[mss_bar_idx]
            mitigated = fvg_df['MitigatedIndex'].iloc[mss_bar_idx]
            if (not pd.isna(fvg_val) and fvg_val == target_val
                    and pd.isna(mitigated)):
                top = fvg_df['Top'].iloc[mss_bar_idx]
                bottom = fvg_df['Bottom'].iloc[mss_bar_idx]
                if not pd.isna(top) and not pd.isna(bottom):
                    top_f = float(top)
                    bottom_f = float(bottom)
                    best_fvg = {
                        'bar_idx': mss_bar_idx,
                        'top': top_f,
                        'bottom': bottom_f,
                        'midpoint': (top_f + bottom_f) / 2.0,
                    }

        if best_fvg is None:
            fvg_label = 'bullish' if direction == 'bullish' else 'bearish'
            logger.debug(
                f"ICT {symbol} step4: no unmitigated {fvg_label} FVG "
                f"after MSS bar {mss_bar_idx}"
            )
            return None

        detail = (
            f"{'bullish' if target_val == 1 else 'bearish'} FVG at bar "
            f"{best_fvg['bar_idx']} "
            f"zone=({best_fvg['top']:.5f}-{best_fvg['bottom']:.5f}) "
            f"midpoint={best_fvg['midpoint']:.5f}"
        )
        logger.debug(f"ICT {symbol} step4 PASS: {detail}")

        return {
            'bar_idx': best_fvg['bar_idx'],
            'top': best_fvg['top'],
            'bottom': best_fvg['bottom'],
            'midpoint': best_fvg['midpoint'],
            'detail': detail,
        }

    except Exception as e:
        logger.warning(f"ICT {symbol} step4: FVG check failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Step 5: Price at FVG
# ---------------------------------------------------------------------------

def _check_step5_price_at_fvg(
    df: pd.DataFrame,
    fvg_zone: dict,
    direction: str,
    symbol: str,
) -> Optional[dict]:
    """Check if the current price is at or approaching the FVG zone.

    For a bullish setup: price should be at or pulling back INTO the FVG
        (current price near or inside the FVG zone from above or within)
    For a bearish setup: price should be at or rallying INTO the FVG
        (current price near or inside the FVG zone from below or within)

    We use a proximity buffer: if price is within FVG_PROXIMITY_BUFFER * FVG_height
    of the zone edges, it counts as "at the FVG".

    Returns dict with 'current_price', 'in_zone', 'detail' or None.
    """
    try:
        current_price = float(df['close'].iloc[-1])
        fvg_top = fvg_zone['top']
        fvg_bottom = fvg_zone['bottom']
        fvg_height = fvg_top - fvg_bottom

        if fvg_height <= 0:
            logger.debug(f"ICT {symbol} step5: invalid FVG height {fvg_height}")
            return None

        buffer = fvg_height * FVG_PROXIMITY_BUFFER

        # Expanded zone with buffer
        zone_top = fvg_top + buffer
        zone_bottom = fvg_bottom - buffer

        # Check if price is in the expanded zone
        in_zone = zone_bottom <= current_price <= zone_top

        if not in_zone:
            # For bullish setups, price approaching from above (pulling back) is also OK
            # if it is within 2x buffer above the zone.  This allows entries where
            # price hasn't quite reached the FVG yet but is heading toward it.
            if direction == 'bullish':
                # Price should be above the FVG bottom (not already through it)
                # and not too far above the top
                approaching = (
                    current_price > fvg_top
                    and current_price <= fvg_top + buffer * 2
                )
            else:
                # For bearish, price should be below the FVG top
                # and not too far below the bottom
                approaching = (
                    current_price < fvg_bottom
                    and current_price >= fvg_bottom - buffer * 2
                )

            if not approaching:
                distance = min(
                    abs(current_price - fvg_top),
                    abs(current_price - fvg_bottom),
                )
                logger.debug(
                    f"ICT {symbol} step5: price {current_price:.5f} not at FVG "
                    f"({fvg_bottom:.5f}-{fvg_top:.5f}), distance={distance:.5f}"
                )
                return None

        detail = (
            f"price={current_price:.5f} "
            f"{'IN' if in_zone else 'approaching'} FVG zone "
            f"({fvg_bottom:.5f}-{fvg_top:.5f})"
        )
        logger.debug(f"ICT {symbol} step5 PASS: {detail}")

        return {
            'current_price': current_price,
            'in_zone': in_zone,
            'detail': detail,
        }

    except Exception as e:
        logger.warning(f"ICT {symbol} step5: price-at-FVG check failed: {e}")
        return None


# ---------------------------------------------------------------------------
# SL / TP computation
# ---------------------------------------------------------------------------

def _compute_sl_tp(
    symbol: str,
    direction: str,
    entry_price: float,
    sweep_extreme: float,
    df_m15: pd.DataFrame,
    htf_bias,
) -> Optional[dict]:
    """Compute stop loss and take profit for the ICT setup.

    SL: Beyond the sweep wick extreme + ATR buffer.
    TP: Nearest opposing HTF S/R level, falling back to ATR-based if no S/R.

    Returns dict with 'sl', 'tp', 'rr_ratio' or None if R:R < MIN_RR_RATIO.
    """
    try:
        # Calculate ATR for buffer sizing
        close = df_m15['close'].values.astype(float)
        high = df_m15['high'].values.astype(float)
        low = df_m15['low'].values.astype(float)

        # Simple ATR (14-period)
        tr_values = []
        for i in range(1, len(close)):
            tr = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
            tr_values.append(tr)

        if len(tr_values) < 14:
            logger.debug(f"ICT {symbol} SL/TP: insufficient data for ATR")
            return None

        atr = float(np.mean(tr_values[-14:]))

        if atr <= 0:
            logger.debug(f"ICT {symbol} SL/TP: ATR is zero")
            return None

        sl_buffer = atr * SL_BUFFER_ATR_FRACTION

        # --- Stop Loss ---
        if direction == 'bullish':
            # SL below the sweep low + buffer
            sl = sweep_extreme - sl_buffer
            sl_distance = entry_price - sl
        else:
            # SL above the sweep high + buffer
            sl = sweep_extreme + sl_buffer
            sl_distance = sl - entry_price

        if sl_distance <= 0:
            logger.debug(
                f"ICT {symbol} SL/TP: invalid SL distance {sl_distance:.5f} "
                f"(entry={entry_price:.5f}, SL={sl:.5f})"
            )
            return None

        # --- Take Profit ---
        # Try to use HTF S/R levels for TP
        tp = None
        tp_source = 'none'

        try:
            from app.quant.indicators.support_resistance import find_sr_levels

            sr = find_sr_levels(df_m15, atr, lookback=5, max_levels=10)

            if direction == 'bullish':
                # TP at nearest resistance above entry
                r_levels = [
                    r for r in sr.get('resistance', [])
                    if r['price'] > entry_price + atr * 0.5
                ]
                if r_levels:
                    r_levels.sort(key=lambda x: x['price'])
                    # Pick the first resistance that gives us min R:R
                    for r in r_levels:
                        candidate_tp = r['price']
                        candidate_rr = (candidate_tp - entry_price) / sl_distance
                        if candidate_rr >= MIN_RR_RATIO:
                            tp = candidate_tp
                            tp_source = f"S/R resistance {tp:.5f}"
                            break
            else:
                # TP at nearest support below entry
                s_levels = [
                    s for s in sr.get('support', [])
                    if s['price'] < entry_price - atr * 0.5
                ]
                if s_levels:
                    s_levels.sort(key=lambda x: x['price'], reverse=True)
                    for s in s_levels:
                        candidate_tp = s['price']
                        candidate_rr = (entry_price - candidate_tp) / sl_distance
                        if candidate_rr >= MIN_RR_RATIO:
                            tp = candidate_tp
                            tp_source = f"S/R support {tp:.5f}"
                            break
        except Exception as e:
            logger.debug(f"ICT {symbol} SL/TP: S/R lookup failed: {e}")

        # Also try using HTF bias levels (previous day high/low) as TP targets
        if tp is None and htf_bias is not None:
            if direction == 'bullish' and htf_bias.previous_day_high > 0:
                pdh = htf_bias.previous_day_high
                if pdh > entry_price + atr * 0.5:
                    candidate_rr = (pdh - entry_price) / sl_distance
                    if candidate_rr >= MIN_RR_RATIO:
                        tp = pdh
                        tp_source = f"HTF previous high {tp:.5f}"
            elif direction == 'bearish' and htf_bias.previous_day_low > 0:
                pdl = htf_bias.previous_day_low
                if pdl < entry_price - atr * 0.5:
                    candidate_rr = (entry_price - pdl) / sl_distance
                    if candidate_rr >= MIN_RR_RATIO:
                        tp = pdl
                        tp_source = f"HTF previous low {tp:.5f}"

        # Fallback: ATR-based TP with min R:R
        if tp is None:
            tp_distance = sl_distance * MIN_RR_RATIO
            if direction == 'bullish':
                tp = entry_price + tp_distance
            else:
                tp = entry_price - tp_distance
            tp_source = f"ATR fallback ({MIN_RR_RATIO}R)"

        # --- Calculate final R:R ---
        if direction == 'bullish':
            rr_ratio = (tp - entry_price) / sl_distance
        else:
            rr_ratio = (entry_price - tp) / sl_distance

        if rr_ratio < MIN_RR_RATIO:
            logger.debug(
                f"ICT {symbol} SL/TP: R:R {rr_ratio:.2f} < {MIN_RR_RATIO} "
                f"-- skipping setup"
            )
            return None

        logger.debug(
            f"ICT {symbol} SL/TP: entry={entry_price:.5f} "
            f"SL={sl:.5f} TP={tp:.5f} R:R={rr_ratio:.2f} "
            f"TP source={tp_source}"
        )

        return {
            'sl': sl,
            'tp': tp,
            'rr_ratio': round(rr_ratio, 2),
            'tp_source': tp_source,
            'atr': atr,
        }

    except Exception as e:
        logger.warning(f"ICT {symbol} SL/TP: computation failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Confluence scoring for ICT setups
# ---------------------------------------------------------------------------

def _compute_confluence(
    symbol: str,
    direction: str,
    htf_bias_detail: dict,
    fvg_present: bool = True,
) -> int:
    """Compute confluence score for a validated ICT 5-step setup.

    A full 5-step ICT setup inherently has:
    - HTF bias aligned (2 pts)
    - Liquidity sweep (2 pts)
    - FVG present (1 pt)
    - Displacement (1 pt, implied by the MSS after sweep)
    = 6 points minimum from the ICT chain itself.

    We then check additional factors (kill zone, CVD, regime, OB) to push
    toward 9+.
    """
    try:
        from app.quant.algorithms.confluence_scorer import score_confluence

        # Map direction for the scorer
        scorer_direction = 'long' if direction == 'bullish' else 'short'
        htf_bias_str = htf_bias_detail.get('direction', None)

        confluence = score_confluence(
            symbol=symbol,
            direction=scorer_direction,
            htf_bias=htf_bias_str,
            liquidity_sweep=True,       # Step 2 confirmed
            fvg_present=fvg_present,    # Step 4 confirmed
            displacement=True,          # Implied by MSS after sweep
            # These are checked dynamically by the scorer:
            cvd_divergence=None,
            kill_zone_active=None,
            order_block_at_entry=None,
            regime_favorable=None,
        )

        return confluence.total_score

    except Exception as e:
        logger.debug(f"ICT {symbol}: confluence scoring failed: {e}")
        # Minimum score for a full 5-step setup: HTF(2) + sweep(2) + FVG(1) + displacement(1)
        return 6


# ---------------------------------------------------------------------------
# Main evaluation function
# ---------------------------------------------------------------------------

def evaluate_ict_setup(symbol: str) -> Optional[ICTSetup]:
    """Evaluate whether a full ICT 5-step setup exists for a symbol.

    Fetches its own data (H4 for HTF bias via mtf_analyzer, M15 for structure).
    Returns an ICTSetup if all 5 steps confirmed in temporal order, None otherwise.

    The 5 steps must be in temporal order on M15:
        1. HTF bias is bullish/bearish (from H4)
        2. Recent sweep in the bias direction (sell-side sweep for bullish)
        3. MSS after the sweep (CHoCH/BOS confirming reversal)
        4. FVG forms after the MSS
        5. Current price is at or approaching the FVG zone

    This function is designed to be called frequently (e.g., every 60s by Celery)
    and returns quickly when early steps fail.
    """
    logger.debug(f"ICT {symbol}: starting 5-step evaluation")

    # -----------------------------------------------------------------------
    # Step 1: HTF Bias
    # -----------------------------------------------------------------------
    step1 = _check_step1_htf_bias(symbol)
    if step1 is None:
        return None

    htf_direction = step1['direction']  # 'bullish' or 'bearish'
    htf_bias = step1['bias']

    # -----------------------------------------------------------------------
    # Fetch M15 data for steps 2-5
    # -----------------------------------------------------------------------
    try:
        from app.utils.api.data import fetch_data_pos
        from app.utils.constants import MT5Timeframe

        df_m15 = fetch_data_pos(symbol, MT5Timeframe.M15, 100)
        if df_m15 is None or len(df_m15) < 30:
            logger.debug(
                f"ICT {symbol}: insufficient M15 data "
                f"({len(df_m15) if df_m15 is not None else 0} bars)"
            )
            return None
    except Exception as e:
        logger.warning(f"ICT {symbol}: M15 data fetch failed: {e}")
        return None

    # -----------------------------------------------------------------------
    # Step 2: Liquidity Sweep
    # -----------------------------------------------------------------------
    step2 = _check_step2_liquidity_sweep(df_m15, htf_direction, symbol)
    if step2 is None:
        return None

    sweep_bar_idx = step2['bar_idx']
    sweep_level = step2['level']
    sweep_extreme = step2['extreme']

    # -----------------------------------------------------------------------
    # Step 3: Market Structure Shift
    # -----------------------------------------------------------------------
    step3 = _check_step3_market_structure_shift(
        df_m15, sweep_bar_idx, htf_direction, symbol,
    )
    if step3 is None:
        return None

    mss_bar_idx = step3['bar_idx']

    # -----------------------------------------------------------------------
    # Step 4: Fair Value Gap
    # -----------------------------------------------------------------------
    step4 = _check_step4_fvg(df_m15, mss_bar_idx, htf_direction, symbol)
    if step4 is None:
        return None

    fvg_zone = {
        'top': step4['top'],
        'bottom': step4['bottom'],
    }
    fvg_midpoint = step4['midpoint']
    fvg_bar_idx = step4['bar_idx']

    # -----------------------------------------------------------------------
    # Step 5: Price at FVG
    # -----------------------------------------------------------------------
    step5 = _check_step5_price_at_fvg(df_m15, fvg_zone, htf_direction, symbol)
    if step5 is None:
        return None

    # -----------------------------------------------------------------------
    # All 5 steps confirmed -- compute SL/TP and build setup
    # -----------------------------------------------------------------------
    entry_price = fvg_midpoint
    trade_direction = 'BUY' if htf_direction == 'bullish' else 'SELL'

    sl_tp = _compute_sl_tp(
        symbol, htf_direction, entry_price, sweep_extreme, df_m15, htf_bias,
    )
    if sl_tp is None:
        return None

    # Compute confluence score
    confluence_score = _compute_confluence(symbol, htf_direction)

    # Assemble step details for logging and analysis
    step_details = {
        'step1_htf_bias': step1['detail'],
        'step2_sweep': step2['detail'],
        'step3_mss': step3['detail'],
        'step4_fvg': step4['detail'],
        'step5_price': step5['detail'],
        'sl_tp': {
            'sl': sl_tp['sl'],
            'tp': sl_tp['tp'],
            'rr_ratio': sl_tp['rr_ratio'],
            'tp_source': sl_tp['tp_source'],
            'atr': sl_tp['atr'],
        },
    }

    setup = ICTSetup(
        symbol=symbol,
        direction=trade_direction,
        entry_price=entry_price,
        stop_loss=sl_tp['sl'],
        take_profit=sl_tp['tp'],
        rr_ratio=sl_tp['rr_ratio'],
        steps_confirmed=5,
        step_details=step_details,
        confluence_score=confluence_score,
        fvg_zone=(fvg_zone['top'], fvg_zone['bottom']),
        sweep_level=sweep_level,
        mss_bar_idx=mss_bar_idx,
        fvg_bar_idx=fvg_bar_idx,
    )

    logger.info(setup.to_log_string())
    logger.info(
        f"ICT {symbol}: 5-STEP SETUP CONFIRMED | "
        f"1.HTF={htf_direction} 2.Sweep@{sweep_level:.5f} "
        f"3.{step3['type']}@bar{mss_bar_idx} "
        f"4.FVG({fvg_zone['top']:.5f}-{fvg_zone['bottom']:.5f}) "
        f"5.Price@FVG | {trade_direction} entry={entry_price:.5f} "
        f"SL={sl_tp['sl']:.5f} TP={sl_tp['tp']:.5f} R:R={sl_tp['rr_ratio']}"
    )

    return setup


# ---------------------------------------------------------------------------
# Multi-symbol scanner
# ---------------------------------------------------------------------------

def scan_ict_setups(symbols: List[str]) -> List[ICTSetup]:
    """Scan multiple symbols for ICT 5-step setups.

    Called by Celery tasks to find institutional entry opportunities.
    Each symbol is evaluated independently; failures on one symbol
    do not affect others.

    Returns a list of confirmed ICTSetup objects (may be empty).
    """
    setups = []

    for symbol in symbols:
        try:
            setup = evaluate_ict_setup(symbol)
            if setup is not None:
                setups.append(setup)
        except Exception as e:
            logger.error(
                f"ICT scan: unhandled error evaluating {symbol}: {e}",
                exc_info=True,
            )

    if setups:
        logger.info(
            f"ICT SCAN: {len(setups)} setup(s) found across {len(symbols)} symbols: "
            f"{', '.join(s.symbol + ' ' + s.direction for s in setups)}"
        )
    else:
        logger.debug(
            f"ICT SCAN: no setups found across {len(symbols)} symbols"
        )

    return setups
