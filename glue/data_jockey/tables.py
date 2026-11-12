"""Clean Iceberg table definitions.

One DDL statement per table, with `{db}` standing in for the fully qualified
database (e.g. `glue_catalog.data_jockey`). The job creates these explicitly
rather than letting Spark or a Glue crawler infer them, so column names and
types stay stable from run to run.

Conventions:
- ids are the source's own ids, stored as BIGINT.
- Raw strings that get converted keep their raw column alongside the
  converted one (`distance` + `distance_yards`, `odds` + `odds_decimal`), which
  makes bad conversions easy to spot in Athena.
- Empty strings and the source's "unknown" markers (`0-0` weight, position 0)
  become NULL.
- Fact tables are partitioned by month(race_date): a day is only ~100 races /
  ~1,000 runners, so daily partitions would just make lots of tiny files.
- `country_code` is kept on races so the UK/Ireland filter is one WHERE clause:
  country_code IN ('ENG', 'Scot', 'Wale', 'Nort', 'Eire'). The crawl also
  covers France, the USA, Hong Kong, South Africa, the UAE etc.; those rows are
  kept in the clean tables and filtered out by the model and website.
- Only races with result_status = 'complete' have trustworthy finishing
  positions.
"""

import re

TABLES: dict[str, str] = {
  "courses": """
      CREATE TABLE IF NOT EXISTS {db}.courses (
          course_id       BIGINT,
          name            STRING,
          shortcode       STRING  COMMENT 'e.g. PUN; from the racecard',
          country_code    STRING  COMMENT 'Source short_name: ENG, Eire, Wale, FR, USA...',
          country_name    STRING,
          feed_source     STRING  COMMENT 'TV feed: RUK, ATR or NULL'
      ) USING iceberg
  """,
  "meetings": """
      CREATE TABLE IF NOT EXISTS {db}.meetings (
          meeting_id      BIGINT,
          meeting_date    DATE,
          course_id       BIGINT,
          going           STRING,
          surface_summary STRING  COMMENT 'e.g. "Dirt, Turf"',
          weather         STRING
      ) USING iceberg
  """,
  "races": """
      CREATE TABLE IF NOT EXISTS {db}.races (
          race_id                 BIGINT,
          meeting_id              BIGINT,
          course_id               BIGINT,
          country_code            STRING,
          race_date               DATE,
          race_time               STRING  COMMENT 'Scheduled local time, HH:MM',
          off_time                STRING  COMMENT 'Actual off, HH:MM:SS',
          name                    STRING,
          race_class              INT     COMMENT 'NULL when unclassified (most non-UK races)',
          age_band                STRING,
          surface                 STRING  COMMENT 'TURF, DIRT, SAND, FIBRESAND, POLYTRACK',
          distance                STRING  COMMENT 'Raw, e.g. 1m 4f 148y',
          distance_yards          INT,
          going                   STRING,
          going_shortcode         STRING,
          has_handicap            BOOLEAN,
          race_stage              STRING  COMMENT 'Raw: WEIGHEDIN, RESULT, ABANDONED, RACEVOID, DORMANT...',
          result_status           STRING  COMMENT 'complete, abandoned, or incomplete (crawled before the result)',
          ride_count              INT     COMMENT 'Declared runners, including non-runners',
          placed_count            INT     COMMENT 'Places paid',
          winning_time            STRING  COMMENT 'Raw, e.g. 1m 45.20s',
          winning_time_seconds    DOUBLE,
          book_percentage         DOUBLE  COMMENT 'On-course overround',
          betting_forecast        STRING,
          verdict                 STRING  COMMENT 'Racecard verdict, HTML stripped'
      ) USING iceberg
      PARTITIONED BY (months(race_date))
  """,
  "runners": """
      CREATE TABLE IF NOT EXISTS {db}.runners (
          ride_id                 BIGINT,
          race_id                 BIGINT,
          race_date               DATE,
          horse_id                BIGINT,
          jockey_id               BIGINT,
          trainer_id              BIGINT,
          owner_name              STRING  COMMENT 'Owners have no id in the source',
          cloth_number            INT,
          draw                    INT,
          status                  STRING  COMMENT 'RUNNER, NONRUNNER or WITHDRAWN',
          finish_position         INT     COMMENT 'NULL if not recorded or did not finish',
          non_finisher_reason     STRING  COMMENT 'PulledUp, Fell, UnseatedRider, RanOut, BroughtDown...',
          horse_age               INT,
          weight                  STRING  COMMENT 'Raw st-lb, e.g. 8-12',
          weight_lbs              INT     COMMENT 'NULL when the source gives 0-0',
          official_rating         INT,
          odds                    STRING  COMMENT 'Starting price as given, e.g. 9/2',
          odds_decimal            DOUBLE,
          favourite               STRING  COMMENT 'f = favourite, j = joint, c = co-favourite',
          headgear                STRING  COMMENT 'Symbols, e.g. "b,t"; first-time-ness is in insights',
          days_since_last_run     INT,
          lifetime_runs           INT,
          lifetime_wins           INT,
          lifetime_places         INT,
          insights                ARRAY<STRING>  COMMENT 'e.g. HOT_JOCKEY, FIRST_TIME_HOOD'
      ) USING iceberg
      PARTITIONED BY (months(race_date))
  """,
  "horses": """
      CREATE TABLE IF NOT EXISTS {db}.horses (
          horse_id        BIGINT,
          name            STRING,
          slug            STRING,
          sex             STRING  COMMENT 'g, f, m, c, h',
          foaled          DATE    COMMENT 'Often just 1 Jan of the birth year'
      ) USING iceberg
  """,
  "jockeys": """
      CREATE TABLE IF NOT EXISTS {db}.jockeys (
          jockey_id       BIGINT,
          name            STRING
      ) USING iceberg
  """,
  "trainers": """
      CREATE TABLE IF NOT EXISTS {db}.trainers (
          trainer_id      BIGINT,
          name            STRING,
          slug            STRING
      ) USING iceberg
  """,
  "prizes": """
      CREATE TABLE IF NOT EXISTS {db}.prizes (
          race_id         BIGINT,
          position        INT,
          amount          DECIMAL(12, 2),
          currency        STRING  COMMENT 'GBP, EUR, USD...'
      ) USING iceberg
  """,
  # Each runner's last few runs, from horse.previous_results. Reaches back
  # before the crawl started and covers races that were never crawled, so
  # it is the main source of form for the model. One row per horse per race;
  # the same run appears in many files, so the job keeps the latest copy.
  "horse_form": """
      CREATE TABLE IF NOT EXISTS {db}.horse_form (
          horse_id            BIGINT,
          race_id             BIGINT  COMMENT 'Joins to races when that race was crawled',
          race_date           DATE,
          race_time           STRING,
          course_name         STRING,
          course_shortcode    STRING,
          race_name           STRING,
          race_class          INT,
          run_type            STRING  COMMENT 'FLAT, HURDLE, CHASE, N_H_FLAT; NULL abroad',
          distance            STRING,
          distance_yards      INT,
          going               STRING,
          going_shortcode     STRING,
          runner_count        INT,
          finish_position     INT,
          non_finisher_reason STRING,
          weight              STRING,
          weight_lbs          INT,
          official_rating     INT     COMMENT 'BHA rating at the time (source field bha)',
          odds                STRING,
          odds_decimal        DOUBLE
      ) USING iceberg
      PARTITIONED BY (years(race_date))
  """,
}


# Each table's key: unique and never NULL. build.py de-duplicates on these.
TABLE_KEYS: dict[str, list[str]] = {
  "courses": ["course_id"],
  "meetings": ["meeting_id"],
  "races": ["race_id"],
  "runners": ["ride_id"],
  "horses": ["horse_id"],
  "jockeys": ["jockey_id"],
  "trainers": ["trainer_id"],
  "prizes": ["race_id", "position"],
  "horse_form": ["horse_id", "race_id"],
}


def local_ddl(name: str, db: str) -> str:
  """A table's DDL as a plain Parquet table, for running without Iceberg (tests,
  run_local.py). Same columns, types and comments; no partitioning."""
  ddl = TABLES[name].format(db=db)
  return re.sub(r"USING iceberg.*", "USING parquet", ddl, flags=re.S)
