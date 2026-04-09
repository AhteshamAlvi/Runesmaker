# Runesmaker

Generate unique 3D runes by blending the glyph shapes of a word translated across 242 languages.

## How It Works

A word like "fire" looks different in every writing system — Arabic, Chinese, Cyrillic, Devanagari, etc. Runesmaker extracts the visual outlines of these characters, mathematically blends them together, and produces a novel composite symbol — a "rune" — that is then extruded into 3D geometry and rendered with Vulkan.

```
"fire" → 242 translations → glyph outlines → normalize → blend → 2D rune → extrude → 3D render
```

## Pipeline

### Stage 1: Translation Input

Translations are provided via CSV files in `translations/`. Each CSV has two columns:

```csv
language,translation
arabic,نار
chinese (simplified),火
hindi,आग
japanese,火
russian,огонь
```

The `translations/languages.txt` file lists all 242 supported languages. The UI walks through each one and lets you type or paste the translation.

### Stage 2: Glyph Extraction

**File:** `pipeline/glyph_extract.py`

For each translation, the pipeline takes the **first character** and extracts its outline from a font file using [fontTools](https://github.com/fonttools/fonttools).

1. Scans `fonts/` for `.ttf` and `.otf` files (e.g., [Noto Sans](https://fonts.google.com/noto) for broad Unicode coverage)
2. For each character, finds the first font whose `cmap` table contains that codepoint
3. Uses a `RecordingPen` to capture the glyph's drawing operations — `moveTo`, `lineTo`, `qCurveTo`, `curveTo`, `closePath`
4. Records glyph width (from `hmtx` table) and height (from `unitsPerEm`)

The result is a `GlyphContour` object per translation — a sequence of drawing commands that describe the character's shape.

### Stage 3: Vectorization

**File:** `pipeline/vectorize.py`

Raw glyph outlines have varying numbers of points and different coordinate scales. Vectorization normalizes them into a common representation so they can be blended.

**Point Extraction:** Walks the drawing operations and collects all coordinate points from move, line, and curve commands.

**Arc-Length Resampling:** Resamples each contour to exactly N evenly-spaced points (default: 64):
1. Computes the Euclidean distance of each segment between consecutive points
2. Builds a cumulative arc-length array along the contour
3. Generates N target distances, evenly spaced from 0 to total length
4. For each target, binary-searches (`searchsorted`) for the segment it falls on
5. Linearly interpolates within that segment to find the exact point

This ensures every glyph is represented by the same number of points with consistent spacing, regardless of the original outline complexity.

**Normalization:** Centers the points around `(0, 0)` and scales them to fit within `[-1, 1] x [-1, 1]`, dividing by half the maximum extent. This removes differences in glyph size and position.

**Output:** An array of shape `(n_contours, 64, 2)` — one normalized 64-point contour per translation.

### Stage 4: Blending

**File:** `pipeline/blend.py`

Multiple glyph contours are combined into a single composite rune shape. Two methods are available:

**Mean Blend (default):** Computes the weighted average of all contour points at each position. With uniform weights, this is a simple arithmetic mean. Supports custom weighting via `numpy.einsum` — you could weight by language family similarity, for example.

**Median Blend:** Takes the median value at each point position across all contours. More robust to outlier glyphs — if one script has a radically different shape, it won't skew the result as much as it would with mean blending.

**Output:** A single contour of shape `(64, 2)` — the composite rune.

### Stage 5: Export

**File:** `pipeline/export.py`

The blended rune contour is exported in two formats:

**SVG** — For visual preview. Transforms `[-1, 1]` coordinates to pixel space with 10% margin. Generates an SVG `<path>` element with white stroke on transparent background (512x512 px default).

**JSON** — For the C++ renderer. Simple format:
```json
{
  "version": 1,
  "points": [[x1, y1], [x2, y2], ...]
}
```
Points remain in normalized `[-1, 1]` space. The renderer handles the 3D transform.

Both files are saved to `output/<Name> Rune/`.

### Stage 6: 3D Extrusion

**File:** `renderer/src/mesh.cpp`

The C++ renderer reads the JSON contour and extrudes it into 3D geometry:

1. Loads the 2D point array from JSON (via nlohmann/json)
2. For each edge in the contour (pairs of consecutive points):
   - Computes the edge direction vector `(dx, dy)`
   - Calculates the outward-facing normal via 90-degree rotation: `(nx, ny) = (-dy/len, dx/len)`
   - Creates 4 vertices: two at `z = -depth/2`, two at `z = +depth/2` (default depth: 0.3 units)
   - Generates 2 triangles forming a quad for the side wall
3. Stores vertex positions and normals in buffers for GPU upload

### Stage 7: Vulkan Rendering

**Files:** `renderer/src/vulkan_context.cpp`, `renderer/src/pipeline.cpp`, `renderer/src/camera.cpp`

The extruded mesh is rendered using a Vulkan graphics pipeline:

**Camera:** Orbital camera system using spherical coordinates. Mouse drag rotates (yaw/pitch), scroll zooms (adjusts distance from origin). View matrix computed via `glm::lookAt`, perspective projection at 45-degree FOV.

**Vertex Shader** (`shaders/rune.vert`): Transforms vertices to clip space using a Model-View-Projection matrix passed as a push constant. Forwards world-space normals and positions to the fragment shader.

**Fragment Shader** (`shaders/rune.frag`): Phong lighting model with:
- Ambient: 0.15 (constant base illumination)
- Diffuse: `max(dot(normal, lightDir), 0.0) * 0.85`
- Light direction: diagonal `(1, 1, 1)` (normalized)
- Rune color: pale blue `(0.7, 0.85, 1.0)`

**Export:** The renderer can capture the framebuffer to PNG via `--export` flag (uses stb_image_write).

## Usage

### GUI

```bash
.venv/bin/python ui.py
```

1. Enter a rune name (e.g., "fire")
2. Walk through the 242 languages, typing/pasting translations
3. Use the dropdown to jump to specific languages (unfilled sort to top)
4. Click **Save CSV** to save your translations
5. Select blend method (mean or median)
6. Click **Generate** — a preview window pops up showing the 2D rune
7. Click **Render** — launches the Vulkan 3D renderer

Press Enter on the rune name field to load an existing rune's translations and state.

### CLI

```bash
# Generate rune from CSV
python -m pipeline.cli translations/fire.csv --name fire --blend median

# Full pipeline via bash script
./runesmaker.sh fire.csv
./runesmaker.sh fire.csv --blend median --no-render
./runesmaker.sh fire.csv --export output/fire.png
```

## Project Structure

```
Runesmaker/
├── ui.py                      # Tkinter GUI application
├── runesmaker.sh              # Bash script for end-to-end pipeline
│
├── pipeline/                  # Python processing pipeline
│   ├── loader.py              #   Load translations from CSV
│   ├── glyph_extract.py       #   Extract character outlines from fonts
│   ├── vectorize.py           #   Normalize and resample contours
│   ├── blend.py               #   Blend contours into composite rune
│   ├── export.py              #   Export as SVG and JSON
│   └── cli.py                 #   CLI entry point
│
├── renderer/                  # C++ Vulkan renderer
│   ├── CMakeLists.txt         #   Build configuration (C++20)
│   ├── src/
│   │   ├── main.cpp           #   Entry point
│   │   ├── app.cpp            #   Application lifecycle
│   │   ├── vulkan_context.cpp #   Vulkan device and swapchain
│   │   ├── pipeline.cpp       #   Graphics pipeline setup
│   │   ├── mesh.cpp           #   JSON → extruded 3D mesh
│   │   ├── camera.cpp         #   Orbital camera
│   │   └── exporter.cpp       #   PNG screenshot export
│   ├── shaders/
│   │   ├── rune.vert          #   Vertex shader (MVP transform)
│   │   └── rune.frag          #   Fragment shader (Phong lighting)
│   └── third_party/           #   GLFW, GLM, nlohmann/json
│
├── translations/              # Input data
│   ├── languages.txt          #   242 supported languages
│   └── *.csv                  #   User translation files
│
├── fonts/                     # TTF/OTF fonts (e.g., Noto Sans)
├── output/                    # Generated runes
│   └── <Name> Rune/           #   Per-rune subfolder
│       ├── <name>.svg         #     2D vector preview
│       └── <name>.json        #     Contour data for renderer
│
├── notebooks/                 # Experimentation notebooks
│   └── langauge_rune.ipynb
├── pyproject.toml             # Python project config
└── requirements.txt           # Python dependencies
```

## Setup

### Python

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Dependencies:** fonttools, numpy, Pillow, cairosvg

**Fonts:** Download [Noto Sans](https://fonts.google.com/noto) (covers most Unicode blocks) and place `.ttf` files in `fonts/`.

### C++ Renderer

```bash
# Install Vulkan SDK
brew install vulkansdk  # or download from https://vulkan.lunarg.com

# Clone third-party libraries
cd renderer/third_party
git clone https://github.com/glfw/glfw.git
git clone https://github.com/g-truc/glm.git
git clone https://github.com/nlohmann/json.git

# Build
cd ..
mkdir build && cd build
cmake ..
make
```

**Dependencies:** Vulkan SDK, GLFW (windowing), GLM (math), nlohmann/json (JSON parsing), CMake 3.20+

### tkinter (macOS)

If `import tkinter` fails:

```bash
brew install tcl-tk python-tk@3.13
```

Then recreate your venv.
