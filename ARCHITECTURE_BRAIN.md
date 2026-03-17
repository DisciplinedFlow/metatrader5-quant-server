# Quant Brain v1.0 — Full Architecture

## System Overview

```mermaid
graph TB
    subgraph DATA["📡 DATA SOURCES"]
        MT5["MT5 Wine/QEMU<br/>14 symbols, 4 TFs<br/>DOM orderbook"]
        RSS["RSS Feeds<br/>CNBC, MarketWatch<br/>BBC, Yahoo"]
        PI["🍓 Raspberry Pi 5<br/>FinBERT NLP 67ms<br/>Ollama Qwen 2.5"]
        CLAUDE["🧠 Claude Haiku<br/>Causal analysis<br/>€100 budget"]
    end

    subgraph INTEL["🔬 INTELLIGENCE LAYER"]
        NEWS_CHAIN{"News Priority Chain"}
        PI --> |"1st: FinBERT NLP"| NEWS_CHAIN
        CLAUDE --> |"2nd: Causal chains"| NEWS_CHAIN
        RSS --> |"3rd: Keywords"| NEWS_CHAIN
        NEWS_CHAIN --> RISK["Risk Level<br/>EXTREME → 0.5x<br/>ELEVATED → 0.75x<br/>NORMAL → 1.0x"]
        CLAUDE --> CAUSAL["CausalChain nodes<br/>Iran → oil → gold"]
    end

    subgraph ENGINES["⚡ DUAL ENTRY ENGINES"]
        direction TB
        CVD["ENGINE 1: CVD Entry<br/>Every 60s + RT ticks<br/>6 active strategies"]
        STRUCT["ENGINE 2: Structure Scanner<br/>Every 30s, autonomous<br/>4 setup types"]
    end

    subgraph BRAIN["🧊 BRAIN PIPELINE"]
        MTF["MTF Context<br/>H4→H1→M15→M5<br/>HH/HL/LH/LL<br/>BOS/CHoCH"]
        ZONES["Zone Mapper<br/>FVGs + Order Blocks<br/>Proximity detection"]
        CONF["Confluence 0-14<br/>HTF, CVD, regime,<br/>VWAP, session, sweep"]
        SL_TP["Structure SL/TP<br/>SL behind swing<br/>TP at opposing zone<br/>Min R:R 2.0"]
        ADVISOR["Neo4j Advisor<br/>Similar setups WR<br/>Causal sentiment<br/>Temporal decay 7d"]
        OB["Orderbook DOM<br/>Bid/ask imbalance<br/>Liquidity levels"]
        MARGIN["Margin + Dry-run<br/>Pre-validate order"]
        SIZING["Risk-Based Sizing<br/>lots = €50 / loss_at_SL<br/>× news × graph mod"]
    end

    subgraph EXEC["💰 EXECUTION"]
        ORDER["MT5 /order<br/>Send market order"]
        RECORD["Record Trade<br/>PostgreSQL + Neo4j<br/>+ TradeReasoning<br/>+ WebSocket push"]
    end

    subgraph MANAGE["🔄 POSITION MANAGEMENT"]
        PM["Position Manager<br/>6-phase trailing<br/>Every 2s"]
        CLOSE["Close Algorithm<br/>Deal history sync<br/>Every 15s"]
        RECON["Reconciliation<br/>MT5↔DB sync<br/>Every 30s"]
        CB["Circuit Breaker<br/>5 losses → 5m<br/>Vol override → 2.5m"]
    end

    subgraph NEO["🧠 NEO4J KNOWLEDGE GRAPH"]
        TRADES["Trade nodes 234+<br/>RULE_BASED → BRAIN_V1"]
        REASONING["TradeReasoning<br/>WHY each trade taken"]
        CHAINS["CausalChain nodes<br/>Event → impact chains"]
        ERAS["TradingEra nodes<br/>RULE_BASED ──SUCCEEDED_BY──► BRAIN_V1"]
        ICT["ICTPartial 24K+"]
    end

    subgraph DASH["📊 DASHBOARD"]
        VUE["Vue 3 :3080<br/>Overview, Positions<br/>History, Strategies"]
        WS["WebSocket :8001<br/>Real-time updates<br/>Green 'Live' indicator"]
    end

    MT5 --> CVD
    MT5 --> STRUCT
    CVD --> MTF
    STRUCT --> MTF
    MTF --> ZONES
    ZONES --> CONF
    CONF --> SL_TP
    SL_TP --> ADVISOR
    ADVISOR --> OB
    OB --> MARGIN
    MARGIN --> SIZING
    RISK --> SIZING
    SIZING --> ORDER
    ORDER --> RECORD
    RECORD --> NEO
    RECORD --> WS
    CAUSAL --> CHAINS
    ADVISOR --> CHAINS
    ADVISOR --> TRADES
    ADVISOR --> REASONING
    CLOSE --> RECORD
    PM --> MT5
    RECON --> MT5
```

