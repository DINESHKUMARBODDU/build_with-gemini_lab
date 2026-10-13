# DataPilot: a data Q&A agent (Flask + Gemini)

Ask questions about a sales database in plain English. The agent writes the SQL, runs it
(read-only), and shows the answer as text, a chart and a table, with the SQL and a CSV download.

**Front end:** chat UI, suggested questions, schema browser, step-by-step progress, bar and line
charts (no libraries), light/dark mode, mobile layout, keyboard shortcuts.
**Back end:** Flask API, in-memory SQLite sample data (48 customers, 12 products, 900 orders),
SQL guard + read-only database + query timeout, tests and CI.

## Run locally
```bash
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```
Open http://127.0.0.1:5000. With no API key it runs in **demo mode** (six built-in questions).

## Turn on Gemini (live mode)
Get a key at https://aistudio.google.com/apikey, then set it as an environment variable:
```bash
export GEMINI_API_KEY="your-key"        # PowerShell: $env:GEMINI_API_KEY="your-key"
python app.py
```
Live mode starts automatically. Optional: `GEMINI_MODEL` (default `gemini-2.5-flash`). Never commit your key.

## Tests
`python -m unittest discover -s tests -v`

## Push to GitHub
Run `./push_to_github.sh` (or the git commands inside it). GitHub Actions then runs the tests.

## Deploy
**Render:** New > Web Service > your repo. Build: `pip install -r requirements.txt`. Start: `gunicorn app:app`.
Add `GEMINI_API_KEY` as a secret environment variable.

**Google Cloud Run:**
```bash
gcloud run deploy datapilot --source . --region asia-south1 --allow-unauthenticated \
  --set-env-vars GEMINI_API_KEY=your-key
```
Health check path: `/healthz`. A public deployment with your key lets anyone spend your quota, so add
rate limiting or authentication before sharing the link widely.

## Use your own data
Replace `_seed()` in `app.py` with code that loads your tables (for example from CSV with `sqlite3`),
then adjust `SAMPLES` and the revenue rule in `SYSTEM_PROMPT`.
