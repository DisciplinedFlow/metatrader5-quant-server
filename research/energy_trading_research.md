# Energy Trading Research: Natural Gas, Brent-WTI Spread, Oil Volatility

Research compiled March 13, 2026. Sources from academic papers, Quantpedia, QuantConnect, CME Group, EIA, and practitioner blogs.

---

## Part 1: Natural Gas (NG) Algorithmic Trading

### 1.1 Seasonal Patterns

Natural gas has the clearest seasonality of any major commodity, driven by heating/cooling demand cycles.

**Two Core Seasons:**
- **Injection Season (April-October):** Supply exceeds demand; excess gas is pumped into underground storage. Prices tend to be LOWER. Futures for this strip trade at a discount to winter.
- **Withdrawal Season (November-March):** Gas is withdrawn from storage to meet heating demand. Prices tend to be HIGHER. Winter futures trade at a structural premium.

**Monthly Patterns (from Equity Clock 10-year data):**
| Month | Tendency | Notes |
|-------|----------|-------|
| January | Bearish late month | Post-winter peak, demand fading |
| February | Mixed | Weather-dependent, often volatile |
| March | Bullish crossover | End of withdrawal = supply uncertainty |
| April | Bullish crossover | Transition month, often rallies |
| May | Bearish crossover | Injection ramps up, supply relief |
| June | Bearish crossover | Peak injection, prices sink |
| July | Mixed | Cooling demand can surprise |
| August | Bottoming | Prices often find floor |
| September | MOST BULLISH MONTH | Pre-winter positioning begins |
| October | Bullish into mid-month | Winter premium pricing in |
| November | Bearish crossover | "Buy the rumor, sell the news" |
| December | Mixed/Volatile | Weather-driven swings |

**Best Historical Seasonal Trade:**
- Buy September 2, sell October 20
- 10-year total return: 56.09%
- Win rate: 7 out of 10 years positive
- Risk-reward: SL at 11.28% below entry, target 36.45% above (1:3.2 R:R)

**Popular Seasonal Spreads:**
- **October/November spread:** Long November, short October (capture winter premium buildup)
- **October/January spread:** Long January, short October (wider winter premium)
- **March/April spread:** Withdrawal season spread capturing end-of-winter dynamics

### 1.2 EIA Natural Gas Storage Report Trading

**Report Details:**
- Released every Thursday at 10:30 AM ET
- Measures weekly change in underground storage (in Bcf)
- Single most important weekly catalyst for NG prices
- Compare actual vs. consensus estimate AND vs. 5-year average

**Price Reaction Mechanics:**
- Each 1 Bcf surprise (actual vs. consensus) typically moves price $0.02-0.04/MMBtu
- Specialized forecast firms predict within +/-1.8 Bcf vs. consensus accuracy of +/-4.2 Bcf
- Initial spike occurs within seconds (HFT-driven)
- First 87 seconds after release have extreme bid-ask spreads from HFT activity -- AVOID trading in this window
- Price often spikes into the 50-day MA before reversing (fade opportunity)
- Overnight continuation occurs when report flips storage deficit/surplus vs. 5-year average

**Implementable EIA Report Strategy:**

```
PARAMETERS:
  report_time = 10:30 ET (Thursday)
  no_trade_window = 87 seconds post-release
  lookback_sma = 20 days (on storage surprise)

RULES:
  1. Calculate storage_surprise = actual_draw_injection - consensus_estimate
  2. Wait 90 seconds after 10:30 ET release
  3. IF storage_surprise > +3 Bcf (bullish surprise - larger draw or smaller injection):
     - LONG NG at market after 90-second window
     - SL = 1.5 * ATR(14) on 5-min chart below entry
     - TP1 = 1.0 * ATR(14) (take 50%)
     - TP2 = trail with 2 * ATR(14) for remainder
  4. IF storage_surprise < -3 Bcf (bearish surprise):
     - SHORT NG at market after 90-second window
     - Mirror SL/TP rules
  5. EXIT all positions by end of session (no overnight EIA holds)

FILTERS:
  - Skip if ATR(14) on daily is > 2x its 20-day average (market already too volatile)
  - Skip if storage is within 2% of 5-year average (no structural bias)
```

### 1.3 Weather-Based Trading

**Key Weather Metrics:**
- **HDD (Heating Degree Days):** = max(0, 65 - daily_avg_temp). Higher HDD = more heating demand = bullish NG
- **CDD (Cooling Degree Days):** = max(0, daily_avg_temp - 65). Higher CDD = more cooling (gas-fired power) = modestly bullish
- **GWDD (Gas-Weighted Degree Days):** Combined HDD + CDD weighted by gas consumption patterns

