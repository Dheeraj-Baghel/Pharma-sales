-- =====================================================================
-- Q7. Which channels generate the most net revenue?
--     Transaction count, total revenue and average revenue per transaction.
--     ACTUALS ONLY: the plan has no channel allocation.
-- Data: SYNTHETIC / fictional
--
-- How it works
--   * GROUP BY channel  -> 4 buckets (Hospital, Retail Pharmacy, Clinic,
--                          Distributor).
--   * AVG(revenue)      -> same as SUM(revenue) / COUNT(*) per channel.
--   * AVG(discount_pct) -> average discount given, shown as a percentage.
--                          (A simple, unweighted average across transactions.)
-- =====================================================================

SELECT
    RANK() OVER (ORDER BY SUM(revenue) DESC)                          AS revenue_rank,
    channel,
    COUNT(*)                                                          AS transaction_count,
    ROUND(SUM(revenue), 2)                                            AS net_revenue_inr,
    ROUND(AVG(revenue), 2)                                            AS avg_revenue_per_transaction_inr,
    ROUND(100.0 * AVG(discount_pct), 2)                               AS avg_discount_pct,
    ROUND(100.0 * SUM(revenue) / (SELECT SUM(revenue) FROM sales), 2) AS share_of_total_pct
FROM sales
GROUP BY channel
ORDER BY SUM(revenue) DESC;
