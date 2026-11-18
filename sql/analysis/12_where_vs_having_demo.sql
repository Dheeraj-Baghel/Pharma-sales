-- =====================================================================
-- Teaching demo: WHERE vs HAVING   (three small queries, three results)
-- Data: SYNTHETIC / fictional
--
-- SQL runs the parts of a query in this order:
--     FROM -> WHERE -> GROUP BY -> HAVING -> SELECT -> ORDER BY
--
--   WHERE  filters individual ROWS (transactions) BEFORE grouping.
--          It can test columns like units_sold, channel or date.
--          It CANNOT use SUM/COUNT/AVG, because no groups exist yet.
--   HAVING filters whole GROUPS AFTER grouping.
--          It tests totals like SUM(revenue) or COUNT(*).
-- =====================================================================


-- (A) WHERE only: revenue per channel counting ONLY large orders
--     (100 units or more). Small orders are removed before grouping, so
--     they never reach the totals.
SELECT
    channel,
    COUNT(*)               AS large_order_count,
    ROUND(SUM(revenue), 2) AS large_order_revenue_inr
FROM sales
WHERE units_sold >= 100
GROUP BY channel
ORDER BY SUM(revenue) DESC;


-- (B) HAVING only: products whose TOTAL net revenue is above 15,00,000 INR.
--     All transactions are added up first; then whole products are kept
--     or removed based on their total.
SELECT
    product,
    ROUND(SUM(revenue), 2) AS net_revenue_inr
FROM sales
GROUP BY product
HAVING SUM(revenue) > 1500000
ORDER BY SUM(revenue) DESC;


-- (C) Both: considering ONLY Distributor transactions (WHERE, row filter),
--     which reps have at least 20 of them (HAVING, group filter)?
SELECT
    sales_rep,
    region,
    COUNT(*)               AS distributor_transactions,
    ROUND(SUM(revenue), 2) AS distributor_revenue_inr
FROM sales
WHERE channel = 'Distributor'
GROUP BY sales_rep, region
HAVING COUNT(*) >= 20
ORDER BY COUNT(*) DESC, sales_rep;