**Temperature Forecast Impact:**
- 6-10 day and 8-14 day NOAA forecasts are the primary movers
- A shift from "normal" to "below normal" temps in winter can move NG 5-10% in a session
- La Nina winters (like 2025-2026) produce colder conditions in North and West US, increasing volatility
- Hurricane season (June-November) can disrupt Gulf of Mexico production, causing supply shocks

**Implementable Weather Strategy:**

```
PARAMETERS:
  hdd_forecast_period = 6-10 day NOAA forecast
  hdd_normal = 30-year average for region/period
  deviation_threshold = 15% above/below normal

RULES:
  1. Daily: Calculate forecast_hdd for next 6-10 days per EIA region
  2. Calculate hdd_deviation = (forecast_hdd - hdd_normal) / hdd_normal
  3. During WITHDRAWAL SEASON (Nov-Mar):
     - IF hdd_deviation > +15% (colder than normal):
       LONG NG with ATR-based sizing
     - IF hdd_deviation < -15% (warmer than normal):
       SHORT NG with ATR-based sizing
  4. During INJECTION SEASON (Apr-Oct):
     - IF cdd_deviation > +20% (hotter than normal, AC demand):
       LONG NG (weaker signal, half size)
     - Hurricane threat in Gulf: LONG NG (supply disruption)
  5. Exit when forecast reverts toward normal OR after 5 trading days

CONFIRMATION FILTERS:
  - Storage levels relative to 5-year average (below avg = amplify long signals)
  - Current price relative to seasonal average (discount = amplify long signals)
```

### 1.4 Best Indicators for NG

Natural gas is extremely volatile -- annualized volatility typically 60-100% (vs. ~30% for crude oil). This demands specific indicator tuning.

**Volatility Profile:**
- Annualized volatility: 60-100% (reached 102% in Feb 2025)
- Daily ATR: Typically 3-5% of price (vs. 1.5-2.5% for crude oil)
- H1 ATR: Roughly 1-2% of price in normal conditions, 3%+ during reports/weather events
- Average daily range: $0.10-0.25/MMBtu at $3-4 price levels (higher in absolute terms at higher prices)
- NG is 2-3x more volatile than crude oil on a percentage basis

**Recommended Indicator Settings for NG:**

| Indicator | Settings | Usage |
|-----------|----------|-------|
| ATR | 14-period, any timeframe | Position sizing, SL placement (1.5-2x ATR) |
| Bollinger Bands (daily) | 20-period, 2.5 StdDev (wider than default 2.0 due to NG volatility) | Mean reversion entries at outer bands |
| Bollinger Bands (5-min, for EIA) | 9-period, 2.0 StdDev | Scalping setups around reports |
| RSI | 14-period | Overbought/oversold; use 75/25 levels (not 70/30) for NG |
| Keltner Channels | 20-period, 2.5x ATR | Volatility squeeze detection (inside Bollinger = squeeze) |
| EMA | 8 and 34 period (H4/Daily) | Trend direction; cross = regime change |
| MACD | 12/26/9 default | Momentum confirmation for seasonal trades |

**NG-Specific Indicator Rules:**
```
SQUEEZE DETECTION (Bollinger + Keltner):
  squeeze = BB_upper < KC_upper AND BB_lower > KC_lower
  # When Bollinger Bands contract INSIDE Keltner Channels,
  # volatility compression = imminent explosive move

  IF squeeze AND seasonal_bias == BULLISH:
    Prepare LONG entry on first BB expansion above KC_upper
  IF squeeze AND seasonal_bias == BEARISH:
    Prepare SHORT entry on first BB expansion below KC_lower

  SL = opposite Keltner Channel
  TP = 2x the squeeze range (KC_upper - KC_lower)
```

### 1.5 Implementable NG Seasonal Strategy (Complete)

