"""Seed pair-specific strategies: GBPUSD sweep fade, XAGUSD trend following,
AUDUSD session hybrid, and Energy trend/range/breakout."""

from django.db import migrations
import json


# ─── GBPUSD: Asian Range Liquidity Sweep Fade ──────────────────────────────

GBPUSD_STRATEGIES = [
    {
        'name': 'GBPUSD Asian Sweep Fade',
        'description': (
            'Trade the failure of Asian session liquidity sweeps during London Kill Zone. '
            'When price sweeps above/below the Asian range then reverses back inside, '
            'enter in the fade direction. Specifically designed for GBPUSD whipsaw behavior.'
        ),
        'definition': {
            'strategy_type': 'SESSION_SWEEP_FADE',
            'timeframe': 'M15',
            'pairs': ['GBPUSD'],
            'indicators': [
                {'type': 'SWEEP_FADE_SIGNAL', 'params': {'sweep_pips': 3, 'confirmation_candles': 3}},
                {'type': 'LONDON_KILLZONE_ACTIVE', 'params': {}},
                {'type': 'RSI', 'params': {'period': 14}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'SWEEP_FADE_SIGNAL', 'condition': 'sweep', 'value': 'bullish_sweep',
                     'description': 'Price swept below Asian low then closed back inside — fade long'},
                    {'indicator': 'LONDON_KILLZONE_ACTIVE', 'condition': 'eq', 'value': 'active',
                     'description': 'Only trade during London Kill Zone 07:00-10:00 UTC'},
                ],
                'short': [
                    {'indicator': 'SWEEP_FADE_SIGNAL', 'condition': 'sweep', 'value': 'bearish_sweep',
                     'description': 'Price swept above Asian high then closed back inside — fade short'},
                    {'indicator': 'LONDON_KILLZONE_ACTIVE', 'condition': 'eq', 'value': 'active',
                     'description': 'Only trade during London Kill Zone 07:00-10:00 UTC'},
                ],
            },
            'exit_rules': {
                'type': 'ASIAN_RANGE_TARGETS',
                'params': {
                    'atr_period': 14,
                    'sl_buffer_atr': 1.0,
                    'tp1': 'opposite_asian_range',
                    'tp2': 'previous_day_hl',
                    'partial_close_pct': 0.5,
                    'time_exit_hour': 15,
                },
            },
            'min_win_rate': 0.45,
            'rules': [
                'Calculate Asian session range (22:00-06:00 UTC) high and low',
                'Wait for London Kill Zone (07:00-10:00 UTC)',
                'Entry: Price sweeps beyond Asian range by 3+ pips, then closes back inside within 3 candles',
                'Confirmation: RSI divergence from sweep direction strengthens signal',
                'SL: Beyond the sweep wick + 1x ATR buffer',
                'TP1: Opposite side of Asian range (close 50%). TP2: Previous day high/low',
                'Time exit: Close remaining position by 15:00 UTC',
                'This exploits GBPUSD tendency to fake breakouts during London open',
            ],
        },
    },
]

# ─── XAGUSD: Donchian Trend Following ──────────────────────────────────────

