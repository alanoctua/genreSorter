import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
import tags
from mutagen.flac import Picture
from mutagen.id3 import APIC, COMM, TXXX
from mutagen.mp4 import MP4Cover, MP4FreeForm

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jk1kAAAAASUVORK5CYII=")


def audio_hash(path):
    return subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-c", "copy",
                                    "-f", "hash", "-hash", "sha256", "-"], text=True).strip()


def other_tags(path):
    audio = tags.open_audio(path)
    excluded = {"genre", "TCON", "\xa9gen"}
    values = {name: value.pprint() if hasattr(value, "pprint") else repr(value)
              for name, value in audio.tags.items() if name not in excluded}
    pictures = [(picture.type, picture.mime, picture.desc, hashlib.sha256(picture.data).hexdigest())
                for picture in getattr(audio, "pictures", [])]
    return values, pictures


def wait(library):
    deadline = time.monotonic() + 15
    while library.snapshot()["busy"]:
        if time.monotonic() > deadline:
            raise AssertionError("Background operation timed out")
        time.sleep(0.02)
    return library.snapshot()


class Workflow(unittest.TestCase):
    def setUp(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg is required to create sample audio")
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "Music"
        folder = self.root / "Sample Artist" / "Sample Album"
        folder.mkdir(parents=True)
        self.paths = []
        for index, (suffix, codec) in enumerate([("flac", "flac"), ("mp3", "libmp3lame"), ("m4a", "aac")], 1):
            path = folder / f"{index:02d} Track.{suffix}"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.3",
                            "-metadata", "album=Sample Album", "-metadata", "album_artist=Sample Artist",
                            "-metadata", "artist=Sample Artist", "-metadata", f"title=Track {index}",
                            "-metadata", "genre=Jazz", "-c:a", codec, str(path)], check=True)
            audio = tags.open_audio(path)
            if suffix == "flac":
                picture = Picture(); picture.data = PNG; picture.mime = "image/png"; picture.type = 3; picture.desc = "Cover"
                audio.add_picture(picture)
                audio["lyrics"] = ["Sample lyrics"]
                audio["replaygain_track_gain"] = ["-3.0 dB"]
                audio.save()
            elif suffix == "mp3":
                audio.tags.add(APIC(encoding=3, mime="image/png", type=3, desc="Cover", data=PNG))
                audio.tags.add(COMM(encoding=3, lang="eng", desc="Test", text=["Sample comment"]))
                audio.tags.add(TXXX(encoding=3, desc="REPLAYGAIN_TRACK_GAIN", text=["-3.0 dB"]))
                audio.tags.save(path, v2_version=4)
            else:
                audio.tags["covr"] = [MP4Cover(PNG, imageformat=MP4Cover.FORMAT_PNG)]
                audio.tags["\xa9lyr"] = ["Sample lyrics"]
                audio.tags["----:com.apple.iTunes:replaygain_track_gain"] = [MP4FreeForm(b"-3.0 dB")]
                audio.save()
            self.paths.append(path)
        self.library = server.Library(self.root, self.base / "cache")

    def tearDown(self):
        self.temp.cleanup()

    def scan(self):
        self.library.scan()
        state = wait(self.library)
        self.assertEqual(state["track_count"], 3)
        self.assertEqual(len(state["albums"]), 1)
        self.assertEqual(state["warnings"], [])
        return state

    def test_multivalue_and_removal_preserve_other_tags_artwork_audio(self):
        for path in self.paths:
            with self.subTest(format=path.suffix):
                before_tags, before_audio = other_tags(path), audio_hash(path)
                tags.write_genres(path, ["Jazz", "Japanese Jazz", "City Pop"])
                self.assertEqual(tags.metadata(path)["genres"], ["Jazz", "Japanese Jazz", "City Pop"])
                self.assertEqual(other_tags(path), before_tags)
                self.assertEqual(audio_hash(path), before_audio)
                tags.write_genres(path, [])
                self.assertEqual(tags.metadata(path)["genres"], [])
                self.assertEqual(other_tags(path), before_tags)
                self.assertEqual(audio_hash(path), before_audio)

    def test_rules_aliases_and_case_insensitive_removal(self):
        rules = tags.Rules("Japanese Jazz", "jazz", True, tags.DEFAULT_ALIASES)
        self.assertEqual(rules.apply(["Jazz", "Citypop; City Pop", "Jazz / Funk"]),
                         ["City Pop", "Jazz / Funk", "Japanese Jazz"])
        with self.assertRaises(ValueError):
            tags.Rules(normalize=True, aliases="Jazz = J\nRock = J")

    def test_preview_is_read_only_and_save_requires_preview_token(self):
        state = self.scan()
        checksums = [hashlib.sha256(path.read_bytes()).hexdigest() for path in self.paths]
        plan = self.library.preview({"albums": [state["albums"][0]["id"]], "add": "City Pop, Japanese Jazz"})
        self.assertEqual(plan["count"], 3)
        self.assertEqual([hashlib.sha256(path.read_bytes()).hexdigest() for path in self.paths], checksums)
        with self.assertRaises(server.Problem):
            self.library.write("made-up-token")
        self.library.write(plan["token"])
        result = wait(self.library)
        self.assertEqual(result["last_write"]["written"], 3)
        self.assertEqual(result["last_write"]["failed"], 0)
        for path in self.paths:
            self.assertEqual(tags.metadata(path)["genres"], ["Jazz", "City Pop", "Japanese Jazz"])

    def test_changed_tags_are_skipped_even_when_timestamp_and_size_match(self):
        state = self.scan()
        plan = self.library.preview({"albums": [state["albums"][0]["id"]], "add": "City Pop"})
        path = self.paths[0]
        old = path.stat()
        tags.write_genres(path, ["Funk"])
        os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
        self.assertEqual(path.stat().st_size, old.st_size)
        self.library.write(plan["token"])
        result = wait(self.library)
        self.assertEqual(result["last_write"]["written"], 2)
        self.assertEqual(result["last_write"]["failed"], 1)
        self.assertIn("Tags changed", result["last_write"]["errors"][0]["error"])
        self.assertEqual(tags.metadata(path)["genres"], ["Funk"])

    def test_replace_previous_genres_and_clear_use_preview_and_preserve_other_data(self):
        tags.write_genres(self.paths[0], ["Old Genre", "Other Old Genre"])
        state = self.scan()
        before = {path: (other_tags(path), audio_hash(path)) for path in self.paths}
        checksums = [hashlib.sha256(path.read_bytes()).hexdigest() for path in self.paths]
        selected = [state["albums"][0]["id"]]
        plan = self.library.preview({"albums": selected, "add": "Citypop, Japanese Jazz", "remove": "City Pop", "replace": True,
                                     "normalize": True, "aliases": "City Pop = Citypop"})
        self.assertEqual(plan["count"], 3)
        self.assertTrue(all(row["after"] == ["City Pop", "Japanese Jazz"] for row in plan["changes"]))
        self.assertEqual([hashlib.sha256(path.read_bytes()).hexdigest() for path in self.paths], checksums)
        self.library.write(plan["token"])
        self.assertEqual(wait(self.library)["last_write"]["written"], 3)
        for path in self.paths:
            self.assertEqual(tags.metadata(path)["genres"], ["City Pop", "Japanese Jazz"])
            self.assertEqual((other_tags(path), audio_hash(path)), before[path])
        clear = self.library.preview({"albums": selected, "replace": True})
        self.assertTrue(all(row["after"] == [] for row in clear["changes"]))
        self.library.write(clear["token"])
        self.assertEqual(wait(self.library)["last_write"]["written"], 3)
        for path in self.paths:
            self.assertEqual(tags.metadata(path)["genres"], [])
            self.assertEqual((other_tags(path), audio_hash(path)), before[path])

    def test_replacement_must_be_boolean_and_does_not_change_normal_add_behavior(self):
        self.assertEqual(tags.Rules("New", replace=True).apply(["Old", "Unexpected"]), ["New"])
        self.assertEqual(tags.Rules("New").apply(["Old"]), ["Old", "New"])
        self.assertTrue(tags.Rules(replace=True).has_action)
        self.assertEqual(tags.Rules(replace=True).apply(["Old"]), [])
        with self.assertRaises(ValueError):
            tags.Rules("New", replace="false")

    def test_cache_reuses_unchanged_tags_after_restart(self):
        self.scan()
        restarted = server.Library(self.root, self.base / "cache")
        with patch.object(tags, "metadata", side_effect=AssertionError("Unexpected tag read")):
            restarted.scan()
            state = wait(restarted)
        self.assertEqual(state["track_count"], 3)
        self.assertEqual(state["warnings"], [])
        with patch.object(tags, "metadata", wraps=tags.metadata) as reader:
            restarted.scan(force=True)
            wait(restarted)
            self.assertEqual(reader.call_count, 3)

    def test_path_boundaries_and_symlink_rejection(self):
        outside = self.base / "Outside"; outside.mkdir()
        (self.root / "link").symlink_to(outside, target_is_directory=True)
        for path in ["../Outside", str(outside), "link"]:
            with self.subTest(path=path), self.assertRaises(server.Problem):
                self.library.safe_path(path)

    def test_real_readonly_file_permission_failure(self):
        path = self.paths[0]
        path.chmod(0o444)
        self.base.chmod(0o755)
        if os.getuid() == 0:
            # Dropping this child process's capabilities exercises real file permissions,
            # including in a user namespace where switching to UID 65534 is unavailable.
            code = """import ctypes,sys
class Header(ctypes.Structure):
    _fields_=[('version',ctypes.c_uint32),('pid',ctypes.c_int)]
class Capabilities(ctypes.Structure):
    _fields_=[('effective',ctypes.c_uint32),('permitted',ctypes.c_uint32),('inheritable',ctypes.c_uint32)]
libc=ctypes.CDLL(None,use_errno=True)
if libc.capset(ctypes.byref(Header(0x20080522,0)),(Capabilities*2)()) != 0:
    sys.exit(77)
import tags
from pathlib import Path
try: tags.write_genres(Path(sys.argv[1]), ['City Pop'])
except PermissionError: sys.exit(0)
else: sys.exit(2)
"""
            completed = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True)
            if completed.returncode == 77:
                self.skipTest("This root environment does not support dropping Linux capabilities")
            self.assertEqual(completed.returncode, 0, completed.stderr)
        else:
            with self.assertRaises(PermissionError):
                tags.write_genres(path, ["City Pop"])
        self.assertEqual(tags.metadata(path)["genres"], ["Jazz"])
        path.chmod(0o644)

    def test_cache_permission_failure_does_not_block_scanning(self):
        blocked = self.base / "cache-file"; blocked.write_text("not a directory")
        library = server.Library(self.root, blocked)
        library.scan()
        state = wait(library)
        self.assertEqual(state["track_count"], 3)
        self.assertIn("cache unavailable", state["cache_note"].lower())

    def test_http_authentication_origin_checks_and_scan(self):
        http = server.make_server(self.root, self.base / "http-cache", "test-password", port=0, host="127.0.0.1")
        thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
        base = f"http://127.0.0.1:{http.server_port}"
        auth = "Basic " + base64.b64encode(b"admin:test-password").decode()
        try:
            with urlopen(base + "/health") as response:
                self.assertEqual(json.load(response), {"ok": True})
            with self.assertRaises(HTTPError) as exc:
                urlopen(base + "/api/state")
            self.assertEqual(exc.exception.code, 401)
            with urlopen(Request(base + "/browser-utils.js", headers={"Authorization": auth})) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("text/javascript", response.headers["Content-Type"])
                self.assertIn(b"globalThis.GenreBrowser", response.read())
            for extra in [{}, {"X-GenreSorter-Request": "1", "Origin": "http://elsewhere.invalid"}]:
                request = Request(base + "/api/scan", data=b'{}', headers={"Authorization": auth, "Content-Type": "application/json", **extra})
                with self.assertRaises(HTTPError) as exc:
                    urlopen(request)
                self.assertEqual(exc.exception.code, 403)
            request = Request(base + "/api/scan", data=b'{}', headers={"Authorization": auth, "Content-Type": "application/json", "X-GenreSorter-Request": "1"})
            with urlopen(request) as response:
                self.assertEqual(response.status, 202)
            self.assertEqual(wait(http.library)["track_count"], 3)
        finally:
            http.shutdown(); http.server_close(); thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
