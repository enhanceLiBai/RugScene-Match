# CLIP 图片建库与相似度检索后端设计

> 日期：2026-09-03  
> 状态：已实施，作为历史设计基线保留
> 执行说明：本文用于解释既有后端的设计背景，不构成新的实现、测试或审查任务。
> 阶段：技术验证

## 1. 目标

为现有地毯买家秀 MVP 增加一个本地 Python 后端，验证 CLIP 图像向量能否召回同一地毯在不同拍摄角度下的照片。

本阶段提供：

- 从单张图片或目录批量建库的 CLI；
- 使用查询图片执行 Top K 相似度检索的 CLI；
- 可供前端调用的最小 FastAPI 服务；
- PostgreSQL + pgvector 向量存储；
- 可替换的图片编码器接口。

本阶段不提供：

- SKU、空间、风格、价格等结构化元数据；
- 用户、权限和运营审核系统；
- 针对大规模图库的 HNSW/IVFFlat 索引调优；
- 自动判断两张相似图片是否属于同一商品。

## 2. 已确认环境

- PostgreSQL 运行在 Docker 容器 `pgvector-demo` 中；
- 主机端口 `5432` 映射到容器端口 `5432`；
- PostgreSQL 版本为 16.15；
- pgvector 版本为 0.8.6；
- 新建独立数据库 `carpet_matcher`；
- 当前没有可用的 NVIDIA CUDA 环境，首版必须支持 CPU；
- Python 虚拟环境、Python 包缓存和模型权重必须位于当前项目目录，不能持久化到 C 盘用户目录。

## 3. 总体架构

```text
测试图片
   ↓
CLI 批量导入
   ↓
图片解码校验 + SHA-256 精确文件去重
   ↓
ImageEncoder 抽象接口
   ↓
OpenClipEncoder（首个实现，模型由配置指定）
   ↓
PostgreSQL carpet_matcher + pgvector

查询图片
   ↓
FastAPI / CLI
   ↓
当前编码器生成归一化向量
   ↓
按相同模型标识和向量维度筛选
   ↓
pgvector 余弦距离排序
   ↓
返回 Top K 相似图片
```

## 4. 本地目录与缓存

所有持久化运行文件均放在项目目录内：

```text
.venv/                  Python 虚拟环境和安装依赖
.cache/pip/             pip 下载缓存
.cache/torch/           PyTorch 缓存
.cache/huggingface/     Hugging Face / OpenCLIP 模型权重
data/images/            已入库图片
```

启动脚本和应用配置显式设置：

- `PIP_CACHE_DIR`
- `TORCH_HOME`
- `HF_HOME`
- `HUGGINGFACE_HUB_CACHE`

上述目录加入 `.gitignore`。模型权重不进入源码或数据库。

## 5. 模型可替换设计

业务层只依赖统一的 `ImageEncoder` 接口：

```python
class ImageEncoder(Protocol):
    @property
    def identity(self) -> EncoderIdentity: ...

    def encode(self, image: Image.Image) -> numpy.ndarray: ...
```

`EncoderIdentity` 至少包含：

- 编码器类型；
- 模型名称；
- 预训练权重名称或版本；
- 输出向量维度。

首个实现使用 `open_clip_torch`。默认验证配置为：

```env
IMAGE_ENCODER=open_clip
CLIP_MODEL_NAME=ViT-B-32
CLIP_PRETRAINED=openai
```

默认值只是配置，不写入建库和检索业务逻辑。未来替换 OpenCLIP 模型、自训练模型或远程编码服务时，只新增编码器实现或调整配置。

编码器负责：

1. 加载模型和对应预处理器；
2. 将输入图片转换为 RGB；
3. 批量生成图像向量；
4. 对向量执行 L2 归一化；
5. 暴露稳定、可持久化的模型标识。

设备选择默认为 `auto`：检测到 CUDA 时使用 CUDA，否则使用 CPU。CPU 是验收基线。

## 6. 图片校验与精确去重

导入时使用 Pillow 解码图片，并校验：

- 文件扩展名和实际内容可被支持的图片解码器读取；
- 图片宽高大于零；
- 图片可以完整加载并转换为 RGB；
- 支持 JPG、JPEG、PNG 和 WEBP。

对原始文件字节计算 SHA-256，并在 `images.sha256` 上设置唯一约束。

SHA-256 只识别完全相同的文件：

- 同一个文件重复导入时跳过；
- 同一图片重新压缩、缩放后视为不同文件；
- 同一地毯不同角度拍摄的照片必然作为不同记录入库。

## 7. 数据库设计

### 7.1 `images`

| 字段 | 类型 | 约束与含义 |
|---|---|---|
| `id` | `bigserial` | 主键 |
| `original_name` | `text` | 原始文件名 |
| `stored_path` | `text` | 相对于项目根目录的路径 |
| `sha256` | `char(64)` | 唯一、非空 |
| `mime_type` | `text` | 图片 MIME 类型 |
| `width` | `integer` | 大于零 |
| `height` | `integer` | 大于零 |
| `created_at` | `timestamptz` | 默认当前时间 |

### 7.2 `image_embeddings`

| 字段 | 类型 | 约束与含义 |
|---|---|---|
| `id` | `bigserial` | 主键 |
| `image_id` | `bigint` | 外键，删除图片时级联删除 |
| `encoder` | `text` | 编码器实现标识 |
| `model_name` | `text` | 模型名称 |
| `pretrained` | `text` | 权重名称或版本 |
| `dimension` | `integer` | 向量维度 |
| `embedding` | `vector` | 不固定维度的 pgvector 列 |
| `created_at` | `timestamptz` | 默认当前时间 |

