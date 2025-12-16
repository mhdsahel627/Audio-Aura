#payments/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('payment/',views.payment,name='payment'),
    path('payment_success/',views.payment_success,name='payment_success'),
    path('payment/razorpay/handler/', views.razorpay_payment_handler, name='razorpay_payment_handler'),
    # path('payment/razorpay/create/', views.create_razorpay_order, name='create_razorpay_order'),
    path('payment-failed/', views.payment_failed, name='payment_failed'),
    path('retry-payment/<int:order_id>/', views.retry_payment, name='retry_payment'),
    




]