```
STRATEGY: NG_SEASONAL_MOMENTUM
INSTRUMENT: NYMEX Henry Hub Natural Gas Futures (NG) or CFD equivalent
TIMEFRAME: Daily bars for signals, H1 for entry timing

PARAMETERS:
  seasonal_long_start = September 1
  seasonal_long_end = October 25
  seasonal_short_start = November 15
  seasonal_short_end = December 31
  ema_fast = 8
  ema_slow = 34
  rsi_period = 14
  rsi_overbought = 75
  rsi_oversold = 25
  atr_period = 14
  sl_atr_mult = 2.0
  tp_atr_mult = 4.0

ENTRY RULES (LONG - September Rally):
  1. Date is within seasonal_long window (Sep 1 - Oct 25)
  2. EMA(8) > EMA(34) on daily chart OR EMA(8) crossing above EMA(34)
  3. RSI(14) > 40 AND RSI(14) < 75 (not already overbought)
  4. Storage below 5-year average (bullish fundamental)
  5. ENTER LONG at next H1 candle open after pullback to EMA(8) on H1

EXIT RULES:
  - SL = 2.0 * ATR(14) below entry
  - TP1 = 2.0 * ATR(14) above entry (close 50%)
  - TP2 = 4.0 * ATR(14) above entry (close remaining 50%)
  - TIME STOP: Exit if still open after October 25

ENTRY RULES (SHORT - Post-Peak Fade):
  1. Date is within seasonal_short window (Nov 15 - Dec 31)
  2. EMA(8) < EMA(34) on daily OR crossing below
  3. RSI(14) < 60 AND RSI(14) > 25
  4. Storage above 5-year average (bearish fundamental)
  5. ENTER SHORT on rally to EMA(8) on H1

EXPECTED PERFORMANCE (based on 10-year seasonal data):
  - Win rate: ~65-70% during September seasonal window
  - Average R:R: 1:3.2
  - Sharpe: ~1.2-1.5 (seasonal window only)
  - Max drawdown: ~15-20% of position
```

---

## Part 2: Brent-WTI Spread Trading

### 2.1 Historical Spread Range

**Normal Conditions:**
- Typical range: $2-5 (Brent premium over WTI)
- Historical average: ~$3-4
- The spread exists because Brent reflects global waterborne crude pricing while WTI reflects US landlocked crude at Cushing, Oklahoma

**Extreme Events:**
| Period | Spread | Cause |
|--------|--------|-------|
| 2011-2012 | $15-27 | Cushing storage glut, US pipeline constraints |
| 2014-2015 | $2-6 | US export ban still in place |
| 2016-2019 | $3-8 | Post export ban, pipeline buildout |
| 2020 (COVID) | Inverted briefly | WTI went negative (-$37), Brent held ~$20 |
| 2022 (Ukraine) | $5-10 | Russian supply risk = Brent premium |
| March 2026 (Iran/Hormuz) | $4-5+ widening | Strait of Hormuz closure, Brent surging |

**Current Situation (March 13, 2026):**
- Brent: ~$100.46/bbl
- WTI: ~$95.73/bbl
- Spread: ~$4.73 (and widening)
- Strait of Hormuz closed since March 9, 2026 -- 20% of global oil flows disrupted
- Goldman Sachs now models 21 days of low flows at 10% normal, then 30-day gradual recovery
- Extreme backwardation: front-month premium of $14.20 over next month (record)
- Geopolitical risk premium embedded: $4-10/bbl in Brent

### 2.2 What Drives the Spread

**Structural Drivers (mean-reverting):**
1. Transportation costs (pipeline, shipping) between Cushing and global market
2. Cushing, OK storage levels (high inventory = wider spread, WTI depressed)
3. US crude oil export capacity (more exports = narrower spread)
4. Quality differential (Brent is lighter/sweeter, slight quality premium)
5. Seasonal refinery maintenance (turnarounds affect regional supply/demand)

**Event-Driven (can cause regime shifts):**
1. Middle East geopolitical risk (Strait of Hormuz, OPEC decisions) -- widens spread
2. US shale production surges -- widens spread (WTI depressed)
3. US sanctions on Iranian/Russian crude -- widens spread (Brent supply shock)
4. OPEC+ production cuts -- affects Brent more than WTI
5. Hurricane season Gulf disruptions -- narrows spread (WTI supply hit)

### 2.3 Algorithmic Spread Trading Strategies

#### Strategy A: Simple SMA Mean Reversion (Quantpedia)

```
STRATEGY: BRENT_WTI_SMA_REVERSION
SOURCE: Quantpedia (backtested 1992-2013)

PARAMETERS:
  spread = Brent_price - WTI_price
  sma_period = 20 days

RULES:
  1. Calculate spread_sma = SMA(spread, 20)
  2. IF spread > spread_sma:
     SHORT the spread (short Brent, long WTI)
     Bet that spread will decrease back to SMA
  3. IF spread < spread_sma:
     LONG the spread (long Brent, short WTI)
     Bet that spread will increase back to SMA
  4. EXIT when spread crosses back through spread_sma

PERFORMANCE (in-sample, Quantpedia):
  - Annual return: ~40% (indicative, includes leverage)
  - Volatility: ~22%
  - Sharpe Ratio: 1.64
  - CAVEAT: Out-of-sample performance was slightly negative
  - This suggests SMA-20 alone is too simple; needs regime filter
```

