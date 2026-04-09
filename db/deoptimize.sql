-- De-optimization Script (Reset to baseline)

-- 1. Drop Indexes (Workload 1)
DROP INDEX IF EXISTS idx_network_events_srcip;
DROP INDEX IF EXISTS idx_network_events_ts;
DROP INDEX IF EXISTS idx_network_events_proto;
DROP INDEX IF EXISTS idx_search_covering;
DROP INDEX IF EXISTS idx_attack_cat;
DROP INDEX IF EXISTS idx_ts_srcip;

-- 2. Drop Materialized Views (Workload 2 & 3)
DROP MATERIALIZED VIEW IF EXISTS mv_network_stats_proto;
DROP MATERIALIZED VIEW IF EXISTS mv_attack_categories;

-- 3. Reset Statistics
ANALYZE network_events;
