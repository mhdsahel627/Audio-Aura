# cart/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.cache import never_cache
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Prefetch
from django.utils import timezone
from category.models import Category
from coupons.models import Coupon
from datetime import date, datetime, timedelta
from decimal import Decimal

from products.models import (
    Product,
    ProductImage,
    ProductVariant,
    ProductVariantImage,
)


# ==================== SESSION CONFIGURATION ====================
CART_SESSION_KEY = "cart"
BUY_NOW_SESSION_KEY = "buy_now_line"
CHECKOUT_SESSION_KEY = "checkout_started_at"
LAST_ACTIVITY_KEY = "last_checkout_activity"

MAX_QTY_PER_LINE = 10  # Max quantity per product line
CHECKOUT_SESSION_TIMEOUT = 1800  # 30 minutes in seconds (industry standard)
CART_SESSION_TIMEOUT = 2592000  # 30 days for regular cart


# ==================== SESSION TIMEOUT HELPERS ====================

def _is_checkout_session_expired(request):
    """Check if checkout session has expired (30 min inactivity)"""
    if LAST_ACTIVITY_KEY not in request.session:
        return False
    
    last_activity = request.session.get(LAST_ACTIVITY_KEY)
    if isinstance(last_activity, str):
        last_activity = datetime.fromisoformat(last_activity)
    
    elapsed = (timezone.now() - last_activity).total_seconds()
    return elapsed > CHECKOUT_SESSION_TIMEOUT


def _update_checkout_activity(request):
    """Update last checkout activity timestamp"""
    request.session[LAST_ACTIVITY_KEY] = timezone.now().isoformat()
    request.session.modified = True


def _clear_expired_checkout_session(request):
    """Clear expired checkout data (buy_now, checkout flags)"""
    if _is_checkout_session_expired(request):
        if BUY_NOW_SESSION_KEY in request.session:
            del request.session[BUY_NOW_SESSION_KEY]
        if CHECKOUT_SESSION_KEY in request.session:
            del request.session[CHECKOUT_SESSION_KEY]
        if LAST_ACTIVITY_KEY in request.session:
            del request.session[LAST_ACTIVITY_KEY]
        if 'checkout_ready' in request.session:
            del request.session['checkout_ready']
        # Clear coupon after timeout (best practice)
        if 'applied_coupon' in request.session:
            del request.session['applied_coupon']
        if 'applied_coupon_discount' in request.session:
            del request.session['applied_coupon_discount']
        request.session.modified = True
        return True
    return False


# ==================== STOCK & CART HELPERS ====================

def _available_stock(product, vkey):
    """Get available stock for product or variant"""
    try:
        if vkey:
            v = ProductVariant.objects.only("id", "stock").get(id=vkey, product_id=product.id)
            return max(0, int(v.stock or 0))
        return max(0, int(product.stock_quantity or 0))
    except ProductVariant.DoesNotExist:
        return 0


def _get_session_cart(request):
    """
    Get cart from session
    Cart shape: {
      "39": [{"qty": 2, "variant_id": "102"}, {"qty": 1, "variant_id": "103"}],
      "41": [{"qty": 1, "variant_id": null}],
    }
    """
    return request.session.get(CART_SESSION_KEY, {})


def _set_session_cart(request, cart):
    """Save cart to session with proper timeout"""
    request.session[CART_SESSION_KEY] = cart
    request.session.set_expiry(CART_SESSION_TIMEOUT)  # 30 days for cart
    request.session.modified = True


def _iter_cart_lines(session_cart):
    """Iterate cart as (product_id:int, qty:int, variant_id:str|None)"""
    for pid_str, node in session_cart.items():
        if isinstance(node, list):
            for line in node:
                yield int(pid_str), int(line.get("qty", 0)), line.get("variant_id")
        else:
            # Legacy single-qty path
            yield int(pid_str), int(node), None


def _sum_items(session_cart):
    """Count total items in cart"""
    total = 0
    for lines in session_cart.values():
        if isinstance(lines, list):
            total += sum(int(l.get("qty", 0)) for l in lines)
        else:
            total += int(lines)
    return total


def _validate_cart_items(request):
    """Remove out-of-stock or invalid items from cart"""
    cart_map = _get_session_cart(request)
    cleaned = False
    
    for pid_str in list(cart_map.keys()):
        try:
            product = Product.objects.get(id=pid_str, is_listed=True)
            node = cart_map[pid_str]
            
            if isinstance(node, list):
                valid_lines = []
                for line in node:
                    vid = line.get("variant_id")
                    stock = _available_stock(product, vid)
                    if stock > 0:
                        # Cap quantity to available stock
                        line["qty"] = min(int(line.get("qty", 1)), stock, MAX_QTY_PER_LINE)
                        valid_lines.append(line)
                    else:
                        cleaned = True
                
                if valid_lines:
                    cart_map[pid_str] = valid_lines
                else:
                    del cart_map[pid_str]
                    cleaned = True
            else:
                stock = _available_stock(product, None)
                if stock <= 0:
                    del cart_map[pid_str]
                    cleaned = True
                    
        except Product.DoesNotExist:
            del cart_map[pid_str]
            cleaned = True
    
    if cleaned:
        _set_session_cart(request, cart_map)
    
    return cleaned



# ==================== BUY NOW (DIRECT CHECKOUT) ====================

