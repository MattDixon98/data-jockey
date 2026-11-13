"""How good a set of win probabilities is.

- log-loss: average -ln(probability given to the winner) per race; lower is
  better. Picking at random scores ln(field size); SP is the bar to aim for.
- calibration: in each band of predicted probability, how often runners
  actually won (20% shots should win about 20% of the time).
- top pick: how often each method's most likely runner won.

SP here has its margin removed by simple division (each 1/odds over the
race total); Shin's method, which also corrects the favourite-longshot bias,
comes with the SP comparison table (TODO 3e).
"""

from __future__ import annotations

import numpy as np

from data_jockey_model.fit import Races

CALIBRATION_BANDS = [0.0, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0]


def log_loss(probs: np.ndarray, races: Races) -> float:
  return float(-np.log(probs[races.winner_rows]).mean())


def random_log_loss(races: Races) -> float:
  """Every runner equally likely."""
  return float(np.log(races.sizes).mean())


def sp_probabilities(sp_decimal: np.ndarray, races: Races) -> tuple[np.ndarray, np.ndarray]:
  """SP as probabilities (1/odds, scaled to sum to 1 per race), and which
  races have a full set of prices (only those can be compared)."""
  implied = 1.0 / sp_decimal
  has_price = np.isfinite(implied) & (implied > 0)
  race_fully_priced = np.minimum.reduceat(has_price.astype(int), races.starts) == 1

  implied = np.where(has_price, implied, 0.0)
  totals = np.add.reduceat(implied, races.starts)
  totals = np.where(totals > 0, totals, 1.0)
  return implied / np.repeat(totals, races.sizes), race_fully_priced


def subset(races: Races, keep: np.ndarray, *row_arrays: np.ndarray) -> tuple:
  """The races where `keep` is True, plus the matching rows of each array."""
  sizes = races.sizes
  row_keep = np.repeat(keep, sizes)
  kept_sizes = sizes[keep]
  starts = np.cumsum(kept_sizes) - kept_sizes
  winner_offsets = (races.winner_rows - races.starts)[keep]
  kept = Races(races.inputs[row_keep], starts, starts + winner_offsets)
  return (kept, *[array[row_keep] for array in row_arrays])


def top_pick_win_rate(probs: np.ndarray, races: Races) -> float:
  """Share of races where the winner had the highest probability (a joint
  top pick counts as a hit)."""
  race_max = np.maximum.reduceat(probs, races.starts)
  return float((probs[races.winner_rows] >= race_max).mean())


def calibration(probs: np.ndarray, races: Races) -> list[dict]:
  won = np.zeros(len(probs), dtype=bool)
  won[races.winner_rows] = True
  bands = []
  for low, high in zip(CALIBRATION_BANDS[:-1], CALIBRATION_BANDS[1:]):
    in_band = (probs >= low) & (probs < high)
    if not in_band.any():
      continue
    bands.append({
      "band": f"{low:.0%}-{high:.0%}",
      "runners": int(in_band.sum()),
      "predicted": float(probs[in_band].mean()),
      "actual": float(won[in_band].mean()),
    })
  return bands


def scorecard(probs: np.ndarray, sp_decimal: np.ndarray, races: Races) -> dict:
  """Every headline number for one set of probabilities on one set of races."""
  sp_probs, fully_priced = sp_probabilities(sp_decimal, races)
  priced, model_priced, sp_priced = subset(races, fully_priced, probs, sp_probs)
  return {
    "races": races.race_count,
    "runners": int(len(probs)),
    "log_loss": log_loss(probs, races),
    "random_log_loss": random_log_loss(races),
    "priced_races": priced.race_count,
    "log_loss_priced": log_loss(model_priced, priced),
    "sp_log_loss_priced": log_loss(sp_priced, priced),
    "top_pick_win_rate": top_pick_win_rate(model_priced, priced),
    "sp_favourite_win_rate": top_pick_win_rate(sp_priced, priced),
    "calibration": calibration(probs, races),
  }
