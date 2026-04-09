"""Extract glyph outlines (contours) from font files for translated characters."""

import os
from dataclasses import dataclass, field
from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import RecordingPen

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
    """List all .ttf and .otf files in the fonts directory."""
    if not os.path.isdir(FONTS_DIR):
        return []
    return [
        os.path.join(FONTS_DIR, f)
        for f in sorted(os.listdir(FONTS_DIR))
        if f.lower().endswith((".ttf", ".otf"))
    ]


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
        # Use the first character of the translation as the representative glyph
        char = text[0] if text else None
        if char is None:
            continue

        contour = extract_glyph(char, t["language"], font_paths)
        if contour is not None:
            contours.append(contour)

    return contours
