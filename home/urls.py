from django.urls import path
from home import views


urlpatterns = [
    path('', views.HomePage, name='home'),
    path('filter-new-arrivals/', views.filter_new_arrivals, name='filter_new_arrivals'),
    path('404/', views.not_found, name='not_found'),

]