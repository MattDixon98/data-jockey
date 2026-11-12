-- Complete UK/IRE races without exactly one winner.
-- Expected: only dead heats (winner_count = 2), no races with 0 winners.
WITH uk_ire_races AS (
  SELECT race_id, race_date, race_time, name
  FROM data_jockey.races
  WHERE result_status = 'complete'
    AND country_code IN ('ENG', 'Scot', 'Wale', 'Nort', 'Eire')
),
winner_counts AS (
  SELECT race_id, COUNT_IF(finish_position = 1) AS winner_count
  FROM data_jockey.runners
  GROUP BY race_id
)
SELECT r.race_date, r.race_time, r.name, COALESCE(w.winner_count, 0) AS winner_count
FROM uk_ire_races r
LEFT JOIN winner_counts w ON w.race_id = r.race_id
WHERE COALESCE(w.winner_count, 0) <> 1
ORDER BY r.race_date, r.race_time;
