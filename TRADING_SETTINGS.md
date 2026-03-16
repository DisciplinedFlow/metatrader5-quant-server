# Trading Settings Changelog

> Track all runtime parameter changes. Revert by restoring previous values and restarting celery.

---

## Active Configuration (as of Mar 16, 2026 06:50 CET)

| Parameter | Value | File | Notes |
|-----------|-------|------|-------|
| TRAINING_MODE | `False` | `cvd/entry.py:74` | All protection gates active except those explicitly disabled below |
| CAPITAL_PER_TRADE | `$2,000` | `cvd/config.py:6` | Energy: $300 |
| SL_ATR_MULTIPLIER | `1.8` | `cvd/config.py:11` | Energy: 2.0 |
| TP_ATR_MULTIPLIER | `3.6` | `cvd/config.py:12` | Energy: 4.0 |
| R:R Ratio | `1:2.0` | Computed | Exact |
| MAX_OPEN_TRADES | `20` | `cvd/config.py:9` | Was 5 |
| GLOBAL_MAX | `20` | `tasks.py:25` | Was 10 |
| Per-strategy max_positions | `10` | DB: StrategyConfig | Was 3 |
| DAILY_MAX_LOSS_USD | `$9,999` (disabled) | `tasks.py:26` | Was $300 |
| DRAWDOWN_REDUCTION | `$2,000` | `tasks.py:27` | Still active — falls to $100/trade |
| MAX_LOSS_PER_TRADE | `$50` | `entry.py:80` | Broker SL, still active |
| Circuit Breaker (symbol) | `3 losses → 30m` | `entry.py:57,60` | Was 1h — reduced for algo bot |
| Circuit Breaker (global) | `5 losses → 15m` | `entry.py:58,59` | Was 1h — reduced for algo bot |
| Time Filter | `24/7 (Mon-Fri)` | `entry.py:425` | Only blocks Sat + Sun before 22:00 UTC |
| Active Strategies | `15` | DB | Including CVD Lack of Participants + Absorption |
| Lighter trading toggle | API + Dashboard | `crypto/views.py`, `lighter/entry.py` | Runtime enable/disable via Redis |
| Hyperliquid trading toggle | API + Dashboard | `crypto/views.py`, `crypto/entry.py` | Runtime enable/disable via Redis |

## Protection Still Active
- Circuit breakers (3 symbol consecutive losses → 30m pause, 5 global → 15m pause)
- Max loss per trade ($50 broker SL)
- Drawdown reduction ($2,000 cumulative → $100/trade fallback)
- Anti-churn (30s cooldown same symbol)
- Confluence gate (min score 4, min 6 outside kill zones)
- Strategy router (regime-based filtering)
- Group tendency (Livermore correlation check)
- Session quality confluence factor (+1 in kill zones)
- Consecutive loss size reduction (2 losses=0.5x, 3+=0.25x)

## Protection Disabled for Data Collection
- Daily halt ($300/day) — disabled to allow unlimited trading volume
- Time filter (07:00-17:00 UTC) — expanded to 24/7
- Backtest gate (SCALPING) — was requiring 55% WR from stale backtest, blocking all SCALPING entries
- Backtest gate (CVD) — already disabled (commented out)

---

## The 6 Fixes (Session 1 Post-Mortem)

| # | Fix | What Changed | Source |
|---|-----|-------------|--------|
| 1 | **Confluence size_multiplier applied to sizing** | Score 3=0.5x, 4-7=1.0x, 8+=1.5x now multiplies position size | entry.py:1697 |
| 2 | **Min confluence 6 outside kill zones** | Requires sweep/FVG/OB confirmation, not just CVD+HTF | entry.py:1578 |
| 3 | **Sunday dead zone blocked** | Sun 22:00 - Mon 02:00 UTC blocked (first 4h thin liquidity) | entry.py:425 |
| 4 | **Consecutive loss size reduction** | 2 losses=0.5x, 3+=0.25x per strategy | entry.py:1677 |
| 5 | **Dead trade exit at 20min** | Was 30min/$3, now 20min/$2 (Marcus rule) | position_manager.py:56 |
| 6 | **Session quality 9th confluence factor** | +1 point in kill zones, max score now 12 | confluence_scorer.py |

