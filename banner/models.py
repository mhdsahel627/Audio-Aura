from django.db import models
from django.utils import timezone
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError
from .storage import VideoCloudinaryStorage  # Add this import


# Keep your existing validators
def validate_video_size(file):
    """Validate video file size - max 10MB for Cloudinary free tier"""
    max_size_mb = 10
    if file.size > max_size_mb * 1024 * 1024:
        raise ValidationError(f'Video file size cannot exceed {max_size_mb}MB')


def validate_image_size(file):
    """Validate image file size - max 10MB"""
    max_size_mb = 10
    if file.size > max_size_mb * 1024 * 1024:
        raise ValidationError(f'Image file size cannot exceed {max_size_mb}MB')


class Banner(models.Model):
    """Main Banner Carousel - supports both image and video"""
    MEDIA_TYPE_CHOICES = [
        ('image', 'Image'),
        ('video', 'Video'),
    ]
    
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    media_type = models.CharField(max_length=10, choices=MEDIA_TYPE_CHOICES, default='image')
    
    # Image with size validation (max 10MB)
    image = models.ImageField(
        upload_to="banners/images/", 
        blank=True, 
        null=True,
        validators=[validate_image_size]
    )
    
    # Video with custom storage (max 10MB)
    video = models.FileField(
        upload_to="banners/videos/", 
        blank=True, 
        null=True,
        storage=VideoCloudinaryStorage(),  # ← Add this line
        validators=[
            FileExtensionValidator(allowed_extensions=['mp4', 'webm', 'ogg']),
            validate_video_size
        ]
    )
    
    link_url = models.URLField(max_length=300, blank=True, help_text="Where to redirect on click")
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)
    priority = models.PositiveIntegerField(default=1, help_text="Lower number = higher priority")
    created_at = models.DateTimeField(auto_now_add=True)


    class Meta:
        ordering = ['priority', '-created_at']


    def __str__(self):
        return self.title


    @property
    def days_left(self):
        today = timezone.now().date()
        if self.end_date and self.end_date >= today:
            return (self.end_date - today).days
        return 0


    @property
    def media_url(self):
        """Returns the appropriate media URL based on type"""
        if self.media_type == 'video' and self.video:
            return self.video.url
        elif self.media_type == 'image' and self.image:
            return self.image.url
        return None


    def clean(self):
        """Validate that appropriate media is provided based on media_type"""
        if self.media_type == 'image' and not self.image:
            raise ValidationError("Image is required when media type is Image")
        if self.media_type == 'video' and not self.video:
            raise ValidationError("Video is required when media type is Video")




class DealOfMonth(models.Model):
    """Limited Time Deal - supports up to 6 images"""
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    cta_text = models.CharField(max_length=30, default="Buy Now")
    cta_url = models.URLField(max_length=300)
    
    starts_on = models.DateTimeField()
    ends_on = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    priority = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['priority', '-created_at']
        verbose_name = "Deal of the Month"
        verbose_name_plural = "Deals of the Month"

    def __str__(self):
        return self.title

    @property
    def days_left(self):
        today = timezone.now()
        if self.ends_on and self.ends_on >= today:
            delta = self.ends_on - today
            return delta.days
        return 0

    @property
    def hours_left(self):
        today = timezone.now()
        if self.ends_on and self.ends_on >= today:
            delta = self.ends_on - today
            return delta.seconds // 3600
        return 0


class DealImage(models.Model):
    """Images for Deal of Month - max 6 per deal"""
    deal = models.ForeignKey(DealOfMonth, related_name='images', on_delete=models.CASCADE)
    image = models.ImageField(upload_to="deals/")
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'created_at']

    def __str__(self):
        return f"{self.deal.title} - Image {self.order}"


class FeaturedProduct(models.Model):
    """Featured Product Showcase - one image per product"""
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="featured_products/")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    link_url = models.URLField(max_length=300, help_text="Product detail page URL")
    is_active = models.BooleanField(default=True)
    priority = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['priority', '-created_at']

    def __str__(self):
        return self.title

    @property
    def formatted_price(self):
        return f"₹{self.price:,.0f}"
