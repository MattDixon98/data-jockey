from django.urls import include, path

urlpatterns = [
  path("graphql/", include("api.graphql.urls")),
  path("api/v1/", include("api.rest.urls")),
]
