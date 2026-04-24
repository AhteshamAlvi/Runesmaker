"""Shared helpers for render methods — 3D render-spec primitives.

Render methods no longer emit SVG. They emit a JSON-serialisable *render
spec*: a list of 3D primitives (tubes, spheres) that the C++ Vulkan
renderer consumes directly. This keeps the 2D SVG concerns out of the
rune pipeline entirely — the same geometry the user orbits in 3D is the
geometry the method produced.

Spec schema (version 5)
-----------------------
    {
      "version": 5,
      "method":  "<name>",
      "tubes": [
        {
          "points":   [[x,y,z], ...],        # centreline (>=2 pts)
          "radius":   0.03,                  # uniform tube radius  (XOR radii)
          "radii":    [r0, r1, ...],         # per-point radii      (XOR radius)
          "sides":    8                      # cross-section vertex count
        }
      ],
      "spheres": [
        {"center": [x,y,z], "radius": r}
      ]
    }

Helpers below build spec fragments; the dispatcher serialises the final
dict to JSON.
"""

from __future__ import annotations
from typing import Iterable, Sequence
import numpy as np


SPEC_VERSION = 5

# Default tube cross-section vertex count. 8 is the visual sweet spot —
# smooth at typical viewing distance, cheap to draw 100+ of.
DEFAULT_SIDES = 8


# ── Spec primitives ──────────────────────────────────────────────────────────

def tube_spec(
    points: np.ndarray,
    *,
    radius: float | None = None,
    radii:  Sequence[float] | np.ndarray | None = None,
    sides:  int = DEFAULT_SIDES,
) -> dict | None:
    """Build one tube primitive. Returns None for curves too short to sweep.

    Exactly one of `radius` (uniform) or `radii` (per-point) must be given.
    Points are expected as an (N, 3) array in world space.
    """
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3 or len(pts) < 2:
        return None

    if (radius is None) == (radii is None):
        raise ValueError("tube_spec: pass exactly one of `radius` or `radii`.")

    out: dict = {"points": pts.tolist(), "sides": int(sides)}
    if radius is not None:
        out["radius"] = float(radius)
    else:
        r = np.asarray(radii, dtype=np.float64)
        if len(r) != len(pts):
            raise ValueError(
                f"tube_spec: radii length {len(r)} != points length {len(pts)}"
            )
        out["radii"] = r.tolist()
    return out


def sphere_spec(center: Iterable[float], radius: float) -> dict:
    """Build one sphere primitive at `center` with world-space `radius`."""
    c = np.asarray(list(center), dtype=np.float64)
    if c.shape != (3,):
        raise ValueError(f"sphere_spec: center must be (3,), got {c.shape}")
    return {"center": c.tolist(), "radius": float(radius)}


def render_spec(
    method:  str,
    tubes:   list[dict] | None = None,
    spheres: list[dict] | None = None,
) -> dict:
    """Assemble the top-level render-spec document."""
    return {
        "version": SPEC_VERSION,
        "method":  method,
        "tubes":   list(tubes   or []),
        "spheres": list(spheres or []),
    }


# ── Numeric helpers (used by shape-aware methods) ────────────────────────────

def normalize_minmax(arr: np.ndarray, epsilon: float = 1e-8) -> np.ndarray:
    """Scale a 1-D array to [0, 1] via (x - min) / (max - min).

    Returns zeros when the input has no range — constant inputs don't
    blow up the normalisation.
    """
    arr = np.asarray(arr, dtype=np.float64)
    lo, hi = arr.min(), arr.max()
    span   = hi - lo
    if span < epsilon:
        return np.zeros_like(arr)
    return (arr - lo) / span


def tangents_nd(points: np.ndarray) -> np.ndarray:
    """Unit tangent vectors along an (N, D) polyline. Works in 2D or 3D."""
    t = np.gradient(points, axis=0)
    norms = np.linalg.norm(t, axis=1, keepdims=True)
    norms[norms < 1e-8] = 1.0
    return t / norms


def curvature_magnitude(points: np.ndarray) -> np.ndarray:
    """|d tangent / ds| at each point — a curvature-like scalar per point.

    Works on 2D or 3D polylines. Higher values mark sharper turns.
    """
    tangents = tangents_nd(points)
    return np.linalg.norm(np.gradient(tangents, axis=0), axis=1)


# ── Radius scheduling ────────────────────────────────────────────────────────

def scaled_radii(signal: np.ndarray, min_r: float, max_r: float) -> np.ndarray:
    """Map an arbitrary positive signal to per-point tube radii.

    `signal` is min-max normalised to [0, 1] then linearly remapped to
    [min_r, max_r]. Constant signals collapse to min_r.
    """
    s = normalize_minmax(signal)
    return min_r + s * (max_r - min_r)
