from django.urls import include, path

urlpatterns = [
  path("graphql/", include("api.graphql.urls")),
]
