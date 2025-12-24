# authentication/views.py

from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.views.decorators.cache import never_cache
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
import random
from django.conf import settings

# Forms
from .forms import (
    LoginForm,
    ForgotPasswordForm,
    ResetPasswordForm,
    SignupForm,
    OTPForm
)
# User Profile
from user.models import Profile
# Referral & Wallet
from wallet.models import ReferralProfile, Referral, ReferralConfig, WalletAccount, WalletTransaction
from wallet.services import credit, qualify_signup_referral_and_credit

# ========== EMAIL UTILITIES ==========

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags


def send_dynamic_otp_email(email, otp, email_type='signup', username=None):
    """
    Send dynamic OTP email based on context.
    
    Args:
        email (str): Recipient email
        otp (str): OTP code
        email_type (str): Type of email - 'signup', 'password_reset', 'email_change'
        username (str): User's name (optional, extracted from email if not provided)
    
    Returns:
        bool: True if sent successfully, False otherwise
    """
    
    # Email type configurations
    EMAIL_CONFIGS = {
        'signup': {
            'subject': '🎉 Welcome to Audio Aura - Verify Your Email',
            'title': '🔐 Verify Your Email Address',
            'greeting': 'Welcome to Audio Aura!',
            'message': 'Thank you for joining <strong style="color: #7c3aed;">Audio Aura</strong>! To complete your registration and start exploring our premium audio collection, please use the verification code below:',
            'icon': '🎉',
            'footer_text': 'We\'re excited to have you on board!',
        },
        'password_reset': {
            'subject': '🔒 Reset Your Password - Audio Aura',
            'title': '🔑 Password Reset Request',
            'greeting': 'Password Reset',
            'message': 'We received a request to reset your password for your <strong style="color: #7c3aed;">Audio Aura</strong> account. Use the verification code below to proceed:',
            'icon': '🔒',
            'footer_text': 'If you didn\'t request this, please ignore this email.',
        },
        'email_change': {
            'subject': '📧 Verify Your New Email - Audio Aura',
            'title': '📧 Email Change Verification',
            'greeting': 'Email Update',
            'message': 'You\'ve requested to change your email address for your <strong style="color: #7c3aed;">Audio Aura</strong> account. Please verify your new email using the code below:',
            'icon': '📧',
            'footer_text': 'Keep your account secure!',
        },
        'login_verification': {
            'subject': '🔐 Login Verification - Audio Aura',
            'title': '🔐 Verify Your Login',
            'greeting': 'Login Attempt Detected',
            'message': 'We detected a login attempt to your <strong style="color: #7c3aed;">Audio Aura</strong> account. Please verify it\'s you using the code below:',
            'icon': '🔐',
            'footer_text': 'Secure your account always!',
        }
    }
    
    # Get config for email type (default to signup)
    config = EMAIL_CONFIGS.get(email_type, EMAIL_CONFIGS['signup'])
    
    # Extract username from email if not provided
    if not username:
        username = email.split('@')[0].capitalize()
    
    # Context for email template
    context = {
        'username': username,
        'otp': otp,
        'email_type': email_type,
        'title': config['title'],
        'greeting': config['greeting'],
        'message': config['message'],
        'icon': config['icon'],
        'footer_text': config['footer_text'],
    }
    
    try:
        # Render HTML email
        html_content = render_to_string('emails/dynamic_otp_email.html', context)
        text_content = strip_tags(html_content)  # Fallback plain text
        
        # Create email
        subject = config['subject']
        from_email = settings.DEFAULT_FROM_EMAIL# Replace with your email
        to_email = [email]
        
        # Create email with HTML
        email_message = EmailMultiAlternatives(subject, text_content, from_email, to_email)
        email_message.attach_alternative(html_content, "text/html")
        email_message.send()
        
        print(f"✅ {email_type.upper()} OTP {otp} sent to {email}")
        return True
        
    except Exception as e:
        print(f'❌ Error sending OTP: {e}')
        return False


# ========== HELPER FUNCTIONS ==========

