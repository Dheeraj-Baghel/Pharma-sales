"""
analyze_sales.py  (Checkpoint 3)
--------------------------------
Pandas analysis of the SYNTHETIC PharmaSales Insight data.

What it does
    1. Opens data/pharma_sales.db READ-ONLY and loads `sales` and `sales_targets`.
    2. Shows row counts and data types, then validates the input. Any
       problem is reported clearly and the script stops (exit code 2).
    3. Converts every amount to whole PAISE (integers) before adding up.
    4. Adds up sales per month + region + product, then left-merges those
       actuals onto the 360-row plan (one plan row per group).
    5. Builds monthly, regional and product summaries, plus month-over-month
       growth.
    6. Verifies every number against the Checkpoint 2 SQL reports. Any
       mismatch is listed with its key and metric (exit code 1).

Run from the project root:
    python src/analyze_sales.py

All results describe a FICTIONAL dataset; they are not real business findings.
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from config import DATA_DIR, DB_NAME, PROJECT_ROOT
from validate_data import as_number, is_blank, run_sales_checks, run_target_checks

DB_PATH = DATA_DIR / DB_NAME
SQL_REPORTS_DIR = PROJECT_ROOT / "sql" / "analysis"

# The three columns that identify one plan group.
KEYS = ["month", "region", "product"]

SALES_REQUIRED = ["transaction_id", "date", "region", "product", "revenue"]
TARGETS_REQUIRED = ["target_month", "region", "product", "target_net_revenue"]

# Reference values reviewed at Checkpoint 2 (paise). Used only for verification.
EXPECTED = {
    "months": 12,
    "regions": 5,
    "products": 6,
    "joined_groups": 360,
    "groups_without_sales": 26,
    "actual_paise": 810_786_443,      # ₹81,07,864.43
    "plan_paise": 836_033_472,        # ₹83,60,334.72
    "shortfall_paise": 25_247_029,    # ₹2,52,470.29
}

EXIT_OK, EXIT_VERIFICATION_FAILED, EXIT_INVALID_INPUT = 0, 1, 2


class InputValidationError(Exception):
    """Raised when input data is not safe to analyse. The message explains why."""


# ===========================================================================
# 1. Loading (read-only)
# ===========================================================================
def open_read_only(db_path=DB_PATH):
    """
    Open SQLite in read-only mode. "mode=ro" makes SQLite itself refuse any
    change, so this script cannot alter the database even by accident.
    """
    db_path = Path(db_path).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    return sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)


def load_tables(conn):
    """Load both tables into DataFrames (tables held in Python memory)."""
    sales = pd.read_sql_query("SELECT * FROM sales ORDER BY transaction_id", conn)
    targets = pd.read_sql_query(
        "SELECT * FROM sales_targets ORDER BY target_month, region, product", conn)
    return sales, targets


def describe_inputs(sales, targets):
    """Print row counts and data types, as loaded from SQLite."""
    for name, df in [("sales", sales), ("sales_targets", targets)]:
        print(f"\n{name}: {len(df)} rows, {len(df.columns)} columns")
        for column, dtype in df.dtypes.items():
            print(f"    {column:<20} {dtype}")
    print("\nNote: SQLite returns dates as text ('object'). They are parsed "
          "explicitly with a fixed format before use.")


# ===========================================================================
# 2. Validation
# ===========================================================================
def examples(values, limit=3):
    """Short preview of problem values for error messages."""
    values = list(values)
    shown = ", ".join(repr(v) for v in values[:limit])
    return shown + (", ..." if len(values) > limit else "")


def check_analysis_inputs(sales, targets):
    """
    The checks this analysis depends on. Returns a list of problem messages
    (empty list = OK). Works on small test tables as well as the real data.

    Missing values in the SOURCE data are errors. (Groups with no sales,
    created later by the merge, are a different, expected case.)
    """
    problems = []

    for name, df, required in [("sales", sales, SALES_REQUIRED),
                               ("sales_targets", targets, TARGETS_REQUIRED)]:
        missing_columns = [c for c in required if c not in df.columns]
        if missing_columns:
            problems.append(f"{name}: missing required column(s) {missing_columns}")
            continue
        for column in required:
            blank = is_blank(df[column])
            if blank.any():
                problems.append(f"{name}.{column}: {int(blank.sum())} missing/blank value(s) "
                                f"in source rows {examples(df.index[blank])}")
    if problems:
        return problems   # later checks need these columns to exist and be filled

    # Duplicate keys
    dup_ids = sales["transaction_id"].duplicated(keep=False)
    if dup_ids.any():
        problems.append(f"sales.transaction_id: duplicate IDs "
                        f"{examples(sales.loc[dup_ids, 'transaction_id'].unique())}")
    target_keys = ["target_month", "region", "product"]
    dup_targets = targets.duplicated(target_keys, keep=False)
    if dup_targets.any():
        keys = targets.loc[dup_targets, target_keys].drop_duplicates()
        problems.append(f"sales_targets: duplicate month+region+product keys "
                        f"{examples(keys.itertuples(index=False, name=None))}")

    # Explicit date parsing with a fixed format. errors="coerce" turns
    # anything invalid into NaT ("not a time") so it can be reported.
    dates = pd.to_datetime(sales["date"].astype(str), format="%Y-%m-%d", errors="coerce")
    if dates.isna().any():
        problems.append(f"sales.date: invalid YYYY-MM-DD date(s) "
                        f"{examples(sales.loc[dates.isna(), 'date'])}")
    months = pd.to_datetime(targets["target_month"].astype(str), format="%Y-%m", errors="coerce")
    if months.isna().any():
        problems.append(f"sales_targets.target_month: invalid YYYY-MM month(s) "
                        f"{examples(targets.loc[months.isna(), 'target_month'])}")

    # Money must be finite numbers and not negative.
    for name, df, column in [("sales", sales, "revenue"),
                             ("sales_targets", targets, "target_net_revenue")]:
        values = as_number(df[column])
        bad = ~np.isfinite(values) | (values < 0)
        if bad.any():
            problems.append(f"{name}.{column}: not a finite, non-negative amount "
                            f"{examples(df.loc[bad, column])}")
    return problems


def validate_inputs(sales, targets):
    """
    Full validation for the real database: the analysis checks above plus
    every Checkpoint 1 rule from validate_data.py (reused, not copied).
    """
    problems = check_analysis_inputs(sales, targets)
    for table, results in [("sales", run_sales_checks(sales)),
                           ("sales_targets", run_target_checks(targets))]:
        for check_name, passed, detail in results:
            if not passed:
                problems.append(f"{table}: {check_name} - {detail}")
    return problems


# ===========================================================================
# 3. Money in paise
# ===========================================================================
def to_paise(amounts):
    """
    Convert INR amounts to whole paise integers, e.g. 0.10 -> 10, 0.70 -> 70.

    Why: decimals are stored approximately, so 0.10 + 0.70 = 0.7999999999999999
    (less than 0.80). Integers add up exactly: 10 + 70 = 80.
    Stored amounts are already whole paise, so rounding only removes that
    tiny storage noise; it never changes a real value.
    """
    values = pd.to_numeric(amounts, errors="raise").astype(float)
    return np.round(values * 100).astype("int64")


def format_inr(paise):
    """Paise -> Indian-style rupees text, e.g. 810786443 -> '₹81,07,864.43'."""
    if pd.isna(paise):
        return "n/a"
    paise = int(paise)
    sign = "-" if paise < 0 else ""
    rupees, remainder = divmod(abs(paise), 100)
    digits = str(rupees)
    if len(digits) > 3:
        # Indian grouping: last 3 digits, then groups of 2 (81,07,864).
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return f"{sign}₹{digits}.{remainder:02d}"


def format_pct(value):
    return "n/a" if pd.isna(value) else f"{value:.2f}"


# ===========================================================================
# 4. Aggregate, merge, summarise
# ===========================================================================
def prepare(sales, targets):
    """Parse dates/months explicitly and add paise columns (on copies)."""
    sales = sales.copy()
    sales["date"] = pd.to_datetime(sales["date"].astype(str), format="%Y-%m-%d")
    sales["month"] = sales["date"].dt.strftime("%Y-%m")       # '2025-01-15' -> '2025-01'
    sales["revenue_paise"] = to_paise(sales["revenue"])

    targets = targets.copy()
    parsed = pd.to_datetime(targets["target_month"].astype(str), format="%Y-%m")
    targets["month"] = parsed.dt.strftime("%Y-%m")
    targets["target_paise"] = to_paise(targets["target_net_revenue"])
    return sales, targets


def aggregate_actuals(sales):
    """One row per month + region + product: total paise and number of sales."""
    return (sales
            .groupby(KEYS, as_index=False)
            .agg(actual_paise=("revenue_paise", "sum"),
                 transaction_count=("transaction_id", "count")))


def join_plan_and_actuals(targets, actuals):
    """
    Start from the plan and LEFT-merge the actuals on all three keys.
    validate="one_to_one" makes Pandas raise an error if either side has
    more than one row for a key, so a target can never be counted twice.
    """
    # Every group with sales must have a plan row; otherwise its revenue
    # would silently vanish from the target reports.
    check = actuals[KEYS].merge(targets[KEYS], on=KEYS, how="left", indicator=True)
    orphans = check[check["_merge"] == "left_only"]
    if not orphans.empty:
        raise InputValidationError(
            f"{len(orphans)} month+region+product group(s) have sales but no target, e.g. "
            f"{examples(orphans[KEYS].itertuples(index=False, name=None))}")

    try:
        joined = targets[KEYS + ["target_paise"]].merge(
            actuals, on=KEYS, how="left", validate="one_to_one", indicator="match")
    except pd.errors.MergeError as error:
        raise InputValidationError(f"Plan/actuals merge is not one-to-one: {error}") from error

    # A missing actual here means "this planned group had no sales" -
    # a normal business case, kept visible in has_sales before filling zeros.
    joined["has_sales"] = joined["match"].eq("both")
    joined["actual_paise"] = joined["actual_paise"].fillna(0).astype("int64")
    joined["transaction_count"] = joined["transaction_count"].fillna(0).astype("int64")
    return joined.drop(columns="match")


def achievement_pct(actual_paise, plan_paise):
    """100 x total actual / total plan; unavailable (NaN) when plan is zero."""
    return 100 * actual_paise / plan_paise.where(plan_paise != 0)


def summarize(joined, by):
    """Roll the joined groups up to one row per value of `by`."""
    joined = joined.assign(no_sales=~joined["has_sales"])
    summary = (joined
               .groupby(by, as_index=False)
               .agg(groups=("target_paise", "size"),
                    groups_without_sales=("no_sales", "sum"),
                    transaction_count=("transaction_count", "sum"),
                    actual_paise=("actual_paise", "sum"),
                    plan_paise=("target_paise", "sum")))
    summary["shortfall_paise"] = summary["plan_paise"] - summary["actual_paise"]
    summary["achievement_pct"] = achievement_pct(summary["actual_paise"], summary["plan_paise"])
    # Exact integer comparison: a tie is at plan; 1 paisa short is below plan.
    summary["status"] = np.where(summary["actual_paise"] < summary["plan_paise"],
                                 "Below plan", "At or above plan")
    return summary


def monthly_summary(joined):
    """Monthly summary in calendar order, with month-over-month growth."""
    monthly = summarize(joined, "month")
    monthly = monthly.sort_values(
        "month", key=lambda m: pd.to_datetime(m, format="%Y-%m")).reset_index(drop=True)

    previous = monthly["actual_paise"].shift(1)        # last month's actual (NaN for the first)
    change = monthly["actual_paise"] - previous
    monthly["growth_paise"] = change.astype("Int64")   # Int64 = integer that allows <NA>
    # Percentage only when last month had revenue; otherwise unavailable.
    monthly["growth_pct"] = 100 * change / previous.where(previous != 0)
    return monthly


def run_analysis(sales, targets):
    """Validate, prepare, merge and summarise. Returns a dict of DataFrames."""
    problems = check_analysis_inputs(sales, targets)
    if problems:
        raise InputValidationError("\n".join(problems))
    sales, targets = prepare(sales, targets)
    joined = join_plan_and_actuals(targets, aggregate_actuals(sales))
    return {
        "joined": joined,
        "monthly": monthly_summary(joined),
        "regional": summarize(joined, "region"),
        "product": summarize(joined, "product"),
    }


# ===========================================================================
# 5. Display
# ===========================================================================
def print_summary(title, summary, key, growth=False):
    table = pd.DataFrame({
        key.capitalize(): summary[key],
        "Txns": summary["transaction_count"],
        "Actual": summary["actual_paise"].map(format_inr),
        "Plan": summary["plan_paise"].map(format_inr),
        "Shortfall": summary["shortfall_paise"].map(format_inr),
        "Achieve %": summary["achievement_pct"].map(format_pct),
        "Status": summary["status"],
    })
    if growth:
        table["Growth"] = summary["growth_paise"].map(format_inr)
        table["Growth %"] = summary["growth_pct"].map(format_pct)
    print(f"\n{title}")
    print("-" * len(title))
    print(table.to_string(index=False))


def print_results(results):
    joined = results["joined"]
    print(f"\nJoined plan groups: {len(joined)}  "
          f"(with sales: {int(joined['has_sales'].sum())}, "
          f"planned but no sales: {int((~joined['has_sales']).sum())} -> actual set to ₹0.00)")
    print_summary("Monthly summary (calendar order)", results["monthly"], "month", growth=True)
    regional = results["regional"].sort_values("achievement_pct")
    print_summary("Regional summary (lowest achievement first)", regional, "region")
    product = results["product"].sort_values("actual_paise", ascending=False)
    print_summary("Product summary (highest revenue first)", product, "product")
    print("\nShortfall = plan - actual (positive = below plan). "
          "Achievement = 100 x total actual / total plan.")


# ===========================================================================
# 6. Verification against SQL
# ===========================================================================
PRODUCT_PLAN_SQL = """
-- Independent product check: plan and actuals summed separately, in paise.
WITH plan AS (
    SELECT product, SUM(CAST(ROUND(target_net_revenue * 100) AS INTEGER)) AS plan_paise
    FROM sales_targets
    GROUP BY product
),
actual AS (
    SELECT product, SUM(CAST(ROUND(revenue * 100) AS INTEGER)) AS actual_paise
    FROM sales
    GROUP BY product
)
SELECT
    p.product,
    COALESCE(a.actual_paise, 0)                                        AS actual_paise,
    p.plan_paise,
    p.plan_paise - COALESCE(a.actual_paise, 0)                         AS shortfall_paise,
    ROUND(100.0 * COALESCE(a.actual_paise, 0) / NULLIF(p.plan_paise, 0), 2) AS achievement_pct
