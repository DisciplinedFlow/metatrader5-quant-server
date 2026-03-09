"""Phase 1A: Adaptive Trading Engine models and fields.

Adds StrategyConfig orchestration fields, Trade position management fields,
PairLock model for pair conflict resolution, and MarketRegime model for
regime-based filtering.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('nexus', '0010_update_ema_ribbon_pullback_v2'),
    ]

    operations = [
        # --- StrategyConfig new fields ---
        migrations.AddField(
            model_name='strategyconfig',
            name='priority',
            field=models.IntegerField(default=10),
        ),
        migrations.AddField(
            model_name='strategyconfig',
            name='max_positions',
            field=models.IntegerField(default=3),
        ),
        migrations.AddField(
            model_name='strategyconfig',
            name='capital_allocation_pct',
            field=models.FloatField(default=0.33),
        ),
        migrations.AddField(
            model_name='strategyconfig',
            name='regime_filter',
            field=models.CharField(
                blank=True,
                choices=[('', 'Any'), ('TRENDING_UP', 'Trending Up'), ('TRENDING_DOWN', 'Trending Down'), ('RANGING', 'Ranging'), ('VOLATILE', 'Volatile')],
                default='',
                max_length=20,
            ),
        ),
        # --- Trade new fields ---
        migrations.AddField(
            model_name='trade',
            name='strategy_config',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='trades',
                to='nexus.strategyconfig',
            ),
        ),
        migrations.AddField(
            model_name='trade',
            name='breakeven_moved',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='trade',
            name='partial_closed',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='trade',
            name='partial_close_volume',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='trade',
            name='partial_close_price',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='trade',
            name='entry_timeframe',
            field=models.CharField(blank=True, default='M15', max_length=10),
        ),
        migrations.AddField(
            model_name='trade',
            name='entry_atr',
            field=models.FloatField(blank=True, null=True),
        ),
        # --- PairLock model ---
        migrations.CreateModel(
            name='PairLock',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('symbol', models.CharField(max_length=20, unique=True)),
                ('ticket', models.BigIntegerField()),
                ('locked_at', models.DateTimeField(auto_now_add=True)),
                ('strategy', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pair_locks', to='nexus.strategyconfig')),
            ],
            options={
                'indexes': [models.Index(fields=['symbol'], name='nexus_pairl_symbol_idx')],
            },
        ),
        # --- MarketRegime model ---
        migrations.CreateModel(
            name='MarketRegime',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('symbol', models.CharField(max_length=20)),
                ('timeframe', models.CharField(default='H1', max_length=10)),
                ('regime', models.CharField(choices=[('TRENDING_UP', 'Trending Up'), ('TRENDING_DOWN', 'Trending Down'), ('RANGING', 'Ranging'), ('VOLATILE', 'Volatile'), ('UNKNOWN', 'Unknown')], default='UNKNOWN', max_length=20)),
                ('adx', models.FloatField(default=0)),
                ('bb_width', models.FloatField(default=0)),
                ('atr_ratio', models.FloatField(default=0)),
                ('confidence', models.FloatField(default=0)),
                ('computed_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'unique_together': {('symbol', 'timeframe')},
            },
        ),
    ]
