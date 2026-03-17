# Quant Brain v1.0 — Full Dual-Domain Architecture

## System Overview

```mermaid
graph TB
    subgraph DATA["DATA SOURCES"]
        MT5["MT5 Wine/QEMU\n14 forex symbols, 4 TFs\nDOM orderbook"]
        LIGHTER_API["Lighter.xyz DEX\nZero-fee perps\n30+ symbols"]
        HL_API["Hyperliquid\nOn-chain perps\nMainnet"]
        RSS["RSS Feeds\nCNBC, MarketWatch\nBBC, Yahoo"]
        PI["Raspberry Pi 5\nFinBERT NLP 67ms\nOllama Qwen 2.5"]
        CLAUDE["Claude Haiku\nCausal analysis\n100 EUR budget"]
    end

    subgraph INTEL["SHARED INTELLIGENCE LAYER"]
        NEWS_CHAIN{"News Priority Chain\nPi -> Claude -> Keywords"}
        PI --> |"1st: FinBERT NLP"| NEWS_CHAIN
        CLAUDE --> |"2nd: Causal chains"| NEWS_CHAIN
        RSS --> |"3rd: Keywords"| NEWS_CHAIN
        NEWS_CHAIN --> RISK["Risk Level\nEXTREME 0.5x\nELEVATED 0.75x\nNORMAL 1.0x"]
        CLAUDE --> CAUSAL["CausalChain nodes\nIran -> oil -> gold -> crypto"]
    end

    subgraph FOREX["FOREX DOMAIN"]
        direction TB
        subgraph FX_ENGINES["Entry Engines"]
            CVD["CVD Entry\n60s + RT ticks\n6 active strategies\n23 gates"]
            STRUCT["Structure Scanner\n30s, autonomous\n4 setup types"]
        end
        subgraph FX_BRAIN["Brain Pipeline"]
            MTF["MTF Context\nH4->H1->M15->M5"]
            ZONES["Zone Mapper\nFVGs + Order Blocks"]
            CONF["Confluence 0-14\n10 factors"]
            FX_SL["Structure SL/TP\nMin R:R 2.0"]
            OB["Orderbook DOM\nBid/ask imbalance"]
            FX_SIZING["Risk Sizing\n50 EUR max loss\n12-factor compound"]
        end
        subgraph FX_EXEC["Execution"]
            FX_ORDER["MT5 /order\nFILLING_IOC"]
        end
        subgraph FX_MANAGE["Position Management"]
            PM["6-phase trailing\nEvery 2s"]
            FX_CLOSE["Close algorithm\nDeal history sync\nEvery 15s"]
            FX_RECON["Reconciliation\nMT5 <-> DB\nEvery 30s"]
            FX_CB["Circuit Breaker\n5 losses -> 5m\nVol override -> 2.5m"]
        end
    end

    subgraph CRYPTO["CRYPTO DOMAIN"]
        direction TB
        subgraph CR_ENGINES["Entry Engines"]
            RSI2["RSI(2) Scalper\nEvery 30s\n5m candles\nRSI<15 + EMA(50)"]
            MR["Mean Reversion\nEvery 45s\n15m candles\nBB + RSI + ADX\n+ liquidation cascade"]
            EMA["EMA Entry\nEvery 60s\n1h EMA(8/21)\n+ 15m RSI timing"]
        end
        subgraph CR_INTEL["Intelligence"]
            CR_NEWS["News Sentiment\nSizing modifier"]
            CR_GRAPH["Graph Advisor\nPattern memory\nCAUTION 0.7x"]
            CR_WHALE["Whale Detection\nCVD flow analysis\nBuy/sell pressure"]
            CR_FUNDING["Funding Signal\nRate z-score\nContrarian sizing"]
        end
        subgraph CR_EXEC["Execution"]
            PROXY["Signer Proxy :5555\nGo native on macOS"]
            CR_ORDER["Lighter Protocol\nZero-fee market orders\nOn-chain SL/TP (OCO)"]
        end
        subgraph CR_MANAGE["Position Management"]
            CR_EXIT["Exit Algorithm\nEvery 30s\nTrailing + SL/TP"]
            CR_RECON["Reconciliation\nExchange <-> DB\nEvery 60s\nSide flip detection"]
            CR_GRID["Grid Strategy\nEvery 60s"]
        end
    end

    subgraph NEO["NEO4J KNOWLEDGE GRAPH"]
        TRADES["Trade 308+\nForex + Crypto\nRULE_BASED -> BRAIN_V1"]
        REASONING["TradeReasoning 6+\nWHY each trade\nSetup + context"]
        CHAINS["CausalChain\nEvent -> impact\nPREDICTS_IMPACT"]
        REJECTED["RejectedSignal 575+\nBlocked entries\nRejection layer"]
        ERAS["TradingEra\nRULE_BASED\nBRAIN_V1"]
        ICT_P["ICTPartial 900+\n5-step chain attempts"]
    end

    subgraph DASH["DASHBOARD"]
        FX_DASH["Forex Pages\nOverview, Positions\nHistory, Chart\nStrategies, Logs\nML, AI Brain"]
        CR_DASH["Crypto Pages\nOverview + News Feed\nPositions, History\nChart, Logs\nStrategies"]
        WS["WebSocket :8001\nReal-time events\ntrade/position/status/news"]
    end

    %% Data flows
    MT5 --> CVD
    MT5 --> STRUCT
    LIGHTER_API --> RSI2
    LIGHTER_API --> MR
    LIGHTER_API --> EMA
    HL_API --> CR_DASH

    %% Forex pipeline
    CVD --> MTF
    STRUCT --> MTF
    MTF --> ZONES --> CONF --> FX_SL
    FX_SL --> OB --> FX_SIZING
    RISK --> FX_SIZING
    FX_SIZING --> FX_ORDER

    %% Crypto pipeline
    RSI2 --> CR_NEWS
    MR --> CR_NEWS
    EMA --> CR_NEWS
    CR_NEWS --> CR_GRAPH
    CR_GRAPH --> CR_WHALE
    CR_WHALE --> CR_ORDER
    CR_ORDER --> PROXY

    %% Neo4j connections
    FX_ORDER --> TRADES
    CR_ORDER --> TRADES
    FX_ORDER --> REASONING
    CR_ORDER --> REASONING
    CAUSAL --> CHAINS

    %% Management
    PM --> MT5
    FX_RECON --> MT5
    CR_EXIT --> LIGHTER_API
    CR_RECON --> LIGHTER_API

    %% Dashboard
    TRADES --> WS
    WS --> CR_DASH
    WS --> FX_DASH
```

