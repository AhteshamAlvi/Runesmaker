"""Export a rune to SVG (2D) and JSON (3D) for the C++ renderer."""

from __future__ import annotations
import json
import numpy as np
from pipeline.rune_map import RuneMap


# ── SVG ─────────────────────────────────────────────────────────────────────

def to_svg(points: np.ndarray, size: int = 512, stroke_width: float = 2.0) -> str:
    """Convert a 2D contour to an SVG string.

    Args:
        points      : shape (N, 2), coordinates in [-1, 1].
        size        : Canvas size in pixels.
        stroke_width: Stroke width in pixels.
    """
    margin = size * 0.1
    scale  = (size - 2 * margin) / 2
    center = size / 2

    svg_pts = points * [scale, -scale] + [center, center]

    d = f"M {svg_pts[0][0]:.2f} {svg_pts[0][1]:.2f}"
    for pt in svg_pts[1:]:
        d += f" L {pt[0]:.2f} {pt[1]:.2f}"
    d += " Z"

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{size}" height="{size}" viewBox="0 0 {size} {size}">\n'
        f'  <path d="{d}" fill="none" stroke="white" '
        f'stroke-width="{stroke_width}" stroke-linejoin="round"/>\n'
        f'</svg>'
    )


def save_svg(points: np.ndarray, path: str, **kwargs) -> None:
    """Save a 2D contour as an SVG file."""
    with open(path, "w") as f:
        f.write(to_svg(points, **kwargs))


# ── JSON (3D) — version 3 ────────────────────────────────────────────────────
#
# Format:
# {
#   "version": 3,
#   "blended":     [[x,y,z], ...],          ← 9th streamline (origin trace)
#   "streamlines": [[[x,y,z],...], ...],    ← 8 seed streamlines
#   "languages":   [{"language":..., "weight":...}, ...],
#   "encodings":   [{"language":..., "weight":..., "signal":[...]}, ...],
#   "projection":  [[x,y], ...]             ← only in full JSON (save_json)
# }
#
# The C++ renderer reads "blended" for the tube sweep — unchanged from v2.
# "streamlines" lets the renderer optionally draw each seed line separately.
# "encodings" lets the View Map rebuild the field interactively.

def _encoding_list(rune_map: RuneMap) -> list[dict]:
    return [
        {
            "language": e["language"],
            "weight":   float(e["weight"]),
            "signal":   np.asarray(e["signal"], dtype=np.float64).tolist(),
        }
        for e in rune_map.encodings
    ]


def _language_list(rune_map: RuneMap) -> list[dict]:
    return [
        {"language": lang, "weight": float(w)}
        for lang, w in zip(rune_map.languages, rune_map.weights.tolist())
    ]


def to_json(rune_map: RuneMap, projection: np.ndarray) -> str:
    """Serialise a RuneMap to JSON for the C++ renderer (version 3)."""
    data = {
        "version":     3,
        "blended":     rune_map.blended.tolist(),
        "streamlines": [c.tolist() for c in rune_map.curves],
        "languages":   _language_list(rune_map),
        "encodings":   _encoding_list(rune_map),
        "projection":  projection.tolist(),
    }
    return json.dumps(data, indent=2)


def save_json(rune_map: RuneMap, projection: np.ndarray, path: str) -> None:
    """Save a RuneMap as the full JSON file for the renderer."""
    with open(path, "w") as f:
        f.write(to_json(rune_map, projection))


# ── Intermediate map (3D only, no projection) ────────────────────────────────

def save_map(rune_map: RuneMap, path: str) -> None:
    """Save the 3D rune map without projection for intermediate storage.

    The C++ renderer can still read this (it only needs 'blended').
    Use load_map() to restore it for the Project step or View Map.
    """
    data = {
        "version":     3,
        "blended":     rune_map.blended.tolist(),
        "streamlines": [c.tolist() for c in rune_map.curves],
        "languages":   _language_list(rune_map),
        "encodings":   _encoding_list(rune_map),
    }
    with open(path, "w") as f:
        f.write(json.dumps(data, indent=2))


def load_map(path: str) -> RuneMap:
    """Reload a RuneMap from a map JSON (produced by save_map or save_json).

    Handles both v3 (current) and v2 (legacy) formats.
    """
    with open(path) as f:
        data = json.load(f)

    version = data.get("version", 1)

    if version >= 3:
        curves  = [np.array(s, dtype=np.float64) for s in data["streamlines"]]
        blended = np.array(data["blended"], dtype=np.float64)
        langs   = [e["language"] for e in data["languages"]]
        weights = np.array([e["weight"] for e in data["languages"]], dtype=np.float64)
        encodings = [
            {
                "language": e["language"],
                "weight":   float(e["weight"]),
                "signal":   np.array(e["signal"], dtype=np.float64),
            }
            for e in data.get("encodings", [])
        ]
    else:
        # Legacy v2: per-curve {language, weight, points}
        curves_data = data.get("curves", [])
        curves      = [np.array(c["points"], dtype=np.float64) for c in curves_data]
        blended     = np.array(data["blended"], dtype=np.float64)
        langs       = [c["language"] for c in curves_data]
        weights     = np.array([c["weight"] for c in curves_data], dtype=np.float64)
        encodings   = []

    return RuneMap(
        curves=curves,
        blended=blended,
        weights=weights,
        languages=langs,
        encodings=encodings,
    )
