"""Update EMA Ribbon Pullback with ADX trend filter and candle confirmation."""

from django.db import migrations


def update_ema_ribbon(apps, schema_editor):
    CustomStrategy = apps.get_model('nexus', 'CustomStrategy')
    try:
        cs = CustomStrategy.objects.get(name='EMA Ribbon Pullback')
    except CustomStrategy.DoesNotExist:
        return

    cs.description = (
        'Trend continuation strategy using 4-EMA ribbon alignment (8, 13, 21, 34) '
        'with confirmed pullback entries. ADX filter ensures only strong trends are '
        'traded. Price must pull back to inner EMAs then close back in the trend '
        'direction. Minimum EMA spread eliminates ranging markets.'
    )
    cs.definition = {
        'strategy_type': 'MOMENTUM',
        'timeframe': 'M15',
        'pairs': ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD'],
        'indicators': [
            {
                'type': 'EMA_RIBBON_PULLBACK',
                'params': {
                    'ema_periods': [8, 13, 21, 34],
                    'rsi_period': 14,
                    'rsi_low': 35,
                    'rsi_high': 65,
                    'adx_period': 14,
                    'adx_threshold': 25,
                    'min_spread_pct': 0.001,
                },
            },
        ],
        'entry_rules': {
            'long': [
                {
                    'indicator': 'EMA_RIBBON_PULLBACK',
                    'condition': 'pullback',
                    'value': 'bullish_ribbon_pullback',
                    'description': 'Strong trend (ADX>25) + EMA ribbon bullish + confirmed pullback',
                },
            ],
            'short': [
                {
                    'indicator': 'EMA_RIBBON_PULLBACK',
                    'condition': 'pullback',
                    'value': 'bearish_ribbon_pullback',
                    'description': 'Strong trend (ADX>25) + EMA ribbon bearish + confirmed pullback',
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
            'ADX must be > 25 confirming a real trend (no ranging markets)',
            'All 4 EMAs properly stacked with minimum 0.1% spread',
            'Price pulls back to touch EMA13 or EMA21',
            'Candle must close back above EMA8 (bull) or below EMA8 (bear)',
            'RSI between 35-65 (wider neutral zone for trend continuation)',
        ],
    }
    cs.save()


def reverse(apps, schema_editor):
    pass  # Non-destructive update, no reverse needed


class Migration(migrations.Migration):

    dependencies = [
        ('nexus', '0009_seed_ema_ribbon_pullback'),
    ]

    operations = [
        migrations.RunPython(update_ema_ribbon, reverse),
    ]
