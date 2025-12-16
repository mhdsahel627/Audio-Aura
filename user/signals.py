# user/signals.py
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Profile

@receiver(post_save, sender=settings.AUTH_USER_MODEL, dispatch_uid="user_profile_autocreate_v1")
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)
