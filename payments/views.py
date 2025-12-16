# payments/views.py

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from coupons.services import complete_coupon_usage
from django.contrib import messages
from django.db import transaction
from decimal import Decimal
import uuid
from django.utils import timezone
from cart.views import _buy_now_summary, _cart_items_context, BUY_NOW_SESSION_KEY, CART_SESSION_KEY
from user.models import Address
from orders.models import Order, OrderItem
from wallet.models import WalletAccount
from wallet.services import debit
from products.models import Product, ProductVariant, StockTransaction  # ✅ NEW IMPORT
from django.core.exceptions import ValidationError  # ✅ NEW IMPORT
import razorpay
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from django.views.decorators.http import require_POST
import hmac
import hashlib


def _gen_order_number():
    return timezone.now().strftime('%y%m%d%H%M') + '-' + uuid.uuid4().hex[:6].upper()


COD_MAX_AMOUNT = Decimal('3000.00')

# Initialize Razorpay client
razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

def _create_order_from_context(user, ctx, address, payment_method, status, subtotal, shipping, coupon_amount, total):
    """
    Helper function to create order with VARIANT stock management
    ✅ Updates both variant stock AND product total stock
    """
    
    # ✅ STEP 1: CREATE ORDER
    order = Order.objects.create(
        user=user,
        order_number=_gen_order_number(),
        paid_at=timezone.now() if status == 'PLACED' else None,
        payment_method=payment_method,
        status=status,
        subtotal=subtotal,
        shipping_amount=shipping,
        discount_amount=coupon_amount,
        total_amount=total,
        ship_full_name=(getattr(address, 'full_name', None) or user.get_full_name() or user.username),
        ship_phone=(getattr(address, 'phone', '') or ''),
        ship_line1=getattr(address, 'address_line1', getattr(address, 'line1', '')),
        ship_line2=getattr(address, 'address_line2', getattr(address, 'line2', '')) or '',
        ship_city=getattr(address, 'city', ''),
        ship_state=getattr(address, 'state', ''),
        ship_postcode=getattr(address, 'postcode', ''),
        ship_country=getattr(address, 'country', 'India') or 'India',
    )

    # ✅ STEP 2: CREATE ORDER ITEMS AND RESERVE VARIANT STOCK
    for it in ctx['items']:
        product_id = int(it['id'])
        variant_id = int(it.get('variant_id', 0))  # ✅ Get variant ID from cart
        quantity = int(it['qty'])
        
        # ✅ RESERVE VARIANT STOCK (not just product)
        try:
            if variant_id:
                # Reserve variant stock
                variant = ProductVariant.objects.select_for_update().get(id=variant_id)
                stock_info = variant.reserve_stock(
                    quantity, 
                    user=user, 
                    reason=f"Order placed: {order.order_number}"
                )
                
                product = variant.product
                
            else:
                # Fallback: No variant (shouldn't happen in your system)
                product = Product.objects.select_for_update().get(id=product_id)
                
                if product.stock_quantity < quantity:
                    raise ValidationError(
                        f"Insufficient stock for '{product.name}'. "
                        f"Only {product.stock_quantity} available."
                    )
                
                stock_before = product.stock_quantity
                product.stock_quantity -= quantity
                product.save(update_fields=['stock_quantity'])
                variant = None
                
        except (ProductVariant.DoesNotExist, Product.DoesNotExist):
            raise ValidationError(f"Product '{it['name']}' is no longer available.")
        
        # ✅ CREATE ORDER ITEM with variant_id
        order_item = OrderItem.objects.create(
            order=order,
            product_id=product_id,
            variant_id=variant_id if variant_id else None,  # ✅ Store variant ID
            product_name=it['name'],
            variant_color=it.get('color', ''),
            image_url=it.get('image') or '',
            quantity=quantity,
            unit_price=Decimal(str(it['unit_sell'])),
            line_total=Decimal(str(it['line_sell'])),
        )
        
        # ✅ LOG STOCK TRANSACTION
        if variant:
            StockTransaction.objects.create(
                product=product,
                variant=variant,  # ✅ Link to variant
                order_item=order_item,
                transaction_type='RESERVE',
                quantity=-quantity,
                stock_before=stock_info['variant_before'],
                stock_after=stock_info['variant_after'],
                reason=f"Order placed: {order.order_number} (Variant: {variant.color})",
                created_by=user
            )
        else:
            StockTransaction.objects.create(
                product=product,
                order_item=order_item,
                transaction_type='RESERVE',
                quantity=-quantity,
                stock_before=stock_before,
                stock_after=product.stock_quantity,
                reason=f"Order placed: {order.order_number}",
                created_by=user
            )
    
    return order

