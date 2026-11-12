"""Catalogue events for the rest of the platform.

Two topics:

- `catalog.variants` (VariantUpserted, VariantRemoved): the inventory service keeps one stock
  row per variant, so it needs to know when a variant appears, changes or goes away.
- `catalog.products` (ProductUpserted, ProductRemoved): the search index holds one document
  per product. Each ProductUpserted carries the whole product (name, category path, images,
  variants, price range) and a revision, so a consumer only has to apply the newest one.

Every change writes to the outbox in the same transaction (the seller views run each request
in one transaction), and the worker publishes it.

Ordering: announcing a product locks its row first, so announcements for one product are
written in the order their transactions commit. Kafka keeps messages with the same key
(the product id) in order, so consumers see the states in the order they happened.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver

from messaging.kafka import enqueue

from .models import Category, Product, ProductImage, ProductRevision, ProductVariant

VARIANTS_TOPIC = "catalog.variants"
PRODUCTS_TOPIC = "catalog.products"


def _money(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


# Variants (inventory) -------------------------------------------------------------

def variant_upserted(variant: ProductVariant) -> None:
    enqueue(VARIANTS_TOPIC, "VariantUpserted", str(variant.id), {
        "variant_id": str(variant.id),
        "product_id": str(variant.product_id),
        "seller_id": str(variant.product.seller_id),
        "sku": variant.sku,
        "active": variant.is_active,
    })


def variant_removed(variant_id) -> None:
    enqueue(VARIANTS_TOPIC, "VariantRemoved", str(variant_id), {"variant_id": str(variant_id)})


# Products (search) ----------------------------------------------------------------

def _next_revision(product: Product) -> int:
    """Lock the product for the rest of the transaction and return its next revision."""
    Product.objects.select_for_update().only("id").get(pk=product.pk)
    row, _ = ProductRevision.objects.get_or_create(product_id=product.pk)
    row.revision += 1
    row.save(update_fields=["revision"])
    return row.revision


def _category_chain(category: Category) -> list[Category]:
    chain, node = [], category
    while node is not None:
        chain.append(node)
        node = node.parent
    return chain


def product_document(product: Product, revision: int) -> dict:
    chain = _category_chain(product.category)
    variants = list(product.variants.order_by("created_at", "sku"))
    images = list(product.images.order_by("position"))
    active_prices = [v.price for v in variants if v.is_active]
    listed = product.status == Product.Status.ACTIVE and all(c.is_active for c in chain)
    return {
        "product_id": str(product.id),
        "revision": revision,
        "listed": listed,
        "seller_id": str(product.seller_id),
        "slug": product.slug,
        "name": product.name,
        "brand": product.brand,
        "description": product.description,
        "status": product.status,
        "category": {"id": str(product.category_id), "name": product.category.name, "slug": product.category.slug},
        # Every category above this one, so a search under a parent category finds its children's products.
        "category_slugs": [c.slug for c in chain],
        "category_names": [c.name for c in chain],
        "image_url": images[0].url if images else "",
        "images": [{"url": i.url, "alt_text": i.alt_text} for i in images],
        "variants": [{
            "id": str(v.id), "sku": v.sku, "colour": v.colour, "size": v.size,
            "price": _money(v.price), "compare_at_price": _money(v.compare_at_price), "is_active": v.is_active,
        } for v in variants],
        "colours": sorted({v.colour for v in variants if v.is_active and v.colour}),
        "sizes": sorted({v.size for v in variants if v.is_active and v.size}),
        "price_min": _money(min(active_prices)) if active_prices else None,
        "price_max": _money(max(active_prices)) if active_prices else None,
        "created_at": product.created_at.isoformat(),
        "updated_at": product.updated_at.isoformat(),
    }


# Products being deleted right now. Their variants and images are removed by the same cascade;
# announcing them then would create a revision row the cascade can't remove.
_deleting: set = set()


def announce_product(product_id) -> None:
    """Send the product's current state on catalog.products. Does nothing if it no longer exists."""
    if product_id in _deleting:
        return
    with transaction.atomic():
        product = (Product.objects.select_related("category", "category__parent")
                   .filter(pk=product_id).first())
        if product is None:
            return
        revision = _next_revision(product)
        enqueue(PRODUCTS_TOPIC, "ProductUpserted", str(product.id), product_document(product, revision))


def product_removed(product_id) -> None:
    enqueue(PRODUCTS_TOPIC, "ProductRemoved", str(product_id), {"product_id": str(product_id)})


def products_under(category: Category):
    return Product.objects.filter(category_id__in=category.descendant_ids())


# Signal hooks ---------------------------------------------------------------------

@receiver(post_save, sender=ProductVariant)
def on_variant_saved(sender, instance, **kwargs):
    variant_upserted(instance)
    announce_product(instance.product_id)


@receiver(post_delete, sender=ProductVariant)
def on_variant_deleted(sender, instance, **kwargs):
    variant_removed(instance.id)
    announce_product(instance.product_id)


@receiver(post_save, sender=Product)
def on_product_saved(sender, instance, **kwargs):
    announce_product(instance.pk)


@receiver(pre_delete, sender=Product)
def on_product_deleting(sender, instance, **kwargs):
    _deleting.add(instance.pk)


@receiver(post_delete, sender=Product)
def on_product_deleted(sender, instance, **kwargs):
    _deleting.discard(instance.pk)
    product_removed(instance.pk)


@receiver(post_save, sender=ProductImage)
@receiver(post_delete, sender=ProductImage)
def on_image_changed(sender, instance, **kwargs):
    announce_product(instance.product_id)


@receiver(post_save, sender=Category)
def on_category_saved(sender, instance, **kwargs):
    # A renamed or hidden category changes the listing of every product beneath it.
    for product in products_under(instance):
        announce_product(product.pk)
