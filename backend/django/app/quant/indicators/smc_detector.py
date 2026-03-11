"""Smart Money Concepts detector using the ``smartmoneyconcepts`` package.

Wraps the third-party library (joshyattridge/smart-money-concepts) and
exposes clean functions that slot into our trading pipeline.  Every public
function accepts a DataFrame with our standard **uppercase** OHLCV columns
(``Open``, ``High``, ``Low``, ``Close``, ``Volume`` / ``tick_volume``) **or**
lowercase columns — the mapping is handled transparently.

Design principles:
- **Fail-open** — if the package is missing or any detector errors, we log
  a warning and return empty / neutral results so the pipeline never breaks.
- **Stateless** — no side-effects on the input DataFrame.
- **Registry-compatible** — the ``_registry_*`` wrappers at the bottom return
  a single pd.Series suitable for ``INDICATOR_REGISTRY``.
"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger('smc_detector')

# ---------------------------------------------------------------------------
# Lazy import of the third-party package
# ---------------------------------------------------------------------------
try:
    from smartmoneyconcepts import smc as _smc
    _SMC_AVAILABLE = True
except ImportError:
    _smc = None  # type: ignore[assignment]
    _SMC_AVAILABLE = False
    logger.warning(
        "smartmoneyconcepts package not installed — SMC detector functions "
        "will return empty results.  Install with: pip install smartmoneyconcepts"
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with lowercase OHLCV columns expected by the library.

    Handles our MT5 uppercase convention (``Open``, …) as well as the
    ``tick_volume`` alias for ``volume``.
    """
    out = df.copy()

    col_map = {}
    for src, dst in [
        ('Open', 'open'), ('High', 'high'), ('Low', 'low'),
        ('Close', 'close'), ('Volume', 'volume'),
        ('tick_volume', 'volume'),
    ]:
        if src in out.columns and dst not in out.columns:
            col_map[src] = dst

    if col_map:
        out = out.rename(columns=col_map)

    # Ensure we have a volume column even if none was present
    if 'volume' not in out.columns:
        out['volume'] = 0

    return out


def _empty_df(index: pd.Index, columns: List[str]) -> pd.DataFrame:
    """Return a DataFrame of NaNs matching *index* and *columns*."""
    return pd.DataFrame(np.nan, index=index, columns=columns)


# ---------------------------------------------------------------------------
# 1. Fair Value Gaps (FVG)
# ---------------------------------------------------------------------------

def detect_fair_value_gaps(
    df: pd.DataFrame,
    swing_lookback: int = 10,
    join_consecutive: bool = False,
) -> pd.DataFrame:
    """Detect bullish and bearish Fair Value Gaps using smartmoneyconcepts.

    Parameters
    ----------
    df : DataFrame
        OHLCV data (uppercase or lowercase columns).
    swing_lookback : int
        Not used directly by the FVG detector — kept for API symmetry with
        the other SMC functions.
    join_consecutive : bool
        If ``True``, consecutive same-direction FVGs are merged into one.

    Returns
    -------
    DataFrame with columns ``FVG``, ``Top``, ``Bottom``, ``MitigatedIndex``.
        ``FVG``: 1 for bullish, -1 for bearish, ``NaN`` for none.
    """
    cols = ['FVG', 'Top', 'Bottom', 'MitigatedIndex']
    if not _SMC_AVAILABLE:
        return _empty_df(df.index, cols)

    try:
        ohlc = _normalise_columns(df)
        result = _smc.fvg(ohlc, join_consecutive=join_consecutive)

        # The library returns a DataFrame — align index with our input
        if isinstance(result, pd.DataFrame):
            result.index = df.index
            # Ensure expected columns exist
            for c in cols:
                if c not in result.columns:
                    result[c] = np.nan
            return result[cols]

        return _empty_df(df.index, cols)

    except Exception:
        logger.exception("FVG detection failed")
        return _empty_df(df.index, cols)


# ---------------------------------------------------------------------------
# 2. Order Blocks (OB)
# ---------------------------------------------------------------------------

