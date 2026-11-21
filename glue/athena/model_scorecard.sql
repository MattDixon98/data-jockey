-- The headline scorecard: all time, all races, both views.
-- Lower log-loss is better (ours vs the market). For the flags: bets_won vs
-- expected_wins_market (what SP expected) and wins_z (above ~2 unlikely to be
-- luck); roi with its 95% range (roi_low..roi_high): while that range spans 0,
-- the picks haven't shown they make or lose money. top_pick_roi_*: 1 unit per
-- race on our favourite vs the market's, at SP, for comparison.
SELECT
  view,
  race_group,
  first_race,
  last_race,
  races,
  ROUND(log_loss_model, 3) AS log_loss_model,
  ROUND(log_loss_market, 3) AS log_loss_market,
  ROUND(top_pick_won_model, 3) AS top_pick_won_model,
  ROUND(top_pick_won_market, 3) AS top_pick_won_market,
  bets,
  bets_won,
  ROUND(expected_wins_market, 1) AS expected_wins_market,
  ROUND(wins_z, 2) AS wins_z,
  ROUND(profit_units, 1) AS profit_units,
  ROUND(roi, 3) AS roi,
  ROUND(roi_low, 3) AS roi_low,
  ROUND(roi_high, 3) AS roi_high,
  ROUND(top_pick_roi_model, 3) AS top_pick_roi_model,
  ROUND(top_pick_roi_market, 3) AS top_pick_roi_market
FROM data_jockey.model_scorecard
WHERE period_type = 'all'
ORDER BY view, race_group;
