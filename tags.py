"""Genre editing only. Audio streams are never decoded or re-encoded."""
import os
import re
import unicodedata
from pathlib import Path

from mutagen.flac import FLAC
from mutagen.id3 import TCON
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4

SUPPORTED = {".flac", ".mp3", ".m4a"}
DEFAULT_ALIASES = """City Pop = Citypop, City-Pop
Japanese Jazz = J-Jazz, Japan Jazz
Jazz Fusion = Fusion Jazz
J-Pop = J Pop, JPop"""


def key(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.strip().casefold())
                   if not unicodedata.combining(c))


def entries(value):
    if not isinstance(value, str):
        raise ValueError("Genres must be text separated with commas or semicolons")
    return [s.strip() for s in re.split(r"[,;\n]", value) if s.strip()]


def unique(values):
    result, seen = [], set()
    for value in values:
        folded = key(value)
        if folded not in seen:
            result.append(value)
            seen.add(folded)
    return result


def valid_genre(value):
    if len(value) > 120 or any(ord(c) < 32 for c in value):
        raise ValueError("A genre must be at most 120 characters and contain no control characters")
    return value


class Rules:
    def __init__(self, add="", remove="", normalize=False, aliases=""):
        self.add = [valid_genre(s) for s in entries(add)]
        self.remove = [valid_genre(s) for s in entries(remove)]
        if len(self.add) + len(self.remove) > 100:
            raise ValueError("Use at most 100 genre names per edit")
        self.normalize = bool(normalize)
        self.aliases = {}
        if self.normalize:
            if not isinstance(aliases, str) or len(aliases) > 20000:
                raise ValueError("Alias rules are too large")
            for number, raw in enumerate(aliases.splitlines(), 1):
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    raise ValueError(f"Alias line {number}: use Canonical = Alias, Alias")
                canonical, names = line.split("=", 1)
                canonical = valid_genre(canonical.strip())
                names = entries(names)
                if not canonical or not names:
                    raise ValueError(f"Alias line {number} needs a canonical name and an alias")
                for name in [canonical] + names:
                    valid_genre(name)
                    previous = self.aliases.get(key(name))
                    if previous and previous != canonical:
                        raise ValueError(f'Alias "{name}" maps to both {previous} and {canonical}')
                    self.aliases[key(name)] = canonical

    def canonical(self, value):
        value = value.strip()
        return self.aliases.get(key(value), value) if self.normalize else value

    def apply(self, current):
        removed = {key(self.canonical(s)) for s in self.remove}
        existing = [self.canonical(s) for raw in current for s in raw.split(";")]
        proposed = unique(s for s in existing + [self.canonical(s) for s in self.add]
                          if s and key(s) not in removed)
        if len(proposed) > 100:
            raise ValueError("An edit cannot produce more than 100 genres on a track")
        return proposed

    @property
    def has_action(self):
        return bool(self.add or self.remove or self.normalize)


def stamp(path):
    info = path.stat()
    return {"size": info.st_size, "mtime": info.st_mtime_ns,
            "device": info.st_dev, "inode": info.st_ino}


def open_audio(path):
    suffix = path.suffix.lower()
    if suffix == ".flac":
        return FLAC(path)
    if suffix == ".mp3":
        return MP3(path)
    if suffix == ".m4a":
        return MP4(path)
    raise ValueError("Only FLAC, MP3 and M4A files are supported")


def metadata(path):
    audio = open_audio(path)
    tags = audio.tags
    result = {"album": "", "album_artist": "", "artist": "", "title": "", "genres": []}
    if tags is None:
        return result
    if path.suffix.lower() == ".mp3":
        for name, frame_id in [("album", "TALB"), ("album_artist", "TPE2"),
                               ("artist", "TPE1"), ("title", "TIT2")]:
            frame = tags.get(frame_id)
            if frame is not None:
                result[name] = "; ".join(str(s) for s in frame.text)
        result["genres"] = [s for frame in tags.getall("TCON") for s in frame.genres]
    else:
        keys = {"album": "album", "album_artist": "albumartist", "artist": "artist", "title": "title"}
        genre_key = "genre"
        if path.suffix.lower() == ".m4a":
            keys = {"album": "\xa9alb", "album_artist": "aART", "artist": "\xa9ART", "title": "\xa9nam"}
            genre_key = "\xa9gen"
        for name, tag_key in keys.items():
            result[name] = "; ".join(str(s) for s in tags.get(tag_key, []))
        result["genres"] = [str(s) for s in tags.get(genre_key, [])]
    return result


def write_genres(path, genres):
    if not os.access(path, os.W_OK):
        raise PermissionError(f"No write access as UID {os.getuid()}, GID {os.getgid()}")
    audio = open_audio(path)
    if audio.tags is None:
        audio.add_tags()
    if path.suffix.lower() == ".mp3":
        audio.tags.delall("TCON")
        if genres:
            audio.tags.add(TCON(encoding=3, text=genres))
        audio.tags.save(path, v2_version=4, v1=1)
    else:
        name = "\xa9gen" if path.suffix.lower() == ".m4a" else "genre"
        if genres:
            audio.tags[name] = genres
        elif name in audio.tags:
            del audio.tags[name]
        audio.save()
    if metadata(path)["genres"] != genres:
        raise ValueError("Save finished but the genres did not read back correctly; inspect this file")
