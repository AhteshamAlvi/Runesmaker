"""Blend multiple normalized glyph contours into a single composite rune shape."""

import numpy as np


def mean_blend(vectors: np.ndarray, weights: np.ndarray | None = None) -> np.ndarray:
    """Blend contours by weighted average.

    Args:
        vectors: Array of shape (n_contours, sample_density, 2).
        weights: Optional array of shape (n_contours,). Defaults to uniform.

    Returns:
        Blended contour of shape (sample_density, 2).
    """
    if weights is None:
        return vectors.mean(axis=0)

    weights = weights / weights.sum()
    return np.einsum("i,ijk->jk", weights, vectors)


def median_blend(vectors: np.ndarray) -> np.ndarray:
    """Blend contours by taking the median at each point.

    More robust to outlier glyphs than mean blending.

    Args:
        vectors: Array of shape (n_contours, sample_density, 2).

    Returns:
        Blended contour of shape (sample_density, 2).
    """
    return np.median(vectors, axis=0)


def blend_rune(vectors: np.ndarray, method: str = "mean", weights: np.ndarray | None = None) -> np.ndarray:
    """Blend glyph vectors into a composite rune.

    Args:
        vectors: Array of shape (n_contours, sample_density, 2).
        method: "mean" or "median".
        weights: Optional weights for mean blending.

    Returns:
        Composite rune contour of shape (sample_density, 2).
    """
    if method == "mean":
        return mean_blend(vectors, weights)
    elif method == "median":
        return median_blend(vectors)
    else:
        raise ValueError(f"Unknown blend method: {method}")
