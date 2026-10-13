'use strict';
const $ = id => document.getElementById(id);
let state = {albums: [], warnings: [], revision: -1, generation: -1, busy: false, folder: ''};
let selected = new Set(), plan = null, pending = false, browsing = '';

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
function genreText(values) { return values.length ? values.join(' · ') : 'No genres'; }
function visible() {
  const query = $('search').value.trim().toLocaleLowerCase();
  return state.albums.filter(album => `${album.name} ${album.artist} ${album.genres.join(' ')}`.toLocaleLowerCase().includes(query));
}
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
  $('albumCount').textContent = state.albums.length;
  const fragment = document.createDocumentFragment();
  for (const album of visible()) {
    const label = node('label', undefined, `album${selected.has(album.id) ? ' selected' : ''}`);
    const checkbox = node('input'); checkbox.type = 'checkbox'; checkbox.checked = selected.has(album.id);
    checkbox.addEventListener('change', () => {
      checkbox.checked ? selected.add(album.id) : selected.delete(album.id);
      label.classList.toggle('selected', checkbox.checked);
      invalidate(); renderTracks(); controls();
    });
    const info = node('div', undefined, 'album-info');
    info.append(node('div', album.name, 'album-name'), node('div', `${album.artist} · ${album.count} tracks`, 'album-meta'), node('div', genreText(album.genres), 'album-genres'));
    if (album.mixed) info.append(node('div', 'Different genres across tracks', 'album-note'));
    if (album.readonly_count) info.append(node('div', `${album.readonly_count} files need write permission`, 'album-note'));
    label.append(checkbox, info); fragment.append(label);
  }
  if (!fragment.childNodes.length) fragment.append(node('p', state.albums.length ? 'No matching albums.' : 'Choose your music folder and scan its tags.', 'empty'));
  $('albums').replaceChildren(fragment);
}
function renderTracks() {
  $('trackTitle').textContent = plan ? 'Preview by track' : 'Current genres by track';
  const rows = plan ? plan.changes : state.albums.filter(album => selected.has(album.id)).flatMap(album => album.tracks);
  const fragment = document.createDocumentFragment();
  for (const row of rows) {
    const item = node('div', undefined, 'track');
    item.append(node('div', row.title || row.path.split('/').pop(), 'track-name'), node('div', row.path, 'track-path'));
    if (plan) {
      item.append(node('div', `Before: ${genreText(row.before)}`, 'genre-line'), node('div', `After: ${genreText(row.after)}`, 'genre-line after'));
    } else item.append(node('div', genreText(row.genres), 'genre-line'));
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
  if (next.folder !== state.folder) selected.clear();
  state = {...state, ...next};
  if (!state.busy) {
    const available = new Set(state.albums.map(album => album.id));
    selected = new Set([...selected].filter(id => available.has(id)));
  }
  $('status').textContent = state.status;
  $('folderLabel').textContent = '/music' + (state.folder && state.folder !== '.' ? '/' + state.folder : '');
  $('scan').textContent = state.albums.length ? 'Rescan' : 'Scan music';
  if (changed) { renderAlbums(); renderTracks(); renderErrors(); }
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
$('search').addEventListener('input', renderAlbums);
$('selectVisible').addEventListener('click', () => { visible().forEach(album => selected.add(album.id)); invalidate(); renderAlbums(); renderTracks(); });
$('clear').addEventListener('click', () => { selected.clear(); invalidate(); renderAlbums(); renderTracks(); });
for (const id of ['add', 'remove', 'aliases']) $(id).addEventListener('input', invalidate);
$('normalize').addEventListener('change', () => { $('aliases').disabled = !$('normalize').checked; invalidate(); });
$('preview').addEventListener('click', async () => {
  error(''); pending = true; controls();
  try {
    plan = await api('/api/preview', {albums: [...selected], add: $('add').value, remove: $('remove').value, normalize: $('normalize').checked, aliases: $('aliases').value});
    renderTracks();
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
  try { const config = await api('/api/config'); $('aliases').value = config.aliases; $('identity').textContent = `Server user: UID ${config.uid} · GID ${config.gid}`; }
  catch (exc) { error(exc.message); }
  polling();
})();
