import time
from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class AdminGateMiddleware:
    """Adds a lightweight shared-computer password gate before Django admin."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/admin/"):
            if request.path.startswith("/admin/logout/"):
                request.session.pop("admin_gate_grace_until", None)
            elif not self._has_admin_gate_access(request):
                query = urlencode({"next": request.get_full_path()})
                return redirect(f"{reverse('admin_gate')}?{query}")

        return self.get_response(request)

    def _has_admin_gate_access(self, request):
        try:
            gate_until = float(request.session.get("admin_gate_grace_until", 0))
        except (TypeError, ValueError):
            gate_until = 0

        if gate_until <= time.time():
            request.session.pop("admin_gate_grace_until", None)
            return False

        return True
