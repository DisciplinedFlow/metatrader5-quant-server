"""
Geopolitical Event Registry — Static knowledge base seeded from Claude's training data.

These events are encoded as context nodes in Neo4j. Trades occurring within ±24h of
an escalation event get tagged, allowing the brain to later query:
"Does FVG_BOUNCE on XAUUSD have a higher WR during active conflict periods?"

News is a HELPER — it enriches context, not a gate.

Coverage:
  - Iran/Israel escalation cycle (2024 direct attacks, ongoing 2025+)
  - Russia/Ukraine infrastructure strikes
  - US Fed/macro events that create structural dislocations
  - OPEC supply decisions affecting energy

Events after Aug 2025 are tagged as generic ERA nodes — the user updates these
manually via Django admin as they occur. Price data already reflects those events
structurally; the era tag adds human-readable context to the graph.
"""

from datetime import date

# ---------------------------------------------------------------------------
# Known geopolitical escalation events (Claude training knowledge)
# Each event tags nearby trades with sentiment context
# ---------------------------------------------------------------------------

GEOPOLITICAL_EVENTS = [

    # --- Iran / Israel / US escalation cycle ---
    {
        'date': '2024-01-15',
        'type': 'ESCALATION',
        'event': 'US strikes Iran-backed militias in Iraq/Syria (Kataib Hezbollah)',
        'affected_classes': ['METAL', 'ENERGY'],
        'sentiment': 'risk_off',
        'intensity': 0.6,
    },
    {
        'date': '2024-01-28',
        'type': 'ESCALATION',
        'event': 'Jordan Tower 22 drone attack kills 3 US soldiers — retaliation risk spike',
        'affected_classes': ['METAL', 'ENERGY'],
        'sentiment': 'risk_off',
        'intensity': 0.8,
    },
    {
        'date': '2024-02-02',
        'type': 'ESCALATION',
        'event': 'US multi-site strikes on 85 targets Iraq/Syria — oil geopolitical premium surges',
        'affected_classes': ['METAL', 'ENERGY'],
        'sentiment': 'risk_off',
        'intensity': 0.7,
    },
    {
        'date': '2024-04-01',
        'type': 'ESCALATION',
        'event': 'Israeli strike on Iranian consulate Damascus — first direct attack on Iranian soil',
        'affected_classes': ['METAL', 'ENERGY'],
        'sentiment': 'risk_off',
        'intensity': 0.9,
    },
    {
        'date': '2024-04-13',
        'type': 'ESCALATION',
        'event': 'Iran launches 300+ drones and missiles directly at Israel — first ever direct attack',
        'affected_classes': ['METAL', 'ENERGY', 'FOREX'],
        'sentiment': 'extreme_risk_off',
        'intensity': 1.0,
    },
    {
        'date': '2024-04-19',
        'type': 'DE_ESCALATION',
        'event': 'Israel limited strike response — both sides signal no wider war, risk partially recovers',
        'affected_classes': ['METAL', 'ENERGY'],
        'sentiment': 'partial_recovery',
        'intensity': 0.5,
    },
    {
        'date': '2024-07-30',
        'type': 'ESCALATION',
        'event': 'Hezbollah commander killed in Beirut — escalation risk resurfaces',
        'affected_classes': ['METAL', 'ENERGY'],
        'sentiment': 'risk_off',
        'intensity': 0.6,
    },
    {
        'date': '2024-07-31',
        'type': 'ESCALATION',
        'event': 'Hamas leader Ismail Haniyeh assassinated in Tehran — major escalation trigger',
        'affected_classes': ['METAL', 'ENERGY', 'FOREX'],
        'sentiment': 'extreme_risk_off',
        'intensity': 0.95,
    },
    {
        'date': '2024-08-05',
        'type': 'ESCALATION',
        'event': 'Global carry trade unwind (Yen spike) compounds Middle East risk-off',
        'affected_classes': ['METAL', 'FOREX'],
        'sentiment': 'risk_off',
        'intensity': 0.8,
    },
    {
        'date': '2024-10-01',
        'type': 'ESCALATION',
        'event': 'Iran fires ~180 ballistic missiles at Israel — largest direct attack in history',
        'affected_classes': ['METAL', 'ENERGY', 'FOREX'],
        'sentiment': 'extreme_risk_off',
        'intensity': 1.0,
    },
    {
        'date': '2024-10-07',
        'type': 'ERA_MARKER',
        'event': '1-year anniversary of Hamas attack — heightened alert period',
        'affected_classes': ['METAL', 'ENERGY'],
        'sentiment': 'elevated_risk',
        'intensity': 0.5,
    },
    {
        'date': '2024-10-26',
        'type': 'ESCALATION',
        'event': 'Israeli strike on Iranian military sites — first direct Israel-Iran military exchange',
        'affected_classes': ['METAL', 'ENERGY'],
        'sentiment': 'risk_off',
        'intensity': 0.8,
    },

    # --- Russia / Ukraine infrastructure strikes ---
    {
        'date': '2024-03-22',
        'type': 'ESCALATION',
        'event': 'Crocus City Hall Moscow attack — Russia escalates Ukraine strikes in response',
        'affected_classes': ['METAL', 'ENERGY', 'FOREX'],
        'sentiment': 'risk_off',
        'intensity': 0.7,
    },
    {
        'date': '2024-06-23',
        'type': 'ESCALATION',
        'event': 'Ukraine strikes Russian early warning radar — NATO escalation concerns',
        'affected_classes': ['METAL', 'ENERGY'],
        'sentiment': 'risk_off',
        'intensity': 0.6,
    },
    {
        'date': '2024-11-19',
        'type': 'ESCALATION',
        'event': 'Biden authorizes Ukraine ATACMS deep strikes into Russia — nuclear rhetoric spike',
        'affected_classes': ['METAL', 'ENERGY', 'FOREX'],
        'sentiment': 'extreme_risk_off',
        'intensity': 0.9,
    },
    {
        'date': '2024-11-21',
        'type': 'ESCALATION',
        'event': 'Russia fires intercontinental ballistic missile at Ukraine for first time',
        'affected_classes': ['METAL', 'ENERGY', 'FOREX'],
        'sentiment': 'extreme_risk_off',
        'intensity': 0.95,
    },

    # --- US Fed / macro structural dislocations ---
    {
        'date': '2024-03-20',
        'type': 'MACRO_EVENT',
        'event': 'Fed holds rates — dot plot shifts hawkish, USD structural move',
        'affected_classes': ['METAL', 'FOREX'],
        'sentiment': 'usd_strength',
        'intensity': 0.6,
    },
    {
        'date': '2024-09-18',
        'type': 'MACRO_EVENT',
        'event': 'Fed cuts 50bps — surprise outsized cut, gold surges to ATH',
        'affected_classes': ['METAL', 'FOREX'],
        'sentiment': 'usd_weakness',
        'intensity': 0.9,
    },
    {
        'date': '2024-11-05',
        'type': 'MACRO_EVENT',
        'event': 'US election — Trump wins, dollar spike, gold initial selloff then recovery',
        'affected_classes': ['METAL', 'FOREX', 'ENERGY'],
        'sentiment': 'volatile_structural',
        'intensity': 1.0,
    },
    {
        'date': '2025-01-20',
        'type': 'MACRO_EVENT',
        'event': 'Trump inauguration — tariff threats, USD volatile, gold re-accelerates',
        'affected_classes': ['METAL', 'FOREX', 'ENERGY'],
        'sentiment': 'volatile_structural',
        'intensity': 0.8,
    },

    # --- OPEC / Energy supply decisions ---
    {
        'date': '2024-06-02',
        'type': 'SUPPLY_EVENT',
        'event': 'OPEC+ extends voluntary cuts through Q3 2024 — oil supported',
        'affected_classes': ['ENERGY'],
        'sentiment': 'oil_bullish',
        'intensity': 0.7,
    },
    {
        'date': '2024-11-03',
        'type': 'SUPPLY_EVENT',
        'event': 'OPEC+ delays production hike again — supply tightness maintained',
        'affected_classes': ['ENERGY'],
        'sentiment': 'oil_bullish',
        'intensity': 0.6,
    },

    # --- Generic era tags for post-knowledge-cutoff period ---
    # Price data reflects these structurally — era tag adds human context
    {
        'date': '2025-09-01',
        'type': 'ERA_START',
        'event': 'Ongoing Iran-Israel-US elevated tensions (user-confirmed, March 2026)',
        'affected_classes': ['METAL', 'ENERGY', 'GAS'],
        'sentiment': 'elevated_geopolitical_risk',
        'intensity': 0.7,
    },
    {
        'date': '2025-09-01',
        'type': 'ERA_START',
        'event': 'Ongoing Russia-Ukraine conflict — energy supply disruption risk',
        'affected_classes': ['ENERGY', 'GAS', 'METAL'],
        'sentiment': 'elevated_geopolitical_risk',
        'intensity': 0.6,
    },
]

# ---------------------------------------------------------------------------
# Helper: find events within N hours of a timestamp
# ---------------------------------------------------------------------------

def _to_date(dt):
    """Extract a date object from a datetime or date input."""
    if hasattr(dt, 'date') and callable(dt.date):
        return dt.date()
    return dt


def _parse_event_date(raw):
    """Parse an event date string or pass through a date object."""
    if isinstance(raw, date):
        return raw
    return date.fromisoformat(raw)


def get_nearby_events(dt, window_hours=24):
    """Return events within ±window_hours of the given datetime."""
    d = _to_date(dt)
    return [
        ev for ev in GEOPOLITICAL_EVENTS
        if abs((d - _parse_event_date(ev['date'])).days) * 24 <= window_hours
    ]


def get_era_sentiment(dt):
    """
    Return the dominant sentiment for a given date based on active era tags.
    Used to enrich trade nodes with macro context without blocking logic.
    """
    d = _to_date(dt)

    for ev in GEOPOLITICAL_EVENTS:
        if ev['type'] == 'ERA_START' and d >= _parse_event_date(ev['date']):
            return ev['sentiment']

    return 'neutral'
