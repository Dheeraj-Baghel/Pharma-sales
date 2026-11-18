"""
Tests for Checkpoint 4 (Streamlit dashboard). All data is SYNTHETIC.

Two layers:
  * dashboard_data.py is tested directly (numbers vs Checkpoint 3 and SQL).
  * dashboard.py is tested with Streamlit's AppTest, which runs the real
    page script headlessly and lets us change filters and read what is shown.

The real database is only read. Broken databases are temporary files.

Run from the project root:
    python -m unittest tests.test_checkpoint4 -v
"""

import hashlib
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import analyze_sales as an  # noqa: E402
import dashboard_data as dd  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(PROJECT_ROOT / "src" / "dashboard.py")
logging.getLogger("streamlit").setLevel(logging.ERROR)   # quieter test output

DATA = dd.load_dashboard_data()
FULL = DATA["full_results"]


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_app(db_path=None):
    """Run the dashboard page headlessly, optionally against another database file."""
    env = {"PHARMA_DB_PATH": str(db_path)} if db_path else {}
    with mock.patch.dict(os.environ, env):
        at = AppTest.from_file(APP, default_timeout=60)
        at.run()
    return at


def metrics(at):
    return {m.label: m.value for m in at.metric}


def text_of(at):
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    return "\n".join(parts)


def sql_slice(where_sales, where_targets, params_sales=(), params_targets=()):
    """Independent SQL totals in paise for a slice (read-only connection)."""
    conn = an.open_read_only()
    try:
        actual = conn.execute(
            f"SELECT COALESCE(SUM(CAST(ROUND(revenue*100) AS INTEGER)),0), "
            f"COALESCE(SUM(units_sold),0), COUNT(*) FROM sales WHERE {where_sales}",
            params_sales).fetchone()
        plan = conn.execute(
            f"SELECT SUM(CAST(ROUND(target_net_revenue*100) AS INTEGER)), COUNT(*) "
            f"FROM sales_targets WHERE {where_targets}", params_targets).fetchone()
    finally:
        conn.close()
    return {"actual_paise": actual[0], "units": actual[1], "transactions": actual[2],
            "plan_paise": plan[0], "plan_rows": plan[1]}


# ===========================================================================
class TestDataLayerMatchesCheckpoint3(unittest.TestCase):
    def setUp(self):
        self.view = dd.compute_view(DATA, dd.default_filters(DATA))

    def test_default_kpis(self):
        k = self.view["kpis"]
        self.assertEqual(k["actual_paise"], 810_786_443)
        self.assertEqual(k["plan_paise"], 836_033_472)
        self.assertEqual(k["shortfall_paise"], 25_247_029)
        self.assertEqual(k["units_sold"], 63_654)
        self.assertEqual(f"{k['achievement_pct']:.2f}", "96.98")
        self.assertEqual((k["planned_groups"], k["groups_without_sales"]), (360, 26))

    def test_rollups_identical_to_verified_pandas(self):
        cols = ["actual_paise", "plan_paise", "shortfall_paise", "achievement_pct",
                "transaction_count", "status"]
        for name, key, extra in [("monthly", "month", ["growth_paise", "growth_pct"]),
                                 ("regional", "region", []), ("product", "product", [])]:
            with self.subTest(summary=name):
                ours = self.view[name].set_index(key).sort_index()[cols + extra]
                verified = FULL[name].set_index(key).sort_index()[cols + extra]
                pd.testing.assert_frame_equal(ours, verified)

    def test_full_dataset_sql_reconciliation(self):
        # The fixed Checkpoint 3 reconciliation, on the FULL year.
        conn = an.open_read_only()
        try:
            self.assertEqual(an.verify_against_sql(conn, FULL), [])
        finally:
            conn.close()

    def test_product_units_and_discount_vs_sql(self):
        conn = an.open_read_only()
        try:
            sql = pd.read_sql_query(
                "SELECT product, SUM(units_sold) AS units, ROUND(100.0*AVG(discount_pct), 6) AS d "
                "FROM sales GROUP BY product", conn).set_index("product")
        finally:
            conn.close()
        product = self.view["product"].set_index("product")
        for name, row in sql.iterrows():
            self.assertEqual(product.at[name, "units_sold"], row["units"])
            self.assertAlmostEqual(product.at[name, "avg_discount_pct"], row["d"], places=5)

    def test_region_shares_add_to_100(self):
        self.assertAlmostEqual(self.view["regional"]["share_pct"].sum(), 100.0, places=9)


