# CLIP 图片建库与检索后端 Implementation Plan

> 状态：已完成，作为历史实施记录保留。
> 执行说明：下方复选框保留原始计划形态，不表示当前待办。除非用户明确重新启用本计划，否则不得据此重复实现、补测、运行全量验证或发起新一轮审查。

> 历史执行方式：实施阶段曾按任务使用 subagent-driven-development / executing-plans；该要求现已结束。下方 checkbox 仅保留当时的计划格式。

**Goal:** 在本地项目目录中建立可替换图片编码器的 Python 后端，将图片及 CLIP 向量写入 PostgreSQL/pgvector，并通过 CLI 与 FastAPI 提供 Top K 相似度检索。

**Architecture:** 图片文件由 `ImageAssetService` 校验、计算 SHA-256 并复制到项目内图库；编码器通过 `ImageEncoder` 协议注入，首个实现为配置驱动的 OpenCLIP。数据库拆分为图片表与模型向量表，搜索只比较模型身份和维度一致的向量。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy 2、Psycopg 3、pgvector-python、Pillow、NumPy、PyTorch、open_clip_torch、pytest。

**Spec:** `docs/superpowers/specs/2026-09-03-clip-backend-design.md`

## Global Constraints

- Python 虚拟环境固定为项目内 `.venv/`。
- pip、Torch、Hugging Face 和 OpenCLIP 的持久化缓存固定到项目内 `.cache/`。
- 所有 Python 文本文件读写必须显式指定 `encoding="utf-8"`。
- 新增代码的必要注释使用简体中文，解释业务规则、边界条件和关键取舍，不逐行复述代码。
- 数据库使用 Docker 中的 PostgreSQL 16，目标数据库名为 `carpet_matcher`，pgvector 已安装。
- 图片只保存到 `data/images/`，数据库不保存图片二进制。
- 结构化商品元数据不属于本次实现范围。
- 模型不得写死在建库或检索业务中，必须通过 `ImageEncoder` 抽象和环境变量选择。
- 技术验证阶段不创建 HNSW 或 IVFFlat 索引。
- `.env`、`.venv/`、`.cache/`、`data/images/` 不进入版本控制。
- 历史背景：编写本计划时目录尚未按最终 Git 工作流管理；当前仓库和分支状态以实际 `git status` 为准。

## File Structure

```text
.env.example                         不含真实密码的配置示例
.gitignore                           忽略本机环境、缓存和图库
requirements.in                      直接依赖及兼容版本范围
scripts/bootstrap.ps1                创建项目内虚拟环境、设置缓存并安装依赖
backend/__init__.py                  Python 包标记
backend/config.py                    项目路径与环境配置
backend/image_assets.py              图片校验、哈希和安全落盘
backend/encoders/base.py              编码器协议与模型身份
backend/encoders/open_clip.py         OpenCLIP 适配器
backend/encoders/factory.py           根据配置创建编码器
backend/db.py                         数据库创建、连接与会话
backend/models.py                     SQLAlchemy 表模型
backend/repository.py                 图片、向量写入和相似度 SQL
backend/services.py                   建库与搜索用例编排
backend/api.py                        FastAPI 路由和响应模型
backend/cli.py                        init-db/import/search/serve 命令
tests/conftest.py                     临时目录、假编码器与测试配置
tests/test_config.py                  项目内缓存和配置测试
tests/test_image_assets.py            图片校验、哈希和存储测试
tests/test_encoder_contract.py        编码器抽象契约测试
tests/test_repository.py              PostgreSQL/pgvector 集成测试
tests/test_services.py                建库、去重和搜索用例测试
tests/test_api.py                     HTTP 行为测试
tests/test_open_clip_smoke.py         真实模型冒烟测试，默认显式选择运行
```

---

### Task 1: 项目内 Python 环境与配置

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `requirements.in`
- Create: `scripts/bootstrap.ps1`
- Create: `backend/__init__.py`
- Create: `backend/config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.load(project_root: Path | None = None) -> Settings`
- Produces: `Settings.cache_environment() -> dict[str, str]`
- Produces: `Settings.database_url(database: str | None = None) -> sqlalchemy.URL`
- Consumes: Windows 上可执行的 Python 3.12 路径由启动脚本参数接收，默认使用 Codex bundled Python。

- [ ] **Step 1: 写配置失败测试**

