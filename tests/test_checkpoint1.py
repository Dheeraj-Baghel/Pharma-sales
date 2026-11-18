"""
Automated tests for Checkpoint 1 (synthetic data, validation, SQLite rules).

Every test works on COPIES of the data, in-memory databases, or temporary
folders. The real files in data/ are only READ, never changed.

Run from the project root:
    python -m unittest discover -s tests -v
"""

import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

# Let the tests import the scripts in src/.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import config  # noqa: E402
import generate_data as gen  # noqa: E402
import validate_data as val  # noqa: E402

# Fingerprint and total of the ORIGINAL 1,000 transactions (from the review
# and the pre-repair backup). These must never change.
ORIGINAL_SALES_SHA256 = "ac98b182d03ec33b1aa604750abb0afb0a34cc3aecb7e6c81918604f1f9f7d06"
ORIGINAL_REVENUE_TOTAL = 8107864.43
ORIGINAL_UNITS_TOTAL = 63654

# Generate once and share between tests (keeps the suite fast).
SALES = gen.generate_sales_data()
TARGETS = gen.generate_target_plan()


def failed_checks(results):
    """Names of the checks that FAILED."""
    return [name for name, ok, _ in results if not ok]


def sales_df_to_csv_bytes(df):
    return df.to_csv(index=False).encode()


def new_db_with_schema():
    conn = sqlite3.connect(":memory:")
    conn.executescript(config.SCHEMA_PATH.read_text())
    return conn


# ===========================================================================
class TestExistingSalesPreserved(unittest.TestCase):
    def test_sales_identical_to_original_file(self):
        digest = hashlib.sha256(sales_df_to_csv_bytes(SALES)).hexdigest()
        self.assertEqual(digest, ORIGINAL_SALES_SHA256)

    def test_totals_unchanged(self):
        self.assertEqual(len(SALES), 1000)
        self.assertAlmostEqual(SALES["revenue"].sum(), ORIGINAL_REVENUE_TOTAL, places=2)
        self.assertEqual(int(SALES["units_sold"].sum()), ORIGINAL_UNITS_TOTAL)

    def test_generation_is_deterministic(self):
        pd.testing.assert_frame_equal(gen.generate_sales_data(), SALES)
        pd.testing.assert_frame_equal(gen.generate_target_plan(), TARGETS)

    def test_clean_data_passes(self):
        self.assertEqual(failed_checks(val.run_sales_checks(SALES)), [])
        self.assertEqual(failed_checks(val.run_target_checks(TARGETS)), [])


