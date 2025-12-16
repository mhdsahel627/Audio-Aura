from django.urls import path
from . import views

urlpatterns = [
    path('coupons/', views.coupon, name='coupon'),
    path('coupons/add-coupen/', views.add_coupon, name="add_coupon"),
    path('edit/<int:coupon_id>/', views.edit_coupon, name='edit_coupon'),
    path('delete/<int:coupon_id>/', views.delete_coupon, name='delete_coupon'),  # ← THIS IS IMPORTANT
    path('toggle/<int:coupon_id>/', views.toggle_coupon_status, name='toggle_coupon_status'),
    path('check-pincode/', views.check_pincode, name='check_pincode'),

]

