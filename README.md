<p align="center">
  <b>tpdb-provider</b><br>
  <b>Plex metadata provider for ThePornDB</b><br>
  The successor to ThePornDB.bundle — an HTTP provider for Plex 1.43+, where plug-in agents no longer load.
</p>

<p align="center">
  <a href="https://github.com/o51r15/ThePornDB.bundle/pkgs/container/tpdb-provider"><img src="https://img.shields.io/badge/ghcr.io-tpdb--provider-blue?style=flat-square&logo=docker" alt="GHCR"></a>
  <a href="https://github.com/o51r15/ThePornDB.bundle/actions"><img src="https://img.shields.io/github/actions/workflow/status/o51r15/ThePornDB.bundle/build.yml?style=flat-square&label=build" alt="Build"></a>
  <img src="https://img.shields.io/badge/plex-1.43%2B-e5a00d?style=flat-square" alt="Plex 1.43+">
  <img src="https://img.shields.io/badge/python-3.12-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python 3.12">
</p>

---

## Why tpdb-provider?

Plex Media Server 1.43 removed the plug-in framework every `.bundle` agent depends on. ThePornDB.bundle — and every fork of it — stopped loading, taking adult scene metadata with it. Plex's replacement is a REST API: a provider is now an external HTTP service that Plex queries, not Python 2 running inside the server. This is that service. The matching logic, preference set and TPDB field mapping are ported from the bundle, so the behaviour you had is intact; the dead plug-in scaffolding is gone. One container, two providers, no cloud dependency beyond TPDB itself.

---

## What it does

Plex sends a match request with whatever it knows about a file — filename, title,
year, sometimes a hash. tpdb-provider cleans that up, asks ThePornDB's `parse`
endpoint to identify it, and hands Plex back a fully populated item: real scene
title, studio, air date, runtime, cast with headshots, genres, poster and
background art, and site / parent / network collections.

**`/scenes` is the one you want for scene releases.** It models each scene as a
movie and groups them with site, parent and network collections — the behaviour
of the old Scenes bundle, and it needs no changes to your filenames. For full
feature releases, **`/movies`** does the same against TPDB's movie catalogue.

