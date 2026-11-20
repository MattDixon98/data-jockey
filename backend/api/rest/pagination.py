from django.conf import settings
from rest_framework.pagination import LimitOffsetPagination


class Pagination(LimitOffsetPagination):
  """?limit=&offset=, with the same default and cap as the GraphQL lists."""
  default_limit = settings.API_PAGE_SIZE
  max_limit = settings.API_MAX_PAGE_SIZE