# ===========================================================================
class TestPythonSalesValidation(unittest.TestCase):
    """Each bad value must FAIL a check, and must never crash."""

    def assert_fails(self, mutate, expected_check):
        df = SALES.copy()
        df = df.astype({c: object for c in df.columns})   # allow any bad value
        mutate(df)
        failures = failed_checks(val.run_sales_checks(df))
        self.assertIn(expected_check, failures, f"got failures: {failures}")

    def test_missing_revenue(self):
        self.assert_fails(lambda d: d.__setitem__("revenue", d["revenue"].where(d.index != 5)),
                          "No missing/blank values")

    def test_infinite_price_and_revenue(self):
        def mutate(d):
            d.loc[3, "unit_price"] = np.inf
            d.loc[3, "revenue"] = np.inf
        self.assert_fails(mutate, "Numbers valid and finite")

    def test_text_in_units(self):
        self.assert_fails(lambda d: d.__setitem__("units_sold", d["units_sold"].where(d.index != 4, "many")),
                          "Numbers valid and finite")

    def test_fractional_units_with_matching_revenue(self):
        def mutate(d):
            d.loc[0, "units_sold"] = 1.5
            d.loc[0, "revenue"] = round(1.5 * d.loc[0, "unit_price"] * (1 - d.loc[0, "discount_pct"]), 2)
        self.assert_fails(mutate, "Units sold whole numbers")

    def test_blank_and_missing_id(self):
        self.assert_fails(lambda d: d.__setitem__("transaction_id", d["transaction_id"].where(d.index != 2, "  ")),
                          "No missing/blank values")
        self.assert_fails(lambda d: d.__setitem__("transaction_id", d["transaction_id"].where(d.index != 2, None)),
                          "No missing/blank values")

    def test_duplicate_id(self):
        self.assert_fails(lambda d: d.__setitem__("transaction_id", d["transaction_id"].where(d.index != 1, "TXN-00001")),
                          "Transaction IDs unique")

    def test_inconsistent_revenue(self):
        self.assert_fails(lambda d: d.__setitem__("revenue", d["revenue"].where(d.index != 7, d.loc[7, "revenue"] + 1)),
                          "Revenue formula correct")

    def test_bad_dates(self):
        for bad in ["hello", "2025-13-01", "2025-02-30", "2024-12-31", "2026-01-01", "2025-1-5"]:
            with self.subTest(date=bad):
                self.assert_fails(lambda d: d.__setitem__("date", d["date"].where(d.index != 9, bad)),
                                  "Dates valid and in 2025")

    def test_bad_discount(self):
        for bad in [-0.1, 1.5]:
            with self.subTest(discount=bad):
                self.assert_fails(lambda d: d.__setitem__("discount_pct", d["discount_pct"].where(d.index != 6, bad)),
                                  "Discount between 0 and 1")

    def test_unknown_categories(self):
        self.assert_fails(lambda d: d.__setitem__("region", d["region"].where(d.index != 0, "Northeast")),
                          "Region allowed")
        self.assert_fails(lambda d: d.__setitem__("product", d["product"].where(d.index != 0, "Aspirin")),
                          "Product allowed")
        self.assert_fails(lambda d: d.__setitem__("channel", d["channel"].where(d.index != 0, "Online")),
                          "Channel allowed")

    def test_rep_in_wrong_region(self):
        # Row 0 is Central (Vikram Tiwari); put a North rep there.
        self.assert_fails(lambda d: d.__setitem__("sales_rep", d["sales_rep"].where(d.index != 0, "Aarav Mehta")),
                          "Rep belongs to region")

    def test_missing_column(self):
        failures = failed_checks(val.run_sales_checks(SALES.drop(columns="revenue")))
        self.assertEqual(failures, ["Required columns"])


# ===========================================================================
class TestTargetPlan(unittest.TestCase):
    def test_360_unique_positive_finite_targets(self):
        self.assertEqual(len(TARGETS), 360)
        self.assertFalse(TARGETS.duplicated(val.TARGET_KEY).any())
        self.assertTrue(np.isfinite(TARGETS["target_net_revenue"]).all())
        self.assertTrue((TARGETS["target_net_revenue"] > 0).all())

    def test_includes_zero_sales_combinations(self):
        sales_keys = set(zip(SALES["date"].str[:7], SALES["region"], SALES["product"]))
        target_keys = set(zip(TARGETS["target_month"], TARGETS["region"], TARGETS["product"]))
        zero_sales = target_keys - sales_keys
        self.assertEqual(len(sales_keys), 334)
        self.assertEqual(len(zero_sales), 26)
        self.assertIn(("2025-01", "East", "Respiclear Inhaler"), zero_sales)

    def test_targets_independent_of_sales(self):
        # Changing the sales seed must not change the target plan, because
        # targets never read sales. (Generating targets also uses its own rng.)
        other_sales = gen.generate_sales_data(seed=7)
        self.assertFalse(other_sales.equals(SALES))
        pd.testing.assert_frame_equal(gen.generate_target_plan(), TARGETS)

    def test_missing_target_row_fails(self):
        failures = failed_checks(val.run_target_checks(TARGETS.drop(index=10)))
        self.assertIn("All 360 combinations once", failures)

    def test_duplicate_target_row_fails(self):
        dup = pd.concat([TARGETS, TARGETS.iloc[[0]]], ignore_index=True)
        self.assertIn("All 360 combinations once", failed_checks(val.run_target_checks(dup)))

    def test_bad_target_values_fail(self):
        for value, check in [(-5.0, "Target revenue positive"), (np.inf, "Numbers valid and finite"),
                             ("lots", "Numbers valid and finite"), (None, "No missing/blank values")]:
            with self.subTest(value=value):
                df = TARGETS.astype({"target_net_revenue": object})
                df.loc[0, "target_net_revenue"] = value
                self.assertIn(check, failed_checks(val.run_target_checks(df)))

    def test_bad_target_month_fails(self):
        df = TARGETS.copy()
        df.loc[0, "target_month"] = "2025-13"
        self.assertIn("Target months in 2025", failed_checks(val.run_target_checks(df)))


