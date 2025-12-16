# forms.py
from django import forms
from django.forms import ValidationError
from .models import Address

class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ['full_name','phone','address_line1','address_line2','city','state','postcode','country','notes','is_default']

    def clean_phone(self):
        p = self.cleaned_data['phone'].strip()
        if len(p) < 7:
            raise forms.ValidationError('Enter a valid phone number.')
        return p

'''
OTP Verification Form
'''
class OTPForm(forms.Form):
    otp = forms.CharField(
        max_length=4,
        min_length=4,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter OTP'
        })
    )
'''
 🔹 Forgot Password Form
 '''
class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(widget=forms.EmailInput(attrs={
        'class': 'form-control',
        'placeholder': 'Enter your email'
    }))
    
    
'''
🔹 Reset Password Form
'''
class ResetPasswordForm(forms.Form):
    new_password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'form-control',
        'placeholder': 'New password'
    }))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'form-control',
        'placeholder': 'Confirm new password'
    }))

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get("new_password")
        p2 = cleaned_data.get("confirm_password")

        if p1 != p2:
            raise ValidationError("Passwords do not match!")