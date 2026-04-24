"""Shared helpers for projection methods.

Kept private to the package (leading underscore) — import with:

    from pipeline.output.project_methods._util import normalize
"""

from __future__ import annotations
import numpy as np


def normalize(points: np.ndarray) -> np.ndarray:
    """Centre a 2D point cloud and scale its longest axis to [-1, 1].

    Aspect ratio is preserved — the shorter axis uses a sub-range of
    [-1, 1]. Safe against degenerate (zero-extent) inputs via a small
    epsilon floor on the scale.
    """
    mins   = points.min(axis=0)
    maxs   = points.max(axis=0)
    center = (mins + maxs) / 2
    scale  = (maxs - mins).max() / 2
    return (points - center) / (scale + 1e-8)
