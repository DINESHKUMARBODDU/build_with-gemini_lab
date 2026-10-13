"""DataPilot: a data Q&A agent. Ask in plain English, get SQL, a table and a chart.

Live mode uses Gemini with a read-only `run_sql` tool. Demo mode answers a set of
built-in questions locally, so the app works with no API key.
"""
import os
import random
import re
import sqlite3
import threading
import time
from datetime import date, timedelta

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

MAX_LEN = 500
MAX_HISTORY = 12
MAX_ROWS = 200      # rows returned to the browser
MODEL_ROWS = 40     # rows shown to the model
QUERY_TIMEOUT = 3   # seconds
MODE = os.environ.get("ASSISTANT_MODE") or ("live" if os.environ.get("GEMINI_API_KEY") else "demo")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
_client = None


# ---------------------------------------------------------------- database
class QueryError(Exception):
    pass


def _seed(conn):
    rnd = random.Random(42)
    conn.executescript(
        """
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, region TEXT, segment TEXT, signup_date TEXT);
        CREATE TABLE products  (id INTEGER PRIMARY KEY, name TEXT, category TEXT, price REAL);
        CREATE TABLE orders    (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id),
                                product_id INTEGER REFERENCES products(id), quantity INTEGER,
                                order_date TEXT, status TEXT);
        """
    )
    first = ["Ava", "Liam", "Noah", "Mia", "Arjun", "Priya", "Sofia", "Lucas", "Yuki", "Chen",
             "Fatima", "Omar", "Elena", "Mateo", "Zara", "Ethan"]
    last = ["Patel", "Smith", "Garcia", "Kim", "Nguyen", "Rossi", "Khan", "Silva", "Tanaka",
            "Mueller", "Singh", "Brown", "Lopez", "Ivanov", "Cohen", "Reddy"]
    names = rnd.sample([f"{f} {l}" for f in first for l in last], 48)
    regions = ["North America", "Europe", "Asia Pacific", "Latin America"]
    segments = ["Enterprise", "SMB", "Consumer"]
    customers = []
    for i, name in enumerate(names, 1):
        signup = date(2024, 1, 1) + timedelta(days=rnd.randint(0, 540))
        customers.append((i, name, rnd.choice(regions), rnd.choice(segments), signup.isoformat()))
    conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?)", customers)
    products = [
        ("Aurora Laptop", "Hardware", 1299), ("Pulse Phone", "Hardware", 799),
        ("Nimbus Tablet", "Hardware", 549), ("Vertex Monitor", "Hardware", 399),
        ("Orbit Headphones", "Accessories", 199), ("Echo Speaker", "Accessories", 129),
        ("Nova Keyboard", "Accessories", 89), ("Link Cable Kit", "Accessories", 39),
        ("InsightBI Suite", "Software", 249), ("TaskFlow Teams", "Software", 149),
        ("CloudSync Pro", "Software", 99), ("GuardVPN", "Software", 59),
    ]
    conn.executemany("INSERT INTO products VALUES (?,?,?,?)", [(i, *p) for i, p in enumerate(products, 1)])
    start, span = date(2025, 1, 1), (date(2026, 9, 30) - date(2025, 1, 1)).days
    seg_of = {c[0]: c[3] for c in customers}
    orders = []
    for i in range(1, 901):
        cid = rnd.randint(1, len(customers))
        qty = rnd.randint(2, 10) if seg_of[cid] == "Enterprise" else rnd.randint(1, 3)
        day = start + timedelta(days=int(span * rnd.random() ** 0.8))  # skew toward recent: growth
        status = rnd.choices(["completed", "shipped", "refunded", "cancelled"], [80, 8, 5, 7])[0]
        orders.append((i, cid, rnd.randint(1, len(products)), qty, day.isoformat(), status))
    conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?)", orders)
    conn.commit()


def _build_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    _seed(conn)
    conn.execute("PRAGMA query_only = ON")  # from here on the database is read-only
    return conn


_conn = _build_db()
_lock = threading.Lock()

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|reindex|truncate)\b", re.I)


def validate_sql(sql):
    if not isinstance(sql, str) or not sql.strip():
        raise QueryError("Empty query.")
    s = sql.strip().rstrip(";").strip()
    if ";" in s:
        raise QueryError("Only a single statement is allowed.")
    if not re.match(r"(?is)^(select|with)\b", s):
        raise QueryError("Only SELECT queries are allowed.")
    if _FORBIDDEN.search(s):
        raise QueryError("That query contains a keyword that is not allowed.")
    return s


