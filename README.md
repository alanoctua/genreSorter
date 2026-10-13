# genreSorter for Docker / OMV

Browser app for viewing and bulk editing album genres. FLAC, MP3 and M4A supported. Choose a mounted music folder, scan, multi-select albums, add/remove genres or normalize aliases, preview every affected track, then Save genres. Saves modify genre tags on the chosen server files directly. The music library is not copied or re-encoded.

## Install on OMV

1. Put this entire folder on the server, for example `/srv/appdata/genresorter`.
2. Run `id tuna` on the server. Note the numeric `uid` and `gid` of the account with write access to your music.
3. In the project folder, run `cp .env.example .env` and edit `.env`:
   - `MUSIC_PATH`: full server path to your music folder, not the Mac `/Volumes/...` path.
   - `PUID` and `PGID`: the numbers from step 2. The container uses these IDs; it does not change file ownership or permissions.
   - `APP_PASSWORD`: choose a password. The placeholder is refused at startup.
   - `PORT`: 8787 by default; change if already occupied.
4. Run:

```bash
docker compose up -d --build
```

5. Open `http://YOUR-SERVER-IP:8787` in your browser. Username **admin**, password from `.env`.
6. Choose a folder within `/music` or press **Scan music** for the mounted root. Select albums, type genres, **Preview changes**, then **Save genres**.

The default address listens on your server's network interfaces. Keep this tool on your home network. You can set `BIND_ADDRESS` to your server's LAN IP to bind only that interface.

## Genres and scanning

Genres entered in the editor are separated by commas or semicolons. Each track keeps its other genres. Removing a name is case-insensitive; when a name is in both Add and Remove, Remove wins. Normalization uses explicit alias rules (`City Pop = Citypop, City-Pop`) and applies only to selected albums. Existing semicolon-separated genre values become separate values when an edit is applied. A slash stays part of the name.

Albums group by album artist + album title. Missing album tags use the containing folder name. Current genres are shown at album and track level, including albums whose tracks differ. Scanning publishes albums progressively and caches unchanged metadata in `/data`. **Shift-click Rescan** to reread all metadata. Saving refreshes only the affected tracks. MP3 multivalue genres are saved as ID3v2.4 TCON values; FLAC uses multiple Vorbis genre values; M4A uses multiple text genre values.

No music file changes until you press **Save genres**. Each file is checked against its scanned size, modification time, filesystem identity and genres before saving. Files changed since scanning are skipped. Each save reads the genres back and displays file-level failures in **skipped files / errors**.

## If saving fails

Open **skipped files / errors** to see the actual failing filename and reason. `Permission denied` means the configured container user needs write access to those files. `Read-only` means the mount or underlying filesystem is read-only. Docker does not bypass host permissions.

Inspect the configured container account and a failing file without modifying it:

```bash
docker compose exec genresorter id
docker compose exec genresorter stat '/music/Artist/Album/01 Track.flac'
```

Set `PUID`/`PGID` to the appropriate account in `.env`, then apply a configuration change with `docker compose up -d`. After correcting host permissions, rescan and preview again. Cache permission errors do not block scanning or music tag writes.

## Local verification

`tests/test_workflow.py` tests FLAC/MP3/M4A multivalue genre writes, artwork and other tag preservation, unchanged encoded audio packets, stale previews, folder boundaries, authentication and real file permission failures using synthesized sample files. It needs ffmpeg and the Python requirements. Run:

```bash
python -m unittest discover -s tests -v
```

The Python server and file workflow can run without Docker for development:

```bash
MUSIC_ROOT='/path/to/music' DATA_ROOT='/path/to/cache' APP_PASSWORD='your-password' python server.py
```

Mutagen is licensed under GPL v2 or later. This genreSorter Docker implementation is provided under GPL v2 or later; see `LICENSE.md`. Review Mutagen's source and license at https://github.com/quodlibet/mutagen.
