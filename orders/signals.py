# orders/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import OrderItem
from wallet.services import credit


@receiver(post_save, sender=OrderItem)
def refund_on_item_update(sender, instance: OrderItem, created, **kwargs):
    """
    Auto-refund when item is cancelled or returned
    Uses proportional refund based on actual amount paid
    """
    if created:
        return
    
    if instance.status not in [OrderItem.ItemStatus.CANCELLED, OrderItem.ItemStatus.RETURNED]:
        return
    
    user = instance.order.user
    
    # ✅ FIXED: Use proportional refund amount
    amount = instance.order.calculate_item_refund(instance)
    
    idem = f"refund:order_item:{instance.id}"
    note = f"Refund for {instance.product_name} (Order {instance.order.order_number})"
    
    credit(user, amount, description=note, reference=str(instance.order.id), idem_key=idem)
    