-- How the price moved for each runner in one race, from the first priced
-- crawl (t-N) to the starting price, plus how many prices the on-course
-- market showed. Change the race_id to look at another race.
WITH on_course AS (
  SELECT ride_id, COUNT(*) AS on_course_prices
  FROM data_jockey.odds_history
  WHERE race_id = 948004
  GROUP BY ride_id
)
SELECT
  s.ride_id,
  h.name AS horse,
  array_join(array_agg(s.snapshot || ' ' || s.odds ORDER BY s.snapshot_rank DESC), ' -> ') AS moves,
  COALESCE(MAX(o.on_course_prices), 0) AS on_course_prices
FROM data_jockey.odds_snapshots s
JOIN data_jockey.horses h ON h.horse_id = s.horse_id
LEFT JOIN on_course o ON o.ride_id = s.ride_id
WHERE s.race_id = 948004
GROUP BY s.ride_id, h.name
ORDER BY s.ride_id;
