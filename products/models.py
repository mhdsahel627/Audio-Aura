# products/models.py

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django.db import models
from django.utils.text import slugify
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from PIL import Image
from datetime import date
from django.contrib.auth.models import User
from django.db.models import Q


class Product(models.Model):
    # Basic Info
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    short_description = models.CharField(max_length=500, blank=True, null=True)
    long_description = models.TextField(blank=True, null=True)
    
    brand = models.ForeignKey('category.Brand', on_delete=models.SET_NULL, blank=True, null=True)
    category = models.ForeignKey('category.Category', on_delete=models.CASCADE, related_name="products")

    # Pricing
    base_price = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))]
    )
    discount_price = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True,
        validators=[MinValueValidator(Decimal("0.00"))]
    )
    offer = models.CharField(max_length=255, blank=True, null=True)

    # Stock
    stock_quantity = models.PositiveIntegerField(default=0)
    
    # ✅ Low stock threshold for alerts
    low_stock_threshold = models.PositiveIntegerField(
        default=5, 
        help_text="Alert when stock falls below this number"
    )

    # Video
    video = models.URLField(blank=True, null=True)

    is_listed = models.BooleanField(default=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_listed"]),
            models.Index(fields=["-created_at"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:200]
            slug = base
            idx = 1
            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{idx}"
                idx += 1
            self.slug = slug
        if self.discount_price is not None and self.discount_price >= self.base_price:
            raise ValidationError("Discount price must be less than base price.")
        super().save(*args, **kwargs)

    # ✅ Stock management properties
    @property
    def is_in_stock(self):
        """Check if product has any stock available"""
        return self.stock_quantity > 0
    
    @property
    def is_low_stock(self):
        """Check if stock is below threshold (but not zero)"""
        return 0 < self.stock_quantity <= self.low_stock_threshold
    
    @property
    def stock_status(self):
        """Get human-readable stock status"""
        if self.stock_quantity == 0:
            return "Out of Stock"
        elif self.is_low_stock:
            return f"Only {self.stock_quantity} left"
        else:
            return "In Stock"
    
    # ✅ Stock management methods (for products WITHOUT variants)
    def reserve_stock(self, quantity):
        """
        Reserve stock when order is placed (BOTH COD and Online payment)
        Raises ValidationError if insufficient stock
        """
        if self.stock_quantity < quantity:
            raise ValidationError(
                f"Insufficient stock for {self.name}. Only {self.stock_quantity} available."
            )
        self.stock_quantity -= quantity
        self.save(update_fields=['stock_quantity'])
    
    def release_stock(self, quantity):
        """
        Release stock when order is cancelled/returned
        """
        self.stock_quantity += quantity
        self.save(update_fields=['stock_quantity'])

    def get_base_selling_price(self):
        # Always use discount_price if set, else fallback to base_price
        return self.discount_price if self.discount_price is not None else self.base_price

    def get_best_discount(self):
        today = date.today()
        prod_offer = self.offers.filter(start_date__lte=today, end_date__gte=today).order_by('-start_date').first()
        prod_discount = prod_offer.discount_percent if prod_offer and prod_offer.discount_percent else 0
        cat_offer = self.category.offers.filter(start_date__lte=today, end_date__gte=today).order_by('-start_date').first()
        cat_discount = cat_offer.discount_percent if cat_offer and cat_offer.discount_percent else 0
        return max(prod_discount, cat_discount)

    from decimal import Decimal, ROUND_HALF_UP

    def get_final_price(self, coupon_discount_percent=0):
        """Calculate final price with all discounts - rounded to nearest rupee"""
        base_selling = self.get_base_selling_price()
        best_discount = self.get_best_discount()
        
        # Apply product/category offer
        discounted_price = base_selling - (base_selling * best_discount / Decimal('100'))
        
        # Apply coupon percentage
        if coupon_discount_percent > 0:
            coupon_discount_percent = Decimal(str(coupon_discount_percent))
            discounted_price -= (discounted_price * coupon_discount_percent / Decimal('100'))
        
        # ✅ Round to nearest whole rupee (999.60 → 1000.00)
        final = discounted_price.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        
        return max(final, Decimal('0.00'))



    def get_discount_percent(self):
        base_price = self.base_price
        final_price = self.get_final_price()
        try:
            percent = ((base_price - final_price) / base_price) * Decimal("100")
            return int(percent.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except (InvalidOperation, ZeroDivisionError):
            return 0

    def get_extra_off(self):
        """
        Returns the rupee difference between base selling price (discount_price if set, else base_price)
        and the final price after all applicable offers.
        """
        selling_price = self.get_base_selling_price()
        final_price = self.get_final_price()
        extra_off = selling_price - final_price
        return max(int(round(float(extra_off))), 0)

    def __str__(self):
        return self.name




class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    color = models.CharField(max_length=50)
    stock = models.PositiveIntegerField(default=0)
    is_default = models.BooleanField(default=False)

    class Meta:
        constraints = [
            # color uniqueness per product
            models.UniqueConstraint(fields=["product", "color"], name="unique_product_variant_color"),
            # at most one default variant per product
            models.UniqueConstraint(
                fields=["product"],
                condition=Q(is_default=True),
                name="unique_default_variant_per_product",
            ),
        ]

    def clean(self):
        if not self.color.strip():
            raise ValidationError("Color cannot be empty.")

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)

        # If this is marked default, demote others for the same product.
        if self.is_default:
            ProductVariant.objects.filter(product=self.product).exclude(pk=self.pk).update(is_default=False)
        else:
            # If no default exists for this product, make this one default (covers first-variant case).
            has_default = ProductVariant.objects.filter(product=self.product, is_default=True).exists()
            if not has_default:
                ProductVariant.objects.filter(pk=self.pk).update(is_default=True)

        # ✅ AUTO-SYNC: Product stock = sum of all variant stocks
        # This runs EVERY TIME a variant is saved!
        total_stock = self.product.variants.aggregate(total=models.Sum('stock'))['total'] or 0
        if total_stock != self.product.stock_quantity:
            self.product.stock_quantity = total_stock
            self.product.save(update_fields=['stock_quantity'])

    # ✅ FIXED: Only update variant stock, product syncs automatically
    def reserve_stock(self, quantity, user=None, reason="Stock reserved"):
        """
        Reserve variant stock - product total updates automatically via save()
        Raises ValidationError if insufficient stock
        """
        if self.stock < quantity:
            raise ValidationError(
                f"Insufficient stock for {self.product.name} - {self.color}. "
                f"Only {self.stock} available."
            )
        
        # Store before values for logging
        stock_before_variant = self.stock
        stock_before_product = self.product.stock_quantity
        
        # ✅ ONLY update variant stock
        self.stock -= quantity
        self.save(update_fields=['stock'])
        # ☝️ This triggers save() → auto-calculates product.stock_quantity
        
        # Refresh product to get the auto-updated stock
        self.product.refresh_from_db()
        
        return {
            'variant_before': stock_before_variant,
            'variant_after': self.stock,
            'product_before': stock_before_product,
            'product_after': self.product.stock_quantity  # Auto-updated value
        }
    
    def release_stock(self, quantity, user=None, reason="Stock released"):
        """
        Release variant stock - product total updates automatically via save()
        """
        # Store before values for logging
        stock_before_variant = self.stock
        stock_before_product = self.product.stock_quantity
        
        # ✅ ONLY update variant stock
        self.stock += quantity
        self.save(update_fields=['stock'])
        # ☝️ This triggers save() → auto-calculates product.stock_quantity
        
        # Refresh product to get the auto-updated stock
        self.product.refresh_from_db()
        
        return {
            'variant_before': stock_before_variant,
            'variant_after': self.stock,
            'product_before': stock_before_product,
            'product_after': self.product.stock_quantity  # Auto-updated value
        }

    # ✅ KEEP ONLY THIS ONE - Works with both cloud_url and image field
    @property
    def primary_image_url(self):
        """Get primary variant image URL"""
        imgs = getattr(self, "prefetched_images", None) or list(self.images.all()[:1])
        return imgs[0].image_url if imgs else '/static/images/placeholder.jpg'

    def __str__(self):
        return f"{self.product.name} - {self.color}"




class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="products/images/", blank=True, null=True)  
    cloud_url = models.URLField(blank=True, null=True)
    featured = models.BooleanField(default=False)
    public_id = models.CharField(max_length=255, blank=True) 
    
    class Meta:
        ordering = ["-featured", "id"]

    def save(self, *args, **kwargs):
        # Ensure only one featured image per product
        if self.featured:
            ProductImage.objects.filter(product=self.product, featured=True).exclude(pk=self.pk).update(featured=False)
        super().save(*args, **kwargs)

    # ✅ NEW: Property to get image URL from either source
    @property
    def image_url(self):
        """Get image URL from cloud_url or image field"""
        if self.cloud_url:
            return self.cloud_url
        if self.image:
            try:
                return self.image.url
            except ValueError:
                return '/static/images/placeholder.jpg'  # Fallback
        return '/static/images/placeholder.jpg'

    def __str__(self):
        return f"{self.product.name} - Image"



class ProductVariantImage(models.Model):
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="products/variants/", blank=True, null=True)  # ✅ Made nullable
    cloud_url = models.URLField(blank=True, null=True)
    featured = models.BooleanField(default=False) 
    public_id = models.CharField(max_length=255, blank=True) 
    
    class Meta:
        ordering = ["-featured", "id"]

    def save(self, *args, **kwargs):
        # Ensure only one featured image per variant
        if self.featured:
            ProductVariantImage.objects.filter(variant=self.variant, featured=True).exclude(pk=self.pk).update(featured=False)
        super().save(*args, **kwargs)

    # ✅ NEW: Property to get image URL from either source
    @property
    def image_url(self):
        """Get image URL from cloud_url or image field"""
        if self.cloud_url:
            return self.cloud_url
        if self.image:
            try:
                return self.image.url
            except ValueError:
                return '/static/images/placeholder.jpg'
        return '/static/images/placeholder.jpg'

    def __str__(self):
        return f"{self.variant.product.name} - {self.variant.color} - Image"



class ProductDetailedImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="detailed_images")
    image = models.ImageField(upload_to="products/detailed/", blank=True, null=True)  # ✅ Made nullable
    cloud_url = models.URLField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    public_id = models.CharField(max_length=255, blank=True)
    
    # ✅ NEW: Property to get image URL from either source
    @property
    def image_url(self):
        """Get image URL from cloud_url or image field"""
        if self.cloud_url:
            return self.cloud_url
        if self.image:
            try:
                return self.image.url
            except ValueError:
                return '/static/images/placeholder.jpg'
        return '/static/images/placeholder.jpg'
    
    def __str__(self):
        return f"Detailed Image for {self.product.name}"



class TemporaryUpload(models.Model):
    # file = models.ImageField(upload_to="staged/")  # ❌ not needed for direct Cloudinary
    owner = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    session_key = models.CharField(max_length=64, blank=True)
    list_key = models.CharField(max_length=64)  # "product", "detailed", f"variant_{idx}"
    cloud_url = models.URLField(blank=True, null=True)      # ✅ add
    public_id = models.CharField(max_length=255, blank=True)  # ✅ add
    created_at = models.DateTimeField(auto_now_add=True)



class ProductOffer(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='offers')
    title = models.CharField(max_length=100)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    discount_rs = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    is_extra = models.BooleanField(default=True)  # New field to mark extra offers


