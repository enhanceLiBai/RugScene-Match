# Task 5 完成报告：建库/搜索服务与 CLI

## 提交

- 实现提交：`b799dc1dd8c1c1301a3c93428737f9a19788a577`（`feat: add library service and CLI`）

## 红灯证据

在实现 `backend.services` 前运行：

```text
.venv\Scripts\python.exe -m pytest tests\test_services.py -v
ModuleNotFoundError: No module named 'backend.services'
```

这证明服务测试覆盖的是此前缺失的公开模块，而不是既有行为。

## 绿灯证据

```text
.venv\Scripts\python.exe -m pytest tests\test_cli.py tests\test_services.py -v
11 passed

.venv\Scripts\python.exe -m backend.cli --help
列出 init-db、import、search、serve 四个子命令

.venv\Scripts\python.exe -m pytest tests -m "not model" -q
93 passed, 1 deselected

git diff --check
退出码 0
```

所有测试使用 fake encoder 或既有非模型测试；未触发真实 OpenCLIP 权重下载。

## 自审结论

- `LibraryService` 对单图分别提交或回滚，目录导入会继续处理后续图片。
- 状态覆盖导入、重复、已有图片补当前模型向量和失败；失败的新图库文件会清理，既有文件不删除。
- 查询仅在内存中校验/编码，默认排除同 SHA，保留不同角度，且限制 `top_k` 为 1–50 的非布尔整数。
- CLI 输出中文，不显示数据库密码或完整连接 URL；帮助和 `init-db` 均不构造编码器。
- 未引入队列、重试框架、后台作业、批处理优化或 FastAPI 路由。
