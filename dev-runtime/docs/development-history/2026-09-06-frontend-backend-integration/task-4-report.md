# Task 4 报告：前端 HTTP 客户端与展示契约

## RED

命令：`node --test tests\\api-client.test.js tests\\matcher-core.test.js`

结果：失败。首次运行因 `api-client.js` 不存在触发 `MODULE_NOT_FOUND`；旧 `matcher-core.js` 仍使用 camelCase 字段和本地排序函数，新增 snake_case 展示断言失败。该失败符合预期，证明测试覆盖了缺失契约。

## GREEN

命令：`node --test tests\\api-client.test.js tests\\matcher-core.test.js`

结果：通过，9 tests、9 pass、0 fail。覆盖图库上传 FormData 和非空字段、图库列表路径、搜索 `top_k` 路径、JSON/non-JSON 错误转换，以及缺失元数据展示。

## 自审

- `api-client.js` 使用 UMD，同时暴露 `CarpetApiClient.create()` 和 Node 可测试导出。
- 上传与搜索均使用 FormData，未手工设置 `Content-Type`；空字符串和纯空白元数据不会写入请求。
- 非 2xx 先读取 JSON `detail`，非 JSON 或成功但非 JSON 响应统一转换为稳定中文错误。
- `matcher-core.js` 已删除 `visualScore()`、`rankBySimilarity()`，展示和话术消费后端 snake_case 字段；商品名缺失时回退原始文件名，再缺失时使用中性占位。
- `node --check api-client.js`、`node --check matcher-core.js` 和 `git diff --check` 均无错误（仅 Git 报告现有换行风格警告）。

## 顾虑

- “OpenCLIP 图片向量相似”是检索卡片的固定推荐理由，当前由页面渲染任务设置；本任务的纯展示函数不再生成本地相似度或 reason。
- 未扩展安全矩阵或构建流程，保持无包管理器、无构建步骤约束。

## Fix round 1

### 变更

- `buildPresentation()` 新增稳定的 `matchReason: "OpenCLIP 图片向量相似"`，供后续页面渲染直接消费。
- `buildRecommendationScript()` 的通用开场改为基于 OpenCLIP 图片向量相似，不再声称由色调和构图计算。
- 更新 matcher 测试，锁定固定推荐理由和新的准确话术。

### 覆盖测试文件

- `tests/api-client.test.js`
- `tests/matcher-core.test.js`

### 精确命令与输出

命令：`node --test tests\\api-client.test.js tests\\matcher-core.test.js`

输出摘要：`tests 9`、`pass 9`、`fail 0`。

命令：`node --check matcher-core.js`

输出：无输出，退出码 0。

### 自审

- 修复只涉及 `matcher-core.js` 与 `tests/matcher-core.test.js`，未扩展页面逻辑或 API 客户端范围。
- `matchReason` 对有无商品元数据均稳定返回，话术仅继续消费后端 `product_name` 与 `selling_point`。
- 未发现残留“整体色调和画面构图”旧匹配表述。
