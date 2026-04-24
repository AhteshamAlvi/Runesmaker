"""3D Rune Map — kernel-smoothed glyph-vector field.

Pipeline
--------
  GlyphContour × N
       │
       ▼  glyph_vector.compute_all_vectors()
  GlyphVector × N      each: origin (3,), direction (3,), magnitude [0,1]
       │
       ▼  _build_field()
  V(x) = Σᵢ magnitude_i · direction_i · exp(−|x − origin_i|² / 2σ²)
         ─────────────────────────────────────────────────────────────
                     Σᵢ magnitude_i · kernel_i(x)
       │
       ▼  _trace_streamline() × N  +  1
  N streamlines    — one per language, starting from that language's origin
  1 blended        — starting from the centroid of all origins
       │
       ├──▶ project.py  → 2D SVG
       └──▶ export.py   → JSON for C++ renderer (tube sweep on blended)

Kernel bandwidth σ = median pairwise distance between origins.
Each vector has local influence — the field near origin_i follows direction_i,
transitioning smoothly to neighbours further away.
"""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np

from pipeline.glyph_extract import GlyphContour
from pipeline.glyph_vector import GlyphVector, compute_all_vectors


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class RuneMap:
    """3D source-of-truth for a generated rune.

    Attributes:
        curves    : N streamlines, one per language, each starting from that
                    language's glyph-derived origin point in 3D space.
        blended   : 1 streamline from the centroid of all origins — the rune's
                    composite centreline for the C++ renderer tube sweep.
        vectors   : The N GlyphVector objects, stored for View Map live replay.
        languages : Language name for each entry (same order as curves/vectors).
    """
    curves:    list[np.ndarray]
    blended:   np.ndarray
    vectors:   list[GlyphVector]
    languages: list[str]
    effects:   list[float]           # per-language share of influence on blended


# ── Vector field ──────────────────────────────────────────────────────────────

def _estimate_bandwidth(origins: np.ndarray) -> float:
    """σ = median pairwise distance between a sample of up to 30 origins."""
    n = len(origins)
    if n < 2:
        return 1.0
    sample = origins[:min(n, 30)]
    dists  = []
    for i in range(len(sample)):
        for j in range(i + 1, len(sample)):
            dists.append(float(np.linalg.norm(sample[i] - sample[j])))
    return float(np.median(dists)) if dists else 1.0


def _build_field(vectors: list[GlyphVector]):
    """Kernel-smoothed vector field from N glyph vectors.

    V(x) = Σᵢ magnitude_i · direction_i · exp(−|x − origin_i|² / 2σ²)
           ──────────────────────────────────────────────────────────────
                        Σᵢ magnitude_i · kernel_i(x)

    Gaussian kernel: each vector has local influence. Near origin_i the
    field strongly follows direction_i; the influence fades with distance
    and the field blends smoothly with neighbouring vectors.
    σ is set to the median pairwise origin distance so no vector is
    isolated and none is smeared across the entire space.
    """
    origins    = np.array([v.origin    for v in vectors], dtype=np.float64)  # (N, 3)
    directions = np.array([v.direction for v in vectors], dtype=np.float64)  # (N, 3)
    magnitudes = np.array([v.magnitude for v in vectors], dtype=np.float64)  # (N,)

    sigma  = _estimate_bandwidth(origins)
    sigma2 = 2.0 * sigma ** 2

    def V(x: np.ndarray) -> np.ndarray:
        diff    = origins - x[np.newaxis, :]          # (N, 3)
        dist2   = (diff ** 2).sum(axis=1)             # (N,)
        kernels = np.exp(-dist2 / sigma2)             # (N,)
        weights = magnitudes * kernels                # (N,)
        total   = weights.sum()
        if total < 1e-12:
            return np.zeros(3)
        return (weights[:, np.newaxis] * directions).sum(axis=0) / total

    return V


