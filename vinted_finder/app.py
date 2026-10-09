"""Web UI: `uvicorn vinted_finder.app:app` then open http://localhost:8000."""

from __future__ import annotations

from pathlib import Path

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from .finder import find
from .vinted import VintedError

app = FastAPI(title="Vinted Finder")
STATIC = Path(__file__).parent / "static"


class FindRequest(BaseModel):
    prompt: str = ""
    liked_urls: list[str] = []
    cookie: str | None = None
    domain: str = "www.vinted.fr"
    max_price: float | None = None
    top_n: int = 12


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/api/find")
async def api_find(req: FindRequest):
    try:
        result = await run_in_threadpool(
            find,
            req.prompt,
            req.liked_urls,
            cookie=req.cookie or None,
            domain=req.domain,
            max_price=req.max_price,
            top_n=max(1, min(req.top_n, 40)),
            log=lambda *_: None,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except VintedError as e:
        raise HTTPException(502, f"Vinted: {e}")
    except anthropic.AuthenticationError:
        raise HTTPException(500, "Set ANTHROPIC_API_KEY before starting the server.")
    except anthropic.APIError as e:
        raise HTTPException(502, f"Claude API error: {e}")
    return result.to_dict()
