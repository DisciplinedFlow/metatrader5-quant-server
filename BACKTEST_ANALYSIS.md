# CVD Lack of Participants Strategy — Backtest Analysis

Generated: 2026-03-17 03:29:22

Strategy: CVD Divergence (Lack of Participants)
- LONG: Price lower low + CVD higher low (sellers exhausted)
- SHORT: Price higher high + CVD lower high (buyers exhausted)
- CVD approximated from OHLCV: delta = volume * (2*close - high - low) / (high - low)
- Risk per trade: $50 fixed
- Default SL: 1.8x ATR(14), TP: 4.0x ATR(14)

## Cross-Symbol Summary

| Symbol | TF | Filter | Trades | WR | PnL | PF | MaxDD | Consec L |
|--------|-----|--------|--------|-----|------|------|-------|----------|
| XAGUSD | M15 | 24h | 115 | 36% | $856 | 1.23 | $844 | 12 |
| XAGUSD | M15 | 07-10 | 23 | 39% | $300 | 1.43 | $300 | 6 |
| XAGUSD | M15 | VWAP | 82 | 44% | $1,700 | 1.74 | $239 | 4 |
| XAGUSD | M15 | 07-10+VWAP | 13 | 31% | $-6 | 0.99 | $300 | 6 |
| XAGUSD | H1 | 24h | 99 | 36% | $850 | 1.27 | $561 | 9 |
| XAUUSD | H1 | 24h | 120 | 35% | $767 | 1.20 | $456 | 6 |
| EURUSD | H1 | 24h | 116 | 38% | $1,289 | 1.36 | $478 | 6 |
| USOUSD | H1 | 24h | 103 | 42% | $1,300 | 1.43 | $600 | 11 |
| XAGUSD | D1 | 24h | 213 | 39% | $2,883 | 1.45 | $1,133 | 13 |
| GBPUSD | H1 | 24h | 134 | 36% | $1,033 | 1.24 | $283 | 5 |

## Live vs Backtest Comparison

| Metric | Live (Mar 15-17) | Backtest XAGUSD M15 (24h) | Backtest XAGUSD M15 (London) |
|--------|------------------|---------------------------|------------------------------|
| Total Trades | 82 | 115 | 23 |
| Win Rate | 40.2% | 35.7% | 39.1% |
| Total PnL | $-112.61 | $855.56 | $300.00 |
| Avg Win | - | $111.11 | $111.11 |
| Avg Loss | - | $-50.00 | $-50.00 |

> **Note:** Live data covers only 2 days (Mar 15-17, 82 trades across ALL strategies and symbols).
> The backtest covers 2.5 months of XAGUSD M15 only, with no ML/confluence/circuit-breaker filters.
> Direct comparison is limited — the live system uses 10+ filter layers that the raw backtest omits.

## XAGUSD M15 (24h)

| Metric | Value |
|--------|-------|
| Data Range | 2025-12-29 15:30:00 to 2026-03-17 05:15:00 |
| Total Bars | 5,000 |
| Total Trades | 115 |
| Wins / Losses | 41 / 74 |
| Win Rate | 35.7% |
| Total PnL | $855.56 |
| Avg Win | $111.11 |
| Avg Loss | $-50.00 |
| Profit Factor | 1.23 |
| Max Drawdown | $844.44 |
| Max Consec Losses | 12 |
| Max Consec Wins | 4 |
| Avg Bars Held | 21.3 |
| Long Trades | 73 (WR: 34.2%, PnL: $377.78) |
| Short Trades | 42 (WR: 38.1%, PnL: $477.78) |

### Performance by Hour of Day

| Hour (UTC) | Trades | Wins | Win Rate | PnL |
|------------|--------|------|----------|-----|
| 01:00 | 6 | 1 | 17% | $-138.89 |
| 02:00 | 4 | 2 | 50% | $122.22 |
| 03:00 | 9 | 0 | 0% | $-450.00 |
| 04:00 | 8 | 2 | 25% | $-77.78 |
| 05:00 | 5 | 2 | 40% | $72.22 |
| 06:00 | 1 | 0 | 0% | $-50.00 |
| 07:00 | 5 | 2 | 40% | $72.22 |
| 08:00 | 1 | 1 | 100% | $111.11 |
| 09:00 | 5 | 1 | 20% | $-88.89 |
| 10:00 | 7 | 3 | 43% | $133.33 |
| 11:00 | 3 | 2 | 67% | $172.22 |
| 12:00 | 5 | 0 | 0% | $-250.00 |
| 13:00 | 4 | 2 | 50% | $122.22 |
| 14:00 | 4 | 3 | 75% | $283.33 |
| 15:00 | 4 | 0 | 0% | $-200.00 |
| 16:00 | 11 | 4 | 36% | $94.44 |
| 17:00 | 10 | 7 | 70% | $627.78 |
| 18:00 | 3 | 0 | 0% | $-150.00 |
| 19:00 | 4 | 2 | 50% | $122.22 |
| 20:00 | 5 | 3 | 60% | $233.33 |
| 21:00 | 5 | 2 | 40% | $72.22 |
| 22:00 | 5 | 2 | 40% | $72.22 |
| 23:00 | 1 | 0 | 0% | $-50.00 |

### Performance by Month

| Month | Trades | Wins | Win Rate | PnL |
|-------|--------|------|----------|-----|
| 2025-12 | 5 | 1 | 20% | $-88.89 |
| 2026-01 | 40 | 17 | 42% | $738.89 |
| 2026-02 | 49 | 14 | 29% | $-194.44 |
| 2026-03 | 21 | 9 | 43% | $400.00 |

### Performance by Day of Week

| Day | Trades | Wins | Win Rate | PnL |
|-----|--------|------|----------|-----|
| Mon | 20 | 8 | 40% | $288.89 |
| Tue | 22 | 6 | 27% | $-133.33 |
| Wed | 33 | 9 | 27% | $-200.00 |
| Thu | 23 | 8 | 35% | $138.89 |
| Fri | 17 | 10 | 59% | $761.11 |

### Performance by Volatility Regime

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 57 | 22 | 39% | $694.44 |
| Normal (ATR) | 29 | 6 | 21% | $-483.33 |
| High (ATR) | 29 | 13 | 45% | $644.44 |

## XAGUSD M15 (London 07-10)

| Metric | Value |
|--------|-------|
| Data Range | 2025-12-29 15:30:00 to 2026-03-17 05:15:00 |
| Total Bars | 5,000 |
| Total Trades | 23 |
| Wins / Losses | 9 / 14 |
| Win Rate | 39.1% |
| Total PnL | $300.00 |
| Avg Win | $111.11 |
| Avg Loss | $-50.00 |
| Profit Factor | 1.43 |
| Max Drawdown | $300.00 |
| Max Consec Losses | 6 |
| Max Consec Wins | 2 |
| Avg Bars Held | 23.2 |
| Long Trades | 12 (WR: 50.0%, PnL: $366.67) |
| Short Trades | 11 (WR: 27.3%, PnL: $-66.67) |

