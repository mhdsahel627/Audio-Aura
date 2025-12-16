# views.py
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


def unauthenticated_user(view_func):
    def wrapper_func(request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('home')  # Redirect to homepage or dashboard
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

    u = request.user
    u.first_name = (request.POST.get('first_name') or u.first_name).strip()
    u.last_name  = (request.POST.get('last_name') or u.last_name).strip()

    profile, _ = Profile.objects.get_or_create(user=u)
    phone = (request.POST.get('phone') or '').strip()
    if phone:
        profile.phone = phone

    # Handle cropped JPEG if provided (preferred path from client)
    cropped_data = request.FILES.get('avatar_cropped')
    raw_avatar   = request.FILES.get('avatar')

    try:
        if cropped_data:
            # Accept only JPEG
            if cropped_data.content_type not in ('image/jpeg', 'image/pjpeg'):
                messages.error(request, "Only JPG format is allowed.")
                return redirect('profile')
            profile.avatar = cropped_data

        elif raw_avatar:
            # Strictly allow only JPG uploads if user bypassed crop
            if raw_avatar.content_type not in ('image/jpeg', 'image/pjpeg'):
                messages.error(request, "Only JPG format is allowed.")
                return redirect('profile')

            # Optional: normalize/strip EXIF by re-encoding to JPEG (safety)
            image = Image.open(raw_avatar)
            if image.mode in ('RGBA','P'):
                image = image.convert('RGB')
            buf = io.BytesIO()
            image.save(buf, format='JPEG', quality=90, optimize=True)
            buf.seek(0)
            dj_file = InMemoryUploadedFile(
                buf, field_name='ImageField', name=f"avatar_{get_random_string(8)}.jpg",
                content_type='image/jpeg', size=buf.getbuffer().nbytes, charset=None
            )
            profile.avatar = dj_file

        u.save()
        profile.save()
        messages.success(request, "Profile updated successfully.")
    except Exception:
        messages.error(request, "Failed to process image. Please upload a valid JPG.")
    return redirect('profile')


def _gen_email_otp():
    return f"{secrets.randbelow(10000):04d}"  

@login_required
@require_POST
def start_email_change(request):
    new_email = request.POST.get('new_email', '').strip().lower()
    if not new_email:
        return JsonResponse({'ok': False, 'error': 'Email required'}, status=400)
    if User.objects.filter(email=new_email).exclude(pk=request.user.pk).exists():
        return JsonResponse({'ok': False, 'error': 'Email already in use'}, status=400)

    profile, _ = Profile.objects.get_or_create(user=request.user)
    code = _gen_email_otp()
    profile.pending_email = new_email
    profile.pending_email_otp = code  # hash in production
    profile.pending_email_expires = timezone.now() + timedelta(minutes=5)
    profile.save()

    send_mail(
        'Confirm your new email',
        f'Your verification code is: {code}. It expires in 5 minutes.',
        getattr(settings, 'DEFAULT_FROM_EMAIL', None),
        [new_email],
        fail_silently=False,
    )
    return JsonResponse({'ok': True, 'pending_email': new_email})


@login_required
def email_change_otp_page(request):
    # Require pending_email to exist
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if not profile.pending_email:
        messages.error(request, "No email change in progress.")
        return redirect('profile')
    return render(request, 'user/emailvarify_otp.html', {'email': profile.pending_email})

def _wants_json(request):
    # If fetch/JS flow is used, prefer JSON; else redirect/messages for template flow
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.headers.get('Accept', '').startswith('application/json')

@login_required
def resend_email_change_otp(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if not profile.pending_email:
        messages.error(request, "No email change in progress.")
        return redirect('profile')

    code = _gen_email_otp()
    profile.pending_email_otp = code
    profile.pending_email_expires = timezone.now() + timedelta(minutes=5)
    profile.save()

    send_mail(
        'Confirm your new email',
        f'Your verification code is: {code}. It expires in 5 minutes.',
        getattr(settings, 'DEFAULT_FROM_EMAIL', None),
        [profile.pending_email],
        fail_silently=False,
    )
    messages.success(request, "OTP resent.")
    return redirect('email_change_otp_page')


@login_required
@require_POST
def verify_email_change(request):
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

    from django.db import transaction
    with transaction.atomic():
        request.user.email = new_email
        request.user.username = new_email  # critical for login
        request.user.save()

        profile.pending_email = None
        profile.pending_email_otp = None
        profile.pending_email_expires = None
        profile.save()

    messages.success(request, "Email updated. Use the new email to sign in next time.")
    return redirect('profile')


def _redirect_next_or(request, fallback_name):
    nxt = request.GET.get('next') or request.POST.get('next')
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect(fallback_name)


@login_required
def address_manage(request):
    addresses = Address.objects.filter(user=request.user)
    return render(request, 'user/address.html', {'addresses': addresses})

from django.shortcuts import render

@login_required
def address_create(request):
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
        messages.success(request, 'Address added.')
        return redirect('address')  # Or your success URL

    # On form errors, re-render template with form so errors show
    addresses = Address.objects.filter(user=request.user).order_by('-is_default', 'id')
    return render(request, 'user/address_manage.html', {
        'addresses': addresses,
        'form': form,
    })



@login_required
def address_update(request, pk):
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
        messages.success(request, 'Address updated.')
    else:
        messages.error(request, 'Please correct the errors in the form.')
    return _redirect_next_or(request, 'address')


@login_required
def address_delete(request, pk):
    if request.method != 'POST':
        return redirect('address_manage')
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    addr.delete()
    messages.success(request, 'Address deleted.')
    return _redirect_next_or(request, 'address')


@login_required
def address_make_default(request, pk):
    if request.method != 'POST':
        return redirect('address_manage')
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    with transaction.atomic():
        Address.objects.filter(user=request.user).update(is_default=False)
        addr.is_default = True
        addr.save(update_fields=['is_default'])
    messages.success(request, 'Default address set.')
    return _redirect_next_or(request, 'address')




@login_required
def password_change(request):
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

    # 4) Validate strength with Django’s validators (AUTH_PASSWORD_VALIDATORS)
    try:
        validate_password(new1, user=request.user)
    except Exception as e:
        # Collect validator messages
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

    # 7) Keep user logged in OR force re-login
    # Option A: keep session alive
    update_session_auth_hash(request, request.user)
    messages.success(request, "Password updated successfully.")
    return redirect('password_change')
@login_required
def generate_otp():
    # Returns a 4-digit random OTP as a string
    return f"{secrets.randbelow(10000):04d}"

def send_otp_email(email, otp):
    subject = "Your Password Reset OTP"
    message = f"Your OTP for password reset is: {otp}. It expires in 5 minutes."
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
    try:
        send_mail(subject, message, from_email, [email], fail_silently=False)
        return True
    except Exception:
        return False
@login_required
def  forgot_password(request):
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
    return render(request, 'user/password_forget.html')

@login_required
def password_reset_otp(request):
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

