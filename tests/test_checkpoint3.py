"""
Tests for Checkpoint 3 (Pandas analysis). All data is SYNTHETIC.

Small hand-made tables check the tricky money and growth cases. The real
database is only opened READ-ONLY; tests that need to break the data work
on a temporary copy.

Run from the project root:
    python -m unittest discover -s tests -v
"""

import contextlib
import hashlib
import io
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import analyze_sales as an  # noqa: E402


def make_sales(rows):
    """rows: list of (date, region, product, revenue). IDs are generated."""
    return pd.DataFrame(
        [{"transaction_id": f"TXN-{i + 1:05d}", "date": d, "region": r,
          "product": p, "revenue": rev} for i, (d, r, p, rev) in enumerate(rows)])


def make_targets(rows):
    """rows: list of (target_month, region, product, target_net_revenue)."""
    return pd.DataFrame(rows, columns=["target_month", "region", "product",
                                       "target_net_revenue"])


def run_quietly(function, *args):
    """Call function, capturing its printed output. Returns (result, output)."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = function(*args)
    return result, buffer.getvalue()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ===========================================================================
class TestPaise(unittest.TestCase):
    def test_float_trap_is_real(self):
        # The reason for paise: as decimals, 0.10 + 0.70 is NOT 0.80.
        self.assertLess(0.10 + 0.70, 0.80)

    def test_to_paise(self):
        self.assertEqual(list(an.to_paise(pd.Series([0.10, 0.70, 999.99, 0.0]))),
                         [10, 70, 99999, 0])

    def test_format_inr(self):
        self.assertEqual(an.format_inr(810_786_443), "₹81,07,864.43")
        self.assertEqual(an.format_inr(-69_604), "-₹696.04")
        self.assertEqual(an.format_inr(5), "₹0.05")
        self.assertEqual(an.format_inr(pd.NA), "n/a")


# ===========================================================================
class TestSmallCases(unittest.TestCase):
    """Hand-made boundary cases, run through the full analysis pipeline."""

    def setUp(self):
        targets = make_targets([
            ("2025-01", "East",  "Infecta-Guard 250mg", 0.80),     # tie via 0.10 + 0.70
            ("2025-01", "North", "Cardiozen 10mg",      1000.00),  # 1 paisa short
            ("2025-01", "South", "Neurocalm 50mg",      500.00),   # planned, no sales
            ("2025-02", "East",  "Infecta-Guard 250mg", 100.00),   # Feb: some sales
        ])
        sales = make_sales([
            ("2025-01-10", "East",  "Infecta-Guard 250mg", 0.10),
            ("2025-01-11", "East",  "Infecta-Guard 250mg", 0.70),
            ("2025-01-12", "North", "Cardiozen 10mg",      999.99),
            ("2025-02-03", "East",  "Infecta-Guard 250mg", 50.00),
        ])
        self.results = an.run_analysis(sales, targets)
        self.joined = self.results["joined"].set_index(an.KEYS)

    def test_tie_in_paise_is_at_plan(self):
        regional = self.results["regional"].set_index("region")
        self.assertEqual(regional.at["East", "actual_paise"], 5080)   # 10 + 70 + 5000
        jan_east = self.joined.loc[("2025-01", "East", "Infecta-Guard 250mg")]
        self.assertEqual(jan_east["actual_paise"], 80)
        self.assertEqual(jan_east["target_paise"], 80)
        self.assertEqual(jan_east["target_paise"] - jan_east["actual_paise"], 0)
        # Summarise just this group to check the status label of an exact tie.
        one_group = self.results["joined"].iloc[[0]]
        status = an.summarize(one_group, "region")["status"].iloc[0]
        self.assertEqual(status, "At or above plan")

    def test_one_paisa_short_is_below_plan(self):
        north = self.results["regional"].set_index("region").loc["North"]
        self.assertEqual(north["shortfall_paise"], 1)
        self.assertEqual(north["status"], "Below plan")
        self.assertEqual(an.format_pct(north["achievement_pct"]), "100.00")  # display rounds up

    def test_planned_group_without_sales(self):
        group = self.joined.loc[("2025-01", "South", "Neurocalm 50mg")]
        self.assertFalse(group["has_sales"])
        self.assertEqual(group["actual_paise"], 0)
        self.assertEqual(group["transaction_count"], 0)
        self.assertEqual(group["target_paise"], 50000)
        south = self.results["regional"].set_index("region").loc["South"]
        self.assertEqual(south["achievement_pct"], 0.0)
        self.assertEqual(south["groups_without_sales"], 1)

    def test_monthly_growth_first_month_unavailable(self):
        monthly = self.results["monthly"]
        self.assertEqual(list(monthly["month"]), ["2025-01", "2025-02"])
        self.assertTrue(pd.isna(monthly.loc[0, "growth_paise"]))
        self.assertTrue(pd.isna(monthly.loc[0, "growth_pct"]))
        # Jan actual = 0.80 + 999.99 = 100079 paise; Feb = 5000 paise
        self.assertEqual(monthly.loc[1, "growth_paise"], 5000 - 100079)

    def test_achievement_unavailable_when_plan_zero(self):
        pct = an.achievement_pct(pd.Series([500, 0]), pd.Series([0, 0]))
        self.assertTrue(pct.isna().all())


class TestGrowthAfterZeroMonth(unittest.TestCase):
    def test_growth_after_zero_revenue_month(self):
        targets = make_targets([
            ("2025-03", "West", "Glucobal 500mg", 100.00),   # March: no sales at all
            ("2025-04", "West", "Glucobal 500mg", 100.00),
            ("2025-05", "West", "Glucobal 500mg", 100.00),
        ])
        sales = make_sales([
            ("2025-04-02", "West", "Glucobal 500mg", 40.00),
            ("2025-05-02", "West", "Glucobal 500mg", 60.00),
        ])
        monthly = an.run_analysis(sales, targets)["monthly"]
        self.assertEqual(list(monthly["actual_paise"]), [0, 4000, 6000])
        # April follows a ₹0 month: INR change shown, percentage unavailable.
        self.assertEqual(monthly.loc[1, "growth_paise"], 4000)
        self.assertTrue(pd.isna(monthly.loc[1, "growth_pct"]))
        # May follows a normal month: both available.
        self.assertEqual(monthly.loc[2, "growth_paise"], 2000)
        self.assertAlmostEqual(monthly.loc[2, "growth_pct"], 50.0)

    def test_months_sorted_by_calendar_not_input_order(self):
        targets = make_targets([("2025-12", "West", "Glucobal 500mg", 1.0),
                                ("2025-02", "West", "Glucobal 500mg", 1.0),
                                ("2025-10", "West", "Glucobal 500mg", 1.0)])
        monthly = an.run_analysis(make_sales([]).reindex(
            columns=["transaction_id", "date", "region", "product", "revenue"]), targets)["monthly"]
        self.assertEqual(list(monthly["month"]), ["2025-02", "2025-10", "2025-12"])


# ===========================================================================
class TestInvalidInputStops(unittest.TestCase):
    def setUp(self):
        self.targets = make_targets([("2025-01", "North", "Cardiozen 10mg", 100.0)])
        self.sales = make_sales([("2025-01-05", "North", "Cardiozen 10mg", 50.0)])

    def assert_invalid(self, sales, targets, expected_text):
        with self.assertRaises(an.InputValidationError) as caught:
            an.run_analysis(sales, targets)
        self.assertIn(expected_text, str(caught.exception))

    def test_missing_source_revenue(self):
        sales = self.sales.copy()
        sales.loc[0, "revenue"] = np.nan
        self.assert_invalid(sales, self.targets, "sales.revenue: 1 missing/blank")

    def test_blank_region(self):
        sales = self.sales.copy()
        sales.loc[0, "region"] = "  "
        self.assert_invalid(sales, self.targets, "sales.region")

    def test_missing_column(self):
        self.assert_invalid(self.sales.drop(columns="revenue"), self.targets,
                            "missing required column(s) ['revenue']")

    def test_duplicate_transaction_id(self):
        sales = pd.concat([self.sales, self.sales], ignore_index=True)
        self.assert_invalid(sales, self.targets, "duplicate IDs 'TXN-00001'")

    def test_duplicate_target_key(self):
        targets = pd.concat([self.targets, self.targets], ignore_index=True)
        self.assert_invalid(self.sales, targets, "duplicate month+region+product")

    def test_invalid_dates(self):
        for bad in ["2025-02-30", "15/01/2025", "hello"]:
            with self.subTest(date=bad):
                sales = self.sales.copy()
                sales.loc[0, "date"] = bad
                self.assert_invalid(sales, self.targets, "invalid YYYY-MM-DD")

    def test_invalid_target_month(self):
        targets = self.targets.copy()
        targets.loc[0, "target_month"] = "2025-13"
        self.assert_invalid(self.sales, targets, "invalid YYYY-MM month")

    def test_infinite_or_text_amount(self):
        for bad in [np.inf, "lots", -5.0]:
            with self.subTest(value=bad):
                sales = self.sales.astype({"revenue": object})
                sales.loc[0, "revenue"] = bad
                self.assert_invalid(sales, self.targets, "sales.revenue")

    def test_sales_without_target(self):
        sales = make_sales([("2025-01-05", "North", "Cardiozen 10mg", 50.0),
                            ("2025-02-05", "North", "Cardiozen 10mg", 20.0)])
        self.assert_invalid(sales, self.targets, "have sales but no target")

    def test_merge_must_be_one_to_one(self):
        # Bypass the duplicate check to prove the merge itself refuses.
        actuals = pd.DataFrame({"month": ["2025-01"], "region": ["North"],
                                "product": ["Cardiozen 10mg"], "actual_paise": [5000],
                                "transaction_count": [1]})
        targets = pd.DataFrame({"month": ["2025-01", "2025-01"], "region": ["North"] * 2,
                                "product": ["Cardiozen 10mg"] * 2, "target_paise": [1, 2]})
        with self.assertRaises(an.InputValidationError) as caught:
            an.join_plan_and_actuals(targets, actuals)
        self.assertIn("not one-to-one", str(caught.exception))


# ===========================================================================
class TestRealDatabase(unittest.TestCase):
    """Full run on the real database (read-only) plus failure behaviour."""

    @classmethod
    def setUpClass(cls):
        cls.db_hash_before = file_hash(an.DB_PATH)
        cls.conn = an.open_read_only()
        sales, targets = an.load_tables(cls.conn)
        cls.results = an.run_analysis(sales, targets)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_database_opened_read_only(self):
        with self.assertRaises(sqlite3.OperationalError):
            self.conn.execute("CREATE TABLE should_fail (x INTEGER)")

    def test_verification_passes(self):
        self.assertEqual(an.verify_against_sql(self.conn, self.results), [])

    def test_counts_and_totals(self):
        r = self.results
        self.assertEqual((len(r["monthly"]), len(r["regional"]), len(r["product"])), (12, 5, 6))
        self.assertEqual(len(r["joined"]), 360)
        self.assertEqual(int((~r["joined"]["has_sales"]).sum()), 26)
        for name in ["monthly", "regional", "product"]:
            with self.subTest(summary=name):
                self.assertEqual(r[name]["actual_paise"].sum(), 810_786_443)
                self.assertEqual(r[name]["plan_paise"].sum(), 836_033_472)
                self.assertEqual(r[name]["shortfall_paise"].sum(), 25_247_029)

    def test_known_no_sales_group(self):
        group = self.results["joined"].set_index(an.KEYS).loc[
            ("2025-01", "East", "Respiclear Inhaler")]
        self.assertFalse(group["has_sales"])
        self.assertEqual(group["actual_paise"], 0)
        self.assertEqual(group["target_paise"], 2_165_916)

    def test_mismatch_names_key_and_metric(self):
        broken = {k: v.copy() for k, v in self.results.items()}
        m = broken["monthly"]
        m.loc[m["month"] == "2025-03", "actual_paise"] += 1         # 1 paisa off
        p = broken["product"]
        p.loc[p["product"] == "Glucobal 500mg", "achievement_pct"] += 0.01
        failures = an.verify_against_sql(self.conn, broken)
        joined_text = "\n".join(failures)
        self.assertIn("monthly vs report 05 [2025-03] actual_paise", joined_text)
        self.assertIn("[Glucobal 500mg] achievement_pct", joined_text)
        self.assertIn("monthly total [actual_paise]", joined_text)

    def test_main_exit_codes(self):
        code, output = run_quietly(an.main)
        self.assertEqual(code, an.EXIT_OK)
        self.assertIn("ALL VERIFICATION CHECKS PASSED", output)

        with mock.patch.dict(an.EXPECTED, {"groups_without_sales": 25}):
            code, output = run_quietly(an.main)
        self.assertEqual(code, an.EXIT_VERIFICATION_FAILED)
        self.assertIn("count [groups_without_sales]: pandas=26 expected=25", output)

        code, output = run_quietly(an.main, Path(tempfile.gettempdir()) / "no_such.db")
        self.assertEqual(code, an.EXIT_INVALID_INPUT)

    def test_invalid_database_copy_stops(self):
        # Break a TEMPORARY COPY (the real database is never written).
        tmp = Path(tempfile.mkdtemp())
        try:
            copy = tmp / "copy.db"
            shutil.copy2(an.DB_PATH, copy)
            # The schema would reject a blank region, so CHECK rules are switched
            # off for this copy only (the primary key still blocks duplicate IDs,
            # which is why duplicates are tested with small tables above).
            with sqlite3.connect(copy) as conn:
                conn.execute("PRAGMA ignore_check_constraints = ON")
                conn.execute("UPDATE sales SET region = '' WHERE transaction_id = 'TXN-00002'")
            conn.close()
            code, output = run_quietly(an.main, copy)
            self.assertEqual(code, an.EXIT_INVALID_INPUT)
            self.assertIn("INVALID INPUT - analysis stopped", output)
            self.assertIn("sales.region: 1 missing/blank value(s)", output)
            self.assertNotIn("Monthly summary", output)   # stopped before analysing
        finally:
            shutil.rmtree(tmp)

    def test_real_database_unchanged(self):
        self.assertEqual(file_hash(an.DB_PATH), self.db_hash_before)


if __name__ == "__main__":
    unittest.main()
