-- =====================================================================
-- Tiny IN-MEMORY test data for the target-miss boundary cases.
-- It never touches data/pharma_sales.db. Load it after schema.sql into a
-- throwaway in-memory database, then run a report on it, e.g.
--
--   cat sql/schema.sql sql/checks/boundary_fixture.sql \
--       sql/analysis/08_annual_target_misses.sql \
--     | sqlite3 -header -column :memory:
--
-- Automated check of reports 03, 08 and 09 against expected output:
--   sh sql/checks/run_boundary_tests.sh
--
-- January 2025 targets (fictional):
--   North / Cardiozen 10mg       target 1000.00  actual  999.99      -> 1 paisa SHORT -> listed
--   North / Glucobal 500mg       target 1000.00  actual 1000.00      -> EXACTLY met   -> excluded
--   North / Respiclear Inhaler   target 1000.00  actual 1500.00      -> beat target   -> excluded
--   North / Neurocalm 50mg       target  500.00  no sales            -> 0%            -> listed
--   South / Cardiozen 10mg       target  100.00  actual  200.00      -> beat target   -> excluded
--   East  / Infecta-Guard 250mg  target    0.80  actual 0.10 + 0.70  -> EXACTLY met   -> excluded
--
-- The East case is the floating-point trap: as decimals, 0.10 + 0.70 is
-- stored as 0.7999999999999999, which is "less than" 0.80. Summing whole
-- paise instead (10 + 70 = 80) shows it is exactly at plan.
--
-- Expected from 03 (region achievement):
--   North  3499.99 vs 3500.00  shortfall 0.01   achievement shows 100.0  'Below plan'
--   East      0.80 vs    0.80  shortfall 0.00   achievement 100.0        'At or above plan'
--   South   200.00 vs  100.00  shortfall -100   achievement 200.0        'At or above plan'
-- Expected from 08 (annual rollups):
--   Product Neurocalm 50mg (short 500.00) - listed
--   Region  North          (short 0.01)   - listed, although its achievement
--                                          DISPLAYS as 100.0 (99.9997% rounds up)
--   Cardiozen is NOT listed at product level: North's 0.01 miss is more than
--   covered by South's 100.00 excess (1199.99 actual vs 1100.00 target).
--   East / Infecta-Guard (exactly met) is not listed at either level.
-- Expected from 09 (monthly gaps):
--   2025-01 North Neurocalm (500.00, No sales) and
--   2025-01 North Cardiozen (0.01, Below plan). Nothing else.
-- =====================================================================

INSERT INTO sales_targets (target_month, region, product, planned_orders, target_net_revenue) VALUES
    ('2025-01', 'North', 'Cardiozen 10mg',      1.0, 1000.0),
    ('2025-01', 'North', 'Glucobal 500mg',      1.0, 1000.0),
    ('2025-01', 'North', 'Respiclear Inhaler',  1.0, 1000.0),
    ('2025-01', 'North', 'Neurocalm 50mg',      1.0,  500.0),
    ('2025-01', 'South', 'Cardiozen 10mg',      1.0,  100.0),
    ('2025-01', 'East',  'Infecta-Guard 250mg', 1.0,    0.8);

INSERT INTO sales (transaction_id, date, region, product, sales_rep, channel,
                   units_sold, unit_price, discount_pct, target_revenue, revenue) VALUES
    ('TXN-00001', '2025-01-10', 'North', 'Cardiozen 10mg',      'Aarav Mehta',  'Clinic', 1,  999.99, 0.0, 1000.0,  999.99),
    ('TXN-00002', '2025-01-11', 'North', 'Glucobal 500mg',      'Simran Kaur',  'Clinic', 1, 1000.0,  0.0, 1000.0, 1000.0),
    ('TXN-00003', '2025-01-12', 'North', 'Respiclear Inhaler',  'Aarav Mehta',  'Clinic', 1, 1500.0,  0.0, 1000.0, 1500.0),
    ('TXN-00004', '2025-01-13', 'South', 'Cardiozen 10mg',      'Karthik Iyer', 'Clinic', 1,  200.0,  0.0,  100.0,  200.0),
    ('TXN-00005', '2025-01-14', 'East',  'Infecta-Guard 250mg', 'Arjun Bose',   'Clinic', 1,    0.1,  0.0,    1.0,    0.1),
    ('TXN-00006', '2025-01-15', 'East',  'Infecta-Guard 250mg', 'Ananya Das',   'Clinic', 1,    0.7,  0.0,    1.0,    0.7);
