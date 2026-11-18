-- =====================================================================
-- Q4. Which products contribute the most net revenue?
--     Each product's share of total revenue (ACTUALS).
-- Data: SYNTHETIC / fictional
--
-- How it works
--   * GROUP BY product     -> one bucket per product (6 rows out).
--   * share_of_total_pct   -> product revenue / grand total. The grand total
--                             comes from a SUBQUERY that runs over the whole
--                             sales table, ignoring the grouping.
--   * The shares add up to 100% (apart from display rounding).
-- =====================================================================

SELECT
    RANK() OVER (ORDER BY SUM(revenue) DESC)                          AS revenue_rank,
    product,
    COUNT(*)                                                          AS transaction_count,
    SUM(units_sold)                                                   AS units_sold,
    ROUND(SUM(revenue), 2)                                            AS net_revenue_inr,
    ROUND(100.0 * SUM(revenue) / (SELECT SUM(revenue) FROM sales), 2) AS share_of_total_pct
FROM sales
GROUP BY product
ORDER BY SUM(revenue) DESC;
