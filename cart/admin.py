from django.contrib import admin
from .models import Cart, CartItem


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    readonly_fields = (
        'unit_price_at_add',
        'line_subtotal',
        'line_addons',
        'line_tax',
    )


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ('user', 'subtotal', 'grand_total', 'updated_at')
    search_fields = ('user__username',)
    inlines = [CartItemInline]


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = (
        'cart',
        'product',
        'variant',
        'quantity',
        'unit_price_at_add',
        'line_subtotal',
        'line_addons',
        'line_tax',
    )
    list_filter = ('product', 'variant')
    search_fields = ('cart__user__username', 'product__name')
