-- model_odds at a glance: our own odds per snapshot.
-- Expected: probabilities sum to 1 in every race (bad_totals = 0), one
-- model_rank 1 per race (bad_favourites = 0), in_sample only for races up to
-- the first model's training end, and a version per stretch of race dates.
WITH totals AS (
  SELECT race_id, snapshot, SUM(model_prob) AS total, COUNT_IF(model_rank = 1) AS favourites
  FROM data_jockey.model_odds
  GROUP BY race_id, snapshot
)
SELECT
  o.snapshot,
  o.model_version,
  o.in_sample,
  MIN(o.race_date) AS first_race,
  MAX(o.race_date) AS last_race,
  COUNT(*) AS runners,
  COUNT(DISTINCT o.race_id) AS races,
  COUNT_IF(ABS(t.total - 1) > 1e-6) AS bad_totals,
  COUNT_IF(t.favourites <> 1 AND o.model_rank = 1) AS bad_favourites,
  ROUND(AVG(o.model_prob) FILTER (WHERE o.model_rank = 1), 3) AS avg_favourite_prob
FROM data_jockey.model_odds o
JOIN totals t ON t.race_id = o.race_id AND t.snapshot = o.snapshot
GROUP BY o.snapshot, o.model_version, o.in_sample
ORDER BY o.model_version, o.snapshot, o.in_sample;