唯一约束覆盖：`image_id + encoder + model_name + pretrained`。

技术验证阶段不创建向量近似索引。检索必须先按编码器标识、模型、权重和维度过滤，再执行余弦距离，避免不同向量空间混用。确定正式模型后，可以为对应维度增加表达式或分表索引。

## 8. 建库流程

CLI 接受图片文件或目录；目录采用递归扫描。

每张图片依次执行：

1. 检查扩展名；
2. 读取原始字节并计算 SHA-256；
3. 查询数据库是否已有相同 SHA-256；
4. 解码并完整加载图片；
5. 将图片复制到 `data/images/<sha256>.<ext>`；
6. 使用当前编码器生成向量；
7. 在一个数据库事务中写入图片记录和向量记录；
8. 输出成功、重复或失败状态。

目录导入时，单张图片失败不会中止其他图片。命令结束后输出成功数、重复数、失败数和失败原因摘要。

如果数据库中已有图片但缺少当前模型的向量，导入流程复用图片记录并补充该模型向量，不重复复制文件。

## 9. 检索流程

1. 接收查询图片并完成相同的图片校验；
2. 计算查询文件 SHA-256；
3. 使用当前编码器生成归一化向量；
4. 从 `image_embeddings` 中筛选模型标识和维度一致的记录；
5. 默认排除 SHA-256 与查询文件完全相同的入库记录；
6. 使用 pgvector 余弦距离操作符 `<=>` 排序；
7. 将余弦距离转换为相似度百分比，并返回 Top K。

同一地毯不同角度照片的 SHA-256 不同，因此不会被排除。

技术验证阶段相似度百分比仅用于结果比较，不设定“同一地毯”的自动判定阈值。

## 10. CLI 设计

```text
python -m backend.cli init-db
python -m backend.cli import <图片或目录>
python -m backend.cli search <查询图片> --top-k 5
python -m backend.cli serve
```

- `init-db`：连接默认管理库，创建 `carpet_matcher`，连接新数据库并启用 `vector`、创建表；重复运行保持幂等。
- `import`：递归导入图片并打印统计结果。
- `search`：打印名次、图片 ID、文件名、路径和相似度。
- `serve`：启动 FastAPI 服务。

## 11. HTTP API 设计

### `GET /health`

检查应用和数据库连接，返回当前编码器标识，不强制提前加载模型权重。

### `GET /api/library`

返回已入库图片列表及其可用模型标识。

### `GET /api/images/{image_id}`

根据数据库记录安全读取 `data/images/` 内的图片。禁止通过路径参数直接访问任意本地文件。

### `POST /api/search`

使用 `multipart/form-data` 上传一张查询图片，参数包含 `top_k`，默认 5，并设置合理上限。

返回结构：

```json
{
  "model": {
    "encoder": "open_clip",
    "name": "ViT-B-32",
    "pretrained": "openai",
    "dimension": 512
  },
  "results": [
    {
      "rank": 1,
      "image_id": 1,
      "original_name": "angle-2.jpg",
      "image_url": "/api/images/1",
      "similarity": 87.42
    }
  ]
}
```

查询图片只在内存中处理，不复制到图库，也不写入数据库。

## 12. 配置与敏感信息

`.env` 保存本机数据库连接和模型配置：

```env
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=carpet_matcher
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<本机密码>
IMAGE_ENCODER=open_clip
CLIP_MODEL_NAME=ViT-B-32
CLIP_PRETRAINED=openai
MODEL_DEVICE=auto
```

`.env` 必须加入 `.gitignore`，示例配置写入不含真实密码的 `.env.example`。日志和异常不得输出数据库密码或完整连接 URI。

## 13. 错误处理

- 数据库不可用：CLI 返回非零退出码；HTTP 返回服务不可用错误。
- 数据库或扩展初始化失败：保留原始异常类型，但隐藏密码。
- 图片损坏或格式不支持：该文件标记失败，不写入数据库。
- 图片重复：作为正常跳过状态，不计入失败。
- 模型权重缺失或下载失败：提示模型名称、项目内缓存目录和重试方式。
- 模型输出维度异常或包含非有限值：拒绝写入数据库。
- 查询库中没有当前模型向量：返回空结果及明确说明。

## 14. 测试与验收

### 自动化测试

- 单元测试：图片格式校验、SHA-256、相对路径、重复状态、模型标识和相似度换算；
- 编码器契约测试：使用轻量测试编码器验证建库与检索业务不依赖 OpenCLIP 实现；
- PostgreSQL 集成测试：在现有 Docker PostgreSQL 中验证表结构、可变维度向量写入、模型过滤和余弦排序；
- OpenCLIP 冒烟测试：使用真实模型处理一张小图，验证向量维度、有限值和 L2 归一化；
- API 测试：验证健康检查、图库列表、图片读取、查询上传和错误响应。

### 人工验证

1. 准备若干同一地毯不同角度的入库图片，以及至少一张其他地毯作为对照；
2. 准备一张未入库的同一地毯查询图片；
3. 执行目录导入；
4. 分别通过 CLI 和 HTTP API 查询 Top K；
5. 确认同一地毯的不同角度图片排在对照图片之前；
6. 重复导入同一目录，确认所有原文件被识别为重复且数据库记录不增长。

## 15. 实施边界

本次实现后端建库与相似检索能力，但不在本阶段把现有静态前端改造成 API 客户端。后端 API 稳定并通过不同角度图片验证后，再单独设计前端迁移。
