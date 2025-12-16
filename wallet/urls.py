from django.urls import path
from . import views

urlpatterns = [
    path("wallet/",views.wallet_view, name="wallet"),
    path('refer/', views.refer, name='refer_code'),
    path("wallet/create-order/", views.create_wallet_order, name="wallet_create_order"),
    path("wallet/verify/", views.verify_wallet_payment, name="wallet_verify"),
    path('wallettransactions/',views.wallet_transactions,name='wallet_transaction'),
    path('transactionexport/',views.export_wallet_transactions,name='walletexport')
]