def _build_proximity_field(vectors: list[GlyphVector]):
    """Unnormalised kernel-weighted field — magnitude decays with distance.

    V(x) = Σᵢ magnitude_i · direction_i · exp(−|x − origin_i|² / 2σ²)

    Unlike _build_field, there is NO division by Σ kernels, so a query far
    from every origin gets a near-zero vector instead of a smeared average
    of all directions. Near origin_i the field reflects that language's
    direction; in the gaps it fades to nothing.

    Use for visualisation only — streamline integration wants the
    normalised version (uniform step size regardless of distance to a
    source).
    """
    origins    = np.array([v.origin    for v in vectors], dtype=np.float64)
    directions = np.array([v.direction for v in vectors], dtype=np.float64)
    magnitudes = np.array([v.magnitude for v in vectors], dtype=np.float64)

    # Tighter bandwidth than the streamline field — we want locality,
    # not smooth coverage. Half the median pairwise distance works well.
    sigma  = 0.5 * _estimate_bandwidth(origins)
    sigma2 = 2.0 * sigma ** 2

    def V(x: np.ndarray) -> np.ndarray:
        diff    = origins - x[np.newaxis, :]
        dist2   = (diff ** 2).sum(axis=1)
        kernels = np.exp(-dist2 / sigma2)
        weights = magnitudes * kernels
        return (weights[:, np.newaxis] * directions).sum(axis=0)

    return V


# ── Language-influence metric ────────────────────────────────────────────────

# Effect-kernel bandwidth multiplier. Decouples the effect metric from the
# field kernel:
#   k = 1   → proximity-dominated (random hash position decides the ranking)
#   k = 3   → magnitude-dominated, proximity as a soft modulator  ← default
#   k → ∞   → pure magnitude ranking (proximity ignored)
# Raising k flattens the Gaussian so kernels stay close to 1 for every
# language, letting magnitude carry the signal. Complex scripts (CJK,
# Devanagari) dominate again regardless of where their hash placed them.
EFFECT_SIGMA_SCALE = 3.0


def _compute_effects(
    vectors:     list[GlyphVector],
    blended_raw: np.ndarray,
    sigma:       float,
) -> list[float]:
    """Fraction of the blended streamline each language is responsible for.

    Effect of language i = average over blended points p of:
        w_i(p) = magnitude_i · exp(−|p − origin_i|²/2σ_eff²)
                 ────────────────────────────────────────────
                 Σⱼ magnitude_j · exp(−|p − origin_j|²/2σ_eff²)

    where σ_eff = EFFECT_SIGMA_SCALE · σ_field. The wider kernel keeps
    proximity from swamping magnitude — complex scripts still win the
    ranking even when their hash-derived origin lands far from the
    streamline's path.

    Summed across points and divided by streamline length, it's a
    normalised share:
        effect_i ∈ [0, 1],  Σᵢ effect_i = 1

    Computed on the un-normalised blended (so origins and blended share
    the same coordinate space used during field construction).
    """
    if not vectors:
        return []

    origins    = np.array([v.origin    for v in vectors], dtype=np.float64)  # (N, 3)
    magnitudes = np.array([v.magnitude for v in vectors], dtype=np.float64)  # (N,)

    sigma_eff = sigma * EFFECT_SIGMA_SCALE
    sigma2    = 2.0 * sigma_eff ** 2

    # (N_lang, N_blended) kernel & weight arrays
    diffs   = origins[:, np.newaxis, :] - blended_raw[np.newaxis, :, :]
    dist2   = (diffs ** 2).sum(axis=2)
    kernels = np.exp(-dist2 / sigma2)
    weights = magnitudes[:, np.newaxis] * kernels

    totals = weights.sum(axis=0) + 1e-12               # (N_blended,)
    shares = weights / totals[np.newaxis, :]           # per-point share
    return [float(s) for s in shares.mean(axis=1)]     # (N,), sums to 1


# ── Streamline integration ────────────────────────────────────────────────────

