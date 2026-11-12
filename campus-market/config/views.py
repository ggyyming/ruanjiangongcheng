from django.http import JsonResponse


def health(request):
    """Return a lightweight response for local and deployment checks."""
    return JsonResponse({"status": "ok"})
