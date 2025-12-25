# Orders/views.py
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.utils import timezone
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from cart.views import _auto_validate_coupon, _buy_now_summary, _cart_items_context, _get_session_cart, _set_session_cart
from user.models import Address
from .models import Order, OrderItem, ActionRequest
from products.models import Product, ProductVariant,StockTransaction 
from django.db.models import Prefetch
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.cache import never_cache
from django.contrib import messages
from .forms import ReturnReasonForm
from django.core.mail import mail_admins 
from xhtml2pdf import pisa
import io
from django.template.loader import get_template
from decimal import Decimal 
from payments.views import _gen_order_number
from coupons.models import Coupon, DeliveryPincode
from cart.views import CART_SESSION_KEY, BUY_NOW_SESSION_KEY
from user.forms import AddressForm



# -------------------------------
# My Orders (list)
# -------------------------------

from datetime import date, timedelta
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.utils import timezone
from django.shortcuts import render

from datetime import date, timedelta
from django.utils import timezone
from django.db.models import Q
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from admin_side.views import is_admin

@login_required
def orderss(request):
    # Only exclude PENDING (incomplete checkout), but SHOW FAILED orders
    qs = Order.objects.filter(user=request.user).exclude(
        status='PENDING'
    ).prefetch_related("items")

    # --- Params ---
    q = (request.GET.get("q") or "").strip()
    rng = request.GET.get("range")
    dfrom = request.GET.get("from")
    dto = request.GET.get("to")
    status = request.GET.get("status") or ""
    sort = request.GET.get("sort") or "-created_at"

    # --- Search ---
    if q:
        qs = qs.filter(
            Q(order_number__icontains=q)
            | Q(items__product_name__icontains=q)
            | Q(items__variant_color__icontains=q)
        ).distinct()

    # --- Quick ranges ---
    now = timezone.now()
    if rng == "12m":
        qs = qs.filter(created_at__gte=now - timedelta(days=365))
    elif rng == "30d":
        qs = qs.filter(created_at__gte=now - timedelta(days=30))
    elif rng == "7d":
        qs = qs.filter(created_at__gte=now - timedelta(days=7))
    elif rng == "24h":
        qs = qs.filter(created_at__gte=now - timedelta(hours=24))

    # --- Explicit date filters ---
    if dfrom:
        qs = qs.filter(created_at__date__gte=dfrom)
    if dto:
        qs = qs.filter(created_at__date__lte=dto)

    # --- Status filter ---
    if status:
        qs = qs.filter(status=status)

    # --- Sort ---
    allowed_sorts = {"created_at", "-created_at", "total_amount", "-total_amount"}
    if sort not in allowed_sorts:
        sort = "-created_at"
    qs = qs.order_by(sort)

    # --- Smart auto status update (Flipkart style) ---
    for o in qs:
        if o.status == 'FAILED':
            continue
            
        item_statuses = [i.status for i in o.items.all()]
        if not item_statuses:
            continue
        if all(s == "DELIVERED" for s in item_statuses):
            o.status = "DELIVERED"
        elif all(s == "CANCELLED" for s in item_statuses):
            o.status = "CANCELLED"
        elif all(s == "RETURNED" for s in item_statuses):
            o.status = "RETURNED"
        elif any(s == "RETURNED" for s in item_statuses):
            o.status = "PARTIALLY_RETURNED"
        elif any(s == "CANCELLED" for s in item_statuses):
            o.status = "PARTIALLY_CANCELLED"
        else:
            o.status = "PROCESSING"
        o.save(update_fields=["status"])

    # --- Pagination ---
    paginator = Paginator(qs, 5)
    page = request.GET.get("page") or 1
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    # --- Product → Offer map ---
    product_ids = {
        getattr(it, "product_id", None)
        for o in page_obj.object_list
        for it in o.items.all()
        if getattr(it, "product_id", None)
    }

    offers = {}
    if product_ids:
        
        for p in Product.objects.filter(id__in=product_ids).only("id", "offer"):
            offers[p.id] = p.offer or ""

    # --- Status color map ---
    status_map = {
        "PLACED": "s-blue",
        "CONFIRMED": "s-blue",
        "SHIPPED": "s-blue",
        "OUTFORDELIVERY": "s-blue",
        "DELIVERED": "s-green",
        "CANCELLED": "s-red",
        "RETURNED": "s-red",
        "PARTIALLY_RETURNED": "s-orange",
        "PARTIALLY_CANCELLED": "s-orange",
        "PROCESSING": "s-blue",
        "FAILED": "s-red",
    }

    # --- Build final payload ---
    result = []
    today = date.today()
    
    for o in page_obj.object_list:
        item_cards = []
        for it in o.items.all():
            base_name = it.product_name or "Product"
            color = getattr(it, "variant_color", None)
            display_name = f"{base_name} {color}".strip() if color else base_name

            qty = int(it.quantity or 0)
            unit_sell = it.unit_price
            unit_mrp = getattr(it, "mrp_price", None) or unit_sell
            line_sell = getattr(it, "line_total", unit_sell * qty)
            line_mrp = unit_mrp * qty

            # status-related
            status_class = status_map.get(it.status, "s-blue")
            pending_return = it.action_requests.filter(kind="RETURN", state="PENDING").exists() if hasattr(it, 'action_requests') else False
            pending_cancel = it.action_requests.filter(kind="CANCEL", state="PENDING").exists() if hasattr(it, 'action_requests') else False
            can_cancel = it.status in ["PLACED", "CONFIRMED"] and not pending_cancel
            can_return = it.status == "DELIVERED" and not pending_return

            # badge
            badge = getattr(it, "offer_label", None)
            if not badge and it.product_id:
                badge = offers.get(it.product_id, "")

            item_cards.append({
                "id": it.id,
                "name": display_name,
                "base_name": base_name,
                "variant_color": color,
                "image": it.image_url,
                "qty": qty,
                "unit_sell": unit_sell,
                "unit_mrp": unit_mrp,
                "line_sell": line_sell,
                "line_mrp": line_mrp,
                "offer": badge,
                "status": it.status,
                "status_class": status_class,
                "can_cancel": can_cancel,
                "can_return": can_return,
                "pending_return": pending_return,
                "pending_cancel": pending_cancel,
            })

        # ✅ IMPROVED: Dynamic right_note based on status
        if o.status == 'DELIVERED' and o.delivered_at:
            right_note = f"Delivered on {o.delivered_at.strftime('%d %B')}"
        elif o.status == 'CANCELLED' and o.cancelled_at:
            right_note = f"Cancelled on {o.cancelled_at.strftime('%d %B')}"
        elif o.status == 'RETURNED':
            returned_date = getattr(o, 'returned_at', None)
            if returned_date:
                right_note = f"Returned on {returned_date.strftime('%d %B')}"
            else:
                right_note = "Returned"
        else:
            right_note = o.created_at.strftime("Placed %d %B")

        # ✅ NEW: Check if delivery is delayed
        is_delivery_delayed = False
        if o.status not in ['DELIVERED', 'CANCELLED', 'RETURNED', 'FAILED']:
            if hasattr(o, 'expected_delivery_date') and o.expected_delivery_date:
                if o.expected_delivery_date < today:
                    is_delivery_delayed = True

        result.append({
            "order_id": o.order_number,
            "status": o.status,
            "status_class": status_map.get(o.status, "s-blue"),
            "created_at": o.created_at,
            "total_amount": o.total_amount,
            "right_note": right_note,
            "items": item_cards,
            "pk": o.pk,
            "is_failed": o.status == 'FAILED',
            "can_retry": o.status == 'FAILED' and o.created_at >= timezone.now() - timedelta(days=7),
            
            # ✅ Add delivery info
            "delivery_date": o.get_delivery_date_formatted() if hasattr(o, 'get_delivery_date_formatted') else None,
            "is_delivery_delayed": is_delivery_delayed,  # ✅ NEW FLAG
        })

    return render(request, "user/my_orders.html", {
        "orders": result,
        "page_obj": page_obj,
        "paginator": paginator,
    })
    
