"""NAS sports organizer. Python 3.13+, standard library only."""
import csv
import ctypes
import errno
import hmac
import hashlib
import io
import json
import logging
import os
import re
import signal
import sqlite3
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG = logging.getLogger("organizer")
VERSION = "1.1.4"
VIDEOS = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".ts", ".m2ts", ".webm"}
SCHEDULE_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"


def normalized(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def safe_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', value)
    value = " ".join(value.split()).strip(" .")
    if not value or len(value.encode()) > 220:
        raise ValueError("Resulting name is empty or too long")
    return value


# Full names, common abbreviations, and franchise aliases.
TEAM_ROWS = [
    ("ARI", "Cardinals", "Arizona Cardinals|Phoenix Cardinals"),
    ("ATL", "Falcons", "Atlanta Falcons"),
    ("BAL", "Ravens", "Baltimore Ravens"),
    ("BUF", "Bills", "Buffalo Bills"),
    ("CAR", "Panthers", "Carolina Panthers"),
    ("CHI", "Bears", "Chicago Bears"),
    ("CIN", "Bengals", "Cincinnati Bengals"),
    ("CLE", "Browns", "Cleveland Browns"),
    ("DAL", "Cowboys", "Dallas Cowboys"),
    ("DEN", "Broncos", "Denver Broncos"),
    ("DET", "Lions", "Detroit Lions"),
    ("GB", "Packers", "Green Bay Packers"),
    ("HOU", "Texans", "Houston Texans"),
    ("IND", "Colts", "Indianapolis Colts|Baltimore Colts"),
    ("JAX", "Jaguars", "Jacksonville Jaguars|JAC"),
    ("KC", "Chiefs", "Kansas City Chiefs"),
    ("LA", "Rams", "Los Angeles Rams|St Louis Rams|St. Louis Rams|LAR|STL"),
    ("LAC", "Chargers", "Los Angeles Chargers|San Diego Chargers|SD"),
    ("LV", "Raiders", "Las Vegas Raiders|Oakland Raiders|Los Angeles Raiders|OAK"),
    ("MIA", "Dolphins", "Miami Dolphins"),
    ("MIN", "Vikings", "Minnesota Vikings"),
    ("NE", "Patriots", "New England Patriots"),
    ("NO", "Saints", "New Orleans Saints"),
    ("NYG", "Giants", "New York Giants"),
    ("NYJ", "Jets", "New York Jets"),
    ("PHI", "Eagles", "Philadelphia Eagles"),
    ("PIT", "Steelers", "Pittsburgh Steelers"),
    ("SEA", "Seahawks", "Seattle Seahawks"),
    ("SF", "49ers", "San Francisco 49ers"),
    ("TB", "Buccaneers", "Tampa Bay Buccaneers"),
    ("TEN", "Titans", "Tennessee Titans|Tennessee Oilers|Houston Oilers|Oilers"),
    ("WAS", "Commanders", "Washington Commanders|Washington Football Team|Washington Redskins"),
]
TEAMS = {}
SHORT = {}
for code, short, aliases in TEAM_ROWS:
    SHORT[code] = short
    for alias in [code, short, *aliases.split("|")]:
        TEAMS[normalized(alias)] = code
AFC = set("BAL BUF CIN CLE DEN HOU IND JAX KC LAC LV MIA NE NYJ PIT TEN".split())


def team(value):
    key = normalized(value)
    if key not in TEAMS:
        raise ValueError(f"Unknown NFL team: {value}")
    return TEAMS[key]


def is_sportarr_filename(filename):
    return bool(re.search(r"(?i)(?<![a-z0-9])s\d{4}e\d+|sportarr[ ._-]+ev[ ._-]+\d+", Path(filename).stem))


def nfl_parts(filename):
    stem = Path(filename).stem.replace("\\", "")
    if not re.match(r"(?i)^nfl(?=[ ._-])", stem):
        raise ValueError("NFL filename must start with NFL")
    date_pattern = r"(?<!\d)(\d{4})[ ._-](\d{2})[ ._-](\d{2})(?!\d)"
    dates = {date(*(int(part) for part in parts)).isoformat() for parts in re.findall(date_pattern, stem)}
    if len(dates) != 1:
        raise ValueError("NFL filename must include one game date (YYYY-MM-DD) and both teams; Sportarr episode numbers are not weeks")
    # Dates and Sportarr's season/episode codes may appear before or after the
    # event title. Strip dates, then match complete team aliases beside vs/at.
    words = normalized(re.sub(date_pattern, " ", stem))
    pairs = set()
    for separator in re.finditer(r"\s+(?:vs|at)\s+", words):
        left, right = words[:separator.start()], words[separator.end():]
        away = [key for key in TEAMS if left == key or left.endswith(" " + key)]
        home = [key for key in TEAMS if right == key or right.startswith(key + " ")]
        if away and home:
            first, second = TEAMS[max(away, key=len)], TEAMS[max(home, key=len)]
            # Sportarr event titles are Home vs Away. Explicit 'at' and
            # original release names remain Away at/vs Home.
            if is_sportarr_filename(filename) and separator.group().strip() == "vs":
                first, second = second, first
            pairs.add((first, second))
    if len(pairs) != 1:
        raise ValueError("NFL filename must contain one recognizable two-team matchup")
    away, home = pairs.pop()
    if away == home:
        raise ValueError("NFL away and home teams must differ")
    return dates.pop(), away, home


def nfl_title(filename, rows):
    gameday, away, home = nfl_parts(filename)
    matches = []
    for row in rows:
        if row["gameday"] != gameday:
            continue
        try:
            # Super Bowl venue designations need not match the user's filename order.
            ordered = (team(row["away_team"]), team(row["home_team"])) == (away, home)
            neutral = row["game_type"] == "SB" and {team(row["away_team"]), team(row["home_team"])} == {away, home}
            if ordered or neutral:
                matches.append(row)
        except ValueError:
            continue
    if len(matches) != 1:
        raise ValueError("No unique schedule match for that date and those teams")
    row = matches[0]
    if is_sportarr_filename(filename):
        # Use the schedule's official away/home designations for neutral-site
        # games too; Sportarr's display order must never dictate output order.
        away, home = team(row["away_team"]), team(row["home_team"])
    season = int(row["season"])
    kind = row["game_type"]
    if kind == "REG":
        label = f"Week {int(row['week']):02d}"
    elif kind == "SB":
        label = f"Super Bowl {season - 1965}"
    elif kind in {"WC", "DIV", "CON"}:
        if (away in AFC) != (home in AFC):
            raise ValueError("Conference mismatch in playoff game")
        conference = "AFC" if away in AFC else "NFC"
        label = conference + " " + {"WC": "Wildcard", "DIV": "Divisional", "CON": "Championship"}[kind]
    else:
        raise ValueError(f"Unsupported game type: {kind}")
    return safe_name(f"{season} - {label} - {SHORT[away]} at {SHORT[home]}")


def ufc_number(filename):
    numbers = {int(value) for value in re.findall(r"(?i)(?<![a-z0-9])ufc[ ._-]+(?:ppv[ ._#-]*)?(\d+)(?=[ ._:-]|$)", Path(filename).stem)}
    if len(numbers) != 1:
        raise ValueError("UFC filename must include one explicit PPV event number, such as UFC 103; Sportarr episode numbers are not event numbers")
    return numbers.pop()


def ufc_part(filename):
    stem = Path(filename).stem
    words = normalized(stem)
    label = None
    if re.search(r"\bearly\s*(?:prelims?|preliminary)(?:\s+card)?\b", words):
        label = "Early Prelims-featurette"
    elif re.search(r"\b(?:prelims?|preliminary)(?:\s+card)?\b", words):
        label = "Prelims-featurette"
    parts = {int(value) for value in re.findall(r"(?i)(?:\bs\d+e\d+[ ._-]*|(?<![a-z0-9]))pt[ ._-]*(\d+)(?!\d)", stem)}
    if not parts:
        return label
    if len(parts) != 1 or not parts <= {1, 2, 3}:
        raise ValueError("Unknown or conflicting UFC part markers; expected pt1, pt2, or pt3")
    numbered = {1: "Early Prelims-featurette", 2: "Prelims-featurette", 3: None}[parts.pop()]
    if label is not None and label != numbered:
        raise ValueError("UFC part marker conflicts with prelim label; needs review")
    return numbered


def verified_copy_move(source, destination, record_copy=None):
    """NAS fallback: exclusively create, verify bytes, journal, then unlink."""
    before = source.stat()
    signature = lambda stat: (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    created = False
    try:
        with source.open("rb") as incoming:
            with destination.open("x+b") as output:
                created = True
                digest = hashlib.sha256()
                while block := incoming.read(4 * 1024 * 1024):
                    output.write(block)
                    digest.update(block)
                output.flush()
                os.fsync(output.fileno())
                output.seek(0)
                copied = hashlib.file_digest(output, "sha256").digest()
                if copied != digest.digest() or os.fstat(output.fileno()).st_size != before.st_size:
                    raise ValueError("NAS copy verification failed; incoming file retained")
        if signature(source.stat()) != signature(before):
            raise ValueError("Incoming file changed during copy; incoming file retained")
        if record_copy:
            record_copy(destination)
        source.unlink()
    except Exception:
        # Never remove a destination that existed before this operation.
        if created:
            try:
                destination.unlink()
            except OSError:
                pass  # Any remaining partial copy is retained for review.
        raise


def rename_no_replace(source, destination, record_copy=None):
    """Atomic rename without replacing a file created by another writer."""
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            verified_copy_move(source, destination, record_copy)
            return
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
            code = ctypes.get_errno()
            if code in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
                LOG.info("Protected rename unavailable; using verified copy-and-remove for %s", destination.name)
                verified_copy_move(source, destination, record_copy)
                return
            raise OSError(code, os.strerror(code), str(destination))
    elif os.name == "nt":
        source.rename(destination)  # Windows rename refuses an existing destination.
    else:
        raise ValueError("Protected moves require Linux or Windows")


def ufc_title(filename, results):
    number = ufc_number(filename)
    candidates = []
    for movie in results:
        title = movie.get("title", "")
        match = re.match(r"(?i)^UFC\s+(\d+)\b\s*[:\-–—]?\s*(.*)$", title)
        if not match or int(match[1]) != number:
            continue
        # Main card only; separate preliminary-card entries must not win a match.
        if re.search(r"(?i)\b(prelims?|preliminary|countdown|weigh.?in|press conference)\b", title):
            continue
        suffix = re.sub(r"(?i)\s+vs\.?\s+", " vs. ", match[2]).strip()
        release = movie.get("release_date", "")
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", release) or " vs. " not in suffix:
            continue
        candidates.append((movie, suffix, release[:4]))
    # Deduplicate paginated results by TMDB ID.
    candidates = list({str(item[0]["id"]): item for item in candidates}.values())
    if len(candidates) != 1:
        raise ValueError("No unique TMDB main-event match; needs review")
    movie, suffix, year = candidates[0]
    # Require each fighter named by TMDB to also appear in the incoming filename.
    incoming = set(normalized(Path(filename).stem).split())
    fighters = suffix.split(" vs. ")
    if ufc_part(filename) is None and not all(set(normalized(fighter).split()) <= incoming for fighter in fighters):
        raise ValueError("TMDB fighters do not match the incoming filename; needs review")
    return safe_name(f"UFC {number} {suffix} ({year})")


def request_json(url, *, headers=None, data=None):
    request = urllib.request.Request(url, headers=headers or {}, data=data)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


@dataclass
class Config:
    data: Path
    routes: dict
    token: str
    mode: str = "webhook"
    dry_run: bool = True
    stable_seconds: int = 120
    poll_seconds: int = 30
    tmdb_token: str = ""
    pushover_enabled: bool = False
    pushover_user: str = ""
    pushover_token: str = ""

    @classmethod
    def env(cls):
        return cls(
            Path(os.getenv("DATA_DIR", "/data")),
            {"nfl": (Path(os.getenv("NFL_INCOMING_DIR", "/nfl/DOWNLOAD")), Path(os.getenv("NFL_DESTINATION_DIR", "/nfl/CHIEFS"))),
             "ufc": (Path(os.getenv("UFC_INCOMING_DIR", "/ufc/DOWNLOAD")), Path(os.getenv("UFC_DESTINATION_DIR", "/ufc/COMPLETE")))},
            os.environ.get("API_TOKEN", ""),
            os.getenv("WATCH_MODE", "webhook"),
            os.getenv("DRY_RUN", "true").lower() == "true",
            int(os.getenv("STABLE_SECONDS", "120")),
            int(os.getenv("POLL_SECONDS", "30")),
            os.getenv("TMDB_READ_ACCESS_TOKEN", ""),
            os.getenv("PUSHOVER_ENABLED", "false").lower() == "true",
            os.getenv("PUSHOVER_USER_KEY", ""),
            os.getenv("PUSHOVER_API_TOKEN", ""),
        )


class Organizer:
    def __init__(self, config):
        self.c = config
        if len(config.token) < 24:
            raise ValueError("API_TOKEN must contain at least 24 characters")
        if config.mode not in {"webhook", "poll", "both"}:
            raise ValueError("WATCH_MODE must be webhook, poll, or both")
        if config.stable_seconds < 1 or config.poll_seconds < 1:
            raise ValueError("Polling and stability intervals must be positive")
        if config.pushover_enabled and not (config.pushover_user and config.pushover_token):
            raise ValueError("Pushover is enabled but credentials are missing")
        config.data.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(config.data / "history.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute('''CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY, sport TEXT NOT NULL, filename TEXT NOT NULL,
            fingerprint TEXT NOT NULL, status TEXT NOT NULL, title TEXT,
            destination TEXT, error TEXT, notification TEXT NOT NULL DEFAULT 'none',
            notify_attempts INTEGER NOT NULL DEFAULT 0, notify_after REAL NOT NULL DEFAULT 0,
            created REAL NOT NULL, updated REAL NOT NULL,
            UNIQUE(sport, filename, fingerprint))''')
        self.db.commit()
        if "destination_fingerprint" not in {row[1] for row in self.db.execute("PRAGMA table_info(jobs)")}:
            self.db.execute("ALTER TABLE jobs ADD COLUMN destination_fingerprint TEXT")
            self.db.commit()
        self.seen = {}
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.last_poll = 0
        self.worker_error = None
        self.thread = None
        self.schedule = None
        self.schedule_loaded = 0
        self.recover()

    def update(self, job_id, **values):
        values["updated"] = time.time()
        with self.lock:
            self.db.execute("UPDATE jobs SET " + ", ".join(k + "=?" for k in values) + " WHERE id=?",
                            [*values.values(), job_id])
            self.db.commit()

    def jobs(self, limit=100):
        with self.lock:
            return [dict(row) for row in self.db.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))]

    def get_job(self, job_id):
        with self.lock:
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise ValueError("Unknown job ID")
            return dict(row)

    def source(self, sport, filename):
        if sport not in self.c.routes:
            raise ValueError("sport must be nfl or ufc")
        if not isinstance(filename, str) or not filename or '/' in filename or '\\' in filename or filename in {'.', '..'}:
            raise ValueError("Supply a filename only, without directories")
        if filename.startswith('.') or Path(filename).suffix.lower() not in VIDEOS:
            raise ValueError("Not a supported video file")
        root = self.c.routes[sport][0]
        path = root / filename
        if path.is_symlink() or path.resolve().parent != root.resolve():
            raise ValueError("Symlinks and paths outside the incoming folder are not allowed")
        if not path.is_file():
            raise ValueError("File does not exist in the incoming folder")
        return path

    @staticmethod
    def fingerprint(path):
        stat = path.stat()
        if stat.st_size == 0:
            raise ValueError("Empty video file")
        return f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}"

    def enqueue(self, sport, filename):
        with self.lock:
            try:
                path = self.source(sport, filename)
            except ValueError:
                # A sender may retry after the first request moved the source.
                # Validate sport/name before looking up a completed job.
                if sport in self.c.routes and isinstance(filename, str) and '/' not in filename and '\\' not in filename:
                    missing = not (self.c.routes[sport][0] / filename).exists()
                    if missing:
                        row = self.db.execute("SELECT * FROM jobs WHERE sport=? AND filename=? AND status='completed' ORDER BY id DESC LIMIT 1",
                                              (sport, filename)).fetchone()
                        if row:
                            return dict(row)
                raise
            fp = self.fingerprint(path)
            now = time.time()
            self.db.execute("INSERT OR IGNORE INTO jobs(sport,filename,fingerprint,status,created,updated) VALUES(?,?,?,'queued',?,?)",
                            (sport, filename, fp, now, now))
            self.db.commit()
            row = self.db.execute("SELECT * FROM jobs WHERE sport=? AND filename=? AND fingerprint=?",
                                  (sport, filename, fp)).fetchone()
        self.wake.set()
        return dict(row)

    def schedule_rows(self):
        if self.schedule is not None and time.time() - self.schedule_loaded < 21600:
            return self.schedule
        cache = self.c.data / "nfl-schedule.csv"
        text = None
        if cache.exists() and time.time() - cache.stat().st_mtime < 21600:
            text = cache.read_text(encoding="utf-8")
        if text is None:
            try:
                with urllib.request.urlopen(SCHEDULE_URL, timeout=20) as response:
                    text = response.read(10_000_000).decode("utf-8-sig")
                rows = self.validate_schedule(text)
                temporary = cache.with_suffix(".tmp")
                temporary.write_text(text, encoding="utf-8")
                temporary.replace(cache)
            except Exception:
                if not cache.exists():
                    raise ValueError("NFL schedule unavailable and no cached schedule exists") from None
                LOG.warning("Using cached NFL schedule because refresh failed")
                text = cache.read_text(encoding="utf-8")
        self.schedule = self.validate_schedule(text)
        self.schedule_loaded = time.time()
        return self.schedule

    @staticmethod
    def validate_schedule(text):
        reader = csv.DictReader(io.StringIO(text))
        if not {"gameday", "season", "game_type", "week", "away_team", "home_team"} <= set(reader.fieldnames or []):
            raise ValueError("Invalid NFL schedule columns")
        rows = list(reader)
        if not rows:
            raise ValueError("Empty NFL schedule")
        return rows

    def title(self, sport, filename):
        if sport == "nfl":
            return nfl_title(filename, self.schedule_rows())
        if not self.c.tmdb_token:
            raise ValueError("TMDB_READ_ACCESS_TOKEN is required for UFC")
        number = ufc_number(filename)
        cache = self.c.data / f"tmdb-{number}.json"
        if cache.exists() and time.time() - cache.stat().st_mtime < 86400:
            results = json.loads(cache.read_text())
        else:
            results = []
            for page in range(1, 6):
                query = urllib.parse.urlencode({"query": f"UFC {number}", "language": "en-US", "page": page})
                data = request_json("https://api.themoviedb.org/3/search/movie?" + query,
                                    headers={"Authorization": "Bearer " + self.c.tmdb_token})
                results.extend(data.get("results", []))
                if data.get("total_pages", 1) <= page:
                    break
            else:
                raise ValueError("Too many TMDB results; needs review")
            temporary = cache.with_suffix(".tmp")
            temporary.write_text(json.dumps(results))
            temporary.replace(cache)
        return ufc_title(filename, results)

    def preview(self, sport, filename):
        with self.lock:
            path = self.source(sport, filename)
            title = self.title(sport, filename)
            part = ufc_part(filename) if sport == "ufc" else None
            destination = self.c.routes[sport][1] / title / ((part or title) + path.suffix)
            return {"sport": sport, "filename": filename, "title": title, "destination": str(destination),
                    "part": part or "main", "folder_exists": destination.parent.exists(), "dry_run": self.c.dry_run}

    @staticmethod
    def check_destination(sport, destination):
        folder = destination.parent
        if folder.is_symlink():
            raise ValueError("Destination folder cannot be a symlink")
        if folder.exists():
            if sport != "ufc" or not folder.is_dir():
                raise ValueError("Destination folder already exists; nothing overwritten")
            # One video per card, even if an alternate copy has another extension.
            if any(p.stem.casefold() == destination.stem.casefold() and p.suffix.lower() in VIDEOS for p in folder.iterdir()):
                raise ValueError("This UFC card already exists; nothing overwritten")
        if destination.exists() or destination.is_symlink():
            raise ValueError("Destination file already exists; nothing overwritten")

    def recover(self):
        # A journal entry is committed before the atomic move. Reconcile a crash
        # between the move and the subsequent database commit.
        for job in self.jobs(1_000_000):
            if job["status"] != "moving":
                continue
            source = self.c.routes[job["sport"]][0] / job["filename"]
            destination = Path(job["destination"])
            expected = job.get("destination_fingerprint") or job["fingerprint"]
            if not source.exists() and destination.is_file() and self.fingerprint(destination) == expected:
                self.update(job["id"], status="completed", error=None,
                            notification="pending" if self.c.pushover_enabled else "disabled")
            elif source.is_file() and not destination.exists():
                # UFC folders may hold other completed cards; retain them.
                if job["sport"] != "ufc":
                    try:
                        destination.parent.rmdir()
                    except OSError:
                        pass
                self.update(job["id"], status="queued", error=None)
            else:
                self.update(job["id"], status="review", error="Interrupted move needs review; no files changed during recovery")

    def process(self, job):
        job_id = job["id"]
        try:
            source = self.source(job["sport"], job["filename"])
            if self.fingerprint(source) != job["fingerprint"]:
                raise ValueError("File changed after completion was reported; submit again when finished")
            plan = self.preview(job["sport"], job["filename"])
            destination = Path(plan["destination"])
            self.check_destination(job["sport"], destination)
            self.update(job_id, title=plan["title"], destination=str(destination))
            if self.c.dry_run:
                self.update(job_id, status="previewed", error=None)
                return
            root = self.c.routes[job["sport"]][1]
            if not root.is_dir():
                raise ValueError("Destination root is missing; check the NAS mount")
            if root.resolve() != destination.parent.parent.resolve():
                raise ValueError("Destination escapes configured root")
            if source.stat().st_dev != root.stat().st_dev:
                raise ValueError("Source and destination must be on one mounted filesystem; check volume mappings")
            # Persist intent before changing the filesystem, allowing restart recovery.
            self.update(job_id, status="moving", error=None, destination_fingerprint=None)
            created_folder = False
            try:
                destination.parent.mkdir()
                created_folder = True
            except FileExistsError:
                if job["sport"] != "ufc":
                    raise
            if job["sport"] == "ufc":
                self.check_destination(job["sport"], destination)
            try:
                if self.fingerprint(source) != job["fingerprint"]:
                    raise ValueError("File changed during processing")
                rename_no_replace(source, destination,
                    lambda copied: self.update(job_id, destination_fingerprint=self.fingerprint(copied)))
            except Exception:
                if created_folder:
                    try:
                        destination.parent.rmdir()
                    except OSError:
                        pass
                raise
            self.update(job_id, status="completed", error=None,
                        notification="pending" if self.c.pushover_enabled else "disabled")
            LOG.info("Completed job %s: %s", job_id, destination)
        except Exception as exc:
            # If a rename already succeeded, keep 'moving' for recovery rather than
            # re-running it. A database failure here must never delete a video.
            current = self.get_job(job_id)
            if current["status"] == "moving" and current["destination"] and Path(current["destination"]).is_file():
                LOG.exception("Move journal needs recovery for job %s", job_id)
            else:
                self.update(job_id, status="review", error=self.error_text(exc))
                LOG.warning("Job %s needs review: %s", job_id, self.error_text(exc))

    @staticmethod
    def error_text(exc):
        # Provider exceptions can contain URLs; avoid persisting credentials.
        if isinstance(exc, urllib.error.HTTPError):
            return f"Metadata provider returned HTTP {exc.code}; check credentials or retry later"
        if isinstance(exc, ValueError):
            return str(exc)
        if isinstance(exc, OSError) and exc.filename:
            return f"{type(exc).__name__}: {exc.strerror or 'filesystem operation failed'}: {exc.filename}"
        if isinstance(exc, OSError):
            return f"{type(exc).__name__}: filesystem or network operation failed"
        return f"{type(exc).__name__}: processing failed"

    def notify(self, job):
        if not self.c.pushover_enabled:
            self.update(job["id"], notification="disabled")
            return
        try:
            data = urllib.parse.urlencode({"token": self.c.pushover_token, "user": self.c.pushover_user,
                "title": "Sports Organizer",
                "message": ("Completed: " + job["title"] + "\nMoved to:\n" + job["destination"])[:1000]}).encode()
            response = request_json("https://api.pushover.net/1/messages.json", data=data)
            if response.get("status") != 1:
                raise ValueError("Pushover did not accept notification")
            self.update(job["id"], notification="sent")
        except Exception:
            attempts = job["notify_attempts"] + 1
            self.update(job["id"], notification="failed" if attempts >= 5 else "pending",
                        notify_attempts=attempts, notify_after=time.time() + min(3600, 60 * 2 ** attempts))
            LOG.warning("Pushover attempt %s failed for job %s; video remains completed", attempts, job["id"])

    def poll(self):
        now = time.monotonic()
        present = set()
        for sport, (root, _) in self.c.routes.items():
            if not root.is_dir():
                LOG.warning("Incoming folder unavailable: %s", root)
                continue
            for path in root.iterdir():
                if path.name.startswith('.') or path.suffix.lower() not in VIDEOS or not path.is_file() or path.is_symlink():
                    continue
                try:
                    key = (sport, path.name)
                    present.add(key)
                    fp = self.fingerprint(path)
                    previous = self.seen.get(key)
                    if previous is None or previous[0] != fp:
                        self.seen[key] = (fp, now)
                    elif now - previous[1] >= self.c.stable_seconds and time.time() - path.stat().st_mtime >= self.c.stable_seconds:
                        self.enqueue(sport, path.name)
                except (OSError, ValueError):
                    continue
        self.seen = {key: value for key, value in self.seen.items() if key in present}

    def retry(self, job_id):
        with self.lock:
            job = self.get_job(job_id)
            if job["status"] not in {"review", "previewed"}:
                raise ValueError("Only review or previewed jobs can be retried")
            source = self.source(job["sport"], job["filename"])
            if self.fingerprint(source) != job["fingerprint"]:
                raise ValueError("File changed; submit a new completion webhook")
            self.update(job_id, status="queued", error=None)
        self.wake.set()
        return self.get_job(job_id)

    def sportarr(self, sport, body):
        if sport not in self.c.routes:
            raise ValueError("sport must be nfl or ufc")
        event = body.get("eventType")
        if event == "Test":
            return {"message": "Sportarr webhook connected; no files queued"}
        if event != "Download":
            return {"message": "Ignored event; only completed imports are accepted"}
        episode = body.get("episodeFile")
        if not isinstance(episode, dict):
            raise ValueError("Sportarr Download payload must include episodeFile")
        filename = episode.get("relativePath") or episode.get("path")
        if not isinstance(filename, str) or not filename:
            raise ValueError("Sportarr payload does not contain a filename")
        # Look ONLY in the configured flat staging folder; never operate on
        # the managed-library path supplied by Sportarr.
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
        return self.enqueue(sport, filename)

    def run_once(self):
        with self.lock:
            if self.c.mode in {"poll", "both"} and time.monotonic() - self.last_poll >= self.c.poll_seconds:
                self.poll()
                self.last_poll = time.monotonic()
            rows = self.db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 20").fetchall()
        for row in rows:
            self.process(dict(row))
        with self.lock:
            rows = self.db.execute("SELECT * FROM jobs WHERE status='completed' AND notification='pending' AND notify_after<=? LIMIT 10", (time.time(),)).fetchall()
        for row in rows:
            self.notify(dict(row))

    def start(self):
        def loop():
            while not self.stop.is_set():
                self.wake.clear()
                try:
                    self.run_once()
                    self.worker_error = None
                except Exception:
                    self.worker_error = "Worker operation failed; check logs and NAS mounts"
                    LOG.exception("Worker operation failed")
                self.wake.wait(1)
        self.thread = threading.Thread(target=loop, name="organizer", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join()
        self.db.close()


def handler_for(service):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SportsOrganizer/" + VERSION

        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def log_message(self, format, *args):
            # Do not log headers, tokens, payloads, or untrusted request URLs.
            LOG.info("API request from %s", self.client_address[0])

        def respond(self, status, value):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def dispatch(self):
            if not hmac.compare_digest(self.headers.get("Authorization", "").encode(), ("Bearer " + service.c.token).encode()):
                self.respond(401, {"error": "Bearer token required"})
                return
            path = urllib.parse.urlsplit(self.path).path
            try:
                if self.command == "GET":
                    if path == "/health":
                        roots = {sport: {"incoming": str(src), "incoming_available": src.is_dir(),
                                         "destination": str(dst), "destination_available": dst.is_dir()}
                                 for sport, (src, dst) in service.c.routes.items()}
                        healthy = bool(service.thread and service.thread.is_alive()) and not service.worker_error and all(
                            r["incoming_available"] and r["destination_available"] for r in roots.values())
                        self.respond(200 if healthy else 503, {"version": VERSION, "healthy": healthy, "dry_run": service.c.dry_run,
                            "watch_mode": service.c.mode, "routes": roots, "worker_error": service.worker_error})
                        return
                    if path == "/jobs":
                        self.respond(200, {"jobs": service.jobs()})
                        return
                    match = re.fullmatch(r"/jobs/(\d+)", path)
                    if match:
                        self.respond(200, service.get_job(int(match[1])))
                        return
                if self.command == "POST":
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 0 or length > 8192:
                        raise ValueError("Request body must be at most 8192 bytes")
                    body = json.loads(self.rfile.read(length) or b"{}")
                    if not isinstance(body, dict):
                        raise ValueError("Expected a JSON object")
                    if path == "/preview":
                        self.respond(200, service.preview(body["sport"], body["filename"]))
                        return
                    if path == "/webhooks/complete":
                        if body.get("transfer_complete") is not True:
                            raise ValueError("transfer_complete must be true; call only after the transfer finishes")
                        self.respond(202, service.enqueue(body["sport"], body["filename"]))
                        return
                    match = re.fullmatch(r"/webhooks/sportarr/(nfl|ufc)", path)
                    if match:
                        self.respond(202, service.sportarr(match[1], body))
                        return
                    if path == "/scan":
                        with service.lock:
                            service.poll()
                        self.respond(202, {"message": "Scan complete; files must satisfy the stability interval before queueing"})
                        return
                    match = re.fullmatch(r"/jobs/(\d+)/retry", path)
                    if match:
                        self.respond(202, service.retry(int(match[1])))
                        return
                self.respond(404, {"error": "Unknown endpoint"})
            except (ValueError, KeyError, TypeError) as exc:
                self.respond(400, {"error": str(exc)})
            except Exception:
                LOG.warning("API operation failed", exc_info=True)
                self.respond(500, {"error": "Operation failed; check service logs"})

        do_GET = dispatch
        do_POST = dispatch

    return Handler


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    service = Organizer(Config.env())
    server = ThreadingHTTPServer(("0.0.0.0", 8080), handler_for(service))
    service.start()
    def shutdown(signum, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    LOG.info("Started v%s: mode=%s dry_run=%s", VERSION, service.c.mode, service.c.dry_run)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        service.close()


if __name__ == "__main__":
    main()
