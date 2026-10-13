# Notes for coding agents (Antigravity)
- Backend: `app.py` (Flask). Frontend: `templates/index.html`, `static/style.css`, `static/script.js` (no build step, no dependencies).
- Live mode = Gemini with a read-only `run_sql` tool. Demo mode = built-in questions in `DEMO_QUERIES`.
- The database is an in-memory SQLite seeded in `_seed()`, locked to read-only with `PRAGMA query_only`. Keep SQL guarded by `validate_sql`.
- Never hardcode secrets: use the `GEMINI_API_KEY` environment variable.
- Tests: `python -m unittest discover -s tests -v`
