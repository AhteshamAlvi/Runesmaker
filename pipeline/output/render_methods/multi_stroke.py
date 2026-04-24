"""Multi-stroke — one tube per language, radius scaled by magnitude.

Each streamline in `RuneMap.curves` becomes its own 3D tube. Tube radius
is driven by the corresponding `GlyphVector.magnitude`:

    - Complex scripts (high magnitude) → thick tube
    - Simple scripts (low magnitude)   → thin tube

The cleanest reading of the raw field — every language gets a
proportionally-weighted line in space.
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

MIN_RADIUS = 0.006
MAX_RADIUS = 0.030
SIDES      = 8


# ── Render ───────────────────────────────────────────────────────────────────

def render(rune_map: RuneMap) -> dict:
    if not rune_map.curves:
        return render_spec("multi_stroke")

    mags   = np.array([v.magnitude for v in rune_map.vectors])
    m_norm = normalize_minmax(mags)

    tubes: list[dict] = []
    for curve, m in zip(rune_map.curves, m_norm):
        r = MIN_RADIUS + float(m) * (MAX_RADIUS - MIN_RADIUS)
        t = tube_spec(curve, radius=r, sides=SIDES)
        if t is not None:
            tubes.append(t)

    return render_spec("multi_stroke", tubes=tubes)
