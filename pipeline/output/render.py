"""Render dispatcher — swaps between 3D render-spec strategies.

Architecture
------------
    RuneMap
       │
       ▼  render_rune(rune_map, method=None)
    _REGISTRY[method].render(rune_map)   ← one of many render_methods/*.py
       │
       ▼
    dict   (JSON-serialisable 3D render spec, version 5)
       │
       ▼  save_render(..., path)
    path/to/<name>__<method>.json
       │
       ▼  (consumed by the C++ Vulkan renderer)
    Interactive 3D tube / sphere geometry.

Each render method is a single module inside `pipeline.output.render_methods`
exposing:

    def render(rune_map: RuneMap) -> dict:
        '''Return a render-spec dict. See _util.SPEC_VERSION for schema.'''

To add a new method:
    1. Create `pipeline/output/render_methods/<name>.py` with a
       `render(rune_map) -> dict` function.
    2. (Optional) Set `CURRENT_METHOD = "<name>"` below to make it
       the default.
    Auto-discovery handles the rest — the UI dropdown picks it up
    on next launch without any code changes.

Methods are free to reuse:
    - `pipeline.output.render_methods._util`      → tube/sphere spec primitives
    - `pipeline.rune_map._build_field`             → re-integrate the vector field
"""

from __future__ import annotations
from typing import Callable
import json
import pkgutil
import importlib

from pipeline.rune_map import RuneMap
from pipeline.output import render_methods as _methods_pkg

# ── Active method ─────────────────────────────────────────────────────────────

CURRENT_METHOD: str = "multi_stroke"


# ── Registry (auto-discovered) ───────────────────────────────────────────────
#
# Every `.py` file inside `pipeline/output/render_methods/` that exposes a
# `render(rune_map) -> dict` function is registered automatically under its
# filename stem. Files whose name starts with '_' (e.g. `_util.py`) are
# skipped so private helpers don't leak into the registry.
_REGISTRY: dict[str, Callable[[RuneMap], dict]] = {}

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


def render_rune(rune_map: RuneMap, method: str | None = None) -> dict:
    """Render a RuneMap to a 3D render-spec dict using the given (or default) method."""
    if not _REGISTRY:
        raise ValueError(
            "No render methods are registered. Add a module under "
            "`pipeline/output/render_methods/` that defines `render(rune_map) -> dict`."
        )

    key = method if method is not None else CURRENT_METHOD
    if not key:
        raise ValueError(
            "No render method selected. Pass `method=<name>` or set "
            "`CURRENT_METHOD` in pipeline/output/render.py. "
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
    """Render a RuneMap and write the resulting spec JSON to `path`."""
    spec = render_rune(rune_map, method=method)
    with open(path, "w") as f:
        json.dump(spec, f, indent=2)
