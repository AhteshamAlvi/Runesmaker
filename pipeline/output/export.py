"""Export a rune to SVG (2D) and JSON (3D) for the C++ renderer.

JSON version 4 format
─────────────────────
{
  "version":     4,
  "blended":     [[x,y,z], ...],           ← centroid streamline (C++ tube sweep)
  "streamlines": [[[x,y,z], ...], ...],    ← one per language
  "vectors": [
    {"language": "...", "origin": [x,y,z],
     "direction": [x,y,z], "magnitude": 0.7},
    ...
  ],
  "projection": [[x,y], ...]               ← only present after Project step
}

The C++ renderer reads only "blended" for the tube sweep — unchanged from v3.
"streamlines" lets the renderer optionally draw each language line separately.
"vectors" lets the View Map rebuild the field interactively when languages
are toggled on/off.
"""

from __future__ import annotations
import json
import numpy as np
from pipeline.rune_map import RuneMap
from pipeline.glyph.vector import GlyphVector


# ── SVG ──────────────────────────────────────────────────────────────────────

def to_svg(points: np.ndarray, size: int = 512, stroke_width: float = 2.0) -> str:
    """Convert a 2D contour to an SVG string.

    Args:
        points      : shape (N, 2), coordinates in [-1, 1].
        size        : Canvas size in pixels.
        stroke_width: Stroke width in pixels.
    """
    margin  = size * 0.1
    scale   = (size - 2 * margin) / 2
    center  = size / 2
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


# ── JSON helpers ──────────────────────────────────────────────────────────────

def _vector_list(rune_map: RuneMap) -> list[dict]:
    # Effects are parallel to vectors; use 0.0 as a safe default if absent.
    effects = rune_map.effects or [0.0] * len(rune_map.vectors)
    return [
        {
            "language":  v.language,
            "origin":    v.origin.tolist(),
            "direction": v.direction.tolist(),
            "magnitude": float(v.magnitude),
            "effect":    float(e),
        }
        for v, e in zip(rune_map.vectors, effects)
    ]


# ── JSON (3D) — version 4 ────────────────────────────────────────────────────

def to_json(rune_map: RuneMap, projection: np.ndarray) -> str:
    """Serialise a RuneMap + 2D projection to JSON (version 4)."""
    data = {
        "version":     4,
        "blended":     rune_map.blended.tolist(),
        "streamlines": [c.tolist() for c in rune_map.curves],
        "vectors":     _vector_list(rune_map),
        "projection":  projection.tolist(),
    }
    return json.dumps(data, indent=2)


def save_json(rune_map: RuneMap, projection: np.ndarray, path: str) -> None:
    """Save the full JSON (with projection) for the C++ renderer."""
    with open(path, "w") as f:
        f.write(to_json(rune_map, projection))


def save_map(rune_map: RuneMap, path: str) -> None:
    """Save the 3D rune map without projection (intermediate after Generate).

    The C++ renderer can still read this (it only needs 'blended').
    Use load_map() to restore it for the Project step or View Map.
    """
    data = {
        "version":     4,
        "blended":     rune_map.blended.tolist(),
        "streamlines": [c.tolist() for c in rune_map.curves],
        "vectors":     _vector_list(rune_map),
    }
    with open(path, "w") as f:
        f.write(json.dumps(data, indent=2))


def load_map(path: str) -> RuneMap:
    """Reload a RuneMap from a JSON file (v4 current, v3 legacy).

    v4: reads vectors directly.
    v3: streamlines + languages/encodings — vectors will be empty (View Map
        language toggle won't work, but render still works via blended).
    """
    with open(path) as f:
        data = json.load(f)

    version = data.get("version", 1)

    if version >= 4:
        curves  = [np.array(s, dtype=np.float64) for s in data["streamlines"]]
        blended = np.array(data["blended"], dtype=np.float64)
        raw_vecs = data.get("vectors", [])
        vectors = [
            GlyphVector(
                language=v["language"],
                origin=np.array(v["origin"],    dtype=np.float64),
                direction=np.array(v["direction"], dtype=np.float64),
                magnitude=float(v["magnitude"]),
            )
            for v in raw_vecs
        ]
        languages = [v.language for v in vectors]
        # "effect" is new in v4.1 — older v4 files won't have it.
        effects = [float(v.get("effect", 0.0)) for v in raw_vecs]

    else:
        # Legacy v3: load what we can, vectors will be empty
        raw_sl = data.get("streamlines", data.get("curves", []))
        if raw_sl and isinstance(raw_sl[0], dict):
            # Very old v2 format: [{language, weight, points}]
            curves    = [np.array(c["points"], dtype=np.float64) for c in raw_sl]
            languages = [c["language"] for c in raw_sl]
        else:
            curves    = [np.array(s, dtype=np.float64) for s in raw_sl]
            lang_entries = data.get("languages", [])
            languages = [e["language"] for e in lang_entries]
        blended = np.array(data["blended"], dtype=np.float64)
        vectors = []
        effects = []

    return RuneMap(
        curves=curves,
        blended=blended,
        vectors=vectors,
        languages=languages,
        effects=effects,
    )