class TestFilteredSlices(unittest.TestCase):
    def check_against_sql(self, filters, where_s, where_t, ps=(), pt=()):
        view = dd.compute_view(DATA, filters)
        expected = sql_slice(where_s, where_t, ps, pt)
        k = view["kpis"]
        self.assertEqual(k["actual_paise"], expected["actual_paise"])
        self.assertEqual(k["plan_paise"], expected["plan_paise"])
        self.assertEqual(k["units_sold"], expected["units"])
        self.assertEqual(k["transactions"], expected["transactions"])
        self.assertEqual(k["planned_groups"], expected["plan_rows"])
        for name in ["monthly", "regional", "product"]:
            self.assertEqual(view[name]["actual_paise"].sum(), k["actual_paise"])
            self.assertEqual(view[name]["plan_paise"].sum(), k["plan_paise"])
        return view

    def test_north_q1_against_sql(self):
        view = self.check_against_sql(
            dd.Filters("2025-01", "2025-03", ("North",), DATA and dd.default_filters(DATA).products),
            "region = 'North' AND date BETWEEN '2025-01-01' AND '2025-03-31'",
            "region = 'North' AND target_month BETWEEN '2025-01' AND '2025-03'")
        self.assertEqual(view["kpis"]["actual_paise"], 49_681_896)   # ₹4,96,818.96
        self.assertEqual(view["kpis"]["plan_paise"], 56_626_147)     # ₹5,66,261.47

    def test_single_month(self):
        view = self.check_against_sql(
            dd.Filters("2025-06", "2025-06", dd.default_filters(DATA).regions,
                       dd.default_filters(DATA).products),
            "date BETWEEN '2025-06-01' AND '2025-06-30'", "target_month = '2025-06'")
        self.assertEqual(len(view["monthly"]), 1)
        self.assertTrue(pd.isna(view["monthly"].loc[0, "growth_paise"]))
        self.assertTrue(pd.isna(view["monthly"].loc[0, "growth_pct"]))

    def test_combined_filters(self):
        self.check_against_sql(
            dd.Filters("2025-04", "2025-09", ("South", "West"), ("Cardiozen 10mg", "Glucobal 500mg")),
            "region IN ('South','West') AND product IN ('Cardiozen 10mg','Glucobal 500mg') "
            "AND date BETWEEN '2025-04-01' AND '2025-09-30'",
            "region IN ('South','West') AND product IN ('Cardiozen 10mg','Glucobal 500mg') "
            "AND target_month BETWEEN '2025-04' AND '2025-09'")

    def test_planned_group_with_no_sales(self):
        view = dd.compute_view(DATA, dd.Filters("2025-01", "2025-01", ("East",),
                                                ("Respiclear Inhaler",)))
        k = view["kpis"]
        self.assertFalse(view["empty"])
        self.assertEqual((k["actual_paise"], k["transactions"], k["units_sold"]), (0, 0, 0))
        self.assertEqual(k["plan_paise"], 2_165_916)                  # ₹21,659.16
        self.assertEqual(k["achievement_pct"], 0.0)
        self.assertEqual(k["groups_without_sales"], 1)
        self.assertTrue(pd.isna(view["product"].loc[0, "avg_discount_pct"]))
        self.assertTrue(pd.isna(view["regional"].loc[0, "share_pct"]))  # 0 of ₹0 selected

    def test_growth_unavailable_after_zero_month_in_scope(self):
        # East / Respiclear: Jan has no sales, Feb has sales.
        view = dd.compute_view(DATA, dd.Filters("2025-01", "2025-02", ("East",),
                                                ("Respiclear Inhaler",)))
        feb = view["monthly"].iloc[1]
        self.assertEqual(view["monthly"].iloc[0]["actual_paise"], 0)
        self.assertGreater(feb["growth_paise"], 0)
        self.assertTrue(pd.isna(feb["growth_pct"]))

    def test_empty_selection_is_not_zero_sales(self):
        d = dd.default_filters(DATA)
        for filters in [dd.Filters(d.start_month, d.end_month, (), d.products),
                        dd.Filters(d.start_month, d.end_month, d.regions, ())]:
            self.assertTrue(dd.compute_view(DATA, filters)["empty"])

    def test_insights_follow_filters(self):
        view = dd.compute_view(DATA, dd.Filters("2025-01", "2025-03", ("North",),
                                                dd.default_filters(DATA).products))
        text = "\n".join(dd.build_insights(view))
        self.assertIn("₹4,96,818.96", text)
        self.assertIn("87.74%", text)
        self.assertNotIn("recommend", text.lower())


