#wallet/service.py
from django.db import transaction
from decimal import Decimal
from .models import WalletAccount, WalletTransaction
from django.utils import timezone
from wallet.models import Referral, ReferralConfig, WalletAccount, WalletTransaction

# wallet/service.py  (augment existing credit)
from django.db.models import Q

def credit(user, amount, description="", reference="", meta=None, idem_key=None):
    meta = meta or {}
    with transaction.atomic():
        acct = WalletAccount.objects.select_for_update().get_or_create(user=user)[0]
        # Idempotency guard: skip if same key already credited for this account
        if idem_key and WalletTransaction.objects.filter(
            account=acct, kind=WalletTransaction.CREDIT, reference=idem_key
        ).exists():
            return None
        acct.balance = (acct.balance or Decimal("0")) + Decimal(amount)
        acct.save(update_fields=["balance"])
        return WalletTransaction.objects.create(
            account=acct,
            kind="CREDIT",
            amount=Decimal(amount),
            description=description,
            reference=idem_key or reference,
            meta=meta,
        )


def debit(user, amount, description="", reference="", meta=None):
    meta = meta or {}
    with transaction.atomic():
        acct = WalletAccount.objects.select_for_update().get(user=user)
        if acct.balance < Decimal(amount):
            raise ValueError("Insufficient wallet balance")
        acct.balance = acct.balance - Decimal(amount)
        acct.save(update_fields=["balance"])
        return WalletTransaction.objects.create(
            account=acct, kind="DEBIT", amount=amount,
            description=description, reference=reference, meta=meta
        )
        

def qualify_signup_referral_and_credit(referee):
    print("QUALIFY FUNCTION TRIGGERED", referee.id)

    cfg = ReferralConfig.objects.filter(active=True).first()
    if not cfg or cfg.signup_reward <= 0:
        return False

    with transaction.atomic():
        ref = (
            Referral.objects
            .select_for_update()
            .select_related("referrer")
            .filter(referee=referee)
            .first()
        )

        if not ref:
            return False

        if ref.status == "qualified":
            return False

        reward = cfg.signup_reward
        referrer = ref.referrer

        wallet, _ = WalletAccount.objects.select_for_update().get_or_create(user=referrer)

        wallet.balance = (wallet.balance or Decimal("0")) + reward
        wallet.save(update_fields=["balance"])

        WalletTransaction.objects.create(
            account=wallet,
            kind=WalletTransaction.CREDIT,
            amount=reward,
            description="Referral Signup Reward",
            reference=f"referral_signup_{referee.id}",
            meta={
                "referrer_id": referrer.id,
                "referee_id": referee.id,
                "code": ref.code_used,
            }
        )

        # ⭐⭐ FIX HERE ⭐⭐
        rp = referrer.referral_profile
        rp.total_referrals += 1
        rp.lifetime_earnings = (rp.lifetime_earnings or Decimal("0")) + reward
        rp.save(update_fields=["total_referrals", "lifetime_earnings"])

        ref.status = "qualified"
        ref.reward_amount = reward
        ref.converted_at = timezone.now()
        ref.save(update_fields=["status", "reward_amount", "converted_at"])

        return True
