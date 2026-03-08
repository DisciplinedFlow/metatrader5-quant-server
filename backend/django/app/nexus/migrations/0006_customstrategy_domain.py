from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('nexus', '0005_customstrategy'),
    ]

    operations = [
        migrations.AddField(
            model_name='customstrategy',
            name='domain',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('FOREX', 'Forex'),
                    ('CRYPTO', 'Crypto'),
                    ('POLYMARKET', 'Polymarket'),
                ],
                default='FOREX',
            ),
        ),
    ]
