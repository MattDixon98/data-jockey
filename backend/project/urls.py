from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("graphql_api.urls")),
    path("", include("app.urls")),
]
