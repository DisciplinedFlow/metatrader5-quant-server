"""
Drop all Polymarket database tables and clean up related metadata.

The polymarket app has been removed from the codebase but the tables
still exist in PostgreSQL. This migration drops them via raw SQL.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("nexus", "0018_enhance_energy_strategies"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "DROP TABLE IF EXISTS polymarket_polybacktestresult CASCADE;",
                "DROP TABLE IF EXISTS polymarket_polyprobabilitylog CASCADE;",
                "DROP TABLE IF EXISTS polymarket_polytrade CASCADE;",
                "DROP TABLE IF EXISTS polymarket_polyposition CASCADE;",
                "DROP TABLE IF EXISTS polymarket_polymarket CASCADE;",
                "DELETE FROM auth_permission WHERE content_type_id IN (SELECT id FROM django_content_type WHERE app_label = 'polymarket');",
                "DELETE FROM django_content_type WHERE app_label = 'polymarket';",
                "DELETE FROM django_migrations WHERE app = 'polymarket';",
            ],
            reverse_sql=[
                # No reverse — these tables are gone and the app has been removed
            ],
        ),
    ]