def _trace_streamline(
    V,
    start: np.ndarray,
    steps: int   = 128,
    dt:    float = 0.05,
) -> np.ndarray:
    """Euler-integrate a streamline through field V starting from `start`.

    Each step is taken as a unit direction (V normalised) scaled by dt,
    so all streamlines have the same total arc-length regardless of
    field magnitude at their starting position.
    """
    pts = []
    pos = start.astype(np.float64).copy()
    for _ in range(steps):
        v    = V(pos)
        norm = np.linalg.norm(v)
        if norm > 1e-12:
            v = v / norm
        pos = pos + dt * v
        pts.append(pos.copy())
    return np.array(pts)   # (steps, 3)


# ── Replay API (View Map live language toggling) ──────────────────────────────

def rebuild_from_vectors(
    vectors: list[GlyphVector],
    steps:   int   = 128,
    dt:      float = 0.05,
) -> tuple[list[np.ndarray], np.ndarray]:
    """Re-trace streamlines from a (possibly filtered) list of GlyphVectors.

    Called when the user toggles languages in the View Map.
    Magnitudes are re-normalised within the active subset so the field
    retains its character even with only a few languages selected.

    Returns:
        (curves, blended) — list of len(vectors) arrays + centroid streamline,
        all normalised together to [−1, 1]³.
    """
    if not vectors:
        return [], np.zeros((steps, 3))

    max_mag = max(v.magnitude for v in vectors) or 1.0
    adjusted = [
        GlyphVector(
            language=v.language,
            origin=v.origin,
            direction=v.direction,
            magnitude=v.magnitude / max_mag,
        )
        for v in vectors
    ]

    V        = _build_field(adjusted)
    origins  = np.array([v.origin for v in adjusted])
    curves   = [_trace_streamline(V, o, steps=steps, dt=dt) for o in origins]
    centroid = origins.mean(axis=0)
    blended  = _trace_streamline(V, centroid, steps=steps, dt=dt)

    all_pts = np.vstack(curves + [blended])
    center  = all_pts.mean(axis=0)
    extent  = float(np.abs(all_pts - center).max()) or 1.0
    curves  = [(c - center) / extent for c in curves]
    blended = (blended - center) / extent

    return curves, blended


# ── Main pipeline entry point ─────────────────────────────────────────────────

def build_rune_map(
    contours:       list[GlyphContour],
    sample_density: int = 128,
) -> RuneMap:
    """Build the 3D rune from glyph contours.

    Args:
        contours       : HarfBuzz-shaped GlyphContours, one per language.
        sample_density : Euler steps per streamline (= points per curve).

    Returns:
        RuneMap with N language streamlines + 1 blended (centroid) streamline,
        all normalised to [−1, 1]³.
    """
    if not contours:
        raise ValueError("No contours provided.")

    # Step 1 — derive one glyph vector per language (origin, direction, magnitude)
    vectors   = compute_all_vectors(contours)
    languages = [v.language for v in vectors]

    # Step 2 — build kernel-smoothed collective vector field
    V = _build_field(vectors)

    # Step 3 — trace one streamline per language, starting from its origin
    origins = np.array([v.origin for v in vectors])
    curves  = [_trace_streamline(V, o, steps=sample_density) for o in origins]

    # Step 4 — trace blended streamline from centroid of all origins
    centroid = origins.mean(axis=0)
    blended  = _trace_streamline(V, centroid, steps=sample_density)

    # Step 5 — compute per-language share of influence on the blended streamline
    # (done BEFORE normalisation, so origins and blended share the field's
    #  native coordinate space — σ was estimated in that same space).
    sigma   = _estimate_bandwidth(origins)
    effects = _compute_effects(vectors, blended, sigma)

    # Step 6 — normalise all curves together to [−1, 1]³
    all_pts = np.vstack(curves + [blended])
    center  = all_pts.mean(axis=0)
    extent  = float(np.abs(all_pts - center).max()) or 1.0
    curves  = [(c - center) / extent for c in curves]
    blended = (blended - center) / extent

    return RuneMap(
        curves=curves,
        blended=blended,
        vectors=vectors,
        languages=languages,
        effects=effects,
    )
