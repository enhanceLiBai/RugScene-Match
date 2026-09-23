# 本机 Docker 部署与测试

## 当前方案

应用使用 Linux CUDA 镜像，默认发布在本机 8001 端口。现有 Windows 服务及 Cloudflare 指向的 8000 端口保持运行。数据库继续使用现有 pgvector 容器；本机数据库目录为 D:/Docker/pgvector/data，不迁移、不删除。

应用的 ./data 挂载到 /app/data，./.cache/open_clip 挂载到 /app/.cache/open_clip。图库扩充写入挂载目录及原数据库，重建应用镜像无需重新导入。数据库内历史和客户照片继续保留。应用镜像不包含密钥、图片、数据库、Excel 或模型缓存。

.env 由 Compose 在运行时注入；数据库地址覆盖为 Docker 网络中的 pgvector，模型设备为 cuda。不要将展开的 docker compose config 输出粘贴到公开位置，它可能包含密钥；验证使用 config --quiet。

## 前置条件

- Docker Desktop 使用 Linux 容器，并具备 NVIDIA GPU 支持。
- 当前主机为 RTX 5060，镜像采用 PyTorch 2.7.1 / CUDA 12.8。实际 GPU 可用性必须由容器内测试确认。
- Docker Hub 和 Python 包下载源可访问，磁盘有足够空间存放 CUDA 镜像。
- 项目根目录已准备 .env、data/images、.cache/open_clip。

## 首次准备（本次已建立网络）

```powershell
cd D:\RugScene-Match-main
docker network create rugscene-network
docker network connect rugscene-network pgvector
```

网络及连接只需建立一次；已存在时不要重复操作。数据库容器应先启动。

## 构建与测试启动

```powershell
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
```

访问 http://127.0.0.1:8001/，使用原图库和历史。此测试环境与现有应用共享业务数据，上传、匹配和删除都会影响真实数据。

```powershell
./scripts/test-docker.ps1
```

脚本检查容器 GPU、首页、数据库健康、图库及历史接口。随后用一张已知图片手动匹配，确认场景识别、预览与原图下载；通过网页导入一张实际需要的图库图片，记录图片 ID。运行 docker compose up -d --force-recreate 后，确认该图片及历史仍在，以验证持久化。尚未执行的步骤不能视为通过。

## 正式切换与回退

测试通过后，先停止当前占用 8000 的 Windows FastAPI，再执行：

```powershell
$env:APP_PORT = '8000'
docker compose up -d
```

现有 Cloudflare 仍指向 127.0.0.1:8000，无需重启隧道。后续维护终端也应设置相同 APP_PORT，或在项目 .env 中设置 APP_PORT=8000，以免重新启动时恢复到 8001。

回退时运行 docker compose down（只管理应用，不会停止外部数据库或删除绑定目录），然后启动原 Windows FastAPI。不要删除图库或数据库目录。

## 日常维护与扩充图库

```powershell
docker compose logs --tail 100 app
docker compose restart app
docker compose up -d --build
```

继续使用网页单图上传和 Excel 导入即可，无需重新构建镜像。优先使用网页入库路径以复用场景标签流程。数据库与 data 目录应配套备份；镜像不是业务数据备份。避免在仍有导入任务时重建应用，当前后台导入不保证进程重启后自动续跑。

## 本次验证状态

- Compose 配置静态校验通过。
- 数据库已有持久化绑定目录，已连接 rugscene-network。
- 已确认现有图片路径使用 data/images/...，适用于 Linux 挂载路径。
- 镜像构建未完成：Docker Desktop 直连 registry-1.docker.io:443 超时，错误提示未配置 HTTPS 代理。
- 容器 GPU、运行接口、真实匹配及重建持久化测试尚未执行；需要先恢复 Docker Hub 下载。
- 现有 8000 服务和隧道未切换。
