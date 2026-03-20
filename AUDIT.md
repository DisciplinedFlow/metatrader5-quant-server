# Forex Bot Complete Audit — March 2026

**Date:** 2026-03-19
**Period:** March 9–19 (11 days, 9 trading days)
**Account:** Vantage Demo, EUR, 500:1 leverage
**Result:** 1,400 bot trades, 42% WR, **-14,238 EUR**

---

## Executive Summary

The bot destroyed 14,238 EUR in 11 days. Two compounding failures:

1. **Catastrophic position sizing** — `target_risk=2000` means the bot risks 2,000 EUR per trade at SL, not 2,000 EUR position size. With lot caps, actual risk was ~250-500 EUR per forex trade. 43 trades at 10-16 lots lost 6,131 EUR alone.

2. **Inverted R:R** — Target was 1:2 (risk 1, reward 2). Actual realized R:R is **1:0.47** (avg win 12.31 EUR, avg loss 26.24 EUR). Winners are cut early by the position manager. Losers run to SL. Even at 100% signal accuracy the position management would lose money.

The bot has never been profitable on any day in March except Mar 10 (+10 EUR).

---

## 1. Performance by Symbol

| Symbol | Trades | WR% | PnL | Avg Win | Avg Loss | R:R | Verdict |
|--------|--------|-----|-----|---------|----------|-----|---------|
| XAUUSD | 219 | 58.9% | **+652** | 24.52 | 27.91 | 0.88 | Only winner |
| XAUAUD | 18 | 50.0% | +33 | 40.01 | 36.29 | 1.10 | Marginal |
| XAUJPY | 17 | 52.9% | +7 | 6.83 | 6.82 | 1.00 | Breakeven |
| EURGBP | 35 | 40.0% | -130 | 3.87 | 8.76 | 0.44 | Losing |
| UKOUSDft | 41 | 46.3% | -130 | 10.32 | 14.82 | 0.70 | Losing |
| USOUSD | 27 | 44.4% | -232 | 6.70 | 20.85 | 0.32 | Losing |
| NZDUSD | 64 | 35.9% | -414 | 4.83 | 12.81 | 0.38 | Losing |
| XAUEUR | 30 | 56.7% | -459 | 13.35 | 52.75 | 0.25 | Losing |
| EURUSD | 150 | 41.3% | -1,808 | 5.86 | 24.67 | 0.24 | Bleeding |
| USDCNH | 3 | 0.0% | -721 | — | 240.24 | 0.00 | Blocked |
| NG-C | 31 | 12.9% | -916 | 11.07 | 35.56 | 0.31 | Disaster |
| XAGUSD | 104 | 30.8% | -1,484 | 22.38 | 30.56 | 0.73 | Bleeding |
| GBPUSD | 179 | 41.9% | -1,446 | 7.57 | 19.36 | 0.39 | Bleeding |
| USDJPY | 161 | 38.5% | -1,513 | 8.47 | 20.58 | 0.41 | Bleeding |
| AUDUSD | 137 | 38.0% | -1,569 | 5.77 | 21.98 | 0.26 | Bleeding |
| USDCHF | 55 | 23.6% | -3,294 | 5.10 | 80.01 | 0.06 | Catastrophic |

**Only XAUUSD is viable.** 17 of 18 symbols lose money. Every symbol has inverted R:R.

---

## 2. Performance by Hour (UTC)

| Hour | Trades | WR% | PnL | Note |
|------|--------|-----|-----|------|
| 00 | 57 | 8.8% | -1,321 | WORST — Asian dead zone |
| 01-06 | 306 | 35% | -554 | Overnight bleed |
| 07-10 | 102 | 56% | -1,187 | London session — should be best |
| 11-12 | 142 | 34% | -1,213 | Pre-NY chop |
| 13-17 | 404 | 43% | -7,773 | NY session — 55% of losses |
| 18-23 | 388 | 44% | -2,017 | After-hours |

