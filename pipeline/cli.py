"""CLI entry point: translations CSV in → rune contour out."""

import argparse
import os

from pipeline.input.loader import load_translations
from pipeline.glyph.extract import extract_glyphs
from pipeline.rune_map import build_rune_map
from pipeline.output.project import project
from pipeline.output.export import save_svg, save_json

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")


def main():
    parser = argparse.ArgumentParser(description="Generate a rune from a translations CSV")
    parser.add_argument("csv", help="Path to translations CSV (columns: language, translation)")
    parser.add_argument("--name", "-n", default=None,
                        help="Output file name (default: CSV filename without extension)")
    parser.add_argument("--samples", type=int, default=128,
                        help="Sample density per glyph curve (default: 128)")
    parser.add_argument("--output", "-o", default=None,
                        help="Output base directory (default: output/)")
    parser.add_argument("--format", choices=["svg", "json", "both"], default="both",
                        help="Output format (default: both)")
    args = parser.parse_args()

    out_base = args.output or OUTPUT_DIR
    name = args.name or os.path.splitext(os.path.basename(args.csv))[0]

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

    print("Building 3D rune map...")
    rune_map = build_rune_map(contours, sample_density=args.samples)
    proj_2d  = project(rune_map)
    print(f"  {len(rune_map.curves)} language streamlines")

    if args.format in ("svg", "both"):
        svg_path = os.path.join(rune_dir, f"{name}.svg")
        save_svg(proj_2d, svg_path)
        print(f"  Saved {svg_path}")
    if args.format in ("json", "both"):
        json_path = os.path.join(rune_dir, f"{name}.json")
        save_json(rune_map, proj_2d, json_path)
        print(f"  Saved {json_path}")

    print("Done.")


if __name__ == "__main__":
    main()