# ===========================================================================
class TestCopyComparison(unittest.TestCase):
    def test_identical_copies_pass(self):
        ok, _ = val.compare_frames(SALES, SALES.copy(), ["transaction_id"])
        self.assertTrue(ok)

    def test_one_paisa_and_ten_paise_differences_detected(self):
        largest = SALES["revenue"].idxmax()
        for change in [0.01, 0.10]:
            with self.subTest(change=change):
                other = SALES.copy()
                other.loc[largest, "revenue"] += change
                ok, detail = val.compare_frames(SALES, other, ["transaction_id"])
                self.assertFalse(ok, detail)

    def test_text_difference_detected(self):
        other = SALES.copy()
        other.loc[0, "channel"] = "Clinic " if other.loc[0, "channel"] == "Clinic" else "Clinic"
        self.assertFalse(val.compare_frames(SALES, other, ["transaction_id"])[0])


# ===========================================================================
class TestSQLiteRules(unittest.TestCase):
    """The schema itself must reject bad rows, even without Python validation."""

    def setUp(self):
        self.conn = new_db_with_schema()
        self.good = SALES.iloc[0].to_dict()
        self.good["units_sold"] = int(self.good["units_sold"])

    def tearDown(self):
        self.conn.close()

    def insert(self, row):
        cols = list(row)
        self.conn.execute(
            f"INSERT INTO sales ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [row[c] for c in cols])

    def assert_rejected(self, **changes):
        row = {**self.good, **changes}
        with self.assertRaises(sqlite3.IntegrityError, msg=f"accepted {changes}"):
            self.insert(row)

    def test_valid_row_accepted(self):
        self.insert(self.good)

    def test_all_real_data_loads(self):
        SALES.to_sql("sales", self.conn, if_exists="append", index=False)
        TARGETS.to_sql("sales_targets", self.conn, if_exists="append", index=False)

    def test_bad_ids(self):
        self.assert_rejected(transaction_id=None)
        self.assert_rejected(transaction_id="")
        self.assert_rejected(transaction_id="ABC")
        self.insert(self.good)
        self.assert_rejected(transaction_id=self.good["transaction_id"])  # duplicate

    def test_bad_dates(self):
        for bad in ["hello", "2025-13-01", "2025-02-30", "2024-12-31", "2026-01-01", "2025-1-5"]:
            with self.subTest(date=bad):
                self.assert_rejected(date=bad)

    def test_bad_units(self):
        for bad in [0, -3, 1.5, "many"]:
            with self.subTest(units=bad):
                self.assert_rejected(units_sold=bad)

    def test_bad_numbers(self):
        self.assert_rejected(unit_price=float("inf"))
        self.assert_rejected(unit_price=float("nan"))   # stored as NULL -> NOT NULL
        self.assert_rejected(unit_price="cheap")
        self.assert_rejected(discount_pct=1.5)
        self.assert_rejected(discount_pct=-0.1)
        self.assert_rejected(target_revenue=0.0)

    def test_inconsistent_revenue(self):
        self.assert_rejected(revenue=self.good["revenue"] + 0.10)
        self.assert_rejected(revenue=self.good["revenue"] + 0.01)

    def test_bad_categories_and_rep_region(self):
        self.assert_rejected(region="Northeast")
        self.assert_rejected(product="Aspirin")
        self.assert_rejected(channel="Online")
        self.assert_rejected(sales_rep="Aarav Mehta")   # North rep in a Central row

    def test_target_table_rules(self):
        good = TARGETS.iloc[0].to_dict()
        sql = ("INSERT INTO sales_targets (target_month, region, product, planned_orders, "
               "target_net_revenue) VALUES (?, ?, ?, ?, ?)")
        values = lambda r: [r[c] for c in val.TARGET_COLUMNS]  # noqa: E731
        self.conn.execute(sql, values(good))
        for changes in [{}, {"target_month": "2025-13"}, {"target_month": "2026-01"},
                        {"target_month": None}, {"target_net_revenue": -1.0},
                        {"target_net_revenue": float("inf")}, {"region": "Northeast"}]:
            with self.subTest(changes=changes), self.assertRaises(sqlite3.IntegrityError):
                self.conn.execute(sql, values({**good, **changes}))

    def test_schema_names_match_config(self):
        schema = config.SCHEMA_PATH.read_text()
        for name in config.REGION_NAMES + config.PRODUCT_NAMES + config.CHANNEL_NAMES:
            self.assertIn(f"'{name}'", schema)
        for reps in config.SALES_REPS.values():
            for rep in reps:
                self.assertIn(f"'{rep}'", schema)


# ===========================================================================
class TestSafeSaving(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def fingerprints(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.tmp.iterdir())}

    def test_save_preserves_unrelated_tables(self):
        gen.save_outputs(SALES, TARGETS, data_dir=self.tmp)
        with sqlite3.connect(self.tmp / config.DB_NAME) as conn:
            conn.execute("CREATE TABLE my_notes (note TEXT)")
            conn.execute("INSERT INTO my_notes VALUES ('keep me')")
        conn.close()
        gen.save_outputs(SALES, TARGETS, data_dir=self.tmp)
        with sqlite3.connect(self.tmp / config.DB_NAME) as conn:
            self.assertEqual(conn.execute("SELECT note FROM my_notes").fetchall(), [("keep me",)])
        conn.close()

    def test_failure_during_swap_restores_previous_files(self):
        gen.save_outputs(SALES, TARGETS, data_dir=self.tmp)
        before = self.fingerprints()

        changed = SALES.copy()
        changed.loc[0, "units_sold"] += 1
        changed.loc[0, "revenue"] = round(changed.loc[0, "units_sold"] * changed.loc[0, "unit_price"]
                                          * (1 - changed.loc[0, "discount_pct"]), 2)
        real_replace = os.replace
        calls = {"n": 0}

        def flaky_replace(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:            # first file swapped, then a "crash"
                raise OSError("simulated disk failure")
            return real_replace(src, dst)

        with mock.patch.object(gen.os, "replace", side_effect=flaky_replace), \
                mock.patch("builtins.print"):
            with self.assertRaises(OSError):
                gen.save_outputs(changed, TARGETS, data_dir=self.tmp)
        self.assertEqual(self.fingerprints(), before)

    def test_failed_validation_leaves_files_untouched(self):
        gen.save_outputs(SALES, TARGETS, data_dir=self.tmp)
        before = self.fingerprints()
        broken_schema = self.tmp.parent / f"{self.tmp.name}_broken.sql"
        broken_schema.write_text("THIS IS NOT SQL;")
        try:
            with mock.patch("builtins.print"), self.assertRaises(Exception):
                gen.save_outputs(SALES, TARGETS, data_dir=self.tmp, schema_path=broken_schema)
        finally:
            broken_schema.unlink()
        self.assertEqual(self.fingerprints(), before)


if __name__ == "__main__":
    unittest.main()