### Performance by Hour of Day

| Hour (UTC) | Trades | Wins | Win Rate | PnL |
|------------|--------|------|----------|-----|
| 07:00 | 13 | 6 | 46% | $316.67 |
| 08:00 | 3 | 1 | 33% | $11.11 |
| 09:00 | 7 | 2 | 29% | $-27.78 |

### Performance by Month

| Month | Trades | Wins | Win Rate | PnL |
|-------|--------|------|----------|-----|
| 2026-01 | 11 | 5 | 45% | $255.56 |
| 2026-02 | 8 | 2 | 25% | $-77.78 |
| 2026-03 | 4 | 2 | 50% | $122.22 |

### Performance by Day of Week

| Day | Trades | Wins | Win Rate | PnL |
|-----|--------|------|----------|-----|
| Mon | 4 | 3 | 75% | $283.33 |
| Tue | 7 | 2 | 29% | $-27.78 |
| Wed | 7 | 1 | 14% | $-188.89 |
| Thu | 2 | 0 | 0% | $-100.00 |
| Fri | 3 | 3 | 100% | $333.33 |

### Performance by Volatility Regime

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 11 | 6 | 55% | $416.67 |
| Normal (ATR) | 6 | 1 | 17% | $-138.89 |
| High (ATR) | 6 | 2 | 33% | $22.22 |

## XAGUSD M15 (VWAP filter)

| Metric | Value |
|--------|-------|
| Data Range | 2025-12-29 15:30:00 to 2026-03-17 05:15:00 |
| Total Bars | 5,000 |
| Total Trades | 82 |
| Wins / Losses | 36 / 46 |
| Win Rate | 43.9% |
| Total PnL | $1,700.00 |
| Avg Win | $111.11 |
| Avg Loss | $-50.00 |
| Profit Factor | 1.74 |
| Max Drawdown | $238.89 |
| Max Consec Losses | 4 |
| Max Consec Wins | 3 |
| Avg Bars Held | 23.3 |
| Long Trades | 54 (WR: 42.6%, PnL: $1,005.56) |
| Short Trades | 28 (WR: 46.4%, PnL: $694.44) |

### Performance by Hour of Day

| Hour (UTC) | Trades | Wins | Win Rate | PnL |
|------------|--------|------|----------|-----|
| 01:00 | 5 | 1 | 20% | $-88.89 |
| 02:00 | 6 | 3 | 50% | $183.33 |
| 03:00 | 2 | 2 | 100% | $222.22 |
| 04:00 | 5 | 2 | 40% | $72.22 |
| 05:00 | 6 | 3 | 50% | $183.33 |
| 06:00 | 1 | 0 | 0% | $-50.00 |
| 07:00 | 2 | 1 | 50% | $61.11 |
| 09:00 | 2 | 0 | 0% | $-100.00 |
| 10:00 | 6 | 2 | 33% | $22.22 |
| 11:00 | 2 | 1 | 50% | $61.11 |
| 12:00 | 3 | 0 | 0% | $-150.00 |
| 13:00 | 3 | 2 | 67% | $172.22 |
| 14:00 | 5 | 3 | 60% | $233.33 |
| 15:00 | 3 | 1 | 33% | $11.11 |
| 16:00 | 6 | 2 | 33% | $22.22 |
| 17:00 | 8 | 5 | 62% | $405.56 |
| 18:00 | 2 | 0 | 0% | $-100.00 |
| 19:00 | 4 | 3 | 75% | $283.33 |
| 20:00 | 6 | 3 | 50% | $183.33 |
| 21:00 | 2 | 1 | 50% | $61.11 |
| 22:00 | 3 | 1 | 33% | $11.11 |

### Performance by Month

| Month | Trades | Wins | Win Rate | PnL |
|-------|--------|------|----------|-----|
| 2025-12 | 2 | 0 | 0% | $-100.00 |
| 2026-01 | 27 | 15 | 56% | $1,066.67 |
| 2026-02 | 34 | 12 | 35% | $233.33 |
| 2026-03 | 19 | 9 | 47% | $500.00 |

### Performance by Day of Week

| Day | Trades | Wins | Win Rate | PnL |
|-----|--------|------|----------|-----|
| Mon | 14 | 8 | 57% | $588.89 |
| Tue | 12 | 5 | 42% | $205.56 |
| Wed | 26 | 9 | 35% | $150.00 |
| Thu | 14 | 6 | 43% | $266.67 |
| Fri | 16 | 8 | 50% | $488.89 |

### Performance by Volatility Regime

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 41 | 17 | 41% | $688.89 |
| Normal (ATR) | 20 | 10 | 50% | $611.11 |
| High (ATR) | 21 | 9 | 43% | $400.00 |

## XAGUSD M15 (London + VWAP)

| Metric | Value |
|--------|-------|
| Data Range | 2025-12-29 15:30:00 to 2026-03-17 05:15:00 |
| Total Bars | 5,000 |
| Total Trades | 13 |
| Wins / Losses | 4 / 9 |
| Win Rate | 30.8% |
| Total PnL | $-5.56 |
| Avg Win | $111.11 |
| Avg Loss | $-50.00 |
| Profit Factor | 0.99 |
| Max Drawdown | $300.00 |
| Max Consec Losses | 6 |
| Max Consec Wins | 1 |
| Avg Bars Held | 25.5 |
| Long Trades | 4 (WR: 25.0%, PnL: $-38.89) |
| Short Trades | 9 (WR: 33.3%, PnL: $33.33) |

### Performance by Hour of Day

| Hour (UTC) | Trades | Wins | Win Rate | PnL |
|------------|--------|------|----------|-----|
| 07:00 | 7 | 3 | 43% | $133.33 |
| 08:00 | 1 | 0 | 0% | $-50.00 |
| 09:00 | 5 | 1 | 20% | $-88.89 |

### Performance by Month

| Month | Trades | Wins | Win Rate | PnL |
|-------|--------|------|----------|-----|
| 2026-01 | 4 | 2 | 50% | $122.22 |
| 2026-02 | 5 | 0 | 0% | $-250.00 |
| 2026-03 | 4 | 2 | 50% | $122.22 |

### Performance by Day of Week

| Day | Trades | Wins | Win Rate | PnL |
|-----|--------|------|----------|-----|
| Mon | 2 | 2 | 100% | $222.22 |
| Tue | 4 | 0 | 0% | $-200.00 |
| Wed | 4 | 0 | 0% | $-200.00 |
| Thu | 1 | 0 | 0% | $-50.00 |
| Fri | 2 | 2 | 100% | $222.22 |

