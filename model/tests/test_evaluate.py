import numpy as np

from data_jockey_model import evaluate
from data_jockey_model.fit import Races


def _races(sizes, winner_offsets):
  sizes = np.asarray(sizes)
  starts = np.cumsum(sizes) - sizes
  return Races(np.zeros((sizes.sum(), 1)), starts, starts + np.asarray(winner_offsets))


def test_difference_of_a_model_with_itself_is_zero():
  races = _races([2, 3], [0, 2])
  probs = np.array([0.6, 0.4, 0.2, 0.3, 0.5])
  difference = evaluate.log_loss_difference(probs, probs, races)
  assert difference["mean"] == 0.0
  assert difference["se"] == 0.0
  assert difference["races"] == 2


def test_difference_is_paired_per_race():
  races = _races([2, 2], [0, 0])
  better = np.array([0.8, 0.2, 0.5, 0.5])
  baseline = np.array([0.5, 0.5, 0.5, 0.5])
  difference = evaluate.log_loss_difference(better, baseline, races)
  per_race = np.array([np.log(0.5) - np.log(0.8), 0.0])
  assert np.isclose(difference["mean"], per_race.mean())
  assert np.isclose(difference["se"], per_race.std(ddof=1) / np.sqrt(2))
  assert difference["mean"] < 0  # negative = better than the baseline
