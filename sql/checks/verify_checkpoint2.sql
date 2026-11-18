-- =====================================================================
-- Checkpoint 2 verification checks (read-only). Data is SYNTHETIC.
-- Every row is one check: expected value, actual value, PASS/FAIL.
-- Money is compared within half a paisa (0.005 INR) using unrounded sums.
--
-- Run:  sqlite3 -readonly -header -column data/pharma_sales.db < sql/checks/verify_checkpoint2.sql
-- =====================================================================

WITH
-- Independent source totals, queried straight from each table.
src_sales AS (
    SELECT COUNT(*) AS txn, SUM(revenue) AS revenue, SUM(units_sold) AS units FROM sales
),
src_plan AS (
    SELECT COUNT(*) AS n, SUM(target_net_revenue) AS target FROM sales_targets
),

-- The same safe join the analysis files use.
monthly_actuals AS (
    SELECT SUBSTR(date, 1, 7) AS sales_month, region, product,
           SUM(revenue) AS actual_revenue, COUNT(*) AS transaction_count
    FROM sales
    GROUP BY SUBSTR(date, 1, 7), region, product
),
plan_vs_actual AS (
    SELECT t.target_month, t.region, t.product, t.target_net_revenue,
           COALESCE(a.actual_revenue, 0)    AS actual_revenue,
           COALESCE(a.transaction_count, 0) AS transaction_count
    FROM sales_targets AS t
    LEFT JOIN monthly_actuals AS a
           ON a.sales_month = t.target_month AND a.region = t.region AND a.product = t.product
),
joined AS (
    SELECT SUM(actual_revenue) AS actual, SUM(target_net_revenue) AS target FROM plan_vs_actual
),
zero_sales AS (
    SELECT * FROM plan_vs_actual WHERE transaction_count = 0
),

-- Rollups, re-totalled.
by_month   AS (SELECT target_month, SUM(actual_revenue) AS a, SUM(target_net_revenue) AS t
               FROM plan_vs_actual GROUP BY target_month),
by_region  AS (SELECT region, SUM(actual_revenue) AS a, SUM(target_net_revenue) AS t
               FROM plan_vs_actual GROUP BY region),
by_product AS (SELECT product, SUM(actual_revenue) AS a, SUM(target_net_revenue) AS t
               FROM plan_vs_actual GROUP BY product),
by_rep     AS (SELECT sales_rep, SUM(revenue) AS a FROM sales GROUP BY sales_rep, region),
by_channel AS (SELECT channel, SUM(revenue) AS a FROM sales GROUP BY channel),

-- Spot check: January 2025 / North / Cardiozen 10mg (several sales).
spot_txns AS (
    SELECT COUNT(*) AS n, SUM(revenue) AS revenue FROM sales
    WHERE date BETWEEN '2025-01-01' AND '2025-01-31'
      AND region = 'North' AND product = 'Cardiozen 10mg'
),
spot_target AS (
    SELECT COUNT(*) AS n, SUM(target_net_revenue) AS target FROM sales_targets
    WHERE target_month = '2025-01' AND region = 'North' AND product = 'Cardiozen 10mg'
),
spot_joined AS (
    SELECT * FROM plan_vs_actual
    WHERE target_month = '2025-01' AND region = 'North' AND product = 'Cardiozen 10mg'
),

-- Filtered slice: North, Q1 2025 (whole months).
slice_src AS (
    SELECT SUM(revenue) AS a FROM sales
    WHERE region = 'North' AND date BETWEEN '2025-01-01' AND '2025-03-31'
),
slice_plan AS (
    SELECT SUM(target_net_revenue) AS t FROM sales_targets
    WHERE region = 'North' AND target_month BETWEEN '2025-01' AND '2025-03'
),
slice_joined AS (
    SELECT SUM(actual_revenue) AS a, SUM(target_net_revenue) AS t FROM plan_vs_actual
    WHERE region = 'North' AND target_month BETWEEN '2025-01' AND '2025-03'
),

