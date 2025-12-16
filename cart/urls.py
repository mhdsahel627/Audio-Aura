#cart/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # 🛒 CORE CART OPERATIONS (view/add/update/remove)
    path('', views.cart, name='cart'),
    path('add/', views.add_to_cart, name='cart_add'),
    path('update-qty/', views.cart_update_qty, name='cart_update_qty'),
    path('remove/', views.cart_remove, name='cart_remove'),  
    path('empty/', views.cart_empty, name='cart_empty'),
    
    # 🎟️ COUPON MANAGEMENT
    path('cart/apply-coupon/', views.apply_coupon, name='apply_coupon'),
    path('cart/remove-coupon/', views.remove_coupon, name='remove_coupon'),
    
    # ➡️ CHECKOUT FLOW
    path('cart/proceed/', views.cart_proceed, name='cart_proceed'),
    path('clear-checkout/', views.clear_checkout_session, name='clear_checkout_session'),
    path('checkout-summary/', views.checkout_cart_summary, name='checkout_cart_summary'),
    
    # ⚡ QUICK BUY-NOW (direct purchase)
    path('buy-now/', views.buy_now, name='buy_now'),
    path('buy-now/update-qty/', views.buy_now_update_qty, name='buy_now_update_qty'),
    
    # 🚀 QUICK ADD 
    path('cart/quick-add-with-coupon/', views.quick_add_with_coupon, name='quick_add_with_coupon'),
]
