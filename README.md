# Vinted Finder

Finds the best Vinted listings for you from two inputs: **items you liked** and **a prompt** describing what you want.

1. **Reads your likes.** Paste liked item links, or give your Vinted browser cookie to import all your favourites.
2. **Plans searches.** Works out a few Vinted searches from your prompt and the style, brands, sizes and budget of your likes.
3. **Searches Vinted.** Runs them, removes duplicates and things you already liked.
4. **Ranks** the listings and shows the top picks with a reason for each.

You pick the matching mode on the page (or with `--mode` on the command line):

| Mode | Cost | What it does |
|---|---|---|
| **Free · photos** (`visual`, default) | $0 | Compares listing photos to your liked items' photos with the open CLIP model, plus keywords. Good at "looks like what I liked". Downloads ~600 MB once. |
| **Free · tags** (`keywords`) | $0 | Matches brands, words and size tags. Fastest, no download. |
| **Paid · Claude API** (`claude`) | Haiku 5.5: under 1 cent per search | Claude reads photos, titles and your request. Best results. Shows as "not set up" until `ANTHROPIC_API_KEY` is set; if Claude fails mid-search (e.g. out of credit), that search falls back to a free mode. |

**Sizes first:** type the sizes you want (e.g. `M, 38`). Listings tagged with one of those sizes are listed before everything else, best match first; other listings follow. Leave it blank to use the sizes of your liked items. Matching ignores prefixes, so `38` matches `EU 38` and `M / 38 / 10`.

**Price range:** set a min and/or max price. Both are sent to Vinted's search and checked again on the results.

## Run it on your computer

You need Python 3.10+ (python.org). Free photo matching needs Python 3.10–3.14, because its `onnxruntime` dependency doesn't support 3.15 yet. On a newer Python the app still runs, using keyword matching. To get photo matching, install 3.13 alongside it (`py install 3.13` on Windows). `start.py` finds it and uses it automatically.

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
- For a hard cap on spending, set a monthly limit in the Anthropic Console (Settings → Limits). When credit runs out, paid searches fall back to a free mode on their own.

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

Options: `--mode visual|keywords|claude`, `--size "M, 38"`, `--min-price`, `--max-price`, `--liked-file likes.txt`, `--cookie "..."` (or `VINTED_COOKIE`) to import all likes, `--domain www.vinted.co.uk`, `--json`.

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
