# genreSorter for Docker / OMV

This source bundle is **v0.3.7**: MusicBrainz artist genre suggestions, live genre autocomplete, fainter genre placeholders, the supplied app logo, artist grouping, coloured genres, genre filters, and Remove previous genres. The original PNG is used unchanged in the header. Browser icons are separately generated at 16px and 32px (PNG) plus a multi-size 16/32/48px ICO; the Apple touch icon is 180px. Resizing preserves the logo proportions and transparency with a square canvas. Icon URLs have a version query to refresh cached favicons. The app status bar displays the server version and the first seven characters of the build commit. `/api/config` includes both the version and full revision.

Browser app for viewing and bulk editing album genres. FLAC, MP3 and M4A supported. Choose a mounted music folder, scan, multi-select albums, add/remove genres or normalize aliases, preview every affected track, then Save genres. Saves modify genre tags on the chosen server files directly. The music library is not copied or re-encoded.

## Install the published image on OMV

1. Put only `compose.yaml` and `.env.example` in a server folder, for example `/srv/appdata/genreSorter`. The source code stays on GitHub and the image is downloaded from GHCR.
2. Run `id YOUR_SERVER_USER` on the server. Note the numeric `uid` and `gid` of the account with write access to your music.
3. In the project folder, run `cp .env.example .env` and edit `.env`:
   - `MUSIC_PATH`: full server path to your music folder, not the Mac `/Volumes/...` path.
   - `GENRESORTER_IMAGE`: `ghcr.io/YOUR_GITHUB_USERNAME/genresorter:latest`, using the actual owner of the published repository. This is a template until the image has been built and made public.
   - `PUID` and `PGID`: the numbers from step 2. The container uses these IDs; it does not change file ownership or permissions.
   - `APP_PASSWORD`: choose a password. The placeholder is refused at startup.
   - `PORT`: 8787 by default; change if already occupied.
4. Run:

```bash
docker compose up -d
```

5. Open `http://YOUR-SERVER-IP:8787` in your browser. Username **admin**, password from `.env`.
6. Choose a folder within `/music` or press **Scan music** for the mounted root. Select albums, type genres, **Preview changes**, then **Save genres**.

The default address listens on your server's network interfaces. Keep this tool on your home network. You can set `BIND_ADDRESS` to your server's LAN IP to bind only that interface.

The published-image Compose file uses `pull_policy: always`, so **Up** checks the registry for the selected image tag and recreates the service when its image changes. This happens when you run Up; it is not a background automatic updater. Existing OMV installations need to add `pull_policy: always` below their image line.

To update the installed image:

```bash
docker compose pull
docker compose up -d
```

## Publish from GitHub

Create a public GitHub repository named `genreSorter` and put this folder's contents at the repository root, including `.github/workflows/docker-image.yml` and `.env.example`. Do not upload your filled `.env`, cache or music. The workflow checks out the exact triggering commit, runs the file tests, and publishes a candidate with a commit SHA tag for Linux AMD64 and ARM64. It pulls that published candidate by its digest and verifies the embedded app version and commit on both architectures. Only a verified commit that is still the head of `main` is promoted to `ghcr.io/OWNER/genresorter:latest`; release tags and old reruns cannot move latest backwards. The job verifies the resulting latest digest and reports it in the workflow summary. Thus latest follows the most recent successfully verified main build, not a commit whose tests or publish failed. It uses GitHub's automatically supplied `GITHUB_TOKEN`; you do not need to create a registry password for the workflow.

After the first successful publish, open the resulting package in your GitHub profile's **Packages** page, select **Package settings**, and change its visibility to **Public**. GitHub container packages start private. A public package can be pulled on OMV without a GitHub login. Only after publishing should you use the image in compose.

Push a version tag such as `v0.1.0` to publish the matching `0.1.0` image tag. Use a numbered version tag in `.env` if you want to choose when to upgrade, or an image digest if you need an exact build.

