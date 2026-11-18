"""Racing data from the serving snapshot (read-only).

Every model here is unmanaged (managed = False): the tables are created by the
Glue job's export (glue/data_jockey/serving.py), never by migrations, and
racing.routers.SnapshotRouter sends all their queries to the read-only
"snapshot" database. Column names follow the clean tables (glue/data_jockey/tables.py).
"""
