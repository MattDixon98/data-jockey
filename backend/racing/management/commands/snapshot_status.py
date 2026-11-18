"""Show which snapshot the site is serving, with a row count per racing model.

  python manage.py snapshot_status

Every count goes through the ORM, so this also checks that the models line up
with the tables in the file.
"""

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from racing.models import SnapshotInfo


class Command(BaseCommand):
  help = "Show the snapshot in use and how many rows each racing model sees."

  def handle(self, *args, **options):
    self.stdout.write(f"Snapshot: {settings.SNAPSHOT_PATH}")
    try:
      info = SnapshotInfo.objects.get()
      self.stdout.write(f"Built at: {info.built_at:%Y-%m-%d %H:%M} UTC (format {info.format_version})")
      for model in apps.get_app_config("racing").get_models():
        # Every field, so a misnamed column fails here rather than on a page.
        model.objects.values(*[field.attname for field in model._meta.concrete_fields]).first()
        self.stdout.write(f"  {model.__name__:17} {model.objects.count():>9,} rows")
    except DatabaseError as error:
      raise CommandError(f"Can't read the snapshot: {error}")
