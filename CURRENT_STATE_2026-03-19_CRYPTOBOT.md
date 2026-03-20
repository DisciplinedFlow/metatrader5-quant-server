# Crypto Bot Current State — 2026-03-19 23:50 UTC

## Account
- **Exchange:** Lighter.xyz (mainnet)
- **Account Index:** 718566
- **Equity:** $23.00
- **Leverage:** 15x cross
- **Currency:** USD

## Status: RUNNING (clean slate)
- DB wiped and rebuilt at ~20:00 UTC after full audit
- 5W/0L since clean slate, +$1.18 realized PnL
- 2 open positions (SOL LONG, XAU LONG) currently underwater in volatile session
- All bugs from audit are fixed and deployed
- ML training pipeline wired — records features at entry, outcome at exit to JSONL

## Performance (post clean-slate)
| Metric | Value |
|--------|-------|
| Closed Trades | 5 |
| Win Rate | 100% (5W/0L) |
| Net PnL | +$1.18 |
| Avg Win | $0.24 |
| Total Fees | $0.44 (37% of PnL — improved by raising profit protection thresholds) |

## Active Strategies
| Strategy | Symbols | Sizing |
|----------|---------|--------|
| RSI Scalper (RSI2) | SOL, XAU | $12 x 15x x combined_sizing(session+symbol+kelly) x funding x flow |
| Mean Reversion (BB) | SOL, XAU, EURUSD | $12 x 15x x combined_sizing x funding x flow |
| Momentum (EMA) | SOL, XAU, AVAX, DOGE | risk-normalised / SL% x combined_sizing |
| CVD Entry | SOL | risk-normalised / SL% x combined_sizing |
| Entry (EMA MTF) | SOL, AVAX, LINK, DOGE, XAU | capital x position% x 15x x combined_sizing |
| Grid | DISABLED | -- |

## Removed Symbols
- **BTC:** 50% WR, -$4.08 net PnL across 12 trades — outsized losses
- **ETH:** 60% WR, -$8.32 net PnL across 15 trades — outsized losses
- Removed from ALL strategy symbol lists (config, rsi_scalper, mean_reversion, grid, momentum, cvd_entry)
- Also removed from `.env` LIGHTER_PAIRS

## Removed Intelligence Layers
| Layer | Reason |
|-------|--------|
| News Sentiment (RSS) | Permanently EXTREME (war/iran/gold always in headlines). Was double-counted (0.5 x 0.5 = 0.25x). Irrelevant for crypto. Removed from ALL strategies. |
| Neo4j Graph Feedback | Offline, always returned 1.0. Could block trades with `return 0.0` in mean_reversion. Removed from ALL strategies. |
| Graph Advisor | Offline, always returned 1.0. AVOID blocked trades in entry, cvd, mean_reversion. Removed from ALL strategies. |
| LLM Scorer (Pi NPU) | Not active for Lighter strategies |

## Active Intelligence Layers
| Layer | Effect |
|-------|--------|
| Session Multiplier | 0.6-1.2x based on UTC hour (Asian 0.6, London 1.0, US Overlap 1.2) |
| Symbol Multiplier | Per-symbol scaling (EURUSD 0.5x, GBPUSD 0.0x disabled) |
| Kelly Sizing | Adaptive from recent trade history (needs 10+ trades to activate) |
| Funding Rate | Contrarian: agrees +20%, disagrees -30% |
| Trade Flow / Whale | Whale in direction +20%, whale against -30% |

## Profit Protection Tiers (raised 2026-03-19 23:00 UTC)
Old tiers cut winners at 40-45% giveback — fees ate 37% of the small exits.
| Peak PnL | Keep Fraction | Giveback to trigger |
|----------|---------------|---------------------|
| $3.00+ | 60% | 40% giveback |
| $1.00+ | 50% | 50% giveback |
| $0.50+ | 40% | 60% giveback |
| < $0.50 | No protection — rides to TP or SL | |