def _clear_cart_session(request, is_buy_now):
    """Helper function to clear cart/session"""
    if is_buy_now:
        request.session.pop(BUY_NOW_SESSION_KEY, None)
    else:
        request.session[CART_SESSION_KEY] = {}
    
    request.session.pop('checkout_address_id', None)
    request.session.pop('applied_coupon_discount', None)
    request.session.pop('applied_coupon_code', None)
    request.session.pop('applied_coupon', None)


@login_required
def payment(request):
    """Payment page - handles cart, buy_now, COD, Razorpay, and Wallet"""
    
    # Get address
    chosen_id = request.session.get('checkout_address_id')
    address = None
    if chosen_id:
        address = Address.objects.filter(id=chosen_id, user=request.user).first()
    if not address:
        address = Address.objects.filter(user=request.user, is_default=True).first()
    if not address:
        messages.error(request, "Add a delivery address to continue.")
        return redirect('address_check')

    # Get cart/buy_now data
    buy_now_line = request.session.get(BUY_NOW_SESSION_KEY)
    if buy_now_line:
        ctx = _buy_now_summary(request)
        is_buy_now = True
    else:
        ctx = _cart_items_context(request)
        is_buy_now = False

    if not ctx or not ctx.get('items'):
        messages.error(request, "Your cart is empty.")
        return redirect('cart')

    # Calculate totals
    coupon_amount = Decimal(str(request.session.get('applied_coupon_discount', 0)))
    subtotal = Decimal(str(ctx['subtotal_sell']))
    shipping = Decimal('0.00')
    grand_total = subtotal - coupon_amount + shipping

    # Payment options
    cod_available = grand_total <= COD_MAX_AMOUNT
    wallet_account, _ = WalletAccount.objects.get_or_create(user=request.user)
    wallet_balance = wallet_account.balance

    # Prepare cart items for display
    cart_items = [{
        'id': it['id'],
        'name': it['name'],
        'qty': it['qty'],
        'image_url': it.get('image') or '',
        'total': it['line_sell'],
    } for it in ctx['items']]

    # Base context
    page_ctx = {
        'cart_items': cart_items,
        'subtotal': subtotal,
        'delivery_text': "Free",
        'coupon_amount': coupon_amount,
        'grand_total': grand_total,
        'cod_available': cod_available,
        'cod_max': COD_MAX_AMOUNT,
        'wallet_balance': wallet_balance,
        'can_use_wallet': wallet_balance >= grand_total,
        'razorpay_enabled': False,
    }

    # Handle POST (payment method selection)
    if request.method == 'POST':
        pm = request.POST.get('payment_method')
        
        if pm not in ['cod', 'razorpay', 'wallet']:
            messages.error(request, "Please select a valid payment option.")
            return redirect('payment')

        # ✅ WRAP IN TRANSACTION (ensures stock rollback on error)
        try:
            with transaction.atomic():
                # COD Payment
                if pm == 'cod':
                    if grand_total > COD_MAX_AMOUNT:
                        messages.error(request, f"COD is not available for orders above ₹{COD_MAX_AMOUNT}.")
                        return redirect('payment')

                    order = _create_order_from_context(
                        user=request.user,
                        ctx=ctx,
                        address=address,
                        payment_method='COD',
                        status='PLACED',
                        subtotal=subtotal,
                        shipping=shipping,
                        coupon_amount=coupon_amount,
                        total=grand_total
                    )
                    
                    # ✅ CRITICAL FIX: Track coupon usage AFTER successful order
                    if 'applied_coupon_id' in request.session:
                        try:
                            from coupons.models import Coupon
                            coupon = Coupon.objects.get(id=request.session['applied_coupon_id'])
                            complete_coupon_usage(request.user, coupon, order)
                        except Coupon.DoesNotExist:
                            pass

                    _clear_cart_session(request, is_buy_now)
                    request.session['last_order_id'] = order.id

                    messages.success(request, "Order placed successfully!")
                    return redirect('payment_success')

                # Wallet Payment
                elif pm == 'wallet':
                    if wallet_balance < grand_total:
                        messages.error(request, "Insufficient wallet balance.")
                        return redirect('payment')

                    order = _create_order_from_context(
                        user=request.user,
                        ctx=ctx,
                        address=address,
                        payment_method='WALLET',
                        status='PLACED',
                        subtotal=subtotal,
                        shipping=shipping,
                        coupon_amount=coupon_amount,
                        total=grand_total
                    )

                    # Debit wallet
                    debit(
                        user=request.user,
                        amount=grand_total,
                        description=f"Order payment #{order.order_number}",
                        reference=order.order_number,
                        meta={"order_id": order.id}
                    )
                    
                    # ✅ CRITICAL FIX: Track coupon usage AFTER successful payment
                    if 'applied_coupon_id' in request.session:
                        try:
                            from coupons.models import Coupon
                            coupon = Coupon.objects.get(id=request.session['applied_coupon_id'])
                            complete_coupon_usage(request.user, coupon, order)
                        except Coupon.DoesNotExist:
                            pass

                    _clear_cart_session(request, is_buy_now)
                    request.session['last_order_id'] = order.id

                    messages.success(request, "Order placed successfully!")
                    return redirect('payment_success')

                # Razorpay Payment
                elif pm == 'razorpay':
                    total_paise = int(grand_total * 100)
                    
                    try:
                        razorpay_order = razorpay_client.order.create({
                            'amount': total_paise,
                            'currency': 'INR',
                            'payment_capture': '1',
                            'notes': {
                                'user_id': request.user.id,
                                'user_email': request.user.email
                            }
                        })
                    except Exception as e:
                        messages.error(request, f"Payment gateway error: {str(e)}")
                        return redirect('payment')

                    # ✅ Create PENDING order (stock already reserved)
                    order = _create_order_from_context(
                        user=request.user,
                        ctx=ctx,
                        address=address,
                        payment_method='razorpay',
                        status='PENDING',  # Will be PLACED after payment success
                        subtotal=subtotal,
                        shipping=shipping,
                        coupon_amount=coupon_amount,
                        total=grand_total
                    )

                    # Store in session for verification
                    request.session['razorpay_order_id'] = razorpay_order['id']
                    request.session['pending_order_id'] = order.id

                    # Update context with Razorpay data and re-render
                    page_ctx.update({
                        'razorpay_order_id': razorpay_order['id'],
                        'razorpay_key': settings.RAZORPAY_KEY_ID,
                        'razorpay_amount': total_paise,
                        'razorpay_enabled': True,
                        'order_id': order.id,
                    })

                    return render(request, 'user/payment.html', page_ctx)
        
        except ValidationError as e:
            # ✅ Stock validation failed - show error
            messages.error(request, str(e))
            return redirect('cart')
        
        except Exception as e:
            # ✅ Any other error - show generic message
            messages.error(request, "Failed to place order. Please try again.")
            return redirect('payment')

    # GET request - show payment page
    return render(request, 'user/payment.html', page_ctx)



