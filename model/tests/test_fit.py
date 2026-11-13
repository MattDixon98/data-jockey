import numpy as np
from scipy.optimize import check_grad

from conftest import TRUE_WEIGHTS, make_races
from data_jockey_model.fit import Races, Standardiser, fit_weights, loss_and_gradient, win_probabilities


def test_probabilities_sum_to_one_per_race():
  races = make_races(TRUE_WEIGHTS, race_count=50)
  probs = win_probabilities(np.array([0.3, 1.0, -2.0]), races)
  assert np.allclose(np.add.reduceat(probs, races.starts), 1.0)


def test_equal_weights_mean_equal_chances():
  races = make_races(TRUE_WEIGHTS, race_count=50)
  probs = win_probabilities(np.zeros(3), races)
  assert np.allclose(probs, np.repeat(1.0 / races.sizes, races.sizes))


def test_huge_scores_dont_overflow():
  races = Races(np.array([[1000.0], [0.0], [-1000.0]]), np.array([0]), np.array([0]))
  probs = win_probabilities(np.array([1.0]), races)
  assert np.isfinite(probs).all() and probs[0] == 1.0


def test_gradient_matches_numerical_gradient():
  races = make_races(TRUE_WEIGHTS, race_count=200)
  weights = np.array([0.2, -0.1, 0.4])
  error = check_grad(
    lambda w: loss_and_gradient(w, races, l2=0.01)[0],
    lambda w: loss_and_gradient(w, races, l2=0.01)[1],
    weights,
  )
  assert error < 1e-5


def test_fit_recovers_known_weights():
  races = make_races(TRUE_WEIGHTS, race_count=5000)
  weights = fit_weights(races, l2=0.0)
  assert np.allclose(weights, TRUE_WEIGHTS, atol=0.08)


def test_penalty_shrinks_weights():
  races = make_races(TRUE_WEIGHTS, race_count=1000)
  loose = fit_weights(races, l2=0.0)
  tight = fit_weights(races, l2=1.0)
  assert np.linalg.norm(tight) < np.linalg.norm(loose)


def test_standardiser_leaves_constant_inputs_alone():
  races = Races(np.array([[1.0, 5.0], [3.0, 5.0]]), np.array([0]), np.array([0]))
  standardiser = Standardiser.fit(races.inputs)
  scaled = standardiser.apply(races).inputs
  assert np.allclose(scaled[:, 0], [-1.0, 1.0])
  assert np.allclose(scaled[:, 1], [0.0, 0.0])
