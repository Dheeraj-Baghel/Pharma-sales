"""
validate_data.py
----------------
Checks the PharmaSales Insight data for quality problems and prints a clear
PASS/FAIL report. All data checked here is SYNTHETIC (fictional).

It validates FOUR stored copies:
    1. data/pharma_sales.csv     (transactions)
    2. sales table in data/pharma_sales.db
    3. data/sales_targets.csv    (monthly target plan)
    4. sales_targets table in data/pharma_sales.db
and then confirms each CSV matches its database table.

Design rule: a check must never CRASH on bad data, and must never PASS bad
data. Bad values are reported, never deleted or "fixed" silently.

Run from the project root:
    python src/validate_data.py

generate_data.py imports these functions to validate data BEFORE saving it.
"""

import re
import sqlite3
import sys

import numpy as np
import pandas as pd

from config import (
    CHANNEL_NAMES,
    COPY_COMPARISON_ABS_TOLERANCE,
    DATA_DIR,
    DATA_YEAR,
    DB_NAME,
    PRODUCT_NAMES,
    PROJECT_ROOT,
    REGION_NAMES,
    REVENUE_ROUNDING_TOLERANCE,
    SALES_CSV_NAME,
    SALES_REPS,
    TARGETS_CSV_NAME,
)

SALES_CSV_PATH = DATA_DIR / SALES_CSV_NAME
TARGETS_CSV_PATH = DATA_DIR / TARGETS_CSV_NAME
DB_PATH = DATA_DIR / DB_NAME

# --- Column lists -----------------------------------------------------------
SALES_TEXT_COLUMNS = ["transaction_id", "date", "region", "product", "sales_rep", "channel"]
SALES_NUMBER_COLUMNS = ["units_sold", "unit_price", "discount_pct", "target_revenue", "revenue"]
SALES_COLUMNS = SALES_TEXT_COLUMNS + SALES_NUMBER_COLUMNS   # all 11 are required

TARGET_TEXT_COLUMNS = ["target_month", "region", "product"]
TARGET_NUMBER_COLUMNS = ["planned_orders", "target_net_revenue"]
TARGET_COLUMNS = TARGET_TEXT_COLUMNS + TARGET_NUMBER_COLUMNS
TARGET_KEY = ["target_month", "region", "product"]          # one row per key

TRANSACTION_ID_PATTERN = r"TXN-\d{5}"
EXPECTED_TARGET_ROWS = 12 * len(REGION_NAMES) * len(PRODUCT_NAMES)  # 360


# ===========================================================================
# Small helpers
# ===========================================================================
def is_blank(series):
    """True for empty cells: NaN/None, or text that is empty after trimming."""
    missing = series.isna()
    empty_text = series.map(lambda v: isinstance(v, str) and v.strip() == "")
    return missing | empty_text


def as_number(series):
    """
    Convert a column to numbers WITHOUT crashing.
    Text like 'many' becomes NaN, so later checks can report it.
    """
    return pd.to_numeric(series, errors="coerce").astype(float)


def as_text(series):
    """Convert to text, keeping empty cells as None."""
    return series.map(lambda v: None if pd.isna(v) else str(v))


def show_rows(df, mask, column, limit=3):
    """Short example list of bad rows for the report, e.g. "row 4: 'many'"."""
    bad = df.loc[mask, column].head(limit)
    examples = ", ".join(f"row {i}: {v!r}" for i, v in bad.items())
    extra = "" if mask.sum() <= limit else ", ..."
    return f"{examples}{extra}"


def fail_or_pass(df, mask, column, fail_text, pass_text):
    """Shared PASS/FAIL message builder used by most checks."""
    count = int(mask.sum())
    if count:
        return False, f"{count} row(s) {fail_text} ({show_rows(df, mask, column)})"
    return True, pass_text


# ===========================================================================
# Generic checks (used for both tables)
# Each check returns (passed: bool, detail: str).
# ===========================================================================
def check_columns_present(df, columns):
    missing = [c for c in columns if c not in df.columns]
    if missing:
        return False, f"Missing columns: {missing}"
    return True, f"All {len(columns)} required columns present"


def check_no_blanks(df, columns):
    problems = {c: int(is_blank(df[c]).sum()) for c in columns}
    problems = {c: n for c, n in problems.items() if n}
    if problems:
        return False, f"Missing/blank values: {problems}"
    return True, "No missing or blank values in any required column"


