"""
config.py
---------
One place for the project's settings and reference lists.

Both generate_data.py (which creates data) and validate_data.py (which checks
data) import from here, so the list of allowed regions, products, reps and
channels can never get out of sync between the two scripts.

All names and numbers are FICTIONAL. They describe how the synthetic data is
shaped and how the synthetic target plan is built; they are not findings.

IMPORTANT: the ORDER of entries in REGIONS, SALES_REPS, PRODUCTS and CHANNELS
must not change. The random generator walks through them in order, so
reordering would change every generated transaction.

If you change an allowed name here, also update the CHECK rules in
sql/schema.sql (the tests in tests/test_checkpoint1.py will warn you).
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# File locations
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"

SALES_CSV_NAME = "pharma_sales.csv"
TARGETS_CSV_NAME = "sales_targets.csv"
DB_NAME = "pharma_sales.db"

# ---------------------------------------------------------------------------
# Sales generation settings
# ---------------------------------------------------------------------------
RANDOM_SEED = 42          # fixed seed => the same "random" sales every run
NUM_RECORDS = 1000
DATA_YEAR = 2025
START_DATE = "2025-01-01"
END_DATE = "2025-12-31"   # 12 full months

# Regions: how often each appears (weight) and a size factor that scales
# order volume. Weights must add up to 1.
REGIONS = {
    #  name       weight  size factor
    "North":   (0.24, 1.15),
    "South":   (0.22, 1.10),
    "West":    (0.21, 1.05),
    "East":    (0.18, 0.85),
    "Central": (0.15, 0.80),
}

# Each region has two fictional sales reps. A rep only sells in their region.
SALES_REPS = {
    "North":   ["Aarav Mehta", "Simran Kaur"],
    "South":   ["Karthik Iyer", "Lakshmi Nair"],
    "West":    ["Rohan Desai", "Priya Joshi"],
    "East":    ["Arjun Bose", "Ananya Das"],
    "Central": ["Vikram Tiwari", "Neha Verma"],
}

# Monthly seasonality patterns (Jan .. Dec). 1.0 = an average month.
SEASONALITY = {
    "steady_growth": [0.85, 0.88, 0.91, 0.94, 0.97, 1.00, 1.02, 1.05, 1.07, 1.09, 1.10, 1.12],
    "winter_peak":   [1.40, 1.30, 1.05, 0.80, 0.65, 0.60, 0.70, 0.80, 0.95, 1.15, 1.30, 1.45],
    "monsoon_peak":  [0.75, 0.75, 0.80, 0.85, 0.95, 1.20, 1.45, 1.50, 1.30, 0.95, 0.80, 0.75],
    "flat":          [1.00, 0.98, 1.02, 1.00, 0.97, 1.01, 1.03, 0.99, 1.00, 1.02, 0.98, 1.00],
    "summer_peak":   [0.85, 0.90, 1.05, 1.25, 1.35, 1.20, 0.95, 0.90, 0.90, 0.95, 0.90, 0.85],
}

# Six fictional products:
#   list price per unit (INR), relative demand, how often it appears, seasonality.
PRODUCTS = {
    #  name                   price  demand  weight  seasonality
    "Cardiozen 10mg":        (185.0, 1.00,   0.20,   "steady_growth"),  # cardiovascular
    "Glucobal 500mg":        (95.0,  1.40,   0.20,   "flat"),           # diabetes
    "Respiclear Inhaler":    (420.0, 0.55,   0.15,   "winter_peak"),    # respiratory
    "Infecta-Guard 250mg":   (140.0, 1.10,   0.17,   "monsoon_peak"),   # anti-infective
    "Hydralyte-Plus ORS":    (35.0,  2.20,   0.13,   "summer_peak"),    # rehydration
    "Neurocalm 50mg":        (310.0, 0.70,   0.15,   "flat"),           # neurology
}

# Sales channels: how often each appears, typical order size (units),
# and the range of discount usually given (as a fraction: 0.10 = 10%).
CHANNELS = {
    #  name                weight  base units  discount range
    "Hospital":          (0.30,   60,         (0.05, 0.15)),
    "Retail Pharmacy":   (0.35,   25,         (0.00, 0.08)),
    "Clinic":            (0.15,   15,         (0.00, 0.05)),
    "Distributor":       (0.20,   120,        (0.10, 0.20)),
}

# LEGACY order benchmark (the old per-transaction `target_revenue` column).
# Kept only so the original 1,000 rows stay exactly the same. It is NOT used
# for target-achievement KPIs; use the sales_targets table instead.
LEGACY_TARGET_STRETCH_RANGE = (1.00, 1.15)

# ---------------------------------------------------------------------------
# Independent monthly target plan (table: sales_targets)
# One row per month + region + product = 12 x 5 x 6 = 360 rows.
# These are PLANNING ASSUMPTIONS made "before the year starts". They never
# look at the generated transactions.
# ---------------------------------------------------------------------------
TARGET_PLAN_SEED = 2025          # separate random stream: does not touch sales
PLANNED_ANNUAL_ORDERS = 1000     # orders the plan expects in the whole year
PLAN_STRETCH = 1.05              # plan asks for 5% more than the baseline
PLAN_ADJUSTMENT_RANGE = (0.95, 1.05)  # small +/-5% planner judgement per row
# The plan is FLAT through the year: each month gets a share of the annual
# plan proportional to its number of days. Seasonality is deliberately NOT
# planned, so seasonal products will run ahead of plan in peak months and
# behind it in quiet months. This is an intentional simplification.

# ---------------------------------------------------------------------------
# Validation policies
# ---------------------------------------------------------------------------
# Revenue is rounded to 2 decimals (whole paise). After rounding it can differ
# from the exact formula by at most half a paisa (0.005).
REVENUE_DECIMALS = 2
REVENUE_ROUNDING_TOLERANCE = 0.005 + 1e-9   # tiny extra for floating-point noise

# When comparing the CSV copy with the database copy, numbers must match to
# within 0.000001 (absolute). No relative tolerance is used, so even a
# one-paisa (0.01) difference is always detected.
COPY_COMPARISON_ABS_TOLERANCE = 1e-6

# Convenience lists used by validation.
REGION_NAMES = list(REGIONS)
PRODUCT_NAMES = list(PRODUCTS)
CHANNEL_NAMES = list(CHANNELS)
