-- Rows per table. Compare with `python scripts/run_local.py` on the same raw data.
SELECT 'courses' AS table_name, COUNT(*) AS row_count FROM data_jockey.courses
UNION ALL SELECT 'meetings', COUNT(*) FROM data_jockey.meetings
UNION ALL SELECT 'races', COUNT(*) FROM data_jockey.races
UNION ALL SELECT 'runners', COUNT(*) FROM data_jockey.runners
UNION ALL SELECT 'horses', COUNT(*) FROM data_jockey.horses
UNION ALL SELECT 'jockeys', COUNT(*) FROM data_jockey.jockeys
UNION ALL SELECT 'trainers', COUNT(*) FROM data_jockey.trainers
UNION ALL SELECT 'prizes', COUNT(*) FROM data_jockey.prizes
UNION ALL SELECT 'horse_form', COUNT(*) FROM data_jockey.horse_form
UNION ALL SELECT 'odds_snapshots', COUNT(*) FROM data_jockey.odds_snapshots
UNION ALL SELECT 'odds_history', COUNT(*) FROM data_jockey.odds_history
UNION ALL SELECT 'runner_features', COUNT(*) FROM data_jockey.runner_features
UNION ALL SELECT 'model_odds', COUNT(*) FROM data_jockey.model_odds
UNION ALL SELECT 'model_value', COUNT(*) FROM data_jockey.model_value
UNION ALL SELECT 'model_scorecard', COUNT(*) FROM data_jockey.model_scorecard
UNION ALL SELECT 'model_calibration', COUNT(*) FROM data_jockey.model_calibration
ORDER BY table_name;
