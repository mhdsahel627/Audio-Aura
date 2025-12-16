from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.views.decorators.cache import never_cache
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
import random
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



def unauthenticated_user(view_func):
    def wrapper_func(request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('home')  # Redirect to homepage or dashboard
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


def send_otp_email(email, otp):
    """
    Send OTP to the specified email address.

    Args:
        email (str): Recipient email.
        otp (str): OTP to send.

    Returns:
        bool: True if email sent successfully, False otherwise.
    """
    from django.core.mail import send_mail
    subject = 'Your OTP Code - Audio Aura'
    message = f'Hello,\nYour OTP is: {otp}\nIt expires in 5 minutes.'
    try:
        send_mail(subject, message, 'your_email@gmail.com', [email])
        print(f"OTP {otp} sent to {email}") 
        return True
    except Exception as e:
        print(f'Error sending OTP: {e}')
        return False



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

    if send_otp_email(temp_user['email'], otp):
        messages.success(request, "New OTP sent successfully ✅")
    else:
        messages.error(request, "Failed to resend OTP. Try again ❌")

    return redirect('verify_otp')

def SignUp(request):
    
    # A) Capture referral code from URL
    ref_from_url = request.GET.get("ref")
    if ref_from_url:
        request.session["ref_code"] = ref_from_url

    if request.method == "POST":
        form = SignupForm(request.POST)

        if form.is_valid():

            # B) Referral code from FORM or URL
            ref_code = (
                form.cleaned_data.get('referral_code') 
                or request.session.get("ref_code")
            )

            # C) Generate OTP
            otp = generate_otp()

            # D) Store Temp User inside session for OTP page
            request.session['temp_user'] = {
                'first_name': form.cleaned_data['first_name'],
                'last_name': form.cleaned_data['last_name'],
                'email': form.cleaned_data['email'],
                'username': form.cleaned_data['email'],
                'password': form.cleaned_data['password'],
                'phone': form.cleaned_data.get('phone'),
                'otp': otp,
                'otp_expires': (timezone.now() + timedelta(minutes=5)).timestamp(),

                # FIXED 🔥 (backend gets referral code now)
                'ref_code': ref_code,
            }

            # E) Send OTP
            if send_otp_email(form.cleaned_data['email'], otp):
                messages.success(request, "OTP sent to your email ✅")
                return redirect('verify_otp')
            else:
                messages.error(request, "Failed to send OTP. Try again.")
                # fall through below

    else:
        form = SignupForm()

    return render(request, "user/sign_up.html", {"form": form})



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

            if send_otp_email(email, otp):
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
    if send_otp_email(user.email, otp):
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
    # ✅ Already logged-in user prevent login page access
    if request.user.is_authenticated:
        return redirect("home")  # or any page you want logged-in user to go
    
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
