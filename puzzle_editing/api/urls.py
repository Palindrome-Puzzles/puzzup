from django.urls import include
from django.urls import path
from rest_framework import routers

from .viewsets import PuzzleViewSet, UserViewSet

# from django.contrib.auth.models import User

# Routers provide an easy way of automatically determining the URL conf.
router = routers.DefaultRouter()
router.register(r"users", UserViewSet)
router.register(r"puzzles", PuzzleViewSet)

# Wire up our API using automatic URL routing.
# Additionally, we include login URLs for the browsable API.
urlpatterns = [
    path("", include(router.urls)),
    path("api-auth/", include("rest_framework.urls", namespace="rest_framework")),
]
