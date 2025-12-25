from django.urls import path
from .import views

urlpatterns = [
    path('profile/',views.profile,name='profile'),
    path('profile/update/', views.profile_update, name='profile_update'),  
    path('profile/email/change/', views.start_email_change, name='start_email_change'),
    path('profile/email/verify/', views.verify_email_change, name='verify_email_change'),
    path('profile/email/otp/', views.email_change_otp_page, name='email_change_otp_page'),
    path('profile/email/resend/', views.resend_email_change_otp, name='resend_email_change_otp'),


    path('addresses/', views.address_manage, name='address'),
    path('addresses/create/', views.address_create, name='address_create'),
    path('addresses/<int:pk>/update/', views.address_update, name='address_update'),
    path('addresses/<int:pk>/delete/', views.address_delete, name='address_delete'),
    path('addresses/<int:pk>/make-default/', views.address_make_default, name='address_make_default'),
    
    path('passwordchange/', views.password_change, name='password_change'),
    path('forgotpassword/', views.forgot_password, name='password_forgot'),
    path('resetpassword/', views.password_reset, name='password_reset'),
    
    
    path('address/get/<int:pk>/', views.address_get_data, name='address_get_data'),

    



]
