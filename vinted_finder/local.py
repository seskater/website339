"""Keyword-based planning and ranking, used when no Anthropic API key is set.

Much rougher than the Claude ranking (no photos, no understanding of style),
but it lets the app run end to end without any credentials.
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
    profile = ("Keyword match (no Claude API key set): " + "; ".join(bits) + ".") if bits else (
        "Keyword match (no Claude API key set)."
    )
    return SearchPlan(
        taste_profile=profile,
        queries=[Query(search_text=q, price_to=price_to) for q in queries],
    )


def rank(
    liked: list[Item], prompt: str, plan: SearchPlan, candidates: list[Item], top_n: int = 12
) -> list[tuple[Item, Pick]]:
    want = set(tokens(_PRICE.sub(" ", prompt)))
    liked_terms = Counter(t for i in liked for t in tokens(f"{i.title} {i.brand} {i.details}"))
    liked_brands = {_norm(i.brand) for i in liked if i.brand}
    price_to = budget(prompt)

    scored = []
    for c in candidates:
        terms = set(tokens(f"{c.title} {c.brand} {c.details}"))
        prompt_hits = len(want & terms) / len(want) if want else 0.0
        taste_hits = sum(min(liked_terms[t], 3) for t in terms) / (3 * max(len(terms), 1))
        brand_hit = 1.0 if c.brand and _norm(c.brand) in liked_brands else 0.0
        score = (0.6 if want else 0.0) * prompt_hits + 0.25 * taste_hits + 0.15 * brand_hit
        if not want:
            score = score / 0.4
        try:
            if price_to and float(c.price) > price_to:
                score *= 0.3
        except ValueError:
            pass
        reasons = []
        if want & terms:
            reasons.append("matches " + ", ".join(sorted(want & terms)[:4]))
        if brand_hit:
            reasons.append(f"a brand you liked ({c.brand})")
        if taste_hits > 0.2:
            reasons.append("similar to your likes")
        scored.append((score, c, "; ".join(reasons) or "related listing"))

    scored.sort(key=lambda s: s[0], reverse=True)
    return [
        (c, Pick(id=c.id, score=round(min(s, 1.0) * 100), reason=r.capitalize()))
        for s, c, r in scored[:top_n]
        if s > 0
    ]
