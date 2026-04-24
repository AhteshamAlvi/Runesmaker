"""Derive a single 3D vector (origin, direction, magnitude) from a glyph contour.

Each language's translation produces one GlyphVector:

  origin    : SHA-256 hash of the translation string → 4 × 8-byte chunks,
              PLUS a salted re-hash for an independent radius.
              First 3 chunks → (x, y, z) each in [−1, 1].
                direction = (x, y, z) / ||(x, y, z)||
              SHA-256(text + "|r") first 8 bytes → u ∈ [0, 1).
                radius = u^(1/3)                          (volume-uniform)
                origin = radius · direction               (uniform inside ball)
              Salt is essential: deriving radius from the same 3 chunks
              that give direction (e.g. ||raw||/√3) algebraically cancels
              to raw/√3 — a cube, not a sphere. An independent source is
              required. Deterministic per-string.

  direction : Orthonormal-frame + hash-sphere-coordinates.
                Step 1: lift the glyph to 3D by using |κ(t)| as Z so
                        the point cloud has genuine 3D signal.
                Step 2: curvature-weighted 3D PCA → three orthonormal
                        eigenvectors (e₁, e₂, e₃) forming a right-handed
                        frame attached to the glyph. Signs are fixed
                        deterministically (centroid + signal slope for
                        e₁; perpendicular projection for e₂; e₃ = e₁×e₂).
                Step 3: SHA-256(text + "|d") → (α, β, γ) sampled
                        UNIFORMLY on the unit sphere (proper arccos/φ
                        parametrisation, not cube-normalised).
                Step 4: D = α·e₁ + β·e₂ + γ·e₃
                        Automatically unit-length because the basis is
                        orthonormal and the coefficients lie on S².
              Different word, same glyph → same frame, different point
              inside it. Different glyph → rotated frame. Full 3D
              sphere coverage; no axis is structurally privileged.

  magnitude : average of two rank-normalised scores (base), then hash-modulated:
                m_base = (arc_length_rank + stroke_count_rank) / 2
                h      = 4th hash chunk, mapped to [−1, 1]
                m      = clip(m_base · (1 + EPSILON · h), 0, 1)
              The base preserves script-level structure (CJK → high,
              Arabic/Hebrew → low, Latin → mid); the hash adds a small
              deterministic per-word perturbation so same-script siblings
              don't end up with identical magnitudes.
"""

from __future__ import annotations
from dataclasses import dataclass
import hashlib
import numpy as np
from pipeline.glyph.extract import GlyphContour


# Hash-based magnitude perturbation strength.
# 0.05 → subtle; 0.1 → noticeable but still structured; 0.2 → strong.
EPSILON = 0.10

# Curvature-weighting floor for PCA. Keeps straight segments from being
# ignored entirely when |κ| ≈ 0.
CURVATURE_FLOOR = 0.10


@dataclass
class GlyphVector:
    """One language's contribution to the rune vector field."""
    language:  str
    origin:    np.ndarray   # (3,) position in shared 3D space
    direction: np.ndarray   # (3,) unit vector
    magnitude: float        # [0, 1] after rank-normalisation + hash modulation


# ── Hash-based origin ─────────────────────────────────────────────────────────