def detect_order_blocks(
    df: pd.DataFrame,
    swing_lookback: int = 10,
    close_mitigation: bool = False,
) -> pd.DataFrame:
    """Detect bullish and bearish Order Blocks.

    Parameters
    ----------
    df : DataFrame
        OHLCV data.
    swing_lookback : int
        Window for swing-point detection fed into the OB detector.
    close_mitigation : bool
        If ``True``, mitigation requires the close to cross the OB zone
        (more conservative).

    Returns
    -------
    DataFrame with columns ``OB``, ``Top``, ``Bottom``, ``OBVolume``,
    ``MitigatedIndex``, ``Percentage``.
        ``OB``: 1 for bullish, -1 for bearish, ``NaN`` for none.
    """
    cols = ['OB', 'Top', 'Bottom', 'OBVolume', 'MitigatedIndex', 'Percentage']
    if not _SMC_AVAILABLE:
        return _empty_df(df.index, cols)

    try:
        ohlc = _normalise_columns(df)
        swing_hl = _smc.swing_highs_lows(ohlc, swing_length=swing_lookback)
        result = _smc.ob(ohlc, swing_hl, close_mitigation=close_mitigation)

        if isinstance(result, pd.DataFrame):
            result.index = df.index
            for c in cols:
                if c not in result.columns:
                    result[c] = np.nan
            return result[cols]

        return _empty_df(df.index, cols)

    except Exception:
        logger.exception("Order Block detection failed")
        return _empty_df(df.index, cols)


# ---------------------------------------------------------------------------
# 3. Market Structure — BOS / CHoCH
# ---------------------------------------------------------------------------

def detect_market_structure(
    df: pd.DataFrame,
    swing_lookback: int = 10,
    close_break: bool = True,
) -> pd.DataFrame:
    """Detect Break of Structure (BOS) and Change of Character (CHoCH).

    Parameters
    ----------
    df : DataFrame
        OHLCV data.
    swing_lookback : int
        Window for swing-point detection.
    close_break : bool
        If ``True``, structure is broken only on a candle *close* beyond
        the level (more reliable).

    Returns
    -------
    DataFrame with columns ``BOS``, ``CHOCH``, ``Level``, ``BrokenIndex``.
        ``BOS``:  1 for bullish, -1 for bearish (trend continuation).
        ``CHOCH``: 1 for bullish, -1 for bearish (trend reversal).
    """
    cols = ['BOS', 'CHOCH', 'Level', 'BrokenIndex']
    if not _SMC_AVAILABLE:
        return _empty_df(df.index, cols)

    try:
        ohlc = _normalise_columns(df)
        swing_hl = _smc.swing_highs_lows(ohlc, swing_length=swing_lookback)
        result = _smc.bos_choch(ohlc, swing_hl, close_break=close_break)

        if isinstance(result, pd.DataFrame):
            result.index = df.index
            for c in cols:
                if c not in result.columns:
                    result[c] = np.nan
            return result[cols]

        return _empty_df(df.index, cols)

    except Exception:
        logger.exception("Market structure detection failed")
        return _empty_df(df.index, cols)


# ---------------------------------------------------------------------------
# 4. Liquidity Sweeps
# ---------------------------------------------------------------------------

def detect_liquidity_sweeps(
    df: pd.DataFrame,
    swing_lookback: int = 10,
    range_percent: float = 0.01,
) -> pd.DataFrame:
    """Detect liquidity sweeps at swing highs / lows.

    Parameters
    ----------
    df : DataFrame
        OHLCV data.
    swing_lookback : int
        Window for swing-point detection.
    range_percent : float
        How close price levels must cluster to be considered the same
        liquidity pool (fraction of price).

    Returns
    -------
    DataFrame with columns ``Liquidity``, ``Level``, ``End``, ``Swept``.
        ``Liquidity``: 1 for buy-side, -1 for sell-side, ``NaN`` for none.
    """
    cols = ['Liquidity', 'Level', 'End', 'Swept']
    if not _SMC_AVAILABLE:
        return _empty_df(df.index, cols)

    try:
        ohlc = _normalise_columns(df)
        swing_hl = _smc.swing_highs_lows(ohlc, swing_length=swing_lookback)
        result = _smc.liquidity(ohlc, swing_hl, range_percent=range_percent)

        if isinstance(result, pd.DataFrame):
            result.index = df.index
            for c in cols:
                if c not in result.columns:
                    result[c] = np.nan
            return result[cols]

        return _empty_df(df.index, cols)

    except Exception:
        logger.exception("Liquidity sweep detection failed")
        return _empty_df(df.index, cols)


# ---------------------------------------------------------------------------
# 5. Swing Points
# ---------------------------------------------------------------------------

