-- 01_detection_events.sql
-- Production table for SENTINEL detection events.
--
-- Engine choice: MergeTree (not ReplacingMergeTree) because every detection
-- request is a unique, immutable event — there is nothing to replace/deduplicate.
-- SummingMergeTree is ruled out because raw events are kept in full; aggregates
-- are handled separately by the materialized view.
--
-- ORDER BY: (user_id, timestamp) — optimises the two most common query patterns:
--   1. "All detections by a specific user in the last N days"
--   2. "All events within a time range for dashboard charts"
--
-- Partitioning by month (toYYYYMM) keeps partition pruning cheap and lets TTL
-- drop entire month-partitions atomically with no rewrite cost.

CREATE TABLE IF NOT EXISTS agent_logs.detection_events
(
    event_id            UUID                        DEFAULT generateUUIDv4(),
    timestamp           DateTime64(3, 'UTC')        DEFAULT now64(3),
    user_id             String,
    session_id          String,
    content_type        Enum8(
                            'text'  = 1,
                            'image' = 2,
                            'audio' = 3,
                            'video' = 4
                        ),
    source_language     LowCardinality(String),
    content_preview     String,
    guard_label         String,
    guard_verdict       Enum8(
                            'safe'          = 1,
                            'unsafe'        = 2,
                            'inconclusive'  = 3,
                            'error'         = 4
                        ),
    misinfo_detected    Bool,
    misinfo_type        LowCardinality(String),
    manipulation_detected Bool,
    manipulation_type   LowCardinality(String),
    explanation         String,
    is_harmful          Bool,
    processing_ms       UInt32,
    model_versions      Map(String, String),
    error_code          LowCardinality(String)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (user_id, timestamp)
TTL toDateTime(timestamp) + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;