A second provider, **`/tv`**, models the site as a show and each scene as an
episode. It works, but Plex's TV scanner cannot assign season or episode numbers
to typical scene filenames, so it requires renaming your library first. Treat it
as optional — see [TV provider](#tv-provider-optional).

---

## Features

- **Drop-in replacement** — `/scenes` and `/movies` reproduce the old Scenes and Movies bundles: movie-type libraries, matched on filename, no renaming required
- **JAV** — the third bundle's `/jav` catalogue is wired the same way, off by default
- **Filename identification** — hands the raw filename to TPDB's `parse` endpoint, the same call the bundle relied on; handles `Site - YYYY-MM-DD - Title`, release-style `Site.YY.MM.DD.stuff`, and messier names
- **Every bundle preference ported** — filename cleanup regex, score method, custom title format, collection prefixes, oshash matching, collected-tagging; all as environment variables
- **Full metadata** — title, studio, summary, air date, runtime, content rating, genres, cast with face images, poster and background art, trailers
- **Collections** — site, parent and network collections with optional prefixes, so a movie library still browses by studio
- **TV hierarchy** — site as show with its own poster and summary, seasons by release year, episode index derived from the air date
- **Concurrent upstream paging** — a site's scene list is fetched in parallel at 100 per page; a 4000-scene site went from 201 serial requests to 41, cold listing 36s → 3s
- **Response caching** — in-process TTL cache keyed on URL and params, so Plex's repeated children calls cost nothing
- **Self-check endpoint** — `/scenes/selftest` makes a real API call and reports exactly which upstream fields are present, missing or empty
- **Bulk renamer** — `tools/rename_for_plex.py` converts a library to the only naming Plex's TV scanner can number, resolving every file against TPDB for the real title; dry run by default
- **46 tests** — every one written against a bug that actually occurred in production
- **Docker-native** — GHCR images, non-root container, healthcheck, CI-built `:dev` and `:latest`

---

## Quick Start

### Docker Compose (recommended)

```yaml
services:
  tpdb-provider:
    image: ghcr.io/o51r15/tpdb-provider:dev   # :latest for releases
    container_name: tpdb-provider
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      - TZ=America/New_York
    env_file:
      - .env
```

```bash
cp .env.example .env     # add your TPDB_API_KEY
docker compose up -d
curl http://your-server:8080/scenes
```

A `MediaProvider` document comes back when it's working.

> **Tip:** Plex sends custom providers **unauthenticated** requests. Keep this on your LAN until Plex ships provider auth.

### Docker Run

```bash
docker run -d --name tpdb-provider \
  -p 8080:8080 \
  -e TPDB_API_KEY=your-token \
  -e TZ=America/New_York \
  --restart unless-stopped \
  ghcr.io/o51r15/tpdb-provider:dev
```

### From Source

```bash
git clone https://github.com/o51r15/ThePornDB.bundle.git && cd ThePornDB.bundle
pip install -r requirements.txt
cp .env.example .env
TPDB_API_KEY=... python3 wsgi.py            # dev
gunicorn --bind 0.0.0.0:8080 wsgi:app       # prod
```

---

## Providers

| Provider | Plex library | Upstream | Model | Filenames |
|---|---|---|---|---|
| **`/scenes`** | Movie | `/scenes` | One scene = one item, grouped by site / parent / network collections | Any — matched on filename |
| **`/movies`** | Movie | `/movies` | One full release = one item | Any — matched on filename |
| `/jav` | Movie | `/jav` | JAV releases — **off by default**, set `TPDB_JAV_ENABLE=true` | Any — matched on filename |
| `/tv` | TV Shows | `/scenes` | Site = show, release year = season, scene = episode | Must carry `S<year>E<MMDD>` — needs a rename pass |

Scenes and full movie releases are different catalogues upstream, so they get a
library each: point a Scenes library at `/scenes` and a Movies library at
`/movies`. Both are movie-type and neither needs renaming.

---

## Plex Setup

1. **Settings → Metadata Agents → Add Provider** → `http://your-server:8080/scenes`
2. **Add Agent** — name it, then set the provider you just added as **Primary**
3. Create a **Movie** library and pick that agent in the **Advanced** pane

That's the whole setup. Scenes are identified from their filenames and grouped
into collections by site, parent studio and network.

For a library of full releases rather than scenes, repeat those three steps with
`http://your-server:8080/movies` and a second agent. The two are separate
providers with separate identifiers, so one library never matches against the
other's catalogue.

> **Important:** a metadata *refresh* never re-matches. Items that failed to match are stored as `local://` stubs and stay that way. Only a fresh scan of a file Plex has not seen, or a manual **Fix Match**, creates a new binding. After changing provider behaviour, Fix Match one item to verify, then recreate the library.

---

## Configuration

Everything is environment variables — the provider API has no Plex-side preferences pane, so the bundle's `DefaultPrefs.json` moved to `.env`.

| Variable | Bundle preference | Default | Notes |
|---|---|---|---|
| `TPDB_API_KEY` | `personal_api_key` | — | **Required** |
| `TPDB_IDENTIFIER` | — | `tv.plex.agents.custom.theporndb.scenes` | Must start with `tv.plex.agents.custom.` |
| `TPDB_MOVIES_ENABLE` | — | `true` | Serve `/movies` |
| `TPDB_MOVIES_IDENTIFIER` | — | `tv.plex.agents.custom.theporndb.movies` | |
| `TPDB_MOVIES_TITLE` | — | `ThePornDB Movies` | |
| `TPDB_JAV_ENABLE` | — | `false` | Serve `/jav` |
| `TPDB_JAV_IDENTIFIER` | — | `tv.plex.agents.custom.theporndb.jav` | |
| `TPDB_TV_IDENTIFIER` | — | `tv.plex.agents.custom.theporndb.tv` | |
| `TPDB_MATCH_BY_FILENAME` | `match_by_filepath_enable` | `true` | Use the filename rather than Plex's cleaned title |
| `TPDB_STRIP_PATH` | `filepath_strip_path_enable` | `true` | |
| `TPDB_CLEANUP_ENABLE` | `filepath_cleanup_enable` | `false` | |
| `TPDB_CLEANUP_REGEX` | `filepath_cleanup` | — | Comma-separated regexes stripped before searching |
| `TPDB_CLEANUP_REPLACE` | `filepath_replace` | — | |
| `TPDB_SCORE_METHOD` | `score_method` | `default` | `default` or `custom` |
| `TPDB_CUSTOM_SCORE` | `custom_score` | `{site} {date} {title}` | Levenshtein target |
| `TPDB_OSHASH_ENABLE` | `oshash_matching_enable` | `false` | Leave off — see below |
| `TPDB_CUSTOM_TITLE_ENABLE` | `custom_title_enable` | `false` | |
| `TPDB_CUSTOM_TITLE` | `custom_title` | `{actors} - {title} [{studio}/{series}]` | |
| `TPDB_COLLECTIONS_FROM_SITE` | `collections_from_site` | `true` | |
| `TPDB_COLLECTIONS_FROM_PARENTS` | `collections_from_parents` | `true` | |
| `TPDB_COLLECTIONS_FROM_NETWORKS` | `collections_from_networks` | `true` | |
| `TPDB_COLLECTIONS_FROM_TAGS` | `create_all_tag_collection_tags` | `false` | |
| `TPDB_COLLECTION_SITE_PREFIX` | `collection_site_prefix` | — | Also `_PARENT_` and `_NETWORK_` |
| `TPDB_SAVE_TO_COLLECTION` | `save_to_collection` | `false` | Marks scenes collected on TPDB |
| `TPDB_CONTENT_RATING` | — | `XXX` | |
| `TPDB_CACHE_TTL` | — | `3600` | Seconds; `0` disables |
| `TPDB_SITE_PAGE_SIZE` | — | `100` | Upstream max is 100 |
| `TPDB_MAX_SITE_PAGES` | — | `60` | 6000 scenes per site |
| `TPDB_SITE_FETCH_WORKERS` | — | `8` | Concurrent page fetches |
| `TPDB_LOG_LEVEL` | `logging_level` | `INFO` | |

### About `TPDB_OSHASH_ENABLE`

Leave it off unless your files genuinely carry OpenSubtitles hashes. Plex puts its **own** hash in every match request, and TPDB rejects any `hash` that isn't 16 hex digits by failing the entire call:

```
422 {"message":"The hash must be valid hash.","errors":{"hash":["The hash must be valid hash."]}}
```

Forwarding it blindly returned empty results for every file in the library. The provider now only sends a hash matching `^[0-9a-fA-F]{16}$`, and only when this is enabled.

---

## TV provider (optional)

Register `/tv` against a **TV Shows** library and each site becomes a show, each
release year a season, each scene an episode.

**Read this before you commit to it.** TPDB scenes have no episode number, so
`/tv` derives one from the air date: `2019-01-25` becomes **S2019E0125**. Stable,
ordered, unique within a site-year. Two scenes from the same site on the same day
share an index but stay distinct by GUID.

The catch is Plex's side, not the provider's. **Plex's TV scanner will not number
typical scene filenames** — it reads the date but assigns no season or episode, so
they land in `[Unknown Season]` and can never bind to anything:

| Filename | Plex scanner result |
|---|---|
| `Show - 2019-01-18 - Title [WEBDL-1080p].mkv` | no index, no season |
| `Show.24.06.27.performer.XXX.mkv` | season 1, arbitrary episode |
| `Show - S2019E0118 - Title.mkv` | **index 118, season 2019** |

The included renamer converts a library to the third form, looking each file up in TPDB so the title is authoritative rather than parsed:

```bash
python3 tools/rename_for_plex.py '/path/to/Scenes'              # dry run + TSV report
python3 tools/rename_for_plex.py '/path/to/Scenes' --apply
python3 tools/rename_for_plex.py '/path/to/Scenes' --only 'Baby Got Boobs'
```

It handles ISO dates, `YY.MM.DD` release style and `DD.MM.YYYY`, skips names already in `S##E##` form, and refuses to guess — same-day collisions it can't resolve from the filename are reported as `AMBIGUOUS` and left alone.

**If renaming isn't something you want to do, use `/scenes`.** It matches on filename alone and has none of this constraint, which is why it's the drop-in replacement for the old Scenes bundle.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/scenes` · `/movies` · `/jav` · `/tv` | Provider manifest |
| `POST` | `.../library/metadata/matches` | Match feature |
| `GET` | `.../library/metadata/{ratingKey}` | Metadata — `?includeChildren=1` embeds children |
| `GET` | `.../library/metadata/{ratingKey}/children` | Seasons of a show, or episodes of a season |
| `GET` | `.../library/metadata/{ratingKey}/grandchildren` | Every episode of a show |
| `GET` | `.../library/metadata/{ratingKey}/images` | Artwork |
| `GET` | `/scenes/selftest?q=<title>` | Validates the live upstream contract |
| `GET` | `/health` | Liveness |

GUIDs follow `<identifier>://<type>/<ratingKey>`. TV rating keys are prefixed `show-<siteId>`, `season-<siteId>-<year>`, `ep-<sceneUuid>`.

---

## Requirements

- **Plex Media Server 1.43.0+** — custom metadata providers do not exist before this
- **A ThePornDB API token** — from your account settings at [theporndb.net](https://theporndb.net/)
- **Docker**, or **Python 3.9+** if running from source
- Network reachability from the Plex server to this service

---

## Docker Images

| Tag | When it's built |
|---|---|
| `ghcr.io/o51r15/tpdb-provider:dev` | Every push to `main` |
| `ghcr.io/o51r15/tpdb-provider:latest` | Tagged releases only |
| `ghcr.io/o51r15/tpdb-provider:vX.Y.Z` | The release itself |

Cut a release with `git tag v1.0.0 && git push origin --tags`.

---

## Notes on Plex's Provider API

Undocumented behaviour that cost real debugging time, recorded so the next person doesn't repeat it:

- **Paging arrives as query parameters** on GETs (`?X-Plex-Container-Start=…`), not only as headers. Reading headers alone makes every page return the same slice, and Plex will happily walk offsets 0→580 receiving identical bodies.
- **`Children` must be an object**, not an array — `{"size": n, "Metadata": [...]}`. An array fails the entire response with `failed to parse JSON response: 'object expected' at 1:44`, and the match is discarded silently.
- **Plex never sends a `type: 4` episode match.** It matches the show, then the season with `includeChildren=1`, and binds files to the children in that response. A season returned without its episodes binds nothing.
- **Its scanner falls back to season 1** when it can't parse a season from the filename, so the provider recovers the year from any date it can find in the name.
- **A refresh never re-matches.** `local://` stubs are permanent until a fresh scan or a manual Fix Match.

---

## Tests

```bash
python3 tests/test_provider.py     # 22
python3 tests/test_tv.py           # 30
```

Upstream is stubbed, so no token is needed. They cover the manifest shape, every match path, pagination via both query params and headers, the `Children` container shape, episode index derivation, and hash handling.

---

## Legacy Bundles

The `ThePornDB*.bundle/` directories are the original Plex plug-in agents. They no longer load — PMS 1.43 removed the framework they depend on. They're kept for reference: the matching logic, preference names and TPDB field usage in `tpdb_provider/` are ported from them. Nothing in those directories runs.

---

## Links

- [Plex Metadata Providers API](https://developer.plex.tv/pms/) — the spec this implements
- [ThePornDB](https://theporndb.net/) — the metadata source
- [Issues](https://github.com/o51r15/ThePornDB.bundle/issues) — bugs and feature requests
