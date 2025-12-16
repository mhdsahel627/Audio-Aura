from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from .models import Wishlist, WishlistItem
from products.models import ProductVariant
from cart.views import add_to_cart


@login_required
def wishlist_list(request):
    """Display user's wishlist with optimized queries"""
    wishlist, created = Wishlist.objects.get_or_create(user=request.user)
    items = wishlist.items.select_related(
        'variant', 
        'variant__product',
        'variant__product__category',
        'variant__product__brand'
    ).prefetch_related(
        'variant__images',           # ✅ Prefetch variant images
        'variant__product__images'   # ✅ Fallback to product images
    ).all()
    
    context = {
        'wishlist_items': items,
    }
    return render(request, 'user/wishlist.html', context)


# ✅ NEW: Toggle wishlist (AJAX) - Add or Remove
@login_required
@require_http_methods(["POST"])
def toggle_wishlist(request, variant_id):
    """
    Toggle wishlist: Add if not present, Remove if already in wishlist.
    Returns JSON response for AJAX handling.
    Works like Flipkart - single button toggles add/remove.
    """
    try:
        variant = get_object_or_404(ProductVariant, id=variant_id)
        wishlist, created = Wishlist.objects.get_or_create(user=request.user)
        
        # Check if variant already in wishlist
        wishlist_item = wishlist.items.filter(variant=variant).first()
        
        if wishlist_item:
            # Remove from wishlist
            wishlist_item.delete()
            return JsonResponse({
                'success': True,
                'action': 'removed',
                'message': 'Removed from wishlist',
                'in_wishlist': False
            })
        else:
            # Add to wishlist
            WishlistItem.objects.create(wishlist=wishlist, variant=variant)
            return JsonResponse({
                'success': True,
                'action': 'added',
                'message': 'Added to wishlist',
                'in_wishlist': True
            })
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=400)


# ✅ NEW: Check if variant is in wishlist (for initial page load)
@login_required
@require_http_methods(["GET"])
def check_wishlist(request, variant_id):
    """
    Check if a specific variant is in user's wishlist.
    Returns JSON response for AJAX.
    Used to set initial heart icon state on page load.
    """
    try:
        wishlist = Wishlist.objects.filter(user=request.user).first()
        
        if not wishlist:
            return JsonResponse({'in_wishlist': False})
        
        in_wishlist = wishlist.items.filter(variant_id=variant_id).exists()
        
        return JsonResponse({'in_wishlist': in_wishlist})
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=400)


# ✅ Keep existing fallback view for non-AJAX requests
@login_required
def add_to_wishlist(request, variant_id):
    """
    Legacy add to wishlist (non-AJAX fallback).
    Redirects to wishlist page after adding.
    """
    user = request.user
    variant = get_object_or_404(ProductVariant, id=variant_id)
    wishlist, created = Wishlist.objects.get_or_create(user=user)
    
    # Add variant only if not already in wishlist
    if not wishlist.items.filter(variant=variant).exists():
        WishlistItem.objects.create(wishlist=wishlist, variant=variant)
    
    return redirect('wishlist:list')


@login_required
def remove_from_wishlist(request, item_id):
    """Remove a specific item from wishlist"""
    wishlist = get_object_or_404(Wishlist, user=request.user)
    item = get_object_or_404(WishlistItem, id=item_id, wishlist=wishlist)
    
    if request.method == "POST":
        item.delete()
    
    return redirect('wishlist:list')


@login_required
def empty_wishlist(request):
    """Clear all items from user's wishlist"""
    wishlist = get_object_or_404(Wishlist, user=request.user)
    
    if request.method == "POST":
        wishlist.items.all().delete()
    
    return redirect('wishlist:list')


@login_required
@require_POST
def add_wishlist_item_to_cart(request, item_id):
    """
    Add a wishlist item to cart and remove from wishlist.
    Reuses existing add_to_cart logic.
    """
    wishlist = get_object_or_404(Wishlist, user=request.user)
    item = get_object_or_404(WishlistItem, id=item_id, wishlist=wishlist)
    
    # Prepare POST-like data for calling your cart add logic
    # Create a mutable copy of request.POST
    mutable_post = request.POST.copy()
    mutable_post['product_id'] = str(item.variant.product.id)
    mutable_post['variant_id'] = str(item.variant.id)
    mutable_post['quantity'] = '1'
    
    # Manually assign to request.POST to simulate a form POST
    request.POST = mutable_post

    # Call your existing add_to_cart view logic
    response = add_to_cart(request)

    # On success, remove item from wishlist
    if response.status_code == 302:  # Redirect status indicating success
        item.delete()
    
    return response
