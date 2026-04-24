"""Render-method package.

Each render strategy lives in its own module inside this package and
exposes a module-level `render(rune_map: RuneMap) -> str` function
that returns a complete SVG document string.

The dispatcher in `pipeline.output.render` auto-discovers every `.py`
file here (except those starting with `_`, e.g. `_util.py`) and
registers it under its filename. To add a new method, drop a file
with a `render()` function — nothing else to wire up.
"""
