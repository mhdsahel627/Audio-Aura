from django.contrib import admin
from .models import (
    Product, ProductVariant,
    ProductImage, ProductVariantImage,
    ProductDetailedImage, TemporaryUpload,ProductOffer
)
from django.utils.html import format_html


# 🔹 Inline admin for ProductImage
class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ["image_preview", "image", "featured"]
    readonly_fields = ["image_preview"]

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" width="80" height="80" style="border-radius:8px;object-fit:cover;" />', obj.image.url)
        return "-"
    image_preview.short_description = "Preview"

    def save_model(self, request, obj, form, change):
        # Ensure only one featured image per product
        if obj.featured:
            ProductImage.objects.filter(product=obj.product, featured=True).exclude(pk=obj.pk).update(featured=False)
        super().save_model(request, obj, form, change)


# 🔹 Inline admin for ProductVariantImage
class ProductVariantImageInline(admin.TabularInline):
    model = ProductVariantImage
    extra = 1
    fields = ["image_preview", "image", "featured"]
    readonly_fields = ["image_preview"]

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" width="80" height="80" style="border-radius:8px;object-fit:cover;" />', obj.image.url)
        return "-"
    image_preview.short_description = "Preview"

    def save_model(self, request, obj, form, change):
        # Ensure only one featured image per variant
        if obj.featured:
            ProductVariantImage.objects.filter(variant=obj.variant, featured=True).exclude(pk=obj.pk).update(featured=False)
        super().save_model(request, obj, form, change)


# 🔹 Inline for ProductVariant (with variant images inside)
class ProductVariantInline(admin.StackedInline):
    model = ProductVariant
    extra = 1
    show_change_link = True
    inlines = [ProductVariantImageInline]


# 🔹 Main Product admin
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "brand", "category", "stock_quantity", "is_listed", "created_at", "updated_at"]
    list_filter = ["is_listed", "category", "brand"]
    search_fields = ["name", "brand__name", "category__name"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ProductImageInline, ProductVariantInline]


# 🔹 Register ProductVariant separately (optional)
@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = ["product", "color", "stock"]
    search_fields = ["product__name", "color"]
    inlines = [ProductVariantImageInline]


# 🔹 Product Detailed Images
@admin.register(ProductDetailedImage)
class ProductDetailedImageAdmin(admin.ModelAdmin):
    list_display = ["product", "created_at"]


# 🔹 Temporary Uploads (staging area)
@admin.register(TemporaryUpload)
class TemporaryUploadAdmin(admin.ModelAdmin):
    list_display = ["file", "owner", "list_key", "created_at"]


@admin.register(ProductOffer)
class ProductOfferAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'title', 'discount_percent', 'discount_rs', 'is_extra', 'start_date', 'end_date')
    list_filter = ('product', 'is_extra')
    search_fields = ('product__name', 'title')