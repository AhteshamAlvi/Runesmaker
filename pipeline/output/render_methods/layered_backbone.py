"""Layered backbone — thin field of tubes with a thick dominant backbone.

Every streamline is emitted as a thin tube (the background field). The
top-K highest-magnitude curves are *also* emitted as a thicker,
higher-poly tube drawn coincident with the thin one — visually they read
as a single thick stroke while the rest of the field hums quietly behind.

Creates strong visual hierarchy in 3D: a few structural backbones stand
out of a faint web of language lines.
"""

from __future__ import annotations
import numpy as np

from pipeline.rune_map import RuneMap
from pipeline.output.render_methods._util import (
    tube_spec,
    render_spec,
    normalize_minmax,
)


# ── Config ───────────────────────────────────────────────────────────────────

TOP_K         = 8

FIELD_RADIUS  = 0.004
FIELD_SIDES   = 6

BACKBONE_MIN  = 0.020
BACKBONE_MAX  = 0.050
BACKBONE_SIDES = 10


# ── Render ───────────────────────────────────────────────────────────────────

def render(rune_map: RuneMap) -> dict:
    if not rune_map.curves:
        return render_spec("layered_backbone")

    mags     = np.array([v.magnitude for v in rune_map.vectors])
    m_norm   = normalize_minmax(mags)
    top_idx  = set(np.argsort(-m_norm)[:TOP_K])

    tubes: list[dict] = []

    # Field layer — every streamline, thin.
    for curve in rune_map.curves:
        t = tube_spec(curve, radius=FIELD_RADIUS, sides=FIELD_SIDES)
        if t is not None:
            tubes.append(t)

    # Backbone layer — top-K, thick.
    for i in top_idx:
        curve = rune_map.curves[i]
        r     = BACKBONE_MIN + float(m_norm[i]) * (BACKBONE_MAX - BACKBONE_MIN)
        t     = tube_spec(curve, radius=r, sides=BACKBONE_SIDES)
        if t is not None:
            tubes.append(t)

    return render_spec("layered_backbone", tubes=tubes)
