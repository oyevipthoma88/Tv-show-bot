"""Spelling correction + shortcuts for TV show / serial searches.

Hindi serial names are typed in many romanised ways (Anupama / Anupamaa /
Anupmaa, Tarak Mehta ka oolta chsma, TMKOC, Big Boss). Order of checks:

1. Known shortcut / alias (aliases.SHOW_ALIASES) — exact or prefix, also
   phonetic ("tarak mehta ka oolta chsma" -> Taarak Mehta Ka Ooltah Chashmah).
2. Fuzzy phonetic match against the alias table.
3. Fuzzy phonetic match against the show-name part of every catalog title.
"""
from __future__ import annotations

import re
from typing import Optional

from rapidfuzz import fuzz, process

from aliases import (SHOW_ALIASES, WORD_FIXES, alias_target, all_alias_names, canonical_show,
                     normalize as _normalize, phonetic)

# Back-compat: old code/tests import COMMON_FIXES (normalised variant -> correct name).
COMMON_FIXES: dict[str, str] = dict(WORD_FIXES)
for _canon, _variants in SHOW_ALIASES.items():
    for _v in _variants:
        COMMON_FIXES.setdefault(_normalize(_v), _canon)

_ALIAS_PHON = {phonetic(name): name for name in all_alias_names() if len(phonetic(name)) >= 3}


def _show_phrases(title: str, n_words: int) -> list[str]:
    words = _normalize(title).split()
    if not words:
        return []
    out = []
    for n in sorted({max(1, n_words - 1), n_words, n_words + 1}):
        if n <= len(words):
            out.append(" ".join(words[:n]))
    return out


def alias_fix(query: str) -> Optional[str]:
    """Canonical show for a shortcut / misspelt alias, else None."""
    q_norm = _normalize(query)
    if not q_norm or len(q_norm) < 2:
        return None
    if q_norm in WORD_FIXES:
        return WORD_FIXES[q_norm]
    canon = canonical_show(q_norm)
    if canon:
        return canon
    if len(q_norm) < 4:
        return None
    q_key = phonetic(q_norm)
    if not q_key:
        return None
    # Fuzzy against every alias phonetic key ("tarak mehta ka olta chsma").
    hit = process.extractOne(q_key, list(_ALIAS_PHON), scorer=fuzz.ratio, score_cutoff=84)
    if hit:
        return alias_target(_ALIAS_PHON[hit[0]]) or None
    # Half-typed name: "taarak meh" / "kundali bha"
    if len(q_norm) >= 6:
        for key, name in _ALIAS_PHON.items():
            if key.startswith(q_key) and len(key) - len(q_key) <= 14:
                return alias_target(name) or None
    return None


def correct_spelling(query: str, catalog_titles: Optional[list[str]] = None) -> Optional[str]:
    """Return the corrected show name for a misspelled query, or None."""
    q_norm = _normalize(query)
    if not q_norm or len(q_norm) < 3:
        return None
    fixed = alias_fix(q_norm)
    if fixed and fixed != q_norm:
        return fixed
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


_STOP = {"ka", "ki", "ke", "hai", "hain", "me", "mein", "the", "a", "of", "and", "se", "ko", "episode",
         "full", "new", "today", "serial", "show", "season", "part"}


def suggest_corrections(query: str, catalog_titles: Optional[list[str]] = None, limit: int = 3) -> list[str]:
    """Up to `limit` related show names that exist in the catalog.

    Mixes phonetic look-alikes, alias hits and shows sharing a meaningful word
    with the query, so "not found" always offers something related.
    """
    q_norm = _normalize(query)
    if not q_norm or not catalog_titles:
        return []
    q_key = phonetic(q_norm)
    n_words = len(q_norm.split())
    phrases: dict[str, str] = {}
    for title in catalog_titles:
        for phrase in _show_phrases(title, n_words):
            phrases.setdefault(phonetic(phrase), phrase)
    out: list[str] = []

    def add(name: str) -> None:
        name = _normalize(name)
        if name and name != q_norm and name not in out and len(out) < limit:
            out.append(name)

    # 1) alias -> only if that show is actually in the catalog
    canon = alias_fix(q_norm)
    if canon:
        c_words = len(canon.split())
        for title in catalog_titles:
            if canonical_show(title) == canon or _normalize(title).startswith(canon):
                add(canon if canonical_show(title) == canon else " ".join(_normalize(title).split()[:c_words]))
                break
    # 2) phonetic look-alikes
    if phrases and q_key:
        for key, _score, _ in process.extract(q_key, list(phrases), scorer=fuzz.ratio,
                                              score_cutoff=66, limit=limit * 3):
            add(phrases[key])
    # 3) shows sharing a real word with the query ("mehta", "boss", "bhagya")
    words = [w for w in q_norm.split() if len(w) >= 4 and w not in _STOP]
    if words and len(out) < limit:
        p_words = {phonetic(w) for w in words}
        for title in catalog_titles:
            t_words = _normalize(title).split()[:5]
            if any(phonetic(w) in p_words for w in t_words):
                add(" ".join(t_words[:4]))
            if len(out) >= limit:
                break
    return out


__all__ = ["COMMON_FIXES", "phonetic", "alias_fix", "correct_spelling", "suggest_corrections"]
