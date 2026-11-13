-- UK/IRE races whose race_type (from the race name) disagrees with the source's
-- run_type for the same race (from runners' previous_results, in horse_form).
-- Expected: no rows. A row means the name rule in conversions.race_type misses a case.
WITH source_types AS (
  SELECT race_id, MIN(run_type) AS run_type, COUNT(DISTINCT run_type) AS type_count
  FROM data_jockey.horse_form
  WHERE run_type IS NOT NULL
  GROUP BY race_id
)
SELECT r.race_date, r.race_time, r.name, r.race_type, s.run_type, s.type_count
FROM data_jockey.races r
JOIN source_types s ON s.race_id = r.race_id
WHERE r.country_code IN ('ENG', 'Scot', 'Wale', 'Nort', 'Eire')
  AND (r.race_type IS DISTINCT FROM s.run_type OR s.type_count > 1)
ORDER BY r.race_date, r.race_time;
