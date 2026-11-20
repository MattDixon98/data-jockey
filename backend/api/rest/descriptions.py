"""Descriptions for the REST docs, borrowed from the racing models.

A column is described once, as help_text in racing/models.py. Response fields
pick it up by themselves (ModelSerializer), but query parameters that filter
on a column don't: drf-spectacular only reads the model for their type. They
borrow the text with column_help() instead, so the docs for ?race_type= say
the same as the race_type field.
"""

from __future__ import annotations


def column_help(model, field_name: str) -> str:
  """The help_text on `model`'s `field_name` column."""
  return model._meta.get_field(field_name).help_text
