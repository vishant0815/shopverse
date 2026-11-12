"""`python manage.py publish_catalog`: announce every variant and product.

For a catalogue that existed before the events did (and to rebuild another service's
copy from scratch). Safe to repeat: consumers treat each announcement as the newest state
of its variant or product, and a stale one is ignored.
With --once it does nothing if the catalogue has been announced before.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.events import announce_product, variant_upserted
from catalog.models import Product, ProductVariant
from messaging.models import OutboxMessage


class Command(BaseCommand):
    help = "Publish the current state of every variant and product."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Skip if the catalogue was announced before.")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["once"] and OutboxMessage.objects.filter(type="ProductUpserted").exists():
            self.stdout.write("Catalogue already announced")
            return
        variants = 0
        for variant in ProductVariant.objects.select_related("product").iterator():
            variant_upserted(variant)
            variants += 1
        products = 0
        for product_id in Product.objects.values_list("id", flat=True).iterator():
            announce_product(product_id)
            products += 1
        self.stdout.write(self.style.SUCCESS(f"Queued {variants} variants and {products} products for publishing"))
