"""`python manage.py publish_catalog`: announce every variant on catalog.variants.

For a catalogue that existed before the events did (and to rebuild another service's
copy from scratch). Safe to repeat: consumers treat each announcement as an upsert.
With --once it does nothing if variants have been announced before.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.events import variant_upserted
from catalog.models import ProductVariant
from messaging.models import OutboxMessage


class Command(BaseCommand):
    help = "Publish a VariantUpserted event for every variant."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Skip if variants were announced before.")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["once"] and OutboxMessage.objects.filter(type="VariantUpserted").exists():
            self.stdout.write("Catalogue already announced")
            return
        count = 0
        for variant in ProductVariant.objects.select_related("product").iterator():
            variant_upserted(variant)
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Queued {count} variants for publishing"))
