'use strict';
(() => {
  const key = value => value.normalize('NFC').trim().toLocaleLowerCase();
  function catalog(albums) {
    const entries = new Map();
    for (const album of albums) {
      const seen = new Set();
      for (const genre of album.genres) {
        const id = key(genre);
        if (!id || seen.has(id)) continue;
        seen.add(id);
        if (!entries.has(id)) entries.set(id, {id, name: genre.trim(), count: 0});
        entries.get(id).count++;
      }
    }
    return [...entries.values()].sort((a, b) => a.name.localeCompare(b.name));
  }
  function matches(album, genres, mode = 'any') {
    if (!genres.size) return true;
    const values = new Set(album.genres.map(key));
    return mode === 'all' ? [...genres].every(id => values.has(id)) : [...genres].some(id => values.has(id));
  }
  function filter(albums, query, genres, mode, onlyMatches) {
    query = key(query);
    return albums.filter(album => (!query || key(`${album.name} ${album.artist} ${album.genres.join(' ')}`).includes(query))
      && (!onlyMatches || matches(album, genres, mode)));
  }
  function page(items, index, size) {
    const pages = Math.max(1, Math.ceil(items.length / size));
    index = Math.max(0, Math.min(index, pages - 1));
    return {index, pages, start: index * size, items: items.slice(index * size, (index + 1) * size)};
  }
  function artists(albums) {
    const groups = new Map();
    for (const album of albums) {
      const name = album.artist.trim() || 'Unknown artist', id = key(name);
      if (!groups.has(id)) groups.set(id, {id, name, albums: []});
      groups.get(id).albums.push(album);
    }
    return [...groups.values()].sort((a, b) => a.name.localeCompare(b.name));
  }
  // Complete only the genre under the caret, preserving the other names in the field.
  function genreContext(value, caret = value.length) {
    caret = Math.max(0, Math.min(caret, value.length));
    let start = caret, end = caret;
    while (start && !/[,;\n]/.test(value[start - 1])) start--;
    while (end < value.length && !/[,;\n]/.test(value[end])) end++;
    const query = value.slice(start, end).trim();
    const used = new Set((value.slice(0, start) + ',' + value.slice(end)).split(/[,;\n]/).map(key).filter(Boolean));
    return {start, end, query, used};
  }
  function genreSuggestions(catalog, value, caret) {
    const context = genreContext(value, caret), query = key(context.query);
    if (!query) return [];
    return catalog.filter(genre => genre.id.includes(query) && !context.used.has(genre.id))
      .sort((a, b) => Number(!a.id.startsWith(query)) - Number(!b.id.startsWith(query)) || a.name.localeCompare(b.name));
  }
  function completeGenre(value, caret, name) {
    const {start, end} = genreContext(value, caret);
    const prefix = value.slice(0, start), suffix = value.slice(end);
    const insertion = (prefix ? ' ' : '') + name.trim() + (suffix ? '' : ', ');
    return {value: prefix + insertion + suffix, caret: prefix.length + insertion.length};
  }
  // Stable pseudorandom hue: identical genre names keep a colour across sessions/devices.
  // This encodes no musical similarity; unrelated genres may have nearby hues.
  function hue(genre) {
    let hash = 2166136261;
    for (const character of key(genre)) {
      hash ^= character.codePointAt(0);
      hash = Math.imul(hash, 16777619);
    }
    hash ^= hash >>> 16;
    hash = Math.imul(hash, 0x85ebca6b);
    hash ^= hash >>> 13;
    return Number(((hash >>> 0) / 4294967296 * 360).toFixed(2));
  }
  const utilities = {key, catalog, matches, filter, page, artists, hue, genreContext, genreSuggestions, completeGenre};
  if (typeof module !== 'undefined' && module.exports) module.exports = utilities;
  else globalThis.GenreBrowser = utilities;
})();