def detect_swing_points(
    df: pd.DataFrame,
    swing_lookback: int = 10,
) -> pd.DataFrame:
    """Detect swing highs and swing lows.

    Parameters
    ----------
    df : DataFrame
        OHLCV data.
    swing_lookback : int
        Window for swing-point detection.

    Returns
    -------
    DataFrame with columns ``HighLow``, ``Level``.
        ``HighLow``: 1 for swing high, -1 for swing low, ``NaN`` for none.
    """
    cols = ['HighLow', 'Level']
    if not _SMC_AVAILABLE:
        return _empty_df(df.index, cols)

    try:
        ohlc = _normalise_columns(df)
        result = _smc.swing_highs_lows(ohlc, swing_length=swing_lookback)

        if isinstance(result, pd.DataFrame):
            result.index = df.index
            for c in cols:
                if c not in result.columns:
                    result[c] = np.nan
            return result[cols]

        return _empty_df(df.index, cols)

    except Exception:
        logger.exception("Swing point detection failed")
        return _empty_df(df.index, cols)


# ---------------------------------------------------------------------------
# 6. Confluence Analysis
# ---------------------------------------------------------------------------

def get_smc_confluence(
    df: pd.DataFrame,
    swing_lookback: int = 10,
) -> Dict[str, Any]:
    """Run all SMC detectors and return a combined analysis.

    This is the high-level function that strategies and the AI Brain can
    call to get a quick read on the Smart Money landscape.

    Parameters
    ----------
    df : DataFrame
        OHLCV data.
    swing_lookback : int
        Shared swing-point window for all sub-detectors.

    Returns
    -------
    dict
        htf_bias : str
            ``'bullish'``, ``'bearish'``, or ``'neutral'`` derived from the
            most recent BOS / CHoCH events.
        active_fvgs : list[dict]
            Unfilled Fair Value Gap zones with ``direction``, ``top``,
            ``bottom``, ``bar_index``.
        active_obs : list[dict]
            Untested Order Blocks with ``direction``, ``top``, ``bottom``,
            ``volume``, ``bar_index``.
        recent_sweeps : list[dict]
            Recent liquidity sweeps with ``direction``, ``level``,
            ``bar_index``.
        structure_shifts : list[dict]
            Recent BOS / CHoCH events with ``type``, ``direction``,
            ``level``, ``bar_index``.
        confluence_count : int
            Number of SMC factors aligning with the current bias.
    """
    empty: Dict[str, Any] = {
        'htf_bias': 'neutral',
        'active_fvgs': [],
        'active_obs': [],
        'recent_sweeps': [],
        'structure_shifts': [],
        'confluence_count': 0,
    }

    if not _SMC_AVAILABLE or len(df) < swing_lookback * 3:
        return empty

    try:
        # --- Run individual detectors ---
        fvg_df = detect_fair_value_gaps(df, swing_lookback=swing_lookback)
        ob_df = detect_order_blocks(df, swing_lookback=swing_lookback)
        ms_df = detect_market_structure(df, swing_lookback=swing_lookback)
        liq_df = detect_liquidity_sweeps(df, swing_lookback=swing_lookback)

        # --- Determine higher-timeframe bias from structure ---
        structure_shifts: List[Dict[str, Any]] = []
        for i in range(len(ms_df)):
            bos_val = ms_df['BOS'].iloc[i]
            choch_val = ms_df['CHOCH'].iloc[i]
            level = ms_df['Level'].iloc[i]

            if not pd.isna(bos_val) and bos_val != 0:
                direction = 'bullish' if bos_val == 1 else 'bearish'
                structure_shifts.append({
                    'type': 'BOS',
                    'direction': direction,
                    'level': float(level) if not pd.isna(level) else None,
                    'bar_index': i,
                })
            if not pd.isna(choch_val) and choch_val != 0:
                direction = 'bullish' if choch_val == 1 else 'bearish'
                structure_shifts.append({
                    'type': 'CHOCH',
                    'direction': direction,
                    'level': float(level) if not pd.isna(level) else None,
                    'bar_index': i,
                })

        # Bias = direction of the most recent structure event (CHoCH weighted
        # higher — if the last event is a CHoCH it overrides a preceding BOS)
        htf_bias = 'neutral'
        if structure_shifts:
            last = structure_shifts[-1]
            htf_bias = last['direction']

        # --- Collect active (unmitigated) FVGs ---
        active_fvgs: List[Dict[str, Any]] = []
        for i in range(len(fvg_df)):
            fvg_val = fvg_df['FVG'].iloc[i]
            mitigated = fvg_df['MitigatedIndex'].iloc[i]
            if not pd.isna(fvg_val) and fvg_val != 0:
                # Unmitigated = MitigatedIndex is NaN
                if pd.isna(mitigated):
                    direction = 'bullish' if fvg_val == 1 else 'bearish'
                    active_fvgs.append({
                        'direction': direction,
                        'top': float(fvg_df['Top'].iloc[i]),
                        'bottom': float(fvg_df['Bottom'].iloc[i]),
                        'bar_index': i,
                    })

        # --- Collect active (unmitigated) Order Blocks ---
        active_obs: List[Dict[str, Any]] = []
        for i in range(len(ob_df)):
            ob_val = ob_df['OB'].iloc[i]
            mitigated = ob_df['MitigatedIndex'].iloc[i]
            if not pd.isna(ob_val) and ob_val != 0:
                if pd.isna(mitigated):
                    direction = 'bullish' if ob_val == 1 else 'bearish'
                    vol = ob_df['OBVolume'].iloc[i]
                    active_obs.append({
                        'direction': direction,
                        'top': float(ob_df['Top'].iloc[i]),
                        'bottom': float(ob_df['Bottom'].iloc[i]),
                        'volume': float(vol) if not pd.isna(vol) else 0.0,
                        'bar_index': i,
                    })

        # --- Collect recent liquidity sweeps ---
        recent_sweeps: List[Dict[str, Any]] = []
        for i in range(len(liq_df)):
            liq_val = liq_df['Liquidity'].iloc[i]
            swept = liq_df['Swept'].iloc[i]
            if not pd.isna(liq_val) and liq_val != 0:
                # Only include actually-swept pools
                if not pd.isna(swept) and swept == 1:
                    direction = 'bullish' if liq_val == -1 else 'bearish'
                    # Sell-side sweep (-1) is bullish reversal signal;
                    # buy-side sweep (1) is bearish reversal signal.
                    level = liq_df['Level'].iloc[i]
                    recent_sweeps.append({
                        'direction': direction,
                        'level': float(level) if not pd.isna(level) else None,
                        'bar_index': i,
                    })

        # --- Compute confluence ---
        # Count how many factors align with the HTF bias
        confluence_count = 0
        if htf_bias != 'neutral':
            # Structure shifts in the bias direction
            aligned_structure = sum(
                1 for s in structure_shifts
                if s['direction'] == htf_bias
                and s['bar_index'] >= len(df) - swing_lookback * 3
            )
            confluence_count += min(aligned_structure, 2)  # Cap at 2

            # Active FVGs in the bias direction
            aligned_fvgs = sum(
                1 for f in active_fvgs if f['direction'] == htf_bias
            )
            if aligned_fvgs > 0:
                confluence_count += 1

            # Active OBs in the bias direction
            aligned_obs = sum(
                1 for o in active_obs if o['direction'] == htf_bias
            )
            if aligned_obs > 0:
                confluence_count += 1

            # Sweeps in the bias direction (reversal confirmation)
            aligned_sweeps = sum(
                1 for sw in recent_sweeps
                if sw['direction'] == htf_bias
                and sw['bar_index'] >= len(df) - swing_lookback * 3
            )
            if aligned_sweeps > 0:
                confluence_count += 1

        return {
            'htf_bias': htf_bias,
            'active_fvgs': active_fvgs,
            'active_obs': active_obs,
            'recent_sweeps': recent_sweeps,
            'structure_shifts': structure_shifts,
            'confluence_count': confluence_count,
        }

    except Exception:
        logger.exception("SMC confluence analysis failed")
        return empty


