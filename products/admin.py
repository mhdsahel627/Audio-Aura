from django import forms
from django.contrib import admin
from .models import (
    Product, ProductVariant,
    ProductImage, ProductVariantImage,
    ProductDetailedImage, TemporaryUpload, ProductOffer
)
from django.utils.html import format_html


#Custom ModelForm for Product (replaces forms.Form)
class ProductModelForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = '__all__'
        widgets = {
            'short_description': forms.Textarea(attrs={'rows': 3}),
            'long_description': forms.Textarea(attrs={'rows': 5}),
        }

    def clean(self):
        cleaned_data = super().clean()
        base_price = cleaned_data.get('base_price')
        discount_price = cleaned_data.get('discount_price')
        
        if base_price and discount_price and discount_price >= base_price:
            raise forms.ValidationError({
                'discount_price': "Discount price must be less than base price."
            })
        
        # Name required validation
        if not cleaned_data.get('name'):
            raise forms.ValidationError({'name': "Product name is required."})
            
        return cleaned_data


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
        if obj.featured:
            ProductVariantImage.objects.filter(variant=obj.variant, featured=True).exclude(pk=obj.pk).update(featured=False)
        super().save_model(request, obj, form, change)


# 🔹 Inline for ProductVariant (with variant images inside)
class ProductVariantInline(admin.StackedInline):
    model = ProductVariant
    extra = 1
    show_change_link = True
    inlines = [ProductVariantImageInline]


# 🔹 Main Product admin - 
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductModelForm  #ModelForm use cheyyunnu
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





@admin.register(ProductOffer)
class ProductOfferAdmin(admin.ModelAdmin):
    list_display = ('id', 'product', 'title', 'discount_percent', 'discount_rs', 'is_extra', 'start_date', 'end_date')
    list_filter = ('product', 'is_extra')
    search_fields = ('product__name', 'title')
    