@login_required
@require_POST
@never_cache
def buy_now(request):
    """Instant checkout for single product"""
    # Clear any expired checkout session first
    _clear_expired_checkout_session(request)
    
    product_id = request.POST.get('product_id')
    variant_id = request.POST.get('variant_id') or None
    qty = int(request.POST.get('quantity') or 1)
    qty = max(1, min(qty, MAX_QTY_PER_LINE))

    if not product_id:
        messages.error(request, "Missing product.")
        return redirect('shop')

    # Validate product and variant
    product = get_object_or_404(Product, id=product_id, is_listed=True)
    vkey = str(variant_id) if variant_id else None
    
    if product.variants.exists():
        if not vkey:
            dv = product.variants.filter(is_default=True).first() or product.variants.order_by("id").first()
            vkey = str(dv.id) if dv else None
        else:
            get_object_or_404(ProductVariant, id=vkey, product_id=product.id)

    # Check stock
    stock = _available_stock(product, vkey)
    if stock <= 0:
        messages.error(request, "Product is out of stock")
        return redirect('product_detail', pk=product_id)
    
    qty = min(qty, stock)

    # Store buy-now line in session
    request.session[BUY_NOW_SESSION_KEY] = {
        "product_id": str(product.id),
        "variant_id": vkey,
        "qty": qty,
    }
    request.session[CHECKOUT_SESSION_KEY] = timezone.now().isoformat()
    _update_checkout_activity(request)

    return redirect('checkout')


@never_cache
@login_required
@require_POST
def buy_now_update_qty(request):
    """Update buy-now quantity + auto-validate coupon"""
    try:
        new_qty = int(request.POST.get('quantity', '1'))
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid quantity'}, status=400)

    # Check session expiry
    if _clear_expired_checkout_session(request):
        return JsonResponse({
            'success': False, 
            'error': 'Session expired',
            'expired': True
        }, status=440)

    line = request.session.get(BUY_NOW_SESSION_KEY)
    if not line:
        return JsonResponse({'success': False, 'error': 'No buy-now line'}, status=404)

    # Validate stock
    pid = line.get('product_id')
    vid = line.get('variant_id')
    
    try:
        product = Product.objects.get(id=pid, is_listed=True)
        max_stock = _available_stock(product, vid)
        
        if max_stock <= 0:
            return JsonResponse({
                'success': False, 
                'error': 'OUT_OF_STOCK'
            }, status=409)
        
    except Product.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Product not found'}, status=404)

    # Cap quantity
    new_qty = max(1, min(new_qty, max_stock, MAX_QTY_PER_LINE))
    
    # Update session
    line['qty'] = new_qty
    request.session[BUY_NOW_SESSION_KEY] = line
    _update_checkout_activity(request)

    # ✅ NEW: Auto-validate coupon
    coupon_removed = _auto_validate_buynow_coupon(request, line)

    # Recalculate summary
    s = _buy_now_summary(request) or {}
    
    # ✅ FIX: Extract values properly
    subtotal_sell = s.get('subtotal_sell', 0)
    subtotal_mrp = s.get('subtotal_mrp', 0)
    discount = s.get('discount', 0)
    coupon_discount = s.get('coupon_discount', 0)
    total_payable = s.get('total_payable', 0)
    save_note = s.get('save_note', 0)
    
    response_data = {
        'success': True,
        'qty': new_qty,
        'max_qty': min(max_stock, MAX_QTY_PER_LINE),
        'subtotal_sell': str(subtotal_sell),
        'subtotal_mrp': str(subtotal_mrp),
        'discount': str(discount),
        'coupon_discount': str(coupon_discount),
        'total_payable': str(total_payable),
        'save_note': str(save_note),
    }
    
    # ✅ Notify if coupon was removed
    if coupon_removed:
        response_data['coupon_removed'] = True
        response_data['coupon_message'] = coupon_removed
    
    return JsonResponse(response_data)



def _buy_now_summary(request):
    """Calculate buy-now summary with pricing"""
    line = request.session.get(BUY_NOW_SESSION_KEY)
    if not line:
        return {}

    pid = line.get('product_id')
    vid = line.get('variant_id')
    qty = int(line.get('qty') or 1)

    # Load product/variant with images
    p = Product.objects.filter(id=pid, is_listed=True).prefetch_related(
        Prefetch(
            'images',
            queryset=ProductImage.objects.order_by("-featured", "id"),
            to_attr="prefetched_images"
        )
    ).first()

    if not p:
        return {}

    v = None
    variant_image_url = None
    if vid:
        v = ProductVariant.objects.filter(id=vid, product_id=pid).prefetch_related(
            Prefetch(
                'images',
                queryset=ProductVariantImage.objects.order_by("-featured", "id")[:1],
                to_attr="first_image"
            )
        ).first()
        if v and getattr(v, 'first_image', None):
            vf = v.first_image[0] if v.first_image else None
            if vf and getattr(vf, "image", None):
                variant_image_url = vf.image.url

    # Pricing
    unit_sell = (
        p.get_final_price() if hasattr(p, "get_final_price") and callable(p.get_final_price)
        else p.discount_price or p.base_price
    )
    unit_mrp = p.base_price

    line_sell = int(unit_sell * qty)
    line_mrp = int(unit_mrp * qty)
    discount_percent = round(100 * (unit_mrp - unit_sell) / unit_mrp, 0) if unit_mrp else 0
    image_url = variant_image_url or (p.prefetched_images[0].image.url if getattr(p, 'prefetched_images', None) and p.prefetched_images else None)

    coupon_discount = Decimal(str(request.session.get('applied_coupon_discount', '0')))
    total_payable = int(max(line_sell - coupon_discount, 0))
    discount = int(max(line_mrp - line_sell, 0))
    save_note = int(discount + coupon_discount)

    return {
        'items': [{
            'id': p.id,
            'name': p.name,
            'variant_id': vid,
            'qty': qty,
            'unit_sell': int(unit_sell),
            'unit_mrp': int(unit_mrp),
            'line_sell': line_sell,
            'line_mrp': line_mrp,
            'discount_percent': int(discount_percent),
            'image': image_url,
        }],
        'subtotal_sell': line_sell,
        'subtotal_mrp': line_mrp,
        'discount': discount,
        'coupon_discount': int(coupon_discount),
        'total_payable': total_payable,
        'save_note': save_note,
        'products_count': 1
    }

