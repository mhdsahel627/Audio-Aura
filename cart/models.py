# carts/models.py
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from products.models import Product, ProductVariant

class Cart(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="cart")

    # NEW cached totals for fast checkout rendering
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    shipping_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    addons_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    updated_at = models.DateTimeField(auto_now=True)

    def recompute_totals(self, coupon_pct: Decimal = Decimal('0')):
        """
        Recompute cached totals from CartItem rows.
        coupon_pct is a percentage like Decimal('10') for 10%.
        """
        subtotal = addons = tax = Decimal('0.00')

        items = self.items.select_related('product')
        for ci in items:
            ci.reprice(coupon_pct=coupon_pct, save=True)
            subtotal += ci.line_subtotal
            addons += ci.line_addons
            tax += ci.line_tax

        self.discount_total = Decimal('0.00')  # plug coupon calculation if not pure percent
        self.subtotal = subtotal
        self.addons_total = addons
        self.tax_total = tax
        self.shipping_total = Decimal('0.00')  # compute later if you add slabs
        self.grand_total = self.subtotal + self.addons_total + self.tax_total + self.shipping_total - self.discount_total
        self.save(update_fields=['subtotal','addons_total','tax_total','shipping_total','discount_total','grand_total','updated_at'])
        return self

class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)

    # NEW persisted pricing fields for this line
    unit_price_at_add = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    addon_fee_per_item = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    # NEW computed/cached line fields for fast rendering
    line_subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    line_addons = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    line_tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        unique_together = [("cart", "product", "variant")]

    # Prefer variant image; fallback to product image
    @property
    def image_url(self):
        if self.variant:
            vimg = self.variant.images.order_by("-featured", "id").first()
            if vimg:
                return vimg.image.url
        pimg = self.product.images.order_by("-featured", "id").first()
        return pimg.image.url if pimg else ""

    def effective_unit_price(self, coupon_pct: Decimal = Decimal('0')):
        # Uses your Product.get_final_price()
        return self.product.get_final_price(coupon_discount_percent=coupon_pct)

    def reprice(self, coupon_pct: Decimal = Decimal('0'), save: bool = False):
        # Recompute this line deterministically
        unit_price = self.effective_unit_price(coupon_pct=coupon_pct)
        self.unit_price_at_add = unit_price
        self.line_subtotal = unit_price * self.quantity
        self.line_addons = (self.addon_fee_per_item or Decimal('0.00')) * self.quantity
        self.line_tax = Decimal('0.00')  # plug in GST logic later
        if save:
            self.save(update_fields=['unit_price_at_add','line_subtotal','line_addons','line_tax'])
        return self