## Change Log

### Mar 16, 2026 — 05:50 UTC (Circuit Breaker Tuning + Venue Controls + Backtest Gate)
- **Circuit Breaker (global):** 1h → **15m** cooldown after 5 consecutive global losses
- **Circuit Breaker (symbol):** 1h → **30m** cooldown after 3 consecutive losses on same symbol
- **Reason:** 1h was designed for human traders ("walk away, cool off") — algo bots don't tilt. 15m lets market conditions shift while maximizing data collection for ML training
- **Circuit Breaker logging:** Reduced global cooldown log from INFO to DEBUG (was flooding ~588 entries/cycle)
- **Circuit Breaker early-exit:** Added fast global CB check at top of `run_quant_entry_algorithm()` in tasks.py to skip strategy iteration entirely when global CB active
- **Per-symbol CB logging:** Reduced to DEBUG level to prevent log spam
- **Lighter signer proxy:** Started on port 5555 (was not running — blocking all Lighter DEX trades)
- **Lighter trading toggle:** New API endpoint `/api/django/v1/crypto/lighter/control/` + dashboard UI toggle
- **Hyperliquid trading toggle:** New API endpoint `/api/django/v1/crypto/hyperliquid/control/` + dashboard UI toggle
- **Dashboard:** Added venue toggle buttons in both system status bar (compact) and venue blocks (labeled)
- **Backtest gate (SCALPING):** Disabled — was blocking all SCALPING entries (33.77% WR < 55% threshold from stale backtest)
- **Backtest gate (CVD):** Already disabled (was commented out earlier)

### Mar 16, 2026 — 05:00 UTC (Session 1 Post-Mortem Fixes)
- **FIX 1:** Confluence size_multiplier now applied to position sizing (was computed but unused)
- **FIX 2:** Min confluence raised to 6 outside kill zones (was 4 everywhere)
- **FIX 3:** Sunday 22:00 - Monday 02:00 UTC blocked (was allowed)
- **FIX 4:** Consecutive loss size reduction: 2 losses=0.5x, 3+=0.25x (was full size always)
- **FIX 5:** Dead trade exit tightened: 30min/$3 → 20min/$2
- **FIX 6:** Session quality added as 9th confluence factor (+1 in kill zones, max score now 12)
- **Reason:** Session 1 was 1W/10L (-$116.65). Root cause: score-4 trades at full size in Asian dead zone

### Mar 16, 2026 — 03:00 UTC
- **DAILY_MAX_LOSS_USD:** $300 → $9,999 (effectively disabled)
- **Reason:** Data collection phase — need maximum trade volume for ML training

### Mar 16, 2026 — 02:55 UTC
- **CVD Lack of Participants:** inactive → ACTIVE (StrategyConfig[25])
- **CVD Absorption:** inactive → ACTIVE (StrategyConfig[24])
- **MAX_OPEN_TRADES:** 5 → 20
- **GLOBAL_MAX:** 10 → 20
- **Per-strategy max_positions:** 3 → 10 (all 15 active strategies)
- **Reason:** Bot was scanning but never trading — CVD strategies had no StrategyConfig, limits too tight

### Mar 15, 2026 — 22:10 UTC
- **Time filter:** 07:00-17:00 UTC only → 24/7 (Mon 00:00 - Fri 22:00, Sun 22:00+)
- **Reason:** Asian session strategies (GBPUSD Asian Sweep, AUDUSD Asian MR) were permanently blocked

### Mar 15, 2026 — 21:00 UTC
- **TP_ATR_MULTIPLIER:** 3.5 → 3.6 (exact 1:2 R:R)
- **Energy TP_ATR:** 3.0 → 4.0 (exact 1:2 R:R)
- **Bot:** paused → UNPAUSED
- **Redis:** all stale state flushed (circuit breakers, orchestrator, daily halt)
- **Reason:** Fresh start for paper trading run Mar 15-31

### Mar 15, 2026 — 21:15 UTC
- **Neo4j Knowledge Graph:** deployed (neo4j:5-community, 1GB mem)
- **Recording hooks:** trade close, entry rejections (10 hooks), exit events (9 hooks), ICT partials (7 hooks)
- **Reason:** Build trading brain for self-refining ML pipeline
