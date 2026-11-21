# CLAUDE.md

Data Jockey is a UK/Irish horse racing data platform: TypeScript crawlers save raw
JSON to S3, AWS Glue (PySpark) turns it into Iceberg tables, and a Django site will
serve it. See README.md for the product overview and status.

Five independent subprojects, each with its own tooling. Run commands from inside
the subproject directory.

| Dir         | What                                    | Stack                          | Status        |
|-------------|-----------------------------------------|--------------------------------|---------------|
| `crawlers/` | Daily scraper Lambda → raw S3 bucket     | TypeScript, Node 22, AWS SAM   | Deployed      |
| `glue/`     | Raw JSON → clean Iceberg tables          | PySpark 3.5.4 (Glue 5.0), SAM  | In progress   |
| `model/`    | Monthly training of the win-odds weights | Python 3.9 (Glue Python shell), numpy/scipy, SAM | In progress |
| `backend/`  | Website + API                            | Django 5.2, DRF, Strawberry GraphQL; EC2, SAM | REST (main) + GraphQL APIs, server stack in progress |
| `dashboard/` | Streamlit charts over the REST API       | Streamlit, pandas, requests    | Local only    |

## Commands

From the repo root, `./deploy crawlers|glue|model|web|all` runs a subproject's own deploy (`all` in that
order: each stack uses a bucket the one before it creates).
`./deploy web-kill` deletes the web stack (`backend/scripts/server.sh`: server down, no cost); `./deploy web-start`
(= `./deploy web`) builds it again from scratch, on a new IP.

### crawlers/
```bash
npm run dev [YYYY-MM-DD]   # crawl one date locally (default: yesterday); needs S3_BUCKET + AWS creds, writes to real S3
npm run typecheck          # tsc --noEmit (no test suite)
npm run deploy             # typecheck + sam build + sam deploy (profile data-jockey, eu-west-2)
```

### glue/
```bash
pip install -r requirements-dev.txt     # pyspark==3.5.4 + pytest; needs Java for Spark
pytest                                  # all tests (pytest.ini sets testpaths=tests, pythonpath=.)
pytest tests/test_build.py -k runners   # single test / subset
python scripts/run_local.py <raw dir containing past/ today/ future/> [out dir]   # full build on real data → Parquet + SQLite snapshot
./scripts/deploy.sh                     # sam deploy + upload data_jockey.zip (don't run sam deploy alone)
aws glue start-job-run --job-name data-jockey-rebuild-clean-tables --profile data-jockey --region eu-west-2
./scripts/athena_checks.sh [file.sql]   # run glue/athena/*.sql checks against the clean tables
```
To get real data for `run_local.py`:
`aws s3 sync s3://data-jockey-raw-2026-11-11/ ./raw/ --profile data-jockey`

### model/
```bash
pip install -r requirements-dev.txt     # numpy, scipy, pandas, boto3, pytest (no Spark, no Java)
pytest                                  # synthetic-race tests (pytest.ini sets testpaths=tests, pythonpath=.)
python scripts/train_local.py [out dir] # dry run on real data from Athena; writes JSON + report locally, publishes nothing
./scripts/deploy.sh                     # sam deploy + build/upload the data_jockey_model wheel (needs the glue stack)
aws glue start-job-run --job-name data-jockey-train-model --profile data-jockey --region eu-west-2
aws s3 cp s3://data-jockey-clean-<account>/model/current.json -   # the weights in use
```

