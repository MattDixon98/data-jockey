"""HTTP caching for the REST API.

The data only changes when a new snapshot is swapped in (once a day), so every
response is cacheable and its validator is the snapshot's built_at: the ETag is
built_at plus the response format (JSON or the browsable HTML). A client or CDN
that sends it back in If-None-Match gets a 304 before any racing query runs, and
max-age is kept short (settings.API_CACHE_MAX_AGE) so a new snapshot shows up
within minutes, after which the old ETags stop matching.
"""

from __future__ import annotations

from django.conf import settings
from django.utils.cache import patch_cache_control, patch_vary_headers
from django.utils.http import parse_etags
from rest_framework.response import Response

from api import queries

CACHEABLE_STATUSES = (200, 304)


class _NotModified(Exception):
  pass


def snapshot_etag(format_name: str) -> str | None:
  info = queries.snapshot_info()
  if info is None:
    return None
  return f'W/"{int(info.built_at.timestamp())}-{format_name}"'


def _matches(if_none_match: str | None, etag: str) -> bool:
  """If-None-Match uses the weak comparison: W/ is ignored on both sides."""
  if not if_none_match:
    return False
  if if_none_match.strip() == "*":
    return True
  opaque = etag.removeprefix("W/")
  return any(tag.removeprefix("W/") == opaque for tag in parse_etags(if_none_match))


class SnapshotCachingMixin:
  """For DRF views: ETag + Cache-Control on successful GETs, 304 when the client already has this snapshot's response."""
  etag = None

  def initial(self, request, *args, **kwargs):
    # After content negotiation (in super), so the format is known.
    super().initial(request, *args, **kwargs)
    if request.method not in ("GET", "HEAD"):
      return
    self.etag = snapshot_etag(request.accepted_renderer.format)
    if self.etag and _matches(request.headers.get("If-None-Match"), self.etag):
      raise _NotModified()

  def handle_exception(self, exc):
    if isinstance(exc, _NotModified):
      return Response(status=304)
    return super().handle_exception(exc)

  def finalize_response(self, request, response, *args, **kwargs):
    response = super().finalize_response(request, response, *args, **kwargs)
    patch_vary_headers(response, ["Accept"])
    if self.etag and response.status_code in CACHEABLE_STATUSES:
      response["ETag"] = self.etag
      patch_cache_control(response, public=True, max_age=settings.API_CACHE_MAX_AGE)
    return response
