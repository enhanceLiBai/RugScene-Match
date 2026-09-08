# Task 3: Excel 增量导入服务与后台任务 API

Plan: `docs/superpowers/plans/2026-09-07-product-buyer-image-linking.md`
Spec: `docs/superpowers/specs/2026-09-07-product-buyer-image-linking-design.md`

## Global constraints

- 网页上传 XLSX 必须分块写入 `data/import_jobs/<job_id>/`，不能整文件读入内存。
- 只处理解析器返回的 F/K/L/M/N 映射；主图不编码，买家秀才生成向量。
- 图片按工作簿原始字节保存，不转码；SHA-256 相同则复用。
- 单图失败记录并继续；致命工作簿/数据库失败标记任务失败；临时 Excel 最终删除。
- 复用现有后端结构，不引入消息队列、迁移框架或额外依赖。
- 必要注释使用简体中文；测试只覆盖本任务主流程并使用工作区 `--basetemp`。

## Files

- Modify: `.gitignore`
- Modify: `backend/config.py`
- Modify: `backend/image_assets.py`
- Create: `backend/excel_import.py`
- Modify: `backend/api.py`
- Create: `tests/test_excel_import.py`
- Modify: `tests/test_api.py`

## Consumed interfaces

- `backend.tencent_excel.iter_product_images(path: Path)` 返回逐张 `WorkbookImage`。
- `ImageRepository` 的图片哈希、图片新增、向量 upsert、`link_product_image`、`set_current_product_main`、导入任务 CRUD。

## Produced interfaces

- `store_image_bytes(data: bytes, original_name: str, image_dir: Path) -> tuple[ValidatedImage, Path]`。
- `ExcelImportService.run(job_id: str, workbook_path: Path) -> None`。
- `POST /api/imports` 返回 `{"job_id": str, "status": "parsing"}`。
- `GET /api/imports/{job_id}` 返回任务状态、processed、total、summary、error。

## Required work

1. 先写 `tests/test_excel_import.py`：用假解析器、假编码器、临时目录和可控仓库验证主图不编码、三张买家秀编码、重复图片复用、主图更新、坏图跳过继续、文件原字节保存。
2. 先在 `tests/test_api.py` 写小 XLSX 上传与任务查询测试：32 位 job ID、仅接受 `.xlsx`、未知任务 404、测试启动器同步执行、完成后任务临时目录删除。避免真实模型和大文件。
3. 使用工作区 `--basetemp .pytest-tmp/task3` 运行 `tests/test_excel_import.py` 与 API 的 import 目标测试取得 RED。
4. `Settings.import_job_dir` 返回 `<project_root>/data/import_jobs`；`.gitignore` 加 `data/import_jobs/`。
5. `store_image_bytes` 复用 `validate_image_bytes` 校验并以哈希命名，写盘采用项目现有原子/安全路径规则；写入内容必须与输入完全一致。
6. `ExcelImportService` 每张图独立事务：查哈希、必要时保存与新增图片；主图建立/切换关联但不生成向量；买家秀建立关联并只在缺少当前模型向量时编码。持续更新 processed/total 与 summary JSON；单图异常回滚当前图并累计 skipped；致命异常将 job 标为 failed；finally 只删除当前 job 临时目录。
7. API 使用 `BackgroundTasks`。上传用 `await workbook.read(1024 * 1024)` 循环写入，验证 `.xlsx` 后缀，使用 32 位 `uuid4().hex`。依赖注入一个可替换的 `import_runner` 以便测试同步执行；响应不暴露本地路径。
8. 状态响应将 `summary_json` 解析为对象；错误文案固定、可读且不含内部异常。上传失败时清理本任务目录。
9. 运行同一目标测试取得 GREEN；不要运行完整回归或真实模型测试。
10. 自审并提交指定文件，提交主题：`feat: import product images from Excel`。

## Environment note

本地 PostgreSQL 在基线阶段没有响应。若数据库测试仍受阻，不要多次等待；完成假仓库单元测试与可执行静态验证，在报告中明确记录未取得的数据库证据。

## Report

完整报告写入 `task-3-report.md`，包含 RED/GREEN、实现、文件、提交、自查和顾虑。最终回复只返回状态、提交、测试摘要、顾虑和报告路径。
