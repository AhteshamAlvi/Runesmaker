"""Shared helpers for render methods.

Every SVG-producing render method tends to reach for the same three
primitives:

    1. Map points in [-1, 1]²  →  pixel coordinates on an SxS canvas.
    2. Build an SVG path `d` attribute from a sequence of pixel points.
    3. Wrap a body of SVG elements in a complete <svg> document.

These are collected here so method files stay focused on the *look* of
the render (stroke styles, layering, decoration) rather than boilerplate.

Import with:

    from pipeline.output.render_methods._util import (
        to_canvas, polyline_d, svg_document,
    )
"""

from __future__ import annotations
import numpy as np


# ── Coordinate mapping ───────────────────────────────────────────────────────

def to_canvas(
    points:       np.ndarray,
    size:         int   = 512,
    margin_frac:  float = 0.1,
) -> np.ndarray:
    """Map 2D points in [-1, 1]² to pixel coordinates on an SxS canvas.

    Y is flipped (SVG's Y axis points down). A `margin_frac` border is
    left empty around the geometry so strokes aren't clipped at the
    edges.
    """
    margin = size * margin_frac
    scale  = (size - 2 * margin) / 2
    center = size / 2
    return points * np.array([scale, -scale]) + np.array([center, center])


# ── Path construction ────────────────────────────────────────────────────────

def polyline_d(svg_pts: np.ndarray, closed: bool = False) -> str:
    """Build an SVG path `d` attribute from a sequence of pixel points.

    Args:
        svg_pts : (N, 2) array in pixel space (see `to_canvas`).
        closed  : If True, append a 'Z' to close the path.
    """
    if len(svg_pts) == 0:
        return ""

    parts = [f"M {svg_pts[0][0]:.2f} {svg_pts[0][1]:.2f}"]
    for pt in svg_pts[1:]:
        parts.append(f"L {pt[0]:.2f} {pt[1]:.2f}")
    if closed:
        parts.append("Z")
    return " ".join(parts)


# ── Document wrapping ────────────────────────────────────────────────────────

def svg_document(
    body:       str,
    size:       int            = 512,
    background: str | None     = None,
) -> str:
    """Wrap an inner SVG body in a complete <svg> document.

    Args:
        body       : Raw SVG element markup (paths, groups, etc.) as a
                     string. Indentation is the caller's concern.
        size       : Canvas size in pixels (width = height = size).
        background : Optional CSS colour for a backing <rect>. None leaves
                     the canvas transparent.
    """
    bg = (
        f'  <rect width="{size}" height="{size}" fill="{background}"/>\n'
        if background else ""
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}">\n'
        f'{bg}'
        f'{body}\n'
        f'</svg>'
    )


# ── Colour helpers ───────────────────────────────────────────────────────────

def lerp_color(t: float, a: tuple[int, int, int], b: tuple[int, int, int]) -> str:
    """Linearly interpolate between two RGB triplets. Returns '#rrggbb'."""
    t = max(0.0, min(1.0, float(t)))
    r = int(round(a[0] + (b[0] - a[0]) * t))
    g = int(round(a[1] + (b[1] - a[1]) * t))
    bb = int(round(a[2] + (b[2] - a[2]) * t))
    return f"#{r:02x}{g:02x}{bb:02x}"
