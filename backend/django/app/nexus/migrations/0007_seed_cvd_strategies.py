"""Seed CVD divergence strategies for Forex, Crypto, and Polymarket domains."""

from django.db import migrations


# ─── Strategy definitions per domain ────────────────────────────────────────

FOREX_STRATEGIES = [
    {
        'name': 'CVD Lack of Participants',
        'description': (
            'Trade when price makes higher highs/lower lows but CVD fails to follow, '
            'indicating exhaustion and lack of aggressive participants. '
            'Signals potential trend reversal or weakness in forex pairs.'
        ),
        'definition': {
            'strategy_type': 'CVD_DIVERGENCE',
            'cvd_type': 'lack_of_participants',
            'timeframe': 'M15',
            'pairs': ['EURUSD', 'GBPUSD', 'XAUUSD', 'USDJPY'],
            'indicators': [
                {'type': 'CVD', 'params': {'source': 'tick_volume', 'lookback': 20}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'CVD', 'condition': 'divergence',
                     'value': 'bullish_lack_of_participants',
                     'description': 'Price makes lower low, CVD makes higher low — sellers exhausted'},
                ],
                'short': [
                    {'indicator': 'CVD', 'condition': 'divergence',
                     'value': 'bearish_lack_of_participants',
                     'description': 'Price makes higher high, CVD makes lower high — buyers exhausted'},
                ],
            },
            'exit_rules': {
                'type': 'ATR_BASED',
                'params': {'atr_period': 14, 'sl_multiplier': 1.5, 'tp_multiplier': 2.5},
            },
            'min_win_rate': 0.50,
            'rules': [
                'Identify when price makes a high followed by a higher high, while CVD makes a high followed by a lower high',
                'For downtrend: price makes lower low, CVD makes higher low',
                'Compare corresponding highs/lows on price to CVD to spot divergence',
                'Interpret divergence as exhaustion — expect corrective move',
                'Can apply on any timeframe; M15 recommended for forex',
                'Look for multiple divergence signals occurring together for stronger confirmation',
            ],
            'warnings': [
                'Divergence patterns may not always be clean or obvious',
                'Multiple forms of divergence exist — absorption is another type',
                'Divergence signals can overlap, requiring careful interpretation',
            ],
        },
    },
    {
        'name': 'CVD Absorption',
        'description': (
            'Trade when CVD makes higher highs/lower lows but price does not follow, '
            'indicating aggressive market orders are being absorbed by limit orders. '
            'The most powerful CVD divergence pattern.'
        ),
        'definition': {
            'strategy_type': 'CVD_DIVERGENCE',
            'cvd_type': 'absorption',
            'timeframe': 'M15',
            'pairs': ['EURUSD', 'GBPUSD', 'XAUUSD', 'USDJPY'],
            'indicators': [
                {'type': 'CVD', 'params': {'source': 'tick_volume', 'lookback': 20}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'CVD', 'condition': 'divergence',
                     'value': 'bullish_absorption',
                     'description': 'CVD makes lower lows (aggressive selling) but price makes higher low — buyers absorbing with limits'},
                ],
                'short': [
                    {'indicator': 'CVD', 'condition': 'divergence',
                     'value': 'bearish_absorption',
                     'description': 'CVD makes higher highs (aggressive buying) but price cannot break above — sellers absorbing with limits'},
                ],
            },
            'exit_rules': {
                'type': 'ATR_BASED',
                'params': {'atr_period': 14, 'sl_multiplier': 1.5, 'tp_multiplier': 3.0},
            },
            'min_win_rate': 0.50,
            'rules': [
                'Bearish: CVD makes higher highs while price fails to break above previous highs',
                'This shows buyers (market orders) being absorbed by sellers (limit orders)',
                'Bullish: CVD makes lower lows while price forms a higher low',
                'Shows sellers being absorbed by buyers with limit orders',
                'Look for lack of participants on subsequent highs/lows as confirmation',
                'Absorption is the most powerful divergence pattern',
            ],
            'warnings': [
                'No specific failure conditions — must use strict risk management',
                'Requires understanding of order book dynamics and limit vs market orders',
            ],
        },
    },
    {
        'name': 'CVD Real-Time Leading Indicator',
        'description': (
            'Use CVD as a leading indicator that updates with every contract traded, '
            'spotting divergences and trend exhaustion earlier than lagging oscillators '
            'that wait for candle closes.'
        ),
        'definition': {
            'strategy_type': 'CVD_DIVERGENCE',
            'cvd_type': 'real_time_leading',
            'timeframe': 'M5',
            'pairs': ['EURUSD', 'GBPUSD', 'XAUUSD'],
            'indicators': [
                {'type': 'CVD', 'params': {'source': 'tick_volume', 'lookback': 10, 'real_time': True}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'CVD', 'condition': 'leading_divergence',
                     'value': 'bullish_exhaustion_early',
                     'description': 'CVD shows buying pressure weakening in real-time before candle close confirms'},
                ],
                'short': [
                    {'indicator': 'CVD', 'condition': 'leading_divergence',
                     'value': 'bearish_exhaustion_early',
                     'description': 'CVD shows selling pressure weakening in real-time before candle close confirms'},
                ],
            },
            'exit_rules': {
                'type': 'ATR_BASED',
                'params': {'atr_period': 14, 'sl_multiplier': 1.0, 'tp_multiplier': 2.0},
            },
            'min_win_rate': 0.48,
            'rules': [
                'Monitor CVD continuously throughout candle formation, not just at closes',
                'Identify divergences forming between price movement and CVD direction in real-time',
                'Use early CVD weakness signals to anticipate reversals before traditional oscillators confirm',
                'CVD is a true leading indicator — no lag from candle-close dependency',
            ],
        },
    },
    {
        'name': 'CVD Extremes Scanner',
        'description': (
            'Systematically scan charts to identify extremes in both price and CVD, '
            'then compare to identify divergence patterns at highs and lows.'
        ),
        'definition': {
            'strategy_type': 'CVD_DIVERGENCE',
            'cvd_type': 'extremes',
            'timeframe': 'H1',
            'pairs': ['EURUSD', 'GBPUSD', 'XAUUSD', 'USDJPY', 'AUDUSD'],
            'indicators': [
                {'type': 'CVD', 'params': {'source': 'tick_volume', 'lookback': 50}},
                {'type': 'SWING_DETECTOR', 'params': {'lookback': 10, 'strength': 3}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'CVD', 'condition': 'extreme_divergence',
                     'value': 'bullish_extreme',
                     'description': 'Price at extreme low with CVD not confirming — scan for reversal'},
                ],
                'short': [
                    {'indicator': 'CVD', 'condition': 'extreme_divergence',
                     'value': 'bearish_extreme',
                     'description': 'Price at extreme high with CVD not confirming — scan for reversal'},
                ],
            },
            'exit_rules': {
                'type': 'ATR_BASED',
                'params': {'atr_period': 14, 'sl_multiplier': 2.0, 'tp_multiplier': 3.0},
            },
            'min_win_rate': 0.50,
            'rules': [
                'Scan along the chart timeline looking for extreme points in price (highest highs, lowest lows)',
                'Simultaneously identify extreme points in CVD during the same periods',
                'Compare price extremes to CVD extremes to identify divergence patterns',
                'Focus on both highs and lows — check for divergences at tops and bottoms',
                'Prioritize the clearest, most obvious divergence examples',
            ],
        },
    },
    {
        'name': 'CVD Pattern Training',
        'description': (
            'Dedicated chart template strategy for training pattern recognition skills. '
            'Price on top, CVD below — practice spotting divergences across timeframes.'
        ),
        'definition': {
            'strategy_type': 'CVD_TRAINING',
            'cvd_type': 'pattern_training',
            'timeframe': 'M15',
            'pairs': ['EURUSD', 'GBPUSD', 'XAUUSD'],
            'indicators': [
                {'type': 'CVD', 'params': {'source': 'tick_volume', 'display': 'separate_panel'}},
            ],
            'training_rules': [
                'Set up chart with price on top, CVD indicator on bottom',
                'Start on M15 timeframe as baseline',
                'Scan for lack of participants divergence first (easiest to spot)',
                'Then look for absorption patterns (CVD continues but price fails)',
                'Practice across multiple timeframes: M1, M5, M15, H1',
                'Once basic recognition is established, expand to candle structure and imbalances',
            ],
            'is_training': True,
        },
    },
    {
        'name': 'CVD Multi-Timeframe Analysis',
        'description': (
            'Analyze CVD divergences across M5, M15, H1, and H4 timeframes to identify '
            'opportunities at different trading horizons and confirm signals.'
        ),
        'definition': {
            'strategy_type': 'CVD_DIVERGENCE',
            'cvd_type': 'multi_timeframe',
            'timeframe': 'M15',
            'timeframes': ['M5', 'M15', 'H1', 'H4'],
            'pairs': ['EURUSD', 'GBPUSD', 'XAUUSD', 'USDJPY'],
            'indicators': [
                {'type': 'CVD', 'params': {'source': 'tick_volume', 'lookback': 20}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'CVD', 'condition': 'mtf_divergence',
                     'value': 'bullish_mtf_confirmed',
                     'description': 'Bullish CVD divergence confirmed on at least 2 timeframes'},
                ],
                'short': [
                    {'indicator': 'CVD', 'condition': 'mtf_divergence',
                     'value': 'bearish_mtf_confirmed',
                     'description': 'Bearish CVD divergence confirmed on at least 2 timeframes'},
                ],
            },
            'exit_rules': {
                'type': 'ATR_BASED',
                'params': {'atr_period': 14, 'sl_multiplier': 1.5, 'tp_multiplier': 2.5},
            },
            'min_win_rate': 0.52,
            'rules': [
                'Analyze CVD patterns across at least 3-4 different timeframes',
                'Identify divergences where price makes new highs but CVD fails to break its previous high',
                'When price is unable to break the CVD high, anticipate a big move down',
                'Higher timeframe confirmations strengthen the signal',
                'Switch between timeframes to find the clearest divergence signals',
            ],
        },
    },
    {
        'name': 'CVD Overlay Visualization',
        'description': (
            'Display CVD as a colored line overlay directly on the price chart to more '
            'easily visualize divergences between price and volume delta.'
        ),
        'definition': {
            'strategy_type': 'CVD_VISUALIZATION',
            'cvd_type': 'overlay',
            'timeframe': 'M15',
            'pairs': ['EURUSD', 'GBPUSD', 'XAUUSD'],
            'indicators': [
                {'type': 'CVD', 'params': {'source': 'tick_volume', 'display': 'overlay', 'color': '#34d399'}},
            ],
            'visualization_rules': [
                'Display CVD as a colored line overlay directly on the main price chart',
                'Use candlestick format for price display',
                'Apply across multiple timeframes to identify patterns (M1, M15, H1)',
                'Single-view overlay eliminates need to look between multiple panels',
                'Makes pattern recognition faster and more intuitive',
            ],
            'is_visualization': True,
        },
    },
    {
        'name': 'CVD Futures vs Spot Comparison',
        'description': (
            'Compare CVD from futures contracts versus spot FX to gain different perspectives '
            'on market participation and identify discrepancies between markets.'
        ),
        'definition': {
            'strategy_type': 'CVD_DIVERGENCE',
            'cvd_type': 'futures_vs_spot',
            'timeframe': 'H1',
            'pairs': ['EURUSD', 'GBPUSD', 'USDJPY'],
            'indicators': [
                {'type': 'CVD', 'params': {'source': 'tick_volume', 'market': 'spot'}},
                {'type': 'CVD', 'params': {'source': 'tick_volume', 'market': 'futures'}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'CVD', 'condition': 'cross_market_divergence',
                     'value': 'bullish_spot_vs_futures',
                     'description': 'Spot CVD shows accumulation while futures CVD shows distribution'},
                ],
                'short': [
                    {'indicator': 'CVD', 'condition': 'cross_market_divergence',
                     'value': 'bearish_spot_vs_futures',
                     'description': 'Spot CVD shows distribution while futures CVD shows accumulation'},
                ],
            },
            'exit_rules': {
                'type': 'ATR_BASED',
                'params': {'atr_period': 14, 'sl_multiplier': 2.0, 'tp_multiplier': 3.0},
            },
            'min_win_rate': 0.48,
            'rules': [
                'Switch between viewing CVD data from spot FX and currency futures',
                'Analyze differences in CVD behavior between the two market types',
                'Spot reflects organic flow from hedgers and corporates',
                'Futures includes leveraged speculators and institutional positioning',
                'Look for discrepancies between spot and futures CVD readings',
            ],
        },
    },
]

