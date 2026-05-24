from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('admin-gate/', views.admin_gate, name='admin_gate'),
]
