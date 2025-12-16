from django.contrib import admin
from .models import ReferralProfile, Referral, ReferralConfig

@admin.register(ReferralProfile)
class ReferralProfileAdmin(admin.ModelAdmin):
    list_display = ("user","code","total_referrals","lifetime_earnings")
    search_fields = ("user__username","user__email","code")

@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = ("referrer","referee","status","reward_amount","created_at","converted_at")
    list_filter = ("status",)
    search_fields = ("referrer__username","referee__username","code_used")

@admin.register(ReferralConfig)
class ReferralConfigAdmin(admin.ModelAdmin):
    list_display = ("active",'signup_reward',"purchase_reward","min_order_amount","monthly_cap")
