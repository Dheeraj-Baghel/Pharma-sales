-- =====================================================================
-- Q5. How does net revenue change month to month?
--     All 12 months in order: actual revenue, planned revenue, achievement,
--     and the change versus the previous month.
-- Data: SYNTHETIC / fictional. The plan is FLAT (no seasonality) by design,
--       so seasonal swings in achievement are expected from how the data
--       was generated; they are not evidence about any real business.
--
-- How it works
--   1. monthly_actuals  : sales -> one row per month + region + product.
--   2. plan_vs_actual   : all 360 plan rows LEFT JOIN those actuals
--                         (missing actuals -> 0).
--   3. monthly          : roll the 360 rows up to 12 months.
--   4. final SELECT     : achievement % and month-on-month change.
--      LAG(x) OVER (ORDER BY month) = "the value of x on the previous row".
--      January has no previous month, so its change is NULL (blank).
-- Starting from sales_targets guarantees all 12 months appear, even if a
-- month ever had no sales at all.
-- =====================================================================

WITH monthly_actuals AS (
    SELECT
        SUBSTR(date, 1, 7)  AS sales_month,
        region,
        product,
        SUM(revenue)        AS actual_revenue,
        COUNT(*)            AS transaction_count
    FROM sales
    GROUP BY SUBSTR(date, 1, 7), region, product
),

plan_vs_actual AS (
    SELECT
        t.target_month,
        t.region,
        t.product,
        t.target_net_revenue,
        COALESCE(a.actual_revenue, 0)    AS actual_revenue,
        COALESCE(a.transaction_count, 0) AS transaction_count
    FROM sales_targets AS t
    LEFT JOIN monthly_actuals AS a
           ON  a.sales_month = t.target_month
           AND a.region      = t.region
           AND a.product     = t.product
),

monthly AS (
    SELECT
        target_month,
        SUM(transaction_count)  AS transaction_count,
        SUM(actual_revenue)     AS actual_revenue,
        SUM(target_net_revenue) AS target_net_revenue
    FROM plan_vs_actual
    GROUP BY target_month
)

SELECT
    target_month                                                       AS month,
    transaction_count,
    ROUND(actual_revenue, 2)                                           AS actual_revenue_inr,
    ROUND(target_net_revenue, 2)                                       AS planned_net_revenue_inr,
    ROUND(100.0 * actual_revenue / NULLIF(target_net_revenue, 0), 2)   AS achievement_pct,
    ROUND(target_net_revenue - actual_revenue, 2)                      AS shortfall_inr,
    ROUND(actual_revenue - LAG(actual_revenue) OVER (ORDER BY target_month), 2)
                                                                       AS change_vs_prev_month_inr,
    ROUND(100.0 * (actual_revenue - LAG(actual_revenue) OVER (ORDER BY target_month))
                / NULLIF(LAG(actual_revenue) OVER (ORDER BY target_month), 0), 2)
                                                                       AS change_vs_prev_month_pct
FROM monthly
ORDER BY target_month;
