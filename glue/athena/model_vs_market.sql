-- Today's and tomorrow's races: our odds next to the forecast price, to eyeball.
-- (Finished races are compared with SP properly in 3e.)
SELECT
  m.race_date,
  r.race_time,
  c.name AS course,
  h.name AS horse,
  m.snapshot,
  m.model_odds AS our_odds,
  ROUND(m.model_prob, 3) AS our_prob,
  m.model_rank AS our_rank,
  s.odds AS forecast_odds
FROM data_jockey.model_odds m
JOIN data_jockey.races r ON r.race_id = m.race_id
JOIN data_jockey.courses c ON c.course_id = r.course_id
JOIN data_jockey.horses h ON h.horse_id = m.horse_id
LEFT JOIN data_jockey.odds_snapshots s ON s.ride_id = m.ride_id AND s.snapshot = m.snapshot
WHERE m.snapshot IN ('today', 't-1')
  AND m.race_date >= current_date
ORDER BY m.race_date, r.race_time, m.snapshot, m.model_rank
LIMIT 60;