def _auto_validate_buynow_coupon(request, buy_now_line):
    """
    Auto-validate applied coupon for buy_now after quantity change.
    Returns removal message if coupon was removed, None otherwise.
    """
    applied_coupon_code = request.session.get('applied_coupon')
    
    if not applied_coupon_code:
        return None  # No coupon applied
    
    try:
        coupon = Coupon.objects.get(
            code=applied_coupon_code,
            is_active=True,
            expiry_date__gte=date.today()
        )
        
        # Get buy_now totals
        ctx = _buy_now_summary(request)
        subtotal = Decimal(str(ctx.get('subtotal_sell', 0)))
        total_quantity = ctx.get('items', [{}])[0].get('qty', 1)
        
        # Check if coupon still eligible
        eligible, message = coupon.check_eligibility(total_quantity, subtotal)
        
        if not eligible:
            # ❌ Coupon no longer valid - REMOVE IT
            if 'applied_coupon' in request.session:
                del request.session['applied_coupon']
            if 'applied_coupon_discount' in request.session:
                del request.session['applied_coupon_discount']
            if 'applied_coupon_id' in request.session:
                del request.session['applied_coupon_id']
            request.session.modified = True
            
            return f"Coupon {applied_coupon_code} removed: {message}"
        
        # ✅ Still eligible - recalculate discount
        discount = coupon.calculate_discount(subtotal)
        request.session['applied_coupon_discount'] = str(discount)
        request.session.modified = True
        
        return None  # Coupon still valid
        
    except Coupon.DoesNotExist:
        # Coupon expired/deleted - remove from session
        if 'applied_coupon' in request.session:
            del request.session['applied_coupon']
        if 'applied_coupon_discount' in request.session:
            del request.session['applied_coupon_discount']
        if 'applied_coupon_id' in request.session:
            del request.session['applied_coupon_id']
        request.session.modified = True
        
        return f"Coupon {applied_coupon_code} expired or invalid"


# ==================== CART MANAGEMENT ====================
@never_cache
@require_POST
def add_to_cart(request):
    """Add or merge product+variant into cart"""
    pid = request.POST.get("product_id")
    qty_str = request.POST.get("quantity", "1")
    variant_id = request.POST.get("variant_id")

    if not pid:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "error": "Missing product_id"}, status=400)
        return redirect("cart")

    # Validate product
    product = get_object_or_404(Product, id=pid, is_listed=True)

    # Parse quantity
    try:
        qty = max(1, int(qty_str))
    except (TypeError, ValueError):
        qty = 1

    # Resolve variant
    vkey = str(variant_id) if variant_id else None
    if product.variants.exists():
        if not vkey:
            dv = product.variants.filter(is_default=True).first() or product.variants.order_by("id").first()
            vkey = str(dv.id) if dv else None
        else:
            try:
                ProductVariant.objects.only("id").get(id=vkey, product_id=product.id)
            except ProductVariant.DoesNotExist:
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({"ok": False, "error": "Invalid variant"}, status=404)
                return redirect("cart")

    # Check stock
    allowed_cap = min(MAX_QTY_PER_LINE, _available_stock(product, vkey))
    if allowed_cap <= 0:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "error": "OUT_OF_STOCK"}, status=409)
        messages.error(request, "Out of stock")
        return redirect("cart")

    # Update cart
    cart_map = _get_session_cart(request)
    node = cart_map.get(str(product.id))
    if not isinstance(node, list):
        node = [] if node is None else [{"qty": int(node) or 1, "variant_id": None}]
        cart_map[str(product.id)] = node

    # Merge or append
    merged = False
    for line in node:
        if str(line.get("variant_id")) == str(vkey):
            new_qty = min(int(line.get("qty", 0)) + qty, allowed_cap)
            line["qty"] = new_qty
            merged = True
            break
    if not merged:
        node.append({"qty": min(qty, allowed_cap), "variant_id": vkey})

    _set_session_cart(request, cart_map)

    total_items = _sum_items(cart_map)
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({
            "ok": True,
            "items": total_items,
            "product_id": str(product.id),
            "variant_id": vkey,
            "max": MAX_QTY_PER_LINE,
        })
    return redirect("cart")