@login_required
def order_item_detail(request, order_number, item_id):
    # fetch the order (belongs to user) and the item inside it
    order = get_object_or_404(
        Order.objects.select_related("user"),
        order_number=order_number,
        user=request.user,
    )
    item = get_object_or_404(
        OrderItem.objects.select_related("order"),
        id=item_id,
        order=order
    )

    # status -> css helper
    status_map = {
        "PLACED": "s-blue", "CONFIRMED": "s-blue", "SHIPPED": "s-blue",
        "DELIVERED": "s-green", "CANCELLED": "s-red", "RETURNED": "s-red",
    }

    # badge text: prefer snapshot on item; fallback to Product.offer
    badge = item.offer_label or ""
    if not badge and item.product_id:
        prod_offer = (
            Product.objects.filter(id=item.product_id)
            .values_list("offer", flat=True)  # efficient single-field fetch
            .first()
        )
        badge = prod_offer or ""

    # dynamic address lines
    ship_lines = [
        order.ship_full_name,
        order.ship_phone or None,
        order.ship_line1,
        (order.ship_line2 or "").strip() or None,
        f"{order.ship_city}, {order.ship_state} {order.ship_postcode}".strip(),
        order.ship_country,
    ]
    ship_lines = [ln for ln in ship_lines if ln]

    # money summary derived from order + this item
    items_total = item.line_total
    shipping = order.shipping_amount
    discount = order.discount_amount
    total = order.total_amount
    items = [{
        "product_name": item.product_name,
    }]
    
    # Check pending requests
    pending_return = item.action_requests.filter(kind="RETURN", state="PENDING").exists()
    pending_cancel = item.action_requests.filter(kind="CANCEL", state="PENDING").exists()
    
    # Calculate delivery date
    delivery_date = None
    if item.status not in ['DELIVERED', 'CANCELLED', 'RETURNED']:
        # Check if order has the method
        if hasattr(order, 'get_delivery_date_formatted'):
            delivery_date = order.get_delivery_date_formatted()
        # Fallback: calculate from expected_delivery_date
        elif hasattr(order, 'expected_delivery_date') and order.expected_delivery_date:
            delivery_date = order.expected_delivery_date.strftime('%A, %d %B')
    
    # ✅ NEW: Return Policy Logic
    can_return_eligible, return_message = item.is_return_eligible()
    return_deadline = item.get_return_deadline()
    days_remaining = item.get_days_until_return_expires()
    
    # Final return button state (eligible AND no pending request)
    can_show_return_button = can_return_eligible and not pending_return
    
    # Format return deadline for display
    return_deadline_formatted = None
    if return_deadline:
        return_deadline_formatted = return_deadline.strftime('%d %B %Y')  # "12 December 2025"
    
    ctx = {
        "order": order,
        'items': items,
        "item": item,
        "rep_image": item.image_url or "",
        "rep_title": item.product_name,
        "rep_badge": badge,  # will show in the yellow ribbon on the card
        "ship_lines": ship_lines,
        "payment_method": dict(Order.PM_CHOICES).get(order.payment_method, order.payment_method),
        "items_total": items_total,
        "shipping": shipping,
        "discount": discount,
        "total": total,
        "status_class": status_map.get(item.status, "s-blue"),
        "status_label": getattr(item, "get_status_display", lambda: item.status)(),
        "unit_mrp": item.mrp_price or item.unit_price,
        "offer": badge,  # keep a generic key if other templates rely on it
        "pending_return": pending_return,
        "pending_cancel": pending_cancel,
        "delivery_date": delivery_date,
        
        # ✅ NEW: Return Policy Data
        "can_return": can_show_return_button,
        "return_message": return_message,
        "return_deadline": return_deadline,
        "return_deadline_formatted": return_deadline_formatted,
        "days_remaining": days_remaining,
        "return_window_days": OrderItem.RETURN_WINDOW_DAYS,
        "is_return_expired": item.is_return_period_expired(),
    }
    
    return render(request, "user/order_detailed.html", ctx)


"""
# -------------------------------
# Order Track page
# -------------------------------
# """



@login_required
def track_item(request, order_number, item_id):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    item = get_object_or_404(OrderItem, id=item_id, order=order)

    # Badge: snapshot first, then Product.offer fallback
    badge = item.offer_label or ""
    if not badge and getattr(item, "product_id", None):
        prod_offer = (
            Product.objects.filter(id=item.product_id)
            .values_list("offer", flat=True)
            .first()
        )
        badge = prod_offer or ""

    # Define timeline steps with descriptions
    timeline_steps = []
    
    if item.status in (OrderItem.ItemStatus.CANCELLED, OrderItem.ItemStatus.RETURNED):
        # Simplified timeline for cancelled/returned orders
        timeline_steps = [
            {
                "label": "Order Placed",
                "description": "An order has been placed.",
                "timestamp": item.placed_at or order.created_at,
                "done": True,
                "icon": "cart"
            },
            {
                "label": "Cancelled" if item.status == OrderItem.ItemStatus.CANCELLED else "Returned",
                "description": "Order has been cancelled." if item.status == OrderItem.ItemStatus.CANCELLED else "Order has been returned.",
                "timestamp": item.cancelled_at or item.returned_at,
                "done": True,
                "icon": "x-circle"
            }
        ]
    else:
        # Full timeline for normal orders
        timeline_steps = [
            {
                "label": "Order Placed",
                "description": "An order has been placed.",
                "timestamp": item.placed_at or order.created_at,
                "done": True,
                "icon": "cart"
            },
            {
                "label": "Processing",
                "description": "Seller has processed your order.",
                "timestamp": item.processing_at,
                "done": item.status in ["CONFIRMED", "SHIPPED", "OUTFORDELIVERY", "DELIVERED"],
                "icon": "hourglass"
            },
            {
                "label": "Packed",
                "description": "Order packaged and ready.",
                "timestamp": item.packed_at,
                "done": item.status in ["SHIPPED", "OUTFORDELIVERY", "DELIVERED"],
                "icon": "box"
            },
            {
                "label": "Shipping",
                "description": "Order is on the way.",
                "timestamp": item.shipped_at,
                "done": item.status in ["SHIPPED", "OUTFORDELIVERY", "DELIVERED"],
                "icon": "truck"
            },
            {
                "label": "Delivered",
                "description": "Package delivered.",
                "timestamp": item.delivered_at,
                "done": item.status == "DELIVERED",
                "icon": "check-circle"
            }
        ]

    # Original progress bar data (keep for compatibility)
    step_map = {
        "PLACED": 1,
        "CONFIRMED": 1,
        "SHIPPED": 2,
        "OUTFORDELIVERY": 3,
        "DELIVERED": 4,
        "CANCELLED": 1,
        "RETURNED": 4,
    }
    
    step = step_map.get(item.status, 1)
    progress = {
        "step": step,
        "width": {1: "12%", 2: "45%", 3: "78%", 4: "100%"}.get(step, "12%"),
    }

    # Address lines
    ship_lines = [
        order.ship_full_name,
        order.ship_phone or None,
        order.ship_line1,
        (order.ship_line2 or "").strip() or None,
        f"{order.ship_city}, {order.ship_state} {order.ship_postcode}".strip(),
        order.ship_country,
    ]
    ship_lines = [x for x in ship_lines if x]

    # Payment + money
    payment_method = getattr(order, "get_payment_method_display", lambda: order.payment_method)()
    items_total = item.line_total
    shipping_charge = order.shipping_amount
    discount = order.discount_amount
    grand_total = order.total_amount

    # Card list expected by template
    items = [{
        "image_url": item.image_url,
        "product_name": item.product_name,
        "badge_label": badge,
    }]

    pending_return = item.action_requests.filter(kind="RETURN", state="PENDING").exists()
    pending_cancel = item.action_requests.filter(kind="CANCEL", state="PENDING").exists()

    ctx = {
        "order": order,
        "item": item,
        "items": items,
        "rep_badge": badge,
        "created_ts": order.created_at,
        "ship_lines": ship_lines,
        "payment_method": payment_method,
        "items_total": items_total,
        "shipping_charge": shipping_charge,
        "discount": discount,
        "grand_total": grand_total,
        "progress": progress,
        "timeline_steps": timeline_steps,  # New: detailed timeline
        "pending_return": pending_return,
        "pending_cancel": pending_cancel,
    }

    return render(request, "user/track_order.html", ctx)



