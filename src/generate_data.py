"""
generate_data.py
----------------
Creates the SYNTHETIC (fictional) data for the PharmaSales Insight portfolio
project and saves it safely.

It produces two tables, each saved as a CSV file AND as a SQLite table:

    sales          one row per transaction        -> data/pharma_sales.csv
    sales_targets  one row per month+region+product -> data/sales_targets.csv
    (both tables also go into data/pharma_sales.db)

Nothing here is real company data. Product names, sales reps and all numbers
are invented. The settings in config.py only shape the random numbers and the
planning assumptions; they are NOT analytical findings.

Run from the project root:
    python src/generate_data.py
"""

import os
import shutil
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    CHANNELS,
    DATA_DIR,
    DATA_YEAR,
    DB_NAME,
    END_DATE,
    LEGACY_TARGET_STRETCH_RANGE,
    NUM_RECORDS,
    PLAN_ADJUSTMENT_RANGE,
    PLAN_STRETCH,
    PLANNED_ANNUAL_ORDERS,
    PRODUCTS,
    PROJECT_ROOT,
    RANDOM_SEED,
    REGIONS,
    REVENUE_DECIMALS,
    SALES_CSV_NAME,
    SALES_REPS,
    SCHEMA_PATH,
    SEASONALITY,
    START_DATE,
    TARGET_PLAN_SEED,
    TARGETS_CSV_NAME,
)
from validate_data import (
    compare_frames,
    load_sales_csv,
    load_targets_csv,
    print_report,
    run_sales_checks,
    run_target_checks,
)


# ===========================================================================
# PART 1 - Sales transactions
# WARNING: do not reorder the random draws in this function. Every draw from
# `rng` happens in a fixed order; changing that order (or removing a draw)
# would change all 1,000 transactions.
# ===========================================================================
def generate_sales_data(seed=RANDOM_SEED, n=NUM_RECORDS):
    """Build the synthetic transactions and return them as a pandas DataFrame."""

    # A random number generator with a fixed seed. Every random value below
    # comes from `rng`, so the whole dataset is reproducible.
    rng = np.random.default_rng(seed)

    # Give each rep a random performance factor (drawn once, from the seed).
    all_reps = [rep for reps in SALES_REPS.values() for rep in reps]
    rep_factor = dict(zip(all_reps, rng.uniform(0.88, 1.12, size=len(all_reps))))

    # --- Pick categories for all n rows at once ---------------------------
    # rng.choice picks n items, using the given probabilities (weights).
    region_names = list(REGIONS)
    regions = rng.choice(region_names, size=n, p=[REGIONS[r][0] for r in region_names])

    product_names = list(PRODUCTS)
    products = rng.choice(product_names, size=n, p=[PRODUCTS[p][2] for p in product_names])

    channel_names = list(CHANNELS)
    channels = rng.choice(channel_names, size=n, p=[CHANNELS[c][0] for c in channel_names])

    # A random day in the year for each row.
    all_days = pd.date_range(START_DATE, END_DATE, freq="D")
    dates = pd.to_datetime(rng.choice(all_days, size=n))

    # --- Build each row ---------------------------------------------------
    rows = []
    for i in range(n):
        region = regions[i]
        product = products[i]
        channel = channels[i]
        date = dates[i]

        # The rep must belong to the row's region.
        rep = rng.choice(SALES_REPS[region])

        list_price, demand, _, season_name = PRODUCTS[product]
        _, base_units, (disc_low, disc_high) = CHANNELS[channel]
        region_size = REGIONS[region][1]
        month_factor = SEASONALITY[season_name][date.month - 1]  # month 1 -> index 0

        # Expected units for this order = combination of all the factors.
        expected_units = (base_units * demand * region_size
                          * month_factor * rep_factor[rep])

        # Real orders vary around the expectation. A Poisson draw gives a
        # whole number near `expected_units`; max(1, ...) keeps it positive.
        units_sold = max(1, int(rng.poisson(expected_units)))

        # Negotiated price: list price +/- 3%, rounded to paise.
        unit_price = round(list_price * rng.uniform(0.97, 1.03), 2)

        # Discount depends on channel (distributors get bigger discounts).
        discount_pct = round(rng.uniform(disc_low, disc_high), 2)

        # LEGACY order benchmark (kept for compatibility, NOT used for KPIs).
        # It is a gross (pre-discount) benchmark for this kind of order.
        # This random draw must stay here so the sequence above is unchanged.
        planned_units = base_units * demand * region_size
        stretch = rng.uniform(*LEGACY_TARGET_STRETCH_RANGE)
        target_revenue = round(planned_units * list_price * stretch, 2)

        rows.append({
            "date": date.strftime("%Y-%m-%d"),
            "region": region,
            "product": product,
            "sales_rep": rep,
            "channel": channel,
            "units_sold": units_sold,
            "unit_price": unit_price,
            "discount_pct": discount_pct,
            "target_revenue": target_revenue,
        })

    df = pd.DataFrame(rows)

    # Sort by date so transaction IDs follow time order, then create IDs
    # like TXN-00001, TXN-00002, ... (zfill pads with zeros to 5 digits).
    df = df.sort_values(["date", "region", "product"]).reset_index(drop=True)
    df.insert(0, "transaction_id", ["TXN-" + str(i + 1).zfill(5) for i in range(len(df))])

    # Actual (net) revenue, using the required business formula, rounded to
    # whole paise. This line works on the whole column at once (no loop).
    df["revenue"] = (
        df["units_sold"] * df["unit_price"] * (1 - df["discount_pct"])
    ).round(REVENUE_DECIMALS)

    return df


