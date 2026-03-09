"""Remove XAUUSD from Forex strategy pairs — symbol unavailable on Vantage International."""

from django.db import migrations


def remove_xauusd_from_forex_strategies(apps, schema_editor):
    CustomStrategy = apps.get_model('nexus', 'CustomStrategy')
    for cs in CustomStrategy.objects.all():
        defn = cs.definition
        if isinstance(defn, dict) and 'pairs' in defn:
            if 'XAUUSD' in defn['pairs']:
                defn['pairs'] = [p for p in defn['pairs'] if p != 'XAUUSD']
                cs.definition = defn
                cs.save()


def add_xauusd_back(apps, schema_editor):
    """Reverse: re-add XAUUSD to forex strategies that have EURUSD (forex indicator)."""
    CustomStrategy = apps.get_model('nexus', 'CustomStrategy')
    for cs in CustomStrategy.objects.all():
        defn = cs.definition
        if isinstance(defn, dict) and 'pairs' in defn:
            if 'EURUSD' in defn['pairs'] and 'XAUUSD' not in defn['pairs']:
                defn['pairs'].append('XAUUSD')
                cs.definition = defn
                cs.save()


class Migration(migrations.Migration):

    dependencies = [
        ('nexus', '0007_seed_cvd_strategies'),
    ]

    operations = [
        migrations.RunPython(
            remove_xauusd_from_forex_strategies,
            reverse_code=add_xauusd_back,
        ),
    ]
