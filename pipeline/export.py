"""Export a rune contour to SVG or JSON for the C++ renderer."""

import json
import numpy as np


def to_svg(points: np.ndarray, size: int = 512, stroke_width: float = 2.0) -> str:
    """Convert a rune contour to an SVG string.

    Args:
        points: Array of shape (n, 2) with coordinates in [-1, 1].
        size: SVG canvas size in pixels.
        stroke_width: Stroke width.

    Returns:
        SVG string.
    """
    margin = size * 0.1
    scale = (size - 2 * margin) / 2
    center = size / 2

    # Transform from [-1,1] to SVG coordinates
    svg_points = points * [scale, -scale] + [center, center]

    path_data = f"M {svg_points[0][0]:.2f} {svg_points[0][1]:.2f}"
    for pt in svg_points[1:]:
        path_data += f" L {pt[0]:.2f} {pt[1]:.2f}"
    path_data += " Z"

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{size}" height="{size}" viewBox="0 0 {size} {size}">\n'
        f'  <path d="{path_data}" fill="none" stroke="white" '
        f'stroke-width="{stroke_width}" stroke-linejoin="round"/>\n'
        f'</svg>'
    )


def to_json(points: np.ndarray) -> str:
    """Convert a rune contour to JSON for the C++ renderer.

    Args:
        points: Array of shape (n, 2) with coordinates in [-1, 1].

    Returns:
        JSON string with contour points.
    """
    data = {
        "version": 1,
        "points": points.tolist(),
    }
    return json.dumps(data, indent=2)


def save_svg(points: np.ndarray, path: str, **kwargs) -> None:
    """Save rune contour as SVG file."""
    with open(path, "w") as f:
        f.write(to_svg(points, **kwargs))


def save_json(points: np.ndarray, path: str) -> None:
    """Save rune contour as JSON file for the renderer."""
    with open(path, "w") as f:
        f.write(to_json(points))