```python
def test_settings_keep_runtime_files_inside_project(tmp_path, monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    settings = Settings.load(tmp_path)

    assert settings.venv_dir == tmp_path / ".venv"
    assert settings.image_dir == tmp_path / "data" / "images"
    assert settings.cache_environment() == {
        "PIP_CACHE_DIR": str(tmp_path / ".cache" / "pip"),
        "TORCH_HOME": str(tmp_path / ".cache" / "torch"),
        "HF_HOME": str(tmp_path / ".cache" / "huggingface"),
        "HUGGINGFACE_HUB_CACHE": str(tmp_path / ".cache" / "huggingface" / "hub"),
    }
```

- [ ] **Step 2: 运行测试并确认因 `backend.config` 尚不存在而失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config.py -v`

Expected: FAIL，错误包含 `ModuleNotFoundError: No module named 'backend.config'`。

- [ ] **Step 3: 实现配置对象**

```python
@dataclass(frozen=True)
class Settings:
    project_root: Path
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    image_encoder: str
    clip_model_name: str
    clip_pretrained: str
    model_device: str

    @classmethod
    def load(cls, project_root: Path | None = None) -> "Settings": ...

    def cache_environment(self) -> dict[str, str]: ...

    def database_url(self, database: str | None = None) -> URL: ...
```

配置加载顺序为环境变量覆盖项目 `.env`，`.env` 使用 `python-dotenv` 读取。数据库 URL 使用 `sqlalchemy.URL.create()` 构造，避免手工拼接密码。

- [ ] **Step 4: 编写项目内环境启动脚本**

`scripts/bootstrap.ps1` 接受 `-PythonExecutable`，先把四个缓存环境变量指向项目 `.cache/`，再执行：

```powershell
& $PythonExecutable -m venv $venvPath
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r $requirementsPath
```

脚本不得修改用户级环境变量；所有变量只在当前进程及子进程内生效。

`requirements.in` 使用兼容范围：

```text
fastapi>=0.116,<1
uvicorn>=0.35,<1
sqlalchemy>=2.0,<2.1
psycopg[binary]>=3.2,<4
pgvector>=0.4,<1
pydantic>=2.11,<3
python-dotenv>=1.1,<2
python-multipart>=0.0.20,<1
pillow>=11,<13
numpy>=2,<3
torch>=2.7,<3
open_clip_torch>=3.2,<4
pytest>=8,<10
httpx>=0.28,<1
```

- [ ] **Step 5: 运行配置测试**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config.py -v`

Expected: PASS，且 `.cache/`、`.venv/`、`data/images/` 均解析到项目根目录下。

- [ ] **Step 6: 检查点**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config.py -q`

Expected: `1 passed`；记录安装后的 `python --version` 和 `pip check` 输出。

---

### Task 2: 图片资产校验、哈希与安全存储

**Files:**
- Create: `backend/image_assets.py`
- Create: `tests/test_image_assets.py`

**Interfaces:**
- Produces: `ValidatedImage(sha256: str, original_name: str, mime_type: str, width: int, height: int, extension: str, image: PIL.Image.Image)`
- Produces: `validate_image(path: Path) -> ValidatedImage`
- Produces: `store_image(source: Path, validated: ValidatedImage, image_dir: Path) -> Path`
- Consumes: `Settings.image_dir`

- [ ] **Step 1: 写有效图片和 SHA-256 失败测试**

```python
def test_validate_image_returns_dimensions_rgb_and_byte_hash(tmp_path):
    source = tmp_path / "样图.png"
    Image.new("RGBA", (12, 8), (10, 20, 30, 120)).save(source)

    result = validate_image(source)

    assert result.width == 12
    assert result.height == 8
    assert result.image.mode == "RGB"
    assert result.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
```

- [ ] **Step 2: 运行测试并确认缺失实现导致失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_image_assets.py::test_validate_image_returns_dimensions_rgb_and_byte_hash -v`

Expected: FAIL，错误包含无法导入 `validate_image`。

- [ ] **Step 3: 实现最小图片校验**

支持 `.jpg`、`.jpeg`、`.png`、`.webp`。使用 `path.read_bytes()` 计算 SHA-256；使用 `Image.open(BytesIO(data))`、`image.verify()` 后重新打开并 `load()`，最终转换为 RGB。损坏文件抛出 `InvalidImageError`，错误包含文件名但不包含原始二进制。