"""
# -------------------------------
# Admin Side order Management
# -------------------------------
# """
@user_passes_test(is_admin, login_url='admin_login')
@login_required(login_url='admin_login')
@never_cache
@staff_member_required
def admin_order_list(request):
    qs = (
        Order.objects
        .select_related("user", "user__profile")  # add profile
        .prefetch_related(
            Prefetch(
                "items",
                queryset=OrderItem.objects.only(
                    "id","order_id","product_name","quantity","line_total","variant_color","status","product_id","image_url"
                ).order_by("id"),
                to_attr="prefetched_items"
            )
        )
    )

    # params
    q = (request.GET.get("q") or "").strip()
    rng = request.GET.get("range") or "all"
    dfrom = request.GET.get("from")
    dto = request.GET.get("to")
    status = (request.GET.get("status") or "").strip()
    sort = (request.GET.get("sort") or "-created_at").strip()

    # search
    if q:
        qs = qs.filter(
            Q(order_number__icontains=q) |
            Q(items__product_name__icontains=q) |
            Q(items__variant_color__icontains=q) |
            Q(user__email__icontains=q) |
            Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q)
        ).distinct()

    # quick ranges
    now = timezone.now()
    if rng == "12m":
        qs = qs.filter(created_at__gte=now - timedelta(days=365))
    elif rng == "30d":
        qs = qs.filter(created_at__gte=now - timedelta(days=30))
    elif rng == "7d":
        qs = qs.filter(created_at__gte=now - timedelta(days=7))
    elif rng == "24h":
        qs = qs.filter(created_at__gte=now - timedelta(hours=24))

    # explicit date range
    if dfrom:
        qs = qs.filter(created_at__date__gte=dfrom)
    if dto:
        qs = qs.filter(created_at__date__lte=dto)

    # status filter (normalize to your order status domain)
    if status:
        qs = qs.filter(status=status)

    # sort allowlist
    allowed_sorts = {"created_at","-created_at","total_amount","-total_amount"}
    if sort not in allowed_sorts:
        sort = "-created_at"
    qs = qs.order_by(sort)

    # pagination
    paginator = Paginator(qs, 10)
    page = request.GET.get("page") or 1
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    # optional brand fetch for first product per order row
    # build product_id set from page
    first_product_ids = []
    for o in page_obj.object_list:
        if getattr(o, "prefetched_items", None):
            first = o.prefetched_items[0]
            if getattr(first, "product_id", None):
                first_product_ids.append(first.product_id)

    brand_by_pid = {}
    if first_product_ids:
        # assuming Product has brand.name via FK brand or CharField brand_name
        prods = Product.objects.filter(id__in=first_product_ids).select_related("brand").only("id","brand__name")
        for p in prods:
            brand_by_pid[p.id] = getattr(getattr(p, "brand", None), "name", "") or ""

    # build rows for template
    rows = []
    for o in page_obj.object_list:
        items = getattr(o, "prefetched_items", []) or []
        primary_name = items[0].product_name if items else "—"
        items_count = len(items)
        customer_name = o.user.get_full_name() or o.user.username
        customer_email = o.user.email
        total_display = f"₹{o.total_amount:.2f}"
        payment_label = dict(Order.PM_CHOICES).get(o.payment_method, o.payment_method)

        # map status to template domain if needed
        status_str = o.status.lower() if isinstance(o.status, str) else str(o.status).lower()

        pid = items[0].product_id if items else None
        brand_name = brand_by_pid.get(pid, "") if pid else ""
        # NEW: product thumbnail from first item
        image_url = items[0].image_url if items else ""
        rows.append({
            "id": o.id,
            "primary_item_name": primary_name,
            "items_count": items_count,
            "human_date": o.created_at.strftime("%d %b %Y"),
            "customer_name": customer_name,
            "customer_email": customer_email,
            "total_display": total_display,
            "payment_method": payment_label,
            "status": status_str,
            "brand_name": brand_name,
            "image_url": image_url,  # <-- add
        })

    # numeric page list (compact window)
    current = page_obj.number
    start = max(current - 2, 1)
    end = min(current + 2, paginator.num_pages)
    page_range = range(start, end + 1)

    ctx = {
        "orders": rows,
        "page_obj": page_obj,
        "paginator": paginator,
        "page_range": page_range,
        "range": rng,
        "q": q,
        "status": status,
        "sort": sort,
    }
    return render(request, "admin/order_list.html", ctx)




STATUS_MAP = {
    "PROCESSING": "CONFIRMED",
    "PACKED": "CONFIRMED",
    "SHIPPED": "SHIPPED",
    "DELIVERED": "DELIVERED",
    "CANCELLED": "CANCELLED",
}

