-- Calibration, all time: within each probability band, how often runners
-- actually won. Well calibrated = actual close to predicted. Compare ours
-- (source = model) with the market's on the same view. Small bands (few
-- runners) swing a lot; judge the bands with hundreds of runners.
SELECT
  view,
  source,
  band_label,
  runners,
  ROUND(predicted, 3) AS predicted,
  ROUND(actual, 3) AS actual,
  ROUND(actual - predicted, 3) AS difference
FROM data_jockey.model_calibration
ORDER BY view, source, band;
