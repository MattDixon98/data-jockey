"""The model's inputs: each one a SQL expression over runner_features.

Written in plain SQL that Athena (Trino) and Spark SQL both run the same way
(column names, arithmetic, ln, CASE, CAST), because both use them: training
selects them in Athena, and the daily Glue rebuild scores with the same
strings, which travel inside the weights JSON. Every input is cast to DOUBLE
when it is selected; flags are 1/0.

Anything that is the same for every runner in a race (field size, race type,
going) cancels out in the per-race softmax, so race-level facts only appear
multiplied by a runner-level input.

Left out of v1 on purpose (see TODO "Model v2 candidates"): draw, headgear,
the source's insights flags, trainer recent form.
"""

from __future__ import annotations


def flag(condition: str) -> str:
  """A SQL condition as 1/0."""
  return f"CASE WHEN {condition} THEN 1 ELSE 0 END"


def won_before(wins_column: str) -> str:
  return flag(f"{wins_column} > 0")


def log_plus_one(column: str) -> str:
  """ln(1 + x): the first few days/runs matter more than later ones."""
  return f"ln(CAST({column} AS DOUBLE) + 1)"


JUMPS = flag("race_type <> 'FLAT'")
HANDICAP = flag("has_handicap")
# CAST: field_rated and field_size are integers, and integer division truncates.
RATED_SHARE = "CAST(field_rated AS DOUBLE) / field_size"

INPUTS: dict[str, str] = {
  # Ability
  "rating_diff": "rating_diff",
  "is_unrated": flag("is_unrated"),
  "rating_change": "rating_change",
  "weight_diff": "weight_diff",
  # Form
  "recent_form": "recent_form",
  "last_form": "last_form",
  "is_debut": flag("is_debut"),
  "log_days_since_run": log_plus_one("days_since_run"),
  # Last run in the other code (flat vs jumps): its form says less about this race.
  "switched_code": flag("switched_code"),
  # Record
  "horse_win_rate": "horse_win_rate",
  "log_horse_runs": log_plus_one("horse_runs"),
  # Suitability
  "won_race_type": won_before("type_wins"),
  "won_course": won_before("course_wins"),
  "won_distance": won_before("distance_wins"),
  "won_going": won_before("going_wins"),
  # Connections
  "jockey_win_rate": "jockey_win_rate",
  "trainer_win_rate": "trainer_win_rate",
  "has_jockey": flag("has_jockey"),
  # Interactions with race-level facts
  "rating_diff_x_jumps": f"rating_diff * {JUMPS}",
  "recent_form_x_jumps": f"recent_form * {JUMPS}",
  "is_debut_x_jumps": f"{flag('is_debut')} * {JUMPS}",
  # In a handicap the weights are set to cancel the rating gap.
  "rating_diff_x_handicap": f"rating_diff * {HANDICAP}",
  # rating_diff is against the rated runners' average: with few of them rated
  # it swings, so it counts more the more of the field is rated.
  "rating_diff_x_rated_share": f"rating_diff * {RATED_SHARE}",
}
