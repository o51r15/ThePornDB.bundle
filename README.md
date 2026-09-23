# tpdb-provider

A Plex **custom metadata provider** for [ThePornDB](https://theporndb.net/).

This is the successor to `ThePornDB.bundle`. Plex Media Server 1.43 replaced the
old `.bundle` agent framework with an HTTP provider API, so the agent is no
longer Python 2 running inside PMS — it is a small service Plex talks to over
HTTP. The matching and metadata logic from the bundle is carried over; the
plugin scaffolding is gone.

Two providers run in one container:

| Endpoint | Plex type | Model |
|---|---|---|
| `/scenes` | movie | one scene = one item, grouped by site/network collections |
| `/tv` | show / season / episode | site = show, year = season, scene = episode |

---

## Requirements

- Plex Media Server **1.43.0+**
- A ThePornDB API token
- Docker, or Python 3.9+

## Run it

```bash
cp .env.example .env      # put your token in TPDB_API_KEY
docker compose up -d
curl http://<host>:8080/scenes      # should return a MediaProvider document
```

Without Docker:

```bash
pip install -r requirements.txt
TPDB_API_KEY=... python wsgi.py           # dev
gunicorn --bind 0.0.0.0:8080 wsgi:app     # prod
```

## Register it with Plex

1. **Settings → Metadata Agents → Add Provider** → `http://<host>:8080/scenes`
   (or `/tv`)
2. **Add Agent** → name it, set that provider as **Primary**
3. Create a **Movie** library for `/scenes`, or a **TV Shows** library for `/tv`,
   and pick the agent in the Advanced pane

Notes:

- Plex sends custom providers **unauthenticated** requests. Keep the service on
  your LAN until Plex ships provider auth.
- HTTPS is not required.
- A metadata *refresh* never re-matches. Items that failed to match are stored
  as `local://` stubs and stay that way — only a fresh scan of a file Plex has
  not seen, or a manual **Fix Match**, creates a new binding. After changing
  provider behaviour, use Fix Match on one item to verify, then recreate the
  library.

---

## Configuration

All configuration is environment variables; the new provider API has no
Plex-side preferences UI, so the bundle's `DefaultPrefs.json` settings moved
here. See `.env.example` for the full list.

| Variable | Old pref | Notes |
|---|---|---|
| `TPDB_API_KEY` | `personal_api_key` | Required |
| `TPDB_IDENTIFIER` | — | Must start with `tv.plex.agents.custom.` |
| `TPDB_MATCH_BY_FILENAME` | `match_by_filepath_enable` | Plex sends `filename` in match hints |
| `TPDB_STRIP_PATH` | `filepath_strip_path_enable` | |
| `TPDB_CLEANUP_ENABLE` / `_REGEX` / `_REPLACE` | `filepath_cleanup*` | Comma-separated regexes |
| `TPDB_SCORE_METHOD` | `score_method` | `default` or `custom` |
| `TPDB_CUSTOM_SCORE` | `custom_score` | `{title}` `{site}` `{date}` |
| `TPDB_OSHASH_ENABLE` | `oshash_matching_enable` | Default **off** — see below |
| `TPDB_COLLECTIONS_FROM_SITE/PARENTS/NETWORKS/TAGS` | `collections_from_*` | |
| `TPDB_COLLECTION_*_PREFIX` | `collection_*_prefix` | |
| `TPDB_CUSTOM_TITLE_ENABLE` / `TPDB_CUSTOM_TITLE` | `custom_title*` | `{title}` `{actors}` `{studio}` `{series}` |
| `TPDB_SAVE_TO_COLLECTION` | `save_to_collection` | Marks scenes collected on TPDB |
| `TPDB_CONTENT_RATING` | — | Default `XXX` |
| `TPDB_CACHE_TTL` | — | In-process cache, seconds |
| `TPDB_SITE_PAGE_SIZE` | — | Upstream page size, max 100 |
| `TPDB_MAX_SITE_PAGES` | — | Cap per site (60 × 100 = 6000 scenes) |
| `TPDB_SITE_FETCH_WORKERS` | — | Concurrent page fetches |

### About `TPDB_OSHASH_ENABLE`

Leave it off unless your files really do carry OpenSubtitles hashes. Plex puts
its **own** hash in every match request, and TPDB rejects any `hash` that is not
16 hex digits by failing the entire request:

```
422 {"message":"The hash must be valid hash.","errors":{"hash":["The hash must be valid hash."]}}
```

Forwarding it blindly made every lookup return empty. The provider now only
sends a hash that matches `^[0-9a-fA-F]{16}$`, and only when this is enabled.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/scenes` or `/tv` | Provider manifest |
| POST | `.../library/metadata/matches` | Match feature |
| GET | `.../library/metadata/{ratingKey}` | Metadata (`?includeChildren=1` embeds children) |
| GET | `.../library/metadata/{ratingKey}/children` | Seasons of a show, or episodes of a season |
| GET | `.../library/metadata/{ratingKey}/grandchildren` | All episodes of a show |
| GET | `.../library/metadata/{ratingKey}/images` | Artwork (movie provider) |
| GET | `/scenes/selftest?q=<title>` | Validates the upstream contract in one call |
| GET | `/health` | Liveness |

GUIDs: `<identifier>://<type>/<ratingKey>`. TV rating keys are prefixed
`show-<siteId>`, `season-<siteId>-<year>`, `ep-<sceneUuid>`.

### TV episode numbering

TPDB scenes have no episode number, so `index` is derived from the air date:
`2019-01-25` → episode **125** in season **2019**. Stable and ordered. Two
scenes released by the same site on the same day collide on `index`; they stay
distinct by GUID.

**Plex's TV scanner will not number `Show - YYYY-MM-DD - Title.ext` or
release-style `Show.YY.MM.DD.stuff.ext` files** — they land in
`[Unknown Season]` with no index and can never bind. Only `S<year>E<MMDD>`
parses. `tools/rename_for_plex.py` converts a library to that form, resolving
every file against TPDB for the real title:

```bash
python3 tools/rename_for_plex.py '/path/to/Scenes Agent'     # dry run
python3 tools/rename_for_plex.py '/path/to/Scenes Agent' --apply
```

The movie provider has no such constraint — it matches on filename alone.

---

## Container images

CI publishes to GHCR on every push to `main`:

```
ghcr.io/o51r15/tpdb-provider:dev        <- working tag, what you run day to day
ghcr.io/o51r15/tpdb-provider:latest     <- releases only (pushed on a vX.Y.Z tag)
ghcr.io/o51r15/tpdb-provider:vX.Y.Z     <- the release itself
```

`docker-compose.yml` uses `:dev`. Cut a release by tagging:

```bash
git tag v1.0.0 && git push origin --tags
```

## Tests

```bash
python tests/test_provider.py    # 16
python tests/test_tv.py          # 30
```

Upstream is stubbed; no token needed. They cover the manifest shape, all match
paths, pagination, the `Children` container shape, and the hash handling —
every one written against a bug that actually occurred.

## Notes on Plex's provider API

Things that cost real debugging time:

- Paging arrives as **query parameters** on GETs (`?X-Plex-Container-Start=…`),
  not only as headers. Reading headers alone makes every page identical.
- `Children` must be an **object** (`{"size": n, "Metadata": [...]}`), not an
  array. An array fails the whole response with
  `failed to parse JSON response: 'object expected' at 1:44`.
- Plex never sends a `type: 4` episode match. It matches show, then season with
  `includeChildren=1`, and binds files to the children in that response.
- Its scanner falls back to season 1 when it cannot parse a season, so the
  provider recovers the year from a date in the filename.

## Changes from the bundle

- Python 3, Flask, runs as a service instead of inside PMS
- Exponential retry backoff (the bundle's `sleep_time * x` was 0 on the first
  retry, and its leaked `str_error` was never cleared between attempts)
- TLS verification on; the bundle used `verify=False` with the warning muted
- No bare `except:`; missing upstream fields no longer raise
- Vendored `requests`/`urllib3`/`idna` dropped in favour of pinned requirements
