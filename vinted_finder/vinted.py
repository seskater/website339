"""Minimal Vinted client.

Vinted has no public API, and its old JSON search endpoint
(/api/v2/catalog/items) now returns 404. The catalog and item pages are
server-rendered with Next.js, so we read item data out of the React Server
Components payload (the `self.__next_f.push(...)` script chunks) instead.
"""

from __future__ import annotations

import base64
import html as html_lib
import json
import re
from dataclasses import asdict, dataclass, field

from curl_cffi import requests

_FLIGHT_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
_ITEM_ID = re.compile(r"/items/(\d+)")


class VintedError(RuntimeError):
    pass


@dataclass
class Item:
    id: int
    title: str
    url: str
    price: str = ""
    currency: str = ""
    brand: str = ""
    details: str = ""  # e.g. "L · Très bon état"
    description: str = ""
    image: str = ""
    favourites: int = 0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        """One compact line for prompting."""
        parts = [f"[{self.id}] {self.title}"]
        if self.brand:
            parts.append(f"brand: {self.brand}")
        if self.details:
            parts.append(self.details)
        if self.price:
            parts.append(f"{self.price} {self.currency}".strip())
        if self.description:
            parts.append("desc: " + " ".join(self.description.split())[:300])
        return " | ".join(parts)


def flight_payload(page_html: str) -> str:
    """Concatenate the decoded RSC flight chunks of a Next.js page."""
    return "".join(json.loads(c) for c in _FLIGHT_CHUNK.findall(page_html))


def _json_objects_after(text: str, key: str):
    decoder = json.JSONDecoder()
    for m in re.finditer(re.escape(f'"{key}":'), text):
        try:
            obj, _ = decoder.raw_decode(text, m.end())
        except ValueError:
            continue
        if isinstance(obj, dict):
            yield obj


def parse_catalog(page_html: str, base_url: str) -> list[Item]:
    """Extract the item grid from a catalog/search or favourites page."""
    items: dict[int, Item] = {}
    for obj in _json_objects_after(flight_payload(page_html), "productItem"):
        if "id" not in obj or "title" not in obj:
            continue
        price = obj.get("price") or {}
        box = obj.get("itemBox") or {}
        items[obj["id"]] = Item(
            id=int(obj["id"]),
            title=obj["title"],
            url=base_url + obj.get("url", f"/items/{obj['id']}"),
            price=str(price.get("amount", "")),
            currency=price.get("currencyCode", ""),
            brand=_clean(box.get("firstLine")),
            details=_clean(box.get("secondLine")),
            image=obj.get("thumbnailUrl") or "",
            favourites=int(obj.get("favouriteCount") or 0),
        )
    return list(items.values())


def parse_item_page(page_html: str, url: str) -> Item:
    """Extract a single item from its product page."""
    m = _ITEM_ID.search(url)
    if not m:
        raise VintedError(f"Not a Vinted item URL: {url}")
    item_id = int(m.group(1))

    def meta(prop: str) -> str:
        mm = re.search(
            rf'<meta (?:property|name)="{re.escape(prop)}" content="([^"]*)"', page_html
        )
        return html_lib.unescape(mm.group(1)) if mm else ""

    flight = flight_payload(page_html)
    brand = ""
    for obj in _json_objects_after(flight, "brand_dto"):
        brand = obj.get("title", "")
        break
    price: dict = {}
    for obj in _json_objects_after(flight, "price"):
        if "amount" in obj:
            price = obj
            break
    # Size, condition and colour are listed as {"code": ..., "data": {"value": ...}}.
    attrs = dict(
        re.findall(r'"code":"(size|status|color)","data":\{[^{}]*?"value":"([^"]*)"', flight)
    )
    title = meta("og:title") or f"Item {item_id}"
    # og:title is usually "<title> | Vinted"
    title = re.sub(r"\s*\|\s*Vinted.*$", "", title)
    return Item(
        id=item_id,
        title=title,
        url=url.split("?")[0],
        price=str(price.get("amount", "")),
        currency=price.get("currency_code", ""),
        brand=brand,
        details=" · ".join(attrs[k] for k in ("size", "status", "color") if k in attrs),
        description=meta("og:description"),
        image=meta("og:image"),
    )


