# XAU RSI(2) Strategy — Saved for Later

## Proven Live Performance
- **11W / 1L (91.7% WR)** on Lighter.xyz (Mar 20-21 2026)
- RSI(2) mean reversion + EMA(50) trend filter on 15m candles

## Fee-Adjusted Optimal Config (60d Yahoo backtest)
- **SL: 2.0%** — wide, gives room to breathe
- **TP: 1.0%** — inverted R:R (0.5x), captures mean reversion snap
- **WR: 75.0%** | **PF: 1.38** | **Total: +17.8%** over 60 days
- Accounts for 0.056% round-trip taker fee on Lighter

## Alternative Config (if XAU gets zero fees)
- SL: 1.2% / TP: 0.3% (R:R=0.2x)
- WR: 86.5% | PF: 1.60 | Total: +26.1%
- Only viable if XAU taker fees are truly zero

## Entry Logic
```
RSI(2) < 15 AND price > EMA(50) → BUY (oversold dip in uptrend)
RSI(2) > 85 AND price < EMA(50) → SELL (overbought pop in downtrend)
```

## Key Parameters
- Timeframe: 15m candles
- RSI period: 2
- EMA period: 50
- Cooldown: 600s between entries
- Sizing: dynamic % of live balance

## Notes
- Gold mean-reverts strongly — inverted R:R is correct (tight TP, wide SL)
- The 9/9 streak (commit 8a1df84) used $1.50 fixed risk
- XAU fee status on Lighter is unclear ("-" shown in trade history)
- Re-enable when: (a) fee structure confirmed, (b) want to diversify from SOL