- [ ] **Step 4: 写损坏图片与稳定存储路径测试**

```python
def test_store_image_uses_hash_name_and_does_not_overwrite(tmp_path):
    source = make_png(tmp_path / "source.png", color="red")
    validated = validate_image(source)

    first = store_image(source, validated, tmp_path / "library")
    second = store_image(source, validated, tmp_path / "library")

    assert first == second
    assert first.name == f"{validated.sha256}.png"
    assert first.read_bytes() == source.read_bytes()
```

- [ ] **Step 5: 实现幂等存储并运行全部资产测试**

Run: `.venv\Scripts\python.exe -m pytest tests/test_image_assets.py -v`

Expected: 有效图片、损坏图片、非支持扩展名、零尺寸防御和重复存储测试全部 PASS。

- [ ] **Step 6: 检查点**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_image_assets.py -q`

Expected: 全部 PASS。

---

### Task 3: 可替换图片编码器与 OpenCLIP 实现

**Files:**
- Create: `backend/encoders/__init__.py`
- Create: `backend/encoders/base.py`
- Create: `backend/encoders/open_clip.py`
- Create: `backend/encoders/factory.py`
- Create: `tests/test_encoder_contract.py`
- Create: `tests/test_open_clip_smoke.py`

**Interfaces:**
- Produces: `EncoderIdentity(encoder: str, model_name: str, pretrained: str, dimension: int)`
- Produces: `ImageEncoder.identity -> EncoderIdentity`
- Produces: `ImageEncoder.encode(image: PIL.Image.Image) -> numpy.ndarray`
- Produces: `create_encoder(settings: Settings) -> ImageEncoder`
- Consumes: `Settings.image_encoder`, `clip_model_name`, `clip_pretrained`, `model_device`

- [ ] **Step 1: 写编码器契约失败测试**

```python
def assert_encoder_contract(encoder: ImageEncoder, image: Image.Image) -> None:
    vector = encoder.encode(image)
    assert vector.shape == (encoder.identity.dimension,)
    assert vector.dtype == np.float32
    assert np.isfinite(vector).all()
    assert np.linalg.norm(vector) == pytest.approx(1.0, abs=1e-5)


def test_fake_encoder_satisfies_contract():
    assert_encoder_contract(FakeEncoder([3.0, 4.0]), Image.new("RGB", (4, 4)))
```

- [ ] **Step 2: 运行并确认协议类型尚不存在**

Run: `.venv\Scripts\python.exe -m pytest tests/test_encoder_contract.py -v`

Expected: FAIL，错误包含无法导入 `EncoderIdentity` 或 `ImageEncoder`。

- [ ] **Step 3: 实现协议、身份和值校验**

```python
@dataclass(frozen=True)
class EncoderIdentity:
    encoder: str
    model_name: str
    pretrained: str
    dimension: int


class ImageEncoder(Protocol):
    @property
    def identity(self) -> EncoderIdentity: ...

    def encode(self, image: Image.Image) -> np.ndarray: ...


def normalize_embedding(values: np.ndarray) -> np.ndarray: ...
```

`normalize_embedding()` 将结果转为一维 `float32`，拒绝空向量、NaN、Infinity 和零范数，然后执行 L2 归一化。

- [ ] **Step 4: 实现 OpenCLIP 延迟加载适配器**

`OpenClipEncoder` 构造时保存配置，第一次读取 `identity` 或调用 `encode()` 时才加载模型。设备规则：`auto` 时使用 `torch.cuda.is_available()` 选择 `cuda` 或 `cpu`；模型必须调用 `eval()`；推理使用 `torch.inference_mode()`。

- [ ] **Step 5: 实现编码器工厂失败分支并测试**

```python
def test_factory_rejects_unknown_encoder(settings):
    settings = replace(settings, image_encoder="unknown")
    with pytest.raises(ValueError, match="不支持的图片编码器"):
        create_encoder(settings)
