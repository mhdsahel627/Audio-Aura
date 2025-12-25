# orders/models.py

from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta, date
from decimal import Decimal


class Order(models.Model):
    PM_CHOICES = [
        ('COD', 'Cash on Delivery'),
        ('razorpay', 'Razorpay'),  # ✅ ADD THIS (used in payment flow)
        ('CARD', 'Card'),
        ('UPI', 'UPI'),
        ('NET', 'Netbanking'),
        ('WALLET', 'Wallet'),
    ]
    ST_CHOICES = [
        ('PLACED', 'Placed'),
        ('CONFIRMED', 'Confirmed'),
        ('SHIPPED', 'Shipped'),
        ('DELIVERED', 'Delivered'),
        ('CANCELLED', 'Cancelled'),
        ('RETURN_REQUESTED', 'Return Requested'),
        ('RETURN_APPROVED', 'Return Approved'),
        ('RETURNED', 'Returned'),
        ('PENDING', 'Pending'),  # ✅ ADD THIS (for unpaid Razorpay orders)
        ('FAILED', 'Failed'),    # ✅ ADD THIS (for failed payments)
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders')
    order_number = models.CharField(max_length=24, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    # Status timestamps
    processing_at = models.DateTimeField(null=True, blank=True)
    packed_at = models.DateTimeField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    payment_method = models.CharField(max_length=8, choices=PM_CHOICES, default='COD')
    status = models.CharField(max_length=25, choices=ST_CHOICES, default='PLACED')

    # ✅ ADD THESE RAZORPAY FIELDS
    razorpay_order_id = models.CharField(
        max_length=100, 
        blank=True, 
        null=True,
        help_text="Razorpay Order ID for tracking"
    )
    razorpay_payment_id = models.CharField(
        max_length=100, 
        blank=True, 
        null=True,
        help_text="Razorpay Payment ID for refunds"
    )
    razorpay_signature = models.CharField(
        max_length=255, 
        blank=True, 
        null=True,
        help_text="Razorpay signature for verification"
    )

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Snapshot address fields
    ship_full_name = models.CharField(max_length=120)
    ship_phone = models.CharField(max_length=32, blank=True)
    ship_line1 = models.CharField(max_length=180)
    ship_line2 = models.CharField(max_length=180, blank=True)
    ship_city = models.CharField(max_length=120)
    ship_state = models.CharField(max_length=120, blank=True)
    ship_postcode = models.CharField(max_length=20, blank=True)
    ship_country = models.CharField(max_length=90, default='India')

    # Delivery fields
    delivery_days = models.IntegerField(default=5)
    expected_delivery_date = models.DateField(null=True, blank=True)
    delay_notified = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.order_number} - {self.user}'
    
    # ✅ NEW: Check if order is delayed
    def is_delayed(self):
        """Check if order delivery is delayed"""
        if self.status not in ['DELIVERED', 'CANCELLED', 'RETURNED']:
            if self.expected_delivery_date and self.expected_delivery_date < date.today():
                return True
        return False
    
    # ✅ NEW: Auto-extend delivery date if delayed
    def auto_extend_delivery_date(self, days=3):
        """Automatically extend delivery date by specified days"""
        if self.is_delayed() and self.status in ['PLACED', 'CONFIRMED', 'SHIPPED']:
            self.expected_delivery_date = date.today() + timedelta(days=days)
            self.delay_notified = False
            self.save(update_fields=['expected_delivery_date', 'delay_notified'])
            return True
        return False
    
    # ✅ NEW: Calculate delivery date with auto-extension
    def calculate_delivery_date(self):
        """Calculate expected delivery date (auto-extends if delayed)"""
        # If already delivered
        if self.status == 'DELIVERED' and self.delivered_at:
            return self.delivered_at.date()
        
        # If cancelled/returned
        if self.status in ['CANCELLED', 'RETURNED']:
            return None
        
        # Check if delayed and auto-extend
        if self.is_delayed():
            self.auto_extend_delivery_date(days=3)
        
        # Return current expected date
        if self.expected_delivery_date:
            return self.expected_delivery_date
        
        # Fallback: calculate from order creation
        if self.created_at:
            return self.created_at.date() + timedelta(days=self.delivery_days)
        
        return None
    
    # ✅ NEW: Get formatted delivery date
    def get_delivery_date_formatted(self):
        """Get formatted delivery date like 'Friday, 29 November'"""
        delivery_date = self.calculate_delivery_date()
        if delivery_date:
            return delivery_date.strftime('%A, %d %B')
        return "To be confirmed"
    
    # ✅ NEW: Get delivery status text
    def get_delivery_status_text(self):
        """Get delivery status text for display"""
        if self.status == 'DELIVERED':
            return f"Delivered on {self.delivered_at.strftime('%d %B %Y') if self.delivered_at else 'N/A'}"
        elif self.status == 'CANCELLED':
            return "Order Cancelled"
        elif self.is_delayed():
            return f"Expected by {self.get_delivery_date_formatted()} (Delayed)"
        else:
            return f"Expected by {self.get_delivery_date_formatted()}"
    
    def calculate_item_refund(self, item):
        """
        Calculate the actual refund amount for an item (proportional to what user paid)
        Accounts for discounts, coupons, etc.
        
        Example:
        Order Subtotal: ₹20,000 (Item A: ₹13,000 + Item B: ₹7,000)
        Coupon Discount: -₹2,000
        User Paid: ₹18,000
        
        If Item A cancelled:
        - Item A proportion: ₹13,000 / ₹20,000 = 0.65
        - Item A refund: ₹18,000 × 0.65 = ₹11,700 ✅
        """
        # If no items or invalid subtotal, can't calculate
        if self.subtotal <= 0:
            return Decimal('0.00')
        
        # Item's original line total (before order-level discounts)
        item_line_total = item.line_total
        
        # Calculate item's proportion of the order subtotal
        item_proportion = item_line_total / self.subtotal
        
        # Total amount actually paid by user (after all discounts)
        amount_paid = self.total_amount
        
        # Proportional refund for this item
        refund_amount = amount_paid * item_proportion
        
        return refund_amount.quantize(Decimal('0.01'))
    
    def get_remaining_order_value(self):
        """
        Calculate the remaining order value after cancelled/returned items
        Useful for order summary updates
        """
        active_items = self.items.exclude(
            status__in=['CANCELLED', 'RETURNED']
        )
        
        if not active_items.exists():
            return Decimal('0.00')
        
        # Sum of active items' refund amounts
        total_active = sum(
            self.calculate_item_refund(item) 
            for item in active_items
        )
        
        return total_active.quantize(Decimal('0.01'))

class OrderItem(models.Model):
    class ItemStatus(models.TextChoices):
        PLACED = "PLACED", "Placed"
        CONFIRMED = "CONFIRMED", "Confirmed"
        SHIPPED = "SHIPPED", "Shipped"
        DELIVERED = "DELIVERED", "Delivered"
        CANCELLED = "CANCELLED", "Cancelled"
        RETURNED = "RETURNED", "Returned"
    
    class CancellationReason(models.TextChoices):
        ORDER_BY_MISTAKE = "ORDER_BY_MISTAKE", "Ordered by mistake"
        FOUND_CHEAPER = "FOUND_CHEAPER", "Found cheaper elsewhere"
        DELIVERY_TOO_LATE = "DELIVERY_TOO_LATE", "Delivery taking too long"
        CHANGED_MIND = "CHANGED_MIND", "Changed my mind"
        ORDERED_WRONG_ITEM = "ORDERED_WRONG_ITEM", "Ordered wrong item"
        DUPLICATE_ORDER = "DUPLICATE_ORDER", "Duplicate order"
        OTHER = "OTHER", "Other reason"
    
    class RefundStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PROCESSING = 'PROCESSING', 'Processing'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'
    
    order = models.ForeignKey("Order", on_delete=models.CASCADE, related_name="items")
    
    # ✅ SNAPSHOT FIELDS - Store product/variant info at time of order
    product_id = models.PositiveIntegerField()
    
    # ✅ Store which variant was purchased
    variant_id = models.PositiveIntegerField(
        null=True, 
        blank=True,
        help_text="ID of the specific variant purchased (if applicable)"
    )
    
    product_name = models.CharField(max_length=240)
    image_url = models.URLField(blank=True)

    offer_label = models.CharField(max_length=120, blank=True)
    variant_color = models.CharField(max_length=60, blank=True)
    mrp_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    status = models.CharField(
        max_length=12,
        choices=ItemStatus.choices,
        default=ItemStatus.PLACED,
    )

    # Status timestamps
    placed_at = models.DateTimeField(null=True, blank=True)
    processing_at = models.DateTimeField(null=True, blank=True)
    packed_at = models.DateTimeField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    out_for_delivery_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    
    # Cancellation fields
    cancelled_at = models.DateTimeField(blank=True, null=True)
    cancellation_reason = models.CharField(
        max_length=50,
        choices=CancellationReason.choices,
        blank=True,
        null=True
    )
    cancellation_note = models.TextField(blank=True, null=True, max_length=500)
    
    # Return fields
    returned_at = models.DateTimeField(blank=True, null=True)
    return_reason = models.TextField(blank=True, null=True)

    # ✅ REFUND TRACKING FIELDS - Prevents double refund
    refund_status = models.CharField(
        max_length=20, 
        choices=RefundStatus.choices,
        null=True, 
        blank=True,
        help_text="Refund processing status"
    )
    refund_amount = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Amount refunded for this item"
    )
    refund_method = models.CharField(
        max_length=20, 
        null=True, 
        blank=True,
        help_text="Refund method: razorpay, wallet, store_credit"
    )
    refund_id = models.CharField(
        max_length=100, 
        null=True, 
        blank=True,
        help_text="Razorpay refund ID (if applicable)"
    )
    refund_processed_at = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="When refund was completed"
    )

    # ✅ Return policy constant
    RETURN_WINDOW_DAYS = 10

    def mark_returned(self, reason: str = ""):
        """Mark item as returned with reason"""
        self.status = self.ItemStatus.RETURNED
        if reason:
            self.return_reason = reason[:1000]
        self.returned_at = timezone.now()
        self.save(update_fields=["status", "return_reason", "returned_at"])

    # ✅ Return eligibility check
    def is_return_eligible(self):
        """
        Check if item is eligible for return (within 10 days of delivery)
        Returns: (is_eligible: bool, reason: str)
        """
        # Must be delivered
        if self.status != self.ItemStatus.DELIVERED:
            return False, "Only delivered items can be returned"
        
        # Must have delivery date
        if not self.delivered_at:
            return False, "Delivery date not found"
        
        # Check if already returned
        if self.status == self.ItemStatus.RETURNED:
            return False, "Item already returned"
        
        # Check if return request pending
        if hasattr(self, 'action_requests'):
            pending_return = self.action_requests.filter(
                kind='RETURN', 
                state='PENDING'
            ).exists()
            if pending_return:
                return False, "Return request already pending"
        
        # ✅ Check 10-day window from delivery
        now = timezone.now()
        days_since_delivery = (now - self.delivered_at).days
        
        if days_since_delivery > self.RETURN_WINDOW_DAYS:
            return False, f"Return period expired (allowed within {self.RETURN_WINDOW_DAYS} days of delivery)"
        
        # Calculate remaining days
        days_remaining = self.RETURN_WINDOW_DAYS - days_since_delivery
        if days_remaining < 0:
            days_remaining = 0
        
        return True, f"{days_remaining} day{'s' if days_remaining != 1 else ''} left to return"

    # ✅ Get return deadline date
    def get_return_deadline(self):
        """
        Get the last date to return this item
        Returns: datetime or None
        """
        if self.delivered_at:
            return self.delivered_at + timedelta(days=self.RETURN_WINDOW_DAYS)
        return None

    # ✅ Check if return period has expired
    def is_return_period_expired(self):
        """
        Check if the 10-day return window has passed
        Returns: bool
        """
        if not self.delivered_at:
            return False
        
        deadline = self.get_return_deadline()
        if deadline:
            return timezone.now() > deadline
        
        return False

    # ✅ Get days remaining for return
    def get_days_until_return_expires(self):
        """
        Get number of days remaining in return window
        Returns: int (0 if expired or not delivered)
        """
        if not self.delivered_at or self.status != self.ItemStatus.DELIVERED:
            return 0
        
        deadline = self.get_return_deadline()
        if deadline:
            days_left = (deadline - timezone.now()).days
            return max(0, days_left)  # Don't return negative
        
        return 0

    def __str__(self):
        return f"{self.product_name} x {self.quantity}"



