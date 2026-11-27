# Project roadmap

Checked items are implemented. Unchecked items are planned and are not included in the running service yet.

## Working organizer

- [x] Docker service, authenticated API, health, job history, previews, scans, retries.
- [x] Sportarr webhooks and optional polling of completed single-video staging copies.
- [x] NFL Home vs Away Sportarr input converted to Away at Home output, using actual schedule dates.
- [x] Season year, two-digit weeks, conference playoff rounds, numeric Super Bowl editions.
- [x] UFC title/year lookup through TMDB; early prelims and prelims in the main event folder.
- [x] Protected moves, NAS verified-copy fallback, restart journal, existing destination protection.
- [x] QNAP account defaults UID 500 / GID 100 (configurable).
- [x] Pushover completion messages with retries and Sports Organizer as the heading.
- [x] Sports Organizer logo and 128x128 transparent Pushover icon.
- [x] GitHub build/release workflow and GHCR image deployment definitions.

## Dashboard and usability

- [x] Authenticated web dashboard backed by the existing API.
- [ ] Logo in the dashboard and favicon derived from the transparent icon.
- [ ] Copy/verification byte progress and clear per-stage status.
- [ ] Job previews, errors, retry buttons, filtering and history.
- [ ] Persistent settings, master notification switch, success/error selection, errors-only mode.
- [ ] Independent retry of artwork, Plex, and notification steps without moving videos again.
- [ ] Less routine health-check logging and more detailed failure-stage reporting.
- [ ] Safe configuration/history export without including credentials by default.

## NFL artwork

- [ ] Game Thumbs: configurable base URL; `/nfl/{away}/{home}/cover?style=99` with short names such as Jets/Chiefs.
- [ ] Save verified image content as `poster.jpg` beside the video.
- [ ] TheSportsDB game-specific landscape artwork, then home-team background fallback, as `background.jpg`.
- [ ] Preserve existing custom artwork by default; separate image failures from video-move success.
- [ ] Verify actual provider coverage and connectivity during implementation.

## NFL-only Plex integration

- [ ] Optional scan after video and artwork are ready; wait for discovery and match the exact mapped file path.
- [ ] Title and sort title equal filename without extension, retaining hyphens.
- [ ] Edition equals title with the season-year prefix removed (including postseason labels).
- [ ] Content rating `E`; studio `NFL`.
- [ ] Source a game recap summary with source attribution recorded.
- [ ] Collections: away team's short name, plus home team's actual starting QB's full name for that game.
- [ ] Preserve pre-existing collections; lock edited metadata fields where supported.
- [ ] Apply poster/background through Plex; retry failed metadata tasks independently.
- [ ] Stack settings for Plex URL, private token, library ID, and organizer-to-Plex path mapping.
- [ ] Keep UFC on its existing TMDB workflow. Edition changes require Plex Pass.

## Existing and historical media

- [ ] Read-only backfill preview, then explicit apply in resumable batches without moving existing files.
- [ ] Preserve manual metadata/artwork unless replacement is explicitly selected.
- [ ] Establish historical sources for games before 1999; do not assume modern playoff formats.
- [ ] Historical franchise names and actual home starting QB; flag missing/ambiguous records instead of guessing.
- [ ] Test representative games across decades before processing the full collection.

## Input workflow

Sportarr standardizes downloaded releases. Sports Organizer processes separate completed library copies, not active torrent seeding data. Direct `.torrent` downloading and hardlink seeding management are outside the implemented scope.
