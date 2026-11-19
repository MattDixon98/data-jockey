from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from strawberry.django.views import GraphQLView

from .schema import schema

urlpatterns = [
  # Read-only and cookie-free, so CSRF protection has nothing to protect; a JS
  # client on another origin can POST queries without a token.
  path("graphql/", csrf_exempt(GraphQLView.as_view(schema=schema)), name="graphql"),
]
