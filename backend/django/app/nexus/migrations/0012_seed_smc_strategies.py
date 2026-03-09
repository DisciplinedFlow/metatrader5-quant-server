"""Seed Smart Money Concepts (ICT) strategies for Forex."""

from django.db import migrations


SMC_STRATEGIES = [
    {
        'name': 'ICT Market Structure + FVG',
        'domain': 'FOREX',
        'description': (
            'Trend reversal strategy using ICT Change of Character (CHoCH) '
            'confirmed by Fair Value Gap fill entries. Waits for a structural '
            'break against the prevailing trend, then enters when price returns '
            'to fill the imbalance gap. High win rate due to structural confluence.'
        ),
        'definition': {
            'strategy_type': 'REVERSAL',
            'timeframe': 'M15',
            'pairs': ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD'],
            'indicators': [
                {
                    'type': 'MARKET_STRUCTURE',
                    'params': {'swing_lookback': 5},
                },
                {
                    'type': 'FAIR_VALUE_GAP',
                    'params': {'min_gap_pct': 0.0005, 'max_fvg_age': 20},
                },
            ],
            'entry_rules': {
                'long': [
                    {
                        'indicator': 'MARKET_STRUCTURE',
                        'condition': 'structure_break',
                        'value': 'bullish_choch',
                        'description': 'Bullish CHoCH — downtrend broken, trend reversing up',
                    },
                    {
                        'indicator': 'FAIR_VALUE_GAP',
                        'condition': 'fvg_fill',
                        'value': 'bullish_fvg',
                        'description': 'Price fills a bullish FVG — discount entry',
                    },
                ],
                'short': [
                    {
                        'indicator': 'MARKET_STRUCTURE',
                        'condition': 'structure_break',
                        'value': 'bearish_choch',
                        'description': 'Bearish CHoCH — uptrend broken, trend reversing down',
                    },
                    {
                        'indicator': 'FAIR_VALUE_GAP',
                        'condition': 'fvg_fill',
                        'value': 'bearish_fvg',
                        'description': 'Price fills a bearish FVG — premium entry',
                    },
                ],
            },
            'exit_rules': {
                'type': 'ATR_BASED',
                'params': {
                    'atr_period': 14,
                    'sl_multiplier': 1.5,
                    'tp_multiplier': 3.0,
                },
            },
            'min_win_rate': 0.35,
            'rules': [
                'Wait for CHoCH (Change of Character) — structural break against prevailing trend',
                'Only enter on FVG fill in the new trend direction',
                'Both signals must fire on the same bar for maximum confluence',
                'SL below the last swing low (bullish) or above last swing high (bearish)',
                'TP at 3:1 R:R — reversal trades need wider targets',
            ],
        },
    },
    {
        'name': 'ICT Liquidity Sweep + Order Block',
        'domain': 'FOREX',
        'description': (
            'Stop-hunt reversal strategy. Detects when price sweeps beyond a swing '
            'point (triggering retail stop losses), then reverses into an institutional '
            'order block. The sweep provides the liquidity for institutions to enter — '
            'the OB retest is the confirmation. Classic TJR/ICT setup.'
        ),
        'definition': {
            'strategy_type': 'REVERSAL',
            'timeframe': 'M15',
            'pairs': ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD'],
            'indicators': [
                {
                    'type': 'LIQUIDITY_SWEEP',
                    'params': {'swing_lookback': 5, 'sweep_buffer_pct': 0.0002},
                },
                {
                    'type': 'ORDER_BLOCK',
                    'params': {
                        'impulse_mult': 2.0,
                        'ob_lookback': 3,
                        'max_ob_age': 30,
                    },
                },
            ],
            'entry_rules': {
                'long': [
                    {
                        'indicator': 'LIQUIDITY_SWEEP',
                        'condition': 'sweep',
                        'value': 'bullish_sweep',
                        'description': 'Bullish sweep — price hunted sell-stops then reversed',
                    },
                    {
                        'indicator': 'ORDER_BLOCK',
                        'condition': 'ob_retest',
                        'value': 'bullish_ob',
                        'description': 'Bullish OB retest — price rejected off institutional demand zone',
                    },
                ],
                'short': [
                    {
                        'indicator': 'LIQUIDITY_SWEEP',
                        'condition': 'sweep',
                        'value': 'bearish_sweep',
                        'description': 'Bearish sweep — price hunted buy-stops then reversed',
                    },
                    {
                        'indicator': 'ORDER_BLOCK',
                        'condition': 'ob_retest',
                        'value': 'bearish_ob',
                        'description': 'Bearish OB retest — price rejected off institutional supply zone',
                    },
                ],
            },
            'exit_rules': {
                'type': 'ATR_BASED',
                'params': {
                    'atr_period': 14,
                    'sl_multiplier': 1.2,
                    'tp_multiplier': 2.5,
                },
            },
            'min_win_rate': 0.35,
            'rules': [
                'Wait for liquidity sweep — price must take out a swing high/low',
                'Candle must close back inside (wick beyond swing = stop hunt)',
                'Confirm with order block retest on the same bar',
                'Tight SL (1.2x ATR) since the setup has clear invalidation',
                'TP at 2.5x ATR — institutional moves tend to be decisive',
            ],
        },
    },
    {
        'name': 'ICT BOS Continuation + FVG',
        'domain': 'FOREX',
        'description': (
            'Trend continuation strategy using Break of Structure (BOS) with '
            'FVG pullback entries. After a BOS confirms the trend, wait for '
            'price to retrace into a Fair Value Gap for an optimal entry. '
            'Lower risk setup compared to CHoCH reversal trades.'
        ),
        'definition': {
            'strategy_type': 'MOMENTUM',
            'timeframe': 'M15',
            'pairs': ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD'],
            'indicators': [
                {
                    'type': 'MARKET_STRUCTURE',
                    'params': {'swing_lookback': 5},
                },
                {
                    'type': 'FAIR_VALUE_GAP',
                    'params': {'min_gap_pct': 0.0003, 'max_fvg_age': 15},
                },
            ],
            'entry_rules': {
                'long': [
                    {
                        'indicator': 'MARKET_STRUCTURE',
                        'condition': 'structure_break',
                        'value': 'bullish_bos',
                        'description': 'Bullish BOS — uptrend confirmed with new higher high',
                    },
                    {
                        'indicator': 'FAIR_VALUE_GAP',
                        'condition': 'fvg_fill',
                        'value': 'bullish_fvg',
                        'description': 'Price fills bullish FVG — trend pullback entry',
                    },
                ],
                'short': [
                    {
                        'indicator': 'MARKET_STRUCTURE',
                        'condition': 'structure_break',
                        'value': 'bearish_bos',
                        'description': 'Bearish BOS — downtrend confirmed with new lower low',
                    },
                    {
                        'indicator': 'FAIR_VALUE_GAP',
                        'condition': 'fvg_fill',
                        'value': 'bearish_fvg',
                        'description': 'Price fills bearish FVG — trend pullback entry',
                    },
                ],
            },
            'exit_rules': {
                'type': 'ATR_BASED',
                'params': {
                    'atr_period': 14,
                    'sl_multiplier': 1.5,
                    'tp_multiplier': 2.5,
                },
            },
            'min_win_rate': 0.40,
            'rules': [
                'Wait for BOS (Break of Structure) to confirm trend direction',
                'Enter when price pulls back to fill a FVG in the trend direction',
                'BOS + FVG must fire on the same bar (both indicators active)',
                'Standard ATR-based exits with 1:1.67 risk-reward',
                'Works best in trending markets — pair with regime filter',
            ],
        },
    },
    {
        'name': 'SMC Full Confluence',
        'domain': 'FOREX',
        'description': (
            'Highest-conviction SMC setup requiring 2+ aligned Smart Money signals '
            'on the same bar. Combines market structure breaks, Fair Value Gaps, '
            'Order Blocks, and Liquidity Sweeps into one confluence score. CHoCH '
            'signals count double. This is how TJR and Trades By Sci trade — '
            'only taking setups where multiple institutional footprints align.'
        ),
        'definition': {
            'strategy_type': 'REVERSAL',
            'timeframe': 'H1',
            'pairs': ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'NZDUSD', 'USDCAD'],
            'indicators': [
                {
                    'type': 'SMC_CONFLUENCE',
                    'params': {
                        'min_confluence': 2,
                        'choch_weight': 2,
                        'market_structure': {'swing_lookback': 5},
                        'fair_value_gap': {'min_gap_pct': 0.0004, 'max_fvg_age': 20},
                        'order_block': {'impulse_mult': 2.0, 'max_ob_age': 30},
                        'liquidity_sweep': {'swing_lookback': 5},
                    },
                },
            ],
            'entry_rules': {
                'long': [
                    {
                        'indicator': 'SMC_CONFLUENCE',
                        'condition': 'confluence',
                        'value': 'bullish_confluence',
                        'description': '2+ bullish SMC signals aligned — high probability long',
                    },
                ],
                'short': [
                    {
                        'indicator': 'SMC_CONFLUENCE',
                        'condition': 'confluence',
                        'value': 'bearish_confluence',
                        'description': '2+ bearish SMC signals aligned — high probability short',
                    },
                ],
            },
            'exit_rules': {
                'type': 'ATR_BASED',
                'params': {
                    'atr_period': 14,
                    'sl_multiplier': 1.5,
                    'tp_multiplier': 3.0,
                },
            },
            'min_win_rate': 0.35,
            'rules': [
                'Requires 2+ aligned SMC signals on the same bar',
                'CHoCH signals count as 2 points (strongest structural signal)',
                'H1 timeframe for higher reliability — fewer but better trades',
                'Wide TP (3x ATR) for high-conviction setups',
                'Trade all major forex pairs for diversification',
                'This is the "sniper" setup — patience for confluence is key',
            ],
        },
    },
]


def seed_smc_strategies(apps, schema_editor):
    CustomStrategy = apps.get_model('nexus', 'CustomStrategy')
    StrategyConfig = apps.get_model('nexus', 'StrategyConfig')

    for strat in SMC_STRATEGIES:
        # Create StrategyConfig
        config_name = f"{strat['name']} ({strat['domain']})"[:50]
        config, _ = StrategyConfig.objects.get_or_create(
            name=config_name,
            defaults={
                'description': strat['description'],
                'is_active': False,
                'priority': 10,
                'max_positions': 3,
            },
        )

        # Create CustomStrategy linked to config
        CustomStrategy.objects.get_or_create(
            name=strat['name'],
            domain=strat['domain'],
            defaults={
                'description': strat['description'],
                'definition': strat['definition'],
                'strategy_config': config,
            },
        )


def reverse(apps, schema_editor):
    CustomStrategy = apps.get_model('nexus', 'CustomStrategy')
    for strat in SMC_STRATEGIES:
        CustomStrategy.objects.filter(name=strat['name'], domain='FOREX').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('nexus', '0011_adaptive_trading_engine'),
    ]

    operations = [
        migrations.RunPython(seed_smc_strategies, reverse),
    ]
