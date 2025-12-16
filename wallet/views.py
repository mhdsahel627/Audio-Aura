# wallet/views.py
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
from django.core.paginator import Paginator
from django.db.models import Sum, Q
from django.conf import settings
from decimal import Decimal
from datetime import datetime, timedelta
import csv
import razorpay

from .models import WalletAccount, WalletTransaction, ReferralProfile, Referral
from .services import credit
from .utils import build_ref_link

# Initialize Razorpay client
client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


@login_required
def wallet_view(request):
    acct, _ = WalletAccount.objects.get_or_create(user=request.user)
    qs = WalletTransaction.objects.filter(account=acct)
    page_obj = Paginator(qs, 10).get_page(request.GET.get("page", 1))
    return render(request, "user/wallet.html", {"wallet": acct, "page_obj": page_obj})


@login_required
@require_POST
def create_wallet_order(request):
    try:
        amount = Decimal(request.POST.get("amount", "0"))
        if amount < 10:
            return HttpResponseBadRequest("Minimum top-up is ₹10")
        
        paise = int(amount * 100)
        rzp_order = client.order.create({
            "amount": paise,
            "currency": "INR",
            "payment_capture": 1,
            "notes": {"purpose": "wallet_topup", "user_id": request.user.id}
        })
        
        data = {
            "order_id": rzp_order["id"],
            "amount": paise,
            "key": settings.RAZORPAY_KEY_ID,
            "name": "Audio Aura",
            "prefill": {
                "name": request.user.get_full_name() or request.user.username,
                "email": request.user.email or "",
                "contact": getattr(getattr(request.user, "profile", None), "phone", "") or ""
            },
        }
        return JsonResponse(data)
    except Exception as e:
        return HttpResponseBadRequest(str(e))


@login_required
@require_POST
@csrf_exempt
def verify_wallet_payment(request):
    payment_id = request.POST.get("razorpay_payment_id")
    order_id = request.POST.get("razorpay_order_id")
    signature = request.POST.get("razorpay_signature")
    amount_paise = int(request.POST.get("amount_paise", "0"))

    if not all([payment_id, order_id, signature]):
        return HttpResponseBadRequest("Missing parameters")

    # Verify signature
    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature
        })
    except razorpay.errors.SignatureVerificationError:
        return HttpResponseBadRequest("Signature verification failed")

    # Credit wallet
    amount_rupees = Decimal(amount_paise) / 100
    credit(
        user=request.user,
        amount=amount_rupees,
        description="Wallet top-up",
        reference=payment_id,
        meta={"order_id": order_id}
    )
    return JsonResponse({"status": "ok"})


@login_required
def refer(request):
    rp, _ = ReferralProfile.objects.get_or_create(user=request.user)
    ctx = {
        "referral_code": rp.code,
        "referral_url": build_ref_link(request, rp.code),
        "stats": {
            "qualified": Referral.objects.filter(referrer=request.user, status="qualified").count(),
            "pending": Referral.objects.filter(referrer=request.user, status="signed_up").count(),
            "earnings": rp.lifetime_earnings,
        }
    }
    return render(request, "user/refer_code.html", ctx)


