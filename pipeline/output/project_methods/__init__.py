"""Project-method package.

Each projection strategy lives in its own module inside this package and
exposes a module-level `project(rune_map: RuneMap) -> np.ndarray` function
that returns an (N, 2) array normalized to [-1, 1].

New methods are wired into the dispatcher by importing the module and
registering it in `pipeline.output.project._REGISTRY`.
"""
