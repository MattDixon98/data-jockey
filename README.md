<p align="center">
  <img src="frontend/src/assets/logo.png" alt="Data Jockey" width="360">
</p>

# Data Jockey
https://mattdixon.uk

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
4. **Model:** the Glue job builds point-in-time features for every runner (career record, form,
   ratings against the rated field, course/distance/ground record, jockey and
   trainer form, draw bias, race-morning flags). A conditional logit (NumPy, SciPy
   L-BFGS, L2) is trained weekly in a Glue Python shell job and promoted only if it
   beats the current inputs on held-out weeks (paired log-loss ± standard error).
   Our odds are compared with the market's (margin removed with Shin's method) to
   flag undervalued horses, with a Benter-style blend of the two that switches on
   once it proves itself; an out-of-sample scorecard grades the flags.
   See [model/model_description.md](model/model_description.md).
5. **Serve:** the Glue job exports the UK and Irish data to a single SQLite file
   in S3. A container on the web server runs a Django management command that
   checks its ETag, then downloads, verifies and atomically swaps in a new one with
   no restart. Django reads it through unmanaged, read-only models, so there's no
   database server to run.
6. **API:** the main API is Django REST Framework, with filtering (django-filter),
   OpenAPI docs and Swagger UI (drf-spectacular), ETag-based HTTP caching and a
   per-IP rate limit. A GraphQL API (Strawberry, with depth and size limits) sits
   alongside it on the same query layer, and every list loads in a fixed number
   of SQL queries.
7. **Website:** a React single-page app (Vite, TypeScript, React Router, TanStack
   Query) built to static files, reading the REST API, with a hand-drawn SVG chart
   of top-pick ROI by day (no chart library). It runs in Docker Compose on one EC2
   instance (its own SAM stack, set up over SSM with no SSH): gunicorn behind Caddy,
   which serves the React build from the same domain (no CORS) and handles HTTPS
   automatically. Multi-stage builds bake the frontend into the Caddy image; images
   are built for ARM, tagged by git commit and scanned on push to ECR, and the same
   Compose file runs the whole site locally. An AWS Budgets action stops the server
   if monthly spend hits its limit.
8. **Dashboard:** a Streamlit app (pandas, requests) charts the same top-pick ROI
   from the public REST API, daily or cumulative, as a second client of the API.

## Tech stack

| Layer          | Technology                                                                                            |
|----------------|-------------------------------------------------------------------------------------------------------|
| Crawlers       | TypeScript, Node.js 22                                                                                |
| Infrastructure | AWS SAM, Lambda, EventBridge Scheduler, S3, IAM, Docker (Compose), ECR, GitHub Actions (CI)           |
| Processing     | AWS Glue (PySpark), Apache Iceberg, Athena                                                            |
| Modelling      | Python (NumPy, SciPy), AWS Glue Python shell                                                          |
| Data serving   | SQLite snapshot generated daily from processed tables                                                 |
| Backend & API  | Python, Django, Django REST Framework, django-filter, drf-spectacular (OpenAPI), GraphQL (Strawberry) |
| Website        | React, TypeScript, Vite, EC2, Caddy (HTTPS), gunicorn                                                 |
| Dashboard      | Streamlit, pandas                                                                                     |

## Status

- ✅ Daily crawling to S3, deployed on AWS, with three months of history backfilled
- ✅ Glue processing into Iceberg tables, rebuilt daily and queryable in Athena
- ✅ Odds snapshots: every crawl of a race kept, so odds movement can be tracked
- ✅ Win-odds model: 29 inputs (career record, form, ratings, connections), trained weekly and promoted only when it beats the current inputs on held-out
  weeks, pricing every runner daily, with an out-of-sample scorecard and daily top-pick ROI against the market
  favourite
  - ✅ Undervalued rule: strong chances at 5/1 or shorter (27 Nov), which broke even over the first 449
    out-of-sample races where the first rule lost 32%; no edge over the market yet
  - 🚧 Blend of our odds with the market's: built and fitted weekly, switches on automatically once it has 1,000
    out-of-sample races and beats the market on the later ones (expected January)
  - 🚧 Draw bias, jockey/trainer recent form and the source's race-morning flags: built, not yet better than noise
    with three and a half months of data; retried as history grows
- ✅ Daily SQLite snapshot for the website, with Django models reading it read-only
- ✅ REST API (OpenAPI docs, HTTP caching, rate limiting) and a GraphQL API serving the daily data
- ✅ Website live at [mattdixon.uk](https://mattdixon.uk): today's races, our odds and picks, and a track record
  with a top-pick ROI chart
- ✅ Streamlit dashboard of top-pick ROI over the REST API (run locally)

## Repository structure

- `crawlers/`: TypeScript crawlers, Lambda entry point and AWS SAM template
- `glue/`: PySpark Glue job, the `data_jockey` package it uses (clean tables, features, model odds and
  scorecard), tests, Athena checks and AWS SAM template
- `model/`: weekly/monthly model training and the blend (Glue Python shell job), its `data_jockey_model` package,
  tests, AWS SAM template and [model_description.md](model/model_description.md); `scripts/train_local.py
  --add/--drop` compares input changes on the same weeks before they go in
- `backend/`: Django project: read-only models over the daily SQLite file, the command that fetches new ones,
  the REST and GraphQL APIs (`api/`) and their tests, plus the web server's Dockerfile, Compose file, AWS SAM
  template and setup (`deploy/`: the Caddy image, the server setup script)
- `frontend/`: the React website (Vite, TypeScript), built into the Caddy image by the web deploy
- `dashboard/`: Streamlit app charting top-pick ROI from the REST API
- `.github/workflows/`: CI, one workflow per subproject (tests, type checks, the website's Docker images)
- `deploy`: deploys a subproject's AWS stack, e.g. `./deploy glue`, or `./deploy all` for every stack in
  dependency order

*Data is sourced from publicly available racing pages for personal, non-commercial
portfolio use.*
