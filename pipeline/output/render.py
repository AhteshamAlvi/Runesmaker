"""Render dispatcher — swaps between 2D SVG rendering strategies.

Architecture
------------
    RuneMap
       │
       ▼  render_rune(rune_map, method=None)
    _REGISTRY[method].render(rune_map)   ← one of many render_methods/*.py
       │
       ▼
    SVG string

Each render method is a single module inside `pipeline.output.render_methods`
exposing:

    def render(rune_map: RuneMap) -> str:
        '''Return a complete SVG document string.'''

To add a new method:
    1. Create `pipeline/render_methods/<name>.py` with a `render()` function.
    2. Import it below and add it to `_REGISTRY` under a short key.
    3. Optionally set `CURRENT_METHOD = "<name>"` to make it the default.

Methods are free to reuse existing helpers:
    - `pipeline.output.project.project(rune_map)`  → orthographic (N, 2) projection
    - `pipeline.output.export.to_svg(points, ...)` → single-polyline SVG wrapper
"""

from __future__ import annotations
from typing import Callable
import pkgutil
import importlib

from pipeline.rune_map import RuneMap
from pipeline.output import render_methods as _methods_pkg

# ── Active method ─────────────────────────────────────────────────────────────
#
# Set to the registry key of the method you want `render_rune()` /
# `save_render()` to use when no explicit `method=` argument is passed.
# Empty string means "no default" — callers must pass `method=` or the
# dispatcher raises.
CURRENT_METHOD: str = "multi_stroke"


# ── Registry (auto-discovered) ───────────────────────────────
#
# Every `.py` file inside `pipeline/output/render_methods/` that
# exposes a `render(rune_map) -> str` function is registered
# automatically under its filename (stem).
#
# Files whose name starts with '_' (e.g. `_util.py`) are skipped,
# so private helpers don't leak into the registry.
#
# To add a new method: drop a file in `render_methods/`, define
# `render()` — done. No edits here, no edits in the UI.
_REGISTRY: dict[str, Callable[[RuneMap], str]] = {}

for _info in pkgutil.iter_modules(_methods_pkg.__path__):
    if _info.name.startswith("_"):
        continue

    _mod = importlib.import_module(
        f"{_methods_pkg.__name__}.{_info.name}"
    )

    if callable(getattr(_mod, "render", None)):
        _REGISTRY[_info.name] = _mod.render


# ── Public API ────────────────────────────────────────────────────────────────

def available_methods() -> list[str]:
    """Return the list of registered render-method keys."""
    return sorted(_REGISTRY.keys())


def render_rune(rune_map: RuneMap, method: str | None = None) -> str:
    """Render a RuneMap to an SVG string using the given (or default) method.

    Args:
        rune_map : The 3D RuneMap to render.
        method   : Registry key of the render method. Falls back to
                   `CURRENT_METHOD` when None.

    Raises:
        ValueError : If the registry is empty, no method is selected, or
                     the requested method is unknown.
    """
    if not _REGISTRY:
        raise ValueError(
            "No render methods are registered. Add a module under "
            "`pipeline/render_methods/` and register it in "
            "`pipeline.render._REGISTRY`."
        )

    key = method if method is not None else CURRENT_METHOD
    if not key:
        raise ValueError(
            "No render method selected. Pass `method=<name>` or set "
            "`CURRENT_METHOD` in pipeline/render.py. "
            f"Available: {available_methods()}"
        )
    if key not in _REGISTRY:
        raise ValueError(
            f"Unknown render method {key!r}. Available: {available_methods()}"
        )

    return _REGISTRY[key](rune_map)


def save_render(
    rune_map: RuneMap,
    path:     str,
    method:   str | None = None,
) -> None:
    """Render a RuneMap and write the resulting SVG to `path`."""
    svg = render_rune(rune_map, method=method)
    with open(path, "w") as f:
        f.write(svg)
