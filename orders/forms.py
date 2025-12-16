from django import forms
from .models import OrderItem

class ReturnReasonForm(forms.Form):
    reason = forms.CharField(
        label="Return reason", max_length=250, required=True,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Explain why you’re returning"})
    )

class CancelItemForm(forms.Form):
    reason = forms.ChoiceField(
        choices=OrderItem.CancellationReason.choices,
        widget=forms.Select(attrs={
            'class': 'form-control',
            'required': True
        }),
        label="Reason for cancellation"
    )
    
    note = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'maxlength': 500,
            'placeholder': 'Please provide additional details (optional)'
        }),
        required=False,
        label="Additional details",
        max_length=500
    )