XAGUSD_STRATEGIES = [
    {
        'name': 'Silver Donchian Trend Follow',
        'description': (
            'Turtle-style trend following for silver using Donchian Channel breakouts. '
            'Silver trends hard — this strategy rides the trend instead of fighting it. '
            'Filtered by Daily EMA(50) to only trade in the prevailing trend direction.'
        ),
        'definition': {
            'strategy_type': 'DONCHIAN_TREND',
            'timeframe': 'H1',
            'pairs': ['XAGUSD'],
            'indicators': [
                {'type': 'DONCHIAN_TREND_FILTER', 'params': {'entry_period': 20, 'ema_period': 50}},
                {'type': 'DONCHIAN_CHANNEL', 'params': {'entry_period': 20, 'exit_period': 10}},
                {'type': 'ATR', 'params': {'period': 14}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'DONCHIAN_TREND_FILTER', 'condition': 'eq', 'value': 'long_confirmed',
                     'description': 'Price breaks above 20-period Donchian high AND above EMA(50)'},
                ],
                'short': [
                    {'indicator': 'DONCHIAN_TREND_FILTER', 'condition': 'eq', 'value': 'short_confirmed',
                     'description': 'Price breaks below 20-period Donchian low AND below EMA(50)'},
                ],
            },
            'exit_rules': {
                'type': 'DONCHIAN_TRAIL',
                'params': {
                    'exit_period': 10,
                    'hard_stop_atr': 2.0,
                    'atr_period': 14,
                },
            },
            'min_win_rate': 0.35,
            'rules': [
                'Enter on 20-period Donchian Channel breakout (new 20-bar high/low)',
                'Only trade in direction of Daily EMA(50) trend filter',
                'Trailing exit: close long when price touches 10-period Donchian low',
                'Hard stop: 2x ATR(14) from entry',
                'No fixed TP — let winners run with trailing stop',
                'Expected: 35-45% WR but winners 2-5x larger than losers',
                'Silver trends strongly — never mean-revert this instrument',
            ],
        },
    },
    {
        'name': 'Gold-Silver Ratio Divergence',
        'description': (
            'Trade silver based on the gold-silver ratio extremes. '
            'When ratio exceeds 80, silver is historically undervalued relative to gold. '
            'When below 65, silver is overvalued. Uses XAUUSD as a leading indicator.'
        ),
        'definition': {
            'strategy_type': 'CROSS_INSTRUMENT_RATIO',
            'timeframe': 'H4',
            'pairs': ['XAGUSD'],
            'indicators': [
                {'type': 'GOLD_SILVER_RATIO', 'params': {'ratio_high': 80, 'ratio_low': 65}},
                {'type': 'MOMENTUM_TREND', 'params': {'fast': 12, 'slow': 26, 'signal': 9, 'ema_period': 50}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'GOLD_SILVER_RATIO', 'condition': 'eq', 'value': 'silver_undervalued',
                     'description': 'XAU/XAG ratio > 80 — silver historically cheap vs gold'},
                    {'indicator': 'MOMENTUM_TREND', 'condition': 'eq', 'value': 'bullish',
                     'description': 'Momentum confirms bullish trend forming'},
                ],
                'short': [
                    {'indicator': 'GOLD_SILVER_RATIO', 'condition': 'eq', 'value': 'silver_overvalued',
                     'description': 'XAU/XAG ratio < 65 — silver historically expensive vs gold'},
                    {'indicator': 'MOMENTUM_TREND', 'condition': 'eq', 'value': 'bearish',
                     'description': 'Momentum confirms bearish trend forming'},
                ],
            },
            'exit_rules': {
                'type': 'ATR_BASED',
                'params': {'atr_period': 14, 'sl_multiplier': 2.0, 'tp_multiplier': 3.0},
            },
            'min_win_rate': 0.40,
            'rules': [
                'Gold-silver ratio > 80 = silver undervalued, long silver',
                'Gold-silver ratio < 65 = silver overvalued, short silver',
                'Combine with MACD momentum confirmation to avoid catching falling knives',
                'Longer timeframe (H4) — this is a swing trade, not a scalp',
                'Target: ratio returning to 20-period mean',
            ],
        },
    },
]

# ─── AUDUSD: Session-Based Hybrid ──────────────────────────────────────────

