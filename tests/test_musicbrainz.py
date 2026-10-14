import base64
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

import musicbrainz
import server


MBID = "0383dadf-2a4e-4d10-a46a-e9e041da8eb3"


class MusicBrainz(unittest.TestCase):
    def test_search_is_literal_and_identified_and_cache_obeys_request_limit(self):
        client = musicbrainz.Client("test")
        now, calls, sleeps = [10.0], [], []
        payload = {"artists": [{"id": MBID, "name": "AC/DC", "disambiguation": "Australian band", "type": "Group", "area": {"name": "Australia"}}]}
        def fetch(request, timeout):
            self.assertEqual(timeout, 8)
            self.assertIn("genreSorter/test", request.get_header("User-agent"))
            self.assertTrue(request.full_url.startswith("https://musicbrainz.org/ws/2/artist/"))
            query = parse_qs(urlsplit(request.full_url).query)
            self.assertEqual(query["dismax"], ["true"])
            calls.append((now[0], query["query"][0]))
            return io.BytesIO(json.dumps(payload).encode())
        def sleep(duration):
            sleeps.append(duration)
            now[0] += duration
        with patch.object(musicbrainz, "urlopen", side_effect=fetch), patch.object(musicbrainz.time, "monotonic", side_effect=lambda: now[0]), patch.object(musicbrainz.time, "sleep", side_effect=sleep):
            first = client.search('AC/DC "live"')
            first["artists"][0]["name"] = "changed"
            self.assertEqual(client.search('AC/DC "live"')["artists"][0]["name"], "AC/DC")
            client.search("Queen")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1], 'AC/DC "live"')
        self.assertGreaterEqual(calls[1][0] - calls[0][0], 1.0)
        self.assertEqual(len(sleeps), 1)

    def test_genres_are_ranked_and_general_tags_are_not_used(self):
        client = musicbrainz.Client("test")
        with patch.object(client, "_get", return_value={"id": MBID, "name": "Queen", "genres": [
                {"name": "rock", "count": 10}, {"name": "progressive rock", "count": 4},
                {"name": "Rock", "count": 1}, {"name": "bad;delimiter", "count": 99}],
                "tags": [{"name": "favourite band", "count": 100}]}) as fetch:
            result = client.genres(MBID)
            self.assertEqual(result["genres"], [{"name": "rock", "votes": 10}, {"name": "progressive rock", "votes": 4}])
            fetch.assert_called_once_with("artist/" + MBID, {"inc": "genres"})
        with patch.object(client, "_get", return_value={"id": MBID, "name": "Queen"}):
            self.assertEqual(client.genres(MBID)["genres"], [])

    def test_invalid_artist_id_never_triggers_network(self):
        client = musicbrainz.Client("test")
        with patch.object(client, "_get") as fetch:
            for value in [None, "https://example.org", "../../files", "wrong"]:
                with self.assertRaises(ValueError):
                    client.genres(value)
            fetch.assert_not_called()

    def test_network_errors_and_malformed_responses_are_clear(self):
        for failure in [URLError("offline"), TimeoutError("timeout"), HTTPError("url", 503, "busy", {}, None)]:
            with self.subTest(failure=failure), patch.object(musicbrainz, "urlopen", side_effect=failure):
                with self.assertRaises(musicbrainz.MusicBrainzError) as error:
                    musicbrainz.Client("test").search("Queen")
                self.assertEqual(error.exception.status, 503)
        with patch.object(musicbrainz, "urlopen", return_value=io.BytesIO(b'not json')):
            with self.assertRaises(musicbrainz.MusicBrainzError):
                musicbrainz.Client("test").search("Queen")
        with patch.object(musicbrainz.Client, "_get", return_value={"id": "wrong", "name": "Wrong", "genres": []}):
            with self.assertRaises(musicbrainz.MusicBrainzError):
                musicbrainz.Client("test").genres(MBID)

    def test_lookup_api_requires_auth_origin_and_single_artist_and_never_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sample = root / "music.flac"; sample.write_bytes(b"untouched sample")
            http = server.make_server(root, root / "data", "test-password", port=0, host="127.0.0.1")
            http.library.albums = [{"id": "a", "artist": "Queen"}, {"id": "b", "artist": "Other"}]
            http.musicbrainz = Mock()
            http.musicbrainz.search.return_value = {"artists": [{"id": MBID, "name": "Queen"}]}
            http.musicbrainz.genres.return_value = {"artist": {"id": MBID, "name": "Queen"}, "genres": [{"name": "rock", "votes": 10}]}
            worker = threading.Thread(target=http.serve_forever, daemon=True); worker.start()
            base = f"http://127.0.0.1:{http.server_port}"
            headers = {"Authorization": "Basic " + base64.b64encode(b"admin:test-password").decode(),
                       "Content-Type": "application/json", "X-GenreSorter-Request": "1"}
            def post(route, payload, extra=None):
                return urlopen(Request(base + route, data=json.dumps(payload).encode(), headers={**headers, **(extra or {})}))
            try:
                for extra, code in [({"Authorization": ""}, 401), ({"X-GenreSorter-Request": ""}, 403), ({"Origin": "https://wrong.invalid"}, 403)]:
                    with self.assertRaises(HTTPError) as error:
                        post("/api/musicbrainz/search", {"albums": ["a"]}, extra)
                    self.assertEqual(error.exception.code, code)
                for albums in [[], ["a", "b"], ["missing"]]:
                    with self.assertRaises(HTTPError):
                        post("/api/musicbrainz/search", {"albums": albums})
                http.musicbrainz.search.assert_not_called()
                with post("/api/musicbrainz/search", {"albums": ["a"]}) as response:
                    self.assertEqual(json.load(response)["local_artist"], "Queen")
                http.musicbrainz.search.assert_called_once_with("Queen")
                with post("/api/musicbrainz/genres", {"albums": ["a"], "mbid": MBID}) as response:
                    self.assertEqual(json.load(response)["genres"][0]["name"], "rock")
                http.musicbrainz.search.side_effect = musicbrainz.MusicBrainzError("Unavailable", 503)
                with self.assertRaises(HTTPError) as error:
                    post("/api/musicbrainz/search", {"albums": ["a"]})
                self.assertEqual(error.exception.code, 503)
                self.assertEqual(sample.read_bytes(), b"untouched sample")
                self.assertEqual(http.library.plans, {})
                self.assertFalse(http.library.busy)
            finally:
                http.shutdown(); http.server_close(); worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
