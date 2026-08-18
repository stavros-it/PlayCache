"""Shared text helpers: HTML stripping, description truncation, ratings, fuzzy match."""
from __future__ import annotations

import html
import math
import re
from collections.abc import Iterable
from difflib import SequenceMatcher

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = _TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def truncate(text: str, max_chars: int = 320) -> str:
    text = (text or "").strip()
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last_space = cut.rfind(" ")
    if last_space > max_chars * 0.6:
        cut = cut[:last_space]
    return cut.rstrip(" ,.;:-") + "…"


def clean_search_query(name: str) -> str:
    """Light extra cleaning for the API query string (e.g. trim trailing edition)."""
    q = strip_html(name)
    q = re.sub(r"\s*[:]\s*.*$", "", q)
    q = re.sub(r"\s+[-–—]\s+.*$", "", q)
    return _WS_RE.sub(" ", q).strip()


def similarity(a: str, b: str) -> float:
    """Return a 0-100 fuzzy similarity score between two names."""
    a = (a or "").lower().strip()
    b = (b or "").lower().strip()
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio() * 100.0


def best_match(
    query: str,
    candidates: Iterable[tuple[str, object]],
    threshold: float = 60.0,
) -> object | None:
    """Pick the candidate whose name best matches ``query``."""
    best: object | None = None
    best_score = threshold
    q_lower = query.lower()
    for name, cand in candidates:
        score = similarity(query, name)
        if q_lower in name.lower() and len(q_lower) >= 3:
            score = max(score, 90.0)
        if score > best_score:
            best_score = score
            best = cand
    return best


def format_rating(out_of_10: float | None) -> str:
    """Format a 0-10 numeric rating as '9/10' or '8.5/10'. Empty if unavailable."""
    if out_of_10 is None:
        return ""
    try:
        val = float(out_of_10)
    except (TypeError, ValueError):
        return ""
    if math.isnan(val) or math.isinf(val) or val <= 0 or val > 10:
        return ""
    formatted = f"{val:.1f}".rstrip("0").rstrip(".")
    return f"{formatted}/10"


def join_names(items: Iterable[dict] | None, key: str = "name", sep: str = " / ") -> str:
    """Join a list of dicts (e.g. genres) on a key, e.g. 'Action / RPG'."""
    if not items:
        return ""
    names = [str(i.get(key, "")).strip() for i in items if i.get(key)]
    return sep.join(n for n in names if n)
