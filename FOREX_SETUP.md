# Forex Bot Setup — March 19, 2026

## System Overview

Four sweep-based strategies on metals + forex. All use the same core pattern: **session range forms → price sweeps the range (liquidity grab) → Market Structure Shift confirms reversal → enter with 1:2 R:R.**

No trailing stops. No position manager phases. Broker SL/TP handles all exits.

## Active Strategies

```
UTC  00  01  02  03  04  05  06  07  08  09  10  11  12  13  14  15  16  17  18  19  20  21  22  23
     ├── Asia range forming ──┤       ├─ XAUUSD TJR (H1) ──────────────────┤
                                      ├─ XAGUSD London (M15) ──┤
                                                                 ├ EURUSD ─┤
                                                                             ├── XAGUSD NY PM (M15) ──┤
```

### Strategy 1: TJR Asia Sweep — XAUUSD H1
- **Window:** 07:00–16:00 UTC
- **Range:** Asia session 00:00–05:00 UTC
- **Setup:** Price sweeps Asia high or low during London/NY → MSS (break of recent swing) → EMA50 > EMA200 trend alignment
- **SL:** 1.8x ATR | **TP:** 3.6x ATR (1:2 R:R)
- **Backtest:** 50–53% WR, PF 2.28, +0.48R/trade, 12–19 trades/290d, 3.0R max DD

### Strategy 2: London Sweep — XAGUSD M15
- **Window:** 07:00–12:00 UTC
- **Range:** Pre-London consolidation 04:00–07:00 UTC
- **Setup:** Price sweeps pre-London high or low during London open → MSS → EMA trend
- **SL:** 2.5x ATR | **TP:** 5.0x ATR (1:2 R:R)
- **Backtest:** 60–67% WR, PF 1.52, +0.88R/trade, 15 trades/290d, 2.5R max DD

### Strategy 3: NY Sweep — EURUSD M15
- **Window:** 13:00–16:00 UTC
- **Range:** London session 07:00–13:00 UTC
- **Setup:** Price sweeps London high or low during NY open → MSS
- **SL:** 1.8x ATR | **TP:** 3.6x ATR (1:2 R:R)
- **Backtest:** 62.5% WR, PF 2.94, +0.76R/trade, 16 trades/290d, 3.3R max DD

### Strategy 4: NY PM Sweep — XAGUSD M15
- **Window:** 16:00–22:00 UTC
- **Range:** London + NY AM 07:00–16:00 UTC
- **Setup:** Price sweeps day range during NY afternoon → MSS → EMA trend
- **SL:** 2.5x ATR | **TP:** 5.0x ATR (1:2 R:R)
- **Backtest:** 67–75% WR, PF 4.52, +1.16R/trade, 12 trades/290d, 1.2R max DD

## Risk Management

| Parameter | Value |
|-----------|-------|
| Risk per trade | €50 at SL |
| Max lot | 0.50 |
| Max open per symbol | 1 |
| Cooldown after entry | 1 hour per symbol |
| Circuit breaker | 3 consecutive losses → 2h pause |
| Daily loss limit | -€100 → stop trading for the day |
| Position management | Hard €50 ceiling only (safety net for gaps) |

## Execution Layer

- **Entry check:** every 60s via Celery beat
- **Position manager:** every 15s — hard loss ceiling only, no SL modifications
- **Close detection:** every 15s — detects broker SL/TP fills, updates Trade records
- **Order verification:** `deal > 0` and `price > 0` required before creating Trade record
- **Orphan handling:** phantom trades (no deals) auto-deleted, real orphans synced from MT5 deal history

## Signal Logic (All Strategies)

Every strategy follows the same three-step pattern:

1. **Range identification** — compute high/low of a prior session window
2. **Sweep detection** — check if any bar in the current session pierced below the range low (bullish) or above the range high (bearish)
3. **MSS confirmation** — current bar's close breaks above the most recent swing high (bullish) or below the most recent swing low (bearish), confirming the reversal

Additional filters:
- **Trend:** EMA50 vs EMA200 alignment (strategies 1, 2, 4)
- **Swing lookback:** 3 bars on H1, 5 bars on M15
- **ATR period:** 14 on H1, 56 on M15 (equivalent to 14 H1 bars)
- **EMA scaling:** M15 EMAs use 200/800 spans (equivalent to 50/200 on H1)

## What Changed From the Old Bot

| Aspect | Old (lost €14,238) | New |
|--------|--------------------|----|
| Symbols | 20 | 3 (XAUUSD, XAGUSD, EURUSD) |
| Risk per trade | €2,000 | €50 |
| Position management | 9 phases, SL modified every 2s | Broker SL/TP only |
| Strategy | MTF indicator crossovers | ICT sweep + MSS (structure-based) |
| Session filter | Broken (73% trades outside window) | Hard-coded per strategy |
| R:R realized | 1:0.47 (inverted) | 1:2 (target, backtested) |
| Entry signals | ADX + MACD + RSI + FVG | Session range sweep + MSS |
| Trade frequency | 1,400 trades / 11 days | ~40–60 trades / 290 days |

## File Locations

| File | Purpose |
|------|---------|
| `backend/django/app/quant/algorithms/entry_forex.py` | All 4 strategies + execution |
| `backend/django/app/quant/algorithms/position_manager.py` | Hard €50 ceiling only |
| `backend/django/app/quant/algorithms/close/close.py` | Close detection + orphan cleanup |
| `backend/django/app/utils/api/order.py` | Order execution + fill verification |
| `backend/django/app/settings.py` | Celery beat schedule |
| `backtest/` | Backtesting engine + strategy research |
| `AUDIT.md` | Full audit of the old system |

## Infrastructure

| Container | Purpose |
|-----------|---------|
| mt5 | MetaTrader 5 (Wine/Docker) — broker connection + API |
| django | REST API + trade database |
| celery | Workers — entry, position manager, close detection |
| celery-beat | Task scheduler |
| redis | Cache (signals, cooldowns, circuit breaker) |
| postgres | Trade records, strategy configs |
| dashboard | Vue 3 monitoring UI |
| traefik | HTTPS reverse proxy |

## Account

- **Broker:** Vantage International Demo
- **Currency:** EUR
- **Leverage:** 500:1
- **Balance:** ~€86,000
- **Filling mode:** IOC (ORDER_FILLING_IOC)
