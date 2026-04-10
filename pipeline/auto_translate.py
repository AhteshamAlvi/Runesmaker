"""Auto-translate a word into all supported languages using Google Translate."""

from deep_translator import GoogleTranslator
from deep_translator.constants import GOOGLE_LANGUAGES_TO_CODES

# Special case overrides for variant languages
SPECIAL_CASES = {
    "kurdish": "ckb",              # Sorani (Arabic script)
    "punjabi (shahmukhi)": None,   # Skip — manual entry only
    "malay (jawi)": None,          # Skip — manual entry only (Arabic script variant)
}


def _build_language_map(languages: list[str]) -> dict[str, str]:
    """Map language names to deep-translator language codes.

    Returns dict of {language_name: code} for supported languages.
    """
    supported = GOOGLE_LANGUAGES_TO_CODES
    mapping = {}

    for lang in languages:
        full_key = lang.lower()
        short_key = full_key.split(" (")[0]

        # Check special cases first
        if full_key in SPECIAL_CASES:
            code = SPECIAL_CASES[full_key]
            if code is not None:
                mapping[lang] = code
            continue
        if short_key in SPECIAL_CASES:
            code = SPECIAL_CASES[short_key]
            if code is not None:
                mapping[lang] = code
            continue

        # Standard lookup: full name first, then short name
        if full_key in supported:
            mapping[lang] = supported[full_key]
        elif short_key in supported:
            mapping[lang] = supported[short_key]

    return mapping


def auto_translate(word: str, languages: list[str],
                   skip: set[str] | None = None,
                   on_progress=None) -> dict[str, str]:
    """Translate a word into all supported languages.

    Args:
        word: The word to translate.
        languages: List of language names from languages.txt.
        skip: Set of language names to skip (e.g. already filled manually).
        on_progress: Optional callback(done, total) for progress updates.

    Returns:
        Dict of {language_name: translated_text} for successful translations.
    """
    if skip is None:
        skip = set()

    mapping = _build_language_map(languages)

    # Filter out skipped languages
    to_translate = {lang: code for lang, code in mapping.items() if lang not in skip}

    results = {}
    total = len(to_translate)

    for i, (lang, code) in enumerate(to_translate.items()):
        try:
            translated = GoogleTranslator(source="auto", target=code).translate(word)
            if translated:
                results[lang] = translated
        except Exception:
            pass

        if on_progress:
            on_progress(i + 1, total)

    return results
