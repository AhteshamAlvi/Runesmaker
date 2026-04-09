"""CLI entry point: translations CSV in → rune contour out."""

import argparse
import os

from pipeline.loader import load_translations
from pipeline.glyph_extract import extract_glyphs
from pipeline.vectorize import vectorize_contours
from pipeline.blend import blend_rune
from pipeline.export import save_svg, save_json

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")


def main():
    parser = argparse.ArgumentParser(description="Generate a rune from a translations CSV")
    parser.add_argument("csv", help="Path to translations CSV (columns: language, translation)")
    parser.add_argument("--name", "-n", default=None,
                        help="Output file name (default: CSV filename without extension)")
    parser.add_argument("--blend", choices=["mean", "median"], default="mean",
                        help="Blending method (default: mean)")
    parser.add_argument("--samples", type=int, default=64,
                        help="Sample density per glyph contour (default: 64)")
    parser.add_argument("--output", "-o", default=None,
                        help="Output base directory (default: output/)")
    parser.add_argument("--format", choices=["svg", "json", "both"], default="both",
                        help="Output format (default: both)")
    args = parser.parse_args()

    out_base = args.output or OUTPUT_DIR
    name = args.name or os.path.splitext(os.path.basename(args.csv))[0]

    # Output goes into output/<name> Rune/
    rune_dir = os.path.join(out_base, f"{name} Rune")
    os.makedirs(rune_dir, exist_ok=True)

    print(f"Loading translations from {args.csv}...")
    translations = load_translations(args.csv)
    print(f"  Loaded {len(translations)} translations")

    print("Extracting glyph outlines...")
    contours = extract_glyphs(translations)
    print(f"  Extracted {len(contours)} glyphs")

    if not contours:
        print("Error: No glyphs could be extracted. Add fonts to the fonts/ directory.")
        return

    print(f"Vectorizing and blending ({args.blend})...")
    vectors = vectorize_contours(contours, args.samples)
    rune = blend_rune(vectors, method=args.blend)

    if args.format in ("svg", "both"):
        svg_path = os.path.join(rune_dir, f"{name}.svg")
        save_svg(rune, svg_path)
        print(f"  Saved {svg_path}")
    if args.format in ("json", "both"):
        json_path = os.path.join(rune_dir, f"{name}.json")
        save_json(rune, json_path)
        print(f"  Saved {json_path}")

    print("Done.")


if __name__ == "__main__":
    main()