# ===========================================================================
# PART 2 - Independent monthly target plan
# Uses its OWN random generator (TARGET_PLAN_SEED), so creating targets can
# never change the sales above. It never reads any sales transactions.
# ===========================================================================
def planned_net_order_value(region, product):
    """
    Planned average NET value (INR, after expected discount) of one order
    for this region and product, averaged over the planned channel mix.
    """
    list_price, demand, _, _ = PRODUCTS[product]
    region_size = REGIONS[region][1]

    value = 0.0
    for channel_weight, base_units, (disc_low, disc_high) in CHANNELS.values():
        planned_units = base_units * demand * region_size
        expected_discount = (disc_low + disc_high) / 2   # middle of the range
        value += channel_weight * planned_units * list_price * (1 - expected_discount)
    return value


def generate_target_plan(seed=TARGET_PLAN_SEED):
    """
    Build one target row for every month + region + product (12 x 5 x 6 = 360).

    target_net_revenue = planned orders in that month
                         x planned net value per order
                         x plan stretch
                         x small random planner adjustment (+/-5%)
    """
    rng = np.random.default_rng(seed)
    days_in_year = 366 if pd.Timestamp(f"{DATA_YEAR}-12-31").dayofyear == 366 else 365

    rows = []
    for month in range(1, 13):
        target_month = f"{DATA_YEAR}-{month:02d}"
        # Flat plan: a month's share of the year is proportional to its days.
        month_share = pd.Period(target_month).days_in_month / days_in_year

        for region, (region_weight, _) in REGIONS.items():
            for product, (_, _, product_weight, _) in PRODUCTS.items():
                planned_orders = (PLANNED_ANNUAL_ORDERS * region_weight
                                  * product_weight * month_share)
                adjustment = rng.uniform(*PLAN_ADJUSTMENT_RANGE)
                target = (planned_orders * planned_net_order_value(region, product)
                          * PLAN_STRETCH * adjustment)
                rows.append({
                    "target_month": target_month,
                    "region": region,
                    "product": product,
                    # Expected number of orders; can be fractional (e.g. 1.37)
                    # because it is an average expectation, not a count.
                    "planned_orders": round(planned_orders, 2),
                    "target_net_revenue": round(target, REVENUE_DECIMALS),
                })
    return pd.DataFrame(rows)


# ===========================================================================
# PART 3 - Safe saving
# Steps:  write everything to temporary files
#      -> read the temporary files back and validate them
#      -> back up the current files
#      -> swap the temporary files into place
#      -> if any swap fails, restore the backups
# The real files are only touched after the new ones are proven valid.
# ===========================================================================
def build_temp_database(temp_db, existing_db, sales_df, targets_df, schema_path):
    """Create the new database as a temporary file."""
    # Start from a COPY of the current database (if any), so other tables
    # you may have added yourself are kept. schema.sql only drops and
    # recreates the two tables this project owns: sales and sales_targets.
    if existing_db.exists():
        shutil.copy2(existing_db, temp_db)

    with sqlite3.connect(temp_db) as conn:
        conn.executescript(schema_path.read_text())
        # if_exists="append" inserts into OUR tables (with their CHECK rules)
        # instead of letting pandas invent tables without any rules.
        sales_df.to_sql("sales", conn, if_exists="append", index=False)
        targets_df.to_sql("sales_targets", conn, if_exists="append", index=False)
    # Note: `with` commits the changes; this closes the connection too.
    conn.close()


