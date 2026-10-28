from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Category

CATEGORY_TREE_CACHE_KEY = "catalog:category-tree"


@receiver([post_save, post_delete], sender=Category)
def invalidate_category_tree(sender, **kwargs):
    # Categories change rarely but are read on every page, so the tree is cached
    # in Redis and thrown away whenever any category changes.
    cache.delete(CATEGORY_TREE_CACHE_KEY)
