from django import forms
from django.contrib.auth.forms import AuthenticationForm


class AdminLoginForm(AuthenticationForm):
    username = forms.CharField(
        label='Email / Username',
        widget=forms.TextInput(attrs={
            'class':'form-control',
            'placeholder':'Enter email or username'
        })
        
    )
    password = forms.CharField(
        widget = forms.PasswordInput(attrs={
            'clsss':'form-control',
            'placeholder':'Enter Password'            
        })
    )
    