```

- [ ] **Step 6: 运行不下载权重的编码器测试**

Run: `.venv\Scripts\python.exe -m pytest tests/test_encoder_contract.py -q`

Expected: 全部 PASS，且测试不触发网络下载。

- [ ] **Step 7: 写并运行显式 OpenCLIP 冒烟测试**

测试标记为 `@pytest.mark.model`，仅在 `RUN_MODEL_TESTS=1` 时执行：创建一张 RGB 小图，调用真实 `OpenClipEncoder`，断言维度大于零、数值有限、范数约为 1。运行时四个缓存变量必须指向项目 `.cache/`。

Run: `$env:RUN_MODEL_TESTS='1'; .venv\Scripts\python.exe -m pytest tests/test_open_clip_smoke.py -v`

Expected: 首次下载模型后 PASS，权重只出现在项目 `.cache/`。

---

### Task 4: PostgreSQL 数据模型与向量仓库

**Files:**
- Create: `backend/db.py`
- Create: `backend/models.py`
- Create: `backend/repository.py`
- Create: `tests/test_repository.py`

**Interfaces:**
- Produces: `create_database_and_schema(settings: Settings) -> None`
- Produces: `create_session_factory(settings: Settings) -> sessionmaker[Session]`
- Produces: `ImageRepository.find_by_sha256(sha256: str) -> ImageRecord | None`
- Produces: `ImageRepository.upsert_embedding(image: ImageRecord, identity: EncoderIdentity, embedding: np.ndarray) -> None`
- Produces: `ImageRepository.search(identity: EncoderIdentity, query: np.ndarray, top_k: int, excluded_sha256: str | None) -> list[SearchRow]`
- Consumes: `ValidatedImage`, `EncoderIdentity`

- [ ] **Step 1: 写数据库模型和初始化失败测试**

```python
def test_schema_supports_multiple_models_for_one_image(db_session, stored_image):
    repository = ImageRepository(db_session)
    image = repository.add_image(stored_image)
    repository.upsert_embedding(image, EncoderIdentity("fake", "a", "v1", 3), unit([1, 0, 0]))
    repository.upsert_embedding(image, EncoderIdentity("fake", "b", "v1", 2), unit([1, 0]))

    assert repository.embedding_count(image.id) == 2
```

- [ ] **Step 2: 运行并确认数据库模块尚不存在**

Run: `.venv\Scripts\python.exe -m pytest tests/test_repository.py::test_schema_supports_multiple_models_for_one_image -v`

Expected: FAIL，错误包含无法导入数据库模块。

- [ ] **Step 3: 实现数据库创建和幂等 schema 初始化**

`create_database_and_schema()` 使用 Psycopg 连接 `postgres` 管理库，以参数化查询检查数据库是否存在，并用 `psycopg.sql.Identifier` 安全创建 `carpet_matcher`。随后连接目标数据库并执行 `CREATE EXTENSION IF NOT EXISTS vector` 与 SQLAlchemy `metadata.create_all()`。

模型严格对应规格中的 `images` 和 `image_embeddings`。`embedding` 使用无固定维度 `VECTOR()`，并定义 `(image_id, encoder, model_name, pretrained)` 唯一约束。

- [ ] **Step 4: 写模型过滤、余弦排序和排除同文件测试**

```python
def test_search_filters_model_and_excludes_identical_file(repository):
    seed_embeddings(repository)
    rows = repository.search(
        identity=EncoderIdentity("fake", "model-a", "v1", 3),
        query=unit([1, 0, 0]),
        top_k=2,
        excluded_sha256="same-query-hash",
    )

    assert [row.original_name for row in rows] == ["same-carpet-angle.jpg", "other.jpg"]
    assert all(row.model_name == "model-a" for row in rows)
```

- [ ] **Step 5: 实现 pgvector 余弦查询**

查询必须同时过滤 `encoder`、`model_name`、`pretrained` 和 `dimension`；使用 `ImageEmbedding.embedding.cosine_distance(query)` 排序。相似度换算集中为：

```python
def cosine_distance_to_percent(distance: float) -> float:
    return round(max(0.0, min(100.0, (1.0 - distance) * 100.0)), 2)
```

- [ ] **Step 6: 运行 PostgreSQL 集成测试**

Run: `.venv\Scripts\python.exe -m pytest tests/test_repository.py -v`

Expected: 表结构、多模型共存、维度过滤、余弦排序、完全相同文件排除和事务回滚测试全部 PASS。测试记录必须在测试事务中回滚，不删除用户数据。

- [ ] **Step 7: 检查点**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_image_assets.py tests/test_encoder_contract.py tests/test_repository.py -q`

Expected: 全部 PASS。

---

### Task 5: 建库与搜索服务、CLI

