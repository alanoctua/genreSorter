'use strict';
const $ = id => document.getElementById(id);
let state = {albums: [], warnings: [], revision: -1, generation: -1, busy: false, folder: ''};
let selected = new Set(), plan = null, pending = false, browsing = '';
let genreFilters = new Set(), genreCatalog = [], albumPage = 0, trackPage = 0;
const collapsedArtists = new Set();
const browser = GenreBrowser;
function matching(album) { return browser.matches(album, genreFilters, $('genreMode').value); }
function albumResults() { return browser.filter(state.albums, $('search').value, genreFilters, $('genreMode').value, $('onlyMatches').checked); }
function currentPage() { return browser.page(albumResults(), albumPage, Number($('pageSize').value)); }
function renderGenreTags() {
  const query = browser.key($('genreSearch').value);
  const fragment = document.createDocumentFragment();
  for (const genre of genreCatalog.filter(genre => browser.key(genre.name).includes(query))) {
    const button = node('button', undefined, `genre-tag${genreFilters.has(genre.id) ? ' active' : ''}`);
    button.type = 'button';
    colourGenre(button, genre.name);
    button.setAttribute('aria-pressed', String(genreFilters.has(genre.id)));
    button.title = `${genre.count} albums include this genre on at least one track`;
    button.append(node('span', '', 'genre-swatch'), node('span', genre.name), node('span', String(genre.count), 'genre-count'));
    button.addEventListener('click', () => {
      genreFilters.has(genre.id) ? genreFilters.delete(genre.id) : genreFilters.add(genre.id);
      albumPage = 0; renderGenreTags(); renderAlbums();
    });
    fragment.append(button);
  }
  if (!fragment.childNodes.length) fragment.append(node('p', genreCatalog.length ? 'No matching genres.' : 'Genres appear as tracks are scanned.', 'hint'));
  $('genreCount').textContent = genreCatalog.length;
  $('genreTags').replaceChildren(fragment);
}


