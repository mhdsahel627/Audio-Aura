from django.contrib import admin
from .models import Category,Brand, CategoryOffer
# Register your models here.

admin.site.register(Category)
admin.site.register(Brand)
admin.site.register(CategoryOffer)