### backend/
```bash
pip install -r requirements.txt   # Django 5.2, strawberry-graphql-django, DRF, django-filter, drf-spectacular, python-dotenv, boto3
cp .env.example .env              # DJANGO_DEBUG=true locally; DJANGO_SECRET_KEY required otherwise
python manage.py fetch_snapshot   # download the serving snapshot from S3 if changed (needs DATA_JOCKEY_SNAPSHOT_S3_URI + AWS creds)
python manage.py snapshot_status  # which snapshot is served + row count per racing model
python manage.py runserver        # GraphiQL at /graphql/, REST at /api/v1/ (Swagger UI at /api/v1/docs/)
python manage.py test api         # both APIs' tests (in-memory snapshot, no real file needed)
python manage.py export_schema api.graphql.schema   # print the GraphQL SDL
python manage.py spectacular --validate --file openapi.yaml   # write + check the REST OpenAPI schema
./scripts/deploy.sh               # bundle backend/ to S3, sam deploy, run deploy/setup.sh on the box via SSM
aws ssm start-session --target <InstanceId> --profile data-jockey --region eu-west-2   # shell on the server (no SSH)
# Django admin (not public: Caddy 404s /admin): tunnel to gunicorn, then http://localhost:8000/admin/ (unstyled:
# Caddy serves /static/). Users live in the box's db.sqlite3 (createsuperuser over the shell; gone after web-kill)
aws ssm start-session --target <InstanceId> --document-name AWS-StartPortForwardingSession \
  --parameters portNumber=8000,localPortNumber=8000 --profile data-jockey --region eu-west-2
```

### dashboard/
```bash
pip install -r requirements.txt   # streamlit, pandas, requests
streamlit run app.py              # top-pick ROI by day; DATA_JOCKEY_API_URL (default https://mattdixon.uk/api/v1)
```

## Architecture

### Data flow
1. **Crawl** ([crawlers/src/crawl-day.ts](crawlers/src/crawl-day.ts)): for one date, fetch the
   racecard from the Sporting Life JSON API, then each race (500 ms delay between requests).
   EventBridge runs the Lambda daily at 06:00–06:20 Europe/London with offsets -1..+3.
   Lambda event: `{"offset": n}` or `{"date": "YYYY-MM-DD"}` (backfill).
2. **Raw S3 layout** (`generateS3FileName` in [s3-storage.ts](crawlers/src/utilities/s3-storage.ts)):
   `{past|today|future}/{racecards|races}/date=YYYY-MM-DD/{name}[-t-N].json`.
   Phase is derived from the date relative to today (UK time). Future files get a
   `-t-N` suffix so odds snapshots on successive days don't overwrite each other.
3. **Glue job** ([glue/jobs/rebuild_clean_tables.py](glue/jobs/rebuild_clean_tables.py)): first stages the raw
   bucket into the Iceberg table `raw_files` (one row per file, JSON as text; only new/changed files are fetched,
   by ETag, see [staging.py](glue/data_jockey/staging.py); `--restage_raw true` re-stages everything), then reads
   **every file in `past/`, `today/` and `future/`** from it every run (full rebuild, not incremental; only the
   S3 reading is incremental), builds every table and replaces each with
   `writeTo(...).overwrite(lit(True))` — one Iceberg commit per table. Catalog is
   `glue_catalog`, database `data_jockey`, warehouse bucket `data-jockey-clean-<account>`.
   EventBridge Scheduler starts it daily at 07:00 Europe/London (`data-jockey-rebuild-clean-tables-daily`).
4. **Serving snapshot** ([glue/data_jockey/serving.py](glue/data_jockey/serving.py)): the job's last step reads the
   committed tables back, keeps the UK/IRE rows (`uk_ire_tables()`; no runner_features) and writes one SQLite file
   (`write_sqlite()`: PK = `TABLE_KEYS`, dates as ISO text, booleans 0/1, arrays JSON, `snapshot_info.built_at`,
   `PRAGMA user_version` = `FORMAT_VERSION`) to `s3://data-jockey-clean-<account>/serving/data_jockey.sqlite3`.
   `run_local.py` writes the same file locally.