async function api(url, body) {
  const options = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-GenreSorter-Request': '1'}, body: JSON.stringify(body)};
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}
function error(message) {
  $('requestError').textContent = message;
  $('requestError').classList.toggle('hidden', !message);
}
function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function colourGenre(element, genre) {
  element.style.setProperty('--genre-hue', browser.hue(genre));
  element.classList.add('genre-colour');
}
function genreChips(values, className = 'album-genres', prefix = '') {
  const line = node('div', undefined, className);
  if (prefix) line.append(node('span', prefix));
  if (!values.length) { line.append(node('span', 'No genres', 'no-genres')); return line; }
  for (const genre of values) {
    const chip = node('span', undefined, 'genre-chip');
    colourGenre(chip, genre);
    chip.append(node('span', '', 'genre-swatch'), node('span', genre));
    line.append(chip);
  }
  return line;
}
function genreText(values) { return values.length ? values.join(' · ') : 'No genres'; }
function visible() { return currentPage().items; }
function controls() {
  const busy = state.busy || pending;
  $('chooseFolder').disabled = busy;
  $('scan').disabled = busy;
  $('preview').disabled = busy || !selected.size;
  $('save').disabled = busy || !plan || !plan.count;
  $('selectedCount').textContent = `${selected.size} selected`;
  $('changeCount').textContent = plan ? `${plan.count} files will change` : '';
  $('activity').classList.toggle('busy', busy);
}
function invalidate() {
  if (plan) { plan = null; renderTracks(); }
  controls();
}
function renderAlbums() {
  const artistGroups = browser.artists(state.albums);
  const allArtists = new Map(artistGroups.map(artist => [artist.id, artist]));
  const trackCount = state.albums.reduce((total, album) => total + album.count, 0);
  $('albumCount').textContent = `${state.albums.length.toLocaleString()} albums · ${artistGroups.length.toLocaleString()} artists · ${trackCount.toLocaleString()} tracks`;
  const results = albumResults(), page = browser.page(results, albumPage, Number($('pageSize').value));
  albumPage = page.index;
  $('albumRange').textContent = results.length ? `${page.start + 1}–${page.start + page.items.length} of ${results.length.toLocaleString()}` : '0 albums';
  $('pageNumber').textContent = `${page.index + 1} / ${page.pages}`;
  $('previousPage').disabled = !page.index;
  $('nextPage').disabled = page.index + 1 === page.pages;
  const matchCount = genreFilters.size ? results.filter(matching).length : 0;
  $('matchSummary').textContent = genreFilters.size ? `${matchCount.toLocaleString()} matching albums · ${genreFilters.size} genres selected. A genre on any track counts.` : 'Click genres to highlight matching albums.';
  $('selectMatching').disabled = !genreFilters.size || !matchCount;
  const fragment = document.createDocumentFragment();
  for (const artist of browser.artists(page.items)) {
    const group = node('details', undefined, 'artist-group');
    group.open = !collapsedArtists.has(artist.id);
    const heading = node('summary', undefined, 'artist-heading');
    const members = allArtists.get(artist.id).albums;
    const artistCheckbox = node('input', undefined, 'artist-checkbox'); artistCheckbox.type = 'checkbox';
    artistCheckbox.setAttribute('aria-label', `Select all ${members.length} albums by ${artist.name}`);
    artistCheckbox.title = `Select or deselect all ${members.length} scanned albums by ${artist.name}, including other pages and filtered albums`;
    function syncArtistCheckbox() {
      const count = members.reduce((total, album) => total + Number(selected.has(album.id)), 0);
      artistCheckbox.checked = count === members.length;
      artistCheckbox.indeterminate = count > 0 && count < members.length;
    }
    syncArtistCheckbox();
    artistCheckbox.addEventListener('click', event => event.stopPropagation());
    artistCheckbox.addEventListener('change', () => {
      for (const album of members) artistCheckbox.checked ? selected.add(album.id) : selected.delete(album.id);
      trackPage = 0; invalidate(); renderAlbums(); renderTracks();
    });
    heading.append(artistCheckbox, node('span', artist.name, 'artist-name'), node('span', `${artist.albums.length} on page · ${members.length} total albums`, 'count'));
    group.append(heading);
    const grid = node('div', undefined, 'artist-albums');
    for (const album of artist.albums) {
    const isMatch = genreFilters.size && matching(album);
    const label = node('label', undefined, `album${selected.has(album.id) ? ' selected' : ''}${isMatch ? ' genre-match' : ''}`);
    const checkbox = node('input'); checkbox.type = 'checkbox'; checkbox.checked = selected.has(album.id);
    checkbox.setAttribute('aria-label', `Select ${album.name} by ${album.artist}`);
    checkbox.addEventListener('change', () => {
      checkbox.checked ? selected.add(album.id) : selected.delete(album.id);
      label.classList.toggle('selected', checkbox.checked); syncArtistCheckbox();
      trackPage = 0; invalidate(); renderTracks(); controls();
    });
    const info = node('div', undefined, 'album-info');
    const title = node('div', album.name, 'album-name'); title.title = album.name;
    info.append(title, node('div', `${album.artist} · ${album.count} tracks`, 'album-meta'));
    const genres = genreChips(album.genres); genres.title = genreText(album.genres); info.append(genres);
    if (album.mixed) info.append(node('div', 'Mixed track genres', 'album-note'));
    if (album.readonly_count) info.append(node('div', `${album.readonly_count} files need write permission`, 'album-note'));
    label.append(checkbox, info); grid.append(label);
    }
    group.append(grid);
    group.addEventListener('toggle', () => {
      if (!group.isConnected) return;
      group.open ? collapsedArtists.delete(artist.id) : collapsedArtists.add(artist.id);
    });
    fragment.append(group);
  }
  if (!page.items.length) fragment.append(node('p', state.albums.length ? 'No matching albums.' : 'Choose your music folder and scan its tags.', 'empty'));
  $('albums').replaceChildren(fragment);
}
function renderTracks() {
  $('trackTitle').textContent = plan ? 'Preview by track' : 'Current genres by track';
  const rows = plan ? plan.changes : state.albums.filter(album => selected.has(album.id)).flatMap(album => album.tracks);
  const fragment = document.createDocumentFragment();
  const page = browser.page(rows, trackPage, 100); trackPage = page.index;
  $('trackRange').textContent = rows.length ? `${page.start + 1}–${page.start + page.items.length} of ${rows.length.toLocaleString()} tracks` : '0 tracks';
  $('previousTracks').disabled = !page.index;
  $('nextTracks').disabled = page.index + 1 === page.pages;
  for (const row of page.items) {
    const item = node('div', undefined, 'track');
    item.append(node('div', row.title || row.path.split('/').pop(), 'track-name'), node('div', row.path, 'track-path'));
    if (plan) {
      item.append(genreChips(row.before, 'genre-line', 'Before: '), genreChips(row.after, 'genre-line after', 'After: '));
    } else item.append(genreChips(row.genres, 'genre-line'));
    fragment.append(item);
  }
  if (!rows.length) fragment.append(node('p', plan ? 'No files need changing.' : 'Select albums to view their track genres.', 'empty'));
  $('tracks').replaceChildren(fragment);
}
function renderErrors() {
  const messages = [...(state.warnings || []), ...(state.last_write?.errors || []).map(row => `${row.path}\n${row.error}`)];
  $('errors').classList.toggle('hidden', !messages.length);
  $('errorSummary').textContent = `${messages.length} skipped files / errors`;
  $('errorList').replaceChildren(...messages.map(message => node('div', message, 'error-item')));
  $('cacheNote').textContent = state.cache_note || '';
}
async function refresh() {
  const next = await api(`/api/state?since=${state.revision}`);
  const changed = !next.unchanged;
  if (next.generation !== state.generation) plan = null;
  if (next.folder !== state.folder) { selected.clear(); genreFilters.clear(); collapsedArtists.clear(); albumPage = 0; trackPage = 0; }
  state = {...state, ...next};
  if (!state.busy) {
    const available = new Set(state.albums.map(album => album.id));
    selected = new Set([...selected].filter(id => available.has(id)));
  }
  $('status').textContent = state.status;
  $('folderLabel').textContent = '/music' + (state.folder && state.folder !== '.' ? '/' + state.folder : '');
  $('scan').textContent = state.albums.length ? 'Rescan' : 'Scan music';
  if (changed) { genreCatalog = browser.catalog(state.albums); renderGenreTags(); renderAlbums(); renderTracks(); renderErrors(); }
  controls();
}
async function polling() {
  try { await refresh(); } catch (exc) { error(exc.message); }
  setTimeout(polling, state.busy ? 700 : 2000);
}
async function scan(folder = state.folder, force = false) {
  error(''); pending = true; invalidate();
  try { await api('/api/scan', {folder, force}); await refresh(); } catch (exc) { error(exc.message); }
  finally { pending = false; controls(); }
}
async function browse(path) {
  try {
    const result = await api(`/api/folders?path=${encodeURIComponent(path)}`);
    browsing = result.path === '.' ? '' : result.path;
    $('browsePath').textContent = '/music' + (browsing ? '/' + browsing : '');
    $('upFolder').disabled = !browsing;
    const fragment = document.createDocumentFragment();
    for (const folder of result.folders) {
      const button = node('button', folder.name); button.addEventListener('click', () => browse(folder.path)); fragment.append(button);
    }
    if (!result.folders.length) fragment.append(node('p', 'No subfolders. You can scan this folder.', 'empty'));
    $('folders').replaceChildren(fragment);
    if (!$('folderDialog').open) $('folderDialog').showModal();
  } catch (exc) { error(exc.message); }
}
$('scan').addEventListener('click', event => scan(state.folder, event.shiftKey));
$('chooseFolder').addEventListener('click', () => browse(state.folder));
$('closeFolder').addEventListener('click', () => $('folderDialog').close());
$('rootFolder').addEventListener('click', () => browse(''));
$('upFolder').addEventListener('click', () => browse(browsing.split('/').slice(0, -1).join('/')));
$('useFolder').addEventListener('click', () => { $('folderDialog').close(); scan(browsing); });
$('search').addEventListener('input', () => { albumPage = 0; renderAlbums(); });
$('genreSearch').addEventListener('input', renderGenreTags);
for (const id of ['genreMode', 'onlyMatches', 'pageSize']) $(id).addEventListener('change', () => { albumPage = 0; renderAlbums(); });
$('clearGenres').addEventListener('click', () => { genreFilters.clear(); albumPage = 0; renderGenreTags(); renderAlbums(); });
$('previousPage').addEventListener('click', () => { albumPage--; renderAlbums(); $('albums').scrollTop = 0; });
$('nextPage').addEventListener('click', () => { albumPage++; renderAlbums(); $('albums').scrollTop = 0; });
$('previousTracks').addEventListener('click', () => { trackPage--; renderTracks(); $('tracks').scrollTop = 0; });
$('nextTracks').addEventListener('click', () => { trackPage++; renderTracks(); $('tracks').scrollTop = 0; });
$('selectMatching').addEventListener('click', () => { albumResults().filter(matching).forEach(album => selected.add(album.id)); trackPage = 0; invalidate(); renderAlbums(); renderTracks(); });
$('selectVisible').addEventListener('click', () => { visible().forEach(album => selected.add(album.id)); trackPage = 0; invalidate(); renderAlbums(); renderTracks(); });
$('clear').addEventListener('click', () => { selected.clear(); trackPage = 0; invalidate(); renderAlbums(); renderTracks(); });
for (const id of ['add', 'remove', 'aliases']) $(id).addEventListener('input', invalidate);
$('replaceGenres').addEventListener('change', () => {
  const replace = $('replaceGenres').checked;
  $('remove').disabled = replace;
  $('addLabel').textContent = replace ? 'New genres' : 'Add genres';
  $('replaceHelp').textContent = replace ? 'Checked: delete every old genre and use only the new genres above. Leave New genres empty to clear all genres. Preview before saving.' : 'Unchecked: keep each track’s current genres and add or remove specific names.';
  invalidate();
});
$('normalize').addEventListener('change', () => { $('aliases').disabled = !$('normalize').checked; invalidate(); });
$('preview').addEventListener('click', async () => {
  error(''); pending = true; controls();
  try {
    plan = await api('/api/preview', {albums: [...selected], add: $('add').value, remove: $('remove').value, replace: $('replaceGenres').checked, normalize: $('normalize').checked, aliases: $('aliases').value});
    trackPage = 0; renderTracks();
  } catch (exc) { plan = null; error(exc.message); renderTracks(); }
  finally { pending = false; controls(); }
});
$('save').addEventListener('click', async () => {
  if (!plan || !plan.count) return;
  error(''); pending = true; controls();
  try { await api('/api/write', {token: plan.token}); plan = null; await refresh(); }
  catch (exc) { error(exc.message); }
  finally { pending = false; controls(); }
});
(async () => {
  try { const config = await api('/api/config'); $('buildVersion').textContent = config.version ? `v${config.version}` : 'Server version unknown'; $('aliases').value = config.aliases; $('identity').textContent = `Server user: UID ${config.uid} · GID ${config.gid}`; }
  catch (exc) { error(exc.message); }
  polling();
})();
