# Sports Organizer

<img src="assets/logo.png" alt="Sports Organizer" width="160">

Organize completed NFL and UFC video copies into consistently named event folders on a NAS. Accepts Sportarr completion webhooks, offers polling, exposes an authenticated JSON API, and sends Pushover notifications after successful moves.

**Source version: 1.2.1.** Optional NFL poster and Plex metadata automation is available.

## Folder routes and naming

| Content | Linux host (example) | Container input | Container destination |
| --- | --- | --- | --- |
| NFL | `/mnt/nfl` | `/nfl/DOWNLOAD` | `/nfl/CHIEFS` |
| UFC | `/mnt/ufc` | `/ufc/DOWNLOAD` | `/ufc/COMPLETE` |

Names are case-sensitive. Each parent is mounted once, exposing both incoming and finished folders on the same mount.

```text
CHIEFS/
  2026 - Week 09 - Jets at Chiefs/
    2026 - Week 09 - Jets at Chiefs.mkv
  2023 - AFC Wildcard - Dolphins at Chiefs/
    2023 - AFC Wildcard - Dolphins at Chiefs.mkv
  2022 - Super Bowl 57 - Chiefs at Eagles/
    2022 - Super Bowl 57 - Chiefs at Eagles.mkv

COMPLETE/
  UFC 103 Franklin vs. Belfort (2009)/
    UFC 103 Franklin vs. Belfort (2009).mkv
    Early Prelims-featurette.mkv
    Prelims-featurette.mp4
```

Extensions are preserved. UFC cards can arrive in any order. Existing cards are not replaced, including duplicates with different extensions. Existing NFL event folders are not merged or overwritten.

## Inputs

Use this same Sportarr naming template for both leagues:

```text
{Series} - {Season}{Episode}{Part} - {Event Title} - {Event Date} - {Sportarr Id}
```

NFL examples:

```text
NFL - S2026E175 - Kansas City Chiefs vs New York Jets - 2026-11-08 - sportarr-ev-1969822.mkv
nfl.2026.11.08.new.york.jets.vs.kansas.city.chiefs.mkv
```

Sportarr names (recognized by the season/episode code or Sportarr ID) use **Home vs Away**. Original release names use **Away vs Home**. Explicit **Away at Home** is supported. Output is always **Away at Home**, verified against the game date and teams. Dates must include year, month, and day, such as YYYY-MM-DD or YYYY.MM.DD. Season/episode codes and IDs do not determine NFL weeks. The schedule supplies season year, week, and playoff round. Unrecognized, preseason, ambiguous, or unsupported historical games stay in review. The default schedule begins in 1999.

UFC titles must include the real PPV event number, for example `UFC 103 Franklin vs. Belfort`; `S2009E175` alone is not an event number. TMDB provides the main event's canonical title/year. Main-card filenames must contain its fighter names. Written `Early Prelims`/`Prelims` markers or Sportarr `pt1`/`pt2`/`pt3` are supported, attached to the episode code or separated. pt1 is early prelims, pt2 prelims, pt3 main card. Conflicting markers go to review. Fight Nights are not supported.

Supported extensions: mkv, mp4, avi, mov, m4v, ts, m2ts, webm. Only flat incoming files are processed; nested downloads, hidden files, symlinks, and `.part` files are skipped.

## Install with Portainer

The [portainer-stack.yaml](portainer-stack.yaml) uses the published image, with no local build required:

```text
ghcr.io/dbowles1975/sports-organizer:latest
```

Use `:1.1.4` to pin the release. Images are built for amd64 and arm64. A private package requires GHCR credentials in Portainer; source repository visibility and image package visibility are separate.

1. Mount the NAS parents on the Docker host. Confirm the four input/destination folders exist before deployment. Bind mounts refuse to create missing source directories, but an existing mountpoint alone does not prove the NAS is mounted.
2. Create a local application-data directory, for example `/home/dave/sports-organizer/data`. Keep SQLite state on local Linux storage, not NFS/SMB.
3. Set its ownership to the container user. Defaults are UID 500 and GID 100 for the confirmed QNAP setup; use IDs matching your own NAS account on other systems.
4. Paste the stack, set the variables below, and deploy with image pulling enabled. Start with `DRY_RUN=true`.

