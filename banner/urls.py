# app/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # List
    path('', views.banner_list, name='banner_list'),
    
    # Banner CRUD
    path('banner/add/', views.banner_add, name='banner_add'),
    path('banner/<int:pk>/edit/', views.banner_edit, name='banner_edit'),
    path('banner/<int:pk>/delete/', views.banner_delete, name='banner_delete'),
    path('banner/<int:pk>/toggle/', views.banner_toggle, name='banner_toggle'),
    
    # Deal CRUD
    path('deal/add/', views.deal_add, name='deal_add'),
    path('deal/<int:pk>/edit/', views.deal_edit, name='deal_edit'),
    path('deal/<int:pk>/delete/', views.deal_delete, name='deal_delete'),
    path('deal/<int:pk>/toggle/', views.deal_toggle, name='deal_toggle'),
    path('deal/image/<int:pk>/delete/', views.deal_image_delete, name='deal_image_delete'),
    
    # Featured Product CRUD
    path('featured/add/', views.featured_add, name='featured_add'),
    path('featured/<int:pk>/edit/', views.featured_edit, name='featured_edit'),
    path('featured/<int:pk>/delete/', views.featured_delete, name='featured_delete'),
    path('featured/<int:pk>/toggle/', views.featured_toggle, name='featured_toggle'),
    
    path('about/', views.about, name='about'),
    path('contact/',views.contact,name='contact')
]
