from django.urls import path
from registration import views

urlpatterns = [
    path('signup/', views.SignUp, name='signup'),
    path('signin/', views.SignIn, name='signin'),
    path('logout/', views.SignOut, name='logout'),
    
    # OTP verification for signup
    path('verify-otp/', views.VerifyOTP, name='verify_otp'),
    path('resend-otp/', views.ResendOTP, name='resend_otp'),

    # -------------------------------
    # Forgot Password flow
    # -------------------------------
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('verify-reset-otp/', views.verify_reset_otp, name='verify_reset_otp'),
    path('resend-forget-otp/', views.resend_reset_otp, name='resend_reset_otp'),
    path('reset-password/', views.reset_password, name='reset_password'),
    

]