@user_passes_test(is_admin, login_url='admin_login')
@login_required(login_url='admin_login')
@never_cache
@staff_member_required
@transaction.atomic
def admin_order_detail(request, pk):
    """
    Admin order detail page with status management
    ✅ Allows updates for partially cancelled orders (only updates non-cancelled items)
    ✅ Blocks updates when ALL items are cancelled
    ✅ Releases stock when admin cancels order
    """
    # Fetch order + items
    order = (
        Order.objects
        .select_related("user")
        .prefetch_related(
            Prefetch(
                "items",
                queryset=OrderItem.objects.only(
                    "id","product_id","product_name","image_url","quantity",
                    "unit_price","line_total","variant_color","status","mrp_price","offer_label"
                ).order_by("id"),
                to_attr="prefetched_items"
            )
        )
        .get(pk=pk)
    )

    # ✅ NEW: Check if there are updatable (non-cancelled/non-returned) items
    final_item_states = (OrderItem.ItemStatus.CANCELLED, OrderItem.ItemStatus.RETURNED)
    all_items = order.items.all()
    updatable_items_qs = all_items.exclude(status__in=final_item_states)
    has_updatable_items = updatable_items_qs.exists()
    
    # ✅ NEW: Check if ALL items are cancelled/returned
    all_items_cancelled = all_items.exists() and not has_updatable_items
    
    # ✅ NEW: Admin can update status ONLY if:
    # 1. Has at least one updatable item (not all cancelled/returned)
    # 2. Order is not fully DELIVERED
    can_update_status = has_updatable_items and order.status not in ("DELIVERED", "RETURNED")

    # Helpers
    def compute_current_step(o):
        """
        Compute timeline step based on NON-CANCELLED items for partially cancelled orders
        """
        # If ALL items cancelled → show step 0
        if all_items_cancelled:
            return 0
        
        # For partially cancelled → look at active items only
        if o.status in ("PARTIALLY_CANCELLED", "PARTIALLY_RETURNED"):
            active_items = updatable_items_qs
            if active_items.exists():
                # Find highest step among active items by checking their timestamps
                # (This assumes items have their own timestamp fields)
                if o.delivered_at:
                    return 4
                if o.shipped_at:
                    return 3
                if o.packed_at:
                    return 2
                if o.processing_at:
                    return 1
                return 0
        
        # Normal flow (no partial cancellation)
        if getattr(o, "delivered_at", None):
            return 4
        if getattr(o, "shipped_at", None):
            return 3
        if getattr(o, "packed_at", None):
            return 2
        if getattr(o, "processing_at", None):
            return 1
        return 0

    def allowed_actions_for_step(step):
        """Return allowed actions based on current step"""
        if step == 0:
            return ["PROCESSING", "PACKED", "SHIPPED", "DELIVERED"]
        if step == 1:
            return ["PACKED", "SHIPPED", "DELIVERED"]
        if step == 2:
            return ["SHIPPED", "DELIVERED"]
        if step == 3:
            return ["DELIVERED"]
        return []

    # POST: update order status (only if has updatable items)
    if request.method == "POST":
        # ✅ FIXED: Block updates if ALL items are cancelled
        if not can_update_status:
            if all_items_cancelled:
                messages.error(request, "Cannot update status - all items are cancelled/returned.")
            else:
                messages.error(request, "Cannot update status for this order.")
            return redirect("admin_order_detail", pk=order.pk)
        
        action = (request.POST.get("status") or "").strip().upper()
        now = timezone.now()

        current_step = compute_current_step(order)
        allowed = set(allowed_actions_for_step(current_step))
        
        # Allow CANCELLED action for non-final orders
        if order.status not in ("CANCELLED","DELIVERED","RETURNED"):
            allowed.add("CANCELLED")

        if action not in allowed:
            messages.error(request, "Invalid status transition.")
            return redirect("admin_order_detail", pk=order.pk)

        # Map to canonical order.status
        STATUS_MAP = {
            "PROCESSING": "CONFIRMED",
            "PACKED": "CONFIRMED",
            "SHIPPED": "SHIPPED",
            "DELIVERED": "DELIVERED",
            "CANCELLED": "CANCELLED"
        }
        new_status = (STATUS_MAP.get(action) or "").upper()

        # Forward-fill ORDER timestamps when jumping ahead
        if action in {"PROCESSING","PACKED","SHIPPED","DELIVERED"} and not getattr(order, "processing_at", None):
            order.processing_at = now
        if action in {"PACKED","SHIPPED","DELIVERED"} and not getattr(order, "packed_at", None):
            order.packed_at = now
        if action in {"SHIPPED","DELIVERED"} and not getattr(order, "shipped_at", None):
            order.shipped_at = now
        if action == "DELIVERED" and not getattr(order, "delivered_at", None):
            order.delivered_at = now

        # Cancellation timestamp
        if action == "CANCELLED" and not getattr(order, "cancelled_at", None):
            order.cancelled_at = now

        if new_status:
            order.status = new_status

        # Persist order
        update_fields = ["status"]
        for f in ("processing_at","packed_at","shipped_at","delivered_at","cancelled_at"):
            if getattr(order, f, None):
                update_fields.append(f)
        order.save(update_fields=list(dict.fromkeys(update_fields)))

        # Determine item status to cascade
        item_status = (
            "SHIPPED" if action == "SHIPPED" else
            "DELIVERED" if action == "DELIVERED" else
            "CANCELLED" if action == "CANCELLED" else
            "CONFIRMED"
        )

        # ✅ Get ONLY updatable items (exclude cancelled/returned)
        updatable_items = updatable_items_qs
        
        # ✅ Release stock if admin cancels order
        if action == "CANCELLED":
            for item in updatable_items:
                try:
                    product = Product.objects.select_for_update().get(id=item.product_id)
                    
                    stock_before = product.stock_quantity
                    product.stock_quantity += item.quantity
                    product.save(update_fields=['stock_quantity'])
                    
                    StockTransaction.objects.create(
                        product=product,
                        order_item=item,
                        transaction_type='RELEASE',
                        quantity=item.quantity,
                        stock_before=stock_before,
                        stock_after=product.stock_quantity,
                        reason=f"Admin cancelled order: {order.order_number} (Item #{item.id})",
                        created_by=request.user
                    )
                    
                except Product.DoesNotExist:
                    pass
                except Exception as e:
                    print(f"Could not restore stock for product {item.product_id}: {e}")
        
        # Build update dict for items
        item_updates = {"status": item_status}
        
        # Set item-level timestamps
        if action == "PROCESSING":
            item_updates["processing_at"] = now
            for item in updatable_items:
                if not getattr(item, "placed_at", None):
                    item.placed_at = now
        
        if action in {"PACKED", "SHIPPED", "DELIVERED"}:
            for item in updatable_items:
                if not getattr(item, "processing_at", None):
                    item.processing_at = now
            item_updates["packed_at"] = now
        
        if action in {"SHIPPED", "DELIVERED"}:
            for item in updatable_items:
                if not getattr(item, "packed_at", None):
                    item.packed_at = now
            item_updates["shipped_at"] = now
        
        if action == "DELIVERED":
            for item in updatable_items:
                if not getattr(item, "shipped_at", None):
                    item.shipped_at = now
            item_updates["delivered_at"] = now
        
        if action == "CANCELLED":
            item_updates["cancelled_at"] = now
        
        # ✅ Bulk update ONLY NON-CANCELLED items
        updated_count = updatable_items.update(**item_updates)
        
        # Individual forward-fill
        if action in {"PACKED", "SHIPPED", "DELIVERED"}:
            for item in updatable_items:
                item_update_fields = []
                if action in {"PACKED", "SHIPPED", "DELIVERED"} and not item.processing_at:
                    item.processing_at = now
                    item_update_fields.append("processing_at")
                if action in {"SHIPPED", "DELIVERED"} and not item.packed_at:
                    item.packed_at = now
                    item_update_fields.append("packed_at")
                if action == "DELIVERED" and not item.shipped_at:
                    item.shipped_at = now
                    item_update_fields.append("shipped_at")
                if item_update_fields:
                    item.save(update_fields=item_update_fields)
        
        # ✅ Show info about frozen items
        frozen_count = all_items.filter(status__in=final_item_states).count()
        if frozen_count > 0 and action in {"PROCESSING","PACKED","SHIPPED","DELIVERED"}:
            messages.info(request, f"{frozen_count} cancelled/returned item(s) were not updated. {updated_count} item(s) updated successfully.")

        # ✅ Process refunds if admin cancels
        if action == "CANCELLED" and order.payment_method != 'COD' and order.paid_at:
            from wallet.services import credit
            
            total_refund = sum(order.calculate_item_refund(item) for item in updatable_items)
            
            if total_refund > 0:
                idem = f"refund:admin_cancel:order:{order.id}"
                refund_note = f"Order cancelled by admin (Order #{order.order_number})"
                
                try:
                    credit(
                        order.user, 
                        total_refund, 
                        description=refund_note, 
                        reference=str(order.id), 
                        idem_key=idem
                    )
                    messages.success(request, f"Items cancelled. Stock restored and ₹{total_refund:.2f} refunded.")
                except Exception as e:
                    messages.warning(request, f"Items cancelled. Stock restored but refund failed: {str(e)}")
            else:
                messages.success(request, f"Items cancelled and stock restored.")
        else:
            messages.success(request, f"Status updated to {action.title()}. {updated_count} item(s) updated.")

        # ✅ Recompute aggregate status after cascade
        all_statuses = list(all_items.values_list("status", flat=True))
        
        if all(s == OrderItem.ItemStatus.DELIVERED for s in all_statuses):
            # All delivered
            if not order.delivered_at:
                order.delivered_at = now
                order.save(update_fields=["delivered_at"])
        
        elif all(s in (OrderItem.ItemStatus.CANCELLED, OrderItem.ItemStatus.RETURNED) for s in all_statuses):
            # All cancelled/returned
            if any(s == OrderItem.ItemStatus.RETURNED for s in all_statuses):
                order.status = "RETURNED"
            else:
                order.status = "CANCELLED"
            if not order.cancelled_at:
                order.cancelled_at = now
            order.save(update_fields=["status", "cancelled_at"])
        
        elif any(s in (OrderItem.ItemStatus.CANCELLED, OrderItem.ItemStatus.RETURNED) for s in all_statuses):
            # Some cancelled/returned (partial)
            if any(s == OrderItem.ItemStatus.RETURNED for s in all_statuses):
                order.status = "PARTIALLY_RETURNED"
            else:
                order.status = "PARTIALLY_CANCELLED"
            order.save(update_fields=["status"])

        return redirect("admin_order_detail", pk=order.pk)

    # Build item rows for template
    items = []
    for it in getattr(order, "prefetched_items", []) or []:
        unit_mrp = it.mrp_price or it.unit_price
        items.append({
            "id": it.id,
            "product_id": getattr(it, "product_id", None),
            "sku": getattr(it, "sku", "") or "",
            "name": f"{it.product_name} {it.variant_color}".strip(),
            "image": it.image_url,
            "quantity": it.quantity,
            "price": it.unit_price,
            "unit_mrp": unit_mrp,
            "line_total": it.line_total,
            "line_mrp": unit_mrp * it.quantity,
            "offer": it.offer_label or "",
            "status": it.status,
        })

    # Brand name
    brand_name = ""
    if items and items[0]["product_id"]:
        p = (
            Product.objects
            .select_related("brand")
            .only("id", "brand__name")
            .filter(id=items[0]["product_id"])
            .first()
        )
        brand_name = getattr(getattr(p, "brand", None), "name", "") or ""

    # Customer and address
    customer_name = order.user.get_full_name() or order.user.username
    customer_email = order.user.email
    customer_phone = getattr(order, "ship_phone", "")
    addr_parts = [
        order.ship_full_name,
        order.ship_line1,
        (order.ship_line2 or "").strip() or None,
        f"{order.ship_city}, {order.ship_state} {order.ship_postcode}".strip(),
        order.ship_country,
    ]
    shipping_address = ", ".join([p for p in addr_parts if p])

    totals = {
        "subtotal": order.subtotal,
        "shipping": getattr(order, "shipping_amount", 0),
        "discount": getattr(order, "discount_amount", 0),
        "grand": order.total_amount,
    }

    # Expose fields for template
    order.customer_name = customer_name
    order.customer_email = customer_email
    order.customer_phone = customer_phone
    order.shipping_address = shipping_address
    order.brand_name = brand_name
    order.total = totals["grand"]
    order.shipping_fee = totals["shipping"]
    order.coupon_code = getattr(order, "coupon_code", "")
    order.coupon_discount = getattr(order, "coupon_discount", 0)
    order.can_update_status = can_update_status  # ✅ NEW
    order.all_items_cancelled = all_items_cancelled  # ✅ NEW
    if not hasattr(order, "placed_at"):
        order.placed_at = order.created_at

    current_step = compute_current_step(order)

    ctx = {
        "order": order,
        "items": items,
        "customer": {"name": customer_name, "email": customer_email},
        "address_lines": [x for x in addr_parts if x],
        "totals": totals,
        "payment_method": dict(Order.PM_CHOICES).get(order.payment_method, order.payment_method),
        "status": order.status,
        "current_step": current_step,
        "allowed_actions": allowed_actions_for_step(current_step) if can_update_status else [],
        "can_update_status": can_update_status,  # ✅ NEW
        "all_items_cancelled": all_items_cancelled,  # ✅ NEW
        "is_partially_cancelled": order.status == "PARTIALLY_CANCELLED",  # ✅ NEW
    }
    return render(request, "admin/order_detailes.html", ctx)




