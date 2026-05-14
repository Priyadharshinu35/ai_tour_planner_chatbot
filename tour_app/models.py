from django.db import models
from django.contrib.auth.models import User


# ---------------- Tourist Places ----------------
class TouristPlace(models.Model):
    place_name = models.CharField(max_length=100)
    location = models.CharField(max_length=100)
    description = models.TextField()
    best_season = models.CharField(max_length=50)

    # extra fields
    image_url = models.URLField(blank=True, null=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)

    def __str__(self):
        return self.place_name


# ---------------- User Preferences ----------------
class UserPreference(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    travel_type = models.CharField(max_length=50)   # Solo / Family / Friends
    budget = models.CharField(max_length=50)        # Low / Medium / High
    season = models.CharField(max_length=50)

    def __str__(self):
        return self.user.username


# ---------------- Recommendations ----------------
class Recommendation(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    place = models.ForeignKey(TouristPlace, on_delete=models.CASCADE)
    recommendation_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.place.place_name}"


# ---------------- Crowd Status ----------------
class CrowdStatus(models.Model):

    CROWD_CHOICES = [
        ('Low', 'Low'),
        ('Medium', 'Medium'),
        ('High', 'High'),
    ]

    place = models.OneToOneField(TouristPlace, on_delete=models.CASCADE)
    crowd_level = models.CharField(max_length=10, choices=CROWD_CHOICES)
    remarks = models.CharField(max_length=200, blank=True)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.place.place_name} - {self.crowd_level}"


# ---------------- Chat History ----------------
class ChatHistory(models.Model):

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField()
    response = models.TextField()
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.message[:40]}"