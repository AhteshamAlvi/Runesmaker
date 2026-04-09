"""Normalize and vectorize glyph contours into a common coordinate space."""

import numpy as np
from pipeline.glyph_extract import GlyphContour


def operations_to_points(contour: GlyphContour, sample_density: int = 64) -> np.ndarray:
    """Convert a GlyphContour's drawing operations into a sampled point array.

    Walks through moveTo, lineTo, qCurveTo, curveTo operations and
    samples them into a fixed number of 2D points.

    Args:
        contour: A GlyphContour with drawing operations.
        sample_density: Number of points to sample along the outline.

    Returns:
        Array of shape (sample_density, 2) with normalized coordinates.
    """
    raw_points = []

    for op, args in contour.operations:
        if op in ("moveTo", "lineTo"):
            raw_points.append(args[0])
        elif op == "qCurveTo":
            for pt in args:
                raw_points.append(pt)
        elif op == "curveTo":
            for pt in args:
                raw_points.append(pt)
        elif op == "closePath":
            continue

    if len(raw_points) < 2:
        return np.zeros((sample_density, 2))

    points = np.array(raw_points, dtype=np.float64)
    return resample_points(points, sample_density)


def resample_points(points: np.ndarray, n: int) -> np.ndarray:
    """Resample a polyline to exactly n evenly-spaced points."""
    diffs = np.diff(points, axis=0)
    seg_lengths = np.sqrt((diffs ** 2).sum(axis=1))
    cumulative = np.concatenate([[0], np.cumsum(seg_lengths)])
    total_length = cumulative[-1]

    if total_length == 0:
        return np.tile(points[0], (n, 1))

    targets = np.linspace(0, total_length, n)
    resampled = np.zeros((n, 2))

    for i, t in enumerate(targets):
        idx = np.searchsorted(cumulative, t, side="right") - 1
        idx = min(idx, len(points) - 2)
        seg_len = seg_lengths[idx]
        if seg_len == 0:
            resampled[i] = points[idx]
        else:
            frac = (t - cumulative[idx]) / seg_len
            resampled[i] = points[idx] + frac * diffs[idx]

    return resampled


def normalize(points: np.ndarray) -> np.ndarray:
    """Center and scale points to fit in [-1, 1] x [-1, 1]."""
    center = (points.max(axis=0) + points.min(axis=0)) / 2
    centered = points - center
    extent = (points.max(axis=0) - points.min(axis=0)).max()
    if extent == 0:
        return centered
    return centered / (extent / 2)


def vectorize_contours(contours: list[GlyphContour], sample_density: int = 64) -> np.ndarray:
    """Convert a list of GlyphContours into a matrix of normalized point vectors.

    Args:
        contours: List of GlyphContour objects.
        sample_density: Points per contour.

    Returns:
        Array of shape (n_contours, sample_density, 2).
    """
    vectors = []
    for contour in contours:
        points = operations_to_points(contour, sample_density)
        points = normalize(points)
        vectors.append(points)
    return np.array(vectors)
