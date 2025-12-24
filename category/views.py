from django.contrib import messages
from django.shortcuts import render, redirect,get_object_or_404
from .models import Category
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.cache import never_cache
from django.http import JsonResponse
from functools import wraps
from .models import Brand
from products.models import Product
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import user_passes_test, login_required
import json
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from .models import Category, CategoryOffer
from django.views.decorators.csrf import csrf_exempt
from admin_side.views import is_admin
from django.utils import timezone
from datetime import datetime
from decimal import Decimal, InvalidOperation
from django.contrib.admin.views.decorators import staff_member_required
from PIL import Image
import re



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



def staff_required(view):
    return user_passes_test(lambda u: u.is_authenticated and u.is_staff)(view)

""" .......................................................Add Brand (AJAX)..................................... """

@admin_required  # Decorator: Ensures only authenticated admin users can access this endpoint.
def add_brand_ajax(request):
    """
    Handle AJAX-based brand creation for the admin panel.

    Behavior:
    - Accepts POST requests with JSON data containing a 'name' field for the new brand.
    - Validates that the brand name is not empty.
    - If valid, creates or retrieves the Brand record using `get_or_create`.
    - Returns a JSON response with success status, brand ID, and name.
    - If invalid or method is not POST, returns a JSON error response.

    Security and Notes:
    - Protected by @admin_required: only admin/staff users can invoke this view.
    - Uses `JsonResponse` for lightweight AJAX communication.
    - `get_or_create` ensures idempotency (no duplicate brands are created if the same name exists).
    - All string inputs are stripped to prevent leading/trailing whitespace issues.
    """

    # Only allow POST requests (AJAX calls from admin dashboard)
    if request.method == "POST":
        import json  # Import inside function for localized use (optional best practice)

        # Parse raw JSON body data from the request
        data = json.loads(request.body)

        # Extract the brand name from parsed data, defaulting to empty string
        brand_name = data.get("name", "").strip()

        # Validate that brand name is provided
        if not brand_name:
            # Respond with error if brand name is missing
            return JsonResponse({"success": False, "message": "Brand name required"})

        # Create or fetch existing brand object based on name
        brand, created = Brand.objects.get_or_create(name=brand_name)

        # Return success response with the brand details
        return JsonResponse({
            "success": True,
            "id": brand.id,
            "name": brand.name
        })

    # For non-POST requests, return an error JSON response
    return JsonResponse({"success": False, "message": "Invalid request"})


'''
CATEGORY
'''

""" .......................................................Add Category..................................... """
@admin_required
@never_cache
def add_category(request):
    """Add category with validation"""
    
    errors = {}
    form_data = {}
    
    if request.method == "POST":
        name = (request.POST.get('name') or '').strip()
        description = (request.POST.get('description') or '').strip()
        image = request.FILES.get('image')
        
        form_data = {
            'name': name,
            'description': description,
        }
        
        # === VALIDATION ===
        
        # 1. Name Validation
        if not name:
            errors['name'] = 'Category name is required'
        elif len(name) < 2:
            errors['name'] = 'Category name must be at least 2 characters'
        elif len(name) > 255:
            errors['name'] = 'Category name cannot exceed 255 characters'
        elif not re.match(r'^[a-zA-Z0-9\s\-&]+$', name):
            errors['name'] = 'Category name can only contain letters, numbers, spaces, hyphens, and ampersands'
        elif Category.objects.filter(name__iexact=name).exists():
            errors['name'] = f'Category "{name}" already exists'
        
        # 2. Description Validation (optional)
        if description:
            if len(description) < 10:
                errors['description'] = 'Description must be at least 10 characters if provided'
            elif len(description) > 500:
                errors['description'] = 'Description cannot exceed 500 characters'
        
        # 3. Image Validation (required)
        if not image:
            errors['image'] = 'Category image is required'
        else:
            max_size = 5 * 1024 * 1024  # 5MB
            if image.size > max_size:
                errors['image'] = f'Image size must be less than 5MB (current: {image.size / 1024 / 1024:.1f}MB)'
            
            allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
            if image.content_type not in allowed_types:
                errors['image'] = 'Only JPG, PNG, and WebP images are allowed'
            
            try:
                from PIL import Image as PILImage
                img = PILImage.open(image)
                width, height = img.size
                
                min_width = 200
                min_height = 200
                
                if width < min_width or height < min_height:
                    errors['image'] = f'Image must be at least {min_width}x{min_height}px (current: {width}x{height}px)'
                
                image.seek(0)
            except Exception as e:
                errors['image'] = 'Invalid image file'
        
        # If errors, show them
        if errors:
            for field, error in errors.items():
                messages.error(request, f"{field.replace('_', ' ').title()}: {error}")
            
            return render(request, 'admin/category_add.html', {
                'errors': errors,
                'form_data': form_data,
            })
        
        # === SAVE CATEGORY ===
        try:
            # 🔥 FIX: Use 'image' not 'header_image'
            Category.objects.create(
                name=name,
                description=description,
                image=image  # ← Correct field name
            )
            messages.success(request, f'✅ Category "{name}" added successfully!')
            return redirect('catogery')
        
        except Exception as e:
            messages.error(request, f'❌ Failed to add category: {str(e)}')
            return render(request, 'admin/category_add.html', {
                'errors': errors,
                'form_data': form_data,
            })
    
    return render(request, 'admin/category_add.html')


