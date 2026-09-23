-- Canonicalize repeated identifiers before aggregating. The first valid source
-- row wins; duplicate source rows are separately reported as data-quality issues.
WITH ranked_events AS (
    SELECT event_id, team, occurred_at, work_minutes,
           ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY source_row) AS rn
    FROM valid_events
),
actual AS (
    SELECT SUBSTR(occurred_at, 1, 10) AS day, team,
           COUNT(*) AS actual_count,
           SUM(work_minutes) AS actual_minutes,
           MAX(occurred_at) AS latest_event_at
    FROM ranked_events
    WHERE rn = 1
    GROUP BY SUBSTR(occurred_at, 1, 10), team
),
ranked_summaries AS (
    SELECT day, team, event_count, work_minutes, generated_at,
           ROW_NUMBER() OVER (PARTITION BY day, team ORDER BY source_row) AS rn
    FROM valid_summaries
),
reported AS (
    SELECT day, team, event_count AS reported_count,
           work_minutes AS reported_minutes, generated_at
    FROM ranked_summaries
    WHERE rn = 1
),
all_keys AS (
    SELECT day, team FROM actual
    UNION
    SELECT day, team FROM reported
)
SELECT k.day, k.team,
       a.actual_count, r.reported_count,
       a.actual_minutes, r.reported_minutes,
       a.latest_event_at, r.generated_at
FROM all_keys AS k
LEFT JOIN actual AS a ON a.day = k.day AND a.team = k.team
LEFT JOIN reported AS r ON r.day = k.day AND r.team = k.team
ORDER BY k.day, k.team;

