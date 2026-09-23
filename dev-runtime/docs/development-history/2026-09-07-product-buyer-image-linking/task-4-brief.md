# Task 4: 关联商品的场景检索与去重

Plan: `docs/superpowers/plans/2026-09-07-product-buyer-image-linking.md`
Spec: `docs/superpowers/specs/2026-09-07-product-buyer-image-linking-design.md`

## Global constraints

- 客户图只在内存中校验和编码，不写文件或数据库。
- 只检索启用的 `buyer_sofa`；推荐必须有同商品启用的 `product_main`。
- 先按向量距离召回 30 张买家秀，再按商品 ID 去重；每个商品保留最高相似度图片。
- 返回最多 `top_k` 个不同商品，不足时返回实际数量。
- 复用现有 `/api/search` 与图片端点，不增加排序元数据或其他业务筛选。
- 必要注释使用简体中文；只运行本任务直接相关测试。

## Files

- Modify: `backend/repository.py`
- Modify: `backend/api.py`
- Modify: `tests/test_repository.py`
- Modify: `tests/test_api.py`

## Interfaces

- Produces: `ProductSearchRow(product_id: str, buyer_image_id: int, buyer_original_name: str, product_image_id: int, cosine_distance: float, similarity_percent: float, source_column: str)`。
- Produces: `ImageRepository.search_products(identity: EncoderIdentity, query: np.ndarray, *, top_k: int, candidate_limit: int = 30, excluded_sha256: str | None = None) -> list[ProductSearchRow]`。
- Modifies `/api/search` item to: `rank`, `product_id`, `matched_buyer_image_id`, `matched_buyer_image_url`, `product_image_id`, `product_image_url`, `matched_source_column`, `similarity`。

## Required work

1. 先写仓库失败测试：商品 A 两张高分买家秀、商品 B 一张；断言按商品 ID 去重、A 保留最高分、结果含当前主图、无启用主图商品不返回。
2. 写 API 失败测试：响应包含上述完整字段；查询图 SHA-256 可排除字节相同的已入库买家秀；查询不增加图片记录。
3. 运行目标测试取得 RED：`$env:PYTHONIOENCODING='utf-8'; D:\电商ai应用\.venv\Scripts\python.exe -m pytest tests\test_repository.py tests\test_api.py -k "search_product or associated_product" --basetemp .pytest-tmp/task4 -q`。数据库无响应时不要反复等待，记录限制并补充可独立验证的纯映射/假仓库测试。
4. 仓库 SQL 只联接当前模型向量、启用 buyer 关联、启用 main 关联。候选按 cosine distance、buyer image ID 稳定排序，SQL limit 为 `candidate_limit`。
5. Python 遍历候选并按 `product_id` 首次出现去重，直到 `top_k`。验证向量、top_k 与 candidate_limit；candidate_limit 至少不小于 top_k。
6. 更新 `/api/search` 使用 `search_products(..., top_k=top_k, candidate_limit=30, excluded_sha256=validated.sha256)` 并映射新响应字段。保留 model 和空结果 message；删除旧结果字段，不维护双协议。
7. 运行同一目标测试取得 GREEN；不要运行完整回归。
8. 自审并提交，主题：`feat: return deduplicated product recommendations`。

## Report

完整报告写入 `task-4-report.md`，包含 RED/GREEN、实现、文件、提交、自查和顾虑。最终回复只返回状态、提交、测试摘要、顾虑和报告路径。
