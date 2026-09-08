# Review package Task 2

Base: 54b21b5
Head: a712dab

## Commits

```
a712dab feat: parse Tencent workbook images

```

## Stat

```
 backend/tencent_excel.py    | 219 ++++++++++++++++++++++++++++++++++++++++++++
 tests/test_tencent_excel.py | 142 ++++++++++++++++++++++++++++
 2 files changed, 361 insertions(+)

```

## Diff

```diff
diff --git a/backend/tencent_excel.py b/backend/tencent_excel.py
new file mode 100644
index 0000000..359ea00
--- /dev/null
+++ b/backend/tencent_excel.py
@@ -0,0 +1,219 @@
+"""以流式方式读取腾讯文档 XLSX 中与商品关联的原始图片。"""
+
+from __future__ import annotations
+
+from dataclasses import dataclass
+from pathlib import Path, PurePosixPath
+import posixpath
+import re
+from typing import Iterator, Literal
+from xml.etree import ElementTree
+from zipfile import BadZipFile, ZipFile
+
+
+OFFICE_RELATIONSHIP = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
+CELL_REFERENCE = re.compile(r"^([A-Za-z]+)([1-9][0-9]*)$")
+
+
+class WorkbookStructureError(ValueError):
+    """工作簿缺少解析所需的 XML、关系或图片时抛出。"""
+
+
+@dataclass(frozen=True)
+class WorkbookImage:
+    """工作簿内一张与商品 ID 对应的原始图片。"""
+
+    product_id: str
+    role: Literal["product_main", "buyer_sofa"]
+    source_column: Literal["K", "L", "M", "N"]
+    filename: str
+    data: bytes
+
+
+def iter_product_images(path: Path) -> Iterator[WorkbookImage]:
+    """按锚点顺序产生“地毯图片”工作表中 K-N 列关联的图片。"""
+    try:
+        with ZipFile(path) as archive:
+            yield from _iter_archive_images(archive)
+    except WorkbookStructureError:
+        raise
+    except (BadZipFile, ElementTree.ParseError, KeyError, OSError, ValueError):
+        raise WorkbookStructureError("工作簿结构错误") from None
+
+
+def _iter_archive_images(archive: ZipFile) -> Iterator[WorkbookImage]:
+    entries = set(archive.namelist())
+    workbook_path = "xl/workbook.xml"
+    workbook = _read_xml(archive, workbook_path)
+    workbook_relationships = _relationship_map(_read_xml(archive, "xl/_rels/workbook.xml.rels"))
+
+    sheet_relationship_id = _find_carpet_sheet_relationship_id(workbook)
+    worksheet_path = _resolve_relationship_path(workbook_path, workbook_relationships[sheet_relationship_id], entries)
+    worksheet = _read_xml(archive, worksheet_path)
+    product_ids = _product_ids_by_row(worksheet, _shared_strings(archive, entries))
+
+    drawing_relationship_id = _find_drawing_relationship_id(worksheet)
+    worksheet_relationships_path = _rels_path(worksheet_path)
+    drawing_relationships = _relationship_map(_read_xml(archive, worksheet_relationships_path))
+    drawing_path = _resolve_relationship_path(
+        worksheet_path, drawing_relationships[drawing_relationship_id], entries
+    )
+    drawing = _read_xml(archive, drawing_path)
+    drawing_relationships = _relationship_map(_read_xml(archive, _rels_path(drawing_path)))
+
+    for row, column, embed_id in _image_anchors(drawing):
+        column_info = _image_column(column)
+        if column_info is None:
+            continue
+        product_id = product_ids.get(row + 1)
+        if not product_id:
+            continue
+        media_path = _resolve_relationship_path(drawing_path, drawing_relationships[embed_id], entries)
+        # 仅在即将产出时读取单张图片，避免解压整个工作簿的媒体文件。
+        data = archive.read(media_path)
+        role, source_column = column_info
+        yield WorkbookImage(
+            product_id=product_id,
+            role=role,
+            source_column=source_column,
+            filename=PurePosixPath(media_path).name,
+            data=data,
+        )
+
+
+def _read_xml(archive: ZipFile, path: str) -> ElementTree.Element:
+    try:
+        return ElementTree.fromstring(archive.read(path))
+    except (KeyError, ElementTree.ParseError) as error:
+        raise WorkbookStructureError("工作簿结构错误") from error
+
+
+def _relationship_map(root: ElementTree.Element) -> dict[str, str]:
+    relationships: dict[str, str] = {}
+    for element in root.iter():
+        if _local_name(element.tag) != "Relationship":
+            continue
+        identifier = element.get("Id")
+        target = element.get("Target")
+        if not identifier or not target:
+            raise WorkbookStructureError("工作簿结构错误")
+        relationships[identifier] = target
+    return relationships
+
+
+def _find_carpet_sheet_relationship_id(workbook: ElementTree.Element) -> str:
+    for element in workbook.iter():
+        if _local_name(element.tag) != "sheet" or element.get("name") != "地毯图片":
+            continue
+        relationship_id = element.get(f"{OFFICE_RELATIONSHIP}id")
+        if relationship_id:
+            return relationship_id
+    raise WorkbookStructureError("找不到工作表：地毯图片")
+
+
+def _find_drawing_relationship_id(worksheet: ElementTree.Element) -> str:
+    for element in worksheet.iter():
+        if _local_name(element.tag) == "drawing":
+            relationship_id = element.get(f"{OFFICE_RELATIONSHIP}id")
+            if relationship_id:
+                return relationship_id
+    raise WorkbookStructureError("工作簿结构错误")
+
+
+def _shared_strings(archive: ZipFile, entries: set[str]) -> list[str]:
+    path = "xl/sharedStrings.xml"
+    if path not in entries:
+        return []
+    root = _read_xml(archive, path)
+    return ["".join(element.itertext()) for element in root.iter() if _local_name(element.tag) == "si"]
+
+
+def _product_ids_by_row(worksheet: ElementTree.Element, shared_strings: list[str]) -> dict[int, str]:
+    product_ids: dict[int, str] = {}
+    for cell in worksheet.iter():
+        if _local_name(cell.tag) != "c":
+            continue
+        match = CELL_REFERENCE.match(cell.get("r", ""))
+        if match is None or match.group(1).upper() != "F":
+            continue
+        value = _cell_value(cell, shared_strings)
+        if value:
+            product_ids[int(match.group(2))] = value
+    return product_ids
+
+
+def _cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> str:
+    cell_type = cell.get("t")
+    if cell_type == "inlineStr":
+        inline = _first_descendant(cell, "is")
+        return "".join(inline.itertext()).strip() if inline is not None else ""
+    value = _first_descendant(cell, "v")
+    if value is None or value.text is None:
+        return ""
+    text = value.text.strip()
+    if cell_type != "s":
+        return text
+    try:
+        return shared_strings[int(text)].strip()
+    except (IndexError, ValueError):
+        raise WorkbookStructureError("工作簿结构错误") from None
+
+
+def _image_anchors(drawing: ElementTree.Element) -> Iterator[tuple[int, int, str]]:
+    for anchor in drawing.iter():
+        if _local_name(anchor.tag) != "oneCellAnchor":
+            continue
+        origin = _first_descendant(anchor, "from")
+        blip = _first_descendant(anchor, "blip")
+        if origin is None or blip is None:
+            raise WorkbookStructureError("工作簿结构错误")
+        column = _integer_child(origin, "col")
+        row = _integer_child(origin, "row")
+        embed_id = blip.get(f"{OFFICE_RELATIONSHIP}embed")
+        if embed_id is None:
+            raise WorkbookStructureError("工作簿结构错误")
+        yield row, column, embed_id
+
+
+def _image_column(
+    column: int,
+) -> tuple[Literal["product_main", "buyer_sofa"], Literal["K", "L", "M", "N"]] | None:
+    columns = {
+        10: ("product_main", "K"),
+        11: ("buyer_sofa", "L"),
+        12: ("buyer_sofa", "M"),
+        13: ("buyer_sofa", "N"),
+    }
+    return columns.get(column)
+
+
+def _integer_child(element: ElementTree.Element, name: str) -> int:
+    child = _first_descendant(element, name)
+    if child is None or child.text is None:
+        raise WorkbookStructureError("工作簿结构错误")
+    try:
+        return int(child.text)
+    except ValueError:
+        raise WorkbookStructureError("工作簿结构错误") from None
+
+
+def _resolve_relationship_path(source_path: str, target: str, entries: set[str]) -> str:
+    if target.startswith(("/", "\\")):
+        raise WorkbookStructureError("工作簿结构错误")
+    path = posixpath.normpath(posixpath.join(posixpath.dirname(source_path), target))
+    if path == "." or path.startswith("../") or path not in entries:
+        raise WorkbookStructureError("工作簿结构错误")
+    return path
+
+
+def _rels_path(source_path: str) -> str:
+    path = PurePosixPath(source_path)
+    return str(path.parent / "_rels" / f"{path.name}.rels")
+
+
+def _first_descendant(element: ElementTree.Element, name: str) -> ElementTree.Element | None:
+    return next((item for item in element.iter() if _local_name(item.tag) == name), None)
+
+
+def _local_name(tag: str) -> str:
+    return tag.rsplit("}", maxsplit=1)[-1]
diff --git a/tests/test_tencent_excel.py b/tests/test_tencent_excel.py
new file mode 100644
index 0000000..5db1685
--- /dev/null
+++ b/tests/test_tencent_excel.py
@@ -0,0 +1,142 @@
+"""腾讯文档 XLSX 图片锚点解析的行为测试。"""
+
+from __future__ import annotations
+
+from pathlib import Path
+from zipfile import ZIP_DEFLATED, ZipFile
+
+import pytest
+
+from backend.tencent_excel import WorkbookStructureError, iter_product_images
+
+
+PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
+
+
+def write_tencent_workbook(
+    path: Path,
+    *,
+    sheet_name: str = "地毯图片",
+    product_cell: str = '<c r="F2" t="n"><v>1001</v></c>',
+    include_shared_strings: bool = False,
+) -> None:
+    """写入一个具备腾讯文档常见图片关系结构的最小 XLSX。"""
+    anchors = "".join(
+        f"""
+        <xdr:oneCellAnchor>
+          <xdr:from><xdr:col>{column}</xdr:col><xdr:row>1</xdr:row></xdr:from>
+          <xdr:ext cx="1" cy="1"/><xdr:pic><xdr:blipFill>
+            <a:blip r:embed="rId{index}"/>
+          </xdr:blipFill></xdr:pic>
+        </xdr:oneCellAnchor>
+        """
+        for index, column in enumerate(range(9, 15), start=1)
+    )
+    workbook_xml = f"""
+    <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
+      xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
+      <sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/></sheets>
+    </workbook>
+    """
+    worksheet_xml = f"""
+    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
+      xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
+      <sheetData><row r="2">{product_cell}</row></sheetData>
+      <drawing r:id="rId1"/>
+    </worksheet>
+    """
+    drawing_xml = f"""
+    <xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
+      xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
+      xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
+      {anchors}
+    </xdr:wsDr>
+    """
+    drawing_rels = "".join(
+        f'<Relationship Id="rId{index}" Type="image" Target="../media/image{index}.png"/>'
+        for index in range(1, 7)
+    )
+    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
+        archive.writestr("xl/workbook.xml", workbook_xml)
+        archive.writestr(
+            "xl/_rels/workbook.xml.rels",
+            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
+            '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
+            "</Relationships>",
+        )
+        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml)
+        archive.writestr(
+            "xl/worksheets/_rels/sheet1.xml.rels",
+            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
+            '<Relationship Id="rId1" Type="drawing" Target="../drawings/drawing1.xml"/>'
+            "</Relationships>",
+        )
+        archive.writestr("xl/drawings/drawing1.xml", drawing_xml)
+        archive.writestr(
+            "xl/drawings/_rels/drawing1.xml.rels",
+            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
+            f"{drawing_rels}</Relationships>",
+        )
+        if include_shared_strings:
+            archive.writestr(
+                "xl/sharedStrings.xml",
+                '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
+                "<si><t>SKU-共享</t></si></sst>",
+            )
+        for index in range(1, 7):
+            archive.writestr(f"xl/media/image{index}.png", PNG_SIGNATURE + bytes([index]))
+
+
+def test_iter_product_images_returns_only_k_to_n_with_shared_product_id(tmp_path: Path) -> None:
+    """J/O 图片必须忽略，K-N 四图应绑定 F 列同一商品。"""
+    workbook = tmp_path / "tencent.xlsx"
+    write_tencent_workbook(workbook)
+
+    images = list(iter_product_images(workbook))
+
+    assert [(image.product_id, image.role, image.source_column, image.filename) for image in images] == [
+        ("1001", "product_main", "K", "image2.png"),
+        ("1001", "buyer_sofa", "L", "image3.png"),
+        ("1001", "buyer_sofa", "M", "image4.png"),
+        ("1001", "buyer_sofa", "N", "image5.png"),
+    ]
+    assert all(image.data.startswith(PNG_SIGNATURE) for image in images)
+
+
+@pytest.mark.parametrize(
+    ("product_cell", "include_shared_strings", "expected_product_id"),
+    [
+        ('<c r="F2" t="n"><v>1001</v></c>', False, "1001"),
+        ('<c r="F2" t="s"><v>0</v></c>', True, "SKU-共享"),
+        ('<c r="F2" t="inlineStr"><is><t>SKU-内联</t></is></c>', False, "SKU-内联"),
+    ],
+)
+def test_iter_product_images_reads_supported_product_id_cell_types(
+    tmp_path: Path, product_cell: str, include_shared_strings: bool, expected_product_id: str
+) -> None:
+    """F 列的普通数值、共享字符串和内联字符串都应作为商品 ID。"""
+    workbook = tmp_path / "cell-types.xlsx"
+    write_tencent_workbook(
+        workbook, product_cell=product_cell, include_shared_strings=include_shared_strings
+    )
+
+    images = list(iter_product_images(workbook))
+
+    assert [image.product_id for image in images] == [expected_product_id] * 4
+
+
+def test_iter_product_images_rejects_workbook_without_carpet_sheet(tmp_path: Path) -> None:
+    """目标工作表被改名时必须给出稳定的结构错误。"""
+    workbook = tmp_path / "wrong-sheet.xlsx"
+    write_tencent_workbook(workbook, sheet_name="其他图片")
+
+    with pytest.raises(WorkbookStructureError, match="^找不到工作表：地毯图片$"):
+        list(iter_product_images(workbook))
+
+
+def test_iter_product_images_skips_anchored_row_without_product_id(tmp_path: Path) -> None:
+    """图片所在行缺少 F 列商品 ID 时不产生可导入图片。"""
+    workbook = tmp_path / "missing-product-id.xlsx"
+    write_tencent_workbook(workbook, product_cell="")
+
+    assert list(iter_product_images(workbook)) == []

```