#### Strategy B: Bollinger Band Z-Score (Bocconi/WUTIS Research)

```
STRATEGY: BRENT_WTI_BOLLINGER_ZSCORE
SOURCE: Academic backtests 1992-2013, Sharpe >2.0

PARAMETERS:
  spread = Brent_price - WTI_price
  lookback = 60 days (for mean and std calculation)
  bb_period = 20 days
  bb_std = 2.0
  entry_zscore = 2.0
  exit_zscore = 0.0 (mean)
  stop_zscore = 3.5

RULES:
  1. Calculate rolling z-score:
     z = (spread - SMA(spread, lookback)) / StdDev(spread, lookback)
  2. IF z > +entry_zscore (+2.0):
     SHORT the spread (spread is abnormally wide)
     Short Brent futures, Long WTI futures (dollar-neutral ratio)
  3. IF z < -entry_zscore (-2.0):
     LONG the spread (spread is abnormally narrow)
     Long Brent futures, Short WTI futures
  4. EXIT when z crosses 0 (spread reverts to mean)
  5. STOP LOSS: Exit if z reaches +/-3.5 (regime shift, not mean-reverting)

POSITION SIZING:
  Hedge ratio from Johansen cointegration test or OLS regression
  Typical ratio: ~1:1 in contract terms, adjust for price differential
  Dollar-neutral: Equal dollar notional on each leg

PERFORMANCE (academic backtest):
  - Sharpe Ratio: >2.0
  - Profitable across every 5-year sub-period (1992-2013)
  - Significantly outperforms random entry strategies
```

#### Strategy C: Kalman Filter + Regime-Switching (Advanced)

```
STRATEGY: BRENT_WTI_KALMAN_REGIME
SOURCE: HMM research on crude oil cointegration

PARAMETERS:
  kalman_observation_noise = 0.01
  kalman_transition_noise = 0.001
  hmm_states = 2 (mean-reverting vs. trending)
  bb_period = 20
  bb_std = 2.0

RULES:
  1. Use Kalman Filter to estimate dynamic hedge ratio and spread mean
     (adapts to changing relationship between Brent and WTI)
  2. Calculate residual = actual_spread - kalman_predicted_spread
  3. Fit 2-state HMM on residual:
     - State 0: Mean-reverting (low volatility, spread oscillates)
     - State 1: Trending (high volatility, spread drifting)
  4. ONLY TRADE when HMM probability of State 0 > 0.7
  5. Apply Bollinger Bands on Kalman residual:
     - Short spread when residual > upper BB
     - Long spread when residual < lower BB
     - Exit at Kalman-predicted mean
  6. NO TRADES when HMM indicates trending regime (State 1 > 0.3)

ADVANTAGES:
  - Dynamic hedge ratio adapts to structural changes (pipeline buildouts, export policy)
  - HMM filter prevents trading during geopolitical blowouts (2026 Hormuz crisis)
  - Kalman smoother provides better mean estimate than simple SMA

IMPLEMENTATION NOTE:
  This integrates with existing HMM infrastructure in regime_hmm.py
  Kalman filter available via pykalman or filterpy Python libraries
```

### 2.4 Current Spread Context (March 2026 Crisis)

**WARNING: The spread is NOT mean-reverting right now.**

The Strait of Hormuz closure is a structural disruption, not a temporary shock. Strategy recommendations:

1. **Suspend mean-reversion strategies** on the spread until Hormuz reopens
2. **Monitor IEA strategic reserve releases** -- coordinated releases will temporarily narrow the spread
3. **Watch for extreme backwardation collapse** -- when front-month premium shrinks from $14.20, it signals the worst is priced in
4. **Re-entry signal:** When spread z-score returns below 2.0 AND HMM switches back to mean-reverting regime

---

## Part 3: Oil Volatility Trading

### 3.1 OVX (CBOE Crude Oil Volatility Index)

**What it is:**
- The "VIX for oil" -- measures 30-day implied volatility from USO ETF options
- Tracks what traders are WILLING TO PAY for oil options (fear/greed gauge)
- Does NOT track oil price direction, only expected magnitude of moves
- Typically overpredicts realized volatility (volatility risk premium)

