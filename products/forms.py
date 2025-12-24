# forms.py
from django import forms
from decimal import Decimal
from django.core.exceptions import ValidationError
import re
from .models import Product

# Name validation regex (letters, numbers, spaces, underscores, hyphens)
name_re = re.compile(r'^[a-zA-Z0-9\s_-]+$')

class ProductAddForm(forms.Form):
    name = forms.CharField(
        max_length=255, 
        label="Product Name",
        widget=forms.TextInput(attrs={'class': 'form-control pa-input'}),
        required=True  # ✅ REQUIRED
    )
    short_desc = forms.CharField(
        required=True,  # ✅ REQUIRED
        label="Short Description",
        widget=forms.TextInput(attrs={'class': 'form-control pa-input'})
    )
    long_desc = forms.CharField(
        required=True,  # ✅ REQUIRED
        label="Long Description",
        widget=forms.Textarea(attrs={'rows': 4, 'class': 'form-control pa-input'})
    )
    brand = forms.IntegerField(
        label="Brand",
        widget=forms.Select(attrs={'class': 'form-control pa-input'}),
        required=True  # ✅ REQUIRED
    )
    category = forms.IntegerField(
        label="Category",
        widget=forms.Select(attrs={'class': 'form-control pa-input'}),
        required=True  # ✅ REQUIRED
    )
    base_price = forms.DecimalField(
        min_value=0.01,  # ✅ Min 0.01 (not 0)
        decimal_places=2, 
        max_digits=10,
        label="Base Price (₹)",
        widget=forms.NumberInput(attrs={'step': '0.01', 'min': '0.01', 'class': 'form-control pa-input'}),
        required=True  # ✅ REQUIRED
    )
    discount_price = forms.DecimalField(
        required=True,  # ✅ REQUIRED
        min_value=0, 
        decimal_places=2, 
        max_digits=10,
        label="Discount Price (₹)",
        widget=forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'class': 'form-control pa-input'})
    )
    offer = forms.CharField(
        max_length=255, 
        label="Offer Badge",
        widget=forms.TextInput(attrs={'class': 'form-control pa-input'}),
        required=True  # ✅ REQUIRED
    )
    video = forms.CharField(  # ✅ CharField (not URLField for flexibility)
        label="Video URL",
        widget=forms.URLInput(attrs={'class': 'form-control pa-input'}),
        required=False
    )

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if not name_re.match(name):
            raise ValidationError("Name can contain letters, numbers, spaces, underscores and hyphens only.")
        if Product.objects.filter(name__iexact=name).exists():
            raise ValidationError(f"Product '{name}' already exists.")
        return name

    def clean_base_price(self):
        base_price = self.cleaned_data['base_price']
        if base_price <= 0:
            raise ValidationError("Base price must be greater than 0.")
        return base_price

    def clean_discount_price(self):
        discount_price = self.cleaned_data['discount_price']
        if discount_price < 0:
            raise ValidationError("Discount price cannot be negative.")
        return discount_price

    def clean(self):
        cleaned_data = super().clean()
        
        # Cross-field validation: discount < base price
        base_price = cleaned_data.get('base_price')
        discount_price = cleaned_data.get('discount_price')
        
        if base_price and discount_price and discount_price >= base_price:
            raise ValidationError({
                'discount_price': "Discount price must be LESS than base price."
            })
        
        return cleaned_data
