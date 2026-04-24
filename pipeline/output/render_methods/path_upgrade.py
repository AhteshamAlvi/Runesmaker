"""Path-follow render — deterministic flow-field rune generator.

Traces particles through the RuneMap vector field to create flowing,
organic paths (like ink in water). This upgraded version includes:

    - Forward + backward tracing (symmetric flow)
    - Deterministic seeding (stable outputs)
    - Field-magnitude-driven stroke width
    - Optional noise for organic motion
    - Dead-path filtering

This is a *dynamic* render: it visualizes how the field behaves,
not just what it looks like.
"""

from __future__ import annotations
import numpy as np

from pipeline.rune_map import RuneMap, _build_field
from pipeline.output.render_methods._util import (
    to_canvas,
    polyline_d,
    svg_document,
)


# ── Config ───────────────────────────────────────────────────

NUM_PATHS = 50
STEPS     = 160
DT        = 0.035

# Width mapping
MIN_WIDTH = 0.6
MAX_WIDTH = 3.5

# Opacity
OPACITY = 0.75

# Noise (organic motion)
NOISE_SCALE = 0.06   # 0.0 = clean, 0.05–0.1 = fluid-like

# Filtering
MIN_ACTIVITY = 0.05  # drop paths that don't move much

# Seed mode
SEED_MODE = "origin_bias"   # "uniform" | "origin_bias"


# ── Deterministic RNG ────────────────────────────────────────

def make_rng(rune_map: RuneMap) -> np.random.Generator:
    """Seed RNG from RuneMap for stable outputs."""
    seed = len(rune_map.vectors) * 131 + int(
        sum(v.magnitude for v in rune_map.vectors) * 1000
    )
    return np.random.default_rng(seed)


# ── Seed generation ──────────────────────────────────────────

def generate_seeds(rune_map: RuneMap, rng) -> np.ndarray:
    if SEED_MODE == "origin_bias":
        origins = np.array([v.origin for v in rune_map.vectors])
        idx = rng.integers(0, len(origins), size=NUM_PATHS)
        noise = 0.25 * rng.standard_normal((NUM_PATHS, 3))
        return origins[idx] + noise

    return rng.uniform(-1, 1, size=(NUM_PATHS, 3))


# ── Tracing ──────────────────────────────────────────────────

def trace(V, start, rng):
    pts = []
    pos = start.copy()

    for _ in range(STEPS):
        v = V(pos)

        if NOISE_SCALE > 0:
            v = v + NOISE_SCALE * rng.standard_normal(3)

        mag = np.linalg.norm(v)
        if mag < 1e-8:
            break

        v = v / mag
        pos = pos + DT * v
        pts.append(pos.copy())

    return np.array(pts)


def trace_bidirectional(V, start, rng):
    """Forward + backward tracing."""
    forward  = trace(V, start, rng)
    backward = trace(lambda x: -V(x), start, rng)

    if len(forward) == 0 or len(backward) == 0:
        return forward

    return np.vstack([backward[::-1], forward])


# ── Width computation ────────────────────────────────────────

def compute_widths(V, curve):
    """Width based on local field magnitude."""
    mags = np.array([np.linalg.norm(V(p)) for p in curve])

    if len(mags) == 0:
        return mags

    m_min, m_max = mags.min(), mags.max()
    denom = (m_max - m_min) if (m_max - m_min) > 1e-8 else 1.0
    m_norm = (mags - m_min) / denom

    return MIN_WIDTH + m_norm * (MAX_WIDTH - MIN_WIDTH)


# ── Render ───────────────────────────────────────────────────

def render(rune_map: RuneMap) -> str:
    rng = make_rng(rune_map)

    # Build vector field
    V = _build_field(rune_map.vectors)

    # Generate seeds
    seeds = generate_seeds(rune_map, rng)

    body_parts = []

    for seed in seeds:
        curve = trace_bidirectional(V, seed, rng)

        if len(curve) < 10:
            continue

        # Filter weak paths
        activity = np.mean([np.linalg.norm(V(p)) for p in curve])
        if activity < MIN_ACTIVITY:
            continue

        pts_2d = curve[:, :2]
        pts_canvas = to_canvas(pts_2d)

        d = polyline_d(pts_canvas)
        if not d:
            continue

        # Width from field strength
        widths = compute_widths(V, curve)
        width  = float(np.mean(widths))  # simplified (SVG limitation)

        body_parts.append(
            f'<path d="{d}" '
            f'stroke="black" '
            f'stroke-width="{width:.2f}" '
            f'opacity="{OPACITY}" '
            f'fill="none" '
            f'stroke-linecap="round" '
            f'stroke-linejoin="round"/>'
        )

    return svg_document("\n".join(body_parts))