"""Auto-translate a word using only Google Translate (deep-translator)."""

from deep_translator import GoogleTranslator
from deep_translator.constants import GOOGLE_LANGUAGES_TO_CODES

# Special case overrides for variant languages
SPECIAL_CASES = {
    "kurdish": "ckb",              # Sorani
    "punjabi (shahmukhi)": None,   # Skip — manual
    "malay (jawi)": None,          # Skip — manual
}


def _build_language_map(languages: list[str]) -> dict[str, str]:
    """Map language names to deep-translator language codes."""
    supported = GOOGLE_LANGUAGES_TO_CODES
    mapping = {}

    for lang in languages:
        full_key = lang.lower()
        short_key = full_key.split(" (")[0]

        # Special cases
        if full_key in SPECIAL_CASES:
            code = SPECIAL_CASES[full_key]
            if code:
                mapping[lang] = code
            continue

        if short_key in SPECIAL_CASES:
            code = SPECIAL_CASES[short_key]
            if code:
                mapping[lang] = code
            continue

        # Standard lookup
        if full_key in supported:
            mapping[lang] = supported[full_key]
        elif short_key in supported:
            mapping[lang] = supported[short_key]

    return mapping


def auto_translate(word: str, languages: list[str],
                   skip: set[str] | None = None,
                   on_progress=None) -> dict[str, str]:
    """Translate a word into all supported languages via Google Translate.

    Args:
        word: Word to translate
        languages: List of language names
        skip: Languages to skip
        on_progress: Optional progress callback

    Returns:
        Dict {language_name: translation}
    """
    if skip is None:
        skip = set()

    word = word.lower()

    mapping = _build_language_map(languages)

    to_translate = [(lang, code) for lang, code in mapping.items()
                    if lang not in skip]

    total = len(to_translate)
    results = {}

    for i, (lang, code) in enumerate(to_translate):
        try:
            translated = GoogleTranslator(source="auto", target=code).translate(word)
            if translated and translated.strip():
                results[lang] = translated.strip()
        except Exception:
            pass  # fail silently

        if on_progress:
            on_progress(i + 1, total)

    return results