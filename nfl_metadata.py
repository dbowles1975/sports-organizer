"""Post-move NFL artwork and Plex library updates."""
import os
import re
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath


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

    def update_game(self, target, title, game_date, poster):
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
        changes = {}
        for field, value in values.items():
            if field not in locked:
                changes[field + ".value"] = value
                changes[field + ".locked"] = 1
        if changes:
            self.request(self.section + "/all", {"id": key, "type": 1, **changes}, method="PUT")
        if poster is not None and "thumb" not in locked and "poster" not in locked:
            content_type = "image/png" if poster.suffix == ".png" else "image/jpeg"
            self.request(item_path + "/posters", method="POST", data=poster.read_bytes(), content_type=content_type)
