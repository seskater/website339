"""The end-to-end pipeline: likes + prompt -> searches -> ranked listings."""

from __future__ import annotations

from dataclasses import dataclass

import anthropic

from . import local, ranker, visual
from .vinted import Item, VintedClient, VintedError

MAX_CANDIDATES = 250
_LABEL = {"visual": "photo", "keywords": "keyword"}


@dataclass
class FindResult:
    liked: list[Item]
    plan: ranker.SearchPlan
    picks: list[tuple[Item, ranker.Pick]]
    candidates_seen: int
    warnings: list[str]
    mode: str = "claude"

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
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
    if claude is None:
        claude = default_claude()
    warnings: list[str] = []
    free_mode = "visual" if visual.available() else "keywords"
    if claude is None:
        warnings.append(f"No ANTHROPIC_API_KEY set: using free {_LABEL[free_mode]} matching.")

    def claude_failed(e: anthropic.APIError):
        nonlocal claude
        claude = None
        warnings.append(
            f"Claude unavailable ({_api_error(e)}): fell back to free {_LABEL[free_mode]} matching."
        )

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

    plan = None
    if claude:
        log("Asking Claude what to search for...")
        try:
            plan = ranker.plan_searches(claude, liked, prompt, effort=effort)
        except anthropic.APIError as e:
            claude_failed(e)
    if plan is None:
        plan = local.plan_searches(liked, prompt)
    if not plan.queries:
        raise ValueError("Couldn't work out what to search for. Add a prompt.")
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

    picks = None
    if claude:
        try:
            picks = ranker.rank(claude, liked, prompt, plan, pool_list, top_n=top_n, effort=effort)
        except anthropic.APIError as e:
            claude_failed(e)
    mode = "claude"
    if picks is None:
        mode, scores = free_mode, None
        if free_mode == "visual":
            log("Comparing photos...")
            scores = visual.scores(
                [i.image for i in liked if i.image],
                prompt,
                {c.id: c.image for c in pool_list if c.image},
            )
        picks = local.rank(liked, prompt, plan, pool_list, top_n=top_n, visual=scores)
    return FindResult(liked, plan, picks, len(candidates), warnings, mode)


def _api_error(e: anthropic.APIError) -> str:
    if isinstance(e, anthropic.AuthenticationError):
        return "API key rejected"
    if isinstance(e, anthropic.RateLimitError):
        return "rate limited"
    if isinstance(e, anthropic.APIStatusError):
        msg = str(e.message) if e.message else ""
        if "credit" in msg.lower() or "billing" in msg.lower():
            return "out of API credit"
        return f"HTTP {e.status_code}"
    return "connection problem"


def default_claude() -> anthropic.Anthropic | None:
    """A Claude client if credentials are configured, else None."""
    client = anthropic.Anthropic()
    if client.api_key or client.auth_token or getattr(client, "credentials", None):
        return client
    return None


def _min(a: float | None, b: float | None) -> float | None:
    vals = [v for v in (a, b) if v is not None]
    return min(vals) if vals else None
