from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("keys/", views.APIKeyListCreateView.as_view(), name="apikey-list-create"),
    path("keys/<uuid:key_id>/revoke/", views.APIKeyRevokeView.as_view(), name="apikey-revoke"),
    path("health/live/", views.LivenessView.as_view(), name="health-live"),
    path("health/ready/", views.ReadinessView.as_view(), name="health-ready"),
]
