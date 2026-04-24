"""Multi-stroke render — one path per language, width scaled by magnitude.

Each streamline in RuneMap.curves is rendered as its own SVG path.
Stroke width is derived from the corresponding GlyphVector.magnitude.

Effect:
    - Complex scripts (high magnitude) → thick strokes
    - Simple scripts → thin strokes
    - Full field is visible (no clustering yet)

This is the first render that fully exposes the structure of the vector field.
"""

from __future__ import annotations
import numpy as np

from pipeline.rune_map import RuneMap
from pipeline.output.project import project
from pipeline.output.render_methods._util import (
    to_canvas,
    polyline_d,
    svg_document,
    lerp_color,
)


# ── Configuration ────────────────────────────────────────────

MIN_WIDTH = 0.5
MAX_WIDTH = 4.0

LOW_COLOR  = (120, 120, 120)   # grey
HIGH_COLOR = (0, 0, 0)         # black


# ── Render ───────────────────────────────────────────────────

def render(rune_map: RuneMap) -> str:
    """Render all streamlines with magnitude-scaled stroke width."""

    curves = rune_map.curves
    mags   = np.array([v.magnitude for v in rune_map.vectors])

    if not curves:
        return svg_document("")

    # Normalize magnitudes to [0,1]
    m_min, m_max = mags.min(), mags.max()
    denom = (m_max - m_min) if (m_max - m_min) > 1e-8 else 1.0
    mags_norm = (mags - m_min) / denom

    body_parts: list[str] = []

    for curve, m in zip(curves, mags_norm):
        # ── Project to 2D ──
        # IMPORTANT: project expects RuneMap, but we want per-curve.
        # So we manually take XY (same as orthographic).
        pts_2d = curve[:, :2]

        # ── Map to canvas ──
        svg_pts = to_canvas(pts_2d)

        # ── Build path ──
        d = polyline_d(svg_pts)
        if not d:
            continue

        # ── Style ──
        width = MIN_WIDTH + m * (MAX_WIDTH - MIN_WIDTH)
        color = lerp_color(m, LOW_COLOR, HIGH_COLOR)

        body_parts.append(
            f'<path d="{d}" '
            f'stroke="{color}" '
            f'stroke-width="{width:.2f}" '
            f'fill="none" '
            f'stroke-linecap="round" '
            f'stroke-linejoin="round"/>'
        )

    body = "\n".join(body_parts)

    return svg_document(body)