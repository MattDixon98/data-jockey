-- model_value at a glance: our probability vs the market's, per snapshot.
-- Expected: past rows against SP, t-1/today against the forecast; market_prob
-- sums to 1 per race (bad_totals = 0); book around 110-130%; won only filled
-- for races that have been run. The win/return columns are a first rough look
-- at the undervalued flags (out-of-sample rows only); 3f does it properly.
WITH totals AS (
  SELECT race_id, snapshot, SUM(market_prob) AS total
  FROM data_jockey.model_value
  GROUP BY race_id, snapshot
)
SELECT
  v.snapshot,
  v.market,
  v.in_sample,
  COUNT(DISTINCT v.race_id) AS races,
  COUNT(*) AS runners,
  COUNT_IF(ABS(t.total - 1) > 1e-6) AS bad_totals,
  ROUND(AVG(v.book_percentage), 1) AS avg_book_pct,
  COUNT_IF(v.undervalued) AS flagged,
  COUNT_IF(v.won IS NOT NULL) AS graded,
  COUNT_IF(v.undervalued AND v.won) AS flagged_won,
  ROUND(SUM(CASE WHEN v.undervalued AND v.won IS NOT NULL THEN v.market_prob END), 1) AS flagged_wins_expected_by_market,
  -- Profit of a 1 unit bet on every graded flagged runner at the market price.
  ROUND(SUM(
    CASE
      WHEN v.undervalued AND v.won THEN v.market_odds_decimal - 1
      WHEN v.undervalued AND v.won = false THEN -1 
    END
  ), 1) AS flagged_profit_units
FROM data_jockey.model_value v
JOIN totals t ON t.race_id = v.race_id AND t.snapshot = v.snapshot
GROUP BY v.snapshot, v.market, v.in_sample
ORDER BY v.in_sample, v.snapshot;
