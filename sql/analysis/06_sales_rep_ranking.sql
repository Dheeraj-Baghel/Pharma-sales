-- =====================================================================
-- Q6. Which sales representatives generate the most net revenue?
--     ACTUALS ONLY: the target plan has no rep allocation, so there is no
--     fair rep-level "achievement %" to report.
-- Data: SYNTHETIC / fictional reps.
--
-- Caution when reading the result: each rep works in one region, and the
-- generator gives regions different sizes. A rep's ranking therefore partly
-- reflects territory size, not only individual performance.
--
-- How it works
--   * GROUP BY sales_rep, region -> one row per rep. Region is included in
--     GROUP BY so it can be shown (each rep has exactly one region).
--   * AVG(revenue)               -> average net revenue per transaction.
-- =====================================================================

SELECT
    RANK() OVER (ORDER BY SUM(revenue) DESC)                          AS revenue_rank,
    sales_rep,
    region,
    COUNT(*)                                                          AS transaction_count,
    ROUND(SUM(revenue), 2)                                            AS net_revenue_inr,
    ROUND(AVG(revenue), 2)                                            AS avg_revenue_per_transaction_inr,
    ROUND(100.0 * SUM(revenue) / (SELECT SUM(revenue) FROM sales), 2) AS share_of_total_pct
FROM sales
GROUP BY sales_rep, region
ORDER BY SUM(revenue) DESC;