CRYPTO_STRATEGIES = [
    {
        'name': 'CVD Lack of Participants',
        'description': (
            'Trade when price makes higher highs/lower lows but CVD fails to follow on crypto pairs. '
            'Exchange order flow reveals exhaustion and lack of aggressive participants.'
        ),
        'definition': {
            'strategy_type': 'CVD_DIVERGENCE',
            'cvd_type': 'lack_of_participants',
            'timeframe': '15m',
            'pairs': ['BTC', 'ETH', 'SOL', 'AVAX'],
            'indicators': [
                {'type': 'CVD', 'params': {'source': 'exchange_volume', 'exchange': 'binance', 'lookback': 20}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'CVD', 'condition': 'divergence',
                     'value': 'bullish_lack_of_participants',
                     'description': 'Price makes lower low, CVD makes higher low — sellers exhausted'},
                ],
                'short': [
                    {'indicator': 'CVD', 'condition': 'divergence',
                     'value': 'bearish_lack_of_participants',
                     'description': 'Price makes higher high, CVD makes lower high — buyers exhausted'},
                ],
            },
            'exit_rules': {
                'type': 'PERCENTAGE_BASED',
                'params': {'stop_loss_pct': 0.02, 'take_profit_pct': 0.05},
            },
            'min_win_rate': 0.50,
            'rules': [
                'Identify when price makes a high followed by a higher high, while CVD makes a lower high',
                'For downtrend: price makes lower low, CVD makes higher low',
                'Use exchange order flow data (Binance/Hyperliquid) for accurate CVD',
                'Crypto markets have 24/7 volume — divergences are more reliable',
                'Apply on 5m-15m for scalps, 1h-4h for swing trades',
                'Look for multiple divergence signals for stronger confirmation',
            ],
            'warnings': [
                'Crypto volatility can produce false divergences during liquidation cascades',
                'Verify with funding rate data when possible',
            ],
        },
    },
    {
        'name': 'CVD Absorption',
        'description': (
            'Trade when CVD makes higher highs/lower lows but crypto price does not follow. '
            'Aggressive market orders are being absorbed by limit orders on the order book. '
            'The most powerful CVD divergence pattern.'
        ),
        'definition': {
            'strategy_type': 'CVD_DIVERGENCE',
            'cvd_type': 'absorption',
            'timeframe': '15m',
            'pairs': ['BTC', 'ETH', 'SOL', 'AVAX'],
            'indicators': [
                {'type': 'CVD', 'params': {'source': 'exchange_volume', 'exchange': 'binance', 'lookback': 20}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'CVD', 'condition': 'divergence',
                     'value': 'bullish_absorption',
                     'description': 'CVD makes lower lows (aggressive selling) but price holds — whale limit buys absorbing'},
                ],
                'short': [
                    {'indicator': 'CVD', 'condition': 'divergence',
                     'value': 'bearish_absorption',
                     'description': 'CVD makes higher highs (aggressive buying) but price cannot break — whale limit sells absorbing'},
                ],
            },
            'exit_rules': {
                'type': 'PERCENTAGE_BASED',
                'params': {'stop_loss_pct': 0.02, 'take_profit_pct': 0.06},
            },
            'min_win_rate': 0.50,
            'rules': [
                'Bearish: CVD makes higher highs while price fails to break above — limit sell walls absorbing',
                'Bullish: CVD makes lower lows while price forms higher low — limit buy walls absorbing',
                'In crypto, large players (whales) use iceberg orders that absorb retail market orders',
                'Absorption is strongest near key liquidity zones and round numbers',
                'Combine with open interest data for additional confirmation',
                'Absorption is the most powerful divergence pattern',
            ],
            'warnings': [
                'Spoofing can create false absorption signals — verify with actual fills',
                'Liquidation events can override absorption zones',
            ],
        },
    },
    {
        'name': 'CVD Real-Time Leading Indicator',
        'description': (
            'Use CVD as a leading indicator with real-time exchange data. Updates with every '
            'contract traded on perpetuals, spotting exhaustion before lagging oscillators.'
        ),
        'definition': {
            'strategy_type': 'CVD_DIVERGENCE',
            'cvd_type': 'real_time_leading',
            'timeframe': '5m',
            'pairs': ['BTC', 'ETH', 'SOL'],
            'indicators': [
                {'type': 'CVD', 'params': {'source': 'exchange_volume', 'exchange': 'binance', 'lookback': 10, 'real_time': True}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'CVD', 'condition': 'leading_divergence',
                     'value': 'bullish_exhaustion_early',
                     'description': 'CVD shows sell pressure weakening tick-by-tick before candle close'},
                ],
                'short': [
                    {'indicator': 'CVD', 'condition': 'leading_divergence',
                     'value': 'bearish_exhaustion_early',
                     'description': 'CVD shows buy pressure weakening tick-by-tick before candle close'},
                ],
            },
            'exit_rules': {
                'type': 'PERCENTAGE_BASED',
                'params': {'stop_loss_pct': 0.015, 'take_profit_pct': 0.04},
            },
            'min_win_rate': 0.48,
            'rules': [
                'Monitor CVD continuously — crypto exchanges provide tick-level data',
                'Identify divergences forming in real-time before candle close',
                'CVD updates with every perpetual contract trade — true leading indicator',
                'Use WebSocket feeds from Binance/Hyperliquid for real-time CVD calculation',
                'Best for scalping on 1m-5m timeframes',
            ],
        },
    },
    {
        'name': 'CVD Extremes Scanner',
        'description': (
            'Scan crypto charts for extreme price and CVD points, then compare to find '
            'divergence patterns at local highs and lows for reversal trades.'
        ),
        'definition': {
            'strategy_type': 'CVD_DIVERGENCE',
            'cvd_type': 'extremes',
            'timeframe': '1h',
            'pairs': ['BTC', 'ETH', 'SOL', 'AVAX', 'DOGE'],
            'indicators': [
                {'type': 'CVD', 'params': {'source': 'exchange_volume', 'exchange': 'binance', 'lookback': 50}},
                {'type': 'SWING_DETECTOR', 'params': {'lookback': 10, 'strength': 3}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'CVD', 'condition': 'extreme_divergence',
                     'value': 'bullish_extreme',
                     'description': 'Price at extreme low with CVD failing to confirm'},
                ],
                'short': [
                    {'indicator': 'CVD', 'condition': 'extreme_divergence',
                     'value': 'bearish_extreme',
                     'description': 'Price at extreme high with CVD failing to confirm'},
                ],
            },
            'exit_rules': {
                'type': 'PERCENTAGE_BASED',
                'params': {'stop_loss_pct': 0.03, 'take_profit_pct': 0.08},
            },
            'min_win_rate': 0.50,
            'rules': [
                'Scan for extreme points in price (highest highs, lowest lows) across crypto pairs',
                'Simultaneously identify CVD extremes during the same periods',
                'Compare to find divergences — price extreme without CVD confirmation = reversal signal',
                'Crypto extremes often coincide with funding rate flips and liquidation clusters',
                'Focus on BTC extremes first as they lead the market',
            ],
        },
    },
    {
        'name': 'CVD Pattern Training',
        'description': (
            'Training template for developing CVD pattern recognition skills on crypto charts. '
            'Practice spotting divergences across multiple timeframes and pairs.'
        ),
        'definition': {
            'strategy_type': 'CVD_TRAINING',
            'cvd_type': 'pattern_training',
            'timeframe': '15m',
            'pairs': ['BTC', 'ETH', 'SOL'],
            'indicators': [
                {'type': 'CVD', 'params': {'source': 'exchange_volume', 'display': 'separate_panel'}},
            ],
            'training_rules': [
                'Set up chart with price on top, CVD indicator on bottom',
                'Start on 15m timeframe — crypto has clean volume data',
                'Practice on BTC first (most liquid, clearest divergences)',
                'Scan for lack of participants divergence first (easiest to spot)',
                'Then look for absorption (CVD continues but price fails to break)',
                'Practice across 1m, 5m, 15m, 1h timeframes',
                'Crypto 24/7 markets provide more practice opportunities than traditional markets',
            ],
            'is_training': True,
        },
    },
    {
        'name': 'CVD Multi-Timeframe Analysis',
        'description': (
            'Analyze CVD divergences across 5m, 15m, 1h, and 4h timeframes on crypto '
            'for scalping and swing trade opportunities with multi-timeframe confirmation.'
        ),
        'definition': {
            'strategy_type': 'CVD_DIVERGENCE',
            'cvd_type': 'multi_timeframe',
            'timeframe': '15m',
            'timeframes': ['5m', '15m', '1h', '4h'],
            'pairs': ['BTC', 'ETH', 'SOL', 'AVAX'],
            'indicators': [
                {'type': 'CVD', 'params': {'source': 'exchange_volume', 'exchange': 'binance', 'lookback': 20}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'CVD', 'condition': 'mtf_divergence',
                     'value': 'bullish_mtf_confirmed',
                     'description': 'Bullish CVD divergence confirmed on at least 2 timeframes'},
                ],
                'short': [
                    {'indicator': 'CVD', 'condition': 'mtf_divergence',
                     'value': 'bearish_mtf_confirmed',
                     'description': 'Bearish CVD divergence confirmed on at least 2 timeframes'},
                ],
            },
            'exit_rules': {
                'type': 'PERCENTAGE_BASED',
                'params': {'stop_loss_pct': 0.02, 'take_profit_pct': 0.05},
            },
            'min_win_rate': 0.52,
            'rules': [
                'Analyze CVD across at least 3-4 timeframes simultaneously',
                'Higher timeframe divergence is the dominant signal direction',
                'Lower timeframe provides entry timing precision',
                'When divergence appears on 1h+, use 5m for entry execution',
                'Crypto multi-timeframe alignment is rare but highly profitable',
            ],
        },
    },
    {
        'name': 'CVD Overlay Visualization',
        'description': (
            'Display CVD as an overlay on crypto price charts for instant visual '
            'divergence recognition. Single-panel view eliminates panel switching.'
        ),
        'definition': {
            'strategy_type': 'CVD_VISUALIZATION',
            'cvd_type': 'overlay',
            'timeframe': '15m',
            'pairs': ['BTC', 'ETH', 'SOL'],
            'indicators': [
                {'type': 'CVD', 'params': {'source': 'exchange_volume', 'display': 'overlay', 'color': '#34d399'}},
            ],
            'visualization_rules': [
                'Display CVD as a green line overlay on the main price chart',
                'Use candlestick format for price display',
                'Apply across 1m, 15m, and 1h timeframes',
                'Single-view overlay makes divergence spotting faster',
                'Particularly effective on crypto due to clean exchange volume data',
            ],
            'is_visualization': True,
        },
    },
    {
        'name': 'CVD Spot vs Perpetual Comparison',
        'description': (
            'Compare CVD from spot exchanges versus perpetual futures to identify '
            'discrepancies between retail and leveraged positioning.'
        ),
        'definition': {
            'strategy_type': 'CVD_DIVERGENCE',
            'cvd_type': 'spot_vs_perpetual',
            'timeframe': '1h',
            'pairs': ['BTC', 'ETH', 'SOL'],
            'indicators': [
                {'type': 'CVD', 'params': {'source': 'exchange_volume', 'market': 'spot', 'exchange': 'binance'}},
                {'type': 'CVD', 'params': {'source': 'exchange_volume', 'market': 'perpetual', 'exchange': 'binance'}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'CVD', 'condition': 'cross_market_divergence',
                     'value': 'bullish_spot_vs_perp',
                     'description': 'Spot accumulation + perp distribution = smart money buying spot'},
                ],
                'short': [
                    {'indicator': 'CVD', 'condition': 'cross_market_divergence',
                     'value': 'bearish_spot_vs_perp',
                     'description': 'Spot distribution + perp accumulation = leveraged speculation without real demand'},
                ],
            },
            'exit_rules': {
                'type': 'PERCENTAGE_BASED',
                'params': {'stop_loss_pct': 0.025, 'take_profit_pct': 0.06},
            },
            'min_win_rate': 0.48,
            'rules': [
                'Compare CVD from Binance spot vs Binance/Hyperliquid perpetuals',
                'Spot CVD reflects organic buying from real holders',
                'Perpetual CVD includes leveraged speculators and funding arbitrage',
                'When spot leads and perps lag, real demand is driving the move',
                'When perps lead and spot lags, the move is speculation-driven (fragile)',
                'Divergence between spot and perp CVD often precedes major moves',
            ],
            'warnings': [
                'Wash trading on some exchanges can distort spot CVD',
                'Funding rate should be checked alongside for context',
            ],
        },
    },
]

