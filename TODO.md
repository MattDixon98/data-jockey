# Data Jockey: To-do

Local checklist, git-ignored. Tick items off with `[x]`.

## Still to build

Roughly in order.

### 1. Clean tables (Glue)
- [ ] Glue infrastructure in its own stack (`glue/`, stack `data-jockey-glue`), separate from the crawler stack
  - [x] Template: warehouse bucket, `data_jockey` database, job role, job definition
  - [ ] Deploy and run the skeleton job as a smoke test
- [ ] PySpark Glue job turns `past/` into Iceberg tables
  - [ ] `courses`
  - [ ] `meetings`
  - [ ] `races`
  - [ ] `runners`
  - [ ] `horses`
  - [ ] `jockeys`
  - [ ] `trainers`
  - [ ] `prizes`
- [ ] Conversions
  - [ ] odds → decimal
  - [ ] distance → yards
  - [ ] winning time → seconds
  - [ ] non-finisher status
  - [ ] HTML stripped from `verdict`
- [ ] Explicit schemas rather than Glue crawlers
- [ ] Check results in Athena

### 2. Odds snapshots
- [ ] Bring in `today/` and `future/` using the order of trust: **past > today > t-1 > t-2 > t-3**
- [ ] Results only ever come from `past`
- [ ] Odds shown are the latest snapshot
- [ ] Every snapshot is kept, to show how the odds moved

### 3. "Undervalued" model
- [ ] Score each runner from past performance: form, rating, course, distance, going, jockey and trainer win rates
- [ ] Compare with the probability the odds imply
- [ ] Calculation runs in the Glue layer

### 4. Serving
- [ ] Daily SQLite snapshot built from the clean tables and saved to S3
- [ ] Django loads it on startup

### 5. API and website
- [ ] django-ninja endpoints inside Django
- [ ] Homepage: today's races, odds and undervalued picks
- [ ] Heavy caching (data changes once a day)
- [ ] Before going public: credit the source and add `noindex`

### 6. Automation
- [ ] Schedule the Glue job (about 07:00, after the crawls)
- [ ] Schedule the SQLite export after the Glue job
- [ ] "Did today's data arrive?" check

## Decisions still open

- [ ] SQLite or Postgres for serving (recommended: SQLite snapshot, about $0/month vs about $15/month for always-on RDS)
- [ ] Where Django will be hosted
- [ ] Intraday odds (several `today` crawls a day)?
