# orders/apps.py

from django.apps import AppConfig


class OrdersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'orders'
    
    # Signal-based refunds disabled to prevent double refunds
    # Refunds now handled manually in views using refund_service.py
