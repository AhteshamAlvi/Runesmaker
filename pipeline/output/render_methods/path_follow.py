"""Path-follow render — particle advection through the vector field.

Instead of rendering precomputed streamlines (one per language), this
method treats the RuneMap's vector field as a flow and traces particles
through it, producing organic, drifting paths.

Effect:
    - Lines follow the "currents" of the field
    - Emergent structure (loops, swirls, divergence)
    - Not tied to languages directly — tied to field dynamics

This is closer to fluid simulation than static visualization.
"""

from __future__ import annotations
import numpy as np

from pipeline.rune_map import RuneMap, _build_field, _trace_streamline
from pipeline.output.render_methods._util import (
    to_canvas,
    polyline_d,
    svg_document,
)


# ── Config ───────────────────────────────────────────────────

NUM_PATHS = 60        # number of particles / paths
STEPS     = 180       # length of each path
DT        = 0.04      # step size

STROKE_WIDTH = 1.2
OPACITY      = 0.7
COLOR        = "#000"

# Seed strategy
SEED_MODE = "uniform"   # "uniform" | "origin_bias"

# Optional randomness
NOISE_SCALE = 0.0       # try 0.05–0.15 later for more organic motion


# ── Seed generation ──────────────────────────────────────────

def generate_seeds(rune_map: RuneMap) -> np.ndarray:
    """Generate starting points for particles."""
    if SEED_MODE == "origin_bias":
        origins = np.array([v.origin for v in rune_map.vectors])
        idx = np.random.choice(len(origins), size=NUM_PATHS)
        noise = 0.2 * np.random.randn(NUM_PATHS, 3)
        return origins[idx] + noise

    # default: uniform cube
    return np.random.uniform(-1, 1, size=(NUM_PATHS, 3))


# ── Custom tracer (adds optional noise) ──────────────────────

def trace_with_noise(V, start: np.ndarray) -> np.ndarray:
    pts = []
    pos = start.astype(np.float64).copy()

    for _ in range(STEPS):
        v = V(pos)

        if NOISE_SCALE > 0.0:
            v = v + NOISE_SCALE * np.random.randn(3)

        norm = np.linalg.norm(v)
        if norm > 1e-8:
            v = v / norm

        pos = pos + DT * v
        pts.append(pos.copy())

    return np.array(pts)


# ── Render ───────────────────────────────────────────────────

def render(rune_map: RuneMap) -> str:
    # Build the vector field from glyph vectors
    V = _build_field(rune_map.vectors)

    # Generate starting points
    seeds = generate_seeds(rune_map)

    body_parts: list[str] = []

    for seed in seeds:
        curve = trace_with_noise(V, seed)

        # Project (orthographic for now)
        pts_2d = curve[:, :2]

        # Map to canvas
        pts_canvas = to_canvas(pts_2d)

        d = polyline_d(pts_canvas)
        if not d:
            continue

        body_parts.append(
            f'<path d="{d}" '
            f'stroke="{COLOR}" '
            f'stroke-width="{STROKE_WIDTH}" '
            f'opacity="{OPACITY}" '
            f'fill="none" '
            f'stroke-linecap="round" '
            f'stroke-linejoin="round"/>'
        )

    return svg_document("\n".join(body_parts))