**Historical OVX Levels:**
| OVX Level | Regime | Trading Implications |
|-----------|--------|---------------------|
| < 25 | Low volatility | Range-bound oil, mean-reversion strategies work |
| 25-35 | Normal volatility | Standard strategies apply |
| 35-50 | Elevated volatility | Reduce position size, widen stops |
| 50-70 | High volatility | Only trend-following, no fading |
| > 70 | Crisis volatility | Reduce exposure or sit out |

**OVX-Price Relationship:**
- Negative correlation: Rising OVX often precedes or accompanies falling oil prices
- Asymmetric: OVX spikes more on oil drops than it falls on oil rallies
- Leading indicator: A rise in OVX can precede a rise in crude oil prices (fear = bottoming)
- OVX often overpredicts 30-day moves (volatility risk premium = potential edge)

### 3.2 OVX as a Strategy Filter

**Implementable OVX Filter:**

```
STRATEGY: OVX_REGIME_FILTER
PURPOSE: Filter for ALL oil trading strategies (NG, Brent-WTI spread, CL directional)

PARAMETERS:
  ovx_low = 25
  ovx_normal_high = 35
  ovx_elevated = 50
  ovx_crisis = 70
  ovx_sma = 20 days

RULES:
  1. Calculate ovx_regime:
     IF OVX < ovx_low AND OVX < SMA(OVX, 20):
       regime = "LOW_VOL"
       -> Use MEAN REVERSION strategies (Bollinger fade, range trading)
       -> Position size: 100%

     IF OVX >= ovx_low AND OVX < ovx_normal_high:
       regime = "NORMAL"
       -> Both mean reversion and trend following allowed
       -> Position size: 100%

     IF OVX >= ovx_normal_high AND OVX < ovx_elevated:
       regime = "ELEVATED"
       -> Only TREND FOLLOWING strategies
       -> Position size: 75%
       -> Widen SL by 1.5x

     IF OVX >= ovx_elevated AND OVX < ovx_crisis:
       regime = "HIGH"
       -> Only TREND FOLLOWING with strong confirmation
       -> Position size: 50%
       -> Widen SL by 2x

     IF OVX >= ovx_crisis:
       regime = "CRISIS"
       -> NO NEW POSITIONS
       -> Trail existing winners tightly
       -> Wait for OVX to drop below 50 before re-entering

  2. OVX DIRECTION FILTER:
     IF OVX falling (OVX < SMA(OVX, 5)):
       -> Bias toward LONG oil (fear leaving market)
     IF OVX rising (OVX > SMA(OVX, 5)):
       -> Bias toward SHORT oil or reduce long exposure

INTEGRATION WITH EXISTING HMM:
  This OVX regime maps to existing regime_hmm.py states:
  - LOW_VOL / NORMAL -> HMM State 0 (range-bound)
  - ELEVATED / HIGH -> HMM State 1 (trending)
  - CRISIS -> HMM State 2 (volatile/uncertain)
```

### 3.3 Volatility Regime Detection for Oil

**ATR-Based Regime Detection:**

```
STRATEGY: OIL_VOLATILITY_REGIME
TIMEFRAME: H4 bars for regime, H1 for signals

PARAMETERS:
  atr_period = 14
  atr_sma_period = 50 (long-term ATR average)
  regime_threshold_low = 0.7  (ATR < 70% of average = low vol)
  regime_threshold_high = 1.3 (ATR > 130% of average = high vol)
  squeeze_bb_period = 20
  squeeze_bb_std = 2.0
  squeeze_kc_period = 20
  squeeze_kc_mult = 1.5

RULES:
  1. Calculate ATR_ratio = ATR(14) / SMA(ATR(14), 50)

  2. REGIME CLASSIFICATION:
     IF ATR_ratio < regime_threshold_low:
       regime = "COMPRESSION" (expect breakout)
       -> Prepare breakout entries
       -> Use Bollinger/Keltner squeeze for timing

     IF ATR_ratio >= regime_threshold_low AND ATR_ratio <= regime_threshold_high:
       regime = "NORMAL"
       -> Both mean reversion and trend following

     IF ATR_ratio > regime_threshold_high:
       regime = "EXPANSION" (trending/volatile)
       -> Only trend following
       -> Increase stop distances
       -> Trail aggressively on winners

  3. SQUEEZE DETECTION (Bollinger inside Keltner):
     bb_upper = SMA(close, 20) + 2.0 * StdDev(close, 20)
     bb_lower = SMA(close, 20) - 2.0 * StdDev(close, 20)
     kc_upper = EMA(close, 20) + 1.5 * ATR(14)
     kc_lower = EMA(close, 20) - 1.5 * ATR(14)

     squeeze = (bb_upper < kc_upper) AND (bb_lower > kc_lower)

     IF squeeze == True for 5+ consecutive bars:
       -> BREAKOUT IMMINENT
       -> Place buy-stop above kc_upper and sell-stop below kc_lower
       -> Cancel unfilled side after breakout triggers
       -> SL = opposite Keltner Channel
       -> TP = 2x squeeze range
```

