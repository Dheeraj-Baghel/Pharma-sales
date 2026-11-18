-- =====================================================================
-- Q2. Which region generates the highest net revenue?
--     Full regional ranking (ACTUALS ONLY; plan comparison is in Q3).
-- Data: SYNTHETIC / fictional
--
-- How it works
--   * GROUP BY region      -> puts the 1,000 transactions into 5 buckets,
--                             one per region. Every SUM/COUNT is then
--                             calculated separately inside each bucket.
--   * (SELECT SUM(revenue) FROM sales)
--                          -> a SUBQUERY: a small query inside the big one.
--                             It returns ONE number (the grand total), used
--                             to turn each region's revenue into a share %.
--   * 100.0 (not 100)      -> forces decimal maths. In SQLite, integer /
--                             integer drops the decimals (7 / 2 = 3).
--   * RANK() OVER (...)    -> numbers the rows 1, 2, 3 ... in the given order.
--   * ORDER BY SUM(revenue) DESC
--                          -> highest first. We sort on the UNROUNDED total;
--                             rounding is only for display.
-- =====================================================================

SELECT
    RANK() OVER (ORDER BY SUM(revenue) DESC)                          AS revenue_rank,
    region,
    COUNT(*)                                                          AS transaction_count,
    SUM(units_sold)                                                   AS units_sold,
    ROUND(SUM(revenue), 2)                                            AS net_revenue_inr,
    ROUND(100.0 * SUM(revenue) / (SELECT SUM(revenue) FROM sales), 2) AS share_of_total_pct
FROM sales
GROUP BY region
ORDER BY SUM(revenue) DESC;