def validate_saved_outputs(sales_csv, targets_csv, db_path):
    """Read saved files back and validate them. Returns True if all is well."""
    sales_csv_df = load_sales_csv(sales_csv)
    targets_csv_df = load_targets_csv(targets_csv)
    with sqlite3.connect(db_path) as conn:
        sales_db_df = pd.read_sql_query("SELECT * FROM sales", conn)
        targets_db_df = pd.read_sql_query("SELECT * FROM sales_targets", conn)
    conn.close()

    results = [
        all(ok for _, ok, _ in run_sales_checks(sales_csv_df)),
        all(ok for _, ok, _ in run_sales_checks(sales_db_df)),
        all(ok for _, ok, _ in run_target_checks(targets_csv_df)),
        all(ok for _, ok, _ in run_target_checks(targets_db_df)),
        compare_frames(sales_csv_df, sales_db_df, ["transaction_id"])[0],
        compare_frames(targets_csv_df, targets_db_df,
                       ["target_month", "region", "product"])[0],
    ]
    return all(results)


def save_outputs(sales_df, targets_df, data_dir=DATA_DIR, schema_path=SCHEMA_PATH):
    """Save both tables to CSV + SQLite without risking the current files."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    finals = {
        "sales_csv": data_dir / SALES_CSV_NAME,
        "targets_csv": data_dir / TARGETS_CSV_NAME,
        "db": data_dir / DB_NAME,
    }
    temps = {key: path.with_name(path.name + ".tmp") for key, path in finals.items()}
    backups = {key: path.with_name(path.name + ".bak") for key, path in finals.items()}

    def remove(paths):
        for path in paths:
            if path.exists():
                path.unlink()

    remove(temps.values())  # clear leftovers from any earlier crash
    try:
        # 1. Write new outputs to temporary files.
        sales_df.to_csv(temps["sales_csv"], index=False)
        targets_df.to_csv(temps["targets_csv"], index=False)
        build_temp_database(temps["db"], finals["db"], sales_df, targets_df, schema_path)

        # 2. Validate the temporary files exactly as they were written.
        if not validate_saved_outputs(temps["sales_csv"], temps["targets_csv"], temps["db"]):
            raise RuntimeError("Temporary outputs failed validation.")
    except Exception:
        remove(temps.values())
        print("New outputs were NOT saved. Your existing files were not changed.")
        raise

    # 3. Back up the current files, then 4. swap the new ones into place.
    remove(backups.values())
    for key, final in finals.items():
        if final.exists():
            shutil.copy2(final, backups[key])
    try:
        for key, final in finals.items():
            os.replace(temps[key], final)  # replaces the file in one step
    except Exception:
        # 5. Something went wrong mid-swap: put every previous file back.
        for key, final in finals.items():
            if backups[key].exists():
                os.replace(backups[key], final)
            elif final.exists():
                final.unlink()  # file did not exist before this run
        remove(temps.values())
        print("Saving failed. The previous files were restored.")
        raise

    remove(backups.values())
    return finals


def main():
    print("Generating synthetic pharmaceutical data (fictional)...")
    sales_df = generate_sales_data()
    targets_df = generate_target_plan()

    # Validate in memory first. If anything fails, stop and save nothing.
    sales_ok = print_report("Pre-save checks: sales", run_sales_checks(sales_df))
    targets_ok = print_report("Pre-save checks: sales_targets", run_target_checks(targets_df))
    if not (sales_ok and targets_ok):
        raise SystemExit("Validation failed - data was NOT saved.")

    finals = save_outputs(sales_df, targets_df)
    print()
    print(f"Saved {finals['sales_csv'].relative_to(PROJECT_ROOT)}   ({len(sales_df)} rows)")
    print(f"Saved {finals['targets_csv'].relative_to(PROJECT_ROOT)}  ({len(targets_df)} rows)")
    print(f"Saved {finals['db'].relative_to(PROJECT_ROOT)}    "
          f"(tables 'sales' and 'sales_targets')")


if __name__ == "__main__":
    main()
