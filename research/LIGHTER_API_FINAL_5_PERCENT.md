# Lighter API — The Final 5% (Mar 17, 2026)

## BIGGEST DISCOVERY: WebSocket Streaming Exists!

We've been polling REST APIs every 10-60 seconds. Lighter has a FULL WebSocket at:
`wss://mainnet.zklighter.elliot.ai/stream`

| Channel | What it gives us |
|---------|-----------------|
| `order_book/{MARKET}` | 50ms order book updates — real-time whale detection |
| `trade/{MARKET}` | Every trade — real-time CVD proxy |
| `market_stats/{MARKET}` | Streaming OI, funding rate, mark/index price |
| `notification/{ACCOUNT}` | Liquidation alerts pushed to us |

The lighter-python SDK already supports this (`lighter.WebSocket`). This eliminates rate limiting entirely and gives us sub-second data.

## Implementation Roadmap (all FREE)

| # | Feature | Edge |
|---|---------|------|
| 1 | **WebSocket streaming** | Millisecond data vs 10-60s polling |
| 2 | **Order book depth imbalance** | Bid/ask ratio > 2:1 = directional signal |
| 3 | **Funding rate z-score** | Extreme funding = contrarian signal |
| 4 | **Trade flow aggressor ratio** | Real-time CVD native to Lighter |
| 5 | **Coinalyze API** (free, 40 req/min) | Cross-exchange OI + funding + liquidations |

## Order Book Depth Analysis

`/api/v1/orderBookOrders` returns up to 250 levels with:
- `owner_account_index` — track which accounts place large orders
- `initial_base_amount` / `remaining_base_amount` — order sizes
- Whale detection: single account placing 10x median order = institutional

## Funding Rate History

`CandlestickApi.fundings()` — we never call this! Returns historical funding candles.
- Z-score > 2 (extreme positive funding) = short signal (longs overlevered)
- Z-score < -2 = long signal (shorts overlevered)
- Half-life: extreme funding reverts within 4-24 hours

## Trade Flow Analysis (data already fetched, signal ignored)

`recent_trades` includes `is_maker_ask` field:
- Taker buy volume vs taker sell volume = real-time CVD
- Trades > 3x median = institutional flow
- Liquidation type appearing = volatility escalating

## Coinalyze API (FREE, 40 req/min)

Cross-exchange aggregated data:
- Open interest history (OHLC)
- Funding rate history across 25 exchanges
- Liquidation history
- Predicted funding rates

High OI + extreme positive funding = short squeeze risk.

## NOT worth paying for (yet)
- CoinGlass: $29/mo — Coinalyze covers same data free
- Glassnode: $799/yr — daily resolution only on free tier
- Whale Alert: $30/mo — on-chain only, not exchange activity
