-- Where would an undervalued flag have made money? Every out-of-sample runner we
-- rate as positive expected value (our prob x the market's decimal odds > 1),
-- not just the flags (build/model_value.py; until 27 Nov EV >= 10% and model_prob >= 5%),
-- grouped three ways: by the market's odds, by our probability and by our EV.
-- Same views as model_scorecard: after_race = past rows vs SP; site_pick = the
-- race-morning row (today, else t-1) vs the forecast. Profit is 1 unit at SP and
-- wins are compared with SP's expectation in both views, as on the scorecard.
-- wins_z > 0: more winners than SP expected (an edge); roi includes the margin.
WITH value AS (
  SELECT *
  FROM data_jockey.model_value
  WHERE NOT in_sample AND won IS NOT NULL
),
sp AS (
  SELECT ride_id, market_odds_decimal AS sp_decimal, market_prob AS sp_prob
  FROM value
  WHERE snapshot = 'past'
),
pre_race AS (
  SELECT
    *,
    MAX(CASE WHEN snapshot = 'today' THEN 1 ELSE 0 END) OVER (PARTITION BY race_id) AS has_today
  FROM value
  WHERE snapshot IN ('today', 't-1')
),
views AS (
  SELECT 'after_race' AS view, race_id, ride_id, model_prob, market_odds_decimal, expected_value, won
  FROM value
  WHERE snapshot = 'past'
  UNION ALL
  SELECT 'site_pick' AS view, race_id, ride_id, model_prob, market_odds_decimal, expected_value, won
  FROM pre_race
  WHERE (has_today = 1 AND snapshot = 'today') OR (has_today = 0 AND snapshot = 't-1')
),
one_winner AS (
  SELECT
    *,
    SUM(CASE WHEN won THEN 1 ELSE 0 END) OVER (PARTITION BY view, race_id) AS winners
  FROM views
),
candidates AS (
  SELECT
    w.view,
    w.model_prob,
    w.market_odds_decimal,
    w.expected_value,
    CASE WHEN w.won THEN 1.0 ELSE 0.0 END AS won,
    sp.sp_prob,
    CASE WHEN w.won THEN sp.sp_decimal - 1 ELSE -1.0 END AS profit
  FROM one_winner w
  JOIN sp ON sp.ride_id = w.ride_id
  WHERE w.winners = 1 AND w.expected_value > 0 AND sp.sp_decimal IS NOT NULL
),
banded AS (
  SELECT
    *,
    CASE
      WHEN market_odds_decimal <= 3 THEN '1. 2/1 or shorter'
      WHEN market_odds_decimal <= 6 THEN '2. 9/4 to 5/1'
      WHEN market_odds_decimal <= 11 THEN '3. 11/2 to 10/1'
      WHEN market_odds_decimal <= 21 THEN '4. 11/1 to 20/1'
      WHEN market_odds_decimal <= 34 THEN '5. 22/1 to 33/1'
      ELSE '6. longer than 33/1'
    END AS odds_band,
    CASE
      WHEN model_prob < 0.05 THEN '1. under 5%'
      WHEN model_prob < 0.10 THEN '2. 5-10%'
      WHEN model_prob < 0.15 THEN '3. 10-15%'
      WHEN model_prob < 0.20 THEN '4. 15-20%'
      WHEN model_prob < 0.30 THEN '5. 20-30%'
      ELSE '6. 30% or more'
    END AS prob_band,
    CASE
      WHEN expected_value < 0.10 THEN '1. 0-10%'
      WHEN expected_value < 0.25 THEN '2. 10-25%'
      WHEN expected_value < 0.50 THEN '3. 25-50%'
      WHEN expected_value < 1.00 THEN '4. 50-100%'
      ELSE '5. 100% or more'
    END AS ev_band
  FROM candidates
),
grouped AS (
  SELECT view, 'odds' AS breakdown, odds_band AS band, won, sp_prob, profit FROM banded
  UNION ALL
  SELECT view, 'model_prob', prob_band, won, sp_prob, profit FROM banded
  UNION ALL
  SELECT view, 'expected_value', ev_band, won, sp_prob, profit FROM banded
)
SELECT
  view,
  breakdown,
  band,
  COUNT(*) AS runners,
  CAST(SUM(won) AS INTEGER) AS won,
  ROUND(SUM(sp_prob), 1) AS sp_expected,
  ROUND((SUM(won) - SUM(sp_prob)) / SQRT(SUM(sp_prob * (1 - sp_prob))), 2) AS wins_z,
  ROUND(SUM(profit), 1) AS profit,
  ROUND(SUM(profit) / COUNT(*), 3) AS roi
FROM grouped
GROUP BY view, breakdown, band
ORDER BY view, breakdown, band
