# Oil & Natural Gas Algorithmic Trading Strategies Research
## Comprehensive Research for MT5 Implementation (March 2026)

**Context**: Oil broke $100/barrel due to Iran-Israel conflict. IEA calls it the "largest supply disruption in the history of the global oil market." ~20% of global oil supply (Strait of Hormuz) disrupted. CTAs are 100% long crude for first time in 4 years. Goldman Sachs models $140/bbl in a 120-day disruption scenario.

---

## Table of Contents
1. [Current Market Regime (March 2026)](#1-current-market-regime)
2. [Proven Quantitative Oil Trading Strategies](#2-proven-quantitative-strategies)
3. [Oil Market Microstructure](#3-oil-market-microstructure)
4. [Geopolitical Crisis Trading Playbook](#4-geopolitical-crisis-trading)
5. [Natural Gas Strategies](#5-natural-gas-strategies)
6. [Risk Management for Energy CFDs](#6-risk-management)
7. [Technical Indicators That Work for Oil](#7-technical-indicators)
8. [Academic Research & ML Approaches](#8-academic-research)
9. [Implementation Plan for MT5](#9-implementation-plan)

---

## 1. Current Market Regime

### The Iran-Israel Supply Shock (March 2026)

**What Happened:**
- U.S.-Israel struck Iranian nuclear facilities + oil infrastructure (late Feb 2026)
- Iran retaliated with strikes on energy and transport infrastructure
- Strait of Hormuz effectively shut down (20% of global oil, 20-25% of global NG)
- ~8M barrels/day supply disruption -- largest in history
- WTI spiked from ~$65 to $120 on March 8 futures open
- Oil surged past $100 on March 12 despite record SPR releases

**Goldman Sachs Scenarios (March 11, 2026):**
| Duration | Brent Fair Value | WTI Fair Value |
|----------|-----------------|----------------|
| 21-day disruption (base case) | $71 | $67 |
| 30-day disruption | $76 | $72 |
| 60-day disruption | $93 | $89 |
| 120-day disruption | >$140 (demand destruction) | >$135 |

**JPMorgan View**: More dovish -- expects targeted action, no protracted disruption. Brent ~$60/bbl base case for 2026 (pre-conflict assumption).

**Key Insight**: Goldman now assumes 21 days of low Hormuz flows at 10% of normal + 30-day gradual recovery. If this extends, we're in 2008 territory.

### Algorithmic Trader Positioning
- CTAs have pushed bullish positions to 100% long in WTI and Brent futures
- This is the first time in 4 years algorithmic traders are fully invested long crude
- This creates a "powder keg" -- if sentiment reverses, CTA liquidation could accelerate downside

### Historical Analogues

| Event | Supply Loss | Price Move | Duration | Recovery |
|-------|-----------|------------|----------|----------|
| Gulf War 1990 | Iraq+Kuwait (5M bbl/d) | $17->$36 (+112%) | 9 months | Full retracement after liberation |
| Iraq War 2003 | Iraq (2.5M bbl/d) | +40% over 3-4 months | Limited | Quick retracement to $23 once uncertainty eased |
| Libya 2011 | Libya (1.6M bbl/d) | +25% | ~6 months | Gradual |
| Iran-Israel 2026 | Hormuz (~8M bbl/d) | $65->$120 (+85%) | Ongoing | TBD -- $84.95 (61.8% Fib) tested as support |

**Pattern**: Markets spike on shock, then typically retrace 50-62% within 2-3 months IF supply normalizes. The 1990 Gulf War is the closest analogue (comparable percentage disruption).

**Current Retracement Data:**
- Rally to $119 was buying climax
- 0.618 Fibonacci retracement of $55.27-$119.40 swing = $79.77 (tested as support)
- 0.618 Fibonacci of latest swing = $84.95 (providing clear support, buyers stepping in)
- Gap-fill tendency: historical energy gap-ups on geopolitical news tend to fill before resuming uptrend

---

## 2. Proven Quantitative Oil Trading Strategies

### Strategy 1: Donchian Channel Breakout (Trend Following)

**What CTAs Actually Use:**
The classic Turtle Traders system adapted for energy futures.

**Rules:**
- **Setup**: 20-day Donchian Channel (highest high / lowest low of last 20 bars)
- **Trend Filter**: 25-day EMA > 350-day MA (only trade in direction of major trend)
- **Entry Long**: Price closes above 20-day high channel
- **Entry Short**: Price closes below 20-day low channel
- **Stop Loss**: 2x ATR(14) from entry
- **Exit**: Price hits opposite channel boundary OR trailing stop at 10-day Donchian opposite channel
- **Position Sizing**: Risk 1% of equity per trade, size = (account_risk) / (2 * ATR * pip_value)

**Backtest Performance (15 years, 20 futures markets including crude oil):**
- Win rate: ~45% (high for trend following, which typically sees 30-35%)
- Profitable on both E-mini S&P 500 and crude oil futures
- Drawdowns relatively small relative to net profit
- **Limitation**: Only ~1.5 trades per year on daily timeframe for a single instrument

**Adaptation for H4:**
- Use 80-bar (20-day equivalent) Donchian Channel on H4
- Trend filter: 100-bar EMA > 1400-bar MA on H4
- This increases trade frequency to ~6-8 per year

### Strategy 2: Bollinger Band Squeeze Breakout (Volatility)

**Rules:**
- **Setup**: 20-period SMA, 2.0 standard deviations (default). For oil, consider 50MA/2SD for better results
- **Squeeze Detection**: Bandwidth (upper - lower) / middle < threshold (use 20-period percentile rank of bandwidth)
- **Entry**: After squeeze (bandwidth in bottom 20th percentile for 6+ bars), price closes above upper band with volume confirmation
- **Stop Loss**: Middle band (20-SMA) or 1.5x ATR below entry
- **Take Profit**: 2x the squeeze range projected from breakout, or trail with middle band
- **Confirmation**: OBV divergence, RSI > 50 for longs

**Backtest Notes:**
- Optimized Bollinger Bands (50MA/2SD) consistently outperformed RSI and MACD alone on crude oil
- Works best when volatility shifts from low to high (which is NOW -- regime shift from $65 range to $100+ range)
- Higher standard deviation multiplier (2.5 or 3.0) reduces false breakouts in volatile markets

### Strategy 3: Momentum / Rate of Change (ROC)

**Rules:**
- **ROC Period**: 14-day for swing trading on H4 (56 bars); 20-day for daily
- **Signal Line**: 5-period SMA of ROC for smoothing
- **Entry Long**: ROC crosses above zero AND price above 20-period SMA
- **Entry Short**: ROC crosses below zero AND price below 20-period SMA
- **Exit**: ROC crosses signal line in opposite direction, OR ROC reaches extreme (>2 standard deviations from mean)
- **Trend Filter**: 200-period MA direction must agree

**Key Research Finding:**
- Past 12-month returns of commodities positively predict next month's returns
- Time-series momentum strategy achieves Sharpe ratios above 1.20 on commodity futures
- Momentum strategies should work for crude oil futures at any reasonable time scale
- Medium-strength trends persist at scales of several days to several years
- Reversion dominates at shorter or longer time scales

### Strategy 4: VWAP Mean Reversion (Intraday/H1)

**Best For**: Range-bound days, consolidation phases after initial spike

**Rules:**
- **Timeframe**: H1 or M15 (use daily VWAP)
- **Entry Long**: Price extends >1.5 ATR below VWAP + RSI < 30 (or z-score < -2)
- **Entry Short**: Price extends >1.5 ATR above VWAP + RSI > 70 (or z-score > 2)
- **Stop Loss**: 1-2 ATR beyond the swing extreme
- **Take Profit**: VWAP line (scale out 50% at VWAP, trail remainder)
- **Time Stop**: If no movement toward VWAP within 4-6 bars, exit at market
- **CRITICAL**: Do NOT use in strong trending markets. Only valid in ranging/consolidation

**Key Research Finding:**
- Mean reversion works in spot markets but NOT well in futures markets for commodities
- Commodity-related instruments have historically not worked well for mean-reverting strategies
- Use this strategy ONLY during confirmed range-bound/consolidation phases
- Oil is currently in a strong trend -- mean reversion is DANGEROUS right now

### Strategy 5: Keltner Channel Breakout

**Rules:**
- **Middle Line**: 20-period EMA
- **Upper Band**: EMA + (2 x ATR(10))
- **Lower Band**: EMA - (2 x ATR(10))
- **Entry Long**: Price closes above upper Keltner Channel with volume > 1.5x average
- **Entry Short**: Price closes below lower Keltner Channel with volume > 1.5x average
- **Stop Loss**: Below middle EMA for longs, above middle EMA for shorts
- **Trailing Stop**: Middle EMA -- exit if price closes below/above middle line
- **Profit Target**: Previous S/R zones or Fibonacci extensions

**Adaptation for Current Crisis:**
- Widen multiplier to 2.5x ATR during high-vol regime (current ATR is 3-5x normal)
- Only trade breakouts in direction of HTF trend (currently bullish)

### Strategy 6: EIA/API Inventory Report Strategy

**Rules:**
- **Data**: EIA Weekly Petroleum Status Report -- Wednesday 10:30 AM ET (15:30 UTC)
- **API Report**: Tuesday 4:30 PM ET (early indicator, less reliable)
- **Entry Condition**: Inventory surprise exceeds threshold
  - Bearish (go long): Actual drawdown > consensus by 2M+ barrels (High vol: relax to 1.5M)
  - Bullish (go short): Actual build > consensus by 2M+ barrels (High vol: relax to 1.5M)
- **Confirmation**: 4-hour RSI < 30 for longs (oversold) or > 70 for shorts (overbought)
- **Entry**: After initial 30-minute reaction, enter on pullback to VWAP
- **Stop**: 1.5x ATR from entry
- **Target**: Hold to end of day or until momentum exhausts (ROC reversal)

**Research Insight:**
- Returns on the 3rd half-hour of EIA announcement days significantly predict returns in the last half-hour
- On non-EIA days, only the first half-hour has significant predictability
- **Also watch**: Cushing, OK inventory changes specifically -- this is the "heartbeat" of WTI spreads
- Storage utilization > 80% at Cushing = supply constraints
- Storage utilization < 40% = oversupply

### Strategy 7: WTI/Brent Spread (Pairs Trading)

**Rules:**
- **Spread**: Brent - WTI (normally $3-7 premium for Brent)
- **Mean**: 20-day SMA of spread
- **Entry**: Spread deviates >2 standard deviations from mean
  - If spread too wide: Long WTI, Short Brent (expect convergence)
  - If spread too narrow: Long Brent, Short WTI
- **Exit**: Spread returns to mean
- **Stop**: Spread widens to 3 standard deviations

**Current Context (March 2026):**
- Brent premium has likely expanded dramatically due to Hormuz closure (Brent = international, more affected)
- USD/WTI correlation: 0.60 (positive)
- USD/Brent correlation: 0.55 (positive)
- OPEC decisions and geopolitical events shift Brent prices faster than WTI
- Spread is currently anomalous -- be cautious with mean reversion assumptions during regime breaks

---

## 3. Oil Market Microstructure

### Best Trading Sessions (All Times UTC)

| Session | UTC Time | Focus | Characteristics |
|---------|----------|-------|-----------------|
| **Asian** | 00:00-08:00 | Brent/WTI | Low volume, wide spreads, avoid new entries |
| **London Open** | 08:00-09:00 | Brent | Brent liquidity surges, initial direction often sets tone |
| **London** | 08:00-16:30 | Brent primary | Strong Brent volume |
| **London-NY Overlap** | 13:00-17:00 | **PEAK LIQUIDITY** | Tightest spreads, highest volume, BEST window |
| **NY Open** | 14:30-15:00 | WTI | WTI volume surges |
| **EIA Report** | 15:30 (Wed) | WTI/Brent | Highest volatility event of the week |
| **NY Close** | 21:00-22:00 | Both | Volume drops off |
| **Dead Zone** | 22:00-01:00 | None | **AVOID** -- widest spreads, no sustained moves |

### Optimal Trading Windows for MT5 Implementation
1. **Primary**: 13:00-17:00 UTC (London-NY overlap) -- enter new positions here
2. **Secondary**: 08:00-12:00 UTC (London session) -- Brent setups
3. **Event**: 15:30 UTC Wednesday (EIA) and Tuesday 21:30 UTC (API preview)
4. **BLOCK**: 22:00-01:00 UTC -- no new entries

### Timeframe Recommendations

| Timeframe | Use Case | Signal Quality | Trade Frequency |
|-----------|----------|---------------|-----------------|
| M15 | Scalping/entry refinement | Low (noisy) | Very high |
| H1 | Intraday swing, VWAP reversion | Medium | ~2-4/week |
| **H4** | **Primary swing trading** | **High** | **~1-2/week** |
| **D1** | **Trend identification, HTF bias** | **Highest** | ~1-2/month |
| W1 | Major trend / regime detection | Context only | Rarely |

**Recommendation**: Use D1 for trend direction, H4 for entries, H1 for entry refinement.

### WTI/Brent CFD Specifications (MT5 Typical)

| Parameter | WTI (USOIL) | Brent (UKOIL) |
|-----------|-------------|----------------|
| Standard lot | 1,000 barrels | 1,000 barrels |
| Min trade | 0.01 lots (10 barrels) | 0.01 lots (10 barrels) |
| Pip size | $0.01 | $0.01 |
| Pip value (1 lot) | $10 | $10 |
| Pip value (0.01 lot) | $0.10 | $0.10 |
| Typical spread | 3-5 pips (normal) | 3-6 pips (normal) |
| Crisis spread | 10-30+ pips | 10-30+ pips |
| Margin (1:25) | 4% | 4% |
| Normal daily ATR | 150-250 pips ($1.50-$2.50) | 150-250 pips |
| **Current crisis ATR** | **400-800 pips ($4-$8)** | **500-1000+ pips** |
| Trading hours | Mon-Fri (near 24h with break) | Mon-Fri |

### ATR Context
- Normal (non-crisis): ATR(14) on D1 = ~$1.50-$2.50 (150-250 pips)
- Current crisis: ATR(14) on D1 = ~$4.00-$8.00+ (400-800+ pips)
- On H4: Divide daily ATR by ~2-3 for approximate H4 ATR
- **CRITICAL**: Position sizing MUST adjust for current ATR, not historical averages

---

## 4. Geopolitical Crisis Trading Playbook

### Phase 1: The Spike (Days 1-5)
**What happens**: Gap-up on futures open. Panic buying. CTAs pile in. Prices overshoot.

**Strategy**:
- **DO NOT CHASE the initial spike** -- gap-ups on geopolitical news historically fill
- Wait for the first 24-48 hours of price discovery
- Look for exhaustion signals: bearish engulfing on H4, RSI > 85, volume divergence
- If already positioned: trail with 3x ATR stops, take 30% off at +3R

### Phase 2: The Consolidation/Pullback (Days 5-30)
**What happens**: Initial shock absorbed. SPR releases. Diplomatic noise. Price retraces 38-62% of initial spike.

**Strategy**:
- Watch Fibonacci retracement levels of the spike:
  - 0.382 retracement: Shallow pullback (very bullish continuation)
  - 0.500 retracement: Normal pullback (bullish if holds)
  - 0.618 retracement: Deep pullback (critical support -- if breaks, spike was overdone)
- **Current data**: $84.95 (61.8% of latest swing) is providing support; $79.77 (61.8% of full $55-$119 swing) is major structural support
- Enter trend-following longs on pullbacks to 50-61.8% Fib with RSI < 40
- Stop below 78.6% Fib level

### Phase 3: The Sustained Move OR Reversion (Days 30+)
**What determines outcome**: ACTUAL supply disruption duration vs. market expectations.

**If supply disruption persists (Hormuz stays closed):**
- Backwardation deepens (front month premium over back months)
- New higher range establishes
- Trend-following strategies dominate
- Target: Goldman's $93-$140 range depending on duration

**If supply normalizes (ceasefire, Hormuz reopens):**
- Gap-fill retracement to pre-crisis levels ($65-$70)
- Contango returns
- Mean reversion strategies become valid
- CTA liquidation accelerates downside

### Phase Indicators to Monitor
1. **Strait of Hormuz shipping data** (AIS vessel tracking, tanker departures)
2. **Brent-WTI spread** (widening = international supply worse)
3. **Brent futures curve** (backwardation depth = supply tightness)
4. **OPEC+ emergency meeting announcements**
5. **U.S. SPR release volume** (higher releases = more bullish offset)
6. **Diplomatic signals** (ceasefire talks, UN resolutions)

---

## 5. Natural Gas Strategies

### Key Differences from Crude Oil
Natural gas is fundamentally different:
- **Weather-driven** (heating in winter, cooling in summer)
- **Seasonal** (predictable demand patterns)
- **Storage-dependent** (injection season Apr-Oct, withdrawal season Nov-Mar)
- **More volatile** than crude oil (bigger percentage moves)
- **Less correlated** to geopolitics (U.S. NG is relatively insulated from Hormuz)

### Current NG Situation (March 2026)
- Henry Hub averages ~$3.80/MMBtu in 2026
- European/Asian LNG prices elevated due to reduced Hormuz LNG flows
- U.S. natural gas prices relatively unaffected (domestic supply)
- Potential arbitrage: U.S. LNG export premium to Europe/Asia

### Strategy 8: NG Seasonal Pattern Trading

**Historical Seasonal Rules:**
| Period | Tendency | Strategy |
|--------|----------|----------|
| Jan-Mar | Bullish (winter withdrawal) | Long on cold weather forecasts, watch storage draws |
| Apr-May | Bearish transition | Short as heating demand drops, injection season begins |
| Jun-Aug | Mixed (summer cooling demand) | Range trading, watch heat waves |
| Sep-Oct | Bullish building | Long as pre-winter stocking begins |
| Nov-Dec | Most volatile | Trade the weather forecasts + storage reports |

**Research Note**: ML models identify seasonal patterns with 82% accuracy vs. 61% using traditional seasonality analysis. Backtests show only 40-50% win rates even in robust patterns, with 3-5 consecutive losses in 30% of years.

### Strategy 9: EIA Natural Gas Storage Report (Thursday)

**Release**: Every Thursday, 10:30 AM ET (15:30 UTC)

**Rules:**
- **Consensus vs Actual**: Pre-position based on weather forecasts, then trade the deviation
- **Bullish signal**: Withdrawal > consensus OR injection < consensus
- **Bearish signal**: Withdrawal < consensus OR injection > consensus
- **Entry**: Wait 15 minutes after release for initial reaction, then enter on pullback to intraday VWAP
- **Threshold**: Only trade when deviation > 5 Bcf from consensus
- **Stop**: 2x ATR(14) on H1 chart
- **Target**: 2:1 reward-to-risk minimum

### Strategy 10: NG Calendar Spread (March/April Spread)

**Concept**: Winter gas (March) should trade at premium to spring gas (April) due to heating demand.

**Rules:**
- **Long**: Buy March NG, Sell April NG when spread is below historical average
- **Exit**: Spread returns to normal or expiry approaches
- **Monitor**: Storage levels at key WNGSR reporting dates
- **RSI Confirmation**: 20-day RSI on spread < 30 = buy spread (oversold)

**October/November and October/January spreads** are also historically popular filling-season spreads.

### Strategy 11: NG Weather-Based Trading

**Data Sources:**
- NOAA weather forecasts (7-day, 14-day)
- Heating Degree Days (HDD) / Cooling Degree Days (CDD)
- Weather model disagreements (GFS vs European model)

**Rules:**
- Cold snap forecast (HDD > seasonal normal by 20%+): Go long NG
- Warm spell forecast (HDD < seasonal normal by 20%+): Go short NG
- **Lead time**: Enter 3-5 days before weather event hits
- **Exit**: When weather arrives (buy the rumor, sell the news)

---

## 6. Risk Management for Energy CFDs

### Position Sizing Formula (ATR-Based)

```
Position Size (lots) = Account Risk ($) / (Stop Distance in $ * Contract Size per lot)

Where:
- Account Risk = Account Equity * Risk Percentage (1-2%)
- Stop Distance = ATR(14) * Multiplier (1.5-2.0)
- Contract Size = 1000 barrels per standard lot for WTI/Brent

Example (current crisis conditions):
- Account: $10,000
- Risk: 1% = $100
- ATR(14) D1: $6.00 (600 pips) -- current crisis level
- Stop: 1.5 * $6.00 = $9.00
- Position: $100 / ($9.00 * 1000) = 0.011 lots

Compare to normal conditions:
- ATR(14) D1: $2.00 (200 pips)
- Stop: 1.5 * $2.00 = $3.00
- Position: $100 / ($3.00 * 1000) = 0.033 lots
```

**Key Point**: Position size is ~3x SMALLER in current crisis conditions due to elevated ATR. This is correct and necessary.

### Risk Management Rules for Energy Trading

| Rule | Parameter | Rationale |
|------|-----------|-----------|
| Risk per trade | 0.5-1% of equity | Commodities are leveraged, 1% max |
| Max oil exposure | 15% of total portfolio equity | Concentration limit |
| Max open positions | 3 for energy (2 oil + 1 NG) | Correlation risk |
| Daily loss halt | 3% of equity | Force reassessment after bad day |
| Max drawdown shutoff | 10% from portfolio peak | Shut down, reassess market/strategy |
| Stop loss | 1.5-2x ATR from entry | Must adjust for current volatility |
| Minimum R:R | 1.5:1 (crisis: 2:1) | Higher bar during high vol |
| No trading zones | 22:00-01:00 UTC; first 30min of session | Thin liquidity = bad fills |
| Event buffer | No new positions 30min before EIA/API | Avoid whipsaw |

### Correlation Matrix (Approximate)

| | WTI | Brent | Nat Gas | Gold | S&P 500 |
|---|-----|-------|---------|------|---------|
| **WTI** | 1.00 | 0.95+ | 0.30-0.50 | 0.20-0.40 | 0.10-0.30 |
| **Brent** | 0.95+ | 1.00 | 0.25-0.45 | 0.20-0.40 | 0.10-0.30 |
| **Nat Gas** | 0.30-0.50 | 0.25-0.45 | 1.00 | 0.10 | 0.05 |
| **Gold** | 0.20-0.40 | 0.20-0.40 | 0.10 | 1.00 | -0.20 |

**Key Takeaway:**
- WTI/Brent: Highly correlated (0.95+) -- treat as ONE exposure for risk purposes
- Crude/NG: Moderate correlation (0.30-0.50) -- somewhat independent
- NG is the most independent energy instrument -- offers real diversification
- During crisis: All energy correlations increase (everything moves together)

### Leverage Guidelines

| Volatility Regime | Recommended Leverage | Reasoning |
|-------------------|---------------------|-----------|
| Low vol (ATR < $1.50) | Up to 1:10 | Normal conditions |
| Medium vol (ATR $1.50-$3.00) | 1:5 to 1:7 | Increased caution |
| High vol (ATR $3.00-$5.00) | 1:3 to 1:5 | Current transitional |
| Crisis vol (ATR > $5.00) | 1:2 to 1:3 max | **CURRENT REGIME** |

---

## 7. Technical Indicators That Work for Oil

### Tier 1: Strong Evidence for Oil

| Indicator | Configuration | Use Case | Research Support |
|-----------|--------------|----------|-----------------|
| **Bollinger Bands** | 50-period MA, 2 SD | Squeeze breakouts, volatility | Outperformed RSI/MACD alone in oil backtest |
| **ATR** | 14-period | Position sizing, stops | Essential for any energy strategy |
| **Donchian Channel** | 20-period (80 bars on H4) | Trend following breakouts | Proven on commodity futures (45% WR) |
| **EMA (20/50/200)** | Multi-timeframe | Trend direction, dynamic S/R | Foundation of CTA strategies |
| **ROC/Momentum** | 14-20 period | Momentum confirmation | Sharpe > 1.20 on commodity TSMOM |

### Tier 2: Useful with Confirmation

| Indicator | Configuration | Use Case | Notes |
|-----------|--------------|----------|-------|
| **RSI** | 14-period, 30/70 thresholds | Overbought/oversold, divergences | Better as filter than standalone |
| **MACD** | 12/26/9 | Momentum confirmation | Golden cross above zero = high-prob buy |
| **OBV** | Default | Volume confirmation | Bullish divergence (price lower low + OBV higher high) predicted $5 crude move |
| **Keltner Channel** | 20 EMA, 2x ATR | Volatility breakouts | Adaptive bands better than fixed Bollinger in trending |
| **VWAP** | Daily reset | Intraday mean reversion | Only for H1 and below |

### Tier 3: Oil-Specific Indicators (Fundamental)

| Indicator | Source | Frequency | What It Tells You |
|-----------|--------|-----------|-------------------|
| **EIA Crude Inventory** | EIA.gov | Weekly (Wed 10:30 ET) | Supply/demand balance. Draw = bullish |
| **Cushing OK Storage** | EIA report detail | Weekly | >80% utilization = constraint, <40% = oversupply |
| **API Report** | API | Weekly (Tue 4:30 PM ET) | Early indicator of EIA data |
| **Inventory Surprise** | Actual minus forecast | Weekly | Larger delta = stronger move |
| **Brent-WTI Spread** | Price difference | Continuous | Regional S/D imbalance, geopolitical risk |
| **Futures Curve Shape** | Front vs back months | Continuous | Backwardation = tight supply; Contango = oversupply |
| **Crack Spread (3:2:1)** | 3 crude vs 2 gas + 1 diesel | Continuous | >$20 = strong refining margins, bullish |
| **Baker Hughes Rig Count** | Baker Hughes | Weekly (Fri) | Future supply indicator |
| **OPEC+ Compliance** | Various | Monthly | Production discipline |

### Combined Indicator Strategy (Recommended for MT5)

**Entry Checklist (Long Example):**
1. D1 trend filter: Price > 200 EMA on Daily -- YES/NO
2. H4 momentum: ROC(14) > 0 AND crossing above signal line -- YES/NO
3. H4 Bollinger: Price near or breaking above upper band after squeeze -- YES/NO
4. H4 volume: OBV making new highs (confirming price) -- YES/NO
5. Fundamental: Last EIA report showed draw (or neutral) -- YES/NO
6. Session: Within 08:00-17:00 UTC window -- YES/NO

**Score**: Need 4/6 minimum for entry. 5/6 or 6/6 = A+ setup (larger position).

---

## 8. Academic Research & ML Approaches

### Key Academic Findings

**1. Momentum vs. Mean Reversion in Oil Futures**
- Source: Bianchi, Fan, Todorova (2020), ScienceDirect
- **Finding**: Momentum performs well in futures markets; mean reversion performs well in SPOT markets but NOT futures
- **Implication**: For CFD/futures trading, use MOMENTUM strategies, not mean reversion
- Time-series momentum strategies achieve Sharpe ratios > 1.20 on commodity futures
- Medium-strength trends persist at scales of several days to several years

**2. Mean-Reverting Calendar Spread Portfolios**
- Source: Lubnau & Todorova (2015), Energy Economics
- **Finding**: Mean-reverting calendar spread portfolios with dynamic hedge ratios work well for crude oil and NG
- **Entry/Exit**: Bollinger Bands on the spread (not the price)
- **Implication**: Mean reversion works on SPREADS even when it fails on directional price

**3. Machine Learning Approaches (2024-2025 Papers)**

| Model | Architecture | Performance |
|-------|-------------|-------------|
| CEEMDAN-VMD-CNN-BiLSTM | Hybrid decomposition + deep learning | MAPE 3.66%, R2 95.94% on WTI 2017-2025 |
| XGBoost-LSTM Hybrid | XGBoost for high-freq + LSTM for low-freq modes | Best hybrid approach for volatility regime detection |
| Random Forest + GRU + XGBoost Ensemble | Stacking ensemble | Robust across multiple oil benchmarks |
| Bayesian-optimized BiLSTM + XGBoost | Ensemble with SLSQP weighting | State-of-art for Brent AND WTI jointly |

**Key ML Insight for Our System:**
- Best approach: Decompose price into low-freq (LSTM) and high-freq (XGBoost) components
- Feature selection matters more than model complexity
- Walk-forward validation essential (what worked in 2022 may fail in 2025)
- **Our existing XGBoost infrastructure can be adapted** -- add oil-specific features:
  - ATR ratio (current/historical)
  - Inventory surprise magnitude
  - Brent-WTI spread z-score
  - Futures curve slope (if available)
  - Day-of-week + session encoding
  - ROC across multiple timeframes (5, 10, 20 periods)

**4. Cross-Asset Momentum**
- Source: Fung, Garvey, Valenzuela (2022), Journal of Banking & Finance
- **Finding**: Crude oil volatility has cross-asset time-series momentum effects on global stock markets
- **Implication**: Oil volatility regime can predict equity market direction

**5. Volume-Price Time-Frequency Decomposition**
- Source: Energy journal (2023)
- **Finding**: Ensemble deep reinforcement learning strategy combining volume-price decomposition outperforms single-model approaches
- **Implication**: Volume data is critical -- OBV/CVD integration with price analysis improves predictions

---

## 9. Implementation Plan for MT5

### Phase 1: Oil Market Data Infrastructure (Week 1)

1. **Add oil symbols** to MT5 watchlist: XTIUSD (WTI), XBRUSD (Brent), XNGUSD (Natural Gas)
2. **Fetch H4 and D1 OHLCV data** via existing `fetch_data_pos` (100 bars max constraint)
3. **Calculate oil-specific indicators**:
   - ATR(14) on H4 and D1
   - Donchian Channel (20-period on D1 = 80-bar on H4)
   - Bollinger Bands (50-period MA, 2 SD)
   - ROC(14) with 5-period SMA signal line
   - Keltner Channel (20 EMA, 2x ATR)
   - OBV

### Phase 2: Oil Strategy Module (Week 2)

Create `algorithms/oil_strategy.py`:
```python
# Key components:
# 1. Volatility regime classifier (low/medium/high/crisis based on ATR percentile)
# 2. Trend following engine (Donchian breakout + ROC confirmation)
# 3. Bollinger squeeze detector
# 4. Session filter (only trade 08:00-17:00 UTC)
# 5. EIA event calendar awareness (reduce exposure before Wed 15:30 UTC)
# 6. Position sizer adjusted for oil ATR
```

### Phase 3: Integrate with Existing Brain (Week 3)

- Add oil symbols to strategy router
- Oil uses DIFFERENT strategy parameters than XAUUSD:
  - Wider stops (2x ATR vs 1.2x ATR for gold)
  - Smaller position sizes (higher ATR = smaller lots)
  - Different session windows (oil peaks at London-NY overlap)
  - Trend-following bias (not mean reversion)
- HMM regime detector: Train on oil data (different states than gold)
- XGBoost: Add oil-specific features to feature vector

### Phase 4: Natural Gas Module (Week 4)

Create `algorithms/ng_strategy.py`:
```python
# Key components:
# 1. Seasonal bias calculator (month of year -> directional bias)
# 2. Storage report calendar (Thursday 15:30 UTC awareness)
# 3. Weather data integration (optional, via API)
# 4. NG-specific position sizing (even smaller -- NG is more volatile than oil)
```

### Risk Parameters for Oil Trading

```python
OIL_RISK_CONFIG = {
    # Position Sizing
    'CAPITAL_PER_TRADE': 300,       # Lower than XAUUSD ($500) due to higher vol
    'MAX_OPEN_OIL': 2,              # Max 2 oil positions (WTI + Brent = 1 effective due to 0.95 correlation)
    'MAX_OPEN_NG': 1,               # Max 1 NG position

    # Stops
    'SL_ATR_MULTIPLIER': 2.0,       # Wider than gold (1.2x) due to oil volatility
    'TP_ATR_MULTIPLIER': 3.0,       # Minimum 1.5:1 R:R

    # Risk Limits
    'MAX_LOSS_PER_TRADE': 50,       # Hard dollar cap
    'DAILY_HALT': 150,              # Lower daily halt for oil (separate from gold)

    # Session Filter (UTC)
    'TRADING_START': '08:00',
    'TRADING_END': '17:00',
    'BLOCKED_PERIODS': [
        ('22:00', '01:00'),         # Dead zone
        ('15:00', '16:00'),         # Wed only -- EIA buffer (30 min before/after)
    ],

    # Volatility Regime Thresholds (ATR percentile)
    'LOW_VOL': 25,                  # Below 25th percentile
    'HIGH_VOL': 75,                 # Above 75th percentile
    'CRISIS_VOL': 95,               # Above 95th percentile -- reduce all sizes by 50%

    # Strategy Selection by Regime
    'LOW_VOL_STRATEGY': 'bollinger_squeeze',    # Wait for breakout
    'NORMAL_STRATEGY': 'donchian_trend',        # Standard trend following
    'HIGH_VOL_STRATEGY': 'donchian_trend',      # Trend following with wider stops
    'CRISIS_STRATEGY': 'reduced_trend',         # Half-size trend following only
}
```

---

## Key Takeaways

1. **RIGHT NOW**: Oil is in a crisis regime. Use TREND FOLLOWING only. No mean reversion. Half position sizes. Wider stops.

2. **Primary Strategy**: Donchian Channel breakout on H4 (80-bar) with ROC confirmation and Bollinger squeeze detection. This is what CTAs use.

3. **Position Sizing is Critical**: Current ATR is 3-5x normal. If you size positions based on normal ATR, you will blow up. Use ATR-based sizing with 1% risk cap.

4. **Oil is NOT Gold**: Different market microstructure, different sessions, different indicators. Do not copy-paste XAUUSD strategy parameters.

5. **Time-Series Momentum Works**: Sharpe > 1.20 on commodity futures. This is the strongest edge in energy markets.

6. **Mean Reversion is Dangerous**: Works on spreads (WTI/Brent) but NOT on directional oil futures prices. Only use during confirmed range-bound regimes.

7. **Natural Gas is Independent**: Moderate correlation to crude (0.30-0.50). Weather-driven, seasonal. Good diversifier.

8. **Watch Fundamentals**: EIA Wednesday report is the weekly volatility event. Cushing storage utilization, futures curve shape, and Brent-WTI spread are all tradeable signals.

9. **Historical Pattern**: Geopolitical spikes retrace 50-62% within 2-3 months IF supply normalizes. Current support: $84.95 (61.8% Fib of latest swing).

10. **ML Enhancement**: Our existing XGBoost pipeline can be adapted with oil-specific features (ATR ratio, inventory surprise, spread z-score, ROC multi-TF).

---

## Sources

### Oil Trading Strategies & Backtests
- [Crude Oil Trading Strategies: 10 Types (Backtests)](https://www.quantifiedstrategies.com/crude-oil-trading-strategies/)
- [Crude Oil Futures: Volatility, Liquidity, and Trading Strategy Backtest](https://www.quantifiedstrategies.com/crude-oil-futures/)
- [Donchian Channels Trading Strategy (Backtest)](https://www.quantifiedstrategies.com/donchian-channel/)
- [Bollinger Band Squeeze Strategy - Backtest](https://www.quantifiedstrategies.com/bollinger-band-squeeze-strategy/)
- [Oil Trading Strategy Analysis (The Robust Trader)](https://therobusttrader.com/oil-trading-strategy/)
- [CTA Trading Strategy: Returns and Backtest](https://www.quantifiedstrategies.com/cta-trading-strategy/)
- [Natural Gas Trading Strategy (Backtest)](https://www.quantifiedstrategies.com/natural-gas-trading-strategy/)
- [Trend Following Trading Strategies](https://www.quantifiedstrategies.com/trend-following-strategy/)
- [Price Channel Strategy for Energy Futures (Benzinga)](https://www.benzinga.com/general/education/25/07/46280812/price-channel-strategy-for-trend-following-energy-futures-backtest-and-optimization)

### Market Microstructure & Sessions
- [Crude Oil Market Time: When to Trade](https://www.ebc.com/forex/crude-oil-market-time-when-to-trade-for-maximum-profit)
- [Oil Trading Hours (IG)](https://www.ig.com/en-ch/trading-strategies/oil-trading-hours--when-to-trade-crude-oil-240429)
- [Oil Trading Hours: Best Time to Trade (TMGM)](https://www.tmgm.com/en/academy/trading-academy/oil-trading-hours)
- [Volatility-Based Position Sizing for CFDs](https://www.activtrades.com/en/news/how-to-use-volatility-based-position-sizing-when-trading-with-cfds)

### Geopolitical & Current Crisis
- [How Will the Iran Conflict Impact Oil Prices? (Goldman Sachs)](https://www.goldmansachs.com/insights/articles/how-will-the-iran-conflict-impact-oil-prices)
- [Goldman Sachs Raises Oil Price Forecast](https://oilprice.com/Latest-Energy-News/World-News/Goldman-Sachs-Raises-Oil-Price-Forecast-as-Middle-East-Conflict-Escalates.html)
- [Goldman Sachs Resets 2026 Oil Forecast (TheStreet)](https://www.thestreet.com/investing/goldman-sachs-resets-oil-price-target-for-rest-of-2026)
- [Oil Price Forecast 2026 (J.P. Morgan)](https://www.jpmorgan.com/insights/global-research/commodities/oil-prices)
- [Iran War Threatens Energy Markets (Al Jazeera)](https://www.aljazeera.com/news/2026/3/8/iran-war-threatens-prolonged-impact-on-energy-markets-as-oil-prices-rise)
- [What Does the Iran War Mean for Global Energy Markets? (CSIS)](https://www.csis.org/analysis/what-does-iran-war-mean-global-energy-markets)
- [How Strait of Hormuz Closure Becomes Tipping Point (CNBC)](https://www.cnbc.com/2026/03/11/strait-of-hormuz-closure-shipping-economy-oil.html)
- [Economic Impact of 2026 Iran War (Wikipedia)](https://en.wikipedia.org/wiki/Economic_impact_of_the_2026_Iran_war)
- [Multi-Asset Playbook for Geopolitical Shocks (MSCI)](https://www.msci.com/research-and-insights/blog-post/a-multi-asset-playbook-for-geopolitical-shocks-and-oil-supply-disruption)
- [Middle East Conflict: Energy Risks (BlackRock)](https://www.blackrock.com/corporate/insights/blackrock-investment-institute/publications/middle-east-conflict-2026)
- [Oil Trading Playbook: Key Levels (Investing.com)](https://www.investing.com/news/commodities-news/oil-trading-playbook-key-levels-to-watch-now-4537076)
- [Oil Market Volatility Eases After Supply Shock](https://www.hngn.com/articles/270030/20260311/oil-market-volatility-eases-after-initial-supply-shock-iran-conflict.htm)
- [Algorithmic Traders Fully Long Crude (FutuNN)](https://news.futunn.com/en/post/69828052/algorithmic-traders-are-fully-invested-in-long-positions-on-crude)
- [Oil Surges Past $100 (The National)](https://www.thenationalnews.com/business/energy/2026/03/12/oil-surges-past-100-as-iranian-strikes-on-energy-infrastructure-rattles-markets/)
- [Historical Oil Price Rallies (BusinessToday)](https://www.businesstoday.in/markets/stocks/story/from-iranian-revolution-and-gulf-war-to-libyan-civil-war-a-look-at-25-300-oil-price-rallies-518725-2026-03-02)
- [1990 Oil Price Shock (Wikipedia)](https://en.wikipedia.org/wiki/1990_oil_price_shock)
- [Oil Price Behavior Before/After Military Conflicts (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S0360544216319077)

### Technical Indicators
- [Best Technical Indicators for Crude Oil (Vantage)](https://www.vantagemarkets.com/en-za/academy/best-indicator-for-crude-oil/)
- [Technical vs Fundamental in Commodity Trading (JMSR)](https://www.jmsr-online.com/article/technical-analysis-vs-fundamental-analysis-a-comparative-study-of-bollinger-bands-rsi-and-macd-against-fundamental-factors-in-commodity-trading-82/)
- [Optimizing Bollinger Bands for Commodity Futures (SAGE)](https://journals.sagepub.com/doi/10.1177/09721509251328555)
- [Keltner Channel Breakout Strategies](https://tradefundrr.com/keltner-channel-breakout-strategies/)
- [VWAP Reversion Strategy](https://masterytraderacademy.com/vwap-reversion-strategy-trading-guide/)
- [Using ATR to Adjust Position Size](https://quantstrategy.io/blog/using-atr-to-adjust-position-size-volatility-based-risk/)

### Oil-Specific Indicators & Fundamentals
- [What API and EIA Data Reveal About Crude Oil Markets (CME)](https://www.cmegroup.com/openmarkets/energy/2025/What-API-and-EIA-Data-Reveal-About-Crude-Oil-Markets.html)
- [Crude Oil Spreads Explained (Switch Markets)](https://www.switchmarkets.com/learn/crude-oil-spreads)
- [Contango and Backwardation (Schwab)](https://www.schwab.com/learn/story/contango-and-backwardation-explained)
- [Introduction to Crack Spreads (CME)](https://www.cmegroup.com/education/articles-and-reports/introduction-to-crack-spreads)
- [Spread Trading Brent vs WTI](https://www.alphaexcapital.com/commodities/energy-commodities/crude-oil-trading/spread-trading-brent-vs-wti)
- [Oil Inventory Reports API EIA](https://www.alphaexcapital.com/commodities/energy-commodities/crude-oil-trading/oil-inventory-reports-api-eia)
- [Understanding the Oil Data Report (CME)](https://www.cmegroup.com/education/courses/learn-about-key-economic-events/understanding-the-oil-data-report)
- [Natural Gas Calendar Spread Options (CME)](https://www.cmegroup.com/education/courses/introduction-to-natural-gas/natural-gas-calendar-spread-options.html)
- [Time Traveling the Natural Gas Market (ICE)](https://www.ice.com/white-paper/natural-gas-market-storage-dynamics-and-alpha-generation)

### Academic & Quantitative Research
- [Trading on Mean-Reversion in Energy Futures (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S014098831500208X)
- [Momentum and Mean-Reversion in Commodity Spot and Futures (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S2405851315300416)
- [Mean-Reverting Statistical Arbitrage in Crude Oil Markets (MDPI)](https://www.mdpi.com/2227-9091/12/7/106)
- [Do Momentum and Reversal Strategies Work in Commodity Futures? (ResearchGate)](https://www.researchgate.net/publication/329135009_Do_Momentum_and_Reversal_Strategies_Work_in_Commodity_Futures_A_Comprehensive_Study)
- [Time Series Momentum Effect (Quantpedia)](https://quantpedia.com/strategies/time-series-momentum-effect)
- [Momentum Effect in Commodities (Quantpedia)](https://quantpedia.com/strategies/momentum-effect-in-commodities)
- [Trading WTI/Brent Spread (Quantpedia)](https://quantpedia.com/strategies/trading-wti-brent-spread)
- [Deep Learning for Crude Oil and Precious Metals (Springer)](https://link.springer.com/article/10.1186/s40854-024-00637-z)
- [Hybrid XGBoost-LSTM for Oil Price Prediction (MDPI)](https://www.mdpi.com/1996-1073/18/9/2246)
- [Deep Learning Ensemble for Brent and WTI (MDPI)](https://www.mdpi.com/1099-4300/27/11/1122)
- [Structural ML Model for Oil Forecasting (Taylor & Francis)](https://www.tandfonline.com/doi/full/10.1080/10168737.2025.2520314)
- [Myths and Realities about Algorithmic Oil Traders (Oxford Energy)](https://www.oxfordenergy.org/wpcms/wp-content/uploads/2024/03/Energy-Quantamentals-%5EN2-Myths-and-Realities-about-CTAs-Final.pdf)
- [CTA Trend-Following Performance (AIForAlpha)](https://aiforalpha.com/dist/img/Spotlight_CTA_Trend_Followers.pdf)
- [Convexity of Trend Following (Hedge Fund Journal)](https://thehedgefundjournal.com/the-convexity-of-trend-following/)
- [Trading Strategies Backtest on Crude Oil (UT Austin)](https://repositories.lib.utexas.edu/items/10b8112f-edf7-4c14-98e0-266b9d0a2fc8)
- [Pairs Trading for Oil Futures (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4601806)
- [Intraday Return Predictability - EIA Announcements (SSRN)](https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID3907324_code2537556.pdf?abstractid=3822093&mirid=1)

### Natural Gas
- [Natural Gas Trading Strategy Explained (PapersWithBacktest)](https://paperswithbacktest.com/wiki/natural-gas-trading-strategy)
- [Gas Algorithmic Trading (PocketOption)](https://pocketoption.com/blog/en/knowledge-base/regulation-and-safety/gas-algorithmic-trading/)
- [NG Futures Trading Strategies (The Robust Trader)](https://therobusttrader.com/natural-gas-futures-ng-trading-strategies/)
- [Truth About Commodity Seasonality (FXEmpire)](https://www.fxempire.com/education/article/the-truth-about-trading-commodity-seasonality-what-still-works-and-what-doesnt-1531337)
- [Understanding NG Spreads and Storage (CME)](https://www.cmegroup.com/education/courses/introduction-to-natural-gas/understanding-natural-gas-risk-management-spreads-storage)

### CFD Specifications
- [Oil Trading 2026: How to Trade Crude Oil CFDs (TIOMarkets)](https://tiomarkets.com/article/oil-trading-2026-how-to-trade-crude-oil-cfds)
- [WTI Oil CFD Trading (Dukascopy)](https://www.dukascopy.com/europe/english/cfd/range-of-markets/wti-oil-cfd-trading/)
- [Crude Oil Trading Complete Guide (Equiti)](https://www.equiti.com/sc-en/news/trading-ideas/crude-oil-trading-complete-guide--strategies/)
- [Oil Trading Guide 2026 (VT Markets)](https://www.vtmarkets.com/discover/how-to-trade-oil/)
