"""Training for the Data Jockey win-odds model.

A conditional logit: each runner's score is a weighted sum of its inputs,
and a race's win probabilities are the softmax of its runners' scores. This
package fits the weights from past races and decides whether a new set beats
the current one; the daily Glue rebuild does the scoring.

Modules, from data to decision:
- inputs:   the model inputs as SQL expressions over runner_features
- data:     the Athena training query, and turning its rows into races
- fit:      the per-race softmax, likelihood, gradient and the fit itself
- evaluate: log-loss against SP and random picks, calibration, top picks
- pipeline: time split, penalty choice, candidate vs current, the report
- aws/:     Athena queries and S3 reads/writes (the only code that talks to AWS)

Runs on a Glue Python shell job (Python 3.9), so the code stays 3.9-compatible.
"""