@admin_required
@never_cache
@require_http_methods(["GET", "POST"])
def category_edit(request, pk):
    """Edit category with validation"""
    
    cat = get_object_or_404(Category, pk=pk)
    errors = {}
    
    if request.method == "POST":
        name = (request.POST.get('name') or '').strip()
        description = (request.POST.get('description') or '').strip()
        image = request.FILES.get('image')
        
        # === VALIDATION ===
        
        # 1. Name Validation
        if not name:
            errors['name'] = 'Category name is required'
        elif len(name) < 2:
            errors['name'] = 'Category name must be at least 2 characters'
        elif len(name) > 255:
            errors['name'] = 'Category name cannot exceed 255 characters'
        elif not re.match(r'^[a-zA-Z0-9\s\-&]+$', name):
            errors['name'] = 'Category name can only contain letters, numbers, spaces, hyphens, and ampersands'
        elif Category.objects.filter(name__iexact=name).exclude(pk=pk).exists():
            errors['name'] = f'Category "{name}" already exists'
        
        # 2. Description Validation
        if description:
            if len(description) < 10:
                errors['description'] = 'Description must be at least 10 characters if provided'
            elif len(description) > 500:
                errors['description'] = 'Description cannot exceed 500 characters'
        
        # 3. Image Validation (optional on edit)
        if image:
            max_size = 5 * 1024 * 1024  # 5MB
            if image.size > max_size:
                errors['image'] = f'Image size must be less than 5MB (current: {image.size / 1024 / 1024:.1f}MB)'
            
            allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
            if image.content_type not in allowed_types:
                errors['image'] = 'Only JPG, PNG, and WebP images are allowed'
            
            try:
                from PIL import Image as PILImage
                img = PILImage.open(image)
                width, height = img.size
                
                min_width = 200
                min_height = 200
                
                if width < min_width or height < min_height:
                    errors['image'] = f'Image must be at least {min_width}x{min_height}px (current: {width}x{height}px)'
                
                image.seek(0)
            except Exception as e:
                errors['image'] = 'Invalid image file'
        
        # If errors, show them
        if errors:
            for field, error in errors.items():
                messages.error(request, f"{field.replace('_', ' ').title()}: {error}")
            
            return render(request, 'admin/category_edit.html', {
                'cat': cat,
                'errors': errors,
            })
        
        # === UPDATE CATEGORY ===
        try:
            cat.name = name
            cat.description = description
            
            # 🔥 FIX: Use 'image' not 'header_image'
            if image:
                cat.image = image  # ← Correct field name
            
            cat.save()
            messages.success(request, f'✅ Category "{name}" updated successfully!')
            return redirect('catogery')
        
        except Exception as e:
            messages.error(request, f'❌ Failed to update category: {str(e)}')
    
    return render(request, 'admin/category_edit.html', {'cat': cat})



@admin_required
@never_cache
def catogery(request):
    """List all categories"""
    categories = Category.objects.all().order_by('-id')
    return render(request, 'admin/catogery.html', {'categories': categories})






""" .......................................................Toggle Category Active Status..................................... """

@never_cache  # Prevent caching to avoid stale responses for AJAX requests
@admin_required  # Ensure only admin/staff users can toggle category status
def toggle_category(request, id):
    """
    Toggle the 'is_active' status of a category via AJAX.

    Behavior:
    - Accepts only POST requests with a category ID.
    - Fetches the category or raises 404 if it does not exist.
    - Switches the 'is_active' boolean field to its opposite.
    - Saves the updated category and returns a JSON success response with new status.
    - Returns a JSON failure response if method is not POST.

    Security and UX Notes:
    - Protected with @admin_required to prevent unauthorized access.
    - Uses @never_cache to ensure clients always get the current status.
    - Designed for AJAX updates in admin UI, avoiding full page reloads.
    """

    # Only allow POST requests for this toggle operation
    if request.method == 'POST':
        # Fetch the category object by ID or return 404
        category = get_object_or_404(Category, id=id)

        # Toggle the is_active boolean field
        category.is_active = not category.is_active

        # Save the change to the database
        category.save()

        # Return JSON response with success status and updated field
        return JsonResponse({'success': True, 'is_active': category.is_active})

    # Return failure JSON response for non-POST requests
    return JsonResponse({'success': False})