### Performance by Volatility Regime

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 6 | 3 | 50% | $183.33 |
| Normal (ATR) | 3 | 1 | 33% | $11.11 |
| High (ATR) | 4 | 0 | 0% | $-200.00 |

## XAGUSD H1 (24h)

| Metric | Value |
|--------|-------|
| Data Range | 2025-05-12 21:00:00 to 2026-03-17 05:00:00 |
| Total Bars | 5,000 |
| Total Trades | 99 |
| Wins / Losses | 36 / 63 |
| Win Rate | 36.4% |
| Total PnL | $850.00 |
| Avg Win | $111.11 |
| Avg Loss | $-50.00 |
| Profit Factor | 1.27 |
| Max Drawdown | $561.11 |
| Max Consec Losses | 9 |
| Max Consec Wins | 7 |
| Avg Bars Held | 24.5 |
| Long Trades | 71 (WR: 45.1%, PnL: $1,605.56) |
| Short Trades | 28 (WR: 14.3%, PnL: $-755.56) |

### Performance by Hour of Day

| Hour (UTC) | Trades | Wins | Win Rate | PnL |
|------------|--------|------|----------|-----|
| 01:00 | 3 | 1 | 33% | $11.11 |
| 02:00 | 3 | 1 | 33% | $11.11 |
| 03:00 | 2 | 1 | 50% | $61.11 |
| 04:00 | 7 | 3 | 43% | $133.33 |
| 05:00 | 2 | 1 | 50% | $61.11 |
| 06:00 | 4 | 2 | 50% | $122.22 |
| 07:00 | 5 | 2 | 40% | $72.22 |
| 08:00 | 3 | 0 | 0% | $-150.00 |
| 09:00 | 3 | 0 | 0% | $-150.00 |
| 10:00 | 5 | 3 | 60% | $233.33 |
| 11:00 | 7 | 2 | 29% | $-27.78 |
| 12:00 | 2 | 0 | 0% | $-100.00 |
| 13:00 | 2 | 1 | 50% | $61.11 |
| 15:00 | 3 | 1 | 33% | $11.11 |
| 16:00 | 8 | 3 | 38% | $83.33 |
| 17:00 | 15 | 6 | 40% | $216.67 |
| 18:00 | 9 | 3 | 33% | $33.33 |
| 19:00 | 4 | 2 | 50% | $122.22 |
| 21:00 | 5 | 2 | 40% | $72.22 |
| 22:00 | 5 | 2 | 40% | $72.22 |
| 23:00 | 2 | 0 | 0% | $-100.00 |

### Performance by Month

| Month | Trades | Wins | Win Rate | PnL |
|-------|--------|------|----------|-----|
| 2025-05 | 8 | 1 | 12% | $-238.89 |
| 2025-06 | 12 | 4 | 33% | $44.44 |
| 2025-07 | 8 | 2 | 25% | $-77.78 |
| 2025-08 | 13 | 3 | 23% | $-166.67 |
| 2025-09 | 11 | 6 | 55% | $416.67 |
| 2025-10 | 8 | 3 | 38% | $83.33 |
| 2025-11 | 12 | 6 | 50% | $366.67 |
| 2025-12 | 7 | 5 | 71% | $455.56 |
| 2026-01 | 7 | 3 | 43% | $133.33 |
| 2026-02 | 10 | 3 | 30% | $-16.67 |
| 2026-03 | 3 | 0 | 0% | $-150.00 |

### Performance by Day of Week

| Day | Trades | Wins | Win Rate | PnL |
|-----|--------|------|----------|-----|
| Mon | 24 | 10 | 42% | $411.11 |
| Tue | 26 | 12 | 46% | $633.33 |
| Wed | 16 | 3 | 19% | $-316.67 |
| Thu | 20 | 6 | 30% | $-33.33 |
| Fri | 13 | 5 | 38% | $155.56 |

### Performance by Volatility Regime

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 49 | 15 | 31% | $-33.33 |
| Normal (ATR) | 25 | 11 | 44% | $522.22 |
| High (ATR) | 25 | 10 | 40% | $361.11 |

## XAUUSD H1 (24h)

| Metric | Value |
|--------|-------|
| Data Range | 2025-05-12 20:00:00 to 2026-03-17 05:00:00 |
| Total Bars | 5,000 |
| Total Trades | 120 |
| Wins / Losses | 42 / 78 |
| Win Rate | 35.0% |
| Total PnL | $766.67 |
| Avg Win | $111.11 |
| Avg Loss | $-50.00 |
| Profit Factor | 1.20 |
| Max Drawdown | $455.56 |
| Max Consec Losses | 6 |
| Max Consec Wins | 3 |
| Avg Bars Held | 20.3 |
| Long Trades | 69 (WR: 42.0%, PnL: $1,222.22) |
| Short Trades | 51 (WR: 25.5%, PnL: $-455.56) |

### Performance by Hour of Day

| Hour (UTC) | Trades | Wins | Win Rate | PnL |
|------------|--------|------|----------|-----|
| 01:00 | 5 | 2 | 40% | $72.22 |
| 02:00 | 5 | 1 | 20% | $-88.89 |
| 03:00 | 4 | 2 | 50% | $122.22 |
| 04:00 | 12 | 4 | 33% | $44.44 |
| 05:00 | 5 | 1 | 20% | $-88.89 |
| 06:00 | 2 | 0 | 0% | $-100.00 |
| 07:00 | 3 | 2 | 67% | $172.22 |
| 08:00 | 7 | 1 | 14% | $-188.89 |
| 09:00 | 1 | 0 | 0% | $-50.00 |
| 10:00 | 6 | 3 | 50% | $183.33 |
| 11:00 | 5 | 4 | 80% | $394.44 |
| 12:00 | 5 | 0 | 0% | $-250.00 |
| 13:00 | 5 | 4 | 80% | $394.44 |
| 14:00 | 2 | 1 | 50% | $61.11 |
| 15:00 | 6 | 2 | 33% | $22.22 |
| 16:00 | 9 | 4 | 44% | $194.44 |
| 17:00 | 7 | 2 | 29% | $-27.78 |
| 18:00 | 6 | 3 | 50% | $183.33 |
| 19:00 | 5 | 2 | 40% | $72.22 |
| 20:00 | 2 | 0 | 0% | $-100.00 |
| 21:00 | 5 | 1 | 20% | $-88.89 |
| 22:00 | 8 | 2 | 25% | $-77.78 |
| 23:00 | 5 | 1 | 20% | $-88.89 |

### Performance by Month

