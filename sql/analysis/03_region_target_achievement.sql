-- =====================================================================
-- Q3. Which region has the lowest target achievement?
--     Actual revenue, planned net revenue, achievement % and shortfall (INR).
-- Data: SYNTHETIC / fictional. Plan = sales_targets.target_net_revenue
--       (NOT the legacy sales.target_revenue column).
--
-- The two tables have different GRAINS (what one row means):
--     sales          one row per transaction
--     sales_targets  one row per month + region + product (360 rows)
-- So we first make the sales data the SAME grain as the plan, then join.
--
-- MONEY AS WHOLE PAISE (integers)
--     Computers store decimals like 0.10 and 0.70 approximately, so
--     0.10 + 0.70 comes out as 0.7999999999999999, which is "less than" 0.80.
--     To avoid this, every stored amount is converted to whole paise FIRST:
--         CAST(ROUND(amount * 100) AS INTEGER)    0.10 -> 10, 0.70 -> 70
--     Integers add up exactly (10 + 70 = 80), so totals, comparisons and
--     status labels are exact. We divide by 100.0 only for display.
--
-- Step 1 (CTE monthly_actuals)
--     Add up revenue (in paise) per month + region + product.
--     SUBSTR(date, 1, 7) takes the first 7 characters of '2025-01-15' -> '2025-01'.
-- Step 2 (CTE plan_vs_actual)
--     Start FROM sales_targets (all 360 plan rows) and LEFT JOIN the
--     actuals on all three key columns. LEFT JOIN keeps every plan row even
--     when there were no sales; those rows get NULL actuals, which
--     COALESCE(..., 0) turns into 0.
-- Step 3 (CTE by_region + final SELECT)
--     Roll up to region in paise, then:
--       achievement % = 100 * SUM(actual) / SUM(target)   (ratio of totals,
--                       never an average of individual percentages)
--       shortfall     = target - actual  (positive = below plan)
--     NULLIF(x, 0) returns NULL instead of 0, so we can never divide by zero.
--     CASE WHEN compares the exact integer totals to choose a label.
--
-- A CTE ("WITH name AS (...)") is a named, temporary result that the rest
-- of the query can use like a table. It only exists while the query runs.
-- =====================================================================

WITH monthly_actuals AS (
    SELECT
        SUBSTR(date, 1, 7)                          AS sales_month,
        region,
        product,
        SUM(CAST(ROUND(revenue * 100) AS INTEGER))  AS actual_paise
    FROM sales
    GROUP BY SUBSTR(date, 1, 7), region, product
),

plan_vs_actual AS (
    SELECT
        t.target_month,
        t.region,
        t.product,
        CAST(ROUND(t.target_net_revenue * 100) AS INTEGER) AS target_paise,
        COALESCE(a.actual_paise, 0)                        AS actual_paise
    FROM sales_targets AS t
    LEFT JOIN monthly_actuals AS a
           ON  a.sales_month = t.target_month
           AND a.region      = t.region
           AND a.product     = t.product
),

by_region AS (
    SELECT
        region,
        SUM(actual_paise) AS actual_paise,
        SUM(target_paise) AS target_paise
    FROM plan_vs_actual
    GROUP BY region
)

SELECT
    region,
    ROUND(actual_paise / 100.0, 2)                                  AS actual_revenue_inr,
    ROUND(target_paise / 100.0, 2)                                  AS planned_net_revenue_inr,
    ROUND(100.0 * actual_paise / NULLIF(target_paise, 0), 2)        AS achievement_pct,
    ROUND((target_paise - actual_paise) / 100.0, 2)                 AS shortfall_inr,
    CASE
        WHEN actual_paise < target_paise THEN 'Below plan'
        ELSE 'At or above plan'
    END                                                             AS status
FROM by_region
-- Lowest achievement first. Sort on the unrounded ratio, not the display value.
ORDER BY 100.0 * actual_paise / NULLIF(target_paise, 0) ASC;