def unauthenticated_user(view_func):
    """Decorator to restrict authenticated users from accessing login/signup pages"""
    def wrapper_func(request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('home')
        else:
            return view_func(request, *args, **kwargs)
    return wrapper_func


def generate_otp():
    """
    Generate a random 4-digit OTP.
    
    Returns:
        str: Random 4-digit OTP as a string.
    """
    return str(random.randint(1000, 9999))


# ========== SIGNUP FLOW ==========

@unauthenticated_user
def SignUp(request):
    """
    Handle user signup with referral support.
    Generates OTP and sends verification email.
    """
    # Capture referral code from URL
    ref_from_url = request.GET.get("ref")
    if ref_from_url:
        request.session["ref_code"] = ref_from_url

    if request.method == "POST":
        form = SignupForm(request.POST)

        if form.is_valid():
            # Referral code from FORM or URL
            ref_code = (
                form.cleaned_data.get('referral_code') 
                or request.session.get("ref_code")
            )

            # Generate OTP
            otp = generate_otp()

            # Store Temp User in session for OTP page
            request.session['temp_user'] = {
                'first_name': form.cleaned_data['first_name'],
                'last_name': form.cleaned_data['last_name'],
                'email': form.cleaned_data['email'],
                'username': form.cleaned_data['email'],
                'password': form.cleaned_data['password'],
                'phone': form.cleaned_data.get('phone'),
                'otp': otp,
                'otp_expires': (timezone.now() + timedelta(minutes=5)).timestamp(),
                'ref_code': ref_code,
            }

            # 🔥 SEND DYNAMIC EMAIL - SIGNUP
            username = f"{form.cleaned_data['first_name']} {form.cleaned_data['last_name']}"
            if send_dynamic_otp_email(
                email=form.cleaned_data['email'],
                otp=otp,
                email_type='signup',
                username=username
            ):
                messages.success(request, "OTP sent to your email ✅")
                return redirect('verify_otp')
            else:
                messages.error(request, "Failed to send OTP. Try again.")

    else:
        form = SignupForm()

    return render(request, "user/sign_up.html", {"form": form})


def VerifyOTP(request):
    """
    Verify OTP during signup, create the auth User, attach referral if present,
    qualify once (atomic) to credit referrer, and clean session.
    """
    temp = request.session.get('temp_user')
    if not temp:
        messages.error(request, "Session expired. Please signup again.")
        return redirect('signup')

    if request.method == 'POST':
        form = OTPForm(request.POST)
        if form.is_valid():
            entered_otp = str(form.cleaned_data['otp']).strip()

            # 1) OTP checks
            if entered_otp != str(temp.get('otp')):
                messages.error(request, "Invalid OTP ❌")
                return redirect('verify_otp')

            if timezone.now().timestamp() > float(temp.get('otp_expires', 0)):
                messages.error(request, "OTP expired. Please signup again ❌")
                request.session.pop('temp_user', None)
                return redirect('signup')

            # 2) Create the real user (idempotent)
            user = User.objects.filter(username=temp['username']).first()
            if not user:
                user = User.objects.create_user(
                    username=temp['username'],
                    email=temp['email'],
                    password=temp['password'],
                    first_name=temp['first_name'],
                    last_name=temp['last_name'],
                )
                # Ensure profile and phone
                profile, _ = Profile.objects.get_or_create(user=user)
                phone = temp.get('phone')
                if phone:
                    profile.phone = phone
                    profile.save(update_fields=["phone"])

                # 3) Capture referral event (no credit yet)
                ref_code = temp.get('ref_code') or request.session.get('ref_code')
                WalletAccount.objects.get_or_create(user=user)
                ReferralProfile.objects.get_or_create(user=user)
                if ref_code:
                    try:
                        referrer_profile = ReferralProfile.objects.select_related("user").get(code=ref_code)
                        referrer = referrer_profile.user
                        if referrer != user:
                            Referral.objects.get_or_create(
                                referee=user,
                                defaults={"referrer": referrer, "code_used": ref_code, "status": "signed_up"}
                            )
                    except ReferralProfile.DoesNotExist:
                        pass

            # 4) Qualify + credit once (atomic and idempotent inside the service)
            try:
                qualify_signup_referral_and_credit(user)
            except Exception as e:
                # Do not block signup; you can log this for ops
                messages.warning(request, f"Referral bonus pending: {e}")

            messages.success(request, "Signup successful! 🎉")

            # 5) Cleanup session and redirect
            for k in ("temp_user", "ref_code"):
                request.session.pop(k, None)
            return redirect('signin')
    else:
        form = OTPForm()

    return render(request, 'verify_otp.html', {'form': form, 'temp_user': temp})


def ResendOTP(request):
    """
    Resend OTP during signup.
    
    Args:
        request (HttpRequest): The HTTP request object.
    
    Returns:
        HttpResponseRedirect: Redirects to OTP verification page.
    """
    temp_user = request.session.get('temp_user')
    if not temp_user:
        messages.error(request, "Session expired. Please signup again.")
        return redirect('signup')

    otp = generate_otp()
    temp_user['otp'] = otp
    temp_user['otp_expires'] = (timezone.now() + timedelta(minutes=5)).timestamp()
    request.session['temp_user'] = temp_user

    # 🔥 SEND DYNAMIC EMAIL - SIGNUP RESEND
    username = f"{temp_user.get('first_name', '')} {temp_user.get('last_name', '')}".strip()
    if send_dynamic_otp_email(
        email=temp_user['email'],
        otp=otp,
        email_type='signup',
        username=username if username else None
    ):
        messages.success(request, "New OTP sent successfully ✅")
    else:
        messages.error(request, "Failed to resend OTP. Try again ❌")

    return redirect('verify_otp')


# ========== PASSWORD RESET FLOW ==========

@unauthenticated_user
def forgot_password(request):
    """
    Handle forgot password requests.
    
    Generates OTP, stores reset info in session, and sends OTP to user's email.
    
    Args:
        request (HttpRequest): The HTTP request object.
    
    Returns:
        HttpResponse: Renders forgot password form or redirects to OTP verification page.
    """
    if request.method == "POST":
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                messages.error(request, "Email not registered ❌")
                return redirect('forgot_password')

            otp = generate_otp()
            otp_expires = (timezone.now() + timedelta(minutes=5)).timestamp()
            request.session['reset_user'] = {
                'user_id': user.id,
                'otp': otp,
                'otp_expires': otp_expires,
            }

            # 🔥 SEND DYNAMIC EMAIL - PASSWORD RESET
            username = user.get_full_name() or user.username
            if send_dynamic_otp_email(
                email=email,
                otp=otp,
                email_type='password_reset',
                username=username
            ):
                messages.success(request, "OTP sent to your email ✅")
            else:
                messages.error(request, "Failed to send OTP. Try again ❌")

            return redirect('verify_reset_otp')

    else:
        form = ForgotPasswordForm()
    return render(request, "forgot_password.html", {'form': form})


def verify_reset_otp(request):
    """
    Verify OTP during forgot password flow.
    
    Args:
        request (HttpRequest): The HTTP request object.
    
    Returns:
        HttpResponse: Renders OTP verification page or redirects to reset password page.
    """
    reset_user = request.session.get('reset_user')
    if not reset_user:
        messages.error(request, 'Session expired. Try again.')
        return redirect('forgot_password')

    if request.method == 'POST':
        entered_otp = request.POST.get('otp')
        if str(reset_user['otp']) != entered_otp:
            messages.error(request, "Invalid OTP ❌")
        elif timezone.now().timestamp() > reset_user['otp_expires']:
            messages.error(request, 'OTP expired. Try again ❌')
            del request.session['reset_user']
            return redirect('forgot_password')
        else:
            request.session['otp_verified'] = True
            return redirect('reset_password')

    return render(request, 'verify_reset_otp.html', {'email': User.objects.get(id=reset_user['user_id']).email})


@unauthenticated_user
def resend_reset_otp(request):
    """
    Resend OTP for forgot password flow.
    
    Args:
        request (HttpRequest): The HTTP request object.
    
    Returns:
        HttpResponseRedirect: Redirects to OTP verification page.
    """
    reset_user = request.session.get('reset_user')
    if not reset_user:
        messages.error(request, 'Session expired. Try again.')
        return redirect('forgot_password')

    otp = generate_otp()
    reset_user['otp'] = otp
    reset_user['otp_expires'] = (timezone.now() + timedelta(minutes=5)).timestamp()
    request.session['reset_user'] = reset_user

    user = User.objects.get(id=reset_user['user_id'])
    
    # 🔥 SEND DYNAMIC EMAIL - PASSWORD RESET RESEND
    username = user.get_full_name() or user.username
    if send_dynamic_otp_email(
        email=user.email,
        otp=otp,
        email_type='password_reset',
        username=username
    ):
        messages.success(request, "OTP resent successfully ✅")
    else:
        messages.error(request, "Failed to resend OTP. Try again ❌")

    return redirect('verify_reset_otp')


@unauthenticated_user
def reset_password(request):
    """
    Reset user password after OTP verification.
    
    Args:
        request (HttpRequest): The HTTP request object.
    
    Returns:
        HttpResponse: Renders reset password form or redirects to login page after successful reset.
    """
    if not request.session.get('otp_verified'):
        messages.error(request, "Unauthorized access ❌")
        return redirect('forgot_password')

    reset_user = request.session.get('reset_user')
    user = User.objects.get(id=reset_user['user_id'])

    if request.method == "POST":
        form = ResetPasswordForm(request.POST)
        if form.is_valid():
            new_password = form.cleaned_data['new_password']
            user.set_password(new_password)
            user.save()
            del request.session['reset_user']
            del request.session['otp_verified']
            messages.success(request, "Password reset successful ✅")
            return redirect('signin')
    else:
        form = ResetPasswordForm()

    return render(request, "reset_password.html", {'form': form})


# ========== LOGIN/LOGOUT ==========

@never_cache
def SignIn(request):
    """
    Handle user login.
    
    Validates form, authenticates user, and logs in if credentials are correct.
    
    Args:
        request (HttpRequest): The HTTP request object.
    
    Returns:
        HttpResponse: Renders login page or redirects to home page on successful login.
    """
    # Already logged-in user prevent login page access
    if request.user.is_authenticated:
        return redirect("home")
    
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data['email']
        password = form.cleaned_data['password']

        user = authenticate(request, username=email, password=password)

        if user is None:
            # Check if user exists but blocked
            try:
                user_check = User.objects.get(username=email)
                if not user_check.is_active:
                    messages.warning(request, "Your account is blocked 🚫")
                else:
                    form.add_error(None, "Invalid credentials ❌")
            except User.DoesNotExist:
                form.add_error(None, "Invalid credentials ❌")
        else:
            login(request, user)
            messages.success(request, f"Welcome {user.username}!")
            return redirect("home")

    return render(request, "user/login.html", {"form": form})


def SignOut(request):
    """
    Logout authenticated user.
    
    Args:
        request (HttpRequest): The HTTP request object.
    
    Returns:
        HttpResponseRedirect: Redirects to login page after logout.
    """
    if request.user.is_authenticated:
        username = request.user.first_name
        logout(request)
        messages.info(request, f"{username} You have been logged out successfully ✅")
    return redirect('signin')
