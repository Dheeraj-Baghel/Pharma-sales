-- =====================================================================
-- Q8b. Largest MONTHLY gaps by region and product.
--      The 10 month + region + product groups furthest below plan.
--      shortfall = target - actual (positive = below plan); groups that met
--      or beat their target are excluded.
-- Data: SYNTHETIC / fictional
--
-- Money is handled as WHOLE PAISE (integers): each stored amount is
-- converted with CAST(ROUND(amount * 100) AS INTEGER) before summing, so a
-- group whose sales add up exactly to its target is never listed because of
-- decimal rounding noise. We divide by 100.0 only for display.
--
-- How it works
--   * plan_vs_actual already has exactly one row per month + region + product
--     (360 rows), so we don't need GROUP BY here.
--   * WHERE shortfall_paise > 0  keeps only below-plan groups. WHERE is right
--     here because each row is already one complete group.
--   * Groups with NO sales stay in (actual = 0, achievement = 0%) thanks to
--     the LEFT JOIN. They are labelled with CASE WHEN.
--   * ORDER BY shortfall_paise DESC + LIMIT 10 = the 10 biggest gaps.
-- =====================================================================

WITH monthly_actuals AS (
    SELECT
        SUBSTR(date, 1, 7)                          AS sales_month,
        region,
        product,
        SUM(CAST(ROUND(revenue * 100) AS INTEGER))  AS actual_paise,
        COUNT(*)                                    AS transaction_count
    FROM sales
    GROUP BY SUBSTR(date, 1, 7), region, product
),

plan_vs_actual AS (
    SELECT
        t.target_month,
        t.region,
        t.product,
        CAST(ROUND(t.target_net_revenue * 100) AS INTEGER) AS target_paise,
        COALESCE(a.actual_paise, 0)                        AS actual_paise,
        COALESCE(a.transaction_count, 0)                   AS transaction_count
    FROM sales_targets AS t
    LEFT JOIN monthly_actuals AS a
           ON  a.sales_month = t.target_month
           AND a.region      = t.region
           AND a.product     = t.product
),

gaps AS (
    SELECT
        *,
        target_paise - actual_paise AS shortfall_paise
    FROM plan_vs_actual
)

SELECT
    target_month                                              AS month,
    region,
    product,
    transaction_count,
    ROUND(actual_paise / 100.0, 2)                            AS actual_revenue_inr,
    ROUND(target_paise / 100.0, 2)                            AS planned_net_revenue_inr,
    ROUND(100.0 * actual_paise / NULLIF(target_paise, 0), 2)  AS achievement_pct,
    ROUND(shortfall_paise / 100.0, 2)                         AS shortfall_inr,
    CASE
        WHEN transaction_count = 0 THEN 'No sales'
        ELSE 'Below plan'
    END                                                       AS note
FROM gaps
WHERE shortfall_paise > 0
ORDER BY shortfall_paise DESC
LIMIT 10;
