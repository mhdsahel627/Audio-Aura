from datetime import date
from decimal import Decimal

def get_active_offer_discount(offer_queryset):
    today = date.today()
    active_offers = offer_queryset.filter(start_date__lte=today, end_date__gte=today, is_active=True)
    if not active_offers.exists():
        return Decimal('0')
    max_discount_offer = active_offers.order_by('-discount_percent').first()
    return max_discount_offer.discount_percent


import cloudinary
import cloudinary.uploader

def upload_to_cloudinary(instance, field_name):
    image = getattr(instance, field_name)
    if not image:
        return None

    upload = cloudinary.uploader.upload(image, folder="products/")
    return upload.get("secure_url")
