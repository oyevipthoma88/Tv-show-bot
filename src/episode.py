"""TV show helpers: season / episode / air-date detection from captions.

Daily TV channels post captions like
    "Anupamaa 28th October 2026 Full Episode 1234 720p"
    "Mirzapur S03E05 1080p WEB-DL"
    "Bigg Boss 19 | Episode 62 | 29-10-2026"
These helpers pull out season, episode and air date so the bot can group
episodes per show, show them newest first and alert followers.
"""
from __future__ import annotations

import datetime as _dt
import re

from aliases import canonical_show

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_ALT = (r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
              r"|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?")

_SXE = re.compile(
    r"\b(?:S|Season)[\s._-]*0*(\d{1,2})[\s._-]*(?:E|Ep|Epi|Episode)[\s._#:-]*0*(\d{1,4})\b", re.I)
_SEASON = re.compile(r"\bseason[\s._-]*0*(\d{1,2})\b|\bS0*(\d{1,2})\b", re.I)
_EPISODE = re.compile(r"\b(?:episode|epi|ep)[\s._#:-]*0*(\d{1,4})\b|\bE0*(\d{1,4})\b", re.I)
_DATE_YMD = re.compile(r"\b((?:19|20)\d{2})[./-](\d{1,2})[./-](\d{1,2})\b")
_DATE_DMY = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-]((?:19|20)?\d{2})\b")
_DATE_D_MON = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?[\s,.-]*({_MONTH_ALT})\.?\b(?:[\s,.-]*((?:19|20)\d{{2}})\b)?", re.I)
_DATE_MON_D = re.compile(
    rf"\b({_MONTH_ALT})\.?[\s,.-]*(\d{{1,2}})(?:st|nd|rd|th)?\b(?:[\s,.-]+((?:19|20)\d{{2}})\b)?", re.I)
_LEFTOVER = re.compile(r"\b(full\s+episode|full|episodes?|season|written\s+update|today'?s?)\b", re.I)
_BARE_NUMBER = re.compile(r"(?<![\w.])(\d{3,5})(?![\w.])")
_QUALITY_JUNK = re.compile(
    r"@\w+|https?://\S+|\b(2160p|1440p|1080p|720p|480p|360p|4k|uhd|fhd|hd|sd|web-?dl|webrip|hdrip|"
    r"hdtv|x264|x265|hevc|aac\d?(?:\s\d)?|esubs?|hindi|english|dual\s+audio|mp4|mkv|avi|"
    r"h\s?\.?\s?26[45]|ddp?\d?(?:\s\d)?|\w*hub|hs\s+dl|hq|new\s+promo|promo|full\s+hd)\b", re.I)


def _safe_date(year: int, month: int, day: int):
    try:
        return _dt.date(year, month, day)
    except ValueError:
        return None


def _guess_year(month: int, day: int, today: _dt.date) -> int:
    year = today.year
    candidate = _safe_date(year, month, day)
    # "28 Dec" seen on 2 Jan belongs to last year.
    if candidate and (candidate - today).days > 31:
        return year - 1
    return year


def _find_date(text: str, today: _dt.date):
    """Return (date, (start, end)) for the first air date in text."""
    for regex, order in ((_DATE_YMD, "ymd"), (_DATE_DMY, "dmy"), (_DATE_D_MON, "dmon"), (_DATE_MON_D, "mond")):
        for m in regex.finditer(text):
            if order == "ymd":
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            elif order == "dmy":
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if y < 100:
                    y += 2000
            elif order == "dmon":
                d, mo = int(m.group(1)), _MONTHS.get(m.group(2).lower().rstrip("."), 0)
                y = int(m.group(3)) if m.group(3) else _guess_year(mo, d, today)
            else:
                mo, d = _MONTHS.get(m.group(1).lower().rstrip("."), 0), int(m.group(2))
                y = int(m.group(3)) if m.group(3) else _guess_year(mo, d, today)
            if not mo:
                continue
            found = _safe_date(y, mo, d)
            if found:
                return found, m.span()
    return None, None


_EXT = re.compile(r"\.(mp4|mkv|avi|mov|webm|m4v|ts)\b", re.I)


