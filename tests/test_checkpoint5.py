"""
Tests for Checkpoint 5 (data-backed recommendations). All data is SYNTHETIC.

  * Rule tests use the real filtered views and small hand-made views.
  * Every displayed number is re-derived independently from the filtered
    sales/targets so the evidence is proven to match the active selection.
  * AppTest drives the real dashboard page to confirm the Business Insights
    tab updates when filters change and resets correctly.

Run from the project root:
    python -m unittest tests.test_checkpoint5 -v
"""

import logging
import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import analyze_sales as an  # noqa: E402
import dashboard_data as dd  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(PROJECT_ROOT / "src" / "dashboard.py")
logging.getLogger("streamlit").setLevel(logging.ERROR)

DATA = dd.load_dashboard_data()
DEFAULT = dd.default_filters(DATA)
ALL_REGIONS, ALL_PRODUCTS = DEFAULT.regions, DEFAULT.products

# Named selections used throughout.
FULL_YEAR = DEFAULT
COMBINED = dd.Filters("2025-04", "2025-09", ("South", "West"), ("Cardiozen 10mg", "Glucobal 500mg"))
SINGLE_MONTH = dd.Filters("2025-06", "2025-06", ALL_REGIONS, ALL_PRODUCTS)
EAST_RESPICLEAR_JAN = dd.Filters("2025-01", "2025-01", ("East",), ("Respiclear Inhaler",))
AT_OR_ABOVE_PLAN = dd.Filters("2025-02", "2025-02", ("Central",), ("Neurocalm 50mg",))


def recs(filters):
    return dd.build_recommendations(dd.compute_view(DATA, filters))


def by_rule(recommendations):
    return {r.rule: r for r in recommendations}


def evidence(rec):
    return dict(rec.evidence)


def independent_totals(filters, level):
    """Recompute actual/plan per region or product straight from the filtered tables."""
    sales = dd.apply_filters(DATA["sales"], filters)
    targets = dd.apply_filters(DATA["targets"], filters)
    actual = sales.groupby(level)["revenue_paise"].sum()
    plan = targets.groupby(level)["target_paise"].sum()
    return pd.DataFrame({"actual": actual, "plan": plan}).fillna(0).astype("int64")


# ===========================================================================
# Small hand-made view for exact boundary cases
# ===========================================================================
def tiny_view(rows, sales_rows=None):
    """
    rows: (month, region, product, target_paise, actual_paise, transactions)
    Builds a view dict with the same columns compute_view produces.
    """
    joined = pd.DataFrame(rows, columns=["month", "region", "product", "target_paise",
                                         "actual_paise", "transaction_count"])
    joined["has_sales"] = joined["transaction_count"] > 0
    sales = pd.DataFrame(sales_rows or [], columns=["transaction_id", "channel", "revenue_paise"])
    return {"empty": False, "joined": joined, "sales": sales,
            "monthly": an.monthly_summary(joined),
            "regional": an.summarize(joined, "region"),
            "product": an.summarize(joined, "product")}


class TestShortfallBoundaries(unittest.TestCase):
    def test_exact_tie_excluded(self):
        # 10 + 70 paise against an 80-paise plan: exactly at plan, not a shortfall.
        view = tiny_view([("2025-01", "East", "Infecta-Guard 250mg", 80, 80, 2)])
        self.assertIsNone(dd.rule_largest_shortfall(view))
        self.assertIsNone(dd.rule_repeated_misses(view))

    def test_one_paisa_miss_qualifies(self):
        view = tiny_view([("2025-01", "North", "Cardiozen 10mg", 100000, 99999, 1)])
        rec = dd.rule_largest_shortfall(view)
        self.assertIsNotNone(rec)
        self.assertEqual(evidence(rec)["Shortfall (plan − actual)"], "₹0.01")
        self.assertEqual(evidence(rec)["Achievement"], "100.00%")   # display rounds; still a miss

    def test_tie_alongside_miss_only_miss_reported(self):
        view = tiny_view([("2025-01", "East", "Infecta-Guard 250mg", 80, 80, 2),
                          ("2025-01", "North", "Cardiozen 10mg", 100000, 99999, 1)])
        rec = dd.rule_largest_shortfall(view)
        self.assertNotIn("East", rec.title)
        self.assertNotIn("Infecta-Guard", rec.title)

    def test_one_paisa_monthly_misses_count_for_repeated_rule(self):
        view = tiny_view([("2025-01", "North", "Cardiozen 10mg", 1000, 999, 1),
                          ("2025-02", "North", "Cardiozen 10mg", 1000, 999, 1),
                          ("2025-03", "North", "Cardiozen 10mg", 1000, 1000, 1)])   # tie
        rec = dd.rule_repeated_misses(view)
        self.assertEqual(evidence(rec)["Months below plan"], "2 of 3")

    def test_no_rule_applies(self):
        view = tiny_view([("2025-01", "East", "Glucobal 500mg", 100, 150, 1)],
                         sales_rows=[("TXN-00001", "Clinic", 150)])
        self.assertEqual(dd.build_recommendations(view), [])


