"""Script-group and unique-language weights for rune blending.

Languages in visually distinctive scripts get higher weight so their glyph
shapes influence the composite rune more than the large Latin majority.
"""

from random import random
import numpy as np

from pipeline.glyph_extract import GlyphContour


# --- Weight tables ---

GROUP_WEIGHTS: dict[str, float] = {
    "latin":      0.008,   # 70+ languages — very common, low per-language weight
    "cyrillic":   0.073,
    "arabic":     0.171,
    "devanagari": 0.100,
    "dravidian":  0.217,
    "cjk":        0.500,
    "se_asian":   0.350,
    "geez":       0.700,
    "hebrew":     0.550,
    "unique":     1.000,   # fallback for unlisted unique-script languages
}

UNIQUE_WEIGHTS: dict[str, float] = {
    "georgian":  1.8,
    "sinhala":   1.7,
    "thaana":    1.8,   # Dhivehi
    "meitei":    1.9,   # Meiteilon (Manipuri)
    "armenian":  1.6,
    "greek":     1.2,   # visually close to Latin but still distinct
}


# --- Language → script group (from the Runic Help CSV) ---

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
    # Devanagari / Indic (grouped as per CSV)
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
    # Unique scripts (resolved individually below)
    "armenian": "unique", "dhivehi": "unique", "georgian": "unique",
    "greek": "unique", "meiteilon (manipuri)": "unique", "sinhala": "unique",
}

# Language name → key into UNIQUE_WEIGHTS (for non-trivial name mappings)
_UNIQUE_KEY: dict[str, str] = {
    "georgian":             "georgian",
    "sinhala":              "sinhala",
    "dhivehi":              "thaana",
    "meiteilon (manipuri)": "meitei",
    "armenian":             "armenian",
    "greek":                "greek",
}


def _base_weight(language: str) -> float:
    """Return the base (pre-jitter) weight for one language."""
    key = language.lower()

    # Check for a per-language unique override first
    unique_key = _UNIQUE_KEY.get(key)
    if unique_key is not None:
        return UNIQUE_WEIGHTS.get(unique_key, GROUP_WEIGHTS["unique"])

    # Fall back to script-group weight
    script = LANGUAGE_SCRIPT.get(key, "latin")
    return GROUP_WEIGHTS.get(script, GROUP_WEIGHTS["latin"])


def compute_weights(contours: list[GlyphContour]) -> np.ndarray:
    """Compute normalised blend weights for a list of glyph contours.

    Each contour is weighted by its language's script group (or unique override),
    with a ±10 % random jitter applied before normalisation so repeated renders
    of the same word produce subtly different runes.

    Args:
        contours: Ordered list of GlyphContour objects (same order as vectors).

    Returns:
        1-D float64 array of length len(contours), summing to 1.0.
    """
    weights = np.array(
        [_base_weight(c.language) * (0.9 + 0.2 * random()) for c in contours],
        dtype=np.float64,
    )

    total = weights.sum()
    if total > 0:
        weights /= total

    return weights