## Intelligence Flow

```mermaid
flowchart LR
    subgraph Headlines
        H1[CNBC]
        H2[MarketWatch]
        H3[BBC]
        H4[Yahoo]
    end

    Headlines --> |RSS fetch| PI_NLP[🍓 Pi FinBERT<br/>67ms NLP]
    Headlines --> |If Pi fails| CLAUDE_AI[🧠 Claude Haiku<br/>Causal analysis]
    Headlines --> |If both fail| KW[Keywords<br/>26 high-impact]

    PI_NLP --> |risk_level + size_mult| CACHE[(Redis Cache<br/>5 min TTL)]
    CLAUDE_AI --> |risk + causal chains| CACHE
    CLAUDE_AI --> |chains| NEO4J[(Neo4j<br/>CausalChain nodes)]
    KW --> |risk_level| CACHE

    CACHE --> ENTRY[Entry Algorithm<br/>sizing modifier]
    NEO4J --> ADVISOR[Graph Advisor<br/>causal sentiment]
    ADVISOR --> ENTRY
```

## Entry Decision Pipeline

```mermaid
flowchart TD
    SIGNAL[CVD Signal or Structure Setup] --> MTF_CHECK{MTF Context<br/>HTF trend?}
    MTF_CHECK --> |Conflicts with trade| SKIP1[Skip ❌]
    MTF_CHECK --> |Aligns or neutral| CONFLUENCE[Confluence Score<br/>0-14 points]

    CONFLUENCE --> |Score < 3| SKIP2[Skip ❌]
    CONFLUENCE --> |Score >= 3| STRUCT_SL[Structure SL/TP<br/>Swing point SL<br/>Zone TP]

    STRUCT_SL --> |R:R < 2.0| SKIP3[Skip ❌]
    STRUCT_SL --> |R:R >= 2.0| NEO_ADV[Neo4j Advisor<br/>7-day decay queries<br/>Causal sentiment]

    NEO_ADV --> |AVOID conf < 0.2| SKIP4[Skip ❌]
    NEO_ADV --> |NORMAL+| OB_CHECK[Orderbook<br/>DOM check]

    OB_CHECK --> MARGIN_CHK[Margin Check<br/>+ Order Dry-Run]
    MARGIN_CHK --> |Fails| SKIP5[Skip ❌]
    MARGIN_CHK --> |Passes| SIZING[Risk-Based Sizing<br/>€50 × news × graph<br/>÷ loss_per_lot]

    SIZING --> EXECUTE[🎯 EXECUTE TRADE]
    EXECUTE --> RECORD_DB[PostgreSQL<br/>Trade record]
    EXECUTE --> RECORD_NEO[Neo4j<br/>Trade + Reasoning]
    EXECUTE --> RECORD_WS[WebSocket<br/>Dashboard push]
```

## Neo4j Knowledge Graph Schema

