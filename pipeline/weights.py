"""Script-group weights for rune blending.

Design
------
Each script group contributes equally to the final rune by default.
With 15 groups and all multipliers at 1.0, every group gets exactly 1/15
(≈ 6.7%) of the total influence, regardless of how many languages are in it.

To skew the result, raise or lower a group's multiplier:
  - 2.0  →  that group has twice the influence of a baseline group
  - 0.5  →  half the influence
  - 0.0  →  excluded entirely

The ±10% random jitter means repeated renders of the same word produce
subtly different runes.

Groups
------
  latin, cyrillic, arabic, devanagari, dravidian,
  cjk, se_asian, geez, hebrew,
  georgian, sinhala, thaana, meitei, armenian, greek
"""

from random import random
import numpy as np

from pipeline.glyph_extract import GlyphContour


# ---------------------------------------------------------------------------
# Tweak these multipliers to skew influence. 1.0 = equal share.
# ---------------------------------------------------------------------------
GROUP_MULTIPLIERS: dict[str, float] = {
    # Script families
    "latin":      1.0,
    "cyrillic":   1.0,
    "arabic":     1.0,
    "devanagari": 1.0,
    "dravidian":  1.0,
    "cjk":        1.0,
    "se_asian":   1.0,
    "geez":       1.0,
    "hebrew":     1.0,
    # Unique-script languages (one language per group)
    "georgian":   1.0,
    "sinhala":    1.0,
    "thaana":     1.0,   # Dhivehi
    "meitei":     1.0,   # Meiteilon (Manipuri)
    "armenian":   1.0,
    "greek":      1.0,
}


# ---------------------------------------------------------------------------
# Language → group key (do not edit unless you add/remove languages)
# ---------------------------------------------------------------------------

# Unique-script languages: maps language name (lowercase) → GROUP_MULTIPLIERS key
UNIQUE_LANGUAGE_KEY: dict[str, str] = {
    "georgian":             "georgian",
    "sinhala":              "sinhala",
    "dhivehi":              "thaana",
    "meiteilon (manipuri)": "meitei",
    "armenian":             "armenian",
    "greek":                "greek",
}