# ✅ UPDATED: Stock Transaction Log Model with Variant Support
class StockTransaction(models.Model):
    """
    Track all stock movements for audit trail (Amazon/Flipkart style)
    ✅ Now tracks BOTH product-level and variant-level transactions
    """
    
    class TransactionType(models.TextChoices):
        RESERVE = "RESERVE", "Stock Reserved (Order Placed)"
        RELEASE = "RELEASE", "Stock Released (Order Cancelled/Returned)"
        MANUAL_ADD = "MANUAL_ADD", "Manual Stock Addition"
        MANUAL_SUBTRACT = "MANUAL_SUBTRACT", "Manual Stock Subtraction"
        RESTOCK = "RESTOCK", "Restocked by Admin"
    
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='stock_transactions'
    )
    
    # ✅ NEW: Track which variant was involved (if applicable)
    variant = models.ForeignKey(
        ProductVariant, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='stock_transactions',
        help_text="Specific variant if transaction is variant-level"
    )
    
    order_item = models.ForeignKey(
        'orders.OrderItem', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        help_text="Related order item if applicable"
    )
    
    transaction_type = models.CharField(
        max_length=20, 
        choices=TransactionType.choices
    )
    quantity = models.IntegerField(
        help_text="Change in quantity (negative for reduction, positive for addition)"
    )
    
    stock_before = models.PositiveIntegerField()
    stock_after = models.PositiveIntegerField()
    
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    
    class Meta:
        db_table = 'stock_transactions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['product', '-created_at']),
            models.Index(fields=['variant', '-created_at']),  # ✅ NEW INDEX
            models.Index(fields=['transaction_type']),
        ]
    
    def __str__(self):
        variant_info = f" - {self.variant.color}" if self.variant else ""
        return f"{self.transaction_type} - {self.product.name}{variant_info} - Qty: {self.quantity} ({self.created_at.strftime('%d %b %Y')})"
