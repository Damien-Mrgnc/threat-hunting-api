-- 1. Optimisation Workload 1 (Search) : Index composite couvrant
DROP INDEX IF EXISTS idx_network_events_srcip;
DROP INDEX IF EXISTS idx_network_events_ts;
DROP INDEX IF EXISTS idx_network_events_proto;
DROP INDEX IF EXISTS idx_search_covering;
DROP INDEX IF EXISTS idx_attack_cat;
DROP INDEX IF EXISTS idx_ts_srcip;

-- Index composite (srcip, ts DESC) + colonnes INCLUDE → 0 heap fetch pour /events/search
CREATE INDEX idx_search_covering ON network_events(srcip, ts DESC)
    INCLUDE (dstip, proto, service, sbytes, attack_cat, label);

-- Index partiel sur attack_cat → accélère /events/top (filtrage + GROUP BY)
CREATE INDEX idx_attack_cat ON network_events(attack_cat)
    WHERE attack_cat IS NOT NULL AND attack_cat <> '';

-- Index sur (ts, srcip) → rapport mensuel avec range ts (évite Seq Scan)
CREATE INDEX idx_ts_srcip ON network_events(ts, srcip);

-- 2. Optimisation Workload 2 (Stats) : Vue Matérialisée proto
DROP MATERIALIZED VIEW IF EXISTS mv_network_stats_proto;

CREATE MATERIALIZED VIEW mv_network_stats_proto AS
SELECT
    proto,
    SUM(sbytes) AS total_sbytes,
    COUNT(*)    AS event_count,
    MAX(ts)     AS last_updated
FROM network_events
GROUP BY proto
ORDER BY total_sbytes DESC;

CREATE INDEX idx_mv_proto_sbytes ON mv_network_stats_proto(total_sbytes DESC);

-- 3. Optimisation Workload 3 (Top) : Vue Matérialisée attack_cat
DROP MATERIALIZED VIEW IF EXISTS mv_attack_categories;

CREATE MATERIALIZED VIEW mv_attack_categories AS
SELECT
    attack_cat,
    COUNT(*) AS cnt
FROM network_events
WHERE attack_cat IS NOT NULL AND attack_cat <> ''
GROUP BY attack_cat
ORDER BY cnt DESC;

CREATE UNIQUE INDEX idx_mv_attack_cat ON mv_attack_categories(attack_cat);

-- Analyze pour mettre à jour les statistiques du planificateur
ANALYZE network_events;
