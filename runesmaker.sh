#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
RENDERER="$SCRIPT_DIR/renderer/build/rune_renderer"
OUTPUT_DIR="$SCRIPT_DIR/output"
TRANSLATIONS_DIR="$SCRIPT_DIR/translations"

# --- Usage ---
usage() {
    echo "Usage: ./runesmaker.sh <file.csv> [options]"
    echo ""
    echo "  Generates a 3D rune from a translations CSV."
    echo "  Place your CSV files in translations/"
    echo ""
    echo "Options:"
    echo "  --blend mean|median    Blending method (default: mean)"
    echo "  --samples N            Sample density per glyph (default: 64)"
    echo "  --export output.png    Also export a PNG screenshot"
    echo "  --no-render            Skip the 3D renderer, only generate SVG/JSON"
    echo ""
    echo "Examples:"
    echo "  ./runesmaker.sh hello.csv"
    echo "  ./runesmaker.sh hello.csv --blend median"
    echo "  ./runesmaker.sh hello.csv --export output/hello.png"
    exit 1
}

if [ $# -lt 1 ]; then
    usage
fi

# --- Parse args ---
CSV_INPUT="$1"
shift

BLEND="mean"
SAMPLES=64
EXPORT_PATH=""
NO_RENDER=false

while [ $# -gt 0 ]; do
    case "$1" in
        --blend)    BLEND="$2"; shift 2 ;;
        --samples)  SAMPLES="$2"; shift 2 ;;
        --export)   EXPORT_PATH="$2"; shift 2 ;;
        --no-render) NO_RENDER=true; shift ;;
        *)          echo "Unknown option: $1"; usage ;;
    esac
done

# --- Resolve CSV path ---
if [ -f "$CSV_INPUT" ]; then
    CSV_PATH="$CSV_INPUT"
elif [ -f "$TRANSLATIONS_DIR/$CSV_INPUT" ]; then
    CSV_PATH="$TRANSLATIONS_DIR/$CSV_INPUT"
else
    echo "Error: Cannot find '$CSV_INPUT'"
    echo "  Looked in: ./ and translations/"
    exit 1
fi

RUNE_NAME="$(basename "$CSV_PATH" .csv)"
RUNE_DIR="$OUTPUT_DIR/${RUNE_NAME} Rune"

echo "=== Runesmaker ==="
echo ""

# --- Step 1: Python pipeline (CSV → SVG + JSON in subfolder) ---
echo "[1/2] Generating rune contour from translations..."
"$VENV/bin/python" -m pipeline.cli "$CSV_PATH" \
    --name "$RUNE_NAME" \
    --blend "$BLEND" \
    --samples "$SAMPLES" \
    --output "$OUTPUT_DIR"

JSON_PATH="$RUNE_DIR/$RUNE_NAME.json"
SVG_PATH="$RUNE_DIR/$RUNE_NAME.svg"

echo ""

# --- Step 2: C++ Vulkan renderer (JSON → 3D window / PNG) ---
if [ "$NO_RENDER" = true ]; then
    echo "[2/2] Skipped (--no-render)"
elif [ ! -f "$RENDERER" ]; then
    echo "[2/2] Renderer not built yet. Skipping 3D render."
    echo "  To build: cd renderer && mkdir -p build && cd build && cmake .. && make"
    echo "  Then re-run this script."
else
    echo "[2/2] Launching 3D renderer..."
    RENDER_CMD="$RENDERER $JSON_PATH"
    if [ -n "$EXPORT_PATH" ]; then
        RENDER_CMD="$RENDER_CMD --export $EXPORT_PATH"
    fi
    $RENDER_CMD
fi

echo ""
echo "=== Output ==="
echo "  Folder: $RUNE_DIR"
[ -f "$SVG_PATH" ]  && echo "  SVG:    $SVG_PATH"
[ -f "$JSON_PATH" ] && echo "  JSON:   $JSON_PATH"
[ -n "$EXPORT_PATH" ] && [ -f "$EXPORT_PATH" ] && echo "  PNG:    $EXPORT_PATH"
echo "Done."
