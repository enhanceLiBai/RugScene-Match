const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function setup() {
  const nodes = Object.fromEntries(['conversionForm', 'conversionFields', 'conversionRank', 'conversionProduct', 'conversionSubmit', 'conversionStatus'].map(id => ['#' + id, {
    value: '', disabled: false, children: [], append(item) {this.children.push(item);}, replaceChildren() {this.children = [];},
  }]));
  nodes['#conversionForm'].reset = () => {nodes['#conversionRank'].value = nodes['#conversionProduct'].value = '';};
  const calls = [];
  let fail = false;
  const context = {document: {querySelector: s => nodes[s], createElement: () => ({}), addEventListener() {}}, fetch() {},
    CarpetApiClient: {requestJson: async (_fetch, url, options) => {
      calls.push({url, data: JSON.parse(options.body)});
      if (fail) throw new Error('暂不可用');
      return {conversion: {rank: 2, product_id: 'P2'}};
    }}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '..', 'orders.js'), 'utf8'), context);
  return {nodes, calls, context, fail: value => {fail = value;}, submit: () => nodes['#conversionForm'].onsubmit({preventDefault() {}})};
}

test('未下单不发送请求；选择Top自动带出ID，提交仅传排名；成功后不重复提交', async () => {
  const s = setup();
  s.context.renderConversionForm({history_id: 7, results: [{rank: 1, product_id: 'P1'}, {rank: 2, product_id: 'P2'}]});
  assert.equal(s.calls.length, 0);
  assert.equal(s.nodes['#conversionRank'].children.length, 3);
  s.nodes['#conversionRank'].value = '2'; s.nodes['#conversionRank'].onchange();
  assert.equal(s.nodes['#conversionProduct'].value, 'P2');
  s.nodes['#conversionProduct'].value = 'FORGED';
  await s.submit();
  assert.deepEqual(s.calls, [{url: '/api/conversions', data: {history_id: 7, rank: 2}}]);
  assert.equal(s.nodes['#conversionProduct'].value, 'P2');
  await s.submit(); assert.equal(s.calls.length, 1);
  const html = fs.readFileSync(path.join(__dirname, '..', 'index.html'), 'utf8');
  assert.match(html, /id="conversionProduct" readonly/);
  assert.ok(!html.includes('matchFeedbackForm'));
});

test('晚些时候打开原查询可登记；已有成交展示为已登记；失败可重试', async () => {
  const s = setup();
  const payload = {history_id: 7, results: [{rank: 2, product_id: 'P2'}]};
  s.context.renderConversionForm(payload);
  s.nodes['#conversionRank'].value = '2';
  s.fail(true); await s.submit();
  assert.equal(s.nodes['#conversionFields'].disabled, false);
  assert.equal(s.nodes['#conversionRank'].value, '2');
  s.fail(false); await s.submit();
  s.context.renderConversionForm({...payload, conversion: {rank: 2, product_id: 'P2'}});
  assert.equal(s.nodes['#conversionFields'].disabled, true);
  assert.equal(s.nodes['#conversionSubmit'].textContent, '已登记');
});