5. **Website** ([backend/](backend/)): the `racing` app's models are unmanaged and routed
   (`racing/routers.py`) to a second database, `snapshot`, opened `mode=ro` with `CONN_MAX_AGE=0`.
   `manage.py fetch_snapshot` (systemd timer every 15 min, `backend/deploy/systemd/`) checks the S3 ETag,
   downloads to a temp file, checks it and `os.replace`s it in: no restart, each request opens the current file.
   Both APIs live in `api/` and sit on those models: GraphQL (`api/graphql/`, Strawberry, `/graphql/`) and REST
   (`api/rest/`, DRF, `/api/v1/`), both through `api/queries.py`; see "APIs" below.
   **Server** (`backend/template.yaml`, stack `data-jockey-web`): one EC2 t4g.micro (Ubuntu 24.04, AMI pinned in
   samconfig) with an Elastic IP, ports 80/443 only, no SSH, `CPUCredits: standard` (load can't add cost); the stack also
   holds the account-wide $30/month budget (`data-jockey-monthly`, email from SSM `/data-jockey/alert-email`), whose
   action stops the instance at 100% actual spend. No user data: `scripts/deploy.sh` uploads the bundle and
   runs the idempotent [deploy/setup.sh](backend/deploy/setup.sh) through SSM Run Command, which sets up a fresh box or
   updates a running one (code in `/opt/data-jockey/backend`, venv beside it, settings in `/etc/data-jockey/env`,
   rewritten every deploy except the generated secret key; gunicorn on 127.0.0.1:8000 behind Caddy).
   Domain **mattdixon.uk** (Porkbun DNS, A records for it and `www` → the Elastic IP; update them after web-kill +
   web-start): Caddy serves only the domain, gets the Let's Encrypt certificate itself and redirects www and HTTP.
   The domain is set in `deploy/Caddyfile` and `scripts/deploy.sh` (`SITE_DOMAIN`, also Django's `ALLOWED_HOSTS`).
   A new snapshot column = DDL + a model field (+ a type field to expose it); a layout change the site must know about = bump
   `serving.FORMAT_VERSION` and `SNAPSHOT_FORMAT_VERSION` in settings together (fetch refuses a mismatch).

### glue/data_jockey package — keep the layers separate
- [raw_schemas.py](glue/data_jockey/raw_schemas.py): explicit Spark read schemas for the raw JSON, and
  `read_raw()`, which reads raw files directly (run_local and tests use it). It adds
  `source_file`; the snapshot (past/today/t-N) is only in the path. The job reads the staged copy instead,
  via `staging.parse_staged()`, which gives the same rows (`tests/test_staging.py` checks it on every fixture).
  Only fields the tables use. Types follow the **real files**, not the TS models in
  `crawlers/src/models` (they disagree, e.g. `official_rating`/`bha` are numbers).
- [conversions.py](glue/data_jockey/conversions.py): pure Spark `Column → Column` functions
  (odds → decimal, distance → yards, st-lb → lbs, time → seconds, HTML stripping…).
  Native Spark functions only, **no Python UDFs**. Unparseable/empty/"unknown" values become NULL, never an error.
- [build/](glue/data_jockey/build/): the transform step, pure DataFrame transformations, **no I/O**.
  One module per table (`races.py`, `runners.py`…, each with `select_<table>_columns()` and the
  table function); shared helpers (`latest`, `conform`, snapshot picking, `from_past`, flattening
  via `meetings_flat`/`card_races`/`rides`) live in `utilities.py`. A new table = a new module plus
  an entry in `build_all()` in `__init__.py`. `build_all()` first keeps only each race's most trusted file
  (`race_files()`; **past > today > t-1 > t-2 > t-3**, `conversions.snapshot_rank`) and each date's
  most trusted racecard, so entries dropped between snapshots don't linger. Results
  (finish_position, non_finisher_reason, winning_time) only ever come from past (`from_past()`).
  Then each table is de-duplicated on its key with `latest()` (most recent race wins; for names,
  most recent non-null). `races` and `runners` carry a `snapshot` column.
  `conform()` selects/casts to the target table schema and fails on missing columns.
- [tables.py](glue/data_jockey/tables.py): `TABLES` dict of Iceberg DDL with a `{db}` placeholder,
  `TABLE_KEYS`, and `local_ddl()` (the same DDL as plain Parquet, for tests and run_local).
  This is the source of truth for table columns — the job creates tables explicitly, no inference.
  `CREATE TABLE IF NOT EXISTS` never alters a live table: add new columns at the **end** of the DDL
  and run `ALTER TABLE data_jockey.<t> ADD COLUMNS (...)` in Athena before the next job run (the job
  fails, via `ddl_columns()`, if a DDL column is missing from the live table).
  The module docstring lists the conventions (BIGINT source ids, keep raw column next to the
  converted one e.g. `odds` + `odds_decimal`, month partitioning on fact tables, `country_code`
  for the UK/IE filter, only `result_status='complete'` has trustworthy positions).

`model_odds` is priced from the promoted model JSONs (`data_jockey/models.py`, `build/model_odds.py`): each
race uses the newest model trained only on earlier races; the job reads them from `--model_location`, and if
that fails it still writes every other table and fails at the end.
`model_value` puts our probability next to the market's (SP for past rows, the forecast for t-1/today; margin
removed with Shin's method, `conversions.shin_z`) with the undervalued flag; `model_scorecard` and
`model_calibration` grade it out of sample (`after_race` vs SP, `site_pick` = race-morning row, else t-1;
profit always at SP).

Tables and their keys: courses(course_id), meetings(meeting_id), races(race_id),
runners(ride_id), horses(horse_id), jockeys(jockey_id), trainers(trainer_id),
prizes(race_id, position), horse_form(horse_id, race_id), odds_snapshots(ride_id, snapshot),
odds_history(ride_id, seq), runner_features(ride_id, snapshot), model_odds(ride_id, snapshot), model_value(ride_id, snapshot),
model_scorecard(view, period_type, period, race_group), model_calibration(view, source, band). `horse_form` comes from each runner's `previous_results` and is the
main form source (reaches back before the crawl began). `odds_snapshots` is the only table built
from **every** race file (one row per priced crawl: t-N/today forecast prices, past = SP);
`odds_history` is past's `betting.historical_odds`, the on-course prices, seq 1 = opening show.
The key map is `TABLE_KEYS` in tables.py (used by the tests and run_local).

Adding/changing a column usually touches all four: raw_schemas → conversions (if parsing
needed) → build → tables DDL, plus tests.

### model/ (training)
Conditional logit: each runner's score is a weighted sum of its inputs, a race's win probabilities are
the softmax of its runners' scores. `data_jockey_model/`: `inputs.py` (inputs as SQL expressions over
`runner_features`, plain SQL that both Athena and Spark run), `data.py` (Athena query, races), `fit.py`
(log-softmax per race, loss + gradient, L-BFGS), `evaluate.py` (log-loss vs SP/random, calibration),
`pipeline.py` (warm-up, train/validate/test split by date, L2 choice, promotion, report), `aws/` (the
only AWS code), `run.py` (wires a run). Glue Python shell job `data-jockey-train-model`, monthly on the 1st
at 08:30; writes `model/versions/<date>.json|.md` and copies to `model/current.json` only if it beats
the current model on the test weeks. Keep it **Python 3.9-compatible** (`from __future__ import annotations`).
Features update daily in the rebuild; training only refreshes the weights.

### APIs (backend/api)
**REST is the main API** (the frontend uses it); GraphQL is kept, live and tested, as a secondary showcase. New
features go into REST first; add them to GraphQL only when it's cheap (shared query + a type field), no strict parity.
One Django app, `api`: `queries.py` (shared), `graphql/`, `rest/`, `tests/` (`snapshot.py`, the in-memory test
snapshot and `add_runners()`, plus `test_graphql.py`, `test_rest.py`). What both APIs need lives once and is imported:
- [api/queries.py](backend/api/queries.py): querysets and rules (orderings, the undervalued rule, name search,
  picking a runner's model row at a snapshot, the `Snapshot` enum that GraphQL wraps with `strawberry.enum`, `ApiError`),
  so the APIs can't disagree; a new question goes there first.
- Column descriptions are `help_text` on the racing models: DRF serializers pick it up by default, Strawberry via
  `FIELD_DESCRIPTION_FROM_HELP_TEXT`. Describe a column there, not in a type or serializer.
- Page size 50, max 200 in both (`API_PAGE_SIZE`/`API_MAX_PAGE_SIZE` in settings).

GraphQL: `types.py` (one Strawberry type per racing model; default orderings in each type's `get_queryset`),
`filters.py`, `schema.py` (Query root, limits, `MaskErrors`). Read-only, public, so: unbounded lists are
paginated top-level queries (`STRAWBERRY_DJANGO` page cap in settings), depth/alias/token limits, and
`ApiError` for messages the client should see (anything else is masked outside DEBUG).
`DjangoOptimizerExtension` turns nested fields into `select_related`/`prefetch_related`; a custom resolver that
reads a model field the query didn't ask for must declare it (`only=[...]`, `prefetch_related=[...]`), or
it costs one query per row. `test_query_count_does_not_grow_with_runners` guards the homepage query.

REST (DRF): generic read-only views in `views.py` (GET/HEAD only, no authentication, no cookies), each taking its
queryset from `queries` and adding the prefetches its serializer needs; query strings validated by the `*Params`
serializers (`params_class`) or django-filter (`filters.py`); limit/offset pagination; OpenAPI by drf-spectacular
(`/api/v1/schema/`, `/api/v1/docs/`). `caching.py`: ETag = snapshot `built_at` + format, `Cache-Control: public,
max-age=API_CACHE_MAX_AGE`, 304 before any racing query. Rate limit: DRF `AnonRateThrottle` per IP
(`API_RATE_LIMIT`, counters in the per-process memory cache; `DJANGO_NUM_PROXIES=1` behind Caddy, 0 locally); tests
clear the cache in `setUp`. Snapshots are the raw values (`t-1`, `today`...), not the
GraphQL enum names. Method fields reuse one nested serializer per parent (building one per row tripled a card's time).

### Tests (glue/tests)
- Fixtures are real crawler output in the raw bucket layout (`tests/fixtures/{past,today,future}/...`):
  the 2026-11-10 past racecard plus races 947829 (UK jumps, non-runners/fallers), 948441 (France,
  unplaced positions missing), 948466 (USA); and every snapshot of 948004 (2026-11-12: t-1, today,
  past) and 946551 (2026-11-14: t-3, t-2, t-1, four entries dropped by t-1), with their racecards.
- `conftest.py` provides session-scoped fixtures: a local `spark` (UTC timezone), `target_schemas`, and every
  table built from the fixtures once (`tables`, `snapshot_tables`, via `build_tables()`), shared by
  `test_build.py` and `test_serving.py`.
- `test_schemas.py` guards against misspelt schema fields by comparing non-null counts
  in Spark vs the raw JSON (a wrong name silently reads as all-NULL).
- `test_build.py` builds every table from fixtures and checks keys/values against the DDL.

## Conventions and gotchas
- Import Spark functions by name (`from pyspark.sql.functions import col, when`), not
  `functions as F`. Ones that shadow Python built-ins get a `spark_` alias
  (`max as spark_max`, `filter as spark_filter`, `round as spark_round`).
- Write Spark expressions as named steps, not nested one-liners: give conditions and
  derived values their own variables (`is_evens = ...`, `decimal = ...`), then combine
  them. Every `when` chain goes on its own lines inside parentheses and ends with an
  explicit `.otherwise(...)` (`.otherwise(lit(None))` for NULL), e.g.
  ```python
  return (
    when(is_evens, lit(2.0))
    .when(is_fraction, decimal)
    .otherwise(lit(None))
  )
  ```
  In `select_<table>_columns()`, build anything non-trivial above the `return [...]`
  and keep the list itself to `expr.alias("name")` lines.
- Spark session timezone is always UTC (job, tests, run_local) so race dates don't shift.
- Raw JSON reads use `multiLine` + `mode=FAILFAST`: a malformed file should fail the run.
- The Glue job imports `data_jockey`, shipped as `s3://data-jockey-clean-<account>/code/data_jockey.zip`
  via `--extra-py-files`. [glue/scripts/deploy.sh](glue/scripts/deploy.sh) zips and uploads it after
  `sam deploy`; a bare `sam deploy` leaves the job running stale package code.
- The clean tables keep every country (FR, USA, HK…); UK/IE filtering is done downstream with
  `country_code IN ('ENG','Scot','Wale','Nort','Eire')`.
- Both SAM stacks pin AWS profile `data-jockey`, region `eu-west-2`. The raw bucket name
  `data-jockey-raw-2026-11-11` is hardcoded in the crawler template and passed to the Glue
  stack as a parameter. Both buckets are `DeletionPolicy: Retain`.
- `crawlers/iam/deployer-policy.json` scopes the deployer to `data-jockey-*` resources; new
  roles/resources must follow that naming.
- Indent with 2 spaces (no tabs) in all files, including Python. Continuation lines
  inside brackets get +2 relative to the line that opened the bracket.
- Line endings are LF. `TODO.md` is personal and git-ignored.
- Don't commit or push — the user commits their own changes.
