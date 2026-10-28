import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.text import slugify


def unique_slug(name):
    """Readable slug with a short random suffix, so two products can share a name."""
    base = slugify(name)[:200] or "item"
    return f"{base}-{uuid.uuid4().hex[:6]}"


class Category(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "name"]
        verbose_name_plural = "categories"
        constraints = [
            models.UniqueConstraint(fields=["parent", "name"], name="unique_category_name_per_parent"),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:140]
        super().save(*args, **kwargs)

    def descendant_ids(self):
        """This category's id plus the ids of every category below it."""
        ids, frontier = [self.id], [self.id]
        while frontier:
            frontier = list(Category.objects.filter(parent_id__in=frontier).values_list("id", flat=True))
            ids.extend(frontier)
        return ids


class ProductQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status=Product.Status.ACTIVE, category__is_active=True)

    def with_listing_data(self):
        """Everything a product card needs, in a fixed number of queries (no N+1)."""
        return (
            self.select_related("category")
            .prefetch_related("images", "variants")
            .annotate(min_price=models.Min("variants__price", filter=models.Q(variants__is_active=True)))
        )


class Product(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # The seller lives in the users service; we keep only their id (database per service).
    seller_id = models.UUIDField(db_index=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    brand = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "category"]),
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["brand"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self.name)
        super().save(*args, **kwargs)


class ProductVariant(models.Model):
    """A buyable version of a product, e.g. 'Blue, M'. Prices live here, not on the product.
    Stock levels belong to the inventory service, keyed by SKU."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    sku = models.CharField(max_length=64, unique=True)
    colour = models.CharField(max_length=50, blank=True)
    size = models.CharField(max_length=20, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    # Optional "was" price shown crossed out next to the real price.
    compare_at_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["price", "created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(price__gt=0), name="variant_price_positive"),
            models.CheckConstraint(
                condition=models.Q(compare_at_price__isnull=True) | models.Q(compare_at_price__gte=models.F("price")),
                name="compare_at_price_not_below_price",
            ),
            models.UniqueConstraint(fields=["product", "colour", "size"], name="unique_variant_options"),
        ]

    def __str__(self):
        options = " / ".join(filter(None, [self.colour, self.size]))
        return f"{self.product.name} ({options})" if options else self.product.name


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    # Images are stored in object storage (S3 or similar); only the URL is kept here.
    url = models.URLField(max_length=500)
    alt_text = models.CharField(max_length=200, blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.url
