"""Layered backbone render — dominant flows + faint field.

Renders:
    - Backbone: top-K curves (by magnitude), thick + opaque
    - Field: all curves, thin + low opacity

Creates strong visual hierarchy while preserving full structure.
"""

from __future__ import annotations
import numpy as np

from pipeline.rune_map import RuneMap
from pipeline.output.render_methods._util import (
    to_canvas,
    polyline_d,
    svg_document,
    lerp_color,
)


# ── Config ───────────────────────────────────────────────────

# Backbone selection
TOP_K = 8

# Backbone styling
BACKBONE_MIN_WIDTH = 2.0
BACKBONE_MAX_WIDTH = 6.0
BACKBONE_OPACITY   = 0.95

# Field styling
FIELD_WIDTH   = 0.6
FIELD_OPACITY = 0.15

# Colors
LOW_COLOR  = (120, 120, 120)
HIGH_COLOR = (0, 0, 0)


# ── Render ───────────────────────────────────────────────────

def render(rune_map: RuneMap) -> str:
    curves = rune_map.curves
    mags   = np.array([v.magnitude for v in rune_map.vectors])

    if not curves:
        return svg_document("")

    # ── Normalize magnitudes ──
    m_min, m_max = mags.min(), mags.max()
    denom = (m_max - m_min) if (m_max - m_min) > 1e-8 else 1.0
    mags_norm = (mags - m_min) / denom

    # ── Select backbone indices ──
    idx_sorted = np.argsort(-mags_norm)
    backbone_idx = set(idx_sorted[:TOP_K])

    body_parts = []

    # ── Layer 2: Field (draw first, underneath) ──
    for i, (curve, m) in enumerate(zip(curves, mags_norm)):
        pts = to_canvas(curve[:, :2])
        d = polyline_d(pts)
        if not d:
            continue

        color = lerp_color(m, LOW_COLOR, HIGH_COLOR)

        body_parts.append(
            f'<path d="{d}" '
            f'stroke="{color}" '
            f'stroke-width="{FIELD_WIDTH}" '
            f'opacity="{FIELD_OPACITY}" '
            f'fill="none" '
            f'stroke-linecap="round" '
            f'stroke-linejoin="round"/>'
        )

    # ── Layer 1: Backbone (draw on top) ──
    for i in backbone_idx:
        curve = curves[i]
        m     = mags_norm[i]

        pts = to_canvas(curve[:, :2])
        d = polyline_d(pts)
        if not d:
            continue

        width = BACKBONE_MIN_WIDTH + m * (BACKBONE_MAX_WIDTH - BACKBONE_MIN_WIDTH)
        color = lerp_color(m, LOW_COLOR, HIGH_COLOR)

        body_parts.append(
            f'<path d="{d}" '
            f'stroke="{color}" '
            f'stroke-width="{width:.2f}" '
            f'opacity="{BACKBONE_OPACITY}" '
            f'fill="none" '
            f'stroke-linecap="round" '
            f'stroke-linejoin="round"/>'
        )

    return svg_document("\n".join(body_parts))