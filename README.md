# Data Jockey

Data Jockey is an end-to-end horse racing data platform. It collects UK and Irish
racing data every day, turns it into clean, queryable tables, and serves it to a
website that shows today's races, their odds, and which horses look undervalued
based on past performance.

## How it works

1. **Crawl:** TypeScript crawlers run on AWS Lambda each morning on a schedule
   (EventBridge Scheduler). They collect yesterday's results, today's racecards
   and the next three days of declarations and odds.
2. **Store:** raw JSON lands in S3, split into `past/`, `today/` and `future/`.
   Upcoming races are saved as daily snapshots (`t-3`, `t-2`, `t-1`), so odds
   movement can be tracked as race day approaches.
3. **Process:** AWS Glue (PySpark) jobs flatten and clean the raw data (odds to
   decimal, distances to yards, times to seconds) into Apache Iceberg tables
   that can be queried with Athena.
4. **Model:** the Glue job builds each runner's pre-race features (form, rating,
   course/distance/ground record, jockey and trainer win rates). A model trained
   monthly in a Glue Python shell job (NumPy, SciPy) turns them into our own win
   odds, which are compared with the market's (bookmakers' margin removed) to flag
   undervalued horses, with a scorecard tracking how those flags perform.
   See [model/model_description.md](model/model_description.md).
5. **Serve:** the Glue job exports the UK and Irish data to a single SQLite file
   in S3. A systemd timer on the web server runs a Django management command that
   checks its ETag, then downloads, verifies and atomically swaps in a new one with
   no restart. Django reads it through unmanaged, read-only models, so there's no
   database server to run.
6. **API:** the main API is Django REST Framework, with filtering (django-filter),
   OpenAPI docs and Swagger UI (drf-spectacular), ETag-based HTTP caching and a
   per-IP rate limit. A GraphQL API (Strawberry, with depth and size limits) sits
   alongside it on the same query layer, and every list loads in a fixed number
   of SQL queries.
7. **Website** *(in progress)*: a React single-page app built to static files,
   reading the REST API. It's served from one EC2 instance (its own SAM stack),
   with gunicorn behind Caddy, which also serves the React build from the same
   domain (no CORS) and handles HTTPS automatically.

## Tech stack

| Layer          | Technology                                                                                            |
|----------------|-------------------------------------------------------------------------------------------------------|
| Crawlers       | TypeScript, Node.js 22                                                                                |
| Infrastructure | AWS SAM, Lambda, EventBridge Scheduler, S3, IAM                                                       |
| Processing     | AWS Glue (PySpark), Apache Iceberg, Athena                                                            |
| Modelling      | Python (NumPy, SciPy), AWS Glue Python shell                                                          |
| Data serving   | SQLite snapshot generated daily from processed tables                                                 |
| Backend & API  | Python, Django, Django REST Framework, django-filter, drf-spectacular (OpenAPI), GraphQL (Strawberry) |
| Website        | React, EC2, Caddy, gunicorn (planned)                                                                 |

## Status

- ✅ Daily crawling to S3, deployed on AWS, with three months of history backfilled
- ✅ Glue processing into Iceberg tables, rebuilt daily and queryable in Athena
- ✅ Odds snapshots: every crawl of a race kept, so odds movement can be tracked
- ✅ Win-odds model: trained monthly, pricing every runner daily, with an out-of-sample scorecard
- 🚧 Undervalued rule: the first results show no edge over the market yet; to be revisited with more data
- ✅ Daily SQLite snapshot for the website, with Django models reading it read-only
- ✅ REST API (OpenAPI docs, HTTP caching, rate limiting) and a GraphQL API serving the daily data; running
  locally, not yet deployed
- 🚧 Website: React frontend and hosting still to build

## Repository structure

- `crawlers/`: TypeScript crawlers, Lambda entry point and AWS SAM template
- `glue/`: PySpark Glue job, the `data_jockey` package it uses (clean tables, features, model odds and
  scorecard), tests, Athena checks and AWS SAM template
- `model/`: monthly model training (Glue Python shell job), its `data_jockey_model` package, tests, AWS SAM
  template and [model_description.md](model/model_description.md)
- `backend/`: Django project: read-only models over the daily SQLite file, the command that fetches new ones,
  the REST and GraphQL APIs (`api/`) and their tests, plus the web server's AWS SAM template and its setup
  (`deploy/`: Caddy, gunicorn and systemd)
- `deploy`: deploys a subproject's AWS stack, e.g. `./deploy glue`, or `./deploy all` for every stack in
  dependency order

*Data is sourced from publicly available racing pages for personal, non-commercial
portfolio use.*
