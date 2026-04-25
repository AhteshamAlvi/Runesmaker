"""Flow-chain — long Hermite curves that thread through multiple origins.

Why this exists
---------------
`path_follow` traces a streamline from each origin: 125 independent
curves shaped by the field. `skeleton` draws K-NN edges between
origins: explicit topology but only ever pairs of nodes. This method
fuses the two.

For each origin O_i we:
    1. Trace a bidirectional streamline through V from O_i (like
       path_follow) — gives a candidate path through space the local
       field carves out.
    2. Find every other origin that lies *near* that path (within
       `WAYPOINT_RADIUS` of any point on the streamline).
    3. Order those origins by their position along the streamline and
       use them — together with O_i — as control points of a single
       cubic-Hermite chain.
    4. Hermite tangent at each waypoint = the field direction at that
       waypoint (signed to point along the chain). This is the same
       trick `skeleton` uses for junctions: every waypoint shared by
       two consecutive segments has one tangent line, so the whole
       chain is C¹-continuous and reads as a single flowing curve.

Result: 125 curves, each one a long flowing thread woven through the
origins it passes near. Where multiple chains pass through the same
origin, they all leave it tangent to the same field direction — so even
the bundle of chains as a whole reads as a coherent flow rather than a
heap of independent lines.

Tube radius scales with the seed origin's magnitude (multi_stroke
flavour), so complex scripts produce thicker chains.
"""

from __future__ import annotations
import numpy as np

from pipeline.rune_map import RuneMap, _build_field
from pipeline.output.render_methods._util import (
    tube_spec,
    render_spec,
    normalize_minmax,
)


# ── Config ───────────────────────────────────────────────────────────────────

# Streamline trace (used to find waypoints — not drawn directly).
TRACE_STEPS         = 80      # per direction (full trace ≤ 2·STEPS+1 points)
TRACE_DT            = 0.03    # arc-length per step (curve uses unit-direction step)
STOP_AMPLITUDE      = 1e-3

# Waypoint pickup.
WAYPOINT_RADIUS     = 0.18    # an origin is a waypoint if any trace point is within this
MAX_WAYPOINTS       = 6       # cap chain length so dense clusters don't make spaghetti

# Hermite chain.
SEGMENT_SAMPLES     = 16      # points per Hermite segment (between consecutive waypoints)
TENSION             = 0.85

# Tubes.
MIN_RADIUS          = 0.006
MAX_RADIUS          = 0.022
SIDES               = 8


# ── Streamline trace (compact, local copy — flow_chain owns its parameters) ──

def _trace_bidirectional(V, start: np.ndarray) -> np.ndarray:
    """Forward + backward unit-step integration through V, anchored at `start`."""
    def _one(sgn: float) -> list[np.ndarray]:
        pts: list[np.ndarray] = []
        pos = start.astype(np.float64).copy()
        for _ in range(TRACE_STEPS):
            v = V(pos) * sgn
            mag = float(np.linalg.norm(v))
            if mag < STOP_AMPLITUDE:
                break
            pos = pos + TRACE_DT * (v / mag)
            pts.append(pos.copy())
        return pts

    fwd  = _one(+1.0)
    back = _one(-1.0)
    return np.array(list(reversed(back)) + [start.astype(np.float64)] + fwd)


# ── Waypoint discovery ───────────────────────────────────────────────────────

def _waypoints_along(
    path:    np.ndarray,        # (P, 3) traced streamline
    origins: np.ndarray,        # (N, 3) all origins
    seed_idx: int,
) -> list[tuple[int, int]]:
    """Find origins close to `path` and return (path_index, origin_index) pairs.

    Each candidate origin is matched to its closest point on the path.
    The list is sorted by path index so consecutive waypoints are in
    flow order. The seed origin is always included.
    """
    # Closest path index for every origin.
    diffs   = origins[:, None, :] - path[None, :, :]      # (N, P, 3)
    dist2   = (diffs ** 2).sum(axis=-1)                   # (N, P)
    min_k   = dist2.argmin(axis=1)                        # (N,)
    min_d2  = dist2[np.arange(len(origins)), min_k]
    threshold2 = WAYPOINT_RADIUS * WAYPOINT_RADIUS

    found: list[tuple[int, int]] = []
    for j in range(len(origins)):
        if j == seed_idx or min_d2[j] < threshold2:
            found.append((int(min_k[j]), j))

    found.sort(key=lambda x: x[0])

    # Cap to MAX_WAYPOINTS — keep the seed plus the closest others, in order.
    if len(found) > MAX_WAYPOINTS:
        # Score by distance to path, but always keep the seed.
        scored = [
            (0.0 if oj == seed_idx else float(min_d2[oj]), pk, oj)
            for pk, oj in found
        ]
        scored.sort(key=lambda x: x[0])              # closest first
        kept = sorted(scored[:MAX_WAYPOINTS], key=lambda x: x[1])  # back to flow order
        found = [(pk, oj) for _, pk, oj in kept]

    return found


