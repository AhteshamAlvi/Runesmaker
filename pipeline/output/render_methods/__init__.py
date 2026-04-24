"""Render-method package.

Each render strategy lives in its own module inside this package and exposes
a module-level `render(rune_map: RuneMap) -> str` function that returns a
complete SVG document string.

New methods are wired into the dispatcher by importing the module and
registering it in `pipeline.render._REGISTRY`.
"""