def _clean(v):
    return round(v, 2) if isinstance(v, float) else v


def run_query(sql):
    sql = validate_sql(sql)
    with _lock:
        deadline = time.time() + QUERY_TIMEOUT
        _conn.set_progress_handler(lambda: int(time.time() > deadline), 10000)
        try:
            cur = _conn.execute(sql)
            cols = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchmany(MAX_ROWS + 1)
        except sqlite3.Error as exc:
            raise QueryError(f"SQL error: {exc}") from exc
        finally:
            _conn.set_progress_handler(None, 0)
    truncated = len(rows) > MAX_ROWS
    rows = [[_clean(v) for v in r] for r in rows[:MAX_ROWS]]
    return {"sql": sql, "columns": cols, "rows": rows, "row_count": len(rows), "truncated": truncated}


def schema_info():
    tables = []
    with _lock:
        for (name,) in _conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
            cols = [{"name": c[1], "type": c[2]} for c in _conn.execute(f"PRAGMA table_info({name})")]
            count = _conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            tables.append({"name": name, "rows": count, "columns": cols})
    return tables


def schema_text():
    lines = []
    for t in schema_info():
        cols = ", ".join(f"{c['name']} {c['type']}" for c in t["columns"])
        lines.append(f"{t['name']}({cols})  -- {t['rows']} rows")
    with _lock:
        lo, hi = _conn.execute("SELECT MIN(order_date), MAX(order_date) FROM orders").fetchone()
    lines.append("orders.status is one of: completed, shipped, refunded, cancelled. Dates are ISO text (YYYY-MM-DD).")
    lines.append(f"Orders span {lo} to {hi}.")
    return "\n".join(lines)


# ---------------------------------------------------------------- demo mode
REV_FROM = ("FROM orders o JOIN customers c ON c.id = o.customer_id "
            "JOIN products p ON p.id = o.product_id WHERE o.status = 'completed'")

SAMPLES = [
    {"q": "What is our revenue by region?", "hint": "Compare regions"},
    {"q": "Show monthly revenue over time", "hint": "Trend line"},
    {"q": "Which products sell the best?", "hint": "Top 5 by revenue"},
    {"q": "Who are our top customers?", "hint": "Top 10 by revenue"},
    {"q": "Revenue by product category", "hint": "Hardware vs software"},
    {"q": "How are orders split by status?", "hint": "Completed, refunded, ..."},
]

DEMO_QUERIES = {
    "region": ("Revenue by region (completed orders)",
               f"SELECT c.region, ROUND(SUM(o.quantity * p.price), 2) AS revenue {REV_FROM} "
               "GROUP BY c.region ORDER BY revenue DESC"),
    "month": ("Monthly revenue (completed orders)",
              f"SELECT strftime('%Y-%m', o.order_date) AS month, ROUND(SUM(o.quantity * p.price), 2) AS revenue "
              f"{REV_FROM} GROUP BY month ORDER BY month"),
    "product": ("Top products by revenue",
                f"SELECT p.name AS product, ROUND(SUM(o.quantity * p.price), 2) AS revenue {REV_FROM} "
                "GROUP BY p.name ORDER BY revenue DESC LIMIT 5"),
    "customer": ("Top customers by revenue",
                 f"SELECT c.name AS customer, ROUND(SUM(o.quantity * p.price), 2) AS revenue {REV_FROM} "
                 "GROUP BY c.name ORDER BY revenue DESC LIMIT 10"),
    "category": ("Revenue by product category",
                 f"SELECT p.category, ROUND(SUM(o.quantity * p.price), 2) AS revenue {REV_FROM} "
                 "GROUP BY p.category ORDER BY revenue DESC"),
    "status": ("Orders by status",
               "SELECT status, COUNT(*) AS orders FROM orders GROUP BY status ORDER BY orders DESC"),
    "segment": ("Customers by segment",
                "SELECT segment, COUNT(*) AS customers FROM customers GROUP BY segment ORDER BY customers DESC"),
}


