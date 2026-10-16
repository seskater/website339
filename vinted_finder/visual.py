"""Free, local image matching with CLIP (no API key needed).

Compares listing photos to the photos of your liked items, and to the text of
your prompt, using the open CLIP ViT-B/32 model run on CPU via ONNX. The model
(~600 MB) downloads once on first use.
"""

from __future__ import annotations

import io
import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

try:
    import numpy as np
except ImportError:  # photo matching is optional (requirements-photo.txt)
    np = None

IMAGE_MODEL = "Qdrant/clip-ViT-B-32-vision"
TEXT_MODEL = "Qdrant/clip-ViT-B-32-text"
CACHE_DIR = os.environ.get(
    "VINTED_FINDER_MODELS", os.path.join(os.path.dirname(__file__), "..", ".models")
)

_lock = threading.Lock()
_models = None
_cache: OrderedDict[str, np.ndarray] = OrderedDict()
_CACHE_MAX = 20000


def available() -> bool:
    if np is None:
        return False
    try:
        import fastembed  # noqa: F401
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


def _load():
    global _models
    with _lock:
        if _models is None:
            from fastembed import ImageEmbedding, TextEmbedding

            _models = (
                ImageEmbedding(IMAGE_MODEL, cache_dir=CACHE_DIR),
                TextEmbedding(TEXT_MODEL, cache_dir=CACHE_DIR),
            )
    return _models


def warm_up():
    """Download/load the models ahead of the first search."""
    if available():
        _load()


def _fetch(urls: list[str]) -> dict[str, bytes]:
    from curl_cffi import requests

    local = threading.local()

    def get(url: str):
        if not hasattr(local, "s"):
            local.s = requests.Session(impersonate="chrome")
        try:
            r = local.s.get(url, timeout=20)
            return url, r.content if r.status_code == 200 else None
        except requests.RequestsError:
            return url, None

    with ThreadPoolExecutor(max_workers=12) as pool:
        return {u: b for u, b in pool.map(get, urls) if b}


def _unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-9)


def embed_images(urls: list[str]) -> dict[str, np.ndarray]:
    """URL -> unit-length embedding. Images that fail to load are left out."""
    from PIL import Image

    image_model, _ = _load()
    todo = [u for u in dict.fromkeys(urls) if u and u not in _cache]
    if todo:
        raw = _fetch(todo)
        pics, keys = [], []
        for url, data in raw.items():
            try:
                pics.append(Image.open(io.BytesIO(data)).convert("RGB"))
                keys.append(url)
            except Exception:
                continue
        if pics:
            for url, vec in zip(keys, image_model.embed(pics, batch_size=32)):
                _cache[url] = _unit(np.asarray(vec, dtype=np.float32))
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return {u: _cache[u] for u in urls if u in _cache}


def embed_text(text: str) -> np.ndarray:
    _, text_model = _load()
    return _unit(np.asarray(next(iter(text_model.embed([text]))), dtype=np.float32))


def scores(liked_images: list[str], prompt: str, candidate_images: dict[int, str]):
    """Per candidate id: (similarity to liked photos, similarity to the prompt), each 0-1.

    Both are rescaled across the candidate pool, so they rank rather than
    measure. Either is None when there was nothing to compare against.
    """
    vecs = embed_images(list(liked_images) + list(candidate_images.values()))
    liked = [vecs[u] for u in liked_images if u in vecs]
    ids = [i for i, u in candidate_images.items() if u in vecs]
    if not ids:
        return {}
    C = np.stack([vecs[candidate_images[i]] for i in ids])

    like_sim = None
    if liked:
        L = np.stack(liked)
        # Blend "close to your taste overall" with "close to one specific like".
        sims = C @ L.T
        like_sim = _rescale(0.5 * (C @ _unit(L.mean(0))) + 0.5 * sims.max(1))
    text_sim = _rescale(C @ embed_text(prompt)) if prompt.strip() else None

    return {
        i: (
            None if like_sim is None else float(like_sim[n]),
            None if text_sim is None else float(text_sim[n]),
        )
        for n, i in enumerate(ids)
    }


def _rescale(x: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(x, 5), np.percentile(x, 99)
    return np.clip((x - lo) / (hi - lo + 1e-9), 0, 1)