For development or building before the image is published, keep the entire source folder and run:

```bash
docker compose -f compose.build.yaml up -d --build
```

## Browse large folders by genre

The album area fills the main window with a compact grid nested under collapsible artist headings. Artist groups use album artist when available, otherwise the track artist. Each artist heading has a checkbox to select or deselect all scanned albums for that artist, including albums on other pages or hidden by a filter. A partially selected artist shows a mixed checkbox. Album, artist and track totals appear at the top. Albums are paged at 50, 100, 200 or 500 per page; selections remain selected when changing pages or filters. The track view shows 100 tracks per page, including change previews, to keep large batch selections manageable.

**Existing genres** lists every genre found in the scanned folder, with the number of albums containing it on at least one track. Click one or more genres to highlight matching albums. **Match any** matches at least one selected genre; **Match all** requires every selected genre somewhere on the album (the genres can appear on different tracks). Turn on **Only show matches** to hide other albums. Search genres separately from the album/artist search.

**Select page** selects the displayed page. **Select all matching** selects every album matching the chosen genres and album search, across all pages. Genre highlights do not select albums for editing automatically. Existing album selections remain selected even when hidden by a filter; **Clear selection** resets them. Preview and Save use the selected albums and retain the existing batch add/remove/alias workflow. A single save supports up to 20,000 tracks.

## Genre colours

Every genre has a stable, pseudorandom colour based on its name. The same name, ignoring case and surrounding whitespace, keeps the same colour on filter buttons, album labels and track previews, across rescans and browser sessions. Colours affect the interface only and are not written into music tags. Active filters remain marked separately with an outline and checkmark.

Colours currently do **not** represent musical similarity. Nearby colours can occur by chance. Related-genre families would need an explicit grouping rule or mapping; no genre families are guessed automatically.

## Genre suggestions while typing

The Add/New genres and Remove genres fields show matching names from all scanned albums as you type. Matches ignore case and include the typed text anywhere in a genre name, with names starting with it shown first. Each comma- or semicolon-separated genre is completed separately; choosing a suggestion keeps the other names in the field and adds a separator at the end for the next name. Already-entered names are excluded. Click a suggestion or use Up/Down and Enter; Escape dismisses the list. If Add/New genres has no match, enter your own name or choose **Use new genre**. The name is only written after Preview and Save. The existing genre catalog refreshes after saving. Autocomplete uses the scanned library locally, without online requests.

## MusicBrainz artist genre suggestions

Select albums belonging to one artist (the artist checkbox can select the whole discography), then click **Suggest genres** in Bulk edit. Choose the correct artist from the MusicBrainz matches; names, artist types and disambiguation/area details help distinguish namesakes. The next screen lists that artist's MusicBrainz genres with their community vote counts and a source link. Up to five genres with positive votes start checked; change the selection as needed. Click **Add to genre field** to merge them with any text already entered. Existing library spellings are reused when they match case-insensitively. Suggestions invalidate an older preview and never save automatically. Preview and Save remain required. Remove previous genres and normalization retain their usual meaning.

This is artist-level guidance: it does not infer the genre of each album or listen to audio. Some artists have no MusicBrainz genres. Multiple artists cannot share one suggestion form; select one artist at a time. Old responses are discarded if the selection or scan changes, and closing the dialog leaves the form untouched.

No API key or new dependency is required. The Python standard library calls the public MusicBrainz JSON API from the server. Only the selected artist name is sent for search, and a MusicBrainz artist ID is sent for genre lookup; audio, file paths, server credentials and other tags are not sent. Lookups happen only when requested, are serialized to at most one request per second, use an identifying User-Agent, have an eight-second network timeout, and cache up to 256 responses in memory for 24 hours. The server needs outbound HTTPS access to musicbrainz.org. Errors and empty results are shown in the dialog; you can always enter genres manually.

## Replace all previous genres

