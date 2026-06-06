"""Deterministic Sentinel incident graph package."""

import warnings

warnings.filterwarnings("ignore", message="The default value of `allowed_objects`.*")

from .incident_graph import build_incident_graph

__all__ = ["build_incident_graph"]
