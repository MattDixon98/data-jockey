-- Prize money per currency, and races where a lower place paid more than a
-- higher one. Expected: only GBP, EUR, USD, ZAR, AED, and a handful of
-- out-of-order races. Those come from the source as-is (e.g. 2026-09-26 Izuzu
-- Ireland Handicap lists 25,000 EUR for 7th), so a sudden jump is what to look for.
SELECT 'total' AS check_name, currency, COUNT(*) AS prize_rows, SUM(amount) AS total_amount
FROM data_jockey.prizes
GROUP BY currency

UNION ALL

SELECT 'out_of_order', higher.currency, COUNT(*), NULL
FROM data_jockey.prizes higher
JOIN data_jockey.prizes lower_place
  ON lower_place.race_id = higher.race_id
  AND lower_place.position = higher.position + 1
WHERE lower_place.amount > higher.amount
GROUP BY higher.currency

ORDER BY check_name, currency;