def _clean(v) -> str:
    return v if isinstance(v, str) and not v.startswith("$") else ""


class VintedClient:
    def __init__(self, domain: str = "www.vinted.fr", cookie: str | None = None):
        if not domain.startswith("www."):
            domain = "www." + domain
        self.base_url = f"https://{domain}"
        self.session = requests.Session(impersonate="chrome")
        self._warmed = False
        self.cookie = cookie.strip() if cookie else None

    def _get(self, path_or_url: str, **params):
        if not self._warmed:
            # Picks up the anonymous session cookies Vinted expects.
            self.session.get(self.base_url + "/", timeout=30)
            self._warmed = True
        url = path_or_url if path_or_url.startswith("http") else self.base_url + path_or_url
        headers = {"Cookie": self.cookie} if self.cookie else None
        r = self.session.get(url, params=params or None, headers=headers, timeout=30)
        if r.status_code != 200:
            raise VintedError(f"GET {url} -> HTTP {r.status_code}")
        return r

    def search(
        self,
        text: str,
        *,
        price_from: float | None = None,
        price_to: float | None = None,
        order: str = "relevance",
        page: int = 1,
    ) -> list[Item]:
        params = {"search_text": text, "order": order, "page": str(page)}
        if price_from is not None:
            params["price_from"] = str(price_from)
        if price_to is not None:
            params["price_to"] = str(price_to)
        return parse_catalog(self._get("/catalog", **params).text, self.base_url)

    def item(self, url: str) -> Item:
        if not url.startswith("http"):
            url = self.base_url + "/" + url.lstrip("/")
        return parse_item_page(self._get(url).text, url)

    def favourites(self) -> list[Item]:
        """The logged-in user's liked items. Needs `cookie` from a logged-in browser."""
        if not self.cookie:
            raise VintedError("Importing likes needs your Vinted cookie.")
        user_id = _user_id_from_cookie(self.cookie)
        if user_id:
            try:
                r = self._get(
                    f"/api/v2/users/{user_id}/items/favourites", per_page="96", page="1"
                )
                items = [self._from_api(raw) for raw in r.json().get("items", [])]
                if items:
                    return items
            except (VintedError, ValueError):
                pass
        items = parse_catalog(
            self._get("/member/items/favourite_list").text, self.base_url
        )
        if not items:
            raise VintedError(
                "Couldn't read your likes. The cookie may be expired; copy a fresh one."
            )
        return items

    def _from_api(self, raw: dict) -> Item:
        price = raw.get("price") or {}
        if not isinstance(price, dict):
            price = {"amount": price, "currency_code": raw.get("currency", "")}
        photo = raw.get("photo") or {}
        return Item(
            id=int(raw["id"]),
            title=raw.get("title", ""),
            url=raw.get("url") or f"{self.base_url}/items/{raw['id']}",
            price=str(price.get("amount", "")),
            currency=price.get("currency_code", ""),
            brand=raw.get("brand_title", "") or "",
            details=" · ".join(x for x in (raw.get("size_title"), raw.get("status")) if x),
            image=photo.get("url", "") if isinstance(photo, dict) else "",
            favourites=int(raw.get("favourite_count") or 0),
        )


def _user_id_from_cookie(cookie: str) -> str | None:
    """Vinted's access_token_web is a JWT whose `sub` claim is the user id."""
    m = re.search(r"access_token_web=([^;\s]+)", cookie)
    if not m:
        return None
    try:
        payload = m.group(1).split(".")[1]
        payload += "=" * (-len(payload) % 4)
        sub = json.loads(base64.urlsafe_b64decode(payload)).get("sub")
        return str(sub) if sub else None
    except (IndexError, ValueError):
        return None
