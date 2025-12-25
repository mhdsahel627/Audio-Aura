# products/views.py
from coupons.models import Coupon 
from django.contrib.auth.decorators import user_passes_test,login_required
from django.contrib.admin.views.decorators import staff_member_required
from admin_side.views import is_admin
from datetime import date, datetime  
from datetime import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from .models import Product, ProductImage, ProductVariant, ProductVariantImage, ProductDetailedImage,ProductOffer
from category.models import Category, Brand
from decimal import Decimal
from functools import wraps
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.db.models import Prefetch
import re
from django.core.paginator import Paginator
from django.views.decorators.csrf import csrf_exempt
from decimal import Decimal, InvalidOperation
from .models import TemporaryUpload
import cloudinary.uploader
import json
from django.db.models import Sum
from django.urls import reverse
from .forms import ProductAddForm 
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_http_methods

def admin_required(view_func):
    """
    Decorator to allow only authenticated superusers (admins) to access a view.
    If the user is not admin, redirects to login page.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        return redirect("login")
    return wrapper



alnum_nospace_re = re.compile(r'^[A-Za-z0-9]+$')  # only letters and numbers, no spaces
name_re = re.compile(r'^[A-Za-z0-9 _-]+$')  # letters, numbers, spaces, underscore, hyphen

""" .......................................................Add Product..................................... """
@login_required
@require_http_methods(["GET", "POST"])
def add_product(request):
    categories = Category.objects.filter(is_active=True)
    brands = Brand.objects.all()
    
    if request.method == "POST":
        form = ProductAddForm(request.POST)
        
        # Variant raw data
        colors = request.POST.getlist("variant_color[]")
        stocks_raw = request.POST.getlist("variant_stock[]")
        
        # Temporary uploads (Cloudinary staged)
        temp_product_ids = request.POST.getlist("temp_product_images[]")
        temp_detailed_ids = request.POST.getlist("temp_detailed_images[]")

        try:
            # ✅ STEP 1: Validate Django Form
            if not form.is_valid():
                return JsonResponse({
                    "success": False,
                    "field_errors": {k: [str(e) for e in v] for k, v in form.errors.items()},
                    "non_field_errors": [str(e) for e in form.non_field_errors()],
                }, status=400)

            # ✅ STEP 2: Extra validations (images, variants)
            non_field_errors = []
            
            # Validate product images
            if not temp_product_ids:
                non_field_errors.append("At least one product image is required.")
            
            # Validate variants
            if not colors:
                non_field_errors.append("At least one variant color is required.")
            
            # Validate each variant
            for idx, color in enumerate(colors):
                if not color.strip():
                    non_field_errors.append(f"Variant {idx + 1}: Color cannot be empty.")
                
                # Validate stock for this variant
                if idx < len(stocks_raw):
                    try:
                        stock_val = int(stocks_raw[idx])
                        if stock_val < 0:
                            non_field_errors.append(f"Variant {idx + 1}: Stock cannot be negative.")
                    except ValueError:
                        non_field_errors.append(f"Variant {idx + 1}: Invalid stock value.")
                
                # ✅ NEW: Validate variant images
                v_ids = request.POST.getlist(f"temp_variant_images_{idx}[]")
                if not v_ids or len(v_ids) == 0:
                    non_field_errors.append(f"Variant {idx + 1} ({color.strip() if color.strip() else 'unnamed'}): At least one image is required.")

            # Return validation errors if any
            if non_field_errors:
                return JsonResponse({
                    "success": False,
                    "field_errors": {},
                    "non_field_errors": non_field_errors,
                }, status=400)

            # ✅ STEP 3: All validations passed - Create Product
            cd = form.cleaned_data

            product = Product.objects.create(
                name=cd["name"],
                short_description=cd["short_desc"],
                long_description=cd["long_desc"],
                brand_id=cd["brand"],
                category_id=cd["category"],
                base_price=cd["base_price"],
                discount_price=cd["discount_price"],
                offer=cd["offer"],
                video=cd["video"] or None,
                is_listed=True
            )

            # ✅ STEP 4: Product images (staged → permanent)
            temp_products = TemporaryUpload.objects.filter(
                list_key="product", id__in=temp_product_ids
            )
            for t in temp_products:
                ProductImage.objects.create(
                    product=product,
                    cloud_url=t.cloud_url,
                    public_id=t.public_id
                )

            # ✅ STEP 5: Detailed images
            temp_details = TemporaryUpload.objects.filter(
                list_key="detailed", id__in=temp_detailed_ids
            )
            for t in temp_details:
                ProductDetailedImage.objects.create(
                    product=product,
                    cloud_url=t.cloud_url,
                    public_id=t.public_id
                )

            # ✅ STEP 6: Variants + variant images
            for idx, color in enumerate(colors):
                if not color.strip():
                    continue
                
                stock_val = 0
                if idx < len(stocks_raw) and stocks_raw[idx]:
                    try:
                        stock_val = max(int(stocks_raw[idx]), 0)
                    except ValueError:
                        stock_val = 0

                variant = ProductVariant.objects.create(
                    product=product,
                    color=color.strip(),
                    stock=stock_val
                )

                # Variant images
                v_ids = request.POST.getlist(f"temp_variant_images_{idx}[]")
                if v_ids:
                    v_temp = TemporaryUpload.objects.filter(
                        list_key=f"variant_{idx}", id__in=v_ids
                    )
                    for t in v_temp:
                        ProductVariantImage.objects.create(
                            variant=variant,
                            cloud_url=t.cloud_url,
                            public_id=t.public_id
                        )

            # Stock sync happens automatically in ProductVariant.save()
            product.refresh_from_db()

            messages.success(request, f"Product '{cd['name']}' created successfully!")
            
            return JsonResponse({
                "success": True,
                "message": f"Product '{cd['name']}' created successfully with {len(product.images.all())} images!",
                "redirect_url": reverse("product_list"),
            })

        except ValidationError as ve:
            # Handle Django ValidationErrors
            return JsonResponse({
                "success": False,
                "field_errors": {},
                "non_field_errors": [str(ve)],
            }, status=400)
        
        except Exception as e:
            # Log the error for debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Product creation failed: {str(e)}", exc_info=True)
            
            return JsonResponse({
                "success": False,
                "field_errors": {},
                "non_field_errors": [f"Failed to create product: {str(e)}"],
            }, status=500)

    # GET request
    form = ProductAddForm()
    return render(request, "admin/product_add.html", {
        "categories": categories,
        "brands": brands,
        "form": form,
    })


@require_http_methods(["POST"])
def upload_temp_image(request):
    try:
        file = request.FILES.get('file')
        list_key = request.POST.get('list_key', 'product')
        
        if not file:
            return JsonResponse({'success': False, 'message': 'No file provided'})
        
        # Upload to Cloudinary
        result = cloudinary.uploader.upload(
            file,
            folder='audio_aura/temp/',
            resource_type='image'
        )
        
        # Create TemporaryUpload record
        temp_upload = TemporaryUpload.objects.create(
            list_key=list_key,
            cloud_url=result['secure_url'],
            public_id=result['public_id'],
            owner=request.user if request.user.is_authenticated else None
        )
        
        return JsonResponse({
            'success': True,
            'temp_id': temp_upload.id,
            'url': result['secure_url']
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)})



@require_POST
@login_required
def ajax_upload_image(request):
    file_obj = request.FILES.get('file')
    list_key = request.POST.get('list_key')  # "product", "detailed", "variant_0" etc.
    if not file_obj or not list_key:
        return JsonResponse({'success': False, 'error': 'Missing file or list_key'}, status=400)

    try:
        result = cloudinary.uploader.upload(file_obj)  # you can pass folder/preset here
        temp = TemporaryUpload.objects.create(
            owner=request.user,
            session_key=request.session.session_key or "",
            list_key=list_key,
            cloud_url=result["secure_url"],
            public_id=result["public_id"],
        )
        return JsonResponse({
            'success': True,
            'id': temp.id,
            'url': temp.cloud_url,
            'public_id': temp.public_id,
            'list_key': list_key,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

    
@admin_required
@csrf_protect
def add_brand_ajax(request):
    """
    AJAX view to add a new brand.
    """
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            name = data.get("name", "").strip()
            if not name:
                return JsonResponse({"success": False, "message": "Brand name is required."}, status=400)
            if len(name) > 255:
                return JsonResponse({"success": False, "message": "Brand name too long."}, status=400)
            if Brand.objects.filter(name__iexact=name).exists():
                return JsonResponse({"success": False, "message": "Brand name already exists."}, status=400)
            brand = Brand.objects.create(name=name)
            return JsonResponse({"success": True, "id": brand.id, "name": brand.name})
        except json.JSONDecodeError:
            return JsonResponse({"success": False, "message": "Invalid JSON data."}, status=400)
        except Exception as e:
            return JsonResponse({"success": False, "message": f"Error: {str(e)}"}, status=500)
    return JsonResponse({"success": False, "message": "Invalid request method."}, status=405)


""" .......................................................Product Detail Page..................................... """
def check_stock(request, variant_id):
    """
    AJAX endpoint to return stock info for a specific variant.
    """
    try:
        variant = ProductVariant.objects.get(id=variant_id)
        return JsonResponse({'stock': variant.stock})
    except ProductVariant.DoesNotExist:
        return JsonResponse({'error': 'Variant not found'}, status=404)
    


@never_cache
def product_detail(request, id):
    try:
        # ✅ BOTH CHECKS: product.is_listed AND category.is_active
        product = (
            Product.objects
            .select_related("category", "brand")
            .prefetch_related(
                Prefetch("variants__images", to_attr="prefetched_images"),
                Prefetch("images", to_attr="prefetched_images"),
                "detailed_images",
            )
            .get(
                id=id, 
                is_listed=True,              # ✅ Product must be listed
                category__is_active=True     # ✅ Category must be active
            )
        )
            
    except ObjectDoesNotExist:
        messages.error(request, "This product is currently unavailable.")
        return redirect("shop")

    # ✅ Only active categories in sidebar
    categories = Category.objects.filter(is_active=True).order_by("name")

    default_variant = None
    if product.variants.exists():
        dv = getattr(product, "default_variant", None)
        default_variant = dv() if callable(dv) else None
        if default_variant is None:
            default_variant = product.variants.filter(is_default=True).first() or product.variants.order_by("id").first()

    if default_variant and getattr(default_variant, "prefetched_images", None):
        images = default_variant.prefetched_images
    elif default_variant:
        images = list(default_variant.images.all())
    elif getattr(product, "prefetched_images", None):
        images = product.prefetched_images
    else:
        images = list(product.images.all())

    stock = int(getattr(default_variant, "stock", None) or 0) if default_variant else int(product.stock_quantity or 0)
    in_stock = stock > 0

    variant_stock_map = {str(v.id): int(v.stock or 0) for v in product.variants.all()} if product.variants.exists() else {}
    variant_stock_map_json = json.dumps(variant_stock_map)

    crumbs = [("Home", reverse("home")), ("Shop", reverse("shop"))]
    if product.category:
        crumbs.append((product.category.name, reverse("shop_category_id", args=[product.category.id])))
    crumbs.append((product.name, None))

    back_to = request.GET.get("ret") or None

    # Calculate final price and discount dynamically
    final_price = product.get_final_price()
    discount_percent = product.get_discount_percent()

    # Get active offers for this product
    today = date.today()
    active_coupons = Coupon.objects.filter(
        is_active=True,
        expiry_date__gte=today,
        min_items__gt=0
    ).order_by('display_order', 'min_items')[:4]

    offers = []
    for coupon in active_coupons:
        condition_text = f"Buy {coupon.min_items} or more"
        
        if coupon.coupon_type == 'percent':
            discount_text = f"Get {coupon.discount:.0f}% off"
        else:
            discount_text = f"Get ₹{coupon.discount:.0f} off"
        
        offers.append({
            'id': coupon.id,
            'code': coupon.code,
            'title': coupon.title,
            'condition_text': condition_text,
            'discount_text': discount_text,
            'badge': coupon.badge or "",
            'min_items': coupon.min_items,
        })

    return render(
        request,
        "user/product_detailed.html",
        {
            "product": product,
            "crumbs": crumbs,
            "back_to": back_to,
            "categories": categories,
            "default_variant": default_variant,
            "images": images,
            "in_stock": in_stock,
            "stock": stock,
            "variant_stock_map_json": variant_stock_map_json,
            "final_price": final_price,
            "discount_percent": discount_percent,
            "offers": offers,
        },
    )

""" .......................................................Variant Images Fetch API..................................... """

@require_GET  # Only allow GET requests
@never_cache  # Prevent caching to ensure latest images are returned
def variant_images(request, variant_id):
    """
    Return all images for a specific product variant as a JSON response.

    Behavior:
    - Fetch the ProductVariant by ID, including its related product.
    - Retrieve all associated variant images (via `images` or `variant_images` related name).
    - If no variant images exist, fallback to the main product's images.
    - Return JSON containing list of image URLs.
    - Return HTTP 404 JSON if variant does not exist.

    Notes:
    - Designed for AJAX requests to dynamically load images for variant selection in the frontend.
    - @never_cache ensures always fresh images.
    - select_related('product') optimizes DB queries for product reference.
    """

    try:
        # Fetch the variant along with its parent product
        variant = ProductVariant.objects.select_related('product').get(id=variant_id)

        # Try to get related variant images
        qs = getattr(variant, 'images', None) or getattr(variant, 'variant_images', None)

        # Collect image URLs; order by 'id' for consistent display
        urls = [vi.image.url for vi in (qs.all().order_by('id') if qs else [])]

        # Fallback: if variant has no images, use product images
        if not urls:
            urls = [pi.image.url for pi in variant.product.images.all().order_by('id')]

        # Return JSON response with images
        return JsonResponse({'images': urls}, status=200)

    except ProductVariant.DoesNotExist:
        # Variant not found, return empty array with 404
        return JsonResponse({'images': []}, status=404)

    
    
    
""" .......................................................Admin Product List..................................... """

@admin_required
@never_cache
def product_list(request):
    query = request.GET.get('search', '').strip()
    category_id = request.GET.get('category')
    brand_id = request.GET.get('brand', '').strip()
    price_range = request.GET.get('price_range', '').strip()
    sort_by = request.GET.get('sort', '')

    products = Product.objects.select_related("brand", "category").all()

    if query:
        products = products.filter(
            Q(name__icontains=query) |
            Q(brand__name__icontains=query) |
            Q(category__name__icontains=query)
        )

    if category_id:
        products = products.filter(category_id=category_id)

    if brand_id:
        products = products.filter(brand_id=brand_id)

    if price_range:
        try:
            min_price, max_price = map(Decimal, price_range.split('-'))
            products = products.filter(
                Q(discount_price__gte=min_price, discount_price__lte=max_price) |
                Q(discount_price__isnull=True, base_price__gte=min_price, base_price__lte=max_price)
            )
        except Exception:
            messages.error(request, "Invalid price range format.")

    if sort_by == "plh":
        products = products.order_by("discount_price")
    elif sort_by == "pll":
        products = products.order_by("-discount_price")
    elif sort_by == "new":
        products = products.order_by("-id")

    # Add discount and final price attributes on each product for template
    for product in products:
        product.best_discount = product.get_best_discount()
        product.final_price = product.get_final_price()

    paginator = Paginator(products, 6) 
    page_number = request.GET.get("page")
    products = paginator.get_page(page_number)

    categories = Category.objects.filter(is_active=True)
    brands = Brand.objects.all()

    return render(
        request,
        "admin/product_list.html",
        {
            "products": products,
            "categories": categories,
            "brands": brands,
            "selected_brand": brand_id,
            "selected_category": int(category_id) if category_id else None,
            "selected_sort": sort_by,
            "search_query": query,
        },
    )

    
""" .......................................................Admin Product Edit..................................... """

@admin_required
@never_cache
@csrf_protect
def product_edit(request, product_id):
    """Edit product with enhanced validation and error handling"""
    
    product = get_object_or_404(Product, id=product_id)
    categories = Category.objects.filter(is_active=True)
    brands = Brand.objects.all()
    
    # File upload limits
    max_file_size = 5 * 1024 * 1024  # 5MB
    max_product_images = 15
    max_detailed_images = 5
    max_variant_images = 15
    
    errors = {}  # For field-specific errors
    
    if request.method == "POST":
        try:
            with transaction.atomic():
                # Core Fields
                name = (request.POST.get("name") or "").strip()
                short_desc = (request.POST.get("short_desc") or "").strip()
                long_desc = (request.POST.get("long_desc") or "").strip()
                brand_id = request.POST.get("brand")
                category_id = request.POST.get("category")
                base_price_in = request.POST.get("base_price")
                discount_price_in = request.POST.get("discount_price", "")
                offer = (request.POST.get("offer") or "").strip()
                video = (request.POST.get("video") or "").strip()
                
                # === VALIDATION ===
                # 1. Name validation
                if not name:
                    errors['name'] = 'Product name is required'
                elif len(name) < 3:
                    errors['name'] = 'Product name must be at least 3 characters'
                elif len(name) > 200:
                    errors['name'] = 'Product name cannot exceed 200 characters'
                elif not re.match(r'^[A-Za-z0-9 _-]+$', name):
                    errors['name'] = 'Product name can only contain letters, numbers, spaces, hyphens, and underscores'
                elif Product.objects.filter(name__iexact=name).exclude(id=product.id).exists():
                    errors['name'] = 'A product with this name already exists'
                

                # 3. Category validation
                if not category_id:
                    errors['category'] = 'Category is required'
                else:
                    try:
                        category_obj = Category.objects.get(id=category_id, is_active=True)
                    except Category.DoesNotExist:
                        errors['category'] = 'Invalid category selected'
                
                # 4. Brand validation
                if not brand_id:
                    errors['brand'] = 'Brand is required'
                else:
                    try:
                        brand_obj = Brand.objects.get(id=brand_id)
                    except Brand.DoesNotExist:
                        errors['brand'] = 'Invalid brand selected'
                
                # 5. Price validation
                if not base_price_in:
                    errors['base_price'] = 'Base price is required'
                else:
                    try:
                        base_price = Decimal(base_price_in)
                        if base_price <= 0:
                            errors['base_price'] = 'Base price must be greater than 0'
                        elif base_price > 9999999:
                            errors['base_price'] = 'Base price is too high'
                    except (ValueError, InvalidOperation):
                        errors['base_price'] = 'Invalid price format'
                
                # 6. Discount price validation
                discount_price = None
                if discount_price_in:
                    try:
                        discount_price = Decimal(discount_price_in)
                        if discount_price <= 0:
                            errors['discount_price'] = 'Discount price must be greater than 0'
                        elif 'base_price' not in errors and discount_price >= base_price:
                            errors['discount_price'] = 'Discount price must be less than base price'
                    except (ValueError, InvalidOperation):
                        errors['discount_price'] = 'Invalid discount price format'
                
                # Handle image removals
                remove_product_image_ids = [int(x) for x in request.POST.getlist("remove_product_image_ids[]") if x]
                remove_detailed_image_ids = [int(x) for x in request.POST.getlist("remove_detailed_image_ids[]") if x]
                remove_variant_ids = [int(x) for x in request.POST.getlist("remove_variant_ids[]") if x]
                
                # Validate new uploads
                new_product_images = request.FILES.getlist("product_images")
                new_detailed_images = request.FILES.getlist("detailed_images")
                
                # 7. Image validation
                for img in new_product_images + new_detailed_images:
                    content_type = getattr(img, "content_type", "") or ""
                    if not content_type.startswith("image/"):
                        errors['images'] = 'Only image files are allowed'
                        break
                    if img.size > max_file_size:
                        errors['images'] = f'Each image must be less than 5MB (found {img.size / 1024 / 1024:.1f}MB)'
                        break
                
                # Check image counts
                remaining_product_count = ProductImage.objects.filter(product=product).exclude(id__in=remove_product_image_ids).count()
                remaining_detailed_count = ProductDetailedImage.objects.filter(product=product).exclude(id__in=remove_detailed_image_ids).count()
                
                if remaining_product_count + len(new_product_images) > max_product_images:
                    errors['product_images'] = f'Maximum {max_product_images} product images allowed'
                
                if remaining_detailed_count + len(new_detailed_images) > max_detailed_images:
                    errors['detailed_images'] = f'Maximum {max_detailed_images} detailed images allowed'
                
                # Ensure at least one product image remains
                if remaining_product_count + len(new_product_images) == 0:
                    errors['product_images'] = 'At least one product image is required'
                
                # 8. Variants validation
                existing_ids = [int(x) for x in request.POST.getlist("existing_variant_id[]")]
                existing_colors = request.POST.getlist("color_existing[]")
                existing_stocks = request.POST.getlist("stock_existing[]")
                new_colors = request.POST.getlist("color_new[]")
                new_stocks = request.POST.getlist("stock_new[]")
                
                if not (len(existing_ids) == len(existing_colors) == len(existing_stocks)):
                    errors['variants'] = 'Invalid variant data submitted'
                
                final_colors = set()
                
                # Validate existing variants
                for idx, v_id in enumerate(existing_ids):
                    if v_id in remove_variant_ids:
                        continue
                    
                    color = (existing_colors[idx] or "").strip()
                    stock_raw = existing_stocks[idx] or ""
                    
                    if not color:
                        errors[f'variant_{v_id}_color'] = 'Variant color is required'
                    
                    try:
                        stock_val = int(stock_raw) if stock_raw != "" else 0
                        if stock_val < 0:
                            errors[f'variant_{v_id}_stock'] = 'Stock cannot be negative'
                    except ValueError:
                        errors[f'variant_{v_id}_stock'] = 'Invalid stock quantity'
                    
                    if color in final_colors:
                        errors[f'variant_{v_id}_color'] = f'Duplicate color "{color}"'
                    else:
                        final_colors.add(color)
                    
                    # Variant images validation
                    try:
                        v = ProductVariant.objects.get(id=v_id, product=product)
                        current_v_count = ProductVariantImage.objects.filter(variant=v).count()
                        to_remove = [int(x) for x in request.POST.getlist(f"remove_variant_image_ids_{v_id}[]") if x]
                        resulting_count = current_v_count - len(to_remove)
                        variant_new_images = request.FILES.getlist(f"variant_images_{v.id}")
                        
                        if resulting_count + len(variant_new_images) > max_variant_images:
                            errors[f'variant_{v_id}_images'] = f'Maximum {max_variant_images} images allowed per variant'
                    except ProductVariant.DoesNotExist:
                        errors[f'variant_{v_id}'] = 'Invalid variant'
                
                # Validate new variants
                for i, (color_raw, stock_raw) in enumerate(zip(new_colors, new_stocks)):
                    color = (color_raw or "").strip()
                    
                    if not color:
                        errors[f'new_variant_{i}_color'] = 'Variant color is required'
                    
                    try:
                        stock_val = int(stock_raw) if stock_raw not in (None, "") else 0
                        if stock_val < 0:
                            errors[f'new_variant_{i}_stock'] = 'Stock cannot be negative'
                    except ValueError:
                        errors[f'new_variant_{i}_stock'] = 'Invalid stock quantity'
                    
                    if color in final_colors:
                        errors[f'new_variant_{i}_color'] = f'Duplicate color "{color}"'
                    else:
                        final_colors.add(color)
                    
                    new_v_images = request.FILES.getlist(f"variant_images_new_{i}")
                    if len(new_v_images) > max_variant_images:
                        errors[f'new_variant_{i}_images'] = f'Maximum {max_variant_images} images allowed'
                
                # If there are errors, stop and return
                if errors:
                    for field, error in errors.items():
                        messages.error(request, f"{field}: {error}")
                    
                    context = {
                        "product": product,
                        "categories": categories,
                        "brands": brands,
                        "product_images": ProductImage.objects.filter(product=product),
                        "detailed_images": ProductDetailedImage.objects.filter(product=product),
                        "variants": ProductVariant.objects.filter(product=product).prefetch_related("images"),
                        "errors": errors
                    }
                    return render(request, "admin/product_edit.html", context)
                
                # === SAVE CHANGES ===
                product.name = name
                product.short_description = short_desc
                product.long_description = long_desc
                product.brand = brand_obj
                product.category = category_obj
                product.base_price = base_price
                product.discount_price = discount_price
                product.offer = offer
                product.video = video
                product.save()
                
                # Apply deletions
                if remove_product_image_ids:
                    ProductImage.objects.filter(product=product, id__in=remove_product_image_ids).delete()
                if remove_detailed_image_ids:
                    ProductDetailedImage.objects.filter(product=product, id__in=remove_detailed_image_ids).delete()
                if remove_variant_ids:
                    ProductVariant.objects.filter(product=product, id__in=remove_variant_ids).delete()
                
                for v_id in ProductVariant.objects.filter(product=product).values_list("id", flat=True):
                    to_remove = [int(x) for x in request.POST.getlist(f"remove_variant_image_ids_{v_id}[]") if x]
                    if to_remove:
                        ProductVariantImage.objects.filter(variant_id=v_id, id__in=to_remove).delete()
                
                # Add new images
                for img in new_product_images:
                    ProductImage.objects.create(product=product, image=img)
                for img in new_detailed_images:
                    ProductDetailedImage.objects.create(product=product, image=img)
                
                # Update existing variants
                for idx, v_id in enumerate(existing_ids):
                    if v_id in remove_variant_ids:
                        continue
                    v = get_object_or_404(ProductVariant, id=v_id, product=product)
                    v.color = (existing_colors[idx] or "").strip()
                    v.stock = int(existing_stocks[idx] or 0)
                    v.save()
                    
                    for img in request.FILES.getlist(f"variant_images_{v.id}"):
                        ProductVariantImage.objects.create(variant=v, image=img)
                
                # Add new variants
                for i, (color_raw, stock_raw) in enumerate(zip(new_colors, new_stocks)):
                    v = ProductVariant.objects.create(
                        product=product,
                        color=(color_raw or "").strip(),
                        stock=int(stock_raw or 0)
                    )
                    for img in request.FILES.getlist(f"variant_images_new_{i}"):
                        ProductVariantImage.objects.create(variant=v, image=img)
                
                # Recalculate total stock
                product.stock_quantity = ProductVariant.objects.filter(product=product).aggregate(s=Sum('stock'))['s'] or 0
                product.save(update_fields=["stock_quantity"])
                
                messages.success(request, f'✅ Product "{product.name}" updated successfully!')
                return redirect(reverse("product_list") + "?edit_success=1")
        
        except ValidationError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"❌ Error: {str(e)}")
    
    # Render template
    context = {
        "product": product,
        "categories": categories,
        "brands": brands,
        "product_images": ProductImage.objects.filter(product=product),
        "detailed_images": ProductDetailedImage.objects.filter(product=product),
        "variants": ProductVariant.objects.filter(product=product).prefetch_related("images"),
        "errors": errors
    }
    return render(request, "admin/product_edit.html", context)


""" .......................................................Admin Toggle Product Listing..................................... """

@admin_required
@never_cache
@csrf_protect
def toggle_product(request, id):
    """
    Admin view to toggle a product's listing status (list/unlist).

    Behavior:
    - Accepts only POST requests.
    - Flips the `is_listed` boolean of the product.
    - Returns a JSON response with the new status.
    - Shows a success message in Django messages for admin feedback.

    Notes:
    - If product does not exist, returns 404 automatically via get_object_or_404.
    - If method is not POST, returns HTTP 405 Method Not Allowed with error message.
    - Can be used via AJAX in admin product list for quick toggling.
    """
    if request.method == 'POST':
        product = get_object_or_404(Product, id=id)

        # Toggle listing status
        product.is_listed = not product.is_listed
        product.save()

        # Admin feedback via Django messages
        status_text = "listed" if product.is_listed else "unlisted"
        messages.success(request, f"Product '{product.name}' {status_text} successfully.")

        # JSON response for AJAX usage
        return JsonResponse({'success': True, 'is_listed': product.is_listed, 'status_text': status_text})

    # Invalid request method
    return JsonResponse({'success': False, 'message': 'Invalid request method. Use POST.'}, status=405)


""" .......................................................View Product Variants..................................... """
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from .models import Product

@never_cache
def view_variants(request, product_id):
    """
    Admin view to display all variants of a specific product.

    Behavior:
    - Handles GET requests only.
    - Fetches the product by ID using get_object_or_404 to ensure it exists.
    - Retrieves all variants associated with the product.
    - Renders a template displaying the product and its variants.

    Notes:
    - Assumes the ProductVariant model has a related_name='variants' in the Product model.
    - Read-only view; no modifications allowed from this endpoint.
    - Can be extended for AJAX, modals, or dynamic variant updates.

    Working Flow:
    - GET request:
        - Fetch product instance by product_id.
        - Fetch all related variants for the product.
        - Pass 'product' and 'variants' to 'view_variant.html' template.
    """

    # Fetch the product object by ID; 404 if not found
    product = get_object_or_404(Product, id=product_id)

    # Retrieve all variants associated with this product
    # Assumes 'variants' is the related_name in the ProductVariant model
    variants = product.variants.all()

    # Render the admin template for viewing variants
    # Pass the product and its variants in the context
    return render(
        request,
        'admin/view_variant.html',
        {
            'product': product,   # Product instance to show info
            'variants': variants, # Queryset of ProductVariant objects
        }
    )


@admin_required
@csrf_protect
@never_cache
def variant_add(request, product_id):
    """
    .......................................................Add Product Variant.....................................
    Admin view to add a new variant to an existing product.

    Behavior
    - Handles GET and POST requests.
    - GET: Renders a form for adding a new variant to the product.
    - POST: Validates submitted color, stock, and images.
        - Ensures color is provided and unique for the product.
        - Ensures stock is a non-negative integer.
        - Ensures variant images count ≤ 10 and are valid image files under 15MB each.
        - Creates the variant and associated images atomically.
        - Displays success or error messages via Django messages framework.
    
    Notes
    - Uses @admin_required to restrict access to admins only.
    - Uses @csrf_protect to enforce CSRF token verification.
    - Uses @never_cache to avoid caching of sensitive admin pages.
    - Validation errors prevent database writes.
    - Supports multiple image uploads via a single input field (request.FILES.getlist).

    Working Flow
    GET Request:
    - Fetch the product by ID.
    - Render 'variant_add.html' with product context.

    POST Request:
    - Retrieve color, stock, and uploaded images.
    - Validate color presence and uniqueness.
    - Validate stock value is integer ≥ 0.
    - Validate number of images and file types/sizes.
    - If any validation fails → show message and redirect back.
    - If all validations pass → create variant and images inside a transaction.
    - Show success message and redirect to view_variants page for the product.
    """
    
    # Fetch the product or show 404 if not found
    product = get_object_or_404(Product, id=product_id)

    # Limits
    max_variant_images = 15
    max_file_size = 15 * 1024 * 1024  # 15MB

    if request.method == "POST":
        # Get form inputs
        color = (request.POST.get("color") or "").strip()
        stock_raw = request.POST.get("stock") or "0"
        files = request.FILES.getlist("variant_images")  # multiple files via same name

        # Validate stock as integer
        try:
            stock = int(stock_raw) if stock_raw else 0
        except ValueError:
            messages.error(request, "Invalid stock value.")
            return redirect("variant_add", product_id=product.id)

        # Validate color presence
        if not color:
            messages.error(request, "Color is required.")
            return redirect("variant_add", product_id=product.id)

        # Check color uniqueness for this product
        if ProductVariant.objects.filter(product=product, color=color).exists():
            messages.error(request, "Duplicate color for this product.")
            return redirect("variant_add", product_id=product.id)

        # Validate stock non-negative
        if stock < 0:
            messages.error(request, "Stock cannot be negative.")
            return redirect("variant_add", product_id=product.id)

        # Validate max images
        if len(files) > max_variant_images:
            messages.error(request, f"Max {max_variant_images} images per variant.")
            return redirect("variant_add", product_id=product.id)

        # Create variant and images atomically
        with transaction.atomic():
            v = ProductVariant.objects.create(product=product, color=color, stock=stock)
            for f in files:
                ctype = getattr(f, "content_type", "") or ""
                # Validate image type
                if ctype and not ctype.startswith("image/"):
                    messages.error(request, "Invalid variant image.")
                    return redirect("variant_add", product_id=product.id)
                # Validate image size
                if f.size > max_file_size:
                    messages.error(request, "Invalid variant image.")
                    return redirect("variant_add", product_id=product.id)
                # Save image
                ProductVariantImage.objects.create(variant=v, image=f)

        # Debug log (optional)
        files = request.FILES.getlist("variant_images")
        print("variant_add received files:", len(files))

        # Success message
        messages.success(request, "Variant created.")
        return redirect("view_variants", product_id=product.id)

    # Render form for GET request
    return render(request, "admin/variant_add.html", {"product": product})



@admin_required
@csrf_protect
@never_cache
def variant_edit(request, product_id, variant_id):
    """
    .......................................................Edit Product Variant.....................................
    Admin view to edit an existing variant of a product.

    Behavior
    - Handles GET and POST requests.
    - GET: Renders a form showing the variant’s current color, stock, and images.
    - POST: Validates submitted color, stock, and image changes.
        - Allows removal of existing images.
        - Allows adding new images (max 10 per variant, ≤15MB each).
        - Ensures color is present.
        - Ensures stock is a non-negative integer.
        - Updates the variant record atomically along with images.
        - Displays success or error messages via Django messages framework.

    Notes
    - Uses @admin_required to restrict access to admins only.
    - Uses @csrf_protect to enforce CSRF token verification.
    - Uses @never_cache to prevent caching of sensitive admin pages.
    - Validation errors prevent database writes.
    - Multiple images handled via request.FILES.getlist.
    - Existing images can be removed by passing their IDs in 'remove_image_ids[]'.

    Working Flow
    GET Request:
    - Fetch product and variant by ID.
    - Fetch existing images.
    - Render 'variant_edit.html' with product, variant, and images.

    POST Request:
    - Retrieve color, stock, images to remove, and new uploaded images.
    - Validate new image count (current + new ≤ 10) and file types/sizes.
    - Delete removed images.
    - Create new images.
    - Validate stock is integer ≥ 0.
    - Update variant color and stock inside a transaction.
    - Show success message and redirect to view_variants page.
    """
    
    # Fetch product and variant or return 404 if not found
    product = get_object_or_404(Product, id=product_id)
    variant = get_object_or_404(ProductVariant, id=variant_id, product=product)

    # Limits
    max_variant_images = 15
    max_file_size = 15 * 1024 * 1024  # 15MB

    if request.method == "POST":
        # Get form inputs
        color = (request.POST.get("color") or "").strip()
        stock_raw = request.POST.get("stock") or "0"
        remove_img_ids = [int(x) for x in request.POST.getlist("remove_image_ids[]") if x]
        add_files = request.FILES.getlist("variant_images")  # new images to add

        # Debug log (optional)
        print("variant_edit received files:", len(add_files))

        with transaction.atomic():
            # Remove selected images
            if remove_img_ids:
                ProductVariantImage.objects.filter(variant=variant, id__in=remove_img_ids).delete()

            # Check total image count limit
            current_count = ProductVariantImage.objects.filter(variant=variant).count()
            if current_count + len(add_files) > max_variant_images:
                messages.error(request, f"Max {max_variant_images} images per variant.")
                return redirect("variant_edit", product_id=product.id, variant_id=variant.id)

            # Validate and save new images
            for f in add_files:
                ctype = getattr(f, "content_type", "") or ""
                if ctype and not ctype.startswith("image/"):
                    messages.error(request, "Invalid variant image.")
                    return redirect("variant_edit", product_id=product.id, variant_id=variant.id)
                if f.size > max_file_size:
                    messages.error(request, "Invalid variant image.")
                    return redirect("variant_edit", product_id=product.id, variant_id=variant.id)
                ProductVariantImage.objects.create(variant=variant, image=f)

            # Validate stock as integer
            try:
                stock = int(stock_raw) if stock_raw else 0
            except ValueError:
                messages.error(request, "Invalid stock value.")
                return redirect("variant_edit", product_id=product.id, variant_id=variant.id)

            # Update variant fields
            variant.color = color
            variant.stock = stock
            variant.save()

        # Success message
        messages.success(request, "Variant updated.")

        # Debug log (optional)
        print("variant_edit received files:", len(request.FILES.getlist("variant_images")))

        return redirect("view_variants", product_id=product.id)

    # GET request: fetch existing images
    images = ProductVariantImage.objects.filter(variant=variant)
    return render(request, "admin/variant_edit.html", {"product": product, "variant": variant, "images": images})


"""product offer"""

def get_discounted_price(product):
    from django.utils import timezone
    today = timezone.now().date()
    offer = product.offers.filter(start_date__lte=today, end_date__gte=today).last()
    if offer:
        if offer.discount_percent:
            return product.price - (product.price * offer.discount_percent/100)
        if offer.discount_rs:
            return product.price - offer.discount_rs
    return product.price
@staff_member_required
@require_http_methods(["POST"])
def add_offer(request):
    """Add product offer with percentage discount only"""
    
    product_id = request.POST.get('product_id')
    title = request.POST.get('title', '').strip()
    discount_percent = request.POST.get('discount_percent', '').strip()
    start_date_str = request.POST.get('start_date')
    end_date_str = request.POST.get('end_date')
    
    errors = {}
    
    # 1. Product validation
    if not product_id:
        return JsonResponse({
            'success': False,
            'message': 'Product ID is required'
        }, status=400)
    
    try:
        product = Product.objects.get(id=product_id, is_listed=True)
    except Product.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Product not found or unlisted'
        }, status=404)
    
    # 2. Title validation
    if not title:
        errors['offer-title'] = 'Offer title is required'
    elif len(title) < 3:
        errors['offer-title'] = 'Title must be at least 3 characters'
    elif len(title) > 100:
        errors['offer-title'] = 'Title cannot exceed 100 characters'
    
    # 3. Discount percentage validation
    if not discount_percent:
        errors['discount-percent'] = 'Discount percentage is required'
    else:
        try:
            discount_percent = Decimal(discount_percent)
            if discount_percent <= 0:
                errors['discount-percent'] = 'Percentage must be greater than 0'
            elif discount_percent > 100:
                errors['discount-percent'] = 'Percentage cannot exceed 100%'
        except (ValueError, InvalidOperation):
            errors['discount-percent'] = 'Invalid percentage value'
    
    # 4. Date validation
    if not start_date_str:
        errors['start-date'] = 'Start date is required'
    if not end_date_str:
        errors['end-date'] = 'End date is required'
    
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            today = timezone.now().date()
            
            if start_date < today:
                errors['start-date'] = 'Start date cannot be in the past'
            
            if end_date < start_date:
                errors['end-date'] = 'End date must be after start date'
            elif end_date == start_date:
                errors['end-date'] = 'Offer must be at least 1 day long'
            
            duration = (end_date - start_date).days
            if duration > 365:
                errors['end-date'] = 'Offer duration cannot exceed 1 year'
            
        except (ValueError, TypeError):
            errors['start-date'] = 'Invalid date format'
    
    # 5. Check for overlapping offers
    if not errors and start_date_str and end_date_str:
        overlapping = ProductOffer.objects.filter(
            product=product,
            start_date__lte=end_date,
            end_date__gte=start_date
        ).exists()
        
        if overlapping:
            errors['general'] = 'An offer already exists for this period. Please choose different dates.'
    
    if errors:
        return JsonResponse({
            'success': False,
            'message': 'Please fix the errors below',
            'errors': errors
        }, status=400)
    
    # Create offer
    try:
        offer = ProductOffer.objects.create(
            product=product,
            title=title,
            discount_percent=discount_percent,
            discount_rs=None,  # Always None
            start_date=start_date,
            end_date=end_date,
            is_extra=True
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Offer "{title}" ({discount_percent}% off) added successfully!',
            'offer': {
                'id': offer.id,
                'title': offer.title,
                'discount_percent': str(discount_percent),
                'start_date': start_date.strftime('%d %b %Y'),
                'end_date': end_date.strftime('%d %b %Y')
            }
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Failed to create offer: {str(e)}'
        }, status=500)


@staff_member_required
@require_http_methods(["POST", "GET"])
def edit_offer(request, offer_id):
    """Edit offer - percentage only"""
    
    offer = get_object_or_404(ProductOffer, id=offer_id)
    
    if request.method == "GET":
        return JsonResponse({
            'success': True,
            'product_id': offer.product_id,
            'title': offer.title,
            'discount_percent': str(offer.discount_percent) if offer.discount_percent else '',
            'start_date': offer.start_date.strftime('%Y-%m-%d'),
            'end_date': offer.end_date.strftime('%Y-%m-%d'),
        })
    
    # POST - Update
    title = request.POST.get('title', '').strip()
    discount_percent = request.POST.get('discount_percent', '').strip()
    start_date_str = request.POST.get('start_date')
    end_date_str = request.POST.get('end_date')
    
    errors = {}
    
    if not title or len(title) < 3:
        errors['offer-title'] = 'Title must be at least 3 characters'
    
    if not discount_percent:
        errors['discount-percent'] = 'Discount percentage is required'
    else:
        try:
            discount_percent = Decimal(discount_percent)
            if discount_percent <= 0 or discount_percent > 100:
                errors['discount-percent'] = 'Percentage must be between 0 and 100'
        except (ValueError, InvalidOperation):
            errors['discount-percent'] = 'Invalid percentage value'
    
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            if end_date <= start_date:
                errors['end-date'] = 'End date must be after start date'
            
            # Check overlapping (exclude current offer)
            overlapping = ProductOffer.objects.filter(
                product=offer.product,
                start_date__lte=end_date,
                end_date__gte=start_date
            ).exclude(id=offer_id).exists()
            
            if overlapping:
                errors['general'] = 'Another offer exists for this period'
                
        except (ValueError, TypeError):
            errors['start-date'] = 'Invalid date format'
    
    if errors:
        return JsonResponse({
            'success': False,
            'message': 'Please fix the errors',
            'errors': errors
        }, status=400)
    
    try:
        offer.title = title
        offer.discount_percent = discount_percent
        offer.discount_rs = None
        offer.start_date = start_date
        offer.end_date = end_date
        offer.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Offer "{title}" updated successfully!'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Failed to update: {str(e)}'
        }, status=500)



@staff_member_required
@require_http_methods(["POST"])
def delete_offer(request, offer_id):
    """Delete offer"""
    try:
        offer = get_object_or_404(ProductOffer, id=offer_id)
        offer_title = offer.title
        offer.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'Offer "{offer_title}" deleted successfully!'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Failed to delete offer: {str(e)}'
        }, status=500)

def get_final_discounted_price(product):
    today = timezone.now().date()
    base_offer = product.offers.filter(
        start_date__lte=today, end_date__gte=today, is_extra=False
    ).last()

    # --- CHANGE START ---
    if base_offer:
        if base_offer.discount_percent:
            base_price = product.base_price * (1 - base_offer.discount_percent / 100)
        elif base_offer.discount_rs:
            base_price = product.base_price - base_offer.discount_rs
        else:
            base_price = product.base_price
    else:
        # Fallback: use product.discount_price if set, else product.base_price
        base_price = product.discount_price if product.discount_price else product.base_price
    # --- CHANGE END ---

    # Now apply extra offer as before ...
    extra_offer = product.offers.filter(
        start_date__lte=today, end_date__gte=today, is_extra=True
    ).last()
    if extra_offer:
        if extra_offer.discount_percent:
            final_price = base_price * (1 - extra_offer.discount_percent / 100)
        elif extra_offer.discount_rs:
            final_price = base_price - extra_offer.discount_rs
        else:
            final_price = base_price
    else:
        final_price = base_price

    return max(final_price, 0)


def get_discount_percentage(product):
    mrp = product.base_price
    sale = get_final_discounted_price(product)
    try:
        percent = round((mrp - sale) / mrp * 100)
        return max(percent, 0)
    except ZeroDivisionError:
        return 0



from django.http import JsonResponse
from django.views.decorators.http import require_POST
from datetime import date, timedelta
from coupons.models import DeliveryPincode

@require_POST
def check_pincode_delivery(request):
    """Check delivery availability and estimate for a pincode"""
    pincode = request.POST.get('pincode', '').strip()
    
    if not pincode or len(pincode) != 6:
        return JsonResponse({
            'success': False,
            'message': 'Please enter a valid 6-digit pincode'
        })
    
    try:
        delivery_info = DeliveryPincode.objects.get(pincode=pincode)
        
        if not delivery_info.is_serviceable:
            return JsonResponse({
                'success': False,
                'message': f'Sorry, we don\'t deliver to {pincode} yet.',
                'serviceable': False
            })
        
        # Calculate delivery date
        today = date.today()
        delivery_date = today + timedelta(days=delivery_info.delivery_days)
        delivery_date_str = delivery_date.strftime('%A, %d %B')  # "Friday, 29 August"
        
        return JsonResponse({
            'success': True,
            'serviceable': True,
            'delivery_date': delivery_date_str,
            'delivery_days': delivery_info.delivery_days,
            'city': delivery_info.city,
            'state': delivery_info.state,
            'cod_available': delivery_info.is_cod_available,
            'message': f'Delivery by {delivery_date_str}'
        })
        
    except DeliveryPincode.DoesNotExist:
        return JsonResponse({
            'success': False,
            'serviceable': False,
            'message': f'Pincode {pincode} is not serviceable yet.'
        })
