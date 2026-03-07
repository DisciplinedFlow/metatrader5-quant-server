from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('nexus', '0002_seed_strategies'),
    ]

    operations = [
        migrations.AddField(
            model_name='backtestresult',
            name='data_source',
            field=models.CharField(default='MT5', max_length=20),
        ),
    ]