| Month | Trades | Wins | Win Rate | PnL |
|-------|--------|------|----------|-----|
| 2025-05 | 8 | 4 | 50% | $244.44 |
| 2025-06 | 11 | 4 | 36% | $94.44 |
| 2025-07 | 14 | 7 | 50% | $427.78 |
| 2025-08 | 13 | 4 | 31% | $-5.56 |
| 2025-09 | 15 | 3 | 20% | $-266.67 |
| 2025-10 | 11 | 4 | 36% | $94.44 |
| 2025-11 | 10 | 2 | 20% | $-177.78 |
| 2025-12 | 12 | 6 | 50% | $366.67 |
| 2026-01 | 9 | 3 | 33% | $33.33 |
| 2026-02 | 15 | 4 | 27% | $-105.56 |
| 2026-03 | 2 | 1 | 50% | $61.11 |

### Performance by Day of Week

| Day | Trades | Wins | Win Rate | PnL |
|-----|--------|------|----------|-----|
| Mon | 19 | 5 | 26% | $-144.44 |
| Tue | 28 | 8 | 29% | $-111.11 |
| Wed | 24 | 8 | 33% | $88.89 |
| Thu | 28 | 10 | 36% | $211.11 |
| Fri | 21 | 11 | 52% | $722.22 |

### Performance by Volatility Regime

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 60 | 21 | 35% | $383.33 |
| Normal (ATR) | 30 | 10 | 33% | $111.11 |
| High (ATR) | 30 | 11 | 37% | $272.22 |

## EURUSD H1 (24h)

| Metric | Value |
|--------|-------|
| Data Range | 2025-05-26 22:00:00 to 2026-03-17 05:00:00 |
| Total Bars | 5,000 |
| Total Trades | 116 |
| Wins / Losses | 44 / 72 |
| Win Rate | 37.9% |
| Total PnL | $1,288.89 |
| Avg Win | $111.11 |
| Avg Loss | $-50.00 |
| Profit Factor | 1.36 |
| Max Drawdown | $477.78 |
| Max Consec Losses | 6 |
| Max Consec Wins | 4 |
| Avg Bars Held | 22.8 |
| Long Trades | 60 (WR: 33.3%, PnL: $222.22) |
| Short Trades | 56 (WR: 42.9%, PnL: $1,066.67) |

### Performance by Hour of Day

| Hour (UTC) | Trades | Wins | Win Rate | PnL |
|------------|--------|------|----------|-----|
| 00:00 | 4 | 2 | 50% | $122.22 |
| 01:00 | 4 | 2 | 50% | $122.22 |
| 02:00 | 3 | 2 | 67% | $172.22 |
| 03:00 | 7 | 4 | 57% | $294.44 |
| 04:00 | 7 | 3 | 43% | $133.33 |
| 05:00 | 4 | 2 | 50% | $122.22 |
| 06:00 | 1 | 0 | 0% | $-50.00 |
| 07:00 | 2 | 1 | 50% | $61.11 |
| 08:00 | 3 | 2 | 67% | $172.22 |
| 09:00 | 5 | 3 | 60% | $233.33 |
| 10:00 | 1 | 0 | 0% | $-50.00 |
| 11:00 | 5 | 0 | 0% | $-250.00 |
| 12:00 | 3 | 1 | 33% | $11.11 |
| 13:00 | 3 | 0 | 0% | $-150.00 |
| 14:00 | 3 | 2 | 67% | $172.22 |
| 15:00 | 10 | 1 | 10% | $-338.89 |
| 16:00 | 12 | 4 | 33% | $44.44 |
| 17:00 | 8 | 5 | 62% | $405.56 |
| 18:00 | 8 | 4 | 50% | $244.44 |
| 19:00 | 9 | 2 | 22% | $-127.78 |
| 20:00 | 8 | 2 | 25% | $-77.78 |
| 21:00 | 3 | 1 | 33% | $11.11 |
| 22:00 | 2 | 1 | 50% | $61.11 |
| 23:00 | 1 | 0 | 0% | $-50.00 |

### Performance by Month

| Month | Trades | Wins | Win Rate | PnL |
|-------|--------|------|----------|-----|
| 2025-05 | 3 | 2 | 67% | $172.22 |
| 2025-06 | 16 | 5 | 31% | $5.56 |
| 2025-07 | 11 | 6 | 55% | $416.67 |
| 2025-08 | 9 | 2 | 22% | $-127.78 |
| 2025-09 | 10 | 3 | 30% | $-16.67 |
| 2025-10 | 10 | 2 | 20% | $-177.78 |
| 2025-11 | 11 | 5 | 45% | $255.56 |
| 2025-12 | 15 | 5 | 33% | $55.56 |
| 2026-01 | 16 | 7 | 44% | $327.78 |
| 2026-02 | 7 | 3 | 43% | $133.33 |
| 2026-03 | 8 | 4 | 50% | $244.44 |

### Performance by Day of Week

| Day | Trades | Wins | Win Rate | PnL |
|-----|--------|------|----------|-----|
| Mon | 22 | 9 | 41% | $350.00 |
| Tue | 27 | 10 | 37% | $261.11 |
| Wed | 16 | 8 | 50% | $488.89 |
| Thu | 27 | 8 | 30% | $-61.11 |
| Fri | 24 | 9 | 38% | $250.00 |

### Performance by Volatility Regime

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 58 | 21 | 36% | $483.33 |
| Normal (ATR) | 29 | 10 | 34% | $161.11 |
| High (ATR) | 29 | 13 | 45% | $644.44 |

## USOUSD H1 (energy params)

| Metric | Value |
|--------|-------|
| Data Range | 2025-05-12 13:00:00 to 2026-03-17 05:00:00 |
| Total Bars | 5,000 |
| Total Trades | 103 |
| Wins / Losses | 43 / 60 |
| Win Rate | 41.7% |
| Total PnL | $1,300.00 |
| Avg Win | $100.00 |
| Avg Loss | $-50.00 |
| Profit Factor | 1.43 |
| Max Drawdown | $600.00 |
| Max Consec Losses | 11 |
| Max Consec Wins | 6 |
| Avg Bars Held | 26.2 |
| Long Trades | 54 (WR: 46.3%, PnL: $1,050.00) |
| Short Trades | 49 (WR: 36.7%, PnL: $250.00) |

### Performance by Hour of Day

