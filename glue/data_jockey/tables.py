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
- Races and runners include upcoming races, from the most trusted snapshot
  crawled so far (past > today > t-1 > t-2 > t-3), named in `snapshot`.
  Results (finish_position, non_finisher_reason, winning_time) are only ever
  filled from past.
- New columns go at the end of a table's DDL, so an existing table can be
  brought up to date with ALTER TABLE ... ADD COLUMNS (the job's CREATE TABLE IF
  NOT EXISTS never changes a table that already exists).
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
          verdict                 STRING  COMMENT 'Racecard verdict, HTML stripped',
          snapshot                STRING  COMMENT 'Crawl the row is from: past, today, t-1, t-2 or t-3',
          race_type               STRING  COMMENT 'FLAT, HURDLE, CHASE or N_H_FLAT, from the race name; NULL outside UK/IRE'
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
          finish_position         INT     COMMENT 'Official (amended) placing; NULL if not recorded or did not finish',
          non_finisher_reason     STRING  COMMENT 'PulledUp, Fell, UnseatedRider, RanOut, BroughtDown...',
          horse_age               INT,
          weight                  STRING  COMMENT 'Raw st-lb, e.g. 8-12',
          weight_lbs              INT     COMMENT 'NULL when the source gives 0-0',
          official_rating         INT,
          odds                    STRING  COMMENT 'As given, e.g. 9/2: starting price from past, latest forecast price before that',
          odds_decimal            DOUBLE,
          favourite               STRING  COMMENT 'f = favourite, j = joint, c = co-favourite',
          headgear                STRING  COMMENT 'Symbols, e.g. "b,t"; first-time-ness is in insights',
          days_since_last_run     INT,
          lifetime_runs           INT,
          lifetime_wins           INT,
          lifetime_places         INT,
          insights                ARRAY<STRING>  COMMENT 'e.g. HOT_JOCKEY, FIRST_TIME_HOOD',
          snapshot                STRING  COMMENT 'Crawl the row is from: past, today, t-1, t-2 or t-3'
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
          run_type            STRING  COMMENT 'FLAT, HURDLE, CHASE, N_H_FLAT; often NULL abroad',
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
  # Each runner's price at every crawl that had one, to show how the odds
  # moved up to the off: the forecast price at t-1 and today (occasionally
  # t-2), then the starting price from past. t-2/t-3 crawls rarely have prices.
  "odds_snapshots": """
      CREATE TABLE IF NOT EXISTS {db}.odds_snapshots (
          ride_id         BIGINT,
          race_id         BIGINT,
          race_date       DATE,
          horse_id        BIGINT,
          snapshot        STRING  COMMENT 't-N, today or past (past = starting price)',
          snapshot_rank   INT     COMMENT 'past 0, today 1, t-1 2...; sort descending for time order',
          status          STRING  COMMENT 'RUNNER, NONRUNNER or WITHDRAWN at that crawl',
          odds            STRING,
          odds_decimal    DOUBLE,
          favourite       STRING  COMMENT 'f = favourite, j = joint, c = co-favourite'
      ) USING iceberg
      PARTITIONED BY (months(race_date))
  """,
  # The on-course market from the past file (betting.historical_odds): every
  # price shown for a runner before the off, opening show first. The starting
  # price itself is runners.odds.
  "odds_history": """
      CREATE TABLE IF NOT EXISTS {db}.odds_history (
          ride_id         BIGINT,
          race_id         BIGINT,
          race_date       DATE,
          horse_id        BIGINT,
          seq             INT     COMMENT '1 = opening show, counting up to the last show before the off',
          odds            STRING,
          odds_decimal    DOUBLE
      ) USING iceberg
      PARTITIONED BY (months(race_date))
  """,
  # Model inputs for every UK/IRE runner at every snapshot, built only from
  # races before the race day (see build/runner_features.py). Feature
  # columns are never NULL: gaps get a neutral value and a flag.
  "runner_features": """
      CREATE TABLE IF NOT EXISTS {db}.runner_features (
          ride_id             BIGINT,
          snapshot            STRING  COMMENT 't-N, today or past; past rows are the training data',
          snapshot_rank       INT,
          race_id             BIGINT,
          race_date           DATE,
          horse_id            BIGINT,
          jockey_id           BIGINT  COMMENT 'NULL until booked (t-3/t-2)',
          trainer_id          BIGINT,
          race_type           STRING,
          has_handicap        BOOLEAN COMMENT 'Weights set to even out ratings; FALSE if unknown',
          distance_band       STRING  COMMENT 'e.g. 9-11f',
          going_group         STRING  COMMENT 'FIRM, GOOD, GOOD_TO_SOFT, SOFT, HEAVY, STANDARD; NULL if unknown',
          field_size          INT     COMMENT 'Runners at this snapshot',
          official_rating     INT,
          rating_diff         DOUBLE  COMMENT 'Rating minus the field average; 0 if unrated',
          is_unrated          BOOLEAN,
          rating_change       INT     COMMENT 'Rating minus the rating at the last known run of the same race type; 0 if unknown',
          weight_lbs          INT,
          weight_diff         DOUBLE  COMMENT 'Weight minus the field average; 0 if unknown',
          horse_runs          INT     COMMENT 'Known runs before the race (horse_form)',
          horse_wins          INT,
          horse_places        INT     COMMENT 'Top-3 finishes',
          horse_win_rate      DOUBLE  COMMENT 'Shrunk towards 10%',
          is_debut            BOOLEAN COMMENT 'No known runs',
          days_since_run      INT     COMMENT '0 on debut',
          last_form           DOUBLE  COMMENT 'Last run: 0 = won, 1 = last or did not finish; 0.5 if none',
          recent_form         DOUBLE  COMMENT 'Average form score over the last 3 runs; 0.5 if none',
          type_runs           INT     COMMENT 'Known runs of the same race type (flat, hurdle, chase, NH flat)',
          type_wins           INT,
          course_runs         INT,
          course_wins         INT,
          distance_runs       INT     COMMENT 'In the same distance band',
          distance_wins       INT,
          going_runs          INT     COMMENT 'In the same going group',
          going_wins          INT,
          has_jockey          BOOLEAN,
          jockey_rides        INT     COMMENT 'Rides in complete UK/IRE races before the race day',
          jockey_win_rate     DOUBLE  COMMENT 'Shrunk towards 10%; 10% when no jockey yet',
          trainer_runs        INT,
          trainer_win_rate    DOUBLE  COMMENT 'Shrunk towards 10%',
          finish_position     INT     COMMENT 'The label: past snapshot only, NULL before'
      ) USING iceberg
      PARTITIONED BY (months(race_date))
  """,
  # Our own fair win odds for every runner_features row, from the model
  # JSON the training job publishes (see build/model_odds.py). Each race is
  # priced by the newest model trained only on earlier races.
  "model_odds": """
      CREATE TABLE IF NOT EXISTS {db}.model_odds (
          ride_id             BIGINT,
          snapshot            STRING  COMMENT 't-N, today or past',
          snapshot_rank       INT,
          race_id             BIGINT,
          race_date           DATE,
          horse_id            BIGINT,
          model_version       STRING  COMMENT 'Which weights priced this row, e.g. 2026-11-13',
          in_sample           BOOLEAN COMMENT 'The model was trained on this race; leave out of the scorecard',
          score               DOUBLE  COMMENT 'Weighted sum of the standardised inputs, before the softmax',
          model_prob          DOUBLE  COMMENT 'Win probability; sums to 1 per race and snapshot',
          model_odds_decimal  DOUBLE  COMMENT '1 / model_prob (stake included)',
          model_odds          STRING  COMMENT 'Nearest standard bookmaker price, e.g. 10/3, Evens',
          model_rank          INT     COMMENT '1 = our favourite in the race at this snapshot',
          field_size          INT     COMMENT 'Runners the probability is shared across'
      ) USING iceberg
      PARTITIONED BY (months(race_date))
  """,
  # Our probability next to the market's (SP for past rows, the forecast price
  # for t-1/today), margin removed with Shin's method, and the undervalued flag
  # (see build/model_value.py). Only races fully priced at that snapshot.
  "model_value": """
      CREATE TABLE IF NOT EXISTS {db}.model_value (
          ride_id             BIGINT,
          snapshot            STRING  COMMENT 't-N, today or past',
          snapshot_rank       INT,
          race_id             BIGINT,
          race_date           DATE,
          horse_id            BIGINT,
          model_version       STRING,
          in_sample           BOOLEAN COMMENT 'The model was trained on this race; leave out of the scorecard',
          model_prob          DOUBLE,
          model_odds          STRING,
          market              STRING  COMMENT 'SP (past) or forecast (t-1, today)',
          market_odds         STRING  COMMENT 'As quoted, e.g. 9/2',
          market_odds_decimal DOUBLE,
          market_prob         DOUBLE  COMMENT 'Margin removed (Shin); sums to 1 per race and snapshot',
          book_percentage     DOUBLE  COMMENT 'Sum of 1/odds x 100 before the margin came off, e.g. 118',
          edge                DOUBLE  COMMENT 'model_prob / market_prob - 1',
          expected_value      DOUBLE  COMMENT 'Average return of a 1 unit bet at market_odds if model_prob is right',
          undervalued         BOOLEAN COMMENT 'expected_value >= 10% and model_prob >= 5%',
          won                 BOOLEAN COMMENT 'Once the race is run; NULL before, and for runners that did not run',
          finish_position     INT
      ) USING iceberg
      PARTITIONED BY (months(race_date))
  """,
  # How good our odds and undervalued picks have been, out of sample (see
  # build/model_scorecard.py). One row per view (after_race = vs SP on the
  # final field, site_pick = the race-morning flag), period and race group.
  "model_scorecard": """
      CREATE TABLE IF NOT EXISTS {db}.model_scorecard (
          view                  STRING  COMMENT 'after_race (vs SP) or site_pick (race-morning row, else t-1)',
          period_type           STRING  COMMENT 'all, month, day or model_version',
          period                STRING  COMMENT 'all, 2026-11, 2026-11-12, or a model version',
          race_group            STRING  COMMENT 'all, flat or jumps',
          first_race            DATE,
          last_race             DATE,
          races                 BIGINT,
          runners               BIGINT,
          log_loss_model        DOUBLE  COMMENT 'Average -ln(our probability for the winner); lower is better',
          log_loss_market       DOUBLE  COMMENT 'The same for the market (SP, or the forecast for site_pick)',
          top_pick_won_model    DOUBLE  COMMENT 'Share of races our favourite won',
          top_pick_won_market   DOUBLE  COMMENT 'Share of races the market favourite won',
          bets                  BIGINT  COMMENT 'Undervalued runners that ran (non-runners are void)',
          bets_won              BIGINT,
          expected_wins_market  DOUBLE  COMMENT 'Wins SP expected from those bets (sum of SP probabilities)',
          expected_wins_model   DOUBLE  COMMENT 'Wins we expected (sum of our probabilities)',
          wins_z                DOUBLE  COMMENT '(bets_won - expected_wins_market) / its standard deviation; above ~2 is unlikely to be luck',
          profit_units          DOUBLE  COMMENT '1 unit on every bet, settled at SP',
          roi                   DOUBLE  COMMENT 'profit_units / bets',
          roi_low               DOUBLE  COMMENT '95% range on roi (normal approximation)',
          roi_high              DOUBLE,
          top_pick_profit_model   DOUBLE  COMMENT '1 unit per race on our favourite at SP (joint favourites split it)',
          top_pick_roi_model      DOUBLE  COMMENT 'top_pick_profit_model per unit staked',
          top_pick_profit_market  DOUBLE  COMMENT 'The same on the market favourite (SP, or the forecast for site_pick)',
          top_pick_roi_market     DOUBLE  COMMENT 'top_pick_profit_market per unit staked'
      ) USING iceberg
  """,
  # Calibration, all time: runners grouped by the probability we (or the
  # market) gave them, and how often they actually won.
  "model_calibration": """
      CREATE TABLE IF NOT EXISTS {db}.model_calibration (
          view          STRING  COMMENT 'after_race or site_pick',
          source        STRING  COMMENT 'model (ours) or market (SP, or the forecast for site_pick)',
          band          INT     COMMENT '1 = 0%-5%, 2 = 5%-10%... (sort order)',
          band_label    STRING,
          runners       BIGINT,
          predicted     DOUBLE  COMMENT 'Average probability given',
          actual        DOUBLE  COMMENT 'Share that won'
      ) USING iceberg
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
  "odds_snapshots": ["ride_id", "snapshot"],
  "odds_history": ["ride_id", "seq"],
  "runner_features": ["ride_id", "snapshot"],
  "model_odds": ["ride_id", "snapshot"],
  "model_value": ["ride_id", "snapshot"],
  "model_scorecard": ["view", "period_type", "period", "race_group"],
  "model_calibration": ["view", "source", "band"],
}


def ddl_columns(name: str) -> list[str]:
  """A table's column names, in order, read from its DDL."""
  ddl = TABLES[name]
  column_list = ddl[ddl.index("(") + 1:ddl.index(") USING")]
  return re.findall(r"^\s*(\w+)\s+[A-Z]", column_list, flags=re.M)


def local_ddl(name: str, db: str) -> str:
  """A table's DDL as a plain Parquet table, for running without Iceberg (tests,
  run_local.py). Same columns, types and comments; no partitioning."""
  ddl = TABLES[name].format(db=db)
  return re.sub(r"USING iceberg.*", "USING parquet", ddl, flags=re.S)