**Files:**
- Create: `backend/services.py`
- Create: `backend/cli.py`
- Create: `tests/test_services.py`

**Interfaces:**
- Produces: `ImportStatus` 枚举：`IMPORTED`、`DUPLICATE`、`EMBEDDING_ADDED`、`FAILED`
- Produces: `ImportResult(path: Path, status: ImportStatus, message: str)`
- Produces: `LibraryService.import_path(path: Path) -> list[ImportResult]`
- Produces: `LibraryService.search(path: Path, top_k: int = 5) -> list[SearchResult]`
- Consumes: `ImageEncoder`、`ImageRepository`、`validate_image()`、`store_image()`

- [ ] **Step 1: 写建库状态失败测试**

```python
def test_import_directory_continues_after_invalid_file(service, image_dir):
    make_png(image_dir / "valid.png", color="red")
    (image_dir / "broken.jpg").write_bytes(b"not-an-image")

    results = service.import_path(image_dir)

    assert [result.status for result in results] == [ImportStatus.FAILED, ImportStatus.IMPORTED]
    assert service.repository.image_count() == 1
```

- [ ] **Step 2: 运行测试并确认服务尚不存在**

Run: `.venv\Scripts\python.exe -m pytest tests/test_services.py -v`

Expected: FAIL，错误包含无法导入 `LibraryService`。

- [ ] **Step 3: 实现导入编排**

目录扩展名匹配采用不区分大小写的递归扫描，并按规范化路径排序以保证稳定输出。行为：

- 新图片和新模型向量：`IMPORTED`；
- 图片和当前模型向量都存在：`DUPLICATE`；
- 图片存在但当前模型向量缺失：`EMBEDDING_ADDED`；
- 单文件异常：`FAILED` 并继续下一张。

如果文件刚复制但数据库事务失败，删除本次新建的目标文件；不得删除原图或既有图库文件。

- [ ] **Step 4: 写搜索服务测试**

```python
def test_search_excludes_exact_query_but_keeps_other_angles(service, query_path):
    results = service.search(query_path, top_k=5)

    assert all(item.sha256 != sha256_file(query_path) for item in results)
    assert results[0].original_name == "same-carpet-angle.jpg"
```

- [ ] **Step 5: 实现搜索和 top_k 校验**

`top_k` 必须在 1 到 50 之间。查询图片使用相同校验和编码器，但不调用 `store_image()`，不产生文件或数据库记录。

- [ ] **Step 6: 实现 argparse CLI**

`backend.cli.main(argv: Sequence[str] | None = None) -> int` 注册 `init-db`、`import`、`search`、`serve`。所有输出使用中文；失败返回非零退出码；不得输出密码或完整数据库 URL。

- [ ] **Step 7: 运行服务测试与 CLI 帮助检查**

Run: `.venv\Scripts\python.exe -m pytest tests/test_services.py -v`

Run: `.venv\Scripts\python.exe -m backend.cli --help`

Expected: 测试全部 PASS，帮助中列出四个子命令。

---

### Task 6: FastAPI 接口

**Files:**
- Create: `backend/api.py`
- Create: `tests/test_api.py`

**Interfaces:**
- Produces: `create_app(settings: Settings | None = None, encoder: ImageEncoder | None = None) -> FastAPI`
- Produces: `app = create_app()`
- Consumes: `LibraryService`、`ImageRepository`、`Settings`

- [ ] **Step 1: 写健康检查与懒加载模型失败测试**

```python
def test_health_does_not_encode_an_image(client, fake_encoder):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["database"] == "ok"
    assert response.json()["model"]["encoder"] == "fake"
    assert fake_encoder.encode_calls == 0
```

- [ ] **Step 2: 运行并确认 API 模块尚不存在**

Run: `.venv\Scripts\python.exe -m pytest tests/test_api.py::test_health_does_not_encode_an_image -v`

Expected: FAIL，错误包含无法导入 `create_app`。

- [ ] **Step 3: 实现健康检查、图库列表和安全图片读取**

`GET /api/images/{image_id}` 只能从数据库取得 `stored_path`，解析后验证最终路径仍位于 `Settings.image_dir` 下，再返回 `FileResponse`。不存在返回 404，路径越界返回 400，不接受用户传入文件路径。

- [ ] **Step 4: 写搜索接口成功和失败测试**

