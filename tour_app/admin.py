from django.contrib import admin
from .models import TouristPlace, CrowdStatus, UserPreference, Recommendation

@admin.register(TouristPlace)
class TouristPlaceAdmin(admin.ModelAdmin):
    list_display = ('place_name', 'location', 'best_season')
    search_fields = ('place_name', 'location')

admin.site.register(CrowdStatus)
admin.site.register(UserPreference)
admin.site.register(Recommendation)

# Register your models here.
