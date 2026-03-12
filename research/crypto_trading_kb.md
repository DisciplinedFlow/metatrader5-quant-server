# Crypto Trading Knowledge Base
## Psychology, Risk Management & Strategy for Quantitative Crypto Traders
### March 2026 | Compiled from books, crash post-mortems, on-chain research, and quant strategy papers

---

## Table of Contents
1. [Universal Crypto Trading Principles](#1-universal-crypto-trading-principles)
2. [Trading in the Zone — Mark Douglas (Applied to Crypto)](#2-trading-in-the-zone--mark-douglas)
3. [The Crypto Trader — Glen Goodman](#3-the-crypto-trader--glen-goodman)
4. [Digital Gold — Nathaniel Popper (Early Bitcoin Lessons)](#4-digital-gold--nathaniel-popper)
5. [Cryptoassets — Chris Burniske & Jack Tatar](#5-cryptoassets--chris-burniske--jack-tatar)
6. [Lessons from Major Crypto Crashes](#6-lessons-from-major-crypto-crashes)
7. [Position Sizing in Crypto (Higher Volatility Than Forex)](#7-position-sizing-in-crypto)
8. [Psychology of 24/7 Markets](#8-psychology-of-247-markets)
9. [Dealing with Extreme Volatility (20%+ Moves)](#9-dealing-with-extreme-volatility)
10. [BTC-Altcoin Correlation & Dominance Rotation](#10-btc-altcoin-correlation--dominance-rotation)
11. [Funding Rate & Basis Trading](#11-funding-rate--basis-trading)
12. [Liquidation Cascades & How to Profit](#12-liquidation-cascades--how-to-profit)
13. [On-Chain Analysis & Sentiment Indicators](#13-on-chain-analysis--sentiment-indicators)
14. [Crypto Market Cycles & Seasonality](#14-crypto-market-cycles--seasonality)
15. [Quant-Specific Crypto Strategies](#15-quant-specific-crypto-strategies)
16. [Synthesized Rules for the Quantitative Crypto Trader](#16-synthesized-rules)

---

## 1. Universal Crypto Trading Principles

### The Crypto Market Is Not the Stock Market
- **Volatility is 3-5x higher** — BTC daily moves of 5-10% are normal; altcoins can move 20-50% in hours
- **24/7 operation** — no closing bell, no weekend break, no circuit breakers on most exchanges
- **Fragmented liquidity** — trading spread across 100+ exchanges with different order books, creating arbitrage but also execution risk
- **Retail-dominated** — institutional participation growing but retail still drives extreme sentiment swings
- **Narrative-driven** — memes, tweets, and influencers move prices more than fundamentals
- **Counterparty risk is real** — exchanges fail (Mt. Gox, FTX), stablecoins depeg (UST, USDC during SVB), protocols get hacked

### The Five Truths of Crypto Trading
1. **Anything can happen** — 90% crashes, 1000% rallies, exchange collapses, regulatory bans — all have happened
2. **The four-year cycle is real until it isn't** — halving cycles have driven BTC but each cycle shows diminishing returns and structural changes
3. **Leverage kills in crypto** — the single biggest destroyer of crypto accounts is overleveraging during volatile moves
4. **On-chain data provides edges traditional markets lack** — transparent blockchains reveal whale movements, exchange flows, and network health in real time
5. **Survival is the only prerequisite for success** — every OG crypto trader's #1 lesson is "don't go to zero"

---

## 2. Trading in the Zone — Mark Douglas

**Core thesis:** Trading success is 80% psychology and 20% strategy. In crypto, where volatility amplifies every emotional response, this ratio may be 90/10.

### Douglas's Seven Principles (Crypto-Adapted)

**Rule 1: Objectively identify your edges.**
- In crypto, edges include: funding rate arbitrage, liquidation cascade front-running, on-chain flow analysis, cross-exchange price discrepancies, and regime-adaptive momentum/mean-reversion switching
- An edge is NOT a hunch about which altcoin will moon next

**Rule 2: Predefine the risk of every trade.**
- In crypto this means: know your exact dollar loss before entry, account for slippage in thin markets, and NEVER hold leveraged positions without stops
- "I'll just hold through the dip" has destroyed more crypto accounts than any other sentence

**Rule 3: Completely accept the risk or don't take the trade.**
- If a 15% drawdown on a position would cause you to panic-sell at 3 AM, the position is too large
- Crypto's 24/7 nature means you WILL wake up to unexpected moves — size accordingly

**Rule 4: Act on your edges without reservation or hesitation.**
- When your system signals, execute. The fear of another crash ("what if this is 2018 again?") causes traders to miss the majority of profitable setups
- Hesitation in crypto is especially costly because moves happen faster

**Rule 5: Pay yourself as the market makes money available.**
- Take partial profits. Crypto's parabolic moves create massive unrealized gains that evaporate in hours
- "I should have sold" is the universal crypto regret — systematic partial closes prevent it

**Rule 6: Continually monitor your susceptibility to errors.**
- In crypto: Are you checking prices every 5 minutes? Trading at 2 AM? Adding to losers because "it's on sale"? These are error patterns
- The 24/7 market is an error amplifier — every emotional weakness gets exploited

**Rule 7: Understand the absolute necessity of these principles.**
- Douglas: "A trader with a mediocre strategy and great risk model becomes fairly successful. A trader with a great strategy and mediocre risk model goes bankrupt."
- This is triply true in crypto where a single overleveraged position can liquidate your entire account

### The Probability Mindset
- **Think in distributions, not individual outcomes** — any single crypto trade is essentially random
- **Your edge plays out over 100+ trades** — not on the next trade
- **Every trade outcome is independent** — the market doesn't owe you a winner after five losers

---

## 3. The Crypto Trader — Glen Goodman

**Background:** Glen Goodman is a former BBC and ITV financial journalist who became a full-time trader. His book is the most practical crypto-specific trading guide, focused on risk management and psychological discipline.

### Core Principles

**Rule 1: Fear and greed drive crypto prices to extremes — creating opportunities for the disciplined.**
- The crypto Fear & Greed Index (0-100) is a quantifiable sentiment measure
- Extreme Fear (<20) historically correlates with buying opportunities
- Extreme Greed (>80) historically precedes corrections
- **Do NOT use this as a timing tool** — use it as a position sizing modifier

**Rule 2: Stop-losses are non-negotiable in crypto.**
- Goodman uses volatility-based stops: wider in high-vol environments, tighter in low-vol
- His stops are placed at technical invalidation levels, not arbitrary percentages
- In crypto: set stops at 8-15% below entry for spot positions depending on asset volatility
- For leveraged positions: stop must be calculated so max loss = predetermined dollar amount

**Rule 3: Winners must be significantly larger than losers.**
- Goodman's average winner is 3x his average loser
- This is the ONLY way to be profitable with a sub-50% win rate
- In crypto where volatility is extreme, this asymmetry is achievable by letting parabolic moves run

**Rule 4: The market is always right — you are not.**
- "I know this project is worth more" is the #1 rationalization for holding losers
- Price is truth. If BTC is dropping, it's dropping — your fundamental thesis doesn't matter in the short term
- Goodman's rule: if your stop is hit, you exit. Period. No rationalization.

**Rule 5: Crowd psychology creates predictable patterns.**
- Crypto crowds are more extreme than any other market — FOMO buying and panic selling create reliable overextensions
- These overextensions are tradeable — but only with strict risk management
- The crowd is almost always wrong at extremes: maximum bullishness = top, maximum despair = bottom

---

## 4. Digital Gold — Nathaniel Popper (Early Bitcoin Lessons)

**Context:** Popper's 2015 book chronicles Bitcoin from 2008-2014 through the eyes of early adopters, entrepreneurs, and ideologues. The lessons from this era remain startlingly relevant.

### Lessons from the OG Era (2010-2014)

**Lesson 1: Technical brilliance doesn't prevent operational catastrophe.**
- Mt. Gox founder Mark Karpeles was technically competent but operationally negligent — didn't track a hacker siphoning 850,000 BTC over years
- Charlie Shrem at BitInstant let his company collapse through personal distractions
- **Trading application:** Your strategy can be excellent, but poor execution infrastructure (wrong exchange, bad API, no redundancy) will kill you

**Lesson 2: The ultra-wealthy move markets.**
- Bitcoin's real price discovery only began when wealthy individuals (Winklevoss twins, Fortress Investment Group's Peter Briger, PayPal's David Marcus) entered in 2013
- **Trading application:** Watch for institutional flow signals — ETF inflows/outflows, Grayscale premium, whale wallet movements. These actors move price more than retail

**Lesson 3: Early volatility was a feature, not a bug.**
- BTC went from $0.06 to $29.38 (+49,000%) in under a year (2010-2011), then crashed to $2.14 (-93%)
- Every single early Bitcoin holder who survived learned the same lesson: **conviction without overleveraging**
- The ones who got rich were NOT the best traders — they were the ones who held through 80%+ drawdowns with position sizes they could stomach

**Lesson 4: Counterparty risk is the silent killer.**
- Mt. Gox handled 70% of global BTC volume before collapsing
- Today's equivalent: keep only trading capital on exchanges, never your entire stack
- **Not your keys, not your coins** remains the most important risk management rule in crypto

**Lesson 5: Regulatory events create the largest dislocations.**
- China's 2013 ban, China's 2017 exchange shutdown, China's 2021 mining ban — each created massive selling followed by recovery
- These events are not tradeable in real-time but the recovery patterns are predictable: panic selling overshoots, followed by slow accumulation, followed by resumption of the prior trend

---

## 5. Cryptoassets — Chris Burniske & Jack Tatar

**Background:** Burniske (ARK Invest, then Placeholder VC) wrote the first serious investment framework for valuing crypto assets. Published 2017, the framework remains foundational.

### Key Investment Principles

**Principle 1: Classify before you trade.**
- **Cryptocurrencies** (BTC, XMR): Digital money — valued by monetary premium, network effects, and stock-to-flow
- **Crypto commodities** (ETH as gas): Digital raw materials consumed by applications — valued by demand for computation/storage
- **Crypto tokens** (governance, utility): Access rights or governance power — valued by protocol revenue and usage metrics
- **Trading implication:** Don't trade a governance token like you'd trade BTC. Different assets have different volatility profiles, correlation structures, and fundamental drivers

**Principle 2: Evaluate network fundamentals, not just price.**
- Network Value-to-Transactions (NVT) ratio: crypto's P/E equivalent
- Developer activity: GitHub commits, active contributors
- Active addresses and transaction volume: usage metrics
- **Trading implication:** Divergence between rising network activity and falling price = accumulation opportunity. Rising price with declining activity = distribution warning

**Principle 3: Diversification across crypto categories reduces correlation risk.**
- BTC, ETH, DeFi blue chips, and stablecoins have different risk profiles
- Holding 100% in altcoins exposes you to maximum beta against BTC
- The safest crypto portfolio for a trader: 50%+ in BTC/ETH, 30% in large-cap alts, 20% in high-conviction small caps

---

## 6. Lessons from Major Crypto Crashes

### Mt. Gox Collapse (February 2014)
**What happened:** Mt. Gox, handling ~70% of global BTC transactions, revealed loss of 850,000 BTC (~$450M at the time). Filed for bankruptcy.

**Root cause:** Centralized custody without audits, opaque operations, insufficient security, no regulatory oversight. A hacker exploited a transaction malleability bug for years undetected.

**Trading lessons:**
1. **Never keep more than your active trading capital on any single exchange** — diversify across venues
2. **Exchange volume dominance is a risk indicator, not a safety signal** — 70% market share meant 70% systemic risk
3. **The recovery took 3 years** — BTC didn't reclaim its 2013 high until 2017. Time horizons in crypto are measured in years, not weeks

### 2018 Bear Market (January 2018 - December 2018)
**What happened:** BTC dropped from $19,783 to $3,122 (-84%). Total crypto market cap fell from $830B to $100B. Most altcoins lost 90-99%.

**Root cause:** ICO bubble burst. Thousands of worthless tokens collapsed. Retail FOMO buying at the top followed by forced selling.

**Trading lessons:**
4. **Bear markets in crypto are longer and deeper than any other asset class** — 84% drawdowns are NORMAL, not anomalies
5. **Altcoins amplify BTC moves by 2-5x on the downside** — if BTC drops 50%, expect altcoins to drop 80-95%
6. **The bottom comes when everyone has given up** — BTC $3,122 was reached when search interest, trading volume, and social media activity all hit multi-year lows
7. **Never use leverage in a bear market** — even correct directional bets get liquidated by volatile bear market rallies (30-40% bear market bounces are common)

### Terra/Luna Collapse (May 2022)
**What happened:** UST (algorithmic stablecoin) depegged from $1 to $0. Luna crashed from $80 to $0.0001. $60B in value evaporated in 72 hours.

**Root cause:** Algorithmic stablecoin mechanism failed under selling pressure. The "death spiral" — UST depeg caused Luna minting, which crashed Luna price, which further depegged UST.

**Trading lessons:**
8. **"Too good to be true" yields are too good to be true** — Anchor Protocol's 20% APY on UST was the red flag. Sustainable yield in DeFi is 2-8%, not 20%
9. **Algorithmic stability mechanisms fail at the extremes they're designed for** — stress testing in calm markets proves nothing
10. **Contagion is rapid** — Luna's collapse caused cascading liquidations across DeFi, hitting 3AC, Celsius, Voyager, and eventually contributing to FTX's liquidity crisis
11. **Stablecoin risk is real and must be managed** — diversify stablecoin holdings (USDT, USDC, DAI), monitor depeg early warning signals (Curve pool imbalances, redemption delays)

### FTX Collapse (November 2022)
**What happened:** FTX, the #2 crypto exchange, collapsed in 48 hours after Alameda Research's balance sheet was revealed to be backed primarily by FTT (FTX's own token). Customer funds (~$8B) were misappropriated.

**Root cause:** Commingling customer funds with Alameda's trading operations. Heavy reliance on self-created, illiquid tokens (FTT, Serum) as collateral. No risk controls, no audits.

**Trading lessons:**
12. **Exchange tokens as collateral = house of cards** — any exchange backing its balance sheet with its own token is a circular dependency waiting to collapse
13. **Due diligence on exchanges is part of risk management** — check: proof of reserves, regulatory status, corporate structure transparency, insurance fund size
14. **Withdrawal speed is a canary in the coal mine** — when an exchange starts delaying withdrawals, get your funds out immediately. Don't wait for "official explanations"
15. **The "smart money" isn't always smart** — SBF's Alameda started with a legitimate arbitrage edge (the "kimchi premium" between US and Korean exchanges), but success bred hubris and fraud. The lesson: past returns don't validate current risk management

---

## 7. Position Sizing in Crypto

### Why Crypto Requires Different Sizing Than Forex

| Factor | Forex (XAUUSD) | Crypto (BTC) | Crypto (Altcoins) |
|--------|----------------|--------------|-------------------|
| Avg daily volatility | 1-2% | 3-5% | 5-15% |
| Max drawdown (yearly) | 10-20% | 50-80% | 80-99% |
| Liquidity depth | Very deep | Moderate | Often thin |
| Correlation within asset class | Low-moderate | HIGH (BTC dominates) | Very high with BTC |
| Leverage available | 50-500x | 1-125x | 1-50x |
| Stop-loss hunting | Moderate | Severe | Extreme |

### Position Sizing Rules

**Rule 1: The 1% Rule (not 2%).**
- In traditional markets, 2% risk per trade is standard. In crypto, use 1% maximum
- Crypto's higher volatility means a 2% risk rule results in drawdowns equivalent to a 4-5% rule in forex
- Formula: Position Size = (Account * 0.01) / (Entry - Stop Loss)

**Rule 2: Volatility-adjusted sizing.**
- Use ATR to scale position size inversely with volatility
- High ATR (wild market) = smaller position. Low ATR (calm market) = larger position
- Target constant dollar risk: if ATR doubles, halve your position size

**Rule 3: Correlation-adjusted total exposure.**
- Five altcoin positions at 20% each = 100% crypto exposure, NOT five independent bets
- When BTC dumps, everything dumps. Treat correlated positions as a single bet
- **Maximum total crypto exposure: 5-6 independent risk units** — where "independent" accounts for BTC correlation

**Rule 4: The Kelly Criterion (use Half-Kelly).**
- Full Kelly: f* = (bp - q) / b, where b = win/loss ratio, p = win rate, q = loss rate
- Full Kelly is too aggressive for crypto — drawdowns will be psychologically unbearable
- **Half-Kelly offers 75% of the maximum growth rate with only 25% of the variance** — a 3x better risk-adjusted return
- Example: 55% win rate, 2:1 R:R = Full Kelly 32.5%, Half-Kelly 16.25%

**Rule 5: Leverage caps.**
- Spot trading: 1x (no leverage) is safest for most strategies
- Futures/perps: 1-3x maximum for swing trading, up to 5x for scalping with tight stops
- Never size a leveraged position where the distance to liquidation is less than 2x your expected max adverse excursion
- "Leverage is how smart people go broke in crypto" — universal OG trader wisdom

**Rule 6: Tiered stop-losses for spot positions.**
- Exit 33% at -5%, 33% at -10%, remaining 34% at -15%
- This prevents full loss from stop-hunts while limiting maximum damage
- Alternatively: use a single stop at the technical invalidation level, but SIZE the position so that stop = 1% account loss

---

## 8. Psychology of 24/7 Markets

### The Unique Psychological Challenges

**Challenge 1: No forced breaks.**
- Traditional markets force rest (weekends, holidays). Crypto never stops
- Sleep deprivation is the #1 cause of bad crypto trading decisions
- **Rule:** Set hard trading hours. If you trade London + NY sessions (07:00-17:00 UTC), those are your hours. What happens at 3 AM is not your problem if your stops are set

**Challenge 2: FOMO is constant.**
- In a 24/7 market, there's always something moving, always a coin pumping 50%
- FOMO leads to: entering without analysis, oversizing "because it's moving fast," abandoning your strategy for the hot narrative
- **Rule:** If you missed a move, you missed it. The next setup will come. Chasing in crypto is how accounts die

**Challenge 3: Overtrading.**
- The always-open market invites compulsive trading
- Studies show crypto traders who check prices more than 4x/day make worse decisions
- **Rule:** Define maximum trades per day (3-5 for active trading, 1-2 for swing trading). Once you hit the cap, stop

**Challenge 4: Weekend volatility traps.**
- Weekends see 20-25% lower trading volume, creating thinner books and larger moves
- Institutional desks are closed, leaving retail-dominated order flow
- **Rule:** Reduce position size by 30-50% going into weekends, or close leveraged positions entirely

**Challenge 5: The dopamine cycle.**
- Crypto's extreme volatility triggers dopamine responses similar to gambling
- Winning streaks create overconfidence; losing streaks create revenge trading
- **Rule:** Track your emotional state in your trading journal. If you notice excitement or anger, stop trading for at least 4 hours

### The Antidote: Systematic Execution
- The ONLY reliable solution to 24/7 market psychology is automation
- Define your rules. Code them. Let the system execute
- Human intervention should be limited to: system monitoring, parameter adjustment during regime changes, and emergency risk management (exchange failure, black swan events)

---

## 9. Dealing with Extreme Volatility (20%+ Moves)

### Flash Crash Anatomy
A typical crypto flash crash follows this sequence:
1. **Trigger event** — news, whale sell, exchange issue, or regulatory announcement
2. **Initial sell-off** — 5-10% drop triggers leveraged long liquidations
3. **Liquidation cascade** — forced selling accelerates the move, thin order books mean price falls further per unit sold
4. **Liquidity vacuum** — market makers pull orders, bid side evaporates, spreads widen to 2-5%
5. **Capitulation wick** — price overshoots to extreme levels as stop-losses and liquidations cascade
6. **Snap-back** — aggressive buyers step in at extreme discount, price recovers 50-80% of the move within hours
7. **Settling** — market finds new equilibrium, usually 10-30% below the pre-crash level

### Rules for Trading Extreme Volatility

**Rule 1: Never catch the falling knife.**
- Wait for the capitulation wick and initial bounce before entering
- Confluence signals for a bottom: RSI < 20, volume spike 3-5x normal, Bollinger Band breach, historical support level, funding rate extremely negative
- **Wait for a retest** of the bounce low — if it holds, the bottom is more likely confirmed

**Rule 2: Cut leverage before news events.**
- Known volatility catalysts: FOMC meetings, CPI releases, halving events, major protocol upgrades, regulatory hearings
- Unknown catalysts can't be prepared for — this is why baseline leverage should always be conservative

**Rule 3: Widen stops during high-vol regimes.**
- If ATR is 2x its 20-day average, your stops should be 2x wider
- This means your position size must be 2x smaller to maintain constant dollar risk
- The WORST mistake: normal-width stops in a high-vol environment = getting stopped out on noise

**Rule 4: The "do nothing" option is valid.**
- When BTC drops 20% in a day, the correct action for most traders is: nothing
- Your existing positions should have stops in place. New positions should wait for volatility to subside
- "The best traders I know do nothing most of the time" — applies even more in crypto flash crashes

**Rule 5: Use limit orders, never market orders, during crashes.**
- Market orders during a flash crash can fill 5-10% away from the displayed price
- Limit orders may not fill, but at least they won't fill at catastrophic levels
- Place a ladder of limit buy orders at key support levels BEFORE crashes happen

**Rule 6: Separate your crash fund.**
- Keep 10-20% of your trading capital in stablecoins, uninvested
- Deploy this ONLY during extreme fear events (Fear & Greed Index < 15, 20%+ BTC drop)
- This "dry powder" approach turns crashes from threats into opportunities

---

## 10. BTC-Altcoin Correlation & Dominance Rotation

### The Four Market Regimes (BTC Dominance Framework)

| BTC Price | BTC Dominance | Market Phase | Strategy |
|-----------|---------------|-------------|----------|
| Rising | Rising | BTC bull run (early cycle) | Long BTC, avoid alts |
| Rising | Falling | Alt season (late cycle) | Rotate into high-beta alts |
| Falling | Rising | Risk-off / flight to safety | Reduce all exposure, or short alts |
| Falling | Falling | Broad bear market | Cash/stables, minimal exposure |

### Correlation Rules for Quant Traders

**Rule 1: BTC is the tide that lifts (or sinks) all boats.**
- In bear markets, BTC-altcoin correlation approaches 0.90+. Diversification is an illusion
- In bull markets, correlation drops to 0.50-0.70 as individual narratives drive altcoin performance
- **Quantitative implication:** Your risk model must account for BTC correlation. Five "independent" altcoin positions are really 1-2 independent bets in a correlated market

**Rule 2: Altcoin beta is asymmetric.**
- Altcoins typically rally 2-5x more than BTC on the way up
- But they fall 2-5x more on the way down
- **This asymmetry is tradeable:** long alts when BTC is in confirmed uptrend + dominance falling; exit alts before BTC shows weakness

**Rule 3: BTC dominance breakouts signal regime changes.**
- BTC.D rising above 60%: alt season is over, rotate to BTC or stables
- BTC.D falling below 50%: capital rotating into alts, increase alt exposure
- BTC.D moving sideways: no clear signal, maintain balanced exposure
- **Combine with BTC price direction for the four-quadrant model above**

**Rule 4: ETH/BTC is the leading indicator.**
- ETH/BTC ratio rising = risk appetite increasing, alts will follow
- ETH/BTC ratio falling = risk appetite decreasing, rotate to BTC or cash
- ETH often leads altcoin moves by 24-72 hours

**Rule 5: Sector rotation happens within crypto too.**
- L1s, DeFi, gaming, AI, memecoins rotate in and out of favor
- Capital flows from narrative to narrative within a bull market
- Track sector performance relative to BTC to identify active rotations

---

## 11. Funding Rate & Basis Trading

### How Perpetual Futures Funding Rates Work
- Perpetual contracts have no expiry — funding rates keep them anchored to spot price
- **Positive funding rate:** Longs pay shorts. Market is bullish-positioned
- **Negative funding rate:** Shorts pay longs. Market is bearish-positioned
- Funding is typically charged every 8 hours (00:00, 08:00, 16:00 UTC on most exchanges)

### Funding Rate Arbitrage Strategy

**The Core Trade: Spot-Perp Basis Arbitrage**
1. Buy 1 BTC on spot market
2. Short 1 BTC on perpetual futures
3. Net market exposure: zero (delta-neutral)
4. When funding is positive: you collect funding payments from longs
5. Annualized returns: 10-30% in normal conditions, 50-100%+ during euphoric markets

**Performance Data:**
- Documented returns of up to 115.9% over six months during high-funding periods
- One ML-enhanced approach (predicting funding rates 4 hours ahead) generated 31% annual returns with Sharpe ratio of 2.3
- Maximum documented loss: 1.92% during adverse conditions

### Funding Rate as a Sentiment Indicator

**Rule 1: Extreme positive funding = market overheated.**
- When BTC funding exceeds 0.1% per 8 hours (equivalent to ~130% annualized), the market is extremely leveraged long
- This precedes corrections more often than not
- **Don't short based on funding alone** — but reduce long exposure and tighten stops

**Rule 2: Extreme negative funding = market washed out.**
- When BTC funding goes deeply negative (-0.05% or below), shorts are paying longs heavily
- This often coincides with local bottoms — the short side is crowded
- **Consider building long positions when funding is deeply negative + price at support**

**Rule 3: Funding rate divergence between exchanges signals dislocation.**
- When Binance funding is +0.05% but Bybit is +0.15%, there's an arbitrage opportunity
- Cross-exchange funding arb: long on low-funding exchange, short on high-funding exchange
- Requires fast execution and accounts on multiple venues

### Basis Trading (Quarterly Futures)
- Quarterly futures trade at a premium (contango) during bull markets and discount (backwardation) during bears
- Annualized basis of 15-30% is common during bull markets
- **Cash-and-carry trade:** Buy spot, short quarterly future, collect the basis as the future converges to spot at expiry
- Lower risk than perp funding arb because the convergence is guaranteed at expiry

---

## 12. Liquidation Cascades & How to Profit

### Understanding the Mechanics
A liquidation cascade occurs when:
1. Price moves against heavily leveraged positions
2. Exchange liquidation engines force-close positions at market
3. These forced sales push price further in the same direction
4. Which triggers MORE liquidations at the next level
5. Creating a domino effect that can move BTC 10-20% in minutes

### Monitoring Liquidation Levels

**Data sources:**
- CoinGlass liquidation heatmaps: show clusters of estimated liquidation prices
- Open interest changes: rapid OI decline = liquidations happening
- Funding rate spikes: extreme funding followed by rapid normalization = cascade in progress
- Exchange-specific liquidation feeds: Binance, Bybit publish real-time liquidation data

### Trading the Cascade

**Strategy 1: Post-Cascade Bottom Fishing**
- After a long liquidation cascade (cascade of long liquidations), the market is "cleansed" of leveraged longs
- Entry signals: funding rate flips negative, OI drops 20%+, volume spike 3-5x average, price hits known support
- Enter with limit orders at support, small position, tight stop below the cascade low
- Risk: the cascade isn't over — always use stops

**Strategy 2: Short Squeeze Detection**
- After a short liquidation cascade (cascade of short liquidations), shorts have been wiped out
- The remaining order flow is naturally bullish as short covering creates buying pressure
- Entry: long after price breaks above the pre-cascade range high with volume confirmation
- These breakouts can be explosive because there's no overhead resistance from shorts

**Strategy 3: Liquidation Level Front-Running (Advanced)**
- Identify clusters of estimated liquidation prices using heatmap data
- These clusters act as magnets — price tends to gravitate toward large liquidation clusters
- Enter positions in the direction of the nearest large cluster
- **Caution:** This is a market-making style approach that requires fast execution and strict risk management

### Liquidation Cascade Rules

**Rule 1: The biggest liquidation cascades happen at all-time highs and cycle lows.**
- At ATHs: max leverage, max euphoria, max liquidation fuel
- At cycle lows: max despair shorts get squeezed by relief rallies

**Rule 2: Cascades create the best risk/reward entries of the entire cycle.**
- March 2020 COVID crash: BTC dropped to $3,800, then rallied to $69,000 (18x)
- November 2022 FTX crash: BTC dropped to $15,500, then rallied to $73,000+ (4.7x)
- The pattern: cascading liquidation creates extreme overshoots that take months/years to recover but ALWAYS recover (for BTC specifically)

**Rule 3: Volume tells you when the cascade is ending.**
- Peak volume during the cascade = capitulation
- Declining volume as price stabilizes = selling exhaustion
- Rising volume on the bounce = new buyers stepping in

---

## 13. On-Chain Analysis & Sentiment Indicators

### On-Chain Signals for Quant Traders

**Signal 1: Exchange Net Flows**
- Large inflows to exchanges = selling pressure incoming (moving to exchange to sell)
- Large outflows from exchanges = accumulation (moving to cold storage to hold)
- **Metric:** Net exchange flow (inflows minus outflows) over 7-day rolling average
- **Divergence signal:** Price rising + net exchange inflows increasing = distribution. Be cautious

**Signal 2: Whale Wallet Movements**
- Wallets holding 1,000+ BTC are "whales"
- Individual transactions are noise; sustained directional flow is signal
- **Metric:** 30-day rolling accumulation/distribution of whale wallets
- **Actionable:** When whales accumulate while price is flat/declining = bullish divergence

**Signal 3: Miner Revenue & Capitulation**
- Miners are forced sellers (they have operational costs in fiat)
- When mining revenue drops below operational costs, miners sell BTC reserves
- Hash Ribbon indicator: when 30-day MA of hash rate crosses above 60-day MA after a decline = miner capitulation over, historically bullish

**Signal 4: MVRV Ratio (Market Value to Realized Value)**
- MVRV > 3.5: Market is overvalued relative to its cost basis — distribution zone
- MVRV < 1.0: Market is undervalued — accumulation zone (historically near cycle bottoms)
- **One of the most reliable on-chain indicators for cycle positioning**

### Sentiment Indicators

**Fear & Greed Index (0-100)**
- Components: volatility (25%), market momentum/volume (25%), social media (15%), dominance (10%), trends (10%), surveys (15%)
- **Trading rule:** When F&G < 20 for 5+ consecutive days, begin scaling into long positions. When F&G > 80 for 5+ consecutive days, begin scaling out

**Long/Short Ratio**
- Ratio > 1.0 = more longs than shorts (bullish sentiment)
- Ratio < 1.0 = more shorts than longs (bearish sentiment)
- **Contrarian signal:** Extreme readings (>2.0 or <0.5) often precede reversals
- **Combine with:** funding rate, open interest, and price trend for confirmation

**Open Interest (OI) Analysis**
- Rising OI + rising price = new money entering longs (trend confirmation)
- Rising OI + falling price = new money entering shorts (bearish, but potential squeeze setup)
- Falling OI + rising price = short covering rally (weak rally, likely to fade)
- Falling OI + falling price = long liquidation (weak selling, potential bottom forming)

---

## 14. Crypto Market Cycles & Seasonality

### The Four-Year (Halving) Cycle

**Historical pattern (with diminishing returns):**

| Cycle | Bottom | Top | Rally | Crash | Time to Recover |
|-------|--------|-----|-------|-------|----------------|
| 2011-2013 | $2 | $1,163 | ~58,000% | -84% ($170) | ~2 years |
| 2015-2017 | $170 | $19,783 | ~11,500% | -84% ($3,122) | ~3 years |
| 2018-2021 | $3,122 | $69,000 | ~2,100% | -77% ($15,500) | ~2 years |
| 2022-2025+ | $15,500 | $108,000+ | ~600%+ | TBD | TBD |

**Key observations:**
1. Each cycle produces diminishing percentage returns (58,000% -> 11,500% -> 2,100% -> 600%)
2. Bear market drawdowns are consistently 77-84%
3. The bottom-to-top phase is typically 2-3 years; the top-to-bottom phase is 1-1.5 years
4. Each cycle is driven by the halving (supply shock) amplified by speculation

### Intra-Cycle Seasonality

**Day-of-week patterns:**
- Weekends: 20-25% lower volume, higher volatility, retail-dominated flow
- Monday Asia open: significant trend-following signals, high-frequency trends form Sunday ~7PM ET through Monday
- Friday: position adjustment day, similar to equity markets — volume rises as traders adjust going into weekend

**Monthly patterns (from academic research):**
- September and October: higher probability of extreme returns (both positive and negative) for most cryptocurrencies
- Q4 (October-December) historically strong for BTC in halving years
- January: often sees continuation of Q4 trends or a correction after year-end rally

**Halving cycle positioning:**
- **6-12 months before halving:** Accumulation phase. Smart money begins positioning
- **0-6 months after halving:** Continued accumulation. Price may be flat or slowly rising
- **6-18 months after halving:** Parabolic phase. This is where the largest gains occur
- **18-24 months after halving:** Distribution and crash phase. Smart money exits

### Quantitative Seasonality Rules

**Rule 1: Reduce leverage going into weekends.**
- Thinner books = larger stop-hunts
- Position size should be 50-70% of weekday size

**Rule 2: Don't fight the cycle.**
- In the 12-18 months after a halving, bias should be long with trend-following strategies
- In the 12-18 months after a cycle top, bias should be defensive with mean-reversion strategies
- Regime-switching (HMM-based) can detect these transitions more precisely than calendar-based rules

**Rule 3: Holiday and event volatility.**
- US holidays, Chinese New Year, major regulatory announcements create liquidity vacuums
- Reduce exposure by 30-50% before known low-liquidity periods

---

## 15. Quant-Specific Crypto Strategies

### Strategy 1: Momentum + Mean Reversion Blend
- **Research finding:** A 50/50 blend of momentum and mean reversion strategies delivered Sharpe 1.71, annualized return 56%, T-stat 4.07 (across crypto markets)
- Momentum outperforms in early trending markets (post-halving, new narratives)
- Mean reversion outperforms in later, choppier markets (mid-cycle, range-bound)
- **Implementation:** Run both strategies simultaneously, let regime detection determine capital allocation

### Strategy 2: BTC-Neutral Residual Mean Reversion
- Strip out the BTC component from altcoin returns (residual = altcoin return - beta * BTC return)
- Trade mean reversion on the residuals — this captures idiosyncratic alt movements, not just BTC-correlated swings
- **Performance:** Excels in post-2021 regimes, highlighting the value of idiosyncratic signal extraction
- **Implementation:** Requires pair-wise cointegration testing and rolling beta estimation

### Strategy 3: Funding Rate Prediction + Execution
- ML model predicts funding rates 4-8 hours ahead based on: open interest, long/short ratio, recent price momentum, historical funding patterns
- Position into expected funding direction ahead of payment
- **Documented performance:** 31% annual returns, Sharpe 2.3
- **Edge source:** Funding rates are mean-reverting and predictable; the market is inefficient at pricing them

### Strategy 4: Liquidation Heatmap Gravity
- Monitor CoinGlass-style liquidation heatmaps for clusters of estimated liquidation prices
- Price tends to "seek" the nearest large liquidation cluster (because cascading liquidations create momentum toward the cluster)
- Enter in the direction of the nearest major cluster with tight stops
- **Risk:** Requires near-real-time data and fast execution; cluster estimates are imprecise

### Strategy 5: Cross-Exchange Basis Arbitrage
- Monitor price differences between spot exchanges and between spot/futures
- During high-volatility events, basis can widen to 2-5%
- Delta-neutral execution: buy on cheap exchange, sell on expensive exchange
- **Constraints:** Requires capital on multiple exchanges (counterparty risk), fast execution, and careful accounting for fees and transfer times

### Strategy 6: Stablecoin Depeg Trading
- Monitor Curve 3pool balance ratios (USDT/USDC/DAI should be ~33/33/33)
- When one stablecoin's share rises above 50%, it's under selling pressure (potential depeg)
- During USDC's SVB depeg, USDC traded as low as $0.87 — those who bought recovered to $1.00 within days
- **Risk:** Stablecoin can actually fail (UST went to $0). Only trade depegs of major, collateralized stablecoins (USDC, USDT), never algorithmic ones

---

## 16. Synthesized Rules for the Quantitative Crypto Trader

### Risk Management (The Foundation)

1. **Never risk more than 1% per trade** — crypto's volatility makes the standard 2% rule too aggressive
2. **Total correlated exposure must not exceed 5-6% of account** — five altcoin positions are NOT five independent bets
3. **Use Half-Kelly for position sizing** — 75% of max growth with 25% of variance
4. **Leverage cap: 3x for swing trades, 5x for scalps, NEVER more** — most blown accounts in crypto are leverage-related
5. **Keep only active trading capital on exchanges** — cold storage the rest
6. **Diversify exchange exposure** — no single exchange should hold >50% of trading capital
7. **Maintain a 10-20% stablecoin "crash fund"** — deploy only during extreme fear events
8. **Monitor stablecoin health** — Curve pool ratios, USDT/USDC peg, exchange withdrawal speeds

### Entry Rules

9. **Regime first, then setup** — use HMM or BTC dominance framework to determine if current regime favors momentum or mean reversion
10. **BTC direction is the master filter** — never go long alts if BTC is in confirmed downtrend
11. **Funding rate confirms, doesn't initiate** — extreme funding readings add confluence but shouldn't be sole entry signals
12. **Wait for liquidation cascades to end before bottom-fishing** — look for funding flip + OI drop + volume spike
13. **Multiple confirmations required** — price action + on-chain + sentiment + regime alignment = high-confidence entry

### Exit Rules

14. **Stops are non-negotiable** — every position has a stop loss before entry
15. **Take partial profits during parabolic moves** — 30% at 2R, 30% at 4R, trail the remaining 40%
16. **Time stops apply in crypto too** — if a trade hasn't moved in your expected timeframe, reassess or exit
17. **Extreme greed = reduce exposure** — Fear & Greed > 80 for 5+ days means start taking profits
18. **Close leveraged positions before weekends and known events** — thin liquidity + leverage = ruin

### Psychology Rules

19. **Set trading hours even though the market is 24/7** — sleep and mental health trump any trade
20. **Maximum trades per day: 3-5** — the always-open market invites overtrading
21. **Never revenge trade** — after a loss, wait at least 1 hour (ideally 4 hours) before the next trade
22. **Track emotional state** — if you're excited or angry, stop trading immediately
23. **FOMO is the enemy** — if you missed a move, you missed it. The next one will come
24. **Automate everything possible** — human psychology is the weakest link in crypto trading

### Cycle & Macro Rules

25. **Respect the four-year cycle** — bias long in the 12-18 months after halving, defensive after cycle top
26. **BTC dominance regime determines alt allocation** — rising dominance = underweight alts, falling = overweight alts
27. **Bear markets in crypto are -77% to -84%** — this is NORMAL, not a reason to leverage short (bear rallies are violent)
28. **Each cycle has diminishing percentage returns** — don't expect 2013-style 58,000% rallies from BTC anymore
29. **Regulatory events create the deepest dislocations and the best recoveries** — but timing them is impossible

### Crypto-Specific Edges

30. **Funding rate arbitrage is the closest thing to a free lunch** — but it requires infrastructure and capital management
31. **Liquidation clusters act as price magnets** — monitor them for directional bias
32. **On-chain divergences (whale accumulation + price decline) are high-conviction setups** — but slow-moving (weeks, not hours)
33. **Stablecoin depeg events create asymmetric opportunities in collateralized stablecoins** — but avoid algorithmic stablecoins entirely
34. **Cross-exchange price discrepancies persist in crypto** — fragmented liquidity is an exploitable inefficiency

---

## Key Quotes Worth Remembering

> "A trader with a mediocre strategy and great risk model becomes fairly successful. A trader with a great strategy and mediocre risk model goes bankrupt." — Mark Douglas

> "In crypto, you don't need to be right more than you're wrong. You need your winners to be 3x your losers." — Glen Goodman

> "Not your keys, not your coins." — Universal crypto wisdom, validated by Mt. Gox, FTX, and every exchange that has ever failed

> "The market can stay irrational longer than you can stay solvent." — John Maynard Keynes (quoted by every crypto survivor)

> "Everyone has a plan until they get punched in the mouth." — Mike Tyson (quoted by every crypto trader who lived through a -80% bear market)

> "Half-Kelly offers 75% of the maximum growth rate with only 25% of the variance." — Kelly Criterion applied wisdom

> "Leverage is how smart people go broke in crypto." — Universal OG trader wisdom

> "The best trade in crypto is the one you don't take." — Patience principle, validated by every crash

---

## Convergence: Crypto KB + Market Wizards + Livermore

| Principle | Livermore (1923) | Market Wizards (1989) | Crypto KB (2026) |
|---|---|---|---|
| Cut losses fast | "Always sell what shows a loss" | Seykota: "Cutting losses x3" | 1% max risk, stops non-negotiable, liquidation awareness |
| Let winners run | "It was always my sitting" | Dennis: "Trade the middle 60%" | Partial profits + trail: 30% at 2R, 30% at 4R, trail 40% |
| Never average losers | "Few greater blunders" | Jones: "#1 account killer" | In crypto, averaging losers + leverage = liquidation cascade |
| Position sizing | Feeling-out bets | Kovner: "Undertrade x3" | 1% rule, Half-Kelly, correlation-adjusted exposure |
| Patience over action | Old Turkey: "It's a bull market!" | Weinstein: "Sitting is a position" | Max 3-5 trades/day, set trading hours, FOMO is the enemy |
| Regime awareness | "Trade with the general market" | HMM regime detection | BTC dominance framework, four-year cycle, regime-adaptive strategies |
| Counterparty risk | N/A (pre-modern) | N/A (regulated markets) | Exchange diversification, cold storage, stablecoin health monitoring |
| Emotional control | "Loses his temper is a goner" | Van Tharp: 60% is psychology | 24/7 amplifies every weakness: automate, set hours, track emotional state |
| Expect the unexpected | "Calamities beyond calculation" | Rogers: "Irrational longer than solvent" | Mt. Gox, Luna, FTX — the impossible happens regularly in crypto |

---

## Direct Application to Our MT5 Crypto Bot

| Crypto KB Principle | Implementation |
|---|---|
| 1% risk rule for crypto volatility | Reduce CAPITAL_PER_TRADE proportionally for crypto pairs; use ATR-scaled sizing |
| Correlation-adjusted exposure | Track BTC correlation for each alt; limit total correlated exposure to 5-6 risk units |
| Funding rate as sentiment filter | Add funding rate data to confluence scorer: extreme positive = reduce long confidence, extreme negative = boost long confidence |
| Liquidation heatmap integration | Monitor CoinGlass API for liquidation clusters; use as price magnet targets for TP levels |
| BTC dominance regime filter | Add BTC.D trend to market context gate: rising dominance = avoid alt longs, falling = favor alt longs |
| Weekend position reduction | Add weekend flag to position sizing: reduce by 30-50% during Saturday-Sunday UTC |
| Fear & Greed sentiment layer | Integrate F&G index into confluence scorer: <20 boosts long confidence, >80 boosts short/exit confidence |
| Exchange risk management | Distribute capital across 2-3 exchanges; monitor withdrawal speed as early warning |
| Flash crash dry powder | Reserve 10-20% of capital as stablecoin crash fund; deploy only when F&G <15 + 20%+ BTC drop |
| Leverage caps | Hard-code 3x max for swing, 5x max for scalp in position manager |
| 24/7 trading hours discipline | Enforce kill zone windows even for crypto; block new positions outside defined hours |
| On-chain flow integration | Add exchange net flow (7d MA) as a feature in ML model: persistent inflows = bearish, outflows = bullish |

---

## Sources & Further Reading

### Books
- [Trading in the Zone — Mark Douglas](https://www.amazon.com/Trading-Zone-Confidence-Discipline-Attitude/dp/0735201447)
- [The Crypto Trader — Glen Goodman](https://www.amazon.com/Crypto-Trader-trading-Bitcoin-cryptocurrencies/dp/0857197177)
- [Digital Gold — Nathaniel Popper](https://www.amazon.com/Digital-Gold-Bitcoin-Millionaires-Reinvent/dp/006236250X)
- [Cryptoassets — Chris Burniske & Jack Tatar](https://www.amazon.com/Cryptoassets-Innovative-Investors-Bitcoin-Beyond/dp/1260026671)
- [Mastering Bitcoin — Andreas Antonopoulos](https://www.amazon.com/Mastering-Bitcoin-Programming-Open-Blockchain/dp/1491954388)

### Crash Analysis & Market History
- [FTX vs. Mt. Gox: How Crypto Reacted to Exchange Collapses — Chainalysis](https://www.chainalysis.com/blog/ftx-vs-mt-gox-collapse/)
- [Mt. Gox Collapse: Critical Lessons for Crypto Traders — Bitget](https://www.bitget.com/academy/mt-gox-lessons-2026)
- [The Collapse of FTX — ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0890838923001348)
- [Bitcoin's $2 Billion Reckoning: Liquidation Cascade Analysis — CoinChange](https://www.coinchange.io/blog/bitcoins-2-billion-reckoning-how-novembers-liquidations-cascade-exposed-cryptos-structural-fragilities)

### Position Sizing & Risk Management
- [Dynamic Position Sizing: 7 Pro Tips — Altrady](https://www.altrady.com/blog/crypto-paper-trading/risk-management-seven-tips)
- [Kelly Criterion for Crypto Traders — Medium](https://medium.com/@tmapendembe_28659/kelly-criterion-for-crypto-traders-a-modern-approach-to-volatile-markets-a0cda654caa9)
- [Risk Management in Crypto Trading: 7 Rules — BingX](https://bingx.com/en/learn/article/risk-management-in-crypto-trading-7-rules-every-trader-must-know)
- [Crypto Risk Management for Safer Trading 2026 — DarkBot](https://darkbot.io/blog/defining-risk-management-in-crypto-for-safer-trading-2026)

### Funding Rate & Basis Trading
- [The Ultimate Guide to Funding Rate Arbitrage — Amberdata](https://blog.amberdata.io/the-ultimate-guide-to-funding-rate-arbitrage-amberdata)
- [Funding Rate Arbitrage — CoinGlass](https://www.coinglass.com/learn/what-is-funding-rate-arbitrage)
- [Exploring Risk and Return of Funding Rate Arbitrage — ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2096720925000818)
- [Perpetual Contract Funding Rate Arbitrage 2025 — Gate.com](https://www.gate.com/learn/articles/perpetual-contract-funding-rate-arbitrage/2166)

### Liquidation Analysis
- [What Are Liquidation Cascades in Crypto — Yield App](https://yield.app/blog/what-are-liquidation-cascades-in-crypto)
- [Liquidations in Crypto: How to Anticipate Volatile Market Moves — Amberdata](https://blog.amberdata.io/liquidations-in-crypto-how-to-anticipate-volatile-market-moves)
- [Bitcoin Liquidation Heatmap Trading Guide — QuadCode](https://quadcode.com/blog/bitcoin-liquidation-heatmap-and-how-to-use-it-for-profitable-trading)

### On-Chain Analysis & Whale Tracking
- [Whale Watching: Top Tools for Monitoring Large Crypto Wallets — Nansen](https://www.nansen.ai/post/whale-watching-top-tools-for-monitoring-large-crypto-wallets)
- [On-Chain Data Analysis and Whale Movements — Gate.com](https://dex.gate.com/crypto-wiki/article/what-is-on-chain-data-analysis-and-how-to-track-active-addresses-whale-movements-and-transaction-trends-in-crypto-20260208)

### BTC Dominance & Correlation
- [Bitcoin Dominance: Ultimate Guide to BTCD Trading Strategies — Phemex](https://phemex.com/academy/what-is-bitcoin-dominance-btcd)
- [What Altcoin Dominance Really Tells You — CoinAPI](https://www.coinapi.io/blog/what-altcoin-dominance-really-tells-you-and-how-to-trade-it)

### Market Cycles & Seasonality
- [Bitcoin 4-Year Cycles Explained — Fidelity](https://www.fidelity.com/learning-center/trading-investing/four-year-bitcoin-and-crypto-cycles)
- [Weekend Effect in Bitcoin — Quantified Strategies](https://www.quantifiedstrategies.com/weekend-effect-bitcoin/)
- [Calendar Effects on Crypto Returns — ScienceDirect](https://www.sciencedirect.com/science/article/pii/S1062940825000816)
- [Seasonality in Bitcoin Intraday Trend Trading — Concretum Group](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/)

### Quant Strategies
- [Systematic Crypto Trading: Momentum, Mean Reversion & Volatility Filtering — Medium](https://medium.com/@briplotnik/systematic-crypto-trading-strategies-momentum-mean-reversion-volatility-filtering-8d7da06d60ed)
- [Revisiting Trend-following and Mean-reversion in Bitcoin — QuantPedia](https://quantpedia.com/revisiting-trend-following-and-mean-reversion-strategies-in-bitcoin/)
- [High Frequency Momentum Trading with Cryptocurrencies — ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0275531919308062)

### Sentiment & Psychology
- [Crypto Fear & Greed Index — Alternative.me](https://alternative.me/crypto/fear-and-greed-index/)
- [Market Psychology: Understanding Fear and Greed in Crypto — Cryptopolitan](https://www.cryptopolitan.com/market-psychology-understanding-fear-and-greed-in-crypto/)
- [Stablecoin Depegging Events — Amberdata](https://blog.amberdata.io/crypto-depegging-event-trading-opportunities-and-market-impact)

### Stablecoin Risk
- [Stablecoins: Valuation and Depegging — S&P Global](https://www.spglobal.com/content/dam/spglobal/corporate/en/images/general/special-editorial/stablecoinsadeepdiveintovaluationanddepegging.pdf)
- [From Depegs to Jumps: Stablecoin Instabilities — ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0261560625000749)