```sh
mkdir -p /home/dave/sports-organizer/data
sudo chown 500:100 /home/dave/sports-organizer/data
```

| Variable | Purpose/default |
| --- | --- |
| `API_TOKEN` | Required random organizer API token, minimum 24 characters; not a Sportarr key |
| `DATA_HOST_PATH` | Required absolute existing LOCAL data directory |
| `NFL_HOST_PATH` / `UFC_HOST_PATH` | Host NAS parents, `/mnt/nfl` and `/mnt/ufc` |
| `PUID` / `PGID` | Container identity, 500 / 100 |
| `API_PORT` | Host port 8383; container port stays 8080 |
| `API_BIND_ADDRESS` | 127.0.0.1 by default; set a specific LAN IP only if direct LAN access is needed |
| `WATCH_MODE` | webhook (default), poll, or both |
| `DRY_RUN` | true by default; previews only, no file movement or completion push |
| `POLL_SECONDS` / `STABLE_SECONDS` | 30 / 120 |
| `TMDB_READ_ACCESS_TOKEN` | TMDB API Read Access Token, required for UFC |
| `PUSHOVER_ENABLED` | false by default |
| `PUSHOVER_USER_KEY` / `PUSHOVER_API_TOKEN` | User key and Pushover application token |
| `SPORTS_ORGANIZER_IMAGE` | Optional image override; defaults to GHCR latest |

The four container-side routes are independently configurable with NFL_INCOMING_DIR, NFL_DESTINATION_DIR, UFC_INCOMING_DIR, and UFC_DESTINATION_DIR. Defaults match the table above.

Generate a token without posting it in a chat:

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

For command-line Compose, clone/download the repository, copy `.env.example` to `.env`, edit private values, then run `docker compose config --quiet`, `docker compose pull`, and `docker compose up -d`. Keep `.env` private and out of Git. Build locally if desired with `docker build -t sports-organizer:local .` and set SPORTS_ORGANIZER_IMAGE=sports-organizer:local; do not attempt to pull that local-only tag.

## Upgrade the existing local installation

Keep the current mounts, credentials, UID/GID, data directory, port, and network settings. Change only the image to the GHCR tag, remove any `build: .` and `pull_policy: never`, and redeploy with pulling enabled. Never replace the live `.env` with example settings. Stop the service before backing up its local data directory. A container restart alone does not load a newly pulled image: recreate/redeploy it.

Health and startup logs identify the image version. Existing completed files are not renamed; review/previewed jobs still need explicit retry. A failed notification does not undo a successful move. To pause processing, stop the container.

## NFL posters and Plex metadata

Build on the Docker host from this directory:

```sh
docker build -t sports-organizer:1.2.1-local .
```

In the existing Portainer stack set `SPORTS_ORGANIZER_IMAGE=sports-organizer:1.2.1-local`
(or replace the current image value if it is literal). Add the following environment
entries to the service if deploying from an older stack definition. Keep the current
mounts, network, and data directory. Disable the option to pull the image when
redeploying a locally built tag.

| Setting | Value |
| --- | --- |
| `GAME_THUMBS_URL` | Base URL reachable by Sports Organizer, including the port if needed. |
| `PLEX_URL` | Plex server base URL reachable by Sports Organizer, such as `http://192.168.50.10:32400`. |
| `PLEX_TOKEN` | Plex server-owner token. Store privately. |
| `PLEX_NFL_LIBRARY_ID` | Numeric section ID for the NFL **Movies** library. Plex Web can show it as `source=server://…/library/sections/ID` or `key=/library/sections/ID` in the URL. |
| `PLEX_NFL_ROOT` | NFL destination as seen by Plex. Defaults to `/nfl/CHIEFS`. |

