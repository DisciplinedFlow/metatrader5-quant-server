"""Add XAUUSD and XAGUSD back to CVD Forex strategy pairs — metals now in Market Watch."""

from django.db import migrations


METALS_TO_ADD = ['XAUUSD', 'XAGUSD']


def add_metals_to_cvd_strategies(apps, schema_editor):
    CustomStrategy = apps.get_model('nexus', 'CustomStrategy')
    for cs in CustomStrategy.objects.filter(domain='FOREX'):
        defn = cs.definition
        if isinstance(defn, dict) and 'pairs' in defn:
            changed = False
            for symbol in METALS_TO_ADD:
                if symbol not in defn['pairs']:
                    defn['pairs'].append(symbol)
                    changed = True
            if changed:
                cs.definition = defn
                cs.save()


def remove_metals_from_cvd_strategies(apps, schema_editor):
    """Reverse: remove XAUUSD and XAGUSD from CVD Forex strategies."""
    CustomStrategy = apps.get_model('nexus', 'CustomStrategy')
    for cs in CustomStrategy.objects.filter(domain='FOREX'):
        defn = cs.definition
        if isinstance(defn, dict) and 'pairs' in defn:
            original_len = len(defn['pairs'])
            defn['pairs'] = [p for p in defn['pairs'] if p not in METALS_TO_ADD]
            if len(defn['pairs']) != original_len:
                cs.definition = defn
                cs.save()


class Migration(migrations.Migration):

    dependencies = [
        ('nexus', '0013_ml_models'),
    ]

    operations = [
        migrations.RunPython(
            add_metals_to_cvd_strategies,
            reverse_code=remove_metals_from_cvd_strategies,
        ),
    ]
