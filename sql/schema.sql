-- =====================================================================
-- PharmaSales Insight - database schema
-- All data in these tables is SYNTHETIC and FICTIONAL.
--
-- Two tables with different "grains" (what one row means):
--   sales          one row per transaction
--   sales_targets  one row per month + region + product (the target plan)
--
-- The CHECK rules are a second line of defence after Python validation.
-- SQLite quirks these rules are written around:
--   * A CHECK whose result is NULL counts as PASSED, so every rule that
--     could produce NULL tests "IS NOT NULL" explicitly.
--   * A TEXT PRIMARY KEY does NOT forbid NULL by itself, so NOT NULL is added.
--   * Declaring a column INTEGER does not stop 1.5 or 'many' being stored,
--     so typeof() is checked.
--   * "< 1e15" rejects infinity (SQLite stores NaN as NULL, which NOT NULL rejects).
--
-- Only these two tables are dropped and recreated. Any other table you
-- add to the database yourself is left alone.
-- Keep the allowed names below in sync with src/config.py.
-- =====================================================================

DROP TABLE IF EXISTS sales;
DROP TABLE IF EXISTS sales_targets;

CREATE TABLE sales (
    transaction_id  TEXT NOT NULL PRIMARY KEY
        CHECK (typeof(transaction_id) = 'text'
               AND transaction_id GLOB 'TXN-[0-9][0-9][0-9][0-9][0-9]'),

    -- Real calendar date in YYYY-MM-DD form, inside 2025.
    -- date('hello') and date('2025-13-01') return NULL, hence IS NOT NULL.
    date            TEXT NOT NULL
        CHECK (typeof(date) = 'text'
               AND date(date) IS NOT NULL
               AND date(date) = date
               AND date BETWEEN '2025-01-01' AND '2025-12-31'),

    region          TEXT NOT NULL
        CHECK (region IN ('North', 'South', 'East', 'West', 'Central')),

    product         TEXT NOT NULL
        CHECK (product IN ('Cardiozen 10mg', 'Glucobal 500mg', 'Respiclear Inhaler',
                           'Infecta-Guard 250mg', 'Hydralyte-Plus ORS', 'Neurocalm 50mg')),

    sales_rep       TEXT NOT NULL,

    channel         TEXT NOT NULL
        CHECK (channel IN ('Hospital', 'Retail Pharmacy', 'Clinic', 'Distributor')),

    units_sold      INTEGER NOT NULL
        CHECK (typeof(units_sold) = 'integer' AND units_sold > 0),

    unit_price      REAL NOT NULL                        -- INR per unit
        CHECK (typeof(unit_price) = 'real' AND unit_price > 0 AND unit_price < 1e15),

    discount_pct    REAL NOT NULL                        -- 0.10 means 10%
        CHECK (typeof(discount_pct) = 'real' AND discount_pct BETWEEN 0 AND 1),

    -- LEGACY order benchmark (gross, before discount). Kept for compatibility.
    -- NOT used for target-achievement KPIs: use sales_targets instead.
    target_revenue  REAL NOT NULL
        CHECK (typeof(target_revenue) = 'real' AND target_revenue > 0 AND target_revenue < 1e15),

    -- Actual net revenue = units_sold * unit_price * (1 - discount_pct),
    -- rounded to whole paise (so at most 0.005 away from the exact formula).
    revenue         REAL NOT NULL
        CHECK (typeof(revenue) = 'real' AND revenue >= 0 AND revenue < 1e15
               AND abs(revenue - units_sold * unit_price * (1 - discount_pct)) <= 0.005000001
               AND abs(revenue * 100 - round(revenue * 100)) < 0.000001),

    -- Each rep may only appear in their own region.
    CHECK (   (region = 'North'   AND sales_rep IN ('Aarav Mehta', 'Simran Kaur'))
           OR (region = 'South'   AND sales_rep IN ('Karthik Iyer', 'Lakshmi Nair'))
           OR (region = 'West'    AND sales_rep IN ('Rohan Desai', 'Priya Joshi'))
           OR (region = 'East'    AND sales_rep IN ('Arjun Bose', 'Ananya Das'))
           OR (region = 'Central' AND sales_rep IN ('Vikram Tiwari', 'Neha Verma')))
);

CREATE TABLE sales_targets (
    target_month        TEXT NOT NULL                    -- 'YYYY-MM', e.g. '2025-01'
        CHECK (typeof(target_month) = 'text'
               AND target_month GLOB '2025-[01][0-9]'
               AND target_month BETWEEN '2025-01' AND '2025-12'),

    region              TEXT NOT NULL
        CHECK (region IN ('North', 'South', 'East', 'West', 'Central')),

    product             TEXT NOT NULL
        CHECK (product IN ('Cardiozen 10mg', 'Glucobal 500mg', 'Respiclear Inhaler',
                           'Infecta-Guard 250mg', 'Hydralyte-Plus ORS', 'Neurocalm 50mg')),

    -- Expected (average) number of orders; may be fractional, e.g. 1.37.
    planned_orders      REAL NOT NULL
        CHECK (typeof(planned_orders) = 'real' AND planned_orders > 0 AND planned_orders < 1e15),

    -- Planned NET revenue (after expected discounts), INR.
    target_net_revenue  REAL NOT NULL
        CHECK (typeof(target_net_revenue) = 'real'
               AND target_net_revenue > 0 AND target_net_revenue < 1e15),

    -- One row per month + region + product. (That ALL 360 rows exist is
    -- checked by Python; SQLite cannot check "completeness".)
    PRIMARY KEY (target_month, region, product)
);

-- Indexes speed up filtering/grouping later.
CREATE INDEX idx_sales_date    ON sales (date);
CREATE INDEX idx_sales_region  ON sales (region);
CREATE INDEX idx_sales_product ON sales (product);