```python
def test_search_returns_ranked_results_without_persisting_query(client, repository, png_bytes):
    before = repository.image_count()
    response = client.post(
        "/api/search",
        params={"top_k": 3},
        files={"image": ("query.png", png_bytes, "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["rank"] == 1
    assert repository.image_count() == before
```

另测损坏图片返回 400、`top_k=0` 或大于 50 返回 422、无当前模型向量时返回空数组和说明字段。

- [ ] **Step 5: 实现内存查询上传**

上传文件设置大小上限；内容写入 `SpooledTemporaryFile` 或项目临时目录后验证，并在请求结束时清理。不得把查询图片复制到 `data/images/`。响应严格包含模型身份、结果名次、图片 ID、原名、图片 URL 和相似度。

- [ ] **Step 6: 运行 API 测试**

Run: `.venv\Scripts\python.exe -m pytest tests/test_api.py -v`

Expected: 全部 PASS，无未处理异常或警告。

- [ ] **Step 7: 检查点**

Run: `.venv\Scripts\python.exe -m pytest tests -m "not model" -q`

Expected: 除显式模型测试外全部 PASS。

---

### Task 7: 真实环境初始化与端到端验证

**Files:**
- Modify: `README.md`
- Modify: `.env`（本机文件，不提交）
- Create: `pytest.ini`

**Interfaces:**
- Consumes: Task 1–6 的所有公开 CLI 和 HTTP 接口。
- Produces: 可运行的 `carpet_matcher` 数据库、项目内模型缓存和可重复的验证命令。

- [ ] **Step 1: 创建本机 `.env`**

使用已确认的主机、端口、数据库、用户和用户提供的密码。模型配置为：

```env
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=carpet_matcher
POSTGRES_USER=postgres
IMAGE_ENCODER=open_clip
CLIP_MODEL_NAME=ViT-B-32
CLIP_PRETRAINED=openai
MODEL_DEVICE=auto
```

密码只写入 `.env`，不得写入计划、README、命令输出或测试快照。

- [ ] **Step 2: 初始化数据库**

Run: `.venv\Scripts\python.exe -m backend.cli init-db`

Expected: 数据库 `carpet_matcher` 存在，`vector` 扩展可用，`images` 与 `image_embeddings` 表存在；重复执行仍成功。

- [ ] **Step 3: 运行完整自动化测试**

Run: `.venv\Scripts\python.exe -m pytest tests -m "not model" -q`

Expected: 全部 PASS。

- [ ] **Step 4: 下载模型并运行真实编码器冒烟测试**

Run: `$env:RUN_MODEL_TESTS='1'; .venv\Scripts\python.exe -m pytest tests/test_open_clip_smoke.py -v`

Expected: PASS；模型权重和缓存只位于项目 `.cache/`。

- [ ] **Step 5: 使用用户测试图片做 CLI 验收**

Run: `.venv\Scripts\python.exe -m backend.cli import <用户测试图片目录>`

Run: `.venv\Scripts\python.exe -m backend.cli search <未入库查询图片> --top-k 5`

Expected: 同一地毯的其他角度排在不同地毯对照图片之前。若用户图片尚未放入项目，跳过此人工数据步骤，但不伪造验收结论。

- [ ] **Step 6: 启动 API 并验证 HTTP**

Run: `.venv\Scripts\python.exe -m backend.cli serve`

验证：

```text
GET  http://127.0.0.1:8000/health
GET  http://127.0.0.1:8000/api/library
POST http://127.0.0.1:8000/api/search?top_k=5
```

Expected: Edge 扩展可访问服务；浏览器控制台无错误；查询图片不进入图库。

- [ ] **Step 7: 更新 README**

README 写明 Windows 初始化、项目内缓存、`.env`、数据库初始化、图片导入、CLI 搜索、API 启动和首次模型下载说明，并明确当前为技术验证、模型可替换、前端尚未接入 API。

- [ ] **Step 8: 最终验证**

Run: `.venv\Scripts\python.exe -m pytest tests -m "not model" -q`

Run: `.venv\Scripts\python.exe -m pip check`

Run: `.venv\Scripts\python.exe -m backend.cli --help`

Expected: 测试零失败、依赖无冲突、CLI 四个子命令完整。检查 `.venv/`、`.cache/`、`.env` 和 `data/images/` 均被 `.gitignore` 覆盖，源码中不存在真实密码。
