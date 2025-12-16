from django import forms
from .models import Banner, DealOfMonth, DealImage, FeaturedProduct


class BannerForm(forms.ModelForm):
    class Meta:
        model = Banner
        fields = ['title', 'description', 'media_type', 'image', 'video', 
                  'link_url', 'start_date', 'end_date', 'is_active', 'priority']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter banner title'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'media_type': forms.Select(attrs={'class': 'form-control'}),
            'link_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://'}),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'end_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'priority': forms.NumberInput(attrs={'class': 'form-control'}),
        }


class DealForm(forms.ModelForm):
    class Meta:
        model = DealOfMonth
        fields = ['title', 'description', 'cta_text', 'cta_url', 
                  'starts_on', 'ends_on', 'is_active', 'priority']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'cta_text': forms.TextInput(attrs={'class': 'form-control'}),
            'cta_url': forms.URLInput(attrs={'class': 'form-control'}),
            'starts_on': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'ends_on': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'priority': forms.NumberInput(attrs={'class': 'form-control'}),
        }


class DealImageForm(forms.ModelForm):
    class Meta:
        model = DealImage
        fields = ['image', 'order']
        widgets = {
            'order': forms.NumberInput(attrs={'class': 'form-control'}),
        }


class FeaturedProductForm(forms.ModelForm):
    class Meta:
        model = FeaturedProduct
        fields = ['title', 'description', 'image', 'price', 'link_url', 'is_active', 'priority']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'link_url': forms.URLInput(attrs={'class': 'form-control'}),
            'priority': forms.NumberInput(attrs={'class': 'form-control'}),
        }