AUDUSD_STRATEGIES = [
    {
        'name': 'AUDUSD Asian Mean Reversion',
        'description': (
            'Mean reversion strategy for AUDUSD during the low-volatility Asian session. '
            'Uses Bollinger Bands + RSI extremes to fade moves to the band edges. '
            'Only active 22:00-06:00 UTC when AUD ranges in Asian trading hours.'
        ),
        'definition': {
            'strategy_type': 'SESSION_MEAN_REVERSION',
            'timeframe': 'M15',
            'pairs': ['AUDUSD', 'NZDUSD'],
            'indicators': [
                {'type': 'ASIAN_MEAN_REVERSION', 'params': {
                    'bb_period': 20, 'bb_std': 2.0, 'rsi_period': 14,
                    'rsi_oversold': 30, 'rsi_overbought': 70,
                }},
                {'type': 'SESSION_STRATEGY_ROUTER', 'params': {}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'ASIAN_MEAN_REVERSION', 'condition': 'eq', 'value': 'bullish_reversion',
                     'description': 'Price at lower BB + RSI oversold during Asian session'},
                ],
                'short': [
                    {'indicator': 'ASIAN_MEAN_REVERSION', 'condition': 'eq', 'value': 'bearish_reversion',
                     'description': 'Price at upper BB + RSI overbought during Asian session'},
                ],
            },
            'exit_rules': {
                'type': 'MEAN_REVERSION_TARGETS',
                'params': {
                    'target': 'middle_bb',
                    'atr_period': 14,
                    'sl_multiplier': 1.5,
                    'time_exit_hour': 6,
                },
            },
            'min_win_rate': 0.55,
            'rules': [
                'Only active during Asian session (22:00-06:00 UTC)',
                'Long: price touches lower BB AND RSI(14) < 30',
                'Short: price touches upper BB AND RSI(14) > 70',
                'Target: middle Bollinger Band (20 SMA)',
                'Close ALL positions by 06:00 UTC before London volatility',
                'AUDUSD ranges during Asian hours — ideal for mean reversion',
            ],
        },
    },
    {
        'name': 'AUDUSD London Breakout',
        'description': (
            'Breakout strategy trading AUDUSD during London session using the Asian range. '
            'After Asian consolidation, London institutional flow creates directional moves. '
            'Filtered by Daily EMA trend to avoid false breakouts.'
        ),
        'definition': {
            'strategy_type': 'SESSION_BREAKOUT',
            'timeframe': 'M15',
            'pairs': ['AUDUSD'],
            'indicators': [
                {'type': 'LONDON_BREAKOUT', 'params': {
                    'breakout_buffer_pips': 5, 'pip_size': 0.0001, 'ema_period': 20,
                }},
                {'type': 'SESSION_STRATEGY_ROUTER', 'params': {}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'LONDON_BREAKOUT', 'condition': 'eq', 'value': 'bullish_breakout',
                     'description': 'Price breaks above Asian high + 5 pips, aligned with Daily EMA trend'},
                ],
                'short': [
                    {'indicator': 'LONDON_BREAKOUT', 'condition': 'eq', 'value': 'bearish_breakout',
                     'description': 'Price breaks below Asian low - 5 pips, aligned with Daily EMA trend'},
                ],
            },
            'exit_rules': {
                'type': 'RANGE_BASED',
                'params': {
                    'tp_range_multiplier': 1.5,
                    'sl': 'opposite_asian_range',
                    'time_exit_hour': 14,
                },
            },
            'min_win_rate': 0.45,
            'rules': [
                'Only active during London session (06:00-10:00 UTC)',
                'Calculate Asian range (22:00-06:00 UTC) high/low',
                'Long: price breaks above Asian high + 5 pip buffer, confirmed by close',
                'Short: price breaks below Asian low - 5 pip buffer, confirmed by close',
                'Direction must align with Daily EMA(20) trend',
                'TP: 1.5x the Asian range height. SL: opposite side of Asian range',
                'Close by 14:00 UTC',
            ],
        },
    },
]

# ─── Energy: Trend Following, Range Trading, Breakout ──────────────────────

