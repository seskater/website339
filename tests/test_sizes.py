import pytest

from vinted_finder import finder, sizes
from vinted_finder.vinted import Item, _size_from_details


def test_size_from_details():
    assert _size_from_details("M / 38 / 10 · Très bon état") == "M / 38 / 10"
    assert _size_from_details("EU\xa038 · Bon état") == "EU 38"
    assert _size_from_details("Très bon état") == ""


@pytest.mark.parametrize(
    "tag,wanted,ok",
    [
        ("M / 38 / 10", "38", True),
        ("M / 38 / 10", "m", True),
        ("EU 38", "38", True),
        ("EU\xa038", "FR 38", True),
        ("L", "m", False),
        ("XM", "m", False),
        ("37.5", "37,5", True),
        ("11 ans / 146 cm", "146", True),
        ("", "m", False),
    ],
)
def test_matches(tag, wanted, ok):
    assert sizes.matches(tag, sizes.parse_wanted(wanted)) is ok


def test_from_likes():
    assert sizes.from_likes(["M", "M / 38 / 10", "", "L"])[0] == "m"


class FakeVinted:
    def __init__(self):
        self.calls = []

    def item(self, url):
        return Item(id=1, title="Pull", url=url, size="M")

    def search(self, text, price_from=None, price_to=None):
        self.calls.append((price_from, price_to))
        return [
            Item(id=2, title="Pull laine", url="u2", price="20", size="L"),
            Item(id=3, title="Pull", url="u3", price="15", size="M / 38 / 10"),
            Item(id=4, title="Pull laine cher", url="u4", price="3", size="M"),
        ]


def _find(**kw):
    kw.setdefault("mode", "keywords")
    return finder.find("pull laine", vinted=kw.pop("vinted", FakeVinted()), log=lambda *_: None, **kw)


def test_size_priority_beats_score():
    r = _find(sizes="M")
    assert [i.id for i, _ in r.picks][:2] in ([3, 4], [4, 3])
    assert r.to_dict()["results"][0]["size_match"]


def test_sizes_inferred_from_likes():
    r = _find(liked_urls=["https://www.vinted.fr/items/1"])
    assert r.sizes == ["m"]
    assert r.picks[0][0].size.startswith("M")


def test_min_price_is_sent_and_enforced():
    v = FakeVinted()
    r = _find(min_price=10, max_price=30, vinted=v)
    assert v.calls and all(c == (10, 30) for c in v.calls)
    assert 4 not in [i.id for i, _ in r.picks]  # 3€ listing is under the min


def test_min_above_max_is_rejected():
    with pytest.raises(ValueError):
        _find(min_price=50, max_price=10)


def test_paid_mode_without_key_explains(monkeypatch):
    monkeypatch.setattr(finder, "default_claude", lambda: None)
    with pytest.raises(ValueError, match="isn't set up yet"):
        _find(mode="claude")


def test_size_priority_in_paid_mode():
    import types

    from vinted_finder import ranker

    def parse(**kw):
        if kw["output_format"] is ranker.SearchPlan:
            out = ranker.SearchPlan(taste_profile="t", queries=[ranker.Query(search_text="pull")])
        else:
            assert "Wanted sizes: m" in kw["messages"][0]["content"][0]["text"]
            out = ranker.Ranking(picks=[ranker.Pick(id=2, score=95, reason="r"), ranker.Pick(id=3, score=80, reason="r")])
        return types.SimpleNamespace(stop_reason="end_turn", parsed_output=out)

    claude = types.SimpleNamespace(beta=types.SimpleNamespace(messages=types.SimpleNamespace(parse=parse)))
    r = _find(mode="claude", claude=claude, sizes="M")
    assert r.mode == "claude"
    assert [i.id for i, _ in r.picks] == [3, 2]  # the M listing jumps above the higher-scored L