# ===========================================================================
class TestRulesOnRealSelections(unittest.TestCase):
    def test_full_year(self):
        r = by_rule(recs(FULL_YEAR))
        self.assertEqual(list(r), ["largest_shortfall", "repeated_misses", "no_transactions"])
        e = evidence(r["largest_shortfall"])
        self.assertIn("Cardiozen 10mg", r["largest_shortfall"].title)
        self.assertEqual(e["Actual net revenue"], "₹16,80,352.22")
        self.assertEqual(e["Planned net revenue"], "₹18,48,178.61")
        self.assertEqual(e["Shortfall (plan − actual)"], "₹1,67,826.39")
        self.assertEqual(evidence(r["no_transactions"])["Groups with no transactions"], "26 of 360")
        self.assertEqual(evidence(r["repeated_misses"])["Months below plan"], "8 of 12")

    def test_largest_shortfall_matches_independent_totals(self):
        for filters in [FULL_YEAR, COMBINED, SINGLE_MONTH,
                        dd.Filters("2025-01", "2025-03", ("North",), ALL_PRODUCTS)]:
            with self.subTest(scope=dd.describe_scope(filters, DATA)):
                best = None
                for level in ["region", "product"]:
                    totals = independent_totals(filters, level)
                    totals["gap"] = totals["plan"] - totals["actual"]
                    for name, row in totals[totals["gap"] > 0].iterrows():
                        if best is None or row["gap"] > best[0]:
                            best = (int(row["gap"]), name, int(row["actual"]), int(row["plan"]))
                rec = by_rule(recs(filters))["largest_shortfall"]
                e = evidence(rec)
                self.assertIn(best[1], rec.title)
                self.assertEqual(e["Shortfall (plan − actual)"], an.format_inr(best[0]))
                self.assertEqual(e["Actual net revenue"], an.format_inr(best[2]))
                self.assertEqual(e["Planned net revenue"], an.format_inr(best[3]))

    def test_combined_selection(self):
        r = by_rule(recs(COMBINED))
        self.assertIn("largest_shortfall", r)
        title = r["largest_shortfall"].title
        self.assertTrue(any(n in title for n in COMBINED.regions + COMBINED.products))
        # Repeated-miss evidence counts only the 6 selected months.
        self.assertTrue(evidence(r["repeated_misses"])["Months below plan"].endswith("of 6"))
        for rec in r.values():   # no entity outside the selection appears in any title
            for outsider in ("North", "East", "Central", "Neurocalm", "Respiclear", "Hydralyte"):
                self.assertNotIn(outsider, rec.title)

    def test_repeated_misses_months_match_data(self):
        rec = by_rule(recs(COMBINED))["repeated_misses"]
        product = rec.title.split(": ", 1)[1]
        sales = dd.apply_filters(DATA["sales"], COMBINED)
        targets = dd.apply_filters(DATA["targets"], COMBINED)
        a = sales[sales["product"] == product].groupby("month")["revenue_paise"].sum()
        t = targets[targets["product"] == product].groupby("month")["target_paise"].sum()
        missed = sorted(m for m in t.index if a.get(m, 0) < t[m])
        self.assertEqual(evidence(rec)["Months below plan"], f"{len(missed)} of {len(t)}")
        self.assertEqual(evidence(rec)["Missed months"], ", ".join(dd.month_label(m) for m in missed))

    def test_single_month_skips_repeated_rule(self):
        r = by_rule(recs(SINGLE_MONTH))
        self.assertNotIn("repeated_misses", r)
        self.assertIn("largest_shortfall", r)
        step = r["largest_shortfall"].next_step
        self.assertNotIn("month by month", step)
        self.assertTrue("by product to find" in step or "by region to find" in step, step)

    def test_east_respiclear_january(self):
        r = by_rule(recs(EAST_RESPICLEAR_JAN))
        e = evidence(r["no_transactions"])
        self.assertEqual(e["Groups with no transactions"], "1 of 1")
        self.assertEqual(e["Transactions in these groups"], "0")
        self.assertEqual(e["Targets in these groups"], "₹21,659.16")
        self.assertIn("Jan 2025 / East / Respiclear Inhaler", e["Largest"])
        s = evidence(r["largest_shortfall"])
        self.assertEqual(s["Actual net revenue"], "₹0.00")
        self.assertEqual(s["Shortfall (plan − actual)"], "₹21,659.16")
        self.assertIn("hypotheses", r["no_transactions"].next_step)
        self.assertNotIn("channel_concentration", r)    # no sales, so no channel claim

    def test_at_or_above_plan_selection(self):
        view = dd.compute_view(DATA, AT_OR_ABOVE_PLAN)
        self.assertLess(view["kpis"]["shortfall_paise"], 0)
        self.assertEqual(recs(AT_OR_ABOVE_PLAN), [])

    def test_channel_rule_uses_actuals_only(self):
        f = dd.Filters("2025-01", "2025-03", ("West",), ("Neurocalm 50mg",))
        rec = by_rule(recs(f))["channel_concentration"]
        e = evidence(rec)
        sales = dd.apply_filters(DATA["sales"], f)
        top = sales.groupby("channel")["revenue_paise"].sum().sort_values().index[-1]
        top_paise = int(sales.loc[sales["channel"] == top, "revenue_paise"].sum())
        top_n = int((sales["channel"] == top).sum())
        self.assertIn(top, rec.title)
        self.assertEqual(e["Channel revenue"], an.format_inr(top_paise))
        self.assertEqual(e["Transactions"], str(top_n))
        self.assertEqual(e["Average order value"], an.format_inr(round(top_paise / top_n)))
        self.assertIn("unavailable", rec.finding)
        self.assertNotIn("Achievement", e)

    def test_at_most_three_and_empty_selection(self):
        for f in [FULL_YEAR, COMBINED, SINGLE_MONTH]:
            self.assertLessEqual(len(recs(f)), dd.MAX_RECOMMENDATIONS)
        empty = dd.compute_view(DATA, dd.Filters("2025-01", "2025-12", (), ALL_PRODUCTS))
        self.assertTrue(empty["empty"])
        self.assertEqual(dd.build_recommendations(empty), [])


