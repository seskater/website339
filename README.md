# Vinted Finder

Finds the best Vinted listings for you from two inputs: **items you liked** and **a prompt** describing what you want.

How it works:

1. **Reads your likes.** Paste liked item links, or give your Vinted browser cookie to import all your favourites at once.
2. **Learns your taste.** Claude looks at the liked items (photos, titles, brands, sizes, prices) together with your prompt and writes a short taste profile plus 3–6 Vinted searches.
3. **Searches Vinted.** Runs each search (up to ~96 results each), removes duplicates and things you already liked.
4. **Ranks.** Claude scores every candidate against your request and taste and returns the top picks with a one-line reason each.

## Setup

Requires Python 3.10+ and an [Anthropic API key](https://console.anthropic.com/).

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

## Web app

```bash
uvicorn vinted_finder.app:app --port 8000
```

Open http://localhost:8000, type what you want, paste some liked item links, and hit **Find items**. A run takes about a minute.

## Command line

```bash
python -m vinted_finder "a vintage leather jacket for autumn, size M" \
  --liked https://www.vinted.fr/items/123-... https://www.vinted.fr/items/456-... \
  --max-price 60 --top 10
```

Options: `--liked-file likes.txt` (one URL per line), `--cookie "..."` or `VINTED_COOKIE` to import all likes, `--domain www.vinted.co.uk` for another country, `--effort high` for a more careful (slower, pricier) ranking, `--json` for machine-readable output.

### Importing all your likes with a cookie

Log in to Vinted in your browser, open DevTools → Network, click any request to the Vinted site and copy the whole `Cookie` request header. The app uses it only to read your favourites from Vinted. Treat it like a password: don't share it. It expires after a while; copy a fresh one if import stops working.

## Notes and limits

- Vinted has no public API. Search results are read from Vinted's own server-rendered search pages, so a Vinted site redesign can break parsing (see `vinted_finder/vinted.py`).
- Each run makes two Claude calls (`claude-opus-5-5`): one with your liked items' photos, one ranking up to 250 listings. Expect roughly $0.20–0.50 per run in API costs.
- Keep your request rate reasonable; Vinted may rate-limit heavy use.

## Tests

```bash
pip install pytest && python -m pytest tests
```
