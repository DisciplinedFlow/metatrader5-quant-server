"""Kill Zone Detection and Session Weighting.

ICT methodology identifies specific time windows where institutional
order flow creates the day's directional moves. Pip ranges during
London-NY overlap are 30-50% larger than single sessions.

Kill zones affect both ENTRY PERMISSION and POSITION SIZING:
- NY Open (12:00-15:00 UTC): Weight 2.0 — highest volatility, biggest moves
- London Open (07:00-10:00 UTC): Weight 1.5 — second highest probability
- London Close (15:00-17:00 UTC): Weight 1.0 — retracement/reversal setups
- Outside kill zones (but in session): Weight 0.5 — lower probability
- Asian (00:00-06:00 UTC): Weight 0.3 — ranging, accumulation only

Livermore Ch X: "In a narrow market, don't anticipate direction — wait for the breakout"
Asian session = narrow market. Kill zones = where breakouts happen.
"""

import logging
from datetime import datetime, time, timedelta, timezone

from django.utils import timezone as dj_timezone

logger = logging.getLogger('kill_zones')


# ---------------------------------------------------------------------------
# Kill zone definitions (UTC times)
# ---------------------------------------------------------------------------

KILL_ZONES = {
    'ny_open': {
        'start': time(12, 0),
        'end': time(15, 0),
        'weight': 2.0,
        'description': 'NY Open — highest volatility, London/NY overlap',
        'best_for': ['trend_continuation', 'displacement', 'breakout'],
    },
    'london_open': {
        'start': time(7, 0),
        'end': time(10, 0),
        'weight': 1.5,
        'description': 'London Open — high probability directional move',
        'best_for': ['trend_start', 'liquidity_sweep', 'displacement'],
    },
    'london_close': {
        'start': time(15, 0),
        'end': time(17, 0),
        'weight': 1.0,
        'description': 'London Close — retracement/reversal setups',
        'best_for': ['mean_reversion', 'reversal', 'fvg_fill'],
    },
    'asian_session': {
        'start': time(0, 0),
        'end': time(6, 0),
        'weight': 0.3,
        'description': 'Asian Session — ranging, accumulation',
        'best_for': ['range_bound', 'accumulation'],
    },
}

# Weight applied when the current time falls outside ALL named kill zones
# but within the broader session (06:00-07:00 UTC or 10:00-12:00 UTC gaps)
DEFAULT_WEIGHT = 0.5

# Ordered list for next-zone calculation (chronological by start time)
_ZONE_ORDER = ['asian_session', 'london_open', 'ny_open', 'london_close']


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_current_kill_zone():
    """Get the currently active kill zone and its weight.

    Returns:
        (zone_name: str or None, weight: float, zone_info: dict or None)
        If no kill zone is active, returns (None, 0.5, None) — base weight.
    """
    now = dj_timezone.now()
    return get_kill_zone_for_time(now)


def get_kill_zone_weight():
    """Get the position sizing weight for the current time.

    Returns float: 0.3 to 2.0 based on current kill zone.
    Used as a multiplier in the confluence scorer and position sizing.
    """
    _, weight, _ = get_current_kill_zone()
    return weight


def is_in_kill_zone():
    """Check if current time is in any named kill zone.

    Returns: bool
    """
    zone_name, _, _ = get_current_kill_zone()
    return zone_name is not None


def get_kill_zone_for_time(dt):
    """Get kill zone info for an arbitrary datetime (for backtesting).

    Args:
        dt: datetime object (timezone-aware preferred; naive assumed UTC)

    Returns:
        (zone_name: str or None, weight: float, zone_info: dict or None)
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    utc_time = dt.astimezone(timezone.utc).time()

    for zone_name, zone_info in KILL_ZONES.items():
        if _time_in_range(utc_time, zone_info['start'], zone_info['end']):
            return zone_name, zone_info['weight'], zone_info

    return None, DEFAULT_WEIGHT, None


def get_session_context():
    """Get full session context for logging/analysis.

    Returns dict with:
    - current_zone: str or None
    - weight: float
    - time_until_next_zone: timedelta or None
    - next_zone: str or None
    - description: str
    """
    now = dj_timezone.now().astimezone(timezone.utc)
    zone_name, weight, zone_info = get_kill_zone_for_time(now)

    next_zone, time_until = _next_kill_zone(now)

    if zone_info:
        description = zone_info['description']
    elif weight == DEFAULT_WEIGHT:
        description = 'Between kill zones — reduced probability'
    else:
        description = 'Outside all sessions'

    return {
        'current_zone': zone_name,
        'weight': weight,
        'time_until_next_zone': time_until,
        'next_zone': next_zone,
        'description': description,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _time_in_range(t, start, end):
    """Check if time ``t`` falls in [start, end) range.

    Handles same-day ranges only (no overnight wrapping needed for our zones).
    """
    return start <= t < end


def _next_kill_zone(now_utc):
    """Find the next kill zone after ``now_utc``.

    Returns (zone_name: str, time_until: timedelta).
    """
    current_time = now_utc.time()

    for zone_name in _ZONE_ORDER:
        zone_start = KILL_ZONES[zone_name]['start']
        if zone_start > current_time:
            # This zone hasn't started yet today
            start_dt = now_utc.replace(
                hour=zone_start.hour, minute=zone_start.minute,
                second=0, microsecond=0,
            )
            return zone_name, start_dt - now_utc

    # All zones for today have passed; next is asian_session tomorrow
    first_zone = _ZONE_ORDER[0]
    first_start = KILL_ZONES[first_zone]['start']
    tomorrow = now_utc + timedelta(days=1)
    start_dt = tomorrow.replace(
        hour=first_start.hour, minute=first_start.minute,
        second=0, microsecond=0,
    )
    return first_zone, start_dt - now_utc