@login_required
def payment_success(request):
    """Order success page"""
    order_id = request.session.pop('last_order_id', None)
    if order_id:
        order = get_object_or_404(Order, id=order_id, user=request.user)
    else:
        order = Order.objects.filter(user=request.user).order_by('-created_at').first()
        if not order:
            return redirect('shop')

    items = [{
        'name': oi.product_name,
        'qty': oi.quantity,
        'line_total': oi.line_total,
        'image': oi.image_url,
    } for oi in order.items.all()]

    ctx = {
        'order': order,
        'items': items,
        'order_id': order.order_number,
        'payment_time': order.paid_at or order.created_at,
        'payment_method': getattr(order, 'get_payment_method_display', lambda: order.payment_method)(),
        'sender_name': request.user.get_full_name() or request.user.username,
        'amount': order.total_amount,
    }
    return render(request, 'user/order_success.html', ctx)


@csrf_exempt
@require_POST
def razorpay_payment_handler(request):
    """Handle Razorpay payment verification"""
    try:
        data = json.loads(request.body.decode('utf-8'))
        razorpay_payment_id = data.get('razorpay_payment_id')
        razorpay_order_id = data.get('razorpay_order_id')
        razorpay_signature = data.get('razorpay_signature')
        
        if not all([razorpay_payment_id, razorpay_order_id, razorpay_signature]):
            return JsonResponse({'success': False, 'message': 'Missing payment data'}, status=400)

        # Verify signature
        generated_signature = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode('utf-8'),
            f"{razorpay_order_id}|{razorpay_payment_id}".encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        if generated_signature != razorpay_signature:
            # ✅ Mark order as failed (stock will be released later by admin/cron)
            pending_order_id = request.session.get('pending_order_id')
            if pending_order_id:
                Order.objects.filter(id=pending_order_id).update(status='FAILED')
            return JsonResponse({'success': False, 'message': 'Signature verification failed'}, status=400)

        # Get the pending order
        pending_order_id = request.session.get('pending_order_id')
        if not pending_order_id:
            return JsonResponse({'success': False, 'message': 'Order session expired'}, status=400)

        order = Order.objects.filter(
            id=pending_order_id,
            user=request.user,
            payment_method='razorpay',
            status='PENDING'
        ).first()

        if not order:
            return JsonResponse({'success': False, 'message': 'Order not found'}, status=404)

        # ✅ Mark as paid (stock already reserved during order creation)
        order.status = 'PLACED'
        order.paid_at = timezone.now()
        order.save(update_fields=['status', 'paid_at'])
        
        # ✅ CRITICAL FIX: Track coupon usage AFTER successful payment
        if 'applied_coupon_id' in request.session:
            try:
                from coupons.models import Coupon
                coupon = Coupon.objects.get(id=request.session['applied_coupon_id'])
                complete_coupon_usage(request.user, coupon, order)
            except Coupon.DoesNotExist:
                pass

        # Clear cart and session
        buy_now_line = request.session.get(BUY_NOW_SESSION_KEY)
        _clear_cart_session(request, bool(buy_now_line))
        request.session['last_order_id'] = order.id
        request.session.pop('pending_order_id', None)
        request.session.pop('razorpay_order_id', None)

        return JsonResponse({'success': True, 'order_id': order.id})

    except Exception as e:
        # ✅ Mark order as failed
        pending_order_id = request.session.get('pending_order_id')
        if pending_order_id:
            Order.objects.filter(id=pending_order_id).update(status='FAILED')
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