def _match_demo(q):
    q = q.lower()
    if "month" in q or "over time" in q or "trend" in q:
        return "month"
    if "region" in q:
        return "region"
    if "categor" in q:
        return "category"
    if "product" in q or "sell" in q:
        return "product"
    if "customer" in q and ("top" in q or "best" in q or "biggest" in q or "revenue" in q or "who" in q):
        return "customer"
    if "segment" in q:
        return "segment"
    if "status" in q or "cancel" in q or "refund" in q:
        return "status"
    return None


def _fmt(v):
    if isinstance(v, float) and not v.is_integer():
        return f"{v:,.2f}"
    if isinstance(v, (int, float)):
        return f"{int(v):,}"
    return str(v)


def answer_demo(question):
    key = _match_demo(question)
    if key is None:
        examples = "; ".join(f'"{s["q"]}"' for s in SAMPLES[:4])
        return {"answer": "I'm in **demo mode**, so I only understand a few built-in questions. "
                          f"Try one of these: {examples}. Add a GEMINI_API_KEY to ask anything.",
                "queries": []}
    title, sql = DEMO_QUERIES[key]
    res = run_query(sql)
    top = max(res["rows"], key=lambda r: r[-1])
    answer = (f"{title}. The highest is **{top[0]}** at **{_fmt(top[-1])}**, "
              f"across {res['row_count']} rows. (Demo mode: matched to a built-in question.)")
    return {"answer": answer, "queries": [res]}


# ---------------------------------------------------------------- live mode
SYSTEM_PROMPT = """You are DataPilot, a careful data analyst. Answer questions about the SQLite database below by calling the run_sql tool.
Rules:
- Only write SELECT queries, using only the tables and columns listed.
- "Revenue" means SUM(orders.quantity * products.price) for orders with status 'completed', unless the user says otherwise.
- Use clear column aliases. For "top" questions use ORDER BY ... LIMIT.
- After you have results, explain the answer in 1-3 short sentences with the key numbers, using **bold** for key figures.
- If the data cannot answer the question, say so and suggest what can be asked. Never invent numbers.

Database schema:
"""


def answer_live(question, history):
    global _client
    from google import genai
    from google.genai import types

    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    trace = []

    def run_sql(query: str) -> dict:
        """Run one read-only SQLite SELECT query and return its columns and rows.

        Args:
            query: A single SELECT statement.
        """
        try:
            res = run_query(query)
        except QueryError as exc:
            return {"error": str(exc)}
        trace.append(res)
        return {"columns": res["columns"], "rows": res["rows"][:MODEL_ROWS],
                "row_count": res["row_count"], "truncated": res["truncated"] or res["row_count"] > MODEL_ROWS}

    contents = [
        types.Content(role="model" if m["role"] == "assistant" else "user", parts=[types.Part(text=m["text"])])
        for m in history
    ]
    contents.append(types.Content(role="user", parts=[types.Part(text=question)]))
    resp = _client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT + schema_text(), tools=[run_sql]),
    )
    answer = (resp.text or "").strip() or "I couldn't produce an answer. Try rephrasing the question."
    return {"answer": answer, "queries": trace}


# ---------------------------------------------------------------- routes
def clean_history(raw):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("'history' must be a list.")
    out = []
    for m in raw[-MAX_HISTORY:]:
        if (not isinstance(m, dict) or m.get("role") not in ("user", "assistant")
                or not isinstance(m.get("text"), str)):
            raise ValueError("Each history item needs a role (user/assistant) and text.")
        out.append({"role": m["role"], "text": m["text"][:2000]})
    return out


@app.get("/")
def index():
    return render_template("index.html", mode=MODE)


@app.get("/healthz")
def healthz():
    return jsonify(status="ok", mode=MODE)


@app.get("/api/schema")
def api_schema():
    return jsonify(tables=schema_info(), samples=SAMPLES, mode=MODE)


@app.post("/api/ask")
def api_ask():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("question"), str):
        return jsonify(error="Request must be JSON with a 'question' string."), 400
    question = data["question"].strip()
    if not question:
        return jsonify(error="Please enter a question."), 400
    if len(question) > MAX_LEN:
        return jsonify(error=f"Question is too long (max {MAX_LEN} characters)."), 400
    try:
        history = clean_history(data.get("history"))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    try:
        result = answer_live(question, history) if MODE == "live" else answer_demo(question)
    except Exception as exc:
        app.logger.exception("Answering failed: %s", exc)
        return jsonify(error="Something went wrong while answering. Please try again."), 500
    return jsonify(answer=result["answer"], queries=result["queries"], mode=MODE)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=True)
