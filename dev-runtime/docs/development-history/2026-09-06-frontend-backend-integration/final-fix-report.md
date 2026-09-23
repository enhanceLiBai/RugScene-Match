# Final fix report — frontend-backend integration

日期：2026-09-06
修复基线：`a6d29c01c24dda103538a222d37ae75c716847a6`
工作目录：`D:/电商ai应用/.worktrees/frontend-backend-integration`
提交：`fe7b1cb fix: harden library import and ui state`

## 修复范围与逐项覆盖

1. **Critical：同 SHA-256 并发入库与文件清理。**
   - `ImageRepository.lock_sha256()` 使用 PostgreSQL `pg_advisory_xact_lock(bigint)`；锁键由 SHA-256 前 64 位转换为有符号 bigint。`LibraryService` 在查重、落盘、建记录、更新元数据、写向量和提交前取得此事务级锁，因此相同哈希的完整入库工作单元串行执行。没有该方法的测试替身仍通过服务层的 no-op seam 运行。
   - `tests/test_services.py::test_same_sha_two_sessions_keep_file_when_failed_import_precedes_successful_import` 使用两个真实 PostgreSQL 会话、barrier 和受控落盘时序。一个会话失败、另一个会话提交后，断言最终文件仍存在。
2. **Critical：提交确认丢失。**
   - 服务在每次调用 commit 前标记 `commit_attempted`。若提交开始后抛出异常，仍回滚当前会话状态，但保留本调用创建的文件；只有提交尝试前的明确失败才删除该文件。
   - `tests/test_services.py::test_import_keeps_new_file_when_commit_acknowledgement_is_lost` 模拟 commit 已调用但确认丢失，断言失败结果不删除文件。
3. **Important：价格步长。**
   - `index.html` 的价格输入新增 `step="0.01"`。
   - `tests/app.test.js::价格输入允许与后端价格契约一致的两位小数` 覆盖页面契约。
4. **Important：图库刷新竞争。**
   - `app.js` 使用递增请求 token，只有最新的 `refreshLibrary()` 响应可以更新列表、计数、状态或刷新按钮。
   - `tests/app.test.js::图库刷新初始失败显示未知计数，后续失败保留资料且忽略过期响应` 覆盖旧请求在新请求之后返回的情形。
5. **Important：README Node 命令。**
   - README 现在显式运行 `tests/app.test.js`，并如实标记当前三份文件共 15 项 Node 测试；台账裁定确认不为旧的 12 项估计删除新增回归。
6. **Minor：价格超过 `NUMERIC(12,2)`。**
   - API 边界拒绝大于 `9999999999.99` 的价格，避免数据库溢出被映射为 503。
   - `tests/test_api.py::test_library_upload_rejects_price_above_database_precision` 覆盖 `10000000000.00` 返回 400。
7. **Minor：首次图库加载与后续失败。**
   - 首次加载失败把计数显示为 `—`；成功过一次后，失败只显示错误并保留最后成功的列表和计数。
   - 覆盖包含在上述一个图库刷新最小回归中。
8. **Minor：预览 URL 生命周期。**
   - 替换预览、成功重置录入表单和页面 `beforeunload` 都会撤销对应的 object URL。
   - `tests/app.test.js::预览替换、成功重置和页面卸载都会释放对象 URL` 覆盖三种明确生命周期事件。
9. **Minor：上传期间的表单编辑。**
   - 上传开始时禁用 `entryForm.elements` 的全部控件；`finally` 中按原状态恢复，避免旧提交成功后清掉上传期间的用户编辑。
   - `tests/app.test.js::图库上传期间禁用全部录入控件，并在完成后恢复` 覆盖请求中的锁定和完成后的恢复。
10. **Minor：bootstrap 文档。**
    - README 准确说明脚本会创建或复用 `.venv`、升级 pip、安装 `requirements.in`，并保留项目内缓存约定。

## TDD 记录

每类新增行为均先添加最小测试并观察预期 RED，再写最小生产改动。

| 类别 | RED 命令与关键输出 | GREEN 命令与关键输出 |
|---|---|---|
| 并发锁与提交确认不确定性 | `pytest tests/test_services.py::test_same_sha_two_sessions_keep_file_when_failed_import_precedes_successful_import tests/test_services.py::test_import_keeps_new_file_when_commit_acknowledgement_is_lost -q --basetemp .superpowers/tmp/red-critical` → `2 failed`；前者断言文件不存在，后者断言文件不存在。 | 同一选择器使用 `green-critical` → `2 passed in 0.93s`；测试重构后再次以 `green-critical-refactor` → `2 passed in 0.77s`。 |
| API 价格上限 | `pytest tests/test_api.py::test_library_upload_rejects_price_above_database_precision -q --basetemp .superpowers/tmp/red-price-cap` → `assert 503 == 400`。 | 同一选择器使用 `green-price-cap` → `1 passed`（保留两条已有 TestClient deprecation warning）。 |
| 前端刷新、价格步长、URL 释放、表单锁定 | `node --test tests/app.test.js` → `4 failed, 2 passed`：初始计数为 `0` 而非 `—`、缺少 `step`、没有 revoke、未禁用全部控件。 | 同一命令 → `6 passed, 0 failed`。 |

## 完整验证

在最终工作树上运行：

```powershell
node --test tests\api-client.test.js tests\matcher-core.test.js tests\app.test.js
$env:PYTHONIOENCODING='utf-8'; D:\电商ai应用\.venv\Scripts\python.exe -m pytest tests -m "not model" -q --basetemp .superpowers\tmp\final-nonmodel
$env:PYTHONIOENCODING='utf-8'; D:\电商ai应用\.venv\Scripts\python.exe -m pip check
node --check api-client.js
node --check matcher-core.js
node --check app.js
git diff --check
```

结果：

- Node：`15 passed, 0 failed`。
- pytest：`119 passed, 1 deselected, 2 warnings`；两条 warning 是 FastAPI/Starlette TestClient 的已知依赖弃用提示，基线同样存在。
- `pip check`：`No broken requirements found.`
- 三份 JavaScript 语法检查均退出码 0。
- `git diff --check` 无空白错误；Git 仅提示既有的 CRLF 工作树转换信息。

## 自审与顾虑

- 锁为 PostgreSQL transaction-scoped advisory lock，锁的释放由 commit 或 rollback 绑定；64 位锁键冲突最多使不同哈希额外串行，不会使同哈希重新并发。
- 提交开始后的文件保留会在确定失败时留下可恢复孤儿文件，这是终审裁定要求的安全取舍；后续可由孤儿回收任务处理，未在本轮扩大范围。
- 并发回归使用随机有效 PNG 生成唯一 SHA，并仅删除该测试实际创建的精确记录；没有清理任何宽泛数据库范围。
- 模型烟测按要求未运行（`-m "not model"`）；普通套件使用 fake encoder，不下载模型权重。
- Node 总数从基线 12 变为 15，是三项新增、聚焦的前端回归所致；README 已依据台账裁定如实记录 15。
