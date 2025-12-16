# orders/services.py
from wallet.services import credit


def refund_shipping_if_applicable(order):
    """
    Refund shipping when entire order is cancelled
    Uses proportional shipping if partial cancellation
    """
    from decimal import Decimal
    
    all_items = order.items.all()
    cancelled_items = order.items.filter(
        status__in=['CANCELLED', 'RETURNED']
    )
    
    # Full refund if all items cancelled/returned
    all_cancelled = cancelled_items.count() == all_items.count()
    
    if all_cancelled and order.shipping_amount and order.shipping_amount > 0:
        idem = f"refund:order:{order.id}:shipping"
        credit(
            order.user,
            order.shipping_amount,
            description=f"Shipping refund (Order {order.order_number})",
            reference=str(order.id),
            idem_key=idem,
        )
    
    # ✅ OPTIONAL: Partial shipping refund if some items remain
    elif cancelled_items.exists() and order.shipping_amount > 0:
        # Calculate proportion of cancelled items
        total_value = sum(item.line_total for item in all_items)
        cancelled_value = sum(item.line_total for item in cancelled_items)
        
        if total_value > 0:
            cancelled_proportion = cancelled_value / total_value
            partial_shipping_refund = order.shipping_amount * Decimal(str(cancelled_proportion))
            
            if partial_shipping_refund > 0:
                idem = f"refund:order:{order.id}:shipping:partial"
                credit(
                    order.user,
                    partial_shipping_refund,
                    description=f"Partial shipping refund (Order {order.order_number})",
                    reference=str(order.id),
                    idem_key=idem,
                )
