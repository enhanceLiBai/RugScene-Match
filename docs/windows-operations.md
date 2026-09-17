# Windows 运行保障与匹配耗时

## 已部署

计划任务 `RugScene-App` 使用 SYSTEM 身份在开机时启动 `scripts/run-service.py`，无需保存用户密码。守护进程运行项目 .ven Python，并启动一个 FastAPI 子进程。应用退出后等待 5 秒再启动；计划任务自身失败时按一分钟间隔尝试恢复，禁止重复任务实例。

已验证 SYSTEM 身份下应用启动与数据库健康接口成功，并通过终止应用子进程验证约 6 秒后恢复。尚未通过实际整机重启验证开机流程。守护只检测进程退出，不根据单个慢请求自动杀进程；不承诺自动修复所有卡死情况。

PostgreSQL 容器已设置 `unless-stopped` 重启策略。Docker Desktop 仍必须启动，其通常在 Windows 用户登录后启动；应用任务启动不代表数据库已经就绪。确保 Docker Desktop 的登录自动启动选项已打开。机器睡眠、断网和 Docker 未启动仍会影响使用。

Cloudflare 临时隧道沿用现有进程，本次没有配置其开机启动；整机重启后需重新启动隧道并向客服提供新地址。

## 运维命令（管理员 PowerShell）

```powershell
Get-ScheduledTask -TaskName RugScene-App
Start-ScheduledTask -TaskName RugScene-App
Stop-ScheduledTask -TaskName RugScene-App
```

停机或更新代码时先停止计划任务，再确认 8000 端口已释放；如仍有应用子进程，核实其属于本项目后停止。不要只杀应用子进程，否则守护会自动重启。不要在任务运行时另行执行 backend.cli serve。

更新完代码后重新 Start-ScheduledTask。需要重新安装任务时执行 scripts/install-service.ps1；迁移项目目录后也需重新安装。

## 日志

日志路径：`.cache/service-logs/service.log`，单文件最大约 10 MiB，保留 5 个历史文件，合计约 60 MiB。应用输出、异常、访问日志和阶段计时统一落盘。

```powershell
Get-Content .cache/service-logs/service.log -Tail 80 -Wait
```

计时格式：`match=<编号> stage=<阶段> seconds=<秒> outcome=<状态>`。

- model_load：模型获取或首次加载。
- encode_including_gpu_wait：GPU 锁等待与向量编码。
- scene_identify：初次场景识别。
- database_search：候选数据库查询，可能多次。
- scene_compare：每一次候选双图复核，可能多次。
- history_save：保存结果及客户照片。
- match_worker_total：整个工作线程执行耗时，包含以上阶段。

编号关联同一次匹配。阶段有包含关系，不能简单全部相加。工作线程总耗时不包含客户端上传、框架 multipart 解析、匹配信号量排队、网络响应和结果图片加载，不能等同客服端等待时间。计时日志不记录照片、文件名、场景内容或密钥；异常记录类型而非原始异常内容。

同图多次耗时可能受模型首次加载、GPU 排队、外部 API 和网络影响。先依据计时判断瓶颈，再决定是否优化，避免仅凭总耗时更换硬件。

## 当前范围

不做数据库备份，不切换 Docker 应用部署；保留原图库和业务入口供客服继续试用。匹配测试会正常产生历史记录。
