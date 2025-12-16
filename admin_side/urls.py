from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.admin_login, name='admin_login'),
    path('dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('customers/', views.user_management, name='customers'),
    path('users/block-unblock/<int:user_id>/', views.block_unblock_user, name='block_unblock_user'),
    path('logout/', views.admin_logout, name='admin_logout'),
    
    path('sales-report/', views.sales_report, name='sales_report'),
    path("export/excel/", views.export_sales_excel, name="export_excel"),
    path('adminside/export-sales-pdf/', views.export_sales_pdf, name='export_sales_pdf'),




    
]

