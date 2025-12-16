# coupons/services.py

from django.db import transaction
from django.db.models import F


def complete_coupon_usage(user, coupon, order):
    """
    Mark coupon as used by this user and increment global usage count.
    Must be called AFTER successful payment.
    
    Args:
        user: User who used the coupon
        coupon: Coupon object that was applied
        order: Order object that was created
    """
    from coupons.models import CouponUsage, Coupon
    
    with transaction.atomic():
        # Create usage record (prevents reuse by same user)
        CouponUsage.objects.get_or_create(
            user=user,
            coupon=coupon,
            defaults={'order': order}
        )
        
        # Atomic increment using F expression (thread-safe)
        Coupon.objects.filter(id=coupon.id).update(
            used_count=F('used_count') + 1
        )
        
        # Refresh to get updated count
        coupon.refresh_from_db()
        
        # Auto-deactivate if limit reached
        if coupon.used_count >= coupon.limit:
            coupon.is_active = False
            coupon.save(update_fields=['is_active'])
