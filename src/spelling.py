"""Spelling correction for TV show / serial searches.

Hindi serial names are typed in many romanised ways (Anupama / Anupamaa /
Anupmaa, Yeh Rishta / Ye Rista, Kundali / Kundli Bhagya). Matching is done on a
*phonetic key* (double letters collapsed, common transliteration swaps
normalised, vowels softened) and only against the show-name part of each
catalog title — the first few words — so long file captions like
"Anupama Anupama'S Unexpected Shock Hs Dl Aac2 0 H 264" don't dilute the score.
"""
from __future__ import annotations

import re
from typing import Optional

from rapidfuzz import fuzz, process


def _normalize(s: str) -> str:
    s = re.sub(r"[^a-z0-9\s]", " ", (s or "").lower())
    return re.sub(r"\s+", " ", s).strip()


# Common misspelling → correction map (normalised form → correct name)
COMMON_FIXES = {
    "mirjapur": "mirzapur",
    "mirjapurr": "mirzapur",
    "mirzapurr": "mirzapur",
    "hanuman ansh": "hanumanansh",
    "hanumanash": "hanumanansh",
    "suryavanshi": "sooryavanshi",
    "suryavansh": "sooryavanshi",
    "brahmashtra": "brahmastra",
    "brahmaastra": "brahmastra",
    "ranjnaa": "ranjana",
    "krissh": "krrish",
    "krishh": "krrish",
    "krisshh": "krrish",
    "rajneeti": "raajneeti",
    "donnd": "don",
    "sholayy": "sholay",
    "sholaay": "sholay",
    # TV serials
    "anupma": "anupamaa",
    "anupmaa": "anupamaa",
    "anupamma": "anupamaa",
    "ye rishta": "yeh rishta kya kehlata hai",
    "yrkkh": "yeh rishta kya kehlata hai",
    "yeh rista": "yeh rishta kya kehlata hai",
    "kundli bhagya": "kundali bhagya",
    "kundli bhagy": "kundali bhagya",
    "kumkum bhagy": "kumkum bhagya",
    "kumkum bagya": "kumkum bhagya",
    "tmkoc": "taarak mehta ka ooltah chashmah",
    "tarak mehta": "taarak mehta ka ooltah chashmah",
    "taarak mehta": "taarak mehta ka ooltah chashmah",
    "gum hai kisi ke pyar me": "ghum hai kisikey pyaar meiin",
    "ghkkpm": "ghum hai kisikey pyaar meiin",
    "bhagya laxmi": "bhagya lakshmi",
    "bhagyalaxmi": "bhagya lakshmi",
    "big boss": "bigg boss",
    "bigboss": "bigg boss",
}

# Applied in order on the normalised string.
_PHONETIC_SWAPS = (
    ("ksh", "x"), ("kh", "k"), ("gh", "g"), ("bh", "b"), ("dh", "d"), ("th", "t"),
    ("ph", "f"), ("sh", "s"), ("ch", "c"), ("jh", "j"), ("z", "j"), ("w", "v"),
    ("q", "k"), ("ck", "k"), ("ee", "i"), ("oo", "u"), ("ou", "u"), ("y", "i"),
)


def phonetic(s: str) -> str:
    """Spelling-insensitive key: 'Anupamaa' == 'anupama' == 'anupmaa'-ish."""
    s = _normalize(s)
    for a, b in _PHONETIC_SWAPS:
        s = s.replace(a, b)
    s = re.sub(r"(.)\1+", r"\1", s)          # collapse doubled letters
    s = re.sub(r"\bh\b|h(?=\s|$)", "", s)      # trailing silent h (yeh -> ye)
    s = re.sub(r"a(?=\s|$)", "", s)            # trailing 'a'/'aa' (anupamaa -> anupam)
    return re.sub(r"\s+", " ", s).strip()


def _show_phrases(title: str, n_words: int) -> list[str]:
    words = _normalize(title).split()
    if not words:
        return []
    out = []
    for n in {max(1, n_words - 1), n_words, n_words + 1}:
        if n <= len(words):
            out.append(" ".join(words[:n]))
    return out


def correct_spelling(query: str, catalog_titles: Optional[list[str]] = None) -> Optional[str]:
    """Return the corrected show name for a misspelled query, or None."""
    q_norm = _normalize(query)
    if not q_norm or len(q_norm) < 3:
        return None
    if q_norm in COMMON_FIXES:
        return COMMON_FIXES[q_norm]
    if not catalog_titles:
        return None

    q_key = phonetic(q_norm)
    n_words = len(q_norm.split())
    best: tuple[float, str] = (0.0, "")
    for title in catalog_titles:
        for phrase in _show_phrases(title, n_words):
            if phrase == q_norm:
                return None  # already spelled correctly
            p_key = phonetic(phrase)
            if not p_key:
                continue
            score = fuzz.ratio(q_key, p_key) if p_key != q_key else 100.0
            # tiny bonus for same first letter — users rarely get that wrong
            if q_key[:1] == p_key[:1]:
                score += 3
            if score > best[0]:
                best = (score, phrase)
    cutoff = 80 if len(q_key) >= 5 else 90
    if best[0] >= cutoff and best[1] != q_norm:
        return best[1]
    return None


def suggest_corrections(query: str, catalog_titles: Optional[list[str]] = None, limit: int = 3) -> list[str]:
    """Up to `limit` distinct show names that look like the query."""
    q_norm = _normalize(query)
    if not q_norm or not catalog_titles:
        return []
    q_key = phonetic(q_norm)
    n_words = len(q_norm.split())
    phrases = {}
    for title in catalog_titles:
        for phrase in _show_phrases(title, n_words):
            phrases.setdefault(phonetic(phrase), phrase)
    if not phrases:
        return []
    results = process.extract(q_key, list(phrases.keys()), scorer=fuzz.ratio, score_cutoff=70, limit=limit * 3)
    out: list[str] = []
    for key, _score, _ in results:
        name = phrases[key]
        if name not in out and name != q_norm:
            out.append(name)
        if len(out) >= limit:
            break
    return out