@never_cache
@require_POST
def cart_update_qty(request):
    """Update or remove cart line + auto-validate coupon"""
    pid = request.POST.get("product_id")
    vkey = request.POST.get("variant_id")
    try:
        qty = int(request.POST.get("qty", 1))
    except (TypeError, ValueError):
        qty = 1

    if not pid:
        return JsonResponse({"ok": False, "error": "missing product_id"}, status=400)

    cart_map = _get_session_cart(request)
    node = cart_map.get(pid)
    if not isinstance(node, list):
        node = [] if node is None else [{"qty": int(node) or 1, "variant_id": None}]
        cart_map[pid] = node

    # Remove if qty <= 0
    if qty <= 0:
        node[:] = [ln for ln in node if str(ln.get("variant_id")) != str(vkey)]
    else:
        # Enforce stock cap
        try:
            product = Product.objects.get(id=pid, is_listed=True)
            cap = min(MAX_QTY_PER_LINE, _available_stock(product, vkey))
            if cap <= 0:
                node[:] = [ln for ln in node if str(ln.get("variant_id")) != str(vkey)]
            else:
                capped = max(1, min(qty, cap))
                updated = False
                for ln in node:
                    if str(ln.get("variant_id")) == str(vkey):
                        ln["qty"] = capped
                        updated = True
                        break
                if not updated:
                    node.append({"qty": capped, "variant_id": vkey})
        except Product.DoesNotExist:
            node[:] = [ln for ln in node if str(ln.get("variant_id")) != str(vkey)]

    if not node:
        cart_map.pop(pid, None)

    _set_session_cart(request, cart_map)
    
    # ✅ NEW: Auto-validate and remove invalid coupon
    coupon_removed = _auto_validate_coupon(request, cart_map)
    
    # Get updated summary
    summary = _cart_summary_from_session(request)
    
    response_data = {
        "ok": True,
        "items": _sum_items(cart_map),
        "max": MAX_QTY_PER_LINE,
        "summary": summary,
    }
    
    # ✅ Notify if coupon was removed
    if coupon_removed:
        response_data['coupon_removed'] = True
        response_data['coupon_message'] = coupon_removed
    
    return JsonResponse(response_data)

@never_cache
@require_POST
def cart_remove(request):
    """Remove specific cart line + auto-validate coupon"""
    pid = request.POST.get("product_id")
    vkey = request.POST.get("variant_id")
    cart_map = _get_session_cart(request)

    node = cart_map.get(pid)
    if isinstance(node, list):
        node[:] = [ln for ln in node if str(ln.get("variant_id")) != str(vkey)]
        if not node:
            cart_map.pop(pid, None)
    else:
        cart_map.pop(pid, None)

    _set_session_cart(request, cart_map)
    
    # ✅ Auto-validate coupon after removal
    coupon_removed = _auto_validate_coupon(request, cart_map)
    
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        response_data = {
            "ok": True, 
            "items": _sum_items(cart_map)
        }
        if coupon_removed:
            response_data['coupon_removed'] = True
            response_data['coupon_message'] = coupon_removed
        return JsonResponse(response_data)
    
    return redirect("cart")


@require_POST
def cart_empty(request):
    """Empty entire cart"""
    _set_session_cart(request, {})
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "items": 0})
    return redirect("cart")


@login_required
@require_POST
def cart_proceed(request):
    """Proceed to checkout from cart"""
    cart_map = _get_session_cart(request)
    if not cart_map:
        messages.error(request, "Your cart is empty")
        return redirect("cart")
    
    # Validate cart before checkout
    _validate_cart_items(request)
    
    request.session["checkout_ready"] = True
    request.session[CHECKOUT_SESSION_KEY] = timezone.now().isoformat()
    _update_checkout_activity(request)
    
    return redirect("checkout")


# ==================== CHECKOUT SESSION CLEANUP ====================

@login_required
@require_POST
def clear_checkout_session(request):
    """Clear checkout session when user leaves (called via AJAX/beacon)"""
    # Clear buy_now
    if BUY_NOW_SESSION_KEY in request.session:
        del request.session[BUY_NOW_SESSION_KEY]
    
    # Clear checkout flags
    if 'checkout_ready' in request.session:
        del request.session['checkout_ready']
    if CHECKOUT_SESSION_KEY in request.session:
        del request.session[CHECKOUT_SESSION_KEY]
    if LAST_ACTIVITY_KEY in request.session:
        del request.session[LAST_ACTIVITY_KEY]
    
    # Clear coupons (best practice after leaving checkout)
    if 'applied_coupon' in request.session:
        del request.session['applied_coupon']
    if 'applied_coupon_discount' in request.session:
        del request.session['applied_coupon_discount']
    
    request.session.modified = True
    return JsonResponse({'success': True, 'message': 'Checkout session cleared'})


# ==================== CART/CHECKOUT CONTEXT BUILDERS ====================

def _cart_summary_from_session(request):
    """Build cart summary for AJAX responses"""
    cart_map = _get_session_cart(request)
    subtotal_sell = Decimal('0')
    subtotal_mrp = Decimal('0')
    items = []

    for pid, qty, vid in _iter_cart_lines(cart_map):
        try:
            p = Product.objects.get(id=pid, is_listed=True)
        except Product.DoesNotExist:
            continue
        
        unit_sell = p.discount_price or p.base_price
        unit_mrp = p.base_price
        line_sell = unit_sell * Decimal(str(qty))
        line_mrp = unit_mrp * Decimal(str(qty))
        
        subtotal_sell += line_sell
        subtotal_mrp += line_mrp
        
        items.append({
            "id": int(pid),
            "qty": int(qty),
            "unit_sell": float(unit_sell),
            "line_sell": float(line_sell),
            "unit_mrp": float(unit_mrp),
            "line_mrp": float(line_mrp),
        })

    # Coupon
    coupon_code = request.session.get('applied_coupon') or ""
    coupon_amount = Decimal(str(request.session.get('applied_coupon_discount', 0)))
    
    # Calculate totals
    discount = subtotal_mrp - subtotal_sell
    grand_total = subtotal_sell - coupon_amount
    if grand_total < 0:
        grand_total = Decimal('0.00')

    return {
        "items": items,
        "subtotal": str(subtotal_mrp),  # MRP total
        "subtotal_sell": str(subtotal_sell),  # Sell price total
        "subtotal_mrp": str(subtotal_mrp),  # MRP total (duplicate for compatibility)
        "discount": str(discount),  # Product discount
        "coupon_code": coupon_code,
        "coupon_amount": str(coupon_amount),
        "shipping": "0.00",
        "tax": "0.00",
        "addons": "0.00",  # ✅ Kept for compatibility
        "grand_total": str(grand_total),
    }


