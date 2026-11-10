from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("healthcheck/", views.healthcheck, name="healthcheck"),
]