Configure Game Thumbs, Plex, or both. Providers run for completed NFL moves with
`DRY_RUN=false`. Game Thumbs uses style 99 and saves JPEG or PNG artwork alongside
the video. The Plex update finds the movie by its full mapped file path, requests
a folder scan if needed, and writes the title, sort title, game date, rating and
studio. The Edition removes the leading season year. The Summary includes
spoiler-free game details, with Wikipedia kickoff, conditions, attendance,
referee, and TV announcers for Chiefs games when available. Chiefs games add the
opponent and Kansas City's starting quarterback to existing Collections when
the data is available. Existing locked fields and artwork are preserved, with
previously generated basic summaries eligible for the fuller preview. The library must use
the Movies type. Optional artwork and metadata failures appear separately from the
completed move in job history.

To update one previously completed game, look up its ID in `GET /jobs` and call
`POST /jobs/ID/retry-metadata` with the organizer API token. The job must still
reference the existing video. There is no need to re-download or move the video.

```sh
read -rsp 'Sports Organizer API token: ' ORGANIZER_TOKEN
printf '\n'
JOB_ID=123
curl --fail-with-body --max-time 10 -X POST \
  -H "Authorization: Bearer $ORGANIZER_TOKEN" \
  "http://127.0.0.1:8383/jobs/$JOB_ID/retry-metadata"
unset ORGANIZER_TOKEN
```

In the job response, `status` tracks the move and `metadata` tracks enrichment.
Use `GET /jobs/ID` to check for `metadata=completed` or read `metadata_error`.
Transient failures retry with backoff. Manual retry can be used after a failure.

## QNAP permissions

The working setup uses **Squash root users**, not Squash all users, for the organizer host's NFL/UFC NFS access; anonymous IDs remain at guest defaults. The container runs as the same numeric NAS account used for Windows SMB access, 500:100 in this installation. This prevents new 755 event folders from being created under the wrong owner. Other shares should retain their intended policies.

Changing container identity or squash does not repair older guest-owned folders. Correct only affected folders in QNAP File Station. Keep LOCAL data ownership aligned too. Confirm with `docker exec sports-organizer id`. Do not broadly reset library permissions just to fix one folder.

## Sportarr and completion webhooks

This service processes **separate completed staging copies**. Do not move Sportarr-managed originals or torrent seeding files. Sportarr sends a completed-import Download event with an episodeFile object; this service extracts the basename and looks only inside the chosen staging directory. It never operates directly on a managed-library path supplied in the webhook. The staged copy must already be finished and use that same filename.

In Sportarr Settings > Notifications, add POST Webhook connections scoped to the appropriate leagues/tags:

```text
http://sports-organizer:8080/webhooks/sportarr/nfl
http://sports-organizer:8080/webhooks/sportarr/ufc
```

Add custom headers:

```json
{"Authorization":"Bearer YOUR_ORGANIZER_API_TOKEN"}
```

Leave Basic Auth blank. Test events are acknowledged without queueing files; other non-Download events are ignored. The containers need a shared Docker network to use that hostname. Keep existing network settings when migrating stacks. For different Compose stacks, create a shared external network and attach both containers. Host port 8383 does not change internal port 8080.

If a separate copy finishes after Sportarr's notification, call `/webhooks/complete` from that copy step, or use polling. `notify_complete.py` is a Python 3 helper using API_TOKEN and ORGANIZER_URL from its environment:

```sh
export ORGANIZER_URL=http://127.0.0.1:8383
python3 notify_complete.py nfl '/mnt/nfl/DOWNLOAD/filename.mkv'
```

Call only after the file is closed and finished. Prefer copying as `filename.mkv.part`, then renaming to the final extension and sending the callback. Completion requests bypass the polling wait because the sender asserts completion, but the source fingerprint is checked again before movement.

## Polling

`WATCH_MODE=both` accepts webhooks and polls, useful for manually placed files. A file must remain unchanged for STABLE_SECONDS and have an old enough modification time. Waiting restarts after container startup. A paused transfer can look stable, so `.part`-then-rename is preferred. Default timing means roughly 2-3 minutes after completion before automatic queueing.

Polling deduplicates unchanged files: putting back the same file may return an existing review job rather than queue another move. Retry that job explicitly. A changed source creates a new job. `POST /scan` is only one stability observation; in webhook-only mode it needs another observation after the interval.

## API

