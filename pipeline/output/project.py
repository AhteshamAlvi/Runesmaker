"""Projection dispatcher — swaps between 3D → 2D projection strategies.

Architecture
------------
    RuneMap (3D)
       │
       ▼  project(rune_map, method=None)
    _REGISTRY[method](rune_map)   ← one of many project_methods/*.py
       │
       ▼
    np.ndarray (N, 2) normalized to [-1, 1]

This module defines the SWAPPABLE PROJECTION LAYER.

It sits between the 3D RuneMap (geometry, vector field, streamlines)
and downstream rendering (SVG output). Changing the projection alters
how the 3D structure is flattened into a 2D glyph — without modifying
any upstream computation or rendering logic.

Each projection method is a single module inside
`pipeline.output.project_methods` exposing:

    def project(rune_map: RuneMap) -> np.ndarray:
        '''Return (N, 2) array normalized to [-1, 1].'''

To add a new method:
    1. Create `pipeline/output/project_methods/<name>.py`
       with a `project()` function.
    2. Import it below and register it in `_REGISTRY`
       under a short key.
    3. Optionally set `CURRENT_METHOD = "<name>"` to make
       it the default.

Design principles
-----------------
- Projection is treated as a "camera": it defines how the 3D rune
  is viewed, not what it is.
- Methods must be deterministic and stateless.
- Output must be normalized to [-1, 1] for compatibility with SVG export.
- No rendering logic should appear here — only geometric transformation.

Typical methods
---------------
- orthographic   : Drop Z (baseline, fast, geometry-preserving)
- pca_plane      : Project onto best-fit 2D plane (structure-aligned)
- optimal_angle  : Rotate to maximize silhouette spread (visual clarity)

Public API
----------
- project(rune_map, method=None) → np.ndarray (N, 2)
- available_methods()            → list[str]
"""

from __future__ import annotations
from typing import Callable
import numpy as np
from pipeline.rune_map import RuneMap


# ── Active method ────────────────────────────────────────────

CURRENT_METHOD: str = "orthographic"


# ── Registry ─────────────────────────────────────────────────

_REGISTRY: dict[str, Callable[[RuneMap], np.ndarray]] = {}


# ── Register methods ─────────────────────────────────────────

from pipeline.output.project_methods import orthographic
from pipeline.output.project_methods import pca_plane
from pipeline.output.project_methods import optimal_angle

_REGISTRY["orthographic"] = orthographic.project
_REGISTRY["pca_plane"]    = pca_plane.project
_REGISTRY["optimal_angle"] = optimal_angle.project


# ── Public API ───────────────────────────────────────────────

def available_methods() -> list[str]:
    return sorted(_REGISTRY.keys())


def project(rune_map: RuneMap, method: str | None = None) -> np.ndarray:
    """Project a RuneMap to 2D using a selected method."""
    if not _REGISTRY:
        raise ValueError("No projection methods registered.")

    key = method if method is not None else CURRENT_METHOD

    if not key:
        raise ValueError(
            f"No projection method selected. Available: {available_methods()}"
        )

    if key not in _REGISTRY:
        raise ValueError(
            f"Unknown method {key!r}. Available: {available_methods()}"
        )

    return _REGISTRY[key](rune_map)