def check_numbers_valid(df, columns):
    """Every numeric cell must be a real, finite number (not text, NaN or infinity)."""
    problems = {}
    for c in columns:
        values = as_number(df[c])
        present = ~is_blank(df[c])           # blanks are reported by check_no_blanks
        bad = present & ~np.isfinite(values)
        if bad.any():
            problems[c] = show_rows(df, bad, c, limit=2)
    if problems:
        return False, f"Not valid finite numbers: {problems}"
    return True, "All numeric values are valid finite numbers"


def check_positive(df, column):
    bad = as_number(df[column]) <= 0
    return fail_or_pass(df, bad, column, f"with {column} <= 0", f"All {column} > 0")


def check_allowed_values(df, column, allowed):
    text = as_text(df[column])
    bad = ~is_blank(df[column]) & ~text.isin(allowed)
    return fail_or_pass(df, bad, column, f"with unknown {column}",
                        f"All {column} values are in the allowed list ({len(allowed)})")


# ===========================================================================
# Sales-specific checks
# ===========================================================================
def check_transaction_ids(df):
    ids = as_text(df["transaction_id"])
    bad_format = ~is_blank(df["transaction_id"]) & ~ids.fillna("").str.fullmatch(TRANSACTION_ID_PATTERN)
    if bad_format.any():
        return fail_or_pass(df, bad_format, "transaction_id",
                            "with an ID not in TXN-00000 format", "")
    dupes = ids.notna() & ids.duplicated(keep=False)
    return fail_or_pass(df, dupes, "transaction_id", "sharing a duplicate transaction_id",
                        "Every transaction_id is unique and in TXN-00000 format")


def check_units_whole(df):
    units = as_number(df["units_sold"])
    bad = np.isfinite(units) & (units % 1 != 0)
    return fail_or_pass(df, bad, "units_sold", "with fractional units_sold",
                        "All units_sold are whole numbers")


def check_discount_range(df):
    discount = as_number(df["discount_pct"])
    bad = np.isfinite(discount) & ~discount.between(0, 1)
    return fail_or_pass(df, bad, "discount_pct", "with discount_pct outside 0-1",
                        "All discount_pct within 0-1")


def check_dates(df):
    """Dates must be real YYYY-MM-DD dates inside the data year."""
    text = as_text(df["date"])
    present = ~is_blank(df["date"])
    right_shape = text.fillna("").str.fullmatch(r"\d{4}-\d{2}-\d{2}")
    # errors="coerce": impossible dates such as 2025-02-30 become NaT.
    parsed = pd.to_datetime(text.where(right_shape), format="%Y-%m-%d", errors="coerce")
    invalid = present & parsed.isna()
    if invalid.any():
        return fail_or_pass(df, invalid, "date", "with an invalid date", "")
    wrong_year = present & (parsed.dt.year != DATA_YEAR)
    if wrong_year.any():
        return fail_or_pass(df, wrong_year, "date", f"with a date outside {DATA_YEAR}", "")
    if not present.any():
        return False, "No dates to check"
    return True, (f"All dates valid and in {DATA_YEAR} "
                  f"({parsed.min().date()} to {parsed.max().date()}, "
                  f"{parsed.dt.month.nunique()} distinct months)")


def check_rep_region(df):
    """Each sales rep must belong to the region on the same row."""
    pairs = list(zip(as_text(df["region"]), as_text(df["sales_rep"])))
    bad = pd.Series([rep not in SALES_REPS.get(region, []) for region, rep in pairs],
                    index=df.index)
    bad &= ~is_blank(df["sales_rep"]) & ~is_blank(df["region"])
    return fail_or_pass(df, bad, "sales_rep", "where the rep does not belong to the row's region",
                        "Every sales_rep belongs to their row's region")


def check_revenue(df):
    """revenue = units_sold * unit_price * (1 - discount_pct), rounded to whole paise."""
    units, price = as_number(df["units_sold"]), as_number(df["unit_price"])
    discount, revenue = as_number(df["discount_pct"]), as_number(df["revenue"])
    expected = units * price * (1 - discount)
    usable = np.isfinite(expected) & np.isfinite(revenue)   # others already reported

    if (usable & (revenue < 0)).any():
        return fail_or_pass(df, usable & (revenue < 0), "revenue", "with negative revenue", "")
    wrong = usable & ((revenue - expected).abs() > REVENUE_ROUNDING_TOLERANCE)
    if wrong.any():
        return fail_or_pass(df, wrong, "revenue",
                            "where revenue != units_sold * unit_price * (1 - discount_pct)", "")
    paise = revenue * 100
    not_rounded = usable & ((paise - paise.round()).abs() > 1e-6)
    return fail_or_pass(df, not_rounded, "revenue", "with revenue not rounded to whole paise",
                        "revenue matches the formula (rounded to paise) on every row")