## Intelligence Flow (Shared Across Domains)

```mermaid
flowchart LR
    subgraph Headlines
        H1[CNBC]
        H2[MarketWatch]
        H3[BBC]
        H4[Yahoo]
    end

    Headlines --> |RSS fetch| PI_NLP["Pi FinBERT\n67ms NLP"]
    Headlines --> |If Pi fails| CLAUDE_AI["Claude Haiku\nCausal analysis"]
    Headlines --> |If both fail| KW["Keywords\n26 high-impact"]

    PI_NLP --> |risk_level + size_mult| CACHE[(Redis Cache\n5 min TTL)]
    CLAUDE_AI --> |risk + causal chains| CACHE
    CLAUDE_AI --> |chains| NEO4J[(Neo4j\nCausalChain nodes)]
    KW --> |risk_level| CACHE

    CACHE --> FX_ENTRY[Forex Entry\n12-factor sizing]
    CACHE --> CR_ENTRY[Crypto Entry\nAll 3 strategies]
    NEO4J --> ADVISOR[Graph Advisor\nTemporal decay 7d\nBRAIN_V1 2x weight]
    ADVISOR --> FX_ENTRY
    ADVISOR --> CR_ENTRY
```

## Forex Entry Pipeline (23 Gates)

```mermaid
flowchart TD
    SIGNAL["CVD Signal or\nStructure Setup"] --> MTF_CHECK{"MTF Context\nHTF trend?"}
    MTF_CHECK --> |Conflicts| SKIP1["Skip"]
    MTF_CHECK --> |Aligns| CONFLUENCE["Confluence Score\n0-14 points"]

    CONFLUENCE --> |"Score < 3"| SKIP2["Skip"]
    CONFLUENCE --> |"Score >= 3"| STRUCT_SL["Structure SL/TP\nSwing point SL\nZone TP"]

    STRUCT_SL --> |"R:R < 2.0"| SKIP3["Skip"]
    STRUCT_SL --> |"R:R >= 2.0"| NEO_ADV["Neo4j Advisor\n7-day decay queries\nCausal sentiment"]

    NEO_ADV --> |"AVOID"| SKIP4["Skip"]
    NEO_ADV --> |"NORMAL+"| OB_CHECK["Orderbook\nDOM check"]

    OB_CHECK --> MARGIN_CHK["Margin Check\n+ Order Dry-Run"]
    MARGIN_CHK --> |Fails| SKIP5["Skip"]
    MARGIN_CHK --> |Passes| SIZING["Risk-Based Sizing\n50 EUR x news x graph\ndiv loss_per_lot"]

    SIZING --> EXECUTE["EXECUTE TRADE"]
    EXECUTE --> RECORD_DB["PostgreSQL"]
    EXECUTE --> RECORD_NEO["Neo4j\nTrade + Reasoning"]
    EXECUTE --> RECORD_WS["WebSocket push"]
```

