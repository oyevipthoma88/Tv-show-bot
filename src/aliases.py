"""Show-name aliases, shortcuts and phonetic keys.

One serial is posted under many names: "TMKOC", "Taarak Mehta", "Tarak Mehta Ka
Oolta Chasma", "Taarak Mehta Ka Ooltah Chashmah 4570"... Every variant listed
here collapses to ONE canonical show name, so search, spelling fixes, the
episode list, Follow and new-episode alerts all treat them as the same show.

Pure-python (only `re`) so episode.py can import it without cycles.
"""
from __future__ import annotations

import re

# canonical name -> shortcuts / common spellings (any case, punctuation ignored)
SHOW_ALIASES: dict[str, list[str]] = {
    "taarak mehta ka ooltah chashmah": [
        "tmkoc", "tmkc", "tmkoc new", "taarak mehta", "tarak mehta", "tarak mehata", "taarak mehata",
        "tarak mehta ka oolta chasma", "tarak mehta ka ulta chasma", "tarak mehta ka ooltah chashmah",
        "taarak mehta ka oolta chashma", "tarak mehta ka oolta chashma", "taarak mehta ka ulta chashma",
        "tarak mehta ka ulta chashma", "taarak mehta ka ooltah chasmah", "tarak meheta", "jethalal",
        "tarak mehta ka oolta chsma", "taarak mehta ka oolta chsma", "tmkoc episode",
    ],
    "bigg boss": [
        "big boss", "bigboss", "biggboss", "bigg bos", "big bos", "bigg boss ott", "bb ott",
        "bigg boss 19", "bigg boss 18", "bigg boss 17", "big boss 19", "big boss 18", "bb19", "bb18",
        "bigg boss hindi", "bigg boss live",
    ],
    "yeh rishta kya kehlata hai": [
        "yrkkh", "ye rishta", "yeh rishta", "yeh rista", "ye rishta kya kehlata hai",
        "yeh rishta kya kahlata hai", "ye rishta kya kehlata hai", "yeh rishta kya kehlata h",
    ],
    "anupamaa": ["anupama", "anupma", "anupmaa", "anupamma", "anupamaa serial", "anupama serial"],
    "ghum hai kisikey pyaar meiin": [
        "ghkkpm", "gum hai kisi ke pyar me", "ghum hai kisi ke pyaar mein", "gum hai kisi ke pyaar mein",
        "ghum hai kisikey pyaar mein", "gum hai kisike pyar me",
    ],
    "kundali bhagya": ["kundli bhagya", "kundli bhagy", "kundali bhagy", "kundli bhagyaa"],
    "kumkum bhagya": ["kumkum bhagy", "kumkum bagya", "kumkum bhagyaa", "kumkum bhagya serial"],
    "bhagya lakshmi": ["bhagya laxmi", "bhagyalaxmi", "bhagyalakshmi", "bhagya laksmi"],
    "kaun banega crorepati": ["kbc", "kbc 17", "kbc17", "kaun banega karodpati", "kon banega crorepati"],
    "khatron ke khiladi": ["kkk", "kkk 15", "khatro ke khiladi", "khatron ke khiladi"],
    "the great indian kapil show": [
        "tgiks", "kapil sharma show", "the kapil sharma show", "kapil show", "great indian kapil show",
    ],
    "indian idol": ["indian idol 16", "indian idol 15", "indian idal"],
    "india's got latent": ["igl", "indias got latent", "india got latent"],
    "laughter chefs": ["laughter chef", "lafter chefs", "laughter chefs unlimited entertainment"],
    "bhabiji ghar par hain": ["bhabi ji ghar par hai", "bhabiji ghar pe hai", "bhabhi ji ghar par hain",
                              "bhabiji ghar par hai", "bhabi ji ghar par hain"],
    "happu ki ultan paltan": ["happu ki ultan paltan", "happu ki ulta paltan"],
    "wagle ki duniya": ["wagle ki duniyaa", "wagle ki dunia"],
    "pushpa impossible": ["pushpa impossibel", "pushpa imposible"],
    "crime patrol": ["crime petrol", "crime patrol satark", "crime patrol 2 0"],
    "savdhaan india": ["savdhan india", "savdhaan india fight back"],
    "cid": ["c i d", "cid 2", "cid season 2"],
    "naagin": ["nagin", "naagin 7", "nagin 7"],
    "mangal lakshmi": ["mangal laxmi", "mangal lakshmi serial"],
    "udne ki aasha": ["udne ki asha", "udne ki aasha serial"],
    "jhanak": ["jhanak serial"],
    "advocate anjali awasthi": ["anjali awasthi", "advocate anjali"],
    "teri meri doriyaann": ["teri meri doriyaan", "teri meri doriya"],
    "kaise mujhe tum mil gaye": ["kaise mujhe tum mil gaye serial", "kmtmg"],
    "parineetii": ["parineeti", "parinitii", "parineeti serial"],
    "vasudha": ["vasudha serial"],
    "shiv shakti tap tyaag tandav": ["shiv shakti", "shiv shakti serial"],
    "iss ishq ka rabb rakha": ["is ishq ka rab rakha", "iss ishq ka rab rakha"],
    "jaane anjaane hum mile": ["jaane anjane hum mile", "jane anjane hum mile"],
    "tum se tum tak": ["tum se tum tak serial"],
    "mirzapur": ["mirjapur", "mirjapurr", "mirzapurr"],
}

