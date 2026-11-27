# Sports Organizer 1.3.1

- Adds the authenticated `GET /jobs/summary` endpoint for completed and active job totals in compact dashboard widgets.

## Sports Organizer 1.3.0

- Adds a web dashboard for service health, rename previews, job history, and retries.
- Adds read-only Plex previews and selected updates for existing Chiefs games. Backfill preserves video files, existing posters and collections, and manually entered metadata.
- Keeps the existing data mount and API token when upgrading.

## Sports Organizer 1.2.1

- Adds Plex Edition without the season-year prefix.
- Adds spoiler-free NFL summaries with Wikipedia game details for Chiefs games when available, and nflverse as a fallback.
- Adds the opponent and Kansas City's actual starting quarterback to Plex Collections while preserving existing entries.
- Supports metadata retries on completed games without moving the video again.

## Sports Organizer 1.1.4

First GitHub/GHCR release of the previously tested local organizer.

- NFL Sportarr Home vs Away inputs produce Away at Home titles, verified against the schedule.
- Two-digit regular-season weeks in both folder and video names.
- Postseason labels, season-year handling, and numeric Super Bowl names.
- UFC TMDB titles and years; main card, early prelims, and prelims share one event folder.
- NAS verified-copy fallback when protected atomic rename is unsupported; source removed only after verification.
- QNAP-compatible UID 500 / GID 100 defaults, configurable for other NAS accounts.
- Pushover messages now use Sports Organizer as the title and put completion details in the body.
- File-operation errors include the affected path when available.
- Container publishing for linux/amd64 and linux/arm64; test suite runs on Linux and Windows.
- Portainer-ready stack, source archive, logo assets, and explicit roadmap.

## Upgrade from the locally built image

Preserve the existing local application-data directory, NAS mounts, and private credentials. In the existing stack, replace the local image with `ghcr.io/dbowles1975/sports-organizer:1.1.4` (or `:latest`), remove `build: .` and `pull_policy: never` if present, and redeploy with image pulling enabled. Keep user 500:100 and host port 8383.

If the GHCR package is private, configure Portainer registry authentication or make the image package public from its GitHub package settings. The source repository's visibility does not necessarily determine image-package visibility.

The first startup adds no new NAS operations by itself. Existing review/previewed jobs require explicit retry. Do not rename destination folders during copy/verification; wait for completed status or the success notification.

## Not included yet

See ROADMAP.md for remaining work.
