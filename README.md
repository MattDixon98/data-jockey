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
4. **Model:** the daily Glue job also builds each runner's features (form, rating
   against the field, course/distance/ground record, jockey and trainer win
   rates) using only data from before the race. A model trained monthly on AWS
   turns those into our own win odds for every runner, which are compared with
   the market's (the racecard forecast before the race, the starting price
   after it, with the bookmakers' margin removed). Horses we rate well above
   the market are flagged as undervalued, and a scorecard tracks how those
   flags perform. See [model/model_description.md](model/model_description.md).
5. **Serve:** the daily Glue job finishes by exporting the UK and Irish rows
   of the tables the website needs to a single SQLite file in S3. The web
   server checks for a new one every 15 minutes and swaps it in atomically,
   and a Django app with GraphQL and REST APIs reads it read-only, so pages load
   quickly at almost no running cost.

## Tech stack

| Layer          | Technology                                            |
|----------------|-------------------------------------------------------|
| Crawlers       | TypeScript, Node.js 22                                |
| Infrastructure | AWS SAM, Lambda, EventBridge Scheduler, S3, IAM       |
| Processing     | AWS Glue (PySpark), Apache Iceberg, Athena            |
| Modelling      | Python (NumPy, SciPy), AWS Glue Python shell          |
| Backend & API  | Python, Django, GraphQL (Strawberry), REST (DRF)      |
| Data serving   | SQLite snapshot generated daily from processed tables |

## Status

- ✅ Daily crawling to S3, deployed on AWS, with three months of history backfilled
- ✅ Glue processing into Iceberg tables, rebuilt daily and queryable in Athena
- ✅ Odds snapshots: every crawl of a race kept, so odds movement can be tracked
- ✅ Win-odds model: trained monthly, pricing every runner daily, with an out-of-sample scorecard
- 🚧 Undervalued rule: the first results show no edge over the market yet; to be revisited with more data
- ✅ Daily SQLite snapshot for the website, with Django models reading it read-only
- 🚧 Django website, GraphQL and REST APIs

## Repository structure

- `crawlers/`: TypeScript crawlers, Lambda entry point and AWS SAM template
- `glue/`: PySpark Glue job, the `data_jockey` package it uses (clean tables, features, model odds and
  scorecard), tests, Athena checks and AWS SAM template
- `model/`: monthly model training (Glue Python shell job), its `data_jockey_model` package, tests, AWS SAM
  template and [model_description.md](model/model_description.md)
- `backend/`: Django project
- `deploy`: deploys a subproject's AWS stack, e.g. `./deploy glue`, or `./deploy all` for every stack in
  dependency order

*Data is sourced from publicly available racing pages for personal, non-commercial
portfolio use.*
