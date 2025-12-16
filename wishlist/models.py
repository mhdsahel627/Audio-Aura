from django.db import models
from django.contrib.auth.models import User
from products.models import ProductVariant  # Import variant model from products app

class Wishlist(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wishlist')

    def __str__(self):
        return f"{self.user.username}'s Wishlist"

class WishlistItem(models.Model):
    wishlist = models.ForeignKey(Wishlist, on_delete=models.CASCADE, related_name='items')
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('wishlist', 'variant')  # Prevent duplicate variant items in the same wishlist

    def __str__(self):
        return f"WishlistItem: {self.variant} in {self.wishlist.user.username}'s Wishlist"
