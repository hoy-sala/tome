"""ISO-639 language normalization for the language facet/filter.

Stored ``Book.language`` values are messy — ``en``, ``eng``, ``en-US``,
``English`` all appear because they come straight from per-file embedded
metadata. We fold them to a canonical lowercase 2-letter code for filtering and
show a human label in the UI, so the dropdown has one "English" entry rather
than four near-duplicates.
"""

# Canonical 2-letter code -> display name. Scoped to languages plausible in an
# ebook library; unknown codes fall through and display their raw token.
_LANG_NAMES = {
    "en": "English", "de": "German", "fr": "French", "es": "Spanish",
    "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "sv": "Swedish",
    "no": "Norwegian", "da": "Danish", "fi": "Finnish", "pl": "Polish",
    "ru": "Russian", "uk": "Ukrainian", "cs": "Czech", "tr": "Turkish",
    "ja": "Japanese", "zh": "Chinese", "ko": "Korean", "ar": "Arabic",
    "he": "Hebrew", "hi": "Hindi", "th": "Thai", "vi": "Vietnamese",
    "id": "Indonesian", "el": "Greek", "hu": "Hungarian", "ro": "Romanian",
    "la": "Latin",
}

# 3-letter (ISO-639-2/B and /T) and English-name aliases -> 2-letter code.
_ALIASES = {
    "eng": "en", "english": "en",
    "ger": "de", "deu": "de", "german": "de",
    "fre": "fr", "fra": "fr", "french": "fr",
    "spa": "es", "spanish": "es",
    "ita": "it", "italian": "it",
    "por": "pt", "portuguese": "pt",
    "dut": "nl", "nld": "nl", "dutch": "nl",
    "swe": "sv", "swedish": "sv",
    "nor": "no", "norwegian": "no",
    "dan": "da", "danish": "da",
    "fin": "fi", "finnish": "fi",
    "pol": "pl", "polish": "pl",
    "rus": "ru", "russian": "ru",
    "ukr": "uk", "ukrainian": "uk",
    "cze": "cs", "ces": "cs", "czech": "cs",
    "tur": "tr", "turkish": "tr",
    "jpn": "ja", "japanese": "ja",
    "chi": "zh", "zho": "zh", "chinese": "zh",
    "kor": "ko", "korean": "ko",
    "ara": "ar", "arabic": "ar",
    "heb": "he", "hebrew": "he",
    "hin": "hi", "hindi": "hi",
    "tha": "th", "thai": "th",
    "vie": "vi", "vietnamese": "vi",
    "ind": "id", "indonesian": "id",
    "gre": "el", "ell": "el", "greek": "el",
    "hun": "hu", "hungarian": "hu",
    "rum": "ro", "ron": "ro", "romanian": "ro",
    "lat": "la", "latin": "la",
}


def normalize_language(raw: str | None) -> str | None:
    """Fold a raw stored language value to a canonical lowercase code.

    ``en`` / ``eng`` / ``en-US`` / ``English`` all collapse to ``en``. Unknown
    values return their lowercased base token so they still group consistently.
    """
    if not raw:
        return None
    s = raw.strip().lower().replace("_", "-")
    if not s:
        return None
    if s in _ALIASES:
        return _ALIASES[s]
    base = s.split("-", 1)[0]
    if base in _LANG_NAMES:
        return base
    if base in _ALIASES:
        return _ALIASES[base]
    return base


def language_label(code: str) -> str:
    """Human-readable name for a canonical code; falls back to the upper-cased code."""
    return _LANG_NAMES.get(code, code.upper())