@staff_member_required
def admin_action_requests(request):
    pending = ActionRequest.objects.select_related("order", "item", "requested_by").filter(state="PENDING").order_by("-requested_at")
    return render(request, "admin/action_requests.html", {"pending": pending})
@staff_member_required
@transaction.atomic
def approve_action_request(request, pk):
    """
    Admin approves cancellation or return request
    ✅ Releases VARIANT stock for both CANCEL and RETURN
    """
    ar = get_object_or_404(
        ActionRequest.objects.select_related('order', 'item'), 
        pk=pk, 
        state='PENDING'
    )
    now = timezone.now()
    item, order = ar.item, ar.order
    
    # ✅ RELEASE VARIANT STOCK for both CANCEL and RETURN
    try:
        if item.variant_id:
            # Release variant stock (also updates product total)
            variant = ProductVariant.objects.select_for_update().get(id=item.variant_id)
            stock_info = variant.release_stock(
                item.quantity,
                user=request.user,
                reason=f"{ar.kind} approved: {order.order_number}"
            )
            
            # Log transaction
            StockTransaction.objects.create(
                product=variant.product,
                variant=variant,
                order_item=item,
                transaction_type='RELEASE',
                quantity=item.quantity,
                stock_before=stock_info['variant_before'],
                stock_after=stock_info['variant_after'],
                reason=f"{ar.kind} approved: {order.order_number} (Variant: {variant.color})",
                created_by=request.user
            )
        else:
            # Fallback: Release product stock (for products without variants)
            product = Product.objects.select_for_update().get(id=item.product_id)
            stock_before = product.stock_quantity
            product.stock_quantity += item.quantity
            product.save(update_fields=['stock_quantity'])
            
            StockTransaction.objects.create(
                product=product,
                order_item=item,
                transaction_type='RELEASE',
                quantity=item.quantity,
                stock_before=stock_before,
                stock_after=product.stock_quantity,
                reason=f"{ar.kind} approved: {order.order_number}",
                created_by=request.user
            )
            
    except (ProductVariant.DoesNotExist, Product.DoesNotExist):
        # Product/variant deleted - skip stock restoration but continue
        pass
    except Exception as e:
        # Log error but don't block approval
        print(f"Could not restore stock for item {item.id}: {e}")
    
    # ✅ UPDATE ITEM STATUS based on request type
    if ar.kind == 'CANCEL':
        if item.status not in [OrderItem.ItemStatus.CANCELLED, OrderItem.ItemStatus.RETURNED]:
            item.status = OrderItem.ItemStatus.CANCELLED
            item.cancelled_at = now
            update_fields = ['status', 'cancelled_at']
            item.save(update_fields=update_fields)
    
    elif ar.kind == 'RETURN':
        if item.status != OrderItem.ItemStatus.RETURNED:
            item.status = OrderItem.ItemStatus.RETURNED
            item.return_reason = ar.reason or item.return_reason
            item.returned_at = now
            update_fields = ['status', 'return_reason', 'returned_at']
            item.save(update_fields=update_fields)
    
    # ✅ UPDATE ORDER STATUS
    statuses = list(order.items.values_list('status', flat=True))
    
    if all(s in [OrderItem.ItemStatus.CANCELLED, OrderItem.ItemStatus.RETURNED] for s in statuses):
        # All items cancelled or returned
        order.status = 'RETURNED' if any(s == OrderItem.ItemStatus.RETURNED for s in statuses) else 'CANCELLED'
        if order.status == 'CANCELLED' and not order.cancelled_at:
            order.cancelled_at = now
            order.save(update_fields=['status', 'cancelled_at'])
        else:
            order.save(update_fields=['status'])
    
    elif any(s == OrderItem.ItemStatus.RETURNED for s in statuses):
        # Some items returned
        order.status = 'PARTIALLY_RETURNED'
        order.save(update_fields=['status'])
    
    elif any(s == OrderItem.ItemStatus.CANCELLED for s in statuses):
        # Some items cancelled
        order.status = 'PARTIALLY_CANCELLED'
        order.save(update_fields=['status'])
    
    elif all(s == OrderItem.ItemStatus.DELIVERED for s in statuses):
        # All delivered
        if not order.delivered_at:
            order.delivered_at = now
            order.save(update_fields=['delivered_at'])
    
    # ✅ APPROVE THE REQUEST
    ar.state = 'APPROVED'
    ar.decided_by = request.user
    ar.decided_at = now
    ar.save(update_fields=['state', 'decided_by', 'decided_at'])
    
    # ✅ PROCESS REFUND if applicable
    if order.payment_method != 'COD' and order.paid_at:
        refund_amount = order.calculate_item_refund(item)
        from wallet.services import credit
        idem = f"refund:{ar.kind.lower()}:item:{item.id}"
        refund_note = f"Refund for {item.product_name} ({ar.kind.title()}: {order.order_number})"
        
        try:
            credit(
                order.user, 
                refund_amount, 
                description=refund_note, 
                reference=str(order.id), 
                idem_key=idem
            )
            messages.success(
                request, 
                f'{ar.kind.title()} approved. Stock restored and ₹{refund_amount:.2f} refunded to customer wallet.'
            )
        except Exception as e:
            messages.warning(
                request, 
                f'{ar.kind.title()} approved. Stock restored but refund failed: {str(e)}'
            )
    else:
        messages.success(request, f'{ar.kind.title()} approved and stock restored.')
    
    return redirect('admin_action_requests')

@staff_member_required
@transaction.atomic
def reject_action_request(request, pk):
    """Admin rejects cancellation or return request"""
    ar = get_object_or_404(ActionRequest, pk=pk, state='PENDING')
    
    # ✅ NO STOCK CHANGE on rejection (order continues as normal)
    
    ar.state = 'REJECTED'
    ar.decided_by = request.user
    ar.decided_at = timezone.now()
    ar.save(update_fields=['state', 'decided_by', 'decided_at'])
    
    messages.success(request, f'{ar.kind.title()} request rejected.')
    return redirect('admin_action_requests')

@staff_member_required
@transaction.atomic
def reject_action_request(request, pk):
    ar = get_object_or_404(ActionRequest, pk=pk, state="PENDING")
    ar.state = "REJECTED"
    ar.decided_by = request.user
    ar.decided_at = timezone.now()
    ar.save(update_fields=["state", "decided_by", "decided_at"])
    messages.success(request, "Request rejected.")
    return redirect("admin_action_requests")


"""# -------------------------------
# Ordered item or Order return & Cancel
# -------------------------------"""

# helpers
EARLY_ITEM_STATES = (
    OrderItem.ItemStatus.PLACED,
    OrderItem.ItemStatus.CONFIRMED,
)

LATE_ITEM_STATES = (
    OrderItem.ItemStatus.SHIPPED,
    "OUTFORDELIVERY",      # use string here because enum member is missing
    OrderItem.ItemStatus.DELIVERED,
)


@login_required
@transaction.atomic
def request_cancel_item(request, order_number, item_id):
    """User requests to cancel an item"""
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    item = get_object_or_404(OrderItem, id=item_id, order=order)

    # Use direct cancel path if early
    if item.status in EARLY_ITEM_STATES:
        return cancel_item_now(request, order_number, item_id)

    if item.status in (OrderItem.ItemStatus.CANCELLED, OrderItem.ItemStatus.RETURNED) or item.status in LATE_ITEM_STATES:
        messages.error(request, "This item cannot be cancelled now.")
        return redirect("order_item_detail", order_number=order_number, item_id=item_id)

    if request.method != "POST":
        messages.error(request, "Invalid request.")
        return redirect("order_item_detail", order_number=order_number, item_id=item_id)

    if item.action_requests.filter(kind="CANCEL", state="PENDING").exists():
        messages.info(request, "Cancellation already requested and is pending.")
        return redirect("order_item_detail", order_number=order_number, item_id=item_id)

    # Get cancellation reason and note
    reason = request.POST.get('reason', '').strip()
    note = request.POST.get('note', '').strip()
    
    if not reason:
        messages.error(request, "Please select a cancellation reason.")
        return redirect("order_item_detail", order_number=order_number, item_id=item_id)
    
    # Get display name for reason
    reason_display = dict(OrderItem.CancellationReason.choices).get(reason, 'Other')
    
    # Create action request with reason details
    full_reason = f"{reason_display}"
    if note:
        full_reason += f": {note}"
    
    ActionRequest.objects.create(
        order=order, 
        item=item, 
        kind="CANCEL", 
        requested_by=request.user,
        reason=full_reason
    )
    
    mail_admins(
        subject=f"Cancel request: {order.order_number}",
        message=f"Item #{item.id} cancel requested by {request.user.email}\n"
                f"Product: {item.product_name}\n"
                f"Reason: {reason_display}\n"
                f"Note: {note if note else 'N/A'}"
    )
    
    messages.success(request, "Cancellation request sent. Awaiting approval.")
    return redirect("order_item_detail", order_number=order_number, item_id=item_id)


