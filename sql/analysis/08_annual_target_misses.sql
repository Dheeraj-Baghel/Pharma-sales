-- =====================================================================
-- Q8a. Which products or regions missed their ANNUAL targets?
--      shortfall = target - actual   (positive = below plan)
--      Groups that met or beat their target are EXCLUDED.
-- Data: SYNTHETIC / fictional
--
-- Money is handled as WHOLE PAISE (integers): each stored amount is
-- converted with CAST(ROUND(amount * 100) AS INTEGER) before summing.
-- Decimal sums are not exact in a computer (0.10 + 0.70 = 0.7999999999999999),
-- which could wrongly list a group that met its target exactly. Integer
-- sums are exact (10 + 70 = 80). We divide by 100.0 only for display.
--
-- How it works
--   1. monthly_actuals / plan_vs_actual: same safe join as Q3 (aggregate
--      sales to month + region + product first, then LEFT JOIN from the plan).
--   2. product_misses : GROUP BY product, then
--         HAVING SUM(target_paise) - SUM(actual_paise) > 0
--      HAVING filters GROUPS after they are added up. WHERE could not do this,
--      because WHERE runs on individual rows BEFORE the totals exist.
--   3. region_misses  : the same, grouped by region.
--   4. UNION ALL stacks the two results into one table; the `level` column
--      says whether a row is a product or a region.
-- A group 1 paisa short (shortfall_paise = 1) is still listed, even though
-- its achievement may DISPLAY as 100.0 (e.g. 99.9997% rounds up);
-- trust shortfall_inr.
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

product_misses AS (
    SELECT
        'Product'                             AS level,
        product                               AS name,
        SUM(actual_paise)                     AS actual_paise,
        SUM(target_paise)                     AS target_paise,
        SUM(target_paise) - SUM(actual_paise) AS shortfall_paise
    FROM plan_vs_actual
    GROUP BY product
    HAVING SUM(target_paise) - SUM(actual_paise) > 0
),

region_misses AS (
    SELECT
        'Region'                              AS level,
        region                                AS name,
        SUM(actual_paise)                     AS actual_paise,
        SUM(target_paise)                     AS target_paise,
        SUM(target_paise) - SUM(actual_paise) AS shortfall_paise
    FROM plan_vs_actual
    GROUP BY region
    HAVING SUM(target_paise) - SUM(actual_paise) > 0
),

all_misses AS (
    SELECT * FROM product_misses
    UNION ALL
    SELECT * FROM region_misses
)

SELECT
    level,
    name,
    ROUND(actual_paise / 100.0, 2)                            AS actual_revenue_inr,
    ROUND(target_paise / 100.0, 2)                            AS planned_net_revenue_inr,
    ROUND(100.0 * actual_paise / NULLIF(target_paise, 0), 2)  AS achievement_pct,
    ROUND(shortfall_paise / 100.0, 2)                         AS shortfall_inr
FROM all_misses
ORDER BY level, shortfall_paise DESC;