# ===========================================================================
class TestInsightsTabInApp(unittest.TestCase):
    """The real page via Streamlit AppTest."""

    def setUp(self):
        self.at = AppTest.from_file(APP, default_timeout=60)
        self.at.run()
        self.assertEqual(len(self.at.exception), 0)

    def set_filters(self, filters):
        self.at.selectbox(key="start_month").set_value(filters.start_month)
        self.at.selectbox(key="end_month").set_value(filters.end_month)
        self.at.multiselect(key="regions").set_value(list(filters.regions))
        self.at.multiselect(key="products").set_value(list(filters.products))
        self.at.run()
        self.assertEqual(len(self.at.exception), 0, [e.value for e in self.at.exception])

    def shown_titles(self):
        return [m.value for m in self.at.markdown
                if m.value.startswith("**") and ". " in m.value[:8]]

    def shown_evidence_tables(self):
        """Evidence tables (st.table) in page order; they follow the order of the titles."""
        return [dict(zip(t.value.index, t.value["Value"])) for t in self.at.table
                if t.value.index.name == "Evidence"]

    def shown_evidence(self, rule):
        """Evidence shown for a rule, or None if that recommendation isn't on the page."""
        rules = [r.rule for r in self.current]
        if rule not in rules:
            return None
        return self.shown_evidence_tables()[rules.index(rule)]

    def assert_page_matches(self, filters):
        expected = recs(filters)
        self.current = expected
        titles = self.shown_titles()
        self.assertEqual(titles, [f"**{i}. {r.title}**" for i, r in enumerate(expected, 1)])
        self.assertEqual(self.shown_evidence_tables(), [evidence(r) for r in expected])
        return expected

    def test_full_year_then_filters_then_reset(self):
        full = self.assert_page_matches(FULL_YEAR)
        self.assertIn("Cardiozen 10mg", full[0].title)
        self.assertTrue(any("Finding:" in m.value for m in self.at.markdown))
        self.assertTrue(any("Suggested next step:" in m.value for m in self.at.markdown))
        self.assertTrue(any("synthetic" in c.value and "flat" in c.value for c in self.at.caption))

        self.set_filters(COMBINED)
        self.assert_page_matches(COMBINED)

        self.set_filters(SINGLE_MONTH)
        shown = self.assert_page_matches(SINGLE_MONTH)
        self.assertNotIn("repeated_misses", [r.rule for r in shown])
        self.assertIsNone(self.shown_evidence("repeated_misses"))   # earlier rec disappeared

        self.at.button(key="reset").click().run()
        self.assertEqual(self.shown_titles(), [f"**{i}. {r.title}**" for i, r in enumerate(full, 1)])

    def test_east_respiclear_january_in_app(self):
        self.set_filters(EAST_RESPICLEAR_JAN)
        self.assert_page_matches(EAST_RESPICLEAR_JAN)
        e = self.shown_evidence("no_transactions")
        self.assertEqual(e["Transactions in these groups"], "0")
        self.assertEqual(e["Targets in these groups"], "₹21,659.16")

    def test_at_or_above_plan_shows_no_rule_message(self):
        self.set_filters(AT_OR_ABOVE_PLAN)
        self.assertEqual(self.shown_titles(), [])
        self.assertIn("No recommendation rule applies to this selection.",
                      [i.value for i in self.at.info])   # exact neutral wording
        # Moving back to a below-plan scope brings recommendations back.
        self.set_filters(EAST_RESPICLEAR_JAN)
        self.assertEqual(len(self.shown_titles()), 2)
        self.assertFalse(any("No recommendation rule applies" in i.value for i in self.at.info))

    def test_empty_selection_keeps_existing_empty_state(self):
        self.at.multiselect(key="products").set_value([]).run()
        self.assertEqual(len(self.at.tabs), 0)
        self.assertEqual(self.shown_titles(), [])
        self.assertTrue(any("No planned groups in this selection" in i.value for i in self.at.info))


if __name__ == "__main__":
    unittest.main()
