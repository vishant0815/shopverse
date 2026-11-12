"""Catalogue events for the rest of the platform (topic catalog.variants).

The inventory service keeps one stock row per variant, so it needs to know when a
variant appears, changes or goes away, and which seller it belongs to. Every save or
delete of a variant writes a message to the outbox in the same transaction (the seller
views run each request in one transaction), and the worker publishes it.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from messaging.kafka import enqueue

from .models import ProductVariant

TOPIC = "catalog.variants"


def variant_upserted(variant: ProductVariant) -> None:
    enqueue(TOPIC, "VariantUpserted", str(variant.id), {
        "variant_id": str(variant.id),
        "product_id": str(variant.product_id),
        "seller_id": str(variant.product.seller_id),
        "sku": variant.sku,
        "active": variant.is_active,
    })


def variant_removed(variant_id) -> None:
    enqueue(TOPIC, "VariantRemoved", str(variant_id), {"variant_id": str(variant_id)})


@receiver(post_save, sender=ProductVariant)
def on_variant_saved(sender, instance, **kwargs):
    variant_upserted(instance)


@receiver(post_delete, sender=ProductVariant)
def on_variant_deleted(sender, instance, **kwargs):
    variant_removed(instance.id)