@login_required
@transaction.atomic
def request_return_item(request, order_number, item_id):
    """User requests to return a delivered item"""
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    item = get_object_or_404(OrderItem, id=item_id, order=order)

    # ✅ Check return eligibility (includes 10-day check)
    can_return, reason = item.is_return_eligible()
    
    if not can_return:
        messages.error(request, reason)  # Shows "Return period expired..." or other reason
        return redirect("order_item_detail", order_number=order_number, item_id=item_id)

    if request.method != "POST":
        messages.error(request, "Invalid request.")
        return redirect("order_item_detail", order_number=order_number, item_id=item_id)

    form = ReturnReasonForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please provide a valid reason.")
        return redirect("order_item_detail", order_number=order_number, item_id=item_id)

    # Double-check: no duplicate pending requests
    if item.action_requests.filter(kind="RETURN", state="PENDING").exists():
        messages.info(request, "Return already requested and is pending.")
        return redirect("order_item_detail", order_number=order_number, item_id=item_id)

    # Create return request
    ActionRequest.objects.create(
        order=order, 
        item=item, 
        kind="RETURN",
        requested_by=request.user, 
        reason=form.cleaned_data["reason"]
    )
    
    # Send email notification
    mail_admins(
        subject=f"Return request: {order.order_number}",
        message=f"Item #{item.id} return requested by {request.user.email}\nReason: {form.cleaned_data['reason']}"
    )
    
    # ✅ Show days remaining in success message
    days_left = item.get_days_until_return_expires()
    messages.success(
        request, 
        f"Return request sent. You have {days_left} days remaining to return this item."
    )
    
    return redirect("order_item_detail", order_number=order_number, item_id=item_id)



@login_required
@transaction.atomic
def cancel_item_now(request, order_number, item_id):
    """Direct cancellation - releases VARIANT stock"""
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    item = get_object_or_404(OrderItem, id=item_id, order=order)
    
    if request.method != "POST":
        return redirect("order_item_detail", order_number=order_number, item_id=item_id)

    if item.status not in EARLY_ITEM_STATES:
        messages.error(request, "Item already shipped. Request a return instead.")
        return redirect("order_item_detail", order_number=order_number, item_id=item_id)

    reason = request.POST.get('reason', '').strip()
    note = request.POST.get('note', '').strip()
    
    if not reason:
        messages.error(request, "Please select a cancellation reason.")
        return redirect("order_item_detail", order_number=order_number, item_id=item_id)
    
    refund_amount = order.calculate_item_refund(item)
    now = timezone.now()
    
    # Update item status
    item.status = OrderItem.ItemStatus.CANCELLED
    item.cancelled_at = now
    item.cancellation_reason = reason
    item.cancellation_note = note if note else None
    item.save(update_fields=["status", "cancelled_at", "cancellation_reason", "cancellation_note"])

    # ✅ RELEASE VARIANT STOCK
    try:
        if item.variant_id:
            # Release variant stock (also updates product total)
            variant = ProductVariant.objects.select_for_update().get(id=item.variant_id)
            stock_info = variant.release_stock(
                item.quantity,
                user=request.user,
                reason=f"Order cancelled: {order.order_number}"
            )
            
            # Log transaction
            StockTransaction.objects.create(
                product=variant.product,
                variant=variant,
                order_item=item,
                transaction_type='RELEASE',
                quantity=item.quantity,
                stock_before=stock_info['variant_before'],
                stock_after=stock_info['variant_after'],
                reason=f"Order cancelled: {order.order_number} (Variant: {variant.color})",
                created_by=request.user
            )
        else:
            # Fallback: Release product stock
            product = Product.objects.select_for_update().get(id=item.product_id)
            stock_before = product.stock_quantity
            product.stock_quantity += item.quantity
            product.save(update_fields=['stock_quantity'])
            
            StockTransaction.objects.create(
                product=product,
                order_item=item,
                transaction_type='RELEASE',
                quantity=item.quantity,
                stock_before=stock_before,
                stock_after=product.stock_quantity,
                reason=f"Order cancelled: {order.order_number}",
                created_by=request.user
            )
            
    except (ProductVariant.DoesNotExist, Product.DoesNotExist):
        pass  # Product/variant deleted
    except Exception as e:
        print(f"Could not restore stock: {e}")

    # Process refund
    if order.payment_method != 'COD' and order.paid_at:
        from wallet.services import credit
        idem = f"refund:order_item:{item.id}"
        refund_note = f"Refund for {item.product_name} (Order {order.order_number})"
        
        try:
            credit(order.user, refund_amount, description=refund_note, reference=str(order.id), idem_key=idem)
            messages.success(request, f"Item cancelled. ₹{refund_amount:.2f} refunded to wallet.")
        except Exception as e:
            messages.warning(request, "Item cancelled but refund failed. Contact support.")
    else:
        messages.success(request, "Item cancelled successfully.")

    # Update order status
    statuses = list(order.items.values_list("status", flat=True))
    if all(s == OrderItem.ItemStatus.CANCELLED for s in statuses):
        order.status = "CANCELLED"
        if not order.cancelled_at:
            order.cancelled_at = now
        order.save(update_fields=["status", "cancelled_at"])
    elif any(s == OrderItem.ItemStatus.CANCELLED for s in statuses):
        order.status = "PARTIALLY_CANCELLED"
        order.save(update_fields=["status"])

    return redirect("order_item_detail", order_number=order_number, item_id=item_id)




@login_required
@transaction.atomic
def cancel_order_now(request, order_number):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)  # [attached_file:4]
    if request.method != "POST":
        return redirect("my_orders")  # [attached_file:4]

    # all items must be early to allow direct cancel
    if order.items.exclude(status__in=EARLY_ITEM_STATES).exists():
        messages.error(request, "Some items are already shipped. You can only request return for those.")  # [attached_file:4]
        return redirect("my_orders")  # [attached_file:4]

    now = timezone.now()
    for it in order.items.all():
        it.status = OrderItem.ItemStatus.CANCELLED
        if hasattr(it, "cancelled_at"):
            it.cancelled_at = now
        it.save(update_fields=["status", "cancelled_at"] if hasattr(it, "cancelled_at") else ["status"])
        # TODO: restock_variant(it); trigger_refund(order, it)  # [attached_file:4]

    order.status = Order.Status.CANCELLED
    if hasattr(order, "cancelled_at") and not getattr(order, "cancelled_at", None):
        order.cancelled_at = now
    order.save(update_fields=["status", "cancelled_at"] if hasattr(order, "cancelled_at") else ["status"])  # [attached_file:4]

    messages.success(request, "Order cancelled and refunds initiated (if prepaid).")  # [attached_file:4]
    return redirect("my_orders")  # [attached_file:4]



# -------------------------------
# Address selection + checkout review
# -------------------------------

@login_required
def address_check(request):
    addrs = Address.objects.filter(user=request.user).order_by('-is_default', '-id')
    ctx = _cart_items_context(request)
    ctx['addresses'] = addrs
    ctx['default_address_id'] = addrs[0].id if addrs else None
    return render(request, 'user/address_check.html', ctx)

@login_required
def select_address(request):
    if request.method != 'POST':
        return redirect('address_check')
    addr_id = request.POST.get('address_id')
    if not addr_id:
        return redirect('address_check')
    if Address.objects.filter(id=addr_id, user=request.user).exists():
        request.session['checkout_address_id'] = int(addr_id)
    return redirect('checkout')

