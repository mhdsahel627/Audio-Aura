from django.db import models
from django.conf import settings
from django.contrib.auth.models import User


class Address(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='addresses')
    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20)
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=120)
    state = models.CharField(max_length=120)
    postcode = models.CharField(max_length=20)
    country = models.CharField(max_length=120)
    notes = models.TextField(blank=True, null=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-is_default', '-created_at',)

    def __str__(self):
        return f'{self.full_name} - {self.city}'
    
    
# user/models.py
class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    phone = models.CharField(max_length=20, blank=True,null=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    pending_email = models.EmailField(blank=True, null=True)
    pending_email_otp = models.CharField(max_length=6, blank=True , null = True)  # store hashed in prod
    pending_email_expires = models.DateTimeField(blank=True, null=True)
