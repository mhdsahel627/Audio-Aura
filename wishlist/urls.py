from django.urls import path
from . import views
app_name = 'wishlist'

urlpatterns = [
    path('', views.wishlist_list, name='list'),  # List view named 'list'
    path('add/<int:variant_id>/', views.add_to_wishlist, name='add'),
    path('remove/<int:item_id>/', views.remove_from_wishlist, name='remove'),
    path('empty/', views.empty_wishlist, name='empty'),
    path('add_item_to_cart/<int:item_id>/', views.add_wishlist_item_to_cart, name='add_item_to_cart'),
    path('toggle/<int:variant_id>/', views.toggle_wishlist, name='toggle'),
    path('check/<int:variant_id>/', views.check_wishlist, name='check'),


]