```mermaid
graph LR
    TRADE((Trade)) --> |TRADED_SYMBOL| SYMBOL((Symbol))
    TRADE --> |EXECUTED_BY| STRATEGY((Strategy))

    REASONING((TradeReasoning)) --> |REASONING_FOR| TRADE

    CAUSAL((CausalChain)) --> |PREDICTS_IMPACT| SYMBOL

    ERA1((RULE_BASED)) --> |SUCCEEDED_BY| ERA2((BRAIN_V1))

    EXIT((ExitEvent)) --> |EXIT_FOR| TRADE
    ICT((ICTPartial)) --> |ON_SYMBOL| SYMBOL

    NEWS((NewsEvent)) --> |AFFECTS| SYMBOL

    style TRADE fill:#4ade80,color:#000
    style REASONING fill:#60a5fa,color:#000
    style CAUSAL fill:#f97316,color:#000
    style ERA2 fill:#8b5cf6,color:#fff
    style SYMBOL fill:#fbbf24,color:#000
```

## Hardware Topology

```mermaid
graph TB
    subgraph MINI["🖥️ Mac Mini M4 16GB (24/7)"]
        direction TB
        MT5_C["MT5 Wine/QEMU<br/>1.75GB + 209% CPU"]
        CELERY_C["Celery 8 workers<br/>1.8GB"]
        DJANGO_C["Django API<br/>952MB"]
        NEO4J_C["Neo4j 1.25GB"]
        REDIS_C["Redis 512MB"]
        PG_C["PostgreSQL"]
        DASH_C["Dashboard :3080"]
        WS_C["WebSocket :8001"]
    end

    subgraph PI_HW["🍓 Raspberry Pi 5 16GB + Hailo 40 TOPS"]
        direction TB
        FINBERT["FinBERT ONNX<br/>67ms sentiment"]
        OLLAMA["Ollama<br/>Qwen 2.5 + Gemma"]
        XGBOOST["XGBoost ONNX<br/>(waiting for model)"]
        FLASK_PI["Flask :8100"]
    end

    subgraph CLOUD["☁️ External APIs"]
        ANTHROPIC["Claude Haiku<br/>€100 budget"]
        VANTAGE["Vantage MT5<br/>Demo account"]
    end

    CELERY_C <--> |"HTTP :8100<br/>172.28.55.86"| FLASK_PI
    MT5_C <--> |"HTTP :5001"| VANTAGE
    CELERY_C <--> |"HTTPS"| ANTHROPIC
    CELERY_C <--> NEO4J_C
    CELERY_C <--> REDIS_C
    CELERY_C <--> PG_C
    WS_C <--> REDIS_C
    DASH_C <--> DJANGO_C

    style MINI fill:#1e293b,color:#e2e8f0
    style PI_HW fill:#1e3a1e,color:#bbf7d0
    style CLOUD fill:#1e1e3a,color:#c4b5fd
```

## Performance Comparison

```mermaid
xychart-beta
    title "Rule Era vs Brain Era"
    x-axis ["Avg Loss $", "R:R Ratio", "Expectancy $/trade"]
    y-axis "Value" 0 --> 5
    bar [4.51, 0.73, 1.37]
    bar [0.82, 1.49, 0.20]
```

## Trading Eras Timeline

```mermaid
timeline
    title Trading System Evolution
    section Rule-Based Era (Mar 15-17)
        Mar 15 : Bot launched, paper trading
                : Fixed ATR SL/TP, CVD signals only
                : 82 trades, 40% WR, -$112
    section Brain v1 Era (Mar 17+)
        Mar 17 AM : Structure reader, autonomous scanner
                  : Neo4j advisor, temporal decay
                  : Risk-based sizing, news sentiment
        Mar 17 PM : Claude API causal intelligence
                  : Pi FinBERT NLP connected
                  : Trade reasoning memory
                  : WebSocket dashboard
                  : DOM orderbook integration
                  : R:R improved 0.73 → 1.49
                  : Avg loss reduced $4.51 → $0.82
```
