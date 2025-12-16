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

@admin_required  # Decorator: restricts access to admin/staff users only.
def add_category(request):
    """
    Handle adding a new product category from the admin panel.

    Behavior:
    - Accepts only POST requests containing category name, description, and image.
    - Validates that the category name is provided and not duplicated.
    - Creates a new Category object if validation passes.
    - Returns success or error messages using Django's messages framework.
    - On GET, renders the category creation form template.

    Security and UX Notes:
    - Protected by @admin_required to ensure only admin/staff can add categories.
    - Uses `request.FILES` to properly handle uploaded image files.
    - Uses `messages` to provide user-friendly feedback.
    - Redirects after form submission to prevent duplicate submissions on refresh.
    """

    # Check if the request is a POST (form submission)
    if request.method == "POST":
        # Extract the name field from form data and remove leading/trailing spaces
        name = request.POST.get('name').strip()

        # Extract description from form data (can be optional)
        description = request.POST.get('description')

        # Extract uploaded image file from FILES dictionary
        image = request.FILES.get('image')  # 🔹 Handles image uploads safely

        # Validate that name is not empty
        if not name:
            messages.error(request, "Category name is required!")  # Show error message
            return redirect('add_catogery')  # Redirect back to the add form
        if not image:
            messages.error(request,'Images is required!')

        # 🔹 Check for duplicate category name (case-insensitive)
        if Category.objects.filter(name__iexact=name).exists():
            # Send user-friendly duplicate name message
            messages.error(request, f"Category '{name}' already exists!")
            return redirect('add_catogery')

        # 🔹 Create and save new Category record
        Category.objects.create(
            name=name,
            description=description,
            image=image
        )

        # Show success feedback message
        messages.success(request, "Category added successfully!")

        # Redirect to category listing page after successful creation
        return redirect('catogery')

    # If GET request, render the category addition form template
    return render(request, 'admin/category_add.html')


""" ........................Category..................................... """
@user_passes_test(is_admin, login_url='admin_login')
@login_required(login_url='admin_login')
@never_cache
def catogery(request):
    categories = Category.objects.all().order_by('-id')
    return render(request, 'admin/catogery.html', {'categories': categories})

 

""" .......................................................Edit Category..................................... """
@user_passes_test(is_admin, login_url='admin_login')
@login_required(login_url='admin_login')
@never_cache
@staff_required  # Ensures that only staff/admin users can access this view
@require_http_methods(["GET", "POST"])  # Restrict HTTP methods to GET and POST for safety
def category_edit(request, pk):
    """
    Handle editing an existing category in the admin panel.

    Behavior:
    - Fetches the category by primary key (pk) or returns 404 if not found.
    - On GET: renders the category edit form with current data.
    - On POST: validates input, updates fields, optionally updates the image, saves changes.
    - Provides feedback using Django messages framework.
    - Redirects to category listing page after successful update.

    Security and UX Notes:
    - Protected by @staff_required to prevent unauthorized access.
    - Only allows GET and POST methods.
    - Image upload is optional; existing image is preserved if no new file is provided.
    - Uses `messages` to display user-friendly success/error messages.
    """

    # Fetch the category object or raise 404 if it doesn't exist
    cat = get_object_or_404(Category, pk=pk)

    # Handle form submission
    if request.method == "POST":
        # Extract and clean name and description from form data
        name = request.POST.get("name", "").strip()
        desc = request.POST.get("description", "").strip()

        # Extract uploaded image if provided; None if not
        img = request.FILES.get("image", None)

        # Validate that name is not empty
        if not name:
            messages.error(request, "Name is required.")  # Show error message
            # Re-render edit form with current category data
            return render(request, "admin/category_edit.html", {"cat": cat})

        # 🔹 Update category fields
        cat.name = name
        cat.description = desc

        # Replace image only if a new one was uploaded
        if img:
            cat.image = img

        # Save the updated category object to the database
        cat.save()

        # Show success feedback to the user
        messages.success(request, "Category updated successfully.")

        # Redirect back to category listing page
        return redirect("catogery")

    # For GET requests, render the edit form with current category data
    return render(request, "admin/category_edit.html", {"cat": cat})



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

@csrf_exempt
def add_category_offer(request):
    if request.method == "POST":
        category_id = request.POST.get('category_id')
        title = request.POST.get('title')
        discount_percent = request.POST.get('discount_percent') or None
        discount_rs = request.POST.get('discount_rs') or None
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        if category_id and title and start_date and end_date:
            CategoryOffer.objects.create(
                category_id=category_id,
                title=title,
                discount_percent=discount_percent,
                discount_rs=discount_rs,
                start_date=start_date,
                end_date=end_date,
            )
            return JsonResponse({'success': True})
    return JsonResponse({'success': False})

@csrf_exempt
def edit_category_offer(request, offer_id):
    offer = get_object_or_404(CategoryOffer, id=offer_id)
    if request.method == "POST":
        offer.title = request.POST.get('title', offer.title)
        offer.discount_percent = request.POST.get('discount_percent') or None
        offer.discount_rs = request.POST.get('discount_rs') or None
        offer.start_date = request.POST.get('start_date', offer.start_date)
        offer.end_date = request.POST.get('end_date', offer.end_date)
        offer.save()
        return JsonResponse({'success': True})
    else:
        return JsonResponse({
            'category_id': offer.category_id,
            'title': offer.title,
            'discount_percent': offer.discount_percent,
            'discount_rs': offer.discount_rs,
            'start_date': offer.start_date,
            'end_date': offer.end_date,
        })

@csrf_exempt
def delete_category_offer(request, offer_id):
    offer = get_object_or_404(CategoryOffer, id=offer_id)
    offer.delete()
    return JsonResponse({'success': True})