checks (check_name, expected, actual, passed) AS (
    SELECT 'Source: transactions', '1000', txn, txn = 1000 FROM src_sales
    UNION ALL SELECT 'Source: revenue INR', '8107864.43', ROUND(revenue, 2),
                     ABS(revenue - 8107864.43) < 0.005 FROM src_sales
    UNION ALL SELECT 'Source: units', '63654', units, units = 63654 FROM src_sales
    UNION ALL SELECT 'Plan: rows', '360', n, n = 360 FROM src_plan
    UNION ALL SELECT 'Plan: total INR', '8360334.72', ROUND(target, 2),
                     ABS(target - 8360334.72) < 0.005 FROM src_plan

    UNION ALL SELECT 'Join: rows', '360', COUNT(*), COUNT(*) = 360 FROM plan_vs_actual
    UNION ALL SELECT 'Join: unique month+region+product', '360', COUNT(*), COUNT(*) = 360
              FROM (SELECT DISTINCT target_month, region, product FROM plan_vs_actual)
    UNION ALL SELECT 'Join: groups with no sales', '26', COUNT(*), COUNT(*) = 26 FROM zero_sales
    UNION ALL SELECT 'No-sales groups: target > 0, actual = 0, achievement 0%', '26', COUNT(*),
                     COUNT(*) = 26 FROM zero_sales
              WHERE target_net_revenue > 0 AND actual_revenue = 0
                AND 100.0 * actual_revenue / NULLIF(target_net_revenue, 0) = 0
    UNION ALL SELECT 'Example 2025-01/East/Respiclear: txns, actual, target',
                     '0 | 0.0 | > 0',
                     transaction_count || ' | ' || actual_revenue || ' | ' || ROUND(target_net_revenue, 2),
                     transaction_count = 0 AND actual_revenue = 0 AND target_net_revenue > 0
              FROM plan_vs_actual
              WHERE target_month = '2025-01' AND region = 'East' AND product = 'Respiclear Inhaler'

    UNION ALL SELECT 'Join actual = sales table total', ROUND(s.revenue, 2), ROUND(j.actual, 2),
                     ABS(j.actual - s.revenue) < 0.005 FROM joined j, src_sales s
    UNION ALL SELECT 'Join target = plan table total', ROUND(p.target, 2), ROUND(j.target, 2),
                     ABS(j.target - p.target) < 0.005 FROM joined j, src_plan p

    UNION ALL SELECT 'Monthly: 12 months, Jan..Dec', '12 | 2025-01..2025-12',
                     COUNT(*) || ' | ' || MIN(target_month) || '..' || MAX(target_month),
                     COUNT(*) = 12 AND MIN(target_month) = '2025-01' AND MAX(target_month) = '2025-12'
              FROM by_month
    UNION ALL SELECT 'Monthly reconciles (actual, plan)', 'source totals',
                     ROUND(SUM(m.a), 2) || ' | ' || ROUND(SUM(m.t), 2),
                     ABS(SUM(m.a) - (SELECT revenue FROM src_sales)) < 0.005
                     AND ABS(SUM(m.t) - (SELECT target FROM src_plan)) < 0.005 FROM by_month m
    UNION ALL SELECT 'Regional reconciles (actual, plan)', 'source totals',
                     ROUND(SUM(r.a), 2) || ' | ' || ROUND(SUM(r.t), 2),
                     ABS(SUM(r.a) - (SELECT revenue FROM src_sales)) < 0.005
                     AND ABS(SUM(r.t) - (SELECT target FROM src_plan)) < 0.005 FROM by_region r
    UNION ALL SELECT 'Product reconciles (actual, plan)', 'source totals',
                     ROUND(SUM(p.a), 2) || ' | ' || ROUND(SUM(p.t), 2),
                     ABS(SUM(p.a) - (SELECT revenue FROM src_sales)) < 0.005
                     AND ABS(SUM(p.t) - (SELECT target FROM src_plan)) < 0.005 FROM by_product p
    UNION ALL SELECT 'Rep ranking reconciles (10 reps)', ROUND((SELECT revenue FROM src_sales), 2),
                     COUNT(*) || ' reps | ' || ROUND(SUM(a), 2),
                     COUNT(*) = 10 AND ABS(SUM(a) - (SELECT revenue FROM src_sales)) < 0.005 FROM by_rep
    UNION ALL SELECT 'Channel ranking reconciles (4 channels)', ROUND((SELECT revenue FROM src_sales), 2),
                     COUNT(*) || ' channels | ' || ROUND(SUM(a), 2),
                     COUNT(*) = 4 AND ABS(SUM(a) - (SELECT revenue FROM src_sales)) < 0.005 FROM by_channel

    UNION ALL SELECT 'Spot 2025-01/North/Cardiozen: txns, actual',
                     st.n || ' | ' || ROUND(st.revenue, 2),
                     sj.transaction_count || ' | ' || ROUND(sj.actual_revenue, 2),
                     st.n > 1 AND st.n = sj.transaction_count AND ABS(st.revenue - sj.actual_revenue) < 0.005
              FROM spot_txns st, spot_joined sj
    UNION ALL SELECT 'Spot 2025-01/North/Cardiozen: one target row',
                     '1 row | ' || ROUND(tt.target, 2),
                     (SELECT COUNT(*) FROM spot_joined) || ' row | ' || ROUND(sj.target_net_revenue, 2),
                     tt.n = 1 AND (SELECT COUNT(*) FROM spot_joined) = 1
                     AND ABS(tt.target - sj.target_net_revenue) < 0.005
              FROM spot_target tt, spot_joined sj
    UNION ALL SELECT 'Slice North Q1: actual, plan',
                     ROUND(s.a, 2) || ' | ' || ROUND(p.t, 2),
                     ROUND(j.a, 2) || ' | ' || ROUND(j.t, 2),
                     ABS(s.a - j.a) < 0.005 AND ABS(p.t - j.t) < 0.005
              FROM slice_src s, slice_plan p, slice_joined j
)

SELECT check_name, expected, actual,
       CASE WHEN passed THEN 'PASS' ELSE 'FAIL' END AS result
FROM checks;
