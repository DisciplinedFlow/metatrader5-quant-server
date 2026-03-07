from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('nexus', '0003_backtestresult_data_source'),
    ]

    operations = [
        migrations.AddField(
            model_name='backtestresult',
            name='trades',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='backtestresult',
            name='equity_curve',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='backtestresult',
            name='symbol_breakdown',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
