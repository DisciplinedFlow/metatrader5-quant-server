"""
Django management command: seed_brain

Seeds the Neo4j trading brain with 6 months of backtested reference trade nodes
derived from real MT5 H4 OHLCV data (no real orders placed).

Usage:
    # All symbols (metals → energy → forex):
    docker exec -it django python manage.py seed_brain

    # Single symbol test:
    docker exec -it django python manage.py seed_brain --symbol XAUUSD

    # Multiple symbols:
    docker exec -it django python manage.py seed_brain --symbol XAUUSD --symbol XAGUSD

    # Geo events only (no trade simulation):
    docker exec -it django python manage.py seed_brain --geo-only

    # Show aggregate stats per symbol:
    docker exec -it django python manage.py seed_brain --verbose

After seeding, query the brain via Django shell:
    from app.quant.knowledge.connection import get_graph
    g = get_graph()
    print(g.get_graph_summary())
"""

import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Seed Neo4j trading brain with backtested reference trade nodes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--symbol',
            action='append',
            dest='symbols',
            metavar='SYMBOL',
            help='Specific symbol(s) to seed (repeat for multiple). Default: all.',
        )
        parser.add_argument(
            '--geo-only',
            action='store_true',
            default=False,
            help='Only seed geopolitical event nodes, skip trade simulation.',
        )
        parser.add_argument(
            '--min-confluence',
            type=float,
            default=0.55,
            help='Minimum confluence score for setups (0.0–1.0). Default: 0.55.',
        )

    def handle(self, *args, **options):
        try:
            from app.quant.knowledge.backtest_seeder import BacktestSeeder
        except ImportError:
            from quant.knowledge.backtest_seeder import BacktestSeeder

        symbols = options.get('symbols')
        geo_only = options.get('geo_only', False)
        min_confluence = options.get('min_confluence', 0.55)

        self.stdout.write(self.style.MIGRATE_HEADING(
            '\n=== Neo4j Trading Brain — Backtest Seeder ===\n'
        ))

        seeder = BacktestSeeder()

        if not seeder.graph:
            self.stderr.write(self.style.ERROR(
                'Cannot connect to Neo4j. Is the neo4j container running?\n'
                'Check: docker compose ps neo4j'
            ))
            return

        self.stdout.write(f'Neo4j connected: {seeder.graph.health_check()}\n')

        if geo_only:
            count = seeder.seed_geo_events()
            self.stdout.write(self.style.SUCCESS(
                f'\nSeeded {count} geopolitical event nodes.\n'
            ))
            return

        # Apply min_confluence override via monkey-patch (simple approach)
        if min_confluence != 0.55:
            try:
                from app.quant.knowledge import pattern_detector as pd
            except ImportError:
                from quant.knowledge import pattern_detector as pd
            _orig_find = pd.find_setups
            def _patched(symbol, bars, **kwargs):
                return _orig_find(symbol, bars, min_confluence=min_confluence)
            pd.find_setups = _patched

        report = seeder.run(symbols=symbols)

        self.stdout.write(self.style.SUCCESS('\n=== Seeding Complete ===\n'))
        self.stdout.write(f"Geo event nodes:         {report['geo_events_seeded']}")
        self.stdout.write(f"Symbols processed:       {report['symbols_processed']}")
        self.stdout.write(f"Total setups detected:   {report['total_setups_detected']}")
        self.stdout.write(f"Reference trades seeded: {report['total_reference_trades_seeded']}")

        if options.get('verbosity', 1) >= 2:
            self.stdout.write('\n--- Per-Symbol Breakdown ---')
            for sym, stats in report['per_symbol'].items():
                agg = stats.get('aggregate_1_2', {})
                self.stdout.write(
                    f"  {sym:12s}  bars={stats.get('bars_fetched', 0):4d}  "
                    f"setups={stats.get('setups', 0):3d}  "
                    f"seeded={stats.get('seeded', 0):3d}  "
                    f"WR@1:2={agg.get('win_rate', '?')}  "
                    f"E(R)={agg.get('expectancy_r', '?')}"
                )

        self.stdout.write(
            '\nQuery the brain:\n'
            '  docker exec -it django python manage.py shell\n'
            '  >>> from app.quant.knowledge.connection import get_graph\n'
            '  >>> g = get_graph(); print(g.get_graph_summary())\n'
        )