ENERGY_STRATEGIES = [
    {
        'name': 'Energy Trend Follow',
        'description': (
            'Triple EMA alignment + MACD trend following for energy commodities. '
            'Crude oil and natural gas trend strongly — this rides established trends '
            'with momentum confirmation to avoid choppy conditions.'
        ),
        'definition': {
            'strategy_type': 'ENERGY_TREND',
            'timeframe': 'H1',
            'pairs': ['UKOUSDft', 'USOUSD', 'NG-C'],
            'indicators': [
                {'type': 'ENERGY_TREND_FOLLOW', 'params': {
                    'fast_ema': 8, 'slow_ema': 21, 'trend_ema': 50,
                    'macd_fast': 12, 'macd_slow': 26, 'macd_signal': 9,
                }},
                {'type': 'ATR', 'params': {'period': 14}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'ENERGY_TREND_FOLLOW', 'condition': 'eq', 'value': 'strong_long',
                     'description': 'EMA8 > EMA21 > EMA50 (stacked bullish) + MACD histogram positive and growing'},
                    {'indicator': 'ENERGY_TREND_FOLLOW', 'condition': 'eq', 'value': 'long',
                     'description': 'EMA8 > EMA21 > EMA50 + MACD positive'},
                ],
                'short': [
                    {'indicator': 'ENERGY_TREND_FOLLOW', 'condition': 'eq', 'value': 'strong_short',
                     'description': 'EMA8 < EMA21 < EMA50 (stacked bearish) + MACD histogram negative and shrinking'},
                    {'indicator': 'ENERGY_TREND_FOLLOW', 'condition': 'eq', 'value': 'short',
                     'description': 'EMA8 < EMA21 < EMA50 + MACD negative'},
                ],
            },
            'exit_rules': {
                'type': 'ATR_TRAIL',
                'params': {'atr_period': 14, 'sl_multiplier': 2.0, 'trail_atr': 1.5},
            },
            'min_win_rate': 0.40,
            'rules': [
                'Enter when 3 EMAs are stacked (aligned in trend direction)',
                'MACD histogram must confirm direction (positive for longs, negative for shorts)',
                'Strong signals: histogram also growing/shrinking (momentum accelerating)',
                'Trailing stop: 1.5x ATR from highest profit point',
                'Hard SL: 2x ATR from entry',
                'Energy markets trend strongly — do not counter-trade',
                'Avoid trading during EIA inventory report release (Wednesday 14:30 UTC)',
            ],
        },
    },
    {
        'name': 'Energy Range Trade',
        'description': (
            'Range trading for energy in sideways markets. Buys support, sells resistance '
            'when ATR compression indicates low volatility. Switches off when breakout detected.'
        ),
        'definition': {
            'strategy_type': 'ENERGY_RANGE',
            'timeframe': 'H1',
            'pairs': ['UKOUSDft', 'USOUSD'],
            'indicators': [
                {'type': 'ENERGY_RANGE_DETECT', 'params': {
                    'atr_period': 14, 'bb_period': 20, 'squeeze_threshold': 0.5,
                }},
                {'type': 'ENERGY_RANGE_TRADE', 'params': {'lookback': 20, 'buffer_pct': 0.002}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'ENERGY_RANGE_DETECT', 'condition': 'eq', 'value': 'ranging',
                     'description': 'Market in ranging mode (ATR compressed, BB narrowing)'},
                    {'indicator': 'ENERGY_RANGE_TRADE', 'condition': 'eq', 'value': 'buy_support',
                     'description': 'Price at support zone with bullish candle confirmation'},
                ],
                'short': [
                    {'indicator': 'ENERGY_RANGE_DETECT', 'condition': 'eq', 'value': 'ranging',
                     'description': 'Market in ranging mode (ATR compressed, BB narrowing)'},
                    {'indicator': 'ENERGY_RANGE_TRADE', 'condition': 'eq', 'value': 'sell_resistance',
                     'description': 'Price at resistance zone with bearish candle confirmation'},
                ],
            },
            'exit_rules': {
                'type': 'RANGE_TARGETS',
                'params': {'target': 'opposite_range', 'sl_multiplier': 1.5},
            },
            'min_win_rate': 0.50,
            'rules': [
                'Only active when ENERGY_RANGE_DETECT returns "ranging"',
                'Buy near support with bullish candle confirmation (close > open)',
                'Sell near resistance with bearish candle confirmation (close < open)',
                'Target: opposite end of range. SL: beyond range boundary',
                'Automatically disabled when market transitions to "volatile" state',
                'Best for consolidation periods between major moves',
            ],
        },
    },
    {
        'name': 'Energy Keltner Breakout',
        'description': (
            'Keltner Channel breakout for energy commodities with volume confirmation. '
            'Catches the transition from ranging to trending conditions. '
            'Volume filter reduces false breakouts.'
        ),
        'definition': {
            'strategy_type': 'ENERGY_BREAKOUT',
            'timeframe': 'H1',
            'pairs': ['UKOUSDft', 'USOUSD', 'NG-C'],
            'indicators': [
                {'type': 'ENERGY_BREAKOUT', 'params': {
                    'kc_period': 20, 'kc_atr_mult': 2.0, 'volume_mult': 1.5,
                }},
                {'type': 'MOMENTUM_TREND', 'params': {'ema_period': 50}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'ENERGY_BREAKOUT', 'condition': 'eq', 'value': 'bullish_breakout',
                     'description': 'Close above upper Keltner Channel + volume confirmation'},
                ],
                'short': [
                    {'indicator': 'ENERGY_BREAKOUT', 'condition': 'eq', 'value': 'bearish_breakout',
                     'description': 'Close below lower Keltner Channel + volume confirmation'},
                ],
            },
            'exit_rules': {
                'type': 'KC_TRAIL',
                'params': {
                    'trail': 'kc_middle',
                    'atr_period': 14,
                    'hard_stop_atr': 2.0,
                },
            },
            'min_win_rate': 0.42,
            'rules': [
                'Enter when price closes beyond Keltner Channel (EMA20 +/- 2x ATR)',
                'Volume must be > 1.5x average for confirmed breakout',
                'Weak signals (no volume) are tracked but not traded',
                'Trail stop using KC middle line (20 EMA)',
                'Hard SL: 2x ATR from entry',
                'Best catches the transition from Energy Range Trade to trending',
            ],
        },
    },
    {
        'name': 'Brent-WTI Spread Trade',
        'description': (
            'Relative value trade between Brent (UKOUSDft) and WTI (USOUSD) based on '
            'the spread between the two benchmarks. When spread is extreme, mean-revert.'
        ),
        'definition': {
            'strategy_type': 'SPREAD_TRADE',
            'timeframe': 'H4',
            'pairs': ['UKOUSDft'],
            'indicators': [
                {'type': 'BRENT_WTI_SPREAD', 'params': {'spread_high': 5.0, 'spread_low': 1.0}},
                {'type': 'RSI', 'params': {'period': 14}},
            ],
            'entry_rules': {
                'long': [
                    {'indicator': 'BRENT_WTI_SPREAD', 'condition': 'eq', 'value': 'spread_narrow',
                     'description': 'Brent premium < $1 — historically low, expect expansion'},
                ],
                'short': [
                    {'indicator': 'BRENT_WTI_SPREAD', 'condition': 'eq', 'value': 'spread_wide',
                     'description': 'Brent premium > $5 — historically high, expect contraction'},
                ],
            },
            'exit_rules': {
                'type': 'ATR_BASED',
                'params': {'atr_period': 14, 'sl_multiplier': 2.0, 'tp_multiplier': 2.5},
            },
            'min_win_rate': 0.45,
            'rules': [
                'Brent-WTI spread > $5 = Brent overpriced, short Brent (or long WTI)',
                'Brent-WTI spread < $1 = Brent underpriced, long Brent (or short WTI)',
                'This is a mean-reversion strategy on the SPREAD, not on price',
                'Longer timeframe (H4) — supply/demand fundamentals drive convergence',
                'Watch for geopolitical events that structurally shift the spread',
            ],
        },
    },
]


