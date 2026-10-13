import base64
import errno
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import tags


class Problem(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class Library:
    def __init__(self, root, data):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("MUSIC_ROOT must be a directory")
        self.data = Path(data)
        self.lock = threading.RLock()
        self.cache = {}
        self.tracks = {}
        self.albums = []
        self.warnings = []
        self.plans = OrderedDict()
        self.busy = False
        self.status = "Choose a folder and scan its tags."
        self.folder = ""
        self.revision = 0
        self.generation = 0
        self.last_write = None
        self.cache_note = ""
        self._load_cache()

    def safe_path(self, relative):
        if not isinstance(relative, str) or len(relative) > 4096:
            raise Problem("Invalid folder or file path")
        raw = self.root / relative
        try:
            path = raw.resolve(strict=True)
        except OSError as exc:
            raise Problem(f"Path is unavailable: {exc}") from exc
        if not path.is_relative_to(self.root):
            raise Problem("Path is outside the mounted music folder", 403)
        if raw.is_symlink() or raw.absolute() != path:
            raise Problem("Symbolic links are not scanned or edited", 403)
        return path

    def folders(self, relative):
        folder = self.safe_path(relative)
        if not folder.is_dir():
            raise Problem("Select a folder")
        result = []
        try:
            for child in folder.iterdir():
                if not child.name.startswith(".") and not child.is_symlink() and child.is_dir():
                    result.append({"name": child.name, "path": child.relative_to(self.root).as_posix()})
        except OSError as exc:
            raise Problem(f"Cannot browse this folder: {exc}") from exc
        return {"path": folder.relative_to(self.root).as_posix(),
                "folders": sorted(result, key=lambda item: item["name"].casefold())}

    def _load_cache(self):
        try:
            saved = json.loads((self.data / "metadata-cache.json").read_text())
            info = self.root.stat()
            if saved.get("version") == 1 and saved.get("root") == [info.st_dev, info.st_ino]:
                self.cache = {path: value for path, value in saved.get("entries", {}).items()
                              if isinstance(path, str) and isinstance(value, dict)
                              and isinstance(value.get("meta"), dict) and isinstance(value.get("stamp"), dict)}
        except (OSError, ValueError, TypeError):
            pass

    def _save_cache(self):
        temp = self.data / (".cache-" + secrets.token_hex(8) + ".tmp")
        try:
            self.data.mkdir(parents=True, exist_ok=True)
            info = self.root.stat()
            temp.write_text(json.dumps({"version": 1, "root": [info.st_dev, info.st_ino], "entries": self.cache},
                                       ensure_ascii=False))
            temp.replace(self.data / "metadata-cache.json")
        except OSError as exc:
            self.cache_note = f"Metadata cache unavailable: {exc}"
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def _track(self, path, force=False):
        relative = path.relative_to(self.root).as_posix()
        current = tags.stamp(path)
        cached = self.cache.get(relative)
        if cached and cached["stamp"] == current and not force:
            meta = cached["meta"]
        else:
            meta = tags.metadata(path)
            if tags.stamp(path) != current:
                raise Problem("File changed while its tags were being read")
        self.cache[relative] = {"stamp": current, "meta": meta}
        album = meta["album"].strip() or path.parent.name
        artist = (meta["album_artist"] or meta["artist"]).strip() or "Unknown Artist"
        album_id = hashlib.sha256((tags.key(artist) + "\x1f" + tags.key(album)).encode()).hexdigest()[:24]
        return {"path": relative, "album_id": album_id, "album": album, "artist": artist,
                "title": meta["title"] or path.stem, "genres": meta["genres"], "stamp": current,
                "writable": os.access(path, os.W_OK)}

    def _publish(self, tracks, warnings, status):
        grouped = {}
        for track in tracks.values():
            grouped.setdefault(track["album_id"], []).append(track)
        albums = []
        for album_id, songs in grouped.items():
            songs.sort(key=lambda item: item["path"].casefold())
            first = songs[0]
            albums.append({"id": album_id, "name": first["album"], "artist": first["artist"],
                           "genres": tags.unique(g for song in songs for g in song["genres"]),
                           "mixed": any(song["genres"] != first["genres"] for song in songs[1:]),
                           "count": len(songs), "readonly_count": sum(not song["writable"] for song in songs),
                           "tracks": [{"path": song["path"], "title": song["title"], "genres": song["genres"]}
                                      for song in songs]})
        albums.sort(key=lambda album: (tags.key(album["artist"]), tags.key(album["name"])))
        with self.lock:
            self.tracks = dict(tracks)
            self.albums = albums
            self.warnings = list(warnings)
            self.status = status
            self.revision += 1

    def snapshot(self, since=None):
        with self.lock:
            common = {"busy": self.busy, "status": self.status, "revision": self.revision,
                      "generation": self.generation, "folder": self.folder,
                      "track_count": len(self.tracks), "last_write": self.last_write}
            if since == str(self.revision):
                return {**common, "unchanged": True}
            return {**common, "albums": self.albums, "warnings": self.warnings,
                    "cache_note": self.cache_note}

    def scan(self, relative="", force=False):
        folder = self.safe_path(relative)
        if not folder.is_dir():
            raise Problem("Select a folder")
        with self.lock:
            if self.busy:
                raise Problem("Wait for the current operation to finish", 409)
            self.busy = True
            self.folder = folder.relative_to(self.root).as_posix()
            self.generation += 1
            self.plans.clear()
            self.last_write = None
            self.status = "Scanning tags…"
            self.revision += 1
        threading.Thread(target=self._scan, args=(folder, bool(force)), daemon=True).start()
        return {"started": True}

    def _scan(self, folder, force):
        found, warnings = {}, []
        last_update = 0
        prefix = folder.relative_to(self.root).as_posix()
        prefix = "" if prefix == "." else prefix + "/"
        previous_paths = [p for p in self.cache if p.startswith(prefix)]
        try:
            def scan_error(exc):
                warnings.append(f"Cannot read folder: {exc}")

            for directory, dirs, files in os.walk(folder, followlinks=False, onerror=scan_error):
                dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (Path(directory) / d).is_symlink())
                for name in sorted(files):
                    path = Path(directory) / name
                    if name.startswith(".") or path.suffix.lower() not in tags.SUPPORTED or path.is_symlink():
                        continue
                    relative = path.relative_to(self.root).as_posix()
                    try:
                        path = self.safe_path(relative)
                        found[relative] = self._track(path, force)
                    except Exception as exc:
                        warnings.append(f"{relative}: {exc}")
                    if time.monotonic() - last_update >= 0.4:
                        self._publish(found, warnings, f"Scanning tags… {len(found)} tracks found.")
                        last_update = time.monotonic()
            for path in previous_paths:
                if path not in found:
                    self.cache.pop(path, None)
            self._save_cache()
            self._publish(found, warnings, f"Scan complete: {len(found)} tracks. Select albums to edit their genres.")
        except Exception as exc:
            self._publish(found, warnings + [str(exc)], f"Scan failed: {exc}")
        finally:
            with self.lock:
                self.busy = False
                self.revision += 1

    def preview(self, payload):
        selected = payload.get("albums")
        if not isinstance(selected, list) or not selected or len(selected) > 10000 or any(not isinstance(s, str) for s in selected):
            raise Problem("Select at least one album")
        rules = tags.Rules(payload.get("add", ""), payload.get("remove", ""),
                           payload.get("normalize", False), payload.get("aliases", ""))
        if not rules.has_action:
            raise Problem("Enter genres to add/remove or enable alias normalization")
        chosen = set(selected)
        with self.lock:
            if self.busy:
                raise Problem("Wait for scanning or saving to finish", 409)
            changes = []
            for track in self.tracks.values():
                if track["album_id"] not in chosen:
                    continue
                after = rules.apply(track["genres"])
                if after != track["genres"]:
                    changes.append({"path": track["path"], "album": track["album"],
                                    "before": track["genres"], "after": after, "stamp": track["stamp"]})
            if len(changes) > 20000:
                raise Problem("Select fewer albums: a single save supports up to 20,000 tracks")
            changes.sort(key=lambda row: row["path"].casefold())
            token = secrets.token_urlsafe(24)
            self.plans[token] = {"changes": changes, "generation": self.generation, "expires": time.time() + 1800}
            while len(self.plans) > 8:
                self.plans.popitem(last=False)
            return {"token": token, "count": len(changes),
                    "changes": [{k: v for k, v in row.items() if k != "stamp"} for row in changes]}

    def write(self, token):
        if not isinstance(token, str):
            raise Problem("Preview the edits before saving")
        with self.lock:
            if self.busy:
                raise Problem("Wait for the current operation to finish", 409)
            plan = self.plans.get(token)
            if not plan or plan["generation"] != self.generation or plan["expires"] < time.time():
                raise Problem("This preview expired or the library changed. Preview again.", 409)
            if not plan["changes"]:
                raise Problem("No files need changing")
            self.busy = True
            self.generation += 1
            self.plans.clear()
            self.last_write = None
            self.status = "Saving genres…"
            self.revision += 1
        threading.Thread(target=self._write, args=(plan["changes"],), daemon=True).start()
        return {"started": True}

    def _write(self, changes):
        written, failures = 0, []
        with self.lock:
            refreshed = dict(self.tracks)
            warnings = list(self.warnings)
        try:
            for number, change in enumerate(changes, 1):
                relative = change["path"]
                try:
                    path = self.safe_path(relative)
                    if tags.stamp(path) != change["stamp"]:
                        raise Problem("File changed since scanning; skipped. Rescan and preview again.")
                    if tags.metadata(path)["genres"] != change["before"] or tags.stamp(path) != change["stamp"]:
                        raise Problem("Tags changed since preview; skipped. Rescan and preview again.")
                    tags.write_genres(path, change["after"])
                    written += 1
                except Exception as exc:
                    message = str(exc)
                    if isinstance(exc, PermissionError):
                        message = f"Write permission denied as UID {os.getuid()}, GID {os.getgid()}. {exc}"
                    elif isinstance(exc, OSError) and exc.errno == errno.EROFS:
                        message = "Music mount is read-only. Set the compose music volume to read_only: false."
                    failures.append({"path": relative, "error": message})
                try:
                    refreshed[relative] = self._track(self.safe_path(relative), force=True)
                except Exception:
                    pass
                if number % 20 == 0:
                    self._publish(refreshed, warnings, f"Saving genres… {number}/{len(changes)} files processed.")
            self._save_cache()
            self._publish(refreshed, warnings,
                          f"Saved {written}/{len(changes)} files. {len(failures)} failed."
                          if failures else f"Saved genres on {written} files.")
        except Exception as exc:
            failures.append({"path": "Save operation", "error": str(exc)})
        finally:
            with self.lock:
                self.last_write = {"written": written, "failed": len(failures), "errors": failures}
                self.busy = False
                self.revision += 1


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def respond(self, value, status=200, content_type="application/json; charset=utf-8", extra=None):
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        try:
            kind, encoded = self.headers.get("Authorization", "").split(" ", 1)
            value = base64.b64decode(encoded, validate=True).decode()
            username, password = value.split(":", 1)
            valid = (kind.lower() == "basic" and hmac.compare_digest(username.encode(), b"admin")
                     and hmac.compare_digest(password.encode(), self.server.password.encode()))
        except (ValueError, UnicodeError):
            valid = False
        if not valid:
            self.close_connection = True
            self.respond({"error": "Sign in with username admin and your APP_PASSWORD"}, 401,
                         extra={"WWW-Authenticate": 'Basic realm="genreSorter", charset="UTF-8"', "Connection": "close"})
        return valid

    def do_GET(self):
        route = urlsplit(self.path)
        if route.path == "/health":
            self.respond({"ok": True})
            return
        if not self.authorized():
            return
        query = parse_qs(route.query)
        try:
            if route.path == "/api/state":
                self.respond(self.server.library.snapshot(query.get("since", [None])[0]))
            elif route.path == "/api/config":
                self.respond({"aliases": tags.DEFAULT_ALIASES, "uid": os.getuid(), "gid": os.getgid()})
            elif route.path == "/api/folders":
                self.respond(self.server.library.folders(query.get("path", [""])[0]))
            elif route.path in {"/", "/app.js", "/browser-utils.js", "/style.css"}:
                name = {"/": "index.html", "/app.js": "app.js", "/browser-utils.js": "browser-utils.js", "/style.css": "style.css"}[route.path]
                kind = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "browser-utils.js": "text/javascript; charset=utf-8", "style.css": "text/css; charset=utf-8"}[name]
                self.respond((self.server.static / name).read_bytes(), content_type=kind)
            else:
                raise Problem("Not found", 404)
        except Problem as exc:
            self.respond({"error": str(exc)}, exc.status)
        except Exception as exc:
            self.respond({"error": str(exc)}, 500)

    def do_POST(self):
        if not self.authorized():
            return
        try:
            origin = self.headers.get("Origin")
            if self.headers.get("X-GenreSorter-Request") != "1" or (origin and urlsplit(origin).netloc.lower() != self.headers.get("Host", "").lower()):
                self.close_connection = True
                raise Problem("Request must come from the genreSorter page", 403)
            if self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                self.close_connection = True
                raise Problem("Expected a JSON request", 415)
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 2_000_000:
                self.close_connection = True
                raise Problem("Invalid request size", 413)
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise Problem("Expected an object")
            route = urlsplit(self.path).path
            if route == "/api/scan":
                self.respond(self.server.library.scan(body.get("folder", ""), body.get("force", False)), 202)
            elif route == "/api/preview":
                self.respond(self.server.library.preview(body))
            elif route == "/api/write":
                self.respond(self.server.library.write(body.get("token")), 202)
            else:
                raise Problem("Not found", 404)
        except Problem as exc:
            self.respond({"error": str(exc)}, exc.status)
        except (ValueError, TypeError) as exc:
            self.respond({"error": str(exc)}, 400)
        except Exception as exc:
            self.respond({"error": str(exc)}, 500)


def make_server(root, data, password, port=8787, host="0.0.0.0"):
    if not password or password == "SET_A_PASSWORD":
        raise ValueError("Set APP_PASSWORD in .env before starting genreSorter")
    server = ThreadingHTTPServer((host, port), Handler)
    server.library = Library(root, data)
    server.password = password
    server.static = Path(__file__).parent / "static"
    return server


if __name__ == "__main__":
    server = make_server(os.environ.get("MUSIC_ROOT", "/music"), os.environ.get("DATA_ROOT", "/data"),
                         os.environ.get("APP_PASSWORD", ""), int(os.environ.get("PORT", "8787")))
    print(f"genreSorter listening on port {server.server_port}; UID {os.getuid()}, GID {os.getgid()}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
