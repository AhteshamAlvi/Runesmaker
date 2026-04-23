"""3D Rune Map — vector field driven by glyph curvature signals.

Pipeline
--------
  GlyphContour  (HarfBuzz-shaped font outlines, one per language)
       │
       ▼  _contour_to_signal()
  1-D curvature signal  ← signed curvature of the glyph outline, in [-1, 1]
       │                   (Arabic smooth curves ≠ CJK sharp corners ≠ Latin strokes)
       ▼  _build_field()
  Vector field V(x)     ← collective field driven by all language signals + weights
       │
       ▼  _trace_streamline()
  8 streamlines         ← Euler-integrated from seeds placed around the origin
  + 1 blended           ← 9th streamline from the origin, follows the "average" trajectory
       │
       ├──▶ project.py  → 2D projection of blended → SVG
       └──▶ export.py   → JSON for renderer (tube sweep on blended)

Changing the mapping
--------------------
- To change how glyphs drive the field: edit _contour_to_signal()
- To change field structure: edit _build_field()
- To change seed placement: edit _generate_seeds()
- To change integration: edit _trace_streamline()
All are decoupled. RuneMap and build_rune_map() are the stable contract.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

from pipeline.glyph_extract import GlyphContour


# ============================================================
# DATA MODEL
# ============================================================

@dataclass
class RuneMap:
    """3D source-of-truth for a generated rune.

    Attributes:
        curves    : 8 streamlines traced from seeds — the rune's geometry.
        blended   : 9th streamline from the origin — the composite centreline.
        weights   : Per-language normalised blend weights (sums to 1).
        languages : Language name for each weight entry (same order).
        encodings : Per-language {language, weight, signal} dicts.
                    Stored so the View Map can rebuild the field interactively
                    when the user toggles languages on/off.
    """
    curves:    list[np.ndarray]
    blended:   np.ndarray
    weights:   np.ndarray
    languages: list[str]
    encodings: list[dict]


# ============================================================
# GLYPH → SIGNAL
# ============================================================

def _contour_to_signal(contour: GlyphContour, resolution: int = 128) -> np.ndarray:
    """Derive a 1-D signal from the glyph's signed curvature profile.

    Each script family has a characteristic curvature signature:
      - Arabic/Hebrew : smooth, sweeping curves  → low-frequency, gentle signal
      - CJK           : sharp perpendicular strokes → high-frequency, spiky signal
      - Devanagari    : horizontal bars + ascenders → rhythmic alternating signal
      - Latin         : moderate open curves → varied mid-range signal

    Returns:
        np.ndarray of shape (resolution,) with values in [-1, 1].
        Positive = left-turning (counter-clockwise) strokes.
        Negative = right-turning (clockwise) strokes.
    """
    pts: list[tuple[float, float]] = []
    for op, args in contour.operations:
        if op in ("moveTo", "lineTo"):
            pts.append(args[0])
        elif op in ("curveTo", "qCurveTo"):
            for pt in args:
                pts.append(pt)

    if len(pts) < 3:
        return np.zeros(resolution)

    raw = np.array(pts, dtype=np.float64)

    # ── Arc-length resample to `resolution` evenly-spaced points ─────────
    diffs       = np.diff(raw, axis=0)
    seg_lengths = np.sqrt((diffs ** 2).sum(axis=1))
    cumulative  = np.concatenate([[0.0], np.cumsum(seg_lengths)])
    total       = cumulative[-1]
    if total == 0.0:
        return np.zeros(resolution)

    targets   = np.linspace(0.0, total, resolution)
    resampled = np.zeros((resolution, 2), dtype=np.float64)
    for i, t in enumerate(targets):
        idx = min(int(np.searchsorted(cumulative, t, side="right")) - 1,
                  len(raw) - 2)
        seg = seg_lengths[idx]
        if seg == 0.0:
            resampled[i] = raw[idx]
        else:
            resampled[i] = raw[idx] + ((t - cumulative[idx]) / seg) * diffs[idx]

    # ── Signed curvature κ = (x'y'' − y'x'') / (x'² + y'²)^(3/2) ────────
    d1  = np.gradient(resampled, axis=0)
    d2  = np.gradient(d1, axis=0)
    num = d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]
    den = (d1[:, 0] ** 2 + d1[:, 1] ** 2) ** 1.5 + 1e-8
    kappa = num / den

    # ── 5-point moving average to remove noise ────────────────────────────
    smoothed = np.convolve(kappa, np.ones(5) / 5.0, mode="same")

    # ── Normalise to [-1, 1] ──────────────────────────────────────────────
    peak = np.abs(smoothed).max()
    if peak == 0.0:
        return np.zeros(resolution)
    return smoothed / peak


# ============================================================
# VECTOR FIELD
# ============================================================

def _build_field(encodings: list[dict]):
    """Build a vector field V(x) from a list of encoding dicts.

    Each encoding must have:
        signal  : np.ndarray of shape (resolution,), values in [-1, 1]
        weight  : float — normalised contribution of this language

    The field at position x ∈ R³ combines three components per language:
        swirl    — tangential (CCW rotation in XY), weight 0.5
        radial   — outward from origin,             weight 0.3
        vertical — Z driven by curvature signal,    weight 0.8

    The curvature signal maps x-position → Z direction:
        positive curvature → Z up   (left-turning strokes push upward)
        negative curvature → Z down (right-turning strokes push downward)
    Different scripts will therefore weave the streamlines through
    characteristic Z oscillation patterns.
    """
    def V(x: np.ndarray) -> np.ndarray:
        v = np.zeros(3)
        for e in encodings:
            signal = e["signal"]
            w      = e["weight"]

            # X position → index into the curvature signal
            t   = float(np.clip((x[0] + 1.0) / 2.0, 0.0, 1.0))
            idx = int(t * (len(signal) - 1))
            s   = float(signal[idx])          # in [-1, 1]

            # Tangential swirl (counter-clockwise)
            swirl = np.array([-x[1], x[0], 0.0])
            swirl /= np.linalg.norm(swirl) + 1e-6

            # Radial (outward)
            radial = x / (np.linalg.norm(x) + 1e-6)

            # Vertical — glyph curvature drives Z
            vertical = np.array([0.0, 0.0, s])

            v += w * (0.5 * swirl + 0.3 * radial + 0.8 * vertical)

        return v

    return V


# ============================================================
# STREAMLINE INTEGRATION
# ============================================================

def _trace_streamline(
    V,
    start: np.ndarray,
    steps: int = 128,
    dt: float = 0.05,
) -> np.ndarray:
    """Euler-integrate a streamline through field V starting from `start`."""
    pts = []
    pos = start.astype(np.float64).copy()
    for _ in range(steps):
        pos = pos + dt * V(pos)
        pts.append(pos.copy())
    return np.array(pts)   # (steps, 3)


# ============================================================
# SEED PLACEMENT
# ============================================================

def _generate_seeds(n_seeds: int = 8) -> list[np.ndarray]:
    """Place n_seeds points evenly around a circle at z=0."""
    angles = np.linspace(0.0, 2.0 * np.pi, n_seeds, endpoint=False)
    seeds  = []
    for i, angle in enumerate(angles):
        r = 0.3 + 0.1 * np.sin(i)
        seeds.append(np.array([r * np.cos(angle), r * np.sin(angle), 0.0]))
    return seeds


# ============================================================
# PUBLIC REPLAY API  (used by View Map for live language toggling)
# ============================================================

def rebuild_from_encodings(
    encodings: list[dict],
    n_seeds:   int   = 8,
    steps:     int   = 128,
    dt:        float = 0.05,
) -> tuple[list[np.ndarray], np.ndarray]:
    """Re-trace streamlines from a (possibly filtered) list of encodings.

    Call this when the user toggles languages in the View Map — pass only
    the active encodings and weights are renormalised automatically.

    Args:
        encodings : Subset of the saved {language, weight, signal} dicts.
        n_seeds   : Number of seed streamlines to trace.
        steps     : Euler integration steps per streamline.
        dt        : Step size.

    Returns:
        (curves, blended) — list of n_seeds arrays + origin streamline,
        all normalised together to [-1, 1]³.
    """
    if not encodings:
        zero = np.zeros((steps, 3))
        return [zero] * n_seeds, zero

    # Renormalise weights so they sum to 1 for the active subset
    total_w  = sum(float(e["weight"]) for e in encodings)
    adjusted = [
        {"signal": np.asarray(e["signal"], dtype=np.float64),
         "weight": float(e["weight"]) / total_w}
        for e in encodings
    ]

    V      = _build_field(adjusted)
    seeds  = _generate_seeds(n_seeds)
    curves = [_trace_streamline(V, s, steps=steps, dt=dt) for s in seeds]
    blended = _trace_streamline(V, np.zeros(3), steps=steps, dt=dt)

    all_pts = np.vstack(curves + [blended])
    center  = all_pts.mean(axis=0)
    extent  = float(np.abs(all_pts - center).max()) or 1.0
    curves  = [(c - center) / extent for c in curves]
    blended = (blended - center) / extent

    return curves, blended


# ============================================================
# MAIN PIPELINE ENTRY POINT
# ============================================================

def build_rune_map(
    contours:       list[GlyphContour],
    weights:        np.ndarray,
    sample_density: int = 128,
) -> RuneMap:
    """Build the 3D rune from glyph contours.

    Args:
        contours       : HarfBuzz-shaped GlyphContours, one per language.
        weights        : Per-language blend weights (will be normalised).
        sample_density : Euler steps per streamline (= points per curve).

    Returns:
        RuneMap with 8 seed streamlines, 1 origin (blended) streamline,
        and all encoding data needed for interactive replay.
    """
    if not contours:
        raise ValueError("No contours provided.")

    weights   = weights / weights.sum()
    languages = [c.language for c in contours]

    # Step 1 — derive per-language glyph curvature signals
    encodings = []
    for c, w in zip(contours, weights):
        signal = _contour_to_signal(c, resolution=sample_density)
        encodings.append({
            "language": c.language,
            "weight":   float(w),
            "signal":   signal,
        })

    # Step 2 — build collective vector field from all signals
    V = _build_field(encodings)

    # Step 3 — trace 8 streamlines from seed positions
    seeds  = _generate_seeds()
    curves = [_trace_streamline(V, s, steps=sample_density) for s in seeds]

    # Step 4 — trace 9th streamline from origin (the natural "average" path)
    blended = _trace_streamline(V, np.zeros(3), steps=sample_density)

    # Step 5 — normalise all curves together to [-1, 1]³
    all_pts = np.vstack(curves + [blended])
    center  = all_pts.mean(axis=0)
    extent  = float(np.abs(all_pts - center).max()) or 1.0
    curves  = [(c - center) / extent for c in curves]
    blended = (blended - center) / extent

    return RuneMap(
        curves=curves,
        blended=blended,
        weights=weights,
        languages=languages,
        encodings=encodings,
    )
