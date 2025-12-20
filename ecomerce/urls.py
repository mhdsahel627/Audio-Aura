"""
URL configuration for ecomerce project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path,include
from django.conf.urls.static import static
from django.conf import settings
from django.views.static import serve
from django.urls import re_path
from django.conf.urls import handler404


handler404 = 'banner.views.custom_404'

urlpatterns = [
    path('adminn/', admin.site.urls),
    path('', include('home.urls')),
    path('accounts/', include('registration.urls')),
    path('oauth/', include('social_django.urls', namespace='social')),  # Google OAuth routes
     path('admin/', include('admin_side.urls')),
    path('categories/', include('category.urls')),
    path('products/', include('products.urls')),
    path('shop/', include('shop.urls')),
    path('cart/', include('cart.urls')),
    path('payment/', include('payments.urls')),
    path('user/', include('user.urls')),
    path('orders/', include('orders.urls')),
    path('wallet/', include('wallet.urls')),
    path('coupons/', include('coupons.urls')),
    path('wishlist/', include('wishlist.urls', namespace='wishlist')),
    path('banner/', include('banner.urls')),



    
  
    # path('reviews/', include('reviews.urls')),
    # path('offers/', include('offers.urls')),
]

# Development & Production media/static serving
if settings.DEBUG:
    # Development mode - Django serves files
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
else:
    # Production mode - Explicit serve for Nginx fallback
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
        re_path(r'^static/(?P<path>.*)$', serve, {'document_root': settings.STATIC_ROOT}),
    ]