from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import ProductVariant

@receiver(post_save, sender=ProductVariant)
def ensure_single_default(sender, instance, created, **kwargs):
    # If no variant for this product is default, mark this one as default.
    if not instance.product.variants.filter(is_default=True).exclude(id=instance.id).exists():
        if not instance.is_default:
            ProductVariant.objects.filter(id=instance.id).update(is_default=True)
            return
    # If this was set default=True, demote others.
    if instance.is_default:
        ProductVariant.objects.filter(product=instance.product).exclude(id=instance.id).update(is_default=False)
