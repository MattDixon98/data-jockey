# Data Jockey: To-do

Local checklist, git-ignored. Tick items off with `[x]`.

## Loose ends

- [ ] Check the first scheduled crawl (12 Nov, 06:00–06:20 UK): `past/date=2026-11-11`, `today/date=2026-11-12` and new `future/` snapshots appear in S3
- [ ] Push and merge `fix-django-dotenv` (adds `python-dotenv` to `backend/requirements.txt`)
- [ ] Add `.gitattributes` (`* text=auto eol=lf`) at the repo root, run `git add --renormalize .`, then commit
- [ ] GitHub: set up code scanning (CodeQL → Default)
- [ ] GitHub: enable Dependabot alerts
- [ ] GitHub: check secret scanning push protection is on (Settings → Advanced Security)
- [ ] AWS: set a monthly budget alert (Billing → Budgets)
- [ ] AWS: rotate the two exposed keys in the old account (651017486032): `matthew.dixon` (…JYJB) and `terraform-matthew.dixon-production` (…3ZEV); keep secrets only in `~/.aws/credentials`

## Still to build

Roughly in order.

### 1. Clean tables (Glue)
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
