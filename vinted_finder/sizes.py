"""Matching the sizes you want against Vinted size tags.

Vinted tags look like "M", "M / 38 / 10", "EU 38", "38" (shoes) or
"11 ans / 146 cm" (kids). A wanted size matches when it equals one of the
tag's parts, ignoring case and prefixes like "EU"/"FR", so "38" matches
"EU 38" and "M / 38 / 10", and "M" matches "M / 38 / 10" but not "XM".
"""

from __future__ import annotations

import re
from collections import Counter

_PREFIX = re.compile(r"^(?:eu|fr|it|uk|us|de|es|taille|size|t)\s*(?=\d)", re.I)
_SUFFIX = re.compile(r"\s*cm$", re.I)


def _norm(part: str) -> str:
    part = " ".join(part.replace("\xa0", " ").lower().split())
    part = _SUFFIX.sub("", _PREFIX.sub("", part))
    return part.replace(",", ".")


def tag_parts(tag: str) -> set[str]:
    return {_norm(p) for p in re.split(r"[/|]", tag or "") if _norm(p)}


def parse_wanted(text: str) -> list[str]:
    """ "M, 38 / W30" -> ["m", "38", "w30"]. A comma between digits is a decimal ("37,5")."""
    return [_norm(p) for p in re.split(r"[;/|]+|,(?!\d)|(?<!\d),", text or "") if _norm(p)]


def matches(tag: str, wanted: list[str]) -> bool:
    return bool(wanted) and bool(tag_parts(tag) & set(wanted))


def from_likes(sizes: list[str]) -> list[str]:
    """Sizes worth prioritising when you didn't type one: what your likes are in."""
    counts = Counter(p for tag in sizes if tag for p in tag_parts(tag))
    return [s for s, _ in counts.most_common(4)]