| Hour (UTC) | Trades | Wins | Win Rate | PnL |
|------------|--------|------|----------|-----|
| 01:00 | 2 | 1 | 50% | $50.00 |
| 02:00 | 8 | 5 | 62% | $350.00 |
| 03:00 | 3 | 2 | 67% | $150.00 |
| 04:00 | 6 | 5 | 83% | $450.00 |
| 05:00 | 3 | 1 | 33% | $-0.00 |
| 06:00 | 5 | 0 | 0% | $-250.00 |
| 07:00 | 3 | 1 | 33% | $0.00 |
| 08:00 | 6 | 2 | 33% | $-0.00 |
| 09:00 | 3 | 1 | 33% | $-0.00 |
| 10:00 | 3 | 1 | 33% | $0.00 |
| 11:00 | 5 | 4 | 80% | $350.00 |
| 12:00 | 3 | 1 | 33% | $0.00 |
| 13:00 | 2 | 1 | 50% | $50.00 |
| 14:00 | 2 | 1 | 50% | $50.00 |
| 15:00 | 5 | 3 | 60% | $200.00 |
| 16:00 | 9 | 2 | 22% | $-150.00 |
| 17:00 | 5 | 0 | 0% | $-250.00 |
| 18:00 | 7 | 2 | 29% | $-50.00 |
| 19:00 | 4 | 2 | 50% | $100.00 |
| 20:00 | 4 | 2 | 50% | $100.00 |
| 21:00 | 5 | 2 | 40% | $50.00 |
| 22:00 | 5 | 3 | 60% | $200.00 |
| 23:00 | 5 | 1 | 20% | $-100.00 |

### Performance by Month

| Month | Trades | Wins | Win Rate | PnL |
|-------|--------|------|----------|-----|
| 2025-05 | 5 | 2 | 40% | $50.00 |
| 2025-06 | 7 | 5 | 71% | $400.00 |
| 2025-07 | 16 | 2 | 12% | $-500.00 |
| 2025-08 | 9 | 3 | 33% | $-0.00 |
| 2025-09 | 10 | 5 | 50% | $250.00 |
| 2025-10 | 13 | 4 | 31% | $-50.00 |
| 2025-11 | 9 | 3 | 33% | $-0.00 |
| 2025-12 | 14 | 7 | 50% | $350.00 |
| 2026-01 | 7 | 3 | 43% | $100.00 |
| 2026-02 | 9 | 7 | 78% | $600.00 |
| 2026-03 | 4 | 2 | 50% | $100.00 |

### Performance by Day of Week

| Day | Trades | Wins | Win Rate | PnL |
|-----|--------|------|----------|-----|
| Mon | 27 | 12 | 44% | $450.00 |
| Tue | 17 | 8 | 47% | $350.00 |
| Wed | 22 | 8 | 36% | $100.00 |
| Thu | 19 | 7 | 37% | $100.00 |
| Fri | 18 | 8 | 44% | $300.00 |

### Performance by Volatility Regime

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 51 | 20 | 39% | $450.00 |
| Normal (ATR) | 26 | 9 | 35% | $50.00 |
| High (ATR) | 26 | 14 | 54% | $800.00 |

## XAGUSD D1 (25 years)

| Metric | Value |
|--------|-------|
| Data Range | 2000-08-30 00:00:00 to 2026-03-16 00:00:00 |
| Total Bars | 6,410 |
| Total Trades | 213 |
| Wins / Losses | 84 / 129 |
| Win Rate | 39.4% |
| Total PnL | $2,883.33 |
| Avg Win | $111.11 |
| Avg Loss | $-50.00 |
| Profit Factor | 1.45 |
| Max Drawdown | $1,133.33 |
| Max Consec Losses | 13 |
| Max Consec Wins | 5 |
| Avg Bars Held | 15.0 |
| Long Trades | 103 (WR: 48.5%, PnL: $2,905.56) |
| Short Trades | 110 (WR: 30.9%, PnL: $-22.22) |

### Performance by Month

