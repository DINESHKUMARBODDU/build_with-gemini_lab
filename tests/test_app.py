import os
import unittest

os.environ.pop("GEMINI_API_KEY", None)
os.environ["ASSISTANT_MODE"] = "demo"
import app as m  # noqa: E402


class DataPilotTests(unittest.TestCase):
    def setUp(self):
        self.c = m.app.test_client()

    def test_sql_guard(self):
        for bad in ["DROP TABLE orders", "SELECT 1; SELECT 2", "DELETE FROM orders",
                    "PRAGMA table_info(orders)", "", "UPDATE orders SET quantity=0"]:
            with self.assertRaises(m.QueryError, msg=bad):
                m.run_query(bad)
        self.assertEqual(m.run_query("SELECT COUNT(*) FROM customers")["rows"][0][0], 48)

    def test_database_is_read_only(self):
        with self.assertRaises(Exception):
            m._conn.execute("DELETE FROM orders")

    def test_row_limit(self):
        res = m.run_query("SELECT * FROM orders")
        self.assertEqual(res["row_count"], m.MAX_ROWS)
        self.assertTrue(res["truncated"])

    def test_every_sample_question_gets_a_chartable_answer(self):
        for s in m.SAMPLES:
            r = self.c.post("/api/ask", json={"question": s["q"]})
            self.assertEqual(r.status_code, 200, s["q"])
            body = r.get_json()
            self.assertEqual(len(body["queries"]), 1, s["q"])
            self.assertGreater(body["queries"][0]["row_count"], 1, s["q"])

    def test_unknown_question_in_demo(self):
        body = self.c.post("/api/ask", json={"question": "what is the weather"}).get_json()
        self.assertEqual(body["queries"], [])
        self.assertIn("demo mode", body["answer"])

    def test_validation(self):
        self.assertEqual(self.c.post("/api/ask", json={"question": "  "}).status_code, 400)
        self.assertEqual(self.c.post("/api/ask", data="x").status_code, 400)
        self.assertEqual(self.c.post("/api/ask", json={"question": "a" * 501}).status_code, 400)
        bad = {"question": "hi", "history": [{"role": "x", "text": "y"}]}
        self.assertEqual(self.c.post("/api/ask", json=bad).status_code, 400)

    def test_pages(self):
        self.assertEqual(self.c.get("/").status_code, 200)
        self.assertEqual(self.c.get("/healthz").get_json()["status"], "ok")
        info = self.c.get("/api/schema").get_json()
        self.assertEqual({t["name"] for t in info["tables"]}, {"customers", "orders", "products"})


if __name__ == "__main__":
    unittest.main()
