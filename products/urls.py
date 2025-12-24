# products/urls.py
from django.urls import path
from . import views
from .views import add_offer 

urlpatterns = [
    
    # """""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
    #                                                                 Product
    # """""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
    
    path("product_add/", views.add_product, name="product_add"),
    path("product_list/", views.product_list, name="product_list"),
    path("product_edit/<int:product_id>/", views.product_edit, name="product_edit"),
    path('admin/product/toggle/<int:id>/', views.toggle_product, name='toggle_product'),
    path("<int:id>/", views.product_detail, name="product_detail"),
    path("admin/add-brand-ajax/", views.add_brand_ajax, name="add_brand_ajax"),
    path("adminn/products/ajax-upload-image/", views.ajax_upload_image, name="product_ajax_upload_image"),
    path('upload-temp-image/', views.upload_temp_image, name='upload_temp_image'),

    
    # """""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""Variant"""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
    # """""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
    
    path('products/products/<int:product_id>/variants/add/', views.variant_add, name='variant_add'),
    path('products/products/<int:product_id>/variants/<int:variant_id>/edit/', views.variant_edit, name="variant_edit"),
    path('check-stock/<int:variant_id>/', views.check_stock, name='check_stock'),
    path("variant-images/<int:variant_id>/", views.variant_images, name="variant_images"),
    path("products/<int:product_id>/variants/", views.view_variants, name="view_variants"),
    
    
    # """""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""offer"""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
    # """""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""""
    
    path('offers/add/', add_offer, name='add_offer'),
    path('offers/edit/<int:offer_id>/', views.edit_offer, name='edit_offer'),
    path('offers/delete/<int:offer_id>/', views.delete_offer, name='delete_offer'),
    path('check-pincode/', views.check_pincode_delivery, name='check_pincode_delivery'),
    
   
    

]