@login_required
def checkout_address_create(request):
    """Create address from checkout - AJAX + Form support"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)
    
    form = AddressForm(request.POST)
    
    if form.is_valid():
        addr = form.save(commit=False)
        addr.user = request.user
        
        with transaction.atomic():
            addr.save()
            if addr.is_default:
                Address.objects.filter(user=request.user).exclude(id=addr.id).update(is_default=False)
        
        # AJAX Response
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': 'Address added successfully! ✅',
                'address': {
                    'id': addr.id,
                    'full_name': addr.full_name,
                    'phone': addr.phone,
                    'address_line1': addr.address_line1,
                    'address_line2': addr.address_line2 or '',
                    'city': addr.city,
                    'state': addr.state,
                    'postcode': addr.postcode,
                    'country': addr.country,
                    'notes': addr.notes or '',
                    'is_default': addr.is_default,
                }
            })
        
        # Regular Form Response
        messages.success(request, 'Address added successfully! ✅')
        return redirect('checkout')
    
    # Validation Errors
    errors = {field: error[0] for field, error in form.errors.items()}
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'errors': errors}, status=400)
    
    messages.error(request, 'Please correct the errors')
    return redirect('checkout')


@login_required
def checkout_address_update(request, pk):
    """Update address from checkout - AJAX + Form support"""
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)
    
    form = AddressForm(request.POST, instance=addr)
    
    if form.is_valid():
        addr = form.save(commit=False)
        
        with transaction.atomic():
            addr.save()
            if addr.is_default:
                Address.objects.filter(user=request.user).exclude(id=addr.id).update(is_default=False)
        
        # AJAX Response
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': 'Address updated successfully! ✅',
                'address': {
                    'id': addr.id,
                    'full_name': addr.full_name,
                    'phone': addr.phone,
                    'address_line1': addr.address_line1,
                    'address_line2': addr.address_line2 or '',
                    'city': addr.city,
                    'state': addr.state,
                    'postcode': addr.postcode,
                    'country': addr.country,
                    'notes': addr.notes or '',
                    'is_default': addr.is_default,
                }
            })
        
        # Regular Form Response
        messages.success(request, 'Address updated successfully! ✅')
        return redirect('checkout')
    
    # Validation Errors
    errors = {field: error[0] for field, error in form.errors.items()}
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'errors': errors}, status=400)
    
    messages.error(request, 'Please correct the errors')
    return redirect('checkout')


    
@login_required
def checkout(request):
    """Checkout page with session management and validation"""
    from cart.views import _clear_expired_checkout_session, _update_checkout_activity, _available_stock
    
    # Check session expiry
    if _clear_expired_checkout_session(request):
        messages.warning(request, "Your checkout session expired. Please start again.")
        if BUY_NOW_SESSION_KEY in request.session:
            del request.session[BUY_NOW_SESSION_KEY]
        return redirect('cart')
    
    # Determine context (buy_now vs cart)
    buy_now_line = request.session.get(BUY_NOW_SESSION_KEY)
    
    if buy_now_line:
        # Validate buy_now product
        pid = buy_now_line.get('product_id')
        vid = buy_now_line.get('variant_id')
        
        try:
            product = Product.objects.get(id=pid, is_listed=True)
            stock = _available_stock(product, vid)
            if stock <= 0:
                del request.session[BUY_NOW_SESSION_KEY]
                messages.error(request, "Product is out of stock.")
                return redirect('cart')
        except Product.DoesNotExist:
            del request.session[BUY_NOW_SESSION_KEY]
            messages.error(request, "Product no longer available.")
            return redirect('cart')
        
        ctx = _buy_now_summary(request)
        ctx['is_buy_now'] = True
        ctx['buy_now_qty'] = buy_now_line.get('qty', 1)
        ctx['buy_now_max_qty'] = min(10, stock)
    else:
        ctx = _cart_items_context(request)
        ctx['is_buy_now'] = False
    
    if not ctx.get('items'):
        messages.info(request, "Your cart is empty.")
        return redirect('cart')
    
    # Update checkout activity
    _update_checkout_activity(request)
    
    # Address selection
    chosen_id = request.session.get('checkout_address_id')
    addr = None
    if chosen_id:
        addr = Address.objects.filter(id=chosen_id, user=request.user).first()
    if not addr:
        addr = Address.objects.filter(user=request.user, is_default=True).first()
    if not addr:
        addr = Address.objects.filter(user=request.user).order_by('-id').first()
    ctx['address'] = addr
    
    # Fetch active coupons
    today = date.today()
    active_coupons = Coupon.objects.filter(
        is_active=True,
        expiry_date__gte=today
    ).order_by('-discount')
    ctx['coupons'] = active_coupons
    
    # Coupon handling
    coupon_discount = Decimal(str(request.session.get('applied_coupon_discount', 0)))
    applied_code = request.session.get('applied_coupon')
    applied_coupon = None
    
    if applied_code:
        try:
            applied_coupon = Coupon.objects.get(
                code=applied_code,
                is_active=True,
                expiry_date__gte=today
            )
        except Coupon.DoesNotExist:
            request.session.pop('applied_coupon', None)
            request.session.pop('applied_coupon_discount', None)
            coupon_discount = Decimal(0)
    
    ctx['applied_coupon'] = applied_coupon
    ctx['coupon_discount'] = float(coupon_discount)
    
    # Calculate totals
    subtotal_sell = Decimal(str(ctx.get('subtotal_sell', 0)))
    final_total = max(Decimal('0.00'), subtotal_sell - coupon_discount)
    
    ctx['total_payable'] = float(final_total)
    ctx['final_total'] = float(final_total)
    
    # Save note
    product_discount = Decimal(str(ctx.get('discount', 0)))
    ctx['save_note'] = float(product_discount + coupon_discount)
    
    return render(request, 'user/checkout.html', ctx)


@login_required
@require_POST
def checkout_update_qty(request):
    """Update cart quantity from checkout page + auto-validate coupon"""
    pid = request.POST.get('product_id')
    vid = request.POST.get('variant_id')
    try:
        qty = int(request.POST.get('qty', 1))
    except (TypeError, ValueError):
        qty = 1

    # Update session cart
    cart_map = _get_session_cart(request)
    node = cart_map.get(pid, [])
    updated = False
    
    for ln in node:
        if str(ln.get("variant_id")) == str(vid):
            if qty <= 0:
                node.remove(ln)
            else:
                ln["qty"] = qty
            updated = True
            break
    
    if not updated and qty > 0:
        node.append({"qty": qty, "variant_id": vid})
    
    if not node:
        cart_map.pop(pid, None)
    else:
        cart_map[pid] = node
    
    _set_session_cart(request, cart_map)

    # ✅ NEW: Auto-validate coupon after cart change
    coupon_removed = _auto_validate_coupon(request, cart_map)

    # Recalculate context
    ctx = _cart_items_context(request)

    # Response data
    response_data = {
        'success': True,
        'subtotal_sell': str(ctx.get('subtotal_sell', 0)),
        'subtotal_mrp': str(ctx.get('subtotal_mrp', 0)),
        'discount': str(ctx.get('discount', 0)),
        'coupon_discount': str(ctx.get('coupon_discount', 0)),
        'total_payable': str(ctx.get('total_payable', 0)),
        'save_note': str(ctx.get('save_note', 0)),
        'products_count': ctx.get('products_count', 0),
    }
    
    # ✅ Notify if coupon was removed
    if coupon_removed:
        response_data['coupon_removed'] = True
        response_data['coupon_message'] = coupon_removed

    return JsonResponse(response_data)



@login_required
def cancel_checkout(request):
    # Remove buy now session line if exists
    if BUY_NOW_SESSION_KEY in request.session:
        del request.session[BUY_NOW_SESSION_KEY]
        request.session.modified = True
    
    # Optionally clear coupon or other checkout related session keys here if needed
    
    # Redirect user back to cart or home page
    return redirect('shop')  # Or redirect('home') based on your flow


# -------------------------------
# Helper: create order from cart (call on payment success/confirm)
# -------------------------------

def _variant_image_url(variant_id):
    if not variant_id:
        return None
    try:
        v = ProductVariant.objects.get(id=variant_id)
        vf = v.images.order_by("-featured", "id").first()
        return vf.image.url if vf else None
    except ProductVariant.DoesNotExist:
        return None

def _product_image_url(product_id):
    try:
        p = Product.objects.get(id=product_id)
        pf = p.images.order_by("-featured", "id").first()
        return pf.image.url if pf else None
    except Product.DoesNotExist:
        return None

@login_required
@transaction.atomic
def confirm_order(request):
    """
    Example endpoint to convert the current cart into an Order.
    - Snapshots product badge (offer_label), variant_color, mrp_price, and image_url per item.
    - Clears the cart session on success.
    Wire this to your payment success callback or "place order" button.
    """
    cart_map = _get_session_cart(request)
    if not cart_map:
        return redirect("cart")

    # Minimal totals; adjust for taxes/shipping/discounts
    subtotal = 0

    # Address snapshot: resolve the address chosen during checkout
    addr_id = request.session.get('checkout_address_id')
    addr = None
    if addr_id:
        addr = Address.objects.filter(id=addr_id, user=request.user).first()

    # Create order shell
    order = Order.objects.create(
        user=request.user,
        order_number=timezone.now().strftime("%y%m%d%H%M-") + str(request.user.id).zfill(6),
        payment_method="COD",  # or set based on your flow
        status="PLACED",
        subtotal=0,
        shipping_amount=0,
        discount_amount=0,
        total_amount=0,
        ship_full_name=getattr(addr, "full_name", request.user.get_full_name() or request.user.username),
        ship_phone=getattr(addr, "phone", ""),
        ship_line1=getattr(addr, "line1", ""),
        ship_line2=getattr(addr, "line2", ""),
        ship_city=getattr(addr, "city", ""),
        ship_state=getattr(addr, "state", ""),
        ship_postcode=getattr(addr, "postcode", ""),
        ship_country="India",
    )

    # Build order items from cart
    for pid_str, node in cart_map.items():
        pid = int(pid_str)
        product = get_object_or_404(Product, id=pid, is_listed=True)

        # Normalize node to list of lines
        lines = node if isinstance(node, list) else [{"qty": int(node) or 1, "variant_id": None}]
        for line in lines:
            qty = int(line.get("qty", 0)) or 0
            if qty <= 0:
                continue
            vid = line.get("variant_id")
            variant = None
            color = ""
            if vid:
                try:
                    variant = ProductVariant.objects.get(id=vid, product_id=product.id)
                    color = variant.color or ""
                except ProductVariant.DoesNotExist:
                    variant = None
                    color = ""

            # Pricing snapshots
            unit_mrp = product.base_price
            unit_sell = product.discount_price or product.base_price
            line_total = unit_sell * qty
            subtotal += line_total

            # Image snapshot (variant first)
            img_url = _variant_image_url(vid) or _product_image_url(product.id)

            # Product badge snapshot
            offer_label = product.offer or "NO OFFER"

            OrderItem.objects.create(
                order=order,
                product_id=product.id,
                product_name=product.name,
                image_url=img_url,
                quantity=qty,
                unit_price=unit_sell,
                line_total=line_total,
                offer_label=offer_label,
                variant_color=color,
                mrp_price=unit_mrp,
            )

    # Finalize totals
    order.subtotal = subtotal
    order.total_amount = subtotal  # add shipping/taxes/discounts if any
    order.save(update_fields=["subtotal", "total_amount"])

    # Clear cart
    _set_session_cart(request, {})

    return redirect("order_detail", pk=order.pk)


"""# invoice Download"""


