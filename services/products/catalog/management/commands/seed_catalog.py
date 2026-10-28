"""Fill the catalogue with demo categories and products.

    python manage.py seed_catalog            # add demo data (safe to run again)
    python manage.py seed_catalog --reset    # delete demo data first
"""

import uuid
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Category, Product, ProductImage, ProductVariant

# Fixed id so every demo product belongs to the same demo seller across runs.
DEMO_SELLER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")

CATEGORIES = {
    "Electronics": ["Mobiles", "Laptops", "Headphones"],
    "Fashion": ["Men's clothing", "Women's clothing", "Footwear"],
    "Home": ["Kitchen", "Furniture"],
}

PRODUCTS = [
    # (category, name, brand, description, [(colour, size, price, compare_at)])
    ("Mobiles", "Nova X1 Smartphone", "Nova", "6.5-inch OLED display, 128 GB storage, dual camera.",
     [("Black", "128GB", "399.00", "449.00"), ("Blue", "128GB", "399.00", "449.00"), ("Black", "256GB", "469.00", None)]),
    ("Mobiles", "Pixelon Lite", "Pixelon", "Compact phone with all-day battery.",
     [("White", "64GB", "199.00", "229.00"), ("Green", "64GB", "199.00", None)]),
    ("Laptops", "AeroBook 14", "Aero", "14-inch ultrabook, 16 GB RAM, 512 GB SSD.",
     [("Silver", "512GB", "849.00", "999.00"), ("Space Grey", "1TB", "1049.00", None)]),
    ("Laptops", "Forge Gaming 16", "Forge", "16-inch gaming laptop with a 165 Hz screen.",
     [("Black", "1TB", "1399.00", "1599.00")]),
    ("Headphones", "QuietWave ANC Headphones", "QuietWave", "Over-ear noise cancelling, 30-hour battery.",
     [("Black", "", "179.00", "229.00"), ("Beige", "", "179.00", "229.00")]),
    ("Headphones", "BudsGo Wireless Earbuds", "BudsGo", "True wireless earbuds with charging case.",
     [("White", "", "59.00", None), ("Black", "", "59.00", None)]),
    ("Men's clothing", "Classic Oxford Shirt", "Thread & Co", "100% cotton, regular fit.",
     [("White", "S", "29.99", None), ("White", "M", "29.99", None), ("White", "L", "29.99", None),
      ("Blue", "M", "29.99", "39.99"), ("Blue", "L", "29.99", "39.99")]),
    ("Men's clothing", "Everyday Crew T-Shirt", "Basics", "Soft organic cotton tee.",
     [("Black", "M", "12.00", None), ("Grey", "M", "12.00", None), ("Grey", "L", "12.00", None)]),
    ("Women's clothing", "Linen Summer Dress", "Meadow", "Lightweight linen, midi length.",
     [("Sage", "S", "49.00", "65.00"), ("Sage", "M", "49.00", "65.00"), ("Sand", "M", "49.00", None)]),
    ("Footwear", "Stride Running Shoes", "Stride", "Cushioned trainers for road running.",
     [("Black", "8", "74.99", "89.99"), ("Black", "9", "74.99", "89.99"), ("White", "9", "74.99", None)]),
    ("Kitchen", "Brew Master Coffee Machine", "Brew", "Bean-to-cup with milk frother.",
     [("Black", "", "289.00", "349.00")]),
    ("Furniture", "Nordic Oak Desk", "Nordic", "Solid oak desk, 140 x 70 cm.",
     [("Oak", "140cm", "229.00", None), ("Walnut", "140cm", "259.00", None)]),
]


class Command(BaseCommand):
    help = "Create demo categories and products for local development."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete existing demo products first")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            deleted, _ = Product.objects.filter(seller_id=DEMO_SELLER_ID).delete()
            self.stdout.write(f"Deleted {deleted} demo rows")

        categories = {}
        for position, (parent_name, children) in enumerate(CATEGORIES.items()):
            parent, _ = Category.objects.get_or_create(name=parent_name, parent=None, defaults={"position": position})
            categories[parent_name] = parent
            for child_position, child_name in enumerate(children):
                child, _ = Category.objects.get_or_create(
                    name=child_name, parent=parent, defaults={"position": child_position}
                )
                categories[child_name] = child

        created = 0
        for category_name, name, brand, description, variants in PRODUCTS:
            if Product.objects.filter(seller_id=DEMO_SELLER_ID, name=name).exists():
                continue
            product = Product.objects.create(
                seller_id=DEMO_SELLER_ID,
                category=categories[category_name],
                name=name,
                brand=brand,
                description=description,
                status=Product.Status.ACTIVE,
            )
            for colour, size, price, compare_at in variants:
                sku_parts = [brand[:4], name.split()[0][:4], colour[:3], size]
                ProductVariant.objects.create(
                    product=product,
                    sku="-".join(p for p in sku_parts if p).upper().replace(" ", "")
                    + f"-{uuid.uuid4().hex[:4].upper()}",
                    colour=colour,
                    size=size,
                    price=Decimal(price),
                    compare_at_price=Decimal(compare_at) if compare_at else None,
                )
            ProductImage.objects.create(
                product=product,
                url=f"https://placehold.co/600x600?text={name.replace(' ', '+')}",
                alt_text=name,
            )
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Catalogue ready: {Category.objects.count()} categories, {created} new products"
        ))
