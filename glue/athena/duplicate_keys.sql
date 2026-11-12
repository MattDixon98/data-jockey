-- Keys that appear more than once, per table. Expected: every count is 0.
SELECT 'courses' AS table_name, COUNT(*) AS duplicate_keys
FROM (SELECT course_id FROM data_jockey.courses GROUP BY course_id HAVING COUNT(*) > 1)
UNION ALL
SELECT 'meetings', COUNT(*)
FROM (SELECT meeting_id FROM data_jockey.meetings GROUP BY meeting_id HAVING COUNT(*) > 1)
UNION ALL
SELECT 'races', COUNT(*)
FROM (SELECT race_id FROM data_jockey.races GROUP BY race_id HAVING COUNT(*) > 1)
UNION ALL
SELECT 'runners', COUNT(*)
FROM (SELECT ride_id FROM data_jockey.runners GROUP BY ride_id HAVING COUNT(*) > 1)
UNION ALL
SELECT 'horses', COUNT(*)
FROM (SELECT horse_id FROM data_jockey.horses GROUP BY horse_id HAVING COUNT(*) > 1)
UNION ALL
SELECT 'jockeys', COUNT(*)
FROM (SELECT jockey_id FROM data_jockey.jockeys GROUP BY jockey_id HAVING COUNT(*) > 1)
UNION ALL
SELECT 'trainers', COUNT(*)
FROM (SELECT trainer_id FROM data_jockey.trainers GROUP BY trainer_id HAVING COUNT(*) > 1)
UNION ALL
SELECT 'prizes', COUNT(*)
FROM (SELECT race_id, position FROM data_jockey.prizes GROUP BY race_id, position HAVING COUNT(*) > 1)
UNION ALL
SELECT 'horse_form', COUNT(*)
FROM (SELECT horse_id, race_id FROM data_jockey.horse_form GROUP BY horse_id, race_id HAVING COUNT(*) > 1);
