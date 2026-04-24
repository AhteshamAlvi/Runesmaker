"""Per-point width render — calligraphic ribbon strokes.

Each streamline is rendered as a filled ribbon whose width varies
along the curve based on local field magnitude.

This produces an ink-brush / calligraphy effect:
    - thick where field is strong
    - thin where field fades
"""

from __future__ import annotations
import numpy as np

from pipeline.rune_map import RuneMap
from pipeline.output.render_methods._util import (
    to_canvas,
    svg_document,
    lerp_color,
)


# ── Config ───────────────────────────────────────────────────

MIN_WIDTH = 0.5
MAX_WIDTH = 6.0

COLOR_A = (50, 50, 50)
COLOR_B = (0, 0, 0)


# ── Helpers ──────────────────────────────────────────────────

def normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-8 else v


def compute_normals(points: np.ndarray) -> np.ndarray:
    """Compute 2D normals along a curve."""
    tangents = np.gradient(points, axis=0)
    tangents = np.array([normalize(t) for t in tangents])

    # rotate 90 degrees → normal
    normals = np.stack([-tangents[:, 1], tangents[:, 0]], axis=1)
    return normals


def estimate_widths(points: np.ndarray) -> np.ndarray:
    """Estimate per-point width.

    For now: use curvature proxy (change in direction).
    Replace later with field sampling if desired.
    """
    tangents = np.gradient(points, axis=0)
    tangents = np.array([normalize(t) for t in tangents])

    # curvature ≈ change in tangent
    dt = np.gradient(tangents, axis=0)
    curvature = np.linalg.norm(dt, axis=1)

    # normalize
    c_min, c_max = curvature.min(), curvature.max()
    denom = (c_max - c_min) if (c_max - c_min) > 1e-8 else 1.0
    c_norm = (curvature - c_min) / denom

    return MIN_WIDTH + c_norm * (MAX_WIDTH - MIN_WIDTH)


def build_ribbon(points: np.ndarray, widths: np.ndarray) -> np.ndarray:
    """Create ribbon polygon from centerline + widths."""
    normals = compute_normals(points)

    left  = points + normals * widths[:, None]
    right = points - normals * widths[:, None]

    # reverse right side and stitch
    ribbon = np.vstack([left, right[::-1]])
    return ribbon


def polygon_d(pts: np.ndarray) -> str:
    if len(pts) == 0:
        return ""

    parts = [f"M {pts[0][0]:.2f} {pts[0][1]:.2f}"]
    for p in pts[1:]:
        parts.append(f"L {p[0]:.2f} {p[1]:.2f}")
    parts.append("Z")
    return " ".join(parts)


# ── Render ───────────────────────────────────────────────────

def render(rune_map: RuneMap) -> str:
    body_parts = []

    for curve, vec in zip(rune_map.curves, rune_map.vectors):

        # 1. project (orthographic for now)
        pts_2d = curve[:, :2]

        # 2. canvas transform
        pts_canvas = to_canvas(pts_2d)

        # 3. widths (per-point)
        widths = estimate_widths(pts_2d)

        # 4. build ribbon
        ribbon = build_ribbon(pts_canvas, widths)

        # 5. color (optional)
        color = lerp_color(vec.magnitude, COLOR_A, COLOR_B)

        d = polygon_d(ribbon)

        if not d:
            continue

        body_parts.append(
            f'<path d="{d}" fill="{color}" stroke="none"/>'
        )

    return svg_document("\n".join(body_parts))