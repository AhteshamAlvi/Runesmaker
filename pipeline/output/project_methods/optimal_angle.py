"""Optimal-angle projection — search full 3D rotations, pick the richest 2D view.

For each candidate rotation R ∈ SO(3):
    1. Rotate the blended streamline.
    2. Drop Z.
    3. Score the resulting silhouette by its pre-normalisation 2D spread.

The highest-scoring rotation is normalised and returned. Unlike a pure
Z-axis sweep, this can tilt the camera to reveal structure that lives
along Z — the orthographic baseline cannot.

Score = Var(x) · Var(y)
    Rewards views that fill both 2D axes. A near-line projection
    (one axis ≈ 0) scores near zero, so the search avoids degenerate
    silhouettes.

The rotation sample is deterministic (seeded) — same input always
yields the same projection.
"""

from __future__ import annotations
import numpy as np
from pipeline.rune_map import RuneMap
from pipeline.output.project_methods._util import normalize


# Number of random SO(3) rotations to try.  128 is a good speed/quality
# trade-off for single-rune projection.
N_SAMPLES = 128
SEED      = 0xBEEF


def project(rune_map: RuneMap) -> np.ndarray:
    pts = rune_map.blended

    best       = None
    best_score = -np.inf

    for R in _sample_rotations(N_SAMPLES, SEED):
        proj  = (pts @ R.T)[:, :2]
        score = float(proj.var(axis=0).prod())

        if score > best_score:
            best_score = score
            best       = proj

    return normalize(best)


# ── Uniform SO(3) sampling ────────────────────────────────────────────────────

def _sample_rotations(n: int, seed: int):
    """Yield `n` rotation matrices uniformly distributed on SO(3).

    Uses the QR decomposition of a Gaussian random matrix — det is
    forced to +1 so the result is a proper rotation (no reflection).
    """
    rng = np.random.default_rng(seed)
    for _ in range(n):
        A    = rng.standard_normal((3, 3))
        Q, _ = np.linalg.qr(A)
        if np.linalg.det(Q) < 0:
            Q[:, 0] *= -1
        yield Q
