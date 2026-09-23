# Task 2：统一内存图片入库服务

## 实现

- 新增 `LibraryService.import_bytes(data, original_name, metadata)`，先在事务捕获范围外校验内存字节，保持 `InvalidImageError` 可供上传接口识别。
- 提取 `_import_validated()` 作为路径与内存导入共享的单图片事务工作单元；路径导入传入空 `ImageMetadata()`。
- `ImportResult` 新增 `image_id`；导入、重复和补向量均返回记录 ID，失败返回 `None`。
- 重复导入先合并非空元数据，再按当前模型向量状态返回 `DUPLICATE` 或 `EMBEDDING_ADDED`，并统一提交。
- 新文件在编码失败时回滚，并仅删除本次创建的图库文件。

## 修改文件

- `backend/services.py`
- `tests/test_services.py`

## TDD 记录

### RED

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'D:\电商ai应用\.venv\Scripts\python.exe' -m pytest tests\test_services.py -q --basetemp .superpowers\tmp\task2-red
```

输出：`2 failed, 8 passed in 1.53s`。两项新增测试均以预期的 `AttributeError: 'LibraryService' object has no attribute 'import_bytes'` 失败。

### GREEN

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'D:\电商ai应用\.venv\Scripts\python.exe' -m pytest tests\test_services.py -q --basetemp .superpowers\tmp\task2-green
```

输出：`10 passed in 1.14s`。

### 最终验证

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'D:\电商ai应用\.venv\Scripts\python.exe' -m pytest tests -m 'not model' -q --basetemp .superpowers\tmp\task2-final
```

输出：`107 passed, 1 deselected, 2 warnings in 5.76s`。

## 自审

- 新图与重复图均通过真实 PNG 字节覆盖；重复案例验证已有字段保留和新非空字段补充。
- 编码失败案例验证返回失败、调用回滚、删除新建哈希文件且保留原有图库文件。
- `git diff --check` 无空白错误。
- 路径导入、目录容错、补向量和检索既有测试均在最终全量非模型测试中通过。

## 顾虑

无未解决功能顾虑。最终测试中的两条警告来自第三方 FastAPI/Starlette `TestClient` 的弃用提示，和本任务改动无关。

## Fix round 1：并发文件归属

### 根因与修复

`LibraryService` 此前在调用 `store_image()` 前读取 `target.exists()`，再据此决定失败时是否删除目标。该预检与 `os.link()` 的原子提交之间存在竞争窗口：另一请求可在预检后创建同一哈希目标，使失败的本请求误删对方文件。

新增 `StoredImage(path, created)` 和 `store_image_with_ownership()`。只有本调用的 `os.link()` 成功时才返回 `created=True`；发现现存目标或链接竞争失败均返回 `False`。保留 `store_image(...) -> Path` 原有公共契约，服务改为消费归属感知结果。新增一项服务级回归，模拟竞争者在链接瞬间创建文件后本请求编码失败，验证竞争者文件被保留。

### RED

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'D:\电商ai应用\.venv\Scripts\python.exe' -m pytest tests\test_services.py -q --basetemp .superpowers\tmp\task2-race-red
```

输出：`1 failed, 10 passed in 1.58s`。新回归以预期的 `FileNotFoundError` 失败，证明服务在竞争者创建目标后仍错误删除该文件。

### GREEN（聚焦）

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'D:\电商ai应用\.venv\Scripts\python.exe' -m pytest tests\test_image_assets.py tests\test_services.py -q --basetemp .superpowers\tmp\task2-race-green
```

输出：`34 passed in 1.38s`。

### GREEN（完整非模型套件）

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'D:\电商ai应用\.venv\Scripts\python.exe' -m pytest tests -m 'not model' -q --basetemp .superpowers\tmp\task2-race-full
```

输出：`108 passed, 1 deselected, 2 warnings in 6.46s`。

### 本轮自审

- `created=True` 的唯一来源是本调用 `os.link()` 成功；预先存在和链接竞争两条路径均明确为 `False`。
- `store_image()` 仍只返回 `Path`，既有调用和资产测试保持兼容。
- 服务失败清理仅使用归属结果；新增回归直接模拟审查指出的竞争窗口。
- 完整套件仅保留既有第三方 FastAPI/Starlette `TestClient` 弃用警告，无本轮失败或新增警告。
