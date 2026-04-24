"""Path-follow — particle advection through the vector field.

Ignores the precomputed streamlines. Drops N particles at deterministic
seeds, advects each forward + backward through the kernel-smoothed
field (with a touch of Gaussian noise), and emits each trajectory as a
tube whose radius tracks local field strength along the path.

Feels organic — less "traced" and more "fluid-carried" than the other
methods.
"""

from __future__ import annotations
import numpy as np

from pipeline.rune_map import RuneMap, _build_field
from pipeline.output.render_methods._util import (
    tube_spec,
    render_spec,
    normalize_minmax,
    scaled_radii,
)


# ── Config ───────────────────────────────────────────────────────────────────

NUM_PATHS = 50
STEPS     = 160
DT        = 0.035

MIN_RADIUS = 0.006
MAX_RADIUS = 0.024
SIDES      = 8

NOISE_SCALE  = 0.06          # 0 = clean, 0.05–0.1 = fluid-like
MIN_ACTIVITY = 0.05          # drop paths that stagnate in the field
SEED_MODE    = "origin_bias" # "uniform" | "origin_bias"


# ── Deterministic RNG ────────────────────────────────────────────────────────

def _make_rng(rune_map: RuneMap) -> np.random.Generator:
    """Seed RNG from rune content — same rune renders identically every time."""
    seed = len(rune_map.vectors) * 131 + int(
        sum(v.magnitude for v in rune_map.vectors) * 1000
    )
    return np.random.default_rng(seed)


# ── Seeds ────────────────────────────────────────────────────────────────────

def _generate_seeds(rune_map: RuneMap, rng: np.random.Generator) -> np.ndarray:
    if SEED_MODE == "origin_bias" and rune_map.vectors:
        origins = np.array([v.origin for v in rune_map.vectors])
        idx     = rng.integers(0, len(origins), size=NUM_PATHS)
        noise   = 0.25 * rng.standard_normal((NUM_PATHS, 3))
        return origins[idx] + noise
    return rng.uniform(-1, 1, size=(NUM_PATHS, 3))


# ── Tracing ──────────────────────────────────────────────────────────────────

def _trace(V, start: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Forward Euler with optional Gaussian noise. Stops on a dead field."""
    pts = []
    pos = start.copy()
    for _ in range(STEPS):
        v = V(pos)
        if NOISE_SCALE > 0:
            v = v + NOISE_SCALE * rng.standard_normal(3)
        mag = np.linalg.norm(v)
        if mag < 1e-8:
            break
        pos = pos + DT * (v / mag)
        pts.append(pos.copy())
    return np.array(pts)


def _trace_bidirectional(V, start: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    forward  = _trace(V,               start, rng)
    backward = _trace(lambda x: -V(x), start, rng)
    if len(forward) == 0 or len(backward) == 0:
        return forward
    return np.vstack([backward[::-1], forward])


# ── Render ───────────────────────────────────────────────────────────────────

def render(rune_map: RuneMap) -> dict:
    rng   = _make_rng(rune_map)
    V     = _build_field(rune_map.vectors)
    seeds = _generate_seeds(rune_map, rng)

    tubes: list[dict] = []

    for seed in seeds:
        curve = _trace_bidirectional(V, seed, rng)
        if len(curve) < 10:
            continue

        # Per-point field magnitude → per-point radius.
        field_mags = np.array([np.linalg.norm(V(p)) for p in curve])
        if float(np.mean(field_mags)) < MIN_ACTIVITY:
            continue
        radii = scaled_radii(field_mags, MIN_RADIUS, MAX_RADIUS)

        t = tube_spec(curve, radii=radii, sides=SIDES)
        if t is not None:
            tubes.append(t)

    return render_spec("path_follow", tubes=tubes)
