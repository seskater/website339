"""The end-to-end pipeline: likes + prompt -> searches -> ranked listings."""

from __future__ import annotations

from dataclasses import dataclass

import anthropic

from . import ranker
from .vinted import Item, VintedClient, VintedError

MAX_CANDIDATES = 250


@dataclass
class FindResult:
    liked: list[Item]
    plan: ranker.SearchPlan
    picks: list[tuple[Item, ranker.Pick]]
    candidates_seen: int
    warnings: list[str]

    def to_dict(self) -> dict:
        return {
            "liked": [i.to_dict() for i in self.liked],
            "taste_profile": self.plan.taste_profile,
            "queries": [q.model_dump() for q in self.plan.queries],
            "candidates_seen": self.candidates_seen,
            "warnings": self.warnings,
            "results": [
                {**item.to_dict(), "score": pick.score, "reason": pick.reason}
                for item, pick in self.picks
            ],
        }


def find(
    prompt: str,
    liked_urls: list[str] | None = None,
    *,
    cookie: str | None = None,
    domain: str = "www.vinted.fr",
    max_price: float | None = None,
    top_n: int = 12,
    effort: str = "medium",
    claude: anthropic.Anthropic | None = None,
    vinted: VintedClient | None = None,
    log=print,
) -> FindResult:
    vinted = vinted or VintedClient(domain=domain, cookie=cookie)
    claude = claude or anthropic.Anthropic()
    warnings: list[str] = []

    liked: list[Item] = []
    if cookie:
        log("Importing your Vinted likes...")
        try:
            liked.extend(vinted.favourites())
        except VintedError as e:
            warnings.append(str(e))
    for url in liked_urls or []:
        url = url.strip()
        if not url:
            continue
        try:
            liked.append(vinted.item(url))
        except VintedError as e:
            warnings.append(f"Skipped {url}: {e}")
    liked = list({i.id: i for i in liked}.values())
    if not liked and not prompt.strip():
        raise ValueError("Give at least a prompt or some liked items.")
    log(f"Using {len(liked)} liked item(s).")

    log("Asking Claude what to search for...")
    plan = ranker.plan_searches(claude, liked, prompt, effort=effort)
    for q in plan.queries:
        q.price_to = _min(q.price_to, max_price)
    log("Searches: " + "; ".join(q.search_text for q in plan.queries))

    def run(q: ranker.Query) -> list[Item]:
        try:
            return vinted.search(q.search_text, price_to=q.price_to)
        except VintedError as e:
            warnings.append(f"Search '{q.search_text}' failed: {e}")
            return []

    batches = [run(q) for q in plan.queries]

    liked_ids = {i.id for i in liked}
    candidates: dict[int, Item] = {}
    # Interleave batches so every query is represented if we hit the cap.
    for rank_pos in range(max((len(b) for b in batches), default=0)):
        for batch in batches:
            if rank_pos < len(batch) and batch[rank_pos].id not in liked_ids:
                candidates.setdefault(batch[rank_pos].id, batch[rank_pos])
    pool_list = list(candidates.values())[:MAX_CANDIDATES]
    log(f"Ranking {len(pool_list)} listings...")

    picks = ranker.rank(claude, liked, prompt, plan, pool_list, top_n=top_n, effort=effort)
    return FindResult(liked, plan, picks, len(candidates), warnings)


def _min(a: float | None, b: float | None) -> float | None:
    vals = [v for v in (a, b) if v is not None]
    return min(vals) if vals else None
