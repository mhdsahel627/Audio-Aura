# user/views.py

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from .models import Address
from .forms import AddressForm, ForgotPasswordForm, ResetPasswordForm
from .models import Profile  
import secrets
from django.utils import timezone
from datetime import timedelta
from django.views.decorators.http import require_POST
from django.core.mail import send_mail
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.hashers import check_password
from django.contrib.auth import update_session_auth_hash
from PIL import Image
import io
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.utils.crypto import get_random_string
from django.utils.http import url_has_allowed_host_and_scheme
import re

# 🔥 IMPORT DYNAMIC EMAIL FUNCTION
from registration.views import send_dynamic_otp_email  # Adjust import path if needed


def unauthenticated_user(view_func):
    def wrapper_func(request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('home')
        else:
            return view_func(request, *args, **kwargs)
    return wrapper_func


@login_required
def profile(request):
    user = request.user
    try:
        profile = Profile.objects.get(user=user)
    except Profile.DoesNotExist:
        profile = None
    return render(request, 'user/profile.html', {'user': user, 'profile': profile})


@login_required
def profile_update(request):
    if request.method != 'POST':
        return redirect('profile')

    errors = {}
    u = request.user
    
    # Get form data
    first_name = (request.POST.get('first_name') or '').strip()
    last_name = (request.POST.get('last_name') or '').strip()
    phone = (request.POST.get('phone') or '').strip()
    
    # === VALIDATION ===
    
    # 1. First Name Validation
    if not first_name:
        errors['first_name'] = 'First name is required'
    elif len(first_name) < 2:
        errors['first_name'] = 'First name must be at least 2 characters'
    elif len(first_name) > 50:
        errors['first_name'] = 'First name cannot exceed 50 characters'
    elif not re.match(r'^[a-zA-Z\s]+$', first_name):
        errors['first_name'] = 'First name can only contain letters and spaces'
    
    # 2. Last Name Validation
    if not last_name:
        errors['last_name'] = 'Last name is required'
    elif len(last_name) < 2:
        errors['last_name'] = 'Last name must be at least 2 characters'
    elif len(last_name) > 50:
        errors['last_name'] = 'Last name cannot exceed 50 characters'
    elif not re.match(r'^[a-zA-Z\s]+$', last_name):
        errors['last_name'] = 'Last name can only contain letters and spaces'
    
    # 3. Phone Validation (Optional but if provided must be valid)
    if phone:
        phone_cleaned = re.sub(r'[\s\-]', '', phone)
        
        if not re.match(r'^\+?[0-9]{10,15}$', phone_cleaned):
            errors['phone'] = 'Phone number must be 10-15 digits (optionally starting with +)'
        elif len(phone_cleaned) < 10:
            errors['phone'] = 'Phone number must be at least 10 digits'
        elif len(phone_cleaned) > 15:
            errors['phone'] = 'Phone number cannot exceed 15 digits'
    
    # 4. Avatar Validation
    cropped_data = request.FILES.get('avatar_cropped')
    raw_avatar = request.FILES.get('avatar')
    
    max_file_size = 5 * 1024 * 1024  # 5MB
    allowed_types = ['image/jpeg', 'image/jpg', 'image/pjpeg']
    
    avatar_to_process = None
    
    if cropped_data:
        if cropped_data.content_type not in allowed_types:
            errors['avatar'] = 'Only JPG/JPEG format is allowed'
        elif cropped_data.size > max_file_size:
            errors['avatar'] = f'Image size must be less than 5MB (current: {cropped_data.size / 1024 / 1024:.1f}MB)'
        else:
            avatar_to_process = cropped_data
    
    elif raw_avatar:
        if raw_avatar.content_type not in allowed_types:
            errors['avatar'] = 'Only JPG/JPEG format is allowed'
        elif raw_avatar.size > max_file_size:
            errors['avatar'] = f'Image size must be less than 5MB (current: {raw_avatar.size / 1024 / 1024:.1f}MB)'
        else:
            avatar_to_process = raw_avatar
    
    # If there are validation errors, return to profile with errors
    if errors:
        for field, error in errors.items():
            messages.error(request, f"{field.replace('_', ' ').title()}: {error}")
        
        profile, _ = Profile.objects.get_or_create(user=u)
        return render(request, 'user/profile.html', {
            'user': u,
            'profile': profile,
            'errors': errors,
            'form_data': {
                'first_name': first_name,
                'last_name': last_name,
                'phone': phone,
            }
        })
    
    # === SAVE CHANGES (No errors) ===
    try:
        u.first_name = first_name
        u.last_name = last_name
        u.save()
        
        profile, _ = Profile.objects.get_or_create(user=u)
        if phone:
            profile.phone = phone
        
        if avatar_to_process:
            if cropped_data:
                profile.avatar = cropped_data
            elif raw_avatar:
                try:
                    image = Image.open(raw_avatar)
                    if image.mode in ('RGBA', 'P'):
                        image = image.convert('RGB')
                    
                    max_dimension = 1024
                    if image.width > max_dimension or image.height > max_dimension:
                        image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
                    
                    buf = io.BytesIO()
                    image.save(buf, format='JPEG', quality=90, optimize=True)
                    buf.seek(0)
                    
                    dj_file = InMemoryUploadedFile(
                        buf,
                        field_name='ImageField',
                        name=f"avatar_{get_random_string(8)}.jpg",
                        content_type='image/jpeg',
                        size=buf.getbuffer().nbytes,
                        charset=None
                    )
                    profile.avatar = dj_file
                except Exception as e:
                    messages.error(request, f"Failed to process image: {str(e)}")
                    return redirect('profile')
        
        profile.save()
        messages.success(request, "✅ Profile updated successfully!")
        
    except Exception as e:
        messages.error(request, f"❌ Failed to update profile: {str(e)}")
    
    return redirect('profile')


def _gen_email_otp():
    """Generate 4-digit OTP"""
    return f"{secrets.randbelow(10000):04d}"


# ========== EMAIL CHANGE FLOW ==========

@login_required
@require_POST
def start_email_change(request):
    """Start email change process with OTP verification"""
    new_email = request.POST.get('new_email', '').strip().lower()
    if not new_email:
        return JsonResponse({'ok': False, 'error': 'Email required'}, status=400)
    if User.objects.filter(email=new_email).exclude(pk=request.user.pk).exists():
        return JsonResponse({'ok': False, 'error': 'Email already in use'}, status=400)

    profile, _ = Profile.objects.get_or_create(user=request.user)
    code = _gen_email_otp()
    profile.pending_email = new_email
    profile.pending_email_otp = code
    profile.pending_email_expires = timezone.now() + timedelta(minutes=5)
    profile.save()

    # 🔥 SEND DYNAMIC EMAIL - EMAIL CHANGE
    username = request.user.get_full_name() or request.user.username
    if send_dynamic_otp_email(
        email=new_email,
        otp=code,
        email_type='email_change',
        username=username
    ):
        return JsonResponse({'ok': True, 'pending_email': new_email})
    else:
        return JsonResponse({'ok': False, 'error': 'Failed to send OTP'}, status=500)


@login_required
def email_change_otp_page(request):
    """Render OTP verification page for email change"""
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if not profile.pending_email:
        messages.error(request, "No email change in progress.")
        return redirect('profile')
    return render(request, 'user/emailvarify_otp.html', {'email': profile.pending_email})


def _wants_json(request):
    """Check if request expects JSON response"""
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Accept', '').startswith('application/json')


@login_required
def resend_email_change_otp(request):
    """Resend OTP for email change"""
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if not profile.pending_email:
        messages.error(request, "No email change in progress.")
        return redirect('profile')

    code = _gen_email_otp()
    profile.pending_email_otp = code
    profile.pending_email_expires = timezone.now() + timedelta(minutes=5)
    profile.save()

    # 🔥 SEND DYNAMIC EMAIL - EMAIL CHANGE RESEND
    username = request.user.get_full_name() or request.user.username
    if send_dynamic_otp_email(
        email=profile.pending_email,
        otp=code,
        email_type='email_change',
        username=username
    ):
        messages.success(request, "OTP resent ✅")
    else:
        messages.error(request, "Failed to resend OTP ❌")
    
    return redirect('email_change_otp_page')


@login_required
@require_POST
def verify_email_change(request):
    """Verify OTP and complete email change"""
    code = (request.POST.get('otp') or '').strip()
    if len(code) != 4 or not code.isdigit():
        messages.error(request, "Enter the 4-digit code.")
        return redirect('email_change_otp_page')

    profile, _ = Profile.objects.get_or_create(user=request.user)
    if not profile.pending_email or not profile.pending_email_otp or not profile.pending_email_expires:
        messages.error(request, "No email change requested.")
        return redirect('profile')

    if timezone.now() > profile.pending_email_expires:
        profile.pending_email = None
        profile.pending_email_otp = None
        profile.pending_email_expires = None
        profile.save()
        messages.error(request, "Code expired. Please start again.")
        return redirect('email_change_otp_page')

    if code != profile.pending_email_otp:
        messages.error(request, "Invalid code.")
        return redirect('email_change_otp_page')

    new_email = profile.pending_email

    # Defensive uniqueness checks
    if User.objects.filter(username=new_email).exclude(pk=request.user.pk).exists():
        messages.error(request, "That email is already used as a login.")
        return redirect('email_change_otp_page')
    if User.objects.filter(email=new_email).exclude(pk=request.user.pk).exists():
        messages.error(request, "That email is already in use.")
        return redirect('email_change_otp_page')

    with transaction.atomic():
        request.user.email = new_email
        request.user.username = new_email
        request.user.save()

        profile.pending_email = None
        profile.pending_email_otp = None
        profile.pending_email_expires = None
        profile.save()

    messages.success(request, "Email updated successfully ✅")
    return redirect('profile')


def _redirect_next_or(request, fallback_name):
    """Redirect to 'next' parameter or fallback"""
    nxt = request.GET.get('next') or request.POST.get('next')
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect(fallback_name)


# ========== ADDRESS MANAGEMENT ==========

@login_required
def address_manage(request):
    """List all user addresses"""
    addresses = Address.objects.filter(user=request.user)
    return render(request, 'user/address.html', {'addresses': addresses})


@login_required
def address_create(request):
    """Create new address"""
    if request.method != 'POST':
        return redirect('address')

    form = AddressForm(request.POST)
    if form.is_valid():
        addr = form.save(commit=False)
        addr.user = request.user
        with transaction.atomic():
            addr.save()
            if addr.is_default:
                Address.objects.filter(user=request.user).exclude(id=addr.id).update(is_default=False)
        messages.success(request, 'Address added ✅')
        return redirect('address')

    addresses = Address.objects.filter(user=request.user).order_by('-is_default', 'id')
    return render(request, 'user/address_manage.html', {
        'addresses': addresses,
        'form': form,
    })


@login_required
def address_update(request, pk):
    """Update existing address"""
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    if request.method != 'POST':
        return redirect('address_manage')
    form = AddressForm(request.POST, instance=addr)
    if form.is_valid():
        addr = form.save(commit=False)
        with transaction.atomic():
            addr.save()
            if addr.is_default:
                Address.objects.filter(user=request.user).exclude(id=addr.id).update(is_default=False)
        messages.success(request, 'Address updated ✅')
    else:
        messages.error(request, 'Please correct the errors in the form.')
    return _redirect_next_or(request, 'address')


@login_required
def address_delete(request, pk):
    """Delete address"""
    if request.method != 'POST':
        return redirect('address_manage')
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    addr.delete()
    messages.success(request, 'Address deleted ✅')
    return _redirect_next_or(request, 'address')


@login_required
def address_make_default(request, pk):
    """Set address as default"""
    if request.method != 'POST':
        return redirect('address_manage')
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    with transaction.atomic():
        Address.objects.filter(user=request.user).update(is_default=False)
        addr.is_default = True
        addr.save(update_fields=['is_default'])
    messages.success(request, 'Default address set ✅')
    return _redirect_next_or(request, 'address')


# ========== PASSWORD CHANGE (LOGGED IN USER) ==========

@login_required
def password_change(request):
    """Change password for logged-in user"""
    if request.method == 'GET':
        return render(request, 'user/password_change.html')

    # POST
    current = (request.POST.get('current_password') or '').strip()
    new1 = (request.POST.get('new_password') or '').strip()
    new2 = (request.POST.get('confirm_password') or '').strip()

    # 1) Basic presence
    if not current or not new1 or not new2:
        messages.error(request, "Please fill all password fields.")
        return redirect('password_change')

    # 2) Verify current password
    if not request.user.check_password(current):
        messages.error(request, "Current password is incorrect.")
        return redirect('password_change')

    # 3) Confirm match
    if new1 != new2:
        messages.error(request, "New passwords do not match.")
        return redirect('password_change')

    # 4) Validate strength with Django's validators
    try:
        validate_password(new1, user=request.user)
    except Exception as e:
        for err in e.error_list:
            messages.error(request, err.messages[0])
        return redirect('password_change')

    # 5) Prevent reusing same password
    if check_password(new1, request.user.password):
        messages.error(request, "New password cannot be the same as the current one.")
        return redirect('password_change')

    # 6) Commit change
    request.user.set_password(new1)
    request.user.save()

    # 7) Keep user logged in
    update_session_auth_hash(request, request.user)
    messages.success(request, "Password updated successfully ✅")
    return redirect('password_change')


# ========== PASSWORD RESET FLOW (FORGOT PASSWORD - LOGGED IN) ==========
# Note: This seems to be for logged-in users who forgot their password
# Typically "forgot password" is for non-authenticated users
# But keeping your logic as-is

def generate_otp():
    """Generate 4-digit OTP"""
    return f"{secrets.randbelow(10000):04d}"


def send_otp_email(email, otp):
    """
    DEPRECATED: Use send_dynamic_otp_email instead
    Keeping for backward compatibility
    """
    subject = "Your Password Reset OTP"
    message = f"Your OTP for password reset is: {otp}. It expires in 5 minutes."
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
    try:
        send_mail(subject, message, from_email, [email], fail_silently=False)
        return True
    except Exception:
        return False


@login_required
def forgot_password(request):
    """
    Forgot password flow for logged-in users
    (Typically this would be for unauthenticated users)
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
    return render(request, 'user/password_forget.html')


@login_required
def password_reset_otp(request):
    """Verify OTP for password reset"""
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

    return render(request, 'user/verify_reset_otp.html', {'email': User.objects.get(id=reset_user['user_id']).email})


@login_required
def password_reset(request):
    """Reset password after OTP verification"""
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
            return redirect('password_change')
    else:
        form = ResetPasswordForm()
    return render(request, 'user/password_reset.html')