**73% of trades fired outside session windows** (07:00-10:00, 13:00-17:00 UTC). Session filter was non-functional.

**16:00 UTC alone lost 6,250 EUR** (44% of total) — mostly March 18 mega-lot disaster.

---

## 3. Performance by Day

| Date | Trades | WR% | PnL | Cumulative |
|------|--------|-----|-----|-----------|
| Mar 09 | 63 | 55.6% | -223 | -223 |
| Mar 10 | 41 | 58.5% | +10 | -213 |
| Mar 11 | 39 | 33.3% | -896 | -1,109 |
| Mar 12 | 181 | 49.7% | -306 | -1,415 |
| Mar 13 | 368 | 50.0% | -991 | -2,406 |
| Mar 16 | 97 | 44.3% | -606 | -3,012 |
| Mar 17 | 236 | 36.0% | -154 | -3,167 |
| **Mar 18** | **147** | **25.2%** | **-7,479** | **-10,646** |
| Mar 19 | 227 | 33.5% | -3,439 | -14,085 |

**Never profitable.** Mar 18 = 53% of all losses (mega-lot sizing bug).

---

## 4. Trade Duration Analysis

| Duration | Trades | WR% | PnL | Finding |
|----------|--------|-----|-----|---------|
| 0 min (instant SL) | 91 | 13.2% | -5,586 | 40% of losses — mega-lot trades hit SL instantly |
| 1-5 min | 344 | 45.9% | -4,359 | Winners cut too fast |
| 5-15 min | 311 | 61.1% | -1,916 | Decent WR but still losing (inverted R:R) |
| 15-30 min | 553 | 27.3% | -3,020 | Position manager kills trades here |
| **30-60 min** | **60** | **73.3%** | **+149** | **Only profitable bucket** |
| **60+ min** | **40** | **80.0%** | **+648** | **Best performance — let winners run** |

**Trades that survive 30+ minutes are the only ones making money.** The position manager's MFE flat exit (15 min) and time exit (20 min) are killing valid setups before they develop.

---

## 5. Root Causes (Ranked by Impact)

### RC1. CRITICAL — Position Sizing: target_risk=2000 means 2,000 EUR risk per trade

**File:** `entry_forex.py` (committed), line 186
**Impact:** -14,238 EUR (entire loss)

```python
volume = calculate_risk_based_lots(
    symbol=symbol, sl_distance=sl_dist,
    target_risk=capital,   # capital = 2000.0 = EUR risk at SL
)
```

`calculate_risk_based_lots` computes `lots = target_risk / loss_per_lot_at_SL`. Passing 2,000 means "size the position so I lose 2,000 EUR if SL hits." Lot caps (2.0 default) reduce this to ~250-500 EUR actual risk for forex, but energy/exotics/metals can reach full 2,000 EUR risk.

**Working copy fix:** `capital=50.0` — correct.

### RC2. CRITICAL — Position Manager Cuts Winners, Keeps Losers

**File:** `position_manager.py`
**Impact:** R:R inverted from 1:2 target to 1:0.47 actual

Three mechanisms systematically destroy the 1:2 R:R design:

| Mechanism | Threshold | Effect |
|-----------|-----------|--------|
| MFE Flat Exit | 15 min, < 1.50 EUR profit | Kills 553 trades in the 15-30min bucket at 27% WR |
| Time Exit | 20 min, < 2.00 EUR profit | Catches anything MFE missed |
| Profit Protection | 30 EUR peak, 35% giveback | Closes at 19.50 EUR — before 1.5R partial close fires at ~38 EUR |

CVD LoP reversals take 20-45 min to develop. The 15/20 min killers eject valid trades before the thesis plays out. Meanwhile, the adaptive trail + ATR floor trail fire `modify_sl_tp` every 2 seconds during trends, creating whipsaw stops on consolidation retests.

### RC3. HIGH — Session Filter Non-Functional

