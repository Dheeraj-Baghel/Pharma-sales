"""
dashboard_data.py  (Checkpoint 4)
---------------------------------
All the DATA logic behind the Streamlit dashboard, kept separate from the
page layout so it can be tested without a browser.

It reuses the verified Checkpoint 3 code in analyze_sales.py:
    * read-only database loader      (open_read_only, load_tables)
    * full input validation          (validate_inputs)
    * integer-paise preparation      (prepare)
    * aggregate-before-merge logic   (aggregate_actuals, join_plan_and_actuals)
    * summaries and growth           (summarize, monthly_summary)

Order of work:
    1. load_dashboard_data()  - open read-only, load, CLOSE the connection,
                                validate the FULL dataset, prepare paise.
    2. compute_view(filters)  - apply the SAME filter to sales and targets,
                                then aggregate -> merge -> summarise.
All amounts stay integer paise; convert to INR only when displaying.
All data is SYNTHETIC (fictional).
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

import analyze_sales as an

REQUIRED_TABLES = ("sales", "sales_targets")
MAX_PROBLEMS_SHOWN = 8


class DashboardDataError(Exception):
    """A loading problem the user can fix. Carries a title, details and a recovery step."""

    def __init__(self, title, details, recovery):
        super().__init__(title)
        self.title = title
        self.details = list(details)
        self.recovery = recovery


# ===========================================================================
# 1. Load + validate the FULL dataset (before any filtering)
# ===========================================================================
def load_dashboard_data(db_path=an.DB_PATH):
    """
    Returns {"sales", "targets", "full_results"}:
        sales / targets  - validated and prepared (month + paise columns)
        full_results     - the Checkpoint 3 analysis of the whole year
    Raises DashboardDataError with a practical recovery step on any problem.
    """
    path = Path(db_path)
    rebuild = "From the project folder run:  python src/generate_data.py"

    if not path.exists():
        raise DashboardDataError("Database file not found",
                                 [f"Expected a SQLite file at: {path}"], rebuild)
    if not path.is_file():
        raise DashboardDataError("Database path is not a file",
                                 [f"{path} is a folder or special file."],
                                 "Point the dashboard at the SQLite file data/pharma_sales.db.")

    # --- Load boundary: every database error is caught here ----------------
    conn = None
    try:
        conn = an.open_read_only(path)
        tables = {row[0] for row in
                  conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        missing = [t for t in REQUIRED_TABLES if t not in tables]
        if missing:
            raise DashboardDataError(
                "Required table(s) missing from the database",
                [f"Missing: {', '.join(missing)}  (found: {', '.join(sorted(tables)) or 'no tables'})"],
                rebuild)
        sales, targets = an.load_tables(conn)
    except DashboardDataError:
        raise
    except (sqlite3.Error, pd.errors.DatabaseError) as error:
        # Corrupt, unreadable, locked or not-a-SQLite file.
        raise DashboardDataError(
            "The database file could not be read",
            [f"{path}: {error}"],
            f"If the file is damaged, move it aside and rebuild it:  "
            f"mv \"{path}\" \"{path}.broken\"  then  python src/generate_data.py") from error
    finally:
        if conn is not None:
            conn.close()          # data is now in memory; the file is released

    # --- Validate the FULL dataset before any filter is applied -----------
    validate_step = ("See the full report with  python src/validate_data.py  and rebuild "
                     "the data with  python src/generate_data.py")
    try:
        problems = an.validate_inputs(sales, targets)
    except Exception as error:     # never show a traceback for bad data
        problems = [f"Validation could not run: {type(error).__name__}: {error}"]
    if problems:
        shown = problems[:MAX_PROBLEMS_SHOWN]
        if len(problems) > MAX_PROBLEMS_SHOWN:
            shown.append(f"... and {len(problems) - MAX_PROBLEMS_SHOWN} more problem(s)")
        raise DashboardDataError("Source data failed validation", shown, validate_step)

    try:
        full_results = an.run_analysis(sales, targets)    # also checks sales-without-target
    except an.InputValidationError as error:
        raise DashboardDataError("Source data failed validation",
                                 str(error).splitlines(), validate_step) from error

    sales_p, targets_p = an.prepare(sales, targets)
    return {"sales": sales_p, "targets": targets_p, "full_results": full_results}


# ===========================================================================
# 2. Filters
# ===========================================================================
@dataclass(frozen=True)
class Filters:
    start_month: str          # 'YYYY-MM', inclusive
    end_month: str            # 'YYYY-MM', inclusive
    regions: tuple
    products: tuple


def default_filters(data):
    """All of 2025, all regions, all products."""
    t = data["targets"]
    return Filters(t["month"].min(), t["month"].max(),
                   tuple(unique_in_order(t["region"])), tuple(unique_in_order(t["product"])))


def unique_in_order(series):
    return list(dict.fromkeys(series))


def apply_filters(df, filters):
    """
    Keep rows inside the month range and the selected regions and products.
    The SAME function filters sales and targets, so both sides always cover
    exactly the same scope. 'YYYY-MM' text sorts like a date, so between()
    works on whole calendar months.
    """
    mask = (df["month"].between(filters.start_month, filters.end_month)
            & df["region"].isin(filters.regions)
            & df["product"].isin(filters.products))
    return df[mask]


# ===========================================================================
# 3. Compute everything the page shows (all money in paise)
# ===========================================================================
def ratio_pct(numerator, denominator):
    """100 x numerator / denominator, or NaN (unavailable) when denominator is 0."""
    return np.nan if denominator == 0 else 100 * numerator / denominator


def compute_view(data, filters):
    """
    Returns a dict. If no plan rows match the filters, returns
    {"empty": True, ...}; that is different from a scope that HAS plan
    rows but zero sales (those keep their targets and show ₹0 actual).
    """
    sales = apply_filters(data["sales"], filters)
    targets = apply_filters(data["targets"], filters)
    if targets.empty:
        return {"empty": True, "filters": filters}

    # Aggregate first (one row per month+region+product), then merge.
    joined = an.join_plan_and_actuals(targets, an.aggregate_actuals(sales))
    monthly = an.monthly_summary(joined)
    regional = an.summarize(joined, "region")
    product = an.summarize(joined, "product")

    # Region share of the SELECTED actual revenue.
    selected_actual = int(joined["actual_paise"].sum())
    regional["share_pct"] = [ratio_pct(a, selected_actual) for a in regional["actual_paise"]]

    # Product units and simple average discount across transactions.
    product_stats = (sales.groupby("product", as_index=False)
                     .agg(units_sold=("units_sold", "sum"),
                          avg_discount_pct=("discount_pct", "mean")))
    product_stats["avg_discount_pct"] *= 100
    product = product.merge(product_stats, on="product", how="left", validate="one_to_one")
    product["units_sold"] = product["units_sold"].fillna(0).astype("int64")
    # avg_discount_pct stays NaN (unavailable) for products with no sales.

    plan = int(joined["target_paise"].sum())
    kpis = {
        "actual_paise": selected_actual,
        "plan_paise": plan,
        "shortfall_paise": plan - selected_actual,
        "achievement_pct": ratio_pct(selected_actual, plan),
        "units_sold": int(sales["units_sold"].sum()),
        "transactions": int(len(sales)),
        "planned_groups": int(len(joined)),
        "groups_without_sales": int((~joined["has_sales"]).sum()),
    }
    return {"empty": False, "filters": filters, "sales": sales, "joined": joined,
            "monthly": monthly, "regional": regional, "product": product, "kpis": kpis}


# ===========================================================================
# 4. Descriptive findings (no recommendations or causes - Checkpoint 5)
# ===========================================================================
def month_label(month):
    return pd.to_datetime(month, format="%Y-%m").strftime("%b %Y")


def describe_scope(filters, data):
    d = default_filters(data)
    months = (month_label(filters.start_month) if filters.start_month == filters.end_month
              else f"{month_label(filters.start_month)} – {month_label(filters.end_month)}")

    def pick(selected, everything, noun):
        if not selected:
            return f"no {noun}"
        if tuple(selected) == tuple(everything):
            return f"all {len(everything)} {noun}"
        return ", ".join(selected)

    return (f"{months} · Regions: {pick(filters.regions, d.regions, 'regions')} · "
            f"Products: {pick(filters.products, d.products, 'products')}")


def build_insights(view):
    """A few factual statements computed from the active filters."""
    k = view["kpis"]
    fmt = an.format_inr
    out = []

    if k["shortfall_paise"] > 0:
        out.append(f"Actual net revenue is {fmt(k['actual_paise'])}, "
                   f"{an.format_pct(k['achievement_pct'])}% of the {fmt(k['plan_paise'])} plan "
                   f"(shortfall {fmt(k['shortfall_paise'])}).")
    else:
        out.append(f"Actual net revenue is {fmt(k['actual_paise'])}, "
                   f"{an.format_pct(k['achievement_pct'])}% of the {fmt(k['plan_paise'])} plan "
                   f"({fmt(-k['shortfall_paise'])} above plan).")

    for level, table in [("region", view["regional"]), ("product", view["product"])]:
        below = table[table["shortfall_paise"] > 0]
        if below.empty:
            out.append(f"Every selected {level} is at or above plan.")
        else:
            worst = below.loc[below["shortfall_paise"].idxmax()]
            out.append(f"Largest {level} shortfall: {worst[level]}, "
                       f"{fmt(worst['shortfall_paise'])} below plan "
                       f"({an.format_pct(worst['achievement_pct'])}% achievement). "
                       f"{len(below)} of {len(table)} selected {level}s are below plan.")

    joined = view["joined"].assign(shortfall_paise=lambda d: d["target_paise"] - d["actual_paise"])
    gaps = joined[joined["shortfall_paise"] > 0]
    if not gaps.empty:
        g = gaps.loc[gaps["shortfall_paise"].idxmax()]
        sales_note = "no sales" if g["transaction_count"] == 0 else f"{g['transaction_count']} sale(s)"
        out.append(f"Largest single monthly gap: {month_label(g['month'])} / {g['region']} / "
                   f"{g['product']}, {fmt(g['shortfall_paise'])} below a "
                   f"{fmt(g['target_paise'])} target ({sales_note}).")

    out.append(f"{k['groups_without_sales']} of {k['planned_groups']} planned "
               f"month–region–product groups in this scope recorded no sales; "
               f"they keep their targets and count as ₹0.00 actual.")

    monthly = view["monthly"]
    if len(monthly) > 1:
        below_months = int((monthly["shortfall_paise"] > 0).sum())
        best = monthly.loc[monthly["achievement_pct"].idxmax()]
        weakest = monthly.loc[monthly["achievement_pct"].idxmin()]
        out.append(f"{below_months} of {len(monthly)} months are below plan. Highest "
                   f"achievement: {month_label(best['month'])} "
                   f"({an.format_pct(best['achievement_pct'])}%); lowest: "
                   f"{month_label(weakest['month'])} ({an.format_pct(weakest['achievement_pct'])}%).")
    return out


# ===========================================================================
# 5. Recommendations (Checkpoint 5)
#
# Simple, documented rules evaluated on the ACTIVE filtered view, so every
# name, ranking and amount comes from the current selection. All money
# comparisons use integer paise; the plan is sales_targets (monthly).
#
#   Rule 1  Largest shortfall: the region or product with the largest
#           positive shortfall (plan - actual) in INR. Ties at exactly 0 are
#           NOT shortfalls; a 1-paisa miss is.
#   Rule 2  Repeated monthly misses: products below plan in at least
#           REPEATED_MISS_MIN_MONTHS of the selected months. Needs 2+ months.
#   Rule 3  Planned groups with no transactions: month+region+product groups
#           that have a target but zero recorded sales.
#   Rule 4  Channel concentration (actuals only): if one channel holds at
#           least CHANNEL_SHARE_THRESHOLD of selected revenue. Channels have
#           no plan allocation, so no channel achievement is shown.
#
# Rules are tried in this order and at most MAX_RECOMMENDATIONS are shown.
# Each recommendation separates the FINDING (what the data shows), the
# EVIDENCE (numbers) and a suggested NEXT STEP. Possible causes are stated
# as hypotheses to check, never as conclusions.
# ===========================================================================
MAX_RECOMMENDATIONS = 3
REPEATED_MISS_MIN_MONTHS = 2
CHANNEL_SHARE_THRESHOLD = 0.40     # 40% of selected net revenue
SEASONALITY_NOTE = ("The data is synthetic, and the monthly plan is flat while generated "
                    "sales are seasonal, so some gaps reflect how the dataset and its plan "
                    "were built rather than real performance.")


@dataclass(frozen=True)
class Recommendation:
    rule: str          # short id, e.g. "largest_shortfall"
    title: str
    finding: str       # what the data shows
    evidence: tuple    # tuple of (label, value text) pairs
    next_step: str     # suggested action, phrased as something to check


def rule_largest_shortfall(view):
    """Rule 1: biggest INR shortfall among selected regions and products."""
    candidates = []
    for level, table in [("region", view["regional"]), ("product", view["product"])]:
        below = table[table["shortfall_paise"] > 0]          # exact tie (0) excluded
        for _, row in below.iterrows():
            candidates.append((int(row["shortfall_paise"]), level, row))
    if not candidates:
        return None
    # Largest shortfall wins; on an exact tie prefer region, then name (stable).
    shortfall, level, row = max(candidates, key=lambda c: (c[0], c[1] == "region", c[2][c[1]]))
    name = row[level]
    others = sum(1 for c in candidates if c[1] == level) - 1
    peer_note = (f" {others} other selected {level}{'s are' if others != 1 else ' is'} also below plan."
                 if others else "")
    other_dimension = "products" if level == "region" else "regions"
    if view["joined"]["month"].nunique() > 1:
        breakdown = f"month by month to find which months and {other_dimension}"
    else:
        breakdown = f"by {other_dimension[:-1]} to find which {other_dimension}"
    return Recommendation(
        rule="largest_shortfall",
        title=f"Largest shortfall: {name} ({level})",
        finding=(f"{name} has the largest shortfall in INR among the selected regions and "
                 f"products.{peer_note}"),
        evidence=(("Actual net revenue", an.format_inr(row["actual_paise"])),
                  ("Planned net revenue", an.format_inr(row["plan_paise"])),
                  ("Shortfall (plan − actual)", an.format_inr(shortfall)),
                  ("Achievement", f"{an.format_pct(row['achievement_pct'])}%")),
        next_step=(f"Review {name}'s results {breakdown} account for most of the "
                   f"{an.format_inr(shortfall)} gap, then check whether the gap comes from fewer "
                   f"orders or smaller orders before deciding on any action."),
    )


def rule_repeated_misses(view):
    """Rule 2: products that missed plan in several of the selected months."""
    months = sorted(view["joined"]["month"].unique())
    if len(months) < REPEATED_MISS_MIN_MONTHS:
        return None                                          # single-month view: skip
    by_pm = (view["joined"].groupby(["product", "month"], as_index=False)
             [["actual_paise", "target_paise"]].sum())
    by_pm["missed"] = by_pm["actual_paise"] < by_pm["target_paise"]
    counts = (by_pm.groupby("product")
              .agg(missed=("missed", "sum"), months=("month", "nunique"),
                   shortfall=("target_paise", "sum"), actual=("actual_paise", "sum"))
              .reset_index())
    counts["shortfall"] -= counts["actual"]
    flagged = counts[counts["missed"] >= REPEATED_MISS_MIN_MONTHS]
    if flagged.empty:
        return None
    flagged = flagged.sort_values(["missed", "shortfall", "product"],
                                  ascending=[False, False, True])
    top = flagged.iloc[0]
    missed_months = by_pm[(by_pm["product"] == top["product"]) & by_pm["missed"]]["month"]
    listing = "; ".join(f"{r['product']}: {int(r['missed'])} of {int(r['months'])}"
                        for _, r in flagged.iterrows())
    return Recommendation(
        rule="repeated_misses",
        title=f"Repeated monthly misses: {top['product']}",
        finding=(f"{top['product']} was below its monthly plan in {int(top['missed'])} of the "
                 f"{int(top['months'])} selected months. "
                 f"{len(flagged)} selected product{'s' if len(flagged) != 1 else ''} missed plan "
                 f"in {REPEATED_MISS_MIN_MONTHS} or more months."),
        evidence=(("Months below plan", f"{int(top['missed'])} of {int(top['months'])}"),
                  ("Missed months", ", ".join(month_label(m) for m in missed_months)),
                  ("Net position over selected months",
                   f"{an.format_inr(abs(int(top['shortfall'])))} "
                   f"{'below' if top['shortfall'] > 0 else 'at or above'} plan"),
                  ("All products with repeated misses", listing)),
        next_step=(f"Compare {top['product']}'s missed months with its other months, and check "
                   f"whether the flat monthly plan suits a product whose sales vary by season "
                   f"before treating the misses as a performance problem."),
    )


def rule_no_transaction_groups(view):
    """Rule 3: planned groups with a target but no recorded sales."""
    joined = view["joined"]
    empty = joined[~joined["has_sales"]].sort_values(["target_paise", "month"],
                                                      ascending=[False, True])
    if empty.empty:
        return None
    total_target = int(empty["target_paise"].sum())
    examples_text = "; ".join(f"{month_label(r['month'])} / {r['region']} / {r['product']} "
                              f"({an.format_inr(r['target_paise'])} target)"
                              for _, r in empty.head(3).iterrows())
    n = len(empty)
    return Recommendation(
        rule="no_transactions",
        title=f"{n} planned group{'s' if n != 1 else ''} with no transactions",
        finding=(f"{n} of {len(joined)} planned month–region–product groups in this selection "
                 f"recorded zero transactions, so their targets count against ₹0.00 actual."),
        evidence=(("Groups with no transactions", f"{n} of {len(joined)}"),
                  ("Transactions in these groups", "0"),
                  ("Targets in these groups", an.format_inr(total_target)),
                  ("Largest", examples_text)),
        next_step=("Check order coverage for these groups and confirm that sales records are "
                   "complete. Possible explanations, such as no customer orders, a missing data "
                   "feed or a planning assumption that doesn't fit, are hypotheses to verify, "
                   "not conclusions."),
    )


def rule_channel_concentration(view):
    """Rule 4: one channel holds a large share of selected revenue (actuals only)."""
    sales = view["sales"]
    total = int(sales["revenue_paise"].sum())
    if total == 0 or sales["channel"].nunique() < 2:
        return None
    by_channel = (sales.groupby("channel", as_index=False)
                  .agg(actual_paise=("revenue_paise", "sum"),
                       transactions=("transaction_id", "count")))
    by_channel = by_channel.sort_values(["actual_paise", "channel"], ascending=[False, True])
    top = by_channel.iloc[0]
    share = int(top["actual_paise"]) / total
    if share < CHANNEL_SHARE_THRESHOLD:
        return None
    avg_order = int(round(int(top["actual_paise"]) / int(top["transactions"])))
    ranking = "; ".join(
        f"{r['channel']}: {an.format_inr(r['actual_paise'])}, {int(r['transactions'])} "
        f"txn{'s' if int(r['transactions']) != 1 else ''}, "
        f"avg {an.format_inr(int(round(int(r['actual_paise']) / int(r['transactions']))))}"
        for _, r in by_channel.iterrows())
    return Recommendation(
        rule="channel_concentration",
        title=f"Revenue concentrated in {top['channel']}",
        finding=(f"{top['channel']} accounts for {100 * share:.2f}% of selected net revenue. "
                 f"Channel target achievement is unavailable because the plan has no channel "
                 f"allocation."),
        evidence=(("Channel revenue", an.format_inr(top["actual_paise"])),
                  ("Share of selected revenue", f"{100 * share:.2f}%"),
                  ("Transactions", f"{int(top['transactions'])}"),
                  ("Average order value", an.format_inr(avg_order)),
                  ("All channels", ranking)),
        next_step=(f"Check how dependent the selected results are on {top['channel']}: review "
                   f"its largest orders and whether other channels' order counts or average "
                   f"order values are lower than expected."),
    )


RULES = (rule_largest_shortfall, rule_repeated_misses,
         rule_no_transaction_groups, rule_channel_concentration)


def build_recommendations(view, limit=MAX_RECOMMENDATIONS):
    """Apply the rules in order to the active view; return up to `limit` recommendations."""
    if view.get("empty"):
        return []
    results = []
    for rule in RULES:
        rec = rule(view)
        if rec is not None:
            results.append(rec)
        if len(results) == limit:
            break
    return results


def top_monthly_gaps(view, limit=5):
    """The largest below-plan month+region+product groups in scope (paise)."""
    joined = view["joined"].assign(shortfall_paise=lambda d: d["target_paise"] - d["actual_paise"])
    return (joined[joined["shortfall_paise"] > 0]
            .sort_values("shortfall_paise", ascending=False)
            .head(limit))
