# 地毯买家秀智能匹配助手

## 场景属性检索

本机 `.env` 配置 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL` 和 `DEEPSEEK_MODEL`。新导入的买家秀自动识别沙发颜色、地板颜色和材质观感；旧图库在“买家秀图库”点击“补充已有买家秀场景标签”，成功标签按模型和规则版本复用，失败项可重新补充。图片、商品关联和已有向量保持保留。

客户查询图在内存中识别，结果展示客户标签与买家秀标签。综合评分权重为沙发颜色 35%、地板颜色 25%、材质观感 20%、CLIP 相似度 20%，按商品去重前对全部有效场景评分。未知属性以图片相似度补充该项；云端失败时明确提示并回退到图片检索。分数是搭配参考分，不是正确率。识别图片会发给配置的云端服务。

这是一个由 FastAPI 同源托管页面、PostgreSQL/pgvector 图库和 OpenCLIP 图片向量检索组成的买家秀匹配工具。正式使用时始终通过后端服务打开页面；不要直接双击 `index.html`。

## Windows 初始化

前置条件：Python 3.12，以及 Docker 中可访问的 PostgreSQL 16 和 pgvector；数据库用户应可创建 `carpet_matcher` 数据库并启用 `vector` 扩展。

```powershell
scripts\bootstrap.ps1
Copy-Item .env.example .env
```

仅在本机 `.env` 中填写 PostgreSQL 配置，不要提交该文件，也不要在日志或截图中记录密码或完整数据库 URL。`scripts\bootstrap.ps1` 会创建或复用项目内 `.ven`、升级 pip，并安装 `requirements.in` 中的依赖；依赖和模型缓存保留在项目 `.cache` 中。

如果 OpenCLIP 权重已经保存在其他项目或共享目录，可在 `.env` 中设置 `CLIP_CACHE_DIR` 指向现有的 OpenCLIP 缓存目录，避免重复下载。相对路径按当前项目根目录解析；未配置时仍使用 `.cache\open_clip`。

## 正式启动方式

在项目根目录依次执行：

```powershell
$env:PYTHONIOENCODING = 'utf-8'
.ven\Scripts\python.exe -m backend.cli init-db
.ven\Scripts\python.exe -m backend.cli serve
```

然后访问 [http://127.0.0.1:8000/](http://127.0.0.1:8000/)。该页面、样式和脚本均由同一后端服务提供，并通过 API 读取图库、上传买家秀和执行检索。

重复运行 `init-db` 是安全的。首次实际导入图片或执行查询时才会加载 OpenCLIP；CPU 上首次加载可能较慢，已下载权重会复用项目 `.cache\open_clip` 中的缓存。

## 录入与检索

页面支持 `.jpg`、`.jpeg`、`.png` 和 `.webp` 图片。

1. 在“录入买家秀”中选择图片后上传，可选填写 SKU、商品名称、规格、参考价、空间、风格、颜色、库存和卖点。
2. 在“开始匹配”中上传客户家居图，页面显示按 OpenCLIP 图片向量相似度排序的结果。

这些商品元数据全部选填，只用于展示和运营补充，**不会影响向量相似度排序**。图库原图以 SHA-256 文件名保存在 `data\images`，图片与元数据/向量记录分别存放在 `data\images` 和 PostgreSQL；查询图片只在内存中处理，不会写入图库或数据库。

也可通过命令行批量建库或查询：

```powershell
.ven\Scripts\python.exe -m backend.cli import .\samples\library
.ven\Scripts\python.exe -m backend.cli search .\samples\query\carpet-a-new-angle.jpg --top-k 5
```

服务提供 `GET /health`、`GET /api/library`、`GET /api/images/{image_id}`、`POST /api/library` 和 `POST /api/search?top_k=5`。人工验收时建议导入同一地毯的多个角度和至少一个不同地毯，再用一张未入库的同款角度查询，确认同款结果排在前列。

## Excel 图片导入

后端支持腾讯工作簿 XLSX 图片解析、商品主图与买家秀关联及后台导入进度记录。通过 `POST /api/imports` 上传工作簿（multipart 字段 `workbook`），再用 `GET /api/imports/{job_id}` 查询进度和汇总；可在 `/docs` 中调用。当前页面尚无 Excel 导入入口。

## 历史匹配记录

当前检索先筛选空间类型、沙发颜色、地板颜色及材质，再按 OpenCLIP 图片相似度排序，不叠加标签分。颜色容差允许“白色/米色/浅灰色”“黑色/深灰色”“浅灰色/深灰色”各组内互通；组间不传递，例如白色与黑色不因此互通。空间和材质默认须一致。

自动检索另外保留视觉 Top 20 候选：对其中被标签过滤、视觉分至少 80 且可能进入最终结果的图片，最多调用 3 次 DeepSeek 双图复核。模型独立查看客户照片和候选，排除地毯和盖毯后逐项判断空间、沙发颜色、地板颜色和材质；四项均确认匹配才放行。不确定、真实冲突和调用失败不放行，页面显示复核说明或失败提示。通过复核后仍使用原视觉分排序，不覆盖图库标签。每次复核超时 30 秒，会增加查询延迟与云端费用；这是有限候选实验策略，不能保证召回所有漏检。

客户识别不可用或关键属性不确定时，可展开“核对或手动确认客户场景”，确认四项属性并勾选后重新匹配。人工确认时不进行双图放行，避免模型覆盖人工条件。不足 Top 10 不凑数。新上传图片要求视觉模型排除地毯后识别地板；本次不自动全库重打标，也未引入区域分割模型。历史记录保留当时结果和分数，不重新排序。

单张图片可从“买家秀图库 → 单张图片导入”上传，复用 Excel 的图片入库、向量生成和 DeepSeek 场景打标流程。无需商品主图或商品 ID，独立图片按图片去重参与同一场景检索；结果中明确显示未填写商品 ID、未提供主图。选填资料不影响排序。打标失败时仍保存图片并显示提示，可通过“补充已有买家秀场景标签”重试；缺少标签的图片不会进入严格场景匹配。此入口不会把选填 SKU 自动当作 Excel 商品 ID。

完成检索后会自动保存当次结果、商品 ID、场景标签和时间（包括无匹配结果的查询）。点击页面的“历史匹配记录”，即可按时间倒序查看，并打开当次匹配结果；每页 20 条，支持加载更多。

当前记录由团队共享。客户原图与结果在同一数据库事务中持久化，不进入检索图库、不保存上传文件名。列表展示客户照片缩略图，打开记录可以对照原图与匹配结果；重启服务后仍可查看。升级前未保存的客户照片无法补回。历史结果保留当时的排序与标签，买家秀和商品图片仍引用现有图库；图库图片删除后，历史中的对应图片将不可用。

升级已有部署时先运行 `.ven\Scripts\python.exe -m backend.cli init-db` 创建历史表和客户照片表，再重启服务。接口为 `GET /api/history`（可选 `before` 游标）、`GET /api/history/{id}` 和 `GET /api/history/{id}/image`。数据库备份应包含 `match_history` 和 `match_history_images` 两张表。

## 验证

以下命令按当前修改范围选择使用，不作为每次开发或合并前的必跑清单。日常开发只运行能证明目标功能可用的最小相关测试，不主动执行完整回归；全量测试和真实 OpenCLIP 冒烟测试仅在用户明确要求时运行。

```powershell
node --check api-client.js
node --check matcher-core.js
node --check app.js
$env:PYTHONIOENCODING='utf-8'; .ven\Scripts\python.exe -m pip check
node --test tests\api-client.test.js tests\matcher-core.test.js tests\app.test.js
$env:PYTHONIOENCODING='utf-8'; .ven\Scripts\python.exe -m pytest tests -m "not model" -q
```

以上三份 Node 内置测试当前共 15 项（原有完整集为 12 项；本轮增加 3 项前端回归）。

真实模型烟测需要可用的已缓存权重或网络访问；日常自动化测试默认使用 fake encoder，因此不触发模型下载。

### 客服并发匹配
匹配接口最多同时处理 8 个请求。完整匹配流程（模型加载、编码、场景识别、双图复核、数据库查询及历史保存）在线程池执行，每个匹配使用独立数据库会话。本机 OpenCLIP 编码串行执行，外部场景请求允许并行；超过 8 个匹配的请求等待空位。该调整避免慢复核直接阻塞事件循环，不保证外部 API 或临时隧道的响应时限。


图库和匹配结果卡片使用 ?preview=1 加载最长边 1200 像素、JPEG 质量 88 的预览图；原图下载保持原始文件。预览缓存最近 32 张，浏览器缓存一小时。

