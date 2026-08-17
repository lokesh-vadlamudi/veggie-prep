"""Root URL configuration for Veggie Prep."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("inventory.urls")),
]