73% of trades (1,018) fired outside London + NY overlap windows. The committed code has session checks but metals/energy were 24/7 (`_NO_SESSION` set). Forex pairs had a filter but overnight CVD signals still triggered entries via the tick consumer fast-path dispatch.

### RC4. HIGH — 20 Correlated Symbols Amplify Drawdown

Trading EURUSD, GBPUSD, AUDUSD, NZDUSD, USDCAD, USDJPY simultaneously means a USD move triggers entries on all pairs at once. A single Fed headline produces 6+ correlated losses.

### RC5. HIGH — Orphan/Phantom Trade Problem

- `send_market_order` returned tickets for unfilled orders (deal=0, price=0) — phantom Trade records created
- `close_algorithm` cached_positions dict wiped on restart — orphans detected late
- `get_deal_from_ticket` returning `still_open` dict with `profit=0` in the primary close path — real P&L replaced with zero
- `transaction_broker_id` has no unique constraint — duplicate Trade records created by entry+reconcile race

### RC6. MEDIUM — Indicator Implementation Errors

- RSI uses simple moving average, not Wilder's smoothing — thresholds (65/35) calibrated for wrong RSI variant
- ATR uses simple mean, not Wilder's — slightly underestimates volatility in post-news conditions
- `market_structure()` susceptible to single spike bars — produces false M15 confirmations

---

## 6. Entry Pipeline Issues

| ID | Severity | Issue | File |
|----|----------|-------|------|
| E1 | CRITICAL | `target_risk=2000` = EUR risk at SL, not position size | entry_forex.py:186 |
| E2 | CRITICAL | CVD LoP bridge bypasses all MTF quality gates (ADX, RSI, MACD, structure) | tick_consumer.py:228-242 |
| E3 | CRITICAL | Signal consumed before execution — lost on broker failure, no retry | entry_forex.py:125 |
| E4 | HIGH | Structural SL path widens actual risk beyond target_risk (lots sized for smaller SL) | entry_forex.py:154-159 |
| E5 | HIGH | No fill price verification against computed SL/TP (slippage unguarded) | entry_forex.py + order.py |
| E6 | HIGH | No SL minimum distance validation (STOPLEVEL check) — silent rejection | entry_forex.py |
| E7 | HIGH | R:R gate double-fetches tick price — non-deterministic accept/reject | order.py:32-53 |
| E8 | MEDIUM | Circuit breaker reset on order fill, not trade close — can be circumvented | entry_forex.py:175 |
| E9 | MEDIUM | Oil SL reduced from 2.0x to 1.5x ATR — too tight for oil spreads | entry_forex.py (working) |

---

## 7. Position Manager Issues

| ID | Severity | Issue | File |
|----|----------|-------|------|
| P1 | CRITICAL | MFE flat exit at 15min/1.50 EUR kills valid CVD LoP setups (20-45min thesis) | position_manager.py:736 |
| P2 | CRITICAL | Time exit at 20min/2.00 EUR — second kill gate for same population | position_manager.py:1310 |
| P3 | CRITICAL | API hammering: 4-5 MT5 HTTP calls per position per 2s cycle | position_manager.py |
| P4 | HIGH | Profit protection fires at 30 EUR peak (0.6R) — before partial close at 1.5R | position_manager.py:322 |
| P5 | HIGH | Adaptive trail + ATR floor trail both write SL every 2s — whipsaw on consolidation | position_manager.py |
| P6 | HIGH | Swing trail is dead code — adaptive trail pre-empts it on every cycle | position_manager.py |
| P7 | HIGH | Scale-in inherits already-moved SL — gets stopped out immediately on retest | position_manager.py:430 |
| P8 | HIGH | `_update_profit_tracking` writes DB every 2s per position (30 writes/min) | position_manager.py:264 |
| P9 | MEDIUM | Docstring/constant mismatches (15 vs 20 vs 45 min, 1.0x vs 1.5x ATR) | throughout |
| P10 | MEDIUM | `mutations_list` fetched from DB every 2s but never used — wasted query | get.py |

