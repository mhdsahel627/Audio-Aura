# coupons/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from .models import Coupon, DeliveryPincode
from .forms import CouponForm
from django.contrib import messages
from datetime import timedelta, date
from django.utils import timezone
from decimal import Decimal

# ============================================
# EXISTING ADMIN VIEWS (Keep as is)
# ============================================
from django.db.models import Count
from django.db.models import Q
from django.utils import timezone

@login_required(login_url='admin_login')
@never_cache
def coupon(request):
    """Display all coupons with filter and search"""
    
    status_filter = request.GET.get('status', 'all')
    search_query = request.GET.get('search', '').strip()
    
    coupons = Coupon.objects.all()
    
    if status_filter == 'active':
        coupons = coupons.filter(is_active=True)
    elif status_filter == 'inactive':
        coupons = coupons.filter(is_active=False)
    
    if search_query:
        coupons = coupons.filter(
            Q(code__icontains=search_query) |
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query)
        )
    
    # ✅ Show actual usage from CouponUsage table
    coupons = coupons.annotate(
        actual_usage=Count('usage_records')
    ).order_by('-id')
    
    context = {
        'coupons': coupons,
        'status_filter': status_filter,
        'search_query': search_query,
        'total_count': Coupon.objects.count(),
        'active_count': Coupon.objects.filter(is_active=True).count(),
        'inactive_count': Coupon.objects.filter(is_active=False).count(),
    }
    
    return render(request, 'admin/coupen.html', context)



@login_required(login_url='admin_login')
@never_cache
def add_coupon(request):
    """Add new coupon"""
    if request.method == 'POST':
        form = CouponForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Coupon added successfully!')
            return redirect('coupon')
        else:
            messages.error(request, 'Error adding coupon. Please check the form.')
    else:
        form = CouponForm()
    return render(request, 'admin/coupon_add.html', {'form': form})


@login_required(login_url='admin_login')
@never_cache
def edit_coupon(request, coupon_id):
    """Edit existing coupon"""
    coupon = get_object_or_404(Coupon, id=coupon_id)
    
    if request.method == 'POST':
        form = CouponForm(request.POST, instance=coupon)
        if form.is_valid():
            form.save()
            messages.success(request, 'Coupon updated successfully!')
            return redirect('coupon')
        else:
            messages.error(request, 'Error updating coupon. Please check the form.')
    else:
        form = CouponForm(instance=coupon)
    
    return render(request, 'admin/edit_coupon.html', {'form': form, 'coupon': coupon})


@login_required(login_url='admin_login')
@require_POST
def delete_coupon(request, coupon_id):
    """Delete coupon"""
    coupon = get_object_or_404(Coupon, id=coupon_id)
    
    # Check if AJAX request
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        coupon.delete()
        return JsonResponse({'success': True, 'message': 'Coupon deleted successfully'})
    
    # Regular POST request
    coupon.delete()
    messages.success(request, 'Coupon deleted successfully!')
    return redirect('coupon')


@login_required(login_url='admin_login')
@require_POST
def toggle_coupon_status(request, coupon_id):
    """Toggle coupon active/inactive status"""
    coupon = get_object_or_404(Coupon, id=coupon_id)
    
    # Toggle the status
    coupon.is_active = not coupon.is_active
    coupon.save()
    
    # Check if AJAX request
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'is_active': coupon.is_active,
            'message': f'Coupon {"activated" if coupon.is_active else "deactivated"} successfully'
        })
    
    # Regular POST request
    status = "activated" if coupon.is_active else "deactivated"
    messages.success(request, f'Coupon {status} successfully!')
    return redirect('coupon')


# ============================================
# ✅ NEW USER-FACING VIEWS (Add below)
# ============================================

@require_POST
def check_pincode(request):
    """Check if pincode is serviceable (User-facing)"""
    pincode = request.POST.get('pincode', '').strip()
    
    if len(pincode) != 6 or not pincode.isdigit():
        return JsonResponse({
            'success': False,
            'message': 'Please enter a valid 6-digit pincode'
        })
    
    try:
        pincode_data = DeliveryPincode.objects.get(pincode=pincode, is_serviceable=True)
        
        # Calculate delivery date
        delivery_date = timezone.now() + timedelta(days=pincode_data.delivery_days)
        
        # Store in session
        request.session['delivery_pincode'] = pincode
        request.session['delivery_city'] = pincode_data.city
        request.session['delivery_date'] = delivery_date.strftime('%A, %d %B')
        request.session['cod_available'] = pincode_data.is_cod_available
        
        return JsonResponse({
            'success': True,
            'pincode': pincode,
            'city': pincode_data.city,
            'delivery_date': delivery_date.strftime('%A, %d %B'),
            'delivery_days': pincode_data.delivery_days,
            'cod_available': pincode_data.is_cod_available,
            'message': f'Delivery available to {pincode_data.city}'
        })
        
    except DeliveryPincode.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Sorry, we do not deliver to this pincode yet.'
        })





