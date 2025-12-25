# wallet/services.py

from django.db import transaction
from decimal import Decimal
from .models import WalletAccount, WalletTransaction
from django.utils import timezone


def credit(user, amount, description="", reference="", meta=None, idem_key=None):
    """
    Credit user wallet with proper idempotency support
    
    Args:
        user: User object
        amount: Amount to credit
        description: Transaction description
        reference: Reference ID (e.g., payment_id)
        meta: Additional metadata (dict)
        idem_key: Idempotency key to prevent duplicates
    
    Returns:
        WalletTransaction object or None if duplicate
    """
    meta = meta or {}
    
    with transaction.atomic():
        # Get or create wallet account
        acct = WalletAccount.objects.select_for_update().get_or_create(user=user)[0]
        
        # ✅ FIXED: Check idempotency using idem_key field
        if idem_key:
            existing = WalletTransaction.objects.filter(
                account=acct,
                idem_key=idem_key  # ✅ Check correct field
            ).first()
            
            if existing:
                print(f"⚠️ DUPLICATE TRANSACTION BLOCKED!")
                print(f"   User: {user.username}")
                print(f"   Idem Key: {idem_key}")
                print(f"   Existing Transaction: {existing.id}")
                print(f"   Created: {existing.created_at}")
                return None  # Don't raise error, just return None
        
        # Update balance
        acct.balance = (acct.balance or Decimal("0")) + Decimal(amount)
        balance_after = acct.balance
        acct.save(update_fields=["balance"])
        
        # Create transaction
        txn = WalletTransaction.objects.create(
            account=acct,
            kind=WalletTransaction.CREDIT,
            amount=Decimal(amount),
            balance_after=balance_after,
            description=description,
            reference=reference,  # ✅ Keep reference separate
            idem_key=idem_key,    # ✅ Store idem_key separately
            meta=meta,
        )
        
        print(f"✅ WALLET CREDITED")
        print(f"   User: {user.username}")
        print(f"   Amount: ₹{amount}")
        print(f"   Balance: ₹{balance_after}")
        print(f"   Transaction: {txn.id}")
        print(f"   Idem Key: {idem_key}")
        
        return txn


def debit(user, amount, description="", reference="", meta=None):
    """Debit user wallet"""
    meta = meta or {}
    
    with transaction.atomic():
        acct = WalletAccount.objects.select_for_update().get(user=user)
        
        if acct.balance < Decimal(amount):
            raise ValueError("Insufficient wallet balance")
        
        acct.balance = acct.balance - Decimal(amount)
        balance_after = acct.balance
        acct.save(update_fields=["balance"])
        
        return WalletTransaction.objects.create(
            account=acct,
            kind=WalletTransaction.DEBIT,
            amount=amount,
            balance_after=balance_after,
            description=description,
            reference=reference,
            meta=meta
        )


def qualify_signup_referral_and_credit(referee):
    """Qualify referral and credit reward"""
    print("QUALIFY FUNCTION TRIGGERED", referee.id)

    from wallet.models import Referral, ReferralConfig
    
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
        balance_after = wallet.balance
        wallet.save(update_fields=["balance"])

        # ✅ Use idempotency key
        WalletTransaction.objects.create(
            account=wallet,
            kind=WalletTransaction.CREDIT,
            amount=reward,
            balance_after=balance_after,
            description="Referral Signup Reward",
            reference=f"referral_signup_{referee.id}",
            idem_key=f"referral:signup:{referee.id}",  # ✅ Add idem_key
            meta={
                "referrer_id": referrer.id,
                "referee_id": referee.id,
                "code": ref.code_used,
            }
        )

        # Update referral profile
        rp = referrer.referral_profile
        rp.total_referrals += 1
        rp.lifetime_earnings = (rp.lifetime_earnings or Decimal("0")) + reward
        rp.save(update_fields=["total_referrals", "lifetime_earnings"])

        ref.status = "qualified"
        ref.reward_amount = reward
        ref.converted_at = timezone.now()
        ref.save(update_fields=["status", "reward_amount", "converted_at"])

        return True
