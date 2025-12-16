from category.models import Category
from wishlist.models import WishlistItem
from cart.views import CART_SESSION_KEY 
from coupons.models import Coupon
from orders.models import Order  


def global_categories(request):
    """Make categories available to all templates"""
    return {
        'categories': Category.objects.filter(is_active=True).order_by('name')
    }
    
def _session_cart_product_count(request):
    """
    Count distinct product lines in the session cart, not total qty.
    """
    cart_map = request.session.get(CART_SESSION_KEY, {})
    count = 0
    for lines in cart_map.values():
        if isinstance(lines, list):
            # each dict in the list is a separate line (product+variant)
            count += len(lines)
        else:
            # legacy single-qty entry treated as one product
            if int(lines or 0) > 0:
                count += 1
    return count

def header_counts(request):
    cart_count = _session_cart_product_count(request)

    wishlist_count = 0
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        wishlist_count = WishlistItem.objects.filter(
            wishlist__user=user
        ).count()

    return {
        "cart_count": cart_count,
        "wishlist_count": wishlist_count,
    }


from orders.models import Order

def welcome_banner(request):
    """
    Show banner if user has never placed a successful order.
    Guests always see it.
    """
    user = getattr(request, "user", None)
    is_guest = not (user and user.is_authenticated)

    # Guests: always show
    if is_guest:
        return {"show_welcome_banner": True}

    # Logged‑in: has any non‑pending, non‑failed order?
    has_real_order = Order.objects.filter(
        user=user
    ).exclude(
        status__in=["PENDING", "FAILED"]
    ).exists()

    return {"show_welcome_banner": not has_real_order}