## Bugs Fixed (2026-03-19 full audit)
| # | Severity | Bug | Fix |
|---|----------|-----|-----|
| 1 | CRITICAL | Proxy `close_position` used `position.position` (always positive) for direction — shorts could never close properly | Uses `position.sign` (1=LONG, -1=SHORT) |
| 2 | CRITICAL | News sentiment double-counted in ALL strategies: 0.5x in `get_combined_sizing()` AND 0.5x again = 0.25x | Removed news entirely from crypto sizing |
| 3 | CRITICAL | `mean_reversion.py` Neo4j feedback could block trades (`return` on 0.0) | Removed |
| 4 | CRITICAL | `mean_reversion.py` Graph AVOID could block trades | Removed |
| 5 | CRITICAL | Reconciler created fake CLOSED trades with estimated PnL — polluted ML data | Now deletes stale records instead of closing them |
| 6 | MEDIUM | `rsi_scalper.py` used `get_session_multiplier()` only, missing kelly + symbol | Uses `get_combined_sizing()` |
| 7 | MEDIUM | `entry.py` news/graph in sizing + AVOID blocking | Removed |
| 8 | MEDIUM | `momentum_entry.py` news in sizing | Removed |
| 9 | MEDIUM | `cvd_entry.py` graph AVOID blocking + graph_mult in sizing | Removed |
| 10 | MEDIUM | `close/close.py` referenced `open_price`/`sl` (don't exist on Trade model) — brain R-multiple always 0 | Uses `entry_atr * 1.8` |
| 11 | MEDIUM | `tasks.py` imported deleted `macro_analyst` — NFP/FOMC guards never ran | Removed dead import |
| 12 | MEDIUM | `mean_reversion.py` log line referenced removed `neo4j_info` variable — MR erroring every cycle | Fixed log format |
| 13 | MEDIUM | Reconciler race condition — closed positions opened <30s ago | 90s grace period added |
| 14 | LOW | `session_sizing.py` had dead BTC/ETH entries in SYMBOL_MULTIPLIERS | Cleaned up |
| 15 | LOW | `rsi_scalper.py` dead `_get_news_risk`, `_get_graph_advice`, `_record_reasoning` functions | Removed |

## Dashboard Wiring
- Pause/play button syncs: Redis `bot:crypto:paused` + proxy `_active` flag + Django cache `lighter:disabled`
- Proxy `/toggle` accepts explicit `{"active": true/false}` (idempotent, no more blind flip)
- ML page: `/v1/crypto/ml/stats/` — live training data count, WR, per-symbol breakdown, progress toward 200-trade target
- API endpoint: `/v1/crypto/lighter/trades/` — trade history from Lighter API (needs proxy restart for `/trades`)

## Position Management Flow (verified working)
1. RSI2/MR/MOM detects signal → determines side (LONG/SHORT) correctly
2. `place_market_order_usd()` → proxy → Lighter exchange
3. `place_oco_sltp()` → on-chain SL + TP orders (1:2 R:R)
4. Exit algorithm monitors: trailing stop, profit protection, time exit
5. Profit protection: $0.50+ peak required, 40-60% giveback threshold
6. On close: exit records ML features to JSONL, reconciler cancels orphaned OCO orders
7. Reconciler: syncs size/entry drift, deletes stale records (never creates fake closes)

## ML Pipeline
- **Training data:** `/app/ml_models/crypto_training_data/trades.jsonl`
- **Features recorded at entry:** rsi2, ema50, trend, funding_mult, flow_mult, session_hour, day_of_week, leverage, position_usd
- **Outcome recorded at exit:** pnl, won, close_price, close_reason, duration_min, peak_pnl
- **Dashboard:** `/ml` page shows live progress (0/200 target, per-symbol breakdown)
- **Model files on disk:** 18 stale `.joblib` files from old 22% WR strategy — DO NOT USE
- **Kelly sizing:** needs 10+ closed trades to activate
- **Target:** 200+ clean trades, then train XGBoost/LightGBM

## Grid Status
Disabled. $23 account needs full exchange order quota for RSI scalper SL/TP OCO orders.

## Known Limitations
- Proxy runs natively on macOS (Go library crashes under QEMU) — must be started manually
- Proxy launchd plist not installed — no auto-start on boot
- Container hot-patching required after code changes (`docker cp` + restart). Use `docker compose restart` NOT `docker compose up -d` (recreates containers, loses patches)
- Exchange pending order quota is global — grid disabled to free slots for SL/TP
- Fees are 0.028% taker — significant on small trades. Profit protection raised to let winners run bigger.
