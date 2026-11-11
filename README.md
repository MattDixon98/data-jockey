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
4. **Model:** each runner is scored from its form, rating, course, distance and
   going record, and from jockey and trainer win rates. A horse is flagged as
   undervalued when its estimated win probability beats the probability implied
   by its odds.
5. **Serve:** a Django app with a django-ninja API reads a daily SQLite
   snapshot of the processed tables, so pages load quickly at almost no running
   cost.

## Tech stack

| Layer          | Technology                                            |
|----------------|-------------------------------------------------------|
| Crawlers       | TypeScript, Node.js 22                                |
| Infrastructure | AWS SAM, Lambda, EventBridge Scheduler, S3, IAM       |
| Processing     | AWS Glue (PySpark), Apache Iceberg, Athena            |
| Backend & API  | Python, Django, django-ninja                          |
| Data serving   | SQLite snapshot generated daily from processed tables |

## Status

- ✅ Daily crawling to S3, deployed on AWS, with three months of history backfilled
- 🚧 Glue processing and Iceberg tables
- 🚧 Undervalued-runner model
- 🚧 Django website and API

## Repository structure

- `crawlers/`: TypeScript crawlers, Lambda entry point and AWS SAM template
- `backend/`: Django project

*Data is sourced from publicly available racing pages for personal, non-commercial
portfolio use.*
