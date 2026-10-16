"""The end-to-end pipeline: likes + prompt -> searches -> ranked listings."""

from __future__ import annotations

from dataclasses import dataclass, field

import anthropic

from . import local, ranker, visual
from . import sizes as size_rules
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
    sizes: list[str] = field(default_factory=list)
    min_price: float | None = None

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "sizes": self.sizes,
            "min_price": self.min_price,
            "liked": [i.to_dict() for i in self.liked],
            "taste_profile": self.plan.taste_profile,
            "queries": [q.model_dump() for q in self.plan.queries],
            "candidates_seen": self.candidates_seen,
            "warnings": self.warnings,
            "results": [
                {
                    **item.to_dict(),
                    "score": pick.score,
                    "reason": pick.reason,
                    "size_match": size_rules.matches(item.size, self.sizes),
                }
                for item, pick in self.picks
            ],
        }


MODES = ("claude", "visual", "keywords")


def available_modes() -> dict[str, bool]:
    return {"claude": default_claude() is not None, "visual": visual.available(), "keywords": True}


def default_mode() -> str:
    # Free photo matching is the default; paid (Claude API) is opt-in.
    return "visual" if visual.available() else "keywords"


def find(
    prompt: str,
    liked_urls: list[str] | None = None,
    *,
    cookie: str | None = None,
    domain: str = "www.vinted.fr",
    min_price: float | None = None,
    max_price: float | None = None,
    sizes: str = "",
    mode: str | None = None,
    top_n: int = 12,
    effort: str = "medium",
    claude: anthropic.Anthropic | None = None,
    vinted: VintedClient | None = None,
    log=print,
) -> FindResult:
    """Find listings. `mode` is "claude" (paid, Claude API), "visual" (free, photos)
    or "keywords" (free, tags/words); None picks the default free mode."""
    mode = mode or default_mode()
    if mode not in MODES:
        raise ValueError(f"Unknown mode: {mode}")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ValueError("Min price is higher than max price.")
    warnings: list[str] = []
    free_mode = "visual" if visual.available() else "keywords"
    if mode == "claude":
        claude = claude or default_claude()
        if claude is None:
            raise ValueError(
                "Paid mode (Claude API) isn't set up yet: add ANTHROPIC_API_KEY to .env and restart."
            )
    else:
        claude = None
        if mode == "visual" and not visual.available():
            warnings.append("Free photo matching isn't installed here: used free tag matching.")
            mode = "keywords"
        free_mode = mode
    vinted = vinted or VintedClient(domain=domain, cookie=cookie)

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

    wanted_sizes = size_rules.parse_wanted(sizes)
    sizes_note = "your sizes"
    if not wanted_sizes:
        wanted_sizes = size_rules.from_likes([i.size for i in liked])
        sizes_note = "sizes from your likes"
    if wanted_sizes:
        log(f"Size priority ({sizes_note}): {', '.join(wanted_sizes)}")

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
        if min_price is not None and q.price_to is not None and q.price_to < min_price:
            q.price_to = max_price  # the prompt's budget conflicts with the min price
    log("Searches: " + "; ".join(q.search_text for q in plan.queries))

    def run(q: ranker.Query) -> list[Item]:
        try:
            return vinted.search(q.search_text, price_from=min_price, price_to=q.price_to)
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
    pool_list = [c for c in candidates.values() if _in_range(c.price, min_price, max_price)]
    pool_list = pool_list[:MAX_CANDIDATES]
    log(f"Ranking {len(pool_list)} listings...")

    picks = None
    if claude:
        try:
            picks = ranker.rank(
                claude, liked, prompt, plan, pool_list,
                top_n=top_n, effort=effort, sizes=wanted_sizes,
            )
        except anthropic.APIError as e:
            claude_failed(e)
    result_mode = "claude"
    if picks is None:
        result_mode, scores = free_mode, None
        if free_mode == "visual":
            log("Comparing photos...")
            scores = visual.scores(
                [i.image for i in liked if i.image],
                prompt,
                {c.id: c.image for c in pool_list if c.image},
            )
        # Rank everything so size priority can pull matching sizes up from further down.
        picks = local.rank(liked, prompt, plan, pool_list, top_n=len(pool_list), visual=scores)

    if wanted_sizes:
        # Size priority: listings tagged with a wanted size come first, best-scored first.
        picks.sort(key=lambda p: not size_rules.matches(p[0].size, wanted_sizes))
        n_match = sum(size_rules.matches(i.size, wanted_sizes) for i, _ in picks[:top_n])
        if n_match < min(top_n, len(picks)):
            warnings.append(
                f"Only {n_match} of the results are in {sizes_note} ({', '.join(wanted_sizes)})."
            )
    return FindResult(
        liked, plan, picks[:top_n], len(candidates), warnings, result_mode, wanted_sizes, min_price
    )


def _in_range(price: str, lo: float | None, hi: float | None) -> bool:
    try:
        p = float(price)
    except ValueError:
        return True
    return (lo is None or p >= lo) and (hi is None or p <= hi)


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
