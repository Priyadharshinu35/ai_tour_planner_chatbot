"""
URL configuration for ai_tour_planner project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.views.generic import RedirectView

def root_redirect(request):
    # Site open panna direct login page
    return redirect("/api/login/")

urlpatterns = [
    path("", root_redirect),
    path("admin/", admin.site.urls),     # Django default admin (optional)
    path("api/", include("tour_app.urls")),
   
    path("", RedirectView.as_view(url="/api/login/")),
]



