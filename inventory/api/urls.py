"""API v1 URL routes for the inventory and meal endpoints (namespace: api)."""

from django.urls import path

from .views import (
    LotConsumeView,
    LotCorrectView,
    LotDiscardView,
    LotEventsView,
    LotViewSet,
    MealCookView,
    MealDetailView,
    MealGenerateView,
    MealListView,
)

app_name = "api"

urlpatterns = [
    path("inventory/lots/", LotViewSet.as_view({"get": "list", "post": "create"}), name="lots_list"),
    path(
        "inventory/lots/<uuid:pk>/",
        LotViewSet.as_view({"get": "retrieve"}),
        name="lot_detail",
    ),
    path(
        "inventory/lots/<uuid:pk>/events/",
        LotEventsView.as_view({"get": "list"}),
        name="lot_events",
    ),
    path(
        "inventory/lots/<uuid:pk>/consume/",
        LotConsumeView.as_view({"post": "post"}),
        name="lot_consume",
    ),
    path(
        "inventory/lots/<uuid:pk>/discard/",
        LotDiscardView.as_view({"post": "post"}),
        name="lot_discard",
    ),
    path(
        "inventory/lots/<uuid:pk>/correct/",
        LotCorrectView.as_view({"post": "post"}),
        name="lot_correct",
    ),
    path("meals/", MealListView.as_view({"get": "list"}), name="meals_list"),
    path(
        "meals/generate/",
        MealGenerateView.as_view({"post": "post"}),
        name="meal_generate",
    ),
    path(
        "meals/<uuid:pk>/",
        MealDetailView.as_view({"get": "retrieve"}),
        name="meal_detail",
    ),
    path(
        "meals/<uuid:pk>/cook/",
        MealCookView.as_view({"post": "post"}),
        name="meal_cook",
    ),
]
