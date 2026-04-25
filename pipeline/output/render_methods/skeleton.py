"""Skeleton — graph between origins, edges flowing with the field.

Why this exists
---------------
The streamline-based methods (`multi_stroke`, `path_follow`, …) draw 125
lines that all *flow* with the field. When the field is locally smooth,
neighbouring streamlines stay roughly parallel and the rune reads as
"bundle of curves going the same way" instead of a structured shape.

This method draws explicit *connectivity* — origins are joined by edges
according to the chosen TOPOLOGY (K-NN, MST, or k-MST). Each edge is a
cubic Hermite spline whose endpoint tangents are the field directions at
the endpoints, so all edges meeting at a node leave it along ±V(node) —
junctions read as flowing forks, not stars.

Topology choices give different rune flavours:
    "knn"  — dense web with crossings, loops, multiple paths between any
             two regions; reads as a complex wireframe.
    "mst"  — pure tree (N−1 edges). Maximum readability, every node is a
             real branching point, no cycles. Reads as a "skeleton".
    "kmst" — MST + a handful of loop-closing short edges. Tree backbone
             with a few sigil-like cycles. Default — best of both.
"""

from __future__ import annotations
import numpy as np

from pipeline.rune_map import RuneMap, _build_field
from pipeline.output.render_methods._util import (
    tube_spec,
    render_spec,
)


# ── Config ───────────────────────────────────────────────────────────────────

# Topology — what edges connect the 125 origins.
#   "knn"  : K nearest neighbours per origin (dense, lots of loops, ~2·K·N/2 edges)
#   "mst"  : Minimum spanning tree (N−1 edges, pure tree, max readability)
#   "kmst" : MST + a few shortest non-MST edges (tree with light loop closure)
TOPOLOGY        = "knn"
K_NEIGHBOURS    = 4         # used by "knn"
KMST_EXTRAS     = 18        # used by "kmst" — number of loop-closing edges added on top of MST

EDGE_SAMPLES    = 32        # points per spline sample (smoothness)
TENSION         = 0.9       # 0 = straight chord, 1 = full chord-length tangents,
                            # >1 = exaggerated swoops. Controls how "flowy" edges feel.
TUBE_RADIUS     = 0.010
SIDES           = 8


# ── Geometry helpers ─────────────────────────────────────────────────────────

def _pairwise(origins: np.ndarray) -> np.ndarray:
    """All pairwise distances (symmetric, zero diagonal)."""
    return np.linalg.norm(origins[:, None, :] - origins[None, :, :], axis=-1)


def _knn_edges(origins: np.ndarray, k: int) -> set[tuple[int, int]]:
    """Symmetric K-NN edge set as (lo, hi) index pairs (no self, no dupes)."""
    n = len(origins)
    if n < 2:
        return set()
    k = min(k, n - 1)

    dist = _pairwise(origins)
    np.fill_diagonal(dist, np.inf)
    nbrs = np.argpartition(dist, k, axis=1)[:, :k]      # (n, k)

    edges: set[tuple[int, int]] = set()
    for i in range(n):
        for j in nbrs[i]:
            a, b = (int(i), int(j)) if i < j else (int(j), int(i))
            if a != b:
                edges.add((a, b))
    return edges


def _mst_edges(origins: np.ndarray) -> set[tuple[int, int]]:
    """Euclidean minimum spanning tree via Kruskal + union-find. N−1 edges."""
    n = len(origins)
    if n < 2:
        return set()

    dist = _pairwise(origins)
    iu, ju = np.triu_indices(n, k=1)
    weights = dist[iu, ju]
    order   = np.argsort(weights)

    parent = list(range(n))
    rank   = [0] * n

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> bool:
        ra, rb = find(a), find(b)
        if ra == rb: return False
        if rank[ra] < rank[rb]: ra, rb = rb, ra
        parent[rb] = ra
        if rank[ra] == rank[rb]: rank[ra] += 1
        return True

    out: set[tuple[int, int]] = set()
    for k in order:
        i, j = int(iu[k]), int(ju[k])
        if union(i, j):
            out.add((i, j))
            if len(out) == n - 1:
                break
    return out