| Month | Trades | Wins | Win Rate | PnL |
|-------|--------|------|----------|-----|
| 2001-01 | 1 | 1 | 100% | $111.11 |
| 2001-03 | 1 | 1 | 100% | $111.11 |
| 2001-05 | 1 | 1 | 100% | $111.11 |
| 2001-09 | 1 | 0 | 0% | $-50.00 |
| 2002-03 | 2 | 0 | 0% | $-100.00 |
| 2002-06 | 1 | 0 | 0% | $-50.00 |
| 2002-09 | 1 | 1 | 100% | $111.11 |
| 2002-12 | 1 | 0 | 0% | $-50.00 |
| 2003-05 | 3 | 1 | 33% | $11.11 |
| 2003-07 | 2 | 0 | 0% | $-100.00 |
| 2003-09 | 1 | 1 | 100% | $111.11 |
| 2003-10 | 1 | 0 | 0% | $-50.00 |
| 2003-11 | 1 | 0 | 0% | $-50.00 |
| 2003-12 | 1 | 0 | 0% | $-50.00 |
| 2004-02 | 1 | 1 | 100% | $111.11 |
| 2004-03 | 2 | 0 | 0% | $-100.00 |
| 2004-04 | 2 | 1 | 50% | $61.11 |
| 2004-05 | 1 | 1 | 100% | $111.11 |
| 2004-07 | 1 | 0 | 0% | $-50.00 |
| 2004-12 | 1 | 0 | 0% | $-50.00 |
| 2005-03 | 1 | 1 | 100% | $111.11 |
| 2005-05 | 1 | 1 | 100% | $111.11 |
| 2005-06 | 1 | 1 | 100% | $111.11 |
| 2005-07 | 2 | 1 | 50% | $61.11 |
| 2005-08 | 1 | 1 | 100% | $111.11 |
| 2005-09 | 1 | 0 | 0% | $-50.00 |
| 2005-11 | 1 | 1 | 100% | $111.11 |
| 2006-01 | 1 | 1 | 100% | $111.11 |
| 2006-02 | 1 | 0 | 0% | $-50.00 |
| 2006-05 | 1 | 1 | 100% | $111.11 |
| 2006-06 | 1 | 1 | 100% | $111.11 |
| 2006-09 | 1 | 1 | 100% | $111.11 |
| 2006-12 | 2 | 2 | 100% | $222.22 |
| 2007-03 | 1 | 0 | 0% | $-50.00 |
| 2007-08 | 1 | 0 | 0% | $-50.00 |
| 2007-10 | 1 | 0 | 0% | $-50.00 |
| 2007-11 | 1 | 1 | 100% | $111.11 |
| 2007-12 | 1 | 1 | 100% | $111.11 |
| 2008-02 | 1 | 0 | 0% | $-50.00 |
| 2008-04 | 1 | 0 | 0% | $-50.00 |
| 2008-09 | 1 | 0 | 0% | $-50.00 |
| 2008-11 | 2 | 1 | 50% | $61.11 |
| 2008-12 | 1 | 0 | 0% | $-50.00 |
| 2009-01 | 1 | 0 | 0% | $-50.00 |
| 2009-02 | 2 | 1 | 50% | $61.11 |
| 2009-03 | 1 | 0 | 0% | $-50.00 |
| 2009-04 | 2 | 1 | 50% | $61.11 |
| 2009-05 | 2 | 0 | 0% | $-100.00 |
| 2009-06 | 1 | 0 | 0% | $-50.00 |
| 2009-08 | 1 | 0 | 0% | $-50.00 |
| 2009-12 | 1 | 0 | 0% | $-50.00 |
| 2010-01 | 1 | 0 | 0% | $-50.00 |
| 2010-03 | 1 | 0 | 0% | $-50.00 |
| 2010-04 | 2 | 0 | 0% | $-100.00 |
| 2010-05 | 3 | 1 | 33% | $11.11 |
| 2010-07 | 1 | 1 | 100% | $111.11 |
| 2011-03 | 2 | 0 | 0% | $-100.00 |
| 2011-05 | 1 | 0 | 0% | $-50.00 |
| 2011-09 | 1 | 0 | 0% | $-50.00 |
| 2012-01 | 3 | 0 | 0% | $-150.00 |
| 2012-03 | 2 | 0 | 0% | $-100.00 |
| 2012-05 | 4 | 0 | 0% | $-200.00 |
| 2012-07 | 1 | 1 | 100% | $111.11 |
| 2012-10 | 3 | 0 | 0% | $-150.00 |
| 2012-11 | 2 | 1 | 50% | $61.11 |
| 2013-01 | 1 | 1 | 100% | $111.11 |
| 2013-04 | 1 | 1 | 100% | $111.11 |
| 2013-05 | 1 | 0 | 0% | $-50.00 |
| 2013-06 | 2 | 1 | 50% | $61.11 |
| 2013-09 | 1 | 1 | 100% | $111.11 |
| 2013-10 | 1 | 0 | 0% | $-50.00 |
| 2013-11 | 1 | 0 | 0% | $-50.00 |
| 2014-02 | 1 | 1 | 100% | $111.11 |
| 2014-03 | 2 | 0 | 0% | $-100.00 |
| 2014-07 | 2 | 1 | 50% | $61.11 |
| 2014-11 | 1 | 1 | 100% | $111.11 |
| 2014-12 | 1 | 1 | 100% | $111.11 |
| 2015-04 | 1 | 0 | 0% | $-50.00 |
| 2015-07 | 2 | 0 | 0% | $-100.00 |
| 2015-08 | 1 | 1 | 100% | $111.11 |
| 2015-12 | 1 | 0 | 0% | $-50.00 |
| 2016-02 | 1 | 0 | 0% | $-50.00 |
| 2016-03 | 2 | 0 | 0% | $-100.00 |
| 2016-06 | 2 | 2 | 100% | $222.22 |
| 2016-07 | 2 | 1 | 50% | $61.11 |
| 2016-12 | 2 | 1 | 50% | $61.11 |
| 2017-02 | 3 | 1 | 33% | $11.11 |
| 2017-03 | 1 | 1 | 100% | $111.11 |
| 2017-04 | 3 | 1 | 33% | $11.11 |
| 2017-05 | 1 | 0 | 0% | $-50.00 |
| 2017-07 | 1 | 1 | 100% | $111.11 |
| 2017-11 | 1 | 1 | 100% | $111.11 |
| 2018-01 | 1 | 1 | 100% | $111.11 |
| 2018-02 | 2 | 1 | 50% | $61.11 |
| 2018-05 | 1 | 0 | 0% | $-50.00 |
| 2018-07 | 2 | 0 | 0% | $-100.00 |
| 2018-08 | 1 | 0 | 0% | $-50.00 |
| 2018-09 | 1 | 1 | 100% | $111.11 |
| 2019-02 | 2 | 1 | 50% | $61.11 |
| 2019-03 | 1 | 0 | 0% | $-50.00 |
| 2019-04 | 1 | 1 | 100% | $111.11 |
| 2019-05 | 1 | 1 | 100% | $111.11 |
| 2019-06 | 1 | 1 | 100% | $111.11 |
| 2019-09 | 1 | 1 | 100% | $111.11 |
| 2019-10 | 1 | 0 | 0% | $-50.00 |
| 2019-11 | 1 | 1 | 100% | $111.11 |
| 2020-01 | 1 | 0 | 0% | $-50.00 |
| 2020-04 | 1 | 0 | 0% | $-50.00 |
| 2020-05 | 2 | 2 | 100% | $222.22 |
| 2020-06 | 1 | 0 | 0% | $-50.00 |
| 2020-09 | 2 | 0 | 0% | $-100.00 |
| 2020-10 | 1 | 1 | 100% | $111.11 |
| 2020-12 | 1 | 0 | 0% | $-50.00 |
| 2021-01 | 1 | 0 | 0% | $-50.00 |
| 2021-03 | 1 | 0 | 0% | $-50.00 |
| 2021-05 | 1 | 1 | 100% | $111.11 |
| 2021-06 | 1 | 0 | 0% | $-50.00 |
| 2021-08 | 1 | 0 | 0% | $-50.00 |
| 2021-09 | 1 | 0 | 0% | $-50.00 |
| 2021-10 | 1 | 1 | 100% | $111.11 |
| 2022-01 | 2 | 1 | 50% | $61.11 |
| 2022-03 | 1 | 1 | 100% | $111.11 |
| 2022-05 | 1 | 0 | 0% | $-50.00 |
| 2022-06 | 1 | 1 | 100% | $111.11 |
| 2022-08 | 2 | 2 | 100% | $222.22 |
| 2022-09 | 3 | 1 | 33% | $11.11 |
| 2022-10 | 2 | 0 | 0% | $-100.00 |
| 2022-12 | 1 | 1 | 100% | $111.11 |
| 2023-02 | 1 | 1 | 100% | $111.11 |
| 2023-03 | 2 | 2 | 100% | $222.22 |
| 2023-05 | 2 | 1 | 50% | $61.11 |
| 2023-07 | 1 | 0 | 0% | $-50.00 |
| 2023-10 | 2 | 1 | 50% | $61.11 |
| 2023-11 | 1 | 1 | 100% | $111.11 |
| 2023-12 | 1 | 0 | 0% | $-50.00 |
| 2024-01 | 1 | 0 | 0% | $-50.00 |
| 2024-03 | 3 | 0 | 0% | $-150.00 |
| 2024-04 | 2 | 0 | 0% | $-100.00 |
| 2024-05 | 1 | 1 | 100% | $111.11 |
| 2024-07 | 1 | 0 | 0% | $-50.00 |
| 2024-09 | 3 | 1 | 33% | $11.11 |
| 2024-10 | 2 | 1 | 50% | $61.11 |
| 2024-11 | 1 | 0 | 0% | $-50.00 |
| 2024-12 | 1 | 1 | 100% | $111.11 |
| 2025-05 | 1 | 1 | 100% | $111.11 |
| 2025-06 | 1 | 1 | 100% | $111.11 |
| 2025-07 | 2 | 1 | 50% | $61.11 |
| 2025-08 | 4 | 0 | 0% | $-200.00 |
| 2025-09 | 1 | 1 | 100% | $111.11 |
| 2025-11 | 2 | 1 | 50% | $61.11 |
| 2026-01 | 2 | 0 | 0% | $-100.00 |

