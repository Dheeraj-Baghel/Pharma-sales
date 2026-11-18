-- =====================================================================
-- Filtered slice: target achievement by product for NORTH, Q1 2025
-- (January to March = whole calendar months, because the plan is monthly).
-- Data: SYNTHETIC / fictional
--
-- How it works
--   * WHERE filters individual ROWS before anything is grouped.
--     - Inside monthly_actuals: keep only North transactions dated
--       2025-01-01 to 2025-03-31.
--     - In the final query: keep only North plan rows for 2025-01 to 2025-03.
--     Both sides use the same whole months, so actuals and plan cover the
--     same period. (Filtering by a part of a month, e.g. 1-15 Jan, would
--     compare half a month of sales with a full month's target.)
--   * Text dates in YYYY-MM-DD form sort like real dates, so BETWEEN works.
--
-- LEFT JOIN pitfall: put filters on the PLAN table (t.region = 'North'),
-- not on the actuals side in the final WHERE. Writing WHERE a.region = 'North'
-- would throw away plan rows with no sales (their a.region is NULL), quietly
-- turning the LEFT JOIN into an INNER JOIN.
-- =====================================================================

WITH monthly_actuals AS (
    SELECT
        SUBSTR(date, 1, 7)  AS sales_month,
        region,
        product,
        SUM(revenue)        AS actual_revenue,
        COUNT(*)            AS transaction_count
    FROM sales
    WHERE date BETWEEN '2025-01-01' AND '2025-03-31'
      AND region = 'North'
    GROUP BY SUBSTR(date, 1, 7), region, product
)

SELECT
    t.product,
    COALESCE(SUM(a.transaction_count), 0)                                       AS transaction_count,
    ROUND(SUM(COALESCE(a.actual_revenue, 0)), 2)                                AS actual_revenue_inr,
    ROUND(SUM(t.target_net_revenue), 2)                                         AS planned_net_revenue_inr,
    ROUND(100.0 * SUM(COALESCE(a.actual_revenue, 0))
                / NULLIF(SUM(t.target_net_revenue), 0), 2)                      AS achievement_pct,
    ROUND(SUM(t.target_net_revenue) - SUM(COALESCE(a.actual_revenue, 0)), 2)    AS shortfall_inr
FROM sales_targets AS t
LEFT JOIN monthly_actuals AS a
       ON  a.sales_month = t.target_month
       AND a.region      = t.region
       AND a.product     = t.product
WHERE t.target_month BETWEEN '2025-01' AND '2025-03'
  AND t.region = 'North'
GROUP BY t.product
ORDER BY 100.0 * SUM(COALESCE(a.actual_revenue, 0)) / NULLIF(SUM(t.target_net_revenue), 0) ASC;
