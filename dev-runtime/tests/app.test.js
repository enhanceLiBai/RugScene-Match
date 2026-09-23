const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const appSource = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
const indexSource = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');

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

function loadApp(api, nodes, options = {}) {
  let ready;
  const windowListeners = {};
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
    URL: options.URL || { createObjectURL: () => 'blob:preview', revokeObjectURL: () => {} },
    document,
    navigator: { clipboard: { writeText: async () => {} } },
    setTimeout,
    window: {
      addEventListener: (name, listener) => { windowListeners[name] = listener; },
    },
  };
  vm.runInNewContext(appSource, context, { filename: 'app.js' });
  return { context, ready, windowListeners };
}

function pageNodes() {
  const entryImage = { ...element(), files: [] };
  const entryForm = {
    ...element(),
    elements: [],
    reset() {},
  };
  const nodes = {
    '#reloadLibraryButton': element('刷新图库'),
    '#libraryStatus': element(),
    '#libraryGrid': createGrid(),
    '#libraryCount': element('0'),
    '#queryImage': { ...element(), files: [] },
    '#queryPreview': { ...element(), hidden: true, src: '' },
    '.dropzone-copy': element(),
    '#entryImage': entryImage,
    '#entryPreview': { ...element(), hidden: true, src: '' },
    '#entryImageText': element(),
    '#sku': { ...element(), value: '' },
    '#productName': { ...element(), value: '' },
    '#size': { ...element(), value: '' },
    '#price': { ...element(), value: '' },
    '#room': { ...element(), value: '' },
    '#style': { ...element(), value: '' },
    '#color': { ...element(), value: '' },
    '#stock': { ...element(), value: '' },
    '#sellingPoint': { ...element(), value: '' },
    '#entrySubmitButton': element('保存并加入图库'),
    '#entryStatus': element(),
    '#matchButton': element('开始匹配'),
    '#matchHint': element(),
    '#results': { ...element(), hidden: false },
    '#resultGrid': createGrid(),
    '#entryForm': entryForm,
  };
  entryForm.elements = [
    entryImage,
    nodes['#sku'],
    nodes['#productName'],
    nodes['#size'],
    nodes['#price'],
    nodes['#room'],
    nodes['#style'],
    nodes['#color'],
    nodes['#stock'],
    nodes['#sellingPoint'],
    nodes['#entrySubmitButton'],
  ];
  return nodes;
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

test('图库刷新初始失败显示未知计数，后续失败保留资料且忽略过期响应', async () => {
  const nodes = pageNodes();
  const stale = deferred();
  const latest = deferred();
  let calls = 0;
  const api = {
    listLibrary: () => {
      calls += 1;
      if (calls === 1) return Promise.reject(new Error('服务暂不可用'));
      if (calls === 2) return Promise.resolve({ images: [{ image_url: '/api/images/1' }] });
      if (calls === 3) return Promise.reject(new Error('服务暂不可用'));
      if (calls === 4) return stale.promise;
      return latest.promise;
    },
  };
  const { context } = loadApp(api, nodes);

  await context.refreshLibrary();
  assert.equal(nodes['#libraryCount'].textContent, '—');

  await context.refreshLibrary();
  const priorCard = nodes['#libraryGrid'].children[0];
  await context.refreshLibrary();

  assert.deepEqual(nodes['#libraryGrid'].children, [priorCard]);
  assert.equal(nodes['#libraryCount'].textContent, '1');
  assert.equal(nodes['#libraryStatus'].textContent, '服务暂不可用');
  assert.equal(nodes['#reloadLibraryButton'].disabled, false);
  assert.equal(nodes['#reloadLibraryButton'].textContent, '刷新图库');

  const olderRequest = context.refreshLibrary();
  const newerRequest = context.refreshLibrary();
  latest.resolve({ images: [] });
  await newerRequest;
  stale.resolve({ images: [{ image_url: '/api/images/2' }] });
  await olderRequest;

  assert.equal(nodes['#libraryCount'].textContent, '0');
});

test('价格输入允许与后端价格契约一致的两位小数', () => {
  assert.match(indexSource, /<input id="price" type="number" min="0" step="0\.01"/);
});

test('预览替换、成功重置和页面卸载都会释放对象 URL', async () => {
  const nodes = pageNodes();
  const revoked = [];
  const api = {
    listLibrary: async () => ({ images: [] }),
    uploadLibraryImage: async () => ({ status: 'imported' }),
  };
  const { ready, windowListeners } = loadApp(api, nodes, {
    URL: {
      createObjectURL: (file) => `blob:${file.name}`,
      revokeObjectURL: (url) => revoked.push(url),
    },
  });
  ready();

  nodes['#entryImage'].files = [{ name: 'entry-first.png' }];
  nodes['#entryImage'].onchange({ target: nodes['#entryImage'] });
  nodes['#entryImage'].files = [{ name: 'entry-second.png' }];
  nodes['#entryImage'].onchange({ target: nodes['#entryImage'] });
  assert.deepEqual(revoked, ['blob:entry-first.png']);

  await nodes['#entryForm'].onsubmit({ preventDefault() {}, target: nodes['#entryForm'] });
  assert.deepEqual(revoked, ['blob:entry-first.png', 'blob:entry-second.png']);

  nodes['#queryImage'].files = [{ name: 'query.png' }];
  nodes['#queryImage'].onchange({ target: nodes['#queryImage'] });
  windowListeners.beforeunload();
  assert.deepEqual(revoked, ['blob:entry-first.png', 'blob:entry-second.png', 'blob:query.png']);
});

test('图库上传期间禁用全部录入控件，并在完成后恢复', async () => {
  const nodes = pageNodes();
  const pending = deferred();
  const api = {
    listLibrary: async () => ({ images: [] }),
    uploadLibraryImage: () => pending.promise,
  };
  const { ready } = loadApp(api, nodes);
  ready();
  nodes['#entryImage'].files = [{ name: 'buyer.png' }];

  const request = nodes['#entryForm'].onsubmit({ preventDefault() {}, target: nodes['#entryForm'] });
  assert.equal(nodes['#entryForm'].elements.every((control) => control.disabled), true);

  pending.resolve({ status: 'imported' });
  await request;

  assert.equal(nodes['#entryForm'].elements.every((control) => !control.disabled), true);
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
