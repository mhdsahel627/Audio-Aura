from django.shortcuts import get_object_or_404, render
from django.db.models import Q, F
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator
from django.urls import reverse
from products.models import Product
from category.models import Category, Brand  # adjust import if Brand lives elsewhere
from django.views.decorators.cache import never_cache
from django.utils import timezone
from decimal import Decimal


@never_cache
def shop(request):
    # Query params
    q          = (request.GET.get('q') or '').strip()
    cat_ids    = request.GET.getlist('category')           # multiple category ids
    brand_ids  = request.GET.getlist('brand')              # multiple brand ids
    color_terms = [t.strip() for t in request.GET.getlist('color') if t.strip()]  # multiple color tokens (e.g., black, blue)
    price_min  = request.GET.get('min')
    price_max  = request.GET.get('max')
    available  = request.GET.get('available')              # '1' for in stock
    sort_key   = request.GET.get('sort') or 'popularity'   # default

    # Base queryset
    products = (
        Product.objects
        .filter(category__is_active=True, is_listed=True)
        .select_related('brand', 'category')
        .prefetch_related('images')
    )

    # 1) facet filters (category, brand)
    if cat_ids:
        products = products.filter(category_id__in=cat_ids)
    if brand_ids:
        products = products.filter(brand_id__in=brand_ids)

    # 2) text search
    if q:
        search_q = Q(name__icontains=q) | Q(short_description__icontains=q) | Q(long_description__icontains=q)
        if not brand_ids:
            search_q |= Q(brand__name__icontains=q)
        if not cat_ids:
            search_q |= Q(category__name__icontains=q)
        products = products.filter(search_q)

    # Color filter: match any provided color token against variant color names (icontains)
    # Adjust relation path if your models differ, e.g., variants__color_name or attributes__name, etc.
    if color_terms:
        cq = Q()
        for term in color_terms:
            cq |= Q(variants__color__name__icontains=term)
        products = products.filter(cq).distinct()

    # Price filter (effective price: discount_price if set else base_price)
    products = products.annotate(price_eff=Coalesce('discount_price', 'base_price'))

    if price_min:
        try:
            products = products.filter(price_eff__gte=float(price_min))
        except (ValueError, TypeError):
            pass
    if price_max:
        try:
            products = products.filter(price_eff__lte=float(price_max))
        except (ValueError, TypeError):
            pass

    # Availability
    if available == '1':
        products = products.filter(stock_quantity__gt=0)

    # Sorting
    sort_map = {
        'popularity': '-id',         # replace with real popularity metric if available
        'newest': '-id',
        'price_asc': 'price_eff',
        'price_desc': '-price_eff',
        'az': 'name',
        'za': '-name',
    }
    products = products.order_by(sort_map.get(sort_key, '-id'))

    # Facets
    categories = Category.objects.filter(is_active=True).order_by('name')
    brands     = Brand.objects.all().order_by('name')
    products_list = []
    for product in products:
        product.final_price = product.get_final_price()
        product.discount_percent = product.get_discount_percent()
        product.extra_off = product.get_extra_off()
       

        products_list.append(product)

    # Pagination (15 per page)
    paginator = Paginator(products, 15)
    page_num  = request.GET.get('page')
    page_obj  = paginator.get_page(page_num)

    # Dynamic page title logic
    dynamic_title = "All Products"
    active_cats = Category.objects.filter(id__in=cat_ids) if cat_ids else Category.objects.none()
    active_brands = Brand.objects.filter(id__in=brand_ids) if brand_ids else Brand.objects.none()

    if q:
        dynamic_title = f"Results for “{q}”"
    elif active_cats.exists() and active_brands.exists():
        dynamic_title = f"{active_brands.first().name} in {active_cats.first().name}"
    elif active_cats.exists():
        dynamic_title = active_cats.first().name
    elif active_brands.exists():
        dynamic_title = active_brands.first().name

    ctx = {
        "products": page_obj,
        "page_obj": page_obj,
        "categories": categories,
        "brands": brands,
        "applied": {
            "q": q,
            "category": cat_ids,
            "brand": brand_ids,
            "color": color_terms,   # persist applied colors for template checks
            "min": price_min,
            "max": price_max,
            "available": available,
            "sort": sort_key,
        },
        "crumbs": [("Home", "> "), ("Shop", request.path)],
        "page_title": dynamic_title,
    }
    for product in products_list:
        print(product.name, product.extra_off)
    return render(request, "user/shop.html", ctx)

def shop_category_by_id(request, id):
    category = get_object_or_404(Category, id=id, is_active=True)
    products = Product.objects.filter(category=category, is_listed=True).select_related('brand','category')
    return render(request, 'user/shop.html', {
        'products': products,
        'categories': Category.objects.filter(is_active=True),
        'brands': Brand.objects.all(),
        'applied': {'category': [str(id)], 'q': '', 'brand': [], 'min': None, 'max': None, 'available': None, 'sort': 'popularity'},
        'crumbs': [("Home", reverse("home")), ("Shop", reverse("shop")), (category.name, None)],
        'page_title': category.name,
    })
    
def get_final_discounted_price(product):
    today = timezone.now().date()
    base_offer = product.offers.filter(
        start_date__lte=today, end_date__gte=today, is_extra=False
    ).last()
    if base_offer:
        if base_offer.discount_percent:
            base_price = product.base_price * (Decimal(str(base_offer.discount_percent)) / Decimal('100'))
            base_price = product.base_price - base_price
        elif base_offer.discount_rs:
            base_price = product.base_price - Decimal(str(base_offer.discount_rs))
        else:
            base_price = product.base_price
    else:
        base_price = product.discount_price if product.discount_price else product.base_price

    extra_offer = product.offers.filter(
        start_date__lte=today, end_date__gte=today, is_extra=True
    ).last()
    if extra_offer:
        if extra_offer.discount_percent:
            extra_amount = base_price * (Decimal(str(extra_offer.discount_percent)) / Decimal('100'))
            final_price = base_price - extra_amount
        elif extra_offer.discount_rs:
            final_price = base_price - Decimal(str(extra_offer.discount_rs))
        else:
            final_price = base_price
    else:
        final_price = base_price

    return max(int(round(float(final_price))), 0)


def get_discount_percentage(product):
    mrp = product.base_price
    sale = get_final_discounted_price(product)
    try:
        percent = round((mrp - sale) / mrp * 100)
        return max(percent, 0)
    except ZeroDivisionError:
        return 0

def get_extra_offer_amount(product):
    from decimal import Decimal
    today = timezone.now().date()
    regular_discount = product.discount_price or product.base_price
    extra_offer = product.offers.filter(
        start_date__lte=today, end_date__gte=today, is_extra=True
    ).last()
    if not extra_offer:
        return 0
    if extra_offer.discount_percent:
        after_offer = regular_discount - (regular_discount * (Decimal(str(extra_offer.discount_percent)) / Decimal('100')))
    elif extra_offer.discount_rs:
        after_offer = regular_discount - Decimal(str(extra_offer.discount_rs))
    else:
        after_offer = regular_discount
    extra_amount = int(round(float(regular_discount - after_offer)))
    return extra_amount if extra_amount > 0 else 0