# Data Jockey

This repository is a lightweight starter structure for:

- a Django-powered website frontend/backend
- TypeScript-based web scrapers

## Structure

- `backend/` — Django project
- `scrapers/` — TypeScript scraping scripts

## Quick start

### Django

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

### TypeScript scrapers

```bash
cd scrapers
npm install
npm run dev
```

## Notes

This is intentionally a minimal scaffold intended for early development and GitHub setup.
