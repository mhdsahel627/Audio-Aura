from django import template

register = template.Library()

@register.filter
def chunk_images(images, chunk_size=2):
    """Split images into chunks of specified size"""
    images_list = list(images)
    return [images_list[i:i + chunk_size] for i in range(0, len(images_list), chunk_size)]
