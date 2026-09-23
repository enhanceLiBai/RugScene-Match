# Re-review package Task 2 round 1

Base: a712dab
Head: 538a3af

## Commits

```
538a3af fix: stream Tencent workbook XML parsing

```

## Stat

```
 backend/tencent_excel.py    | 145 +++++++++++++++++++++++++++++---------------
 tests/test_tencent_excel.py |  26 ++++++++
 2 files changed, 123 insertions(+), 48 deletions(-)

```

## Diff

```diff
diff --git a/backend/tencent_excel.py b/backend/tencent_excel.py
index 359ea00..70657a2 100644
--- a/backend/tencent_excel.py
+++ b/backend/tencent_excel.py
@@ -37,148 +37,197 @@ def iter_product_images(path: Path) -> Iterator[WorkbookImage]:
             yield from _iter_archive_images(archive)
     except WorkbookStructureError:
         raise
     except (BadZipFile, ElementTree.ParseError, KeyError, OSError, ValueError):
         raise WorkbookStructureError("工作簿结构错误") from None


 def _iter_archive_images(archive: ZipFile) -> Iterator[WorkbookImage]:
     entries = set(archive.namelist())
     workbook_path = "xl/workbook.xml"
-    workbook = _read_xml(archive, workbook_path)
-    workbook_relationships = _relationship_map(_read_xml(archive, "xl/_rels/workbook.xml.rels"))
+    workbook_relationships = _relationship_map(archive, "xl/_rels/workbook.xml.rels")

-    sheet_relationship_id = _find_carpet_sheet_relationship_id(workbook)
+    sheet_relationship_id = _find_carpet_sheet_relationship_id(archive, workbook_path)
     worksheet_path = _resolve_relationship_path(workbook_path, workbook_relationships[sheet_relationship_id], entries)
-    worksheet = _read_xml(archive, worksheet_path)
-    product_ids = _product_ids_by_row(worksheet, _shared_strings(archive, entries))
+    raw_product_ids, drawing_relationship_id = _worksheet_details(archive, worksheet_path)
+    product_ids = _resolve_product_ids(archive, entries, raw_product_ids)

-    drawing_relationship_id = _find_drawing_relationship_id(worksheet)
     worksheet_relationships_path = _rels_path(worksheet_path)
-    drawing_relationships = _relationship_map(_read_xml(archive, worksheet_relationships_path))
+    drawing_relationships = _relationship_map(archive, worksheet_relationships_path)
     drawing_path = _resolve_relationship_path(
         worksheet_path, drawing_relationships[drawing_relationship_id], entries
     )
-    drawing = _read_xml(archive, drawing_path)
-    drawing_relationships = _relationship_map(_read_xml(archive, _rels_path(drawing_path)))
+    drawing_relationships = _relationship_map(archive, _rels_path(drawing_path))

-    for row, column, embed_id in _image_anchors(drawing):
+    for row, column, embed_id in _image_anchors(archive, drawing_path):
         column_info = _image_column(column)
         if column_info is None:
             continue
         product_id = product_ids.get(row + 1)
         if not product_id:
             continue
         media_path = _resolve_relationship_path(drawing_path, drawing_relationships[embed_id], entries)
         # 仅在即将产出时读取单张图片，避免解压整个工作簿的媒体文件。
         data = archive.read(media_path)
         role, source_column = column_info
         yield WorkbookImage(
             product_id=product_id,
             role=role,
             source_column=source_column,
             filename=PurePosixPath(media_path).name,
             data=data,
         )


-def _read_xml(archive: ZipFile, path: str) -> ElementTree.Element:
+def _iterparse(archive: ZipFile, path: str) -> Iterator[ElementTree.Element]:
+    """流式读取 XML，并将元素清理时机交给了解父子依赖的调用方。"""
     try:
-        return ElementTree.fromstring(archive.read(path))
+        with archive.open(path) as stream:
+            for _, element in ElementTree.iterparse(stream, events=("end",)):
+                yield element
     except (KeyError, ElementTree.ParseError) as error:
         raise WorkbookStructureError("工作簿结构错误") from error


-def _relationship_map(root: ElementTree.Element) -> dict[str, str]:
+def _relationship_map(archive: ZipFile, path: str) -> dict[str, str]:
     relationships: dict[str, str] = {}
-    for element in root.iter():
+    for element in _iterparse(archive, path):
         if _local_name(element.tag) != "Relationship":
             continue
         identifier = element.get("Id")
         target = element.get("Target")
         if not identifier or not target:
             raise WorkbookStructureError("工作簿结构错误")
         relationships[identifier] = target
+        element.clear()
     return relationships


-def _find_carpet_sheet_relationship_id(workbook: ElementTree.Element) -> str:
-    for element in workbook.iter():
+def _find_carpet_sheet_relationship_id(archive: ZipFile, path: str) -> str:
+    for element in _iterparse(archive, path):
         if _local_name(element.tag) != "sheet" or element.get("name") != "地毯图片":
+            element.clear()
             continue
         relationship_id = element.get(f"{OFFICE_RELATIONSHIP}id")
+        element.clear()
         if relationship_id:
             return relationship_id
     raise WorkbookStructureError("找不到工作表：地毯图片")


-def _find_drawing_relationship_id(worksheet: ElementTree.Element) -> str:
-    for element in worksheet.iter():
-        if _local_name(element.tag) == "drawing":
-            relationship_id = element.get(f"{OFFICE_RELATIONSHIP}id")
-            if relationship_id:
-                return relationship_id
-    raise WorkbookStructureError("工作簿结构错误")
-
-
-def _shared_strings(archive: ZipFile, entries: set[str]) -> list[str]:
+def _shared_strings(archive: ZipFile, entries: set[str], wanted_indexes: set[int]) -> dict[int, str]:
+    """仅读取 F 列实际引用的共享字符串，避免保存完整字符串表。"""
+    if not wanted_indexes:
+        return {}
     path = "xl/sharedStrings.xml"
     if path not in entries:
-        return []
-    root = _read_xml(archive, path)
-    return ["".join(element.itertext()) for element in root.iter() if _local_name(element.tag) == "si"]
-
-
-def _product_ids_by_row(worksheet: ElementTree.Element, shared_strings: list[str]) -> dict[int, str]:
-    product_ids: dict[int, str] = {}
-    for cell in worksheet.iter():
-        if _local_name(cell.tag) != "c":
+        raise WorkbookStructureError("工作簿结构错误")
+    strings: dict[int, str] = {}
+    index = 0
+    for element in _iterparse(archive, path):
+        if _local_name(element.tag) != "si":
+            continue
+        if index in wanted_indexes:
+            strings[index] = "".join(element.itertext()).strip()
+        element.clear()
+        if len(strings) == len(wanted_indexes):
+            return strings
+        index += 1
+    return strings
+
+
+def _worksheet_details(archive: ZipFile, path: str) -> tuple[dict[int, str | int], str]:
+    product_ids: dict[int, str | int] = {}
+    drawing_relationship_id: str | None = None
+    for element in _iterparse(archive, path):
+        name = _local_name(element.tag)
+        if name == "c":
+            _record_product_id(element, product_ids)
+            element.clear()
             continue
-        match = CELL_REFERENCE.match(cell.get("r", ""))
-        if match is None or match.group(1).upper() != "F":
+        if name == "drawing":
+            drawing_relationship_id = element.get(f"{OFFICE_RELATIONSHIP}id")
+            element.clear()
             continue
-        value = _cell_value(cell, shared_strings)
-        if value:
-            product_ids[int(match.group(2))] = value
+        if name == "row":
+            element.clear()
+    if drawing_relationship_id is None:
+        raise WorkbookStructureError("工作簿结构错误")
+    return product_ids, drawing_relationship_id
+
+
+def _record_product_id(
+    cell: ElementTree.Element, product_ids: dict[int, str | int]
+) -> None:
+    match = CELL_REFERENCE.match(cell.get("r", ""))
+    if match is None or match.group(1).upper() != "F":
+        return
+    if cell.get("t") == "s":
+        value = _shared_string_index(cell)
+    else:
+        value = _cell_value(cell)
+    if value is not None and value != "":
+        product_ids[int(match.group(2))] = value
+
+
+def _resolve_product_ids(
+    archive: ZipFile, entries: set[str], raw_product_ids: dict[int, str | int]
+) -> dict[int, str]:
+    shared_indexes = {value for value in raw_product_ids.values() if isinstance(value, int)}
+    shared_strings = _shared_strings(archive, entries, shared_indexes)
+    product_ids: dict[int, str] = {}
+    for row, value in raw_product_ids.items():
+        if isinstance(value, int):
+            try:
+                product_ids[row] = shared_strings[value]
+            except KeyError:
+                raise WorkbookStructureError("工作簿结构错误") from None
+        else:
+            product_ids[row] = value
     return product_ids


-def _cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> str:
+def _cell_value(cell: ElementTree.Element) -> str:
     cell_type = cell.get("t")
     if cell_type == "inlineStr":
         inline = _first_descendant(cell, "is")
         return "".join(inline.itertext()).strip() if inline is not None else ""
     value = _first_descendant(cell, "v")
     if value is None or value.text is None:
         return ""
-    text = value.text.strip()
-    if cell_type != "s":
-        return text
+    return value.text.strip()
+
+
+def _shared_string_index(cell: ElementTree.Element) -> int | None:
+    value = _first_descendant(cell, "v")
+    if value is None or value.text is None:
+        return None
     try:
-        return shared_strings[int(text)].strip()
-    except (IndexError, ValueError):
+        return int(value.text.strip())
+    except ValueError:
         raise WorkbookStructureError("工作簿结构错误") from None


-def _image_anchors(drawing: ElementTree.Element) -> Iterator[tuple[int, int, str]]:
-    for anchor in drawing.iter():
+def _image_anchors(archive: ZipFile, path: str) -> Iterator[tuple[int, int, str]]:
+    for anchor in _iterparse(archive, path):
         if _local_name(anchor.tag) != "oneCellAnchor":
             continue
         origin = _first_descendant(anchor, "from")
         blip = _first_descendant(anchor, "blip")
         if origin is None or blip is None:
             raise WorkbookStructureError("工作簿结构错误")
         column = _integer_child(origin, "col")
         row = _integer_child(origin, "row")
         embed_id = blip.get(f"{OFFICE_RELATIONSHIP}embed")
         if embed_id is None:
             raise WorkbookStructureError("工作簿结构错误")
+        anchor.clear()
         yield row, column, embed_id


 def _image_column(
     column: int,
 ) -> tuple[Literal["product_main", "buyer_sofa"], Literal["K", "L", "M", "N"]] | None:
     columns = {
         10: ("product_main", "K"),
         11: ("buyer_sofa", "L"),
         12: ("buyer_sofa", "M"),
diff --git a/tests/test_tencent_excel.py b/tests/test_tencent_excel.py
index 5db1685..8878fc5 100644
--- a/tests/test_tencent_excel.py
+++ b/tests/test_tencent_excel.py
@@ -118,20 +118,46 @@ def test_iter_product_images_reads_supported_product_id_cell_types(
     workbook = tmp_path / "cell-types.xlsx"
     write_tencent_workbook(
         workbook, product_cell=product_cell, include_shared_strings=include_shared_strings
     )

     images = list(iter_product_images(workbook))

     assert [image.product_id for image in images] == [expected_product_id] * 4


+def test_iter_product_images_streams_worksheet_and_shared_strings_xml(
+    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
+) -> None:
+    """大 worksheet/sharedStrings 解析不能把整个 ZIP 条目交给 archive.read。"""
+    workbook = tmp_path / "streamed-xml.xlsx"
+    write_tencent_workbook(
+        workbook,
+        product_cell='<c r="F2" t="s"><v>0</v></c>',
+        include_shared_strings=True,
+    )
+    read_paths: list[str] = []
+    original_read = ZipFile.read
+
+    def record_read(archive: ZipFile, name: str, *args: object, **kwargs: object) -> bytes:
+        read_paths.append(name)
+        return original_read(archive, name, *args, **kwargs)
+
+    monkeypatch.setattr(ZipFile, "read", record_read)
+
+    images = list(iter_product_images(workbook))
+
+    assert [image.product_id for image in images] == ["SKU-共享"] * 4
+    assert "xl/worksheets/sheet1.xml" not in read_paths
+    assert "xl/sharedStrings.xml" not in read_paths
+
+
 def test_iter_product_images_rejects_workbook_without_carpet_sheet(tmp_path: Path) -> None:
     """目标工作表被改名时必须给出稳定的结构错误。"""
     workbook = tmp_path / "wrong-sheet.xlsx"
     write_tencent_workbook(workbook, sheet_name="其他图片")

     with pytest.raises(WorkbookStructureError, match="^找不到工作表：地毯图片$"):
         list(iter_product_images(workbook))


 def test_iter_product_images_skips_anchored_row_without_product_id(tmp_path: Path) -> None:

```
