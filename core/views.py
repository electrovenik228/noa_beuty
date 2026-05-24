import time

from django.conf import settings
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache

def home(request):
    return render(request, 'core/home.html')


@never_cache
def admin_gate(request):
    next_url = request.GET.get("next") or request.POST.get("next") or reverse("admin:index")
    error = None

    if request.method == "POST":
        password = request.POST.get("password", "")
        if password == settings.ADMIN_GATE_PASSWORD:
            request.session["admin_gate_grace_until"] = time.time() + settings.ADMIN_GATE_GRACE_SECONDS
            return redirect(next_url)
        error = "Неверный пароль"

    return render(
        request,
        "core/admin_gate.html",
        {
            "next": next_url,
            "error": error,
            "grace_seconds": settings.ADMIN_GATE_GRACE_SECONDS,
        },
    )
