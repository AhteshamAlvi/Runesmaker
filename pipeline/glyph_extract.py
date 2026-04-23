"""Extract glyph outlines (contours) from font files for translated characters."""

import os
from dataclasses import dataclass, field
from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import RecordingPen
import uharfbuzz as hb 

FONTS_DIR = os.path.join(os.path.dirname(__file__), "..", "fonts")


@dataclass
class GlyphContour:
    """A single glyph's outline as a list of drawing operations."""
    character: str
    language: str
    operations: list = field(default_factory=list)
    width: float = 0.0
    height: float = 0.0


def find_font_for_char(char: str, font_paths: list[str]) -> TTFont | None:
    """Find the first font in font_paths that contains the given character."""
    codepoint = ord(char)
    for path in font_paths:
        try:
            font = TTFont(path)
            cmap = font.getBestCmap()
            if cmap and codepoint in cmap:
                return font
        except Exception:
            continue
    return None


def list_fonts() -> list[str]:
    """List all .ttf and .otf files in the fonts directory (recursive)."""
    if not os.path.isdir(FONTS_DIR):
        return []
    results = []
    for root, _, files in os.walk(FONTS_DIR):
        for f in sorted(files):
            if f.lower().endswith((".ttf", ".otf")):
                results.append(os.path.join(root, f))
    return results


def extract_glyph(char: str, language: str, font_paths: list[str] | None = None) -> GlyphContour | None:
    """Extract the outline contour for a single character.

    Args:
        char: The character to extract.
        language: Language name (for labeling).
        font_paths: List of font file paths to search. Defaults to fonts/ dir.

    Returns:
        GlyphContour with drawing operations, or None if not found.
    """
    if font_paths is None:
        font_paths = list_fonts()

    font = find_font_for_char(char, font_paths)
    if font is None:
        return None

    cmap = font.getBestCmap()
    glyph_name = cmap[ord(char)]
    glyf = font.getGlyphSet()

    pen = RecordingPen()
    glyf[glyph_name].draw(pen)

    head = font["head"]
    contour = GlyphContour(
        character=char,
        language=language,
        operations=pen.value,
        width=font["hmtx"][glyph_name][0],
        height=head.unitsPerEm,
    )
    font.close()
    return contour

def extract_word_glyph(text: str, language: str, font_paths: list[str]) -> GlyphContour | None:
    """Extract a shaped contour for an entire word using HarfBuzz.

    Unlike extract_glyph (first character only), this shapes the full text so
    ligatures, kerning, and bidirectional scripts (Arabic, Hebrew, Urdu) are
    rendered correctly as a single combined contour.

    Args:
        text: Full translation string to shape.
        language: Language name (for labeling).
        font_paths: Ordered list of font files to search.

    Returns:
        GlyphContour with all shaped glyphs merged, or None if no font covers
        every character in the text.
    """
    font = None
    font_path = None

    for path in font_paths:
        try:
            f = TTFont(path)
            cmap = f.getBestCmap()

            if cmap and all(ord(c) in cmap for c in text if c.strip()):
                font = f
                font_path = path
                break

            f.close()
        except Exception:
            continue

    if font is None:
        return None

    glyph_set = font.getGlyphSet()

    with open(font_path, "rb") as f:
        font_data = f.read()

    face = hb.Face(font_data)
    hb_font = hb.Font(face)

    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()

    hb.shape(hb_font, buf)

    infos = buf.glyph_infos
    positions = buf.glyph_positions

    pen = RecordingPen()

    x_cursor = 0
    y_cursor = 0

    for info, pos in zip(infos, positions):
        glyph_name = font.getGlyphName(info.codepoint)

        glyph_pen = RecordingPen()
        glyph_set[glyph_name].draw(glyph_pen)

        dx = x_cursor + pos.x_offset
        dy = y_cursor + pos.y_offset

        # Only translate ops that carry (x, y) point arguments
        _POINT_OPS = {"moveTo", "lineTo", "curveTo", "qCurveTo"}
        for op, args in glyph_pen.value:
            if op in _POINT_OPS:
                shifted = tuple((x + dx, y + dy) for (x, y) in args)
            else:
                shifted = args  # closePath / endPath / addComponent — pass through
            pen.value.append((op, shifted))

        x_cursor += pos.x_advance
        y_cursor += pos.y_advance

    contour = GlyphContour(
        character=text,
        language=language,
        operations=pen.value,
        width=x_cursor,
        height=font["head"].unitsPerEm,
    )

    font.close()
    return contour

def extract_glyphs(translations: list[dict], font_paths: list[str] | None = None) -> list[GlyphContour]:
    """Extract glyph contours for all translations.

    Args:
        translations: List of dicts from translate.translate_word().
        font_paths: Font paths to search.

    Returns:
        List of GlyphContour objects (skips characters without font coverage).
    """
    if font_paths is None:
        font_paths = list_fonts()

    contours = []
    for t in translations:
        text = t["translation"]
        if not text or not text.strip():
            continue

        # Use HarfBuzz to shape the full word — handles ligatures, kerning,
        # and bidirectional scripts correctly
        contour = extract_word_glyph(text.strip(), t["language"], font_paths)
        if contour is not None:
            contours.append(contour)

    return contours
