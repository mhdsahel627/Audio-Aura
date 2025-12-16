# forms.py
from django import forms
from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError

class ProductForm(forms.Form):
    name = forms.CharField(max_length=255)
    short_desc = forms.CharField(required=False, widget=forms.Textarea)
    long_desc = forms.CharField(required=False, widget=forms.Textarea)
    brand = forms.IntegerField()
    category = forms.IntegerField()
    base_price = forms.CharField()
    discount_price = forms.CharField(required=False)
    offer = forms.CharField(required=False)
    video = forms.CharField(required=False)

    def clean(self):
        cleaned = super().clean()
        base_price = cleaned.get("base_price", "").strip()
        discount_price = cleaned.get("discount_price", "").strip()

        try:
            bp = Decimal(base_price) if base_price != "" else Decimal("0")
        except (InvalidOperation, ValueError):
            self.add_error("base_price", "Invalid price format.")
            bp = None

        dp = None
        if discount_price:
            try:
                dp = Decimal(discount_price)
            except (InvalidOperation, ValueError):
                self.add_error("discount_price", "Invalid price format.")

        if bp is not None:
            if bp < 0:
                self.add_error("base_price", "Base price cannot be negative.")
            if dp is not None and bp is not None and dp >= bp:
                self.add_error("discount_price", "Discount price must be less than base price.")

        # Required cross-field check
        for field in ["name", "category", "brand"]:
            if not cleaned.get(field):
                self.add_error(field, "This field is required.")

        return cleaned