### 3.4 Breakout vs. Fade: When to Use Each

**Breakout Strategies Work When:**
- ATR expanding (ATR_ratio > 1.3)
- OVX rising from low base (volatility expansion beginning)
- After prolonged squeeze (5+ bars inside Keltner)
- Around scheduled catalysts (EIA report, OPEC meeting, inventory data)
- During geopolitical escalation
- During trending HMM regime

**Fade/Mean-Reversion Strategies Work When:**
- ATR contracting or stable (ATR_ratio < 1.0)
- OVX stable or falling below 30
- Price at Bollinger Band extremes in ranging market
- No upcoming catalysts within 4 hours
- During range-bound HMM regime
- Mid-opening-range groups (67% probability of mean reversion during remainder of session)

**Opening Range Breakout (ORB) for Crude Oil:**

```
STRATEGY: CL_OPENING_RANGE_BREAKOUT
INSTRUMENT: CL futures or XTIUSD CFD
TIMEFRAME: 30-minute opening range

PARAMETERS:
  opening_range_minutes = 30 (from session open)
  session_open = 09:00 ET (NYMEX pit open) or 06:00 ET (electronic)
  atr_filter_period = 14
  atr_filter_mult = 0.5 (opening range must be < 50% of daily ATR)
  risk_reward = 2.0

RULES:
  1. Mark the HIGH and LOW of the first 30 minutes after session open
  2. opening_range = high_30min - low_30min

  3. FILTER: Skip if opening_range > 0.5 * ATR(14, daily)
     (too wide = false breakouts more likely)

  4. LONG BREAKOUT:
     Buy-stop at high_30min + 0.02 (2 ticks above range high)
     SL = low_30min - 0.02 (below range low)
     TP = entry + risk_reward * (entry - SL)

  5. SHORT BREAKOUT:
     Sell-stop at low_30min - 0.02
     SL = high_30min + 0.02
     TP = entry - risk_reward * (SL - entry)

  6. Cancel unfilled orders after 2 hours (no breakout = range day)
  7. If BOTH sides trigger, exit the loser immediately
  8. Exit all positions 30 minutes before session close

VOLATILITY FILTER (OVX-based):
  - OVX < 25: Skip ORB (low vol = range day likely, fade instead)
  - OVX 25-40: ORB with standard parameters
  - OVX 40-60: ORB with wider range (use 45-min OR instead of 30-min)
  - OVX > 60: Skip ORB (too volatile, moves are erratic)

PERFORMANCE (approximated from practitioner reports):
  - Average trade: ~$100 per contract
  - Win rate: ~45-50%
  - Profit factor: 1.3-1.5
  - Best performance: Tuesday-Thursday sessions
```

### 3.5 Crude Oil Intraday Volatility-Filtered Strategy

```
STRATEGY: CL_VOLATILITY_FILTERED_DIP_BUY
SOURCE: QuantifiedStrategies.com backtest (341 trades)

PARAMETERS:
  day_of_week_filter = [Wednesday, Thursday, Friday]  # late week best
  session_time = US session only
  midpoint = (daily_high + daily_low) / 2
  wait_after_open = 2 hours
  atr_period = 14
  ovx_threshold = 40  # only trade when OVX < 40

RULES:
  1. Wait 2 hours after session open
  2. Calculate midpoint of the current day's range
  3. IF low of a 5-minute bar crosses BELOW midpoint:
     BUY at market
  4. EXIT if high of a 5-minute bar crosses ABOVE midpoint (quick profit)
  5. EXIT at session close regardless
  6. FILTER: Only trade on Wednesday-Friday
  7. FILTER: Only trade when OVX < 40

PERFORMANCE (backtest):
  - 341 trades
  - Win rate: 58%
  - Average gain per trade: 0.25%
  - Average winner > average loser
  - With OVX filter: avg trade increased from $65 to $126
  - With OVX filter: max drawdown decreased from $10k to $2.7k
  - Sharpe: ~0.8
```

---

## Part 4: Cross-Strategy Integration

### 4.1 How These Fit Into the Existing MT5 System