# Movie spellings kept from the old spelling map (not shows, so no grouping).
WORD_FIXES: dict[str, str] = {
    "hanuman ansh": "hanumanansh", "hanumanash": "hanumanansh", "suryavanshi": "sooryavanshi",
    "suryavansh": "sooryavanshi", "brahmashtra": "brahmastra", "brahmaastra": "brahmastra",
    "ranjnaa": "ranjana", "krissh": "krrish", "krishh": "krrish", "krisshh": "krrish",
    "rajneeti": "raajneeti", "donnd": "don", "sholayy": "sholay", "sholaay": "sholay",
}

# Applied in order on the normalised string.
_PHONETIC_SWAPS = (
    ("ksh", "x"), ("kh", "k"), ("gh", "g"), ("bh", "b"), ("dh", "d"), ("th", "t"),
    ("ph", "f"), ("sh", "s"), ("ch", "c"), ("jh", "j"), ("z", "j"), ("w", "v"),
    ("q", "k"), ("ck", "k"), ("ee", "i"), ("oo", "u"), ("ou", "u"), ("y", "i"),
)


def normalize(s: str) -> str:
    s = re.sub(r"[^a-z0-9\s]", " ", (s or "").lower().replace("'", ""))
    return re.sub(r"\s+", " ", s).strip()


def phonetic(s: str) -> str:
    """Spelling-insensitive key: 'Anupamaa' == 'anupama', 'chashmah' == 'chasma'."""
    s = normalize(s)
    for a, b in _PHONETIC_SWAPS:
        s = s.replace(a, b)
    s = re.sub(r"(.)\1+", r"\1", s)            # collapse doubled letters
    s = re.sub(r"\bh\b|h(?=\s|$)", "", s)      # trailing silent h (yeh -> ye)
    s = re.sub(r"a(?=\s|$)", "", s)            # trailing 'a'/'aa' (anupamaa -> anupam)
    return re.sub(r"\s+", " ", s).strip()


def _build_tables():
    plain: dict[str, str] = {}
    phon: dict[str, str] = {}
    for canon, variants in SHOW_ALIASES.items():
        for v in [canon, *variants]:
            n = normalize(v)
            if not n:
                continue
            plain.setdefault(n, canon)
            p = phonetic(n)
            if p and len(p) >= 3:
                phon.setdefault(p, canon)
    # longest first, so "bigg boss ott" wins over "bigg boss" / "bb"
    return (sorted(plain.items(), key=lambda kv: -len(kv[0])),
            sorted(phon.items(), key=lambda kv: -len(kv[0])))


_PLAIN, _PHON = _build_tables()
ALIAS_VERSION = str(sum(len(k) + len(v) for k, v in _PLAIN))  # changes when the map changes


def _prefix_hit(text: str, table) -> str:
    for variant, canon in table:
        if text == variant or text.startswith(variant + " "):
            return canon
    return ""


def canonical_show(text: str) -> str:
    """Canonical show name if `text` starts with a known show/shortcut, else ''.

    "Tarak Mehta Ka Oolta Chasma 4570" -> "taarak mehta ka ooltah chashmah"
    "Bigg Boss 19 Grand Finale"        -> "bigg boss"
    """
    n = normalize(text)
    if not n:
        return ""
    hit = _prefix_hit(n, _PLAIN)
    if hit:
        return hit
    p = phonetic(n)
    return _prefix_hit(p, _PHON) if p else ""


def all_alias_names() -> list[str]:
    """Every searchable alias + canonical name (normalised)."""
    return [variant for variant, _ in _PLAIN]


def alias_target(variant: str) -> str:
    return dict(_PLAIN).get(normalize(variant), "")


__all__ = ["SHOW_ALIASES", "WORD_FIXES", "normalize", "phonetic", "canonical_show",
           "all_alias_names", "alias_target", "ALIAS_VERSION"]