# ── Cubic-Hermite chain (C¹ at every interior waypoint) ──────────────────────

def _node_tangent(V, p: np.ndarray, toward: np.ndarray) -> np.ndarray:
    """Unit field direction at `p`, signed to point roughly toward `toward`.

    Same idea as in `skeleton.py`: each interior waypoint gets one
    tangent line (the field direction); consecutive segments share it,
    so the joined chain is C¹-continuous and flows through the node.
    """
    v = V(p)
    n = float(np.linalg.norm(v))
    if n < 1e-8:
        d  = toward - p
        nd = float(np.linalg.norm(d))
        return d / nd if nd > 1e-8 else np.array([1.0, 0.0, 0.0])
    u = v / n
    if np.dot(u, toward - p) < 0.0:
        u = -u
    return u


def _hermite_segment(
    p0: np.ndarray, p1: np.ndarray,
    m0: np.ndarray, m1: np.ndarray,    # tangents (already scaled)
    samples: int,
) -> np.ndarray:
    t   = np.linspace(0.0, 1.0, samples)[:, None]
    t2, t3 = t * t, t * t * t
    h00 =  2*t3 - 3*t2 + 1
    h10 =     t3 - 2*t2 + t
    h01 = -2*t3 + 3*t2
    h11 =     t3 -   t2
    return h00 * p0 + h10 * m0 + h01 * p1 + h11 * m1


def _hermite_chain(waypoints: np.ndarray, V) -> np.ndarray:
    """Stitch cubic Hermite segments through `waypoints` (M, 3).

    Each interior point's tangent is the field direction there, signed
    once *for the whole chain*: pick the sign that aligns with the chord
    going *out* of that node (toward the next waypoint). Because that
    same vector is used by the previous segment as its incoming tangent,
    the join is C¹.
    """
    m = len(waypoints)
    if m < 2:
        return waypoints

    # Per-node "outgoing toward next" tangent unit vectors.
    out_unit = np.zeros_like(waypoints)
    for i in range(m - 1):
        out_unit[i] = _node_tangent(V, waypoints[i], waypoints[i + 1])
    # Last node's outgoing tangent — extrapolate from previous chord.
    out_unit[m - 1] = _node_tangent(V, waypoints[m - 1], 2 * waypoints[m - 1] - waypoints[m - 2])

    pieces: list[np.ndarray] = []
    for i in range(m - 1):
        p0, p1 = waypoints[i], waypoints[i + 1]
        chord  = float(np.linalg.norm(p1 - p0))
        if chord < 1e-6:
            continue
        # m0 leaves p0 toward p1 (already signed). m1 *enters* p1 from p0 —
        # which is the same direction as p1's outgoing-toward-next tangent
        # if we flip sign appropriately. Easier: compute m1 explicitly as
        # the field at p1 signed toward chord direction (i.e. away from p0).
        m0 = out_unit[i] * (TENSION * chord)
        m1 = _node_tangent(V, p1, p1 + (p1 - p0)) * (TENSION * chord)

        seg = _hermite_segment(p0, p1, m0, m1, SEGMENT_SAMPLES)
        # Drop the duplicated start of every segment after the first.
        if pieces:
            seg = seg[1:]
        pieces.append(seg)

    return np.vstack(pieces) if pieces else waypoints


# ── Render ───────────────────────────────────────────────────────────────────

def render(rune_map: RuneMap) -> dict:
    if not rune_map.vectors:
        return render_spec("flow_chain")

    V       = _build_field(rune_map.vectors)
    origins = np.array([v.origin for v in rune_map.vectors], dtype=np.float64)
    mags    = np.array([v.magnitude for v in rune_map.vectors], dtype=np.float64)
    m_norm  = normalize_minmax(mags)

    tubes: list[dict] = []
    for i, seed in enumerate(origins):
        path = _trace_bidirectional(V, seed)
        if len(path) < 4:
            continue

        wp_pairs = _waypoints_along(path, origins, seed_idx=i)
        if len(wp_pairs) < 2:
            # Lonely — fall back to the bare streamline so the language
            # still gets a line. Better than dropping it entirely.
            curve = path
        else:
            wp_pts = origins[[oj for _, oj in wp_pairs]]
            curve  = _hermite_chain(wp_pts, V)

        if len(curve) < 2:
            continue

        radius = MIN_RADIUS + float(m_norm[i]) * (MAX_RADIUS - MIN_RADIUS)
        t = tube_spec(curve, radius=radius, sides=SIDES)
        if t is not None:
            tubes.append(t)

    return render_spec("flow_chain", tubes=tubes)
