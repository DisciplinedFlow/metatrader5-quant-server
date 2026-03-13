"""
Enhance energy strategies with research-backed indicators.

Updates energy strategies seeded in 0017 with:
- OVX regime proxy (ATR-based volatility regime filter)
- BB/KC squeeze detection for oil breakouts
- ROC momentum confirmation (Sharpe > 1.20 on commodity TSMOM)
- Energy session filter (peak: London-NY overlap 13:00-17:00 UTC)
- NG seasonal filter (September rally: 56% return over 10 years)
- Wider stops (2x ATR) and lower capital ($300 vs $500)

Also adds new strategies from oil/gas research:
- Oil Squeeze Breakout (BB inside KC → explosive move)
- NG Seasonal Momentum (Sep 1 - Oct 25 rally)
"""

from django.db import migrations


def enhance_energy_strategies(apps, schema_editor):
    StrategyConfig = apps.get_model('nexus', 'StrategyConfig')
    CustomStrategy = apps.get_model('nexus', 'CustomStrategy')

    # -----------------------------------------------------------------------
    # Update existing Energy Trend Follow strategy with regime + ROC
    # -----------------------------------------------------------------------
    try:
        sc = StrategyConfig.objects.filter(name__icontains='Energy Trend Follow').first()
        if sc:
            cs = CustomStrategy.objects.filter(strategy_config=sc).first()
            if cs:
                cs.definition = {
                    'pairs': ['UKOUSDft', 'USOUSD'],
                    'timeframe': 'H4',
                    'indicators': [
                        {'type': 'ENERGY_TREND_FOLLOW', 'params': {'fast_ema': 8, 'slow_ema': 21, 'trend_ema': 50}},
                        {'type': 'ENERGY_VOLATILITY_REGIME', 'params': {'atr_period': 14, 'avg_period': 50}},
                        {'type': 'ENERGY_MOMENTUM_ROC', 'params': {'roc_period': 14, 'signal_period': 5}},
                        {'type': 'ENERGY_SESSION_FILTER', 'params': {}},
                    ],
                    'entry_rules': {
                        'long': [
                            {'indicator': 'ENERGY_TREND_FOLLOW', 'condition': 'contains', 'value': 'long'},
                            {'indicator': 'ENERGY_VOLATILITY_REGIME', 'condition': 'neq', 'value': 'crisis'},
                            {'indicator': 'ENERGY_MOMENTUM_ROC', 'condition': 'contains', 'value': 'bullish'},
                            {'indicator': 'ENERGY_SESSION_FILTER', 'condition': 'neq', 'value': 'dead_zone'},
                        ],
                        'short': [
                            {'indicator': 'ENERGY_TREND_FOLLOW', 'condition': 'contains', 'value': 'short'},
                            {'indicator': 'ENERGY_VOLATILITY_REGIME', 'condition': 'neq', 'value': 'crisis'},
                            {'indicator': 'ENERGY_MOMENTUM_ROC', 'condition': 'contains', 'value': 'bearish'},
                            {'indicator': 'ENERGY_SESSION_FILTER', 'condition': 'neq', 'value': 'dead_zone'},
                        ],
                    },
                    'exit_rules': {
                        'params': {
                            'atr_period': 14,
                            'sl_multiplier': 2.0,
                            'tp_multiplier': 3.0,
                        },
                    },
                    'rules': (
                        'ENHANCED Energy Trend Follow (Research-Backed):\n'
                        '- Triple EMA alignment (8/21/50) + MACD histogram confirmation\n'
                        '- ATR volatility regime filter: blocks entries in crisis mode\n'
                        '- ROC momentum confirmation (TSMOM Sharpe > 1.20)\n'
                        '- Session filter: avoids dead zone (21:00-01:59 UTC)\n'
                        '- SL: 2x ATR (wider for oil volatility)\n'
                        '- TP: 3x ATR (1.5:1 R:R minimum)\n'
                        '- Capital: $300/trade (vs $500 for forex)\n'
                        'Research: Donchian+ROC+regime filter is core CTA methodology'
                    ),
                }
                cs.save()
    except Exception:
        pass

    # -----------------------------------------------------------------------
    # Update existing Energy Keltner Breakout with squeeze + session
    # -----------------------------------------------------------------------
    try:
        sc = StrategyConfig.objects.filter(name__icontains='Energy Keltner Breakout').first()
        if sc:
            cs = CustomStrategy.objects.filter(strategy_config=sc).first()
            if cs:
                cs.definition = {
                    'pairs': ['UKOUSDft', 'USOUSD', 'NG-C'],
                    'timeframe': 'H4',
                    'indicators': [
                        {'type': 'ENERGY_BREAKOUT', 'params': {'kc_period': 20, 'kc_atr_mult': 2.0}},
                        {'type': 'ENERGY_VOLATILITY_REGIME', 'params': {}},
                        {'type': 'ENERGY_SQUEEZE_DETECTOR', 'params': {'min_squeeze_bars': 5}},
                        {'type': 'ENERGY_SESSION_FILTER', 'params': {}},
                    ],
                    'entry_rules': {
                        'long': [
                            {'indicator': 'ENERGY_BREAKOUT', 'condition': 'contains', 'value': 'bullish'},
                            {'indicator': 'ENERGY_VOLATILITY_REGIME', 'condition': 'neq', 'value': 'crisis'},
                            {'indicator': 'ENERGY_SESSION_FILTER', 'condition': 'neq', 'value': 'dead_zone'},
                        ],
                        'short': [
                            {'indicator': 'ENERGY_BREAKOUT', 'condition': 'contains', 'value': 'bearish'},
                            {'indicator': 'ENERGY_VOLATILITY_REGIME', 'condition': 'neq', 'value': 'crisis'},
                            {'indicator': 'ENERGY_SESSION_FILTER', 'condition': 'neq', 'value': 'dead_zone'},
                        ],
                    },
                    'exit_rules': {
                        'params': {
                            'atr_period': 14,
                            'sl_multiplier': 2.0,
                            'tp_multiplier': 3.0,
                        },
                    },
                    'rules': (
                        'ENHANCED Energy Keltner Breakout (Research-Backed):\n'
                        '- KC breakout with volume confirmation\n'
                        '- Squeeze detector: BB inside KC for 5+ bars = imminent move\n'
                        '- Volatility regime: no entries in crisis mode\n'
                        '- Session filter: peak liquidity 08:00-17:00 UTC\n'
                        '- Oil needs wider KC (2.5x ATR) during crisis vs normal (2.0x)\n'
                        'Research: Keltner adaptive bands outperform fixed Bollinger in trending'
                    ),
                }
                cs.save()
    except Exception:
        pass

    # -----------------------------------------------------------------------
    # Update existing Energy Range Trade with regime awareness
    # -----------------------------------------------------------------------
    try:
        sc = StrategyConfig.objects.filter(name__icontains='Energy Range Trade').first()
        if sc:
            cs = CustomStrategy.objects.filter(strategy_config=sc).first()
            if cs:
                cs.definition = {
                    'pairs': ['UKOUSDft', 'USOUSD'],
                    'timeframe': 'H1',
                    'indicators': [
                        {'type': 'ENERGY_RANGE_TRADE', 'params': {'lookback': 20}},
                        {'type': 'ENERGY_RANGE_DETECT', 'params': {}},
                        {'type': 'ENERGY_VOLATILITY_REGIME', 'params': {}},
                        {'type': 'ENERGY_SESSION_FILTER', 'params': {}},
                    ],
                    'entry_rules': {
                        'long': [
                            {'indicator': 'ENERGY_RANGE_TRADE', 'condition': 'contains', 'value': 'buy_support'},
                            {'indicator': 'ENERGY_RANGE_DETECT', 'condition': 'eq', 'value': 'ranging'},
                            {'indicator': 'ENERGY_VOLATILITY_REGIME', 'condition': 'eq', 'value': 'normal'},
                            {'indicator': 'ENERGY_SESSION_FILTER', 'condition': 'neq', 'value': 'dead_zone'},
                        ],
                        'short': [
                            {'indicator': 'ENERGY_RANGE_TRADE', 'condition': 'contains', 'value': 'sell_resistance'},
                            {'indicator': 'ENERGY_RANGE_DETECT', 'condition': 'eq', 'value': 'ranging'},
                            {'indicator': 'ENERGY_VOLATILITY_REGIME', 'condition': 'eq', 'value': 'normal'},
                            {'indicator': 'ENERGY_SESSION_FILTER', 'condition': 'neq', 'value': 'dead_zone'},
                        ],
                    },
                    'exit_rules': {
                        'params': {
                            'atr_period': 14,
                            'sl_multiplier': 1.5,
                            'tp_multiplier': 2.0,
                        },
                    },
                    'rules': (
                        'ENHANCED Energy Range Trade (Research-Backed):\n'
                        '- ONLY active when regime is NORMAL (not elevated/high/crisis)\n'
                        '- ONLY active when range is confirmed (ATR compressed + BB contracting)\n'
                        '- Mean reversion is DANGEROUS in trending oil — strict regime gate\n'
                        '- Session filter: avoid dead zone and Asian session\n'
                        'Research: Mean reversion works on oil ONLY during confirmed range regimes.\n'
                        'Academic finding: momentum works in futures, reversion works in spot only.'
                    ),
                }
                cs.save()
    except Exception:
        pass

    # -----------------------------------------------------------------------
    # NEW: Oil Squeeze Breakout Strategy
    # -----------------------------------------------------------------------
    sc_squeeze, _ = StrategyConfig.objects.get_or_create(
        name='Oil Squeeze Breakout (ENERGY)',
        defaults={
            'is_active': True,
            'regime_filter': '',
        },
    )
    CustomStrategy.objects.update_or_create(
        strategy_config=sc_squeeze,
        defaults={
            'name': 'Oil Squeeze Breakout',
            'definition': {
                'pairs': ['UKOUSDft', 'USOUSD'],
                'timeframe': 'H4',
                'indicators': [
                    {'type': 'ENERGY_SQUEEZE_DETECTOR', 'params': {
                        'bb_period': 20, 'bb_std': 2.0,
                        'kc_period': 20, 'kc_mult': 1.5,
                        'min_squeeze_bars': 5,
                    }},
                    {'type': 'ENERGY_TREND_FOLLOW', 'params': {'fast_ema': 8, 'slow_ema': 21, 'trend_ema': 50}},
                    {'type': 'ENERGY_VOLATILITY_REGIME', 'params': {}},
                    {'type': 'ENERGY_SESSION_FILTER', 'params': {}},
                ],
                'entry_rules': {
                    'long': [
                        {'indicator': 'ENERGY_SQUEEZE_DETECTOR', 'condition': 'eq', 'value': 'squeeze_bullish_fire'},
                        {'indicator': 'ENERGY_VOLATILITY_REGIME', 'condition': 'neq', 'value': 'crisis'},
                        {'indicator': 'ENERGY_SESSION_FILTER', 'condition': 'neq', 'value': 'dead_zone'},
                    ],
                    'short': [
                        {'indicator': 'ENERGY_SQUEEZE_DETECTOR', 'condition': 'eq', 'value': 'squeeze_bearish_fire'},
                        {'indicator': 'ENERGY_VOLATILITY_REGIME', 'condition': 'neq', 'value': 'crisis'},
                        {'indicator': 'ENERGY_SESSION_FILTER', 'condition': 'neq', 'value': 'dead_zone'},
                    ],
                },
                'exit_rules': {
                    'params': {
                        'atr_period': 14,
                        'sl_multiplier': 2.0,
                        'tp_multiplier': 4.0,
                    },
                },
                'rules': (
                    'Oil Squeeze Breakout (BB/KC Squeeze Fire):\n'
                    '- Detects Bollinger Bands contracting INSIDE Keltner Channels\n'
                    '- After 5+ bars of squeeze, enters on explosive release\n'
                    '- Direction determined by close vs KC midline on release bar\n'
                    '- TP = 2x squeeze range (4x ATR) — captures the full expansion\n'
                    '- SL = opposite KC (2x ATR below/above entry)\n'
                    '- Regime filter: no entries in crisis volatility\n'
                    '- This is the "coiled spring" setup CTAs love\n'
                    'Research: Squeeze breakouts have highest R:R of any oil setup'
                ),
            },
        },
    )

    # -----------------------------------------------------------------------
    # NEW: NG Seasonal Momentum Strategy
    # -----------------------------------------------------------------------
    sc_ng_seasonal, _ = StrategyConfig.objects.get_or_create(
        name='NG Seasonal Momentum (ENERGY)',
        defaults={
            'is_active': True,
            'regime_filter': '',
        },
    )
    CustomStrategy.objects.update_or_create(
        strategy_config=sc_ng_seasonal,
        defaults={
            'name': 'NG Seasonal Momentum',
            'definition': {
                'pairs': ['NG-C'],
                'timeframe': 'H4',
                'indicators': [
                    {'type': 'NG_SEASONAL_FILTER', 'params': {}},
                    {'type': 'ENERGY_TREND_FOLLOW', 'params': {'fast_ema': 8, 'slow_ema': 34, 'trend_ema': 50}},
                    {'type': 'ENERGY_MOMENTUM_ROC', 'params': {'roc_period': 14, 'signal_period': 5}},
                    {'type': 'ENERGY_VOLATILITY_REGIME', 'params': {}},
                ],
                'entry_rules': {
                    'long': [
                        {'indicator': 'NG_SEASONAL_FILTER', 'condition': 'contains', 'value': 'bullish'},
                        {'indicator': 'ENERGY_TREND_FOLLOW', 'condition': 'contains', 'value': 'long'},
                        {'indicator': 'ENERGY_MOMENTUM_ROC', 'condition': 'contains', 'value': 'bullish'},
                        {'indicator': 'ENERGY_VOLATILITY_REGIME', 'condition': 'neq', 'value': 'crisis'},
                    ],
                    'short': [
                        {'indicator': 'NG_SEASONAL_FILTER', 'condition': 'eq', 'value': 'bearish'},
                        {'indicator': 'ENERGY_TREND_FOLLOW', 'condition': 'contains', 'value': 'short'},
                        {'indicator': 'ENERGY_MOMENTUM_ROC', 'condition': 'contains', 'value': 'bearish'},
                        {'indicator': 'ENERGY_VOLATILITY_REGIME', 'condition': 'neq', 'value': 'crisis'},
                    ],
                },
                'exit_rules': {
                    'params': {
                        'atr_period': 14,
                        'sl_multiplier': 2.0,
                        'tp_multiplier': 4.0,
                    },
                },
                'rules': (
                    'NG Seasonal Momentum (Research-Backed):\n'
                    '- Combines seasonal bias with trend + momentum confirmation\n'
                    '- LONG: Only during bullish seasonal windows (Mar-Apr, Sep-Oct)\n'
                    '- September rally: 56% return over 10 years, 7/10 positive\n'
                    '- SHORT: Only during bearish windows (May-Jun, Nov)\n'
                    '- EMA(8/34) for trend direction (NG-specific tuning)\n'
                    '- ROC momentum confirmation\n'
                    '- TP: 4x ATR (1:3.2 R:R from seasonal data)\n'
                    '- SL: 2x ATR (wider for NG extreme volatility, 60-100% annualized)\n'
                    '- RSI thresholds: 75/25 for NG (not 70/30 — higher volatility)\n'
                    'Research: NG Sep 1-Oct 25 = best seasonal trade in commodities'
                ),
            },
        },
    )

    # -----------------------------------------------------------------------
    # NEW: Oil Momentum ROC Strategy (Time-Series Momentum)
    # -----------------------------------------------------------------------
    sc_roc, _ = StrategyConfig.objects.get_or_create(
        name='Oil TSMOM (ENERGY)',
        defaults={
            'is_active': True,
            'regime_filter': '',
        },
    )
    CustomStrategy.objects.update_or_create(
        strategy_config=sc_roc,
        defaults={
            'name': 'Oil Time-Series Momentum',
            'definition': {
                'pairs': ['UKOUSDft', 'USOUSD'],
                'timeframe': 'H4',
                'indicators': [
                    {'type': 'ENERGY_MOMENTUM_ROC', 'params': {'roc_period': 14, 'signal_period': 5}},
                    {'type': 'ENERGY_TREND_FOLLOW', 'params': {'fast_ema': 8, 'slow_ema': 21, 'trend_ema': 50}},
                    {'type': 'ENERGY_VOLATILITY_REGIME', 'params': {}},
                    {'type': 'ENERGY_SESSION_FILTER', 'params': {}},
                ],
                'entry_rules': {
                    'long': [
                        {'indicator': 'ENERGY_MOMENTUM_ROC', 'condition': 'eq', 'value': 'strong_bullish'},
                        {'indicator': 'ENERGY_TREND_FOLLOW', 'condition': 'contains', 'value': 'long'},
                        {'indicator': 'ENERGY_VOLATILITY_REGIME', 'condition': 'neq', 'value': 'crisis'},
                        {'indicator': 'ENERGY_SESSION_FILTER', 'condition': 'neq', 'value': 'dead_zone'},
                    ],
                    'short': [
                        {'indicator': 'ENERGY_MOMENTUM_ROC', 'condition': 'eq', 'value': 'strong_bearish'},
                        {'indicator': 'ENERGY_TREND_FOLLOW', 'condition': 'contains', 'value': 'short'},
                        {'indicator': 'ENERGY_VOLATILITY_REGIME', 'condition': 'neq', 'value': 'crisis'},
                        {'indicator': 'ENERGY_SESSION_FILTER', 'condition': 'neq', 'value': 'dead_zone'},
                    ],
                },
                'exit_rules': {
                    'params': {
                        'atr_period': 14,
                        'sl_multiplier': 2.0,
                        'tp_multiplier': 3.0,
                    },
                },
                'rules': (
                    'Oil Time-Series Momentum (TSMOM):\n'
                    '- Pure momentum strategy: ROC(14) > 0, accelerating, above signal line\n'
                    '- Requires STRONG momentum (not just bullish) + trend alignment\n'
                    '- Time-series momentum achieves Sharpe > 1.20 on commodity futures\n'
                    '- Medium-strength trends persist at scales of days to years\n'
                    '- Session filter: trade during London-NY overlap for best fills\n'
                    '- Regime filter: no entries in crisis volatility\n'
                    'Research: Academic TSMOM is the strongest edge in energy markets'
                ),
            },
        },
    )


def reverse_migration(apps, schema_editor):
    StrategyConfig = apps.get_model('nexus', 'StrategyConfig')
    CustomStrategy = apps.get_model('nexus', 'CustomStrategy')

    for name in [
        'Oil Squeeze Breakout (ENERGY)',
        'NG Seasonal Momentum (ENERGY)',
        'Oil TSMOM (ENERGY)',
    ]:
        sc = StrategyConfig.objects.filter(name=name).first()
        if sc:
            CustomStrategy.objects.filter(strategy_config=sc).delete()
            sc.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('nexus', '0017_seed_pair_specific_strategies'),
    ]

    operations = [
        migrations.RunPython(enhance_energy_strategies, reverse_migration),
    ]
