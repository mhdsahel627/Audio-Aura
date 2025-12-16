from django.contrib import admin
from .models import Coupon, DeliveryPincode

@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ['code', 'title', 'discount', 'coupon_type', 'min_purchase', 'max_purchase', 'min_items', 'expiry_date', 'is_active', 'used_count']
    list_filter = ['is_active', 'coupon_type', 'expiry_date']
    search_fields = ['code', 'title']
    readonly_fields = ['used_count']
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('code', 'title', 'description', 'badge')
        }),
        ('Discount', {
            'fields': ('discount', 'coupon_type', 'max_redeemable')
        }),
        ('Conditions', {
            'fields': ('min_purchase', 'max_purchase', 'min_items')
        }),
        ('Validity', {
            'fields': ('expiry_date', 'limit', 'used_count', 'is_active')
        }),
        ('Display', {
            'fields': ('display_order',)
        }),
    )


# ✅ NEW: Delivery Pincode Admin
@admin.register(DeliveryPincode)
class DeliveryPincodeAdmin(admin.ModelAdmin):
    list_display = [
        'pincode', 
        'city', 
        'state', 
        'delivery_days', 
        'is_serviceable', 
        'is_cod_available',
        'created_at'
    ]
    
    list_filter = [
        'is_serviceable', 
        'is_cod_available', 
        'state',
        'delivery_days'
    ]
    
    search_fields = [
        'pincode', 
        'city', 
        'state'
    ]
    
    list_editable = [
        'is_serviceable', 
        'is_cod_available'
    ]
    
    ordering = ['pincode']
    
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Location', {
            'fields': ('pincode', 'city', 'state')
        }),
        ('Delivery Settings', {
            'fields': ('delivery_days', 'is_serviceable', 'is_cod_available')
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    # ✅ Bulk actions
    actions = ['mark_serviceable', 'mark_not_serviceable', 'enable_cod', 'disable_cod']
    
    def mark_serviceable(self, request, queryset):
        updated = queryset.update(is_serviceable=True)
        self.message_user(request, f'{updated} pincode(s) marked as serviceable.')
    mark_serviceable.short_description = "Mark selected as serviceable"
    
    def mark_not_serviceable(self, request, queryset):
        updated = queryset.update(is_serviceable=False)
        self.message_user(request, f'{updated} pincode(s) marked as not serviceable.')
    mark_not_serviceable.short_description = "Mark selected as not serviceable"
    
    def enable_cod(self, request, queryset):
        updated = queryset.update(is_cod_available=True)
        self.message_user(request, f'{updated} pincode(s) enabled for COD.')
    enable_cod.short_description = "Enable COD for selected"
    
    def disable_cod(self, request, queryset):
        updated = queryset.update(is_cod_available=False)
        self.message_user(request, f'{updated} pincode(s) disabled for COD.')
    disable_cod.short_description = "Disable COD for selected"
