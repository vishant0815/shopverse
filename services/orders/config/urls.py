from django.http import JsonResponse
from django.urls import include, path


def health(request):
    return JsonResponse({"status": "ok", "service": "orders"})


urlpatterns = [
    path("health/", health, name="health"),
    path("api/v1/", include("ordering.urls")),
]
