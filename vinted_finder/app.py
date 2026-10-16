"""Web UI: `uvicorn vinted_finder.app:app` then open http://localhost:8000."""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import anthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import visual
from .finder import MODES, available_modes, default_mode, find
from .vinted import VintedError

STATIC = Path(__file__).parent / "static"
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "20"))
USAGE_FILE = Path(os.environ.get("USAGE_FILE", Path(__file__).parent.parent / ".usage.json"))
# Searches hit Vinted and the CPU hard; run a couple at a time, queue the rest.
_searches = threading.BoundedSemaphore(int(os.environ.get("MAX_PARALLEL_SEARCHES", "2")))


class Usage:
    """Searches per visitor per day, saved to disk so restarts don't reset it."""

    def __init__(self, path: Path, limit: int):
        self.path, self.limit = path, limit
        self.lock = threading.Lock()
        try:
            self.data = json.loads(path.read_text())
        except (OSError, ValueError):
            self.data = {}

    def _today(self) -> dict:
        day = dt.date.today().isoformat()
        if self.data.get("day") != day:
            self.data = {"day": day, "counts": {}}
        return self.data["counts"]

    def remaining(self, visitor: str) -> int:
        with self.lock:
            return max(0, self.limit - self._today().get(visitor, 0))

    def take(self, visitor: str) -> bool:
        with self.lock:
            counts = self._today()
            if counts.get(visitor, 0) >= self.limit:
                return False
            counts[visitor] = counts.get(visitor, 0) + 1
            self._save()
            return True

    def refund(self, visitor: str):
        with self.lock:
            counts = self._today()
            counts[visitor] = max(0, counts.get(visitor, 0) - 1)
            self._save()

    def _save(self):
        try:
            self.path.write_text(json.dumps(self.data))
        except OSError:
            pass


usage = Usage(USAGE_FILE, DAILY_LIMIT)


def visitor_id(request: Request) -> str:
    # Behind a Cloudflare tunnel every request arrives from localhost; Cloudflare
    # puts the real address in CF-Connecting-IP. Other hosts (e.g. Hugging Face)
    # append it to X-Forwarded-For, so the last entry is the trustworthy one.
    if ip := request.headers.get("cf-connecting-ip"):
        return ip.strip()
    if fwd := request.headers.get("x-forwarded-for"):
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


@asynccontextmanager
async def lifespan(_app):
    # Load the free image model in the background so the first search is quick.
    threading.Thread(target=visual.warm_up, daemon=True).start()
    yield


app = FastAPI(title="Vinted Finder", lifespan=lifespan)


class FindRequest(BaseModel):
    prompt: str = ""
    liked_urls: list[str] = []
    cookie: str | None = None
    domain: str = "www.vinted.fr"
    min_price: float | None = None
    max_price: float | None = None
    sizes: str = ""
    mode: str | None = None  # "claude" (paid, Claude API), "visual" or "keywords" (free)
    top_n: int = 12


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health(request: Request):
    return {
        "ok": True,
        "mode": default_mode(),
        "modes": available_modes(),
        "daily_limit": DAILY_LIMIT,
        "remaining": usage.remaining(visitor_id(request)),
    }


@app.post("/api/find")
async def api_find(req: FindRequest, request: Request):
    if req.mode is not None and req.mode not in MODES:
        raise HTTPException(400, f"Unknown mode: {req.mode}")
    visitor = visitor_id(request)
    if not usage.take(visitor):
        raise HTTPException(
            429, f"You've used all {DAILY_LIMIT} searches for today. Come back tomorrow!"
        )

    def run():
        with _searches:
            return find(
                req.prompt,
                req.liked_urls[:50],
                cookie=req.cookie or None,
                domain=req.domain,
                min_price=req.min_price,
                max_price=req.max_price,
                sizes=req.sizes[:100],
                mode=req.mode,
                top_n=max(1, min(req.top_n, 40)),
                log=lambda *_: None,
            )

    try:
        result = await run_in_threadpool(run)
    except ValueError as e:
        usage.refund(visitor)
        raise HTTPException(400, str(e))
    except VintedError as e:
        usage.refund(visitor)
        if str(e).startswith("Not a Vinted site"):
            raise HTTPException(400, str(e))
        raise HTTPException(502, f"Vinted: {e}")
    except anthropic.APIError as e:
        usage.refund(visitor)
        raise HTTPException(502, f"Claude API error: {e}")
    return {**result.to_dict(), "remaining": usage.remaining(visitor), "daily_limit": DAILY_LIMIT}
