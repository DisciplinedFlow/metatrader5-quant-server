"""
Remove crypto/Polymarket from the domain and market-type choices.

Crypto trading has moved to a separate project; this repo is forex/MT5-only
now. Drops the leftover domain='POLYMARKET' CustomStrategy rows seeded by
0007_seed_cvd_strategies (the polymarket_* tables themselves were already
dropped in 0019_drop_polymarket_tables) and narrows the choices fields to
match app.nexus.models.
"""

from django.db import migrations, models


def delete_polymarket_strategies(apps, schema_editor):
    CustomStrategy = apps.get_model("nexus", "CustomStrategy")
    CustomStrategy.objects.filter(domain="POLYMARKET").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("nexus", "0021_merge_20260313_1924"),
    ]

    operations = [
        migrations.RunPython(delete_polymarket_strategies, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="customstrategy",
            name="domain",
            field=models.CharField(max_length=20, choices=[("FOREX", "Forex")], default="FOREX"),
        ),
        migrations.AlterField(
            model_name="trade",
            name="market_type",
            field=models.CharField(max_length=50, choices=[("FOREX", "Forex"), ("OTHER", "Other")]),
        ),
    ]