# ---------------------------------------------------------------------------
# INDICATOR_REGISTRY wrappers
# ---------------------------------------------------------------------------
# These return a single pd.Series (like every other registry indicator) so
# they can be plugged straight into the backtester and strategy evolver.

def _registry_fvg(df: pd.DataFrame, params: Optional[Dict] = None) -> pd.Series:
    """Registry-compatible FVG detector.

    Returns a Series of signal strings:
        ``'bullish_fvg_lib'``, ``'bearish_fvg_lib'``, or ``0``.
    The ``_lib`` suffix distinguishes these from the hand-rolled FVG signals
    in ``smc.py``.
    """
    params = params or {}
    swing_lookback = params.get('swing_lookback', 10)
    fvg_df = detect_fair_value_gaps(df, swing_lookback=swing_lookback)
    result = pd.Series(0, index=df.index, dtype=object)

    for i in range(len(fvg_df)):
        val = fvg_df['FVG'].iloc[i]
        mitigated = fvg_df['MitigatedIndex'].iloc[i]
        if not pd.isna(val) and val != 0 and pd.isna(mitigated):
            result.iloc[i] = 'bullish_fvg_lib' if val == 1 else 'bearish_fvg_lib'

    return result


def _registry_ob(df: pd.DataFrame, params: Optional[Dict] = None) -> pd.Series:
    """Registry-compatible Order Block detector.

    Returns ``'bullish_ob_lib'``, ``'bearish_ob_lib'``, or ``0``.
    """
    params = params or {}
    swing_lookback = params.get('swing_lookback', 10)
    ob_df = detect_order_blocks(df, swing_lookback=swing_lookback)
    result = pd.Series(0, index=df.index, dtype=object)

    for i in range(len(ob_df)):
        val = ob_df['OB'].iloc[i]
        mitigated = ob_df['MitigatedIndex'].iloc[i]
        if not pd.isna(val) and val != 0 and pd.isna(mitigated):
            result.iloc[i] = 'bullish_ob_lib' if val == 1 else 'bearish_ob_lib'

    return result


