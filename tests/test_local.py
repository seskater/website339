import pytest

from vinted_finder import local
from vinted_finder.vinted import Item, VintedClient, VintedError


def _item(i, title, brand="", price="10"):
    return Item(id=i, title=title, url=f"https://www.vinted.fr/items/{i}", brand=brand, price=price, currency="EUR")


def test_budget():
    assert local.budget("leather jacket under 60") == 60
    assert local.budget("veste cuir 45€") == 45
    assert local.budget("veste cuir") is None


def test_plan_uses_prompt_and_brands():
    liked = [_item(1, "Levi's 501 baggy", "Levi's"), _item(2, "Levi's 550 vintage", "Levi's")]
    plan = local.plan_searches(liked, "baggy jeans under 30€")
    texts = [q.search_text for q in plan.queries]
    assert texts[0] == "baggy jeans"
    assert any(t.startswith("Levi's") for t in texts)
    assert all(q.price_to == 30 for q in plan.queries)


def test_rank_prefers_matches_within_budget():
    liked = [_item(1, "Levi's 501", "Levi's")]
    cands = [
        _item(10, "Robe fleurie", "Zara"),
        _item(11, "Levi's 501 baggy jeans", "Levi's", "20"),
        _item(12, "Baggy jeans", "H&M", "80"),
    ]
    plan = local.plan_searches(liked, "baggy jeans under 30")
    picks = local.rank(liked, "baggy jeans under 30", plan, cands)
    assert picks[0][0].id == 11
    assert 10 not in [i.id for i, _ in picks]


def test_client_rejects_non_vinted_hosts():
    with pytest.raises(VintedError):
        VintedClient("evil.example.com")
    c = VintedClient("vinted.co.uk")
    with pytest.raises(VintedError):
        c._get("https://evil.example.com/x")
