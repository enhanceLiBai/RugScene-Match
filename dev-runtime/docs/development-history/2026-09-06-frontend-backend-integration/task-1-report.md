# Task 1 报告：可空元数据模型与增量 schema

## 实现

- `ImageRecord` 增加九个可空商品元数据列；`price` 使用 `NUMERIC(12, 2)`，并增加非负价格约束。
- 新增不可变 `ImageMetadata` 值对象和 `ImageRepository.update_metadata()`；更新时只写入非 `None` 字段，保留已有值。
- `LibraryRow`、`SearchRow` 及仓库查询映射包含九个元数据字段。
- 新增幂等 `_upgrade_image_metadata_columns()`：为旧 `images` 表逐列补字段；仅在既有价格合法时补充非负约束，并由 schema 初始化调用。
- 保留 `SearchRow` 原有位置参数顺序，新字段作为可空尾部字段，降低既有调用方迁移风险。

## 文件

- `backend/models.py`
- `backend/db.py`
- `backend/repository.py`
- `tests/test_repository.py`

## TDD 记录

RED：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'D:\电商ai应用\.venv\Scripts\python.exe' -m pytest tests\test_repository.py -q --basetemp '.superpowers\tmp\task1-red'
```

关键输出：测试收集失败，`ImportError: cannot import name 'ImageMetadata' from 'backend.repository'`。

GREEN：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'D:\电商ai应用\.venv\Scripts\python.exe' -m pytest tests\test_repository.py -q --basetemp '.superpowers\tmp\task1-green-2'
```

关键输出：`29 passed in 3.12s`。

## 自审

- 空值保留、元数据持久化、图库投影、搜索投影和重复 schema 初始化均由仓库测试覆盖。
- `git diff --check` 无空白错误。
- 未读取或输出任何 `.env`、数据库 URL 或密码。

## 顾虑

全量非模型测试为 `103 passed, 1 failed, 1 deselected`。唯一失败来自现有 `backend/services.py`：其 `_search_result()` 将新增的 `SearchRow` 字段展开给尚未扩展的 `SearchResult`，产生 `TypeError: unexpected keyword argument 'sku'`。这是后续 Task 2 的预期衔接点，本 Task 未越界修改服务层。

## Fix round 1

### 改动

- `backend/services.py`：给 `SearchResult` 增加九个可空元数据字段，使 `_search_result(rank, row)` 对包含元数据的 `SearchRow.__dict__` 展开保持兼容。
- `tests/test_services.py`：增加带 `product_name` 和 `price` 的搜索行，并断言服务结果保留这两个字段，固定搜索结果元数据契约。
- `tests/test_repository.py`：图库行按本测试创建的 `image.id` 定位，不依赖共享数据库中的最低主键；新增旧 schema 回归测试，先在事务内移除九列和价格约束，再执行增量升级两次，验证列完整性和既有图片记录保留。

### TDD 与验证命令

RED：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'D:\电商ai应用\.venv\Scripts\python.exe' -m pytest tests\test_services.py -q --basetemp '.superpowers\tmp\task1-fix-red-services'
```

关键输出：`1 failed, 7 passed`；失败为 `TypeError: SearchResult.__init__() got an unexpected keyword argument 'sku'`。

聚焦 GREEN：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'D:\电商ai应用\.venv\Scripts\python.exe' -m pytest tests\test_repository.py tests\test_services.py -q --basetemp '.superpowers\tmp\task1-fix-green-focused'
```

关键输出：`38 passed in 3.77s`。

全量非模型验证：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'D:\电商ai应用\.venv\Scripts\python.exe' -m pytest tests -m 'not model' -q --basetemp '.superpowers\tmp\task1-fix-all'
```

关键输出：`105 passed, 1 deselected, 2 warnings in 5.40s`。两个 warning 均为现有 FastAPI/Starlette 测试依赖的弃用提示：`httpx` 与 `starlette.testclient` 兼容层，以及 `anyio.abc.BlockingPortal` 别名。

### 自审

- 三项审查 finding 均有对应测试或实现修复；schema 回归测试在同一外层事务内执行，测试结束回滚，不改动共享数据库持久状态。
- 未新增冗余攻击测试；仅覆盖元数据核心持久化、投影、服务映射和增量 schema 稳定性。

### Fix round 1 最终复核

补充断言确认增量升级同时创建 `ck_images_price_nonnegative` 约束。最终命令与输出：

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'D:\电商ai应用\.venv\Scripts\python.exe' -m pytest tests\test_repository.py tests\test_services.py -q --basetemp '.superpowers\tmp\task1-fix-green-focused-final'
```

输出：`38 passed in 4.09s`。

```powershell
$env:PYTHONIOENCODING='utf-8'; & 'D:\电商ai应用\.venv\Scripts\python.exe' -m pytest tests -m 'not model' -q --basetemp '.superpowers\tmp\task1-fix-all-final'
```

输出：`105 passed, 1 deselected, 2 warnings in 6.86s`。warning 仍为上述两条既有依赖弃用提示。
