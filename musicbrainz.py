"""Read-only MusicBrainz artist search and genre lookup. No music files are sent."""
import copy
import json
import socket
import threading
import time
import uuid
from collections import OrderedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class MusicBrainzError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


class Client:
    def __init__(self, version):
        self.user_agent = f"genreSorter/{version} (https://github.com/alanoctua/genreSorter)"
        self.lock = threading.Lock()
        self.last_request = None
        self.cache = OrderedDict()

    def _get(self, path, parameters):
        url = "https://musicbrainz.org/ws/2/" + path + "?" + urlencode({**parameters, "fmt": "json"})
        # Serialize requests from all browsers; enforce MusicBrainz's 1 request/sec limit.
        with self.lock:
            saved = self.cache.get(url)
            if saved and time.monotonic() < saved[0]:
                self.cache.move_to_end(url)
                return copy.deepcopy(saved[1])
            if self.last_request is not None:
                time.sleep(max(0, 1.05 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
            try:
                with urlopen(request, timeout=8) as response:
                    body = response.read(2_000_001)
                if len(body) > 2_000_000:
                    raise MusicBrainzError("MusicBrainz returned too much data. Try again later.")
                result = json.loads(body)
                if not isinstance(result, dict) or "error" in result:
                    raise MusicBrainzError("MusicBrainz returned an unexpected response. Try again later.")
            except HTTPError as exc:
                if exc.code == 404:
                    raise MusicBrainzError("This artist is no longer available on MusicBrainz.", 404) from exc
                raise MusicBrainzError("MusicBrainz is busy or unavailable. Try again shortly.", 503) from exc
            except (URLError, TimeoutError, socket.timeout, OSError) as exc:
                raise MusicBrainzError("Cannot reach MusicBrainz. Check the server's internet connection and try again.", 503) from exc
            except (ValueError, UnicodeError) as exc:
                raise MusicBrainzError("MusicBrainz returned unreadable data. Try again later.") from exc
            self.cache[url] = (time.monotonic() + 86400, result)
            self.cache.move_to_end(url)
            while len(self.cache) > 256:
                self.cache.popitem(last=False)
            return copy.deepcopy(result)

    @staticmethod
    def _id(value):
        if not isinstance(value, str):
            raise ValueError("Choose a MusicBrainz artist")
        try:
            return str(uuid.UUID(value))
        except ValueError as exc:
            raise ValueError("Invalid MusicBrainz artist ID") from exc

    def search(self, artist):
        if not isinstance(artist, str) or not artist.strip() or len(artist) > 500:
            raise ValueError("Artist name is missing or too long for lookup")
        result = self._get("artist/", {"query": artist.strip(), "dismax": "true", "limit": 10})
        if not isinstance(result.get("artists"), list):
            raise MusicBrainzError("MusicBrainz returned an unexpected artist list. Try again later.")
        candidates = []
        for item in result.get("artists", []):
            if not isinstance(item, dict):
                continue
            try:
                identifier = self._id(item.get("id"))
            except ValueError:
                continue
            if not isinstance(item.get("name"), str):
                continue
            area = item.get("area")
            candidates.append({"id": identifier, "name": item["name"],
                               "description": item.get("disambiguation", ""),
                               "type": item.get("type", ""), "country": item.get("country", ""),
                               "area": area.get("name", "") if isinstance(area, dict) else ""})
        return {"artists": candidates}

    def genres(self, identifier):
        identifier = self._id(identifier)
        result = self._get("artist/" + identifier, {"inc": "genres"})
        if result.get("id") != identifier or not isinstance(result.get("name"), str) or not isinstance(result.get("genres", []), list):
            raise MusicBrainzError("MusicBrainz returned an unexpected artist. Try again later.")
        genres, seen = [], set()
        for genre in result.get("genres", []):
            if not isinstance(genre, dict):
                continue
            name = genre.get("name", "")
            if not isinstance(name, str):
                continue
            name = name.strip()
            # Match the editor's name limits and separators; never turn other tags into genres.
            if not name or len(name) > 120 or any(ord(c) < 32 or c in ",;" for c in name) or name.casefold() in seen:
                continue
            try:
                votes = int(genre.get("count", 0))
            except (ValueError, TypeError):
                votes = 0
            seen.add(name.casefold())
            genres.append({"name": name, "votes": votes})
        genres.sort(key=lambda genre: (-genre["votes"], genre["name"].casefold()))
        return {"artist": {"id": identifier, "name": result.get("name", "Unknown artist")}, "genres": genres[:100]}
