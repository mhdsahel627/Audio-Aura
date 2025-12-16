from django.urls import path
from shop import views

urlpatterns = [
    path('shop/',views.shop,name='shop'),
    path('shop/category/<int:id>/', views.shop_category_by_id, name='shop_category_id'),
]