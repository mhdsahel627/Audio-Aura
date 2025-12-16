from django import template

register = template.Library()

@register.filter
def video_url(url):
    """Convert Cloudinary image URL to video URL"""
    if url and '/image/upload/' in url:
        return url.replace('/image/upload/', '/video/upload/')
    return url