### Performance by Volatility Regime

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 106 | 45 | 42% | $1,950.00 |
| Normal (ATR) | 53 | 22 | 42% | $894.44 |
| High (ATR) | 54 | 17 | 31% | $38.89 |

## GBPUSD H1 (24h)

| Metric | Value |
|--------|-------|
| Data Range | 2025-05-26 22:00:00 to 2026-03-17 05:00:00 |
| Total Bars | 5,000 |
| Total Trades | 134 |
| Wins / Losses | 48 / 86 |
| Win Rate | 35.8% |
| Total PnL | $1,033.33 |
| Avg Win | $111.11 |
| Avg Loss | $-50.00 |
| Profit Factor | 1.24 |
| Max Drawdown | $283.33 |
| Max Consec Losses | 5 |
| Max Consec Wins | 3 |
| Avg Bars Held | 18.9 |
| Long Trades | 67 (WR: 32.8%, PnL: $194.44) |
| Short Trades | 67 (WR: 38.8%, PnL: $838.89) |

### Performance by Hour of Day

| Hour (UTC) | Trades | Wins | Win Rate | PnL |
|------------|--------|------|----------|-----|
| 00:00 | 3 | 2 | 67% | $172.22 |
| 01:00 | 5 | 1 | 20% | $-88.89 |
| 02:00 | 3 | 0 | 0% | $-150.00 |
| 03:00 | 6 | 2 | 33% | $22.22 |
| 04:00 | 6 | 3 | 50% | $183.33 |
| 05:00 | 5 | 1 | 20% | $-88.89 |
| 06:00 | 4 | 1 | 25% | $-38.89 |
| 07:00 | 1 | 0 | 0% | $-50.00 |
| 08:00 | 5 | 1 | 20% | $-88.89 |
| 09:00 | 7 | 1 | 14% | $-188.89 |
| 10:00 | 5 | 2 | 40% | $72.22 |
| 11:00 | 4 | 1 | 25% | $-38.89 |
| 12:00 | 6 | 4 | 67% | $344.44 |
| 13:00 | 6 | 3 | 50% | $183.33 |
| 14:00 | 3 | 2 | 67% | $172.22 |
| 15:00 | 5 | 2 | 40% | $72.22 |
| 16:00 | 9 | 5 | 56% | $355.56 |
| 17:00 | 14 | 5 | 36% | $105.56 |
| 18:00 | 11 | 4 | 36% | $94.44 |
| 19:00 | 6 | 3 | 50% | $183.33 |
| 20:00 | 3 | 1 | 33% | $11.11 |
| 21:00 | 5 | 3 | 60% | $233.33 |
| 22:00 | 9 | 1 | 11% | $-288.89 |
| 23:00 | 3 | 0 | 0% | $-150.00 |

### Performance by Month

| Month | Trades | Wins | Win Rate | PnL |
|-------|--------|------|----------|-----|
| 2025-05 | 1 | 0 | 0% | $-50.00 |
| 2025-06 | 17 | 5 | 29% | $-44.44 |
| 2025-07 | 16 | 6 | 38% | $166.67 |
| 2025-08 | 13 | 4 | 31% | $-5.56 |
| 2025-09 | 11 | 4 | 36% | $94.44 |
| 2025-10 | 13 | 5 | 38% | $155.56 |
| 2025-11 | 15 | 5 | 33% | $55.56 |
| 2025-12 | 10 | 6 | 60% | $466.67 |
| 2026-01 | 18 | 5 | 28% | $-94.44 |
| 2026-02 | 12 | 4 | 33% | $44.44 |
| 2026-03 | 8 | 4 | 50% | $244.44 |

### Performance by Day of Week

| Day | Trades | Wins | Win Rate | PnL |
|-----|--------|------|----------|-----|
| Mon | 32 | 11 | 34% | $172.22 |
| Tue | 21 | 5 | 24% | $-244.44 |
| Wed | 26 | 16 | 62% | $1,277.78 |
| Thu | 28 | 7 | 25% | $-272.22 |
| Fri | 27 | 9 | 33% | $100.00 |

### Performance by Volatility Regime

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 67 | 24 | 36% | $516.67 |
| Normal (ATR) | 33 | 12 | 36% | $283.33 |
| High (ATR) | 34 | 12 | 35% | $233.33 |

## London Open Filter Impact (XAGUSD M15)

| Metric | 24h (No Filter) | London Open (07-10) | VWAP Only | London + VWAP |
|--------|-----------------|---------------------|-----------|---------------|
| Trades | 115 | 23 | 82 | 13 |
| Win Rate | 35.7% | 39.1% | 43.9% | 30.8% |
| Total PnL | $855.56 | $300.00 | $1,700.00 | $-5.56 |
| Profit Factor | 1.23 | 1.43 | 1.74 | 0.99 |
| Max Drawdown | $844.44 | $300.00 | $238.89 | $300.00 |
| Max Consec Loss | 12 | 6 | 4 | 6 |

## Parameter Sensitivity (XAGUSD M15)

| SL/TP Config | Trades | WR | PnL | PF | MaxDD |
|--------------|--------|-----|-----|-----|-------|
| 1.2/2.4 (tight) | 199 | 42% | $2,650 | 1.46 | $1,000 |
| 1.5/3.0 | 151 | 34% | $250 | 1.05 | $1,250 |
| 1.8/3.6 (default) | 118 | 37% | $700 | 1.19 | $900 |
| 1.8/4.0 (London TP) | 115 | 36% | $856 | 1.23 | $844 |
| 2.0/4.0 (energy) | 108 | 41% | $1,200 | 1.38 | $400 |
| 2.0/6.0 (wide TP) | 79 | 32% | $1,050 | 1.39 | $550 |
| 2.5/5.0 (very wide) | 81 | 41% | $900 | 1.38 | $550 |

## Optimal Time Windows (XAGUSD M15, 3-hour windows)

Top 10 windows by PnL:

