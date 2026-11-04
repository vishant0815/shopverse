import django_filters
from django.db.models import Exists, F, OuterRef, Q

from .models import Category, Product, ProductVariant


class ProductFilter(django_filters.FilterSet):
    category = django_filters.CharFilter(method="filter_category", help_text="Category slug; includes subcategories")
    brand = django_filters.CharFilter(method="filter_brand", help_text="One brand or a comma-separated list")
    min_price = django_filters.NumberFilter(field_name="min_price", lookup_expr="gte")
    max_price = django_filters.NumberFilter(field_name="min_price", lookup_expr="lte")
    colour = django_filters.CharFilter(method="filter_variant_option")
    size = django_filters.CharFilter(method="filter_variant_option")
    seller = django_filters.UUIDFilter(field_name="seller_id")
    on_sale = django_filters.BooleanFilter(method="filter_on_sale", help_text="Only products with a discounted variant")
    # Only useful on the seller endpoints: the public catalogue only ever contains published products.
    status = django_filters.ChoiceFilter(choices=Product.Status.choices)

    class Meta:
        model = Product
        fields = ["category", "brand", "min_price", "max_price", "colour", "size", "seller", "on_sale", "status"]

    def filter_on_sale(self, queryset, name, value):
        discounted = ProductVariant.objects.filter(
            product=OuterRef("pk"), is_active=True, compare_at_price__gt=F("price")
        )
        return queryset.filter(Exists(discounted)) if value else queryset.exclude(Exists(discounted))

    def filter_category(self, queryset, name, value):
        category = Category.objects.filter(slug=value).first()
        if category is None:
            return queryset.none()
        return queryset.filter(category_id__in=category.descendant_ids())

    def filter_brand(self, queryset, name, value):
        query = Q()
        for brand in (b.strip() for b in value.split(",")):
            if brand:
                query |= Q(brand__iexact=brand)
        return queryset.filter(query)

    def filter_variant_option(self, queryset, name, value):
        # EXISTS subquery instead of a join, so a product with several matching
        # variants still appears once and the price annotation stays correct.
        matching = ProductVariant.objects.filter(
            product=OuterRef("pk"), is_active=True, **{f"{name}__iexact": value}
        )
        return queryset.filter(Exists(matching))
