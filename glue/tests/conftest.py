from pathlib import Path

import pytest
from pyspark.sql import SparkSession

FIXTURES = Path(__file__).parent / "fixtures" / "past"


@pytest.fixture(scope="session")
def spark(tmp_path_factory):
  session = (
    SparkSession.builder.master("local[1]")
    .appName("data-jockey-tests")
    .config("spark.ui.enabled", "false")
    .config("spark.sql.shuffle.partitions", "1")
    .config("spark.sql.session.timeZone", "UTC")
    .config("spark.sql.warehouse.dir", str(tmp_path_factory.mktemp("warehouse")))
    .getOrCreate()
  )
  yield session
  session.stop()
