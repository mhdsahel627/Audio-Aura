# coupons/models.py
from django.db import models
from django.utils import timezone
from django.conf import settings
from decimal import Decimal


class Coupon(models.Model):
    code = models.CharField(max_length=32, unique=True)
    title = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True, null=True) 
    discount = models.DecimalField(max_digits=6, decimal_places=2)
    coupon_type = models.CharField(max_length=10, choices=(('percent', 'Percent'), ('flat', 'Flat amount')))
    
    # Date validity
    start_date = models.DateField(default=timezone.now, help_text="Date when coupon becomes active")
    expiry_date = models.DateField(help_text="Date when coupon expires")
    
    # Purchase limits
    min_purchase = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Minimum cart value")
    max_purchase = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Maximum cart value (0 = no limit)") 
    max_redeemable = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Max discount amount (for % coupons)")
    
    # Usage limits
    limit = models.PositiveIntegerField(default=1, help_text="Total usage limit (all users)")
    per_user_limit = models.PositiveIntegerField(default=1, help_text="How many times each user can use")
    used_count = models.IntegerField(default=0, help_text="Number of times used globally")
    
    # Conditions
    min_items = models.IntegerField(default=0, help_text="Minimum items required (0 = no minimum)")
    first_time_only = models.BooleanField(default=False, help_text="Only for first-time buyers")
    exclude_discounted = models.BooleanField(default=False, help_text="Exclude already discounted products")
    
    # Display
    is_active = models.BooleanField(default=True)
    badge = models.CharField(max_length=50, blank=True, null=True, help_text="e.g., 'Most Popular', 'Best Value'")
    display_order = models.IntegerField(default=0, help_text="Lower number = higher priority")
    
    class Meta:
        ordering = ['display_order', '-discount']
    
    def __str__(self):
        return f"{self.code} - {self.discount}{'%' if self.coupon_type == 'percent' else '₹'} off"
    
    def is_valid(self):
        """Check if coupon is currently valid (basic checks)"""
        from datetime import date
        today = date.today()
        
        if not self.is_active:
            return False, "Coupon is inactive"
        
        if today < self.start_date:
            return False, "Coupon is not yet active"
        
        if today > self.expiry_date:
            return False, "Coupon has expired"
        
        if self.used_count >= self.limit:
            return False, "Coupon usage limit reached"
        
        return True, "Valid"
    
    def check_user_eligibility(self, user):
        """Check if THIS specific user can use this coupon"""
        # Check if first-time only
        if self.first_time_only:
            from orders.models import Order
            has_previous_orders = Order.objects.filter(
                user=user, 
                status__in=['PLACED', 'SHIPPED', 'DELIVERED']
            ).exists()
            
            if has_previous_orders:
                return False, "This coupon is only for first-time buyers"
        
        # Check per-user usage limit
        user_usage_count = CouponUsage.objects.filter(
            user=user, 
            coupon=self
        ).count()
        
        if user_usage_count >= self.per_user_limit:
            return False, f"You have already used this coupon {self.per_user_limit} time(s)"
        
        return True, "Eligible"
    
    def check_cart_eligibility(self, cart_items_count, cart_total, cart_items=None):
        """Check if cart meets coupon conditions"""
        # Check minimum items
        if self.min_items > 0 and cart_items_count < self.min_items:
            return False, f"Add {self.min_items - cart_items_count} more item(s) to use this coupon"
        
        # Check minimum purchase
        if cart_total < self.min_purchase:
            remaining = self.min_purchase - cart_total
            return False, f"Add ₹{remaining:.0f} more to cart to use this coupon"
        
        # Check maximum purchase
        if self.max_purchase > 0 and cart_total > self.max_purchase:
            excess = cart_total - self.max_purchase
            return False, f"Cart value exceeds ₹{self.max_purchase:.0f}. Remove ₹{excess:.0f} worth items"
        
        # Check if discounted products excluded
        if self.exclude_discounted and cart_items:
            has_discounted = any(
                item.get('has_discount', False) for item in cart_items
            )
            if has_discounted:
                return False, "This coupon cannot be applied to discounted products"
        
        return True, "Cart eligible"
    
    # Keep your existing check_eligibility for backward compatibility
    def check_eligibility(self, cart_items_count, cart_total):
        """Legacy method - calls check_cart_eligibility"""
        return self.check_cart_eligibility(cart_items_count, cart_total)
    
    def calculate_discount(self, cart_total):
        """Calculate discount amount"""
        if self.coupon_type == 'percent':
            discount = (cart_total * self.discount) / 100
            if self.max_redeemable > 0:
                discount = min(discount, self.max_redeemable)
        else:
            discount = self.discount
        
        return min(discount, cart_total)  # Can't discount more than cart total


class CouponUsage(models.Model):
    """Track per-user coupon usage"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    coupon = models.ForeignKey('Coupon', on_delete=models.CASCADE, related_name='usage_records')
    order = models.ForeignKey('orders.Order', on_delete=models.SET_NULL, null=True, blank=True)
    used_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-used_at']
        indexes = [
            models.Index(fields=['user', 'coupon']),
        ]
    
    def __str__(self):
        return f"{self.user.username} used {self.coupon.code}"

class DeliveryPincode(models.Model):
    """Store serviceable pincodes"""
    pincode = models.CharField(max_length=6, unique=True, db_index=True)
    city = models.CharField(max_length=100, db_index=True)  # Office name (Chettippedi)
    district = models.CharField(max_length=100, blank=True)  # ← NEW: District (MALAPPURAM)
    state = models.CharField(max_length=100, db_index=True)
    delivery_days = models.IntegerField(default=5, help_text="Expected delivery days")
    is_cod_available = models.BooleanField(default=True)
    is_serviceable = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Delivery Pincode"
        verbose_name_plural = "Delivery Pincodes"
        indexes = [
            models.Index(fields=['pincode', 'is_serviceable']),
        ]
    
    def __str__(self):
        return f"{self.pincode} - {self.city}, {self.state}"