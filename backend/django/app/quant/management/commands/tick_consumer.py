"""Django management command to run the real-time tick consumer."""

from django.core.management.base import BaseCommand

from app.quant.tick_consumer import start_tick_consumer


class Command(BaseCommand):
    help = 'Start the real-time tick consumer for CVD signal detection'

    def add_arguments(self, parser):
        parser.add_argument(
            '--redis-url',
            default='redis://redis:6379/2',
            help='Redis URL for tick stream (default: redis://redis:6379/2)',
        )

    def handle(self, *args, **options):
        self.stdout.write('Starting real-time tick consumer...')
        start_tick_consumer(redis_url=options['redis_url'])