POLYMARKET_STRATEGIES = [
    {
        'name': 'Volume Divergence (Lack of Participants)',
        'description': (
            'Trade when event probability moves to new extremes but trading volume fails to confirm. '
            'Indicates lack of conviction — the prediction market equivalent of CVD divergence.'
        ),
        'definition': {
            'strategy_type': 'VOLUME_DIVERGENCE',
            'cvd_type': 'lack_of_participants',
            'indicators': [
                {'type': 'VOLUME_DELTA', 'params': {'source': 'polymarket', 'lookback': 24, 'unit': 'hours'}},
            ],
            'entry_rules': {
                'buy_yes': [
                    {'indicator': 'VOLUME_DELTA', 'condition': 'divergence',
                     'value': 'bullish_lack_of_participants',
                     'description': 'Probability drops to new low but sell volume is declining — NO sellers exhausted'},
                ],
                'buy_no': [
                    {'indicator': 'VOLUME_DELTA', 'condition': 'divergence',
                     'value': 'bearish_lack_of_participants',
                     'description': 'Probability rises to new high but buy volume is declining — YES buyers exhausted'},
                ],
            },
            'exit_rules': {
                'type': 'THRESHOLD_BASED',
                'params': {'stop_loss_threshold': 0.15, 'take_profit_probability': 0.70},
            },
            'min_win_rate': 0.55,
            'rules': [
                'Compare probability movements with trading volume trends',
                'Probability reaching new highs with declining volume = weak conviction',
                'Probability reaching new lows with declining volume = sellers exhausted',
                'Works best on markets with >$50k volume and >48h until resolution',
                'Higher confidence near key probability levels (25%, 50%, 75%)',
                'Volume is measured as total YES+NO share turnover',
            ],
            'warnings': [
                'Low-liquidity markets may show false divergences',
                'News events can override volume-based signals instantly',
                'Markets close to resolution may have legitimate low volume',
            ],
        },
    },
    {
        'name': 'Probability Absorption',
        'description': (
            'Trade when heavy buying/selling volume does not move probability as expected. '
            'Large limit orders are absorbing aggressive market orders — '
            'the prediction market equivalent of CVD absorption.'
        ),
        'definition': {
            'strategy_type': 'VOLUME_DIVERGENCE',
            'cvd_type': 'absorption',
            'indicators': [
                {'type': 'VOLUME_DELTA', 'params': {'source': 'polymarket', 'lookback': 24, 'unit': 'hours'}},
                {'type': 'ORDER_BOOK_DEPTH', 'params': {'source': 'polymarket'}},
            ],
            'entry_rules': {
                'buy_yes': [
                    {'indicator': 'VOLUME_DELTA', 'condition': 'divergence',
                     'value': 'bullish_absorption',
                     'description': 'Heavy NO buying but probability holds — YES limit orders absorbing sell pressure'},
                ],
                'buy_no': [
                    {'indicator': 'VOLUME_DELTA', 'condition': 'divergence',
                     'value': 'bearish_absorption',
                     'description': 'Heavy YES buying but probability stalls — NO limit orders absorbing buy pressure'},
                ],
            },
            'exit_rules': {
                'type': 'THRESHOLD_BASED',
                'params': {'stop_loss_threshold': 0.15, 'take_profit_probability': 0.75},
            },
            'min_win_rate': 0.55,
            'rules': [
                'Bearish: Heavy YES buying volume but probability cannot rise — informed limit NO sellers absorbing',
                'Bullish: Heavy NO buying volume but probability holds — informed limit YES buyers absorbing',
                'Large players on Polymarket use limit orders that absorb retail market orders',
                'Absorption at key probability levels (50%, 75%) is the strongest signal',
                'Check order book depth to confirm large resting limit orders',
                'Absorption is the most powerful signal in prediction markets',
            ],
            'warnings': [
                'Order book spoofing exists on Polymarket — verify with actual fills',
                'Near-resolution markets may have legitimate price stability despite volume',
            ],
        },
    },
    {
        'name': 'Real-Time Volume Leading Indicator',
        'description': (
            'Monitor Polymarket trading volume as a leading indicator for probability changes. '
            'Volume surges and direction shifts predict probability movement before it happens.'
        ),
        'definition': {
            'strategy_type': 'VOLUME_DIVERGENCE',
            'cvd_type': 'real_time_leading',
            'indicators': [
                {'type': 'VOLUME_DELTA', 'params': {'source': 'polymarket', 'lookback': 6, 'unit': 'hours', 'real_time': True}},
            ],
            'entry_rules': {
                'buy_yes': [
                    {'indicator': 'VOLUME_DELTA', 'condition': 'leading_volume',
                     'value': 'bullish_volume_surge',
                     'description': 'YES volume surging before probability moves up — early entry'},
                ],
                'buy_no': [
                    {'indicator': 'VOLUME_DELTA', 'condition': 'leading_volume',
                     'value': 'bearish_volume_surge',
                     'description': 'NO volume surging before probability moves down — early entry'},
                ],
            },
            'exit_rules': {
                'type': 'THRESHOLD_BASED',
                'params': {'stop_loss_threshold': 0.10, 'take_profit_probability': 0.65},
            },
            'min_win_rate': 0.50,
            'rules': [
                'Monitor trading volume in real-time via Polymarket API',
                'Volume direction shifts often lead probability changes by 1-6 hours',
                'Large single trades (>$10k) from informed bettors are strongest signals',
                'Volume is a leading indicator — probability is lagging',
                'Best for markets with active trading and sufficient liquidity',
            ],
        },
    },
    {
        'name': 'Volume Extremes Scanner',
        'description': (
            'Scan Polymarket for probability extremes where volume diverges, indicating '
            'mispriced events with reversal potential.'
        ),
        'definition': {
            'strategy_type': 'VOLUME_DIVERGENCE',
            'cvd_type': 'extremes',
            'indicators': [
                {'type': 'VOLUME_DELTA', 'params': {'source': 'polymarket', 'lookback': 72, 'unit': 'hours'}},
                {'type': 'PROBABILITY_EXTREMES', 'params': {'threshold': 0.10}},
            ],
            'entry_rules': {
                'buy_yes': [
                    {'indicator': 'VOLUME_DELTA', 'condition': 'extreme_divergence',
                     'value': 'bullish_probability_extreme',
                     'description': 'Probability at extreme low (<15%) with declining sell volume — mispriced'},
                ],
                'buy_no': [
                    {'indicator': 'VOLUME_DELTA', 'condition': 'extreme_divergence',
                     'value': 'bearish_probability_extreme',
                     'description': 'Probability at extreme high (>85%) with declining buy volume — mispriced'},
                ],
            },
            'exit_rules': {
                'type': 'THRESHOLD_BASED',
                'params': {'stop_loss_threshold': 0.10, 'take_profit_probability': 0.50},
            },
            'min_win_rate': 0.55,
            'rules': [
                'Scan for markets where probability is at extremes (<15% or >85%)',
                'Check if volume supports the extreme probability or is diverging',
                'Extreme probability + declining volume = potential mispricing',
                'Focus on markets with >$100k total volume for reliability',
                'Best for contrarian bets when market overreacts to news',
            ],
        },
    },
    {
        'name': 'Volume Pattern Training',
        'description': (
            'Training template for developing volume-probability divergence recognition '
            'skills on Polymarket. Practice spotting when volume tells a different story than price.'
        ),
        'definition': {
            'strategy_type': 'VOLUME_TRAINING',
            'cvd_type': 'pattern_training',
            'indicators': [
                {'type': 'VOLUME_DELTA', 'params': {'source': 'polymarket', 'display': 'separate_panel'}},
            ],
            'training_rules': [
                'Set up Polymarket chart with probability on top, volume below',
                'Start with high-volume political markets (most data)',
                'Scan for lack of participants: probability moves but volume doesn\'t follow',
                'Then look for absorption: high volume but probability doesn\'t move',
                'Practice on resolved markets to verify predictions',
                'Build pattern library from historical Polymarket data',
            ],
            'is_training': True,
        },
    },
    {
        'name': 'Multi-Market Volume Analysis',
        'description': (
            'Analyze volume divergences across correlated Polymarket events simultaneously '
            'for cross-market confirmation of trading signals.'
        ),
        'definition': {
            'strategy_type': 'VOLUME_DIVERGENCE',
            'cvd_type': 'multi_timeframe',
            'indicators': [
                {'type': 'VOLUME_DELTA', 'params': {'source': 'polymarket', 'lookback': 48, 'unit': 'hours'}},
            ],
            'entry_rules': {
                'buy_yes': [
                    {'indicator': 'VOLUME_DELTA', 'condition': 'multi_market_divergence',
                     'value': 'bullish_cross_market',
                     'description': 'Volume divergence confirmed across correlated markets'},
                ],
                'buy_no': [
                    {'indicator': 'VOLUME_DELTA', 'condition': 'multi_market_divergence',
                     'value': 'bearish_cross_market',
                     'description': 'Volume divergence confirmed across correlated markets'},
                ],
            },
            'exit_rules': {
                'type': 'THRESHOLD_BASED',
                'params': {'stop_loss_threshold': 0.15, 'take_profit_probability': 0.70},
            },
            'min_win_rate': 0.52,
            'rules': [
                'Identify correlated markets (e.g., "Will X win?" and "Will party Y win?")',
                'Analyze volume patterns across all correlated markets simultaneously',
                'When divergence appears on one market, check related markets for confirmation',
                'Cross-market confirmed signals are stronger than single-market signals',
                'Watch for arbitrage opportunities when correlated markets disagree',
            ],
        },
    },
    {
        'name': 'Volume Flow Visualization',
        'description': (
            'Overlay YES/NO volume flow on probability charts to visualize the relationship '
            'between betting activity and probability movement.'
        ),
        'definition': {
            'strategy_type': 'VOLUME_VISUALIZATION',
            'cvd_type': 'overlay',
            'indicators': [
                {'type': 'VOLUME_DELTA', 'params': {'source': 'polymarket', 'display': 'overlay',
                                                     'yes_color': '#34d399', 'no_color': '#f87171'}},
            ],
            'visualization_rules': [
                'Display cumulative YES volume in green and NO volume in red as overlays',
                'Probability line shows the resulting price action',
                'Net volume delta (YES - NO) reveals directional pressure',
                'Makes absorption patterns visually obvious',
                'Apply across different time windows (6h, 24h, 72h)',
            ],
            'is_visualization': True,
        },
    },
    {
        'name': 'YES vs NO Volume Comparison',
        'description': (
            'Compare cumulative YES volume versus NO volume to identify when one side is '
            'dominating without moving probability — the Polymarket equivalent of spot vs perpetual.'
        ),
        'definition': {
            'strategy_type': 'VOLUME_DIVERGENCE',
            'cvd_type': 'yes_vs_no',
            'indicators': [
                {'type': 'VOLUME_DELTA', 'params': {'source': 'polymarket', 'side': 'YES'}},
                {'type': 'VOLUME_DELTA', 'params': {'source': 'polymarket', 'side': 'NO'}},
            ],
            'entry_rules': {
                'buy_yes': [
                    {'indicator': 'VOLUME_DELTA', 'condition': 'cross_side_divergence',
                     'value': 'bullish_yes_vs_no',
                     'description': 'YES volume dominating but probability flat — building pressure for upward move'},
                ],
                'buy_no': [
                    {'indicator': 'VOLUME_DELTA', 'condition': 'cross_side_divergence',
                     'value': 'bearish_yes_vs_no',
                     'description': 'NO volume dominating but probability flat — building pressure for downward move'},
                ],
            },
            'exit_rules': {
                'type': 'THRESHOLD_BASED',
                'params': {'stop_loss_threshold': 0.15, 'take_profit_probability': 0.65},
            },
            'min_win_rate': 0.48,
            'rules': [
                'Compare cumulative YES buying volume vs NO buying volume over time',
                'When one side dominates but probability doesn\'t move, pressure is building',
                'Eventually the absorbed pressure releases in a sharp probability move',
                'Most reliable on high-liquidity political and economic event markets',
                'Check individual large trades to identify informed vs retail flow',
            ],
            'warnings': [
                'Market maker activity can create balanced volume without directional intent',
                'Near-resolution markets may have structural reasons for volume imbalance',
            ],
        },
    },
]


def seed_strategies(apps, schema_editor):
    CustomStrategy = apps.get_model('nexus', 'CustomStrategy')

    for domain, strategies in [
        ('FOREX', FOREX_STRATEGIES),
        ('CRYPTO', CRYPTO_STRATEGIES),
        ('POLYMARKET', POLYMARKET_STRATEGIES),
    ]:
        for s in strategies:
            CustomStrategy.objects.get_or_create(
                name=s['name'],
                domain=domain,
                defaults={
                    'description': s['description'],
                    'definition': s['definition'],
                },
            )


def remove_strategies(apps, schema_editor):
    CustomStrategy = apps.get_model('nexus', 'CustomStrategy')
    strategy_names = (
        [s['name'] for s in FOREX_STRATEGIES]
        + [s['name'] for s in CRYPTO_STRATEGIES]
        + [s['name'] for s in POLYMARKET_STRATEGIES]
    )
    CustomStrategy.objects.filter(name__in=strategy_names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('nexus', '0006_customstrategy_domain'),
    ]

    operations = [
        migrations.RunPython(seed_strategies, remove_strategies),
    ]
