from django.urls import path
from category import views

urlpatterns = [
    
    path('catogery/', views.catogery, name='catogery'),
    path("brands/add-ajax/", views.add_brand_ajax, name="add_brand_ajax"),
    path('add_catogery/', views.add_category, name='add_catogery'),
    path('category/toggle/<int:id>/', views.toggle_category, name='toggle_category'),
    path('categories/<int:pk>/edit/', views.category_edit, name='category_edit'),
    
    path('offers/add/', views.add_category_offer, name='add_category_offer'),
    path('offers/edit/<int:offer_id>/', views.edit_category_offer, name='edit_category_offer'),
    path('offers/delete/<int:offer_id>/', views.delete_category_offer, name='delete_category_offer'),
        

]