All endpoints require `Authorization: Bearer <API_TOKEN>`. Use http://127.0.0.1:8383 from the Docker host, or your configured reachable host address. A normal browser address-bar visit does not attach a bearer token. JSON request bodies are limited to 8192 bytes.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/health` | Version, mode, worker, directory status; does not validate provider credentials |
| GET | `/jobs` | Latest 100 jobs including errors and notifications |
| GET | `/jobs/ID` | One job |
| POST | `/preview` | JSON sport and filename; proposed name/path without moving |
| POST | `/webhooks/complete` | sport, filename, transfer_complete=true |
| POST | `/webhooks/sportarr/nfl` | Native Sportarr NFL payload |
| POST | `/webhooks/sportarr/ufc` | Native Sportarr UFC payload |
| POST | `/scan` | One stability observation |
| POST | `/jobs/ID/retry` | Retry review/previewed job; source must exist and match |

```sh
curl --show-error --max-time 10 -H "Authorization: Bearer YOUR_API_TOKEN" http://127.0.0.1:8383/health

curl --show-error --max-time 10 -H "Authorization: Bearer YOUR_API_TOKEN" -H 'Content-Type: application/json' --data '{"sport":"ufc","filename":"UFC.103.Franklin.vs.Belfort.mkv"}' http://127.0.0.1:8383/preview

curl --show-error --max-time 10 -X POST -H "Authorization: Bearer YOUR_API_TOKEN" http://127.0.0.1:8383/jobs/4/retry
```

Queued means accepted, not completed. States are queued, previewed, moving, completed, review. Notification states are tracked separately. Keep this small HTTP API on a trusted private network; use a TLS reverse proxy for other access.

## Move safety and recovery

Protected same-filesystem renames are attempted first. If unsupported by a NAS mount, the service creates an exclusive destination, copies in chunks, flushes, verifies SHA-256 content, checks the source did not change, journals the result, and only then removes the incoming file. Cross-filesystem routes are refused. Destination duplicates never silently replace files.

The fallback takes longer and temporarily needs enough space for another copy. Its final filename is visible during transfer. **Do not rename, delete, or consume the destination until the job is completed or a success notification arrives.** A full-size destination can still be undergoing verification.

Detected copy failures retain the source and attempt to remove only the new failed destination. Crashes or external folder renames can leave both files: uncertain recovery states remain in review rather than deleting either copy. Check both before cleanup. Recovery history lives in local SQLite; preserve it during updates.

Completion pushes use Sports Organizer as the heading and event/path details in the body. Failures retry up to five times with delays, independently of the successful video move. Timeouts can cause duplicate notifications. Notification-type selection and errors-only pushes remain planned.

NFL schedules cache for six hours (offline fallback supported), TMDB search results for 24 hours. To force refresh, stop the service and remove only the relevant cache file, not SQLite history. Retry the affected job afterward.

## Development and releases

Python 3.13+, no external Python dependencies:

```sh
python -m unittest discover -s tests -v
```

GitHub Actions runs tests on Linux and Windows, builds and smoke-tests a real Linux container, then publishes amd64/arm64 images. Successful main builds publish latest, version, and SHA tags. If that version has no release yet, the workflow creates one with release notes and a source ZIP. Bump organizer.VERSION and update RELEASE_NOTES.md for a new release. Pull requests test without publishing images or releases.

Do not include real credentials, SQLite state, NAS files, or runtime logs in commits. [TESTING.md](TESTING.md) distinguishes application tests, CI checks, and user-reported NAS verification. [RELEASE_NOTES.md](RELEASE_NOTES.md) describes this release; [ROADMAP.md](ROADMAP.md) records future features.

## Artwork and data sources

- [nflverse schedules](https://github.com/nflverse/nfldata/blob/master/data/games.csv).
- [TMDB API](https://developer.themoviedb.org/reference/search-movie). This product uses the TMDB API but is not endorsed or certified by TMDB.
- [Pushover API](https://pushover.net/api). Upload [the 128x128 transparent icon](assets/pushover-icon-128.png) in your application's settings.
- [Sportarr naming](https://wiki.sportarr.net/features/file-naming/) and [notifications](https://wiki.sportarr.net/features/notifications/).

TheSportsDB artwork remains on the roadmap.
