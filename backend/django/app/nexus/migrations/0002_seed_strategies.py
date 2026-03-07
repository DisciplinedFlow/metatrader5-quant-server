from django.db import migrations


def seed_strategies(apps, schema_editor):
    StrategyConfig = apps.get_model('nexus', 'StrategyConfig')
    StrategyConfig.objects.get_or_create(
        name='MEAN_REVERSION',
        defaults={
            'is_active': False,
            'description': 'Bollinger Band mean reversion on M15. Uses $100 capital at 200x leverage.',
        },
    )
    StrategyConfig.objects.get_or_create(
        name='SCALPING',
        defaults={
            'is_active': True,
            'description': 'EMA crossover + RSI confirmation on M5. Conservative sizing for small accounts (3.50 EUR at 100x).',
        },
    )


def reverse_seed(apps, schema_editor):
    StrategyConfig = apps.get_model('nexus', 'StrategyConfig')
    StrategyConfig.objects.filter(name__in=['MEAN_REVERSION', 'SCALPING']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('nexus', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_strategies, reverse_seed),
    ]
