# 地毯买家秀智能匹配助手

## 后端技术验证

本仓库在原静态 MVP 外，提供图片建库与相似检索后端：默认 OpenCLIP 编码器、PostgreSQL 与 pgvector。当前仅按图片向量相似度检索，不要求 SKU、价格或库存等结构化元数据；现有静态前端尚未接入 API。

### Windows 初始化

前置条件：Python 3.12，以及 Docker 中可访问的 PostgreSQL 16 和 pgvector；数据库用户应可创建 `carpet_matcher` 数据库并启用 `vector` 扩展。

```powershell
scripts\bootstrap.ps1
```

脚本只创建项目内 `.venv`。所有依赖与模型缓存均保留在项目 `.cache`：Pip 为 `.cache\pip`，PyTorch 为 `.cache\torch`，Hugging Face 为 `.cache\huggingface`，OpenCLIP 权重为 `.cache\open_clip`。

### 本机配置与数据库

复制示例后，仅在本机 `.env` 填写 PostgreSQL 密码：

```powershell
Copy-Item .env.example .env
.venv\Scripts\python.exe -m backend.cli init-db
```

可配置字段为 `POSTGRES_HOST`、`POSTGRES_PORT`、`POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`IMAGE_ENCODER`、`CLIP_MODEL_NAME`、`CLIP_PRETRAINED` 和 `MODEL_DEVICE`。请勿提交 `.env`，也不要在文档、日志或截图中写入真实密码或完整数据库 URL。重复运行 `init-db` 是安全的。

首次图片导入或查询时才会下载并加载 OpenCLIP；CPU 上首次加载可能较慢，权重会复用项目内 `.cache\open_clip`。

### 建库、检索与 API

支持 `.jpg`、`.jpeg`、`.png` 和 `.webp`，可导入单图或递归目录：

```powershell
.venv\Scripts\python.exe -m backend.cli import .\samples\library
.venv\Scripts\python.exe -m backend.cli search .\samples\query\carpet-a-new-angle.jpg --top-k 5
.venv\Scripts\python.exe -m backend.cli serve
```

图库原图以 SHA-256 命名存至 `data\images`；查询图只在内存中处理，不写入图库或数据库。HTTP 服务默认在 `http://127.0.0.1:8000`，提供：

- `GET /health`：数据库状态与当前配置模型。
- `GET /api/library`：图库图片及模型信息。
- `GET /api/images/{image_id}`：图库图片文件。
- `POST /api/search?top_k=5`：上传查询图并返回相似结果（`top_k` 为 1–50）。

人工验收时，将同一地毯的两到三张不同角度图片和至少一张其他地毯图片置于导入目录；保留一张未入库的同款不同角度图片作为查询图。导入后查询，预期同款其他角度排在对照图片之前。

### 验证命令

```powershell
.venv\Scripts\python.exe -m pytest tests -m "not model" -q
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m backend.cli --help
$env:RUN_MODEL_TESTS = '1'
.venv\Scripts\python.exe -m pytest tests\test_open_clip_smoke.py -v
```


这是一个不依赖后端服务即可演示业务流程的第一版：录入买家秀图片后，客服上传客户家居图即可得到视觉上相近的实拍案例。SKU、商品名称、规格等结构化信息均为选填，可以在获得可靠元数据后逐步补充。

## 启动

直接双击 `index.html`，或用任意静态文件服务器打开该目录。数据存放在浏览器的 IndexedDB 中，不会上传到外部服务。

## 当前匹配逻辑

首版只以本地图像的色调、九宫格构图和宽高比为基础进行相似度排序，不使用空间、风格、预算、库存等结构化元数据影响分数。它可验证录入—匹配—话术—反馈的业务流程，但**不能替代语义级图像检索**；演示数据仅供检查流程，不可作为真实推荐依据。

## 上线前迭代建议

1. 将图片存入对象存储，商品和标签迁移到 PostgreSQL。
2. 用多模态图像向量模型替换 `makeFeature()`，并在 pgvector/Qdrant 中检索 Top 50。
3. 引入库存、可售规格、价格、人工审核等商品规则后重排。
4. 将反馈写入后台，定期检查低分匹配并补充标签。

## 建议的真实数据字段

- 图片 ID、原图地址、缩略图地址、SKU、商品名称、颜色、规格、价格、库存状态
- 空间类型、风格、户型/面积、地板颜色、主色、买家评价、成交话术
- 审核状态、创建时间、来源、运营补充备注