@login_required
def checkout_cart_summary(request):
    """API endpoint for checkout summary"""
    # Check session expiry
    if _clear_expired_checkout_session(request):
        return JsonResponse({
            "ok": False, 
            "error": "Session expired",
            "expired": True
        }, status=440)
    
    _update_checkout_activity(request)
    data = _cart_summary_from_session(request)
    return JsonResponse({"ok": True, "summary": data}, status=200)


def _cart_items_context(request):
    """Build full cart context for rendering"""
    cart_map = _get_session_cart(request)
    
    # Auto-clean invalid items
    _validate_cart_items(request)
    cart_map = _get_session_cart(request)
    
    items, subtotal_sell, subtotal_mrp, qty_sum = [], 0, 0, 0

    # ✅ GET COUPON EARLY - before calculating prices
    applied_coupon_code = request.session.get('applied_coupon')
    applied_coupon = None
    coupon_discount_percent = Decimal('0')
    today = date.today()

    if applied_coupon_code:
        try:
            applied_coupon = Coupon.objects.get(
                code=applied_coupon_code,
                is_active=True,
                expiry_date__gte=today
            )
            # Get percentage for passing to get_final_price()
            if applied_coupon.coupon_type.upper() in ('PERCENT', 'PERCENTAGE'):
                coupon_discount_percent = Decimal(applied_coupon.discount)
        except Coupon.DoesNotExist:
            if 'applied_coupon' in request.session:
                del request.session['applied_coupon']
            if 'applied_coupon_discount' in request.session:
                del request.session['applied_coupon_discount']
            applied_coupon = None

    # Prefetch products/variants
    product_ids, variant_ids = set(), set()
    for pid, qty, vid in _iter_cart_lines(cart_map):
        if qty > 0:
            product_ids.add(pid)
            if vid:
                try:
                    variant_ids.add(int(vid))
                except Exception:
                    pass

    products = (
        Product.objects.filter(id__in=product_ids, is_listed=True)
        .prefetch_related(
            Prefetch(
                "images",
                queryset=ProductImage.objects.order_by("-featured", "id"),
                to_attr="prefetched_images"
            )
        )
    )
    variants = (
        ProductVariant.objects.filter(id__in=variant_ids)
        .prefetch_related(
            Prefetch(
                "images",
                queryset=ProductVariantImage.objects.order_by("-featured", "id")[:1],
                to_attr="first_image"
            )
        )
        if variant_ids else ProductVariant.objects.none()
    )

    p_by_id = {p.id: p for p in products}
    v_by_id = {v.id: v for v in variants}

    for pid, qty, vid in _iter_cart_lines(cart_map):
        if qty <= 0:
            continue
        p = p_by_id.get(pid)
        if not p:
            continue

        # ✅ FIXED: Pass coupon percent to get_final_price
        unit_sell = int(p.get_final_price(coupon_discount_percent))
        unit_mrp = int(p.base_price)
        line_sell = int(unit_sell * qty)
        line_mrp = int(unit_mrp * qty)
        subtotal_sell += line_sell
        subtotal_mrp += line_mrp
        qty_sum += qty

        v = v_by_id.get(int(vid)) if vid else None

        # Images
        img = None
        if v and getattr(v, "first_image", None):
            vf = v.first_image[0] if v.first_image else None
            if vf:
                img = vf.image_url
        
        if not img and getattr(p, "prefetched_images", None):
            fp = p.prefetched_images[0] if p.prefetched_images else None
            if fp:
                img = fp.image_url
        
        if not img:
            img = '/static/images/placeholder.jpg'

        # Metadata
        color = getattr(v, "color", None) if v else None
        display_name = f"{p.name} {color}".strip() if color else p.name

        # ✅ Discount percent (calculated from MRP to final price)
        perc = p.get_discount_percent() if hasattr(p, 'get_discount_percent') else 0

        available_stock = v.stock if v and hasattr(v, "stock") else getattr(p, "stock_quantity", 0)
        max_qty = min(10, available_stock)  # MAX_QTY_PER_LINE

        items.append({
            "id": p.id,
            "name": display_name,
            "base_name": p.name,
            "variant_color": color,
            "image": img,
            "unit_sell": int(unit_sell),
            "unit_mrp": int(unit_mrp),
            "qty": qty,
            "line_sell": int(line_sell),
            "line_mrp": int(line_mrp),
            "offer": getattr(p, "offer", None),
            "discount_percent": perc,
            "variant_id": int(vid) if vid else None,
            "max_qty": max_qty,
        })

    # Calculate product discount
    discount = int(max(subtotal_mrp - subtotal_sell, 0))
    
    # ✅ Coupon discount calculation (for flat coupons or display)
    coupon_discount = Decimal('0')
    if applied_coupon:
        # Check minimum purchase requirement
        if applied_coupon.min_purchase and subtotal_sell < applied_coupon.min_purchase:
            del request.session['applied_coupon']
            if 'applied_coupon_discount' in request.session:
                del request.session['applied_coupon_discount']
            applied_coupon = None
        else:
            if applied_coupon.coupon_type.upper() in ('PERCENT', 'PERCENTAGE'):
                # For percentage coupons, prices already include discount
                # Just calculate for display
                coupon_discount = (Decimal(subtotal_sell) * Decimal(applied_coupon.discount)) / Decimal(100)
                if applied_coupon.max_redeemable:
                    coupon_discount = min(coupon_discount, applied_coupon.max_redeemable)
            else:
                # Flat discount - apply to total
                coupon_discount = Decimal(applied_coupon.discount)
            
            coupon_discount = min(coupon_discount, Decimal(subtotal_sell))
            request.session['applied_coupon_discount'] = str(coupon_discount)

    total_payable = int(subtotal_sell - coupon_discount)
    save_note = int(discount + coupon_discount)

    # Get active coupons
    active_coupons = Coupon.objects.filter(
        is_active=True,
        expiry_date__gte=today
    ).order_by('-discount')

    return {
        "items": items,
        "subtotal_sell": int(subtotal_sell),
        "subtotal_mrp": int(subtotal_mrp),
        "coupons": active_coupons,
        "discount": discount,
        "qty_sum": qty_sum,
        "total_payable": total_payable,
        "save_note": save_note,
        "products_count": len(items),
        "applied_coupon": applied_coupon,
        "coupon_discount": int(coupon_discount),
    }