def normalize_separators(text: str) -> str:
    """File-name style captions -> plain words.

    "Indian_Game_Show_Season_2_Episode_24.mp4" / "Mannat.-.Har.Khushi.S01E05" ->
    "Indian Game Show Season 2 Episode 24" / "Mannat - Har Khushi S01E05".
    Underscores always become spaces ("_" is a regex word char, so it broke
    every \\b-based season/episode rule). Dots become spaces unless they sit
    between two digits (dates like 28.10.2026, "AAC2.0" stay intact).
    """
    t = (text or "").replace("\n", " ")
    t = _EXT.sub(" ", t)
    t = t.replace("_", " ")
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def parse_episode(text: str, today: _dt.date | None = None) -> dict:
    """Detect season/episode/air date and return the text with those parts removed.

    Also returns "show": only the words BEFORE the first season/episode/date
    marker ("Udne Ki Aasha S02E917 Pankhuri Refuses" -> "Udne Ki Aasha"), so the
    per-episode title never pollutes the show name.
    """
    raw = normalize_separators(text)
    today = today or _dt.date.today()
    season = episode = 0
    air_date = ""
    cleaned = raw

    found, span = _find_date(cleaned, today)
    if found:
        air_date = found.isoformat()
        cleaned = cleaned[:span[0]] + " " + cleaned[span[1]:]

    m = _SXE.search(cleaned)
    if m:
        season, episode = int(m.group(1)), int(m.group(2))
        cleaned = cleaned[:m.start()] + " " + cleaned[m.end():]
    else:
        m = _EPISODE.search(cleaned)
        if m:
            episode = int(m.group(1) or m.group(2))
            cleaned = cleaned[:m.start()] + " " + cleaned[m.end():]
        s = _SEASON.search(cleaned)
        if s:
            season = int(s.group(1) or s.group(2))
            cleaned = cleaned[:s.start()] + " " + cleaned[s.end():]
    if not episode and air_date:
        # Daily soaps: "Taarak Mehta 4570 28.10.2026" -> episode 4570.
        for num in _BARE_NUMBER.finditer(cleaned):
            value = int(num.group(1))
            if not (1950 <= value <= 2049):
                episode = value
                cleaned = cleaned[:num.start()] + " " + cleaned[num.end():]
                break

    show = ""
    marks = [mm.start() for rx in (_SXE, _EPISODE, _SEASON) for mm in [rx.search(raw)] if mm]
    if found:
        _, raw_span = _find_date(raw, today)
        if raw_span:
            marks.append(raw_span[0])
    if marks:
        first = min(marks)
        show = _LEFTOVER.sub(" ", raw[:first])
        show = re.sub(r"\s+", " ", show).strip(" -:|,.")
        if len(re.sub(r"[^a-z0-9]", "", show.lower())) < 2:
            show = ""
    cleaned = _LEFTOVER.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:|,.")
    return {"season": season, "episode": episode, "air_date": air_date, "cleaned": cleaned,
            "show": show}


def _norm(value: str) -> str:
    value = re.sub(r"[^a-z0-9\s]", " ", (value or "").lower())
    return re.sub(r"\s+", " ", value).strip()


def show_key(title: str) -> str:
    """Stable grouping key for a show name ("Anupamaa Episode 12" -> "anupamaa")."""
    info = parse_episode(title or "")
    base = info.get("show") or info["cleaned"]
    base = _QUALITY_JUNK.sub(" ", base)
    base = re.sub(r"\b(19[5-9]\d|20[0-4]\d)\b", " ", base)
    key = _norm(base)
    # "Anupama Anupama's Unexpected Shock" -> leading word repeated by uploaders
    key = re.sub(r"^(\w+(?: \w+)?) \1\b", r"\1", key)
    # Shortcuts / spelling variants of one serial collapse to ONE key, so
    # Follow + alerts + episode list cover every caption style.
    canon = canonical_show(key)
    return (canon or key)[:80]


def display_name(key: str, fallback: str = "") -> str:
    """Nice show name for buttons ("taarak mehta ka ooltah chashmah" -> Title Case)."""
    if key and canonical_show(key) == key:
        return key.title()
    return (fallback or key or "Show").strip()


def episode_label(season, episode) -> str:
    try:
        s, e = int(season or 0), int(episode or 0)
    except (TypeError, ValueError):
        return ""
    if s and e:
        return f"S{s:02d}E{e:02d}"
    if e:
        return f"E{e}"
    if s:
        return f"Season {s}"
    return ""


def pretty_date(iso: str) -> str:
    try:
        return _dt.date.fromisoformat(iso).strftime("%d %b %Y")
    except (TypeError, ValueError):
        return ""


__all__ = ["normalize_separators", "parse_episode", "show_key", "display_name", "episode_label", "pretty_date"]