| Window (UTC) | Trades | WR | PnL | PF |
|--------------|--------|----|-----|-----|
| 15:00-18:00 | 45 | 42% | $811 | 1.62 |
| 18:00-21:00 | 27 | 48% | $744 | 2.06 |
| 19:00-22:00 | 27 | 48% | $744 | 2.06 |
| 17:00-20:00 | 32 | 44% | $656 | 1.73 |
| 20:00-23:00 | 30 | 40% | $433 | 1.48 |
| 12:00-15:00 | 27 | 41% | $422 | 1.53 |
| 21:00-00:00 | 25 | 40% | $361 | 1.48 |
| 09:00-12:00 | 25 | 40% | $361 | 1.48 |
| 07:00-10:00 | 23 | 39% | $300 | 1.43 |
| 22:00-01:00 | 18 | 39% | $228 | 1.41 |

Bottom 5 windows by PnL:

| Window (UTC) | Trades | WR | PnL | PF |
|--------------|--------|----|-----|-----|
| 23:00-02:00 | 19 | 26% | $-144 | 0.79 |
| 03:00-06:00 | 32 | 28% | $-150 | 0.87 |
| 02:00-05:00 | 34 | 26% | $-250 | 0.80 |
| 00:00-03:00 | 22 | 23% | $-294 | 0.65 |
| 01:00-04:00 | 34 | 24% | $-411 | 0.68 |

## Volatility Regime Correlation

Analysis of trade performance clustered by ATR regime at entry time.
ATR is split into low (<median), normal (median-P75), high (>P75).

### XAGUSD M15 (24h)

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 57 | 22 | 39% | $694.44 |
| Normal (ATR) | 29 | 6 | 21% | $-483.33 |
| High (ATR) | 29 | 13 | 45% | $644.44 |

### XAGUSD M15 (London 07-10)

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 11 | 6 | 55% | $416.67 |
| Normal (ATR) | 6 | 1 | 17% | $-138.89 |
| High (ATR) | 6 | 2 | 33% | $22.22 |

### XAGUSD M15 (VWAP filter)

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 41 | 17 | 41% | $688.89 |
| Normal (ATR) | 20 | 10 | 50% | $611.11 |
| High (ATR) | 21 | 9 | 43% | $400.00 |

### XAGUSD M15 (London + VWAP)

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 6 | 3 | 50% | $183.33 |
| Normal (ATR) | 3 | 1 | 33% | $11.11 |
| High (ATR) | 4 | 0 | 0% | $-200.00 |

### XAGUSD H1 (24h)

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 49 | 15 | 31% | $-33.33 |
| Normal (ATR) | 25 | 11 | 44% | $522.22 |
| High (ATR) | 25 | 10 | 40% | $361.11 |

### XAUUSD H1 (24h)

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 60 | 21 | 35% | $383.33 |
| Normal (ATR) | 30 | 10 | 33% | $111.11 |
| High (ATR) | 30 | 11 | 37% | $272.22 |

### EURUSD H1 (24h)

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 58 | 21 | 36% | $483.33 |
| Normal (ATR) | 29 | 10 | 34% | $161.11 |
| High (ATR) | 29 | 13 | 45% | $644.44 |

### USOUSD H1 (energy params)

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 51 | 20 | 39% | $450.00 |
| Normal (ATR) | 26 | 9 | 35% | $50.00 |
| High (ATR) | 26 | 14 | 54% | $800.00 |

### XAGUSD D1 (25 years)

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 106 | 45 | 42% | $1,950.00 |
| Normal (ATR) | 53 | 22 | 42% | $894.44 |
| High (ATR) | 54 | 17 | 31% | $38.89 |

### GBPUSD H1 (24h)

| Volatility Regime | Trades | Wins | Win Rate | PnL |
|-------------------|--------|------|----------|-----|
| Low (ATR) | 67 | 24 | 36% | $516.67 |
| Normal (ATR) | 33 | 12 | 36% | $283.33 |
| High (ATR) | 34 | 12 | 35% | $233.33 |


## Key Findings

1. **Best performer:** XAGUSD D1 (24h filter) with 213 trades, 39% WR, $2,883 PnL
2. **London Open filter:** Improved win rate by 3.5% (36% -> 39%). PnL went from $856 to $300.
3. **VWAP filter:** 82 trades vs 115 unfiltered. WR: 44% vs 36%. PnL: $1,700 vs $856.
4. **Best time window:** 15:00-18:00 UTC (45 trades, 42% WR, $811 PnL)
6. **Direction bias (XAGUSD M15):** Longs: 73 trades, 34% WR, $378 PnL | Shorts: 42 trades, 38% WR, $478 PnL
7. **Best SL/TP config:** 1.2/2.4 (tight) — 199 trades, 42% WR, $2,650 PnL

## Recommendations

Based on backtest results:

1. **CVD divergence alone has a sub-40% win rate.** This is expected for a mean-reversion signal using approximated CVD from bar data. The live system's 10+ filter layers (ML, confluence scoring, circuit breakers, regime detection) are essential — do NOT trade CVD divergence without them.
2. **SL/TP tuning:** Test the best-performing parameter set on out-of-sample data before changing live config. The R:R ratio has outsized impact on total PnL when WR is near 50%.
3. **Time filter:** Consider restricting signals to 15:00-18:00 UTC which showed the best PnL in the scan. Verify on other symbols before deploying.
4. **Volatility regimes matter.** Consider reducing position size or skipping signals during extreme ATR spikes (>P75). The high-vol regime often produces larger losses that wipe out gains from normal conditions.
5. **Live performance gap:** The live system's -$112 over 82 trades likely reflects the cost of learning (circuit breakers, regime mismatches, spread/slippage). The backtest does not account for spreads (~2-5 pips on XAGUSD), commission, or order execution latency — real edge is ~$2-5/trade lower than shown.
6. **Next steps:** (a) Run this backtest with spread deduction ($2-5/trade), (b) Add ICT 5-step confirmation filter, (c) Test on walk-forward splits (train 70% / test 30%), (d) Compare CVD divergence signal rate vs actual live signal rate to calibrate lookback params.

## Methodology Notes

- **CVD approximation:** Volume delta = volume * (2*close - high - low) / (high - low). 
  This is the same formula used in the live `indicators/cvd.py` module.
- **Swing detection:** lookback=3 bars either side (matching live min(swing_lookback, lookback//4, 3))
- **Signal detection:** Exact match of live `cvd_divergence()` logic — bearish checked first per bar
- **Position sizing:** Fixed $50 risk, lot_size = $50 / (SL_pips * tick_value)
- **Trade management:** Simple SL/TP only — no trailing stop, no partial close, no breakeven
- **No spread/commission deduction** — results are gross, not net
- **One trade at a time** — no overlapping positions
- **Bar-by-bar simulation** — SL/TP checked on each bar's high/low
- **Same-bar ambiguity:** If both SL and TP are hit on the same bar, 
  the trade is resolved conservatively (SL if bar opened against position)

---
*Script: `research/run_backtest.py` | Re-run: `python3 research/run_backtest.py`*