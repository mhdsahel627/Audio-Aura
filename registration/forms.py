from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
import re


'''
🔹 Login Form
'''
class LoginForm(forms.Form):  
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email'
        }),
        error_messages={
            'required': 'Email is required.',
            'invalid': 'Enter a valid email address.'
        }
    )
    
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your password',
            'id': 'passwordInput'   
        }),
        error_messages={
            'required': 'Password is required.'
        }
    )


'''
🔹 Signup Form
'''
class SignupForm(forms.ModelForm):
    phone = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Phone Number (Optional)'
        })
    )

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password',
            'id': 'password1'
        }),
        label='Password',
        error_messages={
            'required': 'Password is required.'
        }
    )
    
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm Password',
            'id': 'password2'
        }),
        label='Confirm Password',
        error_messages={
            'required': 'Please confirm your password.'
        }
    )
    
    referral_code = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter Referral Code (Optional)'
        })
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email', 'password']
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'First Name'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'Last Name'
            }),
            'username': forms.TextInput(attrs={
                'class': 'form-control', 
                'placeholder': 'Username'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control', 
                'placeholder': 'Email'
            }),
        }
        error_messages = {
            'first_name': {
                'required': 'First name is required.',
            },
            'last_name': {
                'required': 'Last name is required.',
            },
            'username': {
                'required': 'Username is required.',
                'unique': 'This username is already taken.',
            },
            'email': {
                'required': 'Email is required.',
                'invalid': 'Enter a valid email address.',
                'unique': 'This email is already registered.',
            },
        }

    # ------------------------------
    # First Name Validation
    # ------------------------------
    def clean_first_name(self):
        first_name = self.cleaned_data.get('first_name', '').strip()
        
        if not first_name:
            raise ValidationError("First name is required.")
        
        if len(first_name) < 2:
            raise ValidationError("First name must be at least 2 characters long.")
        
        if len(first_name) > 30:
            raise ValidationError("First name cannot exceed 30 characters.")
        
        if any(char.isdigit() for char in first_name):
            raise ValidationError("First name cannot contain numbers.")
        
        if " " in first_name:
            raise ValidationError("First name cannot contain spaces.")
        
        if not re.match(r'^[a-zA-Z]+$', first_name):
            raise ValidationError("First name can only contain letters.")
        
        return first_name.capitalize()

    # ------------------------------
    # Last Name Validation
    # ------------------------------
    def clean_last_name(self):
        last_name = self.cleaned_data.get('last_name', '').strip()
        
        if not last_name:
            raise ValidationError("Last name is required.")
        
        if len(last_name) < 2:
            raise ValidationError("Last name must be at least 2 characters long.")
        
        if len(last_name) > 30:
            raise ValidationError("Last name cannot exceed 30 characters.")
        
        if any(char.isdigit() for char in last_name):
            raise ValidationError("Last name cannot contain numbers.")
        
        if " " in last_name:
            raise ValidationError("Last name cannot contain spaces.")
        
        if not re.match(r'^[a-zA-Z]+$', last_name):
            raise ValidationError("Last name can only contain letters.")
        
        return last_name.capitalize()

    # ------------------------------
    # Username Validation
    # ------------------------------
    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        
        if not username:
            raise ValidationError("Username is required.")
        
        if len(username) < 3:
            raise ValidationError("Username must be at least 3 characters long.")
        
        if len(username) > 20:
            raise ValidationError("Username cannot exceed 20 characters.")
        
        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            raise ValidationError("Username can only contain letters, numbers, and underscores.")
        
        if username[0].isdigit():
            raise ValidationError("Username cannot start with a number.")
        
        # Check for reserved usernames
        reserved_names = ['admin', 'root', 'superuser', 'staff', 'moderator']
        if username.lower() in reserved_names:
            raise ValidationError("This username is reserved.")
        
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("This username is already taken.")
        
        return username.lower()

    # ------------------------------
    # Email Validation
    # ------------------------------
    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        
        if not email:
            raise ValidationError("Email is required.")
        
        # Validate email format
        try:
            validate_email(email)
        except ValidationError:
            raise ValidationError("Enter a valid email address.")
        
        # Check for disposable email domains
        disposable_domains = ['tempmail.com', 'throwaway.email', '10minutemail.com']
        email_domain = email.split('@')[-1]
        if email_domain in disposable_domains:
            raise ValidationError("Disposable email addresses are not allowed.")
        
        # Check if email already exists
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("This email is already registered.")
        
        return email

    # ------------------------------
    # Phone Validation (Optional)
    # ------------------------------
    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '').strip()
        
        if not phone:
            return phone  # Optional field
        
        # Remove common separators
        phone = re.sub(r'[\s\-\(\)]', '', phone)
        
        if not phone.isdigit():
            raise ValidationError("Phone number can only contain digits.")
        
        if len(phone) < 10:
            raise ValidationError("Phone number must be at least 10 digits.")
        
        if len(phone) > 15:
            raise ValidationError("Phone number cannot exceed 15 digits.")
        
        return phone

    # ------------------------------
    # Password Validation
    # ------------------------------
    def clean_password(self):
        password = self.cleaned_data.get('password', '')
        
        if not password:
            raise ValidationError("Password is required.")
        
        errors = []
        
        if len(password) < 8:
            errors.append("Password must be at least 8 characters long.")
        
        if len(password) > 128:
            errors.append("Password cannot exceed 128 characters.")
        
        if not re.search(r'[A-Z]', password):
            errors.append("Password must contain at least one uppercase letter.")
        
        if not re.search(r'[a-z]', password):
            errors.append("Password must contain at least one lowercase letter.")
        
        if not re.search(r'\d', password):
            errors.append("Password must contain at least one number.")
        
        if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\\/~`]', password):
            errors.append("Password must contain at least one special character (!@#$%^&* etc.).")
        
        # Check for common passwords
        common_passwords = ['password', '12345678', 'qwerty', 'abc123', 'password123']
        if password.lower() in common_passwords:
            errors.append("This password is too common. Please choose a stronger password.")
        
        # Check if password contains username or email
        username = self.cleaned_data.get('username', '')
        email = self.cleaned_data.get('email', '')
        if username and username.lower() in password.lower():
            errors.append("Password cannot contain your username.")
        if email and email.split('@')[0].lower() in password.lower():
            errors.append("Password cannot contain your email address.")
        
        if errors:
            raise ValidationError(errors)
        
        return password

    # ------------------------------
    # Referral Code Validation
    # ------------------------------
    def clean_referral_code(self):
        referral_code = self.cleaned_data.get('referral_code', '').strip().upper()
        
        if not referral_code:
            return referral_code  # Optional field
        
        if len(referral_code) < 4:
            raise ValidationError("Referral code must be at least 4 characters.")
        
        if not re.match(r'^[A-Z0-9]+$', referral_code):
            raise ValidationError("Referral code can only contain letters and numbers.")
        
        # Add your referral validation logic here
        # Example: Check if referral code exists in database
        # from .models import ReferralCode
        # if not ReferralCode.objects.filter(code=referral_code, is_active=True).exists():
        #     raise ValidationError("Invalid or expired referral code.")
        
        return referral_code

    # ------------------------------
    # Form-Level Validation (Confirm Password)
    # ------------------------------
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password and confirm_password:
            if password != confirm_password:
                self.add_error('confirm_password', "Passwords do not match.")
        
        return cleaned_data


'''
🔹 OTP Verification Form
'''
class OTPForm(forms.Form):
    otp = forms.CharField(
        max_length=6,
        min_length=4,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter OTP',
            'maxlength': '6',
            'pattern': '[0-9]*',
            'inputmode': 'numeric'
        }),
        error_messages={
            'required': 'OTP is required.',
            'min_length': 'OTP must be at least 4 digits.',
            'max_length': 'OTP cannot exceed 6 digits.'
        }
    )
    
    def clean_otp(self):
        otp = self.cleaned_data.get('otp', '').strip()
        
        if not otp.isdigit():
            raise ValidationError("OTP must contain only numbers.")
        
        if len(otp) < 4:
            raise ValidationError("OTP must be at least 4 digits.")
        
        if len(otp) > 6:
            raise ValidationError("OTP cannot exceed 6 digits.")
        
        return otp


'''
🔹 Forgot Password Form
'''
class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your registered email'
        }),
        error_messages={
            'required': 'Email is required.',
            'invalid': 'Enter a valid email address.'
        }
    )
    
    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        
        if not email:
            raise ValidationError("Email is required.")
        
        try:
            validate_email(email)
        except ValidationError:
            raise ValidationError("Enter a valid email address.")
        
        # Check if email exists in database
        if not User.objects.filter(email__iexact=email).exists():
            raise ValidationError("No account found with this email address.")
        
        return email


'''
🔹 Reset Password Form
'''
class ResetPasswordForm(forms.Form):
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'New password'
        }),
        error_messages={
            'required': 'New password is required.'
        }
    )
    
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm new password'
        }),
        error_messages={
            'required': 'Please confirm your new password.'
        }
    )

    def clean_new_password(self):
        password = self.cleaned_data.get('new_password', '')
        
        if not password:
            raise ValidationError("New password is required.")
        
        errors = []
        
        if len(password) < 8:
            errors.append("Password must be at least 8 characters long.")
        
        if len(password) > 128:
            errors.append("Password cannot exceed 128 characters.")
        
        if not re.search(r'[A-Z]', password):
            errors.append("Password must contain at least one uppercase letter.")
        
        if not re.search(r'[a-z]', password):
            errors.append("Password must contain at least one lowercase letter.")
        
        if not re.search(r'\d', password):
            errors.append("Password must contain at least one number.")
        
        if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\\/~`]', password):
            errors.append("Password must contain at least one special character.")
        
        common_passwords = ['password', '12345678', 'qwerty', 'abc123', 'password123']
        if password.lower() in common_passwords:
            errors.append("This password is too common.")
        
        if errors:
            raise ValidationError(errors)
        
        return password

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password")
        confirm_password = cleaned_data.get("confirm_password")

        if new_password and confirm_password:
            if new_password != confirm_password:
                self.add_error('confirm_password', "Passwords do not match.")
        
        return cleaned_data
