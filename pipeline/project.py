"""3D → 2D projection for SVG export.

This module is the SWAPPABLE PROJECTION LAYER.

It sits between the 3D RuneMap and the 2D SVG export. Change the
project() function to alter how the 3D structure collapses to a flat
glyph — without touching anything upstream or downstream.

Current strategy: orthographic projection — simply drop Z.

Alternative strategies to try later (change only project()):
  - Optimal-angle: rotate to the viewing angle that maximises
    silhouette complexity, then drop the depth axis.
  - Density projection: integrate field intensity along Z,
    giving thicker lines where curves overlap in depth.
  - Skeleton projection: extract 3D centrelines first, then project,
    keeping the glyph clean and stroke-like.
"""

from __future__ import annotations
import numpy as np
from pipeline.rune_map import RuneMap


# ============================================================
# PROJECTION STRATEGY — edit only this section.
#
# Contract for project():
#   Args:    rune_map — the RuneMap from build_rune_map()
#   Returns: np.ndarray of shape (N, 2), normalized to [-1, 1]
#            ready to pass directly to save_svg()
# ============================================================

def project(rune_map: RuneMap) -> np.ndarray:
    """Project the 3D blended curve to a 2D contour for SVG.

    THIS IS THE SWAPPABLE FUNCTION. Replace its body to try a
    different projection strategy. The signature must stay the same.

    Current: orthographic — drop Z, return (x, y) of blended curve.
    blended is the centroid-origin streamline normalised to [−1, 1]³.
    """
    return rune_map.blended[:, :2].copy()
