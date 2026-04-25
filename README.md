# Runesmaker

Generate a unique 3D rune for any word, by translating it into 124 languages, deriving one 3D vector per language from the shape of its written form, smoothing those vectors into a continuous field, tracing curves through the field, and rendering the result as a tube-swept mesh in a Vulkan viewer.

The same word always produces the same rune. Different words produce different runes. The construction is deterministic from beginning to end — every random choice is seeded by a hash of either the word, the language, or both.

This README walks the entire pipeline top-to-bottom, with the math at every step and the reasoning behind each design choice.

---

## Table of contents

1. [Pipeline overview](#pipeline-overview)
2. [Step 1 — Translation](#step-1--translation)
3. [Step 2 — Glyph extraction](#step-2--glyph-extraction)
4. [Step 3 — Glyph vector derivation](#step-3--glyph-vector-derivation)
5. [Step 4 — Vector field construction](#step-4--vector-field-construction)
6. [Step 5 — Streamline tracing](#step-5--streamline-tracing)
7. [Step 6 — Language influence (effects)](#step-6--language-influence-effects)
8. [Step 7 — Render methods (geometry generation)](#step-7--render-methods-geometry-generation)
9. [Step 8 — Render dispatcher and spec format](#step-8--render-dispatcher-and-spec-format)
10. [Step 9 — Vulkan tube renderer (C++)](#step-9--vulkan-tube-renderer-c)
11. [UI flow](#ui-flow)
12. [File layout](#file-layout)
13. [Parameter reference](#parameter-reference)

---

## Pipeline overview

```
       word
        │
        ▼  pipeline/input/auto_translate.py
  124 translations              { language → translated word }
        │
        ▼  pipeline/glyph/extract.py     (HarfBuzz + fontTools)
  124 GlyphContours             { ops, width, height } per language
        │
        ▼  pipeline/glyph/vector.py
  124 GlyphVectors              ( origin ∈ ℝ³, direction ∈ S², magnitude ∈ [0,1] )
        │
        ▼  pipeline/rune_map.py        _build_field()
  V : ℝ³ → ℝ³                   kernel-smoothed vector field
        │
        ▼  pipeline/rune_map.py        _trace_streamline()
  124 streamlines + 1 blended   bidirectional Euler/RK2 integration
        │
        ▼  pipeline/output/render_methods/<name>.py
  v5 render spec                { tubes:[…], spheres:[…] }    (JSON)
        │
        ▼  renderer/src/mesh.cpp       tube_sweep / add_sphere
  triangle mesh                 (parallel-transport frames, Rodrigues rotation)
        │
        ▼  renderer/src/app.cpp        (Vulkan)
  interactive 3D rune
```

Each stage is purely a function of the previous one — there is no shared state — so the whole pipeline can be replayed deterministically from any input word.

---

## Step 1 — Translation

**Files**: `pipeline/input/auto_translate.py`, `pipeline/input/loader.py`, `translations/languages.txt`

The input word is translated into 124 languages via Google Translate (`deep_translator.GoogleTranslator`). A small `SPECIAL_CASES` table overrides or skips a few languages where the default mapping is wrong (e.g. Kurdish is forced to Sorani `ckb`; Punjabi-Shahmukhi and Malay-Jawi are skipped because their target codes don't exist in Google Translate).

Output is a CSV with two columns: `language, translation`. The CSV is the canonical record of a rune's input — the rest of the pipeline reads from it, so editing the CSV by hand re-shapes the rune in a controlled way.

There is no math here, just I/O. The language list (`translations/languages.txt`, 124 entries) is the universe; everything downstream is sized by it.

---

## Step 2 — Glyph extraction

**File**: `pipeline/glyph/extract.py`

For each `(language, translation)` pair we render the translated word's glyph outline using a font that covers all of its characters. The result is a `GlyphContour`:

```python
@dataclass
class GlyphContour:
    character:  str    # the translated word
    language:   str
    operations: list   # fontTools pen recording
    width:      float  # advance width in font units
    height:     float  # em-square (unitsPerEm)
```

### Font selection

For each translated word we walk the `fonts/` directory and pick the **first font whose `cmap` table contains every character in the word**. We do not fall back per-character — mixing fonts within one word would discontinuously change the glyph shape.

### HarfBuzz shaping

Once a font is found we run real text shaping:

```
face = hb.Face(font_data_bytes)
hb_font = hb.Font(face)
buf = hb.Buffer()
buf.add_str(text)
buf.guess_segment_properties()        # auto-detect script + direction
hb.shape(hb_font, buf)
```

HarfBuzz produces two parallel arrays: `glyph_infos` (codepoints) and `glyph_positions` (per-glyph `x_offset, y_offset, x_advance, y_advance`). For each shaped glyph we record its outline through a fontTools `RecordingPen`, then translate every point operation (`moveTo`, `lineTo`, `curveTo`, `qCurveTo`) by the running cursor `(x_cursor + x_offset, y_cursor + y_offset)`. Non-point operations (`closePath`, `endPath`, `addComponent`) are passed through unchanged. After processing each glyph the cursor advances by `(x_advance, y_advance)`.

The result is a single contour for the whole word, in the font's native unit space. We do not normalise here — the next step needs the raw shape (ratio of width to detail) to compute curvature reliably.

---

## Step 3 — Glyph vector derivation

**File**: `pipeline/glyph/vector.py`

This is where each language collapses from "an outline of N points" into a single `GlyphVector`:

```python
@dataclass
class GlyphVector:
    language:  str
    origin:    np.ndarray     # (3,) in [-1, 1]³
    direction: np.ndarray     # (3,) unit vector on S²
    magnitude: float          # scalar in [0, 1]
```

The three fields are derived independently from each other so they encode different signals:

- **origin** — *where* in space this language lives. Determined entirely by hashing the word + language code, so it has no relation to the glyph shape — its job is to space languages out.
- **direction** — *which way* this language pulls. A combination of the glyph's intrinsic shape (via curvature-weighted PCA) and a hash-determined sphere coordinate, so the same word in two different scripts gets two different directions even if their glyph outlines happen to be similar.
- **magnitude** — *how strongly* it pulls. A rank-normalised mix of arc length and stroke count, with a small hash perturbation so same-script siblings don't tie.

### 3a. Origin: hash → 3D position

The origin uses two independent hash chunks so that direction and radius are statistically independent (otherwise the marginal distribution collapses to a cube, not a ball):

```
digest   = SHA256(text)
digest_r = SHA256(text + "|r")        # salt — independent stream

# Direction (unit vector from first 3 hash chunks):
for i in 0,1,2:
    u_i = int.from_bytes(digest[8i : 8(i+1)], "big") / 2⁶⁴
    x_i = 2·u_i − 1                                   ∈ [−1, 1)
raw       = (x_0, x_1, x_2)
direction = raw / ‖raw‖₂

# Radius (uniform-by-volume inside the unit ball):
u_r    = int.from_bytes(digest_r[0:8], "big") / 2⁶⁴   ∈ [0, 1)
radius = u_r^(1/3)

origin = radius · direction
```

The cube-root on radius is the standard inverse-CDF trick: for a uniform distribution by volume in a `d`-dimensional ball, you sample `u ~ U[0,1)` and set `r = u^(1/d)`. With `d = 3` this gives `r = u^(1/3)`. Without it, points concentrate near the centre because `Vol(r) ∝ r³`.

### 3b. Direction: curvature-weighted PCA frame + hash sphere coordinate

The contour points are first lifted into 3D by giving each 2D point a `z` proportional to its **local curvature**, so that "twisty" parts of the glyph poke out of the page:

```
For a 2D polyline P(t) = (x(t), y(t)):

    κ_i = (x'(t_i)·y''(t_i) − y'(t_i)·x''(t_i))
          ─────────────────────────────────────────
                 (‖P'(t_i)‖²)^(3/2)  +  ε

where derivatives are central differences (np.gradient).

Lift:  z_i = (κ_i / κ_max) · (max(Δx, Δy) / 2)
```

`max(Δx, Δy)` is the bounding-box span of the 2D contour — using it for the z-scale keeps the glyph roughly cube-shaped regardless of font size. The normaliser `κ_max` keeps `|z| ≤ max(Δx,Δy)/2` regardless of how curvy the glyph is.

We then run **curvature-weighted PCA** on the lifted points so the principal axes align with the *interesting* parts of the glyph, not the bulk:

```
weights:    w_i = |κ_i| + CURVATURE_FLOOR        (CURVATURE_FLOOR = 0.10)
            W   = Σ w_i

centroid:   c = (Σ w_i · pts_i) / W
centred:    Y = pts − c

covariance: Σ = (Yᵀ · diag(w) · Y) / W

eigendecomp:
    eigh(Σ) → eigenvalues (ascending), eigenvectors
    e₁ = eigenvectors[:, −1]     (largest eigenvalue — primary axis)
    e₂ = eigenvectors[:, −2]     (second axis)
```

`CURVATURE_FLOOR` keeps straight runs of the glyph from being completely ignored; without it a long straight stroke (e.g. the body of "I") would have zero weight and the frame would be undefined.

PCA returns axes only up to sign, so we resolve signs deterministically from the glyph itself (no random tie-breaks):

```
ref = pts[ argmax( ‖pts_i − c‖ ) ]                   # extreme point
if dot(e₁, ref) < 0:           e₁ = −e₁
if mean(diff(curvature)) < 0:  e₁ = −e₁              # tiebreaker
ref_perp = ref − dot(ref, e₁)·e₁
if dot(e₂, ref_perp) < 0:      e₂ = −e₂
e₃ = (e₁ × e₂) / ‖e₁ × e₂‖                           # right-handed
```

That gives a fully-determined orthonormal frame `(e₁, e₂, e₃)` derived from the glyph shape.

Finally the **direction vector** is a uniformly-distributed point on the unit sphere, expressed in this frame:

```
digest = SHA256(text + "|d")
u = int.from_bytes(digest[0:8],  "big") / 2⁶⁴       ∈ [0, 1)
v = int.from_bytes(digest[8:16], "big") / 2⁶⁴       ∈ [0, 1)

θ = arccos(1 − 2u)                                   ∈ [0, π]
φ = 2π·v                                             ∈ [0, 2π)

α = sin θ · cos φ
β = sin θ · sin φ
γ = cos θ

direction = (α·e₁ + β·e₂ + γ·e₃) / ‖…‖
```

`θ = arccos(1 − 2u)` is the inverse CDF for uniform sampling on a sphere — it gives uniform area density rather than the bunching-at-poles you'd get from sampling `θ` linearly in `[0, π]`.

The combined effect: same glyph shape but different word → same frame but different `(α, β, γ)` → different direction. Different glyph shape but same word → rotated frame, same `(α, β, γ)` → different direction. Both inputs always matter.

### 3c. Magnitude: rank-normalised arc length + stroke count, with hash perturbation

A two-pass computation over all 124 contours.

**Pass 1** — per-contour scalars:

```
arc_len_i  = Σ ‖pts_{j+1} − pts_j‖₂           # total path length
strokes_i  = number of "moveTo" operations    # disconnected components
```

**Pass 2** — rank-normalise both signals to `[0, 1]`, average, and perturb with a hash:

```
arc_rank_i    = rank(arc_len_i)    / (M − 1)            # M = number of unique values
stroke_rank_i = rank(strokes_i)    / (M − 1)

m_base = (arc_rank_i + stroke_rank_i) / 2

h = 4th SHA-256 chunk of (language + text), mapped to [−1, 1]
m_i = clip( m_base · (1 + EPSILON · h),  0,  1 )         (EPSILON = 0.10)
```

Rank normalisation (rather than min-max scaling) is robust to outliers — if one CJK script happens to have an arc length 5× longer than everyone else, rank gives it 1.0 without compressing the rest of the distribution into `[0, 0.2]`.

The perturbation `EPSILON · h` is intentionally small (`±10%`) so that base structure (CJK > Latin > Arabic) is preserved but same-magnitude siblings don't tie exactly.

---

## Step 4 — Vector field construction

**File**: `pipeline/rune_map.py` — `_build_field`, `_build_blended_field`

We have 124 `(origin, direction, magnitude)` samples; we want a continuous function `V : ℝ³ → ℝ³` so we can integrate streamlines through it. There are **two different fields** because the per-language streamlines and the centroid streamline want very different things from `V`.

### 4a. Local, unnormalised field (per-language streamlines)

The kernel bandwidth `σ` controls how far each origin's influence reaches. We deliberately use a **k-nearest-neighbour distance** rather than a global statistic:

```
σ = mean over i of ( distance from origin_i to its k-th nearest neighbour )
                                                                    (k = 4)
```

Why not median pairwise distance? For 125 points spread across `[−1, 1]³`, the median pairwise distance is ≈ 0.7 — almost the diameter of the cube. A Gaussian that wide makes every origin influence every query point near-equally, so the field collapses to a single global mean direction and every streamline marches off in the same direction. The k-NN distance is ≈ 0.10–0.15 for the same cloud — the typical gap to a few near neighbours, so each Gaussian only spans the immediate neighbourhood and the field actually varies across space.

The field itself adds a **vortex** term on top of the directional sum so that streamlines bend around origins instead of just being pushed past them:

```
For a query point x ∈ ℝ³:

    diff_i    = x − origin_i                                  ∈ ℝ³
    dist²_i   = ‖diff_i‖²
    kernel_i  = exp( − dist²_i / (2σ²) )
    weight_i  = magnitude_i · kernel_i

    vortex_i  = direction_i × diff_i                          # cross product
    vortex_i  = vortex_i / ( 1 + ‖diff_i‖ + ε )               # distance stabiliser

    f_i       = direction_i + VORTEX_STRENGTH · vortex_i      (VORTEX_STRENGTH = 0.35)

    V(x) = Σᵢ weight_i · f_i                                  ← UNNORMALISED
```

Two things make this field shape work:

1. **No normalising divisor.** Classical kernel regression would divide by `Σ kernel_i` to get a unit-weighted average. We deliberately omit that. Without normalisation, the field amplitude `‖V(x)‖` carries information — it's high near origins, near-zero in empty regions. The streamline integrator below uses that to detect when it's drifted out of meaningful territory and stops.

2. **Vortex term.** The cross product `direction_i × (x − origin_i)` produces a vector perpendicular to both, which curls around `origin_i` in the plane perpendicular to `direction_i`. Adding a fraction of this to the directional sum gives the field rotational structure — adjacent streamlines spiral past each other instead of running parallel. The `1/(1 + ‖diff‖)` damping keeps the vortex from blowing up far from the origin (where `diff` would otherwise dominate).

### 4b. Global, normalised field (centroid streamline)

The centroid of all origins lands somewhere near the middle of `[−1,1]³` — typically in a region where the local field is near-zero. If we ran the local field there, the trace would stop on its first step. So for the *one* "blended" streamline we use a different field:

```
Bandwidth (global, robust):
    σ = median pairwise distance among (up to) 30 origins

For a query point x:
    kernel_i = exp( − ‖origin_i − x‖² / (2σ²) )
    weight_i = magnitude_i · kernel_i
    total    = Σ weight_i

    if total < 10⁻¹²:  V(x) = 0
    else:              V(x) = ( Σ weight_i · direction_i ) / total      ← NORMALISED
```

Wide kernel + classical normalisation gives a smooth average direction at every point, including dead zones. This is "what's the rune pulling toward, on average?" — a single curve representing the consensus.

---

## Step 5 — Streamline tracing

**File**: `pipeline/rune_map.py` — `_trace_streamline`

For each origin we trace a 3D curve through `V` starting at that origin. The integrator is **bidirectional** (so the origin sits in the middle of its curve, not at the leading edge) and uses an **RK2-style look-ahead** so it captures curvature in the field instead of zig-zagging across it.

### Single-step integration

```
v₀ = FIELD_SCALE · V(pos) · sign           (sign = +1 forward, −1 backward)
                                            (FIELD_SCALE = 2.5)

if ‖v₀‖ < stop_amplitude:                  (stop_amplitude = 10⁻³)
    stop — field has faded out

# Look-ahead: evaluate field at where v₀ would take us:
v₁ = V( pos + dt · v₀ ) · sign

# Blend: 60% current direction, 40% future direction
v  = 0.6 · v₀ + 0.4 · v₁

pos ← pos + dt · v                         (dt = 0.02)
```

This is a weighted Heun's method. Pure Euler (`pos += dt · v₀`) overshoots when the field is curving; pure midpoint RK2 evaluates at `pos + 0.5·dt·v₀`. The 60/40 blend is a deliberately asymmetric compromise — slightly biased toward the current direction for stability, but pulling enough from the look-ahead to follow curl.

### Bidirectional tracing

```
forward  = trace(start, sign = +1, steps = 128)
backward = trace(start, sign = −1, steps = 128)

curve = reversed(backward) + [start] + forward
```

The full curve has up to `2·steps + 1 = 257` points, but typically far fewer because the early-stop kicks in once the streamline drifts into a dead zone. That asymmetry is itself signal — busy regions yield long curves, isolated origins yield short ones.

### Final smoothing pass

A 3-tap weighted average smooths the resulting polyline:

```
For each interior point i:
    out_i = 0.15 · pts_{i−1}  +  0.7 · pts_i  +  0.15 · pts_{i+1}
```

This removes sub-step jitter without altering the curve's overall path.

---

## Step 6 — Language influence (effects)

**File**: `pipeline/rune_map.py` — `_compute_effects`

After the blended (centroid) streamline is traced, we compute each language's *share* of responsibility for that streamline's path. This is a soft attribution — every language influences every blended point, but in different proportions.

For a blended streamline with `M` points `p_1, …, p_M`:

```
σ_eff = EFFECT_SIGMA_SCALE · σ_field            (EFFECT_SIGMA_SCALE = 3.0)

For each language i, point p:
    w_i(p)    = magnitude_i · exp( − ‖p − origin_i‖² / (2σ²_eff) )
    share_i(p) = w_i(p) / Σⱼ w_j(p)              # per-point share, sums to 1

effect_i = (1/M) · Σ_{p ∈ blended} share_i(p)
```

The wider kernel (3× the field's `σ`) is intentional — if effect used the same narrow `σ` as the field, ranking would be dominated by which language happened to be hash-placed *closest* to the streamline rather than which language had the highest magnitude. Widening makes proximity a soft modulator rather than the deciding factor; complex scripts (CJK, Devanagari) tend to dominate the ranking again.

By construction `Σ_i effect_i = 1`, so the effects are a valid probability distribution over languages.

---

## Step 7 — Render methods (geometry generation)

**Files**: `pipeline/output/render_methods/*.py`

A render method takes a `RuneMap` and produces a JSON-serialisable **render spec** describing 3D primitives (tubes and spheres) for the C++ renderer to consume. There are seven methods, each with a different geometric idea.

Helpers in `_util.py`:

```
tube_spec(points, radius=… or radii=…, sides=8)  → {"points": …, "radius"|"radii": …, "sides": …}
sphere_spec(center, radius)                       → {"center": …, "radius": …}
render_spec(method, tubes=[], spheres=[])         → {"version": 5, "method": …, "tubes": …, "spheres": …}

normalize_minmax(arr)        → (arr − min) / (max − min),  zeros if span ≈ 0
tangents_nd(points)          → unit tangents via np.gradient
curvature_magnitude(points)  → ‖d tangent / ds‖ at each point
scaled_radii(signal, lo, hi) → normalize_minmax(signal) · (hi − lo) + lo
```

### 7a. multi_stroke

The simplest method. One tube per language streamline, radius proportional to the language's magnitude:

```
m_norm = normalize_minmax( [v.magnitude for v in vectors] )

for curve_i, m_i in zip(curves, m_norm):
    r_i = MIN_RADIUS + m_i · (MAX_RADIUS − MIN_RADIUS)        (0.006 → 0.030)
    tube = tube_spec(curve_i, radius = r_i, sides = 8)
```

### 7b. calligraphic

Per-point radii driven by **local curvature** so each tube swells at sharp turns and narrows on straight runs (an ink-brush effect). Then the whole tube is uniformly scaled by magnitude:

```
For each curve_i:
    κ        = curvature_magnitude(curve_i)               # per-point scalar
    base     = scaled_radii(κ, BASE_LOW, BASE_HIGH)       # (0.008, 0.040)

    mag_k    = MAG_MIN_K + m_norm[i] · (MAG_MAX_K − MAG_MIN_K)   # 0.5 → 1.5
    radii    = base · mag_k

    tube_spec(curve_i, radii = radii, sides = 10)
```

The magnitude scaling is multiplicative on the whole envelope — complex scripts get thicker brushes from end to end, simple scripts get thinner ones, but both still swell/shrink with their own curvature.

### 7c. layered_backbone

Two layers:

1. Every streamline as a thin tube (the "field" layer).
2. The top-K highest-magnitude streamlines drawn *again* as thick tubes (the "backbone").

```
top_idx = argsort( −m_norm )[: TOP_K ]                     (TOP_K = 8)

# Layer 1 — all streamlines as filaments.
for curve_i in curves:
    tube_spec(curve_i, radius = 0.004, sides = 6)

# Layer 2 — backbones overlaid at language thickness.
for i in top_idx:
    r = BACKBONE_MIN + m_norm[i] · (BACKBONE_MAX − BACKBONE_MIN)   # 0.020 → 0.050
    tube_spec(curves[i], radius = r, sides = 10)
```

This gives a faint web with a few prominent threads — visual hierarchy from a single render.

### 7d. path_follow

Re-traces each origin's streamline from scratch (rather than reading `rune_map.curves`) with optional Gaussian noise added per step, and per-point radii driven by local field magnitude:

```
For each origin_i:
    pos = origin_i
    repeat STEPS times (per direction):
        v   = V(pos)
        v  += NOISE_SCALE · 𝒩(0, I₃)                       (NOISE_SCALE = 0.06)
        pos += DT · (v / ‖v‖)                              (DT = 0.035)
    bidirectional join.

    For each point p in curve:
        |V(p)| → per-point radius via scaled_radii(0.006, 0.024)

    tube_spec(curve, radii = …, sides = 8)

RNG seed:  len(vectors)·131 + int( Σ magnitude · 1000 )
```

The seed is derived from the rune itself, so the noise is reproducible — same rune renders identically every time.

### 7e. junction_dots

Every streamline as a thin tube (same as `multi_stroke` but uniform thin) **plus** spheres marking where any two streamlines come within `EPSILON = 0.06` of each other in 3D:

```
Tubes:
    for curve in curves:
        tube_spec(curve, radius = 0.005, sides = 6)

Pairwise junction detection:
    for each pair (A, B):
        D = ‖A[:, None, :] − B[None, :, :]‖₂              # |A|×|B| distance matrix
        idx  = argmin(D, axis = 1)                         # nearest B-point per A-point
        mins = D[ arange(|A|), idx ]
        mask = mins < EPSILON
        if any(mask):
            hits.append( 0.5 · (A[mask] + B[idx[mask]]) )  # midpoint per hit

Greedy dedup:
    keep dots in order, drop any within MIN_DOT_GAP (0.05) of an already-kept dot
    cap at MAX_DOTS = 300

Spheres:
    for dot in dots:
        sphere_spec(dot, radius = 0.030)
```

Result: tangled field becomes a node-and-edge structure with the junctions called out explicitly.

### 7f. skeleton

Draws *explicit connectivity* between the 124 origins as a graph. Three topology choices, all running through the same Hermite spline edge code:

```
TOPOLOGY = "knn"   →  K-NN graph  (default, K = 4 → ≈ 335 edges)
           "mst"   →  Euclidean minimum spanning tree  (124 − 1 = 123 edges)
           "kmst"  →  MST + KMST_EXTRAS shortest non-MST edges  (123 + 18 = 141 edges)
```

**K-NN**: standard symmetric k-nearest-neighbour graph from the pairwise distance matrix.

**MST** (Kruskal's algorithm with union-find):

```
edges     = sorted [ (‖origin_i − origin_j‖, i, j) for all i < j ]
parent[k] = k    # each origin its own tree
out       = ∅

for (w, i, j) in edges:                         # in ascending weight order
    if find(i) ≠ find(j):                       # different trees → no cycle
        union(i, j)
        out.add((i, j))
        if |out| = N − 1: break
```

**k-MST**: MST plus the `KMST_EXTRAS` shortest non-MST edges (loop closures).

For each chosen edge `(i, j)` we draw a **cubic Hermite spline** from `origin_i` to `origin_j`, with endpoint tangents derived from the field at the endpoints:

```
P(t) = h₀₀(t)·p₀  +  h₁₀(t)·m₀  +  h₀₁(t)·p₁  +  h₁₁(t)·m₁

    h₀₀(t) =  2t³ − 3t² + 1
    h₁₀(t) =     t³ − 2t² + t
    h₀₁(t) = −2t³ + 3t²
    h₁₁(t) =     t³ −   t²

# Endpoint tangents — the field direction at each node, signed once per edge
# to point along the chord, scaled by chord length × tension:
length = ‖p₁ − p₀‖
u₀     = node_tangent(V, p₀, p₁)                  # V(p₀)/‖V(p₀)‖, flipped if dot(·, p₁ − p₀) < 0
u₁     = node_tangent(V, p₁, p₀)
m₀     =  u₀ · TENSION · length                   (TENSION = 0.9)
m₁     = −u₁ · TENSION · length                   # Hermite "outgoing" sign convention
```

The crucial property: **every edge meeting at a node uses the same `V(node)` for its tangent** (only the sign differs). Because all incident edges leave the node along the same tangent line `±V(node)`, junctions read as flowing forks rather than star-shaped meeting points. This is what makes the rune feel like it grew rather than was assembled.

Sampled at `EDGE_SAMPLES = 32` points per edge, each becomes one tube of `TUBE_RADIUS = 0.010`.

### 7g. flow_chain

The graph-and-spline idea pushed further: each curve is a **long Hermite chain** that threads through several origins along the field flow.

```
For each origin_i (the "seed"):

    # 1. Trace a bidirectional streamline through V from origin_i
    #    (TRACE_STEPS = 80, TRACE_DT = 0.03)
    path = trace_bidirectional(V, origin_i)

    # 2. Find every other origin within WAYPOINT_RADIUS of any point on path
    For each origin_j (j ≠ i):
        k_min = argmin( ‖origin_j − path[k]‖ )
        if ‖origin_j − path[k_min]‖ < WAYPOINT_RADIUS:           (= 0.18)
            waypoints.append( (k_min, j) )

    waypoints.sort(by k_min)               # flow order along the streamline
    cap to MAX_WAYPOINTS = 6

    # 3. Build a C¹-continuous Hermite chain through the waypoint origins
    For each interior waypoint k:
        u_k = node_tangent(V, p_k, p_{k+1})       # one tangent per node, signed once

    For each consecutive pair (p_k, p_{k+1}):
        m₀ = TENSION · ‖p_{k+1} − p_k‖ · u_k                  (TENSION = 0.85)
        m₁ = TENSION · ‖p_{k+1} − p_k‖ · sign-adjusted V(p_{k+1})
        emit Hermite segment with SEGMENT_SAMPLES = 16 points

    # 4. Tube
    radius = MIN_RADIUS + m_norm[i] · (MAX_RADIUS − MIN_RADIUS)   (0.006 → 0.022)
    tube_spec(chain, radius = radius, sides = 8)
```

Because every waypoint shared between consecutive segments uses the same tangent vector at the join, the entire chain is C¹-continuous (no kinks). And because the same tangent is used by *all* chains passing through the same origin, the whole bundle of chains visually flows through shared nodes rather than crossing them haphazardly.

---

## Step 8 — Render dispatcher and spec format

**Files**: `pipeline/output/render.py`, `pipeline/output/render_methods/_util.py`

### Render-spec schema (version 5)

```json
{
  "version": 5,
  "method":  "<method name>",
  "tubes": [
    {
      "points":   [[x, y, z], …],   // ≥ 2 points, polyline centreline
      "radius":   0.03,             // uniform, XOR with "radii"
      "radii":    [r₀, r₁, …],      // per-point, XOR with "radius"
      "sides":    8                 // tube cross-section vertex count
    }
  ],
  "spheres": [
    {"center": [x, y, z], "radius": 0.02}
  ]
}
```

### Auto-discovery dispatcher

`render.py` walks the `render_methods/` package on import, treating every file whose name doesn't start with `_` and that exposes a `render(rune_map) -> dict` function as a registered method. There is no central list to keep in sync — adding a new method is just adding a file:

```python
_REGISTRY = {}
for info in pkgutil.iter_modules(render_methods.__path__):
    if info.name.startswith("_"):
        continue
    mod = importlib.import_module(f"...render_methods.{info.name}")
    if callable(getattr(mod, "render", None)):
        _REGISTRY[info.name] = mod.render

def render_rune(rune_map, method=None):
    key = method or CURRENT_METHOD             # default = "multi_stroke"
    return _REGISTRY[key](rune_map)

def save_render(rune_map, path, method=None):
    json.dump(render_rune(rune_map, method), open(path, "w"), indent=2)
```

---

## Step 9 — Vulkan tube renderer (C++)

**Files**: `renderer/src/mesh.{h,cpp}`, `renderer/src/app.cpp`, `renderer/shaders/*`

The C++ renderer reads the v5 spec JSON and converts it into a triangle mesh, which it then displays interactively via Vulkan.

### Loading

`RuneMesh::load_from_json` dispatches on the JSON's `version` field. For v5 it iterates `tubes` and `spheres` and calls `tube_sweep` / `add_sphere` on each. The legacy v2–v4 paths (raw `streamlines` and `blended` polylines) are kept so older saved RuneMaps still display in "View Map" without re-rendering.

### Tube sweep — parallel-transport frames

Sweeping a circular cross-section along a 3D polyline naively (e.g. always using world-up as the "up" direction for the cross-section) produces sudden frame flips at bends. The standard fix is **parallel transport of the normal** between consecutive frames using Rodrigues' rotation formula.

For a centreline `cl[0..N−1]` with per-point tangents `T[i]` and per-point radii `radii[i]`:

```
# 1. Tangents
for i in 0..N−2:  T[i] = (cl[i+1] − cl[i]) / ‖…‖
T[N−1] = T[N−2]

# 2. Seed the normal so it's perpendicular to T[0]
seed = (0, 1, 0)
if |dot(seed, T[0])| > 0.9:  seed = (1, 0, 0)
N = (seed − dot(seed, T[0]) · T[0]) / ‖…‖

# 3. Walk the polyline, re-orthogonalising N at each step and rotating it forward
for i in 0..N−1:
    B = T[i] × N            # binormal
    N = B × T[i]            # re-orthogonalised normal

    # Emit a ring of `sides` vertices at cl[i], radius radii[i]
    for j in 0..sides−1:
        angle   = 2π · j / sides
        outward = cos(angle) · N + sin(angle) · B
        vertex  = cl[i] + radii[i] · outward
        normal  = outward                 # for a tube, surface normal = outward radial

    # Parallel-transport N forward to the next frame (Rodrigues rotation)
    if i < N−1:
        axis  = T[i] × T[i+1]
        sin_a = ‖axis‖
        if sin_a > 1e-8:
            axis  = axis / sin_a
            cos_a = dot(T[i], T[i+1])

            #  Rodrigues:  v_rot = cos(θ)·v + sin(θ)·(k × v) + (1 − cos(θ))·(k · v)·k
            N = cos_a · N
              + sin_a · (axis × N)
              + (1 − cos_a) · dot(axis, N) · axis

    # Triangulate this ring against the previous one (2 triangles per quad face)
```

End caps are flat discs: a centre vertex at the polyline endpoint with normal `±T`, fanned out to that ring's vertices.

### UV sphere

Used by `junction_dots` (and any future method that emits spheres). Standard latitude/longitude tessellation:

```
# `lat` rings, `lon` vertices per ring
for i in 0..lat−1:
    φ  = π · (i + 1) / (lat + 1)        # in (0, π), excluding poles
    cy = cos(φ),  sy = sin(φ)
    for j in 0..lon−1:
        θ = 2π · j / lon
        n = (sy · cos(θ),  cy,  sy · sin(θ))    # unit normal
        vertex = centre + radius · n

# Two pole vertices at (centre ± radius·ĵ) with normals ±ĵ
# Quad-fill between adjacent rings, fan-triangulate poles to outermost rings
```

Default `lat = 8`, `lon = 12` is the sweet spot — round enough for typical viewing distance, cheap to draw 100+ of in the same scene.

### Vulkan app structure (briefly)

`renderer/src/app.cpp` initialises a Vulkan device, swapchain, vertex/index buffers from the `RuneMesh`, and a basic shader pair. The fragment shader uses a single white material on a dark blue-grey clear colour `(0.067, 0.078, 0.094, 1.0)` to match the 2D preview palette. Camera is an orbit controller (mouse-drag rotates, scroll zooms). The render loop just rebinds the buffers and draws indexed triangles.

---

## UI flow

**File**: `ui.py`

A Tkinter GUI orchestrates the pipeline in three stages:

```
1. Translate
   ─ enter a word, click Auto-Translate → CSV at translations/<word>.csv
   ─ or fill the language dropdown by hand (124 entries)

2. Generate
   ─ Generate button:  CSV → extract_glyphs → compute_all_vectors
                            → build_rune_map → output/<word>.json   (v4)
   ─ View Map button:  launches an interactive 3D viewer of the raw streamlines,
                       with checkboxes to toggle individual languages on/off
                       (uses rebuild_from_vectors internally)

3. Render
   ─ Render button + method dropdown:
        load_map(<word>.json)
          → render_rune(rune_map, method=…)              (v5 spec dict)
          → save_render(…, output/<word>__<method>.json)
          → launch the Vulkan renderer binary on that JSON
```

The Render path goes straight from RuneMap to v5 spec to Vulkan — there is no intermediate SVG step. Generate writes the v4 RuneMap once; Render re-reads it and re-runs the chosen method on every click, so changing render parameters and re-clicking Render is instant (no re-Generate needed). Methods that only consume `rune_map.vectors` (rebuilding the field each call) reflect upstream field changes immediately; methods that consume `rune_map.curves` directly require a re-Generate.

---

## File layout

```
Runesmaker/
├── README.md                              ← this file
├── ui.py                                  ← Tkinter UI entry point
├── pyproject.toml
├── requirements.txt
│
├── pipeline/
│   ├── input/
│   │   ├── auto_translate.py              ← Google-Translate wrapper, SPECIAL_CASES
│   │   └── loader.py                      ← CSV reader
│   ├── glyph/
│   │   ├── extract.py                     ← HarfBuzz shaping → GlyphContour
│   │   └── vector.py                      ← Hash + curvature-PCA → GlyphVector
│   ├── rune_map.py                        ← Field, streamlines, effects, RuneMap
│   └── output/
│       ├── export.py                      ← v4 RuneMap I/O for "View Map"
│       ├── render.py                      ← Render dispatcher + auto-discovery
│       └── render_methods/
│           ├── _util.py                   ← tube_spec, sphere_spec, render_spec, …
│           ├── multi_stroke.py
│           ├── calligraphic.py
│           ├── layered_backbone.py
│           ├── path_follow.py
│           ├── junction_dots.py
│           ├── skeleton.py
│           └── flow_chain.py
│
├── renderer/
│   ├── src/
│   │   ├── mesh.{h,cpp}                   ← v5 spec → triangle mesh (tube_sweep, add_sphere)
│   │   ├── app.cpp, vulkan_context.cpp    ← Vulkan setup + render loop
│   │   └── …
│   └── shaders/
│       ├── rune.vert
│       └── rune.frag                      ← white material, basic Phong
│
├── translations/
│   ├── languages.txt                      ← 124 language names
│   └── <word>.csv                         ← per-word translation table
│
├── output/
│   └── <Word> Rune/
│       ├── <Word>.json                    ← v4 RuneMap (curves, blended, vectors)
│       └── <Word>__<method>.json          ← v5 render spec
│
└── fonts/                                 ← .ttf / .otf files searched for cmap coverage
```

---

## Parameter reference

Every constant that meaningfully shapes the rune, with where it lives.

### Glyph vector (`pipeline/glyph/vector.py`)

| Constant | Value | Effect |
|---|---|---|
| `CURVATURE_FLOOR` | `0.10` | Lower bound on per-point PCA weight; keeps straight strokes from being ignored. |
| `EPSILON` (magnitude) | `0.10` | Hash-perturbation amplitude on rank-normalised magnitude. Small so script-level structure dominates. |

### Vector field (`pipeline/rune_map.py`)

| Constant | Value | Effect |
|---|---|---|
| `k` (in `_estimate_bandwidth`) | `4` | k-NN bandwidth — defines "local". Lower = sharper but choppier; higher = smoother but mushier. |
| `VORTEX_STRENGTH` | `0.35` | How much rotational curl is added to the directional sum. `0` = pure flow, `1+` = swirly. |
| `EFFECT_SIGMA_SCALE` | `3.0` | Effect kernel σ relative to field σ. Higher = magnitude wins; lower = proximity wins. |

### Streamlines (`pipeline/rune_map.py`, `_trace_streamline`)

| Constant | Value | Effect |
|---|---|---|
| `FIELD_SCALE` | `2.5` | Multiplier on `V` before integration. |
| `dt` | `0.02` | Step size. |
| `stop_amplitude` | `1e-3` | Field-fade threshold for early stop. |
| `steps` | `128` | Per-direction step budget (full curve ≤ 257 points). |
| smoothing weights | `(0.15, 0.7, 0.15)` | Final 3-tap blur. |

### Render methods (per `pipeline/output/render_methods/<file>.py`)

| Method | Key knobs |
|---|---|
| `multi_stroke` | `MIN_RADIUS=0.006`, `MAX_RADIUS=0.030`, `SIDES=8` |
| `calligraphic` | `BASE_LOW=0.008`, `BASE_HIGH=0.040`, `MAG_MIN_K=0.5`, `MAG_MAX_K=1.5`, `SIDES=10` |
| `layered_backbone` | `FIELD_RADIUS=0.004`, `BACKBONE_MIN=0.020`, `BACKBONE_MAX=0.050`, `TOP_K=8` |
| `path_follow` | `STEPS=160`, `DT=0.035`, `NOISE_SCALE=0.06`, `MIN_RADIUS=0.006`, `MAX_RADIUS=0.024` |
| `junction_dots` | `EPSILON=0.06`, `MIN_DOT_GAP=0.05`, `MAX_DOTS=300`, `DOT_RADIUS=0.030` |
| `skeleton` | `TOPOLOGY="knn"`, `K_NEIGHBOURS=4`, `KMST_EXTRAS=18`, `EDGE_SAMPLES=32`, `TENSION=0.9`, `TUBE_RADIUS=0.010` |
| `flow_chain` | `TRACE_STEPS=80`, `TRACE_DT=0.03`, `WAYPOINT_RADIUS=0.18`, `MAX_WAYPOINTS=6`, `SEGMENT_SAMPLES=16`, `TENSION=0.85`, `MIN_RADIUS=0.006`, `MAX_RADIUS=0.022` |

### C++ renderer (`renderer/src/mesh.cpp`)

| Constant | Value | Where |
|---|---|---|
| Default tube `sides` | `8` | `tube_spec` fallback |
| UV sphere `lat`, `lon` | `8`, `12` | `add_sphere` defaults |
| Clear colour | `(0.067, 0.078, 0.094, 1.0)` | `app.cpp` — matches 2D preview |
| Material colour | `(1.0, 1.0, 1.0)` | `rune.frag` |

---

## Determinism guarantee

Every random draw in the pipeline is seeded from one of:

- the input word's bytes (origin direction, origin radius, magnitude perturbation),
- the language code's bytes (some perturbations),
- the rune itself (`path_follow`'s noise RNG seed = `len(vectors)·131 + Σ magnitude · 1000`).

There are no calls to `random.random()` or `np.random.default_rng()` without a derived seed. The same word always produces the same rune, on any machine, at any time.