# All other languages → script group key
LANGUAGE_SCRIPT: dict[str, str] = {
    # Latin (~70 languages)
    "afrikaans": "latin", "albanian": "latin", "aymara": "latin",
    "azerbaijani": "latin", "bambara": "latin", "basque": "latin",
    "catalan": "latin", "cebuano": "latin", "corsican": "latin",
    "croatian": "latin", "czech": "latin", "danish": "latin",
    "dutch": "latin", "english": "latin", "esperanto": "latin",
    "estonian": "latin", "ewe": "latin", "filipino": "latin",
    "finnish": "latin", "french": "latin", "frisian": "latin",
    "galician": "latin", "german": "latin", "guarani": "latin",
    "haitian creole": "latin", "hausa": "latin", "hawaiian": "latin",
    "hmong": "latin", "hungarian": "latin", "icelandic": "latin",
    "igbo": "latin", "ilocano": "latin", "indonesian": "latin",
    "irish": "latin", "italian": "latin", "javanese": "latin",
    "kinyarwanda": "latin", "krio": "latin", "latin": "latin",
    "latvian": "latin", "lithuanian": "latin", "luganda": "latin",
    "luxembourgish": "latin", "malagasy": "latin", "maltese": "latin",
    "maori": "latin", "mizo": "latin", "norwegian": "latin",
    "oromo": "latin", "polish": "latin", "portuguese": "latin",
    "quechua": "latin", "romanian": "latin", "samoan": "latin",
    "scots gaelic": "latin", "sesotho": "latin", "slovenian": "latin",
    "somali": "latin", "spanish": "latin", "sundanese": "latin",
    "swahili": "latin", "tsonga": "latin", "turkish": "latin",
    "turkmen": "latin", "twi": "latin", "uzbek": "latin",
    "vietnamese": "latin", "welsh": "latin", "xhosa": "latin",
    "yoruba": "latin",
    # Cyrillic
    "belarusian": "cyrillic", "bulgarian": "cyrillic", "kazakh": "cyrillic",
    "kyrgyz": "cyrillic", "macedonian": "cyrillic", "mongolian": "cyrillic",
    "russian": "cyrillic", "serbian": "cyrillic", "tajik": "cyrillic",
    "tatar": "cyrillic", "ukrainian": "cyrillic",
    # Arabic script
    "arabic": "arabic", "kurdish": "arabic", "pashto": "arabic",
    "persian": "arabic", "sindhi": "arabic", "urdu": "arabic",
    "uyghur": "arabic",
    # Devanagari / Indic (grouped as per Runic Help CSV)
    "assamese": "devanagari", "bengali": "devanagari", "bhojpuri": "devanagari",
    "dogri": "devanagari", "gujarati": "devanagari", "hindi": "devanagari",
    "konkani": "devanagari", "maithili": "devanagari", "marathi": "devanagari",
    "nepali": "devanagari", "punjabi (gurmukhi)": "devanagari",
    "sanskrit": "devanagari",
    # Dravidian
    "kannada": "dravidian", "malayalam": "dravidian", "odia (oriya)": "dravidian",
    "tamil": "dravidian", "telugu": "dravidian",
    # CJK
    "chinese (traditional)": "cjk", "japanese": "cjk", "korean": "cjk",
    # Southeast Asian
    "khmer": "se_asian", "lao": "se_asian",
    "myanmar (burmese)": "se_asian", "thai": "se_asian",
    # Ge'ez
    "amharic": "geez", "tigrinya": "geez",
    # Hebrew script
    "hebrew": "hebrew", "yiddish": "hebrew",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _group_key(language: str) -> str:
    """Return the GROUP_MULTIPLIERS key for a language name."""
    key = language.lower()
    if key in UNIQUE_LANGUAGE_KEY:
        return UNIQUE_LANGUAGE_KEY[key]
    return LANGUAGE_SCRIPT.get(key, "latin")


def _build_group_sizes(contours: list[GlyphContour]) -> dict[str, int]:
    """Count how many contours belong to each group."""
    sizes: dict[str, int] = {}
    for c in contours:
        g = _group_key(c.language)
        sizes[g] = sizes.get(g, 0) + 1
    return sizes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_weights(contours: list[GlyphContour]) -> np.ndarray:
    """Compute normalised blend weights for a list of glyph contours.

    Each group contributes (multiplier / group_size) per language, so with all
    multipliers equal every group has identical total influence. A ±10% random
    jitter is applied before normalisation.

    Args:
        contours: Ordered list of GlyphContour objects (same order as vectors).

    Returns:
        1-D float64 array of length len(contours), summing to 1.0.
    """
    group_sizes = _build_group_sizes(contours)

    weights = []
    for c in contours:
        g = _group_key(c.language)
        multiplier = GROUP_MULTIPLIERS.get(g, 1.0)
        size = group_sizes[g]
        # Equal-influence baseline: multiplier / size
        # Jitter: ±10% so each render is slightly different
        w = (multiplier / size) * (0.9 + 0.2 * random())
        weights.append(w)

    arr = np.array(weights, dtype=np.float64)
    total = arr.sum()
    if total > 0:
        arr /= total
    return arr


def group_influence(contours: list[GlyphContour]) -> dict[str, float]:
    """Return the expected % influence per group (no jitter, pre-normalisation).

    Useful for previewing how the current GROUP_MULTIPLIERS will distribute
    influence before running a full generate.

    Returns:
        Dict mapping group name → fraction of total influence (sums to 1.0).
    """
    group_sizes = _build_group_sizes(contours)
    raw: dict[str, float] = {}
    for g, size in group_sizes.items():
        multiplier = GROUP_MULTIPLIERS.get(g, 1.0)
        raw[g] = multiplier / size * size   # = multiplier
    total = sum(raw.values())
    return {g: v / total for g, v in raw.items()}
