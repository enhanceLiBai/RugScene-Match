const test = require('node:test');
const assert = require('node:assert/strict');

const { CarpetApiClient } = require('../api-client.js');

function jsonResponse(payload, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    headers: { get: (name) => (name.toLowerCase() === 'content-type' ? 'application/json; charset=utf-8' : null) },
    json: async () => payload,
  };
}

function textErrorResponse() {
  return {
    ok: false,
    status: 502,
    headers: { get: () => 'text/plain' },
    json: async () => ({ ignored: true }),
  };
}

function createClient(fetchImpl) {
  return CarpetApiClient.create({ fetchImpl, FormDataImpl: FormData });
}

test('图库上传只发送图片和非空元数据', async () => {
  const calls = [];
  const client = createClient(async (url, options) => {
    calls.push({ url, options });
    return jsonResponse({ status: 'imported', image: { id: 1 } });
  });

  const image = new Blob(['image'], { type: 'image/png' });
  await client.uploadLibraryImage(image, {
    product_name: '云朵地毯',
    sku: '',
    room: '客厅',
  });

  assert.equal(calls[0].url, '/api/library');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.body.get('product_name'), '云朵地毯');
  assert.equal(calls[0].options.body.get('room'), '客厅');
  assert.equal(calls[0].options.body.has('sku'), false);
  assert.equal(calls[0].options.body.get('image').size, image.size);
  assert.equal(calls[0].options.headers, undefined);
});

test('图库列表使用 GET /api/library', async () => {
  const calls = [];
  const client = createClient(async (url, options) => {
    calls.push({ url, options });
    return jsonResponse({ images: [] });
  });

  const result = await client.listLibrary();

  assert.deepEqual(result, { images: [] });
  assert.deepEqual(calls, [{ url: '/api/library', options: { method: 'GET' } }]);
});

test('相似检索使用 top_k 查询参数并发送图片', async () => {
  const calls = [];
  const client = createClient(async (url, options) => {
    calls.push({ url, options });
    return jsonResponse({ results: [] });
  });
  const image = new Blob(['query'], { type: 'image/png' });

  await client.searchSimilar(image, 5);

  assert.equal(calls[0].url, '/api/search?top_k=5');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.body.get('image').size, image.size);
});

test('JSON 错误优先展示后端 detail', async () => {
  const client = createClient(async () => jsonResponse(
    { detail: '图片无效或格式不受支持。' },
    { ok: false, status: 400 },
  ));

  await assert.rejects(
    client.listLibrary(),
    (error) => error.name === 'ApiError' && error.message === '图片无效或格式不受支持。',
  );
});

test('非 JSON 错误转换为稳定中文消息', async () => {
  const client = createClient(async () => textErrorResponse());

  await assert.rejects(
    client.listLibrary(),
    (error) => error.name === 'ApiError' && error.message === '服务响应异常，请稍后重试。',
  );
});