@login_required
def payment_failed(request):
    """Payment failure page"""
    order_id = request.session.get('pending_order_id')
    error_message = request.session.pop('payment_error_message', None)
    
    # ✅ Mark order as FAILED (admin can release stock later)
    if order_id:
        try:
            order = Order.objects.get(id=order_id, user=request.user)
            order.status = 'FAILED'
            order.save(update_fields=['status'])
        except Order.DoesNotExist:
            pass
    
    # Clear the pending order from session after marking as failed
    request.session.pop('pending_order_id', None)
    request.session.pop('razorpay_order_id', None)

    return render(request, 'user/payment_failed.html', {
        'error_message': error_message,
        'support_email': 'support@audioaura.com',
    })


@login_required
def retry_payment(request, order_id):
    """Retry payment for a failed order"""
    from datetime import timedelta
    
    # Get the failed order
    order = get_object_or_404(Order, id=order_id, user=request.user, status='FAILED')
    
    # ✅ Check if order is too old (7 days limit)
    if order.created_at < timezone.now() - timedelta(days=7):
        messages.error(request, "This order is too old to retry payment. Please place a new order.")
        return redirect('orders')
    
    # ✅ NOTE: Stock was already released when order was marked FAILED
    # So we need to re-reserve stock for retry
    try:
        with transaction.atomic():
            for order_item in order.items.all():
                product = Product.objects.select_for_update().get(id=order_item.product_id)
                
                # Check stock availability
                if product.stock_quantity < order_item.quantity:
                    messages.error(
                        request, 
                        f"Insufficient stock for '{product.name}'. Only {product.stock_quantity} available."
                    )
                    return redirect('orders')
                
                # Reserve stock again
                stock_before = product.stock_quantity
                product.stock_quantity -= order_item.quantity
                product.save(update_fields=['stock_quantity'])
                
                # Log transaction
                StockTransaction.objects.create(
                    product=product,
                    order_item=order_item,
                    transaction_type='RESERVE',
                    quantity=-order_item.quantity,
                    stock_before=stock_before,
                    stock_after=product.stock_quantity,
                    reason=f"Payment retry for order: {order.order_number}",
                    created_by=request.user
                )
    
    except ValidationError as e:
        messages.error(request, str(e))
        return redirect('orders')
    
    # Create new Razorpay order
    total_paise = int(order.total_amount * 100)
    
    try:
        razorpay_order = razorpay_client.order.create({
            'amount': total_paise,
            'currency': 'INR',
            'payment_capture': '1',
            'notes': {
                'user_id': request.user.id,
                'order_id': order.id,
                'retry': 'true'
            }
        })
    except Exception as e:
        messages.error(request, f"Payment gateway error: {str(e)}")
        return redirect('orders')
    
    # Update order status back to PENDING
    order.status = 'PENDING'
    order.save(update_fields=['status'])
    
    # Store in session
    request.session['razorpay_order_id'] = razorpay_order['id']
    request.session['pending_order_id'] = order.id
    request.session['retry_payment'] = True
    
    # Prepare cart items for display
    cart_items = [{
        'id': item.product_id,
        'name': item.product_name,
        'qty': item.quantity,
        'image_url': item.image_url,
        'total': item.line_total,
    } for item in order.items.all()]
    
    # Context for payment page
    context = {
        'cart_items': cart_items,
        'subtotal': order.subtotal,
        'delivery_text': "Free",
        'coupon_amount': order.discount_amount,
        'grand_total': order.total_amount,
        'razorpay_order_id': razorpay_order['id'],
        'razorpay_key': settings.RAZORPAY_KEY_ID,
        'razorpay_amount': total_paise,
        'razorpay_enabled': True,
        'order_id': order.id,
        'is_retry': True,
        'cod_available': False,  # Disable COD for retry
        'can_use_wallet': False,  # Disable wallet for retry
    }
    
    return render(request, 'user/payment.html', context)
