# Session-Based Trading Analysis — Mar 16-17, 2026

## YOUR DATA vs ACADEMIC RESEARCH

### Session Performance (Your Bot, 68 trades)

| Session | UTC Hours | Your Trades | Your WR | Your P&L | Research Says |
|---------|-----------|-------------|---------|----------|---------------|
| Asian | 22:00-08:00 | 54 | 54% | +$9.26 | Worst session (4/8 hrs negative). Range-bound. Use mean reversion/grid |
| London | 08:00-12:00 | 0 | — | — | Good session, volatility ramp. We missed it entirely! |
| Overlap | 12:00-17:00 | 1 | 100% | +$0.79 | BEST session (2/8 hrs negative). Momentum works here |
| NY | 17:00-22:00 | 13 | 46% | +$15.42 | 22:00-23:00 anomaly: 37.26% annual (buy 21:00, sell 23:00) |

### Key Discovery: 21:00 UTC is YOUR best hour
- 10 trades, 40% WR, but +$13.21 P&L
- Research confirms: "22:00-23:00 UTC are the most statistically significant positive return hours for Bitcoin"
- YOUR data matches the academic anomaly perfectly

### What We're Missing
1. **London session (08:00-12:00)** — ZERO trades. Research says this is when liquidity is deepest ($3.86M depth vs $2.71M Asian)
2. **US overlap (12:00-17:00)** — Only 1 trade. Research says this has the best returns
3. We're over-trading Asian session where research says returns are worst

## IMPLEMENTATION PLAN

### 1. Session-Aware Position Sizing
- Asian (22:00-08:00): 60% base size (worst returns historically)
- London (08:00-12:00): 100% base size (deep liquidity, good returns)
- Overlap (12:00-17:00): 120% base size (best risk-adjusted returns)
- Late NY (17:00-22:00): 80% base size, but 100% at 21:00-23:00 (anomaly)

### 2. News Sentiment Integration
- news_sentiment.py already built, uses free RSS feeds
- Negative sentiment = 2-3x stronger price response than positive (asymmetric)
- Process within 1-5 minutes for social signals
- ELEVATED risk → 75% size, EXTREME → 50% size

### 3. The 22:00-23:00 UTC Anomaly Strategy
- Academic: Buy at 21:00, sell at 23:00 = 37.26% annual, -18.87% max DD
- This is a pure time-based strategy, no indicators needed
- Could be a standalone Celery task

### 4. Symbol Allocation Based on Data
- ETH: +$23.90 → INCREASE allocation (primary symbol)
- SOL: +$3.88 → Keep as is
- XAU: +$2.47, 69% WR → Keep, good risk-adjusted
- BTC: -$2.19 → REDUCE allocation
- GBPUSD: -$2.65, 0% WR → DISABLE or reduce to minimum
- EURUSD: +$0.05, 25% WR → REDUCE significantly

## Sources
See full research for 30+ academic papers and backtest data.
