# Task 1: 商品图片关联与导入任务持久层

Plan: `docs/superpowers/plans/2026-09-07-product-buyer-image-linking.md`
Spec: `docs/superpowers/specs/2026-09-07-product-buyer-image-linking-design.md`

## Global constraints

- 只处理“地毯图片”工作表的 F、K、L、M、N 列；J 与 O–Q 不进入推荐链路。
- F 为商品 ID，K 为 `product_main`，L–N 为 `buyer_sofa`。
- 客户查询图只在内存中处理，不持久化。
- 前端必须复用现有 `index.html`、`app.js`、`styles.css` 和推荐卡片，不引入前端框架。
- 图片必须按工作簿内原始字节保存，不截图、不转码。
- 重复图片按 SHA-256 复用；旧买家秀不因新版 Excel 缺失而自动删除。
- 最终结果按商品 ID 去重，每个商品只保留相似度最高的买家秀。
- 新增或修改的必要注释使用简体中文，不添加逐行复述式注释。
- 只运行本任务直接相关测试；pytest 使用工作区内 `--basetemp .pytest-tmp/task1`。

## Files

- Modify: `backend/models.py`
- Modify: `backend/repository.py`
- Test: `tests/test_repository.py`

## Interfaces

- Produces: `ProductImage`, `ImportJob` SQLAlchemy 模型。
- Produces: `ImageRepository.link_product_image(product_id: str, image: ImageRecord, image_role: str, source_column: str) -> ProductImage`。
- Produces: `ImageRepository.set_current_product_main(product_id: str, image: ImageRecord, source_column: str = "K") -> ProductImage`。
- Produces: `ImageRepository.list_product_images(product_id: str) -> list[ProductImage]`。
- Produces: `ImageRepository.create_import_job(job_id: str, original_name: str) -> ImportJob`。
- Produces: `ImageRepository.find_import_job(job_id: str) -> ImportJob | None`。
- Produces: `ImageRepository.update_import_job(job_id: str, **values: object) -> ImportJob`。

## Required work

1. 先在 `tests/test_repository.py` 写失败测试：同一商品的一张主图和三张买家秀共享同一 `product_id`；重复关联不新增记录；更换主图后只有新主图启用；导入任务可以创建、更新和读取状态及计数。
2. 运行：`$env:PYTHONIOENCODING='utf-8'; D:\电商ai应用\.venv\Scripts\python.exe -m pytest tests\test_repository.py -k "product_image or import_job" --basetemp .pytest-tmp/task1 -q`，记录预期 RED。
3. 在 `backend/models.py` 新增 `ProductImage`：`id`、`product_id`、`image_id`、`image_role`、`source_column`、`is_active`、`created_at`。添加 `(product_id, image_id, image_role)` 唯一约束；角色只允许 `product_main`/`buyer_sofa`；来源列只允许 K/L/M/N；图片外键级联删除。
4. 新增 `ImportJob`：32 位 `job_id` 主键、`original_name`、`status`、`processed`、`total`、`summary_json`、`error_message`、`created_at`、`updated_at`。默认状态为 `uploading`，计数为 0。
5. 在仓库实现上述接口。关联使用 PostgreSQL `ON CONFLICT DO NOTHING` 后再读取返回；主图更新必须停用同商品旧主图并启用新主图；任务更新只允许 `status`、`processed`、`total`、`summary_json`、`error_message`。
6. 运行同一目标测试，记录 GREEN。不要运行完整测试集。
7. 自查 diff，确保没有修改任务外文件、没有过度抽象。
8. 提交：`git add backend/models.py backend/repository.py tests/test_repository.py && git commit -m "feat: add product image associations"`。

## Report

将完整报告写入同目录 `task-1-report.md`，包含实现内容、RED/GREEN 命令与输出、文件、提交、自查和顾虑。最终回复只返回状态、提交、测试摘要、顾虑和报告路径。
