"""
One-time management command to backfill all closed Lighter trades into Neo4j.

Usage:
    python manage.py backfill_neo4j_lighter
    # or inside Docker:
    docker compose exec django python manage.py backfill_neo4j_lighter

This forces a full sync (ignores the Redis watermark) to catch all 20+ missing
trades that were lost because record_to_graph used type='trade' instead of
'lighter_trade', causing Trade.objects.get() to fail on 'lighter_123' IDs.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Backfill all closed Lighter trades into Neo4j knowledge graph'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Show what would be synced without writing to Neo4j',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        from app.crypto.models import CryptoPosition
        from app.quant.knowledge.connection import get_graph

        graph = get_graph()
        if graph is None:
            self.stderr.write(self.style.ERROR('Neo4j not available. Check NEO4J_PASSWORD in settings.'))
            return

        closed_trades = CryptoPosition.objects.filter(
            status='CLOSED',
            venue='LIGHTER',
            pnl_usd__isnull=False,
        ).order_by('id')

        total = closed_trades.count()
        self.stdout.write(f'Found {total} closed Lighter trades to sync.')

        if total == 0:
            return

        synced = 0
        skipped = 0
        errors = 0

        for pos in closed_trades:
            trade_data = {
                'trade_id': f'lighter_{pos.id}',
                'django_id': pos.id,
                'symbol': pos.symbol,
                'direction': 'BUY' if pos.side == 'LONG' else 'SELL',
                'entry_time': pos.opened_at,
                'close_time': pos.closed_at,
                'entry_price': float(pos.entry_price or 0),
                'close_price': float(pos.close_price or 0),
                'pnl': float(pos.pnl_usd or 0),
                'strategy': pos.entry_signal or 'unknown',
                'closing_reason': pos.close_reason or '',
                'venue': 'LIGHTER',
                'hour_utc': pos.opened_at.hour if pos.opened_at else 0,
                'day_of_week': pos.opened_at.weekday() if pos.opened_at else 0,
            }

            if dry_run:
                pnl_str = f'${pos.pnl_usd:+.2f}' if pos.pnl_usd else '$0.00'
                self.stdout.write(
                    f'  [DRY RUN] #{pos.id} {pos.symbol} {pos.side} '
                    f'{pnl_str} ({pos.close_reason or "?"}) '
                    f'{pos.opened_at:%Y-%m-%d %H:%M} -> {pos.closed_at:%Y-%m-%d %H:%M if pos.closed_at else "?"}'
                )
                synced += 1
                continue

            try:
                result = graph.record_trade(trade_data)
                if result:
                    synced += 1
                    self.stdout.write(
                        f'  Synced #{pos.id} {pos.symbol} {pos.side} '
                        f'pnl=${pos.pnl_usd:+.2f} -> {result}'
                    )
                else:
                    skipped += 1
            except Exception as e:
                err_str = str(e)
                if 'already exists' in err_str or 'ConstraintValidation' in err_str:
                    skipped += 1
                    self.stdout.write(f'  Skipped #{pos.id} (already in graph)')
                else:
                    errors += 1
                    self.stderr.write(f'  Error #{pos.id}: {e}')

        # Update the watermark so periodic sync doesn't re-process
        if not dry_run and synced > 0:
            from django.core.cache import cache
            max_id = closed_trades.last().id
            cache.set('lighter:neo4j_last_sync_id', max_id, timeout=None)

        prefix = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'\n{prefix}Done: {synced} synced, {skipped} skipped (dupes), {errors} errors out of {total} total.'
        ))
