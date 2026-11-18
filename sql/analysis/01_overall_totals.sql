-- =====================================================================
-- Q1. What are total net revenue, units sold and transaction count?
-- Data: SYNTHETIC / fictional (PharmaSales Insight, calendar year 2025)
--
-- How it works
--   * FROM sales           -> look at every row of the sales table
--                             (one row = one transaction).
--   * COUNT(*)             -> counts the rows = number of transactions.
--   * SUM(column)          -> adds a column up over all rows.
--   * AVG(column)          -> SUM / COUNT, i.e. the mean per transaction.
--   * ROUND(x, 2)          -> show 2 decimals (paise). Used for DISPLAY only.
--   * No GROUP BY          -> the whole table is treated as ONE group, so
--                             the answer is a single row.
-- =====================================================================

SELECT
    COUNT(*)                       AS transaction_count,
    SUM(units_sold)                AS total_units_sold,
    ROUND(SUM(revenue), 2)         AS total_net_revenue_inr,
    ROUND(AVG(revenue), 2)         AS avg_net_revenue_per_transaction_inr
FROM sales;
