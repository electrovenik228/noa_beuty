from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from .middleware import AdminGateMiddleware


class AdminGateMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, path):
        request = self.factory.get(path)
        request.session = {}
        return request

    def test_redirects_only_admin_index_to_gate(self):
        middleware = AdminGateMiddleware(lambda request: HttpResponse("ok"))

        response = middleware(self._request("/admin/"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/admin-gate/?next=%2Fadmin%2F")

    def test_does_not_gate_deeper_admin_urls(self):
        middleware = AdminGateMiddleware(lambda request: HttpResponse("ok"))

        response = middleware(self._request("/admin/sales/sale/add/"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")