The existing trading brain architecture (Phase 0-7) already has:
- HMM regime detection (`ml/regime_hmm.py`) -- extend with OVX input for oil instruments
- Confluence scorer (`algorithms/confluence_scorer.py`) -- add energy-specific factors
- Strategy router (`algorithms/strategy_router.py`) -- route based on OVX regime
- ICT entry scanner (`algorithms/ict_entry.py`) -- can be adapted for CL/NG

**Proposed New Modules:**

| Module | Purpose | Dependencies |
|--------|---------|-------------|
| `indicators/seasonal.py` | NG/CL seasonal bias calculator | Date math, historical patterns |
| `indicators/weather.py` | HDD/CDD deviation from normals | NOAA API or weather data feed |
| `indicators/ovx_regime.py` | OVX-based volatility regime | OVX data feed |
| `algorithms/spread_trader.py` | Brent-WTI spread mean reversion | pykalman, statsmodels (cointegration) |
| `algorithms/eia_scanner.py` | EIA report reaction strategy | Celery scheduled task, news/calendar API |
| `indicators/squeeze.py` | Bollinger/Keltner squeeze detector | Existing BB/KC calculations |

### 4.2 Risk Parameters for Energy Instruments

| Parameter | XAUUSD (current) | XTIUSD (CL) | NATGAS (NG) | Brent-WTI Spread |
|-----------|------------------|-------------|-------------|-----------------|
| SL_ATR_MULT | 1.2 | 1.5 | 2.0 | N/A (z-score based) |
| MAX_LOSS/trade | $50 | $50 | $75 (higher vol) | $40 (hedged) |
| DAILY_HALT | $300 | $200 | $200 | $150 |
| MAX_OPEN | 5 | 2 | 2 | 1 (spread counts as 1) |
| CAPITAL_PER_TRADE | $500 | $500 | $400 | $600 (two legs) |

---

## Key Takeaways

1. **Natural Gas** is the most volatile major commodity -- requires wider stops (2x ATR), seasonal awareness, and weather data integration. The September seasonal trade has the best historical edge (56% return over 10 years). EIA Thursday reports are the #1 weekly catalyst.

2. **Brent-WTI Spread** is a classic mean-reversion trade with Sharpe >2.0 in academic backtests using Bollinger Bands/z-score on a 60-day lookback. CRITICAL: Must have regime filter (HMM or OVX) to avoid trading during structural breaks like the current Hormuz crisis. Kalman filter for dynamic hedge ratio is the gold standard.

3. **Oil Volatility (OVX)** is the master filter for all energy strategies. Below 25 = mean reversion. Above 50 = trend only. Above 70 = sit out. Adding OVX filter to a simple crude oil strategy doubled average trade size and cut drawdown by 73%.

4. **Regime detection is everything** in energy markets. The existing HMM infrastructure is directly applicable. Extend it with OVX as an additional input feature for energy instruments.

---

## Sources

