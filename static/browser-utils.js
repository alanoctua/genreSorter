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
  const utilities = {key, catalog, matches, filter, page};
  if (typeof module !== 'undefined' && module.exports) module.exports = utilities;
  else globalThis.GenreBrowser = utilities;
})();
