-- runner_features at a glance, per snapshot, to eyeball before training.
-- Expected: every model input non-NULL (null_inputs = 0); jockey/trainer rates
-- mostly between 0.05 and 0.25 (10% = no history yet); form scores between 0
-- and 1; past rows are the bulk and the only ones with a finish_position.
SELECT
  snapshot,
  COUNT(*) AS runners,
  COUNT(DISTINCT race_id) AS races,
  COUNT_IF(finish_position IS NOT NULL) AS with_result,
  COUNT_IF(rating_diff IS NULL OR recent_form IS NULL OR jockey_win_rate IS NULL
    OR trainer_win_rate IS NULL OR horse_win_rate IS NULL OR has_handicap IS NULL) AS null_inputs,
  ROUND(AVG(CAST(is_debut AS INTEGER)), 3) AS share_debut,
  ROUND(AVG(CAST(is_unrated AS INTEGER)), 3) AS share_unrated,
  ROUND(AVG(CAST(has_jockey AS INTEGER)), 3) AS share_jockey_booked,
  ROUND(AVG(recent_form), 3) AS avg_recent_form,
  ROUND(APPROX_PERCENTILE(jockey_win_rate, 0.1), 3) AS jockey_rate_p10,
  ROUND(APPROX_PERCENTILE(jockey_win_rate, 0.9), 3) AS jockey_rate_p90,
  ROUND(APPROX_PERCENTILE(trainer_win_rate, 0.1), 3) AS trainer_rate_p10,
  ROUND(APPROX_PERCENTILE(trainer_win_rate, 0.9), 3) AS trainer_rate_p90,
  ROUND(AVG(days_since_run), 1) AS avg_days_since_run
FROM data_jockey.runner_features
GROUP BY snapshot
ORDER BY snapshot;