def _hash_chunks(text: str) -> tuple[float, float, float, float]:
    """SHA-256(text) → 4 × 64-bit chunks → 4 signed floats in [−1, 1].

    Deterministic and well-distributed: flipping one character in the input
    scrambles all 32 output bytes, so related translations land far apart.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()   # 32 bytes
    out = []
    for i in range(4):
        u = int.from_bytes(digest[i * 8:(i + 1) * 8], "big", signed=False)
        out.append(u / float(1 << 64) * 2.0 - 1.0)           # [−1, 1)
    return tuple(out)   # type: ignore[return-value]


def _hash_origin(text: str) -> np.ndarray:
    """Uniformly-inside-the-unit-ball origin from hash chunks.

    Direction comes from the first 3 SHA-256 chunks of `text`.
    Radius comes from a SALTED re-hash, SHA-256(text + "|r"), so it is
    statistically independent of the direction. Without the salt, the
    only 3-chunk-derived radius is ||raw||, which algebraically cancels
    and collapses the distribution to a cube.

    Radius uses u^(1/3) so the resulting points are uniform by volume
    inside the unit ball, not concentrated near the centre.
    """
    x, y, z, _ = _hash_chunks(text)
    raw  = np.array([x, y, z], dtype=np.float64)
    norm = float(np.linalg.norm(raw))
    if norm < 1e-12:
        return np.zeros(3)
    direction = raw / norm

    # Independent radius from a salted hash.
    salt_digest = hashlib.sha256((text + "|r").encode("utf-8")).digest()
    u = int.from_bytes(salt_digest[:8], "big", signed=False) / float(1 << 64)
    radius = u ** (1.0 / 3.0)   # volume-uniform in unit ball

    return radius * direction


def _hash_perturbation(text: str) -> float:
    """4th hash chunk → h ∈ [−1, 1] for centred magnitude modulation."""
    return _hash_chunks(text)[3]


# ── Geometry helpers ─────────────────────────────────────────────────────────

def _extract_points(contour: GlyphContour) -> np.ndarray:
    """Collect all (x, y) coordinate points from a contour's operations."""
    pts = []
    for op, args in contour.operations:
        if op in ("moveTo", "lineTo"):
            pts.append(args[0])
        elif op in ("curveTo", "qCurveTo"):
            for pt in args:
                pts.append(pt)
    return np.array(pts, dtype=np.float64) if pts else np.zeros((1, 2))


def _curvature_signal(pts: np.ndarray, resolution: int = 128) -> np.ndarray:
    """Arc-length-resampled signed curvature, normalised to [−1, 1].

    Used for the PCA sign tie-breaker (Step 2 in _pca_direction).
    """
    if len(pts) < 3:
        return np.zeros(resolution)

    diffs       = np.diff(pts, axis=0)
    seg_lengths = np.sqrt((diffs ** 2).sum(axis=1))
    cumulative  = np.concatenate([[0.0], np.cumsum(seg_lengths)])
    total       = cumulative[-1]
    if total == 0.0:
        return np.zeros(resolution)

    targets   = np.linspace(0.0, total, resolution)
    resampled = np.zeros((resolution, 2))
    for i, t in enumerate(targets):
        idx = min(int(np.searchsorted(cumulative, t, side="right")) - 1, len(pts) - 2)
        seg = seg_lengths[idx]
        resampled[i] = (pts[idx] if seg == 0.0
                        else pts[idx] + ((t - cumulative[idx]) / seg) * diffs[idx])

    d1    = np.gradient(resampled, axis=0)
    d2    = np.gradient(d1, axis=0)
    num   = d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]
    den   = (d1[:, 0] ** 2 + d1[:, 1] ** 2) ** 1.5 + 1e-8
    kappa = num / den

    smoothed = np.convolve(kappa, np.ones(5) / 5.0, mode="same")
    peak = np.abs(smoothed).max()
    return smoothed / peak if peak > 0.0 else smoothed


def _per_point_curvature(pts: np.ndarray) -> np.ndarray:
    """Unsigned curvature |κ(t)| sampled at every contour point.

    Uses central-differences on the raw point sequence (no resampling),
    so the output aligns 1-1 with `pts` and can weight the covariance
    in Method 3. Degenerate cases (very short contour) return uniform
    weights so PCA still runs.
    """
    n = len(pts)
    if n < 3:
        return np.ones(n)
    d1 = np.gradient(pts, axis=0)
    d2 = np.gradient(d1, axis=0)
    num = d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]
    den = (d1[:, 0] ** 2 + d1[:, 1] ** 2) ** 1.5 + 1e-8
    return np.abs(num / den)


