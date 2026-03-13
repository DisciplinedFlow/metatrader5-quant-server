"""Add database indexes to Trade model for frequently queried fields.

Fields indexed:
- symbol: filtered in entry algorithms, AI brain, symbol performance checks
- entry_time: default ordering, time-range filters
- close_time: daily halt check, orphan detection, performance lookups
- strategy: strategy name matching (icontains fallback)
- strategy_config: FK used by orchestrator, performance gates, AI executor
- transaction_broker_id: trade lookup by MT5 ticket on close
- (symbol, close_time): composite for per-symbol recent trade queries
- (strategy_config, close_time): composite for per-strategy performance
- (close_time, pnl): composite for daily P&L aggregation (halt check)
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('nexus', '0015_rotationlog'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='trade',
            index=models.Index(fields=['symbol'], name='idx_trade_symbol'),
        ),
        migrations.AddIndex(
            model_name='trade',
            index=models.Index(fields=['entry_time'], name='idx_trade_entry_time'),
        ),
        migrations.AddIndex(
            model_name='trade',
            index=models.Index(fields=['close_time'], name='idx_trade_close_time'),
        ),
        migrations.AddIndex(
            model_name='trade',
            index=models.Index(fields=['strategy'], name='idx_trade_strategy'),
        ),
        migrations.AddIndex(
            model_name='trade',
            index=models.Index(fields=['strategy_config'], name='idx_trade_strategy_cfg'),
        ),
        migrations.AddIndex(
            model_name='trade',
            index=models.Index(
                fields=['transaction_broker_id'],
                name='idx_trade_broker_id',
            ),
        ),
        migrations.AddIndex(
            model_name='trade',
            index=models.Index(
                fields=['symbol', 'close_time'],
                name='idx_trade_symbol_close',
            ),
        ),
        migrations.AddIndex(
            model_name='trade',
            index=models.Index(
                fields=['strategy_config', 'close_time'],
                name='idx_trade_stratcfg_close',
            ),
        ),
        migrations.AddIndex(
            model_name='trade',
            index=models.Index(
                fields=['close_time', 'pnl'],
                name='idx_trade_close_pnl',
            ),
        ),
    ]