def seed_strategies(apps, schema_editor):
    StrategyConfig = apps.get_model('nexus', 'StrategyConfig')
    CustomStrategy = apps.get_model('nexus', 'CustomStrategy')

    for strategies in [GBPUSD_STRATEGIES, XAGUSD_STRATEGIES, AUDUSD_STRATEGIES, ENERGY_STRATEGIES]:
        for s in strategies:
            # Create StrategyConfig
            config, _ = StrategyConfig.objects.get_or_create(
                name=f"{s['name']} (FOREX)",
                defaults={
                    'description': s['description'],
                    'is_active': True,
                    'max_positions': 3,
                },
            )
            # Create CustomStrategy linked to it
            CustomStrategy.objects.get_or_create(
                name=s['name'],
                domain='FOREX',
                defaults={
                    'description': s['description'],
                    'definition': s['definition'],
                    'strategy_config': config,
                },
            )


def remove_strategies(apps, schema_editor):
    StrategyConfig = apps.get_model('nexus', 'StrategyConfig')
    CustomStrategy = apps.get_model('nexus', 'CustomStrategy')
    all_names = (
        [s['name'] for s in GBPUSD_STRATEGIES]
        + [s['name'] for s in XAGUSD_STRATEGIES]
        + [s['name'] for s in AUDUSD_STRATEGIES]
        + [s['name'] for s in ENERGY_STRATEGIES]
    )
    CustomStrategy.objects.filter(name__in=all_names).delete()
    StrategyConfig.objects.filter(
        name__in=[f"{n} (FOREX)" for n in all_names]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('nexus', '0016_add_trade_indexes'),
    ]

    operations = [
        migrations.RunPython(seed_strategies, remove_strategies),
    ]
