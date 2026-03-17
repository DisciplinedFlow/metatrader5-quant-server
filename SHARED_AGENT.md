# Shared Agent Communication

> This file is the shared communication channel between Claude Code agent instances.
> Each agent should READ this file at session start and UPDATE it before ending work.
> Prevents duplicate work, conflicts, and keeps agents coordinated on shared codebase.

---

## Active Agents

| Agent | Domain | Status | Last Active | tmux Session |
|-------|--------|--------|-------------|-------------|
| Agent A | Forex trading system, backtesting, ML, indicators, Neo4j | Active | Mar 17, 2026 07:30 CET | — |
| Agent B | Forex domain (separate tmux) | Active | Mar 17, 2026 | tmux forex |

## Current System State (Mar 17, 2026)

### Bot Status
- **Bot:** RUNNING, TRAINING_MODE=False
- **Account:** VantageInternational-Demo, EUR currency, 500:1 leverage
- **Balance:** ~€96,785
- **Closed trades:** 82 (33W/49L, 40.2%, -$112 PnL)
- **Open trades:** check `Trade.objects.filter(close_time__isnull=True)`

### Active Strategies (6 of 29)
1. London Open Metals Momentum (p=5) — NEW, session filter temporarily set to 24h
2. CVD Lack of Participants (p=10) — best performer, +$22 PnL
3. CVD Absorption (p=10) — break-even, monitoring
4. CVD Futures vs Spot Comparison (p=10)
5. Oil Time-Series Momentum (p=10)
6. Energy Trend Follow (p=10)

### Disabled Strategies (bleeding money)
- SCALPING — 20W/30L, -$40
- CVD Extremes Scanner — 4W/7L, -$56
- ICT BOS Continuation + FVG — 0W/1L
- ICT Market Structure + FVG — 0W/2L

### Recent Changes (Mar 16-17)

#### Position Sizing
- **Risk-based sizing** replaces leverage-based: `lots = target_risk / loss_per_lot_at_SL`
- MAX_LOSS_PER_TRADE = €50, scaled by size_multiplier (10 factors)
- LEVERAGE=200 no longer used for sizing
- NG-C vol_min guard: skips when risk > 2.5x target

#### Circuit Breaker
- Global: 10m cooldown (was 1h → 15m → 10m)
- Symbol: 30m cooldown (was 1h)
- Volatility override: halves to 5m when XAUUSD ATR > 1.5x average

#### MT5 API (5 new endpoints)
- GET /account_info — balance, equity, margin, leverage
- POST /order_check — dry-run order validation
- GET /order_calc_margin — margin pre-calculation
- GET /order_calc_profit — P&L calculation
- GET /history_deals_get — position param now optional (bulk mode)

#### Reconciliation
- `reconcile_positions()` runs every 30s on critical queue
- Creates DB records for MT5 positions missing from DB
- Closes DB records for trades missing from MT5 (with deal history)
- Bulk deal history via single API call

#### Indicators (new)
- **VWAP** — daily session-reset, feeds +1 confluence point
- **Session levels** — prev day H/L, Asian H/L, sweep detection, +1 confluence
- **News sentiment** — RSS feeds (CNBC, MarketWatch, BBC, Yahoo), keyword detection
  - Currently: EXTREME (iran, war, inflation, crude oil) → 0.5x position sizing
- Confluence max: 12 → 14

#### Deal History Fix
- `get_deal_from_ticket()` fixed — filters by position_id, separates entry/exit deals
- Close algorithm now records actual MT5 execution prices

#### XAGUSD Special Treatment
- Confluence gate lowered to 3 (other symbols: 4-6)
- Silver CVD signals more reliable in thin liquidity

### Files Recently Modified
See `git log --oneline -10` for latest commits.

### Known Issues
- **MT5 Wine dialog** — `msedgewebview2.exe` pops up on restart, blocks Flask API. Must dismiss manually via VNC (localhost:3443). Deleting EdgeWebView dirs helps temporarily but MT5 re-downloads it.
- **Orphan trades** — reconciliation catches them now, but MT5 crashes still cause brief desyncs
- **feedparser** — installed via pip in celery container, not in requirements.txt image. Will be lost on container rebuild.

### Backtest Data Available
- `research/backtest_data/` — 42 CSVs, 191K bars (MT5 + yfinance)
- `research/run_backtest.py` — reusable CVD backtest script
- `BACKTEST_ANALYSIS.md` — full analysis (VWAP filter is the real edge, NY session 15-18 UTC best hours)

### Architecture Documents
- `research/NEO4J_MARKET_MEMORY_ARCHITECTURE.md` — 6-phase design for market memory
- `TRADING_SETTINGS.md` — all runtime parameter changes
- `ARCHITECTURE.md` — infrastructure diagrams

## Rules for Agents

1. **Read this file** at the start of every session
2. **Update your status** in the Active Agents table
3. **Check git status** before making changes — another agent may have uncommitted work
4. **Don't modify files** another agent is actively working on
5. **Hot-patch protocol:** `docker cp` + `docker compose restart celery celery-beat`
6. **Push to:** `disciplined` remote (DisciplinedFlow GitHub)
7. **Neo4j creds:** neo4j / trading_brain_2026, bolt://neo4j:7687
8. **MT5 API:** localhost:5001 (from host) or mt5:5001 (from containers)
9. **Dashboard:** rebuild with `docker compose up -d --build dashboard`
10. **Always clean orphans** after any restart/crash