## Crypto Entry Pipeline (Unshackled — Training Mode)

```mermaid
flowchart TD
    subgraph RSI2_FLOW["RSI(2) Scalper — Every 30s"]
        RSI_SIG["RSI(2) < 15 + Price > EMA(50)\nor RSI(2) > 85 + Price < EMA(50)"]
        RSI_SIG --> RSI_NEWS["News Sentiment\nSizing only"]
        RSI_NEWS --> RSI_GRAPH["Graph Advisor\nCAUTION=0.7x\nAVOID=skip"]
        RSI_GRAPH --> RSI_WHALE["Whale CVD\nFlow analysis"]
        RSI_WHALE --> RSI_SIZE["Position Sizing\n$8 x leverage x news x graph\nx neo4j x funding x flow"]
        RSI_SIZE --> RSI_EXEC["Market Order\n+ OCO SL/TP on-chain"]
    end

    subgraph MR_FLOW["Mean Reversion — Every 45s"]
        MR_SIG["Price near BB(20,2.5)\n+ RSI oversold/overbought\n+ ADX < 40 (ranging)"]
        MR_LIQ{"Liquidation\nCascade?"}
        MR_SIG --> MR_LIQ
        MR_LIQ --> |"Aligned"| MR_BOOST["1.5x boost"]
        MR_LIQ --> |"Alone"| MR_HALF["0.5x solo entry"]
        MR_LIQ --> |"None"| MR_NORMAL["Normal size"]
        MR_BOOST --> MR_INTEL["News + Graph\nSizing modifiers"]
        MR_HALF --> MR_INTEL
        MR_NORMAL --> MR_INTEL
        MR_INTEL --> MR_EXEC["Market Order\n+ OCO SL/TP"]
    end

    subgraph EMA_FLOW["EMA Entry — Every 60s"]
        EMA_SIG["1h EMA(8/21) Crossover\nor Extreme RSI Pullback\ntrend_pullback DISABLED"]
        EMA_SIG --> EMA_INTEL["News + Graph\nSizing modifiers"]
        EMA_INTEL --> EMA_EXEC["Market Order\n+ OCO SL/TP"]
    end

    RSI_EXEC --> RECORD["Record to DB\n+ Neo4j TradeReasoning\n+ WebSocket push"]
    MR_EXEC --> RECORD
    EMA_EXEC --> RECORD
```

