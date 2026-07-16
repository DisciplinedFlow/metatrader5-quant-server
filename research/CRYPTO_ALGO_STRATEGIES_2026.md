# Crypto Algo Strategies Research — Mar 16, 2026

## Implementation Priority for $30-100 on Zero-Fee DEX (Lighter.xyz)

### Phase 1: Foundation (Now)
**Dynamic ATR Grid Trading** — ATR(14) x 0.6 spacing, min 1%, max 4%. EMA(50) trend filter.
- Sharpe: 1.0-1.8 | Win Rate: 65-80% | Max DD: 15-25%

### Phase 2: Alpha Layer (Next)
**BB(20,2.5) + RSI(14) + ADX(14) Mean Reversion** — Toggle ON when ADX < 25.
- Sharpe: 1.0-1.5 | Win Rate: 65-75% | Max DD: 8-15%
- Key finding: ADX filter turned a $7K loss into $57K profit in backtests

### Phase 3: Passive Yield
**Lighter LLP Vault** — 42-47% APR passively. Even $10 earns yield.

### Phase 4: Diversification
**Risk-Managed TSMOM** — 12-month momentum, vol-scaled sizing.
- Sharpe: 1.42 | Uncorrelated to grid/MR strategies

### Phase 5: Advanced
**HMM Regime Toggle** — 3-state HMM switches between grid/momentum/cash
**Cointegration Pairs** — Best Sharpe (1.4-4.0) but needs $200+ capital

## Key Research Findings

### Grid Trading
- Dynamic grids outperform static by 15-30%
- Futures grid = ~2x spot grid returns
- On zero-fee venues, tighter grids (0.5-1%) become viable
- ATR-based spacing formula: `ATR(14) x 0.6`, clamped to [1%, 4%]

### Mean Reversion
- BB + ADX + RSI on BTC: 66.7% WR, dramatically improved with ADX filter
- Crypto needs more extreme RSI thresholds: <20/>80 (not traditional <30/>70)
- Academic finding: mean reversion works in accumulation/sideways, fails in trends

### Market Making
- Hyperliquid HLP Vault: Sharpe 5.2, 42% CAGR (best risk-adjusted return found)
- Lighter LLP: 42-47% APR
- DIY Avellaneda-Stoikov: Sharpe 1.0-2.0, requires $500+ and expertise

### Momentum
- Time-series momentum on crypto: Sharpe 1.51 vs market 0.84
- Risk-managed TSMOM: Sharpe improved from 1.12 to 1.42
- Cross-sectional momentum works BETTER than TSMOM for crypto

### Portfolio Rules
- Quarter Kelly sizing (NEVER full Kelly for crypto)
- Strategy diversification > asset diversification (crypto correlations spike to 0.95+)
- Portfolio drawdown halt: -15% = all strategies off for 24h

## Capital Allocation ($100 Example)
- $40: Dynamic grid (active)
- $25: Mean reversion (active)
- $15: TSMOM momentum (active)
- $10: LLP/HLP vault (passive)
- $10: Cash reserve

## Sources
See full research output for 50+ academic papers and source URLs.
