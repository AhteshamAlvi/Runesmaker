"""Auto-translate a word into all supported languages.

Primary: Google Translate (via deep-translator) — covers ~132 languages.
Fallback: Wiktionary translation tables — covers many of the remaining ~110.
"""

import re

import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from deep_translator.constants import GOOGLE_LANGUAGES_TO_CODES

# Special case overrides for variant languages
SPECIAL_CASES = {
    "kurdish": "ckb",              # Sorani (Arabic script)
    "punjabi (shahmukhi)": None,   # Skip — manual entry only
    "malay (jawi)": None,          # Skip — manual entry only (Arabic script variant)
}

# Wiktionary uses different names for some languages.
# Maps our language name (lowercase) -> list of Wiktionary keys to try.
WIKTIONARY_ALIASES = {
    "cantonese":                ["cantonese", "yue"],
    "dari":                     ["dari", "persian"],
    "fulani":                   ["fula", "fulfulde", "pulaar"],
    "hakha chin":               ["chin"],
    "inuktut":                  ["inuktitut", "inuit"],
    "jamaican patois":          ["jamaican creole", "jamaican"],
    "kalaallisut":              ["greenlandic", "kalaallisut"],
    "kikongo":                  ["kongo", "kikongo"],
    "makassar":                 ["makasar", "makassarese"],
    "marwadi":                  ["marwari", "marwadi"],
    "bikol":                    ["central bikol", "bikol"],
    "fulani":                   ["fula", "fulfulde", "pulaar", "pular", "fulani"],
    "hakha chin":               ["hakha chin", "tedim chin", "thado chin", "daai chin", "chin"],
    "komi":                     ["komi-zyrian", "komi-permyak", "komi"],
    "meadow mari":              ["eastern mari", "western mari", "mari"],
    "minang":                   ["minangkabau", "minang"],
    "nepalbhasa (newari)":      ["newari", "nepal bhasa", "newar"],
    "papiamento":               ["papiamentu", "papiamento"],
    "swati":                    ["swazi", "swati"],
    "tamazight":                ["central atlas tamazight", "tamazight", "berber"],
    "tshiluba":                 ["luba-kasai", "luba", "tshiluba"],
    "waray":                    ["waray-waray", "waray"],
    "batak toba":               ["toba batak", "batak toba", "batak"],
    "cantonese":                ["cantonese"],
    "jingpo":                   ["jingpho", "jingpo", "kachin", "jinghpaw"],
    "ndebele (south)":          ["southern ndebele", "ndebele"],
    "sami (north)":             ["sami", "northern sami"],
    "santali (ol chiki)":       ["santali"],
    "meiteilon (manipuri)":     ["meitei", "manipuri", "meiteilon"],
    "odia (oriya)":             ["odia", "oriya"],
    "myanmar (burmese)":        ["burmese", "myanmar"],
    "punjabi (gurmukhi)":       ["punjabi"],
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


def _clean_wikt_translation(raw: str) -> str:
    """Extract the primary translation word from a Wiktionary entry.

    Strips romanizations, language codes, gender markers, and sub-dialects.
    """
    # If multi-line (sub-dialects), take the first line
    line = raw.split("\n")[0].strip()

    # If line has 'SubDialect: value', take the value part.
    # Only split if the colon appears before any parenthesis (avoid
    # splitting on colons inside romanizations like "(la:)").
    paren_pos = line.find("(")
    colon_pos = line.find(":")
    if colon_pos != -1 and (paren_pos == -1 or colon_pos < paren_pos):
        line = line.split(":", 1)[1].strip()

    # Take the first comma-separated option
    line = line.split(",")[0].strip()

    # Remove parenthesized content: romanizations, codes, notes
    # Also handle unclosed parens like "(la:" by matching to end of string
    line = re.sub(r"\s*\([^)]*\)", "", line)
    line = re.sub(r"\s*\([^)]*$", "", line)

    # Remove stray closing parens
    line = line.replace(")", "").strip()

    # Remove trailing gender markers: m, f, n, m pl, f pl
    line = re.sub(r"\s+[mfn](\s+pl)?$", "", line)

    return line.strip()


def _fetch_wiktionary_translations(word: str) -> dict[str, str]:
    """Scrape Wiktionary's translation tables for a word.

    Returns dict of {language_name_lowercase: cleaned_translation}.
    """
    # Wiktionary keeps translations on a subpage for common words.
    # URLs are case-sensitive — entries are lowercase.
    w = word.lower()
    urls = [
        f"https://en.wiktionary.org/wiki/{w}/translations",
        f"https://en.wiktionary.org/wiki/{w}",
    ]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            translations = {}

            def _direct_text(element):
                """Get only the direct text of an element, excluding nested lists."""
                parts = []
                for child in element.children:
                    if hasattr(child, "name") and child.name in ("ul", "ol", "dl"):
                        continue
                    if hasattr(child, "get_text"):
                        parts.append(child.get_text())
                    elif isinstance(child, str):
                        parts.append(child)
                return "".join(parts).strip()

            def _parse_li(item):
                """Parse a single <li> and return (lang, cleaned_text) or None."""
                text = _direct_text(item)
                if ":" not in text or len(text) > 300:
                    return None
                parts = text.split(":", 1)
                lang_part = parts[0].strip().lower()
                val = parts[1].strip()
                if "please add" in val.lower():
                    return None
                if any(c.isdigit() for c in lang_part):
                    return None
                cleaned = _clean_wikt_translation(val)
                if cleaned:
                    return (lang_part, cleaned)
                return None

            # Parse all <li> elements
            for item in soup.select("li"):
                result = _parse_li(item)
                if result:
                    translations[result[0]] = result[1]

            # Also parse <dd> elements — Wiktionary nests sub-languages
            # (e.g. Cantonese, Mandarin) under parent entries using <dl><dd>
            for dd in soup.select("dd"):
                text = _direct_text(dd)
                if ":" not in text or len(text) > 300:
                    continue
                parts = text.split(":", 1)
                lang_part = parts[0].strip().lower()
                val = parts[1].strip()
                if "please add" in val.lower():
                    continue
                if any(c.isdigit() for c in lang_part):
                    continue
                cleaned = _clean_wikt_translation(val)
                if cleaned:
                    translations[lang_part] = cleaned

            if translations:
                return translations

        except Exception:
            continue

    return {}


def auto_translate(word: str, languages: list[str],
                   skip: set[str] | None = None,
                   on_progress=None) -> dict[str, str]:
    """Translate a word into all supported languages.

    Phase 1: Google Translate (~132 languages).
    Phase 2: Wiktionary fallback for remaining languages.

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

    # Normalize to lowercase for consistent translations
    word = word.lower()

    mapping = _build_language_map(languages)

    # Phase 1: Google Translate
    to_translate = [(lang, mapping[lang]) for lang in languages
                    if lang in mapping and lang not in skip]

    # Phase 2 candidates: languages not covered by Google Translate
    remaining_langs = [lang for lang in languages
                       if lang not in mapping and lang not in skip]

    # Total = all languages we'll attempt (both phases)
    total = len(to_translate) + len(remaining_langs)

    results = {}

    for i, (lang, code) in enumerate(to_translate):
        try:
            translated = GoogleTranslator(source="auto", target=code).translate(word)
            if translated and translated.strip():
                results[lang] = translated.strip()
        except Exception:
            pass  # Skip languages that fail — user can fill manually

        if on_progress:
            on_progress(i + 1, total)

    # Phase 2: Wiktionary fallback for languages not covered by Google
    if remaining_langs:
        wikt_data = _fetch_wiktionary_translations(word)
        google_count = len(to_translate)

        for j, lang in enumerate(remaining_langs):
            if lang not in results and lang not in skip:
                full_key = lang.lower()
                short_key = full_key.split(" (")[0]

                # Try: exact name, short name, then aliases
                keys_to_try = [full_key, short_key]
                if full_key in WIKTIONARY_ALIASES:
                    keys_to_try.extend(WIKTIONARY_ALIASES[full_key])

                for key in keys_to_try:
                    if key in wikt_data:
                        results[lang] = wikt_data[key]
                        break

            if on_progress:
                on_progress(google_count + j + 1, total)

    return results