# ==================== CART PAGE VIEW ====================
@never_cache
def cart(request):
    """Render cart page"""
    context = _cart_items_context(request)
    context['categories'] = Category.objects.filter(is_active=True).order_by('name')
    
    # Active offers
    context['offers'] = get_active_offers(request)
    
    # Pincode data from session
    context['delivery_pincode'] = request.session.get('delivery_pincode')
    context['delivery_city'] = request.session.get('delivery_city')
    context['delivery_date'] = request.session.get('delivery_date')
    context['cod_available'] = request.session.get('cod_available', True)
    
    #applied_coupon and coupon_discount already in context from _cart_items_context!
    
    return render(request, "user/cart.html", context)


""" 
# ============================================
#  Coupon management
# ============================================
"""
@require_http_methods(["POST"])
def apply_coupon(request):
    """
    Complete coupon application with all validations:
    1. User authentication
    2. Coupon existence & active status
    3. Date validity (start & expiry)
    4. Global usage limit
    5. Per-user usage limit
    6. First-time buyer check
    7. Minimum order amount
    8. Maximum order amount
    9. Minimum items
    10. Exclude discounted products
    """
    
    # ✅ CHECK 1: User must be authenticated
    if not request.user.is_authenticated:
        return JsonResponse({
            'success': False, 
            'message': 'Please login to use coupons'
        })
    
    coupon_code = request.POST.get('coupon_code', '').strip().upper()

    if not coupon_code:
        return JsonResponse({
            'success': False, 
            'message': 'Please enter a coupon code'
        })

    try:
        # ✅ CHECK 2: Coupon exists
        from datetime import date
        from coupons.models import Coupon
        coupon = Coupon.objects.get(code=coupon_code)
        
        # ✅ CHECK 3: Basic validity (active, date range, global limit)
        is_valid, message = coupon.is_valid()
        if not is_valid:
            return JsonResponse({'success': False, 'message': message})
        
        # ✅ CHECK 4: User-specific eligibility (first-time, per-user limit)
        user_eligible, message = coupon.check_user_eligibility(request.user)
        if not user_eligible:
            return JsonResponse({'success': False, 'message': message})
        
        # Get cart data
        buy_now_line = request.session.get(BUY_NOW_SESSION_KEY)
        if buy_now_line:
            ctx = _buy_now_summary(request)
            subtotal = Decimal(str(ctx.get('subtotal_sell', 0)))
            total_quantity = ctx.get('items', [{}])[0].get('qty', 1)
            cart_items = ctx.get('items', [])
        else:
            cart_map = _get_session_cart(request)
            subtotal = Decimal('0')
            total_quantity = 0
            cart_items = []
            
            for pid, qty, vid in _iter_cart_lines(cart_map):
                try:
                    product = Product.objects.get(id=pid, is_listed=True)
                    price = product.discount_price or product.base_price
                    subtotal += price * int(qty)
                    total_quantity += int(qty)
                    
                    # Track if product has discount
                    cart_items.append({
                        'id': pid,
                        'qty': qty,
                        'has_discount': product.discount_price is not None
                    })
                except Product.DoesNotExist:
                    continue
        
        # ✅ CHECK 5: Cart eligibility (min amount, max amount, min items, discounted products)
        cart_eligible, message = coupon.check_cart_eligibility(
            total_quantity, 
            subtotal, 
            cart_items
        )
        if not cart_eligible:
            return JsonResponse({'success': False, 'message': message})
        
        # ✅ Calculate discount
        discount = coupon.calculate_discount(subtotal)
        final_total = subtotal - discount
        
        # ✅ Save to session
        request.session['applied_coupon'] = coupon_code
        request.session['applied_coupon_discount'] = str(discount)
        request.session['applied_coupon_id'] = coupon.id
        request.session.modified = True
        
        return JsonResponse({
            'success': True,
            'message': f'Coupon {coupon_code} applied successfully!',
            'coupon_discount': float(discount),
            'final_total': float(final_total),
            'coupon_code': coupon_code,
            'coupon_title': coupon.title
        })
    
    except Coupon.DoesNotExist:
        return JsonResponse({
            'success': False, 
            'message': 'Invalid coupon code'
        })
