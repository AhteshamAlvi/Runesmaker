"""Calligraphic — per-point tube radius driven by local curvature.

Each streamline becomes a tube whose radius swells where the curve
bends sharply and narrows on the straight runs — like an ink brush
that presses harder into a turn. Magnitude sets the overall scale, so
complex scripts produce beefier brushes than simple ones.
"""

from __future__ import annotations
import numpy as np

from pipeline.rune_map import RuneMap
from pipeline.output.render_methods._util import (
    tube_spec,
    render_spec,
    normalize_minmax,
    curvature_magnitude,
    scaled_radii,
)


# ── Config ───────────────────────────────────────────────────────────────────

# Per-curve radius envelope derived from curvature. Actual per-point radii
# live inside [BASE_LOW..BASE_HIGH], then scale by magnitude (0.5–1.5×).
BASE_LOW   = 0.008
BASE_HIGH  = 0.040
MAG_MIN_K  = 0.5     # multiplier at magnitude 0
MAG_MAX_K  = 1.5     # multiplier at magnitude 1
SIDES      = 10


# ── Render ───────────────────────────────────────────────────────────────────

def render(rune_map: RuneMap) -> dict:
    if not rune_map.curves:
        return render_spec("calligraphic")

    mags   = np.array([v.magnitude for v in rune_map.vectors])
    m_norm = normalize_minmax(mags)

    tubes: list[dict] = []
    for curve, m in zip(rune_map.curves, m_norm):
        curv   = curvature_magnitude(curve)
        radii  = scaled_radii(curv, BASE_LOW, BASE_HIGH)
        scale  = MAG_MIN_K + float(m) * (MAG_MAX_K - MAG_MIN_K)
        radii  = radii * scale

        t = tube_spec(curve, radii=radii, sides=SIDES)
        if t is not None:
            tubes.append(t)

    return render_spec("calligraphic", tubes=tubes)
