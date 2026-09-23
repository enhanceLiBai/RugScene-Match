const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { CarpetApiClient } = require('../api-client.js');
test('管理页展示保存的客户照片与全部推荐，图片缺失提供说明', () => {
  function node(tag) {
    return {tag, children: [], append(...items) {this.children.push(...items);}, replaceChildren(...items) {this.children = items;}};
  }
  const context = {document: {createElement: node, addEventListener() {}}, CarpetApiClient: {}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'feedback.js'), 'utf8'), context);
  const container = node('div');
  context.renderFeedbackHistory(container, {
    created_at: '2026-09-16T12:00:00Z', query_image_url: '/api/history/123/image',
    payload: {query_scene: {room: '客厅'}, results: [
      {rank: 1, product_id: 'A', product_name: ' 云纹米色 ', style: '奶油风', similarity: 95, matched_buyer_image_url: '/api/images/1', product_image_url: '/api/images/2'},
      {rank: 2, product_id: null, similarity: 90, matched_buyer_image_url: '/api/images/3'},
    ]},
  });
  const flatten = root => [root, ...root.children.flatMap(flatten)];
  const all = flatten(container);
  assert.deepEqual(all.filter(n => n.tag === 'img').map(n => n.src), [
    '/api/history/123/image', '/api/history/123/image', '/api/images/1?preview=1', '/api/history/123/image', '/api/images/3?preview=1',
  ]);
  assert.equal(all.filter(n => n.tag === 'article').length, 2);
  assert.deepEqual(all.filter(n => n.textContent?.startsWith('商品名称：')).map(n => n.textContent), ['商品名称：云纹米色']);
  const picture = all.find(n => n.tag === 'img' && n.src === '/api/images/3?preview=1');
  picture.onerror();
  assert.equal(picture.hidden, true);
  assert.ok(all.some(n => /图片可能已删除/.test(n.textContent)));
});

test('历史详情复制对应商品 ID 和买家秀图片，无 ID 不显示按钮', async () => {
  const copied = [];
  const png = {type: 'image/png'};
  function node(tag) {
    return {tag, children: [], append(...items) {this.children.push(...items);},
      getContext: () => ({drawImage: image => copied.push(image)}), toBlob: fn => fn(png)};
  }
  const context = {document: {createElement: node, addEventListener() {}}, CarpetApiClient: {},
    navigator: {clipboard: {writeText: async text => copied.push(text), write: async items => copied.push(await items[0].data['image/png'])}},
    window: {isSecureContext: true, ClipboardItem: class {constructor(data) {this.data = data;}}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'feedback.js'), 'utf8'), context);
  const image = {decode: async () => {}, naturalWidth: 100, naturalHeight: 80};
  const actions = context.historyCopyActions({product_id: '12345'}, image);
  assert.deepEqual(actions.children.map(x => x.textContent), ['复制商品 ID', '复制买家秀图片']);
  await actions.children[0].onclick();
  await actions.children[1].onclick();
  assert.deepEqual(copied, ['12345', image, png]);
  assert.ok(actions.children.every(x => x.textContent === '已复制'));
  assert.equal(context.historyCopyActions({}, image).children.length, 1);
  context.window.isSecureContext = false;
  await actions.children[1].onclick();
  assert.match(actions.children[1].textContent, /右键/);
});
