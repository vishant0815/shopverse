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


def approved_seller_ids():
    """Subquery of the sellers whose shops are approved. Their products can be sold."""
    return SellerStatus.objects.filter(status=SellerStatus.Status.APPROVED).values("seller_id")


class ProductQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status=Product.Status.ACTIVE, category__is_active=True)

    def for_shoppers(self):
        """Published products in active categories, from sellers whose shop is approved."""
        return self.active().filter(seller_id__in=approved_seller_ids())

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
    # Kept in step with the visible reviews by reviews.refresh_rating; None until the first one.
    rating_average = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    rating_count = models.PositiveIntegerField(default=0)

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


class Review(models.Model):
    """A customer's review of a product. Only a verified buyer can write one, and only once per product.
    A hidden review stays in the database for admins; it counts neither towards the rating nor on the page."""

    class Status(models.TextChoices):
        VISIBLE = "visible", "Visible"
        HIDDEN = "hidden", "Hidden"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    # The customer lives in the users service; we keep only their id (database per service).
    user_id = models.UUIDField(db_index=True)
    rating = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=120)
    body = models.CharField(max_length=2000)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.VISIBLE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["product", "user_id"], name="one_review_per_customer_per_product"),
            models.CheckConstraint(condition=models.Q(rating__gte=1, rating__lte=5), name="review_rating_range"),
        ]
        indexes = [models.Index(fields=["product", "status", "-created_at"])]

    def __str__(self):
        return f"{self.rating} stars: {self.title}"


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


class ProductRevision(models.Model):
    """How many catalogue announcements this product has had. The search index uses it to
    ignore an announcement older than one it already applied (see catalog/events.py)."""

    product = models.OneToOneField(Product, primary_key=True, on_delete=models.CASCADE, related_name="revision_row")
    revision = models.PositiveBigIntegerField(default=0)

    class Meta:
        db_table = "product_revisions"


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


class SellerStatus(models.Model):
    """Whether a seller's shop is approved, as the users service announces it (SellerStatusChanged).

    Products keeps its own copy, so a seller's write only needs this service's database.
    A seller with no row is treated as not approved."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending approval"
        APPROVED = "approved", "Approved"
        SUSPENDED = "suspended", "Suspended"

    seller_id = models.UUIDField(primary_key=True, editable=False)
    status = models.CharField(max_length=20, choices=Status.choices)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.seller_id} ({self.status})"


class FlashSale(models.Model):
    """A time-boxed sale price on chosen variants. Admins create them; the window is stored in UTC."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at", "created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(ends_at__gt=models.F("starts_at")), name="flash_sale_ends_after_start"),
        ]

    def __str__(self):
        return self.name


class FlashSaleItem(models.Model):
    """One variant on sale. While its sale runs it sells at sale_price. A quantity_cap of None means
    no cap. Units sold are counted by the orders service from live orders, not stored here."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sale = models.ForeignKey(FlashSale, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name="flash_sale_items")
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    quantity_cap = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sale__starts_at", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["sale", "variant"], name="unique_flash_sale_variant"),
            models.CheckConstraint(condition=models.Q(sale_price__gt=0), name="flash_sale_price_positive"),
            models.CheckConstraint(
                condition=models.Q(quantity_cap__isnull=True) | models.Q(quantity_cap__gt=0),
                name="flash_sale_cap_positive",
            ),
        ]

    def __str__(self):
        return f"{self.variant} at {self.sale_price} in {self.sale}"
