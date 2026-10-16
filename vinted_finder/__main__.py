"""CLI: python -m vinted_finder "a warm winter coat under 60€" --liked URL ..."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .finder import find


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="vinted_finder", description="Find Vinted items matching your likes and a prompt."
    )
    p.add_argument("prompt", nargs="?", default="", help="What you're looking for")
    p.add_argument("--liked", nargs="*", default=[], help="URLs of items you liked")
    p.add_argument("--liked-file", help="Text file with one liked item URL per line")
    p.add_argument(
        "--cookie",
        default=os.environ.get("VINTED_COOKIE"),
        help="Your Vinted browser cookie, to import all your likes (or set VINTED_COOKIE)",
    )
    p.add_argument("--domain", default="www.vinted.fr", help="e.g. www.vinted.co.uk")
    p.add_argument("--min-price", type=float)
    p.add_argument("--max-price", type=float)
    p.add_argument("--size", default="", help='Sizes to show first, e.g. "M, 38"')
    p.add_argument(
        "--mode",
        choices=["claude", "visual", "keywords"],
        help="claude = paid (Claude API), visual = free photo matching, keywords = free tag matching",
    )
    p.add_argument("--top", type=int, default=12)
    p.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--json", action="store_true", help="Print raw JSON")
    args = p.parse_args(argv)

    liked = list(args.liked)
    if args.liked_file:
        with open(args.liked_file) as f:
            liked += [line.strip() for line in f if line.strip()]

    log = (lambda *_: None) if args.json else (lambda m: print(m, file=sys.stderr))
    result = find(
        args.prompt,
        liked,
        cookie=args.cookie,
        domain=args.domain,
        min_price=args.min_price,
        max_price=args.max_price,
        sizes=args.size,
        mode=args.mode,
        top_n=args.top,
        effort=args.effort,
        log=log,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 0

    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)
    print(f"\nYour taste: {result.plan.taste_profile}\n")
    for n, (item, pick) in enumerate(result.picks, 1):
        print(f"{n:>2}. [{pick.score}] {item.title} — {item.price} {item.currency}")
        if item.brand or item.details:
            print(f"    {' · '.join(x for x in (item.brand, item.details) if x)}")
        print(f"    {pick.reason}")
        print(f"    {item.url}")
    if not result.picks:
        print("No good matches found. Try a broader prompt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