# ===========================================================================
class TestLoadErrors(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def assert_load_error(self, path, title_part):
        with self.assertRaises(dd.DashboardDataError) as caught:
            dd.load_dashboard_data(path)
        self.assertIn(title_part, caught.exception.title)
        self.assertTrue(caught.exception.recovery)
        return caught.exception

    def make_corrupt(self):
        path = self.tmp / "corrupt.db"
        path.write_bytes(b"this is not a sqlite database" * 100)
        return path

    def make_missing_table(self):
        path = self.tmp / "no_targets.db"
        shutil.copy2(an.DB_PATH, path)
        with sqlite3.connect(path) as conn:
            conn.execute("DROP TABLE sales_targets")
        conn.close()
        return path

    def make_invalid_records(self):
        path = self.tmp / "invalid.db"
        shutil.copy2(an.DB_PATH, path)
        with sqlite3.connect(path) as conn:
            conn.execute("PRAGMA ignore_check_constraints = ON")
            conn.execute("UPDATE sales SET revenue = -5 WHERE transaction_id = 'TXN-00010'")
        conn.close()
        return path

    def test_missing_file(self):
        self.assert_load_error(self.tmp / "nope.db", "not found")

    def test_corrupt_file(self):
        error = self.assert_load_error(self.make_corrupt(), "could not be read")
        self.assertIn("generate_data.py", error.recovery)

    def test_missing_table(self):
        error = self.assert_load_error(self.make_missing_table(), "table(s) missing")
        self.assertIn("sales_targets", error.details[0])

    def test_invalid_records(self):
        error = self.assert_load_error(self.make_invalid_records(), "failed validation")
        self.assertTrue(any("revenue" in d for d in error.details))

    def test_folder_instead_of_file(self):
        self.assert_load_error(self.tmp, "not a file")

    def test_connection_closed_after_load(self):
        opened = []
        real_open = an.open_read_only

        def spy(path=an.DB_PATH):
            conn = real_open(path)
            opened.append(conn)
            return conn

        with mock.patch.object(an, "open_read_only", side_effect=spy):
            dd.load_dashboard_data()
        self.assertEqual(len(opened), 1)
        with self.assertRaises(sqlite3.ProgrammingError):   # closed connections refuse queries
            opened[0].execute("SELECT 1")

    def test_app_shows_error_and_no_kpis(self):
        cases = {
            "missing": (self.tmp / "nope.db", "Database file not found"),
            "corrupt": (self.make_corrupt(), "could not be read"),
            "missing table": (self.make_missing_table(), "table(s) missing"),
            "invalid records": (self.make_invalid_records(), "failed validation"),
        }
        for name, (path, message) in cases.items():
            with self.subTest(case=name):
                at = run_app(path)
                self.assertEqual(len(at.exception), 0, [e.value for e in at.exception])
                self.assertTrue(at.error, "expected an st.error")
                self.assertIn(message, at.error[0].value)
                self.assertTrue(any("How to fix" in i.value for i in at.info))
                self.assertEqual(len(at.metric), 0)          # no KPIs
                self.assertEqual(len(at.tabs), 0)            # no sections


# ===========================================================================
class TestDashboardApp(unittest.TestCase):
    """The real page, driven headlessly with Streamlit AppTest."""

    def setUp(self):
        self.at = run_app()
        self.assertEqual(len(self.at.exception), 0, [e.value for e in self.at.exception])

    def set_filters(self, start=None, end=None, regions=None, products=None):
        if start:
            self.at.selectbox(key="start_month").set_value(start)
        if end:
            self.at.selectbox(key="end_month").set_value(end)
        if regions is not None:
            self.at.multiselect(key="regions").set_value(list(regions))
        if products is not None:
            self.at.multiselect(key="products").set_value(list(products))
        self.at.run()
        self.assertEqual(len(self.at.exception), 0, [e.value for e in self.at.exception])

    def test_default_view_renders_all_sections(self):
        self.assertEqual([t.label for t in self.at.tabs],
                         ["Executive Overview", "Regional Analysis", "Product Analysis",
                          "Business Insights"])
        m = metrics(self.at)
        self.assertEqual(m["Net revenue"], "₹81,07,864.43")
        self.assertEqual(m["Planned net revenue"], "₹83,60,334.72")
        self.assertEqual(m["Target achievement"], "96.98%")
        self.assertEqual(m["Shortfall (plan − actual)"], "₹2,52,470.29")
        self.assertEqual(m["Units sold"], "63,654")
        self.assertEqual(len(self.at.get("plotly_chart")), 4)
        self.assertEqual(len(self.at.dataframe), 4)
        self.assertIn("Jan 2025 – Dec 2025 · Regions: all 5 regions · Products: all 6 products",
                      text_of(self.at))
        self.assertIn("synthetic and fictional", text_of(self.at))

    def test_tables_match_verified_results(self):
        monthly, regional, product, gaps = [d.value for d in self.at.dataframe]
        self.assertEqual(list(monthly["Month"]), [dd.month_label(m) for m in FULL["monthly"]["month"]])
        self.assertEqual(monthly.loc[0, "Change (INR)"], "n/a")
        self.assertEqual(monthly.loc[0, "Change (%)"], "n/a")
        self.assertEqual(monthly.loc[1, "Change (INR)"], "-₹1,09,774.10")
        self.assertEqual(monthly.loc[1, "Change (%)"], "-12.33%")
        central = regional.set_index("Region").loc["Central"]
        self.assertEqual(central["Achievement"], "91.96%")
        self.assertEqual(central["Shortfall"], "₹79,961.99")
        self.assertEqual(central["Share of selected revenue"], "11.28%")
        cardio = product.set_index("Product").loc["Cardiozen 10mg"]
        self.assertEqual(cardio["Shortfall"], "₹1,67,826.39")
        self.assertEqual(cardio["Units sold"], 10202)
        self.assertIn("simple avg", " ".join(product.columns))
        self.assertEqual(len(gaps), 5)

    def test_north_q1(self):
        self.set_filters(start="2025-01", end="2025-03", regions=["North"])
        m = metrics(self.at)
        self.assertEqual(m["Net revenue"], "₹4,96,818.96")
        self.assertEqual(m["Planned net revenue"], "₹5,66,261.47")
        self.assertIn("Jan 2025 – Mar 2025 · Regions: North", text_of(self.at))

    def test_planned_group_with_no_sales(self):
        self.set_filters(start="2025-01", end="2025-01", regions=["East"],
                         products=["Respiclear Inhaler"])
        m = metrics(self.at)
        self.assertEqual(m["Net revenue"], "₹0.00")
        self.assertEqual(m["Planned net revenue"], "₹21,659.16")
        self.assertEqual(m["Target achievement"], "0.00%")
        self.assertEqual(m["Units sold"], "0")
        product = self.at.dataframe[2].value
        self.assertEqual(product.loc[0, "Avg discount (simple avg per transaction)"], "n/a")
        self.assertIn("1 with no sales", text_of(self.at))
        self.assertIn("Only one month is visible", text_of(self.at))

    def test_single_month_growth_unavailable(self):
        self.set_filters(start="2025-07", end="2025-07")
        monthly = self.at.dataframe[0].value
        self.assertEqual(len(monthly), 1)
        self.assertEqual(monthly.loc[0, "Change (INR)"], "n/a")

    def test_combined_filters_then_reset(self):
        self.set_filters(start="2025-04", end="2025-09", regions=["South", "West"],
                         products=["Cardiozen 10mg", "Glucobal 500mg"])
        expected = dd.compute_view(DATA, dd.Filters("2025-04", "2025-09", ("South", "West"),
                                                    ("Cardiozen 10mg", "Glucobal 500mg")))["kpis"]
        self.assertEqual(metrics(self.at)["Net revenue"], an.format_inr(expected["actual_paise"]))
        self.at.button(key="reset").click().run()
        self.assertEqual(metrics(self.at)["Net revenue"], "₹81,07,864.43")
        self.assertIn("all 5 regions", text_of(self.at))

    def test_empty_selection_shows_message_not_zeros(self):
        self.set_filters(regions=[])
        self.assertEqual(len(self.at.metric), 0)
        self.assertEqual(len(self.at.tabs), 0)
        self.assertTrue(any("No planned groups in this selection" in i.value for i in self.at.info))
        self.assertTrue(any("at least one region" in i.value for i in self.at.info))

    def test_reversed_month_range_warns(self):
        self.set_filters(start="2025-09", end="2025-03")
        self.assertEqual(len(self.at.metric), 0)
        self.assertTrue(any("is after 'To month'" in w.value for w in self.at.warning))


class TestSourceUnchanged(unittest.TestCase):
    def test_database_not_modified_by_dashboard(self):
        before = file_hash(an.DB_PATH)
        run_app()
        self.assertEqual(file_hash(an.DB_PATH), before)


if __name__ == "__main__":
    unittest.main()
