// The parts of the REST API's responses the site uses (see /api/v1/docs/).

export interface Ref {
  name: string;
}

export interface ModelOdds {
  model_prob: number;
  model_odds: string | null;
  model_odds_decimal: number | null;
  model_rank: number | null;
  in_sample: boolean;
}

export interface ModelValue {
  model_prob: number;
  market: string;
  market_odds: string | null;
  market_odds_decimal: number | null;
  market_prob: number | null;
  edge: number | null;
  expected_value: number | null;
  undervalued: boolean;
}

export interface Runner {
  ride_id: number;
  horse: { horse_id: number; name: string };
  jockey: Ref | null;
  trainer: Ref | null;
  cloth_number: number | null;
  draw: number | null;
  status: string;
  finish_position: number | null;
  non_finisher_reason: string | null;
  horse_age: number | null;
  weight: string | null;
  official_rating: number | null;
  odds: string | null;
  odds_decimal: number | null;
  model_odds: ModelOdds | null;
  model_value: ModelValue | null;
}

export interface Race {
  race_id: number;
  course: Ref | null;
  race_date: string;
  race_time: string;
  name: string;
  race_type: string | null;
  race_class: number | null;
  age_band: string | null;
  surface: string | null;
  distance: string | null;
  going: string | null;
  result_status: string;
  ride_count: number | null;
  betting_forecast: string | null;
  verdict: string | null;
  snapshot: string;
}

export interface RaceCard extends Race {
  runners: Runner[];
}

export interface Meeting {
  meeting_id: number;
  course: Ref | null;
  going: string | null;
  surface_summary: string | null;
  weather: string | null;
  races: RaceCard[];
}

/** A runner with the race it's in (the /undervalued/ list). */
export interface Pick extends Runner {
  race: Race;
}

export interface Prize {
  position: number;
  amount: number;
  currency: string;
}

export interface RaceDetail extends Race {
  runners: Runner[];
  prizes: Prize[];
}

export interface ScorecardRow {
  view: string;
  period_type: string;
  period: string;
  race_group: string;
  first_race: string;
  last_race: string;
  races: number;
  runners: number;
  log_loss_model: number | null;
  log_loss_market: number | null;
  top_pick_won_model: number | null;
  top_pick_won_market: number | null;
  bets: number;
  bets_won: number;
  profit_units: number | null;
  roi: number | null;
}

export interface SnapshotInfo {
  built_at: string;
}