## Disabled Crypto Gates (Training Mode)

```mermaid
flowchart LR
    ML["ML Filter\nXGBoost score < 0.55\nBLANKET 0.44 on all"] --> |DISABLED| X1["Was blocking 92%\nof signals"]
    STREAK["Losing Streak\n5 losses -> 5m pause"] --> |DISABLED| X2["Brain needs to\nobserve all conditions"]
    PULLBACK["trend_pullback_15m\n36% WR, -$2.38"] --> |KILLED| X3["Statistically\nlosing strategy"]

    style ML fill:#ef4444,color:#fff
    style STREAK fill:#ef4444,color:#fff
    style PULLBACK fill:#ef4444,color:#fff
    style X1 fill:#1e293b,color:#9ca3af
    style X2 fill:#1e293b,color:#9ca3af
    style X3 fill:#1e293b,color:#9ca3af
```

## Neo4j Knowledge Graph Schema

```mermaid
graph LR
    TRADE((Trade\n308+)) --> |TRADED_SYMBOL| SYMBOL((Symbol\n18))
    TRADE --> |EXECUTED_BY| STRATEGY((Strategy\n19))

    REASONING((TradeReasoning)) --> |REASONING_FOR| TRADE

    CAUSAL((CausalChain)) --> |PREDICTS_IMPACT| SYMBOL

    ERA1((RULE_BASED)) --> |SUCCEEDED_BY| ERA2((BRAIN_V1))

    EXIT((ExitEvent\n419)) --> |EXIT_FOR| TRADE
    ICT((ICTPartial\n900+)) --> |ON_SYMBOL| SYMBOL
    REJECTED((RejectedSignal\n575+)) --> |ON_SYMBOL| SYMBOL

    style TRADE fill:#4ade80,color:#000
    style REASONING fill:#60a5fa,color:#000
    style CAUSAL fill:#f97316,color:#000
    style ERA2 fill:#8b5cf6,color:#fff
    style SYMBOL fill:#fbbf24,color:#000
    style REJECTED fill:#f472b6,color:#000
```

## Hardware Topology

```mermaid
graph TB
    subgraph MINI["Mac Mini M4 16GB — 24/7 Trading Server"]
        direction TB
        MT5_C["MT5 Wine/QEMU\n910MB, 2 CPUs"]
        CELERY_C["Celery 6 workers\n~2GB, 2 CPUs\n+ WS server :8001\n+ tick consumer"]
        DJANGO_C["Django 4 workers\n~670MB, 1.5 CPUs"]
        NEO4J_C["Neo4j 768MB\nHeap 256MB"]
        REDIS_C["Redis 512MB\n3 DBs: broker/cache/ticks"]
        PG_C["PostgreSQL 58MB"]
        DASH_C["Dashboard :3080\nVue 3 + Vite"]
        PROXY_C["Lighter Proxy :5555\nGo signer on macOS"]
    end

    subgraph PI_HW["Raspberry Pi 5 16GB + Hailo 40 TOPS"]
        direction TB
        FINBERT["FinBERT ONNX\n67ms sentiment"]
        OLLAMA["Ollama\nQwen 2.5 + Gemma"]
        XGBOOST_PI["XGBoost ONNX\nWaiting for model"]
        FLASK_PI["Flask :8100"]
    end

    subgraph CLOUD["External APIs"]
        ANTHROPIC["Claude Haiku\n100 EUR budget"]
        VANTAGE["Vantage MT5\nDemo account"]
        LIGHTER_EX["Lighter.xyz\nTestnet DEX\nAccount #718566"]
        HYPERLIQ["Hyperliquid\nMainnet\n$0 balance"]
    end

    CELERY_C <--> |"HTTP :8100"| FLASK_PI
    MT5_C <--> |"HTTP :5001"| VANTAGE
    CELERY_C <--> |"HTTPS"| ANTHROPIC
    CELERY_C <--> |"HTTP :5555"| PROXY_C
    PROXY_C <--> |"HTTPS"| LIGHTER_EX
    CELERY_C <--> |"HTTPS"| HYPERLIQ
    CELERY_C <--> NEO4J_C
    CELERY_C <--> REDIS_C
    CELERY_C <--> PG_C
    DASH_C <--> DJANGO_C

    style MINI fill:#1e293b,color:#e2e8f0
    style PI_HW fill:#1e3a1e,color:#bbf7d0
    style CLOUD fill:#1e1e3a,color:#c4b5fd
```

