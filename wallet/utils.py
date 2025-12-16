# wallet/utils.py
from django.urls import reverse

def build_ref_link(request, code: str) -> str:
    """
    Returns an absolute signup URL with the referral code appended.
    Example: https://example.com/signup/?ref=ABCD1234
    """
    base = request.build_absolute_uri("/").rstrip("/")   # https://host
    signup_path = reverse("signup")                      # urlpattern name for your signup page
    return f"{base}{signup_path}?ref={code}"
