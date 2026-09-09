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
