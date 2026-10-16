# Vinted Finder

Finds the best Vinted listings for you from two inputs: **items you liked** and **a prompt** describing what you want.

1. **Reads your likes.** Paste liked item links, or give your Vinted browser cookie to import all your favourites.
2. **Plans searches.** Works out a few Vinted searches from your prompt and the style, brands, sizes and budget of your likes.
3. **Searches Vinted.** Runs them, removes duplicates and things you already liked.
4. **Ranks** the listings and shows the top picks with a reason for each.

Ranking runs in one of two modes, and the page shows which one is active:

| Mode | When | Cost | Quality |
|---|---|---|---|
| **Claude** | `ANTHROPIC_API_KEY` is set | Haiku 5.5: under 1 cent per search (~500 searches for $5) | Best: reads photos, titles and your request |
| **Free photo matching** | no key, or Claude fails (e.g. out of credit) | $0 | Good at "looks like what I liked"; rougher on the text request |

Free mode uses the open CLIP image model on your CPU. It downloads once (~600 MB) on first start.

## Run it on your computer

You need Python 3.10+ (python.org).

```bash
cp .env.example .env        # optional: add your Anthropic API key
python3 start.py            # just you, at http://localhost:8000
python3 start.py --share    # also prints a free public link for testers
```

Shortcuts: `./run.sh --share` on macOS/Linux, or double-click `start.bat` on Windows (`start.bat --share` from a terminal).

The first run installs everything into `.venv` (a few minutes). `--share` downloads Cloudflare's free `cloudflared` tool and creates a `https://<random>.trycloudflare.com` link. No account is needed. Send that link to testers. It works while your computer and `start.py` are running, and a new link is created each time you restart.

If the link never appears, your network (VPN, school or work Wi-Fi) is probably blocking Cloudflare tunnels. Try another network or use the free cloud hosting below.

### Limits for testers

- Each visitor (by IP address) gets **20 searches per day**. Change it with `DAILY_LIMIT` in `.env`. Failed searches don't count.
- At most 2 searches run at once; the rest wait.
- For a hard cap on spending, set a monthly limit in the Anthropic Console (Settings → Limits). When credit runs out, the app switches to free photo matching on its own.

## Getting an API key (optional)

A Claude subscription (Pro/Max) doesn't include API usage; the API is billed separately.

1. Sign in at https://console.anthropic.com
2. Billing → buy credits ($5 goes a long way with Haiku)
3. Settings → Limits → set a monthly spend limit
4. API Keys → create a key → put it in `.env` as `ANTHROPIC_API_KEY=sk-ant-...`

To use the most careful (and pricier, ~$0.20–0.50 per search) model, set `VINTED_FINDER_MODEL=claude-opus-5-5`.

## Free cloud hosting (always-on link)

The `Dockerfile` runs on Hugging Face Spaces' free CPU tier (2 vCPU, 16 GB):

1. Create a free account at https://huggingface.co, then **New Space** → SDK **Docker** → Blank → Public.
2. Push this repo to the Space (`git remote add space https://huggingface.co/spaces/<you>/<name>` then `git push space HEAD:main`). Add this to the top of `README.md` in the Space first:
   ```
   ---
   title: Vinted Finder
   sdk: docker
   app_port: 7860
   ---
   ```
3. Optional: in the Space's **Settings → Variables and secrets**, add `ANTHROPIC_API_KEY` as a secret.

Caveats: free Spaces sleep after 48 h without visits (the first visit wakes them in about a minute), and Vinted's Cloudflare blocks cloud servers more often than home connections, so searches may fail there. If that happens, use `start.py --share` from home instead.

## Command line

```bash
python -m vinted_finder "a vintage leather jacket, size M, under 60€" \
  --liked https://www.vinted.fr/items/123-... --top 10
```

Options: `--liked-file likes.txt`, `--cookie "..."` (or `VINTED_COOKIE`) to import all likes, `--domain www.vinted.co.uk`, `--max-price`, `--json`.

### Importing all your likes with a cookie

Log in to Vinted in your browser, open DevTools → Network, click any request to the Vinted site and copy the whole `Cookie` request header. It's only used to read your favourites. Treat it like a password.

## Notes

- Vinted has no public API, and its terms don't allow scraping. Results are read from Vinted's own search pages. That's fine for a small test, but don't turn it into a public service as is. A site redesign can break parsing (`vinted_finder/vinted.py`).
- Cloudflare sometimes blocks a request (HTTP 403); the client retries with a fresh browser session.
- Only Vinted sites are fetched; links from another Vinted country are read through the site you pick.

## Tests

```bash
.venv/bin/python -m pip install pytest && .venv/bin/python -m pytest tests
```