# ===========================================================================
# Target-plan-specific checks
# ===========================================================================
def check_target_months(df):
    text = as_text(df["target_month"])
    valid = [f"{DATA_YEAR}-{m:02d}" for m in range(1, 13)]
    bad = ~is_blank(df["target_month"]) & ~text.isin(valid)
    return fail_or_pass(df, bad, "target_month",
                        f"with target_month not a YYYY-MM month in {DATA_YEAR}",
                        f"All target_month values are months of {DATA_YEAR}")


def check_target_keys_complete(df):
    """Exactly one row for every month + region + product combination."""
    keys = df[TARGET_KEY].apply(as_text)
    dupes = keys.duplicated(keep=False) & keys.notna().all(axis=1)
    if dupes.any():
        return fail_or_pass(df, dupes, "target_month",
                            "sharing a duplicate month+region+product", "")

    expected = {(f"{DATA_YEAR}-{m:02d}", r, p)
                for m in range(1, 13) for r in REGION_NAMES for p in PRODUCT_NAMES}
    actual = set(keys.itertuples(index=False, name=None))
    missing = sorted(expected - actual)
    if missing:
        return False, f"{len(missing)} combination(s) missing, e.g. {missing[:2]}"
    if len(df) != EXPECTED_TARGET_ROWS:
        return False, f"Expected {EXPECTED_TARGET_ROWS} rows, found {len(df)}"
    return True, f"All {EXPECTED_TARGET_ROWS} month+region+product combinations, each exactly once"


# ===========================================================================
# Run the checks
# ===========================================================================
def run_checks(df, columns, number_columns, checks):
    """
    Run a list of (name, function) checks. The column check runs first:
    if columns are missing, nothing else can be checked meaningfully.
    A safety net turns any unexpected error into a FAIL instead of a crash.
    """
    passed, detail = check_columns_present(df, columns)
    if not passed:
        return [("Required columns", False, detail)]

    results = [("Required columns", True, detail),
               ("No missing/blank values", *check_no_blanks(df, columns)),
               ("Numbers valid and finite", *check_numbers_valid(df, number_columns))]
    for name, check in checks:
        try:
            ok, detail = check(df)
        except Exception as error:   # should not happen; never crash the report
            ok, detail = False, f"Check could not run: {type(error).__name__}: {error}"
        results.append((name, ok, detail))
    return results


def run_sales_checks(df):
    checks = [
        ("Transaction IDs unique", check_transaction_ids),
        ("Units sold positive", lambda d: check_positive(d, "units_sold")),
        ("Units sold whole numbers", check_units_whole),
        ("Unit price positive", lambda d: check_positive(d, "unit_price")),
        ("Legacy target positive", lambda d: check_positive(d, "target_revenue")),
        ("Discount between 0 and 1", check_discount_range),
        (f"Dates valid and in {DATA_YEAR}", check_dates),
        ("Region allowed", lambda d: check_allowed_values(d, "region", REGION_NAMES)),
        ("Product allowed", lambda d: check_allowed_values(d, "product", PRODUCT_NAMES)),
        ("Channel allowed", lambda d: check_allowed_values(d, "channel", CHANNEL_NAMES)),
        ("Rep belongs to region", check_rep_region),
        ("Revenue formula correct", check_revenue),
    ]
    return run_checks(df, SALES_COLUMNS, SALES_NUMBER_COLUMNS, checks)


def run_target_checks(df):
    checks = [
        (f"Target months in {DATA_YEAR}", check_target_months),
        ("Region allowed", lambda d: check_allowed_values(d, "region", REGION_NAMES)),
        ("Product allowed", lambda d: check_allowed_values(d, "product", PRODUCT_NAMES)),
        ("Planned orders positive", lambda d: check_positive(d, "planned_orders")),
        ("Target revenue positive", lambda d: check_positive(d, "target_net_revenue")),
        ("All 360 combinations once", check_target_keys_complete),
    ]
    return run_checks(df, TARGET_COLUMNS, TARGET_NUMBER_COLUMNS, checks)