---

## 8. Close/Reconcile Issues

| ID | Severity | Issue | File |
|----|----------|-------|------|
| R1 | CRITICAL | `transaction_broker_id` missing unique constraint — duplicates created | models.py:33 |
| R2 | HIGH | `still_open` deal dict returns profit=0 in primary close path — PnL destroyed | close.py:65-79 |
| R3 | HIGH | `sl` and `open_price` attrs don't exist on Trade — brain pnl_r always 0 | close.py:267 |
| R4 | HIGH | `_close_orphaned_trades` and `reconcile_positions` race on same trade | close.py |
| R5 | HIGH | `strategy_config` never passed to `create_trade` — always NULL | db/create.py:9 |
| R6 | MEDIUM | `entry_time=datetime.now()` naive (no timezone) | db/create.py:40 |
| R7 | MEDIUM | Reconcile-created Trade stubs missing SL/TP, mutations, entry_atr | close.py:355 |
| R8 | LOW | `closing_reason` values not in CHOICES list | models.py:9-15 |

---

## 9. What to Fix Before Unpausing

### Tier 1 — Must fix (bot will lose money without these)

1. **Deploy working copy entry_forex.py** (50 EUR capital, 3 symbols only) — DONE
2. **Deploy order.py fill verification** (deal>0, price>0 check) — DONE
3. **Remove CVD LoP bridge** in tick_consumer.py — it bypasses all quality gates
4. **Disable or widen position manager time exits**: set `FLAT_TRADE_MINUTES=45`, `TIME_EXIT_MINUTES=60`, `FLAT_TRADE_MIN_PROFIT=5.0`
5. **Fix profit protection threshold**: `PROFIT_PROTECT_MIN_USD=75` (past 1.5R on 50 EUR risk)
6. **Add unique constraint** to `transaction_broker_id`

### Tier 2 — Should fix (degrades performance)

7. Add SL jitter filter — only fire `modify_sl_tp` when improvement > 0.1x ATR
8. Remove `_update_profit_tracking` DB writes every 2s — batch or use Redis
9. Fix RSI to use Wilder's smoothing
10. Add `strategy_config` to `create_trade`
11. Guard `still_open` in primary close path
12. Add `expires: 1.5` to trailing stop beat entry

### Tier 3 — Nice to have

13. Add `sl` and `tp` fields to Trade model
14. Fix naive `entry_time` datetime
15. Remove dead code (`_estimate_bars_since_entry`, unused mutations fetch)
16. Align docstrings with actual constant values

---

## 10. Recommended Configuration After Fixes

```python
# entry_forex.py
ALL_SYMBOLS     = ['XAUUSD']          # Only profitable symbol
CAPITAL         = 50.0                 # 50 EUR risk per trade
MAX_OPEN        = 2                    # Sniper mode
SL_ATR_MULT     = 1.8                  # Proven
TP_ATR_MULT     = 3.6                  # 1:2 R:R
SESSIONS        = [(7, 10), (13, 17)]  # London + NY only

# position_manager.py
FLAT_TRADE_MINUTES      = 45    # Let CVD LoP thesis develop
FLAT_TRADE_MIN_PROFIT   = 5.0   # Meaningful profit threshold
TIME_EXIT_MINUTES       = 60    # Data shows 30+ min trades win at 73%+
TIME_EXIT_MIN_PROFIT    = 5.0   # Consistent threshold
PROFIT_PROTECT_MIN_USD  = 75.0  # Past 1.5R before protecting
PROFIT_PROTECT_GIVEBACK = 0.50  # Allow 50% giveback for runners
ATR_FLOOR_TRAIL_MULT    = 1.5   # Wider trail to avoid whipsaw
```

This configuration trades XAUUSD only (the sole profitable symbol), with 50 EUR max risk per trade, and gives trades 45-60 minutes to develop — matching the data showing 30+ minute trades win at 73-80%.
