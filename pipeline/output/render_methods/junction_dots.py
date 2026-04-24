"""Junction-dots — thin streamline tubes + spheres at 3D crossings.

Draws every streamline as a thin tube, then places a sphere at every
pairwise near-approach between curves. Transforms the tangled field
into a node-based glyph structure: thin connective strands, bright
nodes where languages meet in 3D space.
"""

from __future__ import annotations
import numpy as np

from pipeline.rune_map import RuneMap
from pipeline.output.render_methods._util import (
    tube_spec,
    sphere_spec,
    render_spec,
)


# ── Config ───────────────────────────────────────────────────────────────────

TUBE_RADIUS   = 0.005
TUBE_SIDES    = 6

DOT_RADIUS    = 0.030
EPSILON       = 0.06   # proximity threshold in world units (curves live in [-1,1])
MIN_DOT_GAP   = 0.05   # dedup threshold between accepted dots
MAX_DOTS      = 300    # cap on final dot count


# ── Helpers ──────────────────────────────────────────────────────────────────

def _pairwise_junctions(curves: list[np.ndarray]) -> np.ndarray:
    """Midpoints of close approaches between every pair of 3D curves.

    For each pair (A, B): compute the |A|×|B| distance matrix, pick each
    A-point's nearest B-point, keep pairs below EPSILON. Returns an
    (M, 3) array of midpoints in world space.
    """
    hits: list[np.ndarray] = []
    for i in range(len(curves)):
        A = curves[i]
        for j in range(i + 1, len(curves)):
            B = curves[j]
            dist = np.linalg.norm(A[:, None, :] - B[None, :, :], axis=-1)
            idx  = dist.argmin(axis=1)
            mins = dist[np.arange(len(A)), idx]
            mask = mins < EPSILON
            if mask.any():
                hits.append(0.5 * (A[mask] + B[idx[mask]]))
    return np.vstack(hits) if hits else np.empty((0, 3))


def _deduplicate(points: np.ndarray, min_gap: float, cap: int) -> np.ndarray:
    """Greedy dedup — keep a point only if it's `min_gap` from all kept points."""
    out: list[np.ndarray] = []
    for p in points:
        if all(np.linalg.norm(p - q) > min_gap for q in out):
            out.append(p)
            if len(out) >= cap:
                break
    return np.array(out) if out else np.empty((0, 3))


# ── Render ───────────────────────────────────────────────────────────────────

def render(rune_map: RuneMap) -> dict:
    tubes: list[dict] = []
    for curve in rune_map.curves:
        t = tube_spec(curve, radius=TUBE_RADIUS, sides=TUBE_SIDES)
        if t is not None:
            tubes.append(t)

    dots = _deduplicate(_pairwise_junctions(rune_map.curves), MIN_DOT_GAP, MAX_DOTS)
    spheres = [sphere_spec(p, DOT_RADIUS) for p in dots]

    return render_spec("junction_dots", tubes=tubes, spheres=spheres)
