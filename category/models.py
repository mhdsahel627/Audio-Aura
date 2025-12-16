from django.db import models

class Category(models.Model):
    name = models.CharField(max_length=255,unique=True)
    description = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to='categories/')
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)  # for list/unlist toggle

    def __str__(self):
        return self.name

class Brand(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name
    
class CategoryOffer(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='offers')
    title = models.CharField(max_length=100)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    discount_rs = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    is_extra = models.BooleanField(default=True)
    # Optionally:
    # active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.category.name} - {self.title}"