""" .......................................................View Product Variants..................................... """
@user_passes_test(is_admin, login_url='admin_login')
@login_required(login_url='admin_login')
@never_cache
@never_cache  # Prevent caching to ensure always fresh variant data
@admin_required  # Ensure only admin/staff users can access product variants
def view_variants(request, product_id):
    """
    Display all variants for a specific product in the admin panel.

    Behavior:
    - Fetches the product by ID or returns 404 if not found.
    - Retrieves all associated variants via the related_name 'variants'.
    - Renders the 'view_variants.html' template with product and variants context.

    Security and UX Notes:
    - Protected with @admin_required to restrict access to authorized users.
    - @never_cache ensures the page always shows the latest variant data.
    - Assumes the Product model has a related_name='variants' for its variants.
    """

    # Fetch the product by ID or raise 404 if it doesn't exist
    product = get_object_or_404(Product, id=product_id)

    # Retrieve all variant objects related to this product
    variants = product.variants.all()  # 🔹 related_name='variants' must exist in model

    # Render the admin template with product and its variants
    return render(request, 'admin/view_variants.html', {
        'product': product,    # Product object to display info
        'variants': variants,  # List of all associated variants
    })


""" .......................................................Category Offer Add Edit Delete..................................... """
@staff_member_required
@require_http_methods(["POST"])
def add_category_offer(request):
    """Add category offer with percentage discount only"""
    
    category_id = request.POST.get('category_id')
    title = request.POST.get('title', '').strip()
    discount_percent = request.POST.get('discount_percent', '').strip()
    start_date_str = request.POST.get('start_date')
    end_date_str = request.POST.get('end_date')
    
    errors = {}
    
    # 1. Category validation
    if not category_id:
        return JsonResponse({
            'success': False,
            'message': 'Category ID is required'
        }, status=400)
    
    try:
        category = Category.objects.get(id=category_id, is_active=True)
    except Category.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Category not found or inactive'
        }, status=404)
    
    # 2. Title validation
    if not title:
        errors['offer_title'] = 'Offer title is required'
    elif len(title) < 3:
        errors['offer_title'] = 'Title must be at least 3 characters'
    elif len(title) > 100:
        errors['offer_title'] = 'Title cannot exceed 100 characters'
    
    # 3. Discount percentage validation
    if not discount_percent:
        errors['discount_percent'] = 'Discount percentage is required'
    else:
        try:
            discount_percent = Decimal(discount_percent)
            if discount_percent <= 0:
                errors['discount_percent'] = 'Percentage must be greater than 0'
            elif discount_percent > 100:
                errors['discount_percent'] = 'Percentage cannot exceed 100%'
        except (ValueError, InvalidOperation):
            errors['discount_percent'] = 'Invalid percentage value'
    
    # 4. Date validation
    if not start_date_str:
        errors['start_date'] = 'Start date is required'
    if not end_date_str:
        errors['end_date'] = 'End date is required'
    
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            today = timezone.now().date()
            
            if start_date < today:
                errors['start_date'] = 'Start date cannot be in the past'
            
            if end_date < start_date:
                errors['end_date'] = 'End date must be after start date'
            elif end_date == start_date:
                errors['end_date'] = 'Offer must be at least 1 day long'
            
            duration = (end_date - start_date).days
            if duration > 365:
                errors['end_date'] = 'Offer duration cannot exceed 1 year'
            
        except (ValueError, TypeError):
            errors['start_date'] = 'Invalid date format'
    
    # 5. Check for overlapping offers
    if not errors and start_date_str and end_date_str:
        overlapping = CategoryOffer.objects.filter(
            category=category,
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
        offer = CategoryOffer.objects.create(
            category=category,
            title=title,
            discount_percent=discount_percent,
            discount_rs=None,  # Always None
            start_date=start_date,
            end_date=end_date,
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Category offer "{title}" ({discount_percent}% off) added successfully!',
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
def edit_category_offer(request, offer_id):
    """Edit category offer - percentage only"""
    
    offer = get_object_or_404(CategoryOffer, id=offer_id)
    
    if request.method == "GET":
        return JsonResponse({
            'success': True,
            'category_id': offer.category_id,
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
        errors['offer_title'] = 'Title must be at least 3 characters'
    
    if not discount_percent:
        errors['discount_percent'] = 'Discount percentage is required'
    else:
        try:
            discount_percent = Decimal(discount_percent)
            if discount_percent <= 0 or discount_percent > 100:
                errors['discount_percent'] = 'Percentage must be between 0 and 100'
        except (ValueError, InvalidOperation):
            errors['discount_percent'] = 'Invalid percentage value'
    
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            if end_date <= start_date:
                errors['end_date'] = 'End date must be after start date'
            
            # Check overlapping (exclude current offer)
            overlapping = CategoryOffer.objects.filter(
                category=offer.category,
                start_date__lte=end_date,
                end_date__gte=start_date
            ).exclude(id=offer_id).exists()
            
            if overlapping:
                errors['general'] = 'Another offer exists for this period'
                
        except (ValueError, TypeError):
            errors['start_date'] = 'Invalid date format'
    
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
            'message': f'Category offer "{title}" updated successfully!'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'Failed to update: {str(e)}'
        }, status=500)


@staff_member_required
@require_http_methods(["POST"])
def delete_category_offer(request, offer_id):
    """Delete category offer"""
    
    offer = get_object_or_404(CategoryOffer, id=offer_id)
    
    try:
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