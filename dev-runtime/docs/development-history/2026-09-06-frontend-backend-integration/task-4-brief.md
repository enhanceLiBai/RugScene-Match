### Task 4: 前端 HTTP 客户端与展示契约

**Files:**
- Create: `api-client.js`
- Modify: `matcher-core.js`
- Create: `tests/api-client.test.js`
- Modify: `tests/matcher-core.test.js`

**Interfaces:**
- Produces: `CarpetApiClient.create({ fetchImpl, FormDataImpl })`。
- Produces: `listLibrary() -> Promise<LibraryResponse>`。
- Produces: `uploadLibraryImage(file, metadata) -> Promise<LibraryUploadResponse>`。
- Produces: `searchSimilar(file, topK = 5) -> Promise<SearchResponse>`。
- Produces: `CarpetMatcherCore.buildPresentation(item)` 和 `buildRecommendationScript(item)`，消费后端 snake_case 字段。

- [ ] **Step 1: 写 API 客户端请求测试**

在 `tests/api-client.test.js` 使用最小 fake fetch 和 Node 自带 `FormData`/`Blob`，断言：

```javascript
test('图库上传只发送图片和非空元数据', async () => {
  const calls = [];
  const client = createClient(async (url, options) => {
    calls.push({ url, options });
    return jsonResponse({ status: 'imported', image: { id: 1 } });
  });
  await client.uploadLibraryImage(new Blob(['image']), {
    product_name: '云朵地毯', sku: '', room: '客厅',
  });

  assert.equal(calls[0].url, '/api/library');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.body.get('product_name'), '云朵地毯');
  assert.equal(calls[0].options.body.has('sku'), false);
});
```

另测 `GET /api/library`、`POST /api/search?top_k=5`、JSON 错误 detail 和非 JSON 错误的中文转换。

- [ ] **Step 2: 运行 JavaScript 测试并确认 RED**

Run: `node --test tests\api-client.test.js tests\matcher-core.test.js`

Expected: FAIL，原因是 `api-client.js` 不存在，且展示函数仍消费 camelCase/本地特征。

- [ ] **Step 3: 实现 UMD API 客户端**

`api-client.js` 使用与 `matcher-core.js` 一致的 UMD 形式。请求助手必须先检查 `response.ok`，仅在响应 content-type 为 JSON 时解析 `detail`，其他失败统一抛出：

```javascript
class ApiError extends Error {}

async function requestJson(fetchImpl, url, options) {
  const response = await fetchImpl(url, options);
  const isJson = (response.headers.get('content-type') || '').includes('application/json');
  const payload = isJson ? await response.json() : null;
  if (!response.ok) throw new ApiError(payload?.detail || '服务响应异常，请稍后重试。');
  if (!isJson) throw new ApiError('服务响应异常，请稍后重试。');
  return payload;
}
```

上传 FormData 不手工设置 `Content-Type`，由浏览器生成 multipart boundary。

- [ ] **Step 4: 更新纯展示函数**

删除 `visualScore()` 和 `rankBySimilarity()`；`buildPresentation()` 使用 `product_name`、`original_name`、`selling_point` 等后端字段，价格使用服务端返回值直接展示。推荐理由改为“OpenCLIP 图片向量相似”。

- [ ] **Step 5: 运行 JavaScript 测试并确认 GREEN**

Run: `node --test tests\api-client.test.js tests\matcher-core.test.js`

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add api-client.js matcher-core.js tests/api-client.test.js tests/matcher-core.test.js
git commit -m "feat: add frontend api client"
```

---