@staff_member_required
def wallet_transactions(request):
    # Get filter parameters
    transaction_type = request.GET.get('type', '')
    status = request.GET.get('status', '')
    from_date = request.GET.get('from_date', '')
    to_date = request.GET.get('to_date', '')
    search_query = request.GET.get('search', '')
    
    # Base queryset
    transactions = WalletTransaction.objects.select_related('account__user').all()
    
    # Apply filters
    if transaction_type:
        transactions = transactions.filter(kind=transaction_type.upper())
    
    if status:
        transactions = transactions.filter(status=status)
    
    if from_date:
        transactions = transactions.filter(created_at__gte=from_date)
    
    if to_date:
        try:
            to_date_obj = datetime.strptime(to_date, '%Y-%m-%d') + timedelta(days=1)
            transactions = transactions.filter(created_at__lt=to_date_obj)
        except ValueError:
            pass
    
    if search_query:
        transactions = transactions.filter(
            Q(transaction_id__icontains=search_query) |
            Q(account__user__username__icontains=search_query) |
            Q(account__user__email__icontains=search_query) |
            Q(reference__icontains=search_query)
        )
    
    # Calculate statistics
    total_credits = WalletTransaction.objects.filter(
        kind='CREDIT', 
        status='completed'
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    total_debits = WalletTransaction.objects.filter(
        kind='DEBIT', 
        status='completed'
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    pending_amount = WalletTransaction.objects.filter(
        status='pending'
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    total_balance = WalletAccount.objects.aggregate(total=Sum('balance'))['total'] or 0
    
    # Calculate month-over-month changes
    last_month_start = datetime.now() - timedelta(days=30)
    
    last_month_credits = WalletTransaction.objects.filter(
        kind='CREDIT',
        status='completed',
        created_at__gte=last_month_start
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    prev_month_start = last_month_start - timedelta(days=30)
    prev_month_credits = WalletTransaction.objects.filter(
        kind='CREDIT',
        status='completed',
        created_at__gte=prev_month_start,
        created_at__lt=last_month_start
    ).aggregate(total=Sum('amount'))['total'] or 1
    
    credit_change = ((last_month_credits - prev_month_credits) / prev_month_credits * 100) if prev_month_credits > 0 else 0
    
    # Calculate debit change
    last_month_debits = WalletTransaction.objects.filter(
        kind='DEBIT',
        status='completed',
        created_at__gte=last_month_start
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    prev_month_debits = WalletTransaction.objects.filter(
        kind='DEBIT',
        status='completed',
        created_at__gte=prev_month_start,
        created_at__lt=last_month_start
    ).aggregate(total=Sum('amount'))['total'] or 1
    
    debit_change = ((last_month_debits - prev_month_debits) / prev_month_debits * 100) if prev_month_debits > 0 else 0
    
    # Pagination
    paginator = Paginator(transactions, 10)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    context = {
        'transactions': page_obj,
        'total_credits': total_credits,
        'total_debits': total_debits,
        'pending_amount': pending_amount,
        'total_balance': total_balance,
        'credit_change': round(credit_change, 1),
        'debit_change': round(debit_change, 1),
        'filter_type': transaction_type,
        'filter_status': status,
        'filter_from_date': from_date,
        'filter_to_date': to_date,
        'search_query': search_query,
        'paginator': paginator,
    }
    
    return render(request, 'admin/wallet_transactions.html', context)


@staff_member_required
def export_wallet_transactions(request):
    """Export wallet transactions to CSV"""
    transaction_type = request.GET.get('type', '')
    status = request.GET.get('status', '')
    from_date = request.GET.get('from_date', '')
    to_date = request.GET.get('to_date', '')
    
    transactions = WalletTransaction.objects.select_related('account__user').all()
    
    # Apply filters
    if transaction_type:
        transactions = transactions.filter(kind=transaction_type.upper())
    if status:
        transactions = transactions.filter(status=status)
    if from_date:
        transactions = transactions.filter(created_at__gte=from_date)
    if to_date:
        try:
            to_date_obj = datetime.strptime(to_date, '%Y-%m-%d') + timedelta(days=1)
            transactions = transactions.filter(created_at__lt=to_date_obj)
        except ValueError:
            pass
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="wallet_transactions.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Transaction ID', 'User', 'Email', 'Type', 'Amount', 'Balance After', 'Status', 'Reference', 'Description', 'Date & Time'])
    
    for txn in transactions:
        writer.writerow([
            txn.transaction_id or f"TXN{txn.id}",
            txn.account.user.get_full_name() or txn.account.user.username,
            txn.account.user.email,
            txn.kind.title(),
            f"₹{txn.amount}",
            f"₹{txn.balance_after}",
            txn.status.title(),
            txn.reference or '-',
            txn.description or '-',
            txn.created_at.strftime('%b %d, %Y %I:%M %p')
        ])
    
    return response
