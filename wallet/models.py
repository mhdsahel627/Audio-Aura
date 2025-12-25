# wallet/models.py
from django.conf import settings
from django.db import models
from django.utils.crypto import get_random_string
from django.db.models.signals import post_save
from django.dispatch import receiver

User = settings.AUTH_USER_MODEL


class WalletAccount(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="wallet")
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self): 
        return f"Wallet({self.user.username}) - ₹{self.balance}"


class WalletTransaction(models.Model):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
    KIND_CHOICES = [(CREDIT, "Credit"), (DEBIT, "Debit")]
    
    STATUS_CHOICES = [
        ('completed', 'Completed'),
        ('pending', 'Pending'),
        ('failed', 'Failed'),
    ]

    account = models.ForeignKey(WalletAccount, on_delete=models.CASCADE, related_name="transactions")
    transaction_id = models.CharField(max_length=50, unique=True, blank=True, editable=False) 
    kind = models.CharField(max_length=6, choices=KIND_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='completed')
    description = models.CharField(max_length=128, blank=True)
    reference = models.CharField(max_length=64, blank=True)
    
    # ✅ ADD THIS - Critical for preventing duplicate refunds
    idem_key = models.CharField(
        max_length=255, 
        blank=True, 
        null=True, 
        db_index=True,
        help_text="Idempotency key to prevent duplicate transactions"
    )
    
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['kind', 'status']),
            models.Index(fields=['account', 'idem_key']),  # ✅ ADD THIS
        ]
        # ✅ OPTIONAL: Prevent duplicate idem_keys per account
        constraints = [
            models.UniqueConstraint(
                fields=['account', 'idem_key'],
                condition=models.Q(idem_key__isnull=False),
                name='unique_account_idem_key'
            )
        ]

    def save(self, *args, **kwargs):
        if not self.transaction_id:
            import uuid
            self.transaction_id = f"TXN{uuid.uuid4().hex[:8].upper()}"
        
        if not self.balance_after and self.account_id:
            self.balance_after = self.account.balance
        
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.transaction_id} - {self.account.user.username} - ₹{self.amount}"


@receiver(post_save, sender=User)
def ensure_wallet(sender, instance, created, **kwargs):
    if created:
        WalletAccount.objects.get_or_create(user=instance)


def gen_code():
    return get_random_string(9, allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


class ReferralProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="referral_profile")
    code = models.CharField(max_length=16, unique=True, db_index=True, blank=True)
    total_referrals = models.PositiveIntegerField(default=0)
    lifetime_earnings = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def save(self, *args, **kwargs):
        if not self.code:
            c = gen_code()
            while ReferralProfile.objects.filter(code=c).exists():
                c = gen_code()
            self.code = c
        return super().save(*args, **kwargs)


class Referral(models.Model):
    referrer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="referrals_made")
    referee = models.OneToOneField(User, on_delete=models.CASCADE, related_name="referral_from")
    code_used = models.CharField(max_length=16, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    converted_at = models.DateTimeField(null=True, blank=True)
    reward_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(
        max_length=16,
        choices=[("signed_up","Signed up"),("qualified","Qualified"),("rejected","Rejected")],
        default="signed_up",
        db_index=True
    )
    notes = models.TextField(blank=True)


class ReferralConfig(models.Model):
    active = models.BooleanField(default=True)
    signup_reward = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    purchase_reward = models.DecimalField(max_digits=10, decimal_places=2, default=100)
    min_order_amount = models.DecimalField(max_digits=10, decimal_places=2, default=500)
    monthly_cap = models.PositiveIntegerField(default=100)

    def __str__(self): 
        return "Referral Config"
