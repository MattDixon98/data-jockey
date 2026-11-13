"""Conditional logit: per-race softmax, likelihood, gradient and the fit.

A race's runners sit in consecutive rows. `starts` holds the first row of
each race and `winner_rows` the row of each race's winner. Each runner's
score is `inputs @ weights`; the race's win probabilities are the softmax of
its scores, so they add up to 1 and only differences between runners count.

The fit minimises the average negative log-probability given to each race's
winner (the log-loss), plus an L2 penalty that keeps weights small when the
data can't support them. Inputs are standardised first (mean 0, spread 1),
so the penalty treats them all alike and the weights compare directly.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize


@dataclass
class Races:
  """Model inputs for a set of races, one row per runner, races contiguous."""

  inputs: np.ndarray  # (runners, inputs)
  starts: np.ndarray  # (races,) first row of each race
  winner_rows: np.ndarray  # (races,) row of each race's winner

  @property
  def race_count(self) -> int:
    return len(self.starts)

  @property
  def sizes(self) -> np.ndarray:
    """Runners in each race."""
    ends = np.append(self.starts[1:], len(self.inputs))
    return ends - self.starts


@dataclass
class Standardiser:
  means: np.ndarray
  stds: np.ndarray

  @classmethod
  def fit(cls, inputs: np.ndarray) -> Standardiser:
    means = inputs.mean(axis=0)
    stds = inputs.std(axis=0)
    # An input that never varies (e.g. no unrated runners in a sample) would
    # divide by zero; leave it unscaled, its weight just stays at 0.
    stds = np.where(stds > 0, stds, 1.0)
    return cls(means, stds)

  def apply(self, races: Races) -> Races:
    scaled = (races.inputs - self.means) / self.stds
    return Races(scaled, races.starts, races.winner_rows)


def log_softmax_by_race(scores: np.ndarray, races: Races) -> np.ndarray:
  """log P(runner wins) for every row: score minus log-sum-exp of its race."""
  sizes = races.sizes
  # Subtract each race's top score first so exp() can't overflow.
  race_max = np.maximum.reduceat(scores, races.starts)
  shifted = scores - np.repeat(race_max, sizes)
  log_totals = np.log(np.add.reduceat(np.exp(shifted), races.starts))
  return shifted - np.repeat(log_totals, sizes)


def win_probabilities(weights: np.ndarray, races: Races) -> np.ndarray:
  scores = races.inputs @ weights
  return np.exp(log_softmax_by_race(scores, races))


def loss_and_gradient(weights: np.ndarray, races: Races, l2: float) -> tuple[float, np.ndarray]:
  """Average log-loss per race plus the L2 penalty, and its gradient.

  For one race the gradient of -log P(winner) is
  (probability-weighted average of the field's inputs) - (winner's inputs):
  the fit pushes weights towards whatever the winners had more of.
  """
  scores = races.inputs @ weights
  log_probs = log_softmax_by_race(scores, races)
  probs = np.exp(log_probs)

  log_loss = -log_probs[races.winner_rows].mean()
  penalty = 0.5 * l2 * (weights @ weights)

  winners_inputs = races.inputs[races.winner_rows].sum(axis=0)
  expected_inputs = races.inputs.T @ probs
  gradient = (expected_inputs - winners_inputs) / races.race_count + l2 * weights
  return log_loss + penalty, gradient


def fit_weights(races: Races, l2: float) -> np.ndarray:
  """Weights that minimise the penalised log-loss (L-BFGS, from all zeros,
  i.e. starting from every runner being equally likely)."""
  start = np.zeros(races.inputs.shape[1])
  result = minimize(
    loss_and_gradient,
    start,
    args=(races, l2),
    jac=True,
    method="L-BFGS-B",
  )
  if not result.success:
    raise RuntimeError(f"fit did not converge: {result.message}")
  return result.x
