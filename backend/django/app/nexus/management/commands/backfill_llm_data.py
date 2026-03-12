"""
Backfill LLM training examples from existing labeled TradeFeatures.

Usage:
    python manage.py backfill_llm_data
    python manage.py backfill_llm_data --dry-run
"""

from django.core.management.base import BaseCommand

from app.nexus.models import TradeFeature
from app.quant.ml.data_collector import generate_training_example, save_training_example


class Command(BaseCommand):
    help = 'Backfill LLM training data from labeled TradeFeatures'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be generated without writing to disk',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        # Get all TradeFeatures that have been labeled (actual_win is set)
        labeled = TradeFeature.objects.filter(
            actual_win__isnull=False,
        ).select_related('trade')

        total = labeled.count()
        self.stdout.write(f"Found {total} labeled TradeFeatures")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no files will be written"))

        generated = 0
        skipped = 0
        errors = 0

        for tf in labeled:
            trade = tf.trade
            try:
                example = generate_training_example(trade, tf)
                if example is None:
                    skipped += 1
                    self.stdout.write(
                        f"  SKIP Trade #{trade.id} ({trade.symbol}) — "
                        f"no features_json"
                    )
                    continue

                if not dry_run:
                    save_training_example(example)

                generated += 1
                won = example['metadata']['won']
                pnl = example['metadata']['pnl']
                tag = self.style.SUCCESS("WIN") if won else self.style.ERROR("LOSS")
                self.stdout.write(
                    f"  [{generated}/{total}] Trade #{trade.id} "
                    f"{trade.symbol} {tag} ${pnl:+.2f}"
                )

            except Exception as e:
                errors += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"  ERROR Trade #{trade.id} ({trade.symbol}): {e}"
                    )
                )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Generated: {generated}"))
        self.stdout.write(f"Skipped:   {skipped}")
        if errors:
            self.stdout.write(self.style.ERROR(f"Errors:    {errors}"))
        else:
            self.stdout.write(f"Errors:    {errors}")

        if dry_run:
            self.stdout.write(self.style.WARNING("\nDry run complete — nothing written"))
        else:
            self.stdout.write(f"\nDone. {generated} examples written to JSONL.")
