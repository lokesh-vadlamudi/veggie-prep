"""URL routes for the authenticated inventory workflow (namespace: inventory)."""

from django.contrib.auth import views as auth_views
from django.urls import path

from . import meal_views, views

app_name = "inventory"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("add/", views.AddStockView.as_view(), name="add"),
    path("lots/<uuid:pk>/", views.lot_detail, name="lot_detail"),
    path("lots/<uuid:pk>/consume/", views.ConsumeView.as_view(), name="consume"),
    path("lots/<uuid:pk>/discard/", views.DiscardView.as_view(), name="discard"),
    path("lots/<uuid:pk>/correct/", views.CorrectView.as_view(), name="correct"),
    path("meals/", meal_views.SuggestionFormView.as_view(), name="meal_suggest"),
    path("meals/history/", meal_views.SuggestionHistoryView.as_view(), name="meal_history"),
    path("meals/<uuid:pk>/", meal_views.suggestion_detail, name="meal_detail"),
    path(
        "meals/<uuid:pk>/cook/",
        meal_views.CookSuggestionView.as_view(),
        name="meal_cook",
    ),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path(
        "logout/",
        auth_views.LogoutView.as_view(next_page="inventory:login"),
        name="logout",
    ),
]
