"""Uses Claude to turn liked items + a prompt into searches, then rank results."""

from __future__ import annotations

import os

import anthropic
from pydantic import BaseModel, Field

from .vinted import Item

# Haiku keeps a search under a cent; set VINTED_FINDER_MODEL=claude-opus-5-5
# for the most careful ranking (~$0.20-0.50 per search).
MODEL = os.environ.get("VINTED_FINDER_MODEL", "claude-haiku-5-5")
MAX_LIKED_IMAGES = 20


class Query(BaseModel):
    search_text: str = Field(description="Short Vinted search string, 2-5 words")
    price_to: float | None = Field(
        default=None, description="Max price if the user implied a budget"
    )


class SearchPlan(BaseModel):
    taste_profile: str = Field(
        description="2-4 sentences on the user's style, brands, sizes, colours, price range"
    )
    queries: list[Query] = Field(description="3-6 diverse searches to run on Vinted")


class Pick(BaseModel):
    id: int
    score: int = Field(description="0-100 match score")
    reason: str = Field(description="One short sentence on why it fits")


class Ranking(BaseModel):
    picks: list[Pick]


def _call(client: anthropic.Anthropic, content, output_format, effort: str):
    extra = {}
    if not MODEL.startswith("claude-haiku"):
        # Re-runs a declined request on another model. Haiku has no server-side fallback.
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        messages=[{"role": "user", "content": content}],
        output_format=output_format,
        **extra,
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise RuntimeError(f"Claude returned no result (stop_reason={response.stop_reason})")
    return response.parsed_output


def plan_searches(
    client: anthropic.Anthropic, liked: list[Item], prompt: str, effort: str = "medium"
) -> SearchPlan:
    content: list[dict] = []
    for item in liked[:MAX_LIKED_IMAGES]:
        if item.image:
            content.append({"type": "image", "source": {"type": "url", "url": item.image}})
    liked_text = "\n".join(i.summary() for i in liked) or "(no liked items given)"
    content.append(
        {
            "type": "text",
            "text": (
                "You help someone shop on Vinted, a second-hand clothing marketplace.\n\n"
                f"Items they liked (the photos above are the first {min(len(liked), MAX_LIKED_IMAGES)} of these):\n"
                f"{liked_text}\n\n"
                f"What they're looking for now:\n{prompt or '(nothing specific: more things like their likes)'}\n\n"
                "Describe their taste, then write the Vinted searches most likely to surface "
                "items they'd want. The request takes priority; use the likes to infer style, "
                "brands, sizes and budget. Write searches in the language people list items "
                "in on this Vinted site, and keep them short: Vinted search is keyword-based."
            ),
        }
    )
    return _call(client, content, SearchPlan, effort)


def rank(
    client: anthropic.Anthropic,
    liked: list[Item],
    prompt: str,
    plan: SearchPlan,
    candidates: list[Item],
    top_n: int = 12,
    effort: str = "medium",
) -> list[tuple[Item, Pick]]:
    if not candidates:
        return []
    by_id = {c.id: c for c in candidates}
    text = (
        "Pick the Vinted listings that best match this shopper.\n\n"
        f"Request: {prompt or '(more things like their likes)'}\n"
        f"Taste profile: {plan.taste_profile}\n\n"
        "Liked items:\n" + ("\n".join(i.summary() for i in liked) or "(none)") + "\n\n"
        "Candidate listings:\n" + "\n".join(c.summary() for c in candidates) + "\n\n"
        f"Return up to {top_n} picks, best first, using the ids in square brackets. "
        "Weigh fit to the request first, then fit to their taste, then value for money. "
        "Skip anything that clearly misses the request (wrong item type, size or budget)."
    )
    ranking: Ranking = _call(client, [{"type": "text", "text": text}], Ranking, effort)
    results = []
    seen = set()
    for pick in sorted(ranking.picks, key=lambda p: p.score, reverse=True):
        if pick.id in by_id and pick.id not in seen:
            seen.add(pick.id)
            results.append((by_id[pick.id], pick))
    return results[:top_n]