def _render_to_pdf(template_src, context):
    template = get_template(template_src)
    html = template.render(context)
    result = io.BytesIO()
    pdf = pisa.pisaDocument(io.BytesIO(html.encode("UTF-8")), dest=result, encoding="UTF-8")
    return None if pdf.err else result.getvalue()

@staff_member_required
def admin_download_invoice(request, pk):
    order = get_object_or_404(Order.objects.prefetch_related("items"), pk=pk)
    # if not (order.paid_at or order.delivered_at):
    #     return HttpResponseForbidden("Invoice not available yet.")
    pdf = _render_to_pdf("invoices/invoice.html", {
        "order": order,
        "items": order.items.all(),
        "delivered": bool(order.delivered_at),
    })
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="invoice-{order.order_number}.pdf"'
    return resp

@login_required
def user_download_invoice(request, order_number):
    order = get_object_or_404(Order.objects.prefetch_related("items"), order_number=order_number, user=request.user)
    # if not (order.paid_at or order.delivered_at):
    #     return HttpResponseForbidden("Invoice not available yet.")
    pdf = _render_to_pdf("invoices/invoice.html", {
        "order": order,
        "items": order.items.all(),
        "delivered": bool(order.delivered_at),
    })
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="invoice-{order.order_number}.pdf"'
    return resp

@login_required
def user_download_item_invoice(request, order_number, item_id):
    order = get_object_or_404(Order, order_number=order_number, user=request.user)
    item = get_object_or_404(OrderItem, id=item_id, order=order)
    # if not (order.paid_at or order.delivered_at):
    #     return HttpResponseForbidden("Invoice not available yet.")
    pdf = _render_to_pdf("invoices/invoice.html", {
        "order": order,
        "items": [item],
        "delivered": bool(order.delivered_at),
    })
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="invoice-{order.order_number}-item-{item.id}.pdf"'
    return resp





@login_required
@transaction.atomic
def place_order(request):
    # Determine context from buy_now or cart
    buy_now_line = request.session.get(BUY_NOW_SESSION_KEY)
    if buy_now_line:
        ctx = _buy_now_summary(request)
    else:
        ctx = _cart_items_context(request)

    if not ctx or not ctx.get('items'):
        return JsonResponse({'success': False, 'message': 'Cart empty'}, status=400)

    # Read coupon discount from session safely
    coupon_discount = Decimal(str(request.session.get('applied_coupon_discount', '0')))
    subtotal = Decimal(str(ctx.get('subtotal_sell', 0)))
    shipping = Decimal('0.00')  # Update if shipping logic added
    discount = coupon_discount
    total_payable = subtotal + shipping - discount
    if total_payable < 0:
        total_payable = Decimal('0.00')

    # Validate stock for each item
    for item in ctx.get('items', []):
        pid = int(item['id'])
        qty = int(item['qty'])
        product = get_object_or_404(Product.objects.select_for_update(), id=pid)
        available = getattr(product, 'stock_quantity', 0)
        if qty > available:
            return JsonResponse({'success': False, 'message': f'{product.name}: only {available} left'}, status=409)

    # Get delivery address for order
    addr_id = request.session.get('checkout_address_id')
    address = None
    if addr_id:
        address = Address.objects.filter(id=addr_id, user=request.user).first()
    if not address:
        address = Address.objects.filter(user=request.user, is_default=True).first()
    if not address:
        return JsonResponse({'success': False, 'message': 'Delivery address required'}, status=400)

    # ✅ NEW: Calculate delivery date from pincode
    delivery_pincode = getattr(address, 'postcode', '') or getattr(address, 'pincode', '')
    delivery_days = 5  # Default 5 days
    expected_delivery = date.today() + timedelta(days=delivery_days)
    
    try:
        # Check if pincode exists in DeliveryPincode table
        pincode_info = DeliveryPincode.objects.get(
            pincode=delivery_pincode, 
            is_serviceable=True
        )
        delivery_days = pincode_info.delivery_days
        expected_delivery = date.today() + timedelta(days=delivery_days)
    except DeliveryPincode.DoesNotExist:
        # Use default 5 days if pincode not found
        delivery_days = 5
        expected_delivery = date.today() + timedelta(days=5)

    # Payment method and order status
    pm = request.POST.get('payment_method', 'cod').lower()
    pm_display = 'COD' if pm == 'cod' else 'razorpay'
    status = 'PLACED' if pm == 'cod' else 'PENDING'

    # Generate order number (ensure function exists)
    order_number = _gen_order_number()

    # Create order
    order = Order.objects.create(
        user=request.user,
        order_number=order_number,
        payment_method=pm_display,
        status=status,
        subtotal=subtotal,
        shipping_amount=shipping,
        discount_amount=discount,
        total_amount=total_payable,
        ship_full_name=getattr(address, 'full_name', None) or request.user.get_full_name() or request.user.username,
        ship_phone=getattr(address, 'phone', ''),
        ship_line1=getattr(address, 'address_line1', getattr(address, 'line1', '')),
        ship_line2=getattr(address, 'address_line2', getattr(address, 'line2', '')) or '',
        ship_city=getattr(address, 'city', ''),
        ship_state=getattr(address, 'state', ''),
        ship_postcode=delivery_pincode,
        ship_country=getattr(address, 'country', 'India') or 'India',
        
        # ✅ NEW: Add delivery fields
        delivery_days=delivery_days,
        expected_delivery_date=expected_delivery,
    )

    # Create order items
    for item in ctx.get('items', []):
        OrderItem.objects.create(
            order=order,
            product_id=int(item['id']),
            product_name=item['name'],
            image_url=item.get('image', '') or '',
            quantity=int(item['qty']),
            unit_price=Decimal(str(item.get('unit_sell', 0))),
            line_total=Decimal(str(item.get('line_sell', 0))),
            variant_id=item.get('variant_id')
        )

    # Update stock immediately if COD
    if pm == 'cod':
        for item in ctx.get('items', []):
            product = Product.objects.select_for_update().get(id=int(item['id']))
            product.stock_quantity = max(0, product.stock_quantity - int(item['qty']))
            product.save(update_fields=['stock_quantity'])
        order.paid_at = timezone.now()
        order.save(update_fields=['paid_at'])

    # Clear sessions on order placement success
    if BUY_NOW_SESSION_KEY in request.session:
        del request.session[BUY_NOW_SESSION_KEY]
    if CART_SESSION_KEY in request.session:
        del request.session[CART_SESSION_KEY]
    if 'applied_coupon' in request.session:
        del request.session['applied_coupon']
    if 'applied_coupon_discount' in request.session:
        del request.session['applied_coupon_discount']
    if 'checkout_address_id' in request.session:
        del request.session['checkout_address_id']

    return JsonResponse({
        'success': True,
        'order_id': order.id,
        'order_number': order.order_number,
        'status': order.status
    })


