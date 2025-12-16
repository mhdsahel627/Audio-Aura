# orders/urls.py
from django.urls import path
from . import views

urlpatterns = [
    #ordering
    path('myorders/', views.orderss, name='orders'),
    path("orders/<str:order_number>/items/<int:item_id>/", views.order_item_detail, name="order_item_detail"),
    path("orders/<str:order_number>/items/<int:item_id>/track/",views.track_item,name="track_item"),
    path('address_check/', views.address_check, name='address_check'),
    path('select_address/', views.select_address, name='select_address'),
    
    
    path('checkout/', views.checkout, name='checkout'),
    path('checkout/update-qty/', views.checkout_update_qty, name='checkout_update_qty'),
    path('cancel-checkout/', views.cancel_checkout, name='cancel_checkout'),

    
    # Admin side
    path("admin/orders/", views.admin_order_list, name="order_list"),
    path("admin/orders/<int:pk>/", views.admin_order_detail, name="admin_order_detail"),
    
    # user-facing
    path("orders/<str:order_number>/item/<int:item_id>/request-cancel/", views.request_cancel_item, name="request_cancel_item"),
    path("orders/<str:order_number>/item/<int:item_id>/request-return/", views.request_return_item, name="request_return_item"),

    # staff-facing
    path("admin/orders/action-requests/", views.admin_action_requests, name="admin_action_requests"),
    path("admin/orders/action-requests/<int:pk>/approve/", views.approve_action_request, name="approve_action_request"),
    path("admin/orders/action-requests/<int:pk>/reject/", views.reject_action_request, name="reject_action_request"),

    # invoices
    path("admin/orders/<int:pk>/invoice/", views.admin_download_invoice, name="admin_download_invoice"),
    path("orders/<str:order_number>/invoice/", views.user_download_invoice, name="user_download_invoice"),
    path("orders/<str:order_number>/item/<int:item_id>/invoice/", views.user_download_item_invoice, name="user_download_item_invoice"),
    


]

   

