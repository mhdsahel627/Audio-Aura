# coupons/forms.py
from django import forms
from .models import Coupon


class CouponForm(forms.ModelForm):
    class Meta:
        model = Coupon
        fields = [
            'code',
            'title',
            'description',
            'discount',
            'coupon_type',
            'start_date',  # ✅ ADD THIS
            'expiry_date',
            'min_purchase',
            'max_purchase',
            'max_redeemable',
            'limit',
            'per_user_limit',  # ✅ ADD THIS
            'min_items',
            'first_time_only',  # ✅ ADD THIS
            'exclude_discounted',  # ✅ ADD THIS
            'is_active',
            'badge',
            'display_order',
        ]
        
        widgets = {
            'start_date': forms.DateInput(attrs={  # ✅ ADD THIS
                'type': 'date',
                'class': 'form-control'
            }),
            'expiry_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., BOAT5',
                'style': 'text-transform: uppercase;'
            }),
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., 5% off on 5+ items'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Coupon description...'
            }),
            'discount': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '5 (for 5% or ₹5)',
                'step': '0.01'
            }),
            'coupon_type': forms.Select(attrs={
                'class': 'form-select'
            }),
            'min_purchase': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0 = no minimum',
                'step': '0.01'
            }),
            'max_purchase': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0 = no maximum',
                'step': '0.01'
            }),
            'max_redeemable': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0 = no limit',
                'step': '0.01'
            }),
            'limit': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Total uses allowed (all users)',
                'value': 100
            }),
            'per_user_limit': forms.NumberInput(attrs={  # ✅ ADD THIS
                'class': 'form-control',
                'placeholder': 'Per-user usage limit',
                'value': 1
            }),
            'min_items': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0 = no minimum',
                'value': 0
            }),
            'first_time_only': forms.CheckboxInput(attrs={  # ✅ ADD THIS
                'class': 'form-check-input'
            }),
            'exclude_discounted': forms.CheckboxInput(attrs={  # ✅ ADD THIS
                'class': 'form-check-input'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'badge': forms.Select(attrs={
                'class': 'form-select'
            }, choices=[
                ('', 'No Badge'),
                ('Most Popular', 'Most Popular'),
                ('Best Value', 'Best Value'),
                ('Limited Time', 'Limited Time'),
                ('Most Savings', 'Most Savings'),
            ]),
            'display_order': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0 = highest priority',
                'value': 0
            }),
        }
        
        labels = {
            'code': 'Coupon Code',
            'title': 'Title',
            'description': 'Description',
            'discount': 'Discount Value',
            'coupon_type': 'Discount Type',
            'start_date': 'Start Date',  # ✅ ADD THIS
            'expiry_date': 'Expiry Date',
            'min_purchase': 'Minimum Purchase Amount (₹)',
            'max_purchase': 'Maximum Purchase Amount (₹)',
            'max_redeemable': 'Maximum Discount Cap (₹)',
            'limit': 'Total Usage Limit (All Users)',
            'per_user_limit': 'Per-User Usage Limit',  # ✅ ADD THIS
            'min_items': 'Minimum Items Required',
            'first_time_only': 'First-Time Buyers Only',  # ✅ ADD THIS
            'exclude_discounted': 'Exclude Discounted Products',  # ✅ ADD THIS
            'is_active': 'Active',
            'badge': 'Badge (Optional)',
            'display_order': 'Display Priority',
        }
        
        help_texts = {
            'code': 'Unique coupon code (e.g., BOAT5, GRAB600)',
            'discount': 'Enter 5 for 5% or ₹5 based on type',
            'start_date': 'Date when coupon becomes active',  # ✅ ADD THIS
            'expiry_date': 'Date when coupon expires',
            'min_purchase': 'Leave 0 for no minimum purchase requirement',
            'max_purchase': 'Cart value must be below this (0 = no limit)',
            'max_redeemable': 'For percentage coupons, set max discount (0 = unlimited)',
            'limit': 'Total number of times this coupon can be used across ALL users (e.g., 100 users)',
            'per_user_limit': 'How many times EACH user can use this coupon (usually 1)',  # ✅ ADD THIS
            'min_items': 'Required for "Buy X or more" offers (0 = price-based only)',
            'first_time_only': 'Check if coupon is only for users with no previous orders',  # ✅ ADD THIS
            'exclude_discounted': 'Check to prevent applying on already discounted products',  # ✅ ADD THIS
            'badge': 'Show special badge on product/cart pages',
            'display_order': 'Lower number = higher priority (0 appears first)',
        }