# ===========================================================================
# CSV vs database comparison
# ===========================================================================
def compare_frames(csv_df, db_df, key_columns):
    """
    Confirm two copies hold the same data.
    Text must match exactly. Numbers must match within an ABSOLUTE tolerance
    of 0.000001 with NO relative tolerance, so a 1-paisa change is caught.
    """
    if sorted(csv_df.columns) != sorted(db_df.columns):
        return False, f"Columns differ: CSV={list(csv_df.columns)}, DB={list(db_df.columns)}"
    if len(csv_df) != len(db_df):
        return False, f"Row counts differ: CSV={len(csv_df)}, DB={len(db_df)}"

    # Sort both copies the same way so row order can't cause a false mismatch.
    a = csv_df.astype({k: str for k in key_columns}).sort_values(key_columns).reset_index(drop=True)
    b = db_df.astype({k: str for k in key_columns}).sort_values(key_columns).reset_index(drop=True)

    for column in csv_df.columns:
        a_num, b_num = as_number(a[column]), as_number(b[column])
        is_numeric = a_num.notna().all() and b_num.notna().all()
        if is_numeric:
            diff = (a_num - b_num).abs()
            if not np.isfinite(diff).all() or diff.max() > COPY_COMPARISON_ABS_TOLERANCE:
                worst = int(diff.fillna(np.inf).idxmax())
                return False, (f"'{column}' differs, e.g. sorted row {worst}: "
                               f"CSV={a_num[worst]!r}, DB={b_num[worst]!r}")
        else:
            different = as_text(a[column]).fillna("<missing>") != as_text(b[column]).fillna("<missing>")
            if different.any():
                worst = int(different.idxmax())
                return False, (f"'{column}' differs, e.g. sorted row {worst}: "
                               f"CSV={a[column][worst]!r}, DB={b[column][worst]!r}")
    return True, (f"Identical ({len(csv_df)} rows; numbers within "
                  f"{COPY_COMPARISON_ABS_TOLERANCE:g} absolute, text exact)")


# ===========================================================================
# Loading and reporting
# ===========================================================================
def load_sales_csv(path):
    # Read text columns as text so e.g. an ID is never turned into a number.
    return pd.read_csv(path, dtype={c: str for c in SALES_TEXT_COLUMNS})


def load_targets_csv(path):
    return pd.read_csv(path, dtype={c: str for c in TARGET_TEXT_COLUMNS})


def print_report(title, results):
    """Print results as a readable table. Returns True if every check passed."""
    print(f"\n{title}")
    print("-" * len(title))
    for name, passed, detail in results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name:<28} {detail}")
    return all(passed for _, passed, _ in results)


def main():
    print("=" * 78)
    print("PharmaSales Insight - Data Validation Report  (SYNTHETIC data)")
    print("=" * 78)

    missing = [p for p in (SALES_CSV_PATH, TARGETS_CSV_PATH, DB_PATH) if not p.exists()]
    if missing:
        print("Missing files:", ", ".join(str(p.relative_to(PROJECT_ROOT)) for p in missing))
        print("Run first:  python src/generate_data.py")
        sys.exit(1)

    sales_csv = load_sales_csv(SALES_CSV_PATH)
    targets_csv = load_targets_csv(TARGETS_CSV_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        sales_db = pd.read_sql_query("SELECT * FROM sales", conn)
        targets_db = pd.read_sql_query("SELECT * FROM sales_targets", conn)
    conn.close()

    outcomes = [
        print_report(f"Sales CSV ({len(sales_csv)} rows)", run_sales_checks(sales_csv)),
        print_report(f"Sales DB table ({len(sales_db)} rows)", run_sales_checks(sales_db)),
        print_report(f"Targets CSV ({len(targets_csv)} rows)", run_target_checks(targets_csv)),
        print_report(f"Targets DB table ({len(targets_db)} rows)", run_target_checks(targets_db)),
        print_report("CSV vs database consistency", [
            ("Sales CSV = sales table",
             *compare_frames(sales_csv, sales_db, ["transaction_id"])),
            ("Targets CSV = targets table",
             *compare_frames(targets_csv, targets_db, TARGET_KEY)),
        ]),
    ]

    all_ok = all(outcomes)
    print("\n" + "=" * 78)
    print("RESULT: ALL CHECKS PASSED" if all_ok else "RESULT: VALIDATION FAILED")
    print("=" * 78)
    sys.exit(0 if all_ok else 1)   # 0 = success, 1 = failure (useful for automation)


if __name__ == "__main__":
    main()
