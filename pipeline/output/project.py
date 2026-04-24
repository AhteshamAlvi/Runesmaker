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
       with a `project(rune_map) -> np.ndarray` function.
    2. (Optional) Set `CURRENT_METHOD = "<name>"` below to
       make it the default.
    Auto-discovery handles the rest — the UI dropdown picks it
    up on next launch without any code changes.

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
import importlib
import pkgutil
import numpy as np

from pipeline.rune_map import RuneMap
from pipeline.output import project_methods as _methods_pkg


# ── Active method ────────────────────────────────────────────

CURRENT_METHOD: str = "optimal_angle"


# ── Registry (auto-discovered) ───────────────────────────────
#
# Every `.py` file inside `pipeline/output/project_methods/` that
# exposes a `project(rune_map) -> np.ndarray` function is registered
# automatically under its filename (stem).
#
# Files whose name starts with '_' (e.g. `_util.py`) are skipped,
# so private helpers don't leak into the registry.
#
# To add a new method: drop a file in `project_methods/`, define
# `project()` — done. No edits here, no edits in the UI.
_REGISTRY: dict[str, Callable[[RuneMap], np.ndarray]] = {}

for _info in pkgutil.iter_modules(_methods_pkg.__path__):
    if _info.name.startswith("_"):
        continue
    _mod = importlib.import_module(
        f"{_methods_pkg.__name__}.{_info.name}"
    )
    if callable(getattr(_mod, "project", None)):
        _REGISTRY[_info.name] = _mod.project


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