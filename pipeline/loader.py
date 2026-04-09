"""Load translations from a user-provided CSV file."""

import csv


def load_translations(path: str) -> list[dict]:
    """Load translations from a CSV with columns: language, translation.

    Args:
        path: Path to the CSV file.

    Returns:
        List of dicts with keys: language, translation.
    """
    results = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            lang = row["language"].strip()
            text = row["translation"].strip()
            if lang and text:
                results.append({"language": lang, "translation": text})
    return results
