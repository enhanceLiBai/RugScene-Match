# Task 2: 腾讯文档 XLSX 流式结构解析器

Plan: `docs/superpowers/plans/2026-09-07-product-buyer-image-linking.md`
Spec: `docs/superpowers/specs/2026-09-07-product-buyer-image-linking-design.md`

## Global constraints

- 只处理“地毯图片”工作表；F 是商品 ID，K 是 `product_main`，L/M/N 是 `buyer_sofa`；忽略 J 和 O–Q。
- 不能加载完整 1.28 GB 工作簿或一次解压全部图片；每次只读取一张图片字节。
- 图片必须保持工作簿内原始字节，不截图、不转码。
- 使用 Python 标准库 `zipfile` 与 `xml.etree.ElementTree`，不增加依赖。
- 新增必要注释使用简体中文；所有显式文本文件操作指定 UTF-8。
- 只运行本任务测试，pytest 使用 `--basetemp .pytest-tmp/task2`。

## Files

- Create: `backend/tencent_excel.py`
- Create: `tests/test_tencent_excel.py`

## Interfaces

- Produces: `WorkbookImage(product_id: str, role: Literal["product_main", "buyer_sofa"], source_column: Literal["K", "L", "M", "N"], filename: str, data: bytes)`。
- Produces: `iter_product_images(path: Path) -> Iterator[WorkbookImage]`。
- Produces: `WorkbookStructureError(ValueError)`。

## Required work

1. 先在 `tests/test_tencent_excel.py` 用 `zipfile.ZipFile` 和最小 XML 生成小型腾讯结构 XLSX，包含 F 商品 ID、J–O 图片锚点和小 PNG。测试只返回 K–N；四张图片共享同一商品 ID；角色和列正确；返回字节以 PNG 签名开头。
2. 增加目标工作表不存在时抛出 `WorkbookStructureError("找不到工作表：地毯图片")` 的测试；缺少 F 值的行不产生结果。
3. 运行目标测试获得 RED：`$env:PYTHONIOENCODING='utf-8'; D:\电商ai应用\.venv\Scripts\python.exe -m pytest tests\test_tencent_excel.py --basetemp .pytest-tmp/task2 -q`。
4. 实现解析器：读取 workbook/rels/sharedStrings/目标 worksheet/drawing/drawing rels；解析普通数值、shared string 和 inline string 的 F 列商品 ID；解析 `oneCellAnchor/from` 的零基行列以及 `blip r:embed`；规范化相对关系路径并拒绝越出 XLSX 包。
5. 只为 K–N 锚点读取媒体；在生成每个 `WorkbookImage` 前调用 `archive.read(media_path)`，不建立全部图片字节列表。媒体文件名保留 ZIP 条目末段。
6. 损坏 ZIP、缺少关键 XML/关系、图片目标不存在时转为不含内部堆栈的 `WorkbookStructureError`；单行缺商品 ID 直接跳过。
7. 运行同一目标测试获得 GREEN；不要读取真实 1.28 GB 文件，也不要运行完整测试集。
8. 自查并提交：`git add backend/tencent_excel.py tests/test_tencent_excel.py && git commit -m "feat: parse Tencent workbook images"`。

## Report

完整报告写入 `task-2-report.md`，包含实现、RED/GREEN、文件、提交、自查和顾虑。最终回复只返回状态、提交、测试摘要、顾虑和报告路径。
