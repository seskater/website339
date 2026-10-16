"""Free planning and ranking, used when Claude isn't available.

Searches come from the prompt and liked brands; ranking blends keyword
matches with CLIP photo similarity (see visual.py) when that is installed.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from .ranker import Pick, Query, SearchPlan
from .vinted import Item

# Words that carry no meaning for matching, in the languages Vinted uses most.
_STOP = set(
    """
    a an and any are as at be but by for from i im in is it like looking me my of on or
    please some something that the to under want with without find need size max price
    un une des le la les de du et ou pour avec sans en au aux mon ma mes je cherche veux
    sous moins taille prix style très tres bon etat état neuf
    ein eine der die das und oder für mit ohne ich suche
    el los las y o con sin busco para
    """.split()
)
_PRICE = re.compile(r"(?:under|below|max|moins de|sous|<)\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*(?:€|eur|£|\$)", re.I)


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def tokens(text: str) -> list[str]:
    return [
        t for t in re.findall(r"[a-z0-9]+", _norm(text))
        if t not in _STOP and (len(t) > 1 or t.isdigit())
    ]


def budget(prompt: str) -> float | None:
    m = _PRICE.search(prompt)
    if not m:
        return None
    return float((m.group(1) or m.group(2)).replace(",", "."))


def plan_searches(liked: list[Item], prompt: str) -> SearchPlan:
    price_to = budget(prompt)
    prompt_terms = tokens(_PRICE.sub(" ", prompt))
    brands = Counter(i.brand for i in liked if i.brand)
    liked_terms = Counter(t for i in liked for t in tokens(i.title))
    for b in brands:
        for t in tokens(b):
            liked_terms.pop(t, None)

    queries: list[str] = []
    if prompt_terms:
        queries.append(" ".join(prompt_terms[:5]))
        for brand, _ in brands.most_common(3):
            queries.append(f"{brand} {' '.join(prompt_terms[:3])}")
    else:
        for brand, _ in brands.most_common(3):
            top = [t for t, _ in liked_terms.most_common(2)]
            queries.append(" ".join([brand, *top]))
        if liked_terms:
            queries.append(" ".join(t for t, _ in liked_terms.most_common(3)))
    queries = list(dict.fromkeys(q.strip() for q in queries if q.strip()))[:5]

    bits = []
    if brands:
        bits.append("brands you like: " + ", ".join(b for b, _ in brands.most_common(4)))
    if liked_terms:
        bits.append("recurring words in your likes: " + ", ".join(t for t, _ in liked_terms.most_common(5)))
    if price_to:
        bits.append(f"budget up to {price_to:g}")
    profile = ("Based on " + "; ".join(bits) + ".") if bits else "Based on your request."
    return SearchPlan(
        taste_profile=profile,
        queries=[Query(search_text=q, price_to=price_to) for q in queries],
    )


def rank(
    liked: list[Item],
    prompt: str,
    plan: SearchPlan,
    candidates: list[Item],
    top_n: int = 12,
    visual: dict[int, tuple[float | None, float | None]] | None = None,
) -> list[tuple[Item, Pick]]:
    """Score candidates on keywords, plus CLIP photo similarity when `visual` is given."""
    want = set(tokens(_PRICE.sub(" ", prompt)))
    liked_terms = Counter(t for i in liked for t in tokens(f"{i.title} {i.brand} {i.details}"))
    liked_brands = {_norm(i.brand) for i in liked if i.brand}
    price_to = budget(prompt)
    visual = visual or {}

    scored = []
    for c in candidates:
        terms = set(tokens(f"{c.title} {c.brand} {c.details}"))
        like_img, text_img = visual.get(c.id, (None, None))
        # (weight, value) per signal; signals we can't compute are left out.
        signals = [
            (0.25, len(want & terms) / len(want) if want else None),
            (0.10, sum(min(liked_terms[t], 3) for t in terms) / (3 * max(len(terms), 1)) if liked else None),
            (0.10, (1.0 if c.brand and _norm(c.brand) in liked_brands else 0.0) if liked_brands else None),
            (0.35, like_img),
            (0.20, text_img),
        ]
        present = [(w, v) for w, v in signals if v is not None]
        score = sum(w * v for w, v in present) / sum(w for w, _ in present) if present else 0.0
        try:
            if price_to and float(c.price) > price_to:
                score *= 0.3
        except ValueError:
            pass

        reasons = []
        if like_img is not None and like_img > 0.7:
            reasons.append("looks like items you liked")
        if text_img is not None and text_img > 0.7:
            reasons.append("photo fits your request")
        if want & terms:
            reasons.append("matches " + ", ".join(sorted(want & terms)[:4]))
        if c.brand and _norm(c.brand) in liked_brands:
            reasons.append(f"a brand you liked ({c.brand})")
        scored.append((score, c, "; ".join(reasons) or "related listing"))

    scored.sort(key=lambda s: s[0], reverse=True)
    return [
        (c, Pick(id=c.id, score=round(min(s, 1.0) * 100), reason=r[:1].upper() + r[1:]))
        for s, c, r in scored[:top_n]
        if s > 0
    ]
