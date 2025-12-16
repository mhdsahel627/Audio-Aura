# orders/hooks.py (or wherever you handle paid orders)
from django.utils import timezone
from wallet.models import Referral, ReferralProfile, ReferralConfig
from wallet.services import credit  # <-- import the wallet credit helper

def qualify_referral_on_paid(order):
    """
    Call this once an order is confirmed as PAID.
    order.user        -> the new customer (referee)
    order.total       -> order amount
    """
    cfg = ReferralConfig.objects.first()
    if not cfg or not cfg.active:
        return

    # Find a pending referral for this user
    try:
        ref = Referral.objects.select_related("referrer").get(
            referee=order.user,
            status__in=["signed_up"]
        )
    except Referral.DoesNotExist:
        return  # user wasn't referred

    # Check minimum order amount
    if order.total < cfg.min_order_amount:
        ref.status = "rejected"
        ref.notes = f"Below minimum: {order.total}"
        ref.save(update_fields=["status", "notes"])
        return

    # Mark qualified and set reward amount
    ref.status = "qualified"
    ref.converted_at = timezone.now()
    ref.reward_amount = cfg.purchase_reward
    ref.save(update_fields=["status", "converted_at", "reward_amount"])

    # THIS is the line you asked about:
    # It credits the referrer’s wallet balance and writes a WalletTransaction row.
    credit(
        user=ref.referrer,                      # who receives the money
        amount=cfg.purchase_reward,             # how much to credit
        description="Referral reward",          # appears in transaction history
        reference=str(ref.id),                  # link back to Referral id
        meta={"referee": ref.referee_id}        # optional extra data
    )

    # Update aggregates on the referrer profile (optional but nice)
    rp = ref.referrer.referral_profile
    rp.total_referrals = Referral.objects.filter(referrer=ref.referrer, status="qualified").count()
    rp.lifetime_earnings = rp.lifetime_earnings + cfg.purchase_reward
    rp.save(update_fields=["total_referrals", "lifetime_earnings"])