def _kmst_edges(origins: np.ndarray, extras: int) -> set[tuple[int, int]]:
    """MST + the `extras` shortest edges not already in the MST.

    Closes a few loops on top of the tree so the rune isn't strictly
    acyclic, but stays much sparser than full K-NN.
    """
    mst = _mst_edges(origins)
    if extras <= 0:
        return mst

    n = len(origins)
    dist = _pairwise(origins)
    iu, ju = np.triu_indices(n, k=1)
    weights = dist[iu, ju]
    order   = np.argsort(weights)

    out = set(mst)
    added = 0
    for k in order:
        i, j = int(iu[k]), int(ju[k])
        edge = (i, j)
        if edge in mst:
            continue
        out.add(edge)
        added += 1
        if added >= extras:
            break
    return out


def _build_edges(origins: np.ndarray) -> set[tuple[int, int]]:
    """Dispatch on the TOPOLOGY config."""
    if TOPOLOGY == "knn":
        return _knn_edges(origins, K_NEIGHBOURS)
    if TOPOLOGY == "mst":
        return _mst_edges(origins)
    if TOPOLOGY == "kmst":
        return _kmst_edges(origins, KMST_EXTRAS)
    raise ValueError(
        f"skeleton: unknown TOPOLOGY {TOPOLOGY!r} — use 'knn', 'mst', or 'kmst'."
    )


def _node_tangent(V, p: np.ndarray, toward: np.ndarray) -> np.ndarray:
    """Unit field direction at `p`, signed to point roughly toward `toward`.

    Every edge meeting at an origin uses the *same* tangent at that origin
    (this function with the same `p`, just different `toward`). The sign
    flip per-edge means each incident edge leaves the node along ±V(p) —
    so all incident edges share one tangent line and the junction reads
    as a flowing fork instead of a star.
    """
    v = V(p)
    n = float(np.linalg.norm(v))
    if n < 1e-8:
        # Field dead here — fall back to chord direction.
        d = toward - p
        nd = float(np.linalg.norm(d))
        return d / nd if nd > 1e-8 else np.array([1.0, 0.0, 0.0])
    u = v / n
    # Flip to point along the chord, not against it.
    if np.dot(u, toward - p) < 0.0:
        u = -u
    return u


def _hermite_edge(
    p0: np.ndarray,
    p1: np.ndarray,
    V,
    samples: int,
) -> np.ndarray:
    """Cubic Hermite curve from p0 to p1, endpoint tangents from the field.

    P(t) = h00·p0 + h10·m0 + h01·p1 + h11·m1
        h00 = 2t³−3t²+1   h10 = t³−2t²+t
        h01 = −2t³+3t²    h11 = t³−t²

    Endpoint tangents `m0`, `m1` are the *field directions at the endpoints*,
    each signed to point along the chord and scaled by `TENSION · length`.
    Because every edge incident on a node uses the same V(node) (modulo
    sign), all edges leave that node along one shared tangent line — no
    more star-shaped junctions, branches flow as one.

    `samples` controls smoothness; cubic geometry doesn't need many points
    in straight regions but more help where the spline curves hard.
    """
    chord  = p1 - p0
    length = float(np.linalg.norm(chord))
    if length < 1e-6:
        return np.vstack([p0, p1])

    # Endpoint tangents — same field direction at each node, signed locally.
    t0 = _node_tangent(V, p0, p1) * (TENSION * length)
    t1 = _node_tangent(V, p1, p0) * (TENSION * length)
    # m1 should leave p1 *toward* p0 reversed — i.e. arriving from p0.
    # Hermite expects "outgoing" tangent at both ends, so flip t1.
    m1 = -t1
    m0 = t0

    t   = np.linspace(0.0, 1.0, samples)[:, None]
    t2  = t * t
    t3  = t2 * t
    h00 =  2*t3 - 3*t2 + 1
    h10 =     t3 - 2*t2 + t
    h01 = -2*t3 + 3*t2
    h11 =     t3 -   t2

    return h00 * p0 + h10 * m0 + h01 * p1 + h11 * m1


# ── Render ───────────────────────────────────────────────────────────────────

def render(rune_map: RuneMap) -> dict:
    if not rune_map.vectors:
        return render_spec("skeleton")

    V       = _build_field(rune_map.vectors)
    origins = np.array([v.origin for v in rune_map.vectors], dtype=np.float64)

    edges = _build_edges(origins)

    tubes: list[dict] = []
    for i, j in edges:
        curve = _hermite_edge(origins[i], origins[j], V, EDGE_SAMPLES)
        t = tube_spec(curve, radius=TUBE_RADIUS, sides=SIDES)
        if t is not None:
            tubes.append(t)

    return render_spec("skeleton", tubes=tubes)
