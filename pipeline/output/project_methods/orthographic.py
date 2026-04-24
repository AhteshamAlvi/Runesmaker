"""Orthographic projection — drop Z and normalise.

Baseline method: fast, geometry-preserving, no rotation. Useful as a
sanity check for other projections.
"""

import numpy as np
from pipeline.rune_map import RuneMap
from pipeline.output.project_methods._util import normalize


def project(rune_map: RuneMap) -> np.ndarray:
    return normalize(rune_map.blended[:, :2].copy())
