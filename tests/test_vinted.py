import json

from vinted_finder.vinted import _user_id_from_cookie, parse_catalog, parse_item_page


def _page(payload: str) -> str:
    return f"<script>self.__next_f.push([1,{json.dumps(payload)}])</script>"


def test_parse_catalog():
    item = {
        "id": 42,
        "title": "Levi's 501",
        "url": "/items/42-levis-501",
        "price": {"amount": "24.90", "currencyCode": "EUR"},
        "thumbnailUrl": "https://img/x.webp",
        "favouriteCount": 3,
        "itemBox": {"firstLine": "Levi's", "secondLine": "L · Très bon état", "badge": "$undefined"},
    }
    flight = '5:["$","div",null,{"productItem":' + json.dumps(item) + "}]"
    # Split across two chunks, as Next.js does.
    html = _page(flight[:30]) + _page(flight[30:])
    [parsed] = parse_catalog(html, "https://www.vinted.fr")
    assert parsed.id == 42
    assert parsed.url == "https://www.vinted.fr/items/42-levis-501"
    assert parsed.price == "24.90" and parsed.currency == "EUR"
    assert parsed.brand == "Levi's" and parsed.details == "L · Très bon état"


def test_parse_item_page():
    html = (
        '<meta property="og:title" content="Wool coat | Vinted">'
        '<meta property="og:description" content="Warm &amp; soft">'
        '<meta property="og:image" content="https://img/c.jpg">'
        + _page('{"brand_dto":{"id":"1","title":"COS"}}')
    )
    item = parse_item_page(html, "https://www.vinted.fr/items/7-wool-coat?referrer=catalog")
    assert (item.id, item.title, item.brand, item.description) == (7, "Wool coat", "COS", "Warm & soft")
    assert item.url == "https://www.vinted.fr/items/7-wool-coat"


def test_user_id_from_cookie():
    import base64

    body = base64.urlsafe_b64encode(json.dumps({"sub": 123}).encode()).decode().rstrip("=")
    assert _user_id_from_cookie(f"foo=1; access_token_web=h.{body}.s; x=2") == "123"
    assert _user_id_from_cookie("foo=1") is None
