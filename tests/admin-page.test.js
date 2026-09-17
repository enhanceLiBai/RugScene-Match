const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8');

function node() {
  const classes = new Set();
  return {children: [], dataset: {}, value: '', files: [], elements: [], disabled: false,
    classList: {add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c)},
    append(...children) {this.children.push(...children);}, prepend(...children) {this.children.unshift(...children);},
    replaceChildren(...children) {this.children = children;}, reset() {}, scrollIntoView() {}, addEventListener() {},
  };
}

function page(htmlName, scripts) {
  const html = source(htmlName);
  const nodes = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map(m => [`#${m[1]}`, node()]));
  const tabs = [...html.matchAll(/data-view="([^"]+)"/g)].map(m => ({...node(), dataset: {view: m[1]}}));
  nodes['.dropzone-copy'] = node();
  const ready = [];
  const calls = [];
  const api = {listLibrary: async () => {calls.push('library'); return {images: []};},
    searchSimilar: async () => {calls.push('search'); return {results: [], history_id: 12};}};
  const context = {
    CarpetApiClient: {create: () => api, requestJson: async (_fetch, url) => {
      calls.push(url);
      if (url === '/api/history') return {items: [{id: 12, created_at: '2026-09-16', result_count: 0}], next_before: null};
      if (url === '/api/history/12') return {id: 12, created_at: '2026-09-16', query_image_url: '/api/history/12/image', payload: {results: []}};
      return {items: [], next_before: null};
    }}, CarpetMatcherCore: {}, URLSearchParams, fetch() {},
    URL: {createObjectURL: () => 'blob:test', revokeObjectURL() {}},
    sessionStorage: {getItem: () => null}, window: {addEventListener() {}},
    document: {querySelector: selector => nodes[selector] || null,
      querySelectorAll: selector => selector === '.tab' ? tabs : selector === '.tab,.view' ? [...tabs, ...['feedback', 'library', 'history', 'accounts'].map(id => nodes[`#${id}`])] : [],
      createElement: node, addEventListener: (_, fn) => ready.push(fn)},
  };
  vm.createContext(context);
  scripts.forEach(name => vm.runInContext(source(name), context, {filename: name}));
  ready.forEach(fn => fn());
  return {context, nodes, tabs, calls};
}

test('客服首页独立初始化并可提交匹配，不加载图库或历史', async () => {
  const p = page('index.html', ['orders.js', 'app.js']);
  assert.equal(p.nodes['#entryForm'], undefined);
  assert.equal(p.nodes['#historyList'], undefined);
  p.nodes['#queryImage'].onchange({target: {files: [{}]}});
  await p.nodes['#matchButton'].onclick();
  assert.deepEqual(p.calls, ['search']);
  assert.equal(p.nodes['#matchButton'].disabled, false);
});

test('后台初始化图库与反馈，历史列表和详情留在后台', async () => {
  const p = page('feedback.html', ['app.js', 'feedback.js', 'admin.js']);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(p.calls.includes('library'));
  assert.ok(p.calls.includes('/api/conversions?'));
  assert.equal(typeof p.nodes['#entryForm'].onsubmit, 'function');
  assert.equal(typeof p.nodes['#excelForm'].onsubmit, 'function');
  assert.equal(typeof p.nodes['#labelExisting'].onclick, 'function');
  p.tabs.find(tab => tab.dataset.view === 'history').onclick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(p.nodes['#history'].classList.contains('active'), true);
  assert.equal(p.nodes['#historyList'].children.length, 1);
  await p.nodes['#historyList'].children[0].onclick();
  assert.ok(p.calls.includes('/api/history/12'));
  assert.equal(p.nodes['#historyDetail'].hidden, false);
  assert.ok(p.nodes['#historyDetail'].children.length > 0);
  assert.equal(p.nodes['#matchButton'], undefined);
});

test('历史筛选切换清空旧详情，并在加载更多时保留时间条件', async () => {
  const p = page('feedback.html', ['app.js', 'feedback.js', 'admin.js']);
  await new Promise(resolve => setImmediate(resolve));
  p.context.CarpetApiClient.requestJson = async (_fetch, url) => {
    p.calls.push(url);
    return {items: [], next_before: 123};
  };
  p.nodes['#historyPeriod'].value = '3d';
  await p.nodes['#historyPeriod'].onchange();
  assert.ok(p.calls.includes('/api/history?period=3d'));
  assert.equal(p.nodes['#historyDetail'].hidden, true);
  await p.nodes['#historyMore'].onclick();
  assert.ok(p.calls.includes('/api/history?period=3d&before=123'));
  p.nodes['#historyPeriod'].value = 'today';
  await p.nodes['#historyPeriod'].onchange();
  assert.equal(p.calls.at(-1), '/api/history?period=today');
});

test('客服个人历史打开原照片与原排名，可在原记录补登记', async () => {
  const p = page('index.html', ['orders.js', 'app.js']);
  let rendered;
  p.context.renderResults = (...args) => {rendered = args;};
  p.context.CarpetApiClient.requestJson = async (_fetch, url) => {
    if (url === '/api/my-history') return {items: [{id: 8, created_at: '2026-09-16', result_count: 1}], next_before: null};
    return {id: 8, created_at: '2026-09-16', payload: {results: [{rank: 1, product_id: 'P1'}]}, query_image_url: '/api/my-history/8/image', conversion: null};
  };
  await p.context.loadMyHistory();
  await p.nodes['#myHistoryList'].children[0].onclick();
  assert.equal(rendered[0].history_id, 8);
  assert.equal(rendered[0].results[0].rank, 1);
  assert.equal(rendered[2], '/api/my-history/8/image');
  assert.equal(p.nodes['#viewingMyHistory'].hidden, false);
  assert.equal(p.nodes['#queryImage'].value, '');
  assert.equal(p.nodes['#matchButton'].disabled, false);
});