def _registry_structure(df: pd.DataFrame, params: Optional[Dict] = None) -> pd.Series:
    """Registry-compatible BOS / CHoCH detector.

    Returns ``'bullish_bos_lib'``, ``'bearish_bos_lib'``,
    ``'bullish_choch_lib'``, ``'bearish_choch_lib'``, or ``0``.
    """
    params = params or {}
    swing_lookback = params.get('swing_lookback', 10)
    ms_df = detect_market_structure(df, swing_lookback=swing_lookback)
    result = pd.Series(0, index=df.index, dtype=object)

    for i in range(len(ms_df)):
        bos = ms_df['BOS'].iloc[i]
        choch = ms_df['CHOCH'].iloc[i]

        # CHoCH takes priority (stronger signal)
        if not pd.isna(choch) and choch != 0:
            result.iloc[i] = 'bullish_choch_lib' if choch == 1 else 'bearish_choch_lib'
        elif not pd.isna(bos) and bos != 0:
            result.iloc[i] = 'bullish_bos_lib' if bos == 1 else 'bearish_bos_lib'

    return result


def _registry_liquidity(df: pd.DataFrame, params: Optional[Dict] = None) -> pd.Series:
    """Registry-compatible liquidity sweep detector.

    Returns ``'bullish_sweep_lib'``, ``'bearish_sweep_lib'``, or ``0``.
    """
    params = params or {}
    swing_lookback = params.get('swing_lookback', 10)
    liq_df = detect_liquidity_sweeps(df, swing_lookback=swing_lookback)
    result = pd.Series(0, index=df.index, dtype=object)

    for i in range(len(liq_df)):
        val = liq_df['Liquidity'].iloc[i]
        swept = liq_df['Swept'].iloc[i]
        if not pd.isna(val) and val != 0 and not pd.isna(swept) and swept == 1:
            # Sell-side liquidity swept (-1) => bullish reversal
            # Buy-side liquidity swept (1) => bearish reversal
            result.iloc[i] = 'bullish_sweep_lib' if val == -1 else 'bearish_sweep_lib'

    return result


def _registry_confluence(df: pd.DataFrame, params: Optional[Dict] = None) -> pd.Series:
    """Registry-compatible SMC confluence score.

    Returns ``'bullish_smc_confluence'``, ``'bearish_smc_confluence'``,
    or ``0`` based on the full SMC analysis.
    """
    params = params or {}
    swing_lookback = params.get('swing_lookback', 10)
    min_confluence = params.get('min_confluence', 2)

    analysis = get_smc_confluence(df, swing_lookback=swing_lookback)

    # Build a single bar-level signal from the analysis.
    # The confluence analysis is a snapshot of the *entire* DataFrame, so we
    # report the signal on the last bar only (that is the actionable bar for
    # live trading).
    result = pd.Series(0, index=df.index, dtype=object)

    if analysis['confluence_count'] >= min_confluence:
        bias = analysis['htf_bias']
        if bias == 'bullish':
            result.iloc[-1] = 'bullish_smc_confluence'
        elif bias == 'bearish':
            result.iloc[-1] = 'bearish_smc_confluence'

    return result