class ActionRequest(models.Model):
    class Kind(models.TextChoices):
        CANCEL = "CANCEL", "Cancel"
        RETURN = "RETURN", "Return"

    class State(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="action_requests")
    item = models.ForeignKey(OrderItem, on_delete=models.CASCADE, related_name="action_requests")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    reason = models.TextField(blank=True, null=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.PENDING)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="order_action_requests")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, blank=True, null=True, related_name="order_action_decisions")
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["state", "kind"]),
            models.Index(fields=["order", "item"]),
        ]
        unique_together = [("item", "state", "kind")]  # prevent multiple open requests of same kind per item


class Refund(models.Model):
    """Track all refunds for auditing and reconciliation"""
    
    class RefundStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'
    
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='refunds')
    order_item = models.ForeignKey(OrderItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='refunds')
    
    refund_type = models.CharField(
        max_length=20,
        choices=[
            ('ITEM', 'Item Refund'),
            ('SHIPPING', 'Shipping Refund'),
            ('DISCOUNT', 'Discount Adjustment'),
        ],
        default='ITEM'
    )
    
    original_amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Original item/line total")
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Actual refund amount (after proportional calculation)")
    
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=RefundStatus.choices, default=RefundStatus.PENDING)
    
    # Wallet transaction reference
    wallet_transaction_id = models.CharField(max_length=100, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order', 'status']),
            models.Index(fields=['order_item']),
        ]
    
    def __str__(self):
        return f"Refund ₹{self.refund_amount} for {self.order.order_number}"
