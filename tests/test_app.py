import types

import anthropic
import httpx

from vinted_finder import app as appmod
from vinted_finder import finder
from vinted_finder.vinted import Item


def test_usage_limit_and_refund(tmp_path):
    u = appmod.Usage(tmp_path / "u.json", limit=2)
    assert u.take("a") and u.take("a")
    assert not u.take("a")
    assert u.take("b")
    u.refund("a")
    assert u.remaining("a") == 1
    # Survives a restart.
    assert appmod.Usage(tmp_path / "u.json", limit=2).remaining("a") == 1


def test_visitor_id_prefers_cloudflare_header():
    req = types.SimpleNamespace(
        headers={"cf-connecting-ip": "1.2.3.4", "x-forwarded-for": "9.9.9.9"},
        client=types.SimpleNamespace(host="127.0.0.1"),
    )
    assert appmod.visitor_id(req) == "1.2.3.4"
    req.headers = {"x-forwarded-for": "6.6.6.6, 5.5.5.5"}
    assert appmod.visitor_id(req) == "5.5.5.5"


class FakeVinted:
    def item(self, url):
        return Item(id=1, title="Levi's 501", url=url, brand="Levi's")

    def search(self, text, price_to=None):
        return [
            Item(id=2, title="Levi's 501 baggy", url="u2", brand="Levi's", price="20"),
            Item(id=3, title="Robe", url="u3", brand="Zara", price="5"),
        ]


def test_falls_back_to_free_mode_when_claude_fails(monkeypatch):
    monkeypatch.setattr(finder.visual, "available", lambda: False)
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.BadRequestError(
        "Your credit balance is too low", response=httpx.Response(400, request=req), body=None
    )

    def parse(**_):
        raise err

    claude = types.SimpleNamespace(beta=types.SimpleNamespace(messages=types.SimpleNamespace(parse=parse)))
    r = finder.find("baggy levis", ["https://www.vinted.fr/items/1"], claude=claude, vinted=FakeVinted(), log=lambda *_: None)
    assert r.mode == "keywords"
    assert r.picks[0][0].id == 2
    assert any("out of API credit" in w for w in r.warnings)
