-- 02_materialized_views.sql
-- Pre-aggregated hourly stats for SENTINEL dashboard queries.
--
-- The backing table (detection_hourly_stats) uses SummingMergeTree so that
-- incremental inserts from the materialized view are automatically merged
-- by ClickHouse in the background — no application-side aggregation needed.

CREATE TABLE IF NOT EXISTS agent_logs.detection_hourly_stats
(
    hour                DateTime,
    guard_verdict       LowCardinality(String),
    content_type        LowCardinality(String),
    total_events        UInt64,
    harmful_count       UInt64,
    total_processing_ms UInt64
)
ENGINE = SummingMergeTree
ORDER BY (hour, guard_verdict, content_type);

CREATE MATERIALIZED VIEW IF NOT EXISTS agent_logs.detection_hourly_stats_mv
TO agent_logs.detection_hourly_stats
AS
SELECT
    toStartOfHour(timestamp)    AS hour,
    guard_verdict,
    content_type,
    count()                     AS total_events,
    countIf(is_harmful)         AS harmful_count,
    sum(processing_ms)          AS total_processing_ms
FROM agent_logs.detection_events
GROUP BY hour, guard_verdict, content_type;
