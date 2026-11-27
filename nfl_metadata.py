"""Post-move NFL artwork and Plex library updates."""
import os
import re
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import PurePosixPath


class SeasonGameDetails(HTMLParser):
    """Read only labeled game details from sections of a season article."""

    fields = re.compile(r"^(Date|Game time|Game weather|Game attendance|Referee|"
                        r"TV announcers(?:\s*\([^)]*\))?):\s*(.+)$", re.I)

    def __init__(self):
        super().__init__()
        self.sections = []
        self.heading = None
        self.item = None
        self.active = None

    def handle_starttag(self, tag, attrs):
        if tag in {"h2", "h3", "h4", "h5", "h6"}:
            self.heading = []
        elif tag == "li" and self.active is not None:
            self.item = []

    def handle_data(self, data):
        if self.heading is not None:
            self.heading.append(data)
        if self.item is not None:
            self.item.append(data)

    def handle_endtag(self, tag):
        if tag in {"h2", "h3", "h4", "h5", "h6"} and self.heading is not None:
            self.active = {}
            self.sections.append((" ".join("".join(self.heading).split()), self.active))
            self.heading = None
            self.item = None
        elif tag == "li" and self.item is not None:
            match = self.fields.fullmatch(" ".join("".join(self.item).split()))
            if match:
                label, value = match.groups()
                self.active[label.lower()] = (label, value)
            self.item = None


@lru_cache(maxsize=8)
def chiefs_season_details(season, refresh_day):
    url = f"https://en.wikipedia.org/wiki/{season}_Kansas_City_Chiefs_season"
    request = urllib.request.Request(url, headers={"User-Agent": "SportsOrganizer/1.2 (https://github.com/dbowles1975/sports-organizer)"})
    with urllib.request.urlopen(request, timeout=8) as response:
        html = response.read(6_000_001)
    if len(html) > 6_000_000:
        raise ValueError("Wikipedia season article exceeds size limit")
    parser = SeasonGameDetails()
    parser.feed(html.decode("utf-8"))
    parser.close()
    return parser.sections


def chiefs_game_details(season, game_date, opponent):
    played = date.fromisoformat(game_date)
    month_day = f"{played:%B} {played.day}"
    matches = []
    for heading, fields in chiefs_season_details(season, date.today()):
        if not re.search(rf"\b{re.escape(opponent)}\b", heading, re.I):
            continue
        published = fields.get("date", ("", ""))[1]
        if published.casefold() not in {month_day.casefold(), f"{month_day}, {played.year}".casefold()}:
            continue
        matches.append(fields)
    return matches[0] if len(matches) == 1 else {}


def base_url(value):
    url = urllib.parse.urlsplit(value)
    if (url.scheme not in {"http", "https"} or not url.hostname or
            url.username is not None or url.password is not None or url.query or url.fragment):
        raise ValueError("Service URLs must be HTTP(S) base URLs without credentials or query parameters")
    return value.rstrip("/")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def poster_for(folder, base, away, home):
    for suffix in (".jpg", ".jpeg", ".png"):
        existing = folder / ("poster" + suffix)
        if existing.is_file():
            return existing
    route = "/nfl/" + "/".join(urllib.parse.quote(name, safe="") for name in (away, home))
    request = urllib.request.Request(base + route + "/cover?style=99", headers={"Accept": "image/*"})
    limit = 16 * 1024 * 1024
    with urllib.request.urlopen(request, timeout=15) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Game Thumbs poster exceeds 16 MiB")
    if data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"):
        suffix = ".jpg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n") and data.endswith(b"IEND\xaeB\x60\x82"):
        suffix = ".png"
    else:
        raise ValueError("Game Thumbs did not return a JPEG or PNG poster")
    poster = folder / ("poster" + suffix)
    with tempfile.NamedTemporaryFile(dir=folder, prefix=".poster-", delete=False) as pending:
        temporary = pending.name
        try:
            with pending:
                pending.write(data)
            os.chmod(temporary, 0o644)
            try:
                if os.name == "nt":
                    os.rename(temporary, poster)
                else:
                    os.link(temporary, poster)
            except FileExistsError:
                pass
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    return poster


class Plex:
    def __init__(self, url, token, section):
        self.url = base_url(url)
        if not re.fullmatch(r"[1-9][0-9]*", section):
            raise ValueError("PLEX_NFL_LIBRARY_ID must be a positive numeric ID")
        self.section = "/library/sections/" + section
        self.headers = {"X-Plex-Token": token, "Accept": "application/xml"}
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, path, params=None, *, method="GET", data=None, content_type=None):
        suffix = "?" + urllib.parse.urlencode(params) if params else ""
        headers = dict(self.headers)
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self.url + path + suffix, data=data, headers=headers, method=method)
        with self.opener.open(request, timeout=15) as response:
            return response.read()

    def find_video(self, file_path):
        start = 0
        matched = []
        while True:
            data = self.request(self.section + "/all", {
                "type": 1, "X-Plex-Container-Start": start, "X-Plex-Container-Size": 100,
            })
            page = ET.fromstring(data)
            videos = page.findall("Video")
            matched.extend(video for video in videos if any(
                part.get("file") == file_path for part in video.findall("Media/Part")))
            start += len(videos)
            if not videos or start >= int(page.get("totalSize", str(start))):
                break
        if len(matched) > 1:
            raise ValueError("More than one Plex movie matches the exact file path")
        return matched[0] if matched else None

    def update_game(self, target, title, game_date, poster, *, summary=None, basic_summary=None, collections=()):
        target = PurePosixPath(target)
        video = self.find_video(str(target))
        if video is None:
            self.request(self.section + "/refresh", {"path": str(target.parent)}, method="POST")
            raise ValueError("Waiting for Plex to discover the file in the configured NFL movie library")
        key = video.get("ratingKey", "")
        if not re.fullmatch(r"[1-9][0-9]*", key):
            raise ValueError("Plex returned an invalid movie ID")
        item_path = "/library/metadata/" + key
        details = ET.fromstring(self.request(item_path)).find("Video")
        if details is None:
            raise ValueError("Plex entry disappeared before the update")
        locked = {field.get("name") for field in details.findall("Field") if field.get("locked") == "1"}
        values = {"title": title, "titleSort": title, "originallyAvailableAt": game_date,
                  "contentRating": "E", "studio": "NFL"}
        edition = re.sub(r"^[0-9]{4} - ", "", title)
        if edition != title:
            values["editionTitle"] = edition
        if summary:
            values["summary"] = summary
        changes = {}
        for field, value in values.items():
            upgrade_summary = field == "summary" and basic_summary and details.get("summary") == basic_summary
            if field not in locked or upgrade_summary:
                changes[field + ".value"] = value
                changes[field + ".locked"] = 1
        if collections:
            existing = [node.attrib["tag"] for node in details.findall("Collection") if node.get("tag")]
            original_count = len(existing)
            seen = {name.casefold() for name in existing}
            for name in collections:
                if name.casefold() not in seen:
                    existing.append(name)
                    seen.add(name.casefold())
            if len(existing) > original_count:
                changes["collection.locked"] = 1
                for index, name in enumerate(existing):
                    changes[f"collection[{index}].tag.tag"] = name
        if changes:
            self.request(self.section + "/all", {"id": key, "type": 1, **changes}, method="PUT")
        if poster is not None and "thumb" not in locked and "poster" not in locked:
            content_type = "image/png" if poster.suffix == ".png" else "image/jpeg"
            self.request(item_path + "/posters", method="POST", data=poster.read_bytes(), content_type=content_type)