def _auto_validate_coupon(request, cart_map):
    """
    Auto-validate applied coupon after cart changes.
    Removes coupon if conditions no longer met.
    
    Removal triggers:
    1. Minimum amount not met
    2. Maximum amount exceeded
    3. Minimum items not met
    4. Discounted products added (if excluded)
    5. Coupon expired or not yet active
    6. User logged out
    7. Global usage limit reached
    """
    applied_coupon_code = request.session.get('applied_coupon')
    
    if not applied_coupon_code:
        return None  # No coupon applied
    
    # ✅ CHECK 1: User still authenticated
    if not request.user.is_authenticated:
        _remove_coupon_from_session(request)
        return "Coupon removed: Please login again"
    
    try:
        from datetime import date
        from coupons.models import Coupon
        
        coupon = Coupon.objects.get(code=applied_coupon_code)
        
        # ✅ CHECK 2: Basic validity (active, date range, global limit)
        is_valid, message = coupon.is_valid()
        if not is_valid:
            _remove_coupon_from_session(request)
            return f"Coupon {applied_coupon_code} removed: {message}"
        
        # Calculate current cart totals
        total_quantity = 0
        subtotal = Decimal('0')
        cart_items = []
        
        for pid, qty, vid in _iter_cart_lines(cart_map):
            try:
                product = Product.objects.get(id=pid, is_listed=True)
                price = product.discount_price or product.base_price
                subtotal += price * qty
                total_quantity += qty
                
                # ✅ Track if product has discount
                cart_items.append({
                    'id': pid,
                    'qty': qty,
                    'has_discount': product.discount_price is not None
                })
            except Product.DoesNotExist:
                continue
        
        # ✅ CHECK 3: Cart eligibility (min/max amount, min items, discounted products)
        cart_eligible, message = coupon.check_cart_eligibility(
            total_quantity, 
            subtotal, 
            cart_items
        )
        
        if not cart_eligible:
            _remove_coupon_from_session(request)
            return f"Coupon {applied_coupon_code} removed: {message}"
        
        # ✅ Still eligible - recalculate discount
        discount = coupon.calculate_discount(subtotal)
        request.session['applied_coupon_discount'] = str(discount)
        request.session.modified = True
        
        return None  # Coupon still valid
        
    except Coupon.DoesNotExist:
        _remove_coupon_from_session(request)
        return f"Coupon {applied_coupon_code} expired or invalid"


def _remove_coupon_from_session(request):
    """Helper to clean coupon from session"""
    if 'applied_coupon' in request.session:
        del request.session['applied_coupon']
    if 'applied_coupon_discount' in request.session:
        del request.session['applied_coupon_discount']
    if 'applied_coupon_id' in request.session:
        del request.session['applied_coupon_id']
    request.session.modified = True


@require_http_methods(["POST"])
def remove_coupon(request):
    """Remove applied coupon"""
    if 'applied_coupon' in request.session:
        del request.session['applied_coupon']
    if 'applied_coupon_discount' in request.session:
        del request.session['applied_coupon_discount']
    if 'applied_coupon_id' in request.session:
        del request.session['applied_coupon_id']
    request.session.modified = True
    
    return JsonResponse({'success': True, 'message': 'Coupon removed'})

def get_active_offers(request):
    """
    Get applicable offers for current user & cart.
    Filters out:
    - Coupons user already used (up to per_user_limit)
    - Expired coupons
    - Inactive coupons
    - Coupons that reached global limit
    - Coupons not yet started
    - First-time only coupons (if user has orders)
    """
    from coupons.models import Coupon, CouponUsage
    from datetime import date
    from django.db.models import Count, Q, F
    
    # Get cart data
    buy_now_line = request.session.get(BUY_NOW_SESSION_KEY)
    if buy_now_line:
        ctx = _buy_now_summary(request)
        cart_count = 1
        cart_total = Decimal(str(ctx.get('subtotal_sell', 0)))
        cart_items = ctx.get('items', [])
    else:
        cart_map = _get_session_cart(request)
        cart_total = Decimal('0')
        cart_count = 0
        cart_items = []
        
        for pid, qty, vid in _iter_cart_lines(cart_map):
            try:
                product = Product.objects.get(id=pid, is_listed=True)
                price = product.discount_price or product.base_price
                cart_total += price * int(qty)
                cart_count += 1
                
                # Track discounted products
                cart_items.append({
                    'id': pid,
                    'qty': qty,
                    'has_discount': product.discount_price is not None
                })
            except Product.DoesNotExist:
                continue
    
    # Get active coupons with filters
    today = date.today()
    active_coupons = Coupon.objects.filter(
        is_active=True,
        start_date__lte=today,  # ✅ Started
        expiry_date__gte=today  # ✅ Not expired
    ).filter(
        used_count__lt=F('limit')  # ✅ Global limit not reached
    )
    
    # ✅ Filter by user eligibility if authenticated
    if request.user.is_authenticated:
        # Annotate with user's usage count
        active_coupons = active_coupons.annotate(
            user_usage_count=Count(
                'usage_records',
                filter=Q(usage_records__user=request.user)
            )
        ).filter(
            user_usage_count__lt=F('per_user_limit')  # ✅ Per-user limit not reached
        )
    
    active_coupons = active_coupons.order_by('display_order', '-discount')[:8]
    
    # Build offer data
    offers = []
    for coupon in active_coupons:
        # ✅ Additional user eligibility check (first-time only, etc.)
        if request.user.is_authenticated:
            user_eligible, user_message = coupon.check_user_eligibility(request.user)
            if not user_eligible:
                continue  # Skip this coupon for this user
        
        # ✅ Check cart eligibility
        cart_eligible, cart_message = coupon.check_cart_eligibility(
            cart_count, 
            cart_total, 
            cart_items
        )
        
        # Condition display text
        conditions = []
        if coupon.min_items > 0:
            conditions.append(f"Min {coupon.min_items} items")
        if coupon.min_purchase > 0:
            conditions.append(f"Min ₹{coupon.min_purchase:.0f}")
        if coupon.first_time_only:
            conditions.append("First-time buyers only")
        if coupon.exclude_discounted:
            conditions.append("Not valid on discounted items")
        
        condition_text = " • ".join(conditions) if conditions else "No minimum"
        
        # Discount display
        if coupon.coupon_type == 'percent':
            discount_text = f"Get {coupon.discount:.0f}% off"
            if coupon.max_redeemable > 0:
                discount_text += f" (upto ₹{coupon.max_redeemable:.0f})"
        else:
            discount_text = f"Get ₹{coupon.discount:.0f} off"
        
        offers.append({
            'id': coupon.id,
            'code': coupon.code,
            'title': coupon.title,
            'description': coupon.description or "",
            'condition_text': condition_text,
            'discount_text': discount_text,
            'badge': coupon.badge or "",
            'eligible': cart_eligible,
            'message': cart_message if not cart_eligible else "Apply now",
            'expiry': coupon.expiry_date.strftime('%d %b %Y'),
            'first_time_only': coupon.first_time_only,
            'exclude_discounted': coupon.exclude_discounted,
        })
    
    return offers

