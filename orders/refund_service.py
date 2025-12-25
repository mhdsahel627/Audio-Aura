# orders/refund_service.py

from decimal import Decimal
from django.db import transaction
from django.conf import settings
from django.utils import timezone
import razorpay
from wallet.services import credit
from wallet.models import WalletAccount


# Initialize Razorpay client
razorpay_client = razorpay.Client(
    auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
)


@transaction.atomic
def process_order_item_refund(order_item, reason="Order cancellation/return"):
    """
    Process refund based on ORIGINAL payment method.
    
    Rules:
    - Razorpay payment → Refund to Razorpay
    - Wallet payment → Refund to Wallet
    - COD → Credit to Wallet (store credit)
    
    Args:
        order_item: OrderItem instance
        reason: Refund reason string
        
    Returns:
        dict: {
            'success': bool,
            'method': str,
            'amount': Decimal,
            'refund_id': str (optional)
        }
    """
    
    order = order_item.order
    refund_amount = order.calculate_item_refund(order_item)
    
    print(f"🔍 Processing refund for Order: {order.order_number}")
    print(f"💳 Payment Method: {order.payment_method}")
    print(f"💰 Refund Amount: ₹{refund_amount}")
    print(f"📦 Item: {order_item.product_name}")
    
    # ✅ CRITICAL: Check if already refunded
    if hasattr(order_item, 'refund_status') and order_item.refund_status in ['COMPLETED', 'PROCESSING']:
        print(f"⚠️ Refund already processed for item {order_item.id}")
        return {
            'success': False,
            'method': 'duplicate',
            'amount': Decimal('0'),
            'message': 'Refund already processed'
        }
    
    # ============================================
    # RAZORPAY PAYMENT - Refund via Razorpay API
    # ============================================
    if order.payment_method == 'razorpay':
        return _refund_razorpay(order, order_item, refund_amount, reason)
    
    # ============================================
    # WALLET PAYMENT - Refund to Wallet
    # ============================================
    elif order.payment_method == 'WALLET':
        return _refund_wallet(order, order_item, refund_amount, reason, is_cod=False)
    
    # ============================================
    # COD PAYMENT - Store Credit to Wallet
    # ============================================
    elif order.payment_method == 'COD':
        return _refund_wallet(order, order_item, refund_amount, reason, is_cod=True)
    
    # ============================================
    # UNKNOWN PAYMENT METHOD - Default to Wallet
    # ============================================
    else:
        print(f"⚠️ Unknown payment method: {order.payment_method}")
        return _refund_wallet(order, order_item, refund_amount, reason, is_cod=False)


def _refund_razorpay(order, order_item, amount, reason):
    """Refund via Razorpay API"""
    try:
        # Check if Razorpay payment ID exists
        if not order.razorpay_payment_id:
            print("❌ No Razorpay payment ID found! Falling back to wallet.")
            return _refund_wallet(order, order_item, amount, reason, is_cod=False)
        
        # Create Razorpay refund
        refund = razorpay_client.payment.refund(
            order.razorpay_payment_id,
            {
                "amount": int(amount * 100),  # Convert to paise
                "speed": "normal",
                "notes": {
                    "order_number": order.order_number,
                    "item_id": order_item.id,
                    "reason": reason
                }
            }
        )
        
        print(f"✅ Razorpay refund created: {refund['id']}")
        print(f"   Amount: ₹{amount}")
        print(f"   Status: {refund['status']}")
        
        # Update order item refund tracking
        if hasattr(order_item, 'refund_id'):
            order_item.refund_id = refund['id']
            order_item.refund_status = 'PROCESSING'
            order_item.refund_amount = amount
            order_item.refund_method = 'razorpay'
            order_item.save(update_fields=['refund_id', 'refund_status', 'refund_amount', 'refund_method'])
        
        # ✅ NO WALLET CREDIT!
        return {
            'success': True,
            'method': 'razorpay',
            'amount': amount,
            'refund_id': refund['id'],
            'message': f'Razorpay refund initiated: {refund["id"]}'
        }
        
    except razorpay.errors.BadRequestError as e:
        print(f"❌ Razorpay refund failed: {e}")
        # Fallback to wallet if Razorpay fails
        return _refund_wallet(order, order_item, amount, f"{reason} (Razorpay failed)", is_cod=False)
    
    except Exception as e:
        print(f"❌ Unexpected error in Razorpay refund: {e}")
        return _refund_wallet(order, order_item, amount, f"{reason} (Error)", is_cod=False)


def _refund_wallet(order, order_item, amount, reason, is_cod=False):
    """Refund to user's wallet"""
    try:
        # Ensure wallet exists
        wallet, _ = WalletAccount.objects.get_or_create(user=order.user)
        
        # Create description
        if is_cod:
            description = f"Store credit: {order_item.product_name} (Order {order.order_number})"
        else:
            description = f"Refund: {order_item.product_name} (Order {order.order_number})"
        
        # ✅ CRITICAL: Use proper idempotency key
        idem_key = f"refund:order_item:{order_item.id}"
        
        # Credit wallet with idempotency
        txn = credit(
            user=order.user,
            amount=amount,
            description=description,
            reference=str(order.id),  # Keep reference as order ID
            idem_key=idem_key          # Separate idempotency key
        )
        
        if txn is None:
            # Duplicate transaction blocked
            print(f"⚠️ Duplicate refund blocked for item {order_item.id}")
            return {
                'success': False,
                'method': 'duplicate',
                'amount': Decimal('0'),
                'message': 'Refund already processed'
            }
        
        print(f"✅ Wallet credited: ₹{amount}")
        print(f"   Transaction ID: {txn.id}")
        
        # Update order item refund tracking
        if hasattr(order_item, 'refund_status'):
            order_item.refund_status = 'COMPLETED'
            order_item.refund_amount = amount
            order_item.refund_method = 'store_credit' if is_cod else 'wallet'
            order_item.save(update_fields=['refund_status', 'refund_amount', 'refund_method'])
        
        return {
            'success': True,
            'method': 'wallet' if not is_cod else 'store_credit',
            'amount': amount,
            'transaction_id': txn.id,
            'message': f'Wallet credited: ₹{amount}'
        }
        
    except Exception as e:
        print(f"❌ Wallet credit failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'method': 'wallet',
            'amount': Decimal('0'),
            'message': f'Wallet credit failed: {str(e)}'
        }