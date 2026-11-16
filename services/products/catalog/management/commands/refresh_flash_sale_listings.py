"""Re-announce the products whose flash sale has just started or ended, so search shows the right price.

A sale's price changes at its start and end times, which nothing else triggers. Run this every minute
(`--loop` keeps it running). Each run looks back two minutes, so a missed run is covered by the next.
Announcing a product twice is harmless: every announcement carries a revision and consumers keep the newest.
"""

import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from catalog import events
from catalog.models import FlashSaleItem

LOOKBACK = timedelta(minutes=2)


class Command(BaseCommand):
    help = "Re-announce products whose flash sale started or ended in the last two minutes."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true", help="Keep running, checking once a minute.")

    def handle(self, *args, **options):
        if options["loop"]:
            while True:
                self.refresh()
                time.sleep(60)
        self.refresh()

    def refresh(self):
        now = timezone.now()
        since = now - LOOKBACK
        boundary = (
            Q(sale__starts_at__gt=since, sale__starts_at__lte=now)
            | Q(sale__ends_at__gt=since, sale__ends_at__lte=now)
        )
        product_ids = set(
            FlashSaleItem.objects.filter(boundary, sale__is_active=True).values_list("variant__product_id", flat=True)
        )
        for product_id in product_ids:
            events.announce_product(product_id)
        self.stdout.write(f"Announced {len(product_ids)} product(s) with a flash sale boundary.")
