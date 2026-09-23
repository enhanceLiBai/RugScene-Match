# 目录预筛选与入库

## 合并营销后缀目录

`backend.merge_style_variants` 仅合并同一商品 ID 下、末尾为已确认营销后缀的目录：`可享国补`、`国补`、`预售15天`、`百搭不出错`，以及轻奢、中古、北欧等风格推荐词。它只在无后缀基础款目录已存在时移动图片；没有基础款目录时保留原样，避免猜测。材质、颜色、花型等其他括号内容不会处理。

```powershell
# 预览
.ven\Scripts\python.exe -m backend.merge_style_variants "\\DS923plus\ccfarts二合一运营部\商品买家秀抓取\按商品ID和款式整理_千牛热门30"

# 确认预览后执行
.ven\Scripts\python.exe -m backend.merge_style_variants "\\DS923plus\ccfarts二合一运营部\商品买家秀抓取\按商品ID和款式整理_千牛热门30" --execute
```

同名图片不会覆盖，会自动添加编号；移动明细写入 `data/style-merge-report.jsonl`。合并仅调整通过预筛选后保留在源目录的图片，不会移动同级 `_淘汰` 目录内容。

## 预筛选后人工入库

`backend.folder_screen` 是独立预筛选脚本，不改动旧 `backend.folder_import` 的审核后入库逻辑。

```powershell
.ven\Scripts\python.exe -m backend.folder_screen "\\DS923plus\ccfarts二合一运营部\商品买家秀抓取\按商品ID和款式整理_千牛热门30" --execute
```

DeepSeek 已关闭深度思考，并强制 JSON 模式，只返回 `{"qualified":true}` 或 `{"qualified":false}`。合格图片保留原目录，供人工筛选；不合格图片移动到同级 `按商品ID和款式整理_千牛热门30_淘汰\商品ID_款式\`，不覆盖同名文件。

每张图完成后都会追加 `data/folder-screen-report.jsonl`，同时原子更新 `data/folder-screen-checkpoint.json`。余额不足时，脚本写入 `stopped_quota` 并退出，不继续发起请求；充值后用相同命令重新执行即可。已合格和已移动淘汰图片会跳过，失败或余额不足的当前图片会重试。

先扫描（不读取图片内容、不调用模型、不写库）：

```powershell
.ven\Scripts\python.exe -m backend.folder_import "\\DS923plus\ccfarts二合一运营部\商品买家秀抓取\按商品ID和款式整理_完整"
```

开始入库：在命令后增加 `--execute`，可加 `--limit 20` 限制本轮扫描文件数。移除 limit 处理全部。每张图先校验格式及 20 MiB 上限，再调用 DeepSeek JSON 模式，深度思考关闭。不合格图片移动到来源目录同级的 `_淘汰` 目录，保留商品子目录结构且不覆盖同名文件；不合格图片不会继续打标签或写库。合格图片生成场景、沙发、地板、墙面和画面色调标签后写入图片、向量、标签和商品关联。API、格式或标签响应错误记为 failed，重复运行自动重试。

处理报告默认 data/folder-import.jsonl；包含源路径、哈希、商品 ID、商品名称、标签、图片ID和状态。保留报告，重复运行跳过已成功的同内容同商品记录；不是新增数据库恢复机制，数据库被人工修改后应核对报告再运行。不同内容图片不会因为文件名相同被跳过。文件异常只记录错误类型，不输出密钥或响应原文。

标签包括场景、沙发状态/颜色/材质、地板状态/颜色/材质、拍摄冷暖色调。合格但缺少现有检索要求的沙发或地板属性也可入库，报告 search_eligible=false。当前检索仍按原有场景条件执行。

本版仅实现脚本，商品名称保存 `images.product_name`，不写入 `images.style`；商品 ID 通过 `product_images` 关联。未知商品ID不创建虚假商品。目录来源暂映射为现有 buyer_sofa/L 关联；不代表实际来自 Excel L 列。脚本优先读取 Windows 用户或系统环境变量 `deepseek-api-key`，并兼容 `DEEPSEEK_API_KEY`，无需在启动命令中注入。

重要：商品ID＋款式关联结构和结果按款式去重尚未升级，现有前端仍按商品ID去重并使用商品级主图。故不应将本脚本视为已经完成按款式检索展示的整体交付。本次不会自动执行全部入库；没有更改旧数据库结构或旧历史。

逐张顺序处理，Ctrl+C 可停止，已提交图片保留；中断当张可重跑。图片、向量、标签及关联的数据库写入同事务；写入失败可能留下按哈希存储但未登记的文件，重跑复用，不清理源图或已有文件。
