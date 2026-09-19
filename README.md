# tpdb-provider

A Plex **custom metadata provider** for [ThePornDB](https://theporndb.net/), covering **Scenes**.

This is the successor to `ThePornDBScenes.bundle`. Plex Media Server 1.43+ replaced
the old `.bundle` agent framework with an HTTP provider API, so the agent is no
longer Python 2 code loaded inside PMS — it is a small service PMS talks to over
HTTP. The matching and metadata logic from the bundle is carried over; the
plugin scaffolding is gone.

## Requirements

- Plex Media Server **1.43.0 or newer** (custom metadata providers)
- A ThePornDB API token
- Docker, or Python 3.9+

## Run it

```bash
cp .env.example .env
# put your token in TPDB_API_KEY
docker compose up -d
```

Confirm it's alive:

```bash
curl http://<host>:8080/scenes
```

You should get a `MediaProvider` document back.

Without Docker:

```bash
pip install -r requirements.txt
TPDB_API_KEY=... python wsgi.py          # dev
gunicorn --bind 0.0.0.0:8080 wsgi:app    # prod
```

## Register it with Plex

1. **Settings → Metadata Agents → Add Provider**, enter the provider URL:
   `http://<host>:8080/scenes`
2. **Add Agent** — name it (e.g. "ThePornDB Scenes"), set the provider you just
   added as the **Primary** metadata source.
3. Create a **Movie** library, and in the **Advanced** pane pick your new agent.

Notes:
- PMS currently sends **unauthenticated** requests to custom providers. Keep the
  service on your LAN; don't expose it publicly until Plex ships provider auth.
- HTTPS is not required. Plain HTTP on the LAN is fine.
- If "Metadata Agents" doesn't appear in Settings, restart the Plex client app.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/scenes` | Provider manifest (`MediaProvider`) |
| POST | `/scenes/library/metadata/matches` | Match feature — search |
| GET | `/scenes/library/metadata/{ratingKey}` | Metadata feature |
| GET | `/scenes/library/metadata/{ratingKey}/images` | Artwork list |
| GET | `/health` | Liveness |

GUIDs are emitted as `tv.plex.agents.custom.theporndb.scenes://movie/{ratingKey}`,
where `ratingKey` is the TPDB scene id.

## Configuration

All configuration is environment variables — the new provider API has no Plex-side
preferences UI, so the old `DefaultPrefs.json` settings moved here. See
`.env.example` for the full list with defaults.

| Variable | Old pref | Notes |
|---|---|---|
| `TPDB_API_KEY` | `personal_api_key` | Required |
| `TPDB_IDENTIFIER` | — | Must start with `tv.plex.agents.custom.`; suffix is `[a-zA-Z0-9.]` only |
| `TPDB_MATCH_BY_FILENAME` | `match_by_filepath_enable` | Now defaults on — PMS sends `filename` in match hints |
| `TPDB_STRIP_PATH` | `filepath_strip_path_enable` | |
| `TPDB_CLEANUP_ENABLE` / `_REGEX` / `_REPLACE` | `filepath_cleanup*` | Comma-separated regexes |
| `TPDB_SCORE_METHOD` | `score_method` | `default` or `custom` |
| `TPDB_CUSTOM_SCORE` | `custom_score` | `{title}` `{site}` `{date}` |
| `TPDB_COLLECTIONS_FROM_SITE/PARENTS/NETWORKS/TAGS` | `collections_from_*` | |
| `TPDB_COLLECTION_*_PREFIX` | `collection_*_prefix` | |
| `TPDB_CUSTOM_TITLE_ENABLE` / `TPDB_CUSTOM_TITLE` | `custom_title*` | `{title}` `{actors}` `{studio}` `{series}` |
| `TPDB_SAVE_TO_COLLECTION` | `save_to_collection` | Marks scenes collected on TPDB |
| `TPDB_CONTENT_RATING` | — | Defaults to `XXX` |
| `TPDB_CACHE_TTL` | — | In-process response cache, seconds; `0` disables |

Dropped: `oshash_matching_enable` (PMS does not send an OpenSubtitles hash in
match hints — the `hash` field is still honoured if it ever appears),
`import_trailer` (trailers are exposed as an `Extras` entry unconditionally),
`logging_level` → `TPDB_LOG_LEVEL`.

## Matching behaviour

1. If the request carries a provider `guid`, or the title/filename contains
   `[TPDBID=...]` or a `theporndb.net/scenes/...` URL, the scene is fetched
   directly and scored 100.
2. Otherwise the filename (path and extension stripped, cleanup regexes applied)
   or the title is sent to `/scenes?parse=`, with the year appended when known.
3. Results are scored and sorted. `manual: 1` requests return the full result
   set; automatic matches are capped at `X-Plex-Container-Size`.

As before, filenames in the form `Site YYYY-MM-DD Title` match best.

## Tests

```bash
python tests/test_provider.py
```

Twelve tests covering the manifest shape, all three match paths, pagination,
metadata mapping, sparse upstream payloads, and 404 handling. Upstream is
stubbed — no API token needed.

## Changes from the bundle

- Python 3, Flask, runs as a service instead of inside PMS.
- Fixed the retry loop: backoff is now exponential (the bundle's
  `sleep_time = sleep_time * x` evaluated to 0 on the first retry, and the
  leaked `str_error` was never cleared between attempts, so one failure poisoned
  the remaining tries).
- TLS verification is on. The bundle used `verify=False` with the warning muted.
- No bare `except:`. Missing upstream fields (`description`, `date`, `posters`,
  `background`) no longer raise — the bundle indexed them unguarded.
- Bundled `requests`/`urllib3`/`idna` vendored copies are gone; pinned in
  `requirements.txt` instead.

## Not done yet

Movies and JAV. They are the same shape with a different upstream path
(`/movies`, `/jav`) and their own provider identifier — the blueprint in
`tpdb_provider/app.py` is parameterisable when you want them.
