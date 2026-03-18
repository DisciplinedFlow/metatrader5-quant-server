"""
Trade Simulator — multi-R:R outcome simulation for backtest-seeded reference nodes.

Given a Setup (entry price, direction, ATR) and subsequent OHLCV bars, simulate
what would have happened if we entered at the setup trigger and held to SL/TP.

Three R:R variants are tested per setup:
  - 1:1.5  (TP = 1.5 × SL distance)
  - 1:2.0  (golden standard — must always pass this test)
  - 1:3.0  (extended runner)

Trailing stop variant: tracks peak MFE, exits when price gives back 50% of profit
(approximates the 6-phase position_manager trailing behavior without needing tick data).

Output: SimResult per variant. backtest_seeder.py picks the 1:2 result as the canonical
reference node, attaches 1:1.5 and 1:3 as metadata for the brain to query.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

try:
    from app.quant.knowledge.pattern_detector import Setup, _parse_bar_time
except ImportError:
    from quant.knowledge.pattern_detector import Setup, _parse_bar_time

# SL ATR multiplier — mirrors live config
SL_ATR_MULTIPLIER = 1.8   # matches cvd/config.py
ENERGY_SL_ATR = 2.0        # USOUSD / UKOUSDft / NG-C


_ENERGY_SYMBOLS = frozenset(['USOUSD', 'UKOUSDft', 'NG-C', 'XNGUSD', 'NATGAS'])


@dataclass
class SimResult:
    """Outcome of simulating one Setup with one R:R ratio."""
    setup_symbol: str
    direction: str
    entry_price: float
    sl_price: float
    tp_price: float
    rr_ratio: float                         # 1.5 / 2.0 / 3.0

    outcome: str                            # 'WIN' | 'LOSS' | 'TRAILING_EXIT' | 'EXPIRED'
    exit_price: float
    exit_bar_index: int
    exit_bar_time: Optional[datetime]

    pnl_r: float                            # P&L in R multiples (-1.0 = full loss, +2.0 = full TP hit)
    bars_held: int
    max_favorable_excursion: float          # MFE in R
    max_adverse_excursion: float            # MAE in R

    # Trailing stop exit (filled if trailing variant)
    trailing_exit: bool = False
    trailing_exit_r: float = 0.0

    # Context passed-through from Setup
    confluence_score: float = 0.0
    era_sentiment: str = 'neutral'
    nearby_geo_events: list = None          # type: ignore[assignment]

    def __post_init__(self):
        if self.nearby_geo_events is None:
            self.nearby_geo_events = []


def simulate_setup(
    setup: Setup,
    bars: list[dict],
    rr_ratios: tuple[float, ...] = (1.5, 2.0, 3.0),
    max_bars_held: int = 96,   # 4 days on H4 = max trade duration
    trailing_stop: bool = True,
) -> list[SimResult]:
    """
    Simulate a setup forward from its trigger bar.

    Args:
        setup:          Setup from pattern_detector.find_setups()
        bars:           Full OHLCV list (same bars used to detect setup)
        rr_ratios:      R:R variants to test
        max_bars_held:  Expire trade if not hit SL/TP within this many bars
        trailing_stop:  If True, also simulate a 50%-giveback trailing exit

    Returns:
        List of SimResult, one per rr_ratio. Trailing variant appended if enabled.
    """
    sl_atr_mult = ENERGY_SL_ATR if setup.symbol in _ENERGY_SYMBOLS else SL_ATR_MULTIPLIER
    sl_distance = sl_atr_mult * setup.atr

    results: list[SimResult] = []

    for rr in rr_ratios:
        result = _simulate_single(
            setup=setup,
            bars=bars,
            sl_distance=sl_distance,
            rr=rr,
            max_bars_held=max_bars_held,
            trailing_stop=trailing_stop,
        )
        results.append(result)

    return results


def _simulate_single(
    setup: Setup,
    bars: list[dict],
    sl_distance: float,
    rr: float,
    max_bars_held: int,
    trailing_stop: bool,
) -> SimResult:
    entry = setup.entry_price
    direction = setup.direction
    start_idx = setup.trigger_bar_index

    if direction == 'bullish':
        sl_price = entry - sl_distance
        tp_price = entry + sl_distance * rr
    else:
        sl_price = entry + sl_distance
        tp_price = entry - sl_distance * rr

    tp_distance = abs(tp_price - entry)

    best_r = 0.0     # MFE in R
    worst_r = 0.0    # MAE in R
    trailing_exit_r = 0.0
    peak_r = 0.0     # for trailing stop tracking

    outcome = 'EXPIRED'
    exit_price = entry
    exit_bar_index = min(start_idx + max_bars_held, len(bars) - 1)
    exit_bar_time = None

    for i in range(start_idx + 1, min(start_idx + max_bars_held + 1, len(bars))):
        bar = bars[i]
        high = bar['high']
        low = bar['low']

        # Current favorable/adverse in R multiples
        if direction == 'bullish':
            bar_mfe = (high - entry) / sl_distance
            bar_mae = (entry - low) / sl_distance
            sl_touched = low <= sl_price
            tp_touched = high >= tp_price
        else:
            bar_mfe = (entry - low) / sl_distance
            bar_mae = (high - entry) / sl_distance
            sl_touched = high >= sl_price
            tp_touched = low <= tp_price

        best_r = max(best_r, bar_mfe)
        worst_r = max(worst_r, bar_mae)

        # Track peak for trailing stop
        peak_r = max(peak_r, bar_mfe)

        # Trailing stop: exit if price gives back 50% of peak profit
        # Only activates once peak_r > 1.0R (past 1R profit)
        if trailing_stop and peak_r >= 1.0:
            trailing_exit_level_r = peak_r * 0.5
            if direction == 'bullish':
                trailing_exit_price = entry + trailing_exit_level_r * sl_distance
                if low <= trailing_exit_price and bar_mae > peak_r * 0.5:
                    # Trailing exit triggered — use as secondary outcome
                    trailing_exit_r = trailing_exit_level_r
                    if outcome == 'EXPIRED':  # not yet hit SL/TP
                        outcome = 'TRAILING_EXIT'
                        exit_price = trailing_exit_price
                        exit_bar_index = i
                        exit_bar_time = _parse_bar_time(bar['time'])
                        break
            else:
                trailing_exit_price = entry - trailing_exit_level_r * sl_distance
                if high >= trailing_exit_price and bar_mae > peak_r * 0.5:
                    trailing_exit_r = trailing_exit_level_r
                    if outcome == 'EXPIRED':
                        outcome = 'TRAILING_EXIT'
                        exit_price = trailing_exit_price
                        exit_bar_index = i
                        exit_bar_time = _parse_bar_time(bar['time'])
                        break

        # SL hit — check before TP on same bar (conservative)
        if sl_touched:
            outcome = 'LOSS'
            exit_price = sl_price
            exit_bar_index = i
            bar_time = bar['time']
            if isinstance(bar_time, (int, float)):
                bar_time = datetime.fromtimestamp(bar_time, tz=timezone.utc)
            exit_bar_time = bar_time
            break

        if tp_touched:
            outcome = 'WIN'
            exit_price = tp_price
            exit_bar_index = i
            bar_time = bar['time']
            if isinstance(bar_time, (int, float)):
                bar_time = datetime.fromtimestamp(bar_time, tz=timezone.utc)
            exit_bar_time = bar_time
            break

    # Expired — exit at last bar close
    if outcome == 'EXPIRED':
        last_bar = bars[exit_bar_index]
        exit_price = last_bar['close']
        exit_bar_time = _parse_bar_time(last_bar['time'])

    # Calculate final P&L in R
    if outcome == 'WIN':
        pnl_r = rr
    elif outcome == 'LOSS':
        pnl_r = -1.0
    elif outcome == 'TRAILING_EXIT':
        pnl_r = trailing_exit_r
    else:
        # EXPIRED — measure distance from entry
        if direction == 'bullish':
            pnl_r = (exit_price - entry) / sl_distance
        else:
            pnl_r = (entry - exit_price) / sl_distance

    return SimResult(
        setup_symbol=setup.symbol,
        direction=direction,
        entry_price=entry,
        sl_price=sl_price,
        tp_price=tp_price,
        rr_ratio=rr,
        outcome=outcome,
        exit_price=exit_price,
        exit_bar_index=exit_bar_index,
        exit_bar_time=exit_bar_time,
        pnl_r=round(pnl_r, 3),
        bars_held=exit_bar_index - start_idx,
        max_favorable_excursion=round(best_r, 3),
        max_adverse_excursion=round(worst_r, 3),
        trailing_exit=outcome == 'TRAILING_EXIT',
        trailing_exit_r=round(trailing_exit_r, 3),
        confluence_score=setup.confluence_score,
        era_sentiment=setup.era_sentiment,
        nearby_geo_events=setup.nearby_geo_events,
    )


# ---------------------------------------------------------------------------
# Aggregation helpers for seeder reporting
# ---------------------------------------------------------------------------

def aggregate_results(results: list[SimResult]) -> dict:
    """
    Compute win rates and expectancy across a batch of SimResults.
    Groups by rr_ratio and symbol.
    """
    from collections import defaultdict

    by_rr: dict[float, list[SimResult]] = defaultdict(list)
    for r in results:
        by_rr[r.rr_ratio].append(r)

    summary = {}
    for rr, group in by_rr.items():
        total = len(group)
        wins = sum(1 for r in group if r.outcome == 'WIN')
        losses = sum(1 for r in group if r.outcome == 'LOSS')
        trailing = sum(1 for r in group if r.outcome == 'TRAILING_EXIT')
        expired = sum(1 for r in group if r.outcome == 'EXPIRED')
        wr = wins / total if total else 0.0
        avg_pnl_r = sum(r.pnl_r for r in group) / total if total else 0.0
        expectancy = (wr * rr) - ((1 - wr) * 1.0)

        summary[f'rr_{rr}'] = {
            'total': total,
            'wins': wins,
            'losses': losses,
            'trailing_exits': trailing,
            'expired': expired,
            'win_rate': round(wr, 3),
            'avg_pnl_r': round(avg_pnl_r, 3),
            'expectancy_r': round(expectancy, 3),
        }

    return summary