## Container Memory Budget (Optimized Mar 17)

```mermaid
pie title Memory Allocation (9.8GB of 16GB)
    "Celery (6 workers)" : 3072
    "MT5 (Wine/QEMU)" : 2048
    "Django (4 workers)" : 1536
    "Neo4j (256m heap)" : 768
    "Redis" : 512
    "Celery-Beat" : 512
    "8x Monitoring" : 2048
```

## Crypto Performance (160+ trades)

```mermaid
xychart-beta
    title "Crypto Strategy Performance"
    x-axis ["Reconciled", "RSI2 Buy", "Crossover", "RSI2 Sell", "Pullback (KILLED)"]
    y-axis "Total PnL ($)" -5 --> 35
    bar [31.58, 5.63, 0.79, -1.72, -2.38]
```

## Trading Eras Timeline

```mermaid
timeline
    title Trading System Evolution
    section Rule-Based Era (Mar 15-17)
        Mar 15 : Forex + Crypto bots launched
               : Fixed ATR SL/TP, CVD signals only
               : Lighter.xyz integration ($10 account)
               : 82 forex trades, 40% WR
    section Brain v1 Era (Mar 17+)
        Mar 17 AM : Structure reader, autonomous scanner
                  : Neo4j advisor, temporal decay
                  : Risk-based sizing, news sentiment
        Mar 17 PM : Claude API causal intelligence
                  : Pi FinBERT NLP connected
                  : Trade reasoning memory
                  : WebSocket dashboard live
                  : Crypto news feed card (Finnhub)
                  : DOM orderbook integration
        Mar 17 EVE : Crypto intelligence wired
                   : News + Graph + Reasoning on all 3 strategies
                   : ML filter disabled (training mode)
                   : Streak cooldown disabled
                   : trend_pullback killed (36% WR)
                   : Container memory optimized (14.5GB -> 9.8GB)
                   : Neo4j pruned (36K junk -> 1.7K nodes)
                   : Reconciler side-flip bug fixed
                   : Funding rates + chart data fixed
                   : Entry context pipeline (Redis bridge)
    section Growth Targets
        200 trades : Re-enable ML filter at 0.40 threshold
        $200 equity : Re-enable losing streak cooldown
        500 trades : ML threshold -> 0.55, graph features active
        $500 equity : Increase position limits + sizing
```

## Cross-Domain Data Flow

```mermaid
flowchart TB
    subgraph FOREX_SIGNALS["Forex Signals"]
        FX_NEWS["News: Iran sanctions\noil spike detected"]
        FX_REGIME["Regime: USD strength\nrisk-off detected"]
    end

    subgraph SHARED_BRAIN["Shared Knowledge Graph"]
        CHAIN1["CausalChain:\nIran -> oil -> USD -> gold -> crypto risk-off"]
        ADVISOR2["Graph Advisor:\nBTC loses 65% WR in risk-off"]
    end

    subgraph CRYPTO_IMPACT["Crypto Impact"]
        CR_SIZE["BTC LONG sizing: 0.5x\nSOL LONG sizing: 0.5x\nETH LONG: AVOID"]
    end

    FX_NEWS --> CHAIN1
    FX_REGIME --> CHAIN1
    CHAIN1 --> ADVISOR2
    ADVISOR2 --> CR_SIZE
```
