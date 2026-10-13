'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const browser = require('../static/browser-utils.js');
const albums = [
  {id: 'a', name: 'First', artist: 'Artist A', genres: ['Jazz', 'City Pop'], tracks: [{genres: ['Jazz']}, {genres: ['City Pop']}]},
  {id: 'b', name: 'Second', artist: 'Artist B', genres: ['jazz', 'Jazz'], tracks: [{genres: ['jazz']}]},
  {id: 'c', name: 'Third', artist: 'Artist C', genres: [], tracks: [{genres: []}]}
];
test('catalog counts albums, merges case variants, and includes genres from mixed tracks', () => {
  assert.deepEqual(browser.catalog(albums), [{id: 'city pop', name: 'City Pop', count: 1}, {id: 'jazz', name: 'Jazz', count: 2}]);
});
test('any and all genre matching uses album union, including genres on separate songs', () => {
  const filters = new Set(['jazz', 'city pop']);
  assert.equal(browser.matches(albums[0], filters, 'all'), true);
  assert.equal(browser.matches(albums[1], filters, 'any'), true);
  assert.equal(browser.matches(albums[1], filters, 'all'), false);
  assert.equal(browser.matches(albums[2], filters, 'any'), false);
  assert.equal(browser.matches(albums[2], new Set(), 'all'), true);
});
test('highlight keeps nonmatching albums; only matches combines with album search', () => {
  const filters = new Set(['city pop']);
  assert.equal(browser.filter(albums, '', filters, 'any', false).length, 3);
  assert.deepEqual(browser.filter(albums, '', filters, 'any', true).map(a => a.id), ['a']);
  assert.equal(browser.filter(albums, 'Artist B', filters, 'any', true).length, 0);
  assert.deepEqual(browser.filter(albums, 'Jazz', filters, 'any', false).map(a => a.id), ['a', 'b']);
});
test('20,000 albums page in bounded groups and page clamps when filters reduce results', () => {
  const many = Array.from({length: 20000}, (_, id) => ({id, name: `Album ${id}`, artist: 'Artist', genres: id % 2 ? ['Jazz'] : ['Rock']}));
  const filtered = browser.filter(many, '', new Set(['jazz']), 'any', true);
  assert.equal(filtered.length, 10000);
  assert.equal(browser.catalog(many).find(g => g.id === 'jazz').count, 10000);
  const last = browser.page(filtered, 999, 200);
  assert.equal(last.items.length, 200);
  assert.equal(last.index, 49);
  assert.equal(last.items.at(-1).id, 19999);
  assert.equal(browser.page([], 12, 100).index, 0);
});

// Group after filtering/paging so large artist discographies stay bounded.
test('albums nest under artist groups while retaining each album identity', () => {
  const input = [albums[0], {...albums[1], artist: 'Artist A'}, albums[2], {...albums[0], id: 'unknown', artist: ''}];
  const groups = browser.artists(input);
  assert.equal(groups.length, 3);
  assert.deepEqual(groups[0].albums.map(a => a.id), ['a', 'b']);
  assert.equal(groups.at(-1).name, 'Unknown artist');
  assert.equal(browser.artists(browser.filter(input, 'Second', new Set(), 'any', false))[0].albums[0].id, 'b');
});

test('genre colours stay stable across name case/spacing and span the colour wheel', () => {
  assert.equal(browser.hue(' Jazz '), browser.hue('jazz'));
  assert.equal(browser.hue('City Pop'), browser.hue('City Pop'));
  const hues = ['Jazz', 'Rock', 'City Pop', 'Soul', 'Classical', 'Folk'].map(browser.hue);
  assert.equal(new Set(hues).size, hues.length);
  assert.ok(hues.every(hue => Number.isFinite(hue) && hue >= 0 && hue <= 360));
  assert.ok(Math.max(...hues) - Math.min(...hues) > 180);
});