FROM plan AS p
LEFT JOIN actual AS a ON a.product = p.product
ORDER BY p.product
"""

SOURCE_TOTALS_SQL = """
SELECT
    (SELECT SUM(CAST(ROUND(revenue * 100) AS INTEGER)) FROM sales)                    AS actual_paise,
    (SELECT SUM(CAST(ROUND(target_net_revenue * 100) AS INTEGER)) FROM sales_targets) AS plan_paise
"""


def run_sql_report(conn, filename):
    """Run one existing Checkpoint 2 report file (read-only connection)."""
    return pd.read_sql_query((SQL_REPORTS_DIR / filename).read_text(), conn)


def inr_to_paise(values):
    """SQL display values (INR, 2 decimals) -> paise, keeping missing values as <NA>."""
    return (pd.to_numeric(values).astype(float) * 100).round().astype("Int64")


def compare_rows(label, ours, sql, key, metrics, failures):
    """
    Compare two tables row by row, matched by `key`.
    metrics: list of (our_column, sql_column, kind), where kind is
        "paise" - exact integer match (SQL value given in paise)
        "pct"   - our value rounded to 2 decimals vs SQL's 2-decimal value
        "exact" - equal as-is (counts, text)
    Each mismatch is added to `failures` as "label [key] metric: ...".
    """
    ours = ours.set_index(key)
    sql = sql.set_index(key)
    for missing in sorted(set(sql.index) - set(ours.index)):
        failures.append(f"{label} [{missing}]: present in SQL, missing in Pandas")
    for extra in sorted(set(ours.index) - set(sql.index)):
        failures.append(f"{label} [{extra}]: present in Pandas, missing in SQL")

    for row_key in sorted(set(ours.index) & set(sql.index)):
        for our_col, sql_col, kind in metrics:
            a, b = ours.at[row_key, our_col], sql.at[row_key, sql_col]
            if pd.isna(a) or pd.isna(b):
                same = pd.isna(a) and pd.isna(b)      # both unavailable = match
            elif kind == "paise":
                same = int(a) == int(b)
            elif kind == "pct":
                same = abs(round(float(a), 2) - float(b)) < 1e-9
            else:
                same = a == b
            if not same:
                shown_a = round(float(a), 2) if kind == "pct" and not pd.isna(a) else a
                failures.append(f"{label} [{row_key}] {our_col}: pandas={shown_a!r} sql={b!r}")


def verify_against_sql(conn, results):
    """Return a list of failure messages (empty list = everything matches)."""
    failures = []
    monthly, regional, product = results["monthly"], results["regional"], results["product"]
    joined = results["joined"]

    # --- Monthly vs report 05 (values, growth and order) -------------------
    r05 = run_sql_report(conn, "05_monthly_revenue_vs_plan.sql")
    for column in ["actual_revenue_inr", "planned_net_revenue_inr", "shortfall_inr",
                   "change_vs_prev_month_inr"]:
        r05[column] = inr_to_paise(r05[column])
    compare_rows("monthly vs report 05", monthly, r05, "month", [
        ("transaction_count", "transaction_count", "exact"),
        ("actual_paise", "actual_revenue_inr", "paise"),
        ("plan_paise", "planned_net_revenue_inr", "paise"),
        ("shortfall_paise", "shortfall_inr", "paise"),
        ("achievement_pct", "achievement_pct", "pct"),
        ("growth_paise", "change_vs_prev_month_inr", "paise"),
        ("growth_pct", "change_vs_prev_month_pct", "pct"),
    ], failures)
    if list(monthly["month"]) != list(r05["month"]):
        failures.append(f"monthly order: pandas={list(monthly['month'])} sql={list(r05['month'])}")

    # --- Regional vs report 03 ---------------------------------------------
    r03 = run_sql_report(conn, "03_region_target_achievement.sql")
    for column in ["actual_revenue_inr", "planned_net_revenue_inr", "shortfall_inr"]:
        r03[column] = inr_to_paise(r03[column])
    compare_rows("regional vs report 03", regional, r03, "region", [
        ("actual_paise", "actual_revenue_inr", "paise"),
        ("plan_paise", "planned_net_revenue_inr", "paise"),
        ("shortfall_paise", "shortfall_inr", "paise"),
        ("achievement_pct", "achievement_pct", "pct"),
        ("status", "status", "exact"),
    ], failures)

    # --- Products: actuals vs report 04, plan via independent SQL ----------
    r04 = run_sql_report(conn, "04_product_revenue_share.sql")
    r04["net_revenue_inr"] = inr_to_paise(r04["net_revenue_inr"])
    compare_rows("product actuals vs report 04", product, r04, "product", [
        ("transaction_count", "transaction_count", "exact"),
        ("actual_paise", "net_revenue_inr", "paise"),
    ], failures)
    independent = pd.read_sql_query(PRODUCT_PLAN_SQL, conn)
    compare_rows("product plan vs independent SQL", product, independent, "product", [
        ("actual_paise", "actual_paise", "paise"),
        ("plan_paise", "plan_paise", "paise"),
        ("shortfall_paise", "shortfall_paise", "paise"),
        ("achievement_pct", "achievement_pct", "pct"),
    ], failures)

    # --- Below-plan lists vs report 08 -------------------------------------
    r08 = run_sql_report(conn, "08_annual_target_misses.sql")
    for level, summary, key in [("Product", product, "product"), ("Region", regional, "region")]:
        ours = set(summary.loc[summary["status"] == "Below plan", key])
        sql = set(r08.loc[r08["level"] == level, "name"])
        if ours != sql:
            failures.append(f"below-plan {key}s vs report 08: pandas={sorted(ours)} sql={sorted(sql)}")

    # --- Counts --------------------------------------------------------------
    counts = {
        "months": len(monthly),
        "regions": len(regional),
        "products": len(product),
        "joined_groups": len(joined),
        "groups_without_sales": int((~joined["has_sales"]).sum()),
    }
    for name, value in counts.items():
        if value != EXPECTED[name]:
            failures.append(f"count [{name}]: pandas={value} expected={EXPECTED[name]}")
    if joined.duplicated(KEYS).any():
        failures.append("joined groups: duplicate month+region+product keys")

    # --- Totals: every summary must reconcile to the source tables ----------
    source = pd.read_sql_query(SOURCE_TOTALS_SQL, conn).iloc[0]
    reference = {
        "actual_paise": (int(source["actual_paise"]), EXPECTED["actual_paise"]),
        "plan_paise": (int(source["plan_paise"]), EXPECTED["plan_paise"]),
        "shortfall_paise": (int(source["plan_paise"] - source["actual_paise"]),
                            EXPECTED["shortfall_paise"]),
    }
    for metric, (from_source, expected) in reference.items():
        if from_source != expected:
            failures.append(f"source total [{metric}]: sql={from_source} expected={expected}")
        for name, summary in [("joined", joined.rename(columns={"target_paise": "plan_paise"})
                               .assign(shortfall_paise=lambda d: d.plan_paise - d.actual_paise)),
                              ("monthly", monthly), ("regional", regional), ("product", product)]:
            total = int(summary[metric].sum())
            if total != from_source:
                failures.append(f"{name} total [{metric}]: pandas={total} source={from_source}")
    return failures


# ===========================================================================
# Main
# ===========================================================================
def main(db_path=DB_PATH):
    print("=" * 78)
    print("PharmaSales Insight - Pandas analysis (Checkpoint 3)   SYNTHETIC data")
    print("=" * 78)

    try:
        conn = open_read_only(db_path)
    except FileNotFoundError as error:
        print(f"\nINVALID INPUT: {error}")
        return EXIT_INVALID_INPUT

    try:
        sales, targets = load_tables(conn)
        describe_inputs(sales, targets)

        problems = validate_inputs(sales, targets)
        if problems:
            print("\nINVALID INPUT - analysis stopped:")
            for problem in problems:
                print(f"  - {problem}")
            return EXIT_INVALID_INPUT
        print("\nInput validation: PASS (Checkpoint 1 rules + analysis checks)")

        try:
            results = run_analysis(sales, targets)
        except InputValidationError as error:
            print(f"\nINVALID INPUT - analysis stopped:\n  - {error}")
            return EXIT_INVALID_INPUT

        print_results(results)

        failures = verify_against_sql(conn, results)
        print("\nVerification against SQL reports 03, 04, 05, 08 + independent SQL")
        print("-" * 66)
        if failures:
            for failure in failures:
                print(f"  [FAIL] {failure}")
            print(f"\nRESULT: VERIFICATION FAILED ({len(failures)} problem(s))")
            return EXIT_VERIFICATION_FAILED
        t = results["monthly"]
        print(f"  [PASS] Monthly (12), regional (5) and product (6) rows match SQL "
              f"by key: paise exact, percentages to 2 decimals")
        print(f"  [PASS] Growth values and unavailable values match report 05")
        print(f"  [PASS] Below-plan products and regions match report 08")
        print(f"  [PASS] 360 joined groups, 26 without sales")
        print(f"  [PASS] Every summary reconciles: actual {format_inr(t['actual_paise'].sum())}, "
              f"plan {format_inr(t['plan_paise'].sum())}, "
              f"shortfall {format_inr(t['shortfall_paise'].sum())}")
        print("\nRESULT: ALL VERIFICATION CHECKS PASSED")
        return EXIT_OK
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