def _lifted_points_3d(pts: np.ndarray) -> np.ndarray:
    """Lift 2D contour points to 3D using |κ| as the Z coordinate.

    The curvature axis is rescaled to match the XY bounding-box span so
    PCA doesn't see Z as a "short" axis and systematically demote it.

    Degenerate case (fewer than 3 points ⇒ no curvature): return the 2D
    points padded with Z=0. PCA on that collapses back to effectively 2D,
    which is the best we can do.
    """
    n = len(pts)
    if n < 3:
        return np.column_stack([pts, np.zeros(n)])
    kappa    = _per_point_curvature(pts)
    xy_range = max(float(np.ptp(pts[:, 0])), float(np.ptp(pts[:, 1]))) or 1.0
    k_max    = float(np.abs(kappa).max()) or 1.0
    z        = (kappa / k_max) * (xy_range * 0.5)
    return np.column_stack([pts, z])


def _glyph_frame(pts_3d: np.ndarray, signal: np.ndarray
                 ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Right-handed orthonormal frame (e₁, e₂, e₃) from curvature-weighted 3D PCA.

    Weights: wᵢ = |κ(pᵢ)| + CURVATURE_FLOOR, computed on the 2D
    projection of the lifted points (same curvature signal used to lift).

    Sign determination — fully deterministic, matches the previous 2D
    pipeline where it can:
      e₁: centroid alignment (orient toward the furthest contour point),
          then signal-slope tie-breaker (flip if curvature mean-slope < 0).
      e₂: project the reference vector into the plane perpendicular to
          e₁; orient e₂ with that perpendicular component.
      e₃: e₁ × e₂ — forces a right-handed frame so it's a proper rotation.
    """
    n = len(pts_3d)
    if n < 2:
        return (np.array([1.0, 0.0, 0.0]),
                np.array([0.0, 1.0, 0.0]),
                np.array([0.0, 0.0, 1.0]))

    # Curvature weighting (still valid in 3D — 2D curvature is what defines
    # features; Z is just a lift of that same signal).
    kappa_2d = _per_point_curvature(pts_3d[:, :2])
    w        = kappa_2d + CURVATURE_FLOOR
    w_sum    = float(w.sum()) or 1.0

    centroid = (w[:, np.newaxis] * pts_3d).sum(axis=0) / w_sum
    centered = pts_3d - centroid
    cov      = (centered.T * w) @ centered / w_sum

    _, eigenvectors = np.linalg.eigh(cov)             # ascending order
    e1 = eigenvectors[:, -1].copy()
    e2 = eigenvectors[:, -2].copy()

    # Reference: the furthest point from the weighted centroid.
    diffs = pts_3d - centroid
    ref   = pts_3d[int(np.argmax(np.linalg.norm(diffs, axis=1)))] - centroid

    # e₁ sign — centroid alignment + signal-slope tie-breaker
    if np.dot(e1, ref) < 0:
        e1 = -e1
    if len(signal) > 1 and float(np.mean(np.diff(signal))) < 0:
        e1 = -e1

    # e₂ sign — project ref into the plane ⊥ e₁, align e₂ with it
    ref_perp      = ref - np.dot(ref, e1) * e1
    ref_perp_norm = float(np.linalg.norm(ref_perp))
    if ref_perp_norm > 1e-8 and np.dot(e2, ref_perp) < 0:
        e2 = -e2

    # e₃ — force right-handed via cross product
    e3 = np.cross(e1, e2)
    e3_norm = float(np.linalg.norm(e3))
    e3 = e3 / e3_norm if e3_norm > 1e-8 else np.array([0.0, 0.0, 1.0])

    return e1, e2, e3


def _hash_direction_coords(text: str) -> np.ndarray:
    """Uniformly-random unit-sphere point (α, β, γ) from SHA-256(text + "|d").

    Uses the standard inverse-CDF trick for uniformity on S²:
        θ = arccos(1 − 2u),  φ = 2π · v
    with u, v drawn independently from [0, 1) via two 64-bit hash chunks.
    This is genuinely uniform (cube-normalised isn't — corners get stretched).

    The "|d" salt makes the direction hash statistically independent from
    the origin hash (no salt) and the radius hash ("|r"), so a language's
    origin and direction aren't correlated by shared bits.
    """
    digest = hashlib.sha256((text + "|d").encode("utf-8")).digest()
    u = int.from_bytes(digest[0:8],  "big", signed=False) / float(1 << 64)
    v = int.from_bytes(digest[8:16], "big", signed=False) / float(1 << 64)
    theta = np.arccos(1.0 - 2.0 * u)
    phi   = 2.0 * np.pi * v
    return np.array([
        np.sin(theta) * np.cos(phi),
        np.sin(theta) * np.sin(phi),
        np.cos(theta),
    ], dtype=np.float64)


def _pca_direction(pts: np.ndarray, signal: np.ndarray, text: str) -> np.ndarray:
    """Orthonormal-frame + hash-sphere-coordinates direction.

    Glyph → frame (e₁, e₂, e₃) via curvature-lifted 3D PCA.
    Word  → uniform (α, β, γ) on the unit sphere via salted hash.

        D = α·e₁ + β·e₂ + γ·e₃

    Unit-length by construction (orthonormal basis × unit-sphere coeffs).

    Properties:
      • Deterministic per (glyph, word) pair.
      • Different words, same glyph → same frame, different direction.
      • Different glyphs, same word → rotated frame, different direction.
      • Full sphere coverage — no axis privileged, no structural bias.
    """
    if len(pts) < 2:
        # No usable geometry — fall back to pure hash sphere sample.
        return _hash_direction_coords(text)

    pts_3d         = _lifted_points_3d(pts)
    e1, e2, e3     = _glyph_frame(pts_3d, signal)
    alpha, beta, gamma = _hash_direction_coords(text)

    D = alpha * e1 + beta * e2 + gamma * e3
    norm = float(np.linalg.norm(D))
    return D / norm if norm > 1e-8 else np.array([1.0, 0.0, 0.0])


def _arc_length(pts: np.ndarray) -> float:
    """Total arc-length of the glyph outline."""
    diffs = np.diff(pts, axis=0)
    return float(np.sqrt((diffs ** 2).sum(axis=1)).sum())


def _stroke_count(contour: GlyphContour) -> int:
    """Number of strokes = number of moveTo operations."""
    return sum(1 for op, _ in contour.operations if op == "moveTo")


def _rank_normalize(values: list[float]) -> list[float]:
    """Map raw values to rank-based [0, 1] scores. Ties share the same rank."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0.5]
    sorted_unique = sorted(set(values))
    if len(sorted_unique) == 1:
        return [0.5] * n
    rank_map = {v: i / (len(sorted_unique) - 1) for i, v in enumerate(sorted_unique)}
    return [rank_map[v] for v in values]


# ── Public API ────────────────────────────────────────────────────────────────

def compute_all_vectors(contours: list[GlyphContour]) -> list[GlyphVector]:
    """Compute one GlyphVector per contour.

    Two-pass:
      Pass 1 — per-glyph: hash-based origin, PCA direction, arc_length, strokes,
               and hash perturbation h.
      Pass 2 — rank-normalise arc_length and stroke_count, average to m_base,
               then modulate: m = clip(m_base · (1 + EPSILON · h), 0, 1).

    Args:
        contours: List of GlyphContour objects (one per language).

    Returns:
        List of GlyphVector objects, same order as contours.
    """
    if not contours:
        return []

    # Pass 1 — per-glyph raw values
    records = []
    for c in contours:
        pts    = _extract_points(c)
        signal = _curvature_signal(pts)
        records.append({
            "language":  c.language,
            "origin":    _hash_origin(c.character),
            "direction": _pca_direction(pts, signal, c.character),
            "arc_len":   _arc_length(pts),
            "strokes":   float(_stroke_count(c)),
            "h":         _hash_perturbation(c.character),
        })

    # Pass 2 — rank-normalise magnitude components, then hash-modulate
    arc_ranks    = _rank_normalize([r["arc_len"] for r in records])
    stroke_ranks = _rank_normalize([r["strokes"] for r in records])

    vectors = []
    for r, ar, sr in zip(records, arc_ranks, stroke_ranks):
        m_base = (ar + sr) / 2.0
        m      = float(np.clip(m_base * (1.0 + EPSILON * r["h"]), 0.0, 1.0))
        vectors.append(GlyphVector(
            language=r["language"],
            origin=r["origin"],
            direction=r["direction"],
            magnitude=m,
        ))
    return vectors
