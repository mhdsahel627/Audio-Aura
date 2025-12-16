from django.db import models

# Create your models here.
class Payment(models.Model):
    PAYMENT_METHODS = [
        ('razorpay', 'Razorpay'),
        ('cod', 'Cash on Delivery'),
    ]
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=255, blank=True, null=True)
    amount = models.IntegerField()
    status = models.CharField(max_length=50, default='Created')
    created_at = models.DateTimeField(auto_now_add=True)
