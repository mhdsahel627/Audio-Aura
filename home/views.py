# home/views.py
from django.shortcuts import render,redirect
from django.views.decorators.cache import never_cache
from category.models import Category
from products.models import Product  
from django.http import JsonResponse
from django.urls import reverse
from decimal import Decimal
from django.utils import timezone
from banner.models import Banner
from banner.models import DealOfMonth, DealImage,FeaturedProduct


""" .......................................................Home Page..................................... """

@never_cache
def HomePage(request):
    featured_products = FeaturedProduct.objects.filter(is_active=True)[:4]
    active_deal = DealOfMonth.objects.filter(
        is_active=True,
        starts_on__lte=timezone.now(),
        ends_on__gte=timezone.now()
    ).prefetch_related('images').first()   
     
    # Define today FIRST - before any loop or usage
    today = timezone.now().date()
    
    # Fetch all active categories for display
    categories = Category.objects.filter(is_active=True)

    # Priority list of possible product ordering fields
    order_fields = ['-created_at', '-added_on', '-updated_at', '-id']

    # Determine a valid field to order products by
    for f in order_fields:
        try:
            Product._meta.get_field(f.strip('-'))
            order_by = f
            break
        except Exception:
            continue
    else:
        order_by = '-id'

    # Fetch only listed products
    latest_products = Product.objects.filter(is_listed=True).order_by(order_by)[:8]

    # Enrich with price and offers info
    for p in latest_products:
        p.final_price = p.get_final_price()
        p.discount_percent = p.get_discount_percent()
        p.extra_off = p.get_extra_off()
    
    # Get active banners (today is already defined above)
    banners = Banner.objects.filter(
        is_active=True,
        start_date__lte=today,
        end_date__gte=today
    ).order_by('priority', '-created_at')[:10]
    
    # Render homepage template
    return render(request, 'user/index.html', {
        'featured_products': featured_products,
        'active_deal': active_deal,
        'banners': banners,
        'categories': categories,
        'latest_products': latest_products,
    })
""" .......................................................Filter New Arrivals..................................... """

@never_cache  # Prevent caching to ensure latest products are always shown
def filter_new_arrivals(request):
    """
    AJAX endpoint to filter and display latest/new arrival products.

    Behavior:
    - Accepts an optional 'category' GET parameter to filter products by category name.
    - Fetches only products that are listed (is_listed=True).
    - Determines a valid ordering field ('-created_at' preferred, fallback '-id').
    - Selects the latest 12 products after ordering.
    - Generates HTML for each product card, including image, discount info, rating, offer, and variants.
    - Returns a JSON response containing the HTML and product count.
    - Returns a fallback HTML message if no products are found.

    Notes:
    - Uses `getattr` with defaults to safely handle missing attributes (images, rating, offer).
    - Supports discount display if discount_price < base_price.
    - Intended for dynamic AJAX filtering on the homepage or category pages.
    """

    # Get category filter from GET request, remove leading/trailing spaces
    category_name = request.GET.get('category', '').strip()

    # Base queryset: only products that are listed
    qs = Product.objects.filter(is_listed=True)

    # Filter by category name if provided
    if category_name:
        qs = qs.filter(category__name__iexact=category_name)

    # Determine order field: prefer '-created_at', fallback to '-id'
    order_field = '-created_at'
    try:
        Product._meta.get_field('created_at')  # Check if field exists
    except Exception:
        order_field = '-id'

    # Get the latest 12 products based on order field
    latest_products = qs.order_by(order_field)[:12]

    # Build HTML for all product cards
    cards_html = ""
    for p in latest_products:
        # Determine product image
        if getattr(p, 'images', None) and p.images.all():
            img_url = p.images.first().image.url
        elif getattr(p, 'image', None):
            img_url = p.image.url
        else:
            img_url = '/static/images/default-product.png'  # fallback image

        # Build discount block if applicable
        sub_html = ""
        if p.discount_price and p.base_price and p.discount_price < p.base_price:
            sub_html = (
                f'<div class="aa-sub">'
                f'<span class="aa-mrp">₹{p.base_price}</span>'
                f'<span class="aa-off">{p.get_discount_percent()}% off</span>'
                f'</div>'
            )

        # Safe defaults for rating and offer
        rating = getattr(p, 'rating', None) or 4.7
        offer = getattr(p, 'offer', '') or ''

        # URL to product detail page
        detail_url = reverse('product_detail', args=[p.id])

        # Build full product card HTML
        cards_html += f"""
        <div class="aa-card aa-232 aa-elev">
          <a class="aa-media" href="{detail_url}">
            <span class="aa-badge">
              <span class="aa-badge-emoji">🎉</span>
              <span class="aa-badge-text">New Launch</span>
            </span>
            <img class="aa-img" src="{img_url}" alt="{p.name}">
            <div class="aa-band">
              <span class="aa-band-text">{offer}</span>
              <span class="aa-chip"><span>⭐{rating}</span></span>
            </div>
          </a>
          <div class="aa-info">
            <h3 class="aa-title">
              <a href="{detail_url}" class="text-decoration-none text-reset">{p.name}</a>
            </h3>
            <div class="aa-divider"></div>
            <div class="aa-price-row">
              <div class="aa-price-group">
                <div class="aa-price">₹{p.discount_price or p.base_price}</div>
                {sub_html}
              </div>
              <div class="aa-variants aa-swatches">
                <div class="aa-swatch-wrap" aria-label="colors">
                  <span class="aa-swatch aa-s1" style="--c:#111111"></span>
                  <span class="aa-swatch aa-s2" style="--c:#1E56D9"></span>
                </div>
              </div>
            </div>
          </div>
        </div>
        """

    # Fallback if no products found
    if not cards_html:
        cards_html = '<p class="text-white">No products found in this category.</p>'

    # Return JSON response with HTML and product count
    return JsonResponse({
        'success': True,
        'html': cards_html,
        'count': latest_products.count() if hasattr(latest_products, 'count') else len(latest_products)
    })


def not_found(request):
    return render(request, 'user/404.html')
  
  




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


