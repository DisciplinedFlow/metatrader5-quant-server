# Generated migration for CryptoPosition position management fields

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='CryptoPosition',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('symbol', models.CharField(max_length=20)),
                ('side', models.CharField(choices=[('LONG', 'Long'), ('SHORT', 'Short')], max_length=5)),
                ('entry_price', models.FloatField()),
                ('size', models.FloatField()),
                ('leverage', models.IntegerField(default=1)),
                ('entry_signal', models.CharField(blank=True, max_length=50)),
                ('stop_loss', models.FloatField(blank=True, null=True)),
                ('take_profit', models.FloatField(blank=True, null=True)),
                ('status', models.CharField(choices=[('OPEN', 'Open'), ('CLOSED', 'Closed')], default='OPEN', max_length=6)),
                ('close_price', models.FloatField(blank=True, null=True)),
                ('pnl_usd', models.FloatField(blank=True, null=True)),
                ('close_reason', models.CharField(blank=True, choices=[('SIGNAL_REVERSAL', 'Signal Reversal'), ('STOP_LOSS', 'Stop Loss'), ('TAKE_PROFIT', 'Take Profit'), ('PROFIT_PROTECTION', 'Profit Protection'), ('TIME_EXIT', 'Time Exit'), ('MANUAL', 'Manual')], max_length=20, null=True)),
                ('opened_at', models.DateTimeField(auto_now_add=True)),
                ('closed_at', models.DateTimeField(blank=True, null=True)),
                ('peak_profit_usd', models.FloatField(blank=True, help_text='Peak unrealized PnL in USD, tracked for profit protection', null=True)),
            ],
            options={
                'ordering': ['-opened_at'],
            },
        ),
        migrations.CreateModel(
            name='CryptoBacktestResult',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('run_time', models.DateTimeField(auto_now_add=True)),
                ('symbol', models.CharField(default='BTC', max_length=20)),
                ('strategy_name', models.CharField(default='momentum', max_length=50)),
                ('total_trades', models.IntegerField()),
                ('winning_trades', models.IntegerField()),
                ('losing_trades', models.IntegerField()),
                ('win_rate', models.FloatField()),
                ('total_pnl', models.FloatField()),
                ('profit_factor', models.FloatField(null=True)),
                ('avg_win', models.FloatField(null=True)),
                ('avg_loss', models.FloatField(null=True)),
                ('max_drawdown', models.FloatField(null=True)),
                ('passed', models.BooleanField()),
                ('capital_usd', models.FloatField(default=1000)),
                ('trades', models.JSONField(blank=True, default=list)),
                ('equity_curve', models.JSONField(blank=True, default=list)),
            ],
            options={
                'ordering': ['-run_time'],
            },
        ),
        migrations.CreateModel(
            name='CryptoTrade',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('order_id', models.CharField(max_length=100)),
                ('side', models.CharField(choices=[('BUY', 'Buy'), ('SELL', 'Sell')], max_length=4)),
                ('price', models.FloatField()),
                ('size', models.FloatField()),
                ('fee', models.FloatField(default=0.0)),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('FILLED', 'Filled'), ('FAILED', 'Failed')], default='PENDING', max_length=7)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('position', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='trades', to='crypto.cryptoposition')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