@require_http_methods(["POST"])
def quick_add_with_coupon(request):
    """Add product to cart with required quantity and apply coupon automatically"""
    
    # ✅ ADD: Require authentication
    if not request.user.is_authenticated:
        return JsonResponse({
            'success': False,
            'message': 'Please login to use coupons'
        })
    
    product_id = request.POST.get('product_id')
    variant_id = request.POST.get('variant_id', '')
    coupon_code = request.POST.get('coupon_code', '').strip().upper()
    quantity = int(request.POST.get('quantity', 1))
    
    try:
        # 1-4. Product validation & cart addition (keep existing)
        product = Product.objects.get(id=product_id, is_listed=True)
        
        vkey = str(variant_id) if variant_id else None
        if product.variants.exists() and not vkey:
            dv = product.variants.filter(is_default=True).first() or product.variants.order_by("id").first()
            vkey = str(dv.id) if dv else None
        
        stock = _available_stock(product, vkey)
        if quantity > stock:
            return JsonResponse({
                'success': False,
                'message': f'Only {stock} units available in stock'
            })
        
        cart_map = _get_session_cart(request)
        pid_str = str(product_id)
        cart_map[pid_str] = [{'qty': quantity, 'variant_id': vkey}]
        _set_session_cart(request, cart_map)
        
        # 5. Apply coupon with FULL validation
        coupon_message = ""
        coupon_discount = 0
        
        if coupon_code:
            try:
                from coupons.models import Coupon
                coupon = Coupon.objects.get(code=coupon_code)
                
                # ✅ FIX: Use full validation like apply_coupon()
                is_valid, msg = coupon.is_valid()
                if not is_valid:
                    coupon_message = f" (but {msg})"
                else:
                    user_eligible, msg = coupon.check_user_eligibility(request.user)
                    if not user_eligible:
                        coupon_message = f" (but {msg})"
                    else:
                        # Calculate cart totals
                        total_quantity = 0
                        subtotal = Decimal('0')
                        cart_items = []
                        
                        for pid, qty, vid in _iter_cart_lines(cart_map):
                            try:
                                prod = Product.objects.get(id=pid, is_listed=True)
                                price = prod.discount_price or prod.base_price
                                subtotal += price * qty
                                total_quantity += qty
                                
                                cart_items.append({
                                    'id': pid,
                                    'qty': qty,
                                    'has_discount': prod.discount_price is not None
                                })
                            except Product.DoesNotExist:
                                continue
                        
                        # Check cart eligibility
                        cart_eligible, msg = coupon.check_cart_eligibility(
                            total_quantity, subtotal, cart_items
                        )
                        
                        if cart_eligible:
                            discount = coupon.calculate_discount(subtotal)
                            request.session['applied_coupon'] = coupon_code
                            request.session['applied_coupon_discount'] = str(discount)
                            request.session['applied_coupon_id'] = coupon.id
                            request.session.modified = True
                            
                            coupon_message = f" & coupon {coupon_code} applied (Saved ₹{discount:.0f})"
                            coupon_discount = float(discount)
                        else:
                            coupon_message = f" (but {msg})"
                
            except Coupon.DoesNotExist:
                coupon_message = " (but coupon code is invalid)"
        
        return JsonResponse({
            'success': True,
            'message': f'Added {quantity} item(s) to cart{coupon_message}!',
            'quantity': quantity,
            'coupon_applied': bool(coupon_discount > 0),
            'coupon_discount': coupon_discount,
            'redirect_url': '/cart/'
        })
        
    except Product.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Product not found'})
    except ValueError:
        return JsonResponse({'success': False, 'message': 'Invalid quantity'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Error: {str(e)}'})

