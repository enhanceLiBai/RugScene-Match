const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const appSource = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');

function element(textContent = '') {
  return {
    className: '',
    dataset: {},
    disabled: false,
    hidden: false,
    textContent,
  };
}

function createGrid(initialChildren = []) {
  return {
    children: [...initialChildren],
    replaceChildren(...children) { this.children = children; },
    append(...children) { this.children.push(...children); },
  };
}

function loadApp(api, nodes) {
  let ready;
  const document = {
    addEventListener: (name, listener) => {
      if (name === 'DOMContentLoaded') ready = listener;
    },
    createElement: (tagName) => ({ ...element(), tagName, append() {} }),
    querySelector: (selector) => nodes[selector],
    querySelectorAll: () => [],
  };
  const context = {
    CarpetApiClient: { create: () => api },
    CarpetMatcherCore: {
      buildPresentation: () => ({ productName: '', sku: '', chips: [] }),
      buildRecommendationScript: () => '',
    },
    URL: { createObjectURL: () => 'blob:preview' },
    document,
    navigator: { clipboard: { writeText: async () => {} } },
    setTimeout,
  };
  vm.runInNewContext(appSource, context, { filename: 'app.js' });
  return { context, ready };
}

function pageNodes() {
  return {
    '#reloadLibraryButton': element('刷新图库'),
    '#libraryStatus': element(),
    '#libraryGrid': createGrid(),
    '#libraryCount': element('0'),
    '#queryImage': { ...element(), files: [] },
    '#queryPreview': { ...element(), hidden: true, src: '' },
    '.dropzone-copy': element(),
    '#entryImage': { ...element(), files: [] },
    '#entryPreview': { ...element(), hidden: true, src: '' },
    '#entryImageText': element(),
    '#matchButton': element('开始匹配'),
    '#matchHint': element(),
    '#results': { ...element(), hidden: false },
    '#resultGrid': createGrid(),
    '#entryForm': element(),
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

test('图库刷新失败保留上一轮列表和计数并恢复刷新按钮', async () => {
  const priorCard = { id: 'prior-card' };
  const nodes = pageNodes();
  nodes['#libraryGrid'] = createGrid([priorCard]);
  nodes['#libraryCount'].textContent = '1';
  const api = { listLibrary: async () => { throw new Error('服务暂不可用'); } };
  const { context } = loadApp(api, nodes);

  await context.refreshLibrary();

  assert.deepEqual(nodes['#libraryGrid'].children, [priorCard]);
  assert.equal(nodes['#libraryCount'].textContent, '1');
  assert.equal(nodes['#libraryStatus'].textContent, '服务暂不可用');
  assert.equal(nodes['#reloadLibraryButton'].disabled, false);
  assert.equal(nodes['#reloadLibraryButton'].textContent, '刷新图库');
});

test('搜索期间锁定输入并隐藏旧结果，空结果后恢复按钮和输入', async () => {
  const nodes = pageNodes();
  const pending = deferred();
  const query = { name: 'query-a.png' };
  const api = {
    listLibrary: async () => ({ images: [] }),
    searchSimilar: () => pending.promise,
  };
  const { ready } = loadApp(api, nodes);
  ready();
  nodes['#queryImage'].files = [query];
  nodes['#queryImage'].onchange({ target: nodes['#queryImage'] });

  const request = nodes['#matchButton'].onclick();
  const disabledDuringRequest = nodes['#queryImage'].disabled;
  const hiddenDuringRequest = nodes['#results'].hidden;
  pending.resolve({ results: [], message: '当前模型没有可检索向量。' });
  await request;

  assert.equal(disabledDuringRequest, true);
  assert.equal(hiddenDuringRequest, true);
  assert.equal(nodes['#results'].hidden, true);
  assert.equal(nodes['#matchHint'].textContent, '当前模型没有可检索向量。');
  assert.equal(nodes['#queryImage'].disabled, false);
  assert.equal(nodes['#matchButton'].disabled, false);
  assert.equal(nodes['#matchButton'].textContent, '开始匹配');
});

test('搜索失败后恢复按钮和输入并显示错误', async () => {
  const nodes = pageNodes();
  const pending = deferred();
  const api = {
    listLibrary: async () => ({ images: [] }),
    searchSimilar: () => pending.promise,
  };
  const { ready } = loadApp(api, nodes);
  ready();
  nodes['#queryImage'].files = [{ name: 'query-a.png' }];
  nodes['#queryImage'].onchange({ target: nodes['#queryImage'] });

  const request = nodes['#matchButton'].onclick();
  const disabledDuringRequest = nodes['#queryImage'].disabled;
  pending.reject(new Error('匹配服务繁忙'));
  await request;

  assert.equal(disabledDuringRequest, true);
  assert.equal(nodes['#queryImage'].disabled, false);
  assert.equal(nodes['#matchButton'].disabled, false);
  assert.equal(nodes['#matchButton'].textContent, '开始匹配');
  assert.equal(nodes['#matchHint'].textContent, '匹配服务繁忙');
});
