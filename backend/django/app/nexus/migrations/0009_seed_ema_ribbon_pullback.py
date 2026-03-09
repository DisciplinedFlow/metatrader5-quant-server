"""Seed EMA Ribbon Pullback trend continuation strategy for Forex."""

from django.db import migrations


def seed_ema_ribbon_strategy(apps, schema_editor):
    StrategyConfig = apps.get_model('nexus', 'StrategyConfig')
    CustomStrategy = apps.get_model('nexus', 'CustomStrategy')

    config, _ = StrategyConfig.objects.get_or_create(
        name='EMA Ribbon Pullback (FOREX)',
        defaults={'is_active': False},
    )

    CustomStrategy.objects.get_or_create(
        strategy_config=config,
        defaults={
            'name': 'EMA Ribbon Pullback',
            'description': (
                'Trend continuation strategy using 4-EMA ribbon alignment (8, 13, 21, 34) '
                'with pullback entries. When all EMAs are properly stacked and price pulls '
                'back to the 13 or 21 EMA, enter in the trend direction. RSI filter prevents '
                'entries in overbought/oversold conditions.'
            ),
            'domain': 'FOREX',
            'definition': {
                'strategy_type': 'MOMENTUM',
                'timeframe': 'M15',
                'pairs': ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD'],
                'indicators': [
                    {
                        'type': 'EMA_RIBBON_PULLBACK',
                        'params': {
                            'ema_periods': [8, 13, 21, 34],
                            'rsi_period': 14,
                            'rsi_low': 40,
                            'rsi_high': 60,
                        },
                    },
                ],
                'entry_rules': {
                    'long': [
                        {
                            'indicator': 'EMA_RIBBON_PULLBACK',
                            'condition': 'pullback',
                            'value': 'bullish_ribbon_pullback',
                            'description': 'EMA ribbon aligned bullish + price pullback to inner EMAs',
                        },
                    ],
                    'short': [
                        {
                            'indicator': 'EMA_RIBBON_PULLBACK',
                            'condition': 'pullback',
                            'value': 'bearish_ribbon_pullback',
                            'description': 'EMA ribbon aligned bearish + price pullback to inner EMAs',
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
                'min_win_rate': 0.45,
                'rules': [
                    'All 4 EMAs must be properly stacked (8>13>21>34 for bull, reversed for bear)',
                    'Price must pull back to touch EMA13 or EMA21',
                    'RSI must be between 40-60 (not overbought/oversold)',
                    'Trend continuation — trades WITH the trend, not against it',
                    'Best during London and NY sessions when trends develop',
                ],
            },
        },
    )


def reverse(apps, schema_editor):
    CustomStrategy = apps.get_model('nexus', 'CustomStrategy')
    StrategyConfig = apps.get_model('nexus', 'StrategyConfig')

    CustomStrategy.objects.filter(name='EMA Ribbon Pullback').delete()
    StrategyConfig.objects.filter(name='EMA Ribbon Pullback (FOREX)').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('nexus', '0008_remove_xauusd_from_forex_strategies'),
    ]

    operations = [
        migrations.RunPython(seed_ema_ribbon_strategy, reverse),
    ]
