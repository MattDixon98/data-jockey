SNAPSHOT_DB = "snapshot"
RACING_APP = "racing"


class SnapshotRouter:
  """Racing models read from (and only from) the snapshot database; nothing
  else goes near it and nothing is migrated into it."""

  def db_for_read(self, model, **hints):
    if model._meta.app_label == RACING_APP:
      return SNAPSHOT_DB
    return None

  def db_for_write(self, model, **hints):
    if model._meta.app_label == RACING_APP:
      return SNAPSHOT_DB
    return None

  def allow_relation(self, obj1, obj2, **hints):
    if obj1._meta.app_label == RACING_APP and obj2._meta.app_label == RACING_APP:
      return True
    return None

  def allow_migrate(self, db, app_label, model_name=None, **hints):
    if db == SNAPSHOT_DB or app_label == RACING_APP:
      return False
    return None
