# app/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from django.db.models import Q
from .models import Banner, DealOfMonth, DealImage, FeaturedProduct
from .forms import BannerForm, DealForm, DealImageForm, FeaturedProductForm


@never_cache
def banner_list(request):
    """Combined list view for all banner management"""
    q = request.GET.get("q", "")
    status = request.GET.get("status", "all")
    sort = request.GET.get("sort", "newest")

    # Banners
    banners_qs = Banner.objects.all()
    if q:
        banners_qs = banners_qs.filter(Q(title__icontains=q) | Q(description__icontains=q))
    if status == "active":
        banners_qs = banners_qs.filter(is_active=True)
    elif status == "inactive":
        banners_qs = banners_qs.filter(is_active=False)

    if sort == "priority":
        banners = banners_qs.order_by('priority', '-created_at')
    else:
        banners = banners_qs.order_by('-created_at')

    # Deals with images
    deals = DealOfMonth.objects.prefetch_related('images').all()
    if q:
        deals = deals.filter(Q(title__icontains=q) | Q(description__icontains=q))
    if status == "active":
        deals = deals.filter(is_active=True)
    elif status == "inactive":
        deals = deals.filter(is_active=False)

    # Featured Products
    featured = FeaturedProduct.objects.all()
    if q:
        featured = featured.filter(Q(title__icontains=q) | Q(description__icontains=q))
    if status == "active":
        featured = featured.filter(is_active=True)
    elif status == "inactive":
        featured = featured.filter(is_active=False)

    context = {
        "q": q, "status": status, "sort": sort,
        "banners": banners,
        "deals": deals,
        "featured_products": featured,
    }
    return render(request, "admin/banner.html", context)


# BANNER CRUD
def banner_add(request):
    if request.method == "POST":
        form = BannerForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "✅ Banner created successfully!")
            return redirect("banner_list")
        else:
            messages.error(request, "❌ Please correct the errors below.")
    else:
        form = BannerForm()
    return render(request, "admin/banner_form.html", {"form": form, "title": "Add Banner"})


def banner_edit(request, pk):
    banner = get_object_or_404(Banner, pk=pk)
    if request.method == "POST":
        form = BannerForm(request.POST, request.FILES, instance=banner)
        if form.is_valid():
            form.save()
            messages.success(request, "✅ Banner updated successfully!")
            return redirect("banner_list")
    else:
        form = BannerForm(instance=banner)
    return render(request, "admin/banner_form.html", {"form": form, "title": "Edit Banner", "object": banner})


@require_POST
def banner_delete(request, pk):
    banner = get_object_or_404(Banner, pk=pk)
    banner.delete()
    messages.info(request, "🗑️ Banner deleted.")
    return redirect("banner_list")


def banner_toggle(request, pk):
    banner = get_object_or_404(Banner, pk=pk)
    banner.is_active = not banner.is_active
    banner.save(update_fields=['is_active'])
    messages.success(request, f"Banner {'activated' if banner.is_active else 'deactivated'}.")
    return redirect("banner_list")


# DEAL CRUD
def deal_add(request):
    if request.method == "POST":
        form = DealForm(request.POST)
        images = request.FILES.getlist('deal_images')
        
        if form.is_valid():
            if len(images) > 6:
                messages.error(request, "❌ Maximum 6 images allowed per deal.")
                return render(request, "admin/deal_form.html", {"form": form, "title": "Add Deal"})
            
            deal = form.save()
            
            # Save images
            for idx, img in enumerate(images):
                DealImage.objects.create(deal=deal, image=img, order=idx+1)
            
            messages.success(request, "✅ Deal created successfully!")
            return redirect("banner_list")
    else:
        form = DealForm()
    return render(request, "admin/deal_form.html", {"form": form, "title": "Add Deal"})


def deal_edit(request, pk):
    deal = get_object_or_404(DealOfMonth, pk=pk)
    if request.method == "POST":
        form = DealForm(request.POST, instance=deal)
        images = request.FILES.getlist('deal_images')
        
        if form.is_valid():
            existing_count = deal.images.count()
            if existing_count + len(images) > 6:
                messages.error(request, f"❌ Maximum 6 images allowed. You have {existing_count} already.")
                return render(request, "admin/deal_form.html", {
                    "form": form, "title": "Edit Deal", "object": deal
                })
            
            form.save()
            
            # Add new images
            for idx, img in enumerate(images):
                DealImage.objects.create(deal=deal, image=img, order=existing_count + idx + 1)
            
            messages.success(request, "✅ Deal updated successfully!")
            return redirect("banner_list")
    else:
        form = DealForm(instance=deal)
    return render(request, "admin/deal_form.html", {
        "form": form, "title": "Edit Deal", "object": deal
    })


@require_POST
def deal_delete(request, pk):
    deal = get_object_or_404(DealOfMonth, pk=pk)
    deal.delete()
    messages.info(request, "🗑️ Deal deleted.")
    return redirect("banner_list")


def deal_toggle(request, pk):
    deal = get_object_or_404(DealOfMonth, pk=pk)
    deal.is_active = not deal.is_active
    deal.save(update_fields=['is_active'])
    messages.success(request, f"Deal {'activated' if deal.is_active else 'deactivated'}.")
    return redirect("banner_list")


@require_POST
def deal_image_delete(request, pk):
    """Delete individual deal image"""
    img = get_object_or_404(DealImage, pk=pk)
    deal_pk = img.deal.pk
    img.delete()
    messages.info(request, "Image removed.")
    return redirect("deal_edit", pk=deal_pk)


# FEATURED PRODUCT CRUD
def featured_add(request):
    if request.method == "POST":
        form = FeaturedProductForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "✅ Featured product added!")
            return redirect("banner_list")
    else:
        form = FeaturedProductForm()
    return render(request, "admin/featured_form.html", {"form": form, "title": "Add Featured Product"})


def featured_edit(request, pk):
    product = get_object_or_404(FeaturedProduct, pk=pk)
    if request.method == "POST":
        form = FeaturedProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, "✅ Featured product updated!")
            return redirect("banner_list")
    else:
        form = FeaturedProductForm(instance=product)
    return render(request, "admin/featured_form.html", {
        "form": form, "title": "Edit Featured Product", "object": product
    })


@require_POST
def featured_delete(request, pk):
    product = get_object_or_404(FeaturedProduct, pk=pk)
    product.delete()
    messages.info(request, "🗑️ Featured product deleted.")
    return redirect("banner_list")


def featured_toggle(request, pk):
    product = get_object_or_404(FeaturedProduct, pk=pk)
    product.is_active = not product.is_active
    product.save(update_fields=['is_active'])
    messages.success(request, f"Product {'activated' if product.is_active else 'deactivated'}.")
    return redirect("banner_list")

def about(request):
    return render(request, 'user/about.html')

def contact(request):
    return render(request,'user/contact.html')


def custom_404(request, exception):
    return render(request, '404.html', status=404)
    