# Validation

47 application tests pass locally on Python 3.13.7 / Windows. Tests use temporary folders, fixture schedules, and mocked provider responses. They cover naming, date/team verification, leading-zero weeks, UFC shared folders, all-card arrival order, duplicate protection, source change detection, verified copy success/failures/recovery, SQLite history, polling, API authentication/parsing, Sportarr payloads, Pushover retries/body formatting, and file-error paths.

The user has reported successful live NFL processing on QNAP NFS, including verified-copy fallback, deletion from DOWNLOAD, and Pushover completion delivery. The configured UID/GID 500:100 was confirmed to fix Windows SMB write access to new folders. These observations are not a substitute for a clean test on another NAS.

Docker is not installed locally. GitHub Actions is configured to run the test suite on Linux and Windows, validate Compose, build a Linux container, test live authenticated health/jobs endpoints, and publish amd64/arm64 images only if checks pass. The HTTP unit test itself uses an in-memory connection. See GitHub Actions results for CI verification of this release; no local Docker result is claimed.

After upgrading, preserve existing application data and credentials. Check /health reports the release version, correct directories, and the intended dry-run mode. Preview a disposable video copy before enabling moves. Wait for completed status, verify both output names, incoming removal, and notification. Test UFC cards arriving before/after the main card separately. Do not rename destination folders while verification runs.

Provider coverage, live Sportarr webhook delivery, and ARM deployment should still be verified for the individual installation. Future artwork/Plex features are not represented as tested or implemented.