Check **Remove previous genres** and enter the full replacement list in **New genres**. Every selected track loses all of its previous genres and receives only that list. The Remove names field is disabled and ignored in this mode. Leaving New genres empty clears every genre from selected tracks. Unchecking the option restores the normal add/remove behavior. Nothing is written until Preview and Save.

**Normalize genre names** uses the editable rules below it. A line such as `City Pop = Citypop, City-Pop` turns the names on the right into the preferred name on the left. It does not infer genres from audio. Names outside these rules stay as they are (apart from trimming whitespace and removing duplicates). With replacement enabled, normalization applies to the new names only. Every result is shown in Preview.

## Confirm the update reached OMV

Upload the updated `server.py`, `tags.py`, `musicbrainz.py`, `Dockerfile`, `static` folder, `tests` folder, and `README.md` at the existing repository root. Keep the working publishing workflow. Wait for the latest commit's publish job to finish successfully, then select this app in OMV Compose and use **Pull**, followed by **Up**. Refresh the app page; the status bar must display **v0.3.7**. Pull downloads an image; Up recreates the container with it. Updating this repository does not rewrite an existing OMV Compose file. Restart alone can keep the old image.

If you see an older version (or no version), the new build has not reached the running app. If you see “Server version unknown”, the page and server files are from different builds. Compare the version and revision from the published image and running container to locate that mismatch. In the directory containing your configured Compose file, `docker compose up -d --pull always --force-recreate` replaces a stale container with the selected image. Named volumes and the music bind mount are preserved. No music scan or tag save is required just to check the version.

## Genres and scanning

Genres entered in the editor are separated by commas or semicolons. Each track keeps its other genres. Removing a name is case-insensitive; when a name is in both Add and Remove, Remove wins. Normalization uses explicit alias rules (`City Pop = Citypop, City-Pop`) and applies only to selected albums. Existing semicolon-separated genre values become separate values when an edit is applied. A slash stays part of the name.

Albums group by album artist + album title. Missing album tags use the containing folder name. Current genres are shown at album and track level, including albums whose tracks differ. Scanning publishes albums progressively and caches unchanged metadata in `/data`. **Shift-click Rescan** to reread all metadata. Saving refreshes only the affected tracks. MP3 multivalue genres are saved as ID3v2.4 TCON values; FLAC uses multiple Vorbis genre values; M4A uses multiple text genre values.

No music file changes until you press **Save genres**. Each file is checked against its scanned size, modification time, filesystem identity and genres before saving. Files changed since scanning are skipped. Each save reads the genres back and displays file-level failures in **skipped files / errors**.

## If saving fails

Open **skipped files / errors** to see the actual failing filename and reason. `Permission denied` means the configured container user needs write access to those files. `Read-only` means the mount or underlying filesystem is read-only. Docker does not bypass host permissions.

Inspect the configured container account and a failing file without modifying it:

```bash
docker compose exec genreSorter id
docker compose exec genreSorter stat '/music/Artist/Album/01 Track.flac'
```

Set `PUID`/`PGID` to the appropriate account in `.env`, then apply a configuration change with `docker compose up -d`. After correcting host permissions, rescan and preview again. Cache permission errors do not block scanning or music tag writes.

## Local verification

`tests/test_workflow.py` tests FLAC/MP3/M4A multivalue genre writes, artwork and other tag preservation, unchanged encoded audio packets, stale previews, folder boundaries, authentication and real file permission failures using synthesized sample files. It needs ffmpeg and the Python requirements. Run:

```bash
python -m unittest discover -s tests -v
node --test tests/test_browser.cjs
```

The Python server and file workflow can run without Docker for development:

```bash
MUSIC_ROOT='/path/to/music' DATA_ROOT='/path/to/cache' APP_PASSWORD='your-password' python server.py
```

Mutagen is licensed under GPL v2 or later. This genreSorter Docker implementation is provided under GPL v2 or later; see `LICENSE.md`. Review Mutagen's source and license at https://github.com/quodlibet/mutagen.
