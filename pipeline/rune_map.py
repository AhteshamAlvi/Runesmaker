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
       ├──▶ output/project.py  → 2D coords (N, 2) in [-1, 1]
       │      └──▶ output/render_methods/*  → SVG documents
       └──▶ output/export.py   → JSON for C++ renderer (tube sweep on blended)

Kernel bandwidth σ = median pairwise distance between origins.
Each vector has local influence — the field near origin_i follows direction_i,
transitioning smoothly to neighbours further away.
"""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np

from pipeline.glyph.extract import GlyphContour
from pipeline.glyph.vector import GlyphVector, compute_all_vectors


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

def _estimate_bandwidth(origins: np.ndarray, k: int = 4) -> float:
    """σ = mean distance to the k-th nearest neighbour, averaged across origins.

    Why k-NN, not median pairwise:
        Median pairwise distance is a *global* scale — for a 125-origin
        cloud filling [-1,1]³ it lands around 0.7, almost the cube's
        diameter. A Gaussian that wide makes every origin influence every
        query point equally, which collapses the field to a global mean
        direction and bundles all streamlines into one direction.

        k-NN distance is a *local* scale — the typical gap between an
        origin and its few nearest neighbours. With k=4 in our cloud
        that's around 0.10–0.15, so the Gaussian only spans the immediate
        neighbourhood and the field actually varies across space.
    """
    n = len(origins)
    if n < 2:
        return 1.0
    k = min(k, n - 1)
    dist = np.linalg.norm(origins[:, None, :] - origins[None, :, :], axis=-1)
    np.fill_diagonal(dist, np.inf)
    knn = np.partition(dist, k - 1, axis=1)[:, :k]   # k smallest per row
    return float(np.mean(knn))

def _build_field(vectors: list[GlyphVector]):
    """Local, *unnormalised* kernel-weighted vector field.

    V(x) = Σᵢ magnitude_i · direction_i · exp(−|x − origin_i|² / 2σ²)

    Two design choices that matter for streamline structure:

    1. **Local σ** — set from k-NN origin distance (see `_estimate_bandwidth`),
       not the global median, so the kernel only spans each origin's
       immediate neighbourhood. Different regions of space follow
       different local directions.

    2. **No normalisation** — we deliberately omit the `/ Σ kernels`
       divisor used by classical kernel regression. With normalisation,
       a query far from every origin still receives a *unit-weighted*
       average of all directions, which smears everything into one
       direction. Without it, the field amplitude fades to zero in
       empty regions, and the streamline integrator can detect the
       fade-out and stop instead of drifting through dead space.

    The unnormalised amplitude carries information (it tracks proximity
    to a meaningful origin), so callers should normalise the *direction*
    only when they need a uniform-step integrator.

    V(x) = Σᵢ wᵢ · (directionᵢ + α · vortexᵢ)

    where:
        wᵢ = magnitudeᵢ · exp(−|x − originᵢ|² / 2σ²)
        vortexᵢ = directionᵢ × (x − originᵢ)

    This introduces *circulatory structure* (swirls, loops, bending)
    while preserving the original directional flow.

    Design:
        - Direction term → drives flow
        - Vortex term    → bends flow around origins
        - Both are local (same kernel)
    """

    origins    = np.array([v.origin    for v in vectors], dtype=np.float64)  # (N, 3)
    directions = np.array([v.direction for v in vectors], dtype=np.float64)  # (N, 3)
    magnitudes = np.array([v.magnitude for v in vectors], dtype=np.float64)  # (N,)

    sigma  = _estimate_bandwidth(origins)
    sigma2 = 2.0 * sigma ** 2

    # 🔥 Key parameter — tune this
    VORTEX_STRENGTH = 0.35

    def V(x: np.ndarray) -> np.ndarray:
        diff  = x[np.newaxis, :] - origins        # (N, 3)  ← note direction
        dist2 = (diff ** 2).sum(axis=1)           # (N,)

        kernels = np.exp(-dist2 / sigma2)         # (N,)
        weights = magnitudes * kernels            # (N,)

        # ── Directional component ──
        directional = directions                  # (N, 3)

        # ── Rotational component ──
        # cross(direction, radial vector)
        vortex = np.cross(directions, diff)       # (N, 3)

        # Optional: scale vortex by distance (prevents blow-up far away)
        dist = np.sqrt(dist2) + 1e-8
        vortex = vortex / (1.0 + dist[:, None])   # stabilizer

        # ── Combine ──
        field = directional + VORTEX_STRENGTH * vortex

        return (weights[:, None] * field).sum(axis=0)

    return V

def _build_blended_field(vectors: list[GlyphVector]):
    """Globally-smoothed *normalised* field — used only for the centroid trace.

    Same form as the original `_build_field` (median-pairwise σ, normalised
    by Σ kernels). The blended streamline is supposed to be the rune's
    averaged "spine" so we want a globally-smoothed direction at the
    centroid; the local field would just stop immediately if the centroid
    sits in an empty region.
    """
    origins    = np.array([v.origin    for v in vectors], dtype=np.float64)
    directions = np.array([v.direction for v in vectors], dtype=np.float64)
    magnitudes = np.array([v.magnitude for v in vectors], dtype=np.float64)

    # Global bandwidth — keep the wider median-pairwise σ that the original
    # field used. The blended trace is the "average path", not a local one.
    n = len(origins)
    if n >= 2:
        sample = origins[:min(n, 30)]
        d = np.linalg.norm(sample[:, None, :] - sample[None, :, :], axis=-1)
        sigma = float(np.median(d[np.triu_indices_from(d, k=1)]))
    else:
        sigma = 1.0
    sigma2 = 2.0 * sigma ** 2

    def V(x: np.ndarray) -> np.ndarray:
        diff    = origins - x[np.newaxis, :]
        dist2   = (diff ** 2).sum(axis=1)
        kernels = np.exp(-dist2 / sigma2)
        weights = magnitudes * kernels
        total   = weights.sum()
        if total < 1e-12:
            return np.zeros(3)
        return (weights[:, np.newaxis] * directions).sum(axis=0) / total

    return V


# NOTE: `_build_field` is now the local, unnormalised field that View Map
# previously asked for under the name `_build_proximity_field`. The two
# concepts have merged — there's only one field shape now, and callers
# that want a smoothed global average use `_build_blended_field`.
_build_proximity_field = _build_field   # back-compat alias for View Map


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
    steps: int = 128,
    dt: float = 0.02,
    stop_amplitude: float = 1e-3,
    max_step: float = 0.05,
) -> np.ndarray:
    """Bidirectional streamline through field V, anchored at `start`.

    Traces forward (V) and backward (−V) from `start`, glues the two
    halves together, and returns the combined polyline with `start` at
    the midpoint. Each Euler step uses the field *direction* (unit
    vector) so all valid steps have arc length `dt` regardless of the
    field amplitude — visual consistency across slow and fast regions.

    Why bidirectional + early-stop:
        With the local unnormalised field, a streamline that wanders
        out of any origin's neighbourhood reaches a near-zero amplitude.
        We stop the trace there instead of integrating noise. Origins
        sit in the middle of their streamline, not at the leading edge,
        so the curve covers the language's *neighbourhood* rather than
        marching downstream and out of the rune.

    `steps` is the per-direction step budget — the full curve has up
    to `2·steps + 1` points (start + forward + backward).

    Upgrades:
        - Uses unnormalised field (pos += dt * V(x))
        - RK2-style look-ahead integration (captures curvature)
        - Early stop when field fades (local behavior)
        - Step clamping for stability
        - Final smoothing pass for clean curves
    """

    def _step(pos: np.ndarray, direction_sign: float) -> tuple[np.ndarray, float]:
        """Single RK2 integration step."""
        FIELD_SCALE = 2.5
        v0 = FIELD_SCALE * V(pos) * direction_sign
        mag0 = np.linalg.norm(v0)

        if mag0 < stop_amplitude:
            return pos, mag0

        # Look-ahead (RK2-style)
        v1 = V(pos + dt * v0) * direction_sign

        # Blend current + future direction
        v = 0.6 * v0 + 0.4 * v1
        pos = pos + dt * v
        return pos, np.linalg.norm(v)

    def _trace_one(direction_sign: float) -> list[np.ndarray]:
        pts: list[np.ndarray] = []
        pos = start.astype(np.float64).copy()

        for _ in range(steps):
            pos, mag = _step(pos, direction_sign)

            if mag < stop_amplitude:
                break

            pts.append(pos.copy())

        return pts

    # ── Trace both directions ──
    forward  = _trace_one(+1.0)
    backward = _trace_one(-1.0)

    # Combine into full curve (backward → start → forward)
    curve = list(reversed(backward)) + [start.astype(np.float64)] + forward

    if len(curve) < 3:
        return np.array(curve)

    # ── Smoothing pass ──
    c = np.array(curve)
    out = c.copy()

    for i in range(1, len(c) - 1):
        out[i] = 0.15 * c[i - 1] + 0.7 * c[i] + 0.15 * c[i + 1]

    # Optional second pass for extra smoothness
    # out = _smooth_curve(out)  # if you later extract helper

    return out

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

    V_local   = _build_field(adjusted)
    V_blended = _build_blended_field(adjusted)
    origins   = np.array([v.origin for v in adjusted])
    curves    = [_trace_streamline(V_local, o, steps=steps, dt=dt) for o in origins]
    centroid  = origins.mean(axis=0)
    blended   = _trace_streamline(V_blended, centroid, steps=steps, dt=dt)

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

    # Step 2 — build the two fields:
    #   V_local   — narrow, unnormalised, per-language streamlines stay in
    #               their origin's neighbourhood (gives structure)
    #   V_blended — wide, normalised, only used to trace the centroid spine
    V_local   = _build_field(vectors)
    V_blended = _build_blended_field(vectors)

    # Step 3 — trace one streamline per language, starting from its origin
    origins = np.array([v.origin for v in vectors])
    curves  = [_trace_streamline(V_local, o, steps=sample_density) for o in origins]

    # Step 4 — trace blended streamline from centroid of all origins
    centroid = origins.mean(axis=0)
    blended  = _trace_streamline(V_blended, centroid, steps=sample_density)

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