### Natural Gas
- [Natural Gas Futures Seasonal Chart - Equity Clock](https://equityclock.com/charts/natural-gas-futures-ng-seasonal-chart/)
- [Introduction to Natural Gas Seasonality - CME Group](https://www.cmegroup.com/education/courses/introduction-to-natural-gas/introduction-to-natural-gas-seasonality)
- [Seasonal Strategies: Trading Natural Gas - TradingView](https://www.tradingview.com/chart/NG1!/wdZo63Zv-Seasonal-Strategies-Trading-Natural-Gas-with-a-Tactical-Edge/)
- [Natural Gas Trading Strategy Explained - PapersWithBacktest](https://paperswithbacktest.com/wiki/natural-gas-trading-strategy)
- [Natural Gas Trading Strategy - QuantifiedStrategies](https://www.quantifiedstrategies.com/natural-gas-trading-strategy/)
- [How to Trade Natural Gas: 5 Technologies - PocketOption](https://pocketoption.com/blog/en/knowledge-base/learning/how-to-trade-natural-gas/)
- [Gas Algorithmic Trading - PocketOption](https://pocketoption.com/blog/en/knowledge-base/regulation-and-safety/gas-algorithmic-trading/)
- [EIA Weekly Natural Gas Storage Report](https://www.eia.gov/naturalgas/storage/)
- [EIA Natural Gas Price Volatility](https://www.eia.gov/todayinenergy/detail.php?id=65784)
- [Natural Gas Volatility Prediction: GARCH-MIDAS-ES Model](https://www.sciencedirect.com/science/article/abs/pii/S0140988322005667)
- [Forecasting Natural Gas Prices in Real Time - NBER](https://www.nber.org/system/files/working_papers/w33156/w33156.pdf)
- [GWDD/HDD/CDD Forecasts - World Climate Service](https://www.worldclimateservice.com/trading-markets-application/)
- [Temperature, Storage, and Natural Gas Futures Prices](https://onlinelibrary.wiley.com/doi/full/10.1002/fut.22402)
- [Time Traveling the Natural Gas Market - ICE White Paper](https://www.ice.com/white-paper/natural-gas-market-storage-dynamics-and-alpha-generation)
- [NatGasWeather](https://natgasweather.com/)

### Brent-WTI Spread
- [Trading WTI/BRENT Spread - Quantpedia](https://quantpedia.com/strategies/trading-wti-brent-spread)
- [Trading With WTI Brent Spread - QuantConnect](https://www.quantconnect.com/research/15376/trading-with-wti-brent-spread/)
- [Mean-Reverting Statistical Arbitrage in Crude Oil Markets - MDPI](https://www.mdpi.com/2227-9091/12/7/106)
- [Dynamic Mean Reversion Strategy with WTI and Brent Futures - WUTIS](https://wutis.at/wp-content/uploads/Mean-Reversion-in-Oil-Futures.pdf)
- [Trading the Brent-WTI Spread - Bocconi BSIC](https://bsic.it/trading-brent-wti-spread/)
- [Spread Trading Brent vs WTI - AlphaEx Capital](https://www.alphaexcapital.com/commodities/energy-commodities/crude-oil-trading/spread-trading-brent-vs-wti)
- [Kalman Filters and Statistical Arbitrage - QuantConnect](https://www.quantconnect.com/docs/v2/research-environment/applying-research/kalman-filters-and-stat-arb)
- [Neural Augmented Kalman Filtering with Bollinger Bands for Pairs Trading](https://arxiv.org/abs/2210.15448)
- [Brent WTI Spread Historical Data - YCharts](https://ycharts.com/indicators/brent_wti_spread)

### Oil Volatility
- [OVX Index Dashboard - CBOE](https://www.cboe.com/us/indices/dashboard/ovx/)
- [OVX - Your Guide to the Oil Volatility Index - City Index](https://www.cityindex.com/en-uk/news-and-analysis/ovx-oil-volatility-index/)
- [OVX and Crude Oil Price Relationship - Kalman Filter](https://www.sciencedirect.com/science/article/pii/S1877050915015975)
- [Crude Oil Trading Strategy - TradingSchools.org](https://www.tradingschools.org/reviews/crude-oil-trading/)
- [Crude Oil Trading Strategies: 10 Types - QuantifiedStrategies](https://www.quantifiedstrategies.com/crude-oil-trading-strategies/)
- [Crude Oil Futures: Volatility, Liquidity, Trading - QuantifiedStrategies](https://www.quantifiedstrategies.com/crude-oil-futures/)
- [Detection of Volatility Regime-Switching for Crude Oil](https://www.sciencedirect.com/science/article/abs/pii/S0301420719306439)
- [HMM for Statistical Arbitrage in Crude Oil](https://ideas.repec.org/p/arx/papers/2309.00875.html)
- [HMMs for Trend-Following Volatility Prediction - MQL5](https://www.mql5.com/en/articles/16830)
- [Market Regimes Explained - LuxAlgo](https://www.luxalgo.com/blog/market-regimes-explained-build-winning-trading-strategies/)

### Current Market (March 2026)
- [Crude Oil Price Forecast: Strait of Hormuz Closure - Capital.com](https://capital.com/en-int/market-updates/crude-oil-price-forecast-09-03-2026)
- [US-Iran Conflict: Strait of Hormuz Crisis - Kpler](https://www.kpler.com/blog/us-iran-conflict-strait-of-hormuz-crisis-reshapes-global-oil-markets)
- [Oil Prices Soar Above $100 - CNN](https://www.cnn.com/2026/03/12/energy/oil-jump-record-reserves-release-intl-hnk)
- [Goldman Sachs Raises Crude Price Forecast - BOE Report](https://boereport.com/2026/03/11/goldman-sachs-raises-q4-brent-wti-crude-price-forecast-amid-longer-hormuz-disruption/)
- [Oil Prices: Analysts Raise Alarm - CNBC](https://www.cnbc.com/2026/03/09/oil-prices-iran-war-middle-east-us-israel-strait-of-hormuz.html)
- [Brent Oil Closes at $100 - CNBC](https://www.cnbc.com/2026/03/12/oil-prices-jump-iea-record-reserve-release-markets-doubt-relief.html)
