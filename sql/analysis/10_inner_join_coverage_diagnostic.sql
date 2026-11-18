-- =====================================================================
-- Diagnostic: INNER JOIN vs LEFT JOIN (and the double-counting trap)
-- Data: SYNTHETIC / fictional
--
-- INNER JOIN keeps a plan row ONLY if a matching actuals row exists.
--   -> It answers "how many planned groups had at least one sale?"
--   -> But for target REPORTING it silently DROPS groups with no sales,
--      together with their targets, so the plan looks smaller than it is
--      and the worst misses (0 sales) disappear.
-- LEFT JOIN keeps every plan row; missing actuals become 0.
--
-- The last column shows the mistake we must never make: joining the
-- monthly target to INDIVIDUAL transactions and then summing the target.
-- A target is repeated once per matching transaction, so it is counted
-- several times (e.g. 45,103.83 x 4 transactions = 1,80,415.32).
--
-- Each column is its own scalar SUBQUERY (a query in brackets that returns
-- one value), so the result is a single row of side-by-side numbers.
-- =====================================================================

WITH monthly_actuals AS (
    SELECT
        SUBSTR(date, 1, 7)  AS sales_month,
        region,
        product,
        SUM(revenue)        AS actual_revenue
    FROM sales
    GROUP BY SUBSTR(date, 1, 7), region, product
)

SELECT
    -- How many plan rows exist
    (SELECT COUNT(*) FROM sales_targets)                          AS planned_groups,

    -- INNER JOIN: only plan groups with at least one sale
    (SELECT COUNT(*)
       FROM sales_targets AS t
       INNER JOIN monthly_actuals AS a
               ON  a.sales_month = t.target_month
               AND a.region      = t.region
               AND a.product     = t.product)                     AS groups_with_sales_inner_join,

    -- LEFT JOIN: every plan group survives
    (SELECT COUNT(*)
       FROM sales_targets AS t
       LEFT JOIN monthly_actuals AS a
              ON  a.sales_month = t.target_month
              AND a.region      = t.region
              AND a.product     = t.product)                      AS groups_kept_left_join,

    -- Plan groups whose actuals are missing (dropped by INNER JOIN)
    (SELECT COUNT(*)
       FROM sales_targets AS t
       LEFT JOIN monthly_actuals AS a
              ON  a.sales_month = t.target_month
              AND a.region      = t.region
              AND a.product     = t.product
      WHERE a.sales_month IS NULL)                                AS groups_without_sales,

    -- Correct plan total (straight from the plan table)
    (SELECT ROUND(SUM(target_net_revenue), 2) FROM sales_targets) AS plan_total_correct_inr,

    -- Plan total if you (wrongly) used an INNER JOIN for reporting
    (SELECT ROUND(SUM(t.target_net_revenue), 2)
       FROM sales_targets AS t
       INNER JOIN monthly_actuals AS a
               ON  a.sales_month = t.target_month
               AND a.region      = t.region
               AND a.product     = t.product)                     AS plan_total_inner_join_inr,

    -- WRONG: target joined to every transaction, then summed
    (SELECT ROUND(SUM(t.target_net_revenue), 2)
       FROM sales_targets AS t
       INNER JOIN sales AS s
               ON  SUBSTR(s.date, 1, 7) = t.target_month
               AND s.region             = t.region
               AND s.product            = t.product)              AS plan_total_wrong_